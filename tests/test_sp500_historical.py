"""
Tests de `backtest/sp500_historical.py`.

Todo se testea con una tabla de cambios SINTÉTICA construida a mano (sin
red, sin mockear `pd.read_html`... salvo en los tests de parsing), para
poder verificar el algoritmo de reconstrucción con casos exactos y
conocidos.

Convención de la tabla de cambios en los tests: columnas
[Date, Added_Ticker, Removed_Ticker], ya en el formato de salida de
`_parse_changes_table` / `fetch_changes_table`.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from backtest import sp500_historical as sh


def _changes(rows: list[tuple[str, str | None, str | None]]) -> pd.DataFrame:
    """Construye una tabla de cambios ya parseada a partir de tuplas (fecha, added, removed)."""
    return pd.DataFrame({
        "Date": [pd.Timestamp(d) for d, _, _ in rows],
        "Added_Ticker": [a for _, a, _ in rows],
        "Removed_Ticker": [r for _, _, r in rows],
    })


class TestReconstructMembership:

    def test_sin_cambios_devuelve_constituyentes_actuales(self):
        changes = _changes([])
        result = sh.reconstruct_membership(
            pd.Timestamp("2020-01-01"), changes, current_constituents={"AAPL", "MSFT"}
        )
        assert result == {"AAPL", "MSFT"}

    def test_deshace_una_alta_posterior(self):
        """
        Si NVDA se añadió el 2024-06-01, en cualquier fecha ANTERIOR NVDA
        no debía estar en el índice.
        """
        changes = _changes([("2024-06-01", "NVDA", None)])
        result = sh.reconstruct_membership(
            pd.Timestamp("2024-01-01"), changes, current_constituents={"AAPL", "NVDA"}
        )
        assert "NVDA" not in result
        assert "AAPL" in result

    def test_deshace_una_baja_posterior(self):
        """
        Si XYZ se eliminó el 2024-06-01, en cualquier fecha ANTERIOR XYZ
        sí debía estar en el índice (hay que volver a añadirlo).
        """
        changes = _changes([("2024-06-01", None, "XYZ")])
        result = sh.reconstruct_membership(
            pd.Timestamp("2024-01-01"), changes, current_constituents={"AAPL"}
        )
        assert "XYZ" in result
        assert "AAPL" in result

    def test_cambio_en_la_fecha_exacta_no_se_deshace(self):
        """El filtro es estrictamente posterior (`Date > as_of_date`): un
        cambio EFECTIVO en la fecha consultada ya cuenta como vigente."""
        changes = _changes([("2024-06-01", "NVDA", None)])
        result = sh.reconstruct_membership(
            pd.Timestamp("2024-06-01"), changes, current_constituents={"AAPL", "NVDA"}
        )
        assert "NVDA" in result

    def test_reemplazo_1_a_1_en_la_misma_fecha(self):
        """Caso típico: en la misma fecha entra A y sale B (sustitución)."""
        changes = _changes([("2024-06-01", "NEW", "OLD")])
        result = sh.reconstruct_membership(
            pd.Timestamp("2024-01-01"), changes, current_constituents={"NEW"}
        )
        assert result == {"OLD"}

    def test_multiples_cambios_encadenados(self):
        """
        Secuencia: hoy = {C}. 2024-06: entra C, sale B. 2024-01: entra B, sale A.
        En una fecha anterior a AMBOS cambios (2023), debe quedar {A}.
        """
        changes = _changes([
            ("2024-06-01", "C", "B"),
            ("2024-01-01", "B", "A"),
        ])
        result = sh.reconstruct_membership(
            pd.Timestamp("2023-01-01"), changes, current_constituents={"C"}
        )
        assert result == {"A"}

        # Entre los dos cambios (marzo 2024), debe quedar {B}.
        result_mid = sh.reconstruct_membership(
            pd.Timestamp("2024-03-01"), changes, current_constituents={"C"}
        )
        assert result_mid == {"B"}

    def test_quitar_ticker_que_no_esta_en_membership_no_falla(self):
        """Robustez: si el ticker "añadido" en ese cambio ya no está en el
        conjunto actual (por cualquier inconsistencia de datos), no debe
        lanzar KeyError."""
        changes = _changes([("2024-06-01", "GHOST", None)])
        result = sh.reconstruct_membership(
            pd.Timestamp("2024-01-01"), changes, current_constituents={"AAPL"}
        )
        assert result == {"AAPL"}


class TestBuildMembershipCalendar:

    def test_calendario_vacio_sin_fechas(self):
        assert sh.build_membership_calendar([], changes=_changes([]), current_constituents={"AAPL"}) == {}

    def test_coincide_con_reconstruct_membership_fecha_a_fecha(self):
        """El cálculo por lote (una pasada) debe dar EXACTAMENTE el mismo
        resultado que llamar a reconstruct_membership() fecha por fecha."""
        changes = _changes([
            ("2024-09-01", "E", "D"),
            ("2024-06-01", "D", "C"),
            ("2024-03-01", "C", "B"),
            ("2024-01-01", "B", "A"),
        ])
        current = {"E"}
        fechas = [pd.Timestamp(d) for d in
                  ["2023-06-01", "2024-01-15", "2024-04-01", "2024-07-01", "2024-12-01"]]

        calendario = sh.build_membership_calendar(fechas, changes=changes, current_constituents=current)

        for fecha in fechas:
            esperado = sh.reconstruct_membership(fecha, changes, current)
            assert calendario[fecha] == esperado, f"discrepancia en {fecha}"

    def test_no_mira_al_futuro(self):
        """
        Un cambio en 2024-06 no debe afectar en absoluto al snapshot de
        una fecha POSTERIOR a ese cambio (2024-07): el snapshot de fechas
        futuras respecto al cambio ya debe incluirlo tal cual, sin
        "revertirlo" de más ni de menos.
        """
        changes = _changes([("2024-06-01", "NEW", "OLD")])
        current = {"NEW"}
        fechas = [pd.Timestamp("2024-07-01"), pd.Timestamp("2024-01-01")]

        calendario = sh.build_membership_calendar(fechas, changes=changes, current_constituents=current)

        assert calendario[pd.Timestamp("2024-07-01")] == {"NEW"}
        assert calendario[pd.Timestamp("2024-01-01")] == {"OLD"}

    def test_fechas_duplicadas_no_rompen_nada(self):
        changes = _changes([("2024-06-01", "NEW", "OLD")])
        current = {"NEW"}
        fecha = pd.Timestamp("2024-01-01")
        calendario = sh.build_membership_calendar([fecha, fecha], changes=changes, current_constituents=current)
        assert calendario[fecha] == {"OLD"}


class TestUniverseUnion:

    def test_union_de_varios_snapshots(self):
        calendar = {
            pd.Timestamp("2024-01-01"): {"A", "B"},
            pd.Timestamp("2024-06-01"): {"B", "C"},
        }
        assert sh.universe_union(calendar) == {"A", "B", "C"}

    def test_union_vacia(self):
        assert sh.universe_union({}) == set()


class TestNormalizeTicker:

    def test_normaliza_punto_a_guion(self):
        assert sh._normalize_ticker("BRK.B") == "BRK-B"

    def test_recorta_notas_al_pie(self):
        assert sh._normalize_ticker("AAPL[a]") == "AAPL"

    def test_valores_vacios_devuelven_none(self):
        assert sh._normalize_ticker("") is None
        assert sh._normalize_ticker("  ") is None
        assert sh._normalize_ticker("—") is None
        assert sh._normalize_ticker(None) is None

    def test_valor_nan_de_pandas_devuelve_none(self):
        assert sh._normalize_ticker(float("nan")) is None


class TestParseChangesTable:

    def test_esquema_estandar_columnas_agrupadas(self):
        raw = pd.DataFrame({
            "Date": ["June 1, 2024", "January 1, 2024"],
            "Added Ticker": ["NEW", "MID"],
            "Added Security": ["New Co", "Mid Co"],
            "Removed Ticker": ["OLD", "NEW2"],
            "Removed Security": ["Old Co", "New2 Co"],
            "Reason": ["Market cap change", "Acquisition"],
        })
        parsed = sh._parse_changes_table(raw)
        assert list(parsed.columns) == ["Date", "Added_Ticker", "Removed_Ticker"]
        assert set(parsed["Added_Ticker"]) == {"NEW", "MID"}
        assert set(parsed["Removed_Ticker"]) == {"OLD", "NEW2"}
        # Debe quedar ordenado por fecha ascendente.
        assert parsed["Date"].is_monotonic_increasing

    def test_filas_sin_fecha_se_descartan(self):
        raw = pd.DataFrame({
            "Date": ["June 1, 2024", "no-es-una-fecha"],
            "Added Ticker": ["NEW", "XXX"],
            "Removed Ticker": ["OLD", "YYY"],
        })
        parsed = sh._parse_changes_table(raw)
        assert len(parsed) == 1
        assert parsed.iloc[0]["Added_Ticker"] == "NEW"

    def test_fila_solo_con_alta_se_conserva(self):
        raw = pd.DataFrame({
            "Date": ["June 1, 2024"],
            "Added Ticker": ["NEW"],
            "Removed Ticker": [None],
        })
        parsed = sh._parse_changes_table(raw)
        assert len(parsed) == 1
        assert parsed.iloc[0]["Added_Ticker"] == "NEW"
        assert parsed.iloc[0]["Removed_Ticker"] is None

    def test_columna_de_fecha_ausente_lanza_error_explicito(self):
        raw = pd.DataFrame({"Added Ticker": ["NEW"], "Removed Ticker": ["OLD"]})
        with pytest.raises(ValueError, match="fecha"):
            sh._parse_changes_table(raw)


class TestFetchChangesTableCache:

    @pytest.fixture(autouse=True)
    def _clean_cache(self):
        if sh.CHANGES_CACHE_PATH.exists():
            sh.CHANGES_CACHE_PATH.unlink()
        yield
        if sh.CHANGES_CACHE_PATH.exists():
            sh.CHANGES_CACHE_PATH.unlink()

    def test_primera_llamada_descarga_y_cachea(self):
        raw = pd.DataFrame({
            "Date": ["June 1, 2024"],
            "Added Ticker": ["NEW"],
            "Removed Ticker": ["OLD"],
        })
        with patch.object(sh, "_fetch_changes_table_raw", return_value=raw) as mock_fetch:
            result = sh.fetch_changes_table()
        mock_fetch.assert_called_once()
        assert len(result) == 1
        assert sh.CHANGES_CACHE_PATH.exists()

    def test_segunda_llamada_usa_cache(self):
        raw = pd.DataFrame({
            "Date": ["June 1, 2024"],
            "Added Ticker": ["NEW"],
            "Removed Ticker": ["OLD"],
        })
        with patch.object(sh, "_fetch_changes_table_raw", return_value=raw) as mock_fetch:
            sh.fetch_changes_table()
            sh.fetch_changes_table()
        assert mock_fetch.call_count == 1

    def test_refresh_fuerza_redescarga(self):
        raw = pd.DataFrame({
            "Date": ["June 1, 2024"],
            "Added Ticker": ["NEW"],
            "Removed Ticker": ["OLD"],
        })
        with patch.object(sh, "_fetch_changes_table_raw", return_value=raw) as mock_fetch:
            sh.fetch_changes_table()
            sh.fetch_changes_table(refresh=True)
        assert mock_fetch.call_count == 2
