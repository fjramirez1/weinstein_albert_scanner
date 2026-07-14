"""
Condiciones de entrada/salida configurables para el backtest de cartera.

Diseño (híbrido, según lo acordado)
------------------------------------
- Cada condición (F1-F5 de entrada, S1-S2 de salida) es una función
  Python pura, PRECALCULADA sobre toda la serie histórica de un ticker
  de una sola vez (vectorizado con pandas), no recalculada semana a
  semana. Esto es lo que hace viable ejecutar el backtest sobre ~500
  tickers en tiempo razonable.
- Cada condición se registra como un `ConditionSpec` con un nombre, la
  función que la calcula y sus parámetros por defecto.
- Un `StrategyConfig` (dict-like) decide, para una ejecución concreta,
  qué condiciones están activas y con qué parámetros — sin tocar código
  para simplemente activar/desactivar o cambiar un umbral.
- Añadir una condición NUEVA sí requiere escribir una función Python
  (registrarla en ENTRY_CONDITIONS o EXIT_CONDITIONS) porque puede
  necesitar cualquier cálculo arbitrario; pero una vez registrada, se
  activa/parametriza igual que las demás desde el config.

Contrato de una función de condición de ENTRADA
------------------------------------------------
    def condicion(ctx: TickerContext, **params) -> pd.Series[bool]

Recibe el contexto precalculado de un ticker (precios, indicadores ya
calculados, contexto de mercado alineado a las mismas fechas) y devuelve
una serie booleana (misma longitud/índice que `ctx.close`) que indica, en
cada semana, si esa condición individual se cumple. El motor combina
todas las condiciones activas con AND para entradas.

Contrato de una función de condición de SALIDA
------------------------------------------------
Igual, pero el motor combina las activas con OR (basta una para salir), y
además cada una debe devolver una etiqueta corta para el motivo (se usa
el nombre registrado en el config).

Todas las condiciones son NULL-SAFE: donde no hay datos suficientes,
deben devolver False (nunca lanzar) para no romper la simulación por un
tramo inicial sin histórico suficiente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from weinstein.indicators import (
    coppock_curve,
    distancia_wma_pct,
    momentum_vs_wma,
    rsc_mansfield,
    sp500_alcista,
    sp500_bajista,
    vpm5,
    wma,
)


# ── Contexto precalculado por ticker ───────────────────────────────────

@dataclass
class TickerContext:
    """
    Todo lo que las condiciones necesitan sobre UN ticker, precalculado
    una única vez sobre el histórico completo (vectorizado).

    Todas las series comparten el mismo índice temporal (`close.index`),
    ya realineado contra el S&P 500 / ETF sectorial, para que acceder a
    `serie.iloc[i]` en la semana `i` sea válido para cualquier serie de
    este contexto sin realineaciones repetidas dentro del bucle de
    simulación (que sí sería caro).
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
    coppock_bullish: pd.Series     # F5 evaluado semana a semana (bool)
    coppock_bearish: pd.Series     # S2 evaluado semana a semana (bool)


