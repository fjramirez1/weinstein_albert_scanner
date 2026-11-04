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

## 2026-11-03 (11) — O2 ronda 1: un cambio cada vez, solo calibración

Comando: `python -m backtest.estudios.o2_barrido --ronda 1` (tabla completa,
con rentabilidad por año, en `historial/backtests/o2_barrido_calibracion_r1.csv`).
Tramo 2017-12-01 → 2022-12-30, `next_open`, 0,10 %/lado, 10 posiciones.
Las cifras del baseline coinciden con O1 (los sectores corregidos en (9)
solo afectan a validación).

| Variante | CAGR | Exceso vs SPY | Máx. DD | Sharpe | Ops | PF ($) | % top-5 | Años > SPY |
|---|---|---|---|---|---|---|---|---|
| baseline | −1,92 % | −11,4 pp | −31,0 % | −0,06 | 132 | 0,93 | — | 1 |
| rank_rsc_activo | 2,97 % | −6,5 | −24,9 % | 0,26 | 133 | 1,31 | 146 % | 2 |
| rank_vpm5 | 3,16 % | −6,3 | −23,8 % | 0,27 | 136 | 1,33 | 143 % | 1 |
| s1_-0.25 | −2,81 % | −12,3 | −27,5 % | −0,12 | 153 | 0,87 | — | 1 |
| s1_-1.0 | −2,77 % | −12,2 | −30,7 % | −0,10 | 114 | 0,85 | — | 1 |
| s1_off | −0,42 % | −9,9 | −27,9 % | 0,05 | 89 | 1,08 | 727 % | 1 |
| s2_off | 3,22 % | −6,2 | −33,1 % | 0,26 | 62 | 1,05 | 1309 % | 2 |
| f1_0.0 | −2,62 % | −12,1 | −32,7 % | −0,10 | 131 | 0,88 | — | 1 |
| f1_off | −0,77 % | −10,2 | −28,3 % | 0,03 | 134 | 0,99 | — | 2 |
| f4_5 | −4,05 % | −13,5 | −30,2 % | −0,16 | 147 | 0,77 | — | 0 |
| f4_12 | 2,61 % | −6,9 | −23,7 % | 0,24 | 125 | 1,29 | 158 % | 1 |
| f4_off | 3,27 % | −6,2 | −32,9 % | 0,26 | 121 | 1,25 | 252 % | 3 |
| f6_on (cierre > WMA30) | −2,59 % | −12,1 | −31,0 % | −0,11 | 133 | 0,89 | — | 1 |
| s3_on (trailing 15, >15 sem.) | 2,36 % | −7,1 | −21,7 % | 0,24 | 132 | 1,30 | 132 % | 1 |
| s3_sin_min_semanas | 2,72 % | −6,8 | −21,2 % | 0,27 | 139 | 1,30 | 126 % | 1 |
| video_f6_s3 | 1,52 % | −8,0 | −23,9 % | 0,18 | 133 | 1,22 | 170 % | 1 |
| coppock_14_11 | 0,40 % | −9,1 | −27,2 % | 0,10 | 114 | 1,03 | 1289 % | 2 |
| coppock_14_11_s3 | 2,32 % | −7,2 | −20,5 % | 0,23 | 113 | 1,21 | 234 % | 2 |
| pos_5 | −2,07 % | −11,5 | −34,9 % | −0,05 | 67 | 0,90 | — | 1 |
| pos_20 | −0,09 % | −9,6 | −25,4 % | 0,07 | 267 | 1,07 | 350 % | 1 |
| **f5_off** | **6,79 %** | **−2,7** | −28,1 % | **0,45** | 444 | 1,30 | **94 %** | 2 |
| combo_f6_s3_rsc | 0,21 % | −9,3 | −23,3 % | 0,09 | 137 | 1,08 | 512 % | 1 |
| *SPY* | *9,47 %* | | *−31,8 %* | *0,55* | | | | |

Años del baseline frente a SPY: 2018 +0,9 / −5,4; 2019 +17,4 / +32,8;
**2020 −13,8 / +16,4**; 2021 +15,9 / +30,4; 2022 −21,9 / −18,2.

**Lectura.**
1. **Ninguna variante bate a SPY en calibración.** La mejor (quitar F5)
   se queda a −2,7 pp/año y con Sharpe 0,45 frente a 0,55.
2. **El filtro de mercado es lo que más resta.** Sin F5 el CAGR pasa de
   −1,9 % a 6,8 % y la concentración baja (top-5 = 94 % del P&L, la única
   por debajo del 100 %). El Coppock clásico 14+11 mejora algo al 12+6
   (0,4 % frente a −1,9 %), pero no compensa. En 2020 la estrategia sale
   con S2 cerca del mínimo y F5 tarda en dejar volver a entrar.
