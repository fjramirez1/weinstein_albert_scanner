"""
Señales de la estrategia Weinstein-Albert: única definición compartida por
los escáneres de producción y por el backtest.

Antes, el escáner calculaba cada filtro con escalares en su propio código y
el backtest lo reimplementaba con series en `backtest/conditions.py`; un
cambio en un lado podía no llegar al otro (tarea R1 de
`docs/HOJA_DE_RUTA.md`). Ahora ambos usan:

- `build_ticker_context()`: todos los indicadores de un ticker, calculados
  una vez sobre su histórico completo (vectorizado, sin look-ahead: el
  valor en la semana i solo depende de datos hasta i).
- `market_state_series()`: F5 (Coppock alcista) y S2 (Coppock bajista)
  semana a semana para el S&P 500.
- Las reglas F1-F4 y S1 como funciones de comparación que aceptan tanto un
  escalar (el escáner mira la última semana) como una serie completa (el
  backtest mira todas). Un NaN nunca cumple una regla.

Los umbrales por defecto salen de `weinstein/config.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from weinstein.config import (
    COPPOCK_RECENT_LOOKBACK,
    COPPOCK_ROC_LONG,
    COPPOCK_ROC_SHORT,
    COPPOCK_WMA_PERIOD,
    MAX_DISTANCIA_WMA30,
    RSC_EXIT_THRESHOLD,
    RSC_SMA_PERIOD,
    SECTOR_RSC_MIN,
    VPM_BASE_PERIOD,
    VPM_SMOOTHING,
    WMA30_PERIOD,
)
from weinstein.indicators import coppock_curve, rsc_mansfield, sp500_alcista, sp500_bajista, vpm5, wma

# Velas mínimas para construir un contexto: la SMA del RSC Mansfield
# necesita RSC_SMA_PERIOD semanas y se deja un pequeño margen.
MIN_CONTEXT_BARS = RSC_SMA_PERIOD + 5

Valor = float | pd.Series


# ── Reglas (escalar o serie) ──────────────────────────────────────────

def _cumple(resultado: bool | pd.Series) -> bool | pd.Series:
    """Normaliza el resultado de una comparación: NaN → False, escalar → bool."""
    if isinstance(resultado, pd.Series):
        return resultado.fillna(False).astype(bool)
    return bool(resultado)


def f1_sector_fuerte(rsc_sector: Valor, umbral: float = SECTOR_RSC_MIN) -> bool | pd.Series:
    """F1: RSC Mansfield del sector >= umbral."""
    return _cumple(rsc_sector >= umbral)


def f2_volumen_positivo(vpm5_val: Valor, umbral: float = 0.0) -> bool | pd.Series:
    """F2: VPM5 > umbral (volumen por encima de su media de 52 semanas)."""
    return _cumple(vpm5_val > umbral)


def f3_rsc_activo_positivo(rsc_activo: Valor, umbral: float = 0.0) -> bool | pd.Series:
    """F3: RSC Mansfield del activo > umbral."""
    return _cumple(rsc_activo > umbral)


def f4_distancia_wma30(dist_pct: Valor, max_distancia: float = MAX_DISTANCIA_WMA30) -> bool | pd.Series:
    """F4: distancia % al WMA30 < máximo (sin cota inferior)."""
    return _cumple(dist_pct < max_distancia)


def s1_rsc_debil(rsc_activo: Valor, umbral: float = RSC_EXIT_THRESHOLD) -> bool | pd.Series:
    """S1: RSC Mansfield del activo < umbral → salida."""
    return _cumple(rsc_activo < umbral)


# ── Contexto precalculado por ticker ──────────────────────────────────

@dataclass
class TickerContext:
    """
    Indicadores de UN ticker sobre todo su histórico. Todas las series
    comparten el índice de `close` (ya alineado contra el S&P 500 y el ETF
    sectorial), así que `serie.iloc[i]` es la semana i en cualquiera.
    """
    ticker: str
    sector: str
    close: pd.Series
    volume: pd.Series
    wma30: pd.Series
    vpm5: pd.Series
    rsc_activo: pd.Series          # RSC Mansfield activo vs S&P 500
    dist_wma30_pct: pd.Series
    momentum: pd.Series
    rsc_sector: pd.Series          # RSC Mansfield del sector vs S&P 500 (reindexado a `close`)
    coppock_bullish: pd.Series     # sin uso: F5 lo inyecta el motor (ver market_state_series)
    coppock_bearish: pd.Series     # ídem para S2
    open: pd.Series | None = None  # apertura semanal (ejecución "next_open"); None → se usa close


def build_ticker_context(
    ticker: str,
    sector: str,
    data: pd.DataFrame,
    sp500_close: pd.Series,
    sector_etf_close: pd.Series | None,
) -> TickerContext | None:
    """
    Calcula todos los indicadores de un ticker. Devuelve ``None`` si hay
    menos de `MIN_CONTEXT_BARS` velas. Sin ETF sectorial, `rsc_sector` es
    NaN (F1 no se cumple nunca).
    """
    close = data["Close"].squeeze().astype(float)
    volume = data["Volume"].squeeze().astype(float)
    open_ = data["Open"].squeeze().astype(float) if "Open" in data.columns else None

    if len(close) < MIN_CONTEXT_BARS:
        return None

    wma30 = wma(close, WMA30_PERIOD)
    vpm5_series = vpm5(data, VPM_BASE_PERIOD, VPM_SMOOTHING)

    rsc_activo = rsc_activo_series(close, sp500_close)

    dist_wma30 = ((close - wma30) / wma30) * 100.0
    momentum = (close - wma30) / wma30

    rsc_sector = sector_rsc_series(sector_etf_close, sp500_close)
    rsc_sector = (
        rsc_sector.reindex(close.index, method="ffill")
        if rsc_sector is not None
        else pd.Series(np.nan, index=close.index)
    )

    return TickerContext(
        ticker=ticker,
        sector=sector,
        close=close,
        volume=volume,
        wma30=wma30,
        vpm5=vpm5_series,
        rsc_activo=rsc_activo,
        dist_wma30_pct=dist_wma30,
        momentum=momentum,
        rsc_sector=rsc_sector,
        coppock_bullish=pd.Series(dtype=bool),
        coppock_bearish=pd.Series(dtype=bool),
        open=open_,
    )


def rsc_activo_series(close: pd.Series, sp500_close: pd.Series) -> pd.Series:
    """RSC Mansfield del activo frente al S&P 500, en el índice de `close`."""
    close_a, sp500_a = close.align(sp500_close, join="inner")
    return rsc_mansfield(close_a, sp500_a).reindex(close.index)


def sector_rsc_series(sector_etf_close: pd.Series | None, sp500_close: pd.Series) -> pd.Series | None:
    """RSC Mansfield del ETF sectorial frente al S&P 500 (None si no hay ETF)."""
    if sector_etf_close is None:
        return None
    sector_a, sp500_a = sector_etf_close.align(sp500_close, join="inner")
    return rsc_mansfield(sector_a, sp500_a)


def entry_conditions_at(ctx: TickerContext, i: int = -1) -> dict[str, bool]:
    """
    F1-F4 con los umbrales de `config.py` en la semana `i` (por defecto la
    última). F5 es de mercado y no depende del ticker: ver
    `market_state_series`.
    """
    return {
        "F1_sector_fuerte": f1_sector_fuerte(ctx.rsc_sector.iloc[i]),
        "F2_volumen_positivo": f2_volumen_positivo(ctx.vpm5.iloc[i]),
        "F3_rsc_activo_positivo": f3_rsc_activo_positivo(ctx.rsc_activo.iloc[i]),
        "F4_distancia_wma30": f4_distancia_wma30(ctx.dist_wma30_pct.iloc[i]),
    }


# ── Estado de mercado (F5 / S2) ───────────────────────────────────────

def market_state_series(
    sp500_close: pd.Series,
    recent_lookback: int = COPPOCK_RECENT_LOOKBACK,
    roc_long: int = COPPOCK_ROC_LONG,
    roc_short: int = COPPOCK_ROC_SHORT,
    wma_period: int = COPPOCK_WMA_PERIOD,
) -> tuple[pd.Series, pd.Series]:
    """
    F5 (`sp500_alcista`) y S2 (`sp500_bajista`) semana a semana, sin
    look-ahead: en la semana i solo se usa `coppock.iloc[:i+1]`. El valor
    de la última semana es exactamente lo que ve el escáner hoy. Los
    parámetros del Coppock son configurables para el backtest (O2).
    """
    copk = coppock_curve(sp500_close, roc_long=roc_long, roc_short=roc_short, wma_period=wma_period)
    n = len(copk)
    bullish = np.zeros(n, dtype=bool)
    bearish = np.zeros(n, dtype=bool)
    for i in range(n):
        sub = copk.iloc[: i + 1]
        bullish[i], _ = sp500_alcista(sub, recent_lookback=recent_lookback)
        bearish[i], _ = sp500_bajista(sub)
    return pd.Series(bullish, index=copk.index), pd.Series(bearish, index=copk.index)
