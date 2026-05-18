"""
╔══════════════════════════════════════════════════════════════════════╗
║      WEINSTEIN VERSION ALBERT — ESCÁNER DE CONDICIONES DE SALIDA    ║
║                                                                      ║
║  Operador : OR — cualquiera de las 3 condiciones activa la salida    ║
║                                                                      ║
║  Condiciones de salida:                                              ║
║    S1. RSC Mansfield Activo < -0.5  (pérdida de fuerza relativa)     ║
║    S2. Trailing Stop activado       (precio < mín. 15 cierres)       ║
║    S3. Coppock SP500 bajista        (filtro de mercado)               ║
║                                                                      ║
║  Entrada : CSV con posiciones abiertas (ver formato abajo)           ║
║  Salida  : CSV con el estado de cada posición + motivo de salida     ║
║  Operativa: Revisar en fin de semana mientras haya posiciones        ║
║             abiertas                                                 ║
╚══════════════════════════════════════════════════════════════════════╝

FORMATO DEL CSV DE ENTRADA
──────────────────────────
El archivo debe llamarse  "posiciones.csv"  y estar en la misma carpeta
que este script. Columnas requeridas:

    Ticker   → símbolo de la acción  (ej. AAPL, MSFT, NVDA)
    Sector   → nombre del sector     (ej. Technology, Energy…)
    Precio_Entrada → precio al que se compró (float, usado solo como ref.)
    Fecha_Entrada  → fecha de apertura (YYYY-MM-DD)

Ejemplo de contenido:
    Ticker,Sector,Precio_Entrada,Fecha_Entrada
    AAPL,Technology,175.30,2024-05-17
    MSFT,Technology,415.00,2024-05-17
    XOM,Energy,112.50,2024-05-17
    JPM,Financial Services,198.20,2024-05-17

Puedes copiar el CSV que generó el escáner de entradas y eliminar las
columnas extra — solo se necesitan las cuatro indicadas.

DEPENDENCIAS
────────────
    pip install yfinance pandas numpy

USO
───
    python weinstein_albert_exit_scanner.py
    python weinstein_albert_exit_scanner.py --input mis_posiciones.csv

Este script forma parte de la rutina semanal de seguimiento de la
estrategia: se revisa cuando la semana bursátil ya ha cerrado y existe
al menos una posición abierta.
"""

# ─────────────────────────────────────────────────────────────────────
# IMPORTACIONES
# ─────────────────────────────────────────────────────────────────────

import argparse
import warnings
import sys
from datetime import datetime
from pathlib import Path
import os

import numpy as np
import pandas as pd
import yfinance as yf
from we_utils import wma, rsc_mansfield, coppock_curve

warnings.filterwarnings("ignore")

# Allow a safe dry-run for testing runner scripts without downloading data
if os.getenv("WEINSTEIN_DRY_RUN") == "1":
    print("WEINSTEIN_DRY_RUN=1 detected — dry run, exiting without network calls.")
    sys.exit(0)


# ─────────────────────────────────────────────────────────────────────
# 1. CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────

SP500_INDEX          = "^GSPC"
DOWNLOAD_PERIOD      = "5y"        # historia suficiente para todos los indicadores

# Parámetros de condiciones de salida
RSC_SALIDA_UMBRAL    = -0.5        # S1: RSC Mansfield < este valor → salida
TRAILING_STOP_BARS   = 15          # S2: mínimo de los últimos N cierres semanales
RSC_SMA_PERIOD       = 52          # para el cálculo del RSC Mansfield
COPPOCK_ROC1         = 14
COPPOCK_ROC2         = 11
COPPOCK_WMA_PERIOD   = 10

MIN_BARS             = 70          # mínimo de velas para operar

# Nombre por defecto del CSV de entrada
DEFAULT_INPUT_CSV    = "posiciones.csv"


# ─────────────────────────────────────────────────────────────────────
# 2. DESCARGA DE DATOS
# El cálculo se apoya en cierres semanales, así que la revisión de
# posiciones está pensada para hacerse una vez por semana.
# ─────────────────────────────────────────────────────────────────────

