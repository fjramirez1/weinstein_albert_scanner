"""
Indicadores técnicos de la estrategia Weinstein-Albert.

Todas las funciones son puras: reciben series de pandas y devuelven
series o escalares. No dependen de configuración externa ni de I/O.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from weinstein.config import (
    COPPOCK_RECENT_LOOKBACK,
    COPPOCK_ROC_LONG,
    COPPOCK_ROC_SHORT,
    COPPOCK_WMA_PERIOD,
    RSC_SMA_PERIOD,
    VPM_BASE_PERIOD,
    VPM_SMOOTHING,
    WMA30_PERIOD,
)


# ─────────────────────────────────────────────────────────────────────
# Medias móviles
# ─────────────────────────────────────────────────────────────────────

def wma(series: pd.Series, period: int) -> pd.Series:
    """
    Media Móvil Ponderada de ``period`` periodos.

    El peso lineal asigna 1 al valor más antiguo y ``period`` al más
    reciente: WMA = Σ(precio_i × i) / Σ(i)  para i en [1, period].
    """
    weights = np.arange(1, period + 1, dtype=float)
    w_sum = weights.sum()
    return series.rolling(window=period).apply(
        lambda x: np.dot(x, weights) / w_sum,
        raw=True,
    )


# ─────────────────────────────────────────────────────────────────────
# Fuerza relativa
# ─────────────────────────────────────────────────────────────────────

def rsc_mansfield(
    price_asset: pd.Series,
    price_benchmark: pd.Series,
    sma_period: int = RSC_SMA_PERIOD,
) -> pd.Series:
    """
    RSC Mansfield del activo frente al benchmark.

    Fórmula
    -------
    R(t)   = precio_activo(t) / precio_benchmark(t)
    SMA52  = SMA(R, sma_period)
    RSC(t) = (R(t) / SMA52(t) - 1) × 10

    Valores positivos indican que el activo supera la media de su
    comportamiento relativo respecto al benchmark.
    """
    asset, bench = price_asset.align(price_benchmark, join="inner")
    relative = asset / bench
    sma = relative.rolling(window=sma_period).mean()
    return ((relative / sma) - 1.0) * 10.0


# ─────────────────────────────────────────────────────────────────────
# Volumen
# ─────────────────────────────────────────────────────────────────────

def vpm5(
    data: pd.DataFrame,
    base_period: int = VPM_BASE_PERIOD,
    smoothing_period: int = VPM_SMOOTHING,
) -> pd.Series:
    """
    Volumen Proporcional Medio suavizado (VPM5).

    Pasos
    -----
    1. Estandarizar el volumen respecto a la media y desviación típica
       de las últimas ``base_period`` semanas.
    2. Suavizar con una SMA de ``smoothing_period`` periodos.

    Un valor positivo indica que el volumen actual está por encima de
    su media histórica (interés comprador presente).
    """
    volume = data["Volume"].squeeze().astype(float)
    rolling_mean = volume.rolling(window=base_period).mean()
    rolling_std  = volume.rolling(window=base_period).std(ddof=0)
    vpm          = (volume - rolling_mean) / rolling_std.replace(0, np.nan)
    return vpm.rolling(window=smoothing_period).mean()


# ─────────────────────────────────────────────────────────────────────
# Momentum y distancia
# ─────────────────────────────────────────────────────────────────────

def momentum_vs_wma(
    close: pd.Series,
    period: int = WMA30_PERIOD,
) -> float | None:
    """
    Momentum relativo: (precio_actual - WMA) / WMA.

    Devuelve ``None`` si no hay datos suficientes o la WMA es inválida.
    Se usa para ordenar candidatos que pasan todos los filtros.
    """
    if len(close) < period:
        return None
    wma_series = wma(close, period)
    wma_val    = float(wma_series.iloc[-1])
    if pd.isna(wma_val) or wma_val <= 0:
        return None
    return (float(close.iloc[-1]) - wma_val) / wma_val


def distancia_wma_pct(close: pd.Series, period: int = WMA30_PERIOD) -> float | None:
    """
    Distancia porcentual del precio actual a la WMA: (C - WMA) / WMA × 100.

    Devuelve ``None`` si la WMA no se puede calcular.
    """
    if len(close) < period:
        return None
    wma_series = wma(close, period)
    wma_val    = float(wma_series.iloc[-1])
    if pd.isna(wma_val) or wma_val <= 0:
        return None
    return ((float(close.iloc[-1]) - wma_val) / wma_val) * 100.0


# ─────────────────────────────────────────────────────────────────────
# Coppock
# ─────────────────────────────────────────────────────────────────────

def coppock_curve(
    price: pd.Series,
    roc_long:   int = COPPOCK_ROC_LONG,
    roc_short:  int = COPPOCK_ROC_SHORT,
    wma_period: int = COPPOCK_WMA_PERIOD,
) -> pd.Series:
    """
    Curva de Coppock semanal.

    Fórmula
    -------
    Coppock(t) = WMA_wma_period( ROC_roc_long(P) + ROC_roc_short(P) )

    Parámetros por defecto según la especificación semanal de la
    estrategia: ROC_12 + ROC_6, suavizado con WMA_10.
    """
    roc_l    = price.pct_change(periods=roc_long)  * 100.0
    roc_s    = price.pct_change(periods=roc_short) * 100.0
    combined = roc_l + roc_s
    return wma(combined, wma_period)


def sp500_alcista(
    coppock: pd.Series,
    recent_lookback: int = COPPOCK_RECENT_LOOKBACK,
) -> tuple[bool, str]:
    """
    Determina si el S&P 500 está en fase alcista según el Coppock.

    Señal alcista en dos casos:
    1. **Inicio alcista**: Coppock en negativo, el valor previo era el
       mínimo reciente y la curva comienza a girar al alza.
    2. **Continuación alcista**: Coppock positivo y creciendo.

    Retorna
    -------
    (bool, str)
        Bandera alcista y etiqueta legible («↑ Alcista» / «↓ Bajista»).
    """
    valid = coppock.dropna()
    if len(valid) < 2:
        return False, "↓ Bajista"

    current  = float(valid.iloc[-1])
    previous = float(valid.iloc[-2])

    # Caso 1: giro al alza desde zona negativa
    start_bullish = False
    if len(valid) >= recent_lookback + 1:
        recent_window = valid.iloc[-(recent_lookback + 1):-1]
        prev_is_min   = previous == float(recent_window.min())
        start_bullish = (
            current  < 0.0
            and previous < 0.0
            and prev_is_min
            and current > previous
        )

    # Caso 2: continuación en zona positiva
    continuation_bullish = current > 0.0 and current > previous

    bullish   = start_bullish or continuation_bullish
    direction = "↑ Alcista" if bullish else "↓ Bajista"
    return bullish, direction