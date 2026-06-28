"""
Punto de entrada del escáner de SALIDA — estrategia Weinstein-Albert.

Uso
---
    python weinstein_albert_exit_scanner.py
    python weinstein_albert_exit_scanner.py --input mis_posiciones.csv

Este script es intencionadamente delgado: delega toda la lógica al
paquete ``weinstein``. Editar los parámetros en ``weinstein/config.py``.
"""

import argparse
import os
import sys
import warnings

warnings.filterwarnings("ignore")

# Permite un dry-run sin descargas para validar los scripts de arranque.
if os.getenv("WEINSTEIN_DRY_RUN") == "1":
    print("WEINSTEIN_DRY_RUN=1 — dry run, saliendo sin llamadas de red.")
    sys.exit(0)

from weinstein.config import DEFAULT_POSITIONS_CSV
from weinstein.exit_scanner import run_exit_scanner
from weinstein.exporter import export_exit_results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Weinstein-Albert: escáner de condiciones de salida"
    )
    parser.add_argument(
        "--input", "-i",
        default=DEFAULT_POSITIONS_CSV,
        help=f"Ruta al CSV de posiciones abiertas (por defecto: {DEFAULT_POSITIONS_CSV})",
    )
    args = parser.parse_args()

    df = run_exit_scanner(csv_path=args.input)
    export_exit_results(df, input_csv=args.input)