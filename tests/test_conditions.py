"""
Tests de `backtest/conditions.py`.

Cubre:
  - `precompute_market_series` (F5/S2 semana a semana, sin look-ahead).
  - Las funciones de condición individuales (F1-F5, S1-S2) sobre un
    `TickerContext` construido a mano, sin red.
  - Los criterios de ranking (`RANKING_CRITERIA`).

Se evita `build_ticker_context` con red real; se construye `TickerContext`
directamente con series sintéticas, igual que ya hace el resto de la
suite del proyecto (ver tests/test_scanner_entry.py).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.conftest import weekly_index
from backtest.conditions import (
    ENTRY_CONDITIONS,
    EXIT_CONDITIONS,
    RANKING_CRITERIA,
    TickerContext,
    precompute_market_series,
)

N = 60


def _ctx(
    close_vals=None,
    rsc_activo_vals=None,
    rsc_sector_vals=None,
    vpm5_vals=None,
    dist_vals=None,
    mom_vals=None,
) -> TickerContext:
    idx = weekly_index(N)
    close = pd.Series(close_vals if close_vals is not None else np.linspace(50, 100, N), index=idx)
    return TickerContext(
        ticker="TST",
        sector="Energy",
        close=close,
        volume=pd.Series(1000.0, index=idx),
        wma30=close.rolling(5).mean(),
        vpm5=pd.Series(vpm5_vals if vpm5_vals is not None else np.full(N, 1.0), index=idx),
        rsc_activo=pd.Series(rsc_activo_vals if rsc_activo_vals is not None else np.full(N, 1.0), index=idx),
        dist_wma30_pct=pd.Series(dist_vals if dist_vals is not None else np.full(N, 2.0), index=idx),
        momentum=pd.Series(mom_vals if mom_vals is not None else np.full(N, 0.05), index=idx),
        rsc_sector=pd.Series(rsc_sector_vals if rsc_sector_vals is not None else np.full(N, 0.5), index=idx),
        coppock_bullish=pd.Series(dtype=bool),
        coppock_bearish=pd.Series(dtype=bool),
    )


class TestPrecomputeMarketSeries:

    def test_sin_look_ahead_bullish_en_i_no_depende_de_futuro(self):
        """
        La señal F5 en la semana `i` debe coincidir exactamente si se
        calcula sobre la serie truncada en `i` o sobre la serie completa
        (recorte posterior no debe influir hacia atrás).
        """
        idx = weekly_index(N)
        growth = np.concatenate([np.full(N - 15, 0.005), np.linspace(0.005, 0.02, 15)])
        sp500_close = pd.Series(100 * np.cumprod(1 + growth), index=idx)

        bullish_full, bearish_full = precompute_market_series(sp500_close)

        i = 40
        bullish_trunc, bearish_trunc = precompute_market_series(sp500_close.iloc[: i + 1])

        assert bool(bullish_full.iloc[i]) == bool(bullish_trunc.iloc[-1])
        assert bool(bearish_full.iloc[i]) == bool(bearish_trunc.iloc[-1])

    def test_devuelve_series_del_mismo_largo_que_coppock(self):
        idx = weekly_index(N)
        sp500_close = pd.Series(np.linspace(100, 150, N), index=idx)
        bullish, bearish = precompute_market_series(sp500_close)
        assert len(bullish) == len(bearish)
        assert isinstance(bullish.iloc[0], (bool, np.bool_))


class TestEntryConditions:

    def test_f1_sector_fuerte_umbral(self):
        ctx = _ctx(rsc_sector_vals=np.concatenate([np.full(30, 0.05), np.full(30, 0.20)]))
        mask = ENTRY_CONDITIONS["F1_sector_fuerte"].func(ctx, umbral=0.10)
        assert not mask.iloc[:30].any()
        assert mask.iloc[30:].all()

    def test_f1_nan_es_false(self):
        ctx = _ctx(rsc_sector_vals=np.full(N, np.nan))
        mask = ENTRY_CONDITIONS["F1_sector_fuerte"].func(ctx, umbral=0.10)
        assert not mask.any()

    def test_f2_volumen_positivo(self):
        ctx = _ctx(vpm5_vals=np.concatenate([np.full(30, -1.0), np.full(30, 1.0)]))
        mask = ENTRY_CONDITIONS["F2_volumen_positivo"].func(ctx, umbral=0.0)
        assert not mask.iloc[:30].any()
        assert mask.iloc[30:].all()

    def test_f3_rsc_activo_positivo(self):
        ctx = _ctx(rsc_activo_vals=np.concatenate([np.full(30, -0.5), np.full(30, 0.5)]))
        mask = ENTRY_CONDITIONS["F3_rsc_activo_positivo"].func(ctx, umbral=0.0)
        assert not mask.iloc[:30].any()
        assert mask.iloc[30:].all()

    def test_f4_distancia_wma30(self):
        ctx = _ctx(dist_vals=np.concatenate([np.full(30, 10.0), np.full(30, 3.0)]))
        mask = ENTRY_CONDITIONS["F4_distancia_wma30"].func(ctx, max_distancia=8.0)
        assert not mask.iloc[:30].any()
        assert mask.iloc[30:].all()

    def test_f4_sin_cota_inferior(self):
        """Distancia muy negativa (precio muy por debajo de WMA30) debe seguir pasando F4."""
        ctx = _ctx(dist_vals=np.full(N, -50.0))
        mask = ENTRY_CONDITIONS["F4_distancia_wma30"].func(ctx, max_distancia=8.0)
        assert mask.all()

    def test_f5_usa_serie_de_mercado_inyectada(self):
        idx = weekly_index(N)
        ctx = _ctx()
        coppock_bullish = pd.Series([i >= 40 for i in range(N)], index=idx)
        mask = ENTRY_CONDITIONS["F5_mercado_alcista"].func(ctx, coppock_bullish_aligned=coppock_bullish)
        assert not mask.iloc[:40].any()
        assert mask.iloc[40:].all()

    def test_f5_sin_serie_inyectada_es_siempre_false(self):
        ctx = _ctx()
        mask = ENTRY_CONDITIONS["F5_mercado_alcista"].func(ctx, coppock_bullish_aligned=None)
        assert not mask.any()


class TestExitConditions:

    def test_s1_rsc_debil(self):
        ctx = _ctx(rsc_activo_vals=np.concatenate([np.full(30, 1.0), np.full(30, -1.0)]))
        mask = EXIT_CONDITIONS["S1_rsc_debil"].func(ctx, umbral=-0.5)
        assert not mask.iloc[:30].any()
        assert mask.iloc[30:].all()

    def test_s2_usa_serie_de_mercado_inyectada(self):
        idx = weekly_index(N)
        ctx = _ctx()
        coppock_bearish = pd.Series([i >= 40 for i in range(N)], index=idx)
        mask = EXIT_CONDITIONS["S2_mercado_bajista"].func(ctx, coppock_bearish_aligned=coppock_bearish)
        assert not mask.iloc[:40].any()
        assert mask.iloc[40:].all()


class TestRankingCriteria:

    def test_momentum_devuelve_valor_de_la_semana(self):
        ctx = _ctx(mom_vals=np.linspace(0.0, 0.5, N))
        score = RANKING_CRITERIA["momentum"](ctx, 10)
        assert score == pytest.approx(ctx.momentum.iloc[10])

    def test_momentum_nan_devuelve_menos_infinito(self):
        ctx = _ctx(mom_vals=np.full(N, np.nan))
        score = RANKING_CRITERIA["momentum"](ctx, 5)
        assert score == float("-inf")

    def test_rsc_activo_y_vpm5_registrados(self):
        assert "rsc_activo" in RANKING_CRITERIA
        assert "vpm5" in RANKING_CRITERIA
        ctx = _ctx(rsc_activo_vals=np.full(N, 2.5), vpm5_vals=np.full(N, 3.0))
        assert RANKING_CRITERIA["rsc_activo"](ctx, 0) == pytest.approx(2.5)
        assert RANKING_CRITERIA["vpm5"](ctx, 0) == pytest.approx(3.0)
