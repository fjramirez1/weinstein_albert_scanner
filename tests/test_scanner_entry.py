"""
Tests de `weinstein/scanner_entry.py`.

`_evaluate_ticker` mezcla lógica pura con I/O (descarga vía `download_weekly`),
así que aquí se mockea la descarga con `unittest.mock.patch` para poder
testear cada filtro (F1-F5) de forma aislada y determinista, sin red.

Orden real de evaluación en el código (de más barato a más caro):
    F5 (Coppock alcista) -> F1 (RSC sector) -> [descarga] ->
    F3 (RSC activo) -> F2 (VPM5) -> F4 (distancia WMA30)
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from tests.conftest import make_ohlcv, weekly_index
from weinstein import scanner_entry

N = 90


@pytest.fixture
def sp500_close_base() -> pd.Series:
    return pd.Series(np.linspace(100, 110, N), index=weekly_index(N))


@pytest.fixture
def ohlcv_que_pasa_todos_los_filtros() -> pd.DataFrame:
    """
    Activo con crecimiento marcado (RSC activo > benchmark suave, precio
    razonablemente cerca de su WMA30) y volumen con pico reciente (VPM5 > 0).
    """
    idx = weekly_index(N)
    rng = np.random.default_rng(1)
    close = np.linspace(50, 90, N)
    volume = np.concatenate([1000 + rng.normal(0, 20, N - 5), [3000.0] * 5])
    return make_ohlcv(close, volume, idx)


def _base_kwargs(sp500_close, sector_rsc_map=None, coppock_bullish=True, sem=None):
    from threading import Semaphore
    return dict(
        ticker="TST",
        sector_name="Energy",
        company_name="Test Co",
        sp500_close=sp500_close,
        coppock_bullish=coppock_bullish,
        coppock_direction="↑ Alcista" if coppock_bullish else "↓ Bajista",
        sector_rsc_map=sector_rsc_map if sector_rsc_map is not None else {"XLE": 0.5},
        sem=sem or Semaphore(5),
    )


class TestEvaluateTicker:

    def test_caso_completo_pasa_todos_los_filtros(self, sp500_close_base, ohlcv_que_pasa_todos_los_filtros):
        with patch.object(scanner_entry, "download_weekly", return_value=ohlcv_que_pasa_todos_los_filtros):
            resultado, motivo = scanner_entry._evaluate_ticker(
                **_base_kwargs(sp500_close_base)
            )
        assert motivo == "ok"
        assert resultado is not None
        assert resultado["Ticker"] == "TST"
        assert resultado["RSC Mansfield Sector"] == 0.5

    def test_f5_mercado_bajista_filtra_sin_descargar(self, sp500_close_base):
        """F5 falla (Coppock no alcista) -> ni siquiera se llama a download_weekly."""
        with patch.object(scanner_entry, "download_weekly") as mock_dl:
            resultado, motivo = scanner_entry._evaluate_ticker(
                **_base_kwargs(sp500_close_base, coppock_bullish=False)
            )
        assert resultado is None
        assert motivo == "filtrado"
        mock_dl.assert_not_called()

    def test_f1_sector_debil_filtra_sin_descargar(self, sp500_close_base):
        """F1 falla (RSC sector por debajo del umbral) -> tampoco se descarga el ticker."""
        with patch.object(scanner_entry, "download_weekly") as mock_dl:
            resultado, motivo = scanner_entry._evaluate_ticker(
                **_base_kwargs(sp500_close_base, sector_rsc_map={"XLE": 0.01})
            )
        assert resultado is None
        assert motivo == "filtrado"
        mock_dl.assert_not_called()

    def test_f1_sector_sin_datos_filtra(self, sp500_close_base):
        """Si el ETF del sector no tiene RSC calculado (sin datos), F1 también falla."""
        with patch.object(scanner_entry, "download_weekly") as mock_dl:
            resultado, motivo = scanner_entry._evaluate_ticker(
                **_base_kwargs(sp500_close_base, sector_rsc_map={})
            )
        assert resultado is None
        assert motivo == "filtrado"
        mock_dl.assert_not_called()

    def test_f3_rsc_activo_debil_filtra(self, sp500_close_base):
        """Activo que rinde peor que un benchmark fuerte -> RSC activo <= 0 -> F3 falla."""
        idx = weekly_index(N)
        close_debil = np.linspace(100, 102, N)
        sp500_fuerte = pd.Series(np.linspace(100, 200, N), index=idx)
        volume = np.full(N, 1000.0)
        ohlcv = make_ohlcv(close_debil, volume, idx)

        with patch.object(scanner_entry, "download_weekly", return_value=ohlcv):
            resultado, motivo = scanner_entry._evaluate_ticker(
                **_base_kwargs(sp500_fuerte)
            )
        assert resultado is None
        assert motivo == "filtrado"

    def test_f2_volumen_sin_pico_filtra(self, sp500_close_base):
        """Volumen totalmente plano -> VPM5 indefinido/no positivo -> F2 falla."""
        idx = weekly_index(N)
        close = np.linspace(50, 90, N)
        volume_plano = np.full(N, 1000.0)
        ohlcv = make_ohlcv(close, volume_plano, idx)

        with patch.object(scanner_entry, "download_weekly", return_value=ohlcv):
            resultado, motivo = scanner_entry._evaluate_ticker(
                **_base_kwargs(sp500_close_base)
            )
        assert resultado is None
        assert motivo == "filtrado"

    def test_f4_precio_demasiado_lejos_de_wma30_filtra(self, sp500_close_base, ohlcv_que_pasa_todos_los_filtros):
        """Salto de precio brusco en la última semana -> distancia % WMA30 supera el máximo permitido."""
        idx = weekly_index(N)
        close_spike = np.concatenate([np.full(N - 1, 50.0), [80.0]])
        volume = ohlcv_que_pasa_todos_los_filtros["Volume"].to_numpy()
        ohlcv = make_ohlcv(close_spike, volume, idx)

        with patch.object(scanner_entry, "download_weekly", return_value=ohlcv):
            resultado, motivo = scanner_entry._evaluate_ticker(
                **_base_kwargs(sp500_close_base)
            )
        assert resultado is None
        assert motivo == "filtrado"

    def test_sin_datos_de_descarga_devuelve_sin_datos(self, sp500_close_base):
        with patch.object(scanner_entry, "download_weekly", return_value=None):
            resultado, motivo = scanner_entry._evaluate_ticker(
                **_base_kwargs(sp500_close_base)
            )
        assert resultado is None
        assert motivo == "sin_datos"

    def test_historico_insuficiente_devuelve_sin_datos(self, sp500_close_base):
        idx = weekly_index(10)  # muy corto, por debajo de RSC_SMA_PERIOD + 5
        close = np.linspace(50, 55, 10)
        volume = np.full(10, 1000.0)
        ohlcv = make_ohlcv(close, volume, idx)

        with patch.object(scanner_entry, "download_weekly", return_value=ohlcv):
            resultado, motivo = scanner_entry._evaluate_ticker(
                **_base_kwargs(sp500_close_base)
            )
        assert resultado is None
        assert motivo == "sin_datos"
