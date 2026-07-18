"""
Tests de integración del universo HISTÓRICO en `backtest/portfolio_backtest.py`.

Cubren:
  - `prepare_universe(universe="historical")` construye correctamente el
    `UniverseInfo` (modo, calendario de membresía, tickers sin precio),
    mockeando descarga (`get_cached_weekly`), constituyentes actuales
    (`load_sp500_tickers`) y el calendario histórico
    (`build_membership_calendar_cached`) — sin red.
  - `run_portfolio_backtest` respeta el filtro de membresía histórica al
    ABRIR posiciones nuevas, pero no afecta a la gestión de posiciones ya
    abiertas (ver docstring de `portfolio_backtest.py`).
  - `universe="current"` (comportamiento por defecto) no aplica ningún
    filtro de membresía (compatibilidad hacia atrás).
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from yfinance import ticker

from tests.conftest import weekly_index
from backtest.conditions import TickerContext, precompute_market_series
from backtest import portfolio_backtest as pbt
from backtest.strategy_config import StrategyConfig

N = 60


def _make_ctx(ticker, close_vals, mom_vals, sector="Energy"):
    idx = weekly_index(N)
    close = pd.Series(close_vals, index=idx)
    n = len(close)
    return TickerContext(
        ticker=ticker,
        sector=sector,
        close=close,
        volume=pd.Series(1000.0, index=idx),
        wma30=close.rolling(5).mean(),
        vpm5=pd.Series(1.0, index=idx),
        rsc_activo=pd.Series(1.0, index=idx),
        dist_wma30_pct=pd.Series(2.0, index=idx),
        momentum=pd.Series(mom_vals, index=idx),
        rsc_sector=pd.Series(0.5, index=idx),
        coppock_bullish=pd.Series(dtype=bool),
        coppock_bearish=pd.Series(dtype=bool),
    )


@pytest.fixture
def sp500_alcista_estable():
    idx = weekly_index(N)
    growth = np.concatenate([np.full(N - 20, 0.006), np.linspace(0.006, 0.02, 20)])
    close = pd.Series(100 * np.cumprod(1 + growth), index=idx)
    bullish, bearish = precompute_market_series(close)
    return close, bullish, bearish


def _first_true_idx(mask: pd.Series) -> int:
    first_true = mask[mask].index[0]
    return int(mask.index.get_loc(first_true))


class TestFiltroDeMembresiaHistoricaEnEntradas:
    """
    Ticker 'GHOST' solo pertenece al índice histórico ANTES de f5_start +
    5 (según el calendario simulado); después de esa fecha ya no está en
    el índice. Con F5 activándose justo en f5_start, si el filtro de
    membresía funciona, GHOST solo debería poder ENTRAR si aún estaba en
    el índice esa semana.
    """

    def test_no_permite_abrir_en_ticker_fuera_del_indice_esa_semana(self, sp500_alcista_estable):
        sp500_close, bullish, bearish = sp500_alcista_estable
        f5_start = _first_true_idx(bullish)
        idx = weekly_index(N)

        ctx = _make_ctx("GHOST", np.linspace(50, 100, N), np.full(N, 0.05))

        # Calendario: GHOST NUNCA pertenece al índice (se excluyó siempre).
        calendar = {fecha: set() for fecha in idx}
        info = pbt.UniverseInfo(mode="historical", membership_calendar=calendar)

        config = StrategyConfig(name="t1", max_positions=1, initial_capital=10_000.0)
        result = pbt.run_portfolio_backtest(
            config, sp500_close, bullish, bearish, {"GHOST": ctx},
            universe_info=info, verbose=False,
        )

        assert result.closed_trades == []
        assert result.open_positions_at_end == []

    def test_permite_abrir_en_ticker_que_si_pertenece_esa_semana(self, sp500_alcista_estable):
        sp500_close, bullish, bearish = sp500_alcista_estable
        idx = weekly_index(N)

        ctx = _make_ctx("AAA", np.linspace(50, 100, N), np.full(N, 0.05))

        # Calendario: AAA pertenece al índice TODAS las semanas.
        calendar = {fecha: {"AAA"} for fecha in idx}
        info = pbt.UniverseInfo(mode="historical", membership_calendar=calendar)

        config = StrategyConfig(name="t2", max_positions=1, initial_capital=10_000.0)
        result = pbt.run_portfolio_backtest(
            config, sp500_close, bullish, bearish, {"AAA": ctx},
            universe_info=info, verbose=False,
        )

        assert len(result.open_positions_at_end) == 1 or len(result.closed_trades) >= 1

    def test_posicion_abierta_se_mantiene_aunque_ticker_salga_del_indice(self, sp500_alcista_estable):
        """
        AAA pertenece al índice solo en las primeras semanas (para poder
        ENTRAR), y luego se "excluye" del calendario a partir de cierto
        punto. La posición, si llegó a abrirse, NO debe cerrarse solo por
        eso (el filtro de membresía únicamente bloquea nuevas entradas).
        """
        sp500_close, bullish, bearish = sp500_alcista_estable
        f5_start = _first_true_idx(bullish)
        idx = weekly_index(N)

        ctx = _make_ctx("AAA", np.linspace(50, 100, N), np.full(N, 0.05))

        corte = f5_start + 3
        calendar = {
            fecha: ({"AAA"} if i <= corte else set())
            for i, fecha in enumerate(idx)
        }
        info = pbt.UniverseInfo(mode="historical", membership_calendar=calendar)

        config = StrategyConfig(name="t3", max_positions=1, initial_capital=10_000.0)
        result = pbt.run_portfolio_backtest(
            config, sp500_close, bullish, bearish, {"AAA": ctx},
            universe_info=info, verbose=False,
        )

        # Si entró, la posición se mantiene abierta o se cierra por S1/S2
        # (ninguna activa aquí porque rsc_activo=1.0 siempre y no
        # activamos S2), nunca por "ya no está en el índice".
        total_trades = len(result.closed_trades) + len(result.open_positions_at_end)
        if total_trades > 0:
            # No hay condiciones de salida activas por defecto en config
            # sin exit_conditions explícitas -> S1/S2 activas por defecto
            # pero no disparadas por los datos sintéticos, así que debe
            # seguir abierta al final.
            assert len(result.open_positions_at_end) == 1
            assert result.closed_trades == []


class TestUniverseCurrentSinFiltro:

    def test_universe_info_none_no_aplica_filtro(self, sp500_alcista_estable):
        sp500_close, bullish, bearish = sp500_alcista_estable
        ctx = _make_ctx("AAA", np.linspace(50, 100, N), np.full(N, 0.05))

        config = StrategyConfig(name="t4", max_positions=1, initial_capital=10_000.0)
        result = pbt.run_portfolio_backtest(
            config, sp500_close, bullish, bearish, {"AAA": ctx},
            universe_info=None, verbose=False,
        )
        total_trades = len(result.closed_trades) + len(result.open_positions_at_end)
        assert total_trades >= 1

    def test_universe_info_current_mode_no_aplica_filtro(self, sp500_alcista_estable):
        sp500_close, bullish, bearish = sp500_alcista_estable
        ctx = _make_ctx("AAA", np.linspace(50, 100, N), np.full(N, 0.05))
        info = pbt.UniverseInfo(mode="current", membership_calendar=None)

        config = StrategyConfig(name="t5", max_positions=1, initial_capital=10_000.0)
        result = pbt.run_portfolio_backtest(
            config, sp500_close, bullish, bearish, {"AAA": ctx},
            universe_info=info, verbose=False,
        )
        total_trades = len(result.closed_trades) + len(result.open_positions_at_end)
        assert total_trades >= 1


class TestPrepareUniverseHistorico:
    """Mockea todo el I/O (descarga, constituyentes actuales, calendario) para
    verificar el ensamblaje de `UniverseInfo` sin red."""

    def _fake_ohlcv(self, base=100.0):
        idx = weekly_index(120)
        close = pd.Series(np.linspace(base, base * 1.5, 120), index=idx)
        return pd.DataFrame({
            "Open": close, "High": close, "Low": close, "Close": close,
            "Volume": 1000.0,
        }, index=idx)

    def test_universe_invalido_lanza_error(self):
        with pytest.raises(ValueError, match="universe"):
            pbt.prepare_universe(universe="algo_raro")

    def test_modo_historico_construye_membership_calendar(self):
        sp500_df = self._fake_ohlcv(base=4000.0)
        current_constituents = pd.DataFrame({
            "Symbol": ["AAA", "BBB"],
            "Name": ["Alpha Co", "Beta Co"],
            "Sector": ["Energy", "Technology"],
        })
        fake_calendar = {fecha: {"AAA"} for fecha in sp500_df.index}

        with patch("backtest.portfolio_backtest.get_cached_weekly", return_value=self._fake_ohlcv()), \
             patch("backtest.portfolio_backtest.load_sp500_tickers", return_value=current_constituents), \
             patch("backtest.portfolio_backtest.build_membership_calendar_cached", return_value=fake_calendar):

            sp500_close, bullish, bearish, contexts, info = pbt.prepare_universe(
                period="5y", universe="historical", max_tickers=None,
            )

        assert info.mode == "historical"
        assert info.membership_calendar is not None

    def test_tickers_explicitos_ignoran_modo_historico(self):
        current_constituents = pd.DataFrame({"Symbol": ["AAA"], "Name": ["A"], "Sector": ["Energy"]})
        with patch("backtest.portfolio_backtest.get_cached_weekly", return_value=self._fake_ohlcv()), \
             patch("backtest.portfolio_backtest.load_sp500_tickers", return_value=current_constituents):
            sp500_close, bullish, bearish, contexts, info = pbt.prepare_universe(
                period="5y", universe="historical", tickers=["AAA"],
            )
        assert info.mode == "current"
        assert info.membership_calendar is None

    def test_modo_current_no_construye_calendario(self):
        current_constituents = pd.DataFrame({"Symbol": ["AAA"], "Name": ["A"], "Sector": ["Energy"]})
        with patch("backtest.portfolio_backtest.get_cached_weekly", return_value=self._fake_ohlcv()), \
             patch("backtest.portfolio_backtest.load_sp500_tickers", return_value=current_constituents), \
             patch("backtest.portfolio_backtest.build_membership_calendar_cached") as mock_cal:
            sp500_close, bullish, bearish, contexts, info = pbt.prepare_universe(
                period="5y", universe="current",
            )
        mock_cal.assert_not_called()
        assert info.mode == "current"
        assert info.membership_calendar is None

    def test_tickers_sin_precio_se_reportan_en_modo_historico(self):
        current_constituents = pd.DataFrame({
            "Symbol": ["AAA", "GHOST"], "Name": ["A", "G"], "Sector": ["Energy", "Energy"],
        })
        fake_calendar = {}

        def fake_download(ticker, period, refresh=False, is_current_constituent=True):
            if ticker == "GHOST":
                return None
            return self._fake_ohlcv()

        with patch("backtest.portfolio_backtest.get_cached_weekly", side_effect=fake_download), \
             patch("backtest.portfolio_backtest.load_sp500_tickers", return_value=current_constituents), \
             patch("backtest.portfolio_backtest.build_membership_calendar_cached", return_value=fake_calendar), \
             patch("backtest.portfolio_backtest.universe_union", return_value={"AAA", "GHOST"}):
            sp500_close, bullish, bearish, contexts, info = pbt.prepare_universe(
                period="5y", universe="historical",
            )

        assert "GHOST" in info.tickers_historicos_sin_precio
        assert "AAA" not in info.tickers_historicos_sin_precio
