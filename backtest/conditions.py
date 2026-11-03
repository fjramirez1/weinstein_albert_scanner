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

import pandas as pd

from weinstein.config import MAX_DISTANCIA_WMA30, RSC_EXIT_THRESHOLD, SECTOR_RSC_MIN
from weinstein.signals import (  # noqa: F401  (re-exportados: API histórica del backtest)
    MIN_CONTEXT_BARS,
    TickerContext,
    build_ticker_context,
    f1_sector_fuerte,
    f2_volumen_positivo,
    f3_rsc_activo_positivo,
    f4_distancia_wma30,
    market_state_series,
    s1_rsc_debil,
)

# Nombre antiguo, conservado para no romper llamadas existentes.
precompute_market_series = market_state_series


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

# Envoltorios finos: la regla en sí vive en weinstein/signals.py y es la
# misma que aplica el escáner de producción.

def _f1_sector_fuerte(ctx: TickerContext, umbral: float = SECTOR_RSC_MIN) -> pd.Series:
    """F1: RSC Mansfield del sector >= umbral."""
    return f1_sector_fuerte(ctx.rsc_sector, umbral)


def _f2_volumen_positivo(ctx: TickerContext, umbral: float = 0.0) -> pd.Series:
    """F2: VPM5 > umbral (volumen por encima de su media histórica)."""
    return f2_volumen_positivo(ctx.vpm5, umbral)


def _f3_rsc_activo_positivo(ctx: TickerContext, umbral: float = 0.0) -> pd.Series:
    """F3: RSC Mansfield del activo > umbral."""
    return f3_rsc_activo_positivo(ctx.rsc_activo, umbral)


def _f4_distancia_wma30(ctx: TickerContext, max_distancia: float = MAX_DISTANCIA_WMA30) -> pd.Series:
    """F4: distancia % al WMA30 por debajo del máximo permitido (sin cota inferior)."""
    return f4_distancia_wma30(ctx.dist_wma30_pct, max_distancia)


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
        default_params={"umbral": SECTOR_RSC_MIN},
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
        default_params={"max_distancia": MAX_DISTANCIA_WMA30},
    ),
    "F5_mercado_alcista": ConditionSpec(
        name="F5_mercado_alcista",
        label="F5: Coppock SP500 alcista",
        func=_f5_mercado_alcista,
        default_params={},  # coppock_bullish_aligned se inyecta desde el motor
    ),
}


# ── Condiciones de SALIDA (S1-S2), combinadas con OR ────────────────────

def _s1_rsc_debil(ctx: TickerContext, umbral: float = RSC_EXIT_THRESHOLD) -> pd.Series:
    """S1: RSC Mansfield del activo < umbral."""
    return s1_rsc_debil(ctx.rsc_activo, umbral)


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
        default_params={"umbral": RSC_EXIT_THRESHOLD},
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
