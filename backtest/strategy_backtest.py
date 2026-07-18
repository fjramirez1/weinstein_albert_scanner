"""
Backtest de la estrategia Weinstein-Albert completa (entrada + salida).

Objetivo
--------
`backtest_lookback.py` mide el filtro de mercado F5 en aislamiento (qué
retorno tiene el S&P 500 tras cada señal alcista del Coppock), pero no
dice nada sobre la rentabilidad real de la estrategia: eso depende
también de F1-F4 (selección de ticker) y de S1-S2 (cuándo se sale).

Este módulo simula, ticker a ticker, semana a semana, el ciclo completo:

  1. Si NO hay posición abierta en el ticker: evaluar F1-F5. Si se
     cumplen todos, abrir posición esa semana (precio de cierre).
  2. Si SÍ hay posición abierta: evaluar S1-S2. Si cualquiera se
     cumple, cerrar posición esa semana (precio de cierre) y registrar
     la operación.

Es un backtest **por ticker**, no de cartera: no modela nº máximo de
posiciones simultáneas, tamaño de posición, ni solapamiento entre
tickers. Sirve para medir la calidad de las condiciones F1-F5/S1-S2 en
sí mismas (¿producen operaciones rentables cuando se cumplen?), que es
el requisito previo para después ajustar umbrales (SECTOR_RSC_MIN,
RSC_EXIT_THRESHOLD, MAX_DISTANCIA_WMA30, etc.) con evidencia real.

Sin look-ahead
--------------
Todos los indicadores (RSC, VPM5, WMA30, Coppock) se calculan **una
única vez por serie completa**, usando funciones vectorizadas basadas en
``rolling()`` (ver `weinstein/indicators.py`). Por construcción, el valor
de un indicador en la posición `i` de una serie con `rolling()` depende
únicamente de `serie.iloc[:i+1]` — nunca de datos futuros. Esto es
matemáticamente equivalente a truncar la serie en `i` y recalcular desde
cero en cada paso (como hacía la versión anterior de este módulo), pero
sin repetir el trabajo: se sustituye un recálculo O(n) en cada una de
las n semanas (O(n²) total por ticker) por un único cálculo O(n) por
serie. Ver `tests/test_strategy_backtest.py::TestEntrySignalSinLookAhead`
y `TestExitSignalSinLookAhead`, que verifican explícitamente que evaluar
sobre la serie completa u sobre la serie truncada en `i` da el mismo
resultado.

Por qué salía el aviso de "desalineación de fechas" en bucle
---------------------------------------------------------------
La versión anterior truncaba el S&P 500 (`sp500_close.loc[... <= fecha_i]`)
pero SIN recortar por la izquierda: la serie resultante siempre arrancaba
en el inicio del periodo descargado (p.ej. hace 10 años), mientras que el
activo (o su ETF sectorial) podía tener bastante menos histórico real
(salida a bolsa reciente, límites de disponibilidad en yfinance, etc.).
El `inner join` de `rsc_mansfield()` descartaba entonces, de forma
sistemática y en CADA semana evaluada, la diferencia estructural de
cientos de filas entre ambas series — no una desalineación puntual de
festivos (1-2 filas), que es lo que ese aviso pretende detectar. Con
~500 tickers x cientos de semanas x varias llamadas a `rsc_mansfield`
por semana, el aviso se imprimía miles de veces.

La corrección aquí es alinear cada serie de activo/ETF con el S&P 500
**una sola vez**, al principio (`Series.align(..., join="inner")`), antes
de calcular ningún indicador. A partir de ahí todas las series comparten
exactamente el mismo índice de fechas, así que `rsc_mansfield()` ya no
tiene nada que descartar en el inner join interno y el aviso desaparece
(sigue disponible para detectar desalineaciones REALES, si las hubiera,
porque el guard `> 2` filas se mantiene intacto en `indicators.py`).

Reutilización de lógica real
-----------------------------
Todas las fórmulas (`wma`, `rsc_mansfield`, `vpm5`, `coppock_curve`,
`sp500_alcista`, `sp500_bajista`, `momentum_vs_wma`, `distancia_wma_pct`)
se importan directamente de `weinstein.indicators`, igual que hace
`backtest_lookback.py` con `wma`/`coppock_curve`. Los umbrales (F1-F5,
S1-S2) se importan de `weinstein.config`. Así el backtest mide siempre
la MISMA lógica que corre en producción (`scanner_entry.py` /
`scanner_exit.py`), y si esa lógica cambia, el backtest queda
sincronizado automáticamente.

Uso como script
----------------
    python backtest/strategy_backtest.py
    python backtest/strategy_backtest.py --period 8y --tickers AAPL,MSFT
    python backtest/strategy_backtest.py --max-tickers 50

Uso como CLI del paquete
--------------------------
    python -m weinstein backtest
    python -m weinstein backtest --period 8y --max-tickers 50
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Permite ejecutar el script tanto desde backtest/ como desde la raíz,
# igual que hace backtest_lookback.py.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from weinstein.config import (  # noqa: E402
    BACKTEST_MAX_WORKERS,
    BACKTEST_MIN_BARS,
    BACKTEST_PERIOD_DEFAULT,
    MAX_DISTANCIA_WMA30,
    RSC_EXIT_THRESHOLD,
    RSC_SMA_PERIOD,
    SECTOR_RSC_MIN,
    SECTOR_TO_ETF,
    SP500_INDEX,
    VPM_BASE_PERIOD,
    VPM_SMOOTHING,
    WMA30_PERIOD,
    resolve_sector_etf,
)
from weinstein.data import download_weekly, load_sp500_tickers  # noqa: E402
from weinstein.indicators import (  # noqa: E402
    coppock_curve,
    distancia_wma_pct,
    momentum_vs_wma,
    rsc_mansfield,
    sp500_alcista,
    sp500_bajista,
    vpm5,
    wma,
)


# ── Estructuras de resultado ────────────────────────────────────────────

@dataclass
class Trade:
    """Una operación completa (entrada + salida) de un ticker."""
    ticker:          str
    sector:          str
    fecha_entrada:   pd.Timestamp
    precio_entrada:  float
    fecha_salida:    pd.Timestamp | None
    precio_salida:   float | None
    motivo_salida:   str
    semanas_en_pos:  int
    retorno_pct:     float | None


@dataclass
class BacktestResult:
    """Resultado agregado del backtest sobre un universo de tickers."""
    trades: list[Trade] = field(default_factory=list)
    tickers_procesados: int = 0
    tickers_sin_datos: int = 0
    tickers_error: int = 0

    def to_dataframe(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame()
        rows = [
            {
                "Ticker":          t.ticker,
                "Sector":          t.sector,
                "Fecha Entrada":   t.fecha_entrada,
                "Precio Entrada":  t.precio_entrada,
                "Fecha Salida":    t.fecha_salida,
                "Precio Salida":   t.precio_salida,
                "Motivo Salida":   t.motivo_salida,
                "Semanas en Pos.": t.semanas_en_pos,
                "Retorno %":       t.retorno_pct,
            }
            for t in self.trades
        ]
        return pd.DataFrame(rows)

    def metrics(self) -> dict:
        """Métricas agregadas sobre las operaciones CERRADAS (con retorno conocido)."""
        cerradas = [t for t in self.trades if t.retorno_pct is not None]
        n = len(cerradas)
        abiertas = len(self.trades) - n

        if n == 0:
            return {
                "n_operaciones_cerradas": 0,
                "n_operaciones_abiertas":  abiertas,
                "retorno_medio_pct":      None,
                "retorno_mediana_pct":    None,
                "win_rate_pct":           None,
                "profit_factor":          None,
                "max_drawdown_pct":       None,
                "semanas_medias_en_pos":  None,
            }

        retornos = np.array([t.retorno_pct for t in cerradas], dtype=float)
        ganadoras = retornos[retornos > 0]
        perdedoras = retornos[retornos <= 0]

        suma_ganancias = float(ganadoras.sum()) if len(ganadoras) else 0.0
        suma_perdidas = float(-perdedoras.sum()) if len(perdedoras) else 0.0
        profit_factor = (suma_ganancias / suma_perdidas) if suma_perdidas > 0 else None

        equity_curve = np.cumprod(1 + retornos / 100.0)
        running_max = np.maximum.accumulate(equity_curve)
        drawdowns = (equity_curve - running_max) / running_max * 100.0
        max_dd = float(drawdowns.min()) if len(drawdowns) else None

        return {
            "n_operaciones_cerradas": n,
            "n_operaciones_abiertas":  abiertas,
            "retorno_medio_pct":      round(float(retornos.mean()), 2),
            "retorno_mediana_pct":    round(float(np.median(retornos)), 2),
            "win_rate_pct":           round(100.0 * len(ganadoras) / n, 1),
            "profit_factor":          round(profit_factor, 2) if profit_factor is not None else None,
            "max_drawdown_pct":       round(max_dd, 2) if max_dd is not None else None,
            "semanas_medias_en_pos":  round(float(np.mean([t.semanas_en_pos for t in cerradas])), 1),
        }


# ── Precálculo vectorizado de series de señal (una vez por ticker) ─────

@dataclass
class _TickerSignals:
    """
    Series de señal ya calculadas sobre el histórico COMPLETO de un
    ticker, alineado con el S&P 500 (y opcionalmente con su ETF
    sectorial). Cada serie está indexada por fecha; el valor en la
    posición `i` depende solo de datos hasta `i` (propiedad de
    `rolling()`), así que se puede iterar sin volver a calcular nada.

    `valid_from` es la primera posición con histórico suficiente
    (`BACKTEST_MIN_BARS`) para evaluar F1-F5/S1-S2; antes de esa
    posición ninguna señal se considera válida (igual que la versión
    anterior devolvía False si `i < BACKTEST_MIN_BARS`).
    """
    close:               pd.Series
    entry_ok:            pd.Series   # bool: F1 AND F2 AND F3 AND F4 AND F5
    exit_ok:              pd.Series  # bool: S1 OR S2
    exit_motivo:          pd.Series  # str:  "S1", "S2", "S1+S2" o "—"
    valid_from:            int


def _compute_ticker_signals(
    close_asset:      pd.Series,
    volume_asset:     pd.Series,
    sp500_close:      pd.Series,
    sector_etf_close: pd.Series | None,
) -> _TickerSignals | None:
    """
    Calcula, de una sola vez y para toda la serie, las señales de
    entrada (F1-F5) y salida (S1-S2) de un ticker.

    Alineación (clave para evitar tanto el recálculo O(n^2) como el
    aviso de desalineación en bucle): el activo, el S&P 500 y el ETF
    sectorial se alinean por fecha UNA SOLA VEZ al principio con
    `Series.align(..., join="inner")`. A partir de ahí todos los
    indicadores se calculan sobre series que ya comparten índice, así
    que `rsc_mansfield()` no tiene nada que descartar internamente.

    Devuelve ``None`` si, tras alinear, no queda histórico suficiente
    para evaluar nada (ni F1-F5 ni S1-S2 podrían activarse jamás).
    """
    close_a, sp500_a = close_asset.align(sp500_close, join="inner")
    if len(close_a) < BACKTEST_MIN_BARS:
        return None

    volume_a = volume_asset.reindex(close_a.index)

    # RSC del activo frente al S&P 500 (usado en F3 y en S1).
    rsc_activo = rsc_mansfield(close_a, sp500_a, sma_period=RSC_SMA_PERIOD)

    # RSC del sector (ETF) frente al S&P 500 (usado en F1). Se alinea
    # también una única vez, sobre el índice ya común de close_a/sp500_a.
    if sector_etf_close is not None:
        sector_a = sector_etf_close.reindex(sp500_a.index)
        rsc_sector = rsc_mansfield(sector_a, sp500_a, sma_period=RSC_SMA_PERIOD)
    else:
        rsc_sector = pd.Series(np.nan, index=close_a.index)

    # F2: VPM5 del volumen del activo.
    vpm5_series = vpm5(
        pd.DataFrame({"Volume": volume_a}), VPM_BASE_PERIOD, VPM_SMOOTHING
    )

    # F4 / MOM: WMA30 calculada una única vez y reutilizada.
    wma30_series = wma(close_a, WMA30_PERIOD)
    dist_wma30 = ((close_a - wma30_series) / wma30_series) * 100.0

    # F5: Coppock del S&P 500 (idéntico para todos los tickers, pero se
    # recalcula aquí porque el índice ya está alineado con este activo
    # en concreto; el coste es marginal frente al resto de la serie).
    copk = coppock_curve(sp500_a)
    entry_bullish = _sp500_alcista_series(copk)

    # S2: Coppock bajista del S&P 500.
    exit_bearish = _sp500_bajista_series(copk)

    # ── F1-F5 combinadas (AND) ──────────────────────────────────────
    f1 = rsc_sector >= SECTOR_RSC_MIN
    f2 = vpm5_series > 0.0
    f3 = rsc_activo > 0.0
    f4 = dist_wma30 < MAX_DISTANCIA_WMA30
    entry_ok = f1 & f2 & f3 & f4 & entry_bullish
    entry_ok = entry_ok.fillna(False)

    # ── S1-S2 combinadas (OR) ───────────────────────────────────────
    s1 = rsc_activo < RSC_EXIT_THRESHOLD
    s1 = s1.fillna(False)
    s2 = exit_bearish.fillna(False)
    exit_ok = s1 | s2

    motivo = pd.Series("—", index=close_a.index, dtype=object)
    motivo[s1 & ~s2] = "S1"
    motivo[s2 & ~s1] = "S2"
    motivo[s1 & s2] = "S1+S2"

    # Posiciones con histórico insuficiente (< BACKTEST_MIN_BARS desde
    # el inicio de la serie ya alineada) no pueden generar señal, igual
    # que la versión anterior con `if i < BACKTEST_MIN_BARS: return False`.
    valid_from = BACKTEST_MIN_BARS

    return _TickerSignals(
        close=close_a,
        entry_ok=entry_ok,
        exit_ok=exit_ok,
        exit_motivo=motivo,
        valid_from=valid_from,
    )


def _sp500_alcista_series(coppock: pd.Series) -> pd.Series:
    """
    Versión vectorizada de `sp500_alcista()` (ver weinstein/indicators.py),
    evaluada en cada posición de la serie en vez de solo en la última.
    Replica exactamente la misma condición, fila a fila, usando solo
    `rolling()` (por tanto sin look-ahead: el valor en `i` depende
    únicamente de `coppock.iloc[:i+1]`).
    """
    from weinstein.config import COPPOCK_RECENT_LOOKBACK

    current = coppock
    previous = coppock.shift(1)

    # "previous es el mínimo de la ventana de N valores anteriores a él"
    # equivalente a min(coppock[i-lookback : i]) === min de
    # coppock.shift(1) sobre una ventana rolling que TERMINA en previous.
    recent_min = previous.rolling(window=COPPOCK_RECENT_LOOKBACK, min_periods=1).min()
    prev_is_min = (previous - recent_min).abs() < 1e-9

    start_bullish = (current < 0.0) & (previous < 0.0) & prev_is_min & (current > previous)
    continuation_bullish = (current > 0.0) & (current > previous)

    bullish = start_bullish | continuation_bullish
    return bullish.fillna(False)


def _sp500_bajista_series(coppock: pd.Series) -> pd.Series:
    """
    Versión vectorizada de `sp500_bajista()`, fila a fila, sin
    look-ahead (solo usa el valor actual y el inmediatamente anterior).
    """
    current = coppock
    previous = coppock.shift(1)

    cruce_a_negativo = (previous >= 0.0) & (current < 0.0)
    confirmacion_bajista = (current < 0.0) & (current < previous)

    bajista = cruce_a_negativo | confirmacion_bajista
    return bajista.fillna(False)


# ── Simulación de un ticker completo (vectorizada) ──────────────────────

def simulate_ticker(
    ticker:      str,
    sector:      str,
    close:       pd.Series,
    volume:      pd.Series,
    sp500_close: pd.Series,
    sector_etf_close: pd.Series | None,
) -> list[Trade]:
    """
    Recorre el histórico semanal de un ticker y simula el ciclo
    entrada/salida completo. Puede generar varias operaciones si el
    ticker entra y sale más de una vez dentro del periodo.

    A diferencia de la versión anterior, las señales de entrada/salida
    ya vienen precalculadas para TODA la serie (`_compute_ticker_signals`,
    O(n) vectorizado) y aquí solo se recorre una vez la máquina de
    estados (abierto/cerrado) sobre esas señales — el propio recorrido
    secuencial (abrir/cerrar posición) sí necesita ser un bucle porque
    depende del estado acumulado, pero ya no recalcula ningún indicador
    en cada paso.
    """
    signals = _compute_ticker_signals(close, volume, sp500_close, sector_etf_close)
    if signals is None:
        return []

    close_a = signals.close
    entry_ok = signals.entry_ok.to_numpy()
    exit_ok = signals.exit_ok.to_numpy()
    exit_motivo = signals.exit_motivo.to_numpy()
    close_vals = close_a.to_numpy()
    dates = close_a.index

    trades: list[Trade] = []
    en_posicion = False
    fecha_entrada = None
    precio_entrada = None
    idx_entrada = None

    n = len(close_a)
    start = signals.valid_from
    for i in range(start, n):
        if not en_posicion:
            if entry_ok[i]:
                en_posicion = True
                fecha_entrada = dates[i]
                precio_entrada = float(close_vals[i])
                idx_entrada = i
        else:
            if exit_ok[i]:
                precio_salida = float(close_vals[i])
                retorno = (
                    round(((precio_salida / precio_entrada) - 1) * 100, 2)
                    if precio_entrada else None
                )
                trades.append(Trade(
                    ticker=ticker,
                    sector=sector,
                    fecha_entrada=fecha_entrada,
                    precio_entrada=precio_entrada,
                    fecha_salida=dates[i],
                    precio_salida=precio_salida,
                    motivo_salida=str(exit_motivo[i]),
                    semanas_en_pos=i - idx_entrada,
                    retorno_pct=retorno,
                ))
                en_posicion = False
                fecha_entrada = None
                precio_entrada = None
                idx_entrada = None

    # Posición abierta al final del histórico: se registra sin cerrar
    # (retorno_pct=None) para no perder la operación ni inventar un
    # precio de salida que no ha ocurrido.
    if en_posicion:
        trades.append(Trade(
            ticker=ticker,
            sector=sector,
            fecha_entrada=fecha_entrada,
            precio_entrada=precio_entrada,
            fecha_salida=None,
            precio_salida=None,
            motivo_salida="(posición abierta al final del backtest)",
            semanas_en_pos=n - 1 - idx_entrada,
            retorno_pct=None,
        ))

    return trades


# ── Funciones de señal puntual (mantenidas por compatibilidad/tests) ───
#
# `_entry_signal_at` y `_exit_signal_at` se mantienen con la misma firma
# y semántica que antes (evalúan en un índice posicional `i` de
# `close_asset`, usando solo datos hasta `i`), para no romper los tests
# existentes en `tests/test_strategy_backtest.py` que las llaman
# directamente y verifican la propiedad de "no look-ahead" comparando
# contra la serie truncada. Internamente ya no repiten el cálculo desde
# cero salvo por el propio truncado que exige la firma de la función.

def _entry_signal_at(
    close_asset:     pd.Series,
    volume_asset:    pd.Series,
    sp500_close:     pd.Series,
    sector_etf_close: pd.Series | None,
    i:               int,
) -> bool:
    """
    Evalúa F1-F5 en el índice posicional `i` de `close_asset`, usando
    solo datos hasta `i` (inclusive) de todas las series.
    """
    if i < BACKTEST_MIN_BARS:
        return False

    close_hist = close_asset.iloc[: i + 1]
    sp500_hist = sp500_close.loc[sp500_close.index <= close_asset.index[i]]
    sector_hist = (
        sector_etf_close.loc[sector_etf_close.index <= close_asset.index[i]]
        if sector_etf_close is not None else None
    )
    vol_hist = volume_asset.iloc[: i + 1]

    signals = _compute_ticker_signals(close_hist, vol_hist, sp500_hist, sector_hist)
    if signals is None or len(signals.close) == 0:
        return False
    if len(signals.close) <= signals.valid_from and (len(signals.close) - 1) < signals.valid_from:
        return False
    return bool(signals.entry_ok.iloc[-1])


def _exit_signal_at(
    close_asset:  pd.Series,
    sp500_close:  pd.Series,
    i:            int,
) -> tuple[bool, str]:
    """
    Evalúa S1-S2 (OR) en el índice posicional `i`. Devuelve (salida, motivo).
    """
    close_hist = close_asset.iloc[: i + 1]
    sp500_hist = sp500_close.loc[sp500_close.index <= close_asset.index[i]]

    close_a, sp500_a = close_hist.align(sp500_hist, join="inner")

    motivos: list[str] = []
    if len(close_a) >= RSC_SMA_PERIOD + 5:
        rsc_series = rsc_mansfield(close_a, sp500_a)
        rsc_val = float(rsc_series.iloc[-1]) if len(rsc_series) else float("nan")
        if not pd.isna(rsc_val) and rsc_val < RSC_EXIT_THRESHOLD:
            motivos.append("S1")

    copk = coppock_curve(sp500_a if len(sp500_a) else sp500_hist)
    bearish, _ = sp500_bajista(copk)
    if bearish:
        motivos.append("S2")

    return bool(motivos), "+".join(motivos) if motivos else "—"


# ── Orquestación sobre el universo ──────────────────────────────────────

def _download_sector_etfs(sp500_close: pd.Series, period: str) -> dict[str, pd.Series]:
    """Descarga una vez cada ETF sectorial único y devuelve {etf: close}."""
    unique_etfs = sorted(set(SECTOR_TO_ETF.values()))
    result: dict[str, pd.Series] = {}
    print(f"  → Descargando {len(unique_etfs)} ETFs sectoriales...")
    with ThreadPoolExecutor(max_workers=BACKTEST_MAX_WORKERS) as pool:
        futures = {pool.submit(download_weekly, etf, period): etf for etf in unique_etfs}
        for fut in as_completed(futures):
            etf = futures[fut]
            data = fut.result()
            if data is not None:
                result[etf] = data["Close"].squeeze()
                print(f"    ✓ {etf}")
            else:
                print(f"    ✗ {etf}: sin datos")
    return result


def _worker_backtest_ticker(
    row:              pd.Series,
    sp500_close:      pd.Series,
    sector_etf_map:   dict[str, pd.Series],
    period:           str,
) -> tuple[list[Trade], str]:
    """Descarga y simula un único ticker. Devuelve (trades, estado)."""
    ticker = row["Symbol"]
    sector = row.get("Sector", "Unknown")
    try:
        data = download_weekly(ticker, period=period)
        if data is None or len(data) < BACKTEST_MIN_BARS:
            return [], "sin_datos"

        close = data["Close"].squeeze()
        volume = data["Volume"].squeeze()
        etf_ticker = resolve_sector_etf(sector)
        sector_etf_close = sector_etf_map.get(etf_ticker) if etf_ticker else None

        trades = simulate_ticker(ticker, sector, close, volume, sp500_close, sector_etf_close)
        return trades, "ok"
    except Exception as exc:
        print(f"  ⚠ [{ticker}] error durante la simulación: {exc}", file=sys.stderr)
        return [], "error"


def run_strategy_backtest(
    period:      str = BACKTEST_PERIOD_DEFAULT,
    tickers:     list[str] | None = None,
    max_tickers: int | None = None,
) -> BacktestResult:
    """
    Ejecuta el backtest de la estrategia completa sobre el universo
    indicado (por defecto, todo el S&P 500).

    Rendimiento
    -----------
    - Cada ticker se simula con indicadores VECTORIZADOS: cada serie
      (RSC, VPM5, WMA30, Coppock) se calcula una única vez con
      `rolling()` sobre todo el histórico, en vez de recalcularse en
      cada una de las ~n semanas evaluadas (antes O(n^2) por ticker,
      ahora O(n)).
    - Los tickers se procesan en paralelo con `ThreadPoolExecutor`
      (I/O-bound: la descarga con yfinance libera el GIL), igual que
      hacían ya `scanner_entry.py`/`scanner_exit.py`.

    Parameters
    ----------
    period      : periodo de histórico a descargar por ticker (ej. "10y").
    tickers     : lista explícita de tickers; si es None, se usa el S&P 500 completo.
    max_tickers : límite opcional de tickers a procesar (útil para pruebas rápidas).
    """
    print("\n" + "═" * 72)
    print("  WEINSTEIN VERSION ALBERT — BACKTEST DE ESTRATEGIA COMPLETA")
    print(f"  Periodo   : {period}")
    print("═" * 72)

    print("\n[1/4] Descargando S&P 500 (benchmark)...")
    sp500_data = download_weekly(SP500_INDEX, period=period)
    if sp500_data is None:
        print("  ✗ ERROR CRÍTICO: no se pudo descargar el S&P 500. Abortando.")
        sys.exit(1)
    sp500_close = sp500_data["Close"].squeeze()

    print("\n[2/4] Cargando universo de tickers...")
    if tickers:
        sp500_df = pd.DataFrame({"Symbol": tickers, "Name": tickers, "Sector": "Unknown"})
    else:
        sp500_df = load_sp500_tickers()
    if max_tickers:
        sp500_df = sp500_df.head(max_tickers)
    print(f"  ✓ {len(sp500_df)} tickers a procesar")

    print("\n[3/4] Descargando ETFs sectoriales...")
    sector_etf_map = _download_sector_etfs(sp500_close, period)

    print(f"\n[4/4] Simulando {len(sp500_df)} tickers (paralelo, {BACKTEST_MAX_WORKERS} hilos)...")
    print("─" * 72)

    result = BacktestResult()
    rows = [row for _, row in sp500_df.iterrows()]

    with ThreadPoolExecutor(max_workers=BACKTEST_MAX_WORKERS) as pool:
        futures = {
            pool.submit(_worker_backtest_ticker, row, sp500_close, sector_etf_map, period): row["Symbol"]
            for row in rows
        }
        done = 0
        for fut in as_completed(futures):
            ticker = futures[fut]
            trades, estado = fut.result()
            done += 1
            result.tickers_procesados += 1

            if estado == "sin_datos":
                result.tickers_sin_datos += 1
            elif estado == "error":
                result.tickers_error += 1
            elif trades:
                result.trades.extend(trades)
                cerradas = [t for t in trades if t.retorno_pct is not None]
                if cerradas:
                    ret_medio = np.mean([t.retorno_pct for t in cerradas])
                    print(f"  ★ {ticker:<6} | {len(cerradas)} operación(es) cerrada(s) | ret. medio {ret_medio:+.2f}%")

            if done % 50 == 0:
                print(f"  … {done}/{len(rows)} tickers procesados | operaciones acumuladas: {len(result.trades)}")

    print("\n" + "═" * 72)
    print("  RESUMEN DEL BACKTEST")
    print("─" * 72)
    print(f"  Tickers procesados     : {result.tickers_procesados}")
    print(f"  Tickers sin datos      : {result.tickers_sin_datos}")
    print(f"  Tickers con error      : {result.tickers_error}")
    print(f"  Operaciones totales    : {len(result.trades)}")

    metrics = result.metrics()
    print("─" * 72)
    print(f"  Operaciones cerradas         : {metrics['n_operaciones_cerradas']}")
    print(f"  Operaciones aún abiertas     : {metrics['n_operaciones_abiertas']}")
    print(f"  Retorno medio (%)            : {metrics['retorno_medio_pct']}")
    print(f"  Retorno mediana (%)          : {metrics['retorno_mediana_pct']}")
    print(f"  Win rate (%)                 : {metrics['win_rate_pct']}")
    print(f"  Profit factor                : {metrics['profit_factor']}")
    print(f"  Máx. drawdown (equity, %)    : {metrics['max_drawdown_pct']}")
    print(f"  Semanas medias en posición   : {metrics['semanas_medias_en_pos']}")
    print("═" * 72)

    return result


# ── CLI de script independiente ─────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest de la estrategia Weinstein-Albert completa (entrada F1-F5 + salida S1-S2)"
    )
    parser.add_argument("--period", default=BACKTEST_PERIOD_DEFAULT, help=f"Periodo de histórico (default: {BACKTEST_PERIOD_DEFAULT})")
    parser.add_argument("--tickers", default=None, help="Lista de tickers separados por coma (default: S&P 500 completo)")
    parser.add_argument("--max-tickers", type=int, default=None, help="Límite de tickers a procesar (pruebas rápidas)")
    parser.add_argument("--export", default=None, metavar="CSV", help="Ruta donde exportar el detalle de operaciones a CSV")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None

    result = run_strategy_backtest(period=args.period, tickers=tickers, max_tickers=args.max_tickers)

    df = result.to_dataframe()
    if args.export and not df.empty:
        df.to_csv(args.export, index=False, encoding="utf-8-sig")
        print(f"\n  ✅ Detalle de operaciones exportado → {args.export}")
    elif args.export:
        print("\n  ⚠ No hay operaciones que exportar.")


if __name__ == "__main__":
    main()