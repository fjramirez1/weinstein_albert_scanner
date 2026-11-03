"""
O1 (docs/HOJA_DE_RUTA.md): baseline con las reglas de producción y el motor
corregido, por tramos (calibración / validación / completo), frente a SPY y
frente al modelo antiguo (ejecución al cierre de la señal, sin costes).

Uso (lee la caché de 10 años; ver backtest/download_data.py):
    python -m backtest.estudios.o1_baseline [salida.csv]

Exporta las operaciones del modelo corregido a historial/backtests/o1_baseline_<tramo>.csv.
"""
import sys

import pandas as pd

from backtest.portfolio_backtest import prepare_universe, run_portfolio_backtest  # noqa: E402
from backtest.strategy_config import StrategyConfig  # noqa: E402

TRAMOS = {
    "calibracion": ("2017-12-01", "2022-12-30"),
    "validacion": ("2023-01-06", "2026-10-30"),
    "completo": ("2017-12-01", "2026-10-30"),
}
MODELOS = {
    "corregido": dict(execution="next_open", cost_pct=0.10),
    "antiguo": dict(execution="close", cost_pct=0.0),
}

sp500, bull, bear, ctx, info = prepare_universe(period="10y", universe="historical")
print("\nsector desconocido:", len(info.tickers_sector_desconocido), info.tickers_sector_desconocido)
print("sin precio:", len(info.tickers_historicos_sin_precio))

filas = []
for modelo, kw in MODELOS.items():
    for tramo, (ini, fin) in TRAMOS.items():
        cfg = StrategyConfig(name=f"baseline_{modelo}_{tramo}", **kw)
        res = run_portfolio_backtest(cfg, sp500, bull, bear, ctx, universe_info=info,
                                     verbose=False, start=ini, end=fin)
        m = res.metrics()
        motivos = pd.Series([t.motivo_salida for t in res.closed_trades]).value_counts().to_dict()
        filas.append({
            "modelo": modelo, "tramo": tramo,
            "rent%": m["rentabilidad_total_pct"], "CAGR%": m["cagr_pct"],
            "DD%": m["max_drawdown_pct"], "Sharpe": m["sharpe_aprox"],
            "ops": m["n_operaciones_cerradas"], "win%": m["win_rate_pct"],
            "PF$": m["profit_factor"], "top5%": m["pct_pnl_top5"],
            "inv%": m["pct_semanas_invertido"], "costes$": m["costes_totales_usd"],
            "SPY_CAGR%": m["benchmark_cagr_pct"], "SPY_DD%": m["benchmark_max_drawdown_pct"],
            "SPY_Sharpe": m["benchmark_sharpe_aprox"], "exceso_pp": m["exceso_cagr_pct"],
            "motivos": motivos,
        })
        if modelo == "corregido":
            out = f"historial/backtests/o1_baseline_{tramo}.csv"
            res.to_trades_dataframe().to_csv(out, index=False, encoding="utf-8-sig")

df = pd.DataFrame(filas)
pd.set_option("display.width", 250)
print("\n" + df.drop(columns=["motivos"]).to_string(index=False))
print()
for f in filas:
    print(f["modelo"], f["tramo"], f["motivos"])
if len(sys.argv) > 1:
    df.to_csv(sys.argv[1], index=False)
