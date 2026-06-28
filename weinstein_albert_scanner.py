"""
Punto de entrada del escáner de ENTRADA — estrategia Weinstein-Albert.

Uso
---
    python weinstein_albert_scanner.py

Este script es intencionadamente delgado: delega toda la lógica al
paquete ``weinstein``. Editar los parámetros en ``weinstein/config.py``.
"""

import os
import sys
import warnings

warnings.filterwarnings("ignore")

# Permite un dry-run sin descargas para validar los scripts de arranque.
if os.getenv("WEINSTEIN_DRY_RUN") == "1":
    print("WEINSTEIN_DRY_RUN=1 — dry run, saliendo sin llamadas de red.")
    sys.exit(0)

from weinstein.exporter import export_entry_results
from weinstein.scanner import run_entry_scanner

if __name__ == "__main__":
    df = run_entry_scanner()
    export_entry_results(df)