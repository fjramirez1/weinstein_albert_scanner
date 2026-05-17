# Weinstein Albert Scanner

Repositorio con dos utilidades en Python para analizar acciones con una adaptación del método Weinstein:

- `weinstein_albert_scanner.py`: escáner de entrada que revisa los componentes del S&P 500 y genera candidatos que cumplen los filtros técnicos del sistema.
- `weinstein_albert_exit_scanner.py`: escáner de salida que evalúa posiciones abiertas y marca si conviene salir por deterioro técnico o de mercado.

Ambos scripts trabajan con datos semanales descargados desde `yfinance` y exportan sus resultados a archivos CSV en la misma carpeta del proyecto.

## Qué hace cada script

### Escáner de entrada

`weinstein_albert_scanner.py` descarga los componentes actuales del S&P 500, calcula indicadores como `WMA30`, `RSC Mansfield`, `VPM5` y la curva de `Coppock`, y filtra los valores que cumplen todas las condiciones de compra.

Salida principal:

- Muestra el progreso por consola.
- Genera un CSV con nombre similar a `weinstein_albert_scan_YYYYMMDD_HHMM.csv`.

### Escáner de salida

`weinstein_albert_exit_scanner.py` revisa una lista de posiciones abiertas y comprueba tres condiciones de salida:

- `RSC Mansfield` por debajo del umbral definido.
- `Trailing stop` basado en los últimos cierres semanales desde la fecha de entrada.
- `Coppock` bajista en el S&P 500.

Salida principal:

- Muestra el veredicto de cada posición por consola.
- Genera un CSV con nombre similar a `<archivo_entrada>_salidas_YYYYMMDD_HHMM.csv`.

## Requisitos

- Python 3.11 o superior.
- Conexión a Internet para descargar datos de mercado.
- Dependencias de Python:

```bash
pip install yfinance pandas numpy requests
```

## Instalación y ejecución en Windows

1. Abre `CMD` en la carpeta del proyecto:

```cmd
cd C:\weinstein_albert_scanner
```

2. Crea un entorno virtual:

```cmd
python -m venv venv
```

3. Actívalo:

```cmd
venv\Scripts\activate
```

4. Instala las dependencias:

```cmd
pip install yfinance pandas numpy requests
```

## Cómo ejecutar el escáner de entrada

Con el entorno virtual activo:

```cmd
python weinstein_albert_scanner.py
```

El proceso puede tardar varios minutos porque descarga datos semanales de muchos tickers del S&P 500. Al finalizar, el CSV de resultados quedará guardado en la carpeta del proyecto.

## Cómo ejecutar el escáner de salida

Este script usa por defecto `posiciones.csv` en la carpeta del proyecto:

```cmd
python weinstein_albert_exit_scanner.py
```

Si quieres usar otro archivo de entrada:

```cmd
python weinstein_albert_exit_scanner.py --input mis_posiciones.csv
```

## Formato del archivo de posiciones

El archivo de entrada debe incluir estas columnas:

- `Ticker`
- `Sector`
- `Precio_Entrada`
- `Fecha_Entrada`

Ejemplo:

```csv
Ticker,Sector,Precio_Entrada,Fecha_Entrada
AAPL,Technology,175.30,2024-05-17
MSFT,Technology,415.00,2024-05-17
XOM,Energy,112.50,2024-05-17
JPM,Financial Services,198.20,2024-05-17
```

Notas importantes:

- `Fecha_Entrada` debe tener formato `YYYY-MM-DD`.
- El archivo debe estar en la misma carpeta que el script, salvo que uses `--input` con una ruta distinta.

## Flujo recomendado

1. Ejecuta `weinstein_albert_scanner.py` para detectar candidatos de entrada.
2. Guarda o adapta el CSV de posiciones abiertas con las columnas requeridas.
3. Ejecuta `weinstein_albert_exit_scanner.py` para revisar si alguna posición debe cerrarse.

## Salidas generadas

- `weinstein_albert_scan_YYYYMMDD_HHMM.csv`
- `<archivo_entrada>_salidas_YYYYMMDD_HHMM.csv`

## Solución de problemas

- Si aparece un error de `python` no reconocido, verifica que Python esté instalado y agregado al `PATH`.
- Si no se descargan datos, comprueba tu conexión a Internet.
- Si el escáner de salida indica columnas faltantes, revisa que `posiciones.csv` incluya `Ticker`, `Sector`, `Precio_Entrada` y `Fecha_Entrada`.