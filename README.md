# Weinstein Albert Scanner

Utilidades en Python para ejecutar una estrategia semanal inspirada en el método Weinstein:
detección de candidatos de entrada y evaluación de salidas para posiciones abiertas.

## Estructura del proyecto

```
weinstein/                  ← paquete principal
│   __init__.py
│   __main__.py             ← CLI unificado (python -m weinstein)
│   config.py                ← todos los parámetros en un único lugar
│   indicators.py             ← cálculos técnicos (WMA, RSC, VPM5, Coppock, MOM)
│   data.py                  ← descarga de precios y carga de tickers S&P 500
│   scanner_entry.py          ← lógica del escáner de entrada
│   scanner_exit.py           ← lógica del escáner de salida
│   exporter.py               ← exportación CSV con historial
│
posiciones.csv               ← tus posiciones abiertas
requirements.txt
pytest.ini                   ← configuración de tests
│
scripts/
│   run_entry.sh / run_entry.bat
│   run_exit.sh  / run_exit.bat
│
historial/
│   entradas/                ← CSVs generados por el escáner de entrada
│   salidas/                 ← CSVs generados por el escáner de salida
│
tests/                       ← suite de tests (pytest)
│   conftest.py               ← fixtures compartidas
│   test_indicators.py        ← WMA, RSC Mansfield, VPM5, Coppock, MOM, filtro F5
│   test_sp500_bajista.py     ← condición de mercado bajista (S2) y su relación con F5
│   test_scanner_entry.py     ← filtros de entrada F1-F5 (mockeando descargas)
│   test_scanner_exit.py      ← condiciones de salida S1-S2 (mockeando descargas)
│   test_data.py              ← carga de posiciones y descargas (mockeadas + red real opcional)
│
docs/
    ESTRATEGIA.md             ← descripción técnica completa
│
backtest/
    backtest_lookback.py       ← backtest de sensibilidad de COPPOCK_RECENT_LOOKBACK (F5)
```

## Quickstart (3 pasos)

```bash
# 1. Crear entorno virtual (Python 3.11+)
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# 2. Instalar dependencias
pip install -r requirements.txt

# 3a. Escáner de entrada (ejecutar tras el cierre semanal)
python -m weinstein entry

# 3b. Escáner de salida (revisar posiciones abiertas)
python -m weinstein exit
python -m weinstein exit --input mis_posiciones.csv
```

## Scripts de arranque

```bash
bash scripts/run_entry.sh
bash scripts/run_exit.sh

# Pasar --input desde el script de salida:
bash scripts/run_exit.sh --input mis_posiciones.csv

# Windows
scripts\run_entry.bat
scripts\run_exit.bat
scripts\run_exit.bat --input mis_posiciones.csv
```

## Ajustar parámetros

Todos los umbrales y periodos están centralizados en **`weinstein/config.py`**:

```python
SECTOR_RSC_MIN           = 0.10   # F1: RSC Mansfield sector >= umbral
MAX_DISTANCIA_WMA30      = 8.0    # F4: precio no supera WMA30 en más de X %
RSC_EXIT_THRESHOLD       = -0.5   # S1: RSC Mansfield activo < umbral → salida
MAX_CANDIDATES           = 10     # Top-N candidatos en el ranking
DOWNLOAD_MAX_RETRIES     = 3      # reintentos ante fallos puntuales de descarga
DOWNLOAD_RETRY_BACKOFF_S = 1.5    # segundos de espera entre reintentos (con backoff lineal)
```

Los textos de motivo de salida (`S1: RSC...`, `S2: Coppock SP500 bajista`) también están
centralizados aquí (`EXIT_REASON_S1_LABEL`, `EXIT_REASON_S2_LABEL`, `EXIT_REASON_NONE`), así
que si alguna vez cambian de nombre solo hay que tocarlos en un sitio.

## Cómo funciona

### Escáner de entrada (`weinstein/scanner_entry.py`)

Aplica 5 filtros **AND** sobre el universo del S&P 500:

| # | Condición | Umbral |
|---|-----------|--------|
| F1 | RSC Mansfield del sector | ≥ 0.10 |
| F2 | VPM5 (volumen normalizado) | > 0 |
| F3 | RSC Mansfield del activo | > 0 |
| F4 | Distancia precio / WMA30 | < +8 % |
| F5 | Coppock SP500 alcista (`sp500_alcista()`) | True |

Los candidatos se ordenan por Momentum Relativo (MOM) descendente. La WMA30 se calcula una
única vez por ticker y se reutiliza tanto para F4 como para MOM.

### Escáner de salida (`weinstein/scanner_exit.py`)

Aplica 2 condiciones **OR** sobre las posiciones abiertas:

| # | Condición | Umbral |
|---|-----------|--------|
| S1 | RSC Mansfield del activo | < −0.5 |
| S2 | Coppock SP500 bajista (`sp500_bajista()`) | True |

