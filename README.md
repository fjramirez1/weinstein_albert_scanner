# Weinstein Albert Scanner

Utilidades en Python para ejecutar una estrategia semanal inspirada en el método Weinstein: detección de candidatos de entrada y evaluación de salidas para posiciones abiertas.

## Estructura del proyecto

```
weinstein/                        ← paquete principal
│   __init__.py
│   config.py                     ← todos los parámetros en un único lugar
│   indicators.py                 ← cálculos técnicos (WMA, RSC, VPM5, Coppock, MOM)
│   data.py                       ← descarga de precios y carga de tickers S&P 500
│   scanner.py                    ← lógica de escáner de entrada
│   exit_scanner.py               ← lógica de escáner de salida
│   exporter.py                   ← exportación CSV con historial
│
weinstein_albert_scanner.py       ← entry point: escáner de entrada
weinstein_albert_exit_scanner.py  ← entry point: escáner de salida
we_utils.py                       ← compatibilidad con versiones anteriores
posiciones.csv                    ← tus posiciones abiertas
requirements.txt
│
scripts/
│   run_entry.sh / run_entry.bat
│   run_exit.sh  / run_exit.bat
│
historial/
│   entradas/                     ← CSVs generados por el escáner de entrada
│   salidas/                      ← CSVs generados por el escáner de salida
│
docs/
    ESTRATEGIA.md                 ← descripción técnica completa
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
python weinstein_albert_scanner.py

# 3b. Escáner de salida (revisar posiciones abiertas)
python weinstein_albert_exit_scanner.py
python weinstein_albert_exit_scanner.py --input mis_posiciones.csv
```

## Ajustar parámetros

Todos los umbrales y periodos están centralizados en **`weinstein/config.py`**.
No hace falta tocar ningún otro archivo para modificar la estrategia:

```python
# weinstein/config.py (fragmento)
SECTOR_RSC_MIN      = 0.10   # F1: RSC Mansfield sector >= umbral
MAX_DISTANCIA_WMA30 = 8.0    # F4: precio no supera WMA30 en más de X %
RSC_EXIT_THRESHOLD  = -0.5   # S1: RSC Mansfield activo < umbral → salida
MAX_CANDIDATES      = 10     # Top-N candidatos en el ranking
```

## Cómo funciona

### Escáner de entrada (`weinstein/scanner.py`)

Aplica 5 filtros **AND** sobre el universo del S&P 500:

| # | Condición | Umbral |
|---|-----------|--------|
| F1 | RSC Mansfield del sector | ≥ 0.10 |
| F2 | VPM5 (volumen normalizado) | > 0 |
| F3 | RSC Mansfield del activo | > 0 |
| F4 | Distancia precio / WMA30 | < +8 % |
| F5 | Coppock SP500 alcista | True |

Los candidatos se ordenan por Momentum Relativo (MOM) descendente.

### Escáner de salida (`weinstein/exit_scanner.py`)

Aplica 2 condiciones **OR** sobre las posiciones abiertas:

| # | Condición | Umbral |
|---|-----------|--------|
| S1 | RSC Mansfield del activo | < −0.5 |
| S2 | Coppock SP500 no alcista | True |

### Módulos del paquete

| Módulo | Responsabilidad |
|--------|----------------|
| `config.py` | Constantes y umbrales de la estrategia |
| `indicators.py` | Cálculos puros: WMA, RSC Mansfield, VPM5, Coppock, MOM |
| `data.py` | Descarga yfinance, carga de tickers S&P 500, lectura de posiciones |
| `scanner.py` | Orquestación del escáner de entrada |
| `exit_scanner.py` | Orquestación del escáner de salida |
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

## Scripts de arranque

```bash
bash scripts/run_entry.sh
bash scripts/run_exit.sh

# Windows
scripts\run_entry.bat
scripts\run_exit.bat
```

## Compatibilidad con versiones anteriores

Si tienes código que importa desde `we_utils` directamente, sigue funcionando:

```python
# Esto sigue siendo válido
from we_utils import wma, rsc_mansfield, coppock_curve

# Para código nuevo, importa desde el paquete
from weinstein.indicators import wma, rsc_mansfield, coppock_curve
```

## Troubleshooting

- **`python` no reconocido**: instalar Python 3.11+ y añadir al PATH.
- **Descarga de datos falla**: comprobar conexión; `yfinance` puede tener interrupciones puntuales.
- **Columnas faltantes en `posiciones.csv`**: verificar que existen `Ticker`, `Sector`, `Precio_Entrada` y `Fecha_Entrada`.
- **El proceso tarda mucho**: normal; descargar ~500 tickers lleva varios minutos.

## Referencias

- Estrategia original: <https://youtu.be/reQWjzedlX0?si=xSsagVeCSqrX7miV>
- Descripción técnica completa: [docs/ESTRATEGIA.md](docs/ESTRATEGIA.md)