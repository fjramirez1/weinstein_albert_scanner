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
