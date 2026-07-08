"""
Backtest de sensibilidad de COPPOCK_RECENT_LOOKBACK en sp500_alcista().

Objetivo
--------
`sp500_alcista()` usa una ventana de N semanas para decidir si el valor
Coppock de la semana anterior es el "mínimo reciente" que define el
inicio de una tendencia alcista (ver weinstein/indicators.py). Ese N
(`COPPOCK_RECENT_LOOKBACK`, por defecto 4) es una elección de diseño sin
justificación teórica exacta en la fuente original de la estrategia
(el vídeo solo dice "mínimo reciente", sin cuantificar).

Este script prueba varios valores de N sobre el histórico real del
S&P 500 y mide, para cada uno, 4 métricas que ayudan a decidir cuál
maximiza la utilidad de la señal como filtro de entrada (F5):

  1. Forward return del S&P 500 tras cada señal nueva (False->True),
     a distintos horizontes (4, 8, 12, 26 semanas).
  2. Tasa de señales "falsas" (forward return negativo a 8 semanas).
  3. Número total de señales generadas en el periodo.
  4. Retraso medio (en semanas) entre el mínimo local real del Coppock
     (detectado con retrospectiva total, scipy.signal.argrelextrema) y
     la primera señal `start_bullish` que aparece tras ese mínimo.

Importante — qué mide y qué NO mide este script
-------------------------------------------------
- Mide la calidad de F5 como filtro de MERCADO (usando el Coppock del
  S&P 500), NO la rentabilidad de la estrategia completa (que además
  depende de F1-F4, la selección de ticker y el criterio de salida).
  Es decir: es un backtest del filtro de mercado, no de la cartera.
- Usa datos históricos reales, así que está sujeto al sesgo de que el
  pasado no garantiza el futuro. Trátalo como evidencia orientativa,
  no como prueba definitiva.
- No optimiza en el sentido de "elegir el N que da más rentabilidad
  histórica" a ciegas (eso sería overfitting con una sola serie de
  datos). El objetivo es entender el TRADE-OFF entre sensibilidad
  (N pequeño) y fiabilidad (N grande) con números reales delante,
  no encontrar el N "óptimo" de forma mecánica.

Requisitos
----------
    pip install yfinance pandas numpy scipy --break-system-packages

Uso
---
    python backtest_lookback.py
    python backtest_lookback.py --period 15y --lookbacks 2,3,4,6,8,12
    python backtest_lookback.py --horizons 4,8,12,26
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from scipy.signal import argrelextrema
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


# ── Reutilización exacta de las fórmulas del proyecto ─────────────────
# (copiadas literalmente de weinstein/indicators.py para que el backtest
#  use EXACTAMENTE los mismos cálculos que el escáner real, sin
#  reimplementar con matices distintos que invalidarían la comparación)

def wma(series: pd.Series, period: int) -> pd.Series:
    weights = np.arange(1, period + 1, dtype=float)
    w_sum = weights.sum()
    return series.rolling(window=period).apply(
        lambda x: np.dot(x, weights) / w_sum,
        raw=True,
    )


def coppock_curve(
    price: pd.Series,
    roc_long: int = 12,
    roc_short: int = 6,
    wma_period: int = 10,
) -> pd.Series:
    roc_l = price.pct_change(periods=roc_long) * 100.0
    roc_s = price.pct_change(periods=roc_short) * 100.0
    combined = roc_l + roc_s
    return wma(combined, wma_period)


def sp500_alcista_at(
    coppock: pd.Series,
    idx: int,
    recent_lookback: int,
) -> bool:
    """
    Misma lógica que weinstein.indicators.sp500_alcista(), pero evaluada
    en un índice posicional arbitrario `idx` de la serie (no solo en el
    último valor), para poder recorrer todo el histórico semana a
    semana durante el backtest.

    Replica fielmente start_bullish / continuation_bullish tal como
    están implementados en el proyecto.
    """
    if idx < 1:
        return False

    current = coppock.iloc[idx]
    previous = coppock.iloc[idx - 1]

    if pd.isna(current) or pd.isna(previous):
        return False

    current = float(current)
    previous = float(previous)

    start_bullish = False
    if idx >= recent_lookback:
        window = coppock.iloc[idx - recent_lookback: idx]  # las N previas a "previous"...
        # Nota: replicamos EXACTAMENTE la semántica de indicators.py:
        # recent_window = valid.iloc[-(recent_lookback+1):-1] tomado sobre
        # la serie ya truncada en "current". Aquí, sobre índices
        # posicionales absolutos, la ventana equivalente es
        # coppock[idx-recent_lookback : idx] (excluye "current", incluye
        # "previous" como último elemento).
        window = coppock.iloc[max(0, idx - recent_lookback): idx]
        window_valid = window.dropna()
        if len(window_valid) >= 1:
            prev_is_min = abs(previous - float(window_valid.min())) < 1e-9
            start_bullish = (
                current < 0.0
                and previous < 0.0
                and prev_is_min
                and current > previous
            )

    continuation_bullish = current > 0.0 and current > previous

    return start_bullish or continuation_bullish


# ── Métricas del backtest ──────────────────────────────────────────────

@dataclass
class LookbackResult:
    lookback: int
    n_signals: int = 0
    forward_returns: dict[int, list[float]] = field(default_factory=dict)
    delay_to_real_min: list[int] = field(default_factory=list)

    def summary_row(self, horizons: list[int]) -> dict:
        row: dict = {"Lookback": self.lookback, "N Señales": self.n_signals}
        for h in horizons:
            rets = self.forward_returns.get(h, [])
            if rets:
                row[f"Ret. medio {h}w (%)"] = round(float(np.mean(rets)), 2)
                row[f"Ret. mediana {h}w (%)"] = round(float(np.median(rets)), 2)
                row[f"% señales negativas a {h}w"] = round(
                    100.0 * sum(1 for r in rets if r < 0) / len(rets), 1
                )
            else:
                row[f"Ret. medio {h}w (%)"] = None
                row[f"Ret. mediana {h}w (%)"] = None
                row[f"% señales negativas a {h}w"] = None
        if self.delay_to_real_min:
            row["Retraso medio vs mínimo real (semanas)"] = round(
                float(np.mean(self.delay_to_real_min)), 1
            )
        else:
            row["Retraso medio vs mínimo real (semanas)"] = None
        return row


def find_real_local_minima(coppock: pd.Series, order: int = 4) -> list[int]:
    """
    Detecta mínimos locales REALES del Coppock con retrospectiva total
    (mira hacia adelante y hacia atrás `order` periodos), usando
    scipy.signal.argrelextrema. Esto sirve como "verdad de referencia"
    independiente de cualquier `lookback` que se esté evaluando, para
    medir cuánto tarda la señal en reaccionar tras un suelo real.

    Solo se consideran mínimos en terreno negativo (coppock < 0), que es
    el contexto relevante para `start_bullish`.
    """
    if not HAS_SCIPY:
        return []

    values = coppock.to_numpy()
    valid_mask = ~np.isnan(values)
    if valid_mask.sum() < order * 2 + 1:
        return []

    minima_idx = argrelextrema(values, np.less_equal, order=order)[0]
    # Filtrar solo mínimos en negativo y evitar duplicados en mesetas
    result = []
    prev_i = -10
    for i in minima_idx:
        if np.isnan(values[i]):
            continue
        if values[i] < 0.0 and (i - prev_i) > order:
            result.append(int(i))
            prev_i = i
    return result


def run_backtest_for_lookback(
    coppock: pd.Series,
    close: pd.Series,
    lookback: int,
    horizons: list[int],
    real_minima: list[int],
) -> LookbackResult:
    result = LookbackResult(lookback=lookback)
    n = len(coppock)

    prev_state = False
    signal_indices: list[int] = []

    for i in range(1, n):
        state = sp500_alcista_at(coppock, i, lookback)
        if state and not prev_state:
            # Transición False -> True: nueva señal de entrada
            signal_indices.append(i)
        prev_state = state

    result.n_signals = len(signal_indices)

    for h in horizons:
        result.forward_returns[h] = []

    for sig_idx in signal_indices:
        entry_price = close.iloc[sig_idx]
        if pd.isna(entry_price):
            continue
        for h in horizons:
            target_idx = sig_idx + h
            if target_idx < len(close):
                future_price = close.iloc[target_idx]
                if not pd.isna(future_price) and entry_price != 0:
                    ret = (float(future_price) / float(entry_price) - 1.0) * 100.0
                    result.forward_returns[h].append(ret)

    # Retraso vs. mínimos reales: para cada mínimo real, buscar la
    # primera señal de este lookback que ocurra en/después de ese mínimo
    # (dentro de una ventana razonable de búsqueda de 12 semanas).
    for min_idx in real_minima:
        candidatos = [s for s in signal_indices if min_idx <= s <= min_idx + 12]
        if candidatos:
            result.delay_to_real_min.append(min(candidatos) - min_idx)

    return result


# ── Descarga de datos ──────────────────────────────────────────────────

def download_sp500(period: str) -> pd.DataFrame:
    if yf is None:
        print("✗ yfinance no está instalado. Ejecuta:")
        print("  pip install yfinance pandas numpy scipy --break-system-packages")
        sys.exit(1)

    print(f"→ Descargando S&P 500 (^GSPC), periodo={period}, semanal...")
    raw = yf.download(
        "^GSPC",
        period=period,
        interval="1wk",
        progress=False,
        auto_adjust=True,
        actions=False,
    )
    if raw is None or raw.empty:
        print("✗ No se pudo descargar el S&P 500.")
        sys.exit(1)

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    raw = raw[["Close"]].dropna()
    print(f"  ✓ {len(raw)} velas semanales descargadas "
          f"({raw.index[0].date()} → {raw.index[-1].date()})")
    return raw


# ── Impresión legible de resultados ────────────────────────────────────

def _fmt_pct(value: float | None, decimals: int = 2) -> str:
    """Formatea un porcentaje con signo explícito, o '—' si es None."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    return f"{value:+.{decimals}f}%"


