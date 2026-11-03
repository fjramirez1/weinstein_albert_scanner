"""
Varias API keys de Tiingo: cada clave tiene su propio contador y bloqueo, un
límite en una se reintenta con otra y el proceso solo se bloquea cuando lo
están todas. Todo mockeado, sin red.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pandas as pd
import pytest

import weinstein.data as wdata
from backtest import data_cache, download_data
from tests.test_download_data import FakeTiingo, Reloj
from weinstein.data import TiingoRateLimitError


@pytest.fixture(autouse=True)
def _estado_limpio(tmp_path, monkeypatch):
    monkeypatch.setattr(data_cache, "CACHE_DIR", tmp_path / "cache")
    wdata.reset_tiingo_state()
    yield
    wdata.reset_tiingo_state()


def _dos_claves(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "clave-a")
    monkeypatch.setenv("TIINGO_API_KEY_2", "clave-b")


def _ok(n=100):
    base = pd.Timestamp("2020-01-06")
    payload = [{"date": (base + pd.Timedelta(weeks=i)).strftime("%Y-%m-%dT00:00:00.000Z"),
                "adjOpen": 1.0, "adjHigh": 1.0, "adjLow": 1.0, "adjClose": 1.0, "adjVolume": 1.0}
               for i in range(n)]
    return Mock(status_code=200, json=Mock(return_value=payload), raise_for_status=Mock())


def _limite():
    return Mock(status_code=429, json=Mock(return_value={"detail": "You have run over your hourly request allocation"}))


def _token_usado(mock_get, n):
    return mock_get.call_args_list[n].kwargs["params"]["token"]


class TestLecturaDeClaves:

    def test_combina_variables_sin_duplicados(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEYS", "k1, k2")
        monkeypatch.setenv("TIINGO_API_KEY", "k1")
        monkeypatch.setenv("TIINGO_API_KEY_2", "k3")
        assert wdata._tiingo_api_keys() == ["k1", "k2", "k3"]
        assert wdata.tiingo_key_count() == 3

    def test_sin_claves(self):
        assert wdata._tiingo_api_keys() == []
        assert wdata._tiingo_api_key() is None


class TestRotacion:

    def test_reparte_las_peticiones_entre_claves(self, monkeypatch):
        _dos_claves(monkeypatch)
        with patch("weinstein.data.requests.get", side_effect=[_ok() for _ in range(4)]) as mock_get:
            for t in ("A", "B", "C", "D"):
                assert wdata.download_weekly_tiingo(t) is not None
        tokens = [_token_usado(mock_get, i) for i in range(4)]
        assert tokens == ["clave-a", "clave-b", "clave-a", "clave-b"]
        assert wdata.tiingo_requests_by_key() == {1: 2, 2: 2}

    def test_limite_en_una_clave_reintenta_con_la_otra(self, monkeypatch, capsys):
        _dos_claves(monkeypatch)
        with patch("weinstein.data.requests.get", side_effect=[_limite(), _ok()]) as mock_get:
            df = wdata.download_weekly_tiingo("A")
        assert df is not None
        assert [_token_usado(mock_get, i) for i in range(2)] == ["clave-a", "clave-b"]
        assert wdata.tiingo_block() is None  # queda la clave 2
        err = capsys.readouterr().err
        assert "clave 1" in err and "clave-a" not in err  # nunca se imprime la clave

    def test_clave_limitada_no_se_vuelve_a_usar(self, monkeypatch):
        _dos_claves(monkeypatch)
        with patch("weinstein.data.requests.get", side_effect=[_limite(), _ok(), _ok()]) as mock_get:
            wdata.download_weekly_tiingo("A")
            wdata.download_weekly_tiingo("B")
        assert _token_usado(mock_get, 2) == "clave-b"

    def test_todas_limitadas_lanza_y_bloquea(self, monkeypatch):
        _dos_claves(monkeypatch)
        with patch("weinstein.data.requests.get", side_effect=[_limite(), _limite()]) as mock_get:
            with pytest.raises(TiingoRateLimitError):
                wdata.download_weekly_tiingo("A")
            assert wdata.tiingo_block() is not None
            with pytest.raises(TiingoRateLimitError):
                wdata.download_weekly_tiingo("B")
        assert mock_get.call_count == 2  # tras bloquear ambas, no se toca la red

    def test_token_invalido_en_una_clave_usa_la_otra(self, monkeypatch):
        _dos_claves(monkeypatch)
        no_autorizado = Mock(status_code=401, json=Mock(return_value={"detail": "Invalid token"}))
        with patch("weinstein.data.requests.get", side_effect=[no_autorizado, _ok()]):
            assert wdata.download_weekly_tiingo("A") is not None


class TestDescargadorConVariasClaves:

    def test_presupuesto_horario_se_multiplica_por_clave(self, monkeypatch):
        _dos_claves(monkeypatch)
        fake = FakeTiingo()
        monkeypatch.setattr(wdata, "download_weekly_tiingo", fake)
        reloj = Reloj()
        tickers = [f"T{i}" for i in range(5)]
        state = download_data.load_state()
        download_data._period_state(state, "10y")["pendientes_tiingo"] = sorted(tickers)
        stats = download_data.phase_tiingo(tickers, set(), "10y", state, budget=2,
                                           clock=reloj, sleep=reloj.sleep)
        assert len(fake.calls) == 4  # 2 por clave
        assert stats["parada"] == "presupuesto"


class TestSinTopePropio:
    """Por defecto manda la respuesta de límite de Tiingo, no nuestro contador."""

    def _estado(self, tickers):
        state = download_data.load_state()
        download_data._period_state(state, "10y")["pendientes_tiingo"] = sorted(tickers)
        return state

    def test_sin_limite_de_tiingo_descarga_todo_aunque_pase_de_45(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "clave-a")
        fake = FakeTiingo()
        monkeypatch.setattr(wdata, "download_weekly_tiingo", fake)
        reloj = Reloj()
        tickers = [f"T{i:02d}" for i in range(60)]
        stats = download_data.phase_tiingo(tickers, set(), "10y", self._estado(tickers),
                                           clock=reloj, sleep=reloj.sleep)
        assert len(fake.calls) == 60
        assert stats["parada"] == "completado"

    def test_para_solo_con_el_limite_real_y_reintenta_a_los_minutos(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "clave-a")
        reloj = Reloj(t0=1_800_000_000.0 + 120)  # 2 min después de una hora en punto
        llamadas = []

        def fake(ticker, raise_on_error=False, **_kw):
            llamadas.append((ticker, reloj()))
            if len(llamadas) == 3:  # Tiingo limita la tercera petición
                raise TiingoRateLimitError("límite", motivo="hora",
                                           bloqueado_hasta=reloj() + wdata.TIINGO_LIMIT_RETRY_S)
            from tests.test_download_data import _df, VIEJO
            return _df(end=VIEJO)

        monkeypatch.setattr(wdata, "download_weekly_tiingo", fake)
        tickers = [f"T{i}" for i in range(5)]
        stats = download_data.phase_tiingo(tickers, set(), "10y", self._estado(tickers),
                                           wait=True, clock=reloj, sleep=reloj.sleep)
        assert stats["parada"] == "completado"
        espera = llamadas[3][1] - llamadas[2][1]
        assert espera == pytest.approx(wdata.TIINGO_LIMIT_RETRY_S, abs=1)  # no hasta la hora en punto
        assert data_cache.cache_stats()["n_fallos_cacheados"] == 0

    def test_limite_horario_real_bloquea_la_clave_unos_minutos(self, monkeypatch):
        monkeypatch.setenv("TIINGO_API_KEY", "clave-a")
        t0 = 1_800_000_000.0 + 120
        monkeypatch.setattr(wdata.time, "time", lambda: t0)
        with patch("weinstein.data.requests.get", return_value=_limite()):
            with pytest.raises(TiingoRateLimitError) as exc:
                wdata.download_weekly_tiingo("A")
        assert exc.value.bloqueado_hasta == pytest.approx(t0 + wdata.TIINGO_LIMIT_RETRY_S)
