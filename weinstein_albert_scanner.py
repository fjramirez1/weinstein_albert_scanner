"""
╔══════════════════════════════════════════════════════════════════════╗
║      WEINSTEIN VERSION ALBERT — S&P 500 WEEKLY MARKET SCANNER        ║
║                                                                      ║
║  Sistema: Método Weinstein adaptado por Albert (fuerza relativa,     ║
║           WMA30, VPM5, Coppock como filtro de mercado)               ║
║  Temporalidad : Semanal (1wk)                                        ║
║  Universo     : Acciones/tickers del S&P 500                         ║
║                 (número variable; puede superar 500)                 ║
║  Operativa    : Ejecutar tras el cierre semanal, idealmente          ║
║                 durante el fin de semana                             ║
║  Operador     : AND — todos los filtros deben cumplirse              ║
╚══════════════════════════════════════════════════════════════════════╝

Dependencias:
    pip install yfinance pandas numpy requests

Uso:
    python weinstein_albert_scanner.py

Este script forma parte de una estrategia de trading algorítmico:
evalúa el universo del S&P 500 con datos semanales y devuelve solo
los candidatos que cumplen todos los filtros de entrada.
"""

# ─────────────────────────────────────────────────────────────────────
# IMPORTACIONES
# ─────────────────────────────────────────────────────────────────────

import warnings
import sys
from datetime import datetime
from pathlib import Path
import os

import numpy as np
import pandas as pd
import yfinance as yf
from we_utils import wma, rsc_mansfield, vpm5, coppock_curve, sp500_alcista, calculate_mom

warnings.filterwarnings("ignore")

# Allow a safe dry-run for testing runner scripts without downloading data
if os.getenv("WEINSTEIN_DRY_RUN") == "1":
    print("WEINSTEIN_DRY_RUN=1 detected — dry run, exiting without network calls.")
    sys.exit(0)


# ─────────────────────────────────────────────────────────────────────
# 1. CONFIGURACIÓN GLOBAL
# ─────────────────────────────────────────────────────────────────────

# Ticker del índice de referencia
SP500_INDEX = "^GSPC"

# Fuente primaria para descargar los componentes del S&P 500.
SP500_CSV_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"

# Periodo de descarga semanal usado en el escáner de entrada.
DOWNLOAD_PERIOD = "6y"

# Umbrales y parámetros de los filtros técnicos.
MIN_BARS = 70
WMA30_PERIOD = 30
RSC_SMA_PERIOD = 52
VPM_BASE_PERIOD = 52
VPM_SMOOTHING = 5
COPPOCK_ROC1 = 14
COPPOCK_ROC2 = 11
COPPOCK_WMA = 10
SECTOR_RSC_MIN = 0.10
MAX_DISTANCIA_WMA30 = 8.0

# Mapeo de sectores GICS a ETFs sectoriales SPDR.
SECTOR_TO_ETF = {
    "Communication Services": "XLC",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Technology": "XLK",
    "Utilities": "XLU",
}

# Ventana para detectar un mínimo reciente del Coppock del mercado.
COPPOCK_RECENT_LOOKBACK = 4


# ─────────────────────────────────────────────────────────────────────
# 2. CARGA DE TICKERS S&P 500
# ─────────────────────────────────────────────────────────────────────

def _get_sp500_from_wikipedia() -> pd.DataFrame:
    """Fuente de respaldo: tabla de Wikipedia."""
    print("  → Fallback: leyendo desde Wikipedia...")
    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            attrs={"id": "constituents"},
        )
        df = tables[0].copy()
        df = df.rename(columns={"Security": "Name", "GICS Sector": "Sector"})
        df["Symbol"] = df["Symbol"].astype(str).str.replace(".", "-", regex=False)
        df = df[["Symbol", "Name", "Sector"]].dropna(subset=["Symbol"])
        df = df.reset_index(drop=True)
        print(f"  ✓ {len(df)} tickers cargados desde Wikipedia.")
        return df
    except Exception as exc:
        print(f"  ✗ Fallback fallido: {exc}")
        sys.exit(1)


