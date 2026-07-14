"""
Tests de `PortfolioBacktestResult.metrics()` con datos de trades/equity
construidos a mano, para verificar las fórmulas con valores exactos
conocidos (no derivados de una simulación completa).
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.portfolio_engine import ClosedTrade, EquityPoint, PortfolioBacktestResult
from backtest.strategy_config import StrategyConfig


def _trade(ticker, retorno_pct, pnl_usd, semanas=4):
    return ClosedTrade(
        ticker=ticker, sector="Energy",
        fecha_entrada=pd.Timestamp("2024-01-01"), precio_entrada=100.0,
        n_acciones=100.0, capital_invertido=10_000.0,
        fecha_salida=pd.Timestamp("2024-02-01"), precio_salida=100.0 * (1 + retorno_pct / 100),
        motivo_salida="S1", semanas_en_pos=semanas,
        retorno_pct=retorno_pct, pnl_usd=pnl_usd,
    )


class TestMetricsSinOperaciones:

    def test_sin_trades_ni_equity_devuelve_capital_inicial(self):
        cfg = StrategyConfig(initial_capital=10_000.0)
        result = PortfolioBacktestResult(config=cfg)
        m = result.metrics()
        assert m["capital_final"] == 10_000.0
        assert m["rentabilidad_total_pct"] == 0.0
        assert m["n_operaciones_cerradas"] == 0
        assert m["win_rate_pct"] is None
        assert m["profit_factor"] is None


class TestMetricsConOperaciones:

    def test_capital_final_y_rentabilidad(self):
        cfg = StrategyConfig(initial_capital=10_000.0)
        equity = [
            EquityPoint(pd.Timestamp("2024-01-01"), 10_000.0, 10_000.0, 0),
            EquityPoint(pd.Timestamp("2024-01-08"), 12_500.0, 12_500.0, 0),
        ]
        trades = [_trade("T1", 25.0, 2500.0)]
        result = PortfolioBacktestResult(config=cfg, closed_trades=trades, equity_curve=equity)
        m = result.metrics()
        assert m["capital_final"] == 12_500.0
        assert m["rentabilidad_total_pct"] == pytest.approx(25.0)

    def test_max_drawdown_calculado_sobre_equity_curve(self):
        cfg = StrategyConfig(initial_capital=10_000.0)
        equity = [
            EquityPoint(pd.Timestamp("2024-01-01"), 10_000.0, 10_000.0, 0),
            EquityPoint(pd.Timestamp("2024-01-08"), 11_000.0, 11_000.0, 0),   # pico
            EquityPoint(pd.Timestamp("2024-01-15"), 9_000.0, 9_000.0, 0),    # -18.18% desde el pico
            EquityPoint(pd.Timestamp("2024-01-22"), 12_500.0, 12_500.0, 0),
        ]
        result = PortfolioBacktestResult(config=cfg, closed_trades=[], equity_curve=equity)
        m = result.metrics()
        assert m["max_drawdown_pct"] == pytest.approx(-18.18, abs=0.01)

    def test_win_rate_y_profit_factor(self):
        cfg = StrategyConfig(initial_capital=10_000.0)
        trades = [
            _trade("T1", 10.0, 1000.0),
            _trade("T2", -5.0, -500.0),
            _trade("T3", 20.0, 2000.0),
            _trade("T4", -2.0, -200.0),
        ]
        equity = [EquityPoint(pd.Timestamp("2024-01-01"), 10_000.0, 10_000.0, 0)]
        result = PortfolioBacktestResult(config=cfg, closed_trades=trades, equity_curve=equity)
        m = result.metrics()

        assert m["win_rate_pct"] == 50.0
        # suma ganancias % = 10+20=30, suma pérdidas % = 5+2=7 -> PF = 30/7
        assert m["profit_factor"] == pytest.approx(30 / 7, abs=0.01)
        assert m["retorno_medio_pct"] == pytest.approx((10 - 5 + 20 - 2) / 4, abs=0.01)
        assert m["mejor_operacion_pct"] == 20.0
        assert m["peor_operacion_pct"] == -5.0

    def test_profit_factor_none_sin_perdidas(self):
        cfg = StrategyConfig(initial_capital=10_000.0)
        trades = [_trade("T1", 5.0, 500.0), _trade("T2", 3.0, 300.0)]
        equity = [EquityPoint(pd.Timestamp("2024-01-01"), 10_000.0, 10_000.0, 0)]
        result = PortfolioBacktestResult(config=cfg, closed_trades=trades, equity_curve=equity)
        m = result.metrics()
        assert m["profit_factor"] is None

    def test_pct_semanas_invertido(self):
        cfg = StrategyConfig(initial_capital=10_000.0)
        equity = [
            EquityPoint(pd.Timestamp("2024-01-01"), 10_000.0, 10_000.0, 0),
            EquityPoint(pd.Timestamp("2024-01-08"), 10_500.0, 5_000.0, 1),
            EquityPoint(pd.Timestamp("2024-01-15"), 11_000.0, 5_500.0, 1),
            EquityPoint(pd.Timestamp("2024-01-22"), 11_000.0, 11_000.0, 0),
        ]
        result = PortfolioBacktestResult(config=cfg, closed_trades=[_trade("T1", 10, 500)], equity_curve=equity)
        m = result.metrics()
        assert m["pct_semanas_invertido"] == 50.0  # 2 de 4 semanas con posiciones abiertas

    def test_to_trades_dataframe_columnas(self):
        cfg = StrategyConfig(initial_capital=10_000.0)
        trades = [_trade("T1", 10.0, 1000.0)]
        result = PortfolioBacktestResult(config=cfg, closed_trades=trades)
        df = result.to_trades_dataframe()
        columnas_esperadas = {
            "Ticker", "Sector", "Fecha Entrada", "Precio Entrada", "Nº Acciones",
            "Capital Invertido", "Fecha Salida", "Precio Salida", "Motivo Salida",
            "Semanas en Pos.", "Retorno %", "P&L USD",
        }
        assert columnas_esperadas.issubset(df.columns)

    def test_to_trades_dataframe_vacio_sin_trades(self):
        cfg = StrategyConfig(initial_capital=10_000.0)
        result = PortfolioBacktestResult(config=cfg)
        assert result.to_trades_dataframe().empty

    def test_to_equity_dataframe(self):
        cfg = StrategyConfig(initial_capital=10_000.0)
        equity = [EquityPoint(pd.Timestamp("2024-01-01"), 10_000.0, 10_000.0, 0)]
        result = PortfolioBacktestResult(config=cfg, equity_curve=equity)
        df = result.to_equity_dataframe()
        assert not df.empty
        assert "Valor Cartera" in df.columns
