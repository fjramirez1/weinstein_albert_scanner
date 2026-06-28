"""
Escáner de condiciones de ENTRADA — estrategia Weinstein-Albert.

Flujo
-----
1. Cargar tickers del S&P 500.
2. Descargar ^GSPC y pre-calcular Coppock + RSC sectoriales (una vez).
3. Evaluar cada ticker con los 5 filtros (AND).
4. Devolver el top-N ordenado por Momentum Relativo.
"""

from __future__ import annotations

import sys
from datetime import datetime

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


# ─────────────────────────────────────────────────────────────────────
# Pre-cálculo compartido (S&P 500 + sectores)
# ─────────────────────────────────────────────────────────────────────

def _precompute_market_context(
    sp500_close: pd.Series,
) -> tuple[bool, str, dict[str, float]]:
    """
    Calcula el estado del mercado y los RSC sectoriales.

    Se llama una sola vez por ejecución para evitar descargas redundantes.

    Retorna
    -------
    (coppock_bullish, coppock_direction, sector_rsc_map)
    """
    copk = coppock_curve(sp500_close)
    coppock_bullish, direction = sp500_alcista(copk, recent_lookback=COPPOCK_RECENT_LOOKBACK)

    print(f"\n  Coppock SP500 actual   : {float(copk.iloc[-1]):+.4f}")
    print(f"  Coppock SP500 anterior : {float(copk.iloc[-2]):+.4f}")
    print(f"  Estado de mercado      : {direction}")

    # RSC de cada ETF sectorial
    unique_etfs    = sorted(set(SECTOR_TO_ETF.values()))
    sector_rsc_map: dict[str, float] = {}

    print(f"\n  Calculando RSC de {len(unique_etfs)} ETFs sectoriales...")
    for etf in unique_etfs:
        etf_data = download_weekly(etf)
        if etf_data is None:
            print(f"    ✗ {etf}: sin datos")
            continue
        try:
            rsc_series     = rsc_mansfield(etf_data["Close"].squeeze(), sp500_close)
            rsc_val        = float(rsc_series.iloc[-1])
            sector_rsc_map[etf] = rsc_val
            ok = "✓" if rsc_val >= SECTOR_RSC_MIN else "✗"
            print(f"    {ok} {etf}: RSC = {rsc_val:+.4f}")
        except Exception as exc:
            print(f"    ✗ {etf}: error en RSC ({exc})")

    return coppock_bullish, direction, sector_rsc_map


