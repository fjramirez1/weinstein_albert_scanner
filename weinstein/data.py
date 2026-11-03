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
import threading
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


# ── Normalización de velas semanales ──────────────────────────────────
#
# yfinance etiqueta cada vela semanal con el LUNES de la semana; Tiingo con
# el VIERNES (último día de la semana). El backtest de cartera cruza series
# por fecha exacta, así que sin normalizar los tickers servidos por Tiingo
# (precisamente los delistados) nunca coincidían con el calendario del
# S&P 500 y no podían operar (bug B1, ver docs/BITACORA.md 2026-11-03).
#
# Convención única del proyecto: cada vela se etiqueta con el VIERNES de su
# semana de negociación (lunes-viernes), venga de la fuente que venga.
#
# Además se descarta la vela de la semana en curso si aún no ha cerrado
# (bug B3): si se descarga a mitad de semana, la última vela es parcial y
# sus indicadores cambiarían antes del cierre real del viernes.

_MARKET_TZ = "America/New_York"
_WEEKLY_CLOSE_TIME = pd.Timedelta(hours=16, minutes=30)  # margen tras el cierre de las 16:00


def last_closed_friday(now: pd.Timestamp | None = None) -> pd.Timestamp:
    """
    Viernes (fecha sin hora) de la última semana bursátil ya cerrada.

    Una semana se da por cerrada a partir del viernes a las 16:30 hora de
    Nueva York. ``now`` es inyectable para tests; si no lleva zona horaria
    se interpreta ya en hora de Nueva York.
    """
    if now is None:
        now = pd.Timestamp.now(tz=_MARKET_TZ)
    elif now.tzinfo is not None:
        now = now.tz_convert(_MARKET_TZ)
    now = now.tz_localize(None) if now.tzinfo is not None else now

    day = now.normalize()
    friday = day - pd.Timedelta(days=(day.weekday() - 4) % 7)
    if friday == day and now - day < _WEEKLY_CLOSE_TIME:
        friday -= pd.Timedelta(days=7)
    return friday


