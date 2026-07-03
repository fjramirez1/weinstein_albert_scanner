"""
Tests de `weinstein/data.py`.

- `load_positions` se testea directamente contra CSVs temporales (no hay red).
- `download_weekly` y `load_sp500_tickers` se testean MOCKEANDO yfinance /
  pandas.read_csv, para que la suite por defecto no dependa de red.
- Además se incluyen tests opcionales que SÍ golpean la red real, marcados
  con `@pytest.mark.network` y excluidos de la ejecución por defecto
  (ver pytest.ini). Se pueden lanzar explícitamente con:

      pytest -m network
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from weinstein.data import download_weekly, load_positions, load_sp500_tickers


# ── load_positions ───────────────────────────────────────────────────

class TestLoadPositions:

    def test_csv_valido_se_carga_y_normaliza(self, tmp_path):
        csv = tmp_path / "posiciones.csv"
        pd.DataFrame({
            "Ticker": ["xom", " cvx"],
            "Sector": ["Energy", "Energy"],
            "Precio_Entrada": ["154.08", "192.79"],
            "Fecha_Entrada": ["2026-05-26", "2026-05-18"],
        }).to_csv(csv, index=False)

        df = load_positions(str(csv))

        assert list(df["Ticker"]) == ["XOM", "CVX"]
        assert df["Precio_Entrada"].tolist() == [154.08, 192.79]
        assert pd.api.types.is_datetime64_any_dtype(df["Fecha_Entrada"])

    def test_columnas_faltantes_aborta_con_sys_exit(self, tmp_path):
        csv = tmp_path / "incompleto.csv"
        pd.DataFrame({"Ticker": ["XOM"], "Sector": ["Energy"]}).to_csv(csv, index=False)

        with pytest.raises(SystemExit) as exc_info:
            load_positions(str(csv))
        assert exc_info.value.code == 1

    def test_archivo_inexistente_aborta_con_sys_exit(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            load_positions(str(tmp_path / "no_existe.csv"))
        assert exc_info.value.code == 1

    def test_filas_con_datos_invalidos_se_descartan(self, tmp_path):
        csv = tmp_path / "posiciones.csv"
        pd.DataFrame({
            "Ticker": ["XOM", "CVX"],
            "Sector": ["Energy", "Energy"],
            "Precio_Entrada": ["154.08", "no-es-un-numero"],
            "Fecha_Entrada": ["2026-05-26", "2026-05-18"],
        }).to_csv(csv, index=False)

        df = load_positions(str(csv))

        assert len(df) == 1
        assert df.iloc[0]["Ticker"] == "XOM"


# ── download_weekly (mockeando yfinance) ───────────────────────────────

class TestDownloadWeeklyMocked:

    def test_descarga_valida_devuelve_dataframe_normalizado(self):
        idx = pd.date_range("2020-01-06", periods=100, freq="W")
        raw = pd.DataFrame({
            "Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 100,
        }, index=idx)

        with patch("weinstein.data.yf.download", return_value=raw):
            resultado = download_weekly("TST")

        assert resultado is not None
        assert list(resultado.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert len(resultado) == 100

    def test_historico_insuficiente_devuelve_none(self):
        idx = pd.date_range("2020-01-06", periods=10, freq="W")  # por debajo de MIN_BARS
        raw = pd.DataFrame({"Close": 1.0}, index=idx)

        with patch("weinstein.data.yf.download", return_value=raw):
            resultado = download_weekly("TST")

        assert resultado is None

    def test_dataframe_vacio_devuelve_none(self):
        with patch("weinstein.data.yf.download", return_value=pd.DataFrame()):
            resultado = download_weekly("TST")
        assert resultado is None

    def test_excepcion_en_descarga_devuelve_none(self):
        with patch("weinstein.data.yf.download", side_effect=Exception("network error")):
            resultado = download_weekly("TST")
        assert resultado is None

    def test_multiindex_de_columnas_se_normaliza(self):
        idx = pd.date_range("2020-01-06", periods=100, freq="W")
        raw = pd.DataFrame({
            "Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 100,
        }, index=idx)
        raw.columns = pd.MultiIndex.from_product([raw.columns, ["TST"]])

        with patch("weinstein.data.yf.download", return_value=raw):
            resultado = download_weekly("TST")

        assert resultado is not None
        assert "Close" in resultado.columns


# ── load_sp500_tickers (mockeando pandas.read_csv) ────────────────────

class TestLoadSP500TickersMocked:

    def test_fuente_primaria_ok_normaliza_columnas(self):
        raw = pd.DataFrame({
            "Symbol": ["AAPL", "MSFT"],
            "Name": ["Apple", "Microsoft"],
            "Sector": ["Technology", "Technology"],
        })
        with patch("weinstein.data.pd.read_csv", return_value=raw):
            df = load_sp500_tickers()

        assert list(df.columns) == ["Symbol", "Name", "Sector"]
        assert len(df) == 2

    def test_fallback_a_wikipedia_si_falla_la_fuente_primaria(self):
        raw_wiki = pd.DataFrame({
            "Symbol": ["AAPL"],
            "Security": ["Apple"],
            "GICS Sector": ["Technology"],
        })
        with patch("weinstein.data.pd.read_csv", side_effect=Exception("fuente caída")):
            with patch("weinstein.data.pd.read_html", return_value=[raw_wiki]):
                df = load_sp500_tickers()

        assert list(df.columns) == ["Symbol", "Name", "Sector"]
        assert df.iloc[0]["Symbol"] == "AAPL"

    def test_si_ambas_fuentes_fallan_aborta_con_sys_exit(self):
        with patch("weinstein.data.pd.read_csv", side_effect=Exception("fuente caída")):
            with patch("weinstein.data.pd.read_html", side_effect=Exception("wikipedia caída")):
                with pytest.raises(SystemExit):
                    load_sp500_tickers()


# ── Tests opcionales de red real (excluidos por defecto, ver pytest.ini) ──

@pytest.mark.network
class TestRedReal:
    """
    Estos tests golpean servicios externos reales (yfinance, GitHub/Wikipedia).
    No se ejecutan por defecto; lanzarlos explícitamente con `pytest -m network`.
    Sirven como smoke test de que las fuentes externas siguen respondiendo
    con el formato esperado, no como verificación de la lógica de negocio.
    """

    def test_descarga_real_de_un_ticker_conocido(self):
        resultado = download_weekly("AAPL", period="2y")
        assert resultado is not None
        assert "Close" in resultado.columns
        assert len(resultado) > 0

    def test_carga_real_de_constituyentes_sp500(self):
        df = load_sp500_tickers()
        assert len(df) > 400  # el S&P 500 ronda ese tamaño, con margen por clases múltiples
        assert {"Symbol", "Name", "Sector"}.issubset(df.columns)
