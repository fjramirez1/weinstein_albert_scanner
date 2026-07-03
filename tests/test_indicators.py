"""
Tests de `weinstein/indicators.py`.

Estas son funciones puras (Series/DataFrames -> Series/escalares), así que
se testean directamente con datos sintéticos, sin red y sin mocks.

Cubre en particular el caso que motivó estos tests: poder verificar el
comportamiento de `sp500_alcista` / `coppock_curve` (F5, filtro de mercado)
en todos sus escenarios (alcista por continuación, alcista por inicio de
tendencia, y bajista) sin depender de que el mercado real esté en un
estado concreto la semana en que se ejecutan los tests.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.conftest import weekly_index
from weinstein.indicators import (
    coppock_curve,
    distancia_wma_pct,
    momentum_vs_wma,
    rsc_mansfield,
    sp500_alcista,
    vpm5,
    wma,
)


# ── wma ──────────────────────────────────────────────────────────────

class TestWMA:
    def test_valor_calculado_a_mano(self):
        # WMA(3) de [1, 2, 3] = (1*1 + 2*2 + 3*3) / (1+2+3) = 14/6
        s = pd.Series([1.0, 2.0, 3.0])
        resultado = wma(s, 3).iloc[-1]
        assert resultado == pytest.approx(14 / 6)

    def test_precio_constante_da_wma_igual_al_precio(self, flat_price):
        resultado = wma(flat_price, 10).iloc[-1]
        assert resultado == pytest.approx(100.0)

    def test_nan_antes_de_completar_la_ventana(self):
        s = pd.Series([1.0, 2.0])
        resultado = wma(s, 5)
        assert resultado.isna().all()


# ── rsc_mansfield ────────────────────────────────────────────────────

class TestRSCMansfield:
    def test_activo_identico_al_benchmark_da_rsc_cero(self, flat_price):
        rsc = rsc_mansfield(flat_price, flat_price, sma_period=52)
        assert rsc.dropna().iloc[-1] == pytest.approx(0.0, abs=1e-9)

    def test_activo_mas_fuerte_que_benchmark_da_rsc_positivo(self):
        idx = weekly_index(90)
        bench = pd.Series(np.linspace(100, 110, 90), index=idx)
        asset = pd.Series(np.linspace(100, 200, 90), index=idx)
        rsc = rsc_mansfield(asset, bench, sma_period=52)
        assert rsc.iloc[-1] > 0

    def test_activo_mas_debil_que_benchmark_da_rsc_negativo(self):
        idx = weekly_index(90)
        bench = pd.Series(np.linspace(100, 200, 90), index=idx)
        asset = pd.Series(np.linspace(100, 110, 90), index=idx)
        rsc = rsc_mansfield(asset, bench, sma_period=52)
        assert rsc.iloc[-1] < 0


# ── vpm5 ─────────────────────────────────────────────────────────────

class TestVPM5:
    def test_pico_reciente_de_volumen_da_vpm5_positivo(self, volume_with_recent_spike):
        df = pd.DataFrame({"Volume": volume_with_recent_spike})
        resultado = vpm5(df, base_period=52, smoothing_period=5).iloc[-1]
        assert resultado > 0

    def test_volumen_constante_da_nan_por_desviacion_cero(self, volume_flat):
        df = pd.DataFrame({"Volume": volume_flat})
        resultado = vpm5(df, base_period=52, smoothing_period=5).iloc[-1]
        assert pd.isna(resultado)


# ── momentum_vs_wma / distancia_wma_pct ─────────────────────────────

class TestMomentumYDistancia:
    def test_precio_por_encima_de_wma_da_momentum_positivo(self):
        close = pd.Series(np.linspace(100, 130, 40))
        mom = momentum_vs_wma(close, period=30)
        assert mom is not None
        assert mom > 0

    def test_precio_por_debajo_de_wma_da_momentum_negativo(self):
        close = pd.Series(np.linspace(130, 100, 40))
        mom = momentum_vs_wma(close, period=30)
        assert mom is not None
        assert mom < 0

    def test_historico_insuficiente_devuelve_none(self):
        close = pd.Series(np.linspace(100, 130, 10))
        assert momentum_vs_wma(close, period=30) is None
        assert distancia_wma_pct(close, period=30) is None

    def test_distancia_pct_coincide_con_formula(self):
        close = pd.Series(np.linspace(100, 130, 40))
        dist = distancia_wma_pct(close, period=30)
        mom = momentum_vs_wma(close, period=30)
        # distancia_wma_pct es momentum_vs_wma expresado en % -> deben coincidir *100
        assert dist == pytest.approx(mom * 100, rel=1e-9)


# ── coppock_curve / sp500_alcista (filtro F5 / S2) ──────────────────

class TestSP500Alcista:
    """
    Casos de `sp500_alcista` construidos directamente sobre series de
    valores Coppock (no sobre precios) para que cada escenario sea
    explícito y fácil de verificar a mano, en vez de depender de que un
    precio sintético produzca por casualidad la forma de curva deseada.

    Recordatorio de la lógica (ver weinstein/indicators.py):
      - alcista por CONTINUACIÓN: current > 0 y current > previous
      - alcista por INICIO: current y previous < 0, previous es el mínimo
        de la ventana de `recent_lookback` valores anteriores, y
        current > previous
      - en cualquier otro caso: bajista
    """

    def test_continuacion_alcista_positivo_y_creciendo(self):
        vals = [1.0, 1.5, 2.0, 3.0]
        c = pd.Series(vals, index=weekly_index(len(vals)))
        bullish, direction = sp500_alcista(c, recent_lookback=4)
        assert bullish is True
        assert direction == "↑ Alcista"

    def test_positivo_pero_decreciendo_no_es_alcista(self):
        vals = [1.0, 3.0, 5.0, 4.0]
        c = pd.Series(vals, index=weekly_index(len(vals)))
        bullish, direction = sp500_alcista(c, recent_lookback=4)
        assert bullish is False
        assert direction == "↓ Bajista"

    def test_inicio_alcista_desde_minimo_reciente_en_negativo(self):
        # previous (-6.0) es el mínimo de los 4 valores anteriores [-5,-4,-3,-2]
        # y current (-1.0) sube por encima de previous -> inicio de tendencia alcista
        vals = [-5.0, -4.0, -3.0, -2.0, -6.0, -1.0]
        c = pd.Series(vals, index=weekly_index(len(vals)))
        bullish, direction = sp500_alcista(c, recent_lookback=4)
        assert bullish is True
        assert direction == "↑ Alcista"

    def test_negativo_decreciente_es_bajista(self):
        vals = [-5.0, -4.0, -3.0, -2.0, -1.0, -1.5]
        c = pd.Series(vals, index=weekly_index(len(vals)))
        bullish, direction = sp500_alcista(c, recent_lookback=4)
        assert bullish is False
        assert direction == "↓ Bajista"

    def test_negativo_pero_previous_no_es_el_minimo_reciente_es_bajista(self):
        # current sube respecto a previous, pero previous NO es el mínimo
        # de la ventana -> no cumple la condición de "inicio de tendencia"
        vals = [-6.0, -5.0, -4.0, -3.0, -2.0, -1.0]
        c = pd.Series(vals, index=weekly_index(len(vals)))
        bullish, direction = sp500_alcista(c, recent_lookback=4)
        assert bullish is False
        assert direction == "↓ Bajista"

    def test_menos_de_dos_valores_validos_es_bajista_por_defecto(self):
        c = pd.Series([np.nan, 1.0], index=weekly_index(2))
        bullish, direction = sp500_alcista(c)
        assert bullish is False
        assert direction == "↓ Bajista"

    def test_serie_vacia_es_bajista_por_defecto(self):
        c = pd.Series([], dtype=float)
        bullish, direction = sp500_alcista(c)
        assert bullish is False
        assert direction == "↓ Bajista"

    def test_integracion_coppock_curve_con_precio_acelerando(self, strong_uptrend_price):
        """
        Test de integración: verifica que coppock_curve + sp500_alcista
        juntos detectan correctamente una continuación alcista a partir
        de una serie de PRECIOS (no de valores Coppock ya calculados).
        """
        copk = coppock_curve(strong_uptrend_price)
        bullish, direction = sp500_alcista(copk)
        assert bullish is True
        assert direction == "↑ Alcista"

    def test_integracion_coppock_curve_con_precio_plano_es_bajista(self, flat_price):
        """Precio constante -> ROC=0 siempre -> Coppock=0 -> no cumple ninguna condición alcista."""
        copk = coppock_curve(flat_price)
        bullish, direction = sp500_alcista(copk)
        assert bullish is False
        assert direction == "↓ Bajista"
