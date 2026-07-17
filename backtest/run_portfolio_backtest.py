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
    prepare_universe,
    print_report,
    run_portfolio_backtest,
)
from backtest.strategy_config import ConditionToggle, StrategyConfig  # noqa: E402
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
    )


def _demo_sweep_configs(base_capital: float, base_max_pos: int) -> list[StrategyConfig]:
    """Un pequeño conjunto de configuraciones de ejemplo para --sweep-demo."""
    return [
        StrategyConfig(name="baseline (F1-F5/S1-S2 tal cual)",
                        max_positions=base_max_pos, initial_capital=base_capital),
        StrategyConfig(name="sin F1 (sector)",
                        entry_conditions={"F1_sector_fuerte": ConditionToggle(enabled=False)},
                        max_positions=base_max_pos, initial_capital=base_capital),
        StrategyConfig(name="S1 más laxo (-1.0)",
                        exit_conditions={"S1_rsc_debil": ConditionToggle(params={"umbral": -1.0})},
                        max_positions=base_max_pos, initial_capital=base_capital),
        StrategyConfig(name="ranking por RSC activo",
                        ranking_criterion="rsc_activo",
                        max_positions=base_max_pos, initial_capital=base_capital),
        StrategyConfig(name="máx. 5 posiciones",
                        max_positions=5, initial_capital=base_capital),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest de CARTERA Weinstein-Albert (capital, nº posiciones, condiciones configurables)"
    )
    parser.add_argument("--period", default=DEFAULT_BACKTEST_PERIOD,
                         help=f"Periodo de histórico yfinance (default: {DEFAULT_BACKTEST_PERIOD}; "
                              "se recomienda no alargarlo mucho por el sesgo de supervivencia, ver docstring)")
    parser.add_argument("--tickers", default=None, help="Lista de tickers separados por coma (default: S&P 500 completo)")
    parser.add_argument("--max-tickers", type=int, default=None, help="Límite de tickers a procesar (pruebas rápidas)")
    parser.add_argument("--max-positions", type=int, default=10, help="Nº máximo de posiciones simultáneas (default: 10)")
    parser.add_argument("--capital", type=float, default=10_000.0, help="Capital inicial en USD (default: 10000)")
    parser.add_argument("--ranking", default="momentum", choices=list(RANKING_CRITERIA),
                         help="Criterio de desempate para elegir candidatos (default: momentum)")
    parser.add_argument("--disable", action="append", default=None,
                         help="Nombre de condición a desactivar (repetible). "
                              f"Entrada: {list(ENTRY_CONDITIONS)} | Salida: {list(EXIT_CONDITIONS)}")
    parser.add_argument("--f1-umbral", type=float, default=None, help="Umbral F1 (RSC sector), default 0.10")
    parser.add_argument("--f4-max-distancia", type=float, default=None, help="Umbral F4 (distancia %% WMA30), default 8.0")
    parser.add_argument("--s1-umbral", type=float, default=None, help="Umbral S1 (RSC activo salida), default -0.5")
    parser.add_argument("--name", default="config_cli", help="Nombre de esta configuración (etiqueta en el reporte)")
    parser.add_argument("--export", default=None, metavar="CSV", help="Ruta donde exportar el detalle de operaciones")
    parser.add_argument("--sweep-demo", action="store_true", help="Ignora el resto de flags de condiciones y compara un set de configuraciones de ejemplo")
    parser.add_argument("--clear-cache", action="store_true", help="Vacía la caché de datos en disco antes de ejecutar")
    parser.add_argument("--universe", default="current", choices=["current", "historical"],
                         help="'current' (default): constituyentes ACTUALES del S&P 500 para todo el periodo "
                              "(sesgo de supervivencia). 'historical': reconstruye altas/bajas reales por fecha "
                              "desde Wikipedia (mitiga el sesgo, no lo elimina — ver backtest/sp500_historical.py)")
    args = parser.parse_args()

    if args.clear_cache:
        n = clear_cache()
        print(f"  🗑  Caché vaciada: {n} archivos eliminados.")

    stats = cache_stats()
    print(f"  📦 Caché de datos: {stats['n_archivos']} archivos ({stats['tamano_mb']} MB)")

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None

    if args.sweep_demo:
        run_sweep(
            configs=_demo_sweep_configs(args.capital, args.max_positions),
            period=args.period,
            tickers=tickers,
            max_tickers=args.max_tickers,
            universe=args.universe,
        )
        return

    config = _build_config_from_args(args)
    print(f"\n  Configuración: {config.describe()}")

    sp500_close, coppock_bullish, coppock_bearish, contexts, universe_info = prepare_universe(
        period=args.period, tickers=tickers, max_tickers=args.max_tickers, universe=args.universe,
    )

    result = run_portfolio_backtest(
        config, sp500_close, coppock_bullish, coppock_bearish, contexts,
        universe_info=universe_info,
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


if __name__ == "__main__":
    main()
