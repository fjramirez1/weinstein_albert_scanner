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
4. **Semáforo de concurrencia**: limita las peticiones simultáneas a
   yfinance para evitar rate-limiting (MAX_WORKERS configurable).
5. **Descarga de ETFs en paralelo**: antes del loop principal.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Semaphore

import numpy as np
import pandas as pd

from weinstein.config import (
    COPPOCK_RECENT_LOOKBACK,
    DOWNLOAD_PERIOD_ENTRY,
    MAX_CANDIDATES,
    MAX_DISTANCIA_WMA30,
    RSC_SMA_PERIOD,
    SECTOR_RSC_MIN,
    SECTOR_TO_ETF,
    SP500_INDEX,
    VPM_BASE_PERIOD,
    VPM_SMOOTHING,
    WMA30_PERIOD,
)
from weinstein.data import download_weekly, load_sp500_tickers
from weinstein.indicators import (
    coppock_curve,
    distancia_wma_pct,
    momentum_vs_wma,
    rsc_mansfield,
    sp500_alcista,
    vpm5,
    wma,
)

# Máximo de hilos concurrentes contra yfinance.
# 20-25 es seguro; súbelo si tu red lo aguanta.
MAX_WORKERS = 20


# ── Pre-cálculo compartido ────────────────────────────────────────────

def _download_etf_rsc(
    etf: str,
    sp500_close: pd.Series,
    sem: Semaphore,
) -> tuple[str, float | None]:
    """Descarga un ETF y devuelve (etf, rsc_val | None). Thread-safe."""
    with sem:
        data = download_weekly(etf)
    if data is None:
        return etf, None
    try:
        rsc_val = float(rsc_mansfield(data["Close"].squeeze(), sp500_close).iloc[-1])
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
    coppock_bullish, direction = sp500_alcista(copk, recent_lookback=COPPOCK_RECENT_LOOKBACK)

    print(f"\n  Coppock SP500 actual   : {float(copk.iloc[-1]):+.4f}")
    print(f"  Coppock SP500 anterior : {float(copk.iloc[-2]):+.4f}")
    print(f"  Estado de mercado      : {direction}")

    # ── Early-exit: si el mercado ya es bajista, no hay nada que escanear ──
    if not coppock_bullish:
        print("\n  ⛔ Mercado BAJISTA (F5 falla). No se procesa ningún ticker.")
        return coppock_bullish, direction, {}

    unique_etfs = sorted(set(SECTOR_TO_ETF.values()))
    print(f"\n  Calculando RSC de {len(unique_etfs)} ETFs sectoriales (paralelo)...")

    sem = Semaphore(MAX_WORKERS)
    sector_rsc_map: dict[str, float] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_download_etf_rsc, etf, sp500_close, sem): etf
            for etf in unique_etfs
        }
        for fut in as_completed(futures):
            etf, rsc_val = fut.result()
            if rsc_val is not None:
                sector_rsc_map[etf] = rsc_val
                ok = "✓" if rsc_val >= SECTOR_RSC_MIN else "✗"
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
    sem:               Semaphore,
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
    etf_ticker     = SECTOR_TO_ETF.get(sector_name)
    rsc_sector_val = sector_rsc_map.get(etf_ticker, np.nan) if etf_ticker else np.nan
    f1_ok = (not pd.isna(rsc_sector_val)) and rsc_sector_val >= SECTOR_RSC_MIN
    if not f1_ok:
        return None, "filtrado"

    # Descarga del ticker — único I/O de esta función
    with sem:
        data = download_weekly(ticker)
    if data is None:
        return None, "sin_datos"

    close = data["Close"].squeeze()
    if len(close) < RSC_SMA_PERIOD + 5:
        return None, "sin_datos"

    # F3: RSC Mansfield activo > 0  (solo necesita close + sp500)
    close_a, sp500_a = close.align(sp500_close, join="inner")
    rsc_activo_val = float(rsc_mansfield(close_a, sp500_a).iloc[-1])
    if pd.isna(rsc_activo_val) or rsc_activo_val <= 0.0:
        return None, "filtrado"

    # F2: VPM5 > 0
    vpm5_val = float(vpm5(data, VPM_BASE_PERIOD, VPM_SMOOTHING).iloc[-1])
    if pd.isna(vpm5_val) or vpm5_val <= 0.0:
        return None, "filtrado"

    # F4: distancia WMA30 < MAX_DISTANCIA_WMA30
    wma30_val = float(wma(close, WMA30_PERIOD).iloc[-1])
    if pd.isna(wma30_val) or wma30_val <= 0:
        return None, "sin_datos"

    dist = distancia_wma_pct(close, WMA30_PERIOD)
    if dist is None or dist >= MAX_DISTANCIA_WMA30:
        return None, "filtrado"

    mom = momentum_vs_wma(close, WMA30_PERIOD)
    if mom is None:
        return None, "sin_datos"

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
    sem:               Semaphore,
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
            sem               = sem,
        )
        return result, motivo, ticker
    except Exception as exc:
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

    sem        = Semaphore(MAX_WORKERS)
    resultados: list[dict] = []
    counters   = {"sin_datos": 0, "filtrado": 0, "errores": 0}

    rows = [row for _, row in sp500_df.iterrows()]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(
                _worker, row, sp500_close,
                coppock_bullish, coppock_direction, sector_rsc_map, sem,
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