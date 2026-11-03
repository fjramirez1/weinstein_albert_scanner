# Hoja de ruta — terminar el proyecto Weinstein-Albert

Objetivo final: entregar el escáner semanal (entrada/salida) con las reglas
**fieles al vídeo** de referencia y los parámetros **optimizados con un
backtest fiable**, más documentación de qué señales se usan y por qué.

Cómo usar este documento: es el plan vivo. Cada tarea tiene un id (`B1`,
`V2`...). Al terminar una, se marca `[x]`, se apunta el commit y se registra
el detalle en [BITACORA.md](BITACORA.md). La sección **Estado actual** (al
final) dice siempre cuál es el siguiente paso exacto.

Prioridad: las fases van en orden; dentro de cada fase, de arriba a abajo.
La Fase 1 es bloqueante: mientras el backtest tenga estos bugs, ninguna cifra
de optimización es fiable (incluidas las de `OPTIMIZACION_BACKTEST.md`).

---

## Fase 0 — Puesta en marcha ✅

- [x] Entender el repo y el estado del trabajo anterior.
- [x] Migrar `AGENTS.md` (obsoleto, no versionado) → `CLAUDE.md`.
- [x] Crear hoja de ruta + bitácora.
- [x] Revisión de código (hallazgos → Fase 1 y Fase 3).
- [x] Arreglar test que borraba la caché real (`tests/test_data_cache.py`,
      `tests/test_sp500_historical.py`).

## Fase 1 — Corregir el backtest ✅ (código; falta verificar con datos reales en D1)

Bugs encontrados en la revisión del 2026-11-03, ordenados por impacto:

- [x] **B1** `435a25c` — **Fechas Tiingo desalineadas.** yfinance etiqueta la vela semanal
      en **lunes**, Tiingo en **viernes**. El motor exige coincidencia exacta
      de fecha (`fecha in ctx.close.index`) y el RSC hace *inner join* con el
      S&P 500 → los tickers recuperados vía Tiingo (precisamente los
      delistados: SIVB, FRC, CELG, ATVI...) **nunca pueden operar**. Las 4816
      fechas de operación de los 18 CSV de `historial/backtests/` son lunes. El sesgo
      de supervivencia que el modo `historical` debía mitigar sigue intacto.
      Arreglo: normalizar el índice semanal de ambas fuentes a una misma
      convención (p. ej. viernes de cierre de semana) en `weinstein/data.py`.
- [x] **B2** `c04ef2c` — **Posiciones "zombi" en tickers que dejan de cotizar.** Si un
      ticker deja de tener datos estando en cartera, la salida no se evalúa
      nunca y la equity lo valora a **coste** para siempre (ni pérdida ni
      ganancia) y ocupa un hueco. Arreglo: cerrar al último precio conocido
      (motivo `SIN_DATOS`) y valorar huecos con el último precio (ffill).
- [x] **B3** `435a25c` — **Vela de la semana en curso.** Si se descarga a mitad de semana,
      la última vela es parcial (la caché de julio terminaba en una semana
      incompleta). Afecta a producción y backtest. Arreglo: descartar la vela
      de la semana no cerrada.
- [x] **B4** `c04ef2c` — **Ejecución en el mismo cierre que genera la señal.** Optimista:
      el escáner se ejecuta en fin de semana y la orden real entra el lunes.
      Arreglo: ejecutar en la apertura de la semana siguiente (configurable).
- [x] **B5** `4b77170` — **Umbrales duplicados** `backtest/conditions.py` tiene
      `0.10 / 8.0 / -0.5 / lookback 4` escritos a mano en vez de leerlos de
      `weinstein/config.py`. Arreglo: una única fuente de verdad.
- [x] **B6** `c04ef2c` — **Sin costes.** Añadir comisión + slippage configurables
      (p. ej. 0,1 % por lado por defecto).
- [x] **B7** `c04ef2c` — **Métricas.** Profit factor sobre % en vez de $; CAGR incluye el
      periodo de calentamiento (~1 año sin poder operar); no hay benchmark.
      Arreglo: corregir y añadir *buy & hold* del S&P 500 en el mismo periodo.
