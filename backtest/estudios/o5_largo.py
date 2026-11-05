"""
O5 (docs/HOJA_DE_RUTA.md): estudio largo 2006-2026 con la membresía externa,
tal como está pre-registrado en docs/BITACORA.md (2026-11-05 (1)).

- W1 = 2006-01-06 → 2016-12-30: no usado antes; incluye 2008.
- W2 = 2017-01-06 → 2026-10-30: ya mirado en O1-O3 (con otra membresía).
- Completo 2006-2026: solo se reporta, con los rankings reales.

Cada conjunto de reglas se ejecuta con los rankings MOM, RSC y VPM5 y con
N_SEMILLAS rankings aleatorios (ver `o2_barrido._variantes_con_azar`).
Benchmarks: SPY (con dividendos), RSP (igual peso) y el azar.

Uso (caché `max` poblada desde 2006; ver CLAUDE.md):
    python -m backtest.estudios.o5_largo

Escribe historial/backtests/o5_largo_<ventana>.csv y o5_largo_<ventana>_resumen.csv.
"""
from __future__ import annotations

import sys

import pandas as pd

from backtest.data_cache import get_cached_weekly
from backtest.estudios.o2_barrido import (
    OFF,
    ON,
    RANKINGS_REALES,
    SIN_F5,
    SIN_S2,
    _p,
    _por_anio,
    _resumen_r3,
    _variantes_con_azar,
)
from backtest.portfolio_backtest import prepare_universe, run_portfolio_backtest
from backtest.portfolio_engine import _cagr_pct, _max_drawdown_pct, _sharpe
from backtest.strategy_config import StrategyConfig

DESDE = "2006-01-01"
VENTANAS = {
    "w1": ("2006-01-06", "2016-12-30"),
    "w2": ("2017-01-06", "2026-10-30"),
}
COMPLETO = ("2006-01-06", "2026-10-30")
SALIDA = "historial/backtests/o5_largo_{nombre}.csv"

COPPOCK_CLASICO = dict(coppock_roc_long=14, coppock_roc_short=11, coppock_wma=10)
COPPOCK_LENTO = dict(coppock_roc_long=61, coppock_roc_short=48, coppock_wma=43)

REGLAS_O5: dict[str, dict] = {
    "produccion": {},
    "coppock_clasico": dict(**COPPOCK_CLASICO),
    "coppock_lento": dict(**COPPOCK_LENTO),
    "sin_mercado": dict(entry_conditions=SIN_F5, exit_conditions=SIN_S2),
    "f5b": dict(entry_conditions={"F5_mercado_alcista": OFF, "F5b_mercado_no_bajista": ON}),
    "sin_f4": dict(entry_conditions={"F4_distancia_wma30": OFF}),
}
CON_FILTRO = ("produccion", "coppock_clasico", "coppock_lento", "f5b")


def _benchmark(serie: pd.Series | None, ini: str, fin: str) -> dict:
    if serie is None:
        return {"CAGR%": None, "DD%": None, "Sharpe": None}
    s = serie[(serie.index >= pd.Timestamp(ini)) & (serie.index <= pd.Timestamp(fin))].dropna()
    return {"CAGR%": round(_cagr_pct(float(s.iloc[0]), float(s.iloc[-1]), s.index), 2),
            "DD%": round(_max_drawdown_pct(s), 2), "Sharpe": round(_sharpe(s), 2)}


