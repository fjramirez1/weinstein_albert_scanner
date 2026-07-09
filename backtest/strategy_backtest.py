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
En cada semana `t` evaluada, todos los cálculos (RSC, VPM5, WMA30,
Coppock) se hacen únicamente con datos `close.iloc[:t+1]` — el punto de
evaluación y todo lo anterior, nunca datos futuros. El Coppock y el RSC
de sector se recalculan sobre la serie del S&P 500 / ETF truncada de la
misma forma, así que la señal de mercado en la semana `t` es exactamente
la que se habría visto en tiempo real esa semana.

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


# ── Evaluación de condiciones en un punto temporal (sin look-ahead) ────

def _entry_signal_at(
    close_asset:     pd.Series,
    volume_asset:    pd.Series,
    sp500_close:     pd.Series,
    sector_etf_close: pd.Series | None,
    i:               int,
) -> bool:
    """
    Evalúa F1-F5 en el índice posicional `i` de `close_asset`, usando
    solo datos hasta `i` (inclusive) de todas las series. Replica
    fielmente scanner_entry.py::_evaluate_ticker, filtro por filtro.
    """
    if i < BACKTEST_MIN_BARS:
        return False

    close_hist = close_asset.iloc[: i + 1]
    sp500_hist = sp500_close.loc[sp500_close.index <= close_asset.index[i]]

    # F5: Coppock SP500 alcista
    copk = coppock_curve(sp500_hist)
    bullish, _ = sp500_alcista(copk)
    if not bullish:
        return False

    # F1: RSC sector >= umbral
    if sector_etf_close is None:
        return False
    sector_hist = sector_etf_close.loc[sector_etf_close.index <= close_asset.index[i]]
    if len(sector_hist) < RSC_SMA_PERIOD + 5:
        return False
    rsc_sector_series = rsc_mansfield(sector_hist, sp500_hist)
    rsc_sector_val = float(rsc_sector_series.iloc[-1]) if len(rsc_sector_series) else float("nan")
    if pd.isna(rsc_sector_val) or rsc_sector_val < SECTOR_RSC_MIN:
        return False

    if len(close_hist) < RSC_SMA_PERIOD + 5:
        return False

    # F3: RSC activo > 0
    close_a, sp500_a = close_hist.align(sp500_hist, join="inner")
    rsc_activo_series = rsc_mansfield(close_a, sp500_a)
    rsc_activo_val = float(rsc_activo_series.iloc[-1]) if len(rsc_activo_series) else float("nan")
    if pd.isna(rsc_activo_val) or rsc_activo_val <= 0.0:
        return False

    # F2: VPM5 > 0
    vol_hist = volume_asset.iloc[: i + 1]
    vpm5_series = vpm5(
        pd.DataFrame({"Volume": vol_hist}), VPM_BASE_PERIOD, VPM_SMOOTHING
    )
    vpm5_val = float(vpm5_series.iloc[-1]) if len(vpm5_series) else float("nan")
    if pd.isna(vpm5_val) or vpm5_val <= 0.0:
        return False

    # F4: distancia WMA30 < umbral
    wma30_series = wma(close_hist, WMA30_PERIOD)
    dist = distancia_wma_pct(close_hist, WMA30_PERIOD, wma_series=wma30_series)
    if dist is None or dist >= MAX_DISTANCIA_WMA30:
        return False

    return True


def _exit_signal_at(
    close_asset:  pd.Series,
    sp500_close:  pd.Series,
    i:            int,
) -> tuple[bool, str]:
    """
    Evalúa S1-S2 (OR) en el índice posicional `i`. Replica
    scanner_exit.py::_evaluate_exit. Devuelve (salida, motivo).
    """
    close_hist = close_asset.iloc[: i + 1]
    sp500_hist = sp500_close.loc[sp500_close.index <= close_asset.index[i]]

    motivos: list[str] = []

    # S1: RSC activo < umbral de salida
    close_a, sp500_a = close_hist.align(sp500_hist, join="inner")
    if len(close_a) >= RSC_SMA_PERIOD + 5:
        rsc_series = rsc_mansfield(close_a, sp500_a)
        rsc_val = float(rsc_series.iloc[-1]) if len(rsc_series) else float("nan")
        if not pd.isna(rsc_val) and rsc_val < RSC_EXIT_THRESHOLD:
            motivos.append("S1")

    # S2: Coppock SP500 bajista
    copk = coppock_curve(sp500_hist)
    bearish, _ = sp500_bajista(copk)
    if bearish:
        motivos.append("S2")

    return bool(motivos), "+".join(motivos) if motivos else "—"


# ── Simulación de un ticker completo ────────────────────────────────────

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
    """
    trades: list[Trade] = []
    en_posicion = False
    fecha_entrada = None
    precio_entrada = None
    idx_entrada = None

    n = len(close)
    for i in range(n):
        if not en_posicion:
            if _entry_signal_at(close, volume, sp500_close, sector_etf_close, i):
                en_posicion = True
                fecha_entrada = close.index[i]
                precio_entrada = float(close.iloc[i])
                idx_entrada = i
        else:
            salida, motivo = _exit_signal_at(close, sp500_close, i)
            if salida:
                precio_salida = float(close.iloc[i])
                retorno = (
                    round(((precio_salida / precio_entrada) - 1) * 100, 2)
                    if precio_entrada else None
                )
                trades.append(Trade(
                    ticker=ticker,
                    sector=sector,
                    fecha_entrada=fecha_entrada,
                    precio_entrada=precio_entrada,
                    fecha_salida=close.index[i],
                    precio_salida=precio_salida,
                    motivo_salida=motivo,
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
        etf_ticker = SECTOR_TO_ETF.get(sector)
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