3. **Sin F5 hay mucha rotación**: 444 ops y 1.066 $ de costes, porque S2
   cierra la cartera y a la semana siguiente vuelve a comprar.
4. Mejoras moderadas (≈ +4-5 pp): ranking por RSC o VPM5 en vez de MOM
   (MOM elige las acciones más extendidas), F4 más laxo o sin F4, quitar
   S2, y el trailing stop S3, que además reduce el drawdown (−21,7 % frente
   a −31,0 %).
5. Empeoran: endurecer F4 (5 %), cambiar el umbral de S1 en cualquier
   sentido, F1 más laxo y **F6 (cierre > WMA30)**: el vídeo tenía razón al
   retirarla. El trailing stop, en cambio, **sí aporta** con el motor
   corregido, al contrario de lo que se concluyó al retirarlo.
6. `s2_off`, `s1_off` y `coppock_14_11` tienen un % top-5 > 700 %: su
   resultado depende de unas pocas operaciones y no es fiable.

Siguiente: ronda 2 con combinaciones de lo que mejora (sin F5, sin S2,
ranking RSC/VPM5, S3, F4 laxo).

## 2026-11-03 (12) — O2 ronda 2: combinaciones, solo calibración

Comando: `python -m backtest.estudios.o2_barrido --ronda 2`
(`historial/backtests/o2_barrido_calibracion_r2.csv`). Mismo tramo y modelo.

| Variante | CAGR | Exceso | Máx. DD | Sharpe | Ops | PF ($) | % top-5 | Años > SPY | Costes |
|---|---|---|---|---|---|---|---|---|---|
| baseline | −1,92 % | −11,4 pp | −31,0 % | −0,06 | 132 | 0,93 | — | 1 | 271 $ |
| f5_off | 6,79 % | −2,7 | −28,1 % | 0,45 | 444 | 1,30 | 94 % | 2 | 1.066 $ |
| f5_off_s2_off | 12,21 % | +2,7 | −29,2 % | 0,63 | 50 | 2,97 | 93 % | 3 | 120 $ |
| f5_off_s3 | 3,84 % | −5,6 | −30,9 % | 0,29 | 461 | 1,14 | 147 % | 2 | 1.010 $ |
| f5_off_s2_off_s3 | 6,01 % | −3,5 | −26,8 % | 0,39 | 91 | 1,33 | 145 % | 1 | 205 $ |
| f5_off_rsc | 6,68 % | −2,8 | −28,4 % | 0,42 | 448 | 1,31 | 92 % | 3 | 1.063 $ |
| f5_off_vpm5 | 13,65 % | +4,2 | −25,2 % | 0,71 | 452 | 1,62 | 63 % | 3 | 1.247 $ |
| f5_off_rsc_s3 | 4,94 % | −4,5 | −30,1 % | 0,34 | 464 | 1,21 | 115 % | 2 | 1.049 $ |
| f5_off_s2_off_rsc_s3 | 1,22 % | −8,2 | −36,0 % | 0,17 | 96 | 1,03 | 1440 % | 1 | 206 $ |
| f5_off_f4_off | 2,72 % | −6,7 | −31,1 % | 0,23 | 447 | 1,09 | 176 % | 2 | 942 $ |
| f5_off_f4_12_rsc_s3 | 1,15 % | −8,3 | −29,1 % | 0,16 | 457 | 1,07 | 270 % | 0 | 943 $ |
| f5_off_coppock_14_11 | 3,62 % | −5,9 | −28,8 % | 0,28 | 502 | 1,13 | 155 % | 1 | 1.126 $ |
| f5_off_coppock_14_11_rsc_s3 | 1,98 % | −7,5 | −35,8 % | 0,20 | 521 | 1,06 | 294 % | 1 | 1.078 $ |
| f5_off_rsc_s3_pos20 | 3,58 % | −5,9 | −28,6 % | 0,28 | 923 | 1,14 | 84 % | 2 | 1.015 $ |
| rsc_s3 | 3,32 % | −6,2 | −22,1 % | 0,28 | 136 | 1,33 | 144 % | 2 | 317 $ |
| rsc_s3_f4_12 | 5,73 % | −3,7 | −20,6 % | 0,41 | 128 | 1,74 | 70 % | 2 | 317 $ |
| rsc_s3_s2_off | −0,20 % | −9,7 | −29,5 % | 0,09 | 83 | 0,96 | — | 1 | 174 $ |
| *SPY* | *9,47 %* | | *−31,8 %* | *0,55* | | | | | |