- [x] **B8** `c04ef2c` — **Validación fuera de muestra falsa** `--period 6y` vs `8y`: el
      de 8y *contiene* al de 6y y los 2 años extra son los **más antiguos**,
      no los más recientes como dice el estudio anterior. Arreglo: `--start`
      / `--end` explícitos (hecho). El esquema walk-forward concreto se
      define en O1.
- [x] **B9** `9e3f45d` — **Sectores dudosos** en `HISTORICAL_DELISTED_SECTORS` (BWA, NWL,
      MTCH, WU, HRB, DXC, FLT, KEYS — este último sigue en el índice) y
      disponibilidad de ETFs (XLC existe desde jun-2018, XLRE desde oct-2015).
      Sectores corregidos. **Limitación aceptada:** con XLC desde jun-2018 y
      una SMA de 52 semanas, los valores de Communication Services no pueden
      pasar F1 hasta ~jun-2019; los tramos de calibración deben empezar
      después o asumirlo.
- [x] **B10** `0b54a03` — **Caché sin caducidad.** Clave `(ticker, periodo)` sin fecha:
      `8y` descargado en julio no se refresca nunca. Arreglo: incluir fecha
      de fin / refrescar si la última vela es antigua.

## Fase 2 — Fidelidad al vídeo

- [ ] **V1.** Obtener el contenido del vídeo (transcripción o notas del
      usuario) y listar las reglas exactas que da.
- [ ] **V2.** Tabla regla a regla *vídeo vs código* en `docs/ESTRATEGIA.md`.
      Puntos a confirmar: WMA30 vs SMA30 (Weinstein clásico usa SMA30), escala
      del RSC Mansfield (×10 vs ×100, condiciona los umbrales 0,10 y -0,5),
      parámetros del Coppock (ROC 12+6, WMA10 — el Coppock clásico es 14+11
      mensual), definición de VPM5, regla de desempate, tamaño de cartera.
- [x] **V2b.** Coppock ROC 14 + 11 (original) vs 12 + 6 (desde `9155c85`).
      Según el usuario, probablemente se cambió porque un backtest lo daba
      más rentable, pero aquel backtest tenía los bugs de la Fase 1. Decisión
      (2026-11-03): no se resuelve con el vídeo, se mide en **O2**.
- [ ] **V3.** Corregir las discrepancias que el usuario confirme (con
      `SCANNER_LOGIC_VERSION` → v4). Esta versión fiel es el **baseline** de
      la Fase 4.

## Fase 3 — Reestructuración (lo necesario, sin reescribir por reescribir)

- [x] **R1** `6221ec5` — Módulo de señales único `weinstein/signals.py`
      usado por escáner y backtest. `tests/test_signals_paridad.py` recorta
      los datos a cada semana, ejecuta el escáner y lo compara con la máscara
      del backtest: coinciden en todas (y el test falla si se cambia un
      umbral solo en el escáner).
- [ ] **R2.** Decidir qué hacer con `strategy_backtest.py` y
      `backtest_lookback.py` (duplican lógica del motor de cartera):
      eliminar o reducir a funciones sobre el motor común.
- [x] **R3** `d505bca` — `launcher.py` eliminado; lo sustituye
      `python -m backtest.download_data` (reanudable, presupuesto horario y
      diario por clave de Tiingo, `--wait`). Varias claves: `edb4809`.
- [x] **R4.** Worktrees obsoletos y sus ramas locales eliminados (2026-11-03).
      Queda la rama remota `origin/agents/fix-test-entry-exit-same-week`
      (ya fusionada) en GitHub.

## Fase 4 — Datos y re-optimización

- [x] **D1.** Caché del universo histórico de 10 años: 682/699 tickers con datos
      (588 yfinance, 94 Tiingo, 17 sin fuente). Ver bitácora 2026-11-03 (7).
- [x] **D2.** 79 sin sector mapeados + alias CDAY→DAY: 683/699 con datos,
      0 sin sector (bitácora 2026-11-03 (8)).
