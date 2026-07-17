"""
Indicadores técnicos de la estrategia Weinstein-Albert.

Todas las funciones son puras: reciben series de pandas y devuelven
series o escalares. No dependen de configuración externa ni de I/O.
"""

from __future__ import annotations

import sys

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


# ── Medias móviles ────────────────────────────────────────────────────

def wma(series: pd.Series, period: int) -> pd.Series:
    """
    Media Móvil Ponderada de ``period`` periodos.

    Peso lineal: 1 al valor más antiguo, ``period`` al más reciente.
    WMA = Σ(precio_i × i) / Σ(i)  para i en [1, period].
    """
    weights = np.arange(1, period + 1, dtype=float)
    w_sum = weights.sum()
    return series.rolling(window=period).apply(
        lambda x: np.dot(x, weights) / w_sum,
        raw=True,
    )


# ── Fuerza relativa ───────────────────────────────────────────────────

def rsc_mansfield(
    price_asset: pd.Series,
    price_benchmark: pd.Series,
    sma_period: int = RSC_SMA_PERIOD,
) -> pd.Series:
    """
    RSC Mansfield del activo frente al benchmark.

    R(t)   = precio_activo(t) / precio_benchmark(t)
    SMA52  = SMA(R, sma_period)
    RSC(t) = (R(t) / SMA52(t) - 1) × 10

    Positivo → activo supera la media de su comportamiento relativo.

    ``sma`` puede ser 0 en casos degenerados (p.ej. precios relativos
    extremadamente pequeños en penny stocks); se sustituye por NaN antes
    de dividir para evitar producir ``inf``/``-inf``, igual que ya se
    hacía en ``vpm5`` con la desviación estándar.

    El alineado por fecha (``align(join="inner")``) descarta las fechas
    que no coinciden exactamente entre ``price_asset`` y
    ``price_benchmark`` (p.ej. festivos de mercado distintos o refrescos
    parciales de caché en la fuente de datos). Normalmente la diferencia
    es de 0-1 filas y es inofensiva, pero si es grande indica que algo
    va mal en los datos de entrada, así que se registra un aviso en
    stderr para poder detectarlo en vez de que pase inadvertido.
    """
    asset, bench = price_asset.align(price_benchmark, join="inner")

    dropped_asset = len(price_asset) - len(asset)
    dropped_bench = len(price_benchmark) - len(bench)
    if max(dropped_asset, dropped_bench) > 2:
        print(
            f"  ⚠ rsc_mansfield: desalineación de fechas al hacer inner join "
            f"(activo: {len(price_asset)} -> {len(asset)} filas, "
            f"benchmark: {len(price_benchmark)} -> {len(bench)} filas). "
            "Revisa si las fuentes de datos tienen fechas de cierre distintas.",
            file=sys.stderr,
        )

    relative = asset / bench
    sma = relative.rolling(window=sma_period).mean()
    sma_safe = sma.replace(0, np.nan)
    return ((relative / sma_safe) - 1.0) * 10.0


# ── Volumen ───────────────────────────────────────────────────────────

def vpm5(
    data: pd.DataFrame,
    base_period: int = VPM_BASE_PERIOD,
    smoothing_period: int = VPM_SMOOTHING,
) -> pd.Series:
    """
    Volumen Proporcional Medio suavizado (VPM5).

    1. Estandariza el volumen respecto a media/desv de las últimas
       ``base_period`` semanas.
    2. Suaviza con SMA de ``smoothing_period`` periodos.

    Positivo → volumen por encima de su media histórica.
    """
    volume = data["Volume"].squeeze().astype(float)
    rolling_mean = volume.rolling(window=base_period).mean()
    rolling_std  = volume.rolling(window=base_period).std(ddof=0)
    vpm          = (volume - rolling_mean) / rolling_std.replace(0, np.nan)
    return vpm.rolling(window=smoothing_period).mean()


# ── Momentum y distancia ──────────────────────────────────────────────

def momentum_vs_wma(
    close: pd.Series,
    period: int = WMA30_PERIOD,
    wma_series: pd.Series | None = None,
) -> float | None:
    """
    Momentum relativo: (precio_actual - WMA) / WMA.

    Devuelve ``None`` si no hay datos suficientes o la WMA es inválida.
    Usado para ordenar candidatos que superan todos los filtros.

    Si el llamador ya calculó la WMA (p.ej. porque también la necesita
    para ``distancia_wma_pct``), puede pasarla en ``wma_series`` para
    evitar recalcularla — ``wma()`` es una operación cara
    (``rolling().apply()`` sobre todo el histórico).
    """
    if len(close) < period:
        return None
    wma_calc = wma_series if wma_series is not None else wma(close, period)
    wma_val  = float(wma_calc.iloc[-1])
    if pd.isna(wma_val) or wma_val <= 0:
        return None
    return (float(close.iloc[-1]) - wma_val) / wma_val


