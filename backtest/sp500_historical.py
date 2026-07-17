"""
Reconstrucción histórica de la membresía del S&P 500 (altas/bajas).

Motivación
----------
`backtest/portfolio_backtest.py` y `backtest/strategy_backtest.py` usan
por defecto el universo de constituyentes ACTUALES del S&P 500
(`weinstein.data.load_sp500_tickers()`) para TODO el periodo simulado.
Esto es la causa directa del sesgo de supervivencia documentado en
`backtest/README.md`: empresas que fueron excluidas del índice durante
el periodo simulado (adquiridas, quebradas, degradadas de capitalización)
no aparecen nunca como candidatas, aunque en su momento sí cumplieran los
filtros de entrada.

Este módulo reconstruye, semana a semana, qué tickers pertenecían
realmente al S&P 500 en cada fecha del pasado, usando la tabla de
Wikipedia "Selected changes to the list of S&P 500 components" (la misma
página que ya usa `weinstein/data.py::_sp500_from_wikipedia()` como
fallback de constituyentes actuales, ver `SP500_WIKIPEDIA_URL` en
`weinstein/config.py`).

Algoritmo
---------
La tabla de cambios registra, para cada fecha efectiva, qué ticker(s) se
añadieron y cuáles se eliminaron. Partiendo del conjunto de constituyentes
ACTUALES (hoy), se puede reconstruir el conjunto en cualquier fecha pasada
"deshaciendo" los cambios en orden cronológico inverso:

    para cada cambio en la fecha C, yendo de más reciente a más antigua:
        si C > fecha_objetivo:
            deshacer el cambio -> quitar lo que se añadió en C,
                                   volver a añadir lo que se quitó en C

Es decir, para saber qué había ANTES de un cambio, se invierte ese cambio
sobre el estado que había DESPUÉS. Aplicado a todos los cambios más
recientes que `fecha_objetivo`, se obtiene el conjunto vigente en esa
fecha. `build_membership_calendar` hace esto de forma eficiente para
varias fechas ordenadas en una sola pasada (en vez de recalcular desde
cero por cada fecha), procesando los cambios una única vez.

Limitación conocida — sesgo de supervivencia PARCIAL, no eliminado
---------------------------------------------------------------------
Reconstruir bien la membresía histórica NO resuelve el problema por
completo: muchos tickers que fueron excluidos del índice hace años
(sobre todo antes de ~2015-2018, por quiebra, exclusión de bolsa o
absorción total) ya no tienen datos de precio disponibles en yfinance,
que solo cubre tickers que cotizan hoy o cotizaron hasta hace
relativamente poco. El calendario de membresía que construye este módulo
es correcto independientemente de eso, pero la DESCARGA de precios
seguirá fallando para una parte de esos tickers — el backtest debe seguir
contabilizando y reportando esos casos explícitamente (ver
`tickers_historicos_sin_precio` en `backtest/portfolio_backtest.py`), no
asumir que el sesgo desaparece.

Robustez del parsing
----------------------
La tabla de cambios de Wikipedia no es un dataset estable: ha cambiado de
nombre de columnas varias veces a lo largo de los años (p.ej. "Date" vs
"Effective Date", "Ticker" vs "Added Ticker") y puede tener filas con
huecos (una entrada de "Added" sin "Removed" correspondiente, o
viceversa, es NORMAL — no todo cambio es un reemplazo 1:1). El parser:
  - normaliza columnas por patrón (contiene "date" / "added" / "removed"),
    igual que `weinstein/data.py::load_sp500_tickers()` hace con la tabla
    de constituyentes actuales;
  - trata cada fila de forma independiente: una fila puede aportar solo
    una alta, solo una baja, o ambas;
  - descarta y cuenta (sin abortar) filas sin fecha parseable, y avisa en
    stderr si el número de filas descartadas es alto, para poder detectar
    un cambio de formato en la tabla en vez de que falle en silencio.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

from weinstein.config import SP500_WIKIPEDIA_URL
from weinstein.data import load_sp500_tickers

CACHE_DIR = Path(__file__).parent / ".cache"
CHANGES_CACHE_PATH = CACHE_DIR / "sp500_changes.parquet"


# ── Descarga y parsing de la tabla de cambios ──────────────────────────

def _normalize_ticker(raw: str) -> str | None:
    """Misma normalización que el resto del proyecto (BRK.B -> BRK-B)."""
    if raw is None:
        return None
    val = str(raw).strip().upper()
    if val in ("", "NAN", "NONE", "—", "-"):
        return None
    # Algunas celdas traen notas al pie o referencias entre corchetes.
    val = val.split("[")[0].strip()
    if not val:
        return None
    return val.replace(".", "-")


def _rename_changes_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza el esquema de columnas de la tabla de cambios por PATRÓN,
    no por nombre exacto, porque Wikipedia lo ha renombrado varias veces
    ("Date" -> "Effective Date", "Ticker" -> "Added Ticker", etc.).

    La tabla puede venir con MultiIndex de columnas (cabeceras agrupadas
    "Added" / "Removed" con subcolumnas "Ticker"/"Security"); se aplana
    primero para que el patrón por substring funcione igual en ambos casos.
    """
    if isinstance(df.columns, pd.MultiIndex):
        flat = []
        for tup in df.columns:
            parts = [str(p) for p in tup if p and "Unnamed" not in str(p)]
            flat.append(" ".join(parts).strip())
        df = df.copy()
        df.columns = flat
    else:
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]

    rename: dict[str, str] = {}
    for col in df.columns:
        low = col.lower()
        if "date" in low:
            rename[col] = "Date"
        elif "added" in low and "ticker" in low:
            rename[col] = "Added_Ticker"
        elif "removed" in low and "ticker" in low:
            rename[col] = "Removed_Ticker"
        elif low.strip() == "ticker":
            # Esquemas antiguos sin agrupar "Added"/"Removed": se resuelve
            # por posición más abajo si hace falta; aquí solo se marca.
            rename.setdefault(col, col)
    df = df.rename(columns=rename)
    return df


