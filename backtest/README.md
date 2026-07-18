# Backtest de cartera Weinstein-Albert

Simula la estrategia como una **cartera real**: capital inicial, un número
máximo de posiciones simultáneas, y reglas de entrada/salida configurables.

> Documentación técnica completa (modelo de cartera, condiciones
> configurables, universo histórico, caché, CLI, sweep, `launcher.py`,
> métricas): **[BACKTEST.md](BACKTEST.md)**.

## Instalación

```bash
pip install -r requirements.txt
pip install pyarrow --break-system-packages   # necesario para la caché en disco
```

## Uso rápido

```bash
# Ejecución con la estrategia actual (F1-F5 / S1-S2 tal cual), $10.000, máx. 10 posiciones
python backtest/run_portfolio_backtest.py

# Cambiar capital, nº de posiciones y periodo
python backtest/run_portfolio_backtest.py --capital 20000 --max-positions 8 --period 6y

# Usar el universo HISTÓRICO reconstruido (mitiga el sesgo de supervivencia)
python backtest/run_portfolio_backtest.py --universe historical

# Comparar varias configuraciones de ejemplo automáticamente (sweep)
python backtest/run_portfolio_backtest.py --sweep-demo

# Exportar el detalle de operaciones a CSV
python backtest/run_portfolio_backtest.py --export historial/backtests/salida.csv
```

También disponible como subcomando del CLI unificado:

```bash
python -m weinstein portfolio-backtest --period 8y --max-positions 10
```

Para ejecutarlo en bucle (cada hora, universo histórico), ver
[`launcher.py`](../launcher.py) — detallado en
[BACKTEST.md § 8](BACKTEST.md#8-ejecución-periódica-launcherpy).

## ⚠️ Limitación conocida: sesgo de supervivencia

El universo por defecto es el S&P 500 **actual**, no una reconstrucción
histórica de qué empresas formaban parte del índice en cada semana del
pasado. `--universe historical` mitiga esto (no lo elimina). Ver
[BACKTEST.md § 4](BACKTEST.md#4-universo-constituyentes-actuales-vs-histórico-reconstruido)
para el detalle completo.
