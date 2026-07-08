"""
Tests de `weinstein/indicators.py::sp500_bajista`.

Cubre la corrección de S2 (ver docstring de scanner_exit.py): la salida
por mercado ahora usa una condición de bajista propia, fiel a la fuente
original de la estrategia, en vez de `not sp500_alcista(...)`.

Casos cubiertos:
  - Cruce de positivo a negativo -> bajista
  - Negativo y cayendo (confirmación) -> bajista
  - Negativo pero subiendo (aunque no sea el "primer" rebote de
    sp500_alcista) -> NO bajista (estado neutro)
  - Positivo pero decreciente (aunque no sea "continuación alcista" de
    sp500_alcista) -> NO bajista (estado neutro)
  - sp500_alcista y sp500_bajista NO son complementarias: existe un
    estado neutro donde ambas devuelven False simultáneamente.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.conftest import weekly_index
from weinstein.indicators import sp500_alcista, sp500_bajista


class TestSP500Bajista:

    def test_cruce_de_positivo_a_negativo_es_bajista(self):
        vals = [2.0, 1.0, 0.5, -0.5]
        c = pd.Series(vals, index=weekly_index(len(vals)))
        bajista, direction = sp500_bajista(c)
        assert bajista is True
        assert direction == "↓ Bajista"

    def test_cero_a_negativo_cuenta_como_cruce(self):
        vals = [1.0, 0.0, -1.0]
        c = pd.Series(vals, index=weekly_index(len(vals)))
        bajista, _ = sp500_bajista(c)
        assert bajista is True

    def test_negativo_y_cayendo_es_confirmacion_bajista(self):
        vals = [-1.0, -2.0, -3.0]
        c = pd.Series(vals, index=weekly_index(len(vals)))
        bajista, direction = sp500_bajista(c)
        assert bajista is True
        assert direction == "↓ Bajista"

    def test_negativo_pero_subiendo_no_es_bajista(self):
        """
        Escenario clave de la corrección: Coppock en negativo y en
        recuperación (aunque no sea el "primer" rebote exacto que exige
        sp500_alcista). La fuente original NO considera esto bajista.
        """
        vals = [-5.0, -4.0, -6.0, -3.0, -2.0, -1.0]
        c = pd.Series(vals, index=weekly_index(len(vals)))
        bajista, direction = sp500_bajista(c)
        assert bajista is False
        assert direction == "→ Neutral"

    def test_positivo_pero_decreciente_no_es_bajista(self):
        """
        Coppock positivo y decreciente: ya no es "continuación alcista"
        (sp500_alcista exige current > previous), pero tampoco ha
        cruzado a negativo, así que sp500_bajista tampoco se activa.
        """
        vals = [1.0, 3.0, 5.0, 4.0]
        c = pd.Series(vals, index=weekly_index(len(vals)))
        bajista, direction = sp500_bajista(c)
        assert bajista is False
        assert direction == "→ Neutral"

    def test_positivo_y_subiendo_no_es_bajista(self):
        vals = [1.0, 1.5, 2.0, 3.0]
        c = pd.Series(vals, index=weekly_index(len(vals)))
        bajista, _ = sp500_bajista(c)
        assert bajista is False

    def test_menos_de_dos_valores_validos_no_es_bajista_por_defecto(self):
        c = pd.Series([np.nan, 1.0], index=weekly_index(2))
        bajista, direction = sp500_bajista(c)
        assert bajista is False
        assert direction == "→ Neutral"

    def test_serie_vacia_no_es_bajista_por_defecto(self):
        c = pd.Series([], dtype=float)
        bajista, direction = sp500_bajista(c)
        assert bajista is False
        assert direction == "→ Neutral"


class TestAlcistaYBajistaNoSonComplementarias:
    """
    Verifica explícitamente que existe un estado neutro donde ni
    sp500_alcista ni sp500_bajista se activan — este es el núcleo de la
    corrección: antes, scanner_exit.py trataba `not sp500_alcista` como
    si fuera sp500_bajista, colapsando este estado neutro en "salida".
    """

    def test_rebote_tardio_en_negativo_es_estado_neutro(self):
        # previous (-2.0) NO es el mínimo de la ventana de 4 semanas
        # anteriores [-5.0, -4.0, -6.0, -3.0] (el mínimo real es -6.0)
        # -> sp500_alcista = False
        # pero current (-1.0) > previous (-2.0) -> no cae -> sp500_bajista = False
        vals = [-5.0, -4.0, -6.0, -3.0, -2.0, -1.0]
        c = pd.Series(vals, index=weekly_index(len(vals)))

        alcista, _ = sp500_alcista(c, recent_lookback=4)
        bajista, _ = sp500_bajista(c)

        assert alcista is False
        assert bajista is False  # <- antes de la corrección, esto habría
                                  #    sido tratado como salida (S2=True)

    def test_positivo_decreciente_es_estado_neutro(self):
        vals = [1.0, 3.0, 5.0, 4.0]
        c = pd.Series(vals, index=weekly_index(len(vals)))

        alcista, _ = sp500_alcista(c, recent_lookback=4)
        bajista, _ = sp500_bajista(c)

        assert alcista is False
        assert bajista is False

    def test_continuacion_alcista_es_alcista_y_no_bajista(self):
        vals = [1.0, 1.5, 2.0, 3.0]
        c = pd.Series(vals, index=weekly_index(len(vals)))

        alcista, _ = sp500_alcista(c, recent_lookback=4)
        bajista, _ = sp500_bajista(c)

        assert alcista is True
        assert bajista is False

    def test_confirmacion_bajista_es_bajista_y_no_alcista(self):
        vals = [-1.0, -2.0, -3.0]
        c = pd.Series(vals, index=weekly_index(len(vals)))

        alcista, _ = sp500_alcista(c, recent_lookback=4)
        bajista, _ = sp500_bajista(c)

        assert alcista is False
        assert bajista is True