def normalize_weekly_bars(
    df: pd.DataFrame,
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Reetiqueta cada vela con el viernes de su semana y descarta la semana
    en curso si aún no ha cerrado (ver comentario de la sección).

    Idempotente: aplicarla dos veces da el mismo resultado, así que también
    se usa al leer de la caché en disco. Si dos filas caen en la misma
    semana (yfinance a veces añade una fila extra con la fecha de hoy) se
    conserva la última.
    """
    if df is None or df.empty:
        return df

    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    idx = idx.normalize()
    fridays = idx - pd.to_timedelta(idx.weekday - 4, unit="D")

    out = df.copy()
    out.index = pd.DatetimeIndex(fridays, name="Date")
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.loc[out.index <= last_closed_friday(now)]


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


def _tiingo_api_keys() -> list[str]:
    """
    API keys de Tiingo configuradas, en orden y sin duplicados. Se leen de
    `TIINGO_API_KEYS` (separadas por comas) y de `TIINGO_API_KEY`,
    `TIINGO_API_KEY_2`, `TIINGO_API_KEY_3`... Con varias claves, cada una
    tiene su propio contador y bloqueo (ver "Límite de peticiones").
    Nunca se imprimen: en los mensajes se identifican como "clave 1", "clave 2"...
    """
    raw = [k for k in os.environ.get("TIINGO_API_KEYS", "").split(",")]
    raw.append(os.environ.get("TIINGO_API_KEY", ""))
    n = 2
    while os.environ.get(f"TIINGO_API_KEY_{n}"):
        raw.append(os.environ[f"TIINGO_API_KEY_{n}"])
        n += 1
    keys: list[str] = []
    for k in raw:
        k = k.strip()
        if k and k not in keys:
            keys.append(k)
    return keys


def _tiingo_api_key() -> str | None:
    """Primera API key de Tiingo configurada (o ``None``). Ver `_tiingo_api_keys`."""
    keys = _tiingo_api_keys()
    return keys[0] if keys else None


def tiingo_key_count() -> int:
    """Nº de API keys de Tiingo configuradas."""
    return len(_tiingo_api_keys())


# Alias de tickers que cambiaron de símbolo sin deslistarse realmente
# (la empresa sigue cotizando bajo el símbolo nuevo). Se prueba SOLO
# como último recurso dentro del fallback Tiingo, cuando el símbolo
# original no devuelve nada.
_KNOWN_TICKER_RENAMES: dict[str, str] = {
    "WLTW": "WTW",   # Willis Towers Watson, cambio de ticker
    "ADS":  "BFH",   # Alliance Data Systems -> Bread Financial
    "DISCA": "WBD",  # Discovery -> Warner Bros. Discovery
    "FBHS": "FBIN",  # Fortune Brands Home & Security -> Fortune Brands Innovations
    "HFC":  "DINO",  # HollyFrontier -> HF Sinclair
    "RE":   "EG",    # Everest Re -> Everest Group
    "GPS":  "GAP",   # Gap Inc. cambió de símbolo en 2024
    "FLT":  "CPAY",  # FLEETCOR -> Corpay (2024)
}


# ── Límite de peticiones de Tiingo (plan gratuito) ─────────────────────
#
# El plan gratuito de Tiingo permite ~50 peticiones/hora, ~1000/día y 500
# símbolos distintos/mes. Al superarlo NO hay que confundir la respuesta con
# "ticker sin datos": `backtest/data_cache.py` escribe un marcador `.nodata`
# PERMANENTE para los delistados sin datos, así que un ticker limitado se
# perdería para siempre. Por eso un límite se señala con la excepción
# `TiingoRateLimitError` (nunca con ``None``) y, una vez detectado, se
# bloquean las siguientes llamadas del proceso sin tocar la red hasta que
# abra la siguiente ventana (no se martillea la API).
#
# Tiingo lo señala con HTTP 429 o, a veces, con HTTP 200 y un dict JSON del
# tipo {"detail": "Error: You have run over your hourly request
# allocation..."} en lugar de la lista de velas; se detectan ambas formas.
#
# Además se cuentan TODAS las peticiones HTTP hechas (incluidos los
# reintentos con alias de `_KNOWN_TICKER_RENAMES`) y se puede fijar un
# presupuesto por proceso (`set_tiingo_budget`): al agotarlo se lanza
# `TiingoBudgetExhaustedError` ANTES de hacer la petición. Lo usa el
# descargador reanudable `backtest/download_data.py`.
#
# Varias API keys (`_tiingo_api_keys`): cada petición usa la clave no
# bloqueada con menos peticiones en este proceso. Si Tiingo limita una
# clave, se bloquea SOLO esa y la misma descarga se reintenta con otra; el
# proceso solo queda bloqueado (`TiingoRateLimitError`) cuando lo están
# todas. El presupuesto de `set_tiingo_budget` es el total del proceso
# (el descargador lo multiplica por el nº de claves).


class TiingoRateLimitError(RuntimeError):
    """
    Tiingo no ha servido el ticker por límite de peticiones (no por falta de
    datos). ``motivo`` es "hora", "dia", "mes" o "presupuesto";
    ``bloqueado_hasta`` es el epoch (``time.time()``) a partir del cual tiene
    sentido volver a intentarlo (``float("inf")`` si no se sabe, p.ej. el
    límite mensual).
    """

    def __init__(self, mensaje: str, motivo: str = "hora", bloqueado_hasta: float | None = None):
        super().__init__(mensaje)
        self.motivo = motivo
        self.bloqueado_hasta = bloqueado_hasta


class TiingoBudgetExhaustedError(TiingoRateLimitError):
    """Se agotó el presupuesto de peticiones fijado con `set_tiingo_budget` (no se llegó a llamar a la API)."""


class TiingoUnavailableError(RuntimeError):
    """
    Fallo de Tiingo que NO demuestra que el ticker carezca de datos (error
    de red, HTTP 5xx, JSON inválido, token inválido). Solo se lanza con
    ``download_weekly_tiingo(..., raise_on_error=True)``; sin ese flag se
    devuelve ``None`` como siempre. ``motivo``: "red", "http" o "token".
    """

    def __init__(self, mensaje: str, motivo: str = "red"):
        super().__init__(mensaje)
        self.motivo = motivo


_tiingo_lock = threading.Lock()
_tiingo_requests = 0
_tiingo_budget: int | None = None
_tiingo_key_requests: dict[int, int] = {}
_tiingo_key_blocks: dict[int, TiingoRateLimitError] = {}

# Margen tras el inicio de la siguiente ventana antes de reintentar.
_TIINGO_WINDOW_MARGIN_S = 60


def next_hour_window(now: float | None = None) -> float:
    """Epoch del inicio de la siguiente hora de reloj (más un margen)."""
    now = time.time() if now is None else now
    return (int(now // 3600) + 1) * 3600 + _TIINGO_WINDOW_MARGIN_S


def next_day_window(now: float | None = None) -> float:
    """Epoch de la siguiente medianoche UTC (más un margen)."""
    now = time.time() if now is None else now
    return (int(now // 86400) + 1) * 86400 + _TIINGO_WINDOW_MARGIN_S


def tiingo_requests_made() -> int:
    """Nº de peticiones HTTP a Tiingo hechas por este proceso desde el último reset."""
    return _tiingo_requests


def tiingo_requests_by_key() -> dict[int, int]:
    """Peticiones hechas por cada clave (1, 2, ...) desde el último reset."""
    return {i + 1: n for i, n in sorted(_tiingo_key_requests.items())}


def set_tiingo_budget(budget: int | None) -> None:
    """Fija el máximo de peticiones a Tiingo permitidas (``None`` = sin límite propio)."""
    global _tiingo_budget
    with _tiingo_lock:
        _tiingo_budget = budget


def reset_tiingo_state() -> None:
    """Pone a cero contadores, quita el presupuesto y los bloqueos (inicio de ventana nueva / tests)."""
    global _tiingo_requests, _tiingo_budget
    with _tiingo_lock:
        _tiingo_requests = 0
        _tiingo_budget = None
        _tiingo_key_requests.clear()
        _tiingo_key_blocks.clear()


def _active_blocks_locked(n_keys: int) -> dict[int, TiingoRateLimitError]:
    """Bloqueos vigentes (caduca los vencidos). Requiere `_tiingo_lock`."""
    now = time.time()
    for i, blk in list(_tiingo_key_blocks.items()):
        if i >= n_keys or (blk.bloqueado_hasta is not None and now >= blk.bloqueado_hasta):
            del _tiingo_key_blocks[i]
    return dict(_tiingo_key_blocks)


def _all_blocked_error(ticker: str, blocks: dict[int, TiingoRateLimitError]) -> TiingoRateLimitError:
    first = min(blocks.values(), key=lambda b: b.bloqueado_hasta or float("inf"))
    sufijo = " (todas las claves)" if len(blocks) > 1 else ""
    return TiingoRateLimitError(
        f"[{ticker}] Tiingo bloqueado por límite previo ({first.motivo}){sufijo}",
        motivo=first.motivo, bloqueado_hasta=first.bloqueado_hasta,
    )


def tiingo_block() -> TiingoRateLimitError | None:
    """Bloqueo del proceso: solo si TODAS las claves están limitadas (o ``None``)."""
    n_keys = max(1, tiingo_key_count())
    with _tiingo_lock:
        blocks = _active_blocks_locked(n_keys)
    if len(blocks) < n_keys:
        return None
    return _all_blocked_error("-", blocks)


def _reserve_tiingo_request(ticker: str) -> tuple[int, str]:
    """
    Elige clave (la no bloqueada con menos peticiones), comprueba el
    presupuesto y cuenta la petición (atómico entre hilos). Devuelve
    (índice, clave). Lanza `TiingoRateLimitError` si no se puede.
    """
    global _tiingo_requests
    keys = _tiingo_api_keys()
    with _tiingo_lock:
        blocks = _active_blocks_locked(len(keys))
        libres = [i for i in range(len(keys)) if i not in blocks]
        if not libres:
            raise _all_blocked_error(ticker, blocks)
        if _tiingo_budget is not None and _tiingo_requests >= _tiingo_budget:
            raise TiingoBudgetExhaustedError(
                f"[{ticker}] presupuesto de peticiones a Tiingo agotado "
                f"({_tiingo_requests}/{_tiingo_budget})",
                motivo="presupuesto", bloqueado_hasta=next_hour_window(),
            )
        idx = min(libres, key=lambda i: (_tiingo_key_requests.get(i, 0), i))
        _tiingo_requests += 1
        _tiingo_key_requests[idx] = _tiingo_key_requests.get(idx, 0) + 1
    return idx, keys[idx]


def _tiingo_limit_reason(texto: str) -> str | None:
    """
    Si ``texto`` (campo "detail" de Tiingo) describe un límite de peticiones,
    devuelve su ventana ("hora", "dia", "mes"); si no, ``None``.
    """
    low = texto.lower()
    claves = ("allocation", "run over", "rate limit", "too many requests", "request limit")
    if not any(k in low for k in claves):
        return None
    if "month" in low:
        return "mes"
    if "daily" in low or "day" in low:
        return "dia"
    return "hora"


def _block_tiingo_key(idx: int, ticker: str, motivo: str, detalle: str) -> None:
    """Bloquea la clave `idx` hasta su siguiente ventana y lo registra en stderr."""
    if motivo in ("mes", "token"):
        hasta = float("inf")
    elif motivo == "dia":
        hasta = next_day_window()
    else:
        hasta = next_hour_window()
    exc = TiingoRateLimitError(
        f"[{ticker}] Tiingo: límite de peticiones alcanzado ({motivo}, clave {idx + 1}): {detalle}",
        motivo=motivo, bloqueado_hasta=hasta,
    )
    with _tiingo_lock:
        _tiingo_key_blocks[idx] = exc
    print(f"  ⚠ {exc}", file=sys.stderr)


def _limit_in_response(response) -> tuple[str, str] | None:
    """
    (motivo, detalle) si la respuesta de Tiingo es un límite de peticiones:
    HTTP 429, o un error/HTTP 200 cuyo {"detail": ...} lo describe.
    """
    detalle = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            detalle = str(body.get("detail", ""))
    except Exception:
        pass
    if response.status_code == 429:
        return (_tiingo_limit_reason(detalle) or "hora", detalle or "HTTP 429")
    motivo = _tiingo_limit_reason(detalle) if detalle else None
    return (motivo, detalle) if motivo else None


def download_weekly_tiingo(
    ticker: str,
    period_years: int = 15,
    min_bars: int = MIN_BARS,
    raise_on_error: bool = False,
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

    Lanza ``TiingoRateLimitError`` (nunca devuelve ``None``) si Tiingo
    responde con límite de peticiones, si el proceso ya estaba bloqueado por
    un límite previo o si se agotó el presupuesto de `set_tiingo_budget`:
    "limitado" no es "sin datos" (ver sección "Límite de peticiones").

    Con ``raise_on_error=True`` los fallos que no prueban ausencia de datos
    (red, HTTP 5xx, JSON inválido, token 401) lanzan
    ``TiingoUnavailableError`` en vez de devolver ``None``; lo usa el
    descargador `backtest/download_data.py` para no marcar `.nodata` por un
    fallo transitorio.
    """

    def fallo(mensaje: str, motivo: str) -> None:
        print(f"  ⚠ [{ticker}] Tiingo: {mensaje}", file=sys.stderr)
        if raise_on_error:
            raise TiingoUnavailableError(f"[{ticker}] Tiingo: {mensaje}", motivo=motivo)

    global _tiingo_missing_key_warned

    if not _tiingo_api_keys():
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
    }

    # Con varias claves, un límite (o un token inválido) en una se reintenta
    # con otra; `_reserve_tiingo_request` lanza TiingoRateLimitError cuando
    # ya no queda ninguna disponible.
    while True:
        key_idx, token = _reserve_tiingo_request(ticker)
        try:
            response = requests.get(url, params={**params, "token": token}, timeout=20)
        except Exception as exc:
            fallo(f"error de red: {exc}", "red")
            return None
        limite = _limit_in_response(response)
        if limite:
            _block_tiingo_key(key_idx, ticker, *limite)
            continue
        if response.status_code == 401 and tiingo_key_count() > 1:
            _block_tiingo_key(key_idx, ticker, "token", "HTTP 401: token inválido o sin permisos")
            with _tiingo_lock:
                quedan = len(_active_blocks_locked(tiingo_key_count())) < tiingo_key_count()
            if quedan:
                continue
        break

    if response.status_code == 404:
        # Ticker no reconocido por Tiingo -- puede ser un cambio de
        # símbolo conocido (ver _KNOWN_TICKER_RENAMES) antes de darlo
        # por perdido.
        alias = _KNOWN_TICKER_RENAMES.get(ticker.strip().upper())
        if alias:
            print(f"  → [{ticker}] probando alias conocido de símbolo: {alias}", file=sys.stderr)
            return download_weekly_tiingo(alias, period_years=period_years, min_bars=min_bars,
                                          raise_on_error=raise_on_error)
        return None
    if response.status_code == 401:
        fallo("token inválido o sin permisos (HTTP 401). Revisa TIINGO_API_KEY.", "token")
        return None
    try:
        response.raise_for_status()
    except Exception as exc:
        fallo(f"HTTP {response.status_code}: {exc}", "http")
        return None

    try:
        payload = response.json()
    except Exception as exc:
        fallo(f"respuesta no es JSON válido: {exc}", "http")
        return None

    if isinstance(payload, dict):
        # Tiingo responde a veces HTTP 200 con {"detail": "..."} en vez de la
        # lista de velas. Los límites ya se trataron arriba
        # (`_limit_in_response`); aquí solo queda un error del ticker.
        detalle = str(payload.get("detail", payload))
        print(f"  ⚠ [{ticker}] Tiingo: respuesta inesperada: {detalle[:200]}", file=sys.stderr)
        payload = []

    if not payload:
        alias = _KNOWN_TICKER_RENAMES.get(ticker.strip().upper())
        if alias:
            print(f"  → [{ticker}] probando alias conocido de símbolo: {alias}", file=sys.stderr)
            return download_weekly_tiingo(alias, period_years=period_years, min_bars=min_bars,
                                          raise_on_error=raise_on_error)
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
    raw = normalize_weekly_bars(raw)

    if len(raw) >= min_bars:
        print(f"  ✓ [{ticker}] recuperado vía Tiingo (fallback, {len(raw)} velas)")
        return raw

    # Histórico insuficiente con este símbolo -- probar alias conocido
    # antes de rendirse (ver _KNOWN_TICKER_RENAMES).
    alias = _KNOWN_TICKER_RENAMES.get(ticker.strip().upper())
    if alias:
        print(f"  → [{ticker}] probando alias conocido de símbolo: {alias}", file=sys.stderr)
        return download_weekly_tiingo(alias, period_years=period_years, min_bars=min_bars,
                                          raise_on_error=raise_on_error)

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
    use_tiingo: bool = True,
    raise_on_rate_limit: bool = False,
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

    ``use_tiingo=False`` desactiva el fallback (fase yfinance del
    descargador `backtest/download_data.py`). Si Tiingo está limitado
    (`TiingoRateLimitError`), por defecto se devuelve ``None`` (los
    escáneres no distinguen); con ``raise_on_rate_limit=True`` se propaga la
    excepción para que el llamador NO lo confunda con "sin datos" (lo usa
    `backtest/data_cache.py` para no escribir un `.nodata` permanente).
    """
    def fallback() -> pd.DataFrame | None:
        if not use_tiingo:
            return None
        try:
            return _try_tiingo_fallback(ticker)
        except TiingoRateLimitError:
            if raise_on_rate_limit:
                raise
            return None

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
            return fallback()

        if raw is None or raw.empty:
            # No es necesariamente un error de red: puede ser un ticker
            # deslistado o sin histórico. No merece reintento agresivo,
            # pero sí un aviso si ocurre en el último intento.
            if intento < max_retries:
                time.sleep(DOWNLOAD_RETRY_BACKOFF_S * intento)
                continue
            print(f"  ⚠ [{ticker}] sin datos devueltos por yfinance", file=sys.stderr)
            return fallback()

        # Normalizar MultiIndex que yfinance introduce en algunas versiones.
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in raw.columns]
        raw  = raw[cols].copy()
        raw.dropna(subset=["Close"], inplace=True)
        raw = normalize_weekly_bars(raw)

        if len(raw) < MIN_BARS:
            print(
                f"  ⚠ [{ticker}] histórico insuficiente ({len(raw)} < {MIN_BARS} velas)",
                file=sys.stderr,
            )
            return fallback()

        return raw

    if last_exc is not None:
        print(f"  ✗ [{ticker}] error de descarga: {last_exc}", file=sys.stderr)
    return fallback()


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