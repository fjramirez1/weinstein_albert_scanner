"""
Escáner de condiciones de SALIDA — estrategia Weinstein-Albert.

Operador OR: cualquiera de las condiciones activa la señal de salida.

Condiciones
-----------
S1: RSC Mansfield del activo < −0.5  (pérdida de fuerza relativa)
S2: Coppock SP500 no alcista          (filtro de mercado invertido)
"""

from __future__ import annotations

import sys
from datetime import datetime

import pandas as pd

from weinstein.config import (
    COPPOCK_RECENT_LOOKBACK,
    DOWNLOAD_PERIOD_EXIT,
    RSC_EXIT_THRESHOLD,
    RSC_SMA_PERIOD,
    SP500_INDEX,
)
from weinstein.data import download_weekly, load_positions
from weinstein.indicators import coppock_curve, rsc_mansfield, sp500_alcista


# ─────────────────────────────────────────────────────────────────────
# Evaluación de un ticker
# ─────────────────────────────────────────────────────────────────────

def _evaluate_exit(
    ticker:           str,
    fecha_entrada:    pd.Timestamp,
    sp500_close:      pd.Series,
    coppock_not_bull: bool,
) -> dict:
    """
    Evalúa las condiciones de salida para un ticker individual.

    Retorna un dict con el estado de cada condición y el veredicto final.
    """
    result: dict = {
        "Ticker"               : ticker,
        "Precio Actual"        : None,
        "RSC Mansfield"        : None,
        "S1 RSC < -0.5"        : None,
        "S2 Coppock No Alcista": coppock_not_bull,
        "SALIDA"               : False,
        "Motivo"               : [],
        "Error"                : None,
    }

    data = download_weekly(ticker, period=DOWNLOAD_PERIOD_EXIT)
    if data is None:
        result["Error"] = "Sin datos o histórico insuficiente"
        return result

    close = data["Close"].copy()

    # ── S1: RSC Mansfield < umbral ───────────────────────────────────
    try:
        close_a, sp500_a = close.align(sp500_close, join="inner")
        if len(close_a) < RSC_SMA_PERIOD + 5:
            result["Error"] = "Histórico insuficiente para RSC"
            return result

        rsc_val  = float(rsc_mansfield(close_a, sp500_a).iloc[-1])
        s1_activo = rsc_val < RSC_EXIT_THRESHOLD

        result["RSC Mansfield"] = round(rsc_val, 4)
        result["S1 RSC < -0.5"] = s1_activo
    except Exception as exc:
        result["Error"] = f"Error calculando RSC: {exc}"
        return result

    # Precio actual desde la fecha de entrada
    close_desde_entrada = close.loc[close.index >= fecha_entrada]
    if close_desde_entrada.empty:
        result["Error"] = "Sin cierres desde la fecha de entrada"
        return result

    result["Precio Actual"] = round(float(close_desde_entrada.iloc[-1]), 2)

    # ── Veredicto final (OR) ─────────────────────────────────────────
    motivos: list[str] = []
    if result["S1 RSC < -0.5"]:
        motivos.append(f"S1: RSC={result['RSC Mansfield']:+.3f} < {RSC_EXIT_THRESHOLD}")
    if result["S2 Coppock No Alcista"]:
        motivos.append("S2: Coppock SP500 no alcista")

    result["SALIDA"] = bool(motivos)
    result["Motivo"] = " | ".join(motivos) if motivos else "—"
    return result


# ─────────────────────────────────────────────────────────────────────
# Función principal
# ─────────────────────────────────────────────────────────────────────

