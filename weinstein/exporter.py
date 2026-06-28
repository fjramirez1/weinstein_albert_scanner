"""
Exportación de resultados a CSV con registro histórico.

Los archivos se guardan en carpetas separadas según el tipo de escáner
(entradas / salidas), con marca de tiempo en el nombre del archivo.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from weinstein.config import HISTORY_ENTRIES_DIR, HISTORY_EXITS_DIR


def _export(df: pd.DataFrame, directory: str, stem: str) -> Path | None:
    """
    Lógica común de exportación: crea la carpeta si no existe y guarda.

    Retorna la ruta del archivo creado, o ``None`` si el DataFrame
    estaba vacío.
    """
    if df.empty:
        return None

    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    path      = folder / f"{stem}_{timestamp}.csv"

    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\n  ✅ Resultados exportados → {path}")
    return path


def export_entry_results(df: pd.DataFrame) -> Path | None:
    """
    Guarda el CSV del escáner de entrada en ``historial/entradas/``.

    Nombre del archivo: ``weinstein_albert_scan_YYYYMMDD_HHMM.csv``
    """
    return _export(df, HISTORY_ENTRIES_DIR, "weinstein_albert_scan")


def export_exit_results(df: pd.DataFrame, input_csv: str) -> Path | None:
    """
    Guarda el CSV del escáner de salida en ``historial/salidas/``.

    El prefijo del nombre replica el stem del CSV de posiciones para
    facilitar la trazabilidad:
    ``<stem>_salidas_YYYYMMDD_HHMM.csv``
    """
    stem = Path(input_csv).stem + "_salidas"
    return _export(df, HISTORY_EXITS_DIR, stem)