def _ejecutar(variantes, ini, fin, datos, benchmarks) -> pd.DataFrame:
    sp500, bull, bear, ctx, info = datos
    filas = []
    for i, (nombre, kw) in enumerate(variantes.items(), 1):
        res = run_portfolio_backtest(StrategyConfig(name=nombre, **kw), sp500, bull, bear, ctx,
                                     universe_info=info, verbose=False, start=ini, end=fin)
        m = res.metrics()
        equity = pd.Series([p.valor_cartera for p in res.equity_curve],
                           index=pd.DatetimeIndex([p.fecha for p in res.equity_curve]))
        fila = {
            "variante": nombre, "CAGR%": m["cagr_pct"], "DD%": m["max_drawdown_pct"],
            "Sharpe": m["sharpe_aprox"], "ops": m["n_operaciones_cerradas"], "win%": m["win_rate_pct"],
            "PF$": m["profit_factor"], "top5%": m["pct_pnl_top5"], "inv%": m["pct_semanas_invertido"],
            "costes$": m["costes_totales_usd"],
        }
        for anio, r in _por_anio(equity).items():
            fila[str(anio)] = round(float(r), 1)
        filas.append(fila)
        if i % 10 == 0:
            print(f"    … {i}/{len(variantes)}", flush=True)
    df = pd.DataFrame(filas)
    for nombre, serie in benchmarks.items():
        fila = {"variante": nombre, **_benchmark(serie, ini, fin)}
        s = serie[(serie.index >= pd.Timestamp(ini)) & (serie.index <= pd.Timestamp(fin))]
        for anio, r in _por_anio(s).items():
            fila[str(anio)] = round(float(r), 1)
        df = pd.concat([df, pd.DataFrame([fila])], ignore_index=True)
    return df


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    datos = prepare_universe(period="max", universe="historical", desde=DESDE)
    info = datos[4]
    print("\nsector desconocido:", len(info.tickers_sector_desconocido))
    print("sin precio:", len(info.tickers_historicos_sin_precio))
    rsp = get_cached_weekly("RSP", "max", False, True)
    benchmarks = {"SPY": info.benchmark_close,
                  "RSP": None if rsp is None else rsp["Close"].squeeze()}

    variantes = _variantes_con_azar(REGLAS_O5)
    resumenes = {}
    for nombre, (ini, fin) in VENTANAS.items():
        print(f"\n[{nombre}] {ini} → {fin}: {len(variantes)} ejecuciones")
        df = _ejecutar(variantes, ini, fin, datos, benchmarks)
        df.to_csv(SALIDA.format(nombre=nombre), index=False, encoding="utf-8-sig")
        resumen = _resumen_r3(df)
        resumen.to_csv(SALIDA.format(nombre=f"{nombre}_resumen"), index=False, encoding="utf-8-sig")
        resumenes[nombre] = (resumen, df)
        pd.set_option("display.width", 250)
        print(resumen.to_string(index=False))
        print(df[df["variante"].isin(["SPY", "RSP"])][["variante", "CAGR%", "DD%", "Sharpe"]].to_string(index=False))

    reales = {f"{r}|{k}": dict(kw, ranking_criterion=k) for r, kw in REGLAS_O5.items() for k in RANKINGS_REALES}
    print(f"\n[completo] {COMPLETO[0]} → {COMPLETO[1]}: {len(reales)} ejecuciones")
    completo = _ejecutar(reales, *COMPLETO, datos, benchmarks)
    completo.to_csv(SALIDA.format(nombre="completo"), index=False, encoding="utf-8-sig")

    # ── Hipótesis y regla de decisión pre-registradas ──
    r1 = resumenes["w1"][0].set_index("reglas")
    r2 = resumenes["w2"][0].set_index("reglas")
    bench = {w: resumenes[w][1].set_index("variante") for w in resumenes}
    mejor_filtro = max(CON_FILTRO, key=lambda r: r1.loc[r, "azar_Sharpe_mediana"])
    h1 = r1.loc[mejor_filtro, "azar_Sharpe_mediana"] >= r1.loc["sin_mercado", "azar_Sharpe_mediana"]
    print(f"\nH1 (W1: algún filtro con Sharpe mediano ≥ sin_mercado): {'SÍ' if h1 else 'NO'} "
          f"({mejor_filtro} {r1.loc[mejor_filtro, 'azar_Sharpe_mediana']} frente a "
          f"{r1.loc['sin_mercado', 'azar_Sharpe_mediana']})")
    for k in RANKINGS_REALES:
        print(f"H2 {k}: percentil > 50 en {int((r1[f'{k}_pct'] > 50).sum())}/{len(r1)} conjuntos (W1), "
              f"{int((r2[f'{k}_pct'] > 50).sum())}/{len(r2)} (W2)")
    rsp1, rsp2 = bench["w1"].loc["RSP", "CAGR%"], bench["w2"].loc["RSP", "CAGR%"]
    h3 = [r for r in r1.index if r1.loc[r, "azar_CAGR_mediana"] > rsp1 and r2.loc[r, "azar_CAGR_mediana"] > rsp2]
    print(f"H3 (mediana con azar > RSP en W1 y W2): {h3 or 'ninguno'} (RSP {rsp1} % / {rsp2} %)")
    print("\nRegla de decisión:")
    for r in r1.index:
        if r == "produccion":
            continue
        mejora = all(
            rr.loc[r, "azar_CAGR_mediana"] > rr.loc["produccion", "azar_CAGR_mediana"]
            and rr.loc[r, "azar_Sharpe_mediana"] > rr.loc["produccion", "azar_Sharpe_mediana"]
            for rr in (r1, r2)
        )
        print(f"  reglas {r:<16} {'CANDIDATO' if mejora else 'no'}")
    for k in RANKINGS_REALES:
        ok = (r1[f"{k}_pct"] > 50).sum() >= 5 and (r2[f"{k}_pct"] > 50).sum() >= 5
        print(f"  ranking {k:<15} {'CANDIDATO' if ok else 'no'}")


if __name__ == "__main__":
    main()