def get_sp500_tickers() -> pd.DataFrame:
    """
    Descarga la lista de componentes del S&P 500 desde GitHub con
    normalización robusta de columnas y fallback a Wikipedia.
    """
    print(f"  → Fuente primaria: {SP500_CSV_URL}")
    try:
        df = pd.read_csv(SP500_CSV_URL)
        df.columns = [c.strip() for c in df.columns]

        col_rename: dict[str, str] = {}
        for col in df.columns:
            c_low = col.strip().lower()
            if c_low in ("symbol", "ticker"):
                col_rename[col] = "Symbol"
            elif c_low in ("name", "security", "company", "company name"):
                col_rename[col] = "Name"
            elif "sector" in c_low:
                col_rename[col] = "Sector"
        df.rename(columns=col_rename, inplace=True)

        for req in ("Symbol", "Name", "Sector"):
            if req not in df.columns:
                print(f"  ⚠️  Columna '{req}' no encontrada; se asignará 'N/A'.")
                df[req] = "N/A"

        df["Symbol"] = df["Symbol"].astype(str).str.replace(".", "-", regex=False)
        df = df[["Symbol", "Name", "Sector"]].dropna(subset=["Symbol"])
        df = df.reset_index(drop=True)
        print(f"  ✓ {len(df)} tickers cargados correctamente.")
        return df

    except Exception as exc:
        print(f"  ✗ Error al descargar tickers: {exc}")
        return _get_sp500_from_wikipedia()


# ─────────────────────────────────────────────────────────────────────
# 3. DESCARGA DE DATOS SEMANALES
# ─────────────────────────────────────────────────────────────────────

def download_weekly(ticker: str, period: str = DOWNLOAD_PERIOD) -> pd.DataFrame | None:
    """
    Descarga datos OHLCV semanales de un ticker usando yfinance.

    Retorna
    -------
    pd.DataFrame con columnas [Open, High, Low, Close, Volume] indexado por fecha,
    o None si la descarga falla o hay datos insuficientes.
    """
    try:
        raw = yf.download(
            ticker,
            period=period,
            interval="1wk",
            progress=False,
            auto_adjust=True,
            actions=False,
        )

        if raw is None or raw.empty:
            return None

        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        cols_needed = ["Open", "High", "Low", "Close", "Volume"]
        raw = raw[[c for c in cols_needed if c in raw.columns]].copy()
        raw.dropna(subset=["Close"], inplace=True)

        if len(raw) < MIN_BARS:
            return None

        return raw

    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────
# 4. PRE-CÁLCULO DE DATOS COMPARTIDOS
# ─────────────────────────────────────────────────────────────────────

def precompute_sp500_and_sectors(
    sp500_close: pd.Series,
) -> tuple[bool, str, dict[str, float]]:
    """
    Calcula el estado del S&P 500 (Coppock) y los RSC Mansfield de los
    ETFs sectoriales SPDR. Estos valores son constantes para todos los
    tickers y se calculan una sola vez por eficiencia.
    """
    # ── Coppock del S&P 500
    copk = coppock_curve(sp500_close)
    coppock_bullish, coppock_direction = sp500_alcista(
        copk,
        recent_lookback=COPPOCK_RECENT_LOOKBACK,
    )
    coppock_now  = copk.iloc[-1]
    coppock_prev = copk.iloc[-2]

    print(f"\n  Coppock SP500 actual   : {coppock_now:+.4f}")
    print(f"  Coppock SP500 anterior : {coppock_prev:+.4f}")
    print(f"  Estado de mercado      : {coppock_direction}")

    # ── RSC Mansfield de cada ETF sectorial SPDR
    unique_etfs = sorted(set(SECTOR_TO_ETF.values()))
    sector_rsc: dict[str, float] = {}

    print(f"\n  Calculando RSC de {len(unique_etfs)} ETFs sectoriales...")

    for etf in unique_etfs:
        etf_data = download_weekly(etf)
        if etf_data is None:
            print(f"    ✗ {etf}: sin datos")
            continue

        etf_close = etf_data["Close"].squeeze()

        try:
            rsc_series = rsc_mansfield(etf_close, sp500_close)
            rsc_last   = float(rsc_series.iloc[-1])
            sector_rsc[etf] = rsc_last
            estado = "✓" if rsc_last >= SECTOR_RSC_MIN else "✗"
            print(f"    {estado} {etf}: RSC = {rsc_last:+.4f}")
        except Exception as exc:
            print(f"    ✗ {etf}: error en RSC ({exc})")

    return coppock_bullish, coppock_direction, sector_rsc


