"""
Fixtures compartidas para los tests del paquete `weinstein`.

Todas las series de precios/volumen son sintéticas y construidas para que
el resultado de cada indicador sea predecible (signo o valor conocido),
sin depender de red ni de datos reales de mercado.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def weekly_index(n: int, start: str = "2020-01-06") -> pd.DatetimeIndex:
    """Índice semanal (domingos) de `n` periodos, igual al que usa yfinance con interval='1wk'."""
    return pd.date_range(start, periods=n, freq="W")


# ── Series de precio ──────────────────────────────────────────────────

@pytest.fixture
def flat_price() -> pd.Series:
    """Precio constante: útil como caso degenerado (WMA=precio, RSC=0, etc.)."""
    idx = weekly_index(60)
    return pd.Series(100.0, index=idx)


@pytest.fixture
def strong_uptrend_price() -> pd.Series:
    """
    Serie de precio con crecimiento que se ACELERA en las últimas semanas.
    Necesario para que el Coppock no solo sea positivo sino además CRECIENTE
    (crecimiento constante da Coppock plano, no "continuación alcista").
    """
    idx = weekly_index(80)
    growth = np.concatenate([np.full(60, 0.005), np.linspace(0.005, 0.02, 20)])
    return pd.Series(100 * np.cumprod(1 + growth), index=idx)


@pytest.fixture
def mild_uptrend_price() -> pd.Series:
    """Benchmark de referencia con subida moderada y constante."""
    idx = weekly_index(90)
    return pd.Series(np.linspace(100, 110, 90), index=idx)


# ── Series de volumen ──────────────────────────────────────────────────

@pytest.fixture
def volume_with_recent_spike() -> pd.Series:
    """
    Volumen con ruido pequeño y estable, seguido de un pico sostenido en
    las últimas 5 semanas -> VPM5 final claramente positivo.
    """
    idx = weekly_index(60)
    rng = np.random.default_rng(42)
    base = 1000 + rng.normal(0, 20, 55).round()
    vals = np.concatenate([base, [5000.0] * 5])
    return pd.Series(vals, index=idx)


@pytest.fixture
def volume_flat() -> pd.Series:
    """Volumen constante: desviación 0 -> VPM indefinido/NaN por construcción."""
    idx = weekly_index(60)
    return pd.Series(1000.0, index=idx)


# ── OHLCV sintético completo (para tests de scanner) ───────────────────

def make_ohlcv(close: np.ndarray | pd.Series, volume: np.ndarray | pd.Series, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Construye un DataFrame OHLCV mínimo (Open=High=Low=Close) para tests de scanner."""
    close = np.asarray(close, dtype=float)
    volume = np.asarray(volume, dtype=float)
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": volume},
        index=index,
    )