def _fmt_plain(value: float | None, decimals: int = 1, suffix: str = "") -> str:
    """Formatea un número sin signo (conteos, retrasos), o '—' si es None."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    if decimals == 0:
        return f"{int(round(value))}{suffix}"
    return f"{value:.{decimals}f}{suffix}"


def print_readable_summary(
    rows: list[dict],
    horizons: list[int],
) -> None:
    """
    Imprime los resultados como una tabla legible por consola, en vez de
    depender de `DataFrame.to_string()` (que con muchas columnas numéricas
    se ensancha más de lo que cabe en una terminal normal y se corta o
    se envuelve mal).

    Estrategia: una tabla COMPACTA con las columnas clave (Nº señales,
    retorno medio y % señales negativas por horizonte, retraso), y
    justo debajo, un bloque de detalle por horizonte con también la
    mediana, para quien quiera profundizar sin saturar la tabla principal.
    """
    lookbacks = [r["Lookback"] for r in rows]

    # ── Tabla compacta (una fila por lookback, columnas por horizonte) ──
    col_lb = "Lookback"
    col_n = "Señales"
    w_lb = max(len(col_lb), max(len(str(lb)) for lb in lookbacks)) + 2
    w_n = max(len(col_n), 7) + 2
    w_h = 15  # ancho por bloque de horizonte (ret. medio + % negativas)

    # Ancho de celda de datos: "+9.52%*" (8) + espacio + "38.6%" (6) = 15
    col_w = 15

    header = f"{col_lb:>{w_lb}} | {col_n:>{w_n}}"
    subheader = f"{'':>{w_lb}} | {'':>{w_n}}"
    for h in horizons:
        label = f"{h} semanas"
        header += f" | {label:^{col_w}}"
        sub = f"{'ret.medio':>8} {'%neg':>6}"
        subheader += f" | {sub:^{col_w}}"

    total_width = len(header)
    print("┌" + "─" * total_width + "┐")
    print("  RETORNO MEDIO DEL S&P 500 TRAS CADA SEÑAL, POR VENTANA DE LOOKBACK")
    print("└" + "─" * total_width + "┘")
    print(header)
    print(subheader)
    print("─" * total_width)

    best_ret = {}
    for h in horizons:
        vals = [r.get(f"Ret. medio {h}w (%)") for r in rows]
        vals = [v for v in vals if v is not None]
        best_ret[h] = max(vals) if vals else None

    for r in rows:
        lb = r["Lookback"]
        n = r["N Señales"]
        line = f"{lb:>{w_lb}} | {n:>{w_n}}"
        for h in horizons:
            ret = r.get(f"Ret. medio {h}w (%)")
            neg = r.get(f"% señales negativas a {h}w")
            marca = "★" if best_ret[h] is not None and ret == best_ret[h] else " "
            ret_s = (_fmt_pct(ret) + marca) if marca.strip() else _fmt_pct(ret)
            neg_s = _fmt_plain(neg, decimals=1, suffix="%")
            cell = f"{ret_s:>8} {neg_s:>6}"
            line += f" | {cell:^{col_w}}"
        print(line)

    print("─" * total_width)
    print("  ★ = mejor retorno medio de la columna   |   % neg. = % de señales con retorno negativo a ese horizonte")

    # ── Bloque de detalle: mediana y retraso ────────────────────────────
    print()
    print("┌" + "─" * total_width + "┐")
    print("  DETALLE: MEDIANA DE RETORNO Y RETRASO FRENTE AL MÍNIMO REAL DEL COPPOCK")
    print("└" + "─" * total_width + "┘")

    w_delay = 12
    header2 = f"{col_lb:>{w_lb}} |"
    for h in horizons:
        header2 += f" {'mediana ' + str(h) + 'w':>13} |"
    header2 += f" {'retraso (sem)':>{w_delay}}"
    print(header2)
    print("─" * len(header2))

    for r in rows:
        lb = r["Lookback"]
        line = f"{lb:>{w_lb}} |"
        for h in horizons:
            med = r.get(f"Ret. mediana {h}w (%)")
            line += f" {_fmt_pct(med):>13} |"
        delay = r.get("Retraso medio vs mínimo real (semanas)")
        line += f" {_fmt_plain(delay, decimals=1):>{w_delay}}"
        print(line)

    print("─" * len(header2))

    # ── Meseta / rango sin cambios (detección automática) ───────────────
    print()
    key_cols = [f"Ret. medio {h}w (%)" for h in horizons] + ["N Señales"]
    grupos: list[list[int]] = []
    for r in rows:
        firma = tuple(r.get(c) for c in key_cols)
        if grupos and _firma_de(rows, grupos[-1][-1], key_cols) == firma:
            grupos[-1].append(r["Lookback"])
        else:
            grupos.append([r["Lookback"]])

    mesetas = [g for g in grupos if len(g) > 1]
    if mesetas:
        print("  Nota — rangos con resultados IDÉNTICOS (ninguna señal cambia en ese tramo):")
        for g in mesetas:
            print(f"    · lookback {g[0]}–{g[-1]}: {len(g)} valores probados, mismo resultado exacto")
        print("    → Dentro de estos rangos el parámetro es indiferente para este periodo histórico.")


def _firma_de(rows: list[dict], lookback: int, key_cols: list[str]) -> tuple:
    for r in rows:
        if r["Lookback"] == lookback:
            return tuple(r.get(c) for c in key_cols)
    return ()


# ── Main ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest de COPPOCK_RECENT_LOOKBACK para sp500_alcista()"
    )
    parser.add_argument("--period", default="15y", help="Periodo yfinance (default: 15y)")
    parser.add_argument(
        "--lookbacks", default="2,3,4,6,8,10,12",
        help="Valores de lookback a comparar, separados por coma (default: 2,3,4,6,8,10,12)"
    )
    parser.add_argument(
        "--horizons", default="4,8,12,26",
        help="Horizontes de forward return en semanas, separados por coma (default: 4,8,12,26)"
    )
    args = parser.parse_args()

    lookbacks = [int(x) for x in args.lookbacks.split(",")]
    horizons = [int(x) for x in args.horizons.split(",")]

    data = download_sp500(args.period)
    close = data["Close"]

    print("\n→ Calculando Coppock semanal (ROC12+ROC6, WMA10)...")
    copk = coppock_curve(close)

    real_minima = find_real_local_minima(copk, order=4)
    if HAS_SCIPY:
        print(f"  ✓ {len(real_minima)} mínimos locales reales detectados en terreno negativo "
              f"(referencia con retrospectiva total)")
    else:
        print("  ⚠ scipy no disponible: se omite la métrica de retraso vs. mínimo real.")
        print("    Instala con: pip install scipy --break-system-packages")

    print(f"\n→ Ejecutando backtest para lookbacks: {lookbacks}")
    print(f"  Horizontes de forward return (semanas): {horizons}\n")

    rows = []
    for lb in lookbacks:
        res = run_backtest_for_lookback(copk, close, lb, horizons, real_minima)
        rows.append(res.summary_row(horizons))

    print()
    print_readable_summary(rows, horizons)

    print("""
