"""
Tests de `weinstein/scanner_exit.py`.

`_evaluate_exit` mezcla lógica pura con I/O (descarga vía `download_weekly`),
así que se mockea la descarga para testear las condiciones OR de salida
(S1: RSC activo < -0.5, S2: Coppock no alcista) de forma aislada.
"""

from __future__ import annotations

from threading import Semaphore
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
                "TST", fecha_entrada, sp500_close_base, coppock_not_bull=False, sem=Semaphore(5)
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
                "TST", fecha_entrada, sp500_close_base, coppock_not_bull=True, sem=Semaphore(5)
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
                "TST", fecha_entrada, sp500_close_base, coppock_not_bull=True, sem=Semaphore(5)
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
                "TST", fecha_entrada, sp500_close_base, coppock_not_bull=False, sem=Semaphore(5)
            )

        assert resultado["SALIDA"] is False
        assert resultado["Motivo"] == "—"

    def test_sin_datos_y_mercado_bajista_activa_salida_por_s2(self, sp500_close_base, fecha_entrada):
        """Aunque falle la descarga, S2 (conocido de antemano) puede bastar para activar SALIDA."""
        with patch.object(scanner_exit, "download_weekly", return_value=None):
            resultado = scanner_exit._evaluate_exit(
                "TST", fecha_entrada, sp500_close_base, coppock_not_bull=True, sem=Semaphore(5)
            )

        assert resultado["SALIDA"] is True
        assert resultado["Error"] is not None
        assert "S2" in resultado["Motivo"]

    def test_sin_datos_y_mercado_alcista_no_activa_salida(self, sp500_close_base, fecha_entrada):
        with patch.object(scanner_exit, "download_weekly", return_value=None):
            resultado = scanner_exit._evaluate_exit(
                "TST", fecha_entrada, sp500_close_base, coppock_not_bull=False, sem=Semaphore(5)
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
                "TST", fecha_entrada, sp500_close_base, coppock_not_bull=False, sem=Semaphore(5)
            )

        precio_esperado = round(float(close.loc[close.index >= fecha_entrada].iloc[-1]), 2)
        assert resultado["Precio Actual"] == precio_esperado
