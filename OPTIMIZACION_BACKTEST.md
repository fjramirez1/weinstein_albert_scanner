# Plan de estudio y optimización de la estrategia Weinstein-Albert

Este documento registra el progreso, los comandos ejecutados, los resultados y las
conclusiones del proceso de estudio/optimización del backtest de cartera
(`backtest/portfolio_backtest.py`). Está pensado para que cualquiera (persona o IA
con acceso al repositorio) pueda retomar el trabajo desde aquí sin perder contexto.

**No modifica el plan original por sí solo**: cada cambio propuesto a
`weinstein/config.py` debe quedar aquí documentado con su evidencia antes de
aplicarse, y solo se aplica tras pasar por la Fase 6 (validación).

---

## 0. Contexto y objetivo

El proyecto es un escáner semanal de acciones inspirado en el método Weinstein
(ver `docs/ESTRATEGIA.md` para la estrategia en producción, `backtest/BACKTEST.md`
para el modelo de backtest de cartera). El objetivo de este proceso es **estudiar
la sensibilidad de cada condición/parámetro con evidencia empírica**, no
maximizar mecánicamente la rentabilidad histórica — con una única serie real
(el S&P 500 de los últimos años) el riesgo de sobreajuste es alto y hay que
tratarlo con cautela en cada paso.

### Decisiones de diseño del proceso (importantes, no repetir sin releer esto)