**Lectura.**
1. Los efectos **no son aditivos**: lo que mejoraba por separado empeora al
   combinarlo (S3 restaba en todas las combinaciones sin F5; con F5 activo
   sumaba). Con F5 y S2 activos o no, el ranking cambia el resultado en
   ±7 pp (`f5_off_rsc` 6,7 % frente a `f5_off_vpm5` 13,7 %).
2. Dos variantes superan a SPY en calibración: `f5_off_vpm5` (+4,2 pp,
   Sharpe 0,71, top-5 63 %) y `f5_off_s2_off` (+2,7 pp, pero solo 50 ops en
   5 años: casi comprar y mantener 10 acciones).
3. Sin F5 pero con S2, el motor vende toda la cartera cada semana bajista y
   recompra a la siguiente (≈ 400 salidas S2): es una rotación semanal
   forzada en los mercados bajistas, no una regla de Weinstein.
4. Esta sensibilidad sugiere que buena parte de la diferencia es **ruido de
   selección** (qué 10 acciones de entre muchos candidatos). Antes de elegir
   se mide con rankings aleatorios (ronda 3).

## 2026-11-03 (13) — O2 rondas 3 y 4: robustez frente a rankings aleatorios

Comandos: `python -m backtest.estudios.o2_barrido --ronda 3` y `--ronda 4`
(`historial/backtests/o2_barrido_calibracion_r{3,4}.csv` y `_r{3,4}_resumen.csv`).
Cada conjunto de reglas se ejecuta con los 3 rankings reales y con 20
rankings aleatorios reproducibles (crc32 de semilla, ticker y semana). La
distribución del azar dice cuánto del resultado es suerte en la selección.
Nueva condición inactiva por defecto para la ronda 4:
`F5b_mercado_no_bajista` (entra si el Coppock está alcista **o neutro**).

| Reglas | Azar p10 | Azar mediana | Azar p90 | Sharpe mediano | DD mediano | MOM (pct) | RSC (pct) | VPM5 (pct) |
|---|---|---|---|---|---|---|---|---|
| producción (F5 + S2) | −2,30 % | 1,23 % | 3,00 % | 0,16 | −28,3 % | −1,92 % (15) | 2,97 % (90) | 3,16 % (90) |
| F5b + S2 | 0,93 % | 3,41 % | 5,26 % | 0,28 | −28,0 % | 0,70 % (10) | 4,11 % (80) | 7,18 % (100) |
| F5b + S2 + S3 | 1,42 % | 3,12 % | 5,23 % | 0,26 | −28,2 % | 1,68 % (15) | 3,29 % (50) | 6,14 % (95) |
| F4 12 % + S3 | 0,51 % | 3,22 % | 5,16 % | 0,28 | −24,6 % | 3,16 % (50) | 5,73 % (95) | 3,66 % (60) |
| sin F5 (con S2) | 4,26 % | 7,60 % | 10,40 % | 0,45 | −30,3 % | 6,79 % (35) | 6,68 % (35) | 13,65 % (100) |
| sin F5 ni S2 | 5,36 % | 7,90 % | 10,36 % | 0,46 | −31,6 % | 12,21 % (100) | 9,62 % (70) | 5,76 % (20) |

(pct = % de las 20 semillas aleatorias que quedan por debajo. SPY en el
tramo: 9,47 %, Sharpe 0,55, DD −31,8 %.)

**Conclusiones de O2 (calibración).**
1. **El filtro de mercado del Coppock resta rentabilidad**, y es el efecto
   más robusto del estudio: la mediana con ranking aleatorio sube de forma
   monótona al relajarlo (1,2 % → 3,4 % → 7,6 % → 7,9 %), y el p10 sin F5
   supera al p90 de producción. El tramo incluye la caída y el rebote en V
   de 2020, que castiga mucho a un filtro lento.
2. **MOM, el ranking de producción, es peor que el azar** en 4 de 6
   conjuntos (percentil mediano ≈ 25). Elige las acciones más extendidas
   sobre su WMA30.
3. **VPM5 es el ranking más consistente** (≥ 90 en 4 de 6, mediana ≈ 92);
   RSC queda segundo (mediana ≈ 75). Las diferencias entre rankings son del
   mismo orden que la dispersión del azar, así que es evidencia débil.
4. Ningún conjunto de reglas bate a SPY con un ranking típico. Solo algunas
   combinaciones concretas lo hacen, y eso es elegir el máximo de una
   distribución ruidosa.
