"""
Condiciones registradas fuera de producción: las reglas del vídeo (Fase 6,
F1 de docs/HOJA_DE_RUTA.md) F6 (cierre > WMA30) y S3 (trailing stop de 15
semanas, solo con más de 15 semanas en posición), y F5b (mercado no
bajista, alternativa a F5 estudiada en O2).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.conditions import ENTRY_CONDITIONS, EXIT_CONDITIONS
from backtest.portfolio_backtest import run_portfolio_backtest
from backtest.portfolio_engine import evaluate_exit_masks
from backtest.strategy_config import ConditionToggle, StrategyConfig
from tests.test_portfolio_execution import N, _ctx, _first_bullish, mercado  # noqa: F401


class TestRegistro:

    def test_desactivadas_por_defecto(self):
        cfg = StrategyConfig()
        assert "F6_cierre_sobre_wma30" not in cfg.active_entry_conditions()
        assert "F5b_mercado_no_bajista" not in cfg.active_entry_conditions()
        assert "S3_trailing_stop" not in cfg.active_exit_conditions()
        assert set(cfg.active_entry_conditions()) == {
            "F1_sector_fuerte", "F2_volumen_positivo", "F3_rsc_activo_positivo",
            "F4_distancia_wma30", "F5_mercado_alcista",
        }
        assert set(cfg.active_exit_conditions()) == {"S1_rsc_debil", "S2_mercado_bajista"}

    def test_se_activan_con_toggle(self):
        cfg = StrategyConfig(
            entry_conditions={"F6_cierre_sobre_wma30": ConditionToggle()},
            exit_conditions={"S3_trailing_stop": ConditionToggle(params={"min_semanas": 10})},
        )
        assert cfg.active_entry_conditions()["F6_cierre_sobre_wma30"] == {"min_distancia": 0.0}
        assert cfg.active_exit_conditions()["S3_trailing_stop"] == {"ventana": 15, "min_semanas": 10}


class TestMascaras:

    def test_f6_exige_distancia_positiva(self):
        ctx = _ctx("AAA", np.linspace(50, 100, N))
        ctx.dist_wma30_pct = pd.Series([-1.0, 0.0, 0.5, np.nan] * (N // 4), index=ctx.close.index)
        mask = ENTRY_CONDITIONS["F6_cierre_sobre_wma30"].func(ctx)
        assert mask.tolist()[:4] == [False, False, True, False]

    def test_s3_cierre_bajo_el_minimo_de_los_15_previos(self):
        close = np.linspace(50, 100, N)
        close[30] = 10.0     # rompe el mínimo de las 15 semanas anteriores
        close[31] = 60.0     # por encima del mínimo previo (que ahora incluye el 10)
        mask = EXIT_CONDITIONS["S3_trailing_stop"].func(_ctx("AAA", close), ventana=15)
        assert np.flatnonzero(mask.to_numpy()).tolist() == [30]

    def test_s3_sin_historico_suficiente_no_dispara(self):
        close = np.linspace(100, 50, N)  # bajando siempre
        mask = EXIT_CONDITIONS["S3_trailing_stop"].func(_ctx("AAA", close), ventana=15)
        assert not mask.iloc[:15].any()
        assert mask.iloc[15:].all()

    def test_f5b_alcista_o_neutro_cumple_bajista_no(self):
        ctx = _ctx("AAA", np.linspace(50, 100, N))
        bajista = pd.Series(False, index=ctx.close.index)
        bajista.iloc[10:20] = True
        mask = ENTRY_CONDITIONS["F5b_mercado_no_bajista"].func(ctx, coppock_bearish_aligned=bajista)
        assert not mask.iloc[10:20].any()
        assert mask.iloc[:10].all() and mask.iloc[20:].all()

    def test_f5b_sin_datos_de_mercado_no_cumple(self):
        ctx = _ctx("AAA", np.linspace(50, 100, N))
        mask = ENTRY_CONDITIONS["F5b_mercado_no_bajista"].func(ctx, coppock_bearish_aligned=None)
        assert not mask.any()

    def test_min_semanas_no_llega_a_la_funcion(self):
        cfg = StrategyConfig(exit_conditions={"S3_trailing_stop": ConditionToggle()})
        masks = evaluate_exit_masks(_ctx("AAA", np.linspace(50, 100, N)), cfg, {"coppock_bearish": None})
        assert "S3_trailing_stop" in masks


class TestMotor:

    @staticmethod
    def _run(mercado, close, **cfg_kw):
        sp500, bull, bear = mercado
        cfg = StrategyConfig(max_positions=1, cost_pct=0.0,
                             exit_conditions={"S3_trailing_stop": ConditionToggle()}, **cfg_kw)
        return run_portfolio_backtest(cfg, sp500, bull, bear, {"AAA": _ctx("AAA", close)}, verbose=False)

    def test_s3_ignorada_con_15_semanas_o_menos(self, mercado):
        e = _first_bullish(mercado[1]) + 1  # semana de entrada (next_open)
        close = np.linspace(50, 100, N)
        close[e + 15] = 10.0
        res = self._run(mercado, close)
        assert res.closed_trades == []

    def test_s3_dispara_con_mas_de_15_semanas(self, mercado):
        sp500 = mercado[0]
        e = _first_bullish(mercado[1]) + 1
        close = np.linspace(50, 100, N)
        close[e + 16] = 10.0
        res = self._run(mercado, close)
        t = res.closed_trades[0]
        assert t.motivo_salida == "S3_trailing_stop"
        assert t.fecha_entrada == sp500.index[e]
        assert t.fecha_salida == sp500.index[e + 17]  # apertura de la semana siguiente

    def test_salida_sin_min_semanas_cuenta_desde_la_semana_de_entrada(self, mercado):
        sp500, bull, bear = mercado
        e = _first_bullish(bull) + 1
        rsc = np.full(N, 1.0)
        rsc[e:] = -1.0  # S1 ya en la semana de entrada
        cfg = StrategyConfig(max_positions=1, cost_pct=0.0)
        res = run_portfolio_backtest(cfg, sp500, bull, bear,
                                     {"AAA": _ctx("AAA", np.linspace(50, 100, N), rsc=rsc)}, verbose=False)
        t = res.closed_trades[0]
        assert t.motivo_salida == "S1_rsc_debil"
        assert t.fecha_salida == sp500.index[e + 1]


@pytest.mark.parametrize("cname", ["F6_cierre_sobre_wma30", "S3_trailing_stop"])
def test_cli_enable(cname):
    import argparse

    from backtest.run_portfolio_backtest import _build_config_from_args, add_portfolio_arguments

    parser = argparse.ArgumentParser()
    add_portfolio_arguments(parser)
    cfg = _build_config_from_args(parser.parse_args(["--enable", cname]))
    activas = {**cfg.active_entry_conditions(), **cfg.active_exit_conditions()}
    assert cname in activas
