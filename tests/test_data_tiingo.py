"""
Tests del fallback Tiingo.

Todo mockeado (requests.get / variable de entorno TIINGO_API_KEY / yf.download), sin red real ni
necesidad de una API key válida.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pandas as pd
import pytest

from weinstein.data import (
    _try_tiingo_fallback,
    download_weekly,
    download_weekly_tiingo,
)


def _tiingo_payload_ok(n_weeks: int = 100) -> list[dict]:
    base = pd.Timestamp("2020-01-06")
    return [
        {
            "date": (base + pd.Timedelta(weeks=i)).strftime("%Y-%m-%dT00:00:00.000Z"),
            "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1000,
            "adjOpen": 10.0, "adjHigh": 11.0, "adjLow": 9.0, "adjClose": 10.5, "adjVolume": 1000,
        }
        for i in range(n_weeks)
    ]


class TestDownloadWeeklyTiingo:

    def test_sin_api_key_devuelve_none_y_avisa_una_vez(self, monkeypatch, capsys):
        monkeypatch.delenv("TIINGO_API_KEY", raising=False)
        import weinstein.data as data_mod
        data_mod._tiingo_missing_key_warned = False  # reset del aviso "solo una vez"

        resultado = download_weekly_tiingo("TST", min_bars=10)
        assert resultado is None

        captured = capsys.readouterr()
        assert "TIINGO_API_KEY" in captured.err

    def test_respuesta_valida_devuelve_dataframe_normalizado(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        mock_resp = Mock(status_code=200)
        mock_resp.raise_for_status = Mock()
        mock_resp.json = Mock(return_value=_tiingo_payload_ok(100))

        with patch("weinstein.data.requests.get", return_value=mock_resp):
            resultado = download_weekly_tiingo("TST", min_bars=10)

        assert resultado is not None
        assert list(resultado.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert len(resultado) == 100

    def test_usa_columnas_ajustadas_por_defecto(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        payload = _tiingo_payload_ok(20)
        # Diferenciar adj* de los brutos para verificar que se usa adj*.
        for row in payload:
            row["adjClose"] = 999.0
            row["close"] = 1.0
        mock_resp = Mock(status_code=200)
        mock_resp.raise_for_status = Mock()
        mock_resp.json = Mock(return_value=payload)

        with patch("weinstein.data.requests.get", return_value=mock_resp):
            resultado = download_weekly_tiingo("TST", min_bars=10)

        assert (resultado["Close"] == 999.0).all()

    def test_ticker_404_devuelve_none_sin_reintentar(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        mock_resp = Mock(status_code=404)
        with patch("weinstein.data.requests.get", return_value=mock_resp) as mock_get:
            resultado = download_weekly_tiingo("GHOST", min_bars=10)
        assert resultado is None
        assert mock_get.call_count == 1

    def test_token_invalido_401_devuelve_none(self, monkeypatch, capsys):
        monkeypatch.setenv("TIINGO_API_KEY", "bad-token")
        mock_resp = Mock(status_code=401)
        with patch("weinstein.data.requests.get", return_value=mock_resp):
            resultado = download_weekly_tiingo("TST", min_bars=10)
        assert resultado is None
        assert "401" in capsys.readouterr().err

    def test_rate_limit_429_devuelve_none(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        mock_resp = Mock(status_code=429)
        with patch("weinstein.data.requests.get", return_value=mock_resp):
            resultado = download_weekly_tiingo("TST", min_bars=10)
        assert resultado is None

    def test_historico_insuficiente_devuelve_none(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        mock_resp = Mock(status_code=200)
        mock_resp.raise_for_status = Mock()
        mock_resp.json = Mock(return_value=_tiingo_payload_ok(5))

        with patch("weinstein.data.requests.get", return_value=mock_resp):
            resultado = download_weekly_tiingo("TST", min_bars=70)
        assert resultado is None

    def test_payload_vacio_devuelve_none(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        mock_resp = Mock(status_code=200)
        mock_resp.raise_for_status = Mock()
        mock_resp.json = Mock(return_value=[])

        with patch("weinstein.data.requests.get", return_value=mock_resp):
            resultado = download_weekly_tiingo("TST", min_bars=10)
        assert resultado is None

    def test_error_de_red_devuelve_none(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        with patch("weinstein.data.requests.get", side_effect=Exception("network error")):
            resultado = download_weekly_tiingo("TST", min_bars=10)
        assert resultado is None


class TestTryTiingoFallback:

    def test_desactivado_no_llama_a_tiingo(self):
        with patch("weinstein.config.TIINGO_FALLBACK_ENABLED", False):
            with patch("weinstein.data.download_weekly_tiingo") as mock_dl:
                resultado = _try_tiingo_fallback("TST")
        mock_dl.assert_not_called()
        assert resultado is None

    def test_activado_llama_a_tiingo(self):
        fake_df = pd.DataFrame({"Close": [1.0]})
        with patch("weinstein.config.TIINGO_FALLBACK_ENABLED", True):
            with patch("weinstein.data.download_weekly_tiingo", return_value=fake_df) as mock_dl:
                resultado = _try_tiingo_fallback("TST")
        mock_dl.assert_called_once_with("TST")
        assert resultado is fake_df


class TestDownloadWeeklyConFallback:

    def test_yfinance_sin_datos_recurre_a_tiingo_y_tiene_exito(self):
        fake_tiingo_df = pd.DataFrame(
            {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 100},
            index=pd.date_range("2020-01-06", periods=100, freq="W"),
        )
        with patch("weinstein.data.yf.download", return_value=pd.DataFrame()):
            with patch("weinstein.data.time.sleep"):
                with patch("weinstein.data.download_weekly_tiingo", return_value=fake_tiingo_df) as mock_tiingo:
                    resultado = download_weekly("DELISTED", max_retries=1)

        mock_tiingo.assert_called_once_with("DELISTED")
        assert resultado is not None
        assert len(resultado) == 100

    def test_yfinance_y_tiingo_fallan_devuelve_none(self):
        with patch("weinstein.data.yf.download", return_value=pd.DataFrame()):
            with patch("weinstein.data.time.sleep"):
                with patch("weinstein.data.download_weekly_tiingo", return_value=None):
                    resultado = download_weekly("GHOST", max_retries=1)
        assert resultado is None

    def test_yfinance_exitoso_no_llama_a_tiingo(self):
        idx = pd.date_range("2020-01-06", periods=100, freq="W")
        raw = pd.DataFrame(
            {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 100}, index=idx
        )
        with patch("weinstein.data.yf.download", return_value=raw):
            with patch("weinstein.data.download_weekly_tiingo") as mock_tiingo:
                resultado = download_weekly("TST")

        mock_tiingo.assert_not_called()
        assert resultado is not None
        assert len(resultado) == 100
