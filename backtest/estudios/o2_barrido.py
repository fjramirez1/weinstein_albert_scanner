"""
O2 (docs/HOJA_DE_RUTA.md): barrido de variantes razonables de la estrategia
SOLO en el tramo de calibración (2017-12-01 → 2022-12-30). El tramo de
validación no se toca aquí: se usa una única vez en O3 con la config elegida.

Cada variante cambia UNA cosa respecto al baseline de producción (salvo las
combinaciones marcadas como "combo"), para poder atribuir el efecto.

Además de las métricas globales se calcula la rentabilidad por año natural
frente a SPY: una variante que solo gana por un año concreto no es robusta.

Ronda 1: un cambio cada vez. Ronda 2: combinaciones de los cambios que
mejoraron la ronda 1 (ver docs/BITACORA.md, 2026-11-03 (11)). Ronda 3:
robustez; cada conjunto de reglas candidato con los rankings reales y con
N_SEMILLAS rankings aleatorios, para saber si el ranking aporta algo frente
al azar o si la diferencia entre variantes es ruido de selección. Ronda 4:
igual que la 3 con F5 sustituida por F5b (mercado no bajista).

Uso (lee la caché de 10 años; ver backtest/download_data.py):
    python -m backtest.estudios.o2_barrido [--ronda 1|2|3|4]

Escribe la tabla en historial/backtests/o2_barrido_calibracion_r<ronda>.csv.
"""
import argparse
import zlib

import pandas as pd

from backtest.conditions import RANKING_CRITERIA
from backtest.portfolio_backtest import prepare_universe, run_portfolio_backtest
from backtest.strategy_config import ConditionToggle, StrategyConfig

INICIO, FIN = "2017-12-01", "2022-12-30"
SALIDA = "historial/backtests/o2_barrido_calibracion_r{ronda}.csv"

OFF = ConditionToggle(enabled=False)
ON = ConditionToggle()


def _p(**params) -> ConditionToggle:
    return ConditionToggle(params=params)


COPPOCK_CLASICO = dict(coppock_roc_long=14, coppock_roc_short=11, coppock_wma=10)

VARIANTES: dict[str, dict] = {
    "baseline": {},
    # Ranking de candidatos
    "rank_rsc_activo": dict(ranking_criterion="rsc_activo"),
    "rank_vpm5": dict(ranking_criterion="vpm5"),
    # S1: umbral de salida por debilidad relativa
    "s1_-0.25": dict(exit_conditions={"S1_rsc_debil": _p(umbral=-0.25)}),
    "s1_-1.0": dict(exit_conditions={"S1_rsc_debil": _p(umbral=-1.0)}),
    "s1_off": dict(exit_conditions={"S1_rsc_debil": OFF}),
    # S2: salida por mercado bajista
    "s2_off": dict(exit_conditions={"S2_mercado_bajista": OFF}),
    # F1: fuerza del sector
    "f1_0.0": dict(entry_conditions={"F1_sector_fuerte": _p(umbral=0.0)}),
    "f1_off": dict(entry_conditions={"F1_sector_fuerte": OFF}),
    # F4: distancia máxima al WMA30
    "f4_5": dict(entry_conditions={"F4_distancia_wma30": _p(max_distancia=5.0)}),
    "f4_12": dict(entry_conditions={"F4_distancia_wma30": _p(max_distancia=12.0)}),
    "f4_off": dict(entry_conditions={"F4_distancia_wma30": OFF}),
    # Reglas del vídeo retiradas (docs/ESTRATEGIA.md §10)
    "f6_on": dict(entry_conditions={"F6_cierre_sobre_wma30": ON}),
    "s3_on": dict(exit_conditions={"S3_trailing_stop": ON}),
    "s3_sin_min_semanas": dict(exit_conditions={"S3_trailing_stop": _p(min_semanas=0)}),
    "video_f6_s3": dict(entry_conditions={"F6_cierre_sobre_wma30": ON},
                        exit_conditions={"S3_trailing_stop": ON}),
    # Parámetros del Coppock (F5/S2): clásico 14+11 frente al actual 12+6
    "coppock_14_11": dict(**COPPOCK_CLASICO),
    "coppock_14_11_s3": dict(**COPPOCK_CLASICO, exit_conditions={"S3_trailing_stop": ON}),
    # Número de posiciones
    "pos_5": dict(max_positions=5),
    "pos_20": dict(max_positions=20),
    # F5: sin filtro de mercado en la entrada
    "f5_off": dict(entry_conditions={"F5_mercado_alcista": OFF}),
    # Combo: Weinstein "etapa 2" (0 < Dist% < 8) + trailing + ranking por RSC
    "combo_f6_s3_rsc": dict(ranking_criterion="rsc_activo",
                            entry_conditions={"F6_cierre_sobre_wma30": ON},
                            exit_conditions={"S3_trailing_stop": ON}),
}