- [x] **O1.** Baseline de producción con el motor corregido
      (`python -m backtest.estudios.o1_baseline`): CAGR 1,63 % frente a 14,26 %
      de SPY en 2017-12 → 2026-10. Tramos fijados: calibración 2017-12-01 →
      2022-12-30, validación 2023-01-06 → 2026-10-30. Cuando se resuelva V1,
      repetir con la versión fiel al vídeo.
- [ ] **O2.** Rehacer el barrido con presupuesto acotado (~20 configs):
      ranking, umbral S1, F1/F4, nº posiciones, parámetros del Coppock
      (14 + 11 vs 12 + 6; hoy fijos en `config.py`, habrá que exponerlos en
      `StrategyConfig`). Mirar siempre nº operaciones,
      Sharpe, drawdown, profit factor, % PnL en top-5 y vs benchmark.
- [ ] **O3.** Validar la ganadora en el tramo fuera de muestra (disjunto).
- [ ] **O4.** Decisión final documentada.

## Fase 5 — Producción y documentación final

- [ ] **P1.** Aplicar la configuración ganadora a `weinstein/config.py` y al
      escáner (incluido el ranking si cambia).
- [ ] **P2.** Reescribir `docs/ESTRATEGIA.md`: cada señal, qué mide, por qué
      está (vídeo + evidencia del backtest), parámetros y resultados.
- [ ] **P3.** Actualizar README / `backtest/BACKTEST.md`; archivar
      `OPTIMIZACION_BACKTEST.md` como histórico.
- [ ] **P4.** Ejecutar `entry` y `exit` reales (con permiso) y revisar salida.

## Fase 6 — Futuro: condiciones de entrada/salida editables

Objetivo final del backtest: poder añadir, quitar y editar condiciones de
entrada y salida sin tocar el motor. La base ya existe (`ConditionSpec` +
`StrategyConfig` en `backtest/conditions.py` / `strategy_config.py`); falta
ampliar el catálogo y hacerlo cómodo de usar.

- [ ] **F1.** Registrar las reglas del vídeo que no están en producción
      (`docs/ESTRATEGIA.md` §10) como condiciones **desactivadas por
      defecto**: entrada `Cierre > WMA30` y salida `trailing stop de 15
      barras`. Medirlas con el motor corregido (puede adelantarse a O2: es
      barato y responde si su retirada estaba justificada).
- [ ] **F2.** Definir configuraciones en fichero (YAML/JSON) en vez de flags
      sueltos: activar/desactivar condiciones, umbrales y ranking.
- [ ] **F3.** Condiciones parametrizables genéricas (p. ej. "indicador X
      mayor/menor que umbral") para no escribir una función por regla.

---

## Estado actual

- **Fase 1:** ✅ código corregido y con tests (229 passed). Sin verificar
  todavía con datos reales: se verá en D1/D2.
- **D1:** ✅ caché completa (10y, universo histórico, 97,6 % con datos).
- **Hallazgo O1:** la estrategia de producción rinde ~12,6 pp/año menos que
  SPY con un riesgo similar. El objetivo de O2 es comprobar si alguna variante
  razonable lo corrige; si ninguna lo hace, documentarlo.
- **Hecho para O2:** parámetros del Coppock en `StrategyConfig`
  (`coppock_roc_long/short`, `coppock_wma`, `coppock_lookback`); si difieren
  de `config.py` el motor recalcula F5/S2.
- **Siguiente paso:** F1 de la Fase 6. Registrar en `backtest/conditions.py`,
  desactivadas por defecto, la entrada `F6_cierre_sobre_wma30`
  (dist_wma30_pct > 0) y la salida `S3_trailing_stop` (cierre < mínimo de los
  15 cierres previos, solo con más de 15 semanas en posición: el motor debe
  comprobar las semanas desde la entrada). Después, el estudio O2
  (`backtest/estudios/o2_barrido.py`, ~20 configs SOLO en calibración
  2017-12-01 → 2022-12-30).
- **Sectores GICS de delistados:** verificados (bitácora 2026-11-03 (9)).
- **Pendiente del usuario:** contenido del vídeo (V1).
- **Caché:** repoblada el 2026-11-03 (`backtest/.cache/`, periodo `10y`).