def _fetch_changes_table_raw() -> pd.DataFrame:
    """
    Descarga la tabla de cambios cruda desde Wikipedia (sin caché).

    IMPORTANTE: no se le pasa la URL directamente a ``pd.read_html`` — lo
    hace vía ``urllib`` sin cabeceras, y Wikipedia devuelve 403 Forbidden
    a peticiones sin ``User-Agent`` identificable (las trata como bot no
    identificado). Se descarga el HTML con ``requests`` (con un
    User-Agent explícito) y se le pasa el contenido ya en memoria a
    ``pd.read_html``, evitando ese bloqueo.
    """
    headers = {
        "User-Agent": (
            "weinstein-albert-scanner/1.0 "
            "(https://github.com/; contacto para uso educativo/backtesting) "
            "python-requests"
        )
    }
    response = requests.get(SP500_WIKIPEDIA_URL, headers=headers, timeout=30)
    response.raise_for_status()

    tables = pd.read_html(response.text, attrs={"id": "changes"})
    if not tables:
        raise ValueError("No se encontró la tabla 'changes' en la página de Wikipedia")
    return tables[0]


def _parse_changes_table(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte la tabla cruda de Wikipedia en un DataFrame limpio con
    columnas [Date, Added_Ticker, Removed_Ticker] (cualquiera de los dos
    últimos puede ser None en una fila dada).

    Filas sin fecha parseable se descartan y se cuentan; si superan un
    umbral relevante se avisa en stderr (posible cambio de formato de la
    tabla fuente, no un simple hueco puntual).
    """
    df = _rename_changes_columns(raw)

    if "Date" not in df.columns:
        raise ValueError(
            f"No se reconoce la columna de fecha en la tabla de cambios "
            f"(columnas encontradas: {list(df.columns)})"
        )

    # Si el esquema es antiguo (columnas "Ticker"/"Security" repetidas sin
    # prefijo "Added"/"Removed", distinguibles solo por orden), se asume el
    # orden estándar de Wikipedia: Date, Added Ticker, Added Security,
    # Removed Ticker, Removed Security, Reason. Se resuelve por posición
    # como último recurso, solo si el renombrado por patrón no encontró
    # ambas columnas.
    if "Added_Ticker" not in df.columns or "Removed_Ticker" not in df.columns:
        cols = list(df.columns)
        ticker_like = [c for c in cols if c != "Date"]
        if len(ticker_like) >= 3:
            # Heurística conservadora: primera columna "ticker-like" tras
            # Date es Added_Ticker, la tercera (tras Added_Security) es
            # Removed_Ticker. Si no encaja, se deja como estaba y esa
            # columna quedará ausente -> esas altas/bajas no se podrán
            # usar, pero no se aborta el resto del parsing.
            df = df.rename(columns={
                ticker_like[0]: "Added_Ticker",
                ticker_like[2] if len(ticker_like) > 2 else ticker_like[0]: "Removed_Ticker",
            })

    for needed in ("Added_Ticker", "Removed_Ticker"):
        if needed not in df.columns:
            df[needed] = None

    parsed_date = pd.to_datetime(df["Date"], errors="coerce")
    n_total = len(df)
    n_sin_fecha = int(parsed_date.isna().sum())
    if n_total > 0 and n_sin_fecha / n_total > 0.05:
        print(
            f"  ⚠ sp500_historical: {n_sin_fecha}/{n_total} filas de la tabla de "
            "cambios sin fecha parseable. Puede indicar un cambio de formato "
            "en la tabla de Wikipedia; revisa el parsing si esto persiste.",
            file=sys.stderr,
        )

    out = pd.DataFrame({
        "Date": parsed_date,
        "Added_Ticker": df["Added_Ticker"].map(_normalize_ticker),
        "Removed_Ticker": df["Removed_Ticker"].map(_normalize_ticker),
    })
    out = out.dropna(subset=["Date"])
    # Filas sin NINGUNA alta ni baja aprovechable no aportan nada.
    out = out[out["Added_Ticker"].notna() | out["Removed_Ticker"].notna()]
    out = out.sort_values("Date").reset_index(drop=True)
    return out


def fetch_changes_table(refresh: bool = False) -> pd.DataFrame:
    """
    Devuelve la tabla de cambios [Date, Added_Ticker, Removed_Ticker],
    usando caché en disco (no cambia varias veces al día). Si la
    descarga o el parsing fallan, se propaga la excepción: sin esta
    tabla no es posible reconstruir membresía histórica, así que no
    tiene sentido degradar en silencio a un resultado vacío.
    """
    if not refresh and CHANGES_CACHE_PATH.exists():
        try:
            return pd.read_parquet(CHANGES_CACHE_PATH)
        except Exception as exc:
            print(
                f"  ⚠ sp500_historical: caché de cambios corrupta, redescargando: {exc}",
                file=sys.stderr,
            )

    print("  → Descargando tabla de cambios históricos del S&P 500 (Wikipedia)...")
    raw = _fetch_changes_table_raw()
    changes = _parse_changes_table(raw)
    print(f"  ✓ {len(changes)} cambios históricos parseados "
          f"({changes['Date'].min().date()} → {changes['Date'].max().date()})")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        changes.to_parquet(CHANGES_CACHE_PATH)
    except Exception as exc:
        print(f"  ⚠ sp500_historical: no se pudo escribir caché de cambios: {exc}", file=sys.stderr)

    return changes


# ── Reconstrucción de membresía ────────────────────────────────────────

def reconstruct_membership(
    as_of_date: pd.Timestamp,
    changes: pd.DataFrame,
    current_constituents: set[str],
) -> set[str]:
    """
    Reconstruye el conjunto de tickers vigentes en el S&P 500 en
    `as_of_date`, partiendo de `current_constituents` (hoy) y deshaciendo
    todos los cambios posteriores a `as_of_date`, del más reciente al más
    antiguo.

    Un cambio en fecha C se deshace así (para obtener el estado justo
    ANTES de C a partir del estado justo DESPUÉS de C):
      - lo que se AÑADIÓ en C se QUITA del conjunto.
      - lo que se ELIMINÓ en C se VUELVE A AÑADIR al conjunto.
    """
    membership = set(current_constituents)
    if changes.empty:
        return membership

    dates = pd.to_datetime(changes["Date"])
    changes_after = changes[dates > as_of_date].sort_values("Date", ascending=False)

    for _, row in changes_after.iterrows():
        added = row["Added_Ticker"]
        removed = row["Removed_Ticker"]
        if added is not None and added in membership:
            membership.discard(added)
        if removed is not None:
            membership.add(removed)

    return membership


def build_membership_calendar(
    dates: list[pd.Timestamp],
    changes: pd.DataFrame | None = None,
    current_constituents: set[str] | None = None,
) -> dict[pd.Timestamp, set[str]]:
    """
    Construye ``{fecha: set(tickers vigentes)}`` para una lista de fechas,
    en una única pasada por los cambios (en vez de invocar
    `reconstruct_membership` de forma independiente por cada fecha, lo
    que repetiría trabajo O(fechas × cambios)).

    Estrategia: se ordenan `dates` de más reciente a más antigua y se
    recorre la tabla de cambios (ya ordenada por fecha descendente) una
    sola vez, deshaciendo cambios acumulativamente y "congelando" una
    copia del conjunto cada vez que se cruza una fecha pedida.

    Parameters
    ----------
    dates : fechas para las que se quiere el snapshot de membresía. No
        necesitan venir ordenadas.
    changes : tabla de cambios ya parseada (`fetch_changes_table()`); si
        es ``None``, se descarga (con caché).
    current_constituents : constituyentes de HOY; si es ``None``, se
        descarga con `load_sp500_tickers()`.

    Returns
    -------
    Dict con una entrada por cada fecha en `dates` (mismos objetos
    Timestamp que se pasaron, sin normalizar), sin fechas de más.
    """
    if not dates:
        return {}

    if changes is None:
        changes = fetch_changes_table()
    if current_constituents is None:
        current_constituents = set(load_sp500_tickers()["Symbol"])

    membership = set(current_constituents)
    changes = changes.copy()
    changes["Date"] = pd.to_datetime(changes["Date"])
    changes_desc = changes.sort_values("Date", ascending=False).reset_index(drop=True)

    dates_desc = sorted(set(dates), reverse=True)
    result: dict[pd.Timestamp, set[str]] = {}

    change_idx = 0
    n_changes = len(changes_desc)

    for fecha in dates_desc:
        # Deshacer todos los cambios posteriores a `fecha` que aún no se
        # hayan procesado (la tabla y las fechas están ambas en orden
        # descendente, así que esto es un único recorrido lineal total).
        while change_idx < n_changes and changes_desc.loc[change_idx, "Date"] > fecha:
            added = changes_desc.loc[change_idx, "Added_Ticker"]
            removed = changes_desc.loc[change_idx, "Removed_Ticker"]
            if added is not None and added in membership:
                membership.discard(added)
            if removed is not None:
                membership.add(removed)
            change_idx += 1
        result[fecha] = set(membership)

    return result


def build_membership_calendar_cached(
    dates: list[pd.Timestamp],
    refresh: bool = False,
) -> dict[pd.Timestamp, set[str]]:
    """
    Atajo de conveniencia: descarga (con caché) tanto la tabla de cambios
    como los constituyentes actuales, y construye el calendario completo.
    Pensado para usarse directamente desde `portfolio_backtest.py`.
    """
    changes = fetch_changes_table(refresh=refresh)
    current = set(load_sp500_tickers()["Symbol"])
    return build_membership_calendar(dates, changes=changes, current_constituents=current)


def universe_union(calendar: dict[pd.Timestamp, set[str]]) -> set[str]:
    """
    Unión de todos los tickers que aparecieron en el índice en ALGÚN
    momento cubierto por `calendar`. Útil para saber qué tickers hace
    falta intentar descargar en total (superset de lo que se necesitará
    semana a semana).
    """
    union: set[str] = set()
    for tickers in calendar.values():
        union |= tickers
    return union