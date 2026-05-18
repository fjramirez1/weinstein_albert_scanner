"""
╔══════════════════════════════════════════════════════════════════════╗
║      WEINSTEIN VERSION ALBERT — S&P 500 WEEKLY MARKET SCANNER        ║
║                                                                      ║
║  Sistema: Método Weinstein adaptado por Albert (fuerza relativa,     ║
║           WMA30, VPM5, Coppock como filtro de mercado)               ║
║  Temporalidad : Semanal (1wk)                                        ║
║  Universo     : Componentes del S&P 500                              ║
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

# Período de descarga (necesitamos historia suficiente para todos los indicadores)
# WMA30 → 30 semanas | RSC SMA52 → 52 semanas | Coppock ROC14 + WMA10 → ~24 semanas
# Con 5 años (~260 semanas) tenemos margen más que suficiente

# Ventana para detectar un mínimo reciente del Coppock del mercado.
COPPOCK_RECENT_LOOKBACK = 4
# NUEVA FUNCIÓN: fallback Wikipedia
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
        # Wikipedia usa: Symbol, Security, GICS Sector, ...
        df = df.rename(columns={"Security": "Name", "GICS Sector": "Sector"})
        df["Symbol"] = df["Symbol"].astype(str).str.replace(".", "-", regex=False)
        df = df[["Symbol", "Name", "Sector"]].dropna(subset=["Symbol"])
        df = df.reset_index(drop=True)
        print(f"  ✓ {len(df)} tickers cargados desde Wikipedia.")
        return df
    except Exception as exc:
        print(f"  ✗ Fallback fallido: {exc}")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────
# FUNCIÓN CORREGIDA
# ─────────────────────────────────────────────────────────────────────
def get_sp500_tickers() -> pd.DataFrame:
    """
    Descarga la lista de componentes del S&P 500 desde GitHub con
    normalización robusta de columnas y fallback a Wikipedia.
    """
    print(f"  → Fuente primaria: {SP500_CSV_URL}")
    try:
        df = pd.read_csv(SP500_CSV_URL)
        df.columns = [c.strip() for c in df.columns]

        # ── Normalización robusta: mapear cualquier variante al nombre canónico ──
        col_rename: dict[str, str] = {}
        for col in df.columns:
            c_low = col.strip().lower()
            if c_low in ("symbol", "ticker"):
                col_rename[col] = "Symbol"
            elif c_low in ("name", "security", "company", "company name"):
                col_rename[col] = "Name"
            elif "sector" in c_low:          # captura 'Sector', 'GICS Sector', etc.
                col_rename[col] = "Sector"
        df.rename(columns=col_rename, inplace=True)

        # Si alguna columna sigue faltando, asignar valor por defecto
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
# El análisis está pensado para velas semanales ya cerradas; por eso
# la ejecución práctica se hace una vez por semana, no a diario.
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

        # yfinance >= 0.2.x puede devolver MultiIndex en columnas al descargar
        # un solo ticker; aplanamos si es necesario.
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        # Seleccionar y limpiar columnas OHLCV
        cols_needed = ["Open", "High", "Low", "Close", "Volume"]
        raw = raw[[c for c in cols_needed if c in raw.columns]].copy()
        raw.dropna(subset=["Close"], inplace=True)

        if len(raw) < MIN_BARS:
            return None

        return raw

    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────
# 4. INDICADORES TÉCNICOS
# ─────────────────────────────────────────────────────────────────────

# ── 4.1  WMA (Weighted Moving Average) ────────────────────────────────



# ── 4.2  RSC Mansfield ────────────────────────────────────────────────

# wma and rsc_mansfield moved to we_utils.py


# ── 4.3  VPM5 (Volumen Normalizado Positivo de 5 semanas) ─────────────

def vpm5(
    data: pd.DataFrame,
    base_period: int = VPM_BASE_PERIOD,
    smoothing_period: int = VPM_SMOOTHING,
) -> pd.Series:
    """
    Volumen Normalizado Positivo suavizado.

    Lógica
    ------
    1. Se calcula la media y la desviación estándar del volumen de las
       últimas 52 semanas.
    2. Para cada semana se obtiene el VPM como distancia estandarizada del
       volumen actual respecto a esa media.
    3. El VPM5 es la media móvil de 5 semanas aplicada al VPM.

    Fórmula
    -------
    VPM(t)  = (Volume(t) - mean52(Volume)) / std52(Volume)
    VPM5(t) = SMA5(VPM(t))

    Interpretación
    -------------
    VPM5 > 0 → el volumen reciente está por encima de su media histórica y
               respalda la entrada.
    VPM5 < 0 → el volumen reciente está por debajo de su media histórica.
    """
    volume = data["Volume"].squeeze().astype(float)

    rolling_mean = volume.rolling(window=base_period).mean()
    rolling_std = volume.rolling(window=base_period).std(ddof=0)
    vpm = (volume - rolling_mean) / rolling_std.replace(0, np.nan)

    vpm5_series = vpm.rolling(window=smoothing_period).mean()
    return vpm5_series


# ── 4.4  Coppock Curve ────────────────────────────────────────────────

def coppock_curve(
    price: pd.Series,
    roc_long:  int = COPPOCK_ROC1,
    roc_short: int = COPPOCK_ROC2,
    wma_period: int = COPPOCK_WMA,
) -> pd.Series:
    """
    Curva de Coppock estándar (adaptación semanal).

    Fórmula original (mensual, E. S. C. Coppock, 1962):
        Coppock = WMA(ROC(14) + ROC(11), 10)
    donde ROC(n) = ((Precio / Precio[n]) - 1) × 100

    Aplicado aquí sobre datos semanales del S&P 500 con los mismos
    parámetros numéricos —práctica habitual en trading cuantitativo.

    Interpretación como filtro de mercado
    --------------------------------------
    Coppock(t) > Coppock(t-1) → mercado en fase alcista → permitir entradas.
    Coppock(t) ≤ Coppock(t-1) → mercado sin momentum → evitar nuevas compras.
    """
    roc_l = price.pct_change(periods=roc_long)  * 100.0
    roc_s = price.pct_change(periods=roc_short) * 100.0
    combined = roc_l + roc_s

    return wma(combined, wma_period)


# ─────────────────────────────────────────────────────────────────────
# 5. PRE-CÁLCULO DE DATOS COMPARTIDOS
# ─────────────────────────────────────────────────────────────────────

def precompute_sp500_and_sectors(
    sp500_close: pd.Series,
) -> tuple[bool, str, dict[str, float]]:
    """
    Calcula el estado del S&P 500 (Coppock) y los RSC Mansfield de los
    ETFs sectoriales SPDR. Estos valores son constantes para todos los
    tickers y se calculan una sola vez por eficiencia.

    Parámetros
    ----------
    sp500_close : Serie de cierres semanales del ^GSPC

    Retorna
    -------
    coppock_bullish   : bool  — True si Sp500alcista se activa
    coppock_direction : str   — etiqueta descriptiva
    sector_rsc        : dict  — { 'XLK': valor_rsc, 'XLF': valor_rsc, … }
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
            estado = "✓" if rsc_last > 0 else "✗"
            print(f"    {estado} {etf}: RSC = {rsc_last:+.4f}")
        except Exception as exc:
            print(f"    ✗ {etf}: error en RSC ({exc})")

    return coppock_bullish, coppock_direction, sector_rsc


# ─────────────────────────────────────────────────────────────────────
# 6. EVALUACIÓN DE UN TICKER
# ─────────────────────────────────────────────────────────────────────

def evaluate_ticker(
    ticker:            str,
    sector_name:       str,
    company_name:      str,
    sp500_close:       pd.Series,
    coppock_bullish:   bool,
    coppock_direction: str,
    sector_rsc_map:    dict[str, float],
) -> dict | None:
    """
    Descarga datos del ticker y aplica los 5 filtros Weinstein-Albert.

    Retorna
    -------
    dict con las métricas si pasa todos los filtros, None en caso contrario.
    """
    # ── Descarga
    data = download_weekly(ticker)
    if data is None:
        return None

    close  = data["Close"].squeeze()
    n_bars = len(close)

    if n_bars < MIN_BARS:
        return None

    # ── WMA30
    wma30_series = wma(close, WMA30_PERIOD)
    wma30_val    = float(wma30_series.iloc[-1])
    precio_actual = float(close.iloc[-1])

    if pd.isna(wma30_val) or wma30_val <= 0:
        return None

    # Distancia porcentual a la WMA30
    distancia_wma30 = ((precio_actual - wma30_val) / wma30_val) * 100.0

    # ── Momentum Relativo (MOM)
    mom_val = calculate_mom(close, ma_period=30)
    if mom_val is None:
        return None  # Excluir si no hay datos suficientes para MOM

    # ── Momentum Relativo (MOM)
    mom_val = calculate_mom(close, ma_period=30)
    if mom_val is None:
        return None  # Excluir si no hay datos suficientes para MOM

    # ── RSC Mansfield del activo vs S&P 500
    close_aligned, sp500_aligned = close.align(sp500_close, join="inner")
    if len(close_aligned) < RSC_SMA_PERIOD + 5:
        return None

    rsc_activo_series = rsc_mansfield(close_aligned, sp500_aligned)
    rsc_activo_val    = float(rsc_activo_series.iloc[-1])

    # ── RSC Mansfield del sector (pre-calculado)
    etf_ticker = SECTOR_TO_ETF.get(sector_name)
    if etf_ticker and etf_ticker in sector_rsc_map:
        rsc_sector_val = sector_rsc_map[etf_ticker]
    else:
        rsc_sector_val = np.nan   # sector desconocido → filtro fallará

    # ── VPM5
    vpm5_series = vpm5(data)
    vpm5_val    = float(vpm5_series.iloc[-1])

    # ──────────────────────────────────────────────────────────────────
    # APLICACIÓN DE LOS 5 FILTROS (operador AND)
    # ──────────────────────────────────────────────────────────────────
    #
    #  F1: RSC Mansfield del SECTOR >= 0.10
    #  F2: VPM5 > 0
    #  F3: RSC Mansfield del ACTIVO > 0
    #  F4: Distancia a WMA30 < 8 %
    #  F5: Sp500alcista
    #      - inicio alcista desde un mínimo reciente del Coppock, o
    #      - continuación alcista cuando Coppock ya es positivo y sigue subiendo
    #
    # ──────────────────────────────────────────────────────────────────

    filtros = {
        "F1_rsc_sector"   : (not pd.isna(rsc_sector_val)) and (rsc_sector_val   >= SECTOR_RSC_MIN),
        "F2_vpm5"         : (not pd.isna(vpm5_val))       and (vpm5_val         > 0.0),
        "F3_rsc_activo"   : (not pd.isna(rsc_activo_val)) and (rsc_activo_val   > 0.0),
        "F4_distancia"    : (not pd.isna(distancia_wma30)) and (distancia_wma30 < MAX_DISTANCIA_WMA30),
        "F5_coppock_bull" : coppock_bullish,
    }

    # Solo devolver resultado si todos los filtros son True
    if not all(filtros.values()):
        return None

    return {
        "Ticker"                : ticker,
        "Nombre"                : company_name,
        "Sector"                : sector_name,
        "ETF Sector"            : etf_ticker if etf_ticker else "N/A",
        "Precio Actual"         : round(precio_actual, 2),
        "RSC Mansfield Activo"  : round(rsc_activo_val, 4),
        "Momentum (MOM)"         : round(mom_val, 4),
        "RSC Mansfield Sector"  : round(rsc_sector_val, 4) if not pd.isna(rsc_sector_val) else np.nan,
        "VPM5"                  : round(vpm5_val, 4),
        "Distancia % WMA30"     : round(distancia_wma30, 2),
        "Dirección Coppock SP500": coppock_direction,
    }


