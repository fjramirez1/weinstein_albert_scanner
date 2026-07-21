"""
Backtest de CARTERA completa para la estrategia Weinstein-Albert.

A diferencia de `backtest/strategy_backtest.py` (que simula cada ticker
de forma AISLADA e independiente, sin límite de posiciones simultáneas ni
capital compartido), este módulo simula una única cartera con:

  - Capital inicial (por defecto $10.000).
  - Un máximo de posiciones simultáneas (por defecto 10).
  - Reparto de capital entre posiciones (cartera_actual / max_positions).
  - Ranking/desempate configurable cuando hay más candidatos que huecos.
  - Condiciones de entrada/salida activables y parametrizables (ver
    `backtest/conditions.py` y `backtest/strategy_config.py`).

Es la herramienta pensada para responder "si hubiera operado esta
estrategia de verdad, con este capital y estas reglas, ¿qué resultado
habría tenido?" — y para poder variar reglas/parámetros y comparar.

Universo: constituyentes ACTUALES vs. HISTÓRICOS (parámetro `universe`)
--------------------------------------------------------------------------
Por defecto (`universe="current"`) el universo de tickers candidatos es
el S&P 500 de HOY para todo el periodo simulado — esto introduce sesgo de
supervivencia (ver sección siguiente). El modo `universe="historical"`
usa `backtest/sp500_historical.py` para reconstruir, semana a semana, qué
tickers pertenecían realmente al índice en cada fecha (a partir de la
tabla de altas/bajas de Wikipedia), y solo permite ABRIR posiciones
nuevas en tickers que estaban en el índice esa semana. Una posición ya
abierta se sigue gestionando con normalidad aunque el ticker salga del
índice mientras tanto (igual que en la vida real: no se te obliga a
vender solo porque el índice reponderó).

Sesgo de supervivencia — mitigado en modo "historical", NO eliminado
------------------------------------------------------------------------
Incluso reconstruyendo bien la membresía histórica, una parte de los
tickers que estuvieron en el índice en el pasado (sobre todo empresas
excluidas hace muchos años por quiebra, exclusión de bolsa o absorción
total) ya no tienen datos de precio disponibles en yfinance, que solo
cubre tickers que cotizan hoy o cotizaron hasta hace relativamente poco.
Esos tickers se cuentan y reportan explícitamente
(`tickers_historicos_sin_precio` en el resultado de `prepare_universe`),
no se descartan en silencio. En modo `universe="current"` este problema
es más severo (ni siquiera se INTENTA incluir esos tickers como
candidatos). Se recomienda además no alargar demasiado el periodo de
backtest (`--period`, por defecto `8y`) en cualquiera de los dos modos,
para limitar el tramo de historia afectado.

Sesgo de sector "Unknown" en universo histórico — mitigado, NO eliminado
------------------------------------------------------------------------------
Problema (detectado y cuantificado empíricamente, ver detalle abajo): el
sector de cada ticker histórico se obtenía SIEMPRE mapeándolo contra los
constituyentes ACTUALES del S&P 500 (`load_sp500_tickers()`). Para
tickers que ya NO pertenecen al índice hoy (fusionados, quebrados,
rebrandeados, excluidos por rebalanceo — p.ej. CELG, XLNX, ETFC, WLTW,
TWTR), no había forma de encontrar su sector en la fuente actual, así
que caían a `Sector="Unknown"`. `resolve_sector_etf("Unknown")` devuelve
`None`, así que a esos tickers nunca se les puede calcular `rsc_sector`
(queda `NaN`) y la condición de entrada `F1_sector_fuerte`
(`backtest/conditions.py::_f1_sector_fuerte`) se evalúa siempre `False`
para ellos — quedan excluidos de abrir posición SIEMPRE, sin relación
con su fuerza sectorial real. Esto reintroducía parcialmente el sesgo de
supervivencia que el propio modo "historical" se creó para mitigar.

Cifras verificadas empíricamente (universo histórico 8 años, 653 tickers
totales, antes de la mitigación):
  - 150 tickers (23.0%) quedaban con Sector="Unknown".
  - De esos 150, 76 SÍ tenían histórico de precio suficiente en caché
    (>=70 velas semanales) — candidatos reales y evaluables por F2-F5,
    no ruido ni tickers sin datos.
  - Backtest completo (8y, config por defecto, max_positions=10,
    capital=$10.000): con F1 activo (umbral 0.10, default) la
    rentabilidad total medida fue +25.92% (Sharpe 0.27, max drawdown
    -23.96%, 165 operaciones). Con F1 desactivado por completo:
    +89.14% (Sharpe 0.69, max drawdown -20.51%, 154 operaciones). Con
    F1 con umbral relajado a 0.0 (no eliminado, solo más laxo): +20.39%
    (Sharpe 0.24, max drawdown -26.16%) — PEOR que el baseline, lo que
    confirma que el salto no viene de "cuán estricto es el umbral" sino
    específicamente de dejar de excluir en bloque a los tickers
    Unknown: el problema es binario (mapeo resuelto o no), no gradual.

Mitigación implementada: `resolve_historical_sector()`
(`weinstein/config.py`) añade un mapeo manual estático
(`HISTORICAL_DELISTED_SECTORS`) de sector GICS para los tickers
delistados más comunes, documentado con su fuente (último sector GICS
conocido antes de salir del índice) directamente en `weinstein/config.py`.
Se prioriza sobre "Unknown" pero solo cubre un conjunto acotado de
tickers (los que además tienen histórico de precio evaluable, ver arriba)
— no es un histórico GICS punto-en-el-tiempo completo (esa alternativa,
scrapear el historial de revisiones de Wikipedia, se evaluó y se
descartó por fragilidad/esfuerzo desproporcionado frente a la ganancia
de precisión, dado que las reclasificaciones GICS intra-índice son
infrecuentes). Los tickers que ni siquiera aparecen en el mapeo manual
siguen cayendo a "Unknown" — se cuentan por separado en
`UniverseInfo.tickers_sector_desconocido` (NO mezclados con
`tickers_historicos_sin_precio`, que es un problema distinto: ausencia
de PRECIO, no de sector) para que el reporte (`print_report`) siga
siendo transparente sobre cuánto sesgo queda sin resolver.

**Ninguna comparativa de F1 en modo "historical" debe tratarse como
concluyente hasta que `tickers_sector_desconocido` sea 0 o
suficientemente pequeño** — ver `backtest/BACKTEST.md` sección 4 para el
detalle completo y las cifras exactas.

Caché de FALLOS de descarga (tickers sin histórico suficiente o sin datos)
------------------------------------------------------------------------------
`launcher.py` está pensado para ejecutar este backtest en bucle (cada
hora). En modo `universe="historical"` el universo incluye tickers que
ya NO pertenecen al S&P 500 actual (p.ej. empresas quebradas, absorbidas
o privatizadas) junto con otros que sí pertenecen pero tienen histórico
insuficiente por ser altas muy recientes (p.ej. un spin-off que entró al
índice hace pocas semanas). Sin caché de fallos, cada ejecución repetía
la descarga fallida de esos mismos tickers una y otra vez.

La solución (ver `backtest/data_cache.py::get_cached_weekly`) distingue
entre ambos casos usando el set de constituyentes ACTUALES del S&P 500,
calculado una única vez en `prepare_universe` y pasado a cada worker de
descarga (`_build_context_worker`):

  - Ticker que HOY ya NO pertenece al S&P 500 (p.ej. `FRC`, `APC`,
    `CDAY`): su histórico es finito y quedó fijado en el pasado. Si la
    descarga falla, el fallo se cachea de forma persistente en disco
    (marcador `.nodata`) y no se reintenta en ejecuciones futuras.
  - Ticker que SÍ pertenece HOY al S&P 500 (aunque tenga histórico
    insuficiente ahora mismo, p.ej. un spin-off reciente): el fallo
    nunca se cachea, se reintenta en cada ejecución, porque puede
    resolverse solo con el paso del tiempo (cada semana suma una vela
    más) o por cualquier otra causa transitoria.

Caso límite cubierto explícitamente: un ticker fuera del índice hoy (con
fallo ya cacheado) que en el futuro VUELVE a formar parte del S&P 500 —
ya sea la misma empresa o, como ha pasado literalmente con el símbolo
`Q`, una empresa distinta reutilizando el mismo símbolo. En cuanto
`load_sp500_tickers()` lo detecte de nuevo como constituyente actual,
`get_cached_weekly` ignora y borra automáticamente el marcador de fallo
antiguo, sin necesidad de intervención manual (ver docstring de
`data_cache.py` para el detalle del mecanismo).

Rendimiento
------------
Cada ticker se descarga UNA vez (con caché en disco, ver
`backtest/data_cache.py`) y todos sus indicadores se precalculan de
forma vectorizada sobre el histórico completo (ver
`backtest/conditions.py::build_ticker_context`). El bucle de simulación
semana a semana solo hace lookups (`.iloc[i]`) sobre series ya
calculadas, no recalcula indicadores — así que aunque el bucle en sí es
Python puro (necesario porque hay estado compartido de cartera entre
tickers), es rápido: la parte cara es la descarga de datos, que la
caché elimina en ejecuciones repetidas. El calendario de membresía
histórica (modo `universe="historical"`) también se calcula una única
vez, vectorizado sobre la tabla de cambios completa (ver
`backtest/sp500_historical.py::build_membership_calendar`), no semana a
semana dentro del bucle de simulación.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import pandas as pd

from backtest.conditions import (
    RANKING_CRITERIA,
    TickerContext,
    build_ticker_context,
    precompute_market_series,
)
from backtest.data_cache import get_cached_weekly
from backtest.portfolio_engine import (
    ClosedTrade,
    EquityPoint,
    OpenPosition,
    PortfolioBacktestResult,
    evaluate_entry_mask,
    evaluate_exit_masks,
)
from backtest.sp500_historical import build_membership_calendar_cached, universe_union
from backtest.strategy_config import StrategyConfig
from weinstein.config import SECTOR_TO_ETF, SP500_INDEX, resolve_historical_sector, resolve_sector_etf
from weinstein.data import load_sp500_tickers

DEFAULT_BACKTEST_PERIOD = "8y"   # ventana recomendada para limitar el sesgo de supervivencia
MAX_WORKERS = 20


@dataclass
class UniverseInfo:
    """
    Metadatos del universo preparado, además de los datos en sí.

    `membership_calendar` es ``None`` en modo "current" (no aplica; el
    universo es fijo en todas las fechas). `tickers_historicos_sin_precio`
    solo se rellena en modo "historical": tickers que en algún momento
    pertenecieron al índice pero no se pudo obtener su precio (sesgo de
    supervivencia residual, ver docstring del módulo).

    `tickers_sector_desconocido` también solo se rellena en modo
    "historical": tickers que SÍ tienen precio evaluable pero cuyo sector
    no se pudo resolver ni contra los constituyentes actuales ni contra
    el mapeo manual `HISTORICAL_DELISTED_SECTORS`
    (`weinstein/config.py::resolve_historical_sector`), y por tanto quedan
    con `Sector="Unknown"` y excluidos de F1 (RSC sector) de forma
    permanente. Deliberadamente separado de `tickers_historicos_sin_precio`
    porque es un problema distinto (ausencia de SECTOR, no de PRECIO) con
    una causa e implicación distintas — ver docstring del módulo, sección
    "Sesgo de sector Unknown en universo histórico".
    """
    mode: str
    membership_calendar: dict[pd.Timestamp, set[str]] | None = None
    tickers_historicos_sin_precio: list[str] = field(default_factory=list)
    tickers_sector_desconocido: list[str] = field(default_factory=list)


# ── Descarga + precálculo de contexto (una vez, se reutiliza entre configs) ──

def _download_sector_etfs(period: str) -> dict[str, pd.Series]:
    """
    Descarga (con caché) los ETFs sectoriales usados en F1/S1 (RSC
    sector). Los ETFs no forman parte del universo de tickers del S&P
    500 y siempre se consideran "vigentes": un fallo de descarga aquí
    nunca se cachea de forma persistente (`is_current_constituent=True`
    en la llamada a `get_cached_weekly`), para no arriesgarse a dejar un
    ETF "congelado" como sin datos por un fallo puntual de red.
    """
    unique_etfs = sorted(set(SECTOR_TO_ETF.values()))
    result: dict[str, pd.Series] = {}
    print(f"  → Descargando/cacheando {len(unique_etfs)} ETFs sectoriales...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(get_cached_weekly, etf, period, False, True): etf
            for etf in unique_etfs
        }
        for fut in as_completed(futures):
            etf = futures[fut]
            data = fut.result()
            if data is not None:
                result[etf] = data["Close"].squeeze()
                print(f"    ✓ {etf}")
            else:
                print(f"    ✗ {etf}: sin datos")
    return result


def _build_context_worker(
    row: pd.Series,
    sp500_close: pd.Series,
    sector_etf_map: dict[str, pd.Series],
    period: str,
    current_constituents: set[str],
) -> tuple[TickerContext | None, str]:
    """
    Descarga (con caché) y precalcula el contexto de un ticker.

    `current_constituents` es el set de símbolos que pertenecen HOY al
    S&P 500 (ver `weinstein.data.load_sp500_tickers()`), calculado una
    única vez en `prepare_universe` y compartido por todos los workers.
    Determina si un fallo de descarga se cachea de forma persistente
    (ticker ya fuera del índice actual, ver `data_cache.py`) o se
    reintenta en cada ejecución (ticker vigente hoy, el fallo puede ser
    transitorio -- p.ej. alta reciente con histórico aún insuficiente).
    """
    ticker = row["Symbol"]
    sector = row.get("Sector", "Unknown")
    try:
        is_current = ticker in current_constituents
        data = get_cached_weekly(ticker, period, False, is_current)
        if data is None:
            return None, "sin_datos"
        etf_ticker = resolve_sector_etf(sector)
        sector_etf_close = sector_etf_map.get(etf_ticker) if etf_ticker else None
        ctx = build_ticker_context(ticker, sector, data, sp500_close, sector_etf_close)
        if ctx is None:
            return None, "sin_datos"
        return ctx, "ok"
    except Exception as exc:
        print(f"  ⚠ [{ticker}] error precalculando contexto: {exc}", file=sys.stderr)
        return None, "error"


def _build_historical_universe_rows(
    period: str,
    sp500_close: pd.Series,
) -> tuple[pd.DataFrame, dict[pd.Timestamp, set[str]], list[str]]:
    """
    Construye el calendario de membresía histórica y el DataFrame de
    filas [Symbol, Name, Sector] a procesar: la UNIÓN de todos los
    tickers que pertenecieron al índice en algún momento del periodo
    simulado (superset de lo que hará falta semana a semana).

    Resolución de sector (ver docstring del módulo, sección "Sesgo de
    sector Unknown en universo histórico" para el problema, el impacto
    medido y la mitigación completa): para cada símbolo se intenta,
    en orden:
      1. El sector de los constituyentes ACTUALES del S&P 500
         (`load_sp500_tickers()`) — fuente más fiable cuando el ticker
         sigue vigente hoy.
      2. El mapeo manual `HISTORICAL_DELISTED_SECTORS`
         (`weinstein/config.py`) para tickers ya delistados que no
         aparecen en (1).
      3. "Unknown" si ninguna de las dos anteriores lo cubre — esto solo
         afecta a F1 (RSC sector), que no podrá evaluarse para esos
         tickers concretos, pero no impide intentar descargar su precio
         ni evaluar el resto de condiciones.

    Toda la resolución se hace con `weinstein.config.resolve_historical_sector`
    (función pura, ver su docstring), para que la lógica de "en qué orden
    se prioriza cada fuente" viva en un único sitio testeable en
    aislamiento (`tests/test_config_historical_sector.py`), no repetida
    aquí y en los tests de este módulo.

    Devuelve además, como tercer elemento, la lista de símbolos que
    quedaron en "Unknown" tras los tres pasos — usada por
    `prepare_universe` para poblar `UniverseInfo.tickers_sector_desconocido`
    (solo entre los que además tengan precio evaluable, filtrado más
    abajo en `prepare_universe`).
    """
    dates = list(sp500_close.index)
    print("  → Reconstruyendo membresía histórica del S&P 500 (Wikipedia, con caché)...")
    calendar = build_membership_calendar_cached(dates)
    union = universe_union(calendar)
    print(f"  ✓ {len(union)} tickers distintos pertenecieron al índice en algún momento del periodo")

    current_df = load_sp500_tickers()
    sector_map = dict(zip(current_df["Symbol"], current_df["Sector"]))
    name_map = dict(zip(current_df["Symbol"], current_df["Name"]))

    rows = pd.DataFrame({
        "Symbol": sorted(union),
    })
    rows["Name"] = rows["Symbol"].map(name_map).fillna(rows["Symbol"])
    rows["Sector"] = rows["Symbol"].apply(lambda sym: resolve_historical_sector(sym, sector_map))

    unknown_symbols = sorted(rows.loc[rows["Sector"] == "Unknown", "Symbol"])

    return rows, calendar, unknown_symbols


def prepare_universe(
    period: str = DEFAULT_BACKTEST_PERIOD,
    tickers: list[str] | None = None,
    max_tickers: int | None = None,
    universe: str = "current",
) -> tuple[pd.Series, pd.Series, pd.Series, dict[str, TickerContext], UniverseInfo]:
    """
    Descarga (con caché) y precalcula TODO lo necesario para simular:
    el S&P 500, las series de mercado F5/S2 precalculadas, el
    `TickerContext` de cada ticker del universo, y metadatos del
    universo usado (`UniverseInfo`).

    Esta preparación es independiente de la `StrategyConfig`: se hace
    una sola vez y se reutiliza para lanzar varias configuraciones
    distintas sobre los MISMOS datos (ver `sweep.py`), evitando
    recalcular indicadores por cada configuración probada.

    Parameters
    ----------
    universe : "current" (por defecto) usa los constituyentes ACTUALES
        del S&P 500 para todo el periodo (sesgo de supervivencia
        conocido, ver README). "historical" reconstruye la membresía
        semana a semana a partir de la tabla de cambios de Wikipedia
        (ver `backtest/sp500_historical.py`) y descarga la UNIÓN de
        todos los tickers que pertenecieron al índice en algún momento
        del periodo — el motor de simulación filtra por membresía real
        semana a semana en `run_portfolio_backtest`.

    Returns
    -------
    (sp500_close, coppock_bullish, coppock_bearish, {ticker: TickerContext}, UniverseInfo)
    """
    if universe not in ("current", "historical"):
        raise ValueError(f"universe debe ser 'current' o 'historical', recibido: '{universe}'")

    print("\n[1/4] Descargando/cacheando S&P 500 (benchmark)...")
    # El propio índice se trata como "constituyente actual" (nunca cachea
    # el fallo de forma persistente): es la serie de referencia de todo
    # el backtest, un fallo puntual de red no debe congelarse jamás.
    sp500_data = get_cached_weekly(SP500_INDEX, period, False, True)
    if sp500_data is None:
        print("  ✗ ERROR CRÍTICO: no se pudo obtener el S&P 500. Abortando.")
        sys.exit(1)
    sp500_close = sp500_data["Close"].squeeze()

    print("\n[2/4] Cargando universo de tickers...")
    membership_calendar: dict[pd.Timestamp, set[str]] | None = None
    unknown_sector_candidates: list[str] = []

    if tickers:
        sp500_df = pd.DataFrame({"Symbol": tickers, "Name": tickers, "Sector": "Unknown"})
        if universe == "historical":
            print("  ⚠ universe='historical' se ignora cuando se pasa una lista explícita de --tickers.")
    elif universe == "historical":
        sp500_df, membership_calendar, unknown_sector_candidates = _build_historical_universe_rows(period, sp500_close)
    else:
        sp500_df = load_sp500_tickers()

    if max_tickers:
        sp500_df = sp500_df.head(max_tickers)
        if membership_calendar is not None:
            kept = set(sp500_df["Symbol"])
            membership_calendar = {
                fecha: (tks & kept) for fecha, tks in membership_calendar.items()
            }
        kept_symbols = set(sp500_df["Symbol"])
        unknown_sector_candidates = [s for s in unknown_sector_candidates if s in kept_symbols]
    print(f"  ✓ {len(sp500_df)} tickers a procesar")

    # Set de constituyentes ACTUALES del S&P 500, calculado una única vez
    # y compartido por todos los workers de descarga: determina qué
    # tickers pueden tener un fallo de descarga cacheado de forma
    # persistente (los que ya no pertenecen al índice de hoy) frente a
    # los que se reintentan siempre (los vigentes hoy, ver docstring de
    # `backtest/data_cache.py::get_cached_weekly`).
    #
    # - Si se pasó una lista explícita de --tickers, esa lista ES el
    #   universo "actual" a todos los efectos (no tiene sentido cachear
    #   fallos de forma permanente para algo que el usuario pidió
    #   explícitamente).
    # - En modo "current", `sp500_df` YA ES el resultado de
    #   `load_sp500_tickers()`, así que se reutiliza sin llamada extra.
    # - En modo "historical", `sp500_df` es la UNIÓN histórica (superset
    #   más amplio que los constituyentes de hoy), así que hace falta
    #   pedir los constituyentes actuales por separado.
    if tickers:
        current_constituents = set(sp500_df["Symbol"])
    elif universe == "historical":
        current_constituents = set(load_sp500_tickers()["Symbol"])
    else:
        current_constituents = set(sp500_df["Symbol"])

    print("\n[3/4] Precalculando condición de mercado (F5/S2) semana a semana...")
    coppock_bullish, coppock_bearish = precompute_market_series(sp500_close)
    print(f"  ✓ {len(coppock_bullish)} semanas evaluadas")

    print("\n[4/4] Descargando ETFs sectoriales y precalculando contexto por ticker...")
    sector_etf_map = _download_sector_etfs(period)

    contexts: dict[str, TickerContext] = {}
    n_sin_datos = 0
    tickers_sin_precio: list[str] = []
    rows = [row for _, row in sp500_df.iterrows()]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(
                _build_context_worker, row, sp500_close, sector_etf_map, period,
                current_constituents,
            ): row["Symbol"]
            for row in rows
        }
        done = 0
        for fut in as_completed(futures):
            ticker = futures[fut]
            ctx, estado = fut.result()
            done += 1
            if estado == "ok":
                contexts[ctx.ticker] = ctx
            else:
                n_sin_datos += 1
                tickers_sin_precio.append(ticker)
            if done % 100 == 0:
                print(f"  … {done}/{len(rows)} procesados | contexto OK: {len(contexts)}")

    print(f"  ✓ {len(contexts)} tickers con contexto listo | {n_sin_datos} sin datos suficientes")

    # tickers_sector_desconocido: intersección de "sector no resuelto"
    # (unknown_sector_candidates, calculado en _build_historical_universe_rows)
    # con "sí tiene contexto/precio evaluable" (contexts.keys()) — son los
    # que de verdad importan para el sesgo (ver docstring del módulo):
    # un ticker sin precio ya se cuenta en tickers_historicos_sin_precio,
    # así que no aporta nada nuevo señalar también que su sector era
    # desconocido.
    tickers_sector_desconocido = sorted(
        s for s in unknown_sector_candidates if s in contexts
    ) if universe == "historical" and not tickers else []

    info = UniverseInfo(
        mode=universe if not tickers else "current",
        membership_calendar=membership_calendar,
        tickers_historicos_sin_precio=(
            sorted(tickers_sin_precio) if universe == "historical" and not tickers else []
        ),
        tickers_sector_desconocido=tickers_sector_desconocido,
    )

    if info.tickers_historicos_sin_precio:
        print(
            f"  ⚠ {len(info.tickers_historicos_sin_precio)} tickers pertenecieron al índice "
            "históricamente pero no tienen datos de precio disponibles en yfinance "
            "(sesgo de supervivencia PARCIAL, no eliminado — ver docstring de portfolio_backtest.py)."
        )

    if info.tickers_sector_desconocido:
        print(
            f"  ⚠ {len(info.tickers_sector_desconocido)} tickers con precio evaluable pero sector "
            "no resuelto (ni constituyentes actuales ni HISTORICAL_DELISTED_SECTORS): quedan "
            "excluidos de F1 (RSC sector) de forma permanente. Ver docstring de portfolio_backtest.py, "
            "sección 'Sesgo de sector Unknown en universo histórico'."
        )

    return sp500_close, coppock_bullish, coppock_bearish, contexts, info


# ── Simulación de cartera para UNA configuración ────────────────────────

def run_portfolio_backtest(
    config: StrategyConfig,
    sp500_close: pd.Series,
    coppock_bullish: pd.Series,
    coppock_bearish: pd.Series,
    contexts: dict[str, TickerContext],
    universe_info: UniverseInfo | None = None,
    verbose: bool = True,
) -> PortfolioBacktestResult:
    """
    Ejecuta la simulación de cartera semana a semana para una
    `StrategyConfig` concreta, sobre un universo ya preparado
    (`prepare_universe`). Permite lanzar muchas configuraciones sobre los
    mismos datos sin repetir descargas ni recálculo de indicadores base.

    Orden de eventos POR SEMANA (ver docstring de portfolio_engine.py):
      1. Evaluar y cerrar salidas de posiciones abiertas.
      2. Evaluar candidatos de entrada, rankear, abrir hasta llenar huecos.
      3. Registrar punto de la curva de equity.

    Filtro de membresía histórica (si `universe_info.membership_calendar`
    está presente): en el paso 2, un ticker solo se considera candidato
    de ENTRADA esa semana si pertenecía al S&P 500 en esa fecha según el
    calendario reconstruido. No afecta al paso 1: una posición ya
    abierta se gestiona con normalidad aunque el ticker haya salido del
    índice mientras tanto.
    """
    t0 = time.time()
    extra = {"coppock_bullish": coppock_bullish, "coppock_bearish": coppock_bearish}

    membership_calendar = universe_info.membership_calendar if universe_info else None

    # Precalcular máscaras de entrada/salida para cada ticker una vez
    # (vectorizado), y no en cada iteración semanal.
    entry_masks: dict[str, pd.Series] = {}
    exit_masks: dict[str, dict[str, pd.Series]] = {}
    for ticker, ctx in contexts.items():
        entry_masks[ticker] = evaluate_entry_mask(ctx, config, extra)
        exit_masks[ticker] = evaluate_exit_masks(ctx, config, extra)

    ranking_fn = RANKING_CRITERIA[config.ranking_criterion]

    # Calendario maestro: unión de fechas de todos los tickers, limitado
    # al rango del S&P 500 (evita simular semanas sin contexto de mercado).
    all_dates = sorted(sp500_close.index)

    capital_disponible = config.initial_capital
    valor_cartera_ref = config.initial_capital  # ver docstring: no fluctúa con precio no realizado
    open_positions: dict[str, OpenPosition] = {}
    closed_trades: list[ClosedTrade] = []
    equity_curve: list[EquityPoint] = []

    for fecha in all_dates:
        # ── Paso 1: evaluar salidas de posiciones abiertas ──────────────
        tickers_a_cerrar: list[tuple[str, str]] = []  # (ticker, motivo)
        for ticker in list(open_positions.keys()):
            ctx = contexts.get(ticker)
            if ctx is None or fecha not in ctx.close.index:
                continue
            motivos_activos = []
            for cname, mask in exit_masks.get(ticker, {}).items():
                if fecha in mask.index and bool(mask.loc[fecha]):
                    label = cname
                    motivos_activos.append(label)
            if motivos_activos:
                tickers_a_cerrar.append((ticker, "+".join(motivos_activos)))

        for ticker, motivo in tickers_a_cerrar:
            pos = open_positions.pop(ticker)
            ctx = contexts[ticker]
            precio_salida = float(ctx.close.loc[fecha])
            valor_salida = pos.n_acciones * precio_salida
            capital_disponible += valor_salida
            valor_cartera_ref = valor_cartera_ref - pos.capital_invertido + valor_salida

            retorno_pct = round(((precio_salida / pos.precio_entrada) - 1.0) * 100.0, 2)
            idx_actual = ctx.close.index.get_loc(fecha)
            semanas_en_pos = idx_actual - pos.idx_entrada

            closed_trades.append(ClosedTrade(
                ticker=ticker,
                sector=pos.sector,
                fecha_entrada=pos.fecha_entrada,
                precio_entrada=pos.precio_entrada,
                n_acciones=pos.n_acciones,
                capital_invertido=pos.capital_invertido,
                fecha_salida=fecha,
                precio_salida=precio_salida,
                motivo_salida=motivo,
                semanas_en_pos=int(semanas_en_pos),
                retorno_pct=retorno_pct,
                pnl_usd=round(valor_salida - pos.capital_invertido, 2),
            ))

        # ── Paso 2: evaluar entradas y llenar huecos libres ─────────────
        huecos_libres = config.max_positions - len(open_positions)
        if huecos_libres > 0:
            tickers_vigentes = membership_calendar.get(fecha) if membership_calendar is not None else None

            candidatos: list[tuple[str, float]] = []  # (ticker, score)
            for ticker, ctx in contexts.items():
                if ticker in open_positions:
                    continue
                if fecha not in ctx.close.index:
                    continue
                # Filtro de membresía histórica: solo se puede ABRIR una
                # posición nueva en un ticker que pertenecía al índice
                # esa semana. No aplica a posiciones ya abiertas (paso 1).
                if tickers_vigentes is not None and ticker not in tickers_vigentes:
                    continue
                mask = entry_masks.get(ticker)
                if mask is None or fecha not in mask.index:
                    continue
                if bool(mask.loc[fecha]):
                    idx_actual = ctx.close.index.get_loc(fecha)
                    score = ranking_fn(ctx, idx_actual)
                    candidatos.append((ticker, score))

            candidatos.sort(key=lambda x: x[1], reverse=True)
            elegidos = candidatos[:huecos_libres]

            for ticker, _score in elegidos:
                ctx = contexts[ticker]
                precio_entrada = float(ctx.close.loc[fecha])
                if precio_entrada <= 0:
                    continue

                capital_objetivo = valor_cartera_ref / config.max_positions
                capital_a_invertir = min(capital_objetivo, capital_disponible)
                if capital_a_invertir <= 0:
                    continue

                n_acciones = capital_a_invertir / precio_entrada
                capital_disponible -= capital_a_invertir
                idx_actual = ctx.close.index.get_loc(fecha)

                open_positions[ticker] = OpenPosition(
                    ticker=ticker,
                    sector=ctx.sector,
                    fecha_entrada=fecha,
                    precio_entrada=precio_entrada,
                    n_acciones=n_acciones,
                    capital_invertido=capital_a_invertir,
                    idx_entrada=idx_actual,
                )

        # ── Paso 3: registrar curva de equity (valor a mercado) ─────────
        valor_posiciones_mercado = 0.0
        for ticker, pos in open_positions.items():
            ctx = contexts[ticker]
            if fecha in ctx.close.index:
                precio_actual = float(ctx.close.loc[fecha])
                valor_posiciones_mercado += pos.n_acciones * precio_actual
            else:
                valor_posiciones_mercado += pos.capital_invertido

        valor_total = capital_disponible + valor_posiciones_mercado
        equity_curve.append(EquityPoint(
            fecha=fecha,
            valor_cartera=valor_total,
            capital_disponible=capital_disponible,
            n_posiciones_abiertas=len(open_positions),
        ))

    # Posiciones que siguen abiertas al final del periodo simulado.
    open_at_end = list(open_positions.values())

    result = PortfolioBacktestResult(
        config=config,
        closed_trades=closed_trades,
        open_positions_at_end=open_at_end,
        equity_curve=equity_curve,
        tickers_procesados=len(contexts),
        tickers_sin_datos=0,
        semanas_simuladas=len(all_dates),
    )

    if verbose:
        elapsed = time.time() - t0
        print(f"\n  ✓ [{config.name}] simulación completa en {elapsed:.1f}s "
              f"({len(closed_trades)} operaciones cerradas, {len(open_at_end)} abiertas al final)")

    return result


def print_report(result: PortfolioBacktestResult, universe_info: UniverseInfo | None = None) -> None:
    """Imprime un resumen legible de los resultados por consola."""
    m = result.metrics()
    cfg = result.config

    print("\n" + "═" * 72)
    print(f"  RESULTADO DEL BACKTEST DE CARTERA — {cfg.name}")
    print("═" * 72)
    print(f"  {cfg.describe()}")
    print("─" * 72)
    print(f"  Capital inicial              : ${m['capital_inicial']:,.2f}")
    print(f"  Capital final                : ${m['capital_final']:,.2f}")
    print(f"  Rentabilidad total           : {m['rentabilidad_total_pct']:+.2f}%")
    print(f"  CAGR                         : {m['cagr_pct']}%" if m['cagr_pct'] is not None else "  CAGR                         : —")
    print(f"  Máx. drawdown                : {m['max_drawdown_pct']}%" if m['max_drawdown_pct'] is not None else "  Máx. drawdown                : —")
    print(f"  Sharpe aprox. (semanal, x√52): {m['sharpe_aprox']}")
    print("─" * 72)
    print(f"  Operaciones cerradas         : {m['n_operaciones_cerradas']}")
    print(f"  Posiciones abiertas al final : {m['n_operaciones_abiertas_al_final']}")
    print(f"  Win rate                     : {m['win_rate_pct']}%")
    print(f"  Retorno medio por operación  : {m['retorno_medio_pct']}%")
    print(f"  Retorno mediana por operación: {m['retorno_mediana_pct']}%")
    print(f"  Mejor operación              : {m['mejor_operacion_pct']}%")
    print(f"  Peor operación                : {m['peor_operacion_pct']}%")
    print(f"  Profit factor                : {m['profit_factor']}")
    print(f"  Semanas medias en posición   : {m['semanas_medias_en_pos']}")
    print(f"  % semanas con capital invertido: {m['pct_semanas_invertido']}%")
    print("═" * 72)

    if universe_info is not None and universe_info.mode == "historical":
        print("  ✓ Universo = S&P 500 HISTÓRICO reconstruido (altas/bajas reales por fecha).")
        if universe_info.tickers_historicos_sin_precio:
            n = len(universe_info.tickers_historicos_sin_precio)
            print(f"  ⚠ Sesgo de supervivencia PARCIAL: {n} tickers que pertenecieron al índice")
            print("    no tienen datos de precio en yfinance y no pudieron evaluarse (ver docstring")
            print("    de portfolio_backtest.py). El sesgo se reduce respecto a universe='current',")
            print("    NO se elimina.")
        if universe_info.tickers_sector_desconocido:
            n = len(universe_info.tickers_sector_desconocido)
            print(f"  ⚠ Sesgo de sector Unknown PARCIAL: {n} tickers con precio evaluable pero sin")
            print("    sector resuelto (ni constituyentes actuales ni HISTORICAL_DELISTED_SECTORS,")
            print("    ver weinstein/config.py) — excluidos de F1 (RSC sector) siempre. NINGUNA")
            print("    comparativa de F1 en este modo es concluyente mientras esta cifra no sea 0")
            print("    o muy pequeña (ver backtest/BACKTEST.md sección 4).")
    else:
        print("  ⚠ Universo = S&P 500 ACTUAL (sesgo de supervivencia). Usa --universe historical")
        print("    para mitigarlo (ver docstring de portfolio_backtest.py para el detalle).")
    print("═" * 72)