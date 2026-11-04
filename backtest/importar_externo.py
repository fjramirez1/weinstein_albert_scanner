"""
Importa a la caché del backtest precios de deslistados que no sirven gratis
ni yfinance ni Tiingo, desde un dataset externo descargado a mano.

Fuente: release `snapshot-2026-11` de https://github.com/Johnbrick123/sp500-data
(`prices.parquet`, diario, con una columna `source` por fila). El repo no
tiene licencia y mezcla fuentes, así que **solo se usan filas de fuentes
reutilizables y con volumen** (`FUENTES_PERMITIDAS`): el volcado WIKI de
Quandl (dominio público), Tiingo y Yahoo. Las filas de CRSP se descartan:
no tienen volumen (VPM5 lo necesita) ni licencia de redistribución. Ver
`docs/INVESTIGACION.md` y la bitácora del 2026-11-04.

Las series diarias se ajustan por splits y dividendos con `adj_close / close`
(igual que `auto_adjust=True` en yfinance y los `adj*` de Tiingo) y se pasan
a velas semanales con la etiqueta del viernes (`normalize_weekly_bars`).

`IMPORTACIONES` dice qué etiqueta del dataset va a qué ticker de nuestro
calendario de membresía. Las etiquetas `TICKER-AAAAMM` son las del dataset
(convención de Norgate: mes de salida del índice).

Modo automático (`--auto --desde AAAA-MM-DD`): con la membresía externa
(`HISTORICAL_MEMBERSHIP_SOURCE = "externa"`), los nombres del calendario
salen de las mismas etiquetas que este dataset de precios. Recorre el
universo del periodo y, para cada ticker que ya no está hoy en el índice y
que no tiene datos en la caché, o cuyos datos no se solapan con su
membresía (otra empresa con el mismo ticker), importa la etiqueta
correspondiente si tiene filas de fuentes permitidas.

Uso (el parquet debe estar en `backtest/.cache/externo/`, que no se versiona):
    python -m backtest.importar_externo                           # IMPORTACIONES (period max)
    python -m backtest.importar_externo --auto --desde 2006-01-01 # universo del periodo
    python -m backtest.importar_externo --validar                 # compara con series que ya tenemos
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import data_cache
from weinstein.config import MIN_BARS
from weinstein.data import normalize_weekly_bars

PARQUET = data_cache.CACHE_DIR / "externo" / "johnbrick_sp500_prices.parquet"
MANIFIESTO = data_cache.CACHE_DIR / "externo" / "importados.json"
FUENTES_PERMITIDAS = ("wiki", "tiingo", "yahoo")

# ticker de nuestro calendario -> etiqueta del dataset
IMPORTACIONES: dict[str, str] = {
    # Deslistados sin datos gratis en yfinance/Tiingo (tramo 2011-2016)
    "APOL": "APOL-201702",   # Apollo Education Group
    "BBBY": "BBBY-202305",   # Bed Bath & Beyond (la antigua; el BBBY actual es otra empresa)
    "BIG":  "BIG",           # Big Lots
    "BRCM": "BRCM-201601",   # Broadcom Corp (antes de Avago)
    "BXLT": "BXLT-201606",   # Baxalta
    "CAM":  "CAM-201604",    # Cameron International
    "CCE":  "CCE",           # Coca-Cola Enterprises
    "CPGX": "CPGX-201606",   # Columbia Pipeline Group
    "CSRA": "CSRA-201804",   # CSRA Inc
    "CVC":  "CVC-201606",    # Cablevision Systems
    "DF":   "DF",            # Dean Foods
    "ENDP": "ENDP",          # Endo International
    "ESV":  "ESV",           # Ensco
    "FRC":  "FRC",           # First Republic Bank
    "FTR":  "FTR",           # Frontier Communications (antigua)
    "HAR":  "HAR-201703",    # Harman International
    "HOT":  "HOT-201609",    # Starwood Hotels
    "IGT":  "IGT-201504",    # International Game Technology
    "JCP":  "JCP",           # J. C. Penney
    "LLTC": "LLTC-201703",   # Linear Technology
    "LXK":  "LXK-201611",    # Lexmark
    "MNK":  "MNK",           # Mallinckrodt
    "PCL":  "PCL-201602",    # Plum Creek Timber
    "PCP":  "PCP-201601",    # Precision Castparts
    # Tickers que hoy usa otra empresa: yfinance devolvía la nueva
    "ADT":  "ADT-201604",    # ADT Corp (2012-2016)
    "ALTR": "ALTR-201512",   # Altera
    "BEAM": "BEAM-201404",   # Beam Inc
    "DNB":  "DNB",           # Dun & Bradstreet antigua (privatizada en 2019)
    "PLL":  "PLL-201508",    # Pall Corp
    "SE":   "SE-201702",     # Spectra Energy
    "WIN":  "WIN",           # Windstream
    # Empresas antiguas de tickers actuales (HISTORICAL_TICKER_PERIOD_ALIASES)
    "DOW-201708":  "DOW-201708",   # Dow Chemical
    "DELL-201310": "DELL-201310",  # Dell Inc
}


def cargar(parquet: Path = PARQUET) -> pd.DataFrame:
    if not parquet.exists():
        raise SystemExit(f"Falta {parquet}: descarga prices.parquet del release snapshot-2026-11 de "
                         "https://github.com/Johnbrick123/sp500-data y guárdalo ahí.")
    return pd.read_parquet(parquet)


def serie_semanal(precios: pd.DataFrame, etiqueta: str) -> tuple[pd.DataFrame | None, dict]:
    """OHLCV semanal ajustado de una etiqueta, solo con filas de fuentes permitidas y con volumen."""
    d = precios[(precios["ticker"] == etiqueta) & precios["source"].isin(FUENTES_PERMITIDAS)]
    d = d[d["volume"].notna() & d["close"].gt(0)].copy()
    info = {"etiqueta": etiqueta, "fuentes": d["source"].value_counts().to_dict(), "filas_diarias": len(d)}
    if d.empty:
        return None, info
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
    factor = (d["adj_close"] / d["close"]).where(d["adj_close"].notna(), 1.0)
    diario = pd.DataFrame({
        "Open": d["open"] * factor, "High": d["high"] * factor, "Low": d["low"] * factor,
        "Close": d["close"] * factor, "Volume": d["volume"],
    })
    semanal = diario.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna(subset=["Close"])
    semanal = normalize_weekly_bars(semanal)
    info.update({"desde": str(semanal.index[0].date()), "hasta": str(semanal.index[-1].date()),
                 "velas": len(semanal)})
    if len(semanal) < MIN_BARS:
        return None, info
    return semanal, info


def _leer_manifiesto() -> dict:
    try:
        return json.loads(MANIFIESTO.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _guardar_manifiesto(manifiesto: dict) -> None:
    MANIFIESTO.parent.mkdir(parents=True, exist_ok=True)
    MANIFIESTO.write_text(json.dumps(manifiesto, indent=2, sort_keys=True), encoding="utf-8")


def candidatos_auto(desde: str, hasta: str | None = None, period: str = "max") -> dict[str, str]:
    """
    {nombre del calendario: etiqueta del dataset} de los tickers no actuales
    del universo del periodo sin datos utilizables en la caché.
    """
    from backtest import sp500_historical as sh
    from weinstein.data import load_sp500_tickers

    intervalos = pd.read_parquet(sh.external_intervals_path())
    nombres = sh.external_names(list(intervalos["ticker"].astype(str)))
    etiqueta_de = {}
    for etiqueta, nombre in nombres.items():
        etiqueta_de.setdefault(nombre, etiqueta)
    sp = data_cache.read_cached("^GSPC", period)
    fechas = sp.index[sp.index >= pd.Timestamp(desde)]
    if hasta is not None:
        fechas = fechas[fechas <= pd.Timestamp(hasta)]
    calendario = sh.build_membership_calendar_cached(list(fechas))
    actuales = set(load_sp500_tickers()["Symbol"])
    semanas: dict[str, list[pd.Timestamp]] = {}
    for fecha in fechas:
        for t in calendario.get(fecha, ()):
            semanas.setdefault(t, []).append(fecha)
    out = {}
    for nombre, fs in semanas.items():
        if nombre in actuales or nombre not in etiqueta_de:
            continue
        datos = data_cache.read_cached(nombre, period)
        if datos is not None and not datos.empty and datos.index[0] <= fs[-1] and datos.index[-1] >= fs[0]:
            continue  # ya hay datos que se solapan con su membresía
        out[nombre] = etiqueta_de[nombre]
    return out


def importar(period: str = "max", importaciones: dict[str, str] | None = None) -> dict:
    precios = cargar()
    manifiesto = _leer_manifiesto()
    importados = {}
    for ticker, etiqueta in (importaciones if importaciones is not None else IMPORTACIONES).items():
        semanal, info = serie_semanal(precios, etiqueta)
        if semanal is None or data_cache.save_cached(ticker, period, semanal) is None:
            print(f"  ✗ {ticker:<12} {etiqueta}: sin datos utilizables {info}")
            continue
        data_cache._fail_marker_path(ticker, period).unlink(missing_ok=True)
        manifiesto[ticker] = info
        importados[ticker] = info
        print(f"  ✓ {ticker:<12} {etiqueta:<12} {info['desde']} → {info['hasta']} ({info['velas']} velas) {info['fuentes']}")
    _guardar_manifiesto(manifiesto)
    total = len(importaciones if importaciones is not None else IMPORTACIONES)
    print(f"\n  {len(importados)}/{total} importados. Manifiesto: {MANIFIESTO}")
    return importados


def validar(period: str = "max", etiquetas: dict[str, str] | None = None) -> pd.DataFrame:
    """
    Compara series del dataset con las que ya tenemos de yfinance/Tiingo en
    las semanas comunes: correlación de rentabilidades semanales y mediana
    del cociente de cierres (≈ 1 si la escala de ajuste coincide).
    """
    etiquetas = etiquetas or {
        "CA": "CA-201811", "EMC": "EMC-201609", "STI": "STI-201912", "MON": "MON-201806",
        "AAPL": "AAPL", "XOM": "XOM", "JPM": "JPM", "KO": "KO",
    }
    precios = cargar()
    filas = []
    for ticker, etiqueta in etiquetas.items():
        nuestro = data_cache.read_cached(ticker, period)
        externo, info = serie_semanal(precios, etiqueta)
        if nuestro is None or externo is None:
            filas.append({"ticker": ticker, "etiqueta": etiqueta, "semanas_comunes": 0})
            continue
        comunes = nuestro.index.intersection(externo.index)
        a, b = nuestro.loc[comunes, "Close"], externo.loc[comunes, "Close"]
        ra, rb = a.pct_change().dropna(), b.pct_change().dropna()
        filas.append({
            "ticker": ticker, "etiqueta": etiqueta, "fuentes": info["fuentes"], "semanas_comunes": len(comunes),
            "corr_rent": round(float(np.corrcoef(ra, rb)[0, 1]), 4) if len(ra) > 2 else None,
            "mediana_cociente": round(float((b / a).median()), 4),
            "p5_cociente": round(float((b / a).quantile(0.05)), 4),
            "p95_cociente": round(float((b / a).quantile(0.95)), 4),
        })
    return pd.DataFrame(filas)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Importa deslistados del dataset externo a la caché.")
    parser.add_argument("--period", default="max")
    parser.add_argument("--validar", action="store_true", help="Solo compara con series que ya tenemos.")
    parser.add_argument("--auto", action="store_true", help="Importa lo que falte en el universo del periodo.")
    parser.add_argument("--desde", default=None, metavar="AAAA-MM-DD")
    parser.add_argument("--hasta", default=None, metavar="AAAA-MM-DD")
    args = parser.parse_args()
    if args.auto:
        if not args.desde:
            parser.error("--auto necesita --desde")
        candidatos = candidatos_auto(args.desde, args.hasta, args.period)
        print(f"  {len(candidatos)} tickers sin datos utilizables con etiqueta en el dataset")
        importar(args.period, candidatos)
    elif args.validar:
        pd.set_option("display.width", 200)
        print(validar(args.period).to_string(index=False))
    else:
        importar(args.period)


if __name__ == "__main__":
    main()
