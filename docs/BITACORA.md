# Bitácora

Registro *append-only* de sesiones de trabajo. Entrada más reciente al final.
Cada entrada: qué se hizo, decisiones, cifras exactas con el comando que las
generó, incidencias y siguiente paso. El plan vivo está en
[HOJA_DE_RUTA.md](HOJA_DE_RUTA.md).

---

## 2026-11-03 — Retomar el proyecto, revisión completa y organización

**Contexto.** Proyecto parado desde julio de 2026. El usuario pide terminarlo:
reglas fieles al vídeo, parámetros optimizados con backtest y documentación de
las señales. Último trabajo: `OPTIMIZACION_BACKTEST.md` (fases 0-7 cerradas
con ganador "ranking `rsc_activo` + S1 -1.0", fase 8 a medias), con cambios
sin commitear.

**Hecho.**
- Leído todo el código de `weinstein/` y `backtest/` y la documentación.
- `python -m pytest` → 202 passed, 2 deselected (red).
- `AGENTS.md` (ignorado por git y obsoleto: citaba scripts
  `weinstein_albert_scanner.py` que ya no existen) migrado a `CLAUDE.md`.
- Creadas `docs/HOJA_DE_RUTA.md` y esta bitácora como memoria entre sesiones.
- Git: identidad local del repo `fjramirez1 <fj.ramirezlopez@um.es>`
  (`git config --local`, sin tocar la global). Permiso del usuario para
  commit y push.

**Incidencia — caché real borrada por los tests.** El fixture autouse de
`tests/test_data_cache.py` llamaba a `data_cache.clear_cache()` sobre
`backtest/.cache/` real (y `tests/test_sp500_historical.py` borraba
`sp500_changes.parquet` real). Al ejecutar `pytest` se perdieron los 1282
ficheros (~29 MB) de datos descargados en julio. No estaban en git (ignorados)
y no son recuperables desde el repo. Impacto acotado: esos datos acababan en
la semana del 2026-07-20 (incompleta) y hay que re-descargar de todos modos
para un backtest actualizado; además los de Tiingo eran inservibles por B1.
Corregido: ambos fixtures redirigen la caché a `tmp_path` con `monkeypatch`.
Verificado con un fichero testigo en `backtest/.cache/` que sobrevive a
`pytest`. Regla añadida a `CLAUDE.md`.

**Hallazgos de la revisión** (detalle y plan en la hoja de ruta, Fase 1):
- B1 (crítico): velas yfinance en lunes, Tiingo en viernes. Comprobado sobre
  la caché antes de borrarse: `^GSPC`, `AAPL`, `XLC` → último índice lunes
  2026-07-20; `CELG` (2011-07-22 → 2019-11-22) y `ATVI` (→ 2023-10-13) en
  viernes. El motor nunca encuentra esas fechas → los delistados nunca
  operan. Verificación sobre los 18 CSV de `historial/backtests/`: las 4816
  fechas de entrada/salida son todas lunes (ninguna vela Tiingo) y no aparece
  ninguno de los delistados conocidos (CELG, ATVI, SIVB, FRC, TWTR, XLNX,
  ETFC, PXD, CTXS, CERN, ABMD, ANSS, HES, MRO, DFS, JNPR).
- B2: posiciones sin datos quedan abiertas y valoradas a coste para siempre.
- B4: entrada/salida al cierre de la misma vela que da la señal.
- B5: umbrales del backtest duplicados a mano en `backtest/conditions.py`.
- B8: la "validación 8y" no es fuera de muestra (contiene el tramo de 6y y
  añade los 2 años más antiguos, no los más recientes).
- En producción, `MOM = (C − WMA30)/WMA30` es exactamente `Dist% / 100`: el
  desempate por MOM elige las acciones **más extendidas** que aún pasan
  F4 (< 8 %). Explica por qué el ranking `momentum` era el peor del estudio.
- `historial/backtests/fase5_combo3.csv` existe aunque el estudio dice que
  el combo 3 "no se ejecutó".

**Conclusión.** Las cifras de `OPTIMIZACION_BACKTEST.md` se conservan como
histórico pero **no sirven para decidir**: B1+B2+B4+B8 cambian el universo,
la valoración y la validación. Se rehará la optimización en la Fase 4 tras
corregir el motor.

