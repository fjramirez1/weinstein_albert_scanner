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
en `backtest/.cache/`), sin invalidación automática por fecha: los datos
de mercado de una semana ya cerrada no cambian, así que no hay necesidad
de "refrescar" salvo que el usuario quiera datos de una semana nueva. Para
eso existe `refresh=True` / borrar la carpeta de caché manualmente.

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

from weinstein.data import download_weekly

CACHE_DIR = Path(__file__).parent / ".cache"


def _cache_path(ticker: str, period: str) -> Path:
    # Los tickers pueden traer caracteres poco amigables para nombres de
    # archivo (p.ej. "BRK.B"); se normalizan de forma simple y reversible
    # lo suficiente para no chocar entre sí en la práctica.
    safe_ticker = ticker.replace("/", "_").replace("\\", "_")
    return CACHE_DIR / f"{safe_ticker}__{period}.parquet"


def get_cached_weekly(
    ticker: str,
    period: str,
    refresh: bool = False,
) -> pd.DataFrame | None:
    """
    Devuelve el OHLCV semanal de `ticker` para `period`, usando caché en
    disco cuando existe. Si no existe (o `refresh=True`), descarga con
    `download_weekly` y guarda el resultado antes de devolverlo.

    Devuelve ``None`` si no hay datos disponibles (igual que
    `download_weekly`), sin escribir caché en ese caso, para que un fallo
    puntual de red no se "congele" como ausencia permanente de datos.
    """
    path = _cache_path(ticker, period)

    if not refresh and path.exists():
        try:
            return pd.read_parquet(path)
        except Exception as exc:
            # Caché corrupta (p.ej. interrupción a mitad de escritura):
            # se ignora y se vuelve a descargar en vez de fallar.
            print(f"  ⚠ [{ticker}] caché corrupta, redescargando: {exc}", file=sys.stderr)

    data = download_weekly(ticker, period=period)
    if data is None:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data.to_parquet(path)
    except Exception as exc:
        print(f"  ⚠ [{ticker}] no se pudo escribir caché: {exc}", file=sys.stderr)

    return data


def cache_stats() -> dict:
    """Información básica de la caché actual (nº de archivos, tamaño total en MB)."""
    if not CACHE_DIR.exists():
        return {"n_archivos": 0, "tamano_mb": 0.0}
    files = list(CACHE_DIR.glob("*.parquet"))
    total_bytes = sum(f.stat().st_size for f in files)
    return {"n_archivos": len(files), "tamano_mb": round(total_bytes / (1024 * 1024), 2)}


def clear_cache() -> int:
    """Borra todos los archivos cacheados. Devuelve cuántos se borraron."""
    if not CACHE_DIR.exists():
        return 0
    files = list(CACHE_DIR.glob("*.parquet"))
    for f in files:
        f.unlink()
    return len(files)
