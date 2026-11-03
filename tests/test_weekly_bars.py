"""
Tests de la normalización de velas semanales (`weinstein/data.py`):

- B1: yfinance (lunes) y Tiingo (viernes) deben acabar con la misma
  etiqueta de fecha para poder cruzarse en el backtest.
- B3: la vela de la semana en curso, aún sin cerrar, se descarta.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd

from backtest.conditions import build_ticker_context
from weinstein.data import download_weekly, last_closed_friday, normalize_weekly_bars

NOW = pd.Timestamp("2026-11-03 12:00")  # martes


def _ohlcv(index: pd.DatetimeIndex, close=None) -> pd.DataFrame:
    n = len(index)
    close = np.linspace(100, 150, n) if close is None else close
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "Open": close, "High": close, "Low": close, "Close": close,
        "Volume": 1000 + rng.normal(0, 50, n),
    }, index=index)


class TestLastClosedFriday:

    def test_entre_semana_devuelve_viernes_anterior(self):
        assert last_closed_friday(NOW) == pd.Timestamp("2026-10-30")

    def test_viernes_antes_del_cierre_devuelve_semana_anterior(self):
        assert last_closed_friday(pd.Timestamp("2026-10-30 15:00")) == pd.Timestamp("2026-10-23")

    def test_viernes_tras_el_cierre_devuelve_ese_viernes(self):
        assert last_closed_friday(pd.Timestamp("2026-10-30 17:00")) == pd.Timestamp("2026-10-30")

    def test_fin_de_semana_devuelve_viernes_previo(self):
        assert last_closed_friday(pd.Timestamp("2026-11-01 09:00")) == pd.Timestamp("2026-10-30")

    def test_respeta_zona_horaria(self):
        # 30-oct-2026: Madrid ya en UTC+1, Nueva York aún en UTC-4 → 21:00 Madrid = 16:00 NY (< 16:30)
        madrid = pd.Timestamp("2026-10-30 21:00", tz="Europe/Madrid")
        assert last_closed_friday(madrid) == pd.Timestamp("2026-10-23")


class TestNormalizeWeeklyBars:

    def test_lunes_y_viernes_quedan_con_la_misma_fecha(self):
        lunes = pd.date_range("2025-01-06", periods=10, freq="W-MON")
        viernes = pd.date_range("2025-01-10", periods=10, freq="W-FRI")
        a = normalize_weekly_bars(_ohlcv(lunes), now=NOW)
        b = normalize_weekly_bars(_ohlcv(viernes), now=NOW)
        assert a.index.equals(b.index)
        assert (a.index.weekday == 4).all()

    def test_descarta_semana_en_curso(self):
        idx = pd.date_range("2026-10-05", "2026-11-02", freq="W-MON")  # último lunes = semana actual
        out = normalize_weekly_bars(_ohlcv(idx), now=NOW)
        assert out.index[-1] == pd.Timestamp("2026-10-30")
        assert len(out) == len(idx) - 1

    def test_duplicados_misma_semana_se_queda_el_ultimo(self):
        idx = pd.DatetimeIndex(["2025-03-03", "2025-03-05"])  # lunes y miércoles
        df = pd.DataFrame({"Close": [1.0, 2.0]}, index=idx)
        out = normalize_weekly_bars(df, now=NOW)
        assert len(out) == 1
        assert out["Close"].iloc[0] == 2.0

    def test_idempotente(self):
        idx = pd.date_range("2025-01-06", periods=10, freq="W-MON")
        once = normalize_weekly_bars(_ohlcv(idx), now=NOW)
        twice = normalize_weekly_bars(once, now=NOW)
        pd.testing.assert_frame_equal(once, twice)

    def test_indice_con_zona_horaria(self):
        idx = pd.date_range("2025-01-06", periods=5, freq="W-MON", tz="UTC")
        out = normalize_weekly_bars(_ohlcv(idx), now=NOW)
        assert out.index.tz is None
        assert (out.index.weekday == 4).all()


class TestSerieTiingoCruzaConSP500:
    """Regresión de B1: antes una serie en viernes no tenía RSC contra un S&P 500 en lunes."""

    def test_rsc_activo_calculable_con_fuentes_mezcladas(self):
        sp500 = normalize_weekly_bars(_ohlcv(pd.date_range("2022-01-03", periods=150, freq="W-MON")), now=NOW)
        tiingo = normalize_weekly_bars(_ohlcv(pd.date_range("2022-01-07", periods=150, freq="W-FRI"),
                                              close=np.linspace(50, 120, 150)), now=NOW)
        ctx = build_ticker_context("OLD", "Energy", tiingo, sp500["Close"], None)
        assert ctx is not None
        assert ctx.rsc_activo.notna().sum() > 50
        assert ctx.close.index.isin(sp500.index).all()


class TestDownloadWeeklyAplicaNormalizacion:

    def test_yfinance_lunes_sale_en_viernes(self):
        idx = pd.date_range("2020-01-06", periods=100, freq="W-MON")
        with patch("weinstein.data.yf.download", return_value=_ohlcv(idx)):
            out = download_weekly("TST")
        assert (out.index.weekday == 4).all()