def build_ticker_context(
    ticker: str,
    sector: str,
    data: pd.DataFrame,
    sp500_close: pd.Series,
    sector_etf_close: pd.Series | None,
) -> TickerContext | None:
    """
    Precalcula todos los indicadores necesarios para un ticker, alineados
    a su propio índice de fechas. Devuelve ``None`` si no hay histórico
    suficiente para calcular nada útil.

    Importante — cálculo "sin look-ahead" de F5/S2 semana a semana:
    tanto `sp500_alcista` como `sp500_bajista` solo miran el valor actual
    y el anterior (o una ventana de N anteriores) del Coppock, así que
    evaluarlos con `.expanding()` reproduce exactamente lo que habría
    visto el escáner en tiempo real cada semana, sin usar información
    futura. Se calculan una única vez para todo el histórico del S&P 500
    (compartido entre todos los tickers) fuera de esta función — ver
    `precompute_market_series` — y aquí solo se reindexan al calendario
    del ticker.
    """
    close = data["Close"].squeeze().astype(float)
    volume = data["Volume"].squeeze().astype(float)

    if len(close) < 60:
        return None

    wma30 = wma(close, 30)
    vpm5_series = vpm5(data, 52, 5)

    close_a, sp500_a = close.align(sp500_close, join="inner")
    rsc_activo_full = rsc_mansfield(close_a, sp500_a)
    rsc_activo = rsc_activo_full.reindex(close.index)

    dist_wma30 = ((close - wma30) / wma30) * 100.0
    momentum = (close - wma30) / wma30

    if sector_etf_close is not None:
        sector_a, sp500_b = sector_etf_close.align(sp500_close, join="inner")
        rsc_sector_full = rsc_mansfield(sector_a, sp500_b)
        rsc_sector = rsc_sector_full.reindex(close.index, method="ffill")
    else:
        rsc_sector = pd.Series(np.nan, index=close.index)

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
        coppock_bullish=pd.Series(dtype=bool),  # se rellena por el motor (ver market context)
        coppock_bearish=pd.Series(dtype=bool),
    )


def precompute_market_series(sp500_close: pd.Series, recent_lookback: int = 4) -> tuple[pd.Series, pd.Series]:
    """
    Calcula F5 (Sp500alcista) y S2 (Sp500bajista) semana a semana sobre
    TODO el histórico del S&P 500, sin look-ahead: en la semana `i` solo
    se usa `coppock.iloc[:i+1]`.

    Se hace una sola vez (no por ticker) porque es la misma serie de
    mercado para todos los tickers; el resultado se reindexa después al
    calendario de cada ticker en `build_ticker_context` / en el motor.
    """
    copk = coppock_curve(sp500_close)
    n = len(copk)

    bullish = np.zeros(n, dtype=bool)
    bearish = np.zeros(n, dtype=bool)

    for i in range(n):
        sub = copk.iloc[: i + 1]
        b, _ = sp500_alcista(sub, recent_lookback=recent_lookback)
        d, _ = sp500_bajista(sub)
        bullish[i] = b
        bearish[i] = d

    return (
        pd.Series(bullish, index=copk.index),
        pd.Series(bearish, index=copk.index),
    )


# ── Especificación de una condición ─────────────────────────────────────

@dataclass
class ConditionSpec:
    """
    Metadatos de una condición registrada: nombre corto (usado como clave
    en el config y como etiqueta de motivo de salida), función que la
    calcula, y parámetros por defecto.
    """
    name: str
    label: str
    func: Callable[..., pd.Series]
    default_params: dict = field(default_factory=dict)


# ── Condiciones de ENTRADA (F1-F5), combinadas con AND ─────────────────

def _f1_sector_fuerte(ctx: TickerContext, umbral: float = 0.10) -> pd.Series:
    """F1: RSC Mansfield del sector >= umbral."""
    return (ctx.rsc_sector >= umbral).fillna(False)


def _f2_volumen_positivo(ctx: TickerContext, umbral: float = 0.0) -> pd.Series:
    """F2: VPM5 > umbral (volumen por encima de su media histórica)."""
    return (ctx.vpm5 > umbral).fillna(False)


def _f3_rsc_activo_positivo(ctx: TickerContext, umbral: float = 0.0) -> pd.Series:
    """F3: RSC Mansfield del activo > umbral."""
    return (ctx.rsc_activo > umbral).fillna(False)


def _f4_distancia_wma30(ctx: TickerContext, max_distancia: float = 8.0) -> pd.Series:
    """F4: distancia % al WMA30 por debajo del máximo permitido (sin cota inferior)."""
    return (ctx.dist_wma30_pct < max_distancia).fillna(False)


