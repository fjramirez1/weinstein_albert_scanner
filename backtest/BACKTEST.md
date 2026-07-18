# Backtest de cartera Weinstein-Albert (detallado)

Este documento amplía `backtest/README.md` con el detalle técnico completo del
subsistema de backtest: modelo de cartera, condiciones configurables, universo
actual vs. histórico, caché de datos, CLI y ejecución en bucle. Sigue el mismo
espíritu que [`docs/ESTRATEGIA.md`](../docs/ESTRATEGIA.md) para la estrategia
en producción — documentación ampliada, sin tocar la lógica del código.

> Si solo quieres lanzar el backtest ya, ve directo a
> [`backtest/README.md`](README.md) (quickstart). Este documento es para
> entender el modelo completo, ajustar parámetros con criterio, o extender el
> sistema (nuevas condiciones, nuevos criterios de ranking, etc.).

## Índice

1. [Por qué existe un backtest de CARTERA aparte del backtest por-ticker](#1-por-qué-existe-un-backtest-de-cartera-aparte-del-backtest-por-ticker)
2. [Modelo de cartera (reglas exactas de la simulación)](#2-modelo-de-cartera-reglas-exactas-de-la-simulación)
3. [Condiciones configurables (F1-F5 / S1-S2)](#3-condiciones-configurables-f1-f5--s1-s2)
4. [Universo: constituyentes actuales vs. histórico reconstruido](#4-universo-constituyentes-actuales-vs-histórico-reconstruido)
5. [Caché de datos y caché de fallos](#5-caché-de-datos-y-caché-de-fallos)
6. [CLI y uso programático](#6-cli-y-uso-programático)
7. [Sweep de configuraciones](#7-sweep-de-configuraciones)
8. [Ejecución periódica (`launcher.py`)](#8-ejecución-periódica-launcherpy)
9. [Métricas reportadas](#9-métricas-reportadas)
10. [Referencias de implementación](#10-referencias-de-implementación)

---

## 1. Por qué existe un backtest de CARTERA aparte del backtest por-ticker

El proyecto tiene **dos** backtests con propósitos distintos, no uno solo:

| | `backtest/strategy_backtest.py` (`python -m weinstein backtest`) | `backtest/portfolio_backtest.py` (`python -m weinstein portfolio-backtest`) |
|---|---|---|
| Unidad de simulación | Cada ticker, **aislado e independiente** | Una única **cartera compartida** |
| Capital | No modela capital ni tamaño de posición | Capital inicial configurable, reparto entre posiciones |
| Nº posiciones simultáneas | Sin límite (cada ticker es su propio universo) | `max_positions` configurable |
| Condiciones F1-F5/S1-S2 | Fijas, tal cual producción | Activables/parametrizables por `StrategyConfig` |
| Pregunta que responde | "¿Producen operaciones rentables las condiciones F1-F5/S1-S2 en sí mismas?" | "¿Qué resultado habría tenido operar esta estrategia de verdad, con este capital y estas reglas?" |

Si solo quieres validar que un filtro individual (p.ej. F4) tiene sentido,
`strategy_backtest.py` es más rápido y sencillo. Para evaluar la estrategia
completa como si fuera una cuenta real, usa `portfolio_backtest.py` — el
resto de este documento se centra en este segundo.

Existe además un tercer script, más acotado: `backtest/backtest_lookback.py`,
que solo evalúa la sensibilidad de `COPPOCK_RECENT_LOOKBACK` (parámetro de
F5) — ver su propio docstring, no se detalla aquí.

## 2. Modelo de cartera (reglas exactas de la simulación)

Acordado explícitamente como especificación de negocio; implementado en
`backtest/portfolio_backtest.py::run_portfolio_backtest`.

- **Capital inicial**: configurable, por defecto $10.000 (`--capital`).
- **Máximo de posiciones simultáneas**: configurable, por defecto 10
  (`--max-positions`).
- **Orden semanal** (por cada fecha de calendario del S&P 500):
  1. **Salidas primero**: se evalúan las condiciones de salida (S1-S2, OR)
     de las posiciones abiertas esa semana. Las que cumplen cualquier
     condición activa se cierran al precio de cierre, liberando efectivo y
     un hueco.
  2. **Entradas después, con los huecos YA liberados**: se evalúan las
     condiciones de entrada (F1-F5, AND) sobre todo el universo. Los
     candidatos que las cumplen se ordenan por el criterio de ranking
     configurado (de mayor a menor) y se abren posiciones nuevas hasta
     llenar los huecos libres — **incluidos los liberados ese mismo paso**.
     Es decir: una salida y una entrada **sí** pueden ocurrir en la misma
     semana.
  3. **Registro de la curva de equity**: valor de cartera a precio de
     mercado (efectivo + valor de las posiciones abiertas al precio de esa
     semana).
- **Tamaño de cada posición nueva**:
  `capital_a_invertir = valor_cartera_referencia / max_positions`, acotado
  al efectivo disponible (`min(capital_objetivo, capital_disponible)`).
  - `valor_cartera_referencia` es efectivo + **coste histórico** (no valor a
    mercado) de las posiciones que siguen abiertas. **Solo cambia cuando se
    cierra una posición** (P&L realizado se suma), nunca por la fluctuación
    de precio no realizada de posiciones que siguen abiertas. Esto evita que
    una posición ganadora/perdedora "infle" o "desinfle" el tamaño de la
    siguiente entrada por simple movimiento de precio no realizado.
  - Nunca se invierte más que el efectivo disponible en ese instante.
- **Sin fricción**: sin comisiones ni slippage; precio de cierre exacto.
- **Sin apalancamiento ni posiciones cortas.**

Implementación de referencia: `backtest/portfolio_engine.py` (estructuras
`ClosedTrade`, `OpenPosition`, `EquityPoint`, `PortfolioBacktestResult`) y
`backtest/portfolio_backtest.py::run_portfolio_backtest` (el bucle semanal).

## 3. Condiciones configurables (F1-F5 / S1-S2)

Definidas en `backtest/conditions.py`, activadas/parametrizadas desde
`backtest/strategy_config.py::StrategyConfig`. Cada condición es una función
pura, precalculada **una vez por ticker sobre todo el histórico**
(vectorizado con pandas) — no se recalcula semana a semana dentro del bucle
de simulación, lo que hace viable simular ~500 tickers en tiempo razonable.

| Condición | Tipo | Descripción | Parámetro por defecto |
|---|---|---|---|
| `F1_sector_fuerte` | Entrada | RSC Mansfield del sector ≥ umbral | `umbral=0.10` |
| `F2_volumen_positivo` | Entrada | VPM5 > umbral | `umbral=0.0` |
| `F3_rsc_activo_positivo` | Entrada | RSC Mansfield del activo > umbral | `umbral=0.0` |
| `F4_distancia_wma30` | Entrada | Distancia % a WMA30 < máximo (sin cota inferior) | `max_distancia=8.0` |
| `F5_mercado_alcista` | Entrada | Coppock SP500 alcista (`sp500_alcista()`) | sin parámetros propios |
| `S1_rsc_debil` | Salida | RSC Mansfield del activo < umbral | `umbral=-0.5` |
| `S2_mercado_bajista` | Salida | Coppock SP500 bajista (`sp500_bajista()`) | sin parámetros propios |

Las condiciones de entrada se combinan con **AND**; las de salida con **OR**
(basta una para cerrar la posición). Ver `docs/ESTRATEGIA.md` sección 4 para
el detalle conceptual de F5/S2 y por qué no son complementarias.

### Precálculo sin look-ahead de F5/S2

`backtest/conditions.py::precompute_market_series` calcula `Sp500alcista` y
`Sp500bajista` semana a semana sobre **todo** el histórico del S&P 500, sin
mirar al futuro: el valor en la semana `i` depende únicamente de
`coppock.iloc[:i+1]`. Se calcula una sola vez (no por ticker, porque es la
misma serie de mercado para todos) y se reindexa al calendario de cada
ticker. Ver `tests/test_conditions.py::TestPrecomputeMarketSeries` para la
verificación explícita de la propiedad "sin look-ahead".

### Añadir una condición nueva

1. Escribe una función en `backtest/conditions.py` con la firma
   `func(ctx: TickerContext, **params) -> pd.Series[bool]`. Debe ser
   *null-safe*: si no hay datos suficientes, devuelve `False` en vez de
   lanzar excepción.
2. Regístrala en `ENTRY_CONDITIONS` o `EXIT_CONDITIONS` con un
   `ConditionSpec` (nombre, label, función, parámetros por defecto).
3. Ya queda disponible para activar/desactivar/parametrizar desde cualquier
   `StrategyConfig`, sin tocar el motor de simulación (`portfolio_engine.py`).

### Criterios de ranking (desempate)

`RANKING_CRITERIA` en `backtest/conditions.py`: `momentum` (por defecto, el
MOM de la estrategia original), `rsc_activo`, `vpm5`. Firma:
`func(ctx: TickerContext, i: int) -> float`. Un valor NaN se traduce a
`-inf` para que ese candidato quede siempre al final del ranking sin
excluirlo por error.

## 4. Universo: constituyentes actuales vs. histórico reconstruido

Controlado por `--universe {current,historical}` (por defecto `current`).

### `current` (por defecto)

El universo de tickers candidatos es el S&P 500 de **HOY**, aplicado a todo
el periodo simulado. Introduce **sesgo de supervivencia**: empresas
excluidas del índice durante el periodo (quiebra, adquisición, degradación
de capitalización) nunca aparecen como candidatas, aunque en su momento
cumplieran los filtros de entrada.

### `historical`

Reconstruye, semana a semana, qué tickers pertenecían realmente al S&P 500
en cada fecha pasada, usando la tabla de cambios de Wikipedia
(`backtest/sp500_historical.py`). Solo permite **abrir** posiciones nuevas
en tickers que estaban en el índice esa semana; una posición ya abierta se
sigue gestionando con normalidad aunque el ticker salga del índice mientras
tanto (el filtro de membresía no fuerza salidas).

**El sesgo se mitiga, no se elimina**: muchos tickers excluidos hace años
(sobre todo antes de ~2015-2018) ya no tienen datos de precio en yfinance.
Esos tickers se cuentan y reportan explícitamente
(`UniverseInfo.tickers_historicos_sin_precio`), nunca se descartan en
silencio.

Algoritmo de reconstrucción (`backtest/sp500_historical.py`): partiendo de
los constituyentes de HOY, se deshacen los cambios de la tabla de Wikipedia
en orden cronológico inverso (de más reciente a más antiguo) hasta llegar a
la fecha objetivo. `build_membership_calendar` hace esto en una única pasada
para muchas fechas a la vez, en vez de recalcular desde cero por cada fecha.

**Recomendación**: no alargar demasiado `--period` en ninguno de los dos
modos — cuanto más corto el periodo, menos empresas relevantes han sido
excluidas o han quebrado en ese tramo, y menos pesa el sesgo. El aviso se
imprime también al final de cada ejecución (`print_report`).

## 5. Caché de datos y caché de fallos

Implementada en `backtest/data_cache.py`. Motivación: la parte lenta de cada
ejecución no es la simulación (CPU-bound, rápida), es la **descarga por red**
de ~500 tickers vía yfinance. `launcher.py` está pensado para ejecutarse en
bucle cada hora, así que repetir esa descarga sería insostenible.

- **Caché de datos** (`.parquet` por `ticker+periodo`, en `backtest/.cache/`):
  se descarga una única vez; ejecuciones posteriores con la misma ventana
  temporal reutilizan el fichero sin tocar la red. Sin invalidación
  automática por fecha (los datos de una semana ya cerrada no cambian);
  usa `--clear-cache` o borra la carpeta manualmente para refrescar.
- **Caché de FALLOS** (marcador `.nodata`): solo se cachea el fallo de
  tickers que **hoy ya no pertenecen** al S&P 500 actual (su histórico es
  finito y no puede "crecer" con el tiempo). Para un ticker que sí pertenece
  al índice actual, el fallo **nunca** se cachea — se reintenta siempre,
  porque puede ser transitorio (alta reciente con histórico aún
  insuficiente).
  - **Caso límite cubierto**: un ticker fuera del índice hoy (con fallo ya
    cacheado) que en el futuro **vuelve** a formar parte del S&P 500 — misma
    empresa o símbolo reutilizado por otra (p.ej. el símbolo `Q`). En cuanto
    `load_sp500_tickers()` lo detecta de nuevo como constituyente actual, el
    marcador antiguo se ignora y se borra automáticamente.

```bash
python backtest/run_portfolio_backtest.py --clear-cache
```

### Fallback Tiingo (tickers delistados)

`weinstein/data.py::download_weekly` intenta primero yfinance; si falla
(incluyendo histórico insuficiente), recurre a un único intento contra la
API de Tiingo (`download_weekly_tiingo`), pensado sobre todo para tickers
que Yahoo Finance ya no sirve por deslistado completo (quiebra, fusión,
adquisición, exclusión de bolsa). Requiere `TIINGO_API_KEY` en el entorno
(`.env`); si no está definida, el fallback se desactiva con un único aviso.
Ver `tests/test_data_tiingo.py` para el comportamiento cubierto (alias de
tickers renombrados, códigos HTTP 401/404/429, etc.).

## 6. CLI y uso programático

### Script independiente

```bash
# Estrategia actual tal cual (F1-F5/S1-S2), $10.000, máx. 10 posiciones
python backtest/run_portfolio_backtest.py

python backtest/run_portfolio_backtest.py --capital 20000 --max-positions 8 --period 6y
python backtest/run_portfolio_backtest.py --disable F1_sector_fuerte
python backtest/run_portfolio_backtest.py --s1-umbral -1.0 --f4-max-distancia 12
python backtest/run_portfolio_backtest.py --ranking rsc_activo
python backtest/run_portfolio_backtest.py --universe historical
python backtest/run_portfolio_backtest.py --sweep-demo
python backtest/run_portfolio_backtest.py --export historial/backtests/salida.csv
python backtest/run_portfolio_backtest.py --max-tickers 50   # pruebas rápidas
python backtest/run_portfolio_backtest.py --clear-cache
```

### Como subcomando del CLI unificado

```bash
python -m weinstein portfolio-backtest --period 8y --max-positions 10
python -m weinstein portfolio-backtest --universe historical
python -m weinstein portfolio-backtest --sweep-demo
```

Todos los flags de `run_portfolio_backtest.py` están disponibles también
como flags de `portfolio-backtest` (ver `weinstein/__main__.py`).

### Uso programático (Python)

```python
from backtest.portfolio_backtest import prepare_universe, run_portfolio_backtest, print_report
from backtest.strategy_config import StrategyConfig, ConditionToggle

# Preparar el universo UNA vez (descarga/caché + precálculo de indicadores)
sp500_close, coppock_bullish, coppock_bearish, contexts, info = prepare_universe(period="8y")

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

## 7. Sweep de configuraciones

`backtest/sweep.py::run_sweep(configs, ...)` ejecuta varias `StrategyConfig`
sobre el **mismo** universo ya preparado (misma descarga/caché, mismos
indicadores precalculados) y devuelve una tabla comparativa ordenada por
rentabilidad total descendente. Evita repetir el trabajo caro (descarga +
precálculo) al comparar variaciones.

```bash
python backtest/run_portfolio_backtest.py --sweep-demo
```

`--sweep-demo` compara un set fijo de configuraciones de ejemplo
(`backtest/run_portfolio_backtest.py::_demo_sweep_configs`): baseline, sin
F1, S1 más laxo, ranking por RSC activo, máx. 5 posiciones. Para comparar
configuraciones propias, usa `run_sweep` directamente (ver ejemplo en
sección 6) en vez de escribir el bucle a mano.

## 8. Ejecución periódica (`launcher.py`)

`launcher.py` (raíz del proyecto) ejecuta el backtest de cartera en bucle,
una vez por hora, con universo histórico y exportando el detalle de
operaciones:

```bash
python launcher.py
```

Equivale a lanzar repetidamente:

```bash
python -m weinstein portfolio-backtest --universe historical \
    --export historial/backtests/detalle_operaciones.csv
```

con una espera de 3660 segundos (1h 1min) entre ejecuciones. Gracias a la
caché de datos (sección 5), solo la primera ejecución del día es lenta por
descarga; las siguientes reutilizan los datos ya cacheados salvo que haya
datos nuevos de mercado que descargar (nuevas velas semanales) o tickers
sin caché de fallo aún resuelto.

El CSV exportado (`historial/backtests/detalle_operaciones.csv`) usa las
columnas de `PortfolioBacktestResult.to_trades_dataframe()`: `Ticker`,
`Sector`, `Fecha Entrada`, `Precio Entrada`, `Nº Acciones`,
`Capital Invertido`, `Fecha Salida`, `Precio Salida`, `Motivo Salida`,
`Semanas en Pos.`, `Retorno %`, `P&L USD`.

> `launcher.py` no tiene mecanismo de apagado limpio más allá de
> interrumpir el proceso (Ctrl+C / kill); no persiste estado entre
> reinicios más allá de lo que ya cachea `backtest/.cache/`.

## 9. Métricas reportadas

`PortfolioBacktestResult.metrics()` (`backtest/portfolio_engine.py`) calcula,
sobre las operaciones **cerradas**:

- `capital_inicial`, `capital_final`, `rentabilidad_total_pct`
- `cagr_pct` (anualizado, `None` si el periodo simulado es 0 semanas)
- `max_drawdown_pct` (sobre la curva de equity semanal, no solo trades)
- `n_operaciones_cerradas`, `n_operaciones_abiertas_al_final`
- `win_rate_pct`, `retorno_medio_pct`, `retorno_mediana_pct`
- `profit_factor` (`None` si no hay pérdidas, para no dividir por cero)
- `mejor_operacion_pct`, `peor_operacion_pct`, `semanas_medias_en_pos`
- `sharpe_aprox` (sobre retornos semanales de la equity curve, anualizado
  con √52 — referencia orientativa para comparar configuraciones entre sí,
  no una cifra de nivel institucional)
- `pct_semanas_invertido` (% de semanas con al menos una posición abierta)

Ver `tests/test_portfolio_metrics.py` para las fórmulas verificadas con
valores exactos conocidos.

## 10. Referencias de implementación

| Módulo | Responsabilidad |
|---|---|
| `backtest/conditions.py` | `TickerContext`, condiciones F1-F5/S1-S2, `precompute_market_series`, criterios de ranking |
| `backtest/strategy_config.py` | `StrategyConfig`, `ConditionToggle`: qué condiciones están activas y con qué parámetros |
| `backtest/portfolio_engine.py` | Estructuras de resultado (`ClosedTrade`, `OpenPosition`, `EquityPoint`, `PortfolioBacktestResult`) y evaluación vectorizada de máscaras de entrada/salida |
| `backtest/portfolio_backtest.py` | `prepare_universe` (descarga + precálculo) y `run_portfolio_backtest` (bucle semanal de simulación) |
| `backtest/sp500_historical.py` | Reconstrucción de membresía histórica del S&P 500 desde Wikipedia |
| `backtest/data_cache.py` | Caché en disco de OHLCV + caché de fallos de descarga |
| `backtest/sweep.py` | Comparación de varias `StrategyConfig` sobre el mismo universo preparado |
| `backtest/run_portfolio_backtest.py` | CLI independiente |
| `backtest/strategy_backtest.py` | Backtest por-ticker aislado (sin cartera compartida) — ver sección 1 |
| `backtest/backtest_lookback.py` | Backtest de sensibilidad de `COPPOCK_RECENT_LOOKBACK` (F5) en aislamiento |
| `launcher.py` | Ejecución periódica del backtest de cartera (universo histórico, cada hora) |

Tests relevantes: `tests/test_conditions.py`, `tests/test_strategy_config.py`,
`tests/test_portfolio_engine.py`, `tests/test_portfolio_metrics.py`,
`tests/test_data_cache.py`, `tests/test_sp500_historical.py`,
`tests/test_portfolio_backtest_historical.py`, `tests/test_strategy_backtest.py`.

---

*Este documento es complementario a `backtest/README.md` (quickstart) y no
modifica la lógica del código. Para ajustar umbrales o comportamiento, edita
las constantes/funciones referenciadas arriba y mantén la coherencia con
estas notas.*