# ─────────────────────────────────────────────────────────────────────
# 5. EVALUACIÓN DE UN TICKER
# ─────────────────────────────────────────────────────────────────────

def evaluate_ticker(
    ticker:            str,
    sector_name:       str,
    company_name:      str,
    sp500_close:       pd.Series,
    coppock_bullish:   bool,
    coppock_direction: str,
    sector_rsc_map:    dict[str, float],
) -> tuple[dict | None, str]:
    """
    Descarga datos del ticker y aplica los 5 filtros Weinstein-Albert.

    Retorna
    -------
    (dict | None, str)
        - dict con las métricas si pasa todos los filtros.
        - (None, "sin_datos") si no se pudo descargar histórico suficiente.
        - (None, "filtrado")  si hubo datos pero no pasó algún filtro.
    """
    # ── Descarga
    data = download_weekly(ticker)
    if data is None:
        return None, "sin_datos"

    close  = data["Close"].squeeze()
    n_bars = len(close)

    if n_bars < MIN_BARS:
        return None, "sin_datos"

    # ── WMA30
    wma30_series = wma(close, WMA30_PERIOD)
    wma30_val    = float(wma30_series.iloc[-1])
    precio_actual = float(close.iloc[-1])

    if pd.isna(wma30_val) or wma30_val <= 0:
        return None, "sin_datos"

    # Distancia porcentual a la WMA30
    distancia_wma30 = ((precio_actual - wma30_val) / wma30_val) * 100.0

    # ── Momentum Relativo (MOM)
    mom_val = calculate_mom(close, ma_period=30)
    if mom_val is None:
        return None, "sin_datos"

    # ── RSC Mansfield del activo vs S&P 500
    close_aligned, sp500_aligned = close.align(sp500_close, join="inner")
    if len(close_aligned) < RSC_SMA_PERIOD + 5:
        return None, "sin_datos"

    rsc_activo_series = rsc_mansfield(close_aligned, sp500_aligned)
    rsc_activo_val    = float(rsc_activo_series.iloc[-1])

    # ── RSC Mansfield del sector (pre-calculado)
    etf_ticker = SECTOR_TO_ETF.get(sector_name)
    if etf_ticker and etf_ticker in sector_rsc_map:
        rsc_sector_val = sector_rsc_map[etf_ticker]
    else:
        rsc_sector_val = np.nan

    # ── VPM5 — importado desde we_utils, sin duplicado local
    vpm5_series = vpm5(data, base_period=VPM_BASE_PERIOD, smoothing_period=VPM_SMOOTHING)
    vpm5_val    = float(vpm5_series.iloc[-1])

    # ──────────────────────────────────────────────────────────────────
    # APLICACIÓN DE LOS 5 FILTROS (operador AND)
    #
    #  F1: RSC Mansfield del SECTOR >= 0.10
    #  F2: VPM5 > 0
    #  F3: RSC Mansfield del ACTIVO > 0
    #  F4: Distancia a WMA30 < 8 %
    #  F5: Sp500alcista
    # ──────────────────────────────────────────────────────────────────

    filtros = {
        "F1_rsc_sector"   : (not pd.isna(rsc_sector_val)) and (rsc_sector_val   >= SECTOR_RSC_MIN),
        "F2_vpm5"         : (not pd.isna(vpm5_val))       and (vpm5_val         > 0.0),
        "F3_rsc_activo"   : (not pd.isna(rsc_activo_val)) and (rsc_activo_val   > 0.0),
        "F4_distancia"    : (not pd.isna(distancia_wma30)) and (distancia_wma30 < MAX_DISTANCIA_WMA30),
        "F5_coppock_bull" : coppock_bullish,
    }

    if not all(filtros.values()):
        return None, "filtrado"

    resultado = {
        "Ticker"                 : ticker,
        "Nombre"                 : company_name,
        "Sector"                 : sector_name,
        "ETF Sector"             : etf_ticker if etf_ticker else "N/A",
        "Precio Actual"          : round(precio_actual, 2),
        "RSC Mansfield Activo"   : round(rsc_activo_val, 4),
        "Momentum (MOM)"         : round(mom_val, 4),
        "RSC Mansfield Sector"   : round(rsc_sector_val, 4) if not pd.isna(rsc_sector_val) else np.nan,
        "VPM5"                   : round(vpm5_val, 4),
        "Distancia % WMA30"      : round(distancia_wma30, 2),
        "Dirección Coppock SP500": coppock_direction,
    }
    return resultado, "ok"