# ─────────────────────────────────────────────────────────────────────
# Evaluación de un ticker
# ─────────────────────────────────────────────────────────────────────

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
    Aplica los 5 filtros Weinstein-Albert a un ticker.

    Retorna
    -------
    (dict_resultado, motivo)
        motivo ∈ {"ok", "sin_datos", "filtrado"}
    """
    data = download_weekly(ticker)
    if data is None:
        return None, "sin_datos"

    close = data["Close"].squeeze()
    if len(close) < RSC_SMA_PERIOD + 5:
        return None, "sin_datos"

    # ── Indicadores ──────────────────────────────────────────────────
    wma30_val = float(wma(close, WMA30_PERIOD).iloc[-1])
    if pd.isna(wma30_val) or wma30_val <= 0:
        return None, "sin_datos"

    dist     = distancia_wma_pct(close, WMA30_PERIOD)
    mom      = momentum_vs_wma(close, WMA30_PERIOD)
    vpm5_val = float(vpm5(data, VPM_BASE_PERIOD, VPM_SMOOTHING).iloc[-1])

    close_a, sp500_a = close.align(sp500_close, join="inner")
    rsc_activo_val   = float(rsc_mansfield(close_a, sp500_a).iloc[-1])

    etf_ticker    = SECTOR_TO_ETF.get(sector_name)
    rsc_sector_val = sector_rsc_map.get(etf_ticker, np.nan) if etf_ticker else np.nan

    if dist is None or mom is None:
        return None, "sin_datos"

    # ── Filtros (AND) ────────────────────────────────────────────────
    #  F1: RSC sector >= 0.10
    #  F2: VPM5 > 0
    #  F3: RSC activo > 0
    #  F4: distancia WMA30 < +8 %   (sin cota inferior)
    #  F5: Coppock alcista
    filtros = {
        "F1_rsc_sector"   : (not pd.isna(rsc_sector_val)) and rsc_sector_val >= SECTOR_RSC_MIN,
        "F2_vpm5"         : (not pd.isna(vpm5_val))       and vpm5_val > 0.0,
        "F3_rsc_activo"   : (not pd.isna(rsc_activo_val)) and rsc_activo_val > 0.0,
        "F4_distancia"    : (not pd.isna(dist))            and dist < MAX_DISTANCIA_WMA30,
        "F5_coppock_bull" : coppock_bullish,
    }

    if not all(filtros.values()):
        return None, "filtrado"

    return {
        "Ticker"                 : ticker,
        "Nombre"                 : company_name,
        "Sector"                 : sector_name,
        "ETF Sector"             : etf_ticker or "N/A",
        "Precio Actual"          : round(float(close.iloc[-1]), 2),
        "RSC Mansfield Activo"   : round(rsc_activo_val, 4),
        "Momentum (MOM)"         : round(mom, 4),
        "RSC Mansfield Sector"   : round(rsc_sector_val, 4) if not pd.isna(rsc_sector_val) else np.nan,
        "VPM5"                   : round(vpm5_val, 4),
        "Distancia % WMA30"      : round(dist, 2),
        "Dirección Coppock SP500": coppock_direction,
    }, "ok"


# ─────────────────────────────────────────────────────────────────────
# Función principal
# ─────────────────────────────────────────────────────────────────────

def run_entry_scanner() -> pd.DataFrame:
    """
    Ejecuta el escáner de entrada completo y devuelve los candidatos.

    Retorna
    -------
    pd.DataFrame con hasta ``MAX_CANDIDATES`` filas ordenadas por MOM
    descendente, o un DataFrame vacío si no hay candidatos.
    """
    print("\n" + "═" * 72)
    print("  WEINSTEIN VERSION ALBERT — S&P 500 WEEKLY ENTRY SCANNER")
    print(f"  Ejecución : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
    print("═" * 72)

    # PASO 1 — Tickers
    print("\n[1/3] Descargando constituyentes del S&P 500...")
    sp500_df      = load_sp500_tickers()
    total_tickers = len(sp500_df)

    # PASO 2 — Contexto de mercado
    print("\n[2/3] Descargando S&P 500 y calculando indicadores de mercado...")
    sp500_data = download_weekly(SP500_INDEX, period=DOWNLOAD_PERIOD_ENTRY)
    if sp500_data is None:
        print("  ✗ ERROR CRÍTICO: no se pudo descargar el S&P 500. Abortando.")
        sys.exit(1)

    sp500_close = sp500_data["Close"].squeeze()
    coppock_bullish, coppock_direction, sector_rsc_map = _precompute_market_context(sp500_close)

    # PASO 3 — Escanear tickers
    print(f"\n[3/3] Escaneando {total_tickers} acciones...")
    print("─" * 72)

    resultados: list[dict] = []
    counters = {"sin_datos": 0, "filtrado": 0, "errores": 0, "procesados": 0}

    for _, fila in sp500_df.iterrows():
        ticker = fila["Symbol"]
        nombre = fila.get("Name",   "N/A")
        sector = fila.get("Sector", "Unknown")

        try:
            resultado, motivo = _evaluate_ticker(
                ticker            = ticker,
                sector_name       = sector,
                company_name      = nombre,
                sp500_close       = sp500_close,
                coppock_bullish   = coppock_bullish,
                coppock_direction = coppock_direction,
                sector_rsc_map    = sector_rsc_map,
            )
            if resultado:
                resultados.append(resultado)
                print(
                    f"  ★ CANDIDATO → {ticker:<6} | {sector:<30} | "
                    f"MOM: {resultado['Momentum (MOM)']:+.3f} | "
                    f"RSC: {resultado['RSC Mansfield Activo']:+.3f} | "
                    f"VPM5: {resultado['VPM5']:+.3f} | "
                    f"Dist: {resultado['Distancia % WMA30']:+.1f}%"
                )
            else:
                counters[motivo] += 1
        except Exception:
            counters["errores"] += 1

        counters["procesados"] += 1
        if counters["procesados"] % 50 == 0:
            print(
                f"  … {counters['procesados']}/{total_tickers} procesados | "
                f"Candidatos: {len(resultados)} | Errores: {counters['errores']}"
            )

    # Resumen
    print("\n" + "═" * 72)
    print("  RESUMEN DEL ESCÁNER")
    print("─" * 72)
    print(f"  Acciones procesadas          : {counters['procesados']}")
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