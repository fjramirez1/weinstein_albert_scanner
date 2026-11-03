"""
Escáner de condiciones de ENTRADA — estrategia Weinstein-Albert.

Optimizaciones respecto a la versión original
----------------------------------------------
1. **Early-exit de mercado**: si el Coppock no es alcista se aborta
   antes de descargar cualquier ticker individual (F5 es AND → falla global).
2. **Descarga paralela**: los ~500 tickers y los 11 ETFs sectoriales
   se descargan con ThreadPoolExecutor (I/O-bound; yfinance libera el GIL).
3. **Short-circuit de filtros**: dentro de cada evaluación los filtros se
   ordenan de más barato a más caro. En cuanto uno falla se descarta el
   ticker sin calcular el resto:
     F5 (ya conocido) → F1 (RSC sector, sin I/O extra) → descarga ticker
     → F3 (RSC activo) → F2 (VPM5) → F4 (distancia WMA30)
4. **Concurrencia acotada por el propio ThreadPoolExecutor**: el límite de
   peticiones simultáneas a yfinance lo impone `max_workers` del pool; no
   se usa un `Semaphore` adicional porque sería redundante (cada tarea del
   pool hace una única descarga, así que el pool ya serializa la
   concurrencia al mismo número).
5. **Descarga de ETFs en paralelo**: antes del loop principal.
6. **Mismas señales que el backtest**: los indicadores se calculan con
   `weinstein.signals.build_ticker_context` y cada filtro con las reglas de
   `weinstein/signals.py`, las mismas que usa `backtest/` (tarea R1). Lo
   que el backtest simula una semana es exactamente lo que el escáner
   habría dado esa semana (ver `tests/test_signals_paridad.py`).
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import numpy as np
import pandas as pd

from weinstein.config import (
    DOWNLOAD_PERIOD_ENTRY,
    MAX_CANDIDATES,
    SCANNER_LOGIC_VERSION,
    SECTOR_TO_ETF,
    SP500_INDEX,
    resolve_sector_etf,
)
from weinstein.data import download_weekly, load_sp500_tickers
from weinstein.indicators import coppock_curve
from weinstein.signals import (
    build_ticker_context,
    f1_sector_fuerte,
    f2_volumen_positivo,
    f3_rsc_activo_positivo,
    f4_distancia_wma30,
    market_state_series,
    sector_rsc_series,
)

# Máximo de hilos concurrentes contra yfinance.
# 20-25 es seguro; súbelo si tu red lo aguanta.
MAX_WORKERS = 20


# ── Pre-cálculo compartido ────────────────────────────────────────────

def _download_etf_rsc(
    etf: str,
    sp500_close: pd.Series,
) -> tuple[str, float | None]:
    """Descarga un ETF y devuelve (etf, rsc_val | None). Thread-safe."""
    data = download_weekly(etf)
    if data is None:
        return etf, None
    try:
        rsc_val = float(sector_rsc_series(data["Close"].squeeze(), sp500_close).iloc[-1])
        return etf, rsc_val
    except Exception:
        return etf, None


def _precompute_market_context(
    sp500_close: pd.Series,
) -> tuple[bool, str, dict[str, float]]:
    """
    Calcula estado de mercado y RSC sectoriales en paralelo.

    Returns
    -------
    (coppock_bullish, coppock_direction, sector_rsc_map)
    """
    copk = coppock_curve(sp500_close)
    bullish_series, _ = market_state_series(sp500_close)
    coppock_bullish = bool(bullish_series.iloc[-1])
    direction = "↑ Alcista" if coppock_bullish else "↓ No alcista"

    print(f"\n  Coppock SP500 actual   : {float(copk.iloc[-1]):+.4f}")
    print(f"  Coppock SP500 anterior : {float(copk.iloc[-2]):+.4f}")
    print(f"  Estado de mercado      : {direction}")

    # ── Early-exit: si el mercado ya es bajista, no hay nada que escanear ──
    if not coppock_bullish:
        print("\n  ⛔ Coppock no alcista (F5 falla). No se procesa ningún ticker.")
        return coppock_bullish, direction, {}

    unique_etfs = sorted(set(SECTOR_TO_ETF.values()))
    print(f"\n  Calculando RSC de {len(unique_etfs)} ETFs sectoriales (paralelo)...")

    sector_rsc_map: dict[str, float] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_download_etf_rsc, etf, sp500_close): etf
            for etf in unique_etfs
        }
        for fut in as_completed(futures):
            etf, rsc_val = fut.result()
            if rsc_val is not None:
                sector_rsc_map[etf] = rsc_val
                ok = "✓" if f1_sector_fuerte(rsc_val) else "✗"
                print(f"    {ok} {etf}: RSC = {rsc_val:+.4f}")
            else:
                print(f"    ✗ {etf}: sin datos")

    return coppock_bullish, direction, sector_rsc_map


# ── Evaluación de un ticker (sin I/O propia de ETF) ──────────────────

def _evaluate_ticker(
    ticker:            str,
    sector_name:       str,
    company_name:      str,
    sp500_close:       pd.Series,
    coppock_bullish:   bool,
    coppock_direction: str,
    sector_rsc_map:    dict[str, float],
) -> tuple[dict | None, str]:
    """
    Aplica los 5 filtros Weinstein-Albert con short-circuit.

    Orden de evaluación (de más barato a más caro):
      F5 → F1 → [descarga] → F3 → F2 → F4

    Returns
    -------
    (dict_resultado | None, motivo)
    """
    # F5: Coppock alcista — conocido de antemano, sin coste
    if not coppock_bullish:
        return None, "filtrado"

    # F1: RSC sector — conocido de antemano, sin coste
    etf_ticker     = resolve_sector_etf(sector_name)
    rsc_sector_val = sector_rsc_map.get(etf_ticker, np.nan) if etf_ticker else np.nan
    if not f1_sector_fuerte(rsc_sector_val):
        return None, "filtrado"

    # Descarga del ticker — único I/O de esta función
    data = download_weekly(ticker)
    if data is None:
        return None, "sin_datos"

    # Mismos indicadores que el backtest. El RSC sectorial ya se evaluó
    # arriba con el valor precalculado del ETF, por eso no se pasa aquí.
    ctx = build_ticker_context(ticker, sector_name, data, sp500_close, None)
    if ctx is None:
        return None, "sin_datos"
    close = ctx.close

    # F3: RSC Mansfield activo > 0
    rsc_activo_val = float(ctx.rsc_activo.iloc[-1])
    if not f3_rsc_activo_positivo(rsc_activo_val):
        return None, "filtrado"

    # F2: VPM5 > 0
    vpm5_val = float(ctx.vpm5.iloc[-1])
    if not f2_volumen_positivo(vpm5_val):
        return None, "filtrado"

    # F4: distancia WMA30 < MAX_DISTANCIA_WMA30
    dist = float(ctx.dist_wma30_pct.iloc[-1])
    mom = float(ctx.momentum.iloc[-1])
    if pd.isna(dist) or pd.isna(mom):
        return None, "sin_datos"
    if not f4_distancia_wma30(dist):
        return None, "filtrado"

    return {
        "Ticker"                 : ticker,
        "Nombre"                 : company_name,
        "Sector"                 : sector_name,
        "ETF Sector"             : etf_ticker or "N/A",
        "Precio Actual"          : round(float(close.iloc[-1]), 2),
        "RSC Mansfield Activo"   : round(rsc_activo_val, 4),
        "Momentum (MOM)"         : round(mom, 4),
        "RSC Mansfield Sector"   : round(rsc_sector_val, 4),
        "VPM5"                   : round(vpm5_val, 4),
        "Distancia % WMA30"      : round(dist, 2),
        "Dirección Coppock SP500": coppock_direction,
    }, "ok"


# ── Worker para el pool de tickers ───────────────────────────────────

def _worker(
    row:               pd.Series,
    sp500_close:       pd.Series,
    coppock_bullish:   bool,
    coppock_direction: str,
    sector_rsc_map:    dict[str, float],
) -> tuple[dict | None, str, str]:
    """Envuelve _evaluate_ticker con manejo de excepciones para el pool."""
    ticker = row["Symbol"]
    try:
        result, motivo = _evaluate_ticker(
            ticker            = ticker,
            sector_name       = row.get("Sector", "Unknown"),
            company_name      = row.get("Name",   "N/A"),
            sp500_close       = sp500_close,
            coppock_bullish   = coppock_bullish,
            coppock_direction = coppock_direction,
            sector_rsc_map    = sector_rsc_map,
        )
        return result, motivo, ticker
    except Exception:
        return None, "error", ticker


# ── Función principal ─────────────────────────────────────────────────

def run_entry_scanner() -> pd.DataFrame:
    """
    Ejecuta el escáner de entrada completo y devuelve los candidatos.

    Mejoras de rendimiento vs versión original
    ------------------------------------------
    - Mercado bajista → salida inmediata (0 descargas de tickers).
    - ETFs sectoriales descargados en paralelo.
    - ~500 tickers descargados y evaluados en paralelo con short-circuit.
    - Filtros ordenados por coste: los más baratos eliminan antes.
    - WMA30 calculada una única vez por ticker y reutilizada en F4 y MOM.
    """
    print("\n" + "═" * 72)
    print("  WEINSTEIN VERSION ALBERT — S&P 500 WEEKLY ENTRY SCANNER")
    print(f"  Ejecución : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
    print("═" * 72)

    print("\n[1/3] Descargando constituyentes del S&P 500...")
    sp500_df      = load_sp500_tickers()
    total_tickers = len(sp500_df)

    print("\n[2/3] Descargando S&P 500 y calculando indicadores de mercado...")
    sp500_data = download_weekly(SP500_INDEX, period=DOWNLOAD_PERIOD_ENTRY)
    if sp500_data is None:
        print("  ✗ ERROR CRÍTICO: no se pudo descargar el S&P 500. Abortando.")
        sys.exit(1)

    sp500_close = sp500_data["Close"].squeeze()
    coppock_bullish, coppock_direction, sector_rsc_map = _precompute_market_context(sp500_close)

    # Early-exit de mercado: F5 falla para todos → no procesamos nada
    if not coppock_bullish:
        print("\n  No se encontraron candidatos (mercado bajista).")
        return pd.DataFrame()

    print(f"\n[3/3] Escaneando {total_tickers} acciones (paralelo, {MAX_WORKERS} hilos)...")
    print("─" * 72)

    resultados: list[dict] = []
    counters   = {"sin_datos": 0, "filtrado": 0, "errores": 0}

    rows = [row for _, row in sp500_df.iterrows()]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(
                _worker, row, sp500_close,
                coppock_bullish, coppock_direction, sector_rsc_map,
            ): row["Symbol"]
            for row in rows
        }

        done = 0
        for fut in as_completed(futures):
            result, motivo, ticker = fut.result()
            done += 1

            if result:
                resultados.append(result)
                print(
                    f"  ★ CANDIDATO → {ticker:<6} | {result['Sector']:<30} | "
                    f"MOM: {result['Momentum (MOM)']:+.3f} | "
                    f"RSC: {result['RSC Mansfield Activo']:+.3f} | "
                    f"VPM5: {result['VPM5']:+.3f} | "
                    f"Dist: {result['Distancia % WMA30']:+.1f}%"
                )
            elif motivo == "error":
                counters["errores"] += 1
            else:
                counters[motivo] += 1

            if done % 50 == 0:
                print(
                    f"  … {done}/{total_tickers} procesados | "
                    f"Candidatos: {len(resultados)} | Errores: {counters['errores']}"
                )

    print("\n" + "═" * 72)
    print("  RESUMEN DEL ESCÁNER")
    print("─" * 72)
    print(f"  Acciones procesadas          : {done}")
    print(f"  Sin datos / histórico insuf. : {counters['sin_datos']}")
    print(f"  No cumplen filtros           : {counters['filtrado']}")
    print(f"  Errores de descarga          : {counters['errores']}")
    print(f"  Candidatos (5/5 filtros)     : {len(resultados)}")
    print("═" * 72)

    if not resultados:
        print("\n  No se encontraron candidatos que cumplan todos los filtros.")
        return pd.DataFrame()

    df = (
        pd.DataFrame(resultados)
        .sort_values("Momentum (MOM)", ascending=False)
        .head(MAX_CANDIDATES)
        .reset_index(drop=True)
    )

    # Versión de la lógica del escáner, para poder distinguir sin
    # ambigüedad, en histórico futuro, con qué cálculo se generó cada CSV.
    df["Versión Lógica"] = SCANNER_LOGIC_VERSION

    print(f"\n  [TOP {MAX_CANDIDATES}] {len(df)} stocks con mayor Momentum Relativo")
    print("─" * 72)
    cols_display = [
        "Ticker", "Sector", "Precio Actual", "Momentum (MOM)",
        "RSC Mansfield Activo", "VPM5", "Distancia % WMA30",
        "Dirección Coppock SP500",
    ]
    print(df[cols_display].to_string(index=True))
    print("─" * 72)

    return df