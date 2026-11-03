"""
Paridad escáner ↔ backtest (tarea R1 de docs/HOJA_DE_RUTA.md).

Para cada semana t se recortan todos los datos hasta t, como si el escáner
se ejecutara ese fin de semana, y se comprueba que su veredicto coincide
con la máscara que el backtest precalcula para t sobre el histórico
completo. Si coinciden en todas las semanas:

- el escáner y el backtest aplican exactamente las mismas reglas, y
- el backtest no usa información futura (look-ahead).
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from backtest.portfolio_engine import evaluate_entry_mask, evaluate_exit_masks
from backtest.strategy_config import StrategyConfig
from weinstein import scanner_entry, scanner_exit
from weinstein.signals import build_ticker_context, market_state_series

N = 260
IDX = pd.date_range("2019-01-04", periods=N, freq="W-FRI")


def _serie(seed: int, drift: float, ciclo: float, vol: float = 0.025) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(N)
    rets = drift + ciclo * np.sin(2 * np.pi * t / 70) + rng.normal(0, vol, N)
    return 100 * np.cumprod(1 + rets)


def _ohlcv(close: np.ndarray, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    volume = 1e6 * np.exp(rng.normal(0, 0.4, N) + 0.5 * np.sin(np.arange(N) / 9))
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": volume}, index=IDX)


SEMANAS = range(80, N)
TICKERS = [f"T{k}" for k in range(6)]


@pytest.fixture(scope="module")
def mercado():
    sp500 = pd.Series(_serie(1, 0.002, 0.012, 0.015), index=IDX)
    etf = pd.Series(_serie(2, 0.0025, 0.010, 0.018), index=IDX)
    activos = {t: _ohlcv(_serie(10 + k, 0.003, 0.015), 100 + k) for k, t in enumerate(TICKERS)}
    bullish, bearish = market_state_series(sp500)
    extra = {"coppock_bullish": bullish, "coppock_bearish": bearish}
    config = StrategyConfig()
    mascaras = {}
    for ticker, data in activos.items():
        ctx = build_ticker_context(ticker, "Energy", data, sp500, etf)
        mascaras[ticker] = (evaluate_entry_mask(ctx, config, extra), evaluate_exit_masks(ctx, config, extra))
    return sp500, etf, activos, mascaras


def _estado_escaner(sp500_t: pd.Series, etf_t: pd.Series) -> tuple[bool, bool, float]:
    """Lo que calcularía el escáner con los datos disponibles hasta t (mercado y RSC del sector)."""
    bullish_t, bearish_t = market_state_series(sp500_t)
    with patch.object(scanner_entry, "download_weekly", return_value=etf_t.to_frame("Close")):
        _, rsc_sector = scanner_entry._download_etf_rsc("XLE", sp500_t)
    return bool(bullish_t.iloc[-1]), bool(bearish_t.iloc[-1]), rsc_sector


def test_escaner_coincide_con_el_backtest_semana_a_semana(mercado):
    sp500, etf, activos, mascaras = mercado
    vistos = {"entrada": {True: 0, False: 0}, "s1": {True: 0, False: 0}}

    for i in SEMANAS:
        t = IDX[i]
        sp500_t = sp500.loc[:t]
        bullish_t, bearish_t, rsc_sector = _estado_escaner(sp500_t, etf.loc[:t])

        for ticker, data in activos.items():
            entrada, salidas = mascaras[ticker]
            data_t = data.loc[:t]

            with patch.object(scanner_entry, "download_weekly", return_value=data_t):
                resultado, _ = scanner_entry._evaluate_ticker(
                    ticker=ticker, sector_name="Energy", company_name=ticker,
                    sp500_close=sp500_t, coppock_bullish=bullish_t,
                    coppock_direction="", sector_rsc_map={"XLE": rsc_sector},
                )
            esperado = bool(entrada.loc[t])
            assert (resultado is not None) == esperado, f"entrada {ticker} {t.date()}"
            vistos["entrada"][esperado] += 1

            with patch.object(scanner_exit, "download_weekly", return_value=data_t):
                res = scanner_exit._evaluate_exit(ticker, IDX[0], sp500_t, coppock_bearish=bearish_t)
            s1 = bool(res["S1 RSC < -0.5"])
            assert s1 == bool(salidas["S1_rsc_debil"].loc[t]), f"S1 {ticker} {t.date()}"
            assert bearish_t == bool(salidas["S2_mercado_bajista"].loc[t]), f"S2 {t.date()}"
            vistos["s1"][s1] += 1

    # El escenario debe ejercitar ambos veredictos para que el test signifique algo.
    for clave, conteo in vistos.items():
        assert conteo[True] >= 8 and conteo[False] >= 8, (clave, conteo)