5. S1 (umbral −0,5) y F1 (0,10) ya estaban en su mejor valor del barrido;
   F6 empeora; S3 ayuda solo con el filtro de mercado activo.

## 2026-11-03 (14) — Pre-registro de O3 (antes de mirar validación)

Escrito y commiteado **antes** de ejecutar nada en validación
(2023-01-06 → 2026-10-30), para que no se pueda ajustar a posteriori.

- **Candidato elegido (por reglas robustas, no por el máximo):** reglas
  "sin F5 ni S2" (mejor mediana con azar, menos operaciones y costes,
  concentración baja) + ranking **VPM5** (el más consistente frente al
  azar). Es decir: F1-F4 de entrada, S1 de salida, sin filtro de mercado.
  Su cifra concreta en calibración es mediocre (5,76 %, percentil 20), y
  aun así se elige porque la elección se basa en lo que fue robusto.
- **Se ejecutan en validación**, con 3 rankings reales + 20 aleatorios, los
  conjuntos producción, F5b + S2, sin F5 y sin F5 ni S2.
- **Hipótesis:**
  - H1: la mediana con azar de "sin F5" y "sin F5 ni S2" supera a la de
    producción.
  - H2: VPM5 supera la mediana del azar en la mayoría de los conjuntos y
    MOM no.
  - H3: el candidato supera al baseline de producción (MOM) en CAGR y
    Sharpe.
- **Regla de decisión (O4):** el candidato pasa a producción solo si se
  cumplen H1 y H3, y se documenta su diferencia con SPY sea cual sea. Si
  H1 falla, se mantiene producción y se documenta que el estudio no
  encontró mejoras robustas.

## 2026-11-03 (15) — O3: validación fuera de muestra (una sola ejecución)

Comando: `python -m backtest.estudios.o3_validacion`
(`historial/backtests/o3_validacion.csv` y `o3_validacion_resumen.csv`).
Tramo 2023-01-06 → 2026-10-30, el mismo modelo que O2 y lo pre-registrado
en (14), sin cambios.

| Reglas | Azar p10 | Azar mediana | Azar p90 | Sharpe mediano | MOM (pct) | RSC (pct) | VPM5 (pct) |
|---|---|---|---|---|---|---|---|
| producción (F5 + S2) | 7,47 % | **9,89 %** | 11,80 % | 0,65 | 6,41 % (0) | 12,07 % (90) | 14,68 % (95) |
| F5b + S2 | 6,77 % | 8,73 % | 14,49 % | 0,60 | 11,19 % (70) | 13,32 % (85) | 19,67 % (100) |
| sin F5 (con S2) | 0,71 % | 6,42 % | 9,43 % | 0,44 | 4,98 % (35) | 13,78 % (95) | 16,49 % (100) |
| sin F5 ni S2 | 4,74 % | 8,68 % | 14,48 % | 0,57 | 16,29 % (100) | 10,96 % (60) | 16,61 % (100) |

| Config | CAGR | Máx. DD | Sharpe | Ops | PF ($) | % top-5 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|---|---|
| producción + MOM (baseline actual) | 6,41 % | −19,2 % | 0,46 | 75 | 1,48 | 124 % | 14,1 | 22,0 | −1,0 | −8,0 |
| producción + VPM5 | 14,68 % | −13,4 % | 0,93 | 76 | 2,25 | 81 % | 16,2 | 19,4 | 20,7 | 0,7 |
| F5b + VPM5 | 19,67 % | −13,8 % | 1,13 | 89 | 2,59 | 78 % | 15,9 | 26,3 | 34,4 | 0,8 |
| **candidato: sin F5 ni S2 + VPM5** | 16,61 % | −21,1 % | 0,95 | 69 | 2,50 | 119 % | 18,0 | 46,1 | 8,1 | −3,6 |
| *SPY* | *20,58 %* | *−16,9 %* | *1,41* | | | | *24,3* | *26,8* | *17,4* | *10,3* |

(*2026 hasta el 30 de octubre.)

**Hipótesis pre-registradas.**
- **H1: NO se cumple.** En validación, quitar el filtro de mercado no mejora
  la mediana con ranking aleatorio: producción 9,89 % frente a 6,42 % (sin
  F5) y 8,68 % (sin F5 ni S2). El efecto de O2 dependía del régimen de
  calibración (el rebote en V de 2020).
- **H2: SÍ.** VPM5 supera la mediana del azar en 4/4 conjuntos (percentiles
  95, 100, 100 y 100); MOM solo en 2/4 (0, 70, 35 y 100). Contando
  calibración y validación, VPM5 queda por encima de la mediana en 9 de 10
  comparaciones y MOM en 4 de 10.