# Ronda 2: combinaciones de lo que mejoró en la ronda 1 (sin F5, sin S2,
# ranking por RSC/VPM5, S3, F4 más laxo), más el Coppock clásico para S2.
SIN_F5 = {"F5_mercado_alcista": OFF}
SIN_F5_F4 = {"F5_mercado_alcista": OFF, "F4_distancia_wma30": OFF}
SIN_F5_F4_12 = {"F5_mercado_alcista": OFF, "F4_distancia_wma30": _p(max_distancia=12.0)}
S3 = {"S3_trailing_stop": ON}
SIN_S2 = {"S2_mercado_bajista": OFF}
SIN_S2_S3 = {"S2_mercado_bajista": OFF, "S3_trailing_stop": ON}

VARIANTES_R2: dict[str, dict] = {
    "baseline": {},
    "f5_off": dict(entry_conditions=SIN_F5),
    "f5_off_s2_off": dict(entry_conditions=SIN_F5, exit_conditions=SIN_S2),
    "f5_off_s3": dict(entry_conditions=SIN_F5, exit_conditions=S3),
    "f5_off_s2_off_s3": dict(entry_conditions=SIN_F5, exit_conditions=SIN_S2_S3),
    "f5_off_rsc": dict(entry_conditions=SIN_F5, ranking_criterion="rsc_activo"),
    "f5_off_vpm5": dict(entry_conditions=SIN_F5, ranking_criterion="vpm5"),
    "f5_off_rsc_s3": dict(entry_conditions=SIN_F5, exit_conditions=S3, ranking_criterion="rsc_activo"),
    "f5_off_s2_off_rsc_s3": dict(entry_conditions=SIN_F5, exit_conditions=SIN_S2_S3,
                                 ranking_criterion="rsc_activo"),
    "f5_off_f4_off": dict(entry_conditions=SIN_F5_F4),
    "f5_off_f4_12_rsc_s3": dict(entry_conditions=SIN_F5_F4_12, exit_conditions=S3,
                                ranking_criterion="rsc_activo"),
    "f5_off_coppock_14_11": dict(entry_conditions=SIN_F5, **COPPOCK_CLASICO),
    "f5_off_coppock_14_11_rsc_s3": dict(entry_conditions=SIN_F5, exit_conditions=S3,
                                        ranking_criterion="rsc_activo", **COPPOCK_CLASICO),
    "f5_off_rsc_s3_pos20": dict(entry_conditions=SIN_F5, exit_conditions=S3,
                                ranking_criterion="rsc_activo", max_positions=20),
    # Manteniendo el filtro de mercado F5
    "rsc_s3": dict(exit_conditions=S3, ranking_criterion="rsc_activo"),
    "rsc_s3_f4_12": dict(entry_conditions={"F4_distancia_wma30": _p(max_distancia=12.0)},
                         exit_conditions=S3, ranking_criterion="rsc_activo"),
    "rsc_s3_s2_off": dict(exit_conditions=SIN_S2_S3, ranking_criterion="rsc_activo"),
}

# Ronda 3: conjuntos de reglas (sin ranking) x rankings reales + aleatorios.
REGLAS_R3: dict[str, dict] = {
    "produccion": {},
    "f5_off": dict(entry_conditions=SIN_F5),
    "f5_off_s2_off": dict(entry_conditions=SIN_F5, exit_conditions=SIN_S2),
    "s3_f4_12": dict(entry_conditions={"F4_distancia_wma30": _p(max_distancia=12.0)}, exit_conditions=S3),
}
REGLAS_R4: dict[str, dict] = {
    "f5b": dict(entry_conditions={"F5_mercado_alcista": OFF, "F5b_mercado_no_bajista": ON}),
    "f5b_s3": dict(entry_conditions={"F5_mercado_alcista": OFF, "F5b_mercado_no_bajista": ON},
                   exit_conditions=S3),
}
RANKINGS_REALES = ("momentum", "rsc_activo", "vpm5")
N_SEMILLAS = 20


def _ranking_aleatorio(semilla: int):
    """Puntuación pseudoaleatoria y reproducible por (semilla, ticker, semana)."""
    def puntuar(ctx, i: int) -> float:
        return float(zlib.crc32(f"{semilla}|{ctx.ticker}|{i}".encode()))
    return puntuar


def _variantes_con_azar(conjuntos: dict[str, dict]) -> dict[str, dict]:
    variantes = {}
    for semilla in range(N_SEMILLAS):
        RANKING_CRITERIA.setdefault(f"aleatorio_{semilla}", _ranking_aleatorio(semilla))
    for reglas, kw in conjuntos.items():
        for ranking in RANKINGS_REALES:
            variantes[f"{reglas}|{ranking}"] = dict(kw, ranking_criterion=ranking)
        for semilla in range(N_SEMILLAS):
            variantes[f"{reglas}|aleatorio_{semilla}"] = dict(kw, ranking_criterion=f"aleatorio_{semilla}")
    return variantes