# ─────────────────────────────────────────────────────────────────────
# 6. FUNCIÓN PRINCIPAL — ORQUESTADOR DEL ESCÁNER
# ─────────────────────────────────────────────────────────────────────

def run_scanner() -> pd.DataFrame:
    """
    Punto de entrada principal del escáner.

    Flujo
    -----
    1. Cargar tickers S&P 500 desde CSV público en GitHub
    2. Descargar S&P 500 (^GSPC) y calcular Coppock + RSC sectoriales
    3. Iterar sobre cada ticker con try-except individual
    4. Aplicar los 5 filtros Weinstein-Albert en paralelo (AND)
    5. Construir y devolver el DataFrame de resultados
    """
    print("\n" + "═" * 72)
    print("  WEINSTEIN VERSION ALBERT — S&P 500 WEEKLY SCANNER")
    print(f"  Ejecución: {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
    print("═" * 72)

    # ── PASO 1: Tickers
    print("\n[PASO 1] Descargando componentes del S&P 500...")
    sp500_df = get_sp500_tickers()
    total_tickers = len(sp500_df)

    # ── PASO 2: Datos del índice
    print("\n[PASO 2] Descargando S&P 500 (^GSPC) y pre-calculando indicadores...")
    sp500_data = download_weekly(SP500_INDEX, period=DOWNLOAD_PERIOD)
    if sp500_data is None:
        print("ERROR CRÍTICO: No se pudo descargar el S&P 500. Abortando.")
        sys.exit(1)

    sp500_close = sp500_data["Close"].squeeze()

    coppock_bullish, coppock_direction, sector_rsc_map = precompute_sp500_and_sectors(
        sp500_close
    )

    # ── PASO 3 y 4: Escanear cada ticker
    print(f"\n[PASO 3] Escaneando {total_tickers} acciones (esto puede tardar varios minutos)...")
    print("─" * 72)

    resultados  = []
    errores     = 0
    sin_datos   = 0
    filtrados   = 0
    procesados  = 0

    for idx, fila in sp500_df.iterrows():
        ticker  = fila["Symbol"]
        nombre  = fila.get("Name",   "N/A")
        sector  = fila.get("Sector", "Unknown")

        try:
            resultado, motivo = evaluate_ticker(
                ticker            = ticker,
                sector_name       = sector,
                company_name      = nombre,
                sp500_close       = sp500_close,
                coppock_bullish   = coppock_bullish,
                coppock_direction = coppock_direction,
                sector_rsc_map    = sector_rsc_map,
            )

            if resultado is not None:
                resultados.append(resultado)
                print(
                    f"  ★ CANDIDATO → {ticker:<6} | {sector:<30} | "
                    f"MOM: {resultado['Momentum (MOM)']:+.3f} | "
                    f"RSC: {resultado['RSC Mansfield Activo']:+.3f} | "
                    f"VPM5: {resultado['VPM5']:+.3f} | "
                    f"Dist: {resultado['Distancia % WMA30']:+.1f}%"
                )
            elif motivo == "sin_datos":
                sin_datos += 1
            elif motivo == "filtrado":
                filtrados += 1

        except Exception as exc:
            errores += 1
            # Descomentar para ver detalles de errores:
            # print(f"  ✗ ERROR {ticker}: {exc}")

        procesados += 1

        if procesados % 50 == 0:
            print(f"  … {procesados}/{total_tickers} procesados | "
                  f"Candidatos: {len(resultados)} | Errores: {errores}")

    # ── PASO 5: Resultado final
    print("\n" + "═" * 72)
    print(f"  RESUMEN DEL ESCÁNER")
    print("─" * 72)
    print(f"  Acciones procesadas          : {procesados}")
    print(f"  Sin datos / histórico insuf. : {sin_datos}")
    print(f"  No cumplen filtros           : {filtrados}")
    print(f"  Errores de descarga          : {errores}")
    print(f"  Candidatos (5/5 filtros)     : {len(resultados)}")
    print("═" * 72)

    if not resultados:
        print("\n  No se encontraron acciones que cumplan todos los filtros.")
        return pd.DataFrame()

    df = pd.DataFrame(resultados)

    # Ordenar por Momentum Relativo (mayor → tendencia más alcista)
    df.sort_values("Momentum (MOM)", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Limitar a top 10 posiciones
    df = df.head(10)

    print(f"  [TOP 10] Seleccionados {len(df)} stocks con mayor Momentum Relativo")

    # ── Columnas de salida — ahora incluye VPM5
    columnas_output = [
        "Ticker",
        "Sector",
        "Precio Actual",
        "Momentum (MOM)",
        "RSC Mansfield Activo",
        "VPM5",
        "Distancia % WMA30",
        "Dirección Coppock SP500",
    ]

    print("\n  ACCIONES QUE CUMPLEN LOS 5 FILTROS WEINSTEIN-ALBERT")
    print("─" * 72)
    print(df[columnas_output].to_string(index=True))
    print("─" * 72)

    return df


# ─────────────────────────────────────────────────────────────────────
# 7. EXPORTACIÓN DE RESULTADOS
# ─────────────────────────────────────────────────────────────────────

def export_results(df: pd.DataFrame) -> None:
    """
    Exporta el DataFrame de resultados a CSV con fecha en el nombre.
    El archivo se guarda en historial/entradas/ para mantener un registro
    histórico de todas las ejecuciones del escáner de entrada.

    Columnas del CSV (completo, incluyendo métricas auxiliares):
        Ticker, Nombre, Sector, ETF Sector, Precio Actual,
        RSC Mansfield Activo, Momentum (MOM), RSC Mansfield Sector, VPM5,
        Distancia % WMA30, Dirección Coppock SP500
    """
    if df.empty:
        return

    carpeta = Path("historial") / "entradas"
    carpeta.mkdir(parents=True, exist_ok=True)

    fecha  = datetime.now().strftime("%Y%m%d_%H%M")
    ruta   = carpeta / f"weinstein_albert_scan_{fecha}.csv"

    df.to_csv(ruta, index=False, encoding="utf-8-sig")
    print(f"\n  ✅ Resultados exportados → {ruta}")


# ─────────────────────────────────────────────────────────────────────
# 8. ENTRY POINT
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    df_resultado = run_scanner()
    export_results(df_resultado)