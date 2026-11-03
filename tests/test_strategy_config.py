"""
Tests de `backtest/strategy_config.py`.
"""

from __future__ import annotations

import pytest

from backtest.strategy_config import ConditionToggle, StrategyConfig, default_config


class TestStrategyConfigValidation:

    def test_condicion_entrada_desconocida_lanza_error(self):
        with pytest.raises(ValueError, match="Condición de entrada desconocida"):
            StrategyConfig(entry_conditions={"F99_no_existe": ConditionToggle()})

    def test_condicion_salida_desconocida_lanza_error(self):
        with pytest.raises(ValueError, match="Condición de salida desconocida"):
            StrategyConfig(exit_conditions={"S99_no_existe": ConditionToggle()})

    def test_ranking_desconocido_lanza_error(self):
        with pytest.raises(ValueError, match="Criterio de desempate desconocido"):
            StrategyConfig(ranking_criterion="no_existe")

    def test_max_positions_cero_lanza_error(self):
        with pytest.raises(ValueError, match="max_positions"):
            StrategyConfig(max_positions=0)

    def test_capital_negativo_lanza_error(self):
        with pytest.raises(ValueError, match="initial_capital"):
            StrategyConfig(initial_capital=-100)

    def test_config_por_defecto_es_valida(self):
        cfg = default_config()
        assert cfg.max_positions == 10
        assert cfg.initial_capital == 10_000.0


class TestActiveConditions:

    def test_condicion_no_mencionada_esta_activa_por_defecto(self):
        cfg = StrategyConfig()
        active = cfg.active_entry_conditions()
        assert "F1_sector_fuerte" in active
        assert active["F1_sector_fuerte"]["umbral"] == 0.10

    def test_condicion_desactivada_no_aparece(self):
        cfg = StrategyConfig(entry_conditions={"F1_sector_fuerte": ConditionToggle(enabled=False)})
        active = cfg.active_entry_conditions()
        assert "F1_sector_fuerte" not in active
        assert "F2_volumen_positivo" in active

    def test_parametro_sobrescrito_sin_desactivar(self):
        cfg = StrategyConfig(exit_conditions={"S1_rsc_debil": ConditionToggle(params={"umbral": -2.0})})
        active = cfg.active_exit_conditions()
        assert active["S1_rsc_debil"]["umbral"] == -2.0

    def test_todas_las_condiciones_desactivadas_da_dict_vacio(self):
        cfg = StrategyConfig(exit_conditions={
            "S1_rsc_debil": ConditionToggle(enabled=False),
            "S2_mercado_bajista": ConditionToggle(enabled=False),
        })
        assert cfg.active_exit_conditions() == {}

    def test_describe_no_lanza_excepcion(self):
        cfg = StrategyConfig(name="mi_config")
        texto = cfg.describe()
        assert "mi_config" in texto


class TestParametrosCoppock:

    def test_por_defecto_son_los_de_config(self):
        from weinstein.config import COPPOCK_ROC_LONG, COPPOCK_ROC_SHORT, COPPOCK_WMA_PERIOD
        cfg = StrategyConfig()
        assert cfg.coppock_es_por_defecto()
        assert cfg.coppock_params()[:3] == (COPPOCK_ROC_LONG, COPPOCK_ROC_SHORT, COPPOCK_WMA_PERIOD)

    def test_parametros_invalidos(self):
        import pytest
        with pytest.raises(ValueError):
            StrategyConfig(coppock_roc_long=0)

    def test_otros_parametros_recalculan_f5_s2(self, monkeypatch):
        import numpy as np
        import pandas as pd
        from backtest import portfolio_backtest as pbt

        idx = pd.date_range("2020-01-03", periods=80, freq="W-FRI")
        sp500 = pd.Series(np.linspace(100, 150, 80), index=idx)
        llamadas = []
        original = pbt.market_state_series

        def espia(close, **kw):
            llamadas.append(kw)
            return original(close, **kw)

        monkeypatch.setattr(pbt, "market_state_series", espia)
        vacio = pd.Series(False, index=idx)
        pbt.run_portfolio_backtest(StrategyConfig(), sp500, vacio, vacio, {}, verbose=False)
        assert llamadas == []  # por defecto se usan las series recibidas
        pbt.run_portfolio_backtest(StrategyConfig(coppock_roc_long=14, coppock_roc_short=11),
                                   sp500, vacio, vacio, {}, verbose=False)
        assert llamadas and llamadas[0]["roc_long"] == 14 and llamadas[0]["roc_short"] == 11