def _f5_mercado_alcista(ctx: TickerContext, coppock_bullish_aligned: pd.Series | None = None) -> pd.Series:
    """F5: Coppock del S&P 500 alcista (condición de mercado, igual para todos los tickers)."""
    if coppock_bullish_aligned is None:
        return pd.Series(False, index=ctx.close.index)
    return coppock_bullish_aligned.reindex(ctx.close.index, method="ffill").fillna(False)


ENTRY_CONDITIONS: dict[str, ConditionSpec] = {
    "F1_sector_fuerte": ConditionSpec(
        name="F1_sector_fuerte",
        label="F1: RSC sector",
        func=_f1_sector_fuerte,
        default_params={"umbral": 0.10},
    ),
    "F2_volumen_positivo": ConditionSpec(
        name="F2_volumen_positivo",
        label="F2: VPM5",
        func=_f2_volumen_positivo,
        default_params={"umbral": 0.0},
    ),
    "F3_rsc_activo_positivo": ConditionSpec(
        name="F3_rsc_activo_positivo",
        label="F3: RSC activo",
        func=_f3_rsc_activo_positivo,
        default_params={"umbral": 0.0},
    ),
    "F4_distancia_wma30": ConditionSpec(
        name="F4_distancia_wma30",
        label="F4: Distancia WMA30",
        func=_f4_distancia_wma30,
        default_params={"max_distancia": 8.0},
    ),
    "F5_mercado_alcista": ConditionSpec(
        name="F5_mercado_alcista",
        label="F5: Coppock SP500 alcista",
        func=_f5_mercado_alcista,
        default_params={},  # coppock_bullish_aligned se inyecta desde el motor
    ),
}


# ── Condiciones de SALIDA (S1-S2), combinadas con OR ────────────────────

def _s1_rsc_debil(ctx: TickerContext, umbral: float = -0.5) -> pd.Series:
    """S1: RSC Mansfield del activo < umbral."""
    return (ctx.rsc_activo < umbral).fillna(False)


def _s2_mercado_bajista(ctx: TickerContext, coppock_bearish_aligned: pd.Series | None = None) -> pd.Series:
    """S2: Coppock del S&P 500 bajista (condición propia, no complemento de F5)."""
    if coppock_bearish_aligned is None:
        return pd.Series(False, index=ctx.close.index)
    return coppock_bearish_aligned.reindex(ctx.close.index, method="ffill").fillna(False)


EXIT_CONDITIONS: dict[str, ConditionSpec] = {
    "S1_rsc_debil": ConditionSpec(
        name="S1_rsc_debil",
        label="S1: RSC",
        func=_s1_rsc_debil,
        default_params={"umbral": -0.5},
    ),
    "S2_mercado_bajista": ConditionSpec(
        name="S2_mercado_bajista",
        label="S2: Coppock SP500 bajista",
        func=_s2_mercado_bajista,
        default_params={},
    ),
}


# ── Criterios de desempate (ranking de candidatos) ──────────────────────

def _rank_momentum(ctx: TickerContext, i: int) -> float:
    """Momentum relativo (MOM) — el criterio original de la estrategia."""
    val = ctx.momentum.iloc[i]
    return float(val) if pd.notna(val) else float("-inf")


def _rank_rsc_activo(ctx: TickerContext, i: int) -> float:
    """RSC Mansfield del activo — prioriza fuerza relativa en vez de distancia a WMA30."""
    val = ctx.rsc_activo.iloc[i]
    return float(val) if pd.notna(val) else float("-inf")


def _rank_vpm5(ctx: TickerContext, i: int) -> float:
    """VPM5 — prioriza el mayor pico relativo de volumen."""
    val = ctx.vpm5.iloc[i]
    return float(val) if pd.notna(val) else float("-inf")


RANKING_CRITERIA: dict[str, Callable[[TickerContext, int], float]] = {
    "momentum": _rank_momentum,
    "rsc_activo": _rank_rsc_activo,
    "vpm5": _rank_vpm5,
}
