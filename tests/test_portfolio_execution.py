"""
Tests de las correcciones del motor de cartera (Fase 1 de docs/HOJA_DE_RUTA.md):

- B4: ejecución a la apertura de la semana siguiente ("next_open") vs. al
  cierre de la propia semana de la señal ("close").
- B6: costes por lado.
- B2: posición en un ticker que deja de tener datos se cierra al último
  precio (no queda "zombi" valorada a coste para siempre).
- B7/B8: ventana start/end, métricas en $ y benchmark.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.conditions import TickerContext, precompute_market_series
from backtest.portfolio_backtest import MOTIVO_SIN_DATOS, UniverseInfo, run_portfolio_backtest
from backtest.portfolio_engine import ClosedTrade, EquityPoint, PortfolioBacktestResult
from backtest.strategy_config import StrategyConfig
from tests.conftest import weekly_index

N = 60


@pytest.fixture
def mercado():
    idx = weekly_index(N)
    growth = np.concatenate([np.full(N - 20, 0.006), np.linspace(0.006, 0.02, 20)])
    close = pd.Series(100 * np.cumprod(1 + growth), index=idx)
    bullish, bearish = precompute_market_series(close)
    return close, bullish, bearish


def _ctx(ticker, close, open_=None, rsc=None, mom=0.05, n=None):
    n = len(close) if n is None else n
    idx = weekly_index(N)[:n]
    close = pd.Series(np.asarray(close, dtype=float)[:n], index=idx)
    return TickerContext(
        ticker=ticker,
        sector="Energy",
        close=close,
        volume=pd.Series(1000.0, index=idx),
        wma30=close,
        vpm5=pd.Series(1.0, index=idx),
        rsc_activo=pd.Series(np.full(n, 1.0) if rsc is None else np.asarray(rsc)[:n], index=idx),
        dist_wma30_pct=pd.Series(2.0, index=idx),
        momentum=pd.Series(mom, index=idx),
        rsc_sector=pd.Series(0.5, index=idx),
        coppock_bullish=pd.Series(dtype=bool),
        coppock_bearish=pd.Series(dtype=bool),
        open=None if open_ is None else pd.Series(np.asarray(open_, dtype=float)[:n], index=idx),
    )


def _first_bullish(bullish: pd.Series) -> int:
    return int(np.flatnonzero(bullish.to_numpy())[0])


class TestEjecucion:

    def test_next_open_compra_a_la_apertura_de_la_semana_siguiente(self, mercado):
        sp500, bull, bear = mercado
        i0 = _first_bullish(bull)
        close = np.linspace(50, 100, N)
        open_ = close - 1.0  # apertura distinguible del cierre
        cfg = StrategyConfig(max_positions=1, execution="next_open", cost_pct=0.0)
        res = run_portfolio_backtest(cfg, sp500, bull, bear, {"AAA": _ctx("AAA", close, open_)}, verbose=False)
        pos = res.open_positions_at_end[0]
        assert pos.fecha_entrada == sp500.index[i0 + 1]
        assert pos.precio_entrada == pytest.approx(open_[i0 + 1])

    def test_close_compra_al_cierre_de_la_semana_de_la_senal(self, mercado):
        sp500, bull, bear = mercado
        i0 = _first_bullish(bull)
        close = np.linspace(50, 100, N)
        cfg = StrategyConfig(max_positions=1, execution="close", cost_pct=0.0)
        res = run_portfolio_backtest(cfg, sp500, bull, bear, {"AAA": _ctx("AAA", close, close - 1)}, verbose=False)
        pos = res.open_positions_at_end[0]
        assert pos.fecha_entrada == sp500.index[i0]
        assert pos.precio_entrada == pytest.approx(close[i0])

    def test_next_open_vende_a_la_apertura_tras_la_senal_de_salida(self, mercado):
        sp500, bull, bear = mercado
        i0 = _first_bullish(bull)
        close = np.linspace(50, 100, N)
        rsc = np.full(N, 1.0)
        rsc[i0 + 5:] = -1.0  # S1 dispara en i0+5
        cfg = StrategyConfig(max_positions=1, execution="next_open", cost_pct=0.0)
        res = run_portfolio_backtest(cfg, sp500, bull, bear,
                                     {"AAA": _ctx("AAA", close, close - 1, rsc=rsc)}, verbose=False)
        t = res.closed_trades[0]
        assert t.fecha_salida == sp500.index[i0 + 6]
        assert t.precio_salida == pytest.approx(close[i0 + 6] - 1)

    def test_sin_apertura_usa_el_cierre(self, mercado):
        sp500, bull, bear = mercado
        i0 = _first_bullish(bull)
        close = np.linspace(50, 100, N)
        cfg = StrategyConfig(max_positions=1, execution="next_open", cost_pct=0.0)
        res = run_portfolio_backtest(cfg, sp500, bull, bear, {"AAA": _ctx("AAA", close)}, verbose=False)
        assert res.open_positions_at_end[0].precio_entrada == pytest.approx(close[i0 + 1])

    def test_execution_invalida_lanza_error(self):
        with pytest.raises(ValueError):
            StrategyConfig(execution="mañana")


class TestCostes:

    def test_ida_y_vuelta_a_precio_plano_pierde_los_costes(self, mercado):
        sp500, bull, bear = mercado
        i0 = _first_bullish(bull)
        close = np.full(N, 100.0)
        rsc = np.full(N, 1.0)
        rsc[i0 + 3:] = -1.0
        cfg = StrategyConfig(max_positions=1, execution="close", cost_pct=1.0, initial_capital=10_000.0)
        res = run_portfolio_backtest(cfg, sp500, bull, bear, {"AAA": _ctx("AAA", close, rsc=rsc)}, verbose=False)
        t = res.closed_trades[0]
        # compra: 100 de comisión; venta: 1 % de 9.900 = 99
        assert t.pnl_usd == pytest.approx(-199.0, abs=0.01)
        assert res.costes_totales == pytest.approx(199.0, abs=0.01)
        assert res.metrics()["capital_final"] == pytest.approx(9_801.0, abs=0.01)


class TestDelisting:

    def test_posicion_se_cierra_al_ultimo_precio_cuando_acaban_los_datos(self, mercado):
        sp500, bull, bear = mercado
        i0 = _first_bullish(bull)
        n_datos = i0 + 8
        close = np.linspace(50, 30, N)  # cae: el valor a coste ocultaría la pérdida
        cfg = StrategyConfig(max_positions=1, execution="close", cost_pct=0.0)
        res = run_portfolio_backtest(cfg, sp500, bull, bear,
                                     {"OLD": _ctx("OLD", close, n=n_datos)}, verbose=False)
        assert res.open_positions_at_end == []
        t = res.closed_trades[0]
        assert t.motivo_salida == MOTIVO_SIN_DATOS
        assert t.fecha_salida == sp500.index[n_datos - 1]
        assert t.precio_salida == pytest.approx(close[n_datos - 1])
        assert t.pnl_usd < 0
        assert res.equity_curve[-1].valor_cartera == pytest.approx(10_000.0 + t.pnl_usd)

    def test_hueco_liberado_por_delisting_se_reutiliza(self, mercado):
        sp500, bull, bear = mercado
        i0 = _first_bullish(bull)
        contexts = {
            "OLD": _ctx("OLD", np.linspace(50, 60, N), mom=0.09, n=i0 + 5),
            "NEW": _ctx("NEW", np.linspace(50, 60, N), mom=0.01),
        }
        cfg = StrategyConfig(max_positions=1, execution="close", cost_pct=0.0)
        res = run_portfolio_backtest(cfg, sp500, bull, bear, contexts, verbose=False)
        assert [p.ticker for p in res.open_positions_at_end] == ["NEW"]


class TestVentanaYMetricas:

    def test_start_end_acotan_la_curva(self, mercado):
        sp500, bull, bear = mercado
        start, end = sp500.index[45], sp500.index[55]
        cfg = StrategyConfig(max_positions=1, cost_pct=0.0)
        res = run_portfolio_backtest(cfg, sp500, bull, bear, {"AAA": _ctx("AAA", np.linspace(50, 100, N))},
                                     verbose=False, start=start, end=end)
        fechas = [p.fecha for p in res.equity_curve]
        assert fechas[0] == start and fechas[-1] == end
        assert all(t.fecha_entrada >= start for t in res.closed_trades)

    def test_benchmark_en_las_mismas_fechas(self, mercado):
        sp500, bull, bear = mercado
        info = UniverseInfo(mode="current", benchmark_close=sp500)
        cfg = StrategyConfig(max_positions=1, cost_pct=0.0)
        res = run_portfolio_backtest(cfg, sp500, bull, bear, {"AAA": _ctx("AAA", np.linspace(50, 100, N))},
                                     universe_info=info, verbose=False, start=sp500.index[40])
        m = res.metrics()
        esperado = (sp500.iloc[-1] / sp500.iloc[40] - 1) * 100
        assert m["benchmark_rentabilidad_pct"] == pytest.approx(esperado, abs=0.01)
        assert m["exceso_cagr_pct"] == pytest.approx(m["cagr_pct"] - m["benchmark_cagr_pct"], abs=0.02)


def _trade(pnl, capital, ret):
    f = pd.Timestamp("2024-01-05")
    return ClosedTrade("X", "Energy", f, 1.0, 1.0, capital, f, 1.0, "S1", 1, ret, pnl)


class TestMetricasEnDolares:

    def test_profit_factor_pondera_por_dolares(self):
        # +50 % con 100 $ (= +50 $) y -10 % con 1.000 $ (= -100 $):
        # en suma de % daría PF 5, en dólares es 0,5.
        cfg = StrategyConfig(initial_capital=1_000.0)
        f0, f1 = pd.Timestamp("2024-01-05"), pd.Timestamp("2025-01-03")
        res = PortfolioBacktestResult(
            config=cfg,
            closed_trades=[_trade(50.0, 100.0, 50.0), _trade(-100.0, 1_000.0, -10.0)],
            equity_curve=[EquityPoint(f0, 1_000.0, 1_000.0, 0), EquityPoint(f1, 950.0, 950.0, 0)],
        )
        m = res.metrics()
        assert m["profit_factor"] == pytest.approx(0.5)
        assert m["cagr_pct"] == pytest.approx(-5.0, abs=0.1)  # 1 año real, no nº de semanas / 52

    def test_concentracion_top5(self):
        cfg = StrategyConfig(initial_capital=1_000.0)
        trades = [_trade(p, 100.0, p) for p in (100, 50, 30, 20, 10, -5, -5)]
        res = PortfolioBacktestResult(config=cfg, closed_trades=trades)
        assert res.metrics()["pct_pnl_top5"] == pytest.approx(100 * 210 / 200, abs=0.1)