**Worktrees.** `C:\UNI\weinstein_albert_scanner.worktrees\` contiene 2
worktrees de git (`agents/backtest-review-and-guidance`,
`agents/debug-test-failure-salida-entrada-misma-semana`) y una carpeta vacía
(`agents-fix-test-entry-exit-same-week`), restos de sesiones de un agente IA
de julio. Ambas ramas están fusionadas en `main`; el único cambio sin
commitear (un test) quedó superado por `_first_true_idx` en `main` (PR #1).
Se pueden borrar → tarea R4, pendiente de OK del usuario.

**Siguiente paso.** Fase 1, B1.

---

## 2026-11-03 (2) — Fase 1: corrección del backtest

**Organización.** Petición del usuario: commits solo con su autoría (sin
`Co-Authored-By`), y nada de carpetas extra. Eliminados los dos worktrees de
`../weinstein_albert_scanner.worktrees/`, la carpeta vacía y las tres ramas
locales `agents/*` (todas fusionadas en `main`). Regla añadida a `CLAUDE.md`.
Los tres primeros commits de la sesión (ya subidos) llevaban la línea de
coautoría; reescribirlos requería `push --force` → ver la entrada
siguiente.

**Commits de la fase** (`python -m pytest`: 202 → 229 passed):

| Commit | Tareas | Qué cambia |
|---|---|---|
| `4b77170` | B5 | `backtest/conditions.py` lee umbrales/periodos de `weinstein/config.py` |
| `435a25c` | B1, B3 | `normalize_weekly_bars()`: velas en viernes para yfinance y Tiingo, sin la semana en curso (cierre: viernes 16:30 Nueva York). En descarga y en caché |
| `c04ef2c` | B2, B4, B6, B7, B8 | Motor: ejecución `next_open` por defecto, cierre `SIN_DATOS` al acabar los datos, costes por lado (0,10 %), profit factor en $, CAGR por fechas, % P&L top-5, benchmark SPY, `--start/--end`. CLI de `portfolio-backtest` definido una sola vez |
| `0b54a03` | B10 | Caché de tickers vigentes se refresca al cerrar una semana nueva |
| `9e3f45d` | B9 | Sectores GICS corregidos (BWA, NWL, MTCH, WU, DXC, VNT, HRB, INFO, FLT; fuera KEYS) |

**Decisiones de diseño.**
- Convención de fecha: viernes de la semana de negociación. Se eligió el
  viernes (y no el lunes) porque es el día en que la vela está completa.
- Ejecución por defecto `next_open`: el escáner corre en fin de semana y la
  orden entra el lunes. `close` se conserva solo para medir cuánto inflaba
  el modelo antiguo.
- Coste por defecto 0,10 % por lado (broker barato + deslizamiento en
  acciones líquidas del S&P 500). Configurable con `--coste`.
- Benchmark SPY y no ^GSPC: ^GSPC no incluye dividendos (~1,5 %/año) y las
  acciones sí (precios ajustados), así que comparar contra ^GSPC
  favorecía a la estrategia.
- Arranque por defecto de la simulación en la semana 57 (cuando existe VPM5,
  el indicador con la ventana más larga) para que el CAGR no incluya un año
  forzosamente en efectivo.
- `Retorno %` de cada operación pasa a ser neto de costes.

**Verificación.** Tests nuevos: `tests/test_weekly_bars.py` (convención,
semana en curso, zonas horarias, regresión RSC con fuentes mezcladas),
`tests/test_portfolio_execution.py` (apertura vs cierre, costes exactos,
delisting, reutilización del hueco, ventana, benchmark, PF en $, top-5) y
caducidad en `tests/test_data_cache.py`. Prueba de humo del CLI completo con
datos sintéticos y descargas sustituidas: informe con benchmark y CSV
exportado correctos. **No se ha ejecutado con datos reales** (la caché está
vacía y requiere permiso de red, D1).

**Limitación aceptada.** XLC empieza en jun-2018: con la SMA de 52 semanas,
Communication Services no puede pasar F1 hasta ~jun-2019.

**Siguiente paso.** V1 (contenido del vídeo) cuando el usuario lo facilite;
mientras, R1 sin red.

---

## 2026-11-03 (3) — Intento de reescribir el historial sin coautoría (descartado)

Con permiso del usuario se reescribieron en local los 9 commits posteriores a
`8221d77` quitando la línea `Co-Authored-By` (`git filter-branch
--msg-filter`, contenido idéntico). GitHub **rechazó** el `push
--force-with-lease`: `main` está protegida (`GH006: Cannot force-push to this
branch`). No se ha saltado la protección. El usuario decidió no insistir
("no es importante"): se devolvió el local a `origin/main` (`172fdc0`) y el
trabajo posterior se reaplicó encima. Resultado: `d2a3e89`, `7b21c4f` y
`0d2ea9c` conservan la línea de coautoría; todos los commits desde `4b77170`
salen solo a nombre de `fjramirez1`. Los hashes citados en esta bitácora y en
la hoja de ruta son los de GitHub.

## 2026-11-03 (4) — Reglas del vídeo retiradas, recuperadas del historial

El usuario recuerda que el vídeo mostraba backtests por regla y que algunas
se quitaron por restar rentabilidad. Revisado el historial de git:

- `456c810` (2026-05-18) quita la entrada **Cierre > WMA30**.
- `73b185c` (2026-05-18) quita la salida **trailing stop de 15 barras**
  (cierre < mínimo de los 15 cierres semanales previos, tras más de 15
  semanas en posición; código en `weinstein_albert_exit_scanner.py` de
  `4182c36`).
- Ningún commit explica el motivo de ninguna de las dos retiradas.
- **Hallazgo:** hasta `9155c85` (2026-06-28) ambos scripts usaban Coppock
  **ROC 14 + 11**; desde la refactorización al paquete usa 12 + 6, sin
  justificación. Abierto como V2b.

Documentado en `docs/ESTRATEGIA.md` §10 y como Fase 6 (condiciones
editables) en la hoja de ruta.

**Decisión del usuario (mismo día) sobre el Coppock:** el cambio 14 + 11 →
12 + 6 pudo deberse a un backtest que lo daba más rentable, pero ese backtest
no era fiable. Ninguno de los dos valores cuenta como validado; se comparan en
O2. V2b cerrada como tarea de vídeo.

## 2026-11-03 (5) — R1: señales únicas para escáner y backtest

Petición del usuario: usar agentes en paralelo siempre que sea útil. Se
delega D1 + R3 (descarga de datos con el límite de Tiingo de 50
peticiones/hora del plan gratuito) a un agente que trabaja solo en
`weinstein/data.py`, `backtest/data_cache.py`, un módulo de descarga nuevo y
sus tests. Fallo detectado antes de lanzar la descarga: una respuesta de
"límite alcanzado" de Tiingo devolvía `None` y `get_cached_weekly` marcaba al
ticker delistado como `.nodata` **para siempre**; el agente lo corrige antes
de descargar.

R1 (`6221ec5`): `weinstein/signals.py` reúne `TickerContext`,
`build_ticker_context`, `market_state_series` y las reglas F1-F4/S1
(comparaciones válidas para escalar o serie). Los dos escáneres y
`backtest/conditions.py` las usan. Formato de los CSV sin cambios.

Verificación: `tests/test_signals_paridad.py` — 6 tickers sintéticos, 180
semanas; en cada semana se recortan todos los datos hasta esa fecha, se
ejecutan `_evaluate_ticker` y `_evaluate_exit` y se comparan con las máscaras
de entrada, S1 y S2 del backtest. Coinciden en todas las semanas, con al
menos 8 casos verdaderos y 8 falsos de entrada y de S1. Prueba de mutación:
cambiar F4 a 9 % solo en el escáner hace fallar el test (entrada T1
2023-07-07). Tests de los módulos afectados: 157 passed. (La suite completa
tenía fallos en ese momento solo en los tests de Tiingo, por el trabajo en
curso del agente.)

Herramienta: se instaló `pyflakes` en el venv para revisar importaciones
(no está en `requirements.txt`). Quitada una importación sobrante en
`backtest/portfolio_engine.py`.

## 2026-11-03 (6) — D1/R3: descarga reanudable y dos claves de Tiingo

**Trabajo del agente** (revisado; 262 tests al entregar, ningún commit con
coautoría):
- `5c395cc`: `TiingoRateLimitError` (HTTP 429, o HTTP 200 con
  `{"detail": "...allocation..."}`) nunca se confunde con "sin datos" ni
  escribe `.nodata`; contador de peticiones (alias incluidos) y presupuesto.
- `d505bca`: `python -m backtest.download_data` (R3): fase yfinance, fase
  Tiingo con presupuesto por hora/día, estado en
  `backtest/.cache/descarga_estado.json`, `--wait`. `launcher.py` eliminado.
- `5cafee5`: Wikipedia movió la tabla de cambios del S&P 500 a
  "Historical components of the S&P 500" (con una 7ª columna "Refs"); el
  universo histórico no se podía construir. Revisado: 414 cambios desde 1976,
  20-30 por año entre 2015 y 2026 (lo esperable).

**Dos claves de Tiingo** (petición del usuario, `edb4809`): claves en `.env`
como `TIINGO_API_KEY` y `TIINGO_API_KEY_2` (nunca en git ni en logs). Cada
clave tiene contador y bloqueo propios; un límite en una reintenta con otra;
el presupuesto del descargador es por clave (45/h → 90/h). Se avisó al usuario
de que usar varias cuentas gratuitas puede ir contra las condiciones de
Tiingo. `tests/conftest.py` quita las claves reales del entorno en cada test.
Bug encontrado por los tests: el diccionario `params` se reutilizaba entre
reintentos (ahora se pasa una copia por petición).

**Validación contra la API real:** en la segunda ventana la clave 1 recibió
el límite real ("You have run over your hourly request allocation"); se
detectó, se bloqueó solo esa clave y el mismo ticker (HES) se descargó con la
clave 2.

**Otros arreglos del informe del agente** (`bb30a5f`, `f5044e6`):
- `get_cached_weekly` ya no usa Tiingo para tickers vigentes (los spin-offs
  recientes FDXF, HONA, KVUE, Q, VYLR gastaban cupo en cada backtest).
- Un fallo transitorio de Tiingo (red, 5xx, token) ya no marca `.nodata`
  fuera del descargador.
- Menciones a `launcher.py` actualizadas (CLAUDE.md, BACKTEST.md, README).
- Pendiente menor, sin cambiar: `clear_cache()` también borra
  `sp500_changes.parquet` (se regenera desde Wikipedia).

**Cobertura** (10y, universo histórico, 699 tickers, 503 vigentes): tras la
primera ventana, yfinance 588, Tiingo 37, sin datos 5 (APC, BBBY, CDAY,
CSRA, ENDP), pendientes 69. Tras la segunda ventana (dos claves): +33 vía
Tiingo, 27 pendientes para la ventana de las 11:01. Cifra final: ver la
entrada siguiente.

**Cambio de criterio (mismo día, `4673e22`):** el usuario vio en Tiingo que
la segunda cuenta aún tenía 11 peticiones libres cuando nuestro presupuesto
(45/h por clave) ya daba la hora por gastada: el contador propio no coincide
con el de Tiingo. Ahora no hay tope propio por defecto: se pide hasta que
Tiingo devuelve su error de límite, que bloquea esa clave y pasa a la
siguiente; con todas limitadas se reintenta a los 10 minutos
(`TIINGO_LIMIT_RETRY_S`) en vez de esperar a la hora en punto.
`--tiingo-budget` queda como tope opcional. 276 tests.

## 2026-11-03 (7) — D1 completada: cobertura final del universo de 10 años

`python -m backtest.download_data --period 10y --universe historical --wait`
terminó a las 11:05 (salida 0). El límite real de Tiingo cortó la clave 1
(en SIVB) y la clave 2 (en TSS); tras 10 minutos se reintentó y se completó.

| | Tickers |
|---|---|
| Universo histórico 10 años (503 vigentes) | 699 |
| Datos vía yfinance | 588 |
| Datos vía Tiingo | 94 |
| Sin datos en ninguna fuente | 17 |
| Pendientes | 0 |
| Series auxiliares (^GSPC, SPY, 11 ETFs) | 13/13 |

Cobertura: 682/699 = 97,6 %. Tiingo: 120 peticiones hoy, 111/500 símbolos
del mes.

Sin datos (17): APC BBBY CDAY CSRA ENDP FDXF FRC FTR HAR HONA LLTC MNK NFX
Q SOLS SPLS VYLR. Para D2: FDXF, HONA, Q, SOLS y VYLR parecen altas
recientes con pocas velas (se reintentan solas cada semana); CDAY se
renombró a DAY (posible alias que falta en `_KNOWN_TICKER_RENAMES`); el
resto son delistados que ninguna fuente sirve (quiebras como FRC, BBBY,
ENDP, MNK, o absorciones antiguas).

## 2026-11-03 (8) — D2 y O1: universo limpio y baseline con el motor corregido

**D2** (`eba1c8a` y siguiente commit). `prepare_universe(period="10y",
universe="historical")` desde la caché (34 s):
- 79 tickers con precio pero sector "Unknown" (11,6 % del universo, nunca
  podían pasar F1): sobre todo absorciones de 2016-2019 que ahora sí tienen
  precio gracias a B1. Añadidos a `HISTORICAL_DELISTED_SECTORS` sin tocar el
  bloque existente (sin duplicados; CELG/TWTR/XLNX/ETFC/WLTW siguen). SNI y
  TWX van en Consumer Discretionary (salieron antes de la reforma GICS de
  2018). CDAY y DAY pasan a Industrials (DAY estaba como Consumer
  Discretionary; marcados "verificar").
- Alias CDAY→DAY: recuperado vía Tiingo (407 velas).
- Resultado: **683/699 con datos, 0 sin sector**. Sin datos (16): APC BBBY
  CSRA ENDP FDXF FRC FTR HAR HONA LLTC MNK NFX Q SOLS SPLS VYLR (5 altas
  recientes con < 70 velas; el resto, delistados sin fuente).

**Tramos de evaluación (decisión metodológica).** Datos 2016-11-04 →
2026-10-30; los indicadores existen desde la semana 57.
- Calibración: 2017-12-01 → 2022-12-30 (incluye la caída de 2020 y el
  mercado bajista de 2022). Aquí se comparan variantes en O2.
- Validación fuera de muestra, disjunta: 2023-01-06 → 2026-10-30. Se mira
  una sola vez, al final (O3).
- Limitación: Communication Services no puede pasar F1 hasta ~jun-2019 (XLC).

**O1** — `python -m backtest.estudios.o1_baseline` (reglas de producción:
F1-F5, S1 -0,5, S2, ranking `momentum`, 10 posiciones, $10.000). Operaciones
en `historial/backtests/o1_baseline_<tramo>.csv`.

| Modelo | Tramo | Rent. | CAGR | Máx. DD | Sharpe | Ops | Win | PF ($) | % P&L top-5 | SPY CAGR | SPY DD | SPY Sharpe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| corregido | calibración | −9,40 % | −1,92 % | −30,96 % | −0,06 | 132 | 41,7 % | 0,93 | — (P&L < 0) | 9,47 % | −31,83 % | 0,55 |
| corregido | validación | +26,75 % | 6,41 % | −19,18 % | 0,46 | 75 | 46,7 % | 1,48 | 123,6 % | 20,58 % | −16,88 % | 1,41 |
| corregido | completo | +15,47 % | 1,63 % | −30,96 % | 0,18 | 207 | 42,0 % | 1,08 | 285,3 % | 14,26 % | −31,83 % | 0,83 |
| antiguo | calibración | +2,89 % | 0,56 % | −23,75 % | 0,11 | 133 | 39,8 % | 1,16 | 218,3 % | | | |
| antiguo | validación | +33,66 % | 7,90 % | −16,61 % | 0,55 | 75 | 48,0 % | 1,65 | 98,9 % | | | |
| antiguo | completo | +37,55 % | 3,64 % | −24,54 % | 0,32 | 208 | 41,3 % | 1,29 | 93,9 % | | | |

("corregido" = apertura de la semana siguiente + 0,10 % por lado;
"antiguo" = al cierre de la señal y sin costes.)

**Conclusiones de O1.**
1. **La estrategia de producción rinde mucho menos que SPY en todos los
   tramos**: −12,6 pp de CAGR al año en el periodo completo, con Sharpe 0,18
   frente a 0,83 y un drawdown similar. No compensa ni en rentabilidad ni en
   riesgo.
2. El modelo antiguo inflaba el resultado: el CAGR del periodo completo
   pasaba de 1,63 % a 3,64 % (ejecución al cierre + costes 0). Aun así
   perdía contra SPY.
3. Las cifras de `OPTIMIZACION_BACKTEST.md` (p. ej. baseline 8y +26 %,
   combo2 +120 %) no son comparables: otro universo (sin delistados
   operables, 79 sin sector), otra ejecución y sin costes.

**Diagnóstico para O2** (periodo completo, modelo corregido):
- Mercado (desde 2017-12): F5 alcista el 41,6 % de las semanas, S2 bajista
  el 11,8 %, neutro el 46,6 %. S2 se activa 12 veces y cada vez cierra toda
  la cartera: 98 salidas, P&L +1.213 $ (retorno medio 1,5 %, 13,7 semanas).
- S1 (RSC < −0,5): 105 salidas con retorno medio 0,0 % y P&L −418 $; sale
  de operaciones casi en tablas tras ~20 semanas.
- Operación mediana −2,48 %; 17,2 semanas de media en posición.
- Mejores operaciones: TSCO +62,6 %, MPWR +54,6 %, HLT +54,4 %, APH +45,4 %,
  SEE +41,2 %.

Hipótesis a probar en O2 (en calibración): ranking (MOM elige las acciones
más extendidas), umbral de S1, Cierre > WMA30 y trailing stop del vídeo
(Fase 6, F1), parámetros del Coppock (14+11 vs 12+6), nº de posiciones.

## 2026-11-03 (9) — Verificación de sectores GICS de delistados

Un agente revisó, solo investigando, los sectores dudosos de
`HISTORICAL_DELISTED_SECTORS` con revisiones históricas de Wikipedia y
comunicados de S&P Dow Jones Indices. Criterio: el sector GICS **vigente
mientras el ticker estuvo en el índice** (el último, si cambió de sector).

Cambios aplicados en `weinstein/config.py`:
- **TTD**: Information Technology → **Communication Services** (Advertising
  desde la reforma GICS de marzo de 2023; salió del índice en 2026-09).
- **PAYC**: Information Technology → **Industrials** (Human Resource
  Services desde la reforma de 2023; salió en 2026-03).
- **TGNA**: Communication Services → **Consumer Discretionary** (salió en
  junio de 2017, antes de que la reforma de 2018 moviera Media a
  Communication Services).
- **DNB**: solo el comentario; salió del índice en abril de 2017, no en 2019.
- **CDAY / DAY**: confirmados Industrials (confianza alta); se quitan las
  marcas "verificar".

MBC y LVLT quedan como estaban (confianza media, sin evidencia en contra).
TTD y PAYC estuvieron en el índice en el tramo de validación, así que las
cifras de O1 pueden moverse algo; el baseline se recalcula dentro de O2.
`python -m pytest`: 279 passed.

## 2026-11-03 (10) — Fase 6 F1: reglas del vídeo como condiciones inactivas

- `backtest/conditions.py`: `ConditionSpec.enabled_by_default` (True salvo
  indicación). Nuevas condiciones **inactivas por defecto**:
  - `F6_cierre_sobre_wma30` (entrada): `dist_wma30_pct > min_distancia`
    (0 por defecto).
  - `S3_trailing_stop` (salida): cierre < mínimo de los `ventana` (15)
    cierres anteriores, con `min_semanas=15`.
- `min_semanas` es un parámetro que interpreta el **motor** para cualquier
  condición de salida (`ENGINE_PARAMS`): la salida solo cuenta con MÁS de N
  semanas en posición. Las condiciones sin él siguen aplicándose desde la
  semana de entrada (test de regresión: en `next_open`, S1 puede disparar
  en la propia semana de compra).
- CLI: `--enable NOMBRE` (repetible).
- Tests: `tests/test_condiciones_video.py` (11). `python -m pytest`: 290
  passed.
- Regresión con datos reales (universo guardado antes del arreglo de
  CDAY/DAY, periodo completo): la config por defecto da 209 ops / +15,19 %
  con el código anterior y con el nuevo, idénticos. Con S3 activo salió
  213 ops / +40,64 % (CAGR 3,9 %), pero esa cifra mezcla validación y **no
  se usa para decidir**; la medición válida es la de calibración en O2.