1. **Partición temporal para evitar overfitting**: las Fases 1-5 (calibración)
   se ejecutan con `--period 6y`. La Fase 6 (validación final) se ejecuta con
   `--period 8y` (periodo completo) para comprobar si las conclusiones se
   sostienen al incluir los 2 años más recientes no vistos durante la
   calibración. No es una partición perfecta (los periodos se solapan en los
   primeros 6 años), pero es lo que el CLI permite sin tocar código, y ya evita
   la forma más burda de overfitting ("elegir la config que mejor le vino al
   único periodo completo disponible").
2. **Presupuesto de configuraciones**: máximo ~18-20 variantes en total entre
   fases 2-5, para no derivar en grid search descontrolado. Se cuentan al
   final de cada fase en este documento.
3. **En cada resultado de sweep/backtest se miran SIEMPRE 3+ cosas juntas**,
   nunca solo la rentabilidad total:
   - `Nº Operaciones cerradas` (con pocas operaciones, cualquier métrica es poco fiable).
   - Consistencia entre métricas independientes (Sharpe, drawdown, profit factor,
     win rate) — si solo mejora la rentabilidad pero empeora el resto, sospechar.
   - **Concentración en outliers**: qué % del P&L total aportan las 5 mejores
     operaciones (ver metodología en sección 3, Fase 2). Esto ha demostrado ser
     crítico en este proyecto: el propio baseline tiene concentración extrema
     (179.4%, ver Fase 2), así que ninguna comparación de rentabilidad agregada
     es tan fiable como parece a primera vista sin este chequeo.
4. **Universo**: todo se ejecuta con `--universe historical` (reconstrucción de
   membresía histórica real del S&P 500, mitiga sesgo de supervivencia — ver
   `backtest/BACKTEST.md` sección 4). **Requiere el mapeo
   `HISTORICAL_DELISTED_SECTORS` en `weinstein/config.py` bien poblado** (ver
   Fase -1 más abajo); si `tickers_sector_desconocido` sale alto en el log,
   cualquier comparación que involucre F1 queda contaminada y hay que arreglarlo
   antes de seguir.
5. **Entorno de quien ejecuta**: Windows (Git Bash / MINGW64), venv ya activado,
   caché de datos (`backtest/.cache/`) ya poblada (~614 archivos, 11.69 MB),
   `TIINGO_API_KEY` configurada y funcional.

### Cómo continuar si retomas este documento

1. Lee la sección "Estado actual" (al final) para saber en qué fase/paso se quedó.
2. Antes de lanzar nada nuevo, repasa la lista de comandos ya ejecutados en la
   fase correspondiente para no repetir trabajo.
3. Cualquier conclusión nueva se añade a la fase correspondiente, con los
   números exactos (no resúmenes vagos) y el comando que los generó.
4. Los cambios a `weinstein/config.py` NO se aplican hasta la Fase 7
   (documentación final) y solo si sobreviven a la Fase 6 (validación).

### Instrucción de mantenimiento (obligatoria, no solo para humanos)

**Este documento se actualiza EN CADA PASO, no al final de la sesión.** Si eres
una IA ejecutando este plan con acceso al repositorio, tras cada comando (o
grupo pequeño de comandos de la misma fase) que produzca un resultado:

1. Edita este archivo y registra: el comando exacto ejecutado, la tabla/cifras
   de resultado, y cualquier conclusión o sospecha que surja — aunque sea
   parcial o esté pendiente de verificar. No esperes a "tener todo" para
   escribir; una fase puede quedar a medias documentada y eso es preferible a
   no documentarla.
2. Actualiza el campo "Estado" de la fase en curso (`⬜ No iniciada` /
   `🔄 En curso` / `✅ Completada`) y la sección "Estado actual" al final del
   documento, incluyendo qué queda pendiente exactamente (el próximo comando a
   ejecutar, no solo "seguir con la fase X").
3. Si detectas una incidencia (bug, dato inesperado, un mock o supuesto que
   resulta falso, un límite de API alcanzado, etc.), documéntala igual que se
   hizo con la incidencia del diccionario sobrescrito en la Fase -1: qué pasó,
   cómo se detectó, cómo se corrigió. Es información tan valiosa como los
   resultados numéricos.
4. Nunca sobrescribas conclusiones anteriores sin dejar constancia de que se
   revisaron — si una fase posterior contradice algo dicho antes, se anota el
   cambio de conclusión con el motivo, no se borra silenciosamente el rastro.
5. El presupuesto de configuraciones (contador al final de cada fase y en
   "Estado actual") se actualiza también en cada paso, no solo al cerrar fase.

El motivo de esta exigencia: el proceso completo puede ejecutarse en varias
sesiones o por distintos agentes, y la única fuente de verdad compartida es
este archivo — no el historial de chat, que no es accesible entre sesiones.

---

## Fase -1 — Corrección de prerequisito: sesgo de sector "Unknown"

**Estado: ✅ Completada**

Antes de la Fase 0 se detectó que el baseline en modo `historical` tenía 78/611
tickers (~13%) con `Sector="Unknown"`, lo cual los excluye de F1 (RSC sector) de
forma permanente y contamina cualquier comparación que toque F1 (ver aviso en
`backtest/portfolio_backtest.py::print_report` y `backtest/BACKTEST.md` sección 4).

**Causa**: el mapeo manual `HISTORICAL_DELISTED_SECTORS` en `weinstein/config.py`
no cubría suficientes tickers delistados/excluidos del S&P 500 actual.

**Acción tomada**: se amplió `HISTORICAL_DELISTED_SECTORS` con ~90 tickers
adicionales (identificados vía `prepare_universe(...).tickers_sector_desconocido`),
verificado con `tests/test_config_historical_sector.py`.

**Incidencia durante el proceso**: al pegar el bloque nuevo se sobrescribió por
error el diccionario original (se perdieron ~40 entradas previas, ej. `CELG`,
`TWTR`, `XLNX`). Detectado porque
`test_ticker_delistado_con_mapeo_manual_lo_resuelve` falló (`CELG` ya no
resolvía a `"Health Care"`). Se reconstruyó el diccionario completo (original +
ampliación) y se verificó de nuevo. **Lección**: al editar
`HISTORICAL_DELISTED_SECTORS` en el futuro, añadir entradas nuevas sin
reemplazar el bloque completo, o verificar con `grep` que las claves antiguas
conocidas (`CELG`, `TWTR`, `XLNX`, `ETFC`...) siguen presentes tras el cambio.

**Resultado tras la corrección**: `tickers_sector_desconocido` bajó de 78 a
**2** (nivel aceptable, no bloqueante). `tickers_historicos_sin_precio` se
mantiene en 10 (no relacionado con sector, son tickers sin datos de precio en
ninguna fuente — FDXF, HONA, Q entre ellos; ver log de cualquier ejecución).

```bash
pytest tests/test_config_historical_sector.py -v   # todos los tests pasan
```

---

## Fase 0 — Baseline

**Estado: ✅ Completada**

```bash
python backtest/run_portfolio_backtest.py --universe historical --period 6y --name baseline --export historial/backtests/fase0_baseline.csv
```

### Resultado (baseline oficial de referencia para todo el proceso)

| Métrica | Valor |
|---|---|
| Capital inicial → final | $10,000 → $12,221.70 |
| Rentabilidad total | **+22.22%** |
| CAGR | 3.38% |
| Max drawdown | -22.69% |
| Sharpe aprox. | 0.31 |
| Operaciones cerradas | 130 |
| Posiciones abiertas al final | 5 |
| Win rate | 39.2% |
| Retorno medio por operación | 1.41% |
| Retorno mediana por operación | -2.41% |
| Mejor / peor operación | +73.14% / -20.68% |
| Profit factor | 1.34 |
| % semanas con capital invertido | 70.1% |
| `tickers_sector_desconocido` | 2 |
| `tickers_historicos_sin_precio` | 10 |

### Conclusión clave (importante para leer todas las fases siguientes)

Al calcular la concentración de P&L en las 5 mejores operaciones (ver
metodología en Fase 2), el baseline dio **179.4%** — es decir, las 5 mejores
operaciones suman MÁS que el P&L total, lo que implica que el resto de las 125
operaciones restantes tiene, en conjunto, P&L neto **negativo**. Esto confirma
que la estrategia es intrínsecamente de "cola muy pesada" (gana pocas veces,
pero en grande) — patrón típico de seguimiento de tendencia, coherente con
`win_rate=39.2%` y mediana negativa pero mejor operación muy superior a la
peor. **Consecuencia práctica**: ninguna comparación de rentabilidad agregada
entre configuraciones es fiable sin revisar también su concentración de
outliers — el propio baseline ya depende fuertemente de ellos.

---

## Fase 1 — Sensibilidad de `COPPOCK_RECENT_LOOKBACK` (F5)

**Estado: ✅ Completada — sin cambios recomendados**

```bash
python backtest/backtest_lookback.py --period 6y --lookbacks 2,3,4,6,8,10,12
```

### Resultado

Meseta completa: lookback 3 a 12 dan **resultados idénticos** (38 señales, mismo
retorno medio/mediana en todos los horizontes, mismo retraso de 1 semana).
Solo lookback=2 difiere mínimamente (39 señales). El valor actual en
`weinstein/config.py` (`COPPOCK_RECENT_LOOKBACK = 4`) está dentro de esa meseta.

### Conclusión

**No hay ninguna base para cambiar `COPPOCK_RECENT_LOOKBACK`.** El parámetro es
indiferente en el rango razonable durante este periodo histórico. No se toca.

Nota aparte (no accionable, pero relevante para contexto): solo 38 señales en 6
años y hasta 34% de ellas con retorno negativo a 4 semanas — F5 en aislamiento
es un filtro bastante ruidoso, consistente con el Sharpe modesto del baseline.

---

## Fase 2 — Barrido individual de condiciones de entrada/salida

**Estado: ✅ Completada (6 variantes + 2 chequeos de concentración adicionales)**

Cada comando cambia una sola cosa respecto al baseline (Fase 0).

```bash
python backtest/run_portfolio_backtest.py --universe historical --period 6y --disable F1_sector_fuerte --name sin_F1 --export historial/backtests/fase2_sin_F1.csv
python backtest/run_portfolio_backtest.py --universe historical --period 6y --disable F2_volumen_positivo --name sin_F2 --export historial/backtests/fase2_sin_F2.csv
python backtest/run_portfolio_backtest.py --universe historical --period 6y --disable F4_distancia_wma30 --name sin_F4 --export historial/backtests/fase2_sin_F4.csv
python backtest/run_portfolio_backtest.py --universe historical --period 6y --s1-umbral -1.0 --name s1_laxo --export historial/backtests/fase2_s1_laxo.csv
python backtest/run_portfolio_backtest.py --universe historical --period 6y --s1-umbral -0.25 --name s1_estricto --export historial/backtests/fase2_s1_estricto.csv
python backtest/run_portfolio_backtest.py --universe historical --period 6y --f4-max-distancia 12 --name f4_laxo --export historial/backtests/fase2_f4_laxo.csv
```

### Resultado (tabla comparativa)

| Config | Rentab. | CAGR | Sharpe | Max DD | Ops | Win rate | Profit factor |
|---|---|---|---|---|---|---|---|
| **baseline** | +22.22% | 3.38% | 0.31 | -22.69% | 130 | 39.2% | 1.34 |
| sin F1 | +69.02% | 9.08% | 0.83 | -14.70% | 125 | 48.0% | 2.15 |
| sin F2 | -9.24% | -1.59% | -0.07 | -27.68% | 140 | 40.0% | 0.93 |
| sin F4 | +97.63% | 11.94% | 0.72 | -23.77% | 100 | 59.0% | 2.97 |
| S1 laxo (-1.0) | +36.54% | 5.29% | 0.47 | -22.70% | 107 | 43.0% | 1.66 |
| S1 estricto (-0.25) | +11.51% | 1.82% | 0.20 | -25.64% | 146 | 33.6% | 1.15 |
| F4 laxo (12%) | +38.15% | 5.50% | 0.51 | -24.88% | 129 | 42.6% | 1.56 |

### Chequeo adicional 1 — ¿es F4 un efecto real o un artefacto de ranking?

Sospecha: al quitar F4, el nº de operaciones **bajó** (130→100), lo cual es
contraintuitivo (quitar un filtro debería dejar entrar más candidatos, no
menos). Hipótesis: efecto de ranking, no de filtrado — tickers con distancia
extrema a WMA30 (alto momentum) desplazan a otros en el desempate.

```bash
python backtest/run_portfolio_backtest.py --universe historical --period 6y --f4-max-distancia 100 --name f4_practicamente_desactivado --export historial/backtests/fase2_f4_check.csv
```

Resultado: **idéntico** a `sin_F4` (100 ops, +97.63%, mismo Sharpe/DD/peor
operación). Confirma que `--disable` funciona correctamente (no es un bug de
CLI), pero no confirma que la mejora sea estructural.

### Chequeo adicional 2 — Concentración de P&L en top-5 operaciones

Metodología (reutilizable para cualquier CSV de operaciones exportado):

```bash
python -c "
import pandas as pd
df = pd.read_csv('RUTA_AL_CSV.csv')
df = df.dropna(subset=['Retorno %'])
print('Nº operaciones:', len(df))
print('Suma P&L total:', round(df['P&L USD'].sum(), 2))
print('Suma P&L top 5 mejores:', round(df.nlargest(5, 'Retorno %')['P&L USD'].sum(), 2))
print('% del PnL que aportan las 5 mejores:', round(100 * df.nlargest(5, 'Retorno %')['P&L USD'].sum() / df['P&L USD'].sum(), 1), '%')
"
```

| Config | % PnL en top-5 | Nº ops |
|---|---|---|
| **baseline** | **179.4%** (resto pierde neto) | 130 |
| sin F1 | 59.3% | 125 |
| sin F4 | 69.0% | 100 |
| S1 laxo (-1.0) | 96.7% | 107 |

Nota: el chequeo de `s1_laxo` se completó más tarde, durante la preparación de
la Fase 5 (no en el momento original de la Fase 2) — se documenta aquí para
mantener agrupada toda la evidencia de concentración de outliers de esta
fase.

Detalle de sin_F4: las 5 mejores operaciones (GEV +116.5%, WDC +110.65%, MU
+94.64%, HII +87.33%, HWM +74.82%, todas con fecha de entrada en 2025) suman
$6,118.81 de un P&L total de $8,866.43.

### Conclusión de la Fase 2

- **F2 (volumen) es la señal más sólida y fiable de esta fase.** Desactivarla
  empeora *todas* las métricas de forma consistente y simultánea (rentabilidad,
  Sharpe pasa a negativo, peor drawdown, profit factor <1). Esa consistencia
  entre métricas independientes pesa más que un número aislado de rentabilidad.
  **Se mantiene activa sin cambios.**
- **F1 y F4**: la evidencia de que "quitarlos ayuda" es más débil de lo que
  parecía a primera vista. Sorprendentemente, ambas variantes concentran
  *menos* P&L en outliers que el propio baseline (59.3% y 69.0% vs 179.4%), lo
  que invierte parcialmente la sospecha inicial — pero con solo 100-125
  operaciones y una sola serie histórica, **no hay evidencia suficiente para
  decidir en ningún sentido**. Pasan a Fase 5 como hipótesis a validar, no
  como cambios decididos.
- **S1 (umbral RSC de salida)**: relación monótona y coherente (laxo mejora,
  estricto empeora) en todas las métricas. Concentración de outliers 96.7%
  (dato añadido después, ver tabla arriba) — intermedia entre el baseline y
  los rankings alternativos de la Fase 3. Candidato razonable para Fase 5, de
  confianza media.
- **F4 en particular**: aunque el número agregado es el más alto de toda la
  fase (+97.63%), es el caso con mayor concentración en outliers (69%) y con
  MENOS operaciones que el baseline (100 vs 130) pese a quitar un filtro —
  tratarlo con la máxima cautela. Sea cual sea la decisión final, revisar en
  Fase 6 si las operaciones ganadoras (GEV, WDC, MU, HII, HWM, todas de 2025)
  caen dentro o fuera del tramo de validación, porque de eso depende en gran
  medida si el resultado se sostiene.

**Configuraciones usadas en esta fase: 8** (6 planificadas + 2 chequeos de
concentración/ranking). Presupuesto total del proceso: 8/20.

---

## Fase 3 — Ranking / criterio de desempate

**Estado: ✅ Completada**

```bash
python backtest/run_portfolio_backtest.py --universe historical --period 6y --ranking rsc_activo --name rank_rsc --export historial/backtests/fase3_rank_rsc.csv
python backtest/run_portfolio_backtest.py --universe historical --period 6y --ranking vpm5 --name rank_vpm5 --export historial/backtests/fase3_rank_vpm5.csv
```

(`momentum`, el ranking por defecto, ya es el baseline de la Fase 0 — no se
repite.)

### Resultado

| Config | Rentab. | CAGR | Sharpe | Max DD | Ops | Win rate | Profit factor |
|---|---|---|---|---|---|---|---|
| **baseline (momentum)** | +22.22% | 3.38% | 0.31 | -22.69% | 130 | 39.2% | 1.34 |
| ranking rsc_activo | +79.64% | 10.19% | 0.73 | -17.91% | 124 | 49.2% | 2.14 |
| ranking vpm5 | +80.89% | 10.31% | 0.77 | -19.68% | 128 | 50.0% | 2.23 |

A diferencia de F4, aquí NO hay caída sospechosa en el nº de operaciones (124 y
128, similar al baseline 130), y la mejora es consistente en todas las
métricas simultáneamente (mejor Sharpe, mejor drawdown, mejor win rate, mejor
profit factor) — buena señal preliminar, pero **pendiente el chequeo de
concentración en outliers** (obligatorio según la metodología de esta fase,
ver Fase 2) antes de sacar conclusiones definitivas.

### Chequeo de concentración de outliers (ejecutado)

```bash
python -c "
import pandas as pd
for nombre, ruta in [('rank_rsc','historial/backtests/fase3_rank_rsc.csv'), ('rank_vpm5','historial/backtests/fase3_rank_vpm5.csv')]:
    df = pd.read_csv(ruta).dropna(subset=['Retorno %'])
    top5 = df.nlargest(5, 'Retorno %')['P&L USD'].sum()
    total = df['P&L USD'].sum()
    print(nombre, '-> Nº ops:', len(df), '| % PnL en top-5:', round(100*top5/total, 1))
"
```

Resultado:

| Config | % PnL en top-5 | Nº ops |
|---|---|---|
| baseline (referencia, Fase 0) | 179.4% | 130 |
| sin_F1 (referencia, Fase 2) | 59.3% | 125 |
| sin_F4 (referencia, Fase 2) | 69.0% | 100 |
| **rank_rsc** | **79.4%** | 124 |
| **rank_vpm5** | **68.8%** | 128 |

### Conclusión de la Fase 3

Ambos rankings alternativos concentran claramente menos que el baseline
(79.4% y 68.8% vs 179.4%), en línea con sin_F1/sin_F4 — ni sospechosamente
bajo ni anormalmente alto. Combinado con que:

- el nº de operaciones se mantiene similar al baseline (124/128 vs 130, sin la
  caída rara que sí vimos en F4),
- la mejora es simultánea y coherente en Sharpe, drawdown, win rate y profit
  factor (no solo en rentabilidad total),

este es, junto con S1 laxo, el hallazgo **más creíble de todo el proceso hasta
ahora**. `rank_vpm5` tiene ligera ventaja sobre `rank_rsc` en casi todas las
métricas (Sharpe 0.77 vs 0.73, drawdown -19.68% vs -17.91% es ligeramente peor
para vpm5 pero el resto favorece vpm5) y además menor concentración en
outliers (68.8% vs 79.4%) — con estos números tan cercanos, ninguno de los dos
domina claramente al otro; ambos son candidatos válidos para la Fase 5.

**Cambio de criterio de ranking (`momentum` → `rsc_activo` o `vpm5`) queda
marcado como candidato fuerte para la Fase 5**, junto con S1 laxo. F1/F4
siguen con evidencia débil (Fase 2) y se combinarán con más cautela.

**Configuraciones usadas en esta fase: 2.** Presupuesto total del proceso: 10/20.

**Estado de la Fase 3: ✅ Completada.**

---

## Fase 4 — Dimensionamiento de cartera

**Estado: ✅ Completada**

```bash
python backtest/run_portfolio_backtest.py --universe historical --period 6y --max-positions 5 --name pos_5 --export historial/backtests/fase4_pos5.csv
python backtest/run_portfolio_backtest.py --universe historical --period 6y --max-positions 15 --name pos_15 --export historial/backtests/fase4_pos15.csv
python backtest/run_portfolio_backtest.py --universe historical --period 6y --max-positions 20 --name pos_20 --export historial/backtests/fase4_pos20.csv
```

Nota: el capital inicial no se varió — en este motor sin fricción/comisiones no
afecta a rentabilidad %/Sharpe/drawdown, no aporta información nueva.

### Resultado

| Config | Rentab. | CAGR | Sharpe | Max DD | Ops | Win rate | Profit factor |
|---|---|---|---|---|---|---|---|
| pos_5 (max_pos=5) | +25.57% | 3.84% | 0.36 | -16.33% | 64 | 43.8% | 1.55 |
| baseline (max_pos=10) | +22.22% | 3.38% | 0.31 | -22.69% | 130 | 39.2% | 1.34 |
| pos_15 (max_pos=15) | +37.00% | 5.35% | 0.47 | -21.82% | 189 | 40.2% | 1.63 |
| pos_20 (max_pos=20) | +23.05% | 3.49% | 0.34 | -23.80% | 255 | 38.4% | 1.38 |

Patrón NO monótono con `max_positions`: `pos_15` destaca por encima de `pos_5`,
`pos_10` (baseline) y `pos_20` en casi todas las métricas simultáneamente,
mientras que `pos_20` vuelve a comportarse casi como el baseline. Sugiere un
punto intermedio favorable de diversificación que se diluye si se amplía
demasiado (probablemente porque, con pocos candidatos pasando F1-F5 a la vez
en este universo, `max_positions=20` termina llenando huecos con candidatos de
peor ranking).

### Chequeo de concentración de outliers

```bash
python -c "
import pandas as pd
for nombre, ruta in [('pos_5','historial/backtests/fase4_pos5.csv'), ('pos_15','historial/backtests/fase4_pos15.csv'), ('pos_20','historial/backtests/fase4_pos20.csv')]:
    df = pd.read_csv(ruta).dropna(subset=['Retorno %'])
    top5 = df.nlargest(5, 'Retorno %')['P&L USD'].sum()
    total = df['P&L USD'].sum()
    print(nombre, '-> Nº ops:', len(df), '| % PnL en top-5:', round(100*top5/total, 1))
"
```

| Config | % PnL en top-5 | Nº ops |
|---|---|---|
| baseline (referencia) | 179.4% | 130 |
| rank_rsc / rank_vpm5 (referencia, Fase 3) | 79.4% / 68.8% | 124 / 128 |
| pos_5 | **158.7%** | 64 |
| **pos_15** | **108.1%** | 189 |
| pos_20 | 141.0% | 255 |

### Conclusión de la Fase 4

A diferencia del ranking (Fase 3), aquí **la concentración en outliers sigue
siendo alta en las tres variantes** (todas >100%, es decir, en los tres casos
el resto de operaciones fuera del top-5 tiene P&L neto negativo) — mucho más
cercano al patrón del baseline que al de los rankings alternativos. Esto
templa el entusiasmo por la mejora agregada de `pos_15`.

Dicho esto, `pos_15` es la variante *relativamente* menos concentrada de las
tres (108.1% vs 158.7% y 141.0%), y además tiene la muestra más grande (189
operaciones cerradas, la mayor de todo el proceso hasta ahora) — con más
operaciones, cualquier métrica agregada es algo más fiable, aunque la
concentración en sí no mejore proporcionalmente. Es un candidato razonable
para la Fase 5, pero con la misma cautela que F1/F4 (Fase 2): no tratarlo como
una mejora confirmada, sino como una hipótesis con evidencia mixta.

`pos_5` (menor drawdown, -16.33%, el mejor de toda la fase) es interesante
para un perfil más conservador, pero su concentración de outliers (158.7%)
sobre solo 64 operaciones es la combinación menos fiable de las tres — la
muestra es demasiado pequeña para concluir nada con solidez.

**`max_positions=20` no aporta nada — descartado.** Se comporta casi como el
baseline pero con más operaciones (más "trabajo" del sistema) sin mejora
proporcional, y con concentración de outliers peor que `pos_15`.

**Configuraciones usadas en esta fase: 3.** Presupuesto total del proceso: 13/20.

---

## Fase 5 — Combinación acotada (grid search pequeño)

**Estado: 🔄 En curso — combo 1 y combo 2 completados, pendiente combo 3**

Presupuesto restante tras fases 2-4: 20 - 13 = **7 configuraciones**.

### Cuadro completo de confianza (rentabilidad + concentración de outliers)

| Candidato | Rentab. (aislado) | Sharpe | % PnL top-5 | Ops | Confianza |
|---|---|---|---|---|---|
| ranking `vpm5` | +80.89% | 0.77 | 68.8% | 128 | **Alta** |
| ranking `rsc_activo` | +79.64% | 0.73 | 79.4% | 124 | **Alta** |
| S1 laxo (-1.0) | +36.54% | 0.47 | 96.7% | 107 | Media |
| `max_positions=15` | +37.00% | 0.47 | 108.1% | 189 | Media-baja |
| sin F1 | +69.02% | 0.83 | 59.3% | 125 | Baja (ver Fase 2) |
| sin F4 | +97.63% | 0.72 | 69.0% | 100 | Baja (ver Fase 2, caída de ops) |
| `max_positions=5` | +25.57% | 0.36 | 158.7% | 64 | Baja (muestra pequeña) |

*(referencia: baseline +22.22%, Sharpe 0.31, 179.4% top-5, 130 ops)*

### Combo 1 — ranking `vpm5` + S1 laxo (-1.0)

```bash
python backtest/run_portfolio_backtest.py --universe historical --period 6y --ranking vpm5 --s1-umbral -1.0 --name combo1_vpm5_s1laxo --export historial/backtests/fase5_combo1.csv
```

| Métrica | Valor |
|---|---|
| Rentabilidad | +91.99% |
| CAGR | 11.41% |
| Sharpe | 0.85 |
| Max drawdown | -19.47% |
| Ops cerradas | 107 |
| Win rate | 51.4% |
| Profit factor | 2.66 |
| % PnL en top-5 | **61.1%** |

### Combo 2 — ranking `rsc_activo` + S1 laxo (-1.0)

```bash
python backtest/run_portfolio_backtest.py --universe historical --period 6y --ranking rsc_activo --s1-umbral -1.0 --name combo2_rsc_s1laxo --export historial/backtests/fase5_combo2.csv
```

| Métrica | Valor |
|---|---|
| Rentabilidad | +102.05% |
| CAGR | 12.35% |
| Sharpe | **0.92** |
| Max drawdown | **-16.58%** |
| Ops cerradas | 105 |
| Win rate | 51.4% |
| Profit factor | **2.77** |
| % PnL en top-5 | **60.5%** |

### Análisis combo 1 vs combo 2

`combo2` (rsc_activo) gana en casi todas las métricas simultáneamente: mejor
Sharpe (0.92 vs 0.85), mejor drawdown (-16.58% vs -19.47%), mejor profit
factor (2.77 vs 2.66), rentabilidad ligeramente superior, y también menor
concentración de outliers (60.5% vs 61.1%, diferencia mínima).

**Hallazgo importante**: ambos combos tienen concentración de outliers
notablemente MENOR que sus componentes individuales por separado (rsc_activo
solo: 79.4%; S1 laxo solo: 96.7%; combinados: 60.5%). Esto es una señal de
calidad genuina — combinar ambos cambios no solo mejora las métricas
agregadas, sino que hace el resultado menos dependiente de un puñado de
operaciones extremas, justo la dirección de fiabilidad que se busca en todo
este proceso. Refuerza que ranking alternativo + S1 laxo son cambios que se
complementan de verdad, no que simplemente apilen ruido en la misma
dirección favorable.

**`combo2_rsc_s1laxo` (ranking `rsc_activo` + S1 umbral -1.0) es el ganador
provisional del proceso hasta ahora.** Pasa a ser la base sobre la que se
construye el combo 3.

### Combo 3 — pendiente de ejecutar

Añadir `max_positions=15` (confianza media-baja, Fase 4) sobre la base del
combo 2 ganador:

```bash
python backtest/run_portfolio_backtest.py --universe historical --period 6y --ranking rsc_activo --s1-umbral -1.0 --max-positions 15 --name combo3_mas_pos15 --export historial/backtests/fase5_combo3.csv
```

Las 4 configuraciones restantes del presupuesto (7 - 3 = 4) se reservan para:
- Si algún combo de arriba decepciona, no repetir con F1/F4 (confianza baja,
  ver Fase 2) salvo que los combos 1-3 no den ninguna mejora sólida sobre el
  baseline — en ese caso sí probar añadir `--disable F1_sector_fuerte` sobre
  el mejor combo, como último recurso, dejando claro en el documento que es
  una hipótesis de baja confianza.
- Guardar margen para un ajuste fino si algún resultado combinado es
  prometedor pero con algún parámetro claramente subóptimo (p.ej. probar
  `max_positions=12` si 15 resulta mejor que 10 pero no está claro que 15 sea
  el óptimo exacto).

**Tras cada combo, aplicar el chequeo de concentración de outliers de
siempre** antes de decidir si se mantiene para la Fase 6.

---

## Fase 6 — Validación final sobre periodo completo (8y, aún no iniciada)

```bash
python backtest/run_portfolio_backtest.py --universe historical --period 8y --name ganadora_validacion --export historial/backtests/fase6_validacion.csv
```

Una única pasada de la config ganadora de la Fase 5. Si el resultado se
degrada mucho respecto a la calibración (6y), es señal de overfitting a la
ventana de 6y y la conclusión correcta es quedarse con algo más conservador o
con el baseline — no buscar otra config.

**Atención especial**: revisar si las operaciones ganadoras identificadas en
Fase 2 (GEV, WDC, MU, HII, HWM, entradas de 2025) quedan dentro del tramo
2020-2026 igualmente en el run de 8y, y si aparecen operaciones ganadoras
nuevas en el tramo 2018-2020 que no se vieron en calibración.

---

## Fase 7 — Documentación y decisión final (aún no iniciada)

Tabla comparativa de todo el proceso + decisión de qué (si algo) se lleva a
`weinstein/config.py` como nuevo valor por defecto, con la evidencia de este
documento como justificación en el commit/PR correspondiente.

---

## Estado actual

**Fases 0-4 completadas. Fase 5 en curso**: combo 1 y combo 2 completados y
comparados. **`combo2_rsc_s1laxo` (ranking `rsc_activo` + S1 umbral -1.0) es
el ganador provisional del proceso** (+102.05%, Sharpe 0.92, drawdown
-16.58%, 60.5% concentración top-5 — mejor que sus componentes por separado
en todas las métricas).

**Presupuesto de configuraciones usado: 15 de ~20** (quedan 5 para el resto
de la Fase 5).

**Próximo comando a ejecutar (combo 3):**

```bash
python backtest/run_portfolio_backtest.py --universe historical --period 6y --ranking rsc_activo --s1-umbral -1.0 --max-positions 15 --name combo3_mas_pos15 --export historial/backtests/fase5_combo3.csv
```

Tras obtenerlo, aplicar el chequeo de concentración de outliers y comparar
contra `combo2` (no solo contra el baseline) para decidir si
`max_positions=15` aporta algo real una vez ya aplicados el ranking y S1
laxo, o si simplemente diluye lo ya conseguido.

**Cambios ya decididos para `weinstein/config.py`:** ninguno todavía (todo
pendiente de Fase 6/7). Candidato líder actual si no mejora nada más:
`RANKING = "rsc_activo"` + `RSC_EXIT_THRESHOLD = -1.0` (nombres de constantes
a verificar contra `weinstein/config.py` antes de aplicar en Fase 7).
