# Weinstein Albert Scanner

Pequeñas utilidades en Python para ejecutar una estrategia semanal inspirada en el método Weinstein: detección de candidatos de entrada y evaluación de salidas para posiciones abiertas.

**Resumen**: dos scripts principales — `weinstein_albert_scanner.py` (escáner de entrada) y `weinstein_albert_exit_scanner.py` (escáner de salida). Ambos producen CSVs con resultados y están pensados para ejecutarse semanalmente (tras el cierre de la semana bursátil).

## Quickstart (3 pasos)

1. Crear y activar un entorno virtual (recomendado Python 3.11+):

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

2. Instalar dependencias:

```bash
pip install -r requirements.txt
```

3. Ejecutar el escáner de entrada (preferiblemente después del cierre semanal):

```bash
python weinstein_albert_scanner.py
```

Para revisar salidas sobre posiciones abiertas:

```bash
python weinstein_albert_exit_scanner.py
# o con otro archivo de posiciones
python weinstein_albert_exit_scanner.py --input mis_posiciones.csv
```

## Instalación

- Requiere Python 3.11+.
- Instalar dependencias con `pip install -r requirements.txt` o `pip install yfinance pandas numpy requests`.
- Conexión a Internet para descargar datos desde `yfinance`.

## Estructura del proyecto

- `weinstein_albert_scanner.py` — escáner de entrada (genera `weinstein_albert_scan_*.csv`).
- `weinstein_albert_exit_scanner.py` — escáner de salida (usa `posiciones.csv` por defecto).
- `we_utils.py` — funciones helper (WMA, RSC Mansfield, VPM5, Coppock, MOM).
- `requirements.txt` — dependencias.
- `posiciones.csv` — ejemplo/plantilla de posiciones abiertas.
- `scripts/` — wrappers `run_entry` / `run_exit` para Windows y Unix.
- `weinstein_albert_scan_*.csv` / `posiciones_salidas_*.csv` — CSVs de ejemplo generados por los scripts.

## Cómo funciona (breve)

- `weinstein_albert_scanner.py` descarga componentes del S&P 500, calcula indicadores (WMA30, RSC Mansfield, VPM5, Coppock) y filtra candidatos que cumplen las condiciones de entrada.
- `weinstein_albert_exit_scanner.py` evalúa posiciones abiertas y marca salidas cuando se cumple cualquiera de las condiciones de salida (RSC débil, Coppock bajista, trailing stop).

Para la descripción técnica completa (fórmulas y criterios), ver [docs/ESTRATEGIA.md](docs/ESTRATEGIA.md#condiciones-de-la-estrategia).

## Scripts y uso

- Escáner de entrada:

```bash
python weinstein_albert_scanner.py
```

- Escáner de salida (usa `posiciones.csv` por defecto):

```bash
python weinstein_albert_exit_scanner.py
```

- Wrappers de conveniencia:

```cmd
scripts\\run_entry.bat
scripts\\run_exit.bat
# o
bash scripts/run_entry.sh
bash scripts/run_exit.sh
```

## Formato de archivos y ejemplos reales

### `posiciones.csv` (archivo de entrada)

Columnas requeridas: `Ticker`, `Sector`, `Precio_Entrada`, `Fecha_Entrada` (formato `YYYY-MM-DD`).

Ejemplo real (en repo):

```csv
Ticker,Sector,Precio_Entrada,Fecha_Entrada
AAPL,Technology,175.30,2024-05-17
MSFT,Technology,415.00,2024-05-17
NVDA,Technology,620.50,2024-05-17
XOM,Energy,112.50,2024-05-17
JPM,Financial Services,198.20,2024-05-17
```

### `weinstein_albert_scan_YYYYMMDD_HHMM.csv` (salida del escáner de entrada)

Cabecera de ejemplo (archivo real en repo):

```csv
Ticker,Nombre,Sector,ETF Sector,Precio Actual,RSC Mansfield Activo,Momentum (MOM),RSC Mansfield Sector,VPM5,Distancia % WMA30,Dirección Coppock SP500
CVX,Chevron Corporation,Energy,XLE,191.1,0.6133,0.0513,1.2554,0.2496,5.13,↑ Alcista
```

Descripción breve de columnas (resumen):
- `Ticker`: símbolo.
- `Nombre`: nombre de la compañía.
- `Sector`, `ETF Sector`: sector y ETF representativo.
- `Precio Actual`: último cierre semanal.
- `RSC Mansfield Activo`: fuerza relativa frente al S&P 500.
- `Momentum (MOM)`: (Precio Actual - WMA30) / WMA30.
- `VPM5`: volumen normalizado suavizado (SMA5 de VPM).
- `Distancia % WMA30`: separación porcentual respecto a la WMA30.

### `<archivo_entrada>_salidas_YYYYMMDD_HHMM.csv` (salida del escáner de salida)

Cabecera de ejemplo (archivo real en repo):

```csv
Ticker,Precio Actual,RSC Mansfield,S1 RSC < -0.5,S3 Coppock Bajista,SALIDA,Motivo,Error,Sector,Precio Entrada,Rentabilidad %
MSFT,421.92,-1.8943,True,False,True,S1: RSC=-1.894 < -0.5,,Technology,415.0,1.67
JPM,297.81,-1.0111,True,False,True,S1: RSC=-1.011 < -0.5,,Financial Services,198.2,50.26
NVDA,225.32,1.3208,False,False,False,—,,Technology,620.5,-63.69
```

Descripción breve de columnas (resumen):
- `S1 RSC < -0.5`: bandera si `RSC Mansfield` del activo cae por debajo de −0.5.
- `S3 Coppock Bajista`: indicador de mercado (Coppock) bajista.
- `SALIDA`: `True`/`False` si debe cerrarse.
- `Motivo`: texto con la razón principal de la señal de salida.

## Troubleshooting / Validaciones

- Si `python` no se reconoce: instalar Python y añadir al `PATH`.
- Si la descarga de datos falla: comprobar conexión a Internet o problemas temporales con `yfinance`.
- Si el script indica columnas faltantes al leer `posiciones.csv`: verificar que `Ticker`, `Sector`, `Precio_Entrada` y `Fecha_Entrada` existen y están correctamente nombradas.
- Si el proceso tarda demasiado: ejecutar los scripts en fin de semana y dejar correr; las descargas de muchos tickers pueden tardar varios minutos.

## Referencias y licencia

- Fuente de la estrategia: https://youtu.be/reQWjzedlX0?si=xSsagVeCSqrX7miV

## Estado técnico completo

La descripción técnica completa (cálculos, fórmulas y criterios detallados) está en [docs/ESTRATEGIA.md](docs/ESTRATEGIA.md#condiciones-de-la-estrategia).
