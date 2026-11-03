# CLAUDE.md — instrucciones para agentes de IA

Escáner semanal del S&P 500 basado en el método Weinstein (versión "Albert",
del vídeo <https://youtu.be/reQWjzedlX0>) más un backtest de cartera para
validar y optimizar las reglas. Todo el proyecto (código, comentarios,
documentación, commits) está en **español**.

## Antes de hacer nada en una sesión nueva

1. Lee **[docs/HOJA_DE_RUTA.md](docs/HOJA_DE_RUTA.md)** → sección "Estado actual"
   (qué fase está en curso y cuál es el siguiente paso exacto).
2. Lee la última entrada de **[docs/BITACORA.md](docs/BITACORA.md)**.
3. Trabaja la siguiente tarea pendiente de mayor prioridad, salvo que el
   usuario pida otra cosa.

### Al terminar cada tarea (no al final de la sesión)

- Marca la tarea en `docs/HOJA_DE_RUTA.md` y actualiza "Estado actual" con el
  siguiente paso concreto (un comando o una tarea, no "seguir con la fase X").
- Añade una entrada a `docs/BITACORA.md` (fecha, qué se hizo, decisiones,
  cifras exactas y el comando que las generó). La bitácora es *append-only*:
  si una conclusión anterior resulta errónea, se anota la corrección, no se
  borra.
- Motivo: el chat se compacta o se cambia; estos dos ficheros son la única
  memoria compartida entre sesiones.

## Estructura

| Ruta | Qué es |
|---|---|
| `weinstein/` | Paquete de producción: `config.py` (umbrales, única fuente de verdad), `indicators.py` (WMA, RSC Mansfield, VPM5, Coppock), `data.py` (yfinance + fallback Tiingo), `scanner_entry.py`, `scanner_exit.py`, `exporter.py`, `__main__.py` (CLI) |
| `backtest/` | Backtests: `portfolio_backtest.py` + `portfolio_engine.py` (cartera, el principal), `conditions.py` / `strategy_config.py` (reglas configurables), `sp500_historical.py` (membresía histórica), `data_cache.py`, `strategy_backtest.py` (por ticker), `backtest_lookback.py` |
| `tests/` | pytest, 200+ tests offline con datos sintéticos |
| `docs/` | `ESTRATEGIA.md` (reglas en producción), `HOJA_DE_RUTA.md`, `BITACORA.md` |
| `historial/` | CSVs generados por los escáneres y backtests (solo histórico, no fuente de verdad) |
| `OPTIMIZACION_BACKTEST.md` | Estudio de optimización anterior (julio 2026). **Conclusiones invalidadas** por bugs encontrados después, ver hoja de ruta |

## Comandos

```bash
venv\Scripts\activate                       # Windows (Python 3.13 en el venv)
pip install -r requirements.txt
python -m pytest                            # tests offline (excluye -m network)
python -m weinstein entry                   # escáner de entrada (red)
python -m weinstein exit                    # escáner de salida sobre posiciones.csv (red)
python -m weinstein portfolio-backtest --universe historical --period 8y   # (red + caché)
```

## Reglas

- **Red**: los escáneres y backtests descargan datos de mercado (yfinance,
  Tiingo, Wikipedia, GitHub). Pide permiso antes de lanzar ejecuciones que
  descarguen el universo completo. Tiingo (gratis) tiene límite de peticiones
  por hora: no lances descargas masivas contra él sin avisar.
- **Tests nunca tocan datos reales**: cualquier test que use caché o ficheros
  debe redirigir `CACHE_DIR` / rutas a `tmp_path` con `monkeypatch`. (Un
  fixture antiguo borró `backtest/.cache/` real; ver bitácora 2026-11-03.)
- **No commitear** `backtest/.cache/`, `.env` ni datos de mercado descargados.
- **`.env`** contiene `TIINGO_API_KEY`: no leer su valor, no imprimirlo, no
  enviarlo a ningún sitio.
- **CSV de posiciones** (`posiciones.csv`): conservar columnas `Ticker`,
  `Sector`, `Precio_Entrada`, `Fecha_Entrada` salvo migración acordada.
- **Cambios de lógica**: si cambia el significado de una condición F1-F5 /
  S1-S2, incrementar `SCANNER_LOGIC_VERSION` en `weinstein/config.py` y
  actualizar `docs/ESTRATEGIA.md`.
- **Optimización**: ningún cambio de parámetro llega a `weinstein/config.py`
  sin evidencia registrada en la bitácora (comando + métricas + chequeo de
  concentración en outliers + comparación con benchmark) y validación fuera
  de muestra real.
- No crear tareas programadas / bucles (cron, `launcher.py`) sin confirmación.
- **Git**: hay permiso para `commit` y `push` a `origin` para mantener un
  historial ordenado (un commit por bloque lógico: fix, refactor, docs...,
  mensajes en español). Autor **solo** con la config local del repo
  (`user.name=fjramirez1`, `user.email=fj.ramirezlopez@um.es`, ya fijada con
  `git config --local`); nunca tocar la config global. **Sin** líneas
  `Co-Authored-By` ni otra atribución a la IA en commits o PRs: el único
  autor visible debe ser `fjramirez1`. Antes de commitear, `python -m pytest`
  debe pasar.
- **Sin carpetas extra**: no crear worktrees ni copias del repo; trabajar
  siempre en esta carpeta.