Cómo leer esta tabla
---------------------
- Señales: cuántas veces se activó start_bullish/continuation_bullish
  (transición False->True) durante el periodo. Muy pocas señales indica
  que el filtro rara vez deja entrar; muchas señales indica que es
  permisivo (más riesgo de ruido).
- Ret. medio Xw: rentabilidad del S&P 500 en las X semanas siguientes a
  cada señal. Más alto es mejor, pero compáralo también con la mediana
  del bloque de detalle (la media puede estar distorsionada por pocos
  casos extremos).
- % neg.: proporción de señales que resultaron en pérdida a X semanas —
  una proxy de "señales falsas". Más bajo es mejor.
- Retraso (sem): cuántas semanas tarda la señal en aparecer después de
  un suelo real del Coppock (detectado con retrospectiva). Más bajo
  significa que entras más cerca del suelo real; más alto significa que
  entras tarde (el movimiento ya lleva recorrido).

Qué NO concluir de esta tabla
-------------------------------
- No elijas mecánicamente "el lookback con mayor retorno medio": con una
  sola serie histórica (el S&P 500) hay alto riesgo de sobreajuste. Usa
  la tabla para entender el TRADE-OFF (sensibilidad vs. fiabilidad) y
  decide con margen de seguridad, no el máximo puntual.
- Esto solo mide el filtro de mercado F5 en aislamiento, no el resultado
  de la estrategia completa (que depende también de F1-F4 y de S1-S2).
""")


if __name__ == "__main__":
    main()