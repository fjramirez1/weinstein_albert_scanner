"""
CLI del backtest de cartera Weinstein-Albert.

Uso
---
    # Ejecución simple con la estrategia actual (F1-F5/S1-S2 tal cual):
    python backtest/run_portfolio_backtest.py

    python backtest/run_portfolio_backtest.py --period 6y --max-positions 8

    # Desactivar F1 (RSC sector) y bajar el umbral de S1:
    python backtest/run_portfolio_backtest.py --disable F1_sector_fuerte --s1-umbral -1.0

    # Cambiar el criterio de desempate:
    python backtest/run_portfolio_backtest.py --ranking rsc_activo

    # Usar el universo HISTÓRICO reconstruido (altas/bajas reales del
    # índice) en vez del S&P 500 actual, para mitigar el sesgo de
    # supervivencia (ver docstring de backtest/sp500_historical.py):
    python backtest/run_portfolio_backtest.py --universe historical

    # Sweep: comparar varias configuraciones predefinidas de ejemplo:
    python backtest/run_portfolio_backtest.py --sweep-demo

    # Exportar operaciones a CSV:
    python backtest/run_portfolio_backtest.py --export historial/backtests/salida.csv

    # Vaciar caché de datos antes de ejecutar:
    python backtest/run_portfolio_backtest.py --clear-cache

    # Simular solo un tramo (los datos previos se usan para calentar
    # indicadores), p.ej. calibrar en uno y validar en otro disjunto:
    python backtest/run_portfolio_backtest.py --period 10y --start 2017-01-01 --end 2021-12-31

    # Modelo de ejecución antiguo (al cierre de la señal) y sin costes:
    python backtest/run_portfolio_backtest.py --execution close --coste 0

Uso como módulo del paquete
------------------------------
    python -m weinstein portfolio-backtest --period 8y --max-positions 10
    python -m weinstein portfolio-backtest --universe historical
"""

from __future__ import annotations

import argparse
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backtest.conditions import ENTRY_CONDITIONS, EXIT_CONDITIONS, RANKING_CRITERIA  # noqa: E402
from backtest.data_cache import cache_stats, clear_cache  # noqa: E402
from backtest.portfolio_backtest import (  # noqa: E402
    DEFAULT_BACKTEST_PERIOD,
    default_simulation_start,
    prepare_universe,
    print_report,
    run_portfolio_backtest,
)
from backtest.strategy_config import EXECUTION_MODES, ConditionToggle, StrategyConfig  # noqa: E402
from weinstein.config import MAX_DISTANCIA_WMA30, RSC_EXIT_THRESHOLD, SECTOR_RSC_MIN  # noqa: E402
from backtest.sweep import run_sweep  # noqa: E402


def _build_config_from_args(args: argparse.Namespace) -> StrategyConfig:
    entry_conditions = {}
    exit_conditions = {}

    for cname in (args.disable or []):
        if cname in ENTRY_CONDITIONS:
            entry_conditions[cname] = ConditionToggle(enabled=False)
        elif cname in EXIT_CONDITIONS:
            exit_conditions[cname] = ConditionToggle(enabled=False)
        else:
            print(f"  ✗ Condición desconocida en --disable: '{cname}'")
            print(f"    Entrada disponibles: {list(ENTRY_CONDITIONS)}")
            print(f"    Salida disponibles : {list(EXIT_CONDITIONS)}")
            sys.exit(1)

    for cname in (args.enable or []):
        if cname in ENTRY_CONDITIONS:
            entry_conditions[cname] = ConditionToggle()
        elif cname in EXIT_CONDITIONS:
            exit_conditions[cname] = ConditionToggle()
        else:
            print(f"  ✗ Condición desconocida en --enable: '{cname}'")
            sys.exit(1)

    if args.f1_umbral is not None:
        entry_conditions.setdefault("F1_sector_fuerte", ConditionToggle()).params["umbral"] = args.f1_umbral
    if args.f4_max_distancia is not None:
        entry_conditions.setdefault("F4_distancia_wma30", ConditionToggle()).params["max_distancia"] = args.f4_max_distancia
    if args.s1_umbral is not None:
        exit_conditions.setdefault("S1_rsc_debil", ConditionToggle()).params["umbral"] = args.s1_umbral

    return StrategyConfig(
        name=args.name,
        entry_conditions=entry_conditions,
        exit_conditions=exit_conditions,
        ranking_criterion=args.ranking,
        max_positions=args.max_positions,
        initial_capital=args.capital,
        execution=args.execution,
        cost_pct=args.coste,
    )


def _demo_sweep_configs(args: argparse.Namespace) -> list[StrategyConfig]:
    """Un pequeño conjunto de configuraciones de ejemplo para --sweep-demo."""
    comun = dict(max_positions=args.max_positions, initial_capital=args.capital,
                 execution=args.execution, cost_pct=args.coste)
    return [
        StrategyConfig(name="baseline (F1-F5/S1-S2 tal cual)", **comun),
        StrategyConfig(name="sin F1 (sector)",
                       entry_conditions={"F1_sector_fuerte": ConditionToggle(enabled=False)}, **comun),
        StrategyConfig(name="S1 más laxo (-1.0)",
                       exit_conditions={"S1_rsc_debil": ConditionToggle(params={"umbral": -1.0})}, **comun),
        StrategyConfig(name="ranking por RSC activo", ranking_criterion="rsc_activo", **comun),
        StrategyConfig(name="máx. 5 posiciones",
                       **{**comun, "max_positions": 5}),
    ]


