"""
Capa de acceso a datos de la estrategia Weinstein-Albert.

Responsabilidades
-----------------
- Descargar datos OHLCV semanales desde yfinance.
- Cargar la lista de constituyentes del S&P 500.
- Cargar el CSV de posiciones abiertas.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

from weinstein.config import (
    DEFAULT_POSITIONS_CSV,
    DOWNLOAD_MAX_RETRIES,
    DOWNLOAD_PERIOD_ENTRY,
    DOWNLOAD_RETRY_BACKOFF_S,
    MIN_BARS,
    SP500_CSV_URL,
)


# ── Descarga OHLCV semanal ────────────────────────────────────────────

def download_weekly(
    ticker: str,
    period: str = DOWNLOAD_PERIOD_ENTRY,
    max_retries: int = DOWNLOAD_MAX_RETRIES,
) -> pd.DataFrame | None:
    """
    Descarga datos OHLCV semanales de un ticker con yfinance.

    Reintenta con backoff lineal ante fallos puntuales de red o
    rate-limiting (yfinance es notoriamente inestable con muchas
    peticiones concurrentes). Registra en stderr el motivo del fallo
    final para poder distinguir "sin datos" de "error de red".

    Retorna un DataFrame con columnas [Open, High, Low, Close, Volume]
    o ``None`` si la descarga falla o el histórico es insuficiente.
    """
    last_exc: Exception | None = None

    for intento in range(1, max_retries + 1):
        try:
            raw = yf.download(
                ticker,
                period=period,
                interval="1wk",
                progress=False,
                auto_adjust=True,
                actions=False,
            )
        except Exception as exc:
            last_exc = exc
            if intento < max_retries:
                time.sleep(DOWNLOAD_RETRY_BACKOFF_S * intento)
                continue
            print(
                f"  ✗ [{ticker}] descarga falló tras {max_retries} intentos: {exc}",
                file=sys.stderr,
            )
            return None

        if raw is None or raw.empty:
            # No es necesariamente un error de red: puede ser un ticker
            # deslistado o sin histórico. No merece reintento agresivo,
            # pero sí un aviso si ocurre en el último intento.
            if intento < max_retries:
                time.sleep(DOWNLOAD_RETRY_BACKOFF_S * intento)
                continue
            print(f"  ⚠ [{ticker}] sin datos devueltos por yfinance", file=sys.stderr)
            return None

        # Normalizar MultiIndex que yfinance introduce en algunas versiones.
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in raw.columns]
        raw  = raw[cols].copy()
        raw.dropna(subset=["Close"], inplace=True)

        if len(raw) < MIN_BARS:
            print(
                f"  ⚠ [{ticker}] histórico insuficiente ({len(raw)} < {MIN_BARS} velas)",
                file=sys.stderr,
            )
            return None

        return raw

    if last_exc is not None:
        print(f"  ✗ [{ticker}] error de descarga: {last_exc}", file=sys.stderr)
    return None


# ── Constituyentes del S&P 500 ────────────────────────────────────────

def _sp500_from_wikipedia() -> pd.DataFrame:
    """Fuente de respaldo: tabla HTML de Wikipedia."""
    print("  → Fallback: leyendo desde Wikipedia...")
    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            attrs={"id": "constituents"},
        )
        df = tables[0].copy()
        df = df.rename(columns={"Security": "Name", "GICS Sector": "Sector"})
        df["Symbol"] = df["Symbol"].astype(str).str.replace(".", "-", regex=False)
        df = df[["Symbol", "Name", "Sector"]].dropna(subset=["Symbol"]).reset_index(drop=True)
        print(f"  ✓ {len(df)} tickers cargados desde Wikipedia.")
        return df
    except Exception as exc:
        print(f"  ✗ Fallback fallido: {exc}")
        sys.exit(1)


def load_sp500_tickers() -> pd.DataFrame:
    """
    Descarga la lista de constituyentes del S&P 500.

    Intenta primero el CSV público en GitHub; si falla, recurre a
    Wikipedia.

    Retorna un DataFrame con columnas [Symbol, Name, Sector].
    """
    print(f"  → Fuente primaria: {SP500_CSV_URL}")
    try:
        df = pd.read_csv(SP500_CSV_URL)
        df.columns = [c.strip() for c in df.columns]

        rename: dict[str, str] = {}
        for col in df.columns:
            low = col.strip().lower()
            if low in ("symbol", "ticker"):
                rename[col] = "Symbol"
            elif low in ("name", "security", "company", "company name"):
                rename[col] = "Name"
            elif "sector" in low:
                rename[col] = "Sector"
        df.rename(columns=rename, inplace=True)

        for required in ("Symbol", "Name", "Sector"):
            if required not in df.columns:
                df[required] = "N/A"

        df["Symbol"] = df["Symbol"].astype(str).str.replace(".", "-", regex=False)
        df = df[["Symbol", "Name", "Sector"]].dropna(subset=["Symbol"]).reset_index(drop=True)
        print(f"  ✓ {len(df)} tickers cargados correctamente.")
        return df

    except Exception as exc:
        print(f"  ✗ Error al descargar tickers: {exc}")
        return _sp500_from_wikipedia()


# ── CSV de posiciones abiertas ────────────────────────────────────────

def load_positions(csv_path: str = DEFAULT_POSITIONS_CSV) -> pd.DataFrame:
    """
    Carga el CSV de posiciones abiertas y valida su estructura.

    Columnas requeridas: Ticker, Sector, Precio_Entrada, Fecha_Entrada.
    Aborta con mensaje claro si el archivo no existe o faltan columnas.
    """
    path = Path(csv_path)
    if not path.exists():
        print(f"\n  ✗ No se encontró el archivo: {csv_path}")
        print(  "    Columnas requeridas: Ticker, Sector, Precio_Entrada, Fecha_Entrada")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]

    required = {"Ticker", "Sector", "Precio_Entrada", "Fecha_Entrada"}
    missing  = required - set(df.columns)
    if missing:
        print(f"\n  ✗ Faltan columnas en el CSV: {missing}")
        print(  "    Asegúrate de incluir Fecha_Entrada (formato YYYY-MM-DD)")
        sys.exit(1)

    # Bug fix: convertir explícitamente a str ANTES de .str.strip()/.str.upper().
    # Si la columna Ticker contiene NaN o valores no-string (p.ej. Excel
    # autoformateando una celda vacía o numérica), acceder a .str directamente
    # podía fallar o dejar basura ("NAN", "nan") que no se filtraba con
    # dropna(). Ahora se normaliza a texto y esos casos se convierten
    # explícitamente en NaN para que el dropna() posterior los descarte.
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df["Ticker"] = df["Ticker"].replace({"": pd.NA, "NAN": pd.NA, "NONE": pd.NA})

    df["Precio_Entrada"] = pd.to_numeric(df["Precio_Entrada"], errors="coerce")
    df["Fecha_Entrada"]  = pd.to_datetime(df["Fecha_Entrada"], errors="coerce")
    df = df.dropna(subset=["Ticker", "Precio_Entrada", "Fecha_Entrada"]).reset_index(drop=True)
    return df