def distancia_wma_pct(
    close: pd.Series,
    period: int = WMA30_PERIOD,
    wma_series: pd.Series | None = None,
) -> float | None:
    """
    Distancia porcentual del precio actual a la WMA: (C - WMA) / WMA × 100.

    Devuelve ``None`` si la WMA no se puede calcular.

    Acepta una ``wma_series`` precalculada (ver ``momentum_vs_wma``) para
    evitar recomputar la misma WMA dos veces sobre el mismo histórico.
    """
    if len(close) < period:
        return None
    wma_calc = wma_series if wma_series is not None else wma(close, period)
    wma_val  = float(wma_calc.iloc[-1])
    if pd.isna(wma_val) or wma_val <= 0:
        return None
    return ((float(close.iloc[-1]) - wma_val) / wma_val) * 100.0


# ── Coppock ───────────────────────────────────────────────────────────

def coppock_curve(
    price: pd.Series,
    roc_long:   int = COPPOCK_ROC_LONG,
    roc_short:  int = COPPOCK_ROC_SHORT,
    wma_period: int = COPPOCK_WMA_PERIOD,
) -> pd.Series:
    """
    Curva de Coppock semanal.

    Coppock(t) = WMA_wma_period( ROC_roc_long(P) + ROC_roc_short(P) )

    Parámetros por defecto: ROC_12 + ROC_6, suavizado con WMA_10.
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
    1. Inicio alcista: Coppock negativo, valor previo era el mínimo
       reciente y la curva comienza a girar al alza.
    2. Continuación alcista: Coppock positivo y creciendo.

    Retorna (bool, str) → bandera alcista y etiqueta legible.
    """
    valid = coppock.dropna()
    if len(valid) < 2:
        return False, "↓ Bajista"

    current  = float(valid.iloc[-1])
    previous = float(valid.iloc[-2])

    start_bullish = False
    if len(valid) >= recent_lookback + 1:
        recent_window = valid.iloc[-(recent_lookback + 1):-1]
        prev_is_min = abs(previous - float(recent_window.min())) < 1e-9
        start_bullish = (
            current  < 0.0
            and previous < 0.0
            and prev_is_min
            and current > previous
        )

    continuation_bullish = current > 0.0 and current > previous

    bullish   = start_bullish or continuation_bullish
    direction = "↑ Alcista" if bullish else "↓ Bajista"
    return bullish, direction


def sp500_bajista(
    coppock: pd.Series,
) -> tuple[bool, str]:
    """
    Determina si el S&P 500 está en fase bajista según el Coppock, tal
    como se define en la fuente original de la estrategia (vídeo de
    referencia — ver README, sección "Referencias"). NO es simplemente
    el complemento lógico de ``sp500_alcista()``.

    Señal bajista en dos casos:
    1. Cruce a negativo: Coppock estaba en terreno positivo (o cero) la
       semana anterior y pasa a negativo esta semana. Señala el fin de
       una tendencia alcista.
    2. Confirmación de bajista: Coppock ya es negativo y sigue cayendo
       respecto a la semana anterior. Señala que la tendencia bajista
       se mantiene y se fortalece.

    A diferencia de ``sp500_alcista()``, esta función no exige que el
    valor previo sea el mínimo de una ventana reciente: basta con que
    el valor actual sea menor que el anterior estando ya en negativo.

    Importante — estado neutro: ``sp500_alcista()`` y ``sp500_bajista()``
    NO son complementarias. Existe un tercer estado ("ni alcista ni
    bajista") para tramos de transición, por ejemplo:
      - Un rebote en negativo que no es el primer rebote desde el
        mínimo reciente (no cumple ``sp500_alcista``, y tampoco cae
        respecto a la semana anterior, así que no cumple
        ``sp500_bajista``).
      - Un Coppock positivo pero decreciente: ya no es "continuación
        alcista" (exige ``current > previous``), pero tampoco ha
        cruzado a negativo, así que no es "bajista" según esta función.
    En ese estado neutro ambas funciones devuelven False.

    Retorna (bool, str) → bandera bajista y etiqueta legible.
    """
    valid = coppock.dropna()
    if len(valid) < 2:
        return False, "→ Neutral"

    current  = float(valid.iloc[-1])
    previous = float(valid.iloc[-2])

    cruce_a_negativo     = previous >= 0.0 and current < 0.0
    confirmacion_bajista = current < 0.0 and current < previous

    bajista   = cruce_a_negativo or confirmacion_bajista
    direction = "↓ Bajista" if bajista else "→ Neutral"
    return bajista, direction