# ─────────────────────────────────────────────────────────────────────
# 7. FUNCIÓN PRINCIPAL — ORQUESTADOR DEL ESCÁNER
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
    print("\n" + "═" * 68)
    print("  WEINSTEIN VERSION ALBERT — S&P 500 WEEKLY SCANNER")
    print(f"  Ejecución: {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
    print("═" * 68)

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

    # Pre-calcular Coppock + RSC sectoriales (operación costosa, se hace una vez)
    coppock_bullish, coppock_direction, sector_rsc_map = precompute_sp500_and_sectors(
        sp500_close
    )

    # ── PASO 3 y 4: Escanear cada ticker
    print(f"\n[PASO 3] Escaneando {total_tickers} acciones (esto puede tardar varios minutos)...")
    print("─" * 68)

    resultados  = []
    errores     = 0
    sin_datos   = 0
    procesados  = 0

    for idx, fila in sp500_df.iterrows():
        ticker  = fila["Symbol"]
        nombre  = fila.get("Name",   "N/A")
        sector  = fila.get("Sector", "Unknown")

        try:
            resultado = evaluate_ticker(
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
                # Feedback inmediato al usuario cuando encuentra un candidato
                print(f"  ★ CANDIDATO → {ticker:<6} | {sector:<30} | "
                      f"MOM: {resultado['Momentum (MOM)']:+.3f} | "
                      f"RSC: {resultado['RSC Mansfield Activo']:+.3f} | "
                      f"Dist: {resultado['Distancia % WMA30']:+.1f}%")

        except Exception as exc:
            # Captura cualquier error inesperado sin detener el script
            errores += 1
            # Descomentar la siguiente línea para ver detalles de errores:
            # print(f"  ✗ ERROR {ticker}: {exc}")

        else:
            if resultado is None:
                sin_datos += 1

        procesados += 1

        # Progreso cada 50 tickers
        if procesados % 50 == 0:
            print(f"  … {procesados}/{total_tickers} procesados | "
                  f"Candidatos: {len(resultados)} | Errores: {errores}")

    # ── PASO 5: Resultado final
    print("\n" + "═" * 68)
    print(f"  RESUMEN DEL ESCÁNER")
    print("─" * 68)
    print(f"  Acciones procesadas      : {procesados}")
    print(f"  Sin datos / insuf.       : {sin_datos}")
    print(f"  Errores de descarga      : {errores}")
    print(f"  Candidatos (5/5 filtros) : {len(resultados)}")
    print("═" * 68)

    if not resultados:
        print("\n  No se encontraron acciones que cumplan todos los filtros.")
        return pd.DataFrame()

    # Construir DataFrame de resultados
    df = pd.DataFrame(resultados)

    # Ordenar por Momentum Relativo (mayor → tendencia más alcista)
    df.sort_values("Momentum (MOM)", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Limitar a top 10 posiciones
    df = df.head(10)

    print(f"  [TOP 10] Seleccionados {len(df)} stocks con mayor Momentum Relativo")

    # ── Columnas de salida requeridas (especificación del sistema)
    columnas_output = [
        "Ticker",
        "Sector",
        "Precio Actual",
        "Momentum (MOM)",
        "RSC Mansfield Activo",
        "Distancia % WMA30",
        "Dirección Coppock SP500",
    ]

    print("\n  ACCIONES QUE CUMPLEN LOS 5 FILTROS WEINSTEIN-ALBERT")
    print("─" * 68)
    print(df[columnas_output].to_string(index=True))
    print("─" * 68)

    return df


# ─────────────────────────────────────────────────────────────────────
# 8. EXPORTACIÓN DE RESULTADOS
# ─────────────────────────────────────────────────────────────────────

def export_results(df: pd.DataFrame) -> None:
    """
    Exporta el DataFrame de resultados a CSV con fecha en el nombre.

    Columnas del CSV (completo, incluyendo métricas auxiliares):
        Ticker, Nombre, Sector, ETF Sector, Precio Actual,
        RSC Mansfield Activo, Momentum (MOM), RSC Mansfield Sector, VPM5,
        Distancia % WMA30, Dirección Coppock SP500
    """
    if df.empty:
        return

    fecha  = datetime.now().strftime("%Y%m%d_%H%M")
    nombre = f"weinstein_albert_scan_{fecha}.csv"

    df.to_csv(nombre, index=False, encoding="utf-8-sig")
    print(f"\n  ✅ Resultados exportados → {nombre}")


# ─────────────────────────────────────────────────────────────────────
# 9. ENTRY POINT
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    df_resultado = run_scanner()
    export_results(df_resultado)

    # El objeto df_resultado está disponible para análisis adicional
    # en notebooks o scripts que importen este módulo.
