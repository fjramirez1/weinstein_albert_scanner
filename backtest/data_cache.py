"""
Caché en disco de datos OHLCV semanales para el backtest de cartera.

Motivación
----------
`portfolio_backtest.py` está pensado para lanzarse muchas veces seguidas
probando distintas configuraciones de estrategia (activar/desactivar
condiciones, cambiar umbrales, cambiar el criterio de desempate...).
La parte lenta de cada ejecución no es la simulación en sí (es CPU-bound
y rápida sobre datos ya descargados), es la DESCARGA por red de ~500
tickers vía yfinance.

Este módulo separa completamente "descargar" de "simular": los datos
OHLCV de cada ticker se descargan una única vez y se guardan en disco en
formato parquet, bajo una clave (ticker, periodo). Ejecuciones
posteriores del backtest con la MISMA ventana temporal reutilizan el
fichero cacheado sin tocar la red, así que solo la primera ejecución es
lenta.

La caché es deliberadamente simple (un archivo parquet por ticker+periodo
en `backtest/.cache/`). Caducidad: el fichero de un ticker que sigue en el
índice se vuelve a descargar en cuanto cierra una semana que no contiene
(`weinstein.data.last_closed_friday`); el de un ticker delistado vale para
siempre (su histórico ya no crece). `refresh=True` fuerza la descarga.

Caché de FALLOS (tickers sin histórico suficiente o sin datos)
------------------------------------------------------------------
Cuando `universe="historical"` (ver `sp500_historical.py`), el universo
a procesar incluye tickers que ya NO pertenecen al S&P 500 actual (p.ej.
`FRC`, `APC`, `CDAY`) y otros que sí pertenecen pero tienen histórico
insuficiente por ser altas muy recientes (p.ej. un spin-off que entró al
índice hace pocas semanas). Sin caché de fallos, cada ejecución del
backtest repetiría la descarga fallida de esos mismos tickers,
indefinidamente.

La clave para cachear un fallo sin arriesgar "perder" un ticker que
vuelve a tener datos válidos es: **solo se cachea el fallo de tickers
que HOY ya no pertenecen al S&P 500 actual**. Su histórico es finito y
quedó fijado en el pasado — si falló una vez, va a seguir fallando
siempre con la misma fuente de datos, así que no tiene sentido
reintentar. Para un ticker que SÍ pertenece al índice actual, el fallo
puede ser transitorio (histórico insuficiente hoy, pero que crecerá con
cada semana que pase) o del todo permanente (deslistado a mitad de
periodo); en cualquiera de esos casos se prefiere reintentar en cada
ejecución antes que arriesgarse a dejarlo "congelado" como fallo para
siempre.

Caso límite cubierto explícitamente: un ticker fuera del índice hoy
(con fallo ya cacheado) que en el futuro VUELVE a formar parte del S&P
500 -- ya sea la misma empresa o, como ha pasado literalmente con el
símbolo `Q`, una empresa distinta reutilizando el mismo símbolo. En
cuanto `load_sp500_tickers()` lo detecte como constituyente actual, el
marcador de fallo antiguo se ignora y se borra automáticamente (ver
`get_cached_weekly`), sin necesidad de intervención manual.

Límite de Tiingo: "limitado" no es "sin datos"
----------------------------------------------
Si el fallback Tiingo responde con límite de peticiones
(`weinstein.data.TiingoRateLimitError`), `get_cached_weekly` NO escribe el
marcador `.nodata` (el ticker se perdería para siempre) y devuelve la caché
antigua si la hay o ``None``: se reintentará en la próxima ejecución. El
descargador reanudable `backtest/download_data.py` usa `cache_status`,
`save_cached` y `mark_nodata` de este módulo para poblar la caché
respetando el presupuesto horario de Tiingo.

Nota técnica: el formato parquet no conserva el atributo `.freq` del
`DatetimeIndex` original (pandas lo recupera como `None` tras un
roundtrip). Los VALORES y FECHAS se conservan exactos; solo se pierde
esa metadata de conveniencia, que ningún cálculo del proyecto utiliza
(`weinstein/indicators.py` y `backtest/conditions.py` operan por
`.iloc[]`/alineación de índice, no por `.freq`), así que no afecta a la
lógica de negocio.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from weinstein.config import TIINGO_PRICE_SYMBOLS
from weinstein.data import (
    TiingoRateLimitError,
    TiingoUnavailableError,
    download_weekly,
    download_weekly_tiingo,
    last_closed_friday,
    normalize_weekly_bars,
    period_to_years,
)

CACHE_DIR = Path(__file__).parent / ".cache"


def _cache_path(ticker: str, period: str) -> Path:
    # Los tickers pueden traer caracteres poco amigables para nombres de
    # archivo (p.ej. "BRK.B"); se normalizan de forma simple y reversible
    # lo suficiente para no chocar entre sí en la práctica.
    safe_ticker = ticker.replace("/", "_").replace("\\", "_")
    return CACHE_DIR / f"{safe_ticker}__{period}.parquet"


def _fail_marker_path(ticker: str, period: str) -> Path:
    """
    Ruta del marcador de "descarga fallida y no reintentable" para un
    ticker+periodo. Solo se escribe/respeta para tickers que ya NO
    pertenecen al S&P 500 actual (ver docstring del módulo).
    """
    safe_ticker = ticker.replace("/", "_").replace("\\", "_")
    return CACHE_DIR / f"{safe_ticker}__{period}.nodata"


def read_cached(ticker: str, period: str) -> pd.DataFrame | None:
    """Lee (normalizado) el parquet cacheado de `ticker`+`period`; ``None`` si no existe, está vacío o corrupto."""
    path = _cache_path(ticker, period)
    if not path.exists():
        return None
    try:
        # Normalizar también al leer: cubre ficheros escritos antes de
        # introducir la convención de velas en viernes (bug B1).
        cached = normalize_weekly_bars(pd.read_parquet(path))
    except Exception as exc:
        # Caché corrupta (p.ej. interrupción a mitad de escritura): se
        # ignora y se vuelve a descargar en vez de fallar.
        print(f"  ⚠ [{ticker}] caché corrupta, redescargando: {exc}", file=sys.stderr)
        return None
    return cached if cached is not None and not cached.empty else None


def cache_status(ticker: str, period: str, is_current_constituent: bool = True) -> str:
    """
    Estado de la caché de `ticker`+`period` con las MISMAS reglas que
    `get_cached_weekly`, sin tocar la red:

    - "ok": hay parquet y no está caducado (delistado, o vigente al día).
    - "caducado": parquet de un vigente al que le falta la última semana cerrada.
    - "nodata": marcador de fallo permanente (solo cuenta si no es vigente).
    - "falta": no hay nada cacheado.
    """
    if not is_current_constituent and _fail_marker_path(ticker, period).exists():
        return "nodata"
    cached = read_cached(ticker, period)
    if cached is None:
        return "falta"
    if not is_current_constituent or cached.index[-1] >= last_closed_friday():
        return "ok"
    return "caducado"


def save_cached(ticker: str, period: str, data: pd.DataFrame) -> pd.DataFrame | None:
    """
    Normaliza y guarda `data` en la caché, borrando un marcador `.nodata`
    previo. Devuelve el DataFrame normalizado, o ``None`` si queda vacío.
    """
    data = normalize_weekly_bars(data)
    if data is None or data.empty:
        return None
    fail_path = _fail_marker_path(ticker, period)
    if fail_path.exists():
        try:
            fail_path.unlink()
        except FileNotFoundError:
            pass
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data.to_parquet(_cache_path(ticker, period))
    except Exception as exc:
        print(f"  ⚠ [{ticker}] no se pudo escribir caché: {exc}", file=sys.stderr)
    return data


def mark_nodata(ticker: str, period: str) -> None:
    """Escribe el marcador de fallo permanente (solo para tickers que ya NO son constituyentes)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _fail_marker_path(ticker, period).touch()
    except Exception as exc:
        print(f"  ⚠ [{ticker}] no se pudo escribir marcador de fallo: {exc}", file=sys.stderr)