def add_portfolio_arguments(parser: argparse.ArgumentParser) -> None:
    """Opciones del backtest de cartera. Compartidas con `python -m weinstein portfolio-backtest`."""
    parser.add_argument("--period", default=DEFAULT_BACKTEST_PERIOD,
                        help=f"Histórico a descargar, formato yfinance (default: {DEFAULT_BACKTEST_PERIOD})")
    parser.add_argument("--start", default=None, metavar="AAAA-MM-DD",
                        help="Primera semana simulada (default: en cuanto los indicadores están calculados)")
    parser.add_argument("--end", default=None, metavar="AAAA-MM-DD", help="Última semana simulada (default: la última)")
    parser.add_argument("--tickers", default=None, help="Lista de tickers separados por coma (default: S&P 500 completo)")
    parser.add_argument("--max-tickers", type=int, default=None, help="Límite de tickers a procesar (pruebas rápidas)")
    parser.add_argument("--max-positions", type=int, default=10, help="Nº máximo de posiciones simultáneas (default: 10)")
    parser.add_argument("--capital", type=float, default=10_000.0, help="Capital inicial en USD (default: 10000)")
    parser.add_argument("--ranking", default="momentum", choices=list(RANKING_CRITERIA),
                        help="Criterio de desempate para elegir candidatos (default: momentum)")
    parser.add_argument("--execution", default="next_open", choices=list(EXECUTION_MODES),
                        help="next_open (default): órdenes a la apertura de la semana siguiente a la señal; "
                             "close: al cierre de la propia semana (optimista, solo para comparar)")
    parser.add_argument("--coste", type=float, default=0.10, metavar="PCT",
                        help="Coste por lado en %% (comisión + deslizamiento), default 0.10")
    parser.add_argument("--disable", action="append", default=None,
                        help="Nombre de condición a desactivar (repetible). "
                             f"Entrada: {list(ENTRY_CONDITIONS)} | Salida: {list(EXIT_CONDITIONS)}")
    parser.add_argument("--enable", action="append", default=None,
                        help="Activa una condición desactivada por defecto (repetible), p. ej. S3_trailing_stop")
    parser.add_argument("--f1-umbral", type=float, default=None, help=f"Umbral F1 (RSC sector), default {SECTOR_RSC_MIN}")
    parser.add_argument("--f4-max-distancia", type=float, default=None,
                        help=f"Umbral F4 (distancia %% WMA30), default {MAX_DISTANCIA_WMA30}")
    parser.add_argument("--s1-umbral", type=float, default=None, help=f"Umbral S1 (RSC activo salida), default {RSC_EXIT_THRESHOLD}")
    parser.add_argument("--name", default="config_cli", help="Nombre de esta configuración (etiqueta en el reporte)")
    parser.add_argument("--export", default=None, metavar="CSV", help="Ruta donde exportar el detalle de operaciones")
    parser.add_argument("--sweep-demo", action="store_true",
                        help="Ignora el resto de flags de condiciones y compara un set de configuraciones de ejemplo")
    parser.add_argument("--clear-cache", action="store_true", help="Vacía la caché de datos en disco antes de ejecutar")
    parser.add_argument("--desde", default=None, metavar="AAAA-MM-DD",
                        help="Universo histórico: membresía desde esta fecha (necesario con --period max). "
                             "Si no se da --start, la simulación empieza aquí.")
    parser.add_argument("--universe", default="current", choices=["current", "historical"],
                        help="'current' (default): constituyentes ACTUALES del S&P 500 para todo el periodo "
                             "(sesgo de supervivencia). 'historical': reconstruye altas/bajas reales por fecha "
                             "desde Wikipedia (mitiga el sesgo, no lo elimina — ver backtest/sp500_historical.py)")


def run_from_args(args: argparse.Namespace) -> None:
    """Ejecuta el backtest de cartera (o el sweep de ejemplo) a partir de las opciones del CLI."""
    if args.clear_cache:
        n = clear_cache()
        print(f"  🗑  Caché vaciada: {n} archivos eliminados.")

    stats = cache_stats()
    print(f"  📦 Caché de datos: {stats['n_archivos']} archivos ({stats['tamano_mb']} MB)")

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None

    if args.sweep_demo:
        run_sweep(
            configs=_demo_sweep_configs(args),
            period=args.period,
            tickers=tickers,
            max_tickers=args.max_tickers,
            universe=args.universe,
            start=args.start,
            end=args.end,
        )
        return

    config = _build_config_from_args(args)
    print(f"\n  Configuración: {config.describe()}")

    sp500_close, coppock_bullish, coppock_bearish, contexts, universe_info = prepare_universe(
        period=args.period, tickers=tickers, max_tickers=args.max_tickers, universe=args.universe,
        desde=args.desde,
    )

    result = run_portfolio_backtest(
        config, sp500_close, coppock_bullish, coppock_bearish, contexts,
        universe_info=universe_info,
        start=args.start or args.desde or default_simulation_start(sp500_close),
        end=args.end,
    )
    print_report(result, universe_info=universe_info)

    if args.export:
        df = result.to_trades_dataframe()
        if not df.empty:
            os.makedirs(os.path.dirname(args.export) or ".", exist_ok=True)
            df.to_csv(args.export, index=False, encoding="utf-8-sig")
            print(f"\n  ✅ Detalle de operaciones exportado → {args.export}")
        else:
            print("\n  ⚠ No hay operaciones que exportar.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest de CARTERA Weinstein-Albert (capital, nº posiciones, condiciones configurables)"
    )
    add_portfolio_arguments(parser)
    run_from_args(parser.parse_args())


if __name__ == "__main__":
    main()
