"""
Tests del descargador reanudable `backtest/download_data.py`.

Sin red: se sustituyen `download_weekly` (yfinance) y `download_weekly_tiingo`
por falsos, y la caché + el fichero de estado se redirigen a `tmp_path`
(nunca se toca `backtest/.cache/` real).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import data_cache, download_data
from weinstein import data as wdata
from weinstein.data import TiingoRateLimitError, TiingoUnavailableError, last_closed_friday


@pytest.fixture(autouse=True)
def _aislado(tmp_path, monkeypatch):
    monkeypatch.setattr(data_cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setenv("TIINGO_API_KEY", "fake-token")
    wdata.reset_tiingo_state()
    yield
    wdata.reset_tiingo_state()


def _df(end=None, n=100):
    idx = pd.date_range(end=end or last_closed_friday(), periods=n, freq="W-FRI")
    return pd.DataFrame({
        "Open": 1.0, "High": 1.0, "Low": 1.0,
        "Close": np.linspace(10, 20, n), "Volume": 1000.0,
    }, index=idx)


VIEJO = pd.Timestamp("2021-06-04")


class FakeTiingo:
    """Falso de `download_weekly_tiingo` que cuenta peticiones como el real."""

    def __init__(self, results: dict | None = None, default="df"):
        self.results = results or {}
        self.default = default
        self.calls: list[str] = []

    def __call__(self, ticker, raise_on_error=False, **_kw):
        wdata._reserve_tiingo_request(ticker)  # presupuesto / bloqueo reales
        self.calls.append(ticker)
        r = self.results.get(ticker, self.default)
        if isinstance(r, Exception):
            raise r
        if r == "df":
            return _df(end=VIEJO)
        return None


class Reloj:
    def __init__(self, t0: float = 1_800_000_000.0):
        self.t = t0

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


class TestFaseYfinance:

    def test_descarga_y_deja_pendientes_lo_que_yfinance_no_sirve(self, monkeypatch):
        def fake_yf(ticker, period, use_tiingo=True, **_kw):
            assert use_tiingo is False
            return _df() if ticker in ("AAA", "BBB") else None

        monkeypatch.setattr(wdata, "download_weekly", fake_yf)
        state = download_data.load_state()
        stats = download_data.phase_yfinance(["AAA", "BBB", "OLD"], {"AAA", "BBB"}, "10y", state)
        assert stats["descargados"] == 2
        assert state["periodos"]["10y"]["pendientes_tiingo"] == ["OLD"]
        assert data_cache.cache_status("AAA", "10y") == "ok"
        # Persistido en disco (reanudable).
        assert download_data.load_state()["periodos"]["10y"]["pendientes_tiingo"] == ["OLD"]

    def test_no_repite_yfinance_para_delistados_pendientes_ni_cacheados(self, monkeypatch):
        llamadas: list[str] = []

        def fake_yf(ticker, period, use_tiingo=True, **_kw):
            llamadas.append(ticker)
            return _df() if ticker == "AAA" else None

        monkeypatch.setattr(wdata, "download_weekly", fake_yf)
        state = download_data.load_state()
        download_data.phase_yfinance(["AAA", "OLD"], {"AAA"}, "10y", state)
        llamadas.clear()
        download_data.phase_yfinance(["AAA", "OLD"], {"AAA"}, "10y", download_data.load_state())
        assert llamadas == []


class TestFaseTiingo:

    def _estado_con_pendientes(self, tickers):
        state = download_data.load_state()
        download_data._period_state(state, "10y")["pendientes_tiingo"] = sorted(tickers)
        return state

    def test_respeta_el_presupuesto_horario_y_para_sin_wait(self, monkeypatch):
        fake = FakeTiingo()
        monkeypatch.setattr(wdata, "download_weekly_tiingo", fake)
        reloj = Reloj()
        tickers = [f"T{i}" for i in range(5)]
        state = self._estado_con_pendientes(tickers)
        stats = download_data.phase_tiingo(tickers, set(), "10y", state, budget=3,
                                           clock=reloj, sleep=reloj.sleep)
        assert len(fake.calls) == 3
        assert stats["parada"] == "presupuesto"
        assert stats["reanudar_en"] is not None
        assert state["tiingo"]["peticiones_hora"] == 3
        assert len(state["periodos"]["10y"]["pendientes_tiingo"]) == 2
        assert data_cache.cache_stats()["n_fallos_cacheados"] == 0

        # Otra ejecución en la MISMA hora no gasta nada (cupo compartido vía estado).
        fake.calls.clear()
        download_data.phase_tiingo(tickers, set(), "10y", download_data.load_state(), budget=3,
                                   clock=reloj, sleep=reloj.sleep)
        assert fake.calls == []

    def test_con_wait_duerme_entre_ventanas_hasta_terminar(self, monkeypatch):
        fake = FakeTiingo()
        monkeypatch.setattr(wdata, "download_weekly_tiingo", fake)
        reloj = Reloj()
        tickers = [f"T{i}" for i in range(5)]
        state = self._estado_con_pendientes(tickers)
        stats = download_data.phase_tiingo(tickers, set(), "10y", state, budget=2, wait=True,
                                           clock=reloj, sleep=reloj.sleep)
        assert stats["parada"] == "completado"
        assert sorted(fake.calls) == tickers
        assert reloj.t - 1_800_000_000.0 >= 2 * 3600  # dos esperas de ventana (3 ventanas)
        assert state["periodos"]["10y"]["pendientes_tiingo"] == []
        assert sorted(state["periodos"]["10y"]["via_tiingo"]) == tickers

    def test_limite_de_tiingo_no_marca_nodata_y_bloquea(self, monkeypatch):
        reloj = Reloj()
        limite = TiingoRateLimitError("limitado", motivo="hora", bloqueado_hasta=reloj.t + 600)
        fake = FakeTiingo({"T1": limite})
        monkeypatch.setattr(wdata, "download_weekly_tiingo", fake)
        tickers = ["T0", "T1", "T2"]
        state = self._estado_con_pendientes(tickers)
        stats = download_data.phase_tiingo(tickers, set(), "10y", state, budget=45,
                                           clock=reloj, sleep=reloj.sleep)
        assert fake.calls == ["T0", "T1"]
        assert stats["parada"] == "limite"
        assert state["tiingo"]["bloqueado_hasta"] == reloj.t + 600
        assert state["periodos"]["10y"]["pendientes_tiingo"] == ["T1", "T2"]
        assert data_cache.cache_stats()["n_fallos_cacheados"] == 0

    def test_sin_datos_marca_nodata_solo_para_delistados(self, monkeypatch):
        fake = FakeTiingo({"OLD": None, "CUR": None})
        monkeypatch.setattr(wdata, "download_weekly_tiingo", fake)
        reloj = Reloj()
        state = self._estado_con_pendientes(["OLD", "CUR"])
        download_data.phase_tiingo(["OLD", "CUR"], {"CUR"}, "10y", state, clock=reloj, sleep=reloj.sleep)
        assert data_cache.cache_status("OLD", "10y", is_current_constituent=False) == "nodata"
        assert data_cache.cache_stats()["n_fallos_cacheados"] == 1
        ps = state["periodos"]["10y"]
        assert ps["vigentes_sin_datos"] == {"CUR": str(last_closed_friday().date())}
        # El vigente no se reintenta en la misma semana.
        fake.calls.clear()
        download_data.phase_tiingo(["OLD", "CUR"], {"CUR"}, "10y", state, clock=reloj, sleep=reloj.sleep)
        assert fake.calls == []

    def test_error_transitorio_deja_pendiente_sin_nodata(self, monkeypatch):
        fake = FakeTiingo({"T0": TiingoUnavailableError("red", motivo="red")})
        monkeypatch.setattr(wdata, "download_weekly_tiingo", fake)
        reloj = Reloj()
        state = self._estado_con_pendientes(["T0", "T1"])
        download_data.phase_tiingo(["T0", "T1"], set(), "10y", state, clock=reloj, sleep=reloj.sleep)
        assert state["periodos"]["10y"]["pendientes_tiingo"] == ["T0"]
        assert data_cache.cache_stats()["n_fallos_cacheados"] == 0
        assert data_cache.cache_status("T1", "10y", is_current_constituent=False) == "ok"

    def test_alias_que_no_cabe_espera_a_la_siguiente_ventana(self, monkeypatch):
        fake = FakeTiingo()
        monkeypatch.setattr(wdata, "download_weekly_tiingo", fake)
        reloj = Reloj()
        # WLTW tiene alias conocido (necesita 2 peticiones); con presupuesto 1
        # se salta y no se entra en un bucle sin progreso.
        state = self._estado_con_pendientes(["WLTW"])
        stats = download_data.phase_tiingo(["WLTW"], set(), "10y", state, budget=1,
                                           clock=reloj, sleep=reloj.sleep)
        assert fake.calls == []
        assert stats["parada"] == "presupuesto"

    def test_sin_api_key_no_llama_y_no_marca(self, monkeypatch):
        monkeypatch.delenv("TIINGO_API_KEY", raising=False)
        fake = FakeTiingo()
        monkeypatch.setattr(wdata, "download_weekly_tiingo", fake)
        state = self._estado_con_pendientes(["OLD"])
        stats = download_data.phase_tiingo(["OLD"], set(), "10y", state)
        assert stats["parada"] == "sin_api_key"
        assert fake.calls == []
        assert data_cache.cache_stats()["n_fallos_cacheados"] == 0


class TestCobertura:

    def test_clasifica_yfinance_tiingo_sin_datos_y_pendientes(self, monkeypatch):
        state = download_data.load_state()
        ps = download_data._period_state(state, "10y")
        data_cache.save_cached("YF", "10y", _df())
        data_cache.save_cached("TI", "10y", _df(end=VIEJO))
        ps["via_tiingo"] = ["TI"]
        data_cache.mark_nodata("NO", "10y")
        ps["pendientes_tiingo"] = ["PE"]
        rep = download_data.coverage(["YF", "TI", "NO", "PE"], {"YF"}, "10y", state)
        assert rep == {"yfinance": ["YF"], "tiingo": ["TI"], "sin_datos": ["NO"], "pendientes": ["PE"]}

    def test_comando_de_reanudacion(self):
        cmd = download_data.resume_command("10y", "historical", 45, download_data.DEFAULT_TIINGO_DAILY_BUDGET, True)
        assert cmd == "python -m backtest.download_data --period 10y --universe historical --tiingo-budget 45 --wait"

    def test_estado_se_guarda_en_cache_dir_redirigido(self, tmp_path):
        download_data.save_state(download_data.load_state())
        assert (tmp_path / "cache" / download_data.STATE_FILENAME).exists()
