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
  - trata cada fila de forma independiente: una fila puede aportar solo
    una alta, solo una baja, o ambas;
  - descarta y cuenta (sin abortar) filas sin fecha parseable, y avisa en
    stderr si el número de filas descartadas es alto, para poder detectar
    un cambio de formato en la tabla en vez de que falle en silencio.

Parsing manual con BeautifulSoup (fix — ver historial de incidencias)
------------------------------------------------------------------------
Este módulo NO usa ``pandas.read_html`` para la tabla de cambios. Dos
problemas encontrados en la práctica lo descartaron:

1. Wikipedia sirve esta página renderizada con **Parsoid**
   (``useParsoid=1``), cuyo HTML anida mucho más marcado (``<div>``,
   ``<section>``, navboxes, etc.) que el HTML "clásico" de MediaWiki.
   Pasar el documento COMPLETO a
   ``pd.read_html(html, attrs={"id": "changes"})`` no aísla de forma
   fiable los límites del nodo: en la práctica devolvía contenido
   mezclado con otras zonas de la página (el navbox de constituyentes
   por sector, más abajo en el documento).

2. Aislar primero el nodo exacto ``<table id="changes">`` con
   BeautifulSoup y pasar SOLO ese fragmento a ``pd.read_html`` tampoco
   funciona: ``pd.read_html`` interpreta el string de entrada con una
   heurística que, para fragmentos HTML largos, puede tratarlo como una
   posible RUTA DE ARCHIVO en vez de HTML en memoria, y lanza
   ``FileNotFoundError`` (el propio fragmento HTML aparece, de forma
   confusa, como parte del mensaje de la excepción).

Ambos problemas se evitan recorriendo el árbol DOM que ya construye
BeautifulSoup directamente (``<tr>`` -> ``<td>``/``<th>``), sin volver a
pasar por ``pd.read_html`` en ningún momento. Esto además da control
explícito sobre el layout real de la tabla (dos filas de cabecera,
"Effective Date" / "Added" / "Removed" / "Reason", con sub-cabeceras
"Ticker"/"Security"), en vez de depender de que pandas infiera
correctamente un `MultiIndex` de columnas a partir de celdas con
``colspan``/``rowspan``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

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


def _fetch_changes_table_raw() -> pd.DataFrame:
    """
    Descarga la tabla de cambios cruda desde Wikipedia (sin caché) y la
    parsea manualmente con BeautifulSoup (ver docstring del módulo para
    por qué NO se usa ``pandas.read_html`` aquí).

    IMPORTANTE sobre la descarga: no se le pasa la URL directamente a
    ningún parser HTTP-aware de pandas — se descarga con ``requests``
    (con un ``User-Agent`` explícito, ya que Wikipedia devuelve 403
    Forbidden a peticiones sin uno identificable) y se parsea el HTML ya
    en memoria.

    Layout real de la tabla (dos filas de cabecera, verificado contra el
    HTML real de la página):
        Fila 0: Effective Date | Added (colspan 2) | Removed (colspan 2) | Reason
        Fila 1:                | Ticker | Security  | Ticker | Security  |
        Fila 2+: datos, en el mismo orden de 6 columnas:
            [Date, Added_Ticker, Added_Security, Removed_Ticker, Removed_Security, Reason]

    Se construye directamente un DataFrame con las columnas ya en el
    esquema esperado por ``_parse_changes_table``. Si el número de
    columnas de una fila no coincide con 6 (celda vacía por
    ``colspan``/fila corta, formato inesperado), la fila se descarta y
    se cuenta — igual que las filas sin fecha parseable más adelante.
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

    soup = BeautifulSoup(response.text, "lxml")
    table = soup.find("table", id="changes")
    if table is None:
        raise ValueError("No se encontró el nodo <table id=\"changes\"> en la página de Wikipedia")

    body = table.find("tbody") or table
    all_rows = body.find_all("tr", recursive=False)

    # Las filas de cabecera contienen <th>; las de datos, solo <td>. Se
    # detectan por contenido, no por posición fija, por si Wikipedia
    # añade/quita alguna fila de cabecera en el futuro.
    data_rows = [tr for tr in all_rows if not tr.find("th")]

    records = []
    n_descartadas_por_columnas = 0
    for tr in data_rows:
        cells = tr.find_all("td", recursive=False)
        texts = [c.get_text(strip=True) for c in cells]
        if len(texts) != 6:
            n_descartadas_por_columnas += 1
            continue
        records.append({
            "Date": texts[0],
            "Added_Ticker": texts[1],
            "Added_Security": texts[2],
            "Removed_Ticker": texts[3],
            "Removed_Security": texts[4],
            "Reason": texts[5],
        })

    if n_descartadas_por_columnas > 0:
        print(
            f"  ⚠ sp500_historical: {n_descartadas_por_columnas} filas de la tabla "
            "de cambios descartadas por no tener el nº de columnas esperado (6). "
            "Puede indicar un cambio de formato en la tabla de Wikipedia.",
            file=sys.stderr,
        )

    return pd.DataFrame.from_records(records)


def _parse_changes_table(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte la tabla cruda (ya con columnas [Date, Added_Ticker,
    Added_Security, Removed_Ticker, Removed_Security, Reason], ver
    ``_fetch_changes_table_raw``) en un DataFrame limpio con columnas
    [Date, Added_Ticker, Removed_Ticker] (cualquiera de los dos últimos
    puede ser None en una fila dada).

    Se mantiene tolerante a variaciones de columnas (por si se pasa un
    DataFrame construido a mano en tests, o con un esquema distinto)
    normalizando por patrón de nombre en vez de asumir ciegamente el
    esquema fijo de ``_fetch_changes_table_raw``.

    Filas sin fecha parseable se descartan y se cuentan; si superan un
    umbral relevante se avisa en stderr (posible cambio de formato de la
    tabla fuente, no un simple hueco puntual).
    """
    df = raw.copy()
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
    df = df.rename(columns=rename)

    if "Date" not in df.columns:
        raise ValueError(
            f"No se reconoce la columna de fecha en la tabla de cambios "
            f"(columnas encontradas: {list(df.columns)})"
        )

    # Esquema antiguo/alternativo sin columnas Added_Ticker/Removed_Ticker
    # explícitas: se resuelve por posición como último recurso (fallback
    # conservador por si algún día se recupera un camino de parsing
    # distinto a _fetch_changes_table_raw, p.ej. en tests).
    if "Added_Ticker" not in df.columns or "Removed_Ticker" not in df.columns:
        cols = list(df.columns)
        ticker_like = [c for c in cols if c != "Date"]
        if len(ticker_like) >= 3:
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
        # pd.notna() en vez de "is not None": tras un roundtrip por caché
        # parquet, una celda vacía puede llegar como float('nan') en vez
        # de None (columna 'object' con tipos mezclados). "is not None"
        # no detecta ese caso y deja colar un NaN flotante como si fuera
        # un ticker válido, rompiendo sorted()/comparaciones más adelante
        # (ver _build_historical_universe_rows -> universe_union).
        if pd.notna(added) and added in membership:
            membership.discard(added)
        if pd.notna(removed):
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
            # Ver comentario equivalente en reconstruct_membership: pd.notna()
            # cubre tanto None como float('nan') que puede colarse tras un
            # roundtrip por caché parquet en columnas 'object' mixtas.
            if pd.notna(added) and added in membership:
                membership.discard(added)
            if pd.notna(removed):
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