"""
Escáner de condiciones de SALIDA — estrategia Weinstein-Albert.

Operador OR: cualquiera de las condiciones activa la señal de salida.

Condiciones
-----------
S1: RSC Mansfield del activo < −0.5  (pérdida de fuerza relativa)
S2: Coppock SP500 no alcista          (filtro de mercado invertido)

Optimizaciones respecto a la versión original
---------------------------------------------
1. **Short-circuit en S2**: si el Coppock no es alcista, S2 ya activa
   SALIDA=True para todas las posiciones. Se sigue descargando para
   calcular el RSC actual y la rentabilidad, pero el veredicto ya es
   conocido.
2. **Descarga paralela**: las N posiciones se descargan concurrentemente
   con ThreadPoolExecutor (normalmente son pocas, pero el patrón escala).
3. **Sin semáforo adicional**: el límite de concurrencia ya lo impone
   `max_workers` del propio ThreadPoolExecutor (cada tarea hace una única
   descarga), así que un `Semaphore` extra sería redundante.

Nota sobre el histórico
------------------------
Los CSVs generados por versiones anteriores de este escáner (antes de
`historial/salidas/posiciones_salidas_20260619_1342.csv`) usan la columna
``S3 Coppock Bajista`` en lugar de ``S2 Coppock No Alcista``. Esa condición
fue renombrada/simplificada; el código actual ya no distingue una "S3"
independiente. Esos CSVs antiguos se conservan tal cual por motivos de
historial y no reflejan el esquema de columnas actual.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

from weinstein.config import (
    COPPOCK_RECENT_LOOKBACK,
    DOWNLOAD_PERIOD_EXIT,
    EXIT_REASON_NONE,
    EXIT_REASON_S1_LABEL,
    EXIT_REASON_S2_LABEL,
    RSC_EXIT_THRESHOLD,
    RSC_SMA_PERIOD,
    SP500_INDEX,
)
from weinstein.data import download_weekly, load_positions
from weinstein.indicators import coppock_curve, rsc_mansfield, sp500_alcista

MAX_WORKERS = 10  # las posiciones suelen ser pocas; 10 es más que suficiente


# ── Evaluación de una posición (thread-safe) ─────────────────────────

def _evaluate_exit(
    ticker:           str,
    fecha_entrada:    pd.Timestamp,
    sp500_close:      pd.Series,
    coppock_not_bull: bool,
) -> dict:
    """
    Evalúa las condiciones de salida para un ticker individual.

    Short-circuit: si S2 ya es True, el veredicto SALIDA=True es
    inmediato. Aun así se descarga el ticker para obtener precio
    actual y RSC (información útil para el trader).

    Returns
    -------
    Dict con el estado de cada condición y el veredicto final. El campo
    "Motivo" es siempre un string (nunca una lista intermedia), tanto en
    los caminos de retorno anticipado como en el final.
    """
    result: dict = {
        "Ticker"               : ticker,
        "Precio Actual"        : None,
        "RSC Mansfield"        : None,
        "S1 RSC < -0.5"        : None,
        "S2 Coppock No Alcista": coppock_not_bull,
        "SALIDA"               : False,
        "Motivo"               : EXIT_REASON_NONE,
        "Error"                : None,
    }

    data = download_weekly(ticker, period=DOWNLOAD_PERIOD_EXIT)

    if data is None:
        result["Error"]  = "Sin datos o histórico insuficiente"
        result["SALIDA"] = coppock_not_bull   # S2 podría bastar
        result["Motivo"] = EXIT_REASON_S2_LABEL if coppock_not_bull else EXIT_REASON_NONE
        return result

    close = data["Close"].copy()

    # S1: RSC Mansfield activo < umbral
    try:
        close_a, sp500_a = close.align(sp500_close, join="inner")
        if len(close_a) < RSC_SMA_PERIOD + 5:
            result["Error"] = "Histórico insuficiente para RSC"
            # S2 aún puede activar SALIDA
        else:
            rsc_val = float(rsc_mansfield(close_a, sp500_a).iloc[-1])
            result["RSC Mansfield"] = round(rsc_val, 4)
            result["S1 RSC < -0.5"] = rsc_val < RSC_EXIT_THRESHOLD
    except Exception as exc:
        result["Error"] = f"Error calculando RSC: {exc}"

    # Precio actual desde la fecha de entrada
    close_desde_entrada = close.loc[close.index >= fecha_entrada]
    if not close_desde_entrada.empty:
        result["Precio Actual"] = round(float(close_desde_entrada.iloc[-1]), 2)
    elif not result["Error"]:
        result["Error"] = "Sin cierres desde la fecha de entrada"

    # Veredicto final (OR). Se construye en una lista local de trabajo y
    # se convierte a string una única vez al final, evitando el tipo
    # inconsistente (list -> str) que tenía la versión anterior.
    motivos: list[str] = []
    if result.get("S1 RSC < -0.5"):
        motivos.append(f"{EXIT_REASON_S1_LABEL}={result['RSC Mansfield']:+.3f} < {RSC_EXIT_THRESHOLD}")
    if coppock_not_bull:
        motivos.append(EXIT_REASON_S2_LABEL)

    result["SALIDA"] = bool(motivos)
    result["Motivo"] = " | ".join(motivos) if motivos else EXIT_REASON_NONE
    return result


# ── Worker para el pool ───────────────────────────────────────────────

def _worker_exit(
    fila:             pd.Series,
    sp500_close:      pd.Series,
    coppock_not_bull: bool,
) -> dict:
    """Evalúa una posición e incorpora los campos de rentabilidad."""
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

    # Bug fix: "if precio_entrada and ..." trataba 0 como falsy y omitía
    # la rentabilidad sin avisar cuando Precio_Entrada == 0 (dato corrupto).
    # Se comprueba explícitamente que no sea None/NaN en vez de su verdad
    # booleana, y se registra el caso en Error para que no pase inadvertido.
    precio_entrada_valido = precio_entrada is not None and not pd.isna(precio_entrada)

    if precio_entrada_valido and precio_entrada == 0:
        res["Rentabilidad %"] = None
        aviso = "Precio_Entrada = 0: rentabilidad no calculable"
        res["Error"] = f"{res['Error']} | {aviso}" if res["Error"] else aviso
    elif precio_entrada_valido and res["Precio Actual"] is not None:
        res["Rentabilidad %"] = round(
            ((res["Precio Actual"] / float(precio_entrada)) - 1) * 100, 2
        )
    else:
        res["Rentabilidad %"] = None

    return res


# ── Función principal ─────────────────────────────────────────────────

def run_exit_scanner(csv_path: str) -> pd.DataFrame:
    """
    Ejecuta el escáner de salida sobre las posiciones del CSV indicado.

    Retorna un DataFrame con el estado de cada posición, ordenado por
    SALIDA (primero las señales activas) y Rentabilidad %.
    """
    print("\n" + "═" * 68)
    print("  WEINSTEIN VERSION ALBERT — ESCÁNER DE CONDICIONES DE SALIDA")
    print(f"  Ejecución : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
    print(f"  Archivo   : {csv_path}")
    print("═" * 68)

    print("\n[1/3] Cargando posiciones abiertas...")
    posiciones = load_positions(csv_path)
    print(f"  ✓ {len(posiciones)} posiciones: {list(posiciones['Ticker'])}")

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

    n = len(posiciones)
    workers = min(MAX_WORKERS, n) if n else 1
    print(f"\n[3/3] Evaluando {n} posiciones (paralelo, {workers} hilos)...")
    print("─" * 68)

    resultados: list[dict] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_worker_exit, fila, sp500_close, coppock_not_bull): fila["Ticker"]
            for _, fila in posiciones.iterrows()
        }
        for fut in as_completed(futures):
            res = fut.result()
            resultados.append(res)

            ticker = res["Ticker"]
            icono  = "🔴 SALIDA" if res["SALIDA"] else "🟢 Mantener"
            motivo = res["Motivo"] if res["SALIDA"] else ""
            error  = f"  ⚠ {res['Error']}" if res["Error"] else ""
            print(f"  {icono:<14} {ticker:<6} | RSC: {str(res['RSC Mansfield']):<9} | {motivo}{error}")

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
