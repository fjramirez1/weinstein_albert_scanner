"""
CLI unificado de la estrategia Weinstein-Albert.

Uso
---
    python -m weinstein entry
    python -m weinstein exit
    python -m weinstein exit --input mis_posiciones.csv

Ejecutar desde la raíz del proyecto (donde está posiciones.csv).
Editar parámetros en weinstein/config.py.
"""

from __future__ import annotations

import argparse
import os
import sys
import warnings

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
    from weinstein.config import DEFAULT_POSITIONS_CSV
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

    args = parser.parse_args()

    if args.command == "entry":
        _cmd_entry(args)
    elif args.command == "exit":
        _cmd_exit(args)


if __name__ == "__main__":
    main()