def get_cached_weekly(
    ticker: str,
    period: str,
    refresh: bool = False,
    is_current_constituent: bool = True,
) -> pd.DataFrame | None:
    """
    Devuelve el OHLCV semanal de `ticker` para `period`, usando caché en
    disco cuando existe. Si no existe (o `refresh=True`), descarga con
    `download_weekly` y guarda el resultado antes de devolverlo.

    Devuelve ``None`` si no hay datos disponibles (igual que
    `download_weekly`).

    Parameters
    ----------
    is_current_constituent : indica si `ticker` pertenece HOY al S&P 500
        actual (ver `weinstein.data.load_sp500_tickers()`). Por defecto
        `True` (comportamiento conservador: nunca cachea un fallo salvo
        que el llamador confirme explícitamente que el ticker ya no
        pertenece al índice actual).

        - Si es `True`: nunca se cachea el fallo, se reintenta la
          descarga en cada llamada (igual que antes de introducir esta
          caché de fallos). Cubre tanto el caso de histórico insuficiente
          transitorio (alta reciente que aún no acumula suficientes
          semanas) como cualquier otro fallo que convenga reintentar.
        - Si es `False`: el ticker ya no forma parte del índice actual,
          así que su histórico es finito y no puede "crecer" con el
          tiempo. Un fallo se cachea de forma persistente (marcador
          `.nodata`) para no repetir la descarga en cada ejecución del
          backtest. Si en el futuro el ticker vuelve a aparecer en el
          S&P 500 actual (misma empresa o símbolo reutilizado por otra),
          basta con volver a llamar con `is_current_constituent=True`
          (lo hará automáticamente `portfolio_backtest.py` en cuanto
          `load_sp500_tickers()` lo detecte) para que el marcador
          antiguo se ignore y se borre, sin intervención manual.
    """
    fail_path = _fail_marker_path(ticker, period)

    if not refresh and fail_path.exists():
        if is_current_constituent:
            # El ticker volvió a formar parte del índice actual (o nunca
            # debió cachearse como fallo permanente con la información de
            # hoy) -- el marcador antiguo ya no es de fiar. Se descarta y
            # se reintenta la descarga con normalidad más abajo.
            try:
                fail_path.unlink()
            except FileNotFoundError:
                pass
        else:
            # Sigue sin pertenecer al índice actual: su histórico no ha
            # podido cambiar desde que se cacheó el fallo, así que se
            # respeta sin tocar la red.
            return None

    cached = None if refresh else read_cached(ticker, period)

    if cached is not None:
        # Caducidad (B10): un ticker delistado tiene histórico cerrado y su
        # caché vale para siempre; uno vigente queda desfasado en cuanto
        # cierra una semana nueva que no está en el fichero.
        if not is_current_constituent or cached.index[-1] >= last_closed_friday():
            return cached

    try:
        if not is_current_constituent and ticker in TIINGO_PRICE_SYMBOLS:
            # Ticker reutilizado por otra empresa: yfinance devolvería la
            # nueva; Tiingo conserva la antigua con otro símbolo.
            data = download_weekly_tiingo(
                TIINGO_PRICE_SYMBOLS[ticker], period_years=period_to_years(period), raise_on_error=True,
            )
        else:
            # Tiingo solo para delistados: un vigente lo sirve yfinance y, si
            # tiene pocas velas (alta reciente), Tiingo no tendría más; así no
            # se gasta cupo en cada ejecución del backtest.
            data = download_weekly(
                ticker, period=period,
                use_tiingo=not is_current_constituent,
                raise_on_rate_limit=True,
                raise_on_tiingo_error=True,
            )
    except (TiingoRateLimitError, TiingoUnavailableError) as exc:
        # Tiingo limitado o caído: NO es "sin datos". Sin marcador `.nodata`;
        # se reintentará en otra ejecución (ver docstring del módulo).
        if cached is not None:
            return cached
        motivo = "Tiingo limitado" if isinstance(exc, TiingoRateLimitError) else "Tiingo no disponible"
        print(f"  ⚠ [{ticker}] pendiente: {motivo}, se reintentará en otra "
              "ejecución (python -m backtest.download_data)", file=sys.stderr)
        return None
    if data is not None:
        data = normalize_weekly_bars(data)
    if data is None or data.empty:
        if cached is not None:
            # Falló el refresco: mejor datos con alguna semana de retraso
            # que ninguno (y sin marcar fallo).
            print(f"  ⚠ [{ticker}] no se pudo refrescar; se usa la caché hasta "
                  f"{cached.index[-1].date()}", file=sys.stderr)
            return cached
        if not is_current_constituent:
            mark_nodata(ticker, period)
        return None

    # Descarga con éxito: `save_cached` también limpia un marcador de fallo
    # previo (p.ej. de una ejecución anterior en la que
    # is_current_constituent era False y ahora es True).
    return save_cached(ticker, period, data)


def cache_stats() -> dict:
    """Información básica de la caché actual (nº de archivos de datos, nº de fallos cacheados, tamaño total en MB)."""
    if not CACHE_DIR.exists():
        return {"n_archivos": 0, "n_fallos_cacheados": 0, "tamano_mb": 0.0}
    data_files = list(CACHE_DIR.glob("*.parquet"))
    fail_files = list(CACHE_DIR.glob("*.nodata"))
    total_bytes = sum(f.stat().st_size for f in data_files)
    return {
        "n_archivos": len(data_files),
        "n_fallos_cacheados": len(fail_files),
        "tamano_mb": round(total_bytes / (1024 * 1024), 2),
    }


def clear_cache() -> int:
    """Borra todos los archivos cacheados (datos y marcadores de fallo). Devuelve cuántos se borraron."""
    if not CACHE_DIR.exists():
        return 0
    files = list(CACHE_DIR.glob("*.parquet")) + list(CACHE_DIR.glob("*.nodata"))
    for f in files:
        f.unlink()
    return len(files)