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
