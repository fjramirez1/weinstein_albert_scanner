# Backtest de cartera Weinstein-Albert

Simula la estrategia como una **cartera real**: capital inicial, un número
máximo de posiciones simultáneas, y reglas de entrada/salida configurables
— pensado para ir probando variaciones y comparar resultados, no solo para
ejecutar la config actual una vez.

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

# Desactivar una condición
python backtest/run_portfolio_backtest.py --disable F1_sector_fuerte

# Cambiar un umbral sin tocar código
python backtest/run_portfolio_backtest.py --s1-umbral -1.0 --f4-max-distancia 12

# Cambiar el criterio de desempate (ranking) para elegir candidatos
python backtest/run_portfolio_backtest.py --ranking rsc_activo

# Comparar varias configuraciones de ejemplo automáticamente (sweep)
python backtest/run_portfolio_backtest.py --sweep-demo

# Exportar el detalle de operaciones a CSV
python backtest/run_portfolio_backtest.py --export historial/backtests/salida.csv

# Pruebas rápidas con pocos tickers (no descarga los ~500 del S&P 500)
python backtest/run_portfolio_backtest.py --max-tickers 50
```

También disponible como subcomando del CLI unificado:

```bash
python -m weinstein portfolio-backtest --period 8y --max-positions 10
```

## Caché de datos

La primera ejecución descarga datos de yfinance para todos los tickers
del universo (puede tardar varios minutos). Esos datos se guardan en
`backtest/.cache/` (parquet), así que **ejecuciones posteriores con el
mismo periodo son casi instantáneas en la parte de descarga**, incluso
probando configuraciones de estrategia completamente distintas — la
caché es independiente de qué condiciones actives o desactives.

```bash
# Vaciar caché (por ejemplo, para forzar datos más recientes)
python backtest/run_portfolio_backtest.py --clear-cache
```

## Modelo de cartera (reglas exactas de la simulación)

- **Capital inicial**: configurable, por defecto $10.000.
- **Máx. posiciones simultáneas**: configurable, por defecto 10.
- **Orden semanal**: cada semana se evalúan primero las SALIDAS
  (condiciones S1/S2, combinadas con OR) de las posiciones abiertas, y
  luego las ENTRADAS (condiciones F1-F5, combinadas con AND) para llenar
  los huecos que queden libres — **incluidos los que se acaban de liberar
  esa misma semana**. Una salida y una entrada pueden ocurrir en la misma
  semana.
- **Desempate**: si hay más candidatos que huecos libres, se ordenan por
  el criterio de ranking configurado (por defecto, Momentum/MOM) y entran
  los mejores hasta llenar los huecos.
- **Tamaño de posición**: `valor_de_cartera_actual / max_positions`. El
  "valor de cartera" usado para este cálculo es efectivo disponible +
  coste de las posiciones que siguen abiertas — **no fluctúa con el
  precio de mercado no realizado** de esas posiciones, solo cambia
  cuando una posición se cierra (ganancia o pérdida realizada). Nunca se
  invierte más que el efectivo disponible en ese momento.
- **Sin fricción**: sin comisiones ni slippage, precio de cierre exacto.
- **Sin apalancamiento ni posiciones cortas.**

## Condiciones configurables

Definidas en `backtest/conditions.py`, activadas/parametrizadas desde
`backtest/strategy_config.py::StrategyConfig`:

| Condición | Tipo | Descripción | Parámetro |
|---|---|---|---|
| `F1_sector_fuerte` | Entrada | RSC Mansfield del sector ≥ umbral | `umbral` (default 0.10) |
| `F2_volumen_positivo` | Entrada | VPM5 > umbral | `umbral` (default 0.0) |
| `F3_rsc_activo_positivo` | Entrada | RSC Mansfield del activo > umbral | `umbral` (default 0.0) |
| `F4_distancia_wma30` | Entrada | Distancia % a WMA30 < máximo | `max_distancia` (default 8.0) |
| `F5_mercado_alcista` | Entrada | Coppock SP500 alcista | (sin parámetros propios) |
| `S1_rsc_debil` | Salida | RSC Mansfield del activo < umbral | `umbral` (default -0.5) |
| `S2_mercado_bajista` | Salida | Coppock SP500 bajista | (sin parámetros propios) |

Las condiciones de entrada se combinan con **AND**; las de salida con
**OR** (basta una para cerrar la posición).

### Añadir una condición nueva

1. Escribir una función en `backtest/conditions.py` con la firma
   `func(ctx: TickerContext, **params) -> pd.Series[bool]`.
2. Registrarla en `ENTRY_CONDITIONS` o `EXIT_CONDITIONS` con un
   `ConditionSpec` (nombre, label, función, parámetros por defecto).
3. Ya queda disponible para activar/desactivar/parametrizar desde
   cualquier `StrategyConfig`, sin tocar el motor de simulación.

### Criterios de desempate disponibles

`RANKING_CRITERIA` en `backtest/conditions.py`: `momentum` (por defecto,
el MOM de la estrategia original), `rsc_activo`, `vpm5`. Añadir uno
nuevo sigue el mismo patrón: función `(ctx, i) -> float` registrada en
el dict.

## Uso programático (Python)

```python
from backtest.portfolio_backtest import prepare_universe, run_portfolio_backtest, print_report
from backtest.strategy_config import StrategyConfig, ConditionToggle

# Preparar el universo UNA vez (descarga/caché + precálculo de indicadores)
sp500_close, coppock_bullish, coppock_bearish, contexts = prepare_universe(period="8y")

# Probar varias configuraciones sobre los MISMOS datos, sin repetir descargas
config_a = StrategyConfig(name="baseline")
config_b = StrategyConfig(
    name="sin_F1_S1_mas_laxo",
    entry_conditions={"F1_sector_fuerte": ConditionToggle(enabled=False)},
    exit_conditions={"S1_rsc_debil": ConditionToggle(params={"umbral": -1.0})},
    max_positions=8,
)

for cfg in (config_a, config_b):
    result = run_portfolio_backtest(cfg, sp500_close, coppock_bullish, coppock_bearish, contexts)
    print_report(result)
```

O usar `backtest/sweep.py::run_sweep([...])` directamente para obtener la
tabla comparativa sin escribir el bucle a mano.

## ⚠️ Limitación conocida: sesgo de supervivencia

El universo de tickers es el **S&P 500 actual** (constituyentes de hoy),
no una reconstrucción histórica de qué empresas formaban parte del
índice en cada semana del pasado. Esto significa que empresas que
quebraron, fueron adquiridas, o salieron del índice durante el periodo
simulado **no aparecen**, sesgando el universo hacia compañías que "han
ido bien" (sobrevivieron hasta hoy).

Mitigación aplicada: se recomienda no alargar demasiado el periodo de
backtest (`--period`, por defecto `8y`) — cuanto más corto el periodo,
menos empresas relevantes han sido excluidas o han quebrado en ese
tramo, así que el sesgo pesa menos. El aviso se imprime también al
final de cada ejecución.

Este es un problema conocido y aceptado deliberadamente por ahora (ver
discusión de diseño). La vía para reducirlo de forma más rigurosa sería
reconstruir el universo histórico real (altas/bajas del índice por
fecha), con la limitación adicional de que muchos tickers deslistados
hace tiempo ya no tienen datos disponibles en yfinance. Queda como
mejora futura, no implementada todavía.