- **H3: SÍ.** Candidato 16,61 % / Sharpe 0,95 frente a 6,41 % / 0,46.

**Aplicación de la regla de decisión (14):** requería H1 **y** H3. H1 falla,
así que **el candidato "sin F5 ni S2" no pasa a producción**: las reglas
F1-F5 / S1-S2 se mantienen.

**Lo que sí es robusto en los dos tramos:** cambiar el ranking de MOM a
VPM5. Con las reglas de producción, VPM5 mejora en calibración (3,16 %
frente a −1,92 %, percentil 90) y en validación (14,68 % frente a 6,41 %,
Sharpe 0,93 frente a 0,46, DD −13,4 % frente a −19,2 %, top-5 81 %). H2
estaba pre-registrada, pero el cambio de ranking por sí solo no era el
candidato. Como decisión de O4 se propone al usuario, que decide.

**En ningún tramo la estrategia bate a SPY de forma robusta.** La mejor
config de validación (F5b + VPM5, 19,67 %) se queda a 0,9 pp, y el tramo
de validación ya está usado, así que elegirla ahora sería sobreajustar.

## 2026-11-04 (1) — Fase 4b: ampliar el backtest hacia atrás por tramos

**Acuerdo con el usuario.** El sistema de producción no se toca hasta
terminar el estudio del backtest (O4 aplazada). El rango se amplía hacia
atrás por tramos, todo lo que se pueda. Cada tramo se da por cerrado cuando
sus años tienen datos fiables (membresía, precios, sector, ETF).

**Infraestructura** (commits `1f6de68`, `3e1d5c2`, `dc5841f`):
- Caché de histórico completo: `--period max`, con el universo acotado por
  `--desde` (`prepare_universe(desde=...)`, `download_data --desde`,
  `run_portfolio_backtest --desde`). Cada ticker se descarga una sola vez
  con toda su historia; los tramos siguientes solo añaden tickers nuevos.
  Tiingo pide ahora los años del periodo (`period_to_years`: "10y" → 11,
  "max" → 60); antes pedía siempre 15.
- Lector de la tabla de Wikipedia: recortaba mal tickers con restos de
  formato ("ITT |", "JCP |", "ALLE |"). Corregido y regenerada la caché.
- ETFs sustitutos antes de su lanzamiento (`SECTOR_ETF_PROXIES`): XLRE ←
  IYR (desde 2000-06), XLC ← VOX (desde 2004-10), empalmados por escala
  el primer día común. Sin ellos, Real Estate no podía pasar F1 antes de
  2015-10 ni Communication Services antes de 2018-06.
- `save_state` del descargador reintenta `os.replace` ante PermissionError
  de Windows (fallo intermitente visto en los tests).
- Nuevo `python -m backtest.estudios.cobertura --desde AAAA-MM-DD`:
  cobertura por año (semanas-miembro con precio, sector y ETF) y tickers
  problemáticos (sin datos, ticker reutilizado por otra empresa, parcial).

**Fuente de membresía anterior a 2011** (un agente lo investigó; no tocó
el repo):
- Desde 2011, la tabla de Wikipedia y el dataset fja05680/sp500 (GitHub,
  derivado de Norgate) coinciden casi exactamente en altas y bajas por año
  (p. ej. 2012: 18/18 en ambas). Las diferencias de conjuntos son sobre
  todo renombres (FB↔META, ANTM↔ELV, BLL↔BALL...).
- Antes de 2011 Wikipedia solo recoge entre el 0 y el 35 % de los cambios
  (2008: 8 frente a 35), y la reconstrucción da más de 500 miembros (516
  en 2005). **Para ≤ 2010 hay que usar fja**: el fichero original
  (1996 → 2019-01, tickers deslistados con sufijo `-YYYYMM`), no el
  "Updated", que al quitar los sufijos fusiona empresas distintas (C /
  C-199811, JCI / JCI-201609...).
- Riesgos para los tramos antiguos: tickers reutilizados por otra empresa
  (52 en fja), símbolos de 2019 en lugar de los actuales (hace falta un
  mapa de alias) y, sobre todo, **cobertura de precios de los
  deslistados**.

**Tramo 1 (2011-2016), en curso:** membresía de Wikipedia.
- `python -m backtest.download_data --period max --universe historical --desde 2011-01-01 --wait`
- Un agente busca el sector GICS de los 123 tickers que salieron en
  2011-2016 sin sector en `config.py`, en su época y con la estructura
  actual.
