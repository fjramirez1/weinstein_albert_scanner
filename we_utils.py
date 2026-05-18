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
