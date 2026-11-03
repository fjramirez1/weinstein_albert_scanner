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

from backtest import data_cache
from weinstein.data import TiingoRateLimitError, last_closed_friday


@pytest.fixture(autouse=True)
def _clean_cache(tmp_path, monkeypatch):
    """
    Redirige la caché a un directorio temporal vacío por test.

    Nunca debe tocarse `backtest/.cache/` real: una versión anterior de
    este fixture llamaba a `clear_cache()` sobre el directorio real y
    borraba toda la caché de datos descargada al ejecutar `pytest`.
    """
    monkeypatch.setattr(data_cache, "CACHE_DIR", tmp_path / "cache")
    yield


def _fake_df(end=None):
    # Termina en la última semana cerrada: una caché al día no se refresca.
    idx = pd.date_range(end=end or last_closed_friday(), periods=100, freq="W-FRI")
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


class TestCaducidad:

    def test_ticker_vigente_con_cache_desfasada_se_refresca(self):
        viejo = _fake_df(end=last_closed_friday() - pd.Timedelta(weeks=3))
        nuevo = _fake_df()
        with patch.object(data_cache, "download_weekly", side_effect=[viejo, nuevo]) as mock_dl:
            data_cache.get_cached_weekly("TST", "5y", is_current_constituent=True)
            result = data_cache.get_cached_weekly("TST", "5y", is_current_constituent=True)
        assert mock_dl.call_count == 2
        assert result.index[-1] == last_closed_friday()

    def test_ticker_delistado_nunca_se_refresca(self):
        viejo = _fake_df(end=pd.Timestamp("2021-06-04"))
        with patch.object(data_cache, "download_weekly", return_value=viejo) as mock_dl:
            data_cache.get_cached_weekly("OLD", "5y", is_current_constituent=False)
            data_cache.get_cached_weekly("OLD", "5y", is_current_constituent=False)
        assert mock_dl.call_count == 1

    def test_si_falla_el_refresco_se_usa_la_cache_antigua(self):
        viejo = _fake_df(end=last_closed_friday() - pd.Timedelta(weeks=3))
        with patch.object(data_cache, "download_weekly", side_effect=[viejo, None]):
            data_cache.get_cached_weekly("TST", "5y")
            result = data_cache.get_cached_weekly("TST", "5y")
        assert result is not None
        assert result.index[-1] == viejo.index[-1]


class TestLimiteTiingo:
    """Un ticker limitado por Tiingo NO es "sin datos": nunca deja `.nodata`."""

    def test_delistado_limitado_no_escribe_nodata(self):
        with patch.object(data_cache, "download_weekly",
                          side_effect=TiingoRateLimitError("limitado")):
            result = data_cache.get_cached_weekly("OLD", "5y", is_current_constituent=False)
        assert result is None
        assert data_cache.cache_stats()["n_fallos_cacheados"] == 0
        assert data_cache.cache_status("OLD", "5y", is_current_constituent=False) == "falta"

    def test_se_pide_a_download_weekly_que_propague_el_limite(self):
        with patch.object(data_cache, "download_weekly", return_value=None) as mock_dl:
            data_cache.get_cached_weekly("OLD", "5y", is_current_constituent=False)
        assert mock_dl.call_args.kwargs.get("raise_on_rate_limit") is True

    def test_tras_el_limite_se_reintenta_en_la_siguiente_llamada(self):
        fake_df = _fake_df(end=pd.Timestamp("2021-06-04"))
        with patch.object(data_cache, "download_weekly",
                          side_effect=[TiingoRateLimitError("limitado"), fake_df]) as mock_dl:
            assert data_cache.get_cached_weekly("OLD", "5y", is_current_constituent=False) is None
            result = data_cache.get_cached_weekly("OLD", "5y", is_current_constituent=False)
        assert mock_dl.call_count == 2
        assert result is not None

    def test_vigente_caducado_y_limitado_usa_la_cache_antigua(self):
        viejo = _fake_df(end=last_closed_friday() - pd.Timedelta(weeks=3))
        with patch.object(data_cache, "download_weekly",
                          side_effect=[viejo, TiingoRateLimitError("limitado")]):
            data_cache.get_cached_weekly("TST", "5y")
            result = data_cache.get_cached_weekly("TST", "5y")
        assert result is not None
        assert result.index[-1] == viejo.index[-1]


class TestHelpersDeEstado:

    def test_cache_status_falta_ok_caducado_nodata(self):
        assert data_cache.cache_status("TST", "5y") == "falta"
        data_cache.save_cached("TST", "5y", _fake_df())
        assert data_cache.cache_status("TST", "5y") == "ok"

        data_cache.save_cached("VIE", "5y", _fake_df(end=last_closed_friday() - pd.Timedelta(weeks=2)))
        assert data_cache.cache_status("VIE", "5y", is_current_constituent=True) == "caducado"
        # Un delistado nunca caduca.
        assert data_cache.cache_status("VIE", "5y", is_current_constituent=False) == "ok"

        data_cache.mark_nodata("OLD", "5y")
        assert data_cache.cache_status("OLD", "5y", is_current_constituent=False) == "nodata"
        # Para un vigente el marcador no cuenta (get_cached_weekly lo ignora).
        assert data_cache.cache_status("OLD", "5y", is_current_constituent=True) == "falta"

    def test_save_cached_borra_marcador_y_lo_lee_get_cached_weekly(self):
        data_cache.mark_nodata("OLD", "5y")
        data_cache.save_cached("OLD", "5y", _fake_df(end=pd.Timestamp("2021-06-04")))
        assert data_cache.cache_stats()["n_fallos_cacheados"] == 0
        with patch.object(data_cache, "download_weekly") as mock_dl:
            result = data_cache.get_cached_weekly("OLD", "5y", is_current_constituent=False)
        mock_dl.assert_not_called()
        assert result is not None and len(result) == 100

    def test_helpers_escriben_solo_en_cache_dir_redirigido(self, tmp_path):
        data_cache.save_cached("TST", "5y", _fake_df())
        data_cache.mark_nodata("OLD", "5y")
        assert data_cache.CACHE_DIR == tmp_path / "cache"
        assert sorted(p.name for p in data_cache.CACHE_DIR.iterdir()) == [
            "OLD__5y.nodata", "TST__5y.parquet",
        ]