def _resumen_r3(df: pd.DataFrame) -> pd.DataFrame:
    """Por conjunto de reglas: distribución del azar y percentil de cada ranking real."""
    df = df[df["variante"].str.contains("|", regex=False)].copy()
    df[["reglas", "ranking"]] = df["variante"].str.split("|", expand=True)
    filas = []
    for reglas, g in df.groupby("reglas", sort=False):
        azar = g[g["ranking"].str.startswith("aleatorio_")]
        fila = {
            "reglas": reglas,
            "azar_CAGR_p10": round(azar["CAGR%"].quantile(0.10), 2),
            "azar_CAGR_mediana": round(azar["CAGR%"].median(), 2),
            "azar_CAGR_p90": round(azar["CAGR%"].quantile(0.90), 2),
            "azar_Sharpe_mediana": round(azar["Sharpe"].median(), 2),
            "azar_DD_mediana": round(azar["DD%"].median(), 2),
        }
        for ranking in RANKINGS_REALES:
            real = g[g["ranking"] == ranking].iloc[0]
            fila[f"{ranking}_CAGR"] = real["CAGR%"]
            fila[f"{ranking}_pct"] = int(round((azar["CAGR%"] < real["CAGR%"]).mean() * 100))
        filas.append(fila)
    return pd.DataFrame(filas)


RONDAS = {
    1: lambda: VARIANTES,
    2: lambda: VARIANTES_R2,
    3: lambda: _variantes_con_azar(REGLAS_R3),
    4: lambda: _variantes_con_azar(REGLAS_R4),
}


def _por_anio(serie: pd.Series) -> pd.Series:
    """Rentabilidad % por año natural de una serie semanal (sin años de menos de 40 semanas)."""
    grupos = serie.groupby(serie.index.year)
    fin_anio = grupos.last()
    inicio = fin_anio.shift(1)
    inicio.iloc[0] = serie.iloc[0]
    anual = (fin_anio / inicio - 1.0) * 100.0
    return anual[grupos.size() >= 40]


def ejecutar(variantes: dict[str, dict], inicio: str, fin: str) -> pd.DataFrame:
    """
    Ejecuta cada variante en [inicio, fin] sobre el universo histórico de 10
    años y devuelve una fila de métricas por variante más una fila "SPY".
    """
    sp500, bull, bear, ctx, info = prepare_universe(period="10y", universe="historical")
    print("\nsector desconocido:", len(info.tickers_sector_desconocido))
    print("sin precio:", len(info.tickers_historicos_sin_precio))

    filas = []
    for nombre, kw in variantes.items():
        cfg = StrategyConfig(name=nombre, **kw)
        res = run_portfolio_backtest(cfg, sp500, bull, bear, ctx, universe_info=info,
                                     verbose=False, start=inicio, end=fin)
        m = res.metrics()
        equity = pd.Series([p.valor_cartera for p in res.equity_curve],
                           index=pd.DatetimeIndex([p.fecha for p in res.equity_curve]))
        anual = _por_anio(equity)
        spy = info.benchmark_close.reindex(equity.index, method="ffill")
        anual_spy = _por_anio(spy)
        motivos = pd.Series([t.motivo_salida for t in res.closed_trades]).value_counts().to_dict()
        fila = {
            "variante": nombre,
            "CAGR%": m["cagr_pct"], "exceso_pp": m["exceso_cagr_pct"],
            "DD%": m["max_drawdown_pct"], "Sharpe": m["sharpe_aprox"],
            "ops": m["n_operaciones_cerradas"], "win%": m["win_rate_pct"],
            "PF$": m["profit_factor"], "top5%": m["pct_pnl_top5"],
            "inv%": m["pct_semanas_invertido"], "costes$": m["costes_totales_usd"],
            "anios>SPY": int((anual > anual_spy).sum()),
        }
        for anio, r in anual.items():
            fila[str(anio)] = round(float(r), 1)
        fila["motivos"] = motivos
        filas.append(fila)
        print(f"  {nombre:<22} CAGR {m['cagr_pct']:>6}%  Sharpe {m['sharpe_aprox']:>5}  ops {m['n_operaciones_cerradas']}")

    df = pd.DataFrame(filas)
    spy_fila = {"variante": "SPY", "CAGR%": m["benchmark_cagr_pct"],
                "DD%": m["benchmark_max_drawdown_pct"], "Sharpe": m["benchmark_sharpe_aprox"]}
    for anio, r in anual_spy.items():
        spy_fila[str(anio)] = round(float(r), 1)
    df = pd.concat([df, pd.DataFrame([spy_fila])], ignore_index=True)

    pd.set_option("display.width", 300)
    pd.set_option("display.max_columns", 50)
    print("\n" + df.drop(columns=["motivos"]).to_string(index=False))
    print()
    for f in filas:
        print(f["variante"], f["motivos"])
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--ronda", type=int, choices=sorted(RONDAS), default=1)
    args = parser.parse_args()

    df = ejecutar(RONDAS[args.ronda](), INICIO, FIN)
    df.to_csv(SALIDA.format(ronda=args.ronda), index=False, encoding="utf-8-sig")
    if args.ronda in (3, 4):
        resumen = _resumen_r3(df)
        print("\nRanking real frente a rankings aleatorios (pct = % de semillas que supera):")
        print(resumen.to_string(index=False))
        resumen.to_csv(SALIDA.format(ronda=f"{args.ronda}_resumen"), index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
