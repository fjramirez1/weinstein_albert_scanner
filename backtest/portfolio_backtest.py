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

Sesgo de supervivencia (limitación conocida, documentada)
------------------------------------------------------------
El universo de tickers usado es el S&P 500 ACTUAL (constituyentes de
hoy), no una reconstrucción histórica de qué empresas estaban en el
índice cada semana del pasado. Esto introduce sesgo de supervivencia:
empresas que quebraron, fueron adquiridas o salieron del índice durante
el periodo simulado no aparecen, así que el universo está sesgado hacia
"empresas que han ido bien" (sobrevivieron hasta hoy). Por eso se
recomienda usar periodos NO demasiado largos (p.ej. 5-8 años) y tratar
los resultados como orientativos, no como una réplica exacta de qué
habría pasado invirtiendo en tiempo real. Este aviso se imprime también
en la salida del backtest. Ver README para la hoja de ruta hacia un
universo histórico reconstruido (con sus propias limitaciones de
cobertura de datos en yfinance).

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
caché elimina en ejecuciones repetidas.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

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
from backtest.strategy_config import StrategyConfig
from weinstein.config import SECTOR_TO_ETF, SP500_INDEX
from weinstein.data import load_sp500_tickers

DEFAULT_BACKTEST_PERIOD = "8y"   # ventana recomendada para limitar el sesgo de supervivencia
MAX_WORKERS = 20


# ── Descarga + precálculo de contexto (una vez, se reutiliza entre configs) ──

def _download_sector_etfs(period: str) -> dict[str, pd.Series]:
    unique_etfs = sorted(set(SECTOR_TO_ETF.values()))
    result: dict[str, pd.Series] = {}
    print(f"  → Descargando/cacheando {len(unique_etfs)} ETFs sectoriales...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(get_cached_weekly, etf, period): etf for etf in unique_etfs}
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
) -> tuple[TickerContext | None, str]:
    ticker = row["Symbol"]
    sector = row.get("Sector", "Unknown")
    try:
        data = get_cached_weekly(ticker, period)
        if data is None:
            return None, "sin_datos"
        etf_ticker = SECTOR_TO_ETF.get(sector)
        sector_etf_close = sector_etf_map.get(etf_ticker) if etf_ticker else None
        ctx = build_ticker_context(ticker, sector, data, sp500_close, sector_etf_close)
        if ctx is None:
            return None, "sin_datos"
        return ctx, "ok"
    except Exception as exc:
        print(f"  ⚠ [{ticker}] error precalculando contexto: {exc}", file=sys.stderr)
        return None, "error"


def prepare_universe(
    period: str = DEFAULT_BACKTEST_PERIOD,
    tickers: list[str] | None = None,
    max_tickers: int | None = None,
) -> tuple[pd.Series, pd.Series, pd.Series, dict[str, TickerContext]]:
    """
    Descarga (con caché) y precalcula TODO lo necesario para simular:
    el S&P 500, las series de mercado F5/S2 precalculadas, y el
    `TickerContext` de cada ticker del universo.

    Esta preparación es independiente de la `StrategyConfig`: se hace
    una sola vez y se reutiliza para lanzar varias configuraciones
    distintas sobre los MISMOS datos (ver `sweep.py`), evitando
    recalcular indicadores por cada configuración probada.

    Returns
    -------
    (sp500_close, coppock_bullish, coppock_bearish, {ticker: TickerContext})
    """
    print("\n[1/4] Cargando universo de tickers (S&P 500 actual)...")
    if tickers:
        sp500_df = pd.DataFrame({"Symbol": tickers, "Name": tickers, "Sector": "Unknown"})
    else:
        sp500_df = load_sp500_tickers()
    if max_tickers:
        sp500_df = sp500_df.head(max_tickers)
    print(f"  ✓ {len(sp500_df)} tickers a procesar")

    print("\n[2/4] Descargando/cacheando S&P 500 (benchmark)...")
    sp500_data = get_cached_weekly(SP500_INDEX, period)
    if sp500_data is None:
        print("  ✗ ERROR CRÍTICO: no se pudo obtener el S&P 500. Abortando.")
        sys.exit(1)
    sp500_close = sp500_data["Close"].squeeze()

    print("\n[3/4] Precalculando condición de mercado (F5/S2) semana a semana...")
    coppock_bullish, coppock_bearish = precompute_market_series(sp500_close)
    print(f"  ✓ {len(coppock_bullish)} semanas evaluadas")

    print("\n[4/4] Descargando ETFs sectoriales y precalculando contexto por ticker...")
    sector_etf_map = _download_sector_etfs(period)

    contexts: dict[str, TickerContext] = {}
    n_sin_datos = 0
    rows = [row for _, row in sp500_df.iterrows()]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_build_context_worker, row, sp500_close, sector_etf_map, period): row["Symbol"]
            for row in rows
        }
        done = 0
        for fut in as_completed(futures):
            ctx, estado = fut.result()
            done += 1
            if estado == "ok":
                contexts[ctx.ticker] = ctx
            else:
                n_sin_datos += 1
            if done % 100 == 0:
                print(f"  … {done}/{len(rows)} procesados | contexto OK: {len(contexts)}")

    print(f"  ✓ {len(contexts)} tickers con contexto listo | {n_sin_datos} sin datos suficientes")
    return sp500_close, coppock_bullish, coppock_bearish, contexts


# ── Simulación de cartera para UNA configuración ────────────────────────

def run_portfolio_backtest(
    config: StrategyConfig,
    sp500_close: pd.Series,
    coppock_bullish: pd.Series,
    coppock_bearish: pd.Series,
    contexts: dict[str, TickerContext],
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
    """
    t0 = time.time()
    extra = {"coppock_bullish": coppock_bullish, "coppock_bearish": coppock_bearish}

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
            candidatos: list[tuple[str, float]] = []  # (ticker, score)
            for ticker, ctx in contexts.items():
                if ticker in open_positions:
                    continue
                if fecha not in ctx.close.index:
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


def print_report(result: PortfolioBacktestResult) -> None:
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
    print("  ⚠ Universo = S&P 500 ACTUAL (sesgo de supervivencia). Ver docstring")
    print("    de portfolio_backtest.py para más detalle sobre esta limitación.")
    print("═" * 72)