> **S2 es una condición propia, no el complemento de F5.** `sp500_bajista()` se activa solo en
> dos casos: (a) el Coppock cruza de positivo/cero a negativo, o (b) el Coppock ya es negativo y
> sigue cayendo respecto a la semana anterior. Existe un **tercer estado neutro** (ni alcista ni
> bajista) — por ejemplo, un rebote en negativo que aún no es el "primer" rebote que exige F5, o
> un Coppock positivo pero ya decreciente — en el que ni F5 ni S2 se activan, y por tanto no
> fuerza salidas. Ver `docs/ESTRATEGIA.md` sección 4 y el docstring de `weinstein/scanner_exit.py`
> para el detalle completo.

> **Nota sobre `historial/`**: los CSVs no reflejan todos la misma versión de la lógica de S2.
> No hagas mucho caso a los CSVs de `historial/` como fuente para decisiones automáticas — pueden
> corresponder a versiones anteriores del proyecto y se conservan solo por historial. Desde esta
> versión, cada CSV exportado incluye una columna `Versión Lógica`
> (`SCANNER_LOGIC_VERSION` en `config.py`) que identifica sin ambigüedad con qué lógica se generó
> — ver `docs/ESTRATEGIA.md` sección 4 para el detalle de versiones anteriores a esta columna.

### Módulos del paquete

| Módulo | Responsabilidad |
|--------|----------------|
| `__main__.py` | CLI unificado con subcomandos `entry` y `exit` |
| `config.py` | Constantes y umbrales de la estrategia |
| `indicators.py` | Cálculos puros: WMA, RSC Mansfield, VPM5, Coppock, MOM, `sp500_alcista`, `sp500_bajista` |
| `data.py` | Descarga yfinance (con reintentos/backoff), carga de tickers S&P 500, lectura de posiciones |
| `scanner_entry.py` | Orquestación del escáner de entrada |
| `scanner_exit.py` | Orquestación del escáner de salida |
| `exporter.py` | Exportación a CSV con historial fechado |

## Formato de archivos

### `posiciones.csv` (entrada del escáner de salida)

```csv
Ticker,Sector,Precio_Entrada,Fecha_Entrada
XOM,Energy,154.08,2026-05-26
CVX,Energy,192.79,2026-05-18
```

### CSV de salida — entradas (`historial/entradas/`)

```
weinstein_albert_scan_YYYYMMDD_HHMM.csv
```

### CSV de salida — salidas (`historial/salidas/`)

```
posiciones_salidas_YYYYMMDD_HHMM.csv
```

## Testing

Hay tests (`pytest`) que verifican los cálculos de cada filtro (F1-F5, S1-S2) de forma aislada
con datos sintéticos, sin depender del estado real del mercado ni de red. En particular,
`tests/test_sp500_bajista.py` cubre explícitamente que `sp500_alcista()` y `sp500_bajista()` no
son complementarias y verifica el estado neutro descrito en la sección anterior.

```bash
pip install -r requirements.txt
pytest                # suite completa
pytest -m network     # opcional: tests que sí golpean APIs externas reales
```

## Troubleshooting

- **`python` no reconocido**: instalar Python 3.11+ y añadir al PATH.
- **Descarga de datos falla**: comprobar conexión; `yfinance` puede tener interrupciones puntuales. `download_weekly()` ya reintenta automáticamente (`DOWNLOAD_MAX_RETRIES` en `config.py`) antes de darse por vencido, y registra en stderr si el fallo final fue de red o de "sin datos".
- **Columnas faltantes en `posiciones.csv`**: verificar que existen `Ticker`, `Sector`, `Precio_Entrada` y `Fecha_Entrada`.
- **El proceso tarda mucho**: normal; descargar ~500 tickers lleva varios minutos.
- **Los tests no encuentran el paquete `weinstein`**: ejecutar `pytest` desde la raíz del proyecto (usa `python -m pytest` si el problema persiste).

## Backtest

`backtest/backtest_lookback.py` evalúa distintos valores de `COPPOCK_RECENT_LOOKBACK` (filtro F5,
mercado alcista) sobre el histórico real del S&P 500: retorno futuro a varios horizontes, % de
señales negativas y retraso frente al mínimo real del Coppock. Es un backtest del filtro de
mercado en aislamiento, no de la estrategia completa.

```bash
pip install yfinance pandas numpy scipy --break-system-packages
python backtest/backtest_lookback.py
python backtest/backtest_lookback.py --period 15y --lookbacks 2,3,4,6,8,12
```

## Referencias

- Estrategia original: <https://youtu.be/reQWjzedlX0?si=xSsagVeCSqrX7miV>
- Descripción técnica completa: [docs/ESTRATEGIA.md](docs/ESTRATEGIA.md)