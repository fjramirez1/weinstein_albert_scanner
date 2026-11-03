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

## Fase 1 — Corregir el backtest (bloqueante)

Bugs encontrados en la revisión del 2026-11-03, ordenados por impacto:

- [ ] **B1. Fechas Tiingo desalineadas.** yfinance etiqueta la vela semanal
      en **lunes**, Tiingo en **viernes**. El motor exige coincidencia exacta
      de fecha (`fecha in ctx.close.index`) y el RSC hace *inner join* con el
      S&P 500 → los tickers recuperados vía Tiingo (precisamente los
      delistados: SIVB, FRC, CELG, ATVI...) **nunca pueden operar**. Las 4816
      fechas de operación de los 18 CSV de `historial/backtests/` son lunes. El sesgo
      de supervivencia que el modo `historical` debía mitigar sigue intacto.
      Arreglo: normalizar el índice semanal de ambas fuentes a una misma
      convención (p. ej. viernes de cierre de semana) en `weinstein/data.py`.
- [ ] **B2. Posiciones "zombi" en tickers que dejan de cotizar.** Si un
      ticker deja de tener datos estando en cartera, la salida no se evalúa
      nunca y la equity lo valora a **coste** para siempre (ni pérdida ni
      ganancia) y ocupa un hueco. Arreglo: cerrar al último precio conocido
      (motivo `DELISTED`) y valorar huecos con el último precio (ffill).
- [ ] **B3. Vela de la semana en curso.** Si se descarga a mitad de semana,
      la última vela es parcial (la caché de julio terminaba en una semana
      incompleta). Afecta a producción y backtest. Arreglo: descartar la vela
      de la semana no cerrada.
- [ ] **B4. Ejecución en el mismo cierre que genera la señal.** Optimista:
      el escáner se ejecuta en fin de semana y la orden real entra el lunes.
      Arreglo: ejecutar en la apertura de la semana siguiente (configurable).
- [ ] **B5. Umbrales duplicados.** `backtest/conditions.py` tiene
      `0.10 / 8.0 / -0.5 / lookback 4` escritos a mano en vez de leerlos de
      `weinstein/config.py`. Arreglo: una única fuente de verdad.
- [ ] **B6. Sin costes.** Añadir comisión + slippage configurables
      (p. ej. 0,1 % por lado por defecto).
- [ ] **B7. Métricas.** Profit factor sobre % en vez de $; CAGR incluye el
      periodo de calentamiento (~1 año sin poder operar); no hay benchmark.
      Arreglo: corregir y añadir *buy & hold* del S&P 500 en el mismo periodo.
- [ ] **B8. Validación fuera de muestra falsa.** `--period 6y` vs `8y`: el
      de 8y *contiene* al de 6y y los 2 años extra son los **más antiguos**,
      no los más recientes como dice el estudio anterior. Arreglo: `--start`
      / `--end` explícitos y esquema walk-forward (calibrar en un tramo,
      validar en otro disjunto).
- [ ] **B9. Sectores dudosos** en `HISTORICAL_DELISTED_SECTORS` (BWA, NWL,
      MTCH, WU, HRB, DXC, FLT, KEYS — este último sigue en el índice) y
      disponibilidad de ETFs (XLC existe desde jun-2018, XLRE desde oct-2015).
- [ ] **B10. Caché sin caducidad.** Clave `(ticker, periodo)` sin fecha:
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
- [ ] **V3.** Corregir las discrepancias que el usuario confirme (con
      `SCANNER_LOGIC_VERSION` → v4). Esta versión fiel es el **baseline** de
      la Fase 4.

## Fase 3 — Reestructuración (lo necesario, sin reescribir por reescribir)

- [ ] **R1.** Un único módulo de señales vectorizado usado por escáner Y
      backtest (hoy el escáner calcula escalares y el backtest series; pueden
      divergir). Test: el escáner sobre la última semana == máscara del
      backtest en esa semana.
- [ ] **R2.** Decidir qué hacer con `strategy_backtest.py` y
      `backtest_lookback.py` (duplican lógica del motor de cartera):
      eliminar o reducir a funciones sobre el motor común.
- [ ] **R3.** Sustituir `launcher.py` (bucle infinito cada hora para sortear
      el límite de Tiingo) por un comando de descarga reanudable que respete el
      límite y termine.
- [ ] **R4.** Limpiar worktrees obsoletos en `../weinstein_albert_scanner.worktrees/`
      (ramas ya fusionadas en `main`) — requiere OK del usuario.

## Fase 4 — Datos y re-optimización

- [ ] **D1.** Re-descargar la caché (con permiso: red, Tiingo con límite).
- [ ] **D2.** Diagnóstico de cobertura del universo histórico (cuántos
      tickers sin precio / sin sector) — antigua "Fase 8".
- [ ] **O1.** Baseline fiel al vídeo + benchmark, en tramo de calibración.
- [ ] **O2.** Rehacer el barrido con presupuesto acotado (~20 configs):
      ranking, umbral S1, F1/F4, nº posiciones. Mirar siempre nº operaciones,
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

---

## Estado actual

- **Fase en curso:** Fase 1.
- **Siguiente paso:** B1 — normalizar el índice semanal en
  `weinstein/data.py::download_weekly` / `download_weekly_tiingo` + test que
  cubra una serie Tiingo (viernes) contra el S&P 500 (lunes).
- **Pendiente del usuario:** acceso al contenido del vídeo (V1) y OK para
  borrar los worktrees obsoletos (R4).
- **Caché:** `backtest/.cache/` está **vacía** (borrada por el test
  defectuoso el 2026-11-03). Se regenera en D1; hasta entonces cualquier
  backtest descargará de red.
