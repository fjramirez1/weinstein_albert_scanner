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
