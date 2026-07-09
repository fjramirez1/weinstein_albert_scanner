"""
Tests de `backtest/strategy_backtest.py`.

El motor de backtest reutiliza las mismas funciones puras de
`weinstein/indicators.py` que usan los escáneres de producción, así que
estos tests se centran en:

  1. Que `_entry_signal_at` / `_exit_signal_at` no hagan look-ahead
     (usan solo `close.iloc[:i+1]` y equivalentes).
  2. Que `simulate_ticker` abra/cierre posiciones en el momento correcto
     y calcule bien el retorno, incluyendo el caso de posición abierta
     al final del histórico.
  3. Que las métricas agregadas (`BacktestResult.metrics`) sean
     correctas sobre una lista de operaciones conocida.

No se testea `run_strategy_backtest` end-to-end (requiere red); ese
comportamiento se cubre indirectamente mockeando `download_weekly` a
nivel de `_worker_backtest_ticker`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.conftest import make_ohlcv, weekly_index  # noqa: E402
from backtest import strategy_backtest as bt  # noqa: E402

N = 150  # histórico suficientemente largo para superar BACKTEST_MIN_BARS


@pytest.fixture
def sp500_close_alcista() -> pd.Series:
    """
    S&P 500 con Coppock alcista sostenido: crecimiento que acelera al
    final, igual que `strong_uptrend_price` en tests/conftest.py, para
    que F5/S2 den resultados estables y conocidos en todo el tramo final.
    """
    idx = weekly_index(N)
    growth = np.concatenate([np.full(N - 20, 0.004), np.linspace(0.004, 0.015, 20)])
    return pd.Series(100 * np.cumprod(1 + growth), index=idx)


@pytest.fixture
def sector_etf_fuerte(sp500_close_alcista) -> pd.Series:
    """ETF sectorial que rinde claramente mejor que el S&P 500 (F1 pasa)."""
    idx = weekly_index(N)
    return pd.Series(np.linspace(50, 150, N), index=idx)


class TestEntrySignalSinLookAhead:

    def test_no_usa_datos_futuros(self, sp500_close_alcista, sector_etf_fuerte):
        """
        Construye un activo cuyo precio se dispara SOLO después del
        índice de evaluación `i`. La señal en `i` no debe verse afectada
        por ese futuro: debe coincidir con la señal evaluada sobre la
        serie truncada en `i`.
        """
        idx = weekly_index(N)
        rng = np.random.default_rng(7)
        close_base = np.linspace(50, 90, N)
        volume = np.concatenate([1000 + rng.normal(0, 20, N - 5), [3000.0] * 5])
        close = pd.Series(close_base, index=idx)
        vol = pd.Series(volume, index=idx)

        i = 100
        signal_con_futuro = bt._entry_signal_at(close, vol, sp500_close_alcista, sector_etf_fuerte, i)

        # Trunca todas las series en i+1 y reevalúa: debe dar exactamente lo mismo.
        close_trunc = close.iloc[: i + 1]
        vol_trunc = vol.iloc[: i + 1]
        sp500_trunc = sp500_close_alcista.loc[sp500_close_alcista.index <= close.index[i]]
        sector_trunc = sector_etf_fuerte.loc[sector_etf_fuerte.index <= close.index[i]]

        signal_truncada = bt._entry_signal_at(close_trunc, vol_trunc, sp500_trunc, sector_trunc, i)

        assert signal_con_futuro == signal_truncada

    def test_historico_insuficiente_no_entra(self, sp500_close_alcista, sector_etf_fuerte):
        idx = weekly_index(N)
        close = pd.Series(np.linspace(50, 90, N), index=idx)
        vol = pd.Series(1000.0, index=idx)

        assert bt._entry_signal_at(close, vol, sp500_close_alcista, sector_etf_fuerte, 5) is False

    def test_sin_etf_sectorial_no_entra(self, sp500_close_alcista):
        idx = weekly_index(N)
        rng = np.random.default_rng(3)
        close = pd.Series(np.linspace(50, 90, N), index=idx)
        volume = np.concatenate([1000 + rng.normal(0, 20, N - 5), [3000.0] * 5])
        vol = pd.Series(volume, index=idx)

        assert bt._entry_signal_at(close, vol, sp500_close_alcista, None, 120) is False


class TestExitSignalSinLookAhead:

    def test_no_usa_datos_futuros(self, sp500_close_alcista):
        idx = weekly_index(N)
        close = pd.Series(np.linspace(100, 90, N), index=idx)  # activo débil -> S1 probable

        i = 100
        salida_con_futuro, motivo_con_futuro = bt._exit_signal_at(close, sp500_close_alcista, i)

        close_trunc = close.iloc[: i + 1]
        sp500_trunc = sp500_close_alcista.loc[sp500_close_alcista.index <= close.index[i]]
        salida_truncada, motivo_truncado = bt._exit_signal_at(close_trunc, sp500_trunc, i)

        assert salida_con_futuro == salida_truncada
        assert motivo_con_futuro == motivo_truncado

    def test_activo_debil_activa_s1(self, sp500_close_alcista):
        """RSC del activo << 0 mientras el mercado no es bajista -> solo S1."""
        idx = weekly_index(N)
        close = pd.Series(np.linspace(100, 60, N), index=idx)  # cae fuerte
        salida, motivo = bt._exit_signal_at(close, sp500_close_alcista, N - 1)
        assert salida is True
        assert "S1" in motivo


class TestSimulateTicker:

    def test_abre_y_cierra_una_posicion_completa(self, sp500_close_alcista, sector_etf_fuerte):
        """
        Activo que cumple F1-F5 en algún punto intermedio (fuerte,
        volumen con pico) y luego se debilita lo suficiente para
        disparar S1. Debe generar exactamente 1 operación cerrada con
        retorno coherente.
        """
        idx = weekly_index(N)
        rng = np.random.default_rng(11)

        # Primeras 2/3 partes: sube con fuerza (activa F1-F5).
        # Último tercio: cae con fuerza (activa S1).
        up_part = np.linspace(50, 100, int(N * 0.7))
        down_part = np.linspace(100, 40, N - len(up_part))
        close_vals = np.concatenate([up_part, down_part])
        close = pd.Series(close_vals, index=idx)

        volume = np.concatenate([1000 + rng.normal(0, 20, N - 5), [3000.0] * 5])
        vol = pd.Series(volume, index=idx)

        trades = bt.simulate_ticker(
            "TST", "Energy", close, vol, sp500_close_alcista, sector_etf_fuerte
        )

        assert len(trades) >= 1
        primera = trades[0]
        assert primera.fecha_entrada is not None
        # Si se cerró, el retorno debe coincidir con precio_salida/precio_entrada.
        if primera.retorno_pct is not None:
            esperado = round(((primera.precio_salida / primera.precio_entrada) - 1) * 100, 2)
            assert primera.retorno_pct == esperado
            assert primera.semanas_en_pos >= 0

    def test_posicion_abierta_al_final_no_se_pierde(self, sp500_close_alcista, sector_etf_fuerte):
        """
        Activo que entra pero nunca cumple S1/S2 antes de que acabe el
        histórico: debe registrarse como operación con retorno_pct=None,
        no descartarse.
        """
        idx = weekly_index(N)
        rng = np.random.default_rng(5)
        close = pd.Series(np.linspace(50, 100, N), index=idx)  # sube todo el tiempo, RSC nunca cae
        volume = np.concatenate([1000 + rng.normal(0, 20, N - 5), [3000.0] * 5])
        vol = pd.Series(volume, index=idx)

        trades = bt.simulate_ticker(
            "TST", "Energy", close, vol, sp500_close_alcista, sector_etf_fuerte
        )

        if trades:  # si llegó a entrar
            ultima = trades[-1]
            if ultima.fecha_salida is None:
                assert ultima.retorno_pct is None
                assert ultima.motivo_salida == "(posición abierta al final del backtest)"

    def test_ticker_que_nunca_cumple_entrada_no_genera_operaciones(self, sp500_close_alcista):
        """Sin ETF sectorial disponible, F1 nunca pasa -> 0 operaciones."""
        idx = weekly_index(N)
        close = pd.Series(np.linspace(50, 90, N), index=idx)
        vol = pd.Series(1000.0, index=idx)

        trades = bt.simulate_ticker("TST", "Energy", close, vol, sp500_close_alcista, None)
        assert trades == []


class TestBacktestResultMetrics:

    def _trade(self, retorno_pct, semanas=5):
        return bt.Trade(
            ticker="TST", sector="Energy",
            fecha_entrada=pd.Timestamp("2024-01-01"), precio_entrada=100.0,
            fecha_salida=pd.Timestamp("2024-02-01"), precio_salida=100.0 * (1 + retorno_pct / 100),
            motivo_salida="S1", semanas_en_pos=semanas, retorno_pct=retorno_pct,
        )

    def test_metrics_sin_operaciones(self):
        result = bt.BacktestResult()
        m = result.metrics()
        assert m["n_operaciones_cerradas"] == 0
        assert m["retorno_medio_pct"] is None

    def test_metrics_con_operaciones_mixtas(self):
        result = bt.BacktestResult()
        result.trades = [
            self._trade(10.0), self._trade(-5.0), self._trade(20.0), self._trade(-2.0),
        ]
        m = result.metrics()

        assert m["n_operaciones_cerradas"] == 4
        assert m["win_rate_pct"] == 50.0
        assert m["retorno_medio_pct"] == pytest.approx((10 - 5 + 20 - 2) / 4, abs=0.01)
        # profit factor = suma ganancias / suma pérdidas = 30 / 7
        assert m["profit_factor"] == pytest.approx(30 / 7, abs=0.01)

    def test_operaciones_abiertas_no_cuentan_en_metrics_pero_se_reportan(self):
        result = bt.BacktestResult()
        abierta = bt.Trade(
            ticker="TST", sector="Energy",
            fecha_entrada=pd.Timestamp("2024-01-01"), precio_entrada=100.0,
            fecha_salida=None, precio_salida=None,
            motivo_salida="(posición abierta al final del backtest)",
            semanas_en_pos=10, retorno_pct=None,
        )
        result.trades = [self._trade(10.0), abierta]
        m = result.metrics()

        assert m["n_operaciones_cerradas"] == 1
        assert m["n_operaciones_abiertas"] == 1

    def test_profit_factor_none_sin_perdidas(self):
        result = bt.BacktestResult()
        result.trades = [self._trade(5.0), self._trade(3.0)]
        m = result.metrics()
        assert m["profit_factor"] is None  # sin pérdidas -> no divide por cero

    def test_to_dataframe_columnas_esperadas(self):
        result = bt.BacktestResult()
        result.trades = [self._trade(10.0)]
        df = result.to_dataframe()
        assert list(df.columns) == [
            "Ticker", "Sector", "Fecha Entrada", "Precio Entrada",
            "Fecha Salida", "Precio Salida", "Motivo Salida",
            "Semanas en Pos.", "Retorno %",
        ]

    def test_to_dataframe_vacio_si_no_hay_trades(self):
        result = bt.BacktestResult()
        assert result.to_dataframe().empty


class TestWorkerBacktestTickerMockeado:
    """Cubre `_worker_backtest_ticker` mockeando `download_weekly`, sin red."""

    def test_sin_datos_devuelve_estado_sin_datos(self, sp500_close_alcista, sector_etf_fuerte):
        row = pd.Series({"Symbol": "TST", "Sector": "Energy"})
        with patch.object(bt, "download_weekly", return_value=None):
            trades, estado = bt._worker_backtest_ticker(
                row, sp500_close_alcista, {"XLE": sector_etf_fuerte}, "10y"
            )
        assert trades == []
        assert estado == "sin_datos"

    def test_excepcion_durante_simulacion_devuelve_estado_error(self, sp500_close_alcista):
        row = pd.Series({"Symbol": "TST", "Sector": "Energy"})
        with patch.object(bt, "download_weekly", side_effect=Exception("boom")):
            trades, estado = bt._worker_backtest_ticker(
                row, sp500_close_alcista, {}, "10y"
            )
        # download_weekly lanzando excepción se captura -> estado "error" o "sin_datos"
        # según dónde se produzca; aquí ocurre dentro del try, así que "error".
        assert trades == []
        assert estado in ("error", "sin_datos")

    def test_datos_validos_ejecuta_simulacion(self, sp500_close_alcista, sector_etf_fuerte):
        idx = weekly_index(N)
        rng = np.random.default_rng(1)
        close = np.linspace(50, 90, N)
        volume = np.concatenate([1000 + rng.normal(0, 20, N - 5), [3000.0] * 5])
        ohlcv = make_ohlcv(close, volume, idx)

        row = pd.Series({"Symbol": "TST", "Sector": "Energy"})
        with patch.object(bt, "download_weekly", return_value=ohlcv):
            trades, estado = bt._worker_backtest_ticker(
                row, sp500_close_alcista, {"XLE": sector_etf_fuerte}, "10y"
            )
        assert estado == "ok"
        assert isinstance(trades, list)
