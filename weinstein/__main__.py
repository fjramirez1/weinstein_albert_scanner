"""
CLI unificado de la estrategia Weinstein-Albert.

Uso
---
    python -m weinstein entry
    python -m weinstein exit
    python -m weinstein exit --input mis_posiciones.csv
    python -m weinstein backtest
    python -m weinstein backtest --period 8y --max-tickers 50 --export out.csv
    python -m weinstein portfolio-backtest
    python -m weinstein portfolio-backtest --period 6y --max-positions 8
    python -m weinstein portfolio-backtest --universe historical
    python -m weinstein portfolio-backtest --sweep-demo

Ejecutar desde la raíz del proyecto (donde está posiciones.csv).
Editar parámetros en weinstein/config.py.
"""

from __future__ import annotations

import argparse
import os
import sys
import warnings
from dotenv import load_dotenv

load_dotenv()

warnings.filterwarnings("ignore")


def _cmd_entry(_args: argparse.Namespace) -> None:
    from weinstein.exporter import export_entry_results
    from weinstein.scanner_entry import run_entry_scanner

    df = run_entry_scanner()
    export_entry_results(df)


def _cmd_exit(args: argparse.Namespace) -> None:
    from weinstein.exporter import export_exit_results
    from weinstein.scanner_exit import run_exit_scanner

    df = run_exit_scanner(csv_path=args.input)
    export_exit_results(df, input_csv=args.input)


def _cmd_backtest(args: argparse.Namespace) -> None:
    _project_root_on_path()
    from backtest.strategy_backtest import run_strategy_backtest

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
    result = run_strategy_backtest(
        period=args.period,
        tickers=tickers,
        max_tickers=args.max_tickers,
    )

    if args.export:
        df = result.to_dataframe()
        if not df.empty:
            df.to_csv(args.export, index=False, encoding="utf-8-sig")
            print(f"\n  ✅ Detalle de operaciones exportado → {args.export}")
        else:
            print("\n  ⚠ No hay operaciones que exportar.")


def _project_root_on_path() -> None:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


def _cmd_portfolio_backtest(args: argparse.Namespace) -> None:
    from backtest.run_portfolio_backtest import run_from_args

    run_from_args(args)


def main() -> None:
    # Dry-run para validar scripts de arranque sin llamadas de red.
    if os.getenv("WEINSTEIN_DRY_RUN") == "1":
        print("WEINSTEIN_DRY_RUN=1 — dry run, saliendo sin llamadas de red.")
        sys.exit(0)

    parser = argparse.ArgumentParser(
        prog="python -m weinstein",
        description="Weinstein-Albert Scanner — escáner semanal del S&P 500",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMANDO")
    subparsers.required = True

    # Subcomando: entry
    subparsers.add_parser(
        "entry",
        help="Escáner de condiciones de ENTRADA (busca candidatos en el S&P 500)",
    )

    # Subcomando: exit
    from weinstein.config import BACKTEST_PERIOD_DEFAULT, DEFAULT_POSITIONS_CSV
    exit_parser = subparsers.add_parser(
        "exit",
        help="Escáner de condiciones de SALIDA (evalúa posiciones abiertas)",
    )
    exit_parser.add_argument(
        "--input", "-i",
        default=DEFAULT_POSITIONS_CSV,
        metavar="CSV",
        help=f"Ruta al CSV de posiciones abiertas (por defecto: {DEFAULT_POSITIONS_CSV})",
    )

    # Subcomando: backtest (por-ticker, aislado, sin cartera)
    backtest_parser = subparsers.add_parser(
        "backtest",
        help="Backtest de la estrategia completa POR TICKER, aislado (entrada F1-F5 + salida S1-S2) sobre histórico real",
    )
    backtest_parser.add_argument(
        "--period",
        default=BACKTEST_PERIOD_DEFAULT,
        metavar="PERIODO",
        help=f"Periodo de histórico a descargar por ticker, formato yfinance (por defecto: {BACKTEST_PERIOD_DEFAULT})",
    )
    backtest_parser.add_argument(
        "--tickers",
        default=None,
        metavar="TICK1,TICK2,...",
        help="Lista de tickers separados por coma (por defecto: todo el S&P 500)",
    )
    backtest_parser.add_argument(
        "--max-tickers",
        type=int,
        default=None,
        metavar="N",
        help="Limita el nº de tickers procesados (útil para pruebas rápidas)",
    )
    backtest_parser.add_argument(
        "--export",
        default=None,
        metavar="CSV",
        help="Ruta donde exportar el detalle de operaciones simuladas a CSV",
    )

    # Subcomando: portfolio-backtest (cartera completa, capital compartido).
    # Las opciones viven en backtest/run_portfolio_backtest.py para no duplicarlas.
    _project_root_on_path()
    from backtest.run_portfolio_backtest import add_portfolio_arguments

    pbt_parser = subparsers.add_parser(
        "portfolio-backtest",
        help="Backtest de CARTERA completa: capital inicial, máx. nº posiciones, "
             "condiciones de entrada/salida configurables (ver backtest/README.md)",
    )
    add_portfolio_arguments(pbt_parser)

    args = parser.parse_args()

    if args.command == "entry":
        _cmd_entry(args)
    elif args.command == "exit":
        _cmd_exit(args)
    elif args.command == "backtest":
        _cmd_backtest(args)
    elif args.command == "portfolio-backtest":
        _cmd_portfolio_backtest(args)


if __name__ == "__main__":
    main()
