"""
Capa de acceso a datos de la estrategia Weinstein-Albert.

Responsabilidades
-----------------
- Descargar datos OHLCV semanales desde yfinance (con fallback a Tiingo
  para tickers delistados que Yahoo ya no sirve, ver
  ``download_weekly_tiingo`` / ``_try_tiingo_fallback``).
- Cargar la lista de constituyentes del S&P 500.
- Cargar el CSV de posiciones abiertas.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

from weinstein.config import (
    DEFAULT_POSITIONS_CSV,
    DOWNLOAD_MAX_RETRIES,
    DOWNLOAD_PERIOD_ENTRY,
    DOWNLOAD_RETRY_BACKOFF_S,
    MIN_BARS,
    SP500_CSV_URL,
    SP500_WIKIPEDIA_URL,
    TIINGO_BASE_URL,
)


# ── Fallback Tiingo para tickers delistados ───────────────────────────
#
# yfinance (Yahoo Finance) deja de servir histórico de un ticker en
# cuanto este se deslistó por completo del mercado (quiebra, fusión,
# adquisición, exclusión de bolsa, o -- caso más reciente -- salida a
# manos privadas como WBA en 2025). Esto NO es un fallo transitorio de
# red: es una limitación permanente de la fuente para ese ticker en
# concreto, y ningún número de reintentos de yfinance lo soluciona (ver
# ``DOWNLOAD_MAX_RETRIES``/``DOWNLOAD_RETRY_BACKOFF_S``).
#
# Se probó primero Stooq como fallback (scraping de su endpoint CSV
# público), pero Stooq bloquea activamente el acceso automatizado
# (robots.txt lo prohíbe explícitamente, y el endpoint /q/d/l/ devuelve
# 404 de forma poco fiable incluso para tickers que sí existen ahí --
# ver historial de incidencias equivalente en pandas-datareader). Se
# sustituyó por Tiingo (https://api.tiingo.com), que ofrece una REST API
# real con autenticación por token, sin necesidad de scraping. Tiene un
# tier gratuito (con límite de peticiones/hora) suficiente para tapar
# huecos puntuales de un backtest, no para sustituir yfinance como
# fuente principal.
#
# Requiere una API key gratuita de Tiingo, configurada en la variable de
# entorno TIINGO_API_KEY (nunca hardcodeada en el repositorio). Si la
# variable no está definida, el fallback se desactiva automáticamente
# con un único aviso (no se repite por cada ticker) en vez de fallar
# silenciosamente en cada intento.

_tiingo_missing_key_warned = False


def _tiingo_api_key() -> str | None:
    """
    Lee la API key de Tiingo desde la variable de entorno TIINGO_API_KEY.
    ...
    """
    return os.environ.get("TIINGO_API_KEY")


# Alias de tickers que cambiaron de símbolo sin deslistarse realmente
# (la empresa sigue cotizando bajo el símbolo nuevo). Se prueba SOLO
# como último recurso dentro del fallback Tiingo, cuando el símbolo
# original no devuelve nada.
_KNOWN_TICKER_RENAMES: dict[str, str] = {
    "WLTW": "WTW",   # Willis Towers Watson, cambio de ticker 2022-01-10
}


def download_weekly_tiingo(
    ticker: str,
    period_years: int = 15,
    min_bars: int = MIN_BARS,
) -> pd.DataFrame | None:
    """
    Descarga histórico semanal desde Tiingo como fuente de RESPALDO,
    pensada para usarse solo cuando ``yf.download`` ya falló (ver
    ``download_weekly``). No reintenta con backoff como la descarga
    primaria: un fallo aquí normalmente significa que el ticker tampoco
    está disponible en Tiingo (o la API key no tiene acceso a él), no un
    problema transitorio de red puntual.

    ``period_years`` es una aproximación deliberadamente generosa del
    periodo pedido a yfinance (que usa strings tipo "8y"): Tiingo pide
    fechas concretas, así que se usa una ventana lo bastante amplia
    hacia atrás y se deja que el llamador recorte lo que necesite, igual
    que hace `download_weekly` con MIN_BARS después de la descarga.

    Devuelve un DataFrame con columnas [Open, High, Low, Close, Volume]
    (mismo esquema que ``download_weekly``, usando los precios YA
    ajustados por splits/dividendos de Tiingo -- adjOpen/adjHigh/adjLow/
    adjClose/adjVolume --, coherente con ``auto_adjust=True`` en la
    descarga primaria de yfinance) o ``None`` si no hay datos
    suficientes o falta la API key.
    """
    global _tiingo_missing_key_warned

    api_key = _tiingo_api_key()
    if not api_key:
        if not _tiingo_missing_key_warned:
            print(
                "  ⚠ Fallback Tiingo desactivado: falta la variable de entorno "
                "TIINGO_API_KEY (regístrate gratis en https://www.tiingo.com para "
                "obtener una). Este aviso solo se muestra una vez.",
                file=sys.stderr,
            )
            _tiingo_missing_key_warned = True
        return None

    symbol = ticker.strip().upper().replace("-", ".")  # Tiingo usa BRK.B, no BRK-B
    start_date = (pd.Timestamp.today() - pd.DateOffset(years=period_years)).strftime("%Y-%m-%d")

    url = f"{TIINGO_BASE_URL}/{symbol}/prices"
    params = {
        "startDate": start_date,
        "format": "json",
        "resampleFreq": "weekly",
        "token": api_key,
    }

    try:
        response = requests.get(url, params=params, timeout=20)
    except Exception as exc:
        print(f"  ⚠ [{ticker}] Tiingo: error de red: {exc}", file=sys.stderr)
        return None

    if response.status_code == 404:
        # Ticker no reconocido por Tiingo -- puede ser un cambio de
        # símbolo conocido (ver _KNOWN_TICKER_RENAMES) antes de darlo
        # por perdido.
        alias = _KNOWN_TICKER_RENAMES.get(ticker.strip().upper())
        if alias:
            print(f"  → [{ticker}] probando alias conocido de símbolo: {alias}", file=sys.stderr)
            return download_weekly_tiingo(alias, period_years=period_years, min_bars=min_bars)
        return None
    if response.status_code == 401:
        print(
            f"  ✗ [{ticker}] Tiingo: token inválido o sin permisos (HTTP 401). "
            "Revisa TIINGO_API_KEY.",
            file=sys.stderr,
        )
        return None
    if response.status_code == 429:
        print(f"  ⚠ [{ticker}] Tiingo: límite de peticiones alcanzado (HTTP 429).", file=sys.stderr)
        return None
    try:
        response.raise_for_status()
    except Exception as exc:
        print(f"  ⚠ [{ticker}] Tiingo: HTTP {response.status_code}: {exc}", file=sys.stderr)
        return None

    try:
        payload = response.json()
    except Exception as exc:
        print(f"  ⚠ [{ticker}] Tiingo: respuesta no es JSON válido: {exc}", file=sys.stderr)
        return None

    if not payload:
        alias = _KNOWN_TICKER_RENAMES.get(ticker.strip().upper())
        if alias:
            print(f"  → [{ticker}] probando alias conocido de símbolo: {alias}", file=sys.stderr)
            return download_weekly_tiingo(alias, period_years=period_years, min_bars=min_bars)
        return None

    raw = pd.DataFrame(payload)
    if raw.empty or "date" not in raw.columns:
        return None

    raw["date"] = pd.to_datetime(raw["date"], errors="coerce", utc=True).dt.tz_localize(None)
    raw = raw.dropna(subset=["date"]).set_index("date").sort_index()

    # Usar precios AJUSTADOS (adj*) para ser coherentes con
    # auto_adjust=True de la descarga primaria de yfinance.
    rename = {
        "adjOpen": "Open", "adjHigh": "High", "adjLow": "Low",
        "adjClose": "Close", "adjVolume": "Volume",
    }
    missing_adj = [c for c in rename if c not in raw.columns]
    if missing_adj:
        # Fallback dentro del fallback: si por lo que sea Tiingo no trae
        # columnas ajustadas para este ticker, usar las brutas antes que
        # descartar el dato por completo.
        rename = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}

    cols_presentes = [c for c in rename if c in raw.columns]
    raw = raw[cols_presentes].rename(columns=rename)
    raw.dropna(subset=["Close"], inplace=True)

    if len(raw) >= min_bars:
        print(f"  ✓ [{ticker}] recuperado vía Tiingo (fallback, {len(raw)} velas)")
        return raw

    # Histórico insuficiente con este símbolo -- probar alias conocido
    # antes de rendirse (ver _KNOWN_TICKER_RENAMES).
    alias = _KNOWN_TICKER_RENAMES.get(ticker.strip().upper())
    if alias:
        print(f"  → [{ticker}] probando alias conocido de símbolo: {alias}", file=sys.stderr)
        return download_weekly_tiingo(alias, period_years=period_years, min_bars=min_bars)

    return None


def _try_tiingo_fallback(ticker: str) -> pd.DataFrame | None:
    """
    Punto único de entrada al fallback de Tiingo desde ``download_weekly``.

    Aislado en su propia función para poder desactivarlo globalmente con
    ``TIINGO_FALLBACK_ENABLED`` (weinstein/config.py) sin tocar la
    lógica de reintentos de yfinance, y para que el log distinga
    claramente "yfinance agotó reintentos, probando Tiingo" de un fallo
    silencioso.
    """
    from weinstein.config import TIINGO_FALLBACK_ENABLED  # import local: mantiene el acoplamiento explícito y mínimo

    if not TIINGO_FALLBACK_ENABLED:
        return None

    print(f"  → [{ticker}] yfinance sin datos, probando fallback Tiingo...", file=sys.stderr)
    return download_weekly_tiingo(ticker)


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

    Si yfinance agota todos los reintentos sin éxito (tanto por
    excepción, por "sin datos devueltos" como por histórico
    insuficiente), se intenta un único fallback a Tiingo
    (``_try_tiingo_fallback``) antes de rendirse: esto cubre el caso --
    frecuente en el backtest con universo histórico -- de tickers ya
    delistados de Yahoo Finance (quiebras, fusiones, adquisiciones,
    exclusiones de bolsa) que Tiingo sí puede tener archivados. Ver
    docstring de la sección "Fallback Tiingo" más arriba.

    Retorna un DataFrame con columnas [Open, High, Low, Close, Volume]
    o ``None`` si la descarga falla en ambas fuentes o el histórico es
    insuficiente en ambas.
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
            return _try_tiingo_fallback(ticker)

        if raw is None or raw.empty:
            # No es necesariamente un error de red: puede ser un ticker
            # deslistado o sin histórico. No merece reintento agresivo,
            # pero sí un aviso si ocurre en el último intento.
            if intento < max_retries:
                time.sleep(DOWNLOAD_RETRY_BACKOFF_S * intento)
                continue
            print(f"  ⚠ [{ticker}] sin datos devueltos por yfinance", file=sys.stderr)
            return _try_tiingo_fallback(ticker)

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
            return _try_tiingo_fallback(ticker)

        return raw

    if last_exc is not None:
        print(f"  ✗ [{ticker}] error de descarga: {last_exc}", file=sys.stderr)
    return _try_tiingo_fallback(ticker)


# ── Constituyentes del S&P 500 ────────────────────────────────────────

def _sp500_from_wikipedia() -> pd.DataFrame:
    """
    Fuente de respaldo: tabla HTML de Wikipedia.

    No se pasa la URL directamente a ``pd.read_html`` porque descarga vía
    ``urllib`` sin cabeceras, y Wikipedia devuelve 403 Forbidden a
    peticiones sin ``User-Agent`` identificable. Se descarga el HTML con
    ``requests`` (con User-Agent explícito) y se le pasa el contenido ya
    en memoria a ``pd.read_html``.
    """
    print("  → Fallback: leyendo desde Wikipedia...")
    try:
        headers = {"User-Agent": "weinstein-albert-scanner/1.0 python-requests"}
        response = requests.get(SP500_WIKIPEDIA_URL, headers=headers, timeout=30)
        response.raise_for_status()
        tables = pd.read_html(response.text, attrs={"id": "constituents"})
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