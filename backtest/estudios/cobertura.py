"""
Cobertura de datos del universo histórico, año a año (Fase 4b de
docs/HOJA_DE_RUTA.md: ampliar el backtest hacia atrás por tramos).

Para cada semana y cada ticker que ese día pertenecía al S&P 500 mira, solo
en la caché (sin red salvo la tabla de constituyentes actuales):

- precio: si hay vela de ese ticker esa semana;
- sector: si su sector GICS es conocido (actual o `HISTORICAL_DELISTED_SECTORS`);
- evaluable: precio, sector y ETF sectorial (o su sustituto) con datos esa semana.

Un tramo se da por resuelto cuando la cobertura evaluable de sus años es
alta (objetivo orientativo: >= 95 % de las semanas-miembro).

Además lista los tickers problemáticos:
- sin_datos: miembro del periodo sin ninguna vela en la caché;
- sospechoso: la primera vela es posterior a su última semana como miembro,
  o la última anterior a la primera; probablemente es otra empresa que
  reutilizó el ticker (sus precios no sirven);
- parcial: le faltan velas en más del 10 % de sus semanas como miembro.

Uso:
    python -m backtest.estudios.cobertura --desde 2011-01-01 [--period max] [--csv salida.csv]
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from backtest.data_cache import read_cached
from backtest.sp500_historical import build_membership_calendar_cached
from weinstein.config import SECTOR_ETF_PROXIES, SECTOR_TO_ETF, SP500_INDEX, resolve_historical_sector
from weinstein.data import load_sp500_tickers


def _indices_cache(tickers, period: str) -> dict[str, pd.DatetimeIndex]:
    out = {}
    for t in tickers:
        df = read_cached(t, period)
        if df is not None and not df.empty:
            out[t] = df.index
    return out


def analizar(desde: str, period: str = "max", hasta: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (tabla por año, tabla de tickers problemáticos)."""
    sp500 = read_cached(SP500_INDEX, period)
    if sp500 is None:
        raise SystemExit(f"Falta {SP500_INDEX} en la caché para period={period}: ejecuta antes backtest.download_data")
    fechas = sp500.index[sp500.index >= pd.Timestamp(desde)]
    if hasta is not None:
        fechas = fechas[fechas <= pd.Timestamp(hasta)]
    calendario = build_membership_calendar_cached(list(fechas))

    actuales = load_sp500_tickers()
    sector_actual = dict(zip(actuales["Symbol"], actuales["Sector"]))
    union = sorted(set().union(*calendario.values()))
    sectores = {t: resolve_historical_sector(t, sector_actual) for t in union}
    velas = _indices_cache(union, period)

    etfs = _indices_cache(set(SECTOR_TO_ETF.values()) | set(SECTOR_ETF_PROXIES.values()), period)
    inicio_etf = {}
    for sector, etf in SECTOR_TO_ETF.items():
        candidatos = [etfs[e][0] for e in (etf, SECTOR_ETF_PROXIES.get(etf)) if e in etfs]
        inicio_etf[sector] = min(candidatos) if candidatos else None

    filas_anio: dict[int, dict[str, int]] = {}
    semanas_miembro: dict[str, list[pd.Timestamp]] = {t: [] for t in union}
    for fecha in fechas:
        anio = filas_anio.setdefault(fecha.year, {"miembros": 0, "precio": 0, "sector": 0, "evaluable": 0})
        for t in calendario.get(fecha, ()):
            semanas_miembro[t].append(fecha)
            con_precio = t in velas and fecha in velas[t]
            sector = sectores[t]
            con_sector = sector != "Unknown"
            ini = inicio_etf.get(sector)
            anio["miembros"] += 1
            anio["precio"] += con_precio
            anio["sector"] += con_sector
            anio["evaluable"] += con_precio and con_sector and ini is not None and fecha >= ini

    por_anio = pd.DataFrame.from_dict(filas_anio, orient="index")
    por_anio.index.name = "anio"
    for col in ("precio", "sector", "evaluable"):
        por_anio[f"%{col}"] = (por_anio[col] / por_anio["miembros"] * 100).round(1)
    por_anio["miembros_medios"] = (por_anio["miembros"] / pd.Series(fechas.year).value_counts().sort_index()).round(0)

    problemas = []
    for t, semanas in semanas_miembro.items():
        if not semanas:
            continue
        primera, ultima = semanas[0], semanas[-1]
        idx = velas.get(t)
        if idx is None:
            tipo, faltan = "sin_datos", len(semanas)
        elif idx[0] > ultima or idx[-1] < primera:
            tipo, faltan = "sospechoso", len(semanas)
        else:
            faltan = sum(1 for f in semanas if f not in idx)
            if faltan <= 0.10 * len(semanas):
                continue
            tipo = "parcial"
        problemas.append({
            "ticker": t, "tipo": tipo, "actual": t in sector_actual, "sector": sectores[t],
            "miembro_desde": primera.date(), "miembro_hasta": ultima.date(),
            "semanas_miembro": len(semanas), "semanas_sin_vela": faltan,
            "datos_desde": None if idx is None else idx[0].date(),
            "datos_hasta": None if idx is None else idx[-1].date(),
        })
    problemas_df = pd.DataFrame(problemas)
    if not problemas_df.empty:
        problemas_df = problemas_df.sort_values(["tipo", "semanas_sin_vela"], ascending=[True, False])
    return por_anio, problemas_df


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Cobertura de datos del universo histórico por año.")
    parser.add_argument("--desde", required=True, metavar="AAAA-MM-DD")
    parser.add_argument("--hasta", default=None, metavar="AAAA-MM-DD")
    parser.add_argument("--period", default="max")
    parser.add_argument("--csv", default=None, help="Guarda aquí la lista de tickers problemáticos.")
    args = parser.parse_args()

    por_anio, problemas = analizar(args.desde, args.period, args.hasta)
    pd.set_option("display.width", 200)
    print("\nCobertura por año (semanas-miembro):")
    print(por_anio.to_string())
    if problemas.empty:
        print("\nSin tickers problemáticos.")
    else:
        print(f"\nTickers problemáticos: {problemas['tipo'].value_counts().to_dict()}")
        print(problemas.to_string(index=False))
        if args.csv:
            problemas.to_csv(args.csv, index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
