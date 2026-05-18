import numpy as np
import pandas as pd


def wma(series: pd.Series, period: int) -> pd.Series:
    """
    Media Móvil Ponderada de `period` periodos.

    Fórmula
    -------
    WMA_n = Σ(precio_i × peso_i) / Σ(pesos)
    donde peso_i = i  (1 para el más antiguo, n para el más reciente)
    """
    weights = np.arange(1, period + 1, dtype=float)
    w_sum = weights.sum()

    return series.rolling(window=period).apply(
        lambda x: np.dot(x, weights) / w_sum,
        raw=True,
    )


def rsc_mansfield(
    price_asset: pd.Series,
    price_benchmark: pd.Series,
    sma_period: int = 52,
) -> pd.Series:
    """
    Fuerza Relativa de Mansfield respecto al benchmark.
    """
    asset_aligned, bench_aligned = price_asset.align(price_benchmark, join="inner")
    base_rs = asset_aligned / bench_aligned
    sma52 = base_rs.rolling(window=sma_period).mean()
    rsc = ((base_rs / sma52) - 1.0) * 10.0
    return rsc


def vpm5(data: pd.DataFrame, base_period: int = 52, smoothing_period: int = 5) -> pd.Series:
    """
    Volumen Normalizado Positivo suavizado (VPM5).
    """
    volume = data["Volume"].squeeze().astype(float)

    rolling_mean = volume.rolling(window=base_period).mean()
    rolling_std = volume.rolling(window=base_period).std(ddof=0)
    vpm = (volume - rolling_mean) / rolling_std.replace(0, np.nan)

    vpm5_series = vpm.rolling(window=smoothing_period).mean()
    return vpm5_series


def coppock_curve(price: pd.Series, roc_long: int = 14, roc_short: int = 11, wma_period: int = 10) -> pd.Series:
    """
    Curva de Coppock: WMA(ROC(roc_long) + ROC(roc_short), wma_period)
    """
    roc_l = price.pct_change(periods=roc_long) * 100.0
    roc_s = price.pct_change(periods=roc_short) * 100.0
    combined = roc_l + roc_s
    return wma(combined, wma_period)


def sp500_alcista(coppock: pd.Series, recent_lookback: int = 4) -> tuple[bool, str]:
    """
    Estado alcista del S&P 500 a partir de la curva de Coppock semanal.

    La señal se activa en dos casos:
    1. Inicio alcista: Coppock sigue por debajo de cero, el valor previo fue
       el mínimo reciente y la serie empieza a girar al alza.
    2. Continuación alcista: Coppock ya es positivo y sigue subiendo.
    """
    valid = coppock.dropna()
    if len(valid) < 2:
        return False, "↓ Bajista"

    current = float(valid.iloc[-1])
    previous = float(valid.iloc[-2])

    start_bullish = False
    if len(valid) >= recent_lookback + 1:
        recent_window = valid.iloc[-(recent_lookback + 1):-1]
        previous_was_recent_min = previous == float(recent_window.min())
        start_bullish = (
            current < 0.0
            and previous < 0.0
            and previous_was_recent_min
            and current > previous
        )

    continuation_bullish = current > 0.0 and current > previous
    bullish = start_bullish or continuation_bullish
    direction = "↑ Alcista" if bullish else "↓ Bajista"
    return bullish, direction
