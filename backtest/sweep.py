"""
Barrido (sweep) de configuraciones del backtest de cartera.

Permite lanzar varias `StrategyConfig` sobre el MISMO universo ya
preparado (misma descarga/caché, mismos indicadores precalculados) y
compararlas en una tabla, para poder "ir probando variaciones" de forma
eficiente sin repetir el trabajo caro (descarga + precálculo).
"""

from __future__ import annotations

import pandas as pd

from backtest.portfolio_backtest import prepare_universe, run_portfolio_backtest
from backtest.strategy_config import StrategyConfig


def run_sweep(
    configs: list[StrategyConfig],
    period: str = "8y",
    tickers: list[str] | None = None,
    max_tickers: int | None = None,
) -> pd.DataFrame:
    """
    Ejecuta el backtest de cartera para cada config en `configs`, sobre
    el mismo universo preparado una única vez, y devuelve una tabla
    comparativa (una fila por configuración) ordenada por rentabilidad
    total descendente.
    """
    if not configs:
        raise ValueError("run_sweep necesita al menos una StrategyConfig")

    print(f"\n{'═' * 72}\n  SWEEP DE {len(configs)} CONFIGURACIONES\n{'═' * 72}")

    sp500_close, coppock_bullish, coppock_bearish, contexts = prepare_universe(
        period=period, tickers=tickers, max_tickers=max_tickers,
    )

    filas = []
    for i, config in enumerate(configs, start=1):
        print(f"\n[{i}/{len(configs)}] Simulando: {config.describe()}")
        result = run_portfolio_backtest(
            config, sp500_close, coppock_bullish, coppock_bearish, contexts,
        )
        m = result.metrics()
        filas.append({
            "Config": config.name,
            "Rentabilidad %": m["rentabilidad_total_pct"],
            "Capital Final": m["capital_final"],
            "CAGR %": m["cagr_pct"],
            "Max Drawdown %": m["max_drawdown_pct"],
            "Nº Operaciones": m["n_operaciones_cerradas"],
            "Win Rate %": m["win_rate_pct"],
            "Profit Factor": m["profit_factor"],
            "Sharpe aprox.": m["sharpe_aprox"],
            "Ret. Medio Op. %": m["retorno_medio_pct"],
            "% Semanas Invertido": m["pct_semanas_invertido"],
        })

    df = pd.DataFrame(filas).sort_values("Rentabilidad %", ascending=False).reset_index(drop=True)

    print(f"\n{'═' * 72}\n  TABLA COMPARATIVA\n{'═' * 72}")
    print(df.to_string(index=True))
    print("═" * 72)
    print("  ⚠ Universo = S&P 500 ACTUAL (sesgo de supervivencia).")
    print("═" * 72)

    return df