def download_weekly(ticker: str, period: str = DOWNLOAD_PERIOD) -> pd.DataFrame | None:
    """Descarga OHLCV semanal. Retorna None si falla o hay datos insuficientes."""
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

        # Aplanar MultiIndex si yfinance lo devuelve así (versión >= 0.2.x)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        raw = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
        raw.dropna(subset=["Close"], inplace=True)

        return raw if len(raw) >= MIN_BARS else None

    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────
# 3. INDICADORES
# ─────────────────────────────────────────────────────────────────────



# wma and rsc_mansfield moved to we_utils.py


# coppock_curve moved to we_utils.py


# ─────────────────────────────────────────────────────────────────────
# 4. LECTURA DEL CSV DE POSICIONES
# ─────────────────────────────────────────────────────────────────────

def load_positions(csv_path: str) -> pd.DataFrame:
    path = Path(csv_path)
    if not path.exists():
        print(f"\n  ✗ No se encontró el archivo: {csv_path}")
        print(  "    Columnas requeridas: Ticker, Sector, Precio_Entrada, Fecha_Entrada")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]

    required = {"Ticker", "Sector", "Precio_Entrada", "Fecha_Entrada"}   # ← añadida
    missing  = required - set(df.columns)
    if missing:
        print(f"\n  ✗ Faltan columnas en el CSV: {missing}")
        print(  "    Asegúrate de incluir Fecha_Entrada (formato YYYY-MM-DD)")
        sys.exit(1)

    df["Ticker"]        = df["Ticker"].str.strip().str.upper()
    df["Precio_Entrada"] = pd.to_numeric(df["Precio_Entrada"], errors="coerce")
    df["Fecha_Entrada"] = pd.to_datetime(df["Fecha_Entrada"], errors="coerce")
    df = df.dropna(subset=["Ticker", "Precio_Entrada", "Fecha_Entrada"]).reset_index(drop=True)
    return df


# ─────────────────────────────────────────────────────────────────────
# 5. EVALUACIÓN DE CONDICIONES DE SALIDA PARA UN TICKER
# ─────────────────────────────────────────────────────────────────────