def run_exit_scanner(csv_path: str) -> pd.DataFrame:
    """
    Ejecuta el escáner de salida sobre las posiciones del CSV indicado.

    Retorna
    -------
    pd.DataFrame con el estado de cada posición, ordenado por
    SALIDA (primero las señales activas) y Rentabilidad %.
    """
    print("\n" + "═" * 68)
    print("  WEINSTEIN VERSION ALBERT — ESCÁNER DE CONDICIONES DE SALIDA")
    print(f"  Ejecución : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
    print(f"  Archivo   : {csv_path}")
    print("═" * 68)

    # PASO 1 — Posiciones
    print("\n[1/3] Cargando posiciones abiertas...")
    posiciones = load_positions(csv_path)
    print(f"  ✓ {len(posiciones)} posiciones: {list(posiciones['Ticker'])}")

    # PASO 2 — S&P 500 y Coppock
    print("\n[2/3] Descargando S&P 500 y calculando Coppock...")
    sp500_data = download_weekly(SP500_INDEX, period="6y")
    if sp500_data is None:
        print("  ✗ ERROR: No se pudo descargar el S&P 500.")
        sys.exit(1)

    sp500_close = sp500_data["Close"].copy()
    copk = coppock_curve(sp500_close)
    coppock_bullish, estado_mkt = sp500_alcista(copk, recent_lookback=COPPOCK_RECENT_LOOKBACK)
    coppock_not_bull = not coppock_bullish

    print(f"  Coppock actual   : {float(copk.iloc[-1]):+.4f}")
    print(f"  Coppock anterior : {float(copk.iloc[-2]):+.4f}")
    print(f"  Estado mercado   : {estado_mkt}")

    if coppock_not_bull:
        print("  ⚠️  S2 ACTIVA para TODAS las posiciones (Coppock no alcista)")

    # PASO 3 — Evaluar posiciones
    print(f"\n[3/3] Evaluando {len(posiciones)} posiciones...")
    print("─" * 68)

    resultados: list[dict] = []

    for _, fila in posiciones.iterrows():
        ticker         = fila["Ticker"]
        sector         = fila.get("Sector", "N/A")
        precio_entrada = fila.get("Precio_Entrada")
        fecha_entrada  = fila["Fecha_Entrada"]

        res = _evaluate_exit(
            ticker           = ticker,
            fecha_entrada    = fecha_entrada,
            sp500_close      = sp500_close,
            coppock_not_bull = coppock_not_bull,
        )
        res["Sector"]         = sector
        res["Precio Entrada"] = precio_entrada

        if precio_entrada and res["Precio Actual"]:
            res["Rentabilidad %"] = round(
                ((res["Precio Actual"] / float(precio_entrada)) - 1) * 100, 2
            )
        else:
            res["Rentabilidad %"] = None

        resultados.append(res)

        icono  = "🔴 SALIDA" if res["SALIDA"] else "🟢 Mantener"
        motivo = res["Motivo"] if res["SALIDA"] else ""
        error  = f"  ⚠ {res['Error']}" if res["Error"] else ""
        print(f"  {icono:<14} {ticker:<6} | RSC: {str(res['RSC Mansfield']):<9} | {motivo}{error}")

    # ── DataFrame y orden ────────────────────────────────────────────
    df = pd.DataFrame(resultados)
    df["_sort"] = df["SALIDA"].apply(lambda x: 0 if x else 1)
    df.sort_values(["_sort", "Rentabilidad %"], ascending=[True, True], inplace=True)
    df.drop(columns=["_sort"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    cols_output = [
        c for c in [
            "Ticker", "Sector", "Precio Entrada", "Precio Actual",
            "Rentabilidad %", "RSC Mansfield", "S1 RSC < -0.5",
            "S2 Coppock No Alcista", "SALIDA", "Motivo",
        ] if c in df.columns
    ]

    n_salida   = int(df["SALIDA"].sum())
    n_mantener = len(df) - n_salida

    print("\n" + "═" * 68)
    print("  RESUMEN")
    print("─" * 68)
    print(f"  Posiciones analizadas : {len(df)}")
    print(f"  🔴 SALIDA             : {n_salida}")
    print(f"  🟢 Mantener           : {n_mantener}")
    print("─" * 68)
    print(df[cols_output].to_string(index=True))
    print("═" * 68)

    return df