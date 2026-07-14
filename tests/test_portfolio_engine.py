"""
Tests de `backtest/portfolio_engine.py` y `backtest/portfolio_backtest.py`.

Se construyen `TickerContext` sintéticos a mano (sin red, sin
`build_ticker_context`) para poder controlar exactamente en qué semana
cada ticker cumple F1-F5/S1-S2, y así verificar las reglas de negocio de
la cartera acordadas explícitamente con el usuario:

  1. Ranking por criterio de desempate (por defecto MOM) cuando hay más
     candidatos que huecos libres.
  2. Una salida y una entrada pueden ocurrir en la MISMA semana (el
     hueco liberado se puede ocupar de inmediato).
  3. Tamaño de posición = valor de cartera de referencia / max_positions
     en el momento de la entrada; ese valor de referencia solo cambia al
     cerrar posiciones (P&L realizado), nunca por fluctuación de
     mercado no realizada de posiciones que siguen abiertas.
  4. Nunca se supera max_positions ni se invierte más que el efectivo
     disponible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.conftest import weekly_index
from backtest.conditions import TickerContext, precompute_market_series
from backtest.portfolio_backtest import run_portfolio_backtest
from backtest.strategy_config import StrategyConfig

N = 60


def _first_true_idx(mask: pd.Series) -> int:
    first_true = mask[mask].index[0]
    return int(mask.index.get_loc(first_true))


@pytest.fixture
def sp500_alcista_estable():
    """
    S&P 500 con Coppock alcista estable desde un punto conocido en
    adelante (crecimiento que acelera al final, igual patrón que
    `strong_uptrend_price` en tests/conftest.py).
    """
    idx = weekly_index(N)
    growth = np.concatenate([np.full(N - 20, 0.006), np.linspace(0.006, 0.02, 20)])
    close = pd.Series(100 * np.cumprod(1 + growth), index=idx)
    bullish, bearish = precompute_market_series(close)
    return close, bullish, bearish


def _make_ctx(ticker, close_vals, mom_vals, rsc_activo_vals=None, sector="Energy"):
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
        rsc_activo=pd.Series(rsc_activo_vals if rsc_activo_vals is not None else np.full(n, 1.0), index=idx),
        dist_wma30_pct=pd.Series(2.0, index=idx),
        momentum=pd.Series(mom_vals, index=idx),
        rsc_sector=pd.Series(0.5, index=idx),
        coppock_bullish=pd.Series(dtype=bool),
        coppock_bearish=pd.Series(dtype=bool),
    )


class TestSucesionEntradaSalidaMismaSemana:
    """
    Escenario: con max_positions=1, un ticker A entra primero (mayor
    momentum), luego sale por S1, y en la MISMA semana un ticker B con
    menor momentum ocupa el hueco liberado.
    """

    def test_ticker_con_mayor_momentum_entra_primero(self, sp500_alcista_estable):
        sp500_close, bullish, bearish = sp500_alcista_estable
        f5_start = _first_true_idx(bullish)

        close_a = np.linspace(50, 100, N)
        rsc_a = np.full(N, 1.0)
        salida_idx = f5_start + 10
        rsc_a[salida_idx:] = -1.0  # dispara S1 en salida_idx

        ctx_a = _make_ctx("AAA", close_a, np.full(N, 0.05), rsc_activo_vals=rsc_a)
        ctx_b = _make_ctx("BBB", np.linspace(60, 90, N), np.full(N, 0.02))  # menor momentum

        config = StrategyConfig(name="t1", max_positions=1, initial_capital=10_000.0)
        result = run_portfolio_backtest(
            config, sp500_close, bullish, bearish,
            {"AAA": ctx_a, "BBB": ctx_b}, verbose=False,
        )

        df = result.to_trades_dataframe()
        assert len(df) == 1
        assert df.iloc[0]["Ticker"] == "AAA"

    def test_salida_y_entrada_en_la_misma_semana(self, sp500_alcista_estable):
        sp500_close, bullish, bearish = sp500_alcista_estable
        f5_start = _first_true_idx(bullish)

        close_a = np.linspace(50, 100, N)
        rsc_a = np.full(N, 1.0)
        salida_idx = f5_start + 10
        rsc_a[salida_idx:] = -1.0

        ctx_a = _make_ctx("AAA", close_a, np.full(N, 0.05), rsc_activo_vals=rsc_a)
        ctx_b = _make_ctx("BBB", np.linspace(60, 90, N), np.full(N, 0.02))

        config = StrategyConfig(name="t2", max_positions=1, initial_capital=10_000.0)
        result = run_portfolio_backtest(
            config, sp500_close, bullish, bearish,
            {"AAA": ctx_a, "BBB": ctx_b}, verbose=False,
        )

        df = result.to_trades_dataframe()
        fecha_salida_a = df.iloc[0]["Fecha Salida"]

        assert len(result.open_positions_at_end) == 1
        pos_b = result.open_positions_at_end[0]
        assert pos_b.ticker == "BBB"
        assert pos_b.fecha_entrada == fecha_salida_a, (
            "BBB debería entrar la MISMA semana en que AAA sale (regla acordada), "
            f"pero entró en {pos_b.fecha_entrada} y AAA salió en {fecha_salida_a}"
        )

    def test_tamano_de_bbb_usa_valor_de_cartera_actualizado_tras_cierre_de_aaa(self, sp500_alcista_estable):
        sp500_close, bullish, bearish = sp500_alcista_estable
        f5_start = _first_true_idx(bullish)

        close_a = np.linspace(50, 100, N)
        rsc_a = np.full(N, 1.0)
        salida_idx = f5_start + 10
        rsc_a[salida_idx:] = -1.0

        ctx_a = _make_ctx("AAA", close_a, np.full(N, 0.05), rsc_activo_vals=rsc_a)
        ctx_b = _make_ctx("BBB", np.linspace(60, 90, N), np.full(N, 0.02))

        config = StrategyConfig(name="t3", max_positions=1, initial_capital=10_000.0)
        result = run_portfolio_backtest(
            config, sp500_close, bullish, bearish,
            {"AAA": ctx_a, "BBB": ctx_b}, verbose=False,
        )

        df = result.to_trades_dataframe()
        pnl_aaa = df.iloc[0]["P&L USD"]
        pos_b = result.open_positions_at_end[0]

        valor_esperado = 10_000.0 + pnl_aaa
        assert pos_b.capital_invertido == pytest.approx(valor_esperado, abs=0.01)


class TestRepartoEntreMultiplesPosiciones:

    def test_solo_entran_los_n_mejores_por_momentum(self, sp500_alcista_estable):
        sp500_close, bullish, bearish = sp500_alcista_estable

        momentums = {"T1": 0.10, "T2": 0.08, "T3": 0.06, "T4": 0.04, "T5": 0.02}
        contexts = {
            name: _make_ctx(name, np.linspace(50, 100, N), np.full(N, mom))
            for name, mom in momentums.items()
        }

        config = StrategyConfig(name="t4", max_positions=3, initial_capital=9_000.0)
        result = run_portfolio_backtest(config, sp500_close, bullish, bearish, contexts, verbose=False)

        tickers_entrados = {p.ticker for p in result.open_positions_at_end}
        assert tickers_entrados == {"T1", "T2", "T3"}

    def test_capital_repartido_equitativamente(self, sp500_alcista_estable):
        sp500_close, bullish, bearish = sp500_alcista_estable

        momentums = {"T1": 0.10, "T2": 0.08, "T3": 0.06}
        contexts = {
            name: _make_ctx(name, np.linspace(50, 100, N), np.full(N, mom))
            for name, mom in momentums.items()
        }

        config = StrategyConfig(name="t5", max_positions=3, initial_capital=9_000.0)
        result = run_portfolio_backtest(config, sp500_close, bullish, bearish, contexts, verbose=False)

        for pos in result.open_positions_at_end:
            assert pos.capital_invertido == pytest.approx(3_000.0, abs=0.01)

    def test_nunca_se_supera_max_positions(self, sp500_alcista_estable):
        sp500_close, bullish, bearish = sp500_alcista_estable

        momentums = {f"T{i}": 0.01 * i for i in range(1, 8)}
        contexts = {
            name: _make_ctx(name, np.linspace(50, 100, N), np.full(N, mom))
            for name, mom in momentums.items()
        }

        config = StrategyConfig(name="t6", max_positions=3, initial_capital=9_000.0)
        result = run_portfolio_backtest(config, sp500_close, bullish, bearish, contexts, verbose=False)

        max_simultaneas = max(p.n_posiciones_abiertas for p in result.equity_curve)
        assert max_simultaneas <= 3


class TestSinCandidatos:

    def test_sin_ninguna_senal_no_hay_operaciones(self, sp500_alcista_estable):
        sp500_close, bullish, bearish = sp500_alcista_estable
        # RSC activo siempre negativo -> F3 nunca pasa -> nunca entra
        ctx = _make_ctx("AAA", np.linspace(50, 100, N), np.full(N, 0.05), rsc_activo_vals=np.full(N, -1.0))

        config = StrategyConfig(name="t7", max_positions=1, initial_capital=10_000.0)
        result = run_portfolio_backtest(config, sp500_close, bullish, bearish, {"AAA": ctx}, verbose=False)

        assert result.closed_trades == []
        assert result.open_positions_at_end == []
        assert result.metrics()["capital_final"] == 10_000.0


class TestMetricsResultado:

    def test_metrics_incluyen_todas_las_claves_esperadas(self, sp500_alcista_estable):
        sp500_close, bullish, bearish = sp500_alcista_estable
        f5_start = _first_true_idx(bullish)
        close_a = np.linspace(50, 100, N)
        rsc_a = np.full(N, 1.0)
        rsc_a[f5_start + 10:] = -1.0
        ctx_a = _make_ctx("AAA", close_a, np.full(N, 0.05), rsc_activo_vals=rsc_a)

        config = StrategyConfig(name="t8", max_positions=1, initial_capital=10_000.0)
        result = run_portfolio_backtest(config, sp500_close, bullish, bearish, {"AAA": ctx_a}, verbose=False)

        m = result.metrics()
        claves_esperadas = {
            "capital_inicial", "capital_final", "rentabilidad_total_pct", "cagr_pct",
            "max_drawdown_pct", "n_operaciones_cerradas", "n_operaciones_abiertas_al_final",
            "win_rate_pct", "retorno_medio_pct", "retorno_mediana_pct", "profit_factor",
            "mejor_operacion_pct", "peor_operacion_pct", "semanas_medias_en_pos",
            "sharpe_aprox", "pct_semanas_invertido",
        }
        assert claves_esperadas.issubset(m.keys())
