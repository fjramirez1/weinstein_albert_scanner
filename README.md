# Weinstein Albert Scanner

Utilidades en Python para ejecutar una estrategia semanal inspirada en el método Weinstein:
detección de candidatos de entrada y evaluación de salidas para posiciones abiertas.

## Estructura del proyecto

```
weinstein/                  ← paquete principal
│   __init__.py
│   __main__.py             ← CLI unificado (python -m weinstein)
│   config.py               ← todos los parámetros en un único lugar
│   indicators.py           ← cálculos técnicos (WMA, RSC, VPM5, Coppock, MOM)
│   data.py                 ← descarga de precios y carga de tickers S&P 500
│   scanner_entry.py        ← lógica del escáner de entrada
│   scanner_exit.py         ← lógica del escáner de salida
│   exporter.py             ← exportación CSV con historial
│
posiciones.csv              ← tus posiciones abiertas
requirements.txt
pytest.ini                  ← configuración de tests
│
scripts/
│   run_entry.sh / run_entry.bat
│   run_exit.sh  / run_exit.bat
│
historial/
│   entradas/               ← CSVs generados por el escáner de entrada
│   salidas/                ← CSVs generados por el escáner de salida
│
tests/                      ← suite de tests (pytest)
│   conftest.py             ← fixtures compartidas
│   test_indicators.py      ← WMA, RSC Mansfield, VPM5, Coppock, MOM, filtro F5/S2
│   test_scanner_entry.py   ← filtros de entrada F1-F5 (mockeando descargas)
│   test_scanner_exit.py    ← condiciones de salida S1-S2 (mockeando descargas)
│   test_data.py            ← carga de posiciones y descargas (mockeadas + red real opcional)
│
docs/
    ESTRATEGIA.md           ← descripción técnica completa
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
SECTOR_RSC_MIN      = 0.10   # F1: RSC Mansfield sector >= umbral
MAX_DISTANCIA_WMA30 = 8.0    # F4: precio no supera WMA30 en más de X %
RSC_EXIT_THRESHOLD  = -0.5   # S1: RSC Mansfield activo < umbral → salida
MAX_CANDIDATES      = 10     # Top-N candidatos en el ranking
```

## Cómo funciona

### Escáner de entrada (`weinstein/scanner_entry.py`)

Aplica 5 filtros **AND** sobre el universo del S&P 500:

| # | Condición | Umbral |
|---|-----------|--------|
| F1 | RSC Mansfield del sector | ≥ 0.10 |
| F2 | VPM5 (volumen normalizado) | > 0 |
| F3 | RSC Mansfield del activo | > 0 |
| F4 | Distancia precio / WMA30 | < +8 % |
| F5 | Coppock SP500 alcista | True |

Los candidatos se ordenan por Momentum Relativo (MOM) descendente.

### Escáner de salida (`weinstein/scanner_exit.py`)

Aplica 2 condiciones **OR** sobre las posiciones abiertas:

| # | Condición | Umbral |
|---|-----------|--------|
| S1 | RSC Mansfield del activo | < −0.5 |
| S2 | Coppock SP500 no alcista | True |

### Módulos del paquete

| Módulo | Responsabilidad |
|--------|----------------|
| `__main__.py` | CLI unificado con subcomandos `entry` y `exit` |
| `config.py` | Constantes y umbrales de la estrategia |
| `indicators.py` | Cálculos puros: WMA, RSC Mansfield, VPM5, Coppock, MOM |
| `data.py` | Descarga yfinance, carga de tickers S&P 500, lectura de posiciones |
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
con datos sintéticos, sin depender del estado real del mercado ni de red.

```bash
pip install -r requirements.txt
pytest                # suite completa
pytest -m network     # opcional: tests que sí golpean APIs externas reales
```

## Troubleshooting

- **`python` no reconocido**: instalar Python 3.11+ y añadir al PATH.
- **Descarga de datos falla**: comprobar conexión; `yfinance` puede tener interrupciones puntuales.
- **Columnas faltantes en `posiciones.csv`**: verificar que existen `Ticker`, `Sector`, `Precio_Entrada` y `Fecha_Entrada`.
- **El proceso tarda mucho**: normal; descargar ~500 tickers lleva varios minutos.
- **Los tests no encuentran el paquete `weinstein`**: ejecutar `pytest` desde la raíz del proyecto (usa `python -m pytest` si el problema persiste).

## Referencias

- Estrategia original: <https://youtu.be/reQWjzedlX0?si=xSsagVeCSqrX7miV>
- Descripción técnica completa: [docs/ESTRATEGIA.md](docs/ESTRATEGIA.md)