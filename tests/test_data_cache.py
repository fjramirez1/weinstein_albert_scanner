"""
Tests de `backtest/data_cache.py`, mockeando `download_weekly` para no
depender de red real (igual que `tests/test_data.py` para el módulo
equivalente de `weinstein/data.py`).
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from tests.conftest import weekly_index
from backtest import data_cache


@pytest.fixture(autouse=True)
def _clean_cache():
    """Asegura una caché vacía antes y después de cada test de este módulo."""
    data_cache.clear_cache()
    yield
    data_cache.clear_cache()


def _fake_df():
    idx = weekly_index(100)
    return pd.DataFrame({
        "Open": 1.0, "High": 1.0, "Low": 1.0,
        "Close": np.linspace(100, 200, 100), "Volume": 1000.0,
    }, index=idx)


class TestGetCachedWeekly:

    def test_primera_llamada_descarga_y_cachea(self):
        fake_df = _fake_df()
        with patch.object(data_cache, "download_weekly", return_value=fake_df) as mock_dl:
            result = data_cache.get_cached_weekly("TST", "5y")
        mock_dl.assert_called_once()
        assert result is not None
        assert len(result) == 100

    def test_segunda_llamada_usa_cache_sin_redescargar(self):
        fake_df = _fake_df()
        with patch.object(data_cache, "download_weekly", return_value=fake_df) as mock_dl:
            data_cache.get_cached_weekly("TST", "5y")
            data_cache.get_cached_weekly("TST", "5y")
        assert mock_dl.call_count == 1

    def test_refresh_true_fuerza_redescarga(self):
        fake_df = _fake_df()
        with patch.object(data_cache, "download_weekly", return_value=fake_df) as mock_dl:
            data_cache.get_cached_weekly("TST", "5y")
            data_cache.get_cached_weekly("TST", "5y", refresh=True)
        assert mock_dl.call_count == 2

    def test_valores_leidos_de_cache_coinciden_con_originales(self):
        fake_df = _fake_df()
        with patch.object(data_cache, "download_weekly", return_value=fake_df):
            r1 = data_cache.get_cached_weekly("TST", "5y")
            r2 = data_cache.get_cached_weekly("TST", "5y")
        assert (r1.values == r2.values).all()
        assert (r1.index == r2.index).all()

    def test_descarga_fallida_no_escribe_cache_ni_rompe(self):
        with patch.object(data_cache, "download_weekly", return_value=None):
            result = data_cache.get_cached_weekly("TST", "5y")
        assert result is None
        stats = data_cache.cache_stats()
        assert stats["n_archivos"] == 0

    def test_tickers_distintos_no_comparten_cache(self):
        fake_df_a = _fake_df()
        fake_df_b = _fake_df() * 2
        with patch.object(data_cache, "download_weekly", side_effect=[fake_df_a, fake_df_b]):
            data_cache.get_cached_weekly("AAA", "5y")
            data_cache.get_cached_weekly("BBB", "5y")
        stats = data_cache.cache_stats()
        assert stats["n_archivos"] == 2

    def test_periodos_distintos_no_comparten_cache(self):
        fake_df = _fake_df()
        with patch.object(data_cache, "download_weekly", return_value=fake_df) as mock_dl:
            data_cache.get_cached_weekly("TST", "5y")
            data_cache.get_cached_weekly("TST", "8y")
        assert mock_dl.call_count == 2


class TestCacheStatsYClear:

    def test_cache_stats_vacia(self):
        stats = data_cache.cache_stats()
        assert stats["n_archivos"] == 0
        assert stats["tamano_mb"] == 0.0

    def test_clear_cache_devuelve_numero_de_archivos_borrados(self):
        fake_df = _fake_df()
        with patch.object(data_cache, "download_weekly", return_value=fake_df):
            data_cache.get_cached_weekly("AAA", "5y")
            data_cache.get_cached_weekly("BBB", "5y")
        n_borrados = data_cache.clear_cache()
        assert n_borrados == 2
        assert data_cache.cache_stats()["n_archivos"] == 0

    def test_clear_cache_sobre_cache_vacia_no_falla(self):
        assert data_cache.clear_cache() == 0
