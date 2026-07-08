"""
Tests de `weinstein/scanner_exit.py`.

`_evaluate_exit` mezcla lógica pura con I/O (descarga vía `download_weekly`),
así que se mockea la descarga para testear las condiciones OR de salida
(S1: RSC activo < -0.5, S2: Coppock bajista) de forma aislada.

`_worker_exit` se testea aparte para cubrir el cálculo de Rentabilidad %,
incluido el caso de `Precio_Entrada == 0` (bug 5).

Nota sobre el parámetro `coppock_bearish`
------------------------------------------
Antes de la corrección de S2 (ver docstring en scanner_exit.py), este
parámetro se llamaba `coppock_not_bull` y representaba `not
sp500_alcista(...)`. Ahora representa `sp500_bajista(...)`, una condición
propia fiel a la fuente original de la estrategia. A nivel de estos tests
(que ya reciben el booleano directamente, sin calcularlo) el cambio es
solo de nombre, pero es importante no confundirlo: `coppock_bearish=False`
ya no significa "el mercado es alcista", significa "el mercado no está en
fase bajista confirmada" (puede estar en el tercer estado neutro).
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from tests.conftest import weekly_index
from weinstein import scanner_exit

N = 90


@pytest.fixture
def sp500_close_base() -> pd.Series:
    return pd.Series(np.linspace(100, 110, N), index=weekly_index(N))


@pytest.fixture
def fecha_entrada() -> pd.Timestamp:
    return weekly_index(N)[10]


class TestEvaluateExit:

    def test_s1_activo_debil_activa_salida(self, sp500_close_base, fecha_entrada):
        idx = weekly_index(N)
        close_debil = pd.Series(np.linspace(100, 90, N), index=idx)  # cae mientras el benchmark sube
        df = pd.DataFrame({"Close": close_debil})

        with patch.object(scanner_exit, "download_weekly", return_value=df):
            resultado = scanner_exit._evaluate_exit(
                "TST", fecha_entrada, sp500_close_base, coppock_bearish=False
            )

        assert resultado["SALIDA"] is True
        assert resultado["S1 RSC < -0.5"] is True
        assert "S1" in resultado["Motivo"]
        assert "S2" not in resultado["Motivo"]

    def test_s2_mercado_bajista_activa_salida_pese_a_rsc_bueno(self, sp500_close_base, fecha_entrada):
        idx = weekly_index(N)
        close_fuerte = pd.Series(np.linspace(100, 200, N), index=idx)  # RSC muy positivo
        df = pd.DataFrame({"Close": close_fuerte})

        with patch.object(scanner_exit, "download_weekly", return_value=df):
            resultado = scanner_exit._evaluate_exit(
                "TST", fecha_entrada, sp500_close_base, coppock_bearish=True
            )

        assert resultado["SALIDA"] is True
        assert resultado["S1 RSC < -0.5"] is False
        assert "S2" in resultado["Motivo"]
        assert "S1" not in resultado["Motivo"]

    def test_ambas_condiciones_activas_incluyen_los_dos_motivos(self, sp500_close_base, fecha_entrada):
        idx = weekly_index(N)
        close_debil = pd.Series(np.linspace(100, 90, N), index=idx)
        df = pd.DataFrame({"Close": close_debil})

        with patch.object(scanner_exit, "download_weekly", return_value=df):
            resultado = scanner_exit._evaluate_exit(
                "TST", fecha_entrada, sp500_close_base, coppock_bearish=True
            )

        assert resultado["SALIDA"] is True
        assert "S1" in resultado["Motivo"]
        assert "S2" in resultado["Motivo"]

    def test_ninguna_condicion_mantiene_la_posicion(self, sp500_close_base, fecha_entrada):
        idx = weekly_index(N)
        close_fuerte = pd.Series(np.linspace(100, 200, N), index=idx)
        df = pd.DataFrame({"Close": close_fuerte})

        with patch.object(scanner_exit, "download_weekly", return_value=df):
            resultado = scanner_exit._evaluate_exit(
                "TST", fecha_entrada, sp500_close_base, coppock_bearish=False
            )

        assert resultado["SALIDA"] is False
        assert resultado["Motivo"] == "—"

    def test_motivo_es_siempre_string_nunca_lista(self, sp500_close_base, fecha_entrada):
        """El campo Motivo no debe quedar como lista intermedia en ningún camino de retorno."""
        idx = weekly_index(N)
        close_fuerte = pd.Series(np.linspace(100, 200, N), index=idx)
        df = pd.DataFrame({"Close": close_fuerte})

        with patch.object(scanner_exit, "download_weekly", return_value=df):
            resultado = scanner_exit._evaluate_exit(
                "TST", fecha_entrada, sp500_close_base, coppock_bearish=False
            )
        assert isinstance(resultado["Motivo"], str)

        with patch.object(scanner_exit, "download_weekly", return_value=None):
            resultado_sin_datos = scanner_exit._evaluate_exit(
                "TST", fecha_entrada, sp500_close_base, coppock_bearish=True
            )
        assert isinstance(resultado_sin_datos["Motivo"], str)

    def test_sin_datos_y_mercado_bajista_activa_salida_por_s2(self, sp500_close_base, fecha_entrada):
        """Aunque falle la descarga, S2 (conocido de antemano) puede bastar para activar SALIDA."""
        with patch.object(scanner_exit, "download_weekly", return_value=None):
            resultado = scanner_exit._evaluate_exit(
                "TST", fecha_entrada, sp500_close_base, coppock_bearish=True
            )

        assert resultado["SALIDA"] is True
        assert resultado["Error"] is not None
        assert "S2" in resultado["Motivo"]

    def test_sin_datos_y_mercado_no_bajista_no_activa_salida(self, sp500_close_base, fecha_entrada):
        with patch.object(scanner_exit, "download_weekly", return_value=None):
            resultado = scanner_exit._evaluate_exit(
                "TST", fecha_entrada, sp500_close_base, coppock_bearish=False
            )

        assert resultado["SALIDA"] is False
        assert resultado["Error"] is not None
        assert resultado["Motivo"] == "—"

    def test_precio_actual_se_calcula_desde_la_fecha_de_entrada(self, sp500_close_base, fecha_entrada):
        idx = weekly_index(N)
        close = pd.Series(np.linspace(100, 200, N), index=idx)
        df = pd.DataFrame({"Close": close})

        with patch.object(scanner_exit, "download_weekly", return_value=df):
            resultado = scanner_exit._evaluate_exit(
                "TST", fecha_entrada, sp500_close_base, coppock_bearish=False
            )

        precio_esperado = round(float(close.loc[close.index >= fecha_entrada].iloc[-1]), 2)
        assert resultado["Precio Actual"] == precio_esperado


class TestWorkerExitRentabilidad:
    """
    Cubre el cálculo de Rentabilidad % en `_worker_exit`, incluyendo el
    bug 5: `Precio_Entrada == 0` se trataba como "sin precio de entrada"
    (falsy) y la rentabilidad se omitía en silencio sin dejar rastro.
    """

    def _fila(self, precio_entrada) -> pd.Series:
        return pd.Series({
            "Ticker": "TST",
            "Sector": "Energy",
            "Precio_Entrada": precio_entrada,
            "Fecha_Entrada": weekly_index(N)[10],
        })

    def test_precio_entrada_cero_no_calcula_rentabilidad_y_deja_aviso(self, sp500_close_base):
        idx = weekly_index(N)
        close = pd.Series(np.linspace(100, 200, N), index=idx)
        df = pd.DataFrame({"Close": close})

        with patch.object(scanner_exit, "download_weekly", return_value=df):
            resultado = scanner_exit._worker_exit(
                self._fila(0), sp500_close_base, coppock_bearish=False
            )

        assert resultado["Rentabilidad %"] is None
        assert resultado["Error"] is not None
        assert "Precio_Entrada" in resultado["Error"]

    def test_precio_entrada_valido_calcula_rentabilidad_normalmente(self, sp500_close_base):
        idx = weekly_index(N)
        close = pd.Series(np.linspace(100, 200, N), index=idx)
        df = pd.DataFrame({"Close": close})

        with patch.object(scanner_exit, "download_weekly", return_value=df):
            resultado = scanner_exit._worker_exit(
                self._fila(150.0), sp500_close_base, coppock_bearish=False
            )

        assert resultado["Rentabilidad %"] is not None

    def test_precio_entrada_nan_no_calcula_rentabilidad(self, sp500_close_base):
        idx = weekly_index(N)
        close = pd.Series(np.linspace(100, 200, N), index=idx)
        df = pd.DataFrame({"Close": close})

        with patch.object(scanner_exit, "download_weekly", return_value=df):
            resultado = scanner_exit._worker_exit(
                self._fila(np.nan), sp500_close_base, coppock_bearish=False
            )

        assert resultado["Rentabilidad %"] is None