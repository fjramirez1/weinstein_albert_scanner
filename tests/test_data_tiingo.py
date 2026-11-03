"""
Tests del fallback Tiingo.

Todo mockeado (requests.get / variable de entorno TIINGO_API_KEY / yf.download), sin red real ni
necesidad de una API key válida.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pandas as pd
import pytest

import weinstein.data as data_mod
from weinstein.data import (
    TiingoBudgetExhaustedError,
    TiingoRateLimitError,
    _try_tiingo_fallback,
    download_weekly,
    download_weekly_tiingo,
    reset_tiingo_state,
    set_tiingo_budget,
    tiingo_block,
    tiingo_requests_made,
)


@pytest.fixture(autouse=True)
def _estado_tiingo_limpio():
    """El contador/bloqueo de Tiingo es global del módulo: se resetea por test."""
    reset_tiingo_state()
    yield
    reset_tiingo_state()


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

    def test_rate_limit_429_lanza_excepcion_no_none(self, monkeypatch):
        # "Limitado" no es "sin datos": devolver None haría que data_cache
        # escribiera un .nodata permanente para un delistado.
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        mock_resp = Mock(status_code=429)
        mock_resp.json = Mock(side_effect=ValueError("sin cuerpo"))
        with patch("weinstein.data.requests.get", return_value=mock_resp):
            with pytest.raises(TiingoRateLimitError) as info:
                download_weekly_tiingo("TST", min_bars=10)
        assert info.value.motivo == "hora"

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


class TestLimiteDePeticiones:
    """Límite del plan gratuito de Tiingo (HTTP 429 o HTTP 200 con {"detail": ...})."""

    def test_http_200_con_detail_de_limite_horario_lanza_excepcion(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        mock_resp = Mock(status_code=200)
        mock_resp.raise_for_status = Mock()
        mock_resp.json = Mock(return_value={
            "detail": "Error: You have run over your hourly request allocation. "
                      "Please upgrade at https://api.tiingo.com/pricing to have your limits increased."
        })
        with patch("weinstein.data.requests.get", return_value=mock_resp):
            with pytest.raises(TiingoRateLimitError) as info:
                download_weekly_tiingo("TST", min_bars=10)
        assert info.value.motivo == "hora"
        assert info.value.bloqueado_hasta is not None

    def test_detail_de_limite_mensual_de_simbolos(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        mock_resp = Mock(status_code=200)
        mock_resp.raise_for_status = Mock()
        mock_resp.json = Mock(return_value={
            "detail": "Error: You have run over your monthly unique symbol request allocation."
        })
        with patch("weinstein.data.requests.get", return_value=mock_resp):
            with pytest.raises(TiingoRateLimitError) as info:
                download_weekly_tiingo("TST", min_bars=10)
        assert info.value.motivo == "mes"
        assert info.value.bloqueado_hasta == float("inf")

    def test_429_con_detail_diario(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        mock_resp = Mock(status_code=429)
        mock_resp.json = Mock(return_value={"detail": "Error: You have run over your daily request allocation."})
        with patch("weinstein.data.requests.get", return_value=mock_resp):
            with pytest.raises(TiingoRateLimitError) as info:
                download_weekly_tiingo("TST", min_bars=10)
        assert info.value.motivo == "dia"

    def test_dict_sin_mensaje_de_limite_es_sin_datos(self, monkeypatch):
        # Un dict que no habla de límites (p.ej. ticker no encontrado) es
        # "sin datos"; antes rompía en pd.DataFrame(dict de escalares).
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        mock_resp = Mock(status_code=200)
        mock_resp.raise_for_status = Mock()
        mock_resp.json = Mock(return_value={"detail": "Error: Ticker 'GHOST' not found"})
        with patch("weinstein.data.requests.get", return_value=mock_resp):
            assert download_weekly_tiingo("GHOST", min_bars=10) is None
        assert tiingo_block() is None

    def test_tras_el_limite_no_se_vuelve_a_llamar_a_la_api(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        mock_resp = Mock(status_code=429)
        mock_resp.json = Mock(return_value={})
        with patch("weinstein.data.requests.get", return_value=mock_resp) as mock_get:
            with pytest.raises(TiingoRateLimitError):
                download_weekly_tiingo("AAA", min_bars=10)
            for t in ("BBB", "CCC", "DDD"):
                with pytest.raises(TiingoRateLimitError):
                    download_weekly_tiingo(t, min_bars=10)
        assert mock_get.call_count == 1
        assert tiingo_requests_made() == 1
        assert tiingo_block() is not None

    def test_el_bloqueo_caduca_al_abrir_la_siguiente_ventana(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        limitado = Mock(status_code=429)
        limitado.json = Mock(return_value={})
        ok = Mock(status_code=200)
        ok.raise_for_status = Mock()
        ok.json = Mock(return_value=_tiingo_payload_ok(20))
        reloj = [1_000_000.0]
        monkeypatch.setattr(data_mod.time, "time", lambda: reloj[0])
        with patch("weinstein.data.requests.get", side_effect=[limitado, ok]):
            with pytest.raises(TiingoRateLimitError) as info:
                download_weekly_tiingo("AAA", min_bars=10)
            reloj[0] = info.value.bloqueado_hasta + 1
            assert download_weekly_tiingo("AAA", min_bars=10) is not None

    def test_cuenta_peticiones_incluidos_alias(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        no_encontrado = Mock(status_code=404)
        ok = Mock(status_code=200)
        ok.raise_for_status = Mock()
        ok.json = Mock(return_value=_tiingo_payload_ok(20))
        # WLTW -> WTW (alias conocido): 404 + reintento con alias = 2 peticiones.
        with patch("weinstein.data.requests.get", side_effect=[no_encontrado, ok]) as mock_get:
            resultado = download_weekly_tiingo("WLTW", min_bars=10)
        assert resultado is not None
        assert mock_get.call_count == 2
        assert tiingo_requests_made() == 2

    def test_presupuesto_agotado_lanza_sin_hacer_la_peticion(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        ok = Mock(status_code=200)
        ok.raise_for_status = Mock()
        ok.json = Mock(return_value=_tiingo_payload_ok(20))
        set_tiingo_budget(2)
        with patch("weinstein.data.requests.get", return_value=ok) as mock_get:
            download_weekly_tiingo("AAA", min_bars=10)
            download_weekly_tiingo("BBB", min_bars=10)
            with pytest.raises(TiingoBudgetExhaustedError) as info:
                download_weekly_tiingo("CCC", min_bars=10)
        assert mock_get.call_count == 2
        assert info.value.motivo == "presupuesto"
        assert isinstance(info.value, TiingoRateLimitError)

    def test_presupuesto_cortado_a_mitad_de_alias(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
        set_tiingo_budget(1)
        with patch("weinstein.data.requests.get", return_value=Mock(status_code=404)) as mock_get:
            with pytest.raises(TiingoBudgetExhaustedError):
                download_weekly_tiingo("WLTW", min_bars=10)
        assert mock_get.call_count == 1


class TestDownloadWeeklyConLimite:

    def test_por_defecto_el_limite_devuelve_none(self):
        # Escáneres: comportamiento de siempre (None), sin excepción.
        with patch("weinstein.data.yf.download", return_value=pd.DataFrame()):
            with patch("weinstein.data.time.sleep"):
                with patch("weinstein.data.download_weekly_tiingo",
                           side_effect=TiingoRateLimitError("limitado")):
                    assert download_weekly("DELISTED", max_retries=1) is None

    def test_raise_on_rate_limit_propaga(self):
        with patch("weinstein.data.yf.download", return_value=pd.DataFrame()):
            with patch("weinstein.data.time.sleep"):
                with patch("weinstein.data.download_weekly_tiingo",
                           side_effect=TiingoRateLimitError("limitado")):
                    with pytest.raises(TiingoRateLimitError):
                        download_weekly("DELISTED", max_retries=1, raise_on_rate_limit=True)

    def test_use_tiingo_false_no_llama_a_tiingo(self):
        with patch("weinstein.data.yf.download", return_value=pd.DataFrame()):
            with patch("weinstein.data.time.sleep"):
                with patch("weinstein.data.download_weekly_tiingo") as mock_tiingo:
                    assert download_weekly("DELISTED", max_retries=1, use_tiingo=False) is None
        mock_tiingo.assert_not_called()
