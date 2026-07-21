"""
Tests de `weinstein/config.py::resolve_historical_sector` y del mapeo
`HISTORICAL_DELISTED_SECTORS`.

Cubre la mitigación del sesgo de sector "Unknown" en el universo
histórico del backtest de cartera (ver docstring de
`backtest/portfolio_backtest.py`, sección "Sesgo de sector Unknown en
universo histórico", para el problema completo y las cifras empíricas
que lo motivaron).

`resolve_historical_sector` es una función pura (dos dicts -> str), así
que se testea directamente sin red ni mocks.
"""

from __future__ import annotations

from weinstein.config import (
    HISTORICAL_DELISTED_SECTORS,
    resolve_historical_sector,
    resolve_sector_etf,
)


class TestResolveHistoricalSector:

    def test_ticker_en_constituyentes_actuales_usa_ese_sector(self):
        """Prioridad 1: si el ticker sigue vigente hoy, se usa su sector actual,
        aunque también aparezca (por error) en el mapeo manual de delistados."""
        current_map = {"AAPL": "Information Technology"}
        assert resolve_historical_sector("AAPL", current_map) == "Information Technology"

    def test_ticker_delistado_con_mapeo_manual_lo_resuelve(self):
        """Prioridad 2: ticker que ya no está en constituyentes actuales,
        pero sí en HISTORICAL_DELISTED_SECTORS."""
        current_map = {"AAPL": "Information Technology"}
        assert resolve_historical_sector("CELG", current_map) == "Health Care"
        assert resolve_historical_sector("XLNX", current_map) == "Information Technology"
        assert resolve_historical_sector("TWTR", current_map) == "Communication Services"

    def test_ticker_no_cubierto_por_ninguna_fuente_da_unknown(self):
        """Prioridad 3: ni constituyentes actuales ni mapeo manual -> Unknown
        (mismo comportamiento que antes de la mitigación, pero ahora solo
        para el residuo no cubierto)."""
        current_map = {"AAPL": "Information Technology"}
        assert resolve_historical_sector("GHOSTCO", current_map) == "Unknown"

    def test_mapeo_manual_no_se_usa_si_el_ticker_esta_vigente(self):
        """Caso borde: un símbolo que por error estuviera en ambos mapeos
        debe resolver por el mapeo ACTUAL (más fiable), no por el manual."""
        current_map = {"XLNX": "Some Other Sector"}
        assert resolve_historical_sector("XLNX", current_map) == "Some Other Sector"

    def test_todas_las_entradas_del_mapeo_manual_resuelven_a_un_etf_valido(self):
        """
        Cada sector del mapeo manual debe ser un nombre GICS reconocido
        por `resolve_sector_etf` (o su alias) — si no, la entrada manual
        no serviría de nada porque F1 seguiría sin poder evaluarse.
        """
        for symbol, sector in HISTORICAL_DELISTED_SECTORS.items():
            etf = resolve_sector_etf(sector)
            assert etf is not None, (
                f"El sector '{sector}' asignado a '{symbol}' en "
                "HISTORICAL_DELISTED_SECTORS no resuelve a ningún ETF "
                "sectorial (revisa el nombre GICS)."
            )

    def test_mapeo_manual_no_esta_vacio(self):
        """Guard-rail básico: si alguien vacía el diccionario por error,
        que un test falle en vez de degradar en silencio a 'todo Unknown'."""
        assert len(HISTORICAL_DELISTED_SECTORS) > 0