def evaluate_exit(
    ticker:        str,
    fecha_entrada: pd.Timestamp,   # ← nuevo parámetro
    sp500_close:   pd.Series,
    coppock_bearish: bool,
) -> dict:
    """
    Evalúa las 3 condiciones de salida para un ticker.
    Retorna un dict con el estado de cada condición y el veredicto final.

    Condiciones (OR — cualquiera activa la salida):
      S1: RSC Mansfield Activo < -0.5
      S2: Precio actual < mínimo de los últimos 15 cierres semanales
      S3: Coppock SP500 bajista (actual ≤ anterior)
    """
    resultado = {
        "Ticker"             : ticker,
        "Precio Actual"      : None,
        "RSC Mansfield"      : None,
        "Trailing Stop Ref"  : None,
        "Barras Abierto"     : None,   # ← nuevo campo informativo
        "S1 RSC < -0.5"      : None,
        "S2 Trailing Stop"   : None,
        "S3 Coppock Bajista" : coppock_bearish,
        "SALIDA"             : False,
        "Motivo"             : [],
        "Error"              : None,
    }

    data = download_weekly(ticker)
    if data is None:
        resultado["Error"] = "Sin datos o histórico insuficiente"
        return resultado

    close: pd.Series = data["Close"].copy()

    # ── S1: RSC Mansfield < -0.5 (sin cambios) ──────────────────────
    try:
        close_a, sp500_a = close.align(sp500_close, join="inner")
        if len(close_a) < RSC_SMA_PERIOD + 5:
            resultado["Error"] = "Histórico insuficiente para RSC"
            return resultado
        rsc_series  = rsc_mansfield(close_a, sp500_a)
        rsc_val     = float(rsc_series.iloc[-1])
        s1_activado = rsc_val < RSC_SALIDA_UMBRAL
        resultado["RSC Mansfield"] = round(rsc_val, 4)
        resultado["S1 RSC < -0.5"] = s1_activado
    except Exception as exc:
        resultado["Error"] = f"Error calculando RSC: {exc}"
        return resultado

    # ── S2: Trailing Stop ────────────────────────────────────────────
    # La condición solo puede evaluarse cuando la posición ya acumula
    # al menos 15 velas semanales desde la fecha de entrada.
    close_desde_entrada = close.loc[close.index >= fecha_entrada]
    barras_abierto = len(close_desde_entrada)
    resultado["Barras Abierto"] = barras_abierto

    precio_actual = float(close_desde_entrada.iloc[-1])
    resultado["Precio Actual"] = round(precio_actual, 2)

    # Se requiere disponer de 15 barras COMPLETAS previas al cierre actual
    # para evaluar correctamente el trailing stop de 15 barras.
    if barras_abierto <= TRAILING_STOP_BARS:
        resultado["S2 Trailing Stop"] = False
        resultado["Trailing Stop Ref"] = None
    else:
        history_before_current = close_desde_entrada.iloc[:-1]
        if len(history_before_current) < TRAILING_STOP_BARS:
            resultado["S2 Trailing Stop"] = False
            resultado["Trailing Stop Ref"] = None
        else:
            trailing_min = float(history_before_current.tail(TRAILING_STOP_BARS).min())
            resultado["Trailing Stop Ref"] = round(trailing_min, 2)
            resultado["S2 Trailing Stop"] = precio_actual < trailing_min

    # ── Veredicto final: OR ──────────────────────────────────────────
    motivos = []
    if resultado["S1 RSC < -0.5"]:
        motivos.append(f"S1: RSC={resultado['RSC Mansfield']:+.3f} < -0.5")
    if resultado["S2 Trailing Stop"]:
        motivos.append(
            f"S2: Precio {resultado['Precio Actual']} < Stop {resultado['Trailing Stop Ref']}"
            f" (tras {barras_abierto} semanas)"
        )
    if resultado["S3 Coppock Bajista"]:
        motivos.append("S3: Coppock SP500 bajista")

    resultado["SALIDA"] = len(motivos) > 0
    resultado["Motivo"] = " | ".join(motivos) if motivos else "—"
    return resultado


# ─────────────────────────────────────────────────────────────────────
# 6. FUNCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────

def run_exit_scanner(csv_path: str = DEFAULT_INPUT_CSV) -> pd.DataFrame:

    print("\n" + "═" * 68)
    print("  WEINSTEIN VERSION ALBERT — ESCÁNER DE CONDICIONES DE SALIDA")
    print(f"  Ejecución : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
    print(f"  Archivo   : {csv_path}")
    print("═" * 68)

    # ── Cargar posiciones
    print("\n[1/3] Cargando posiciones abiertas...")
    posiciones = load_positions(csv_path)
    print(f"  ✓ {len(posiciones)} posiciones encontradas: {list(posiciones['Ticker'])}")

    # ── Descargar S&P 500 y calcular Coppock
    print("\n[2/3] Descargando S&P 500 y calculando Coppock...")
    sp500_data = download_weekly(SP500_INDEX, period="6y")
    if sp500_data is None:
        print("  ✗ ERROR: No se pudo descargar el S&P 500.")
        sys.exit(1)

    sp500_close: pd.Series = sp500_data["Close"].copy()
    copk         = coppock_curve(sp500_close)
    coppock_now  = float(copk.iloc[-1])
    coppock_prev = float(copk.iloc[-2])
    coppock_bearish = coppock_now < coppock_prev
    estado_mkt   = "↓ Bajista" if coppock_bearish else "↑ Alcista"

    print(f"  Coppock actual   : {coppock_now:+.4f}")
    print(f"  Coppock anterior : {coppock_prev:+.4f}")
    print(f"  Estado mercado   : {estado_mkt}")

    if coppock_bearish:
        print("  ⚠️  S3 ACTIVA para TODAS las posiciones (Coppock bajista)")

    # ── Evaluar cada ticker
    print(f"\n[3/3] Evaluando {len(posiciones)} posiciones...")
    print("─" * 68)

    resultados = []

    for _, fila in posiciones.iterrows():
        ticker         = fila["Ticker"]
        sector         = fila.get("Sector", "N/A")
        precio_entrada = fila.get("Precio_Entrada", None)
        fecha_entrada  = fila["Fecha_Entrada"]

        res = evaluate_exit(
            ticker        = ticker,
            fecha_entrada = fecha_entrada,
            sp500_close   = sp500_close,
            coppock_bearish = coppock_bearish,
        )

        res["Sector"]         = sector
        res["Precio Entrada"] = precio_entrada

        # Calcular rentabilidad si tenemos los datos
        if precio_entrada and res["Precio Actual"]:
            rentabilidad = ((res["Precio Actual"] / float(precio_entrada)) - 1) * 100
            res["Rentabilidad %"] = round(rentabilidad, 2)
        else:
            res["Rentabilidad %"] = None

        resultados.append(res)

        # Feedback inmediato
        icono  = "🔴 SALIDA" if res["SALIDA"] else "🟢 Mantener"
        motivo = res["Motivo"] if res["SALIDA"] else ""
        error  = f"  ⚠ {res['Error']}" if res["Error"] else ""
        print(f"  {icono:<14} {ticker:<6} | RSC: {str(res['RSC Mansfield']):<9} | {motivo}{error}")

    # ── Construir DataFrame final
    df = pd.DataFrame(resultados)

    # Ordenar: primero las que requieren salida, luego por rentabilidad
    df["_sort_salida"] = df["SALIDA"].apply(lambda x: 0 if x else 1)
    df.sort_values(["_sort_salida", "Rentabilidad %"], ascending=[True, True], inplace=True)
    df.drop(columns=["_sort_salida"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    # ── Columnas para la salida
    cols_output = [
        "Ticker",
        "Sector",
        "Precio Entrada",
        "Precio Actual",
        "Rentabilidad %",
        "RSC Mansfield",
        "Trailing Stop Ref",
        "S1 RSC < -0.5",
        "S2 Trailing Stop",
        "S3 Coppock Bajista",
        "SALIDA",
        "Motivo",
    ]
    cols_output = [c for c in cols_output if c in df.columns]

    # ── Resumen
    n_salida   = df["SALIDA"].sum()
    n_mantener = len(df) - n_salida

    print("\n" + "═" * 68)
    print(f"  RESUMEN")
    print("─" * 68)
    print(f"  Posiciones analizadas : {len(df)}")
    print(f"  🔴 SALIDA             : {n_salida}")
    print(f"  🟢 Mantener           : {n_mantener}")
    print("─" * 68)
    print(df[cols_output].to_string(index=True))
    print("═" * 68)

    return df


# ─────────────────────────────────────────────────────────────────────
# 7. EXPORTACIÓN
# ─────────────────────────────────────────────────────────────────────

def export_results(df: pd.DataFrame, input_csv: str) -> None:
    if df.empty:
        return
    fecha  = datetime.now().strftime("%Y%m%d_%H%M")
    stem   = Path(input_csv).stem
    nombre = f"{stem}_salidas_{fecha}.csv"
    df.to_csv(nombre, index=False, encoding="utf-8-sig")
    print(f"\n  ✅ Resultados exportados → {nombre}")


# ─────────────────────────────────────────────────────────────────────
# 8. ENTRY POINT
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Weinstein-Albert: escáner de condiciones de salida"
    )
    parser.add_argument(
        "--input", "-i",
        default=DEFAULT_INPUT_CSV,
        help=f"Ruta al CSV de posiciones abiertas (por defecto: {DEFAULT_INPUT_CSV})"
    )
    args = parser.parse_args()

    df_resultado = run_exit_scanner(csv_path=args.input)
    export_results(df_resultado, input_csv=args.input)
