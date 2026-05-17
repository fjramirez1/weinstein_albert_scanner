# Weinstein Albert Scanner

Repositorio con dos utilidades en Python para implementar, de forma operativa, una estrategia de trading algorítmico inspirada en el método Weinstein:

- `weinstein_albert_scanner.py`: escáner de entrada que revisa los componentes del S&P 500 y genera candidatos que cumplen los filtros técnicos del sistema.
- `weinstein_albert_exit_scanner.py`: escáner de salida que evalúa posiciones abiertas y marca si conviene salir por deterioro técnico o de mercado.

La idea es trabajar con una rutina semanal: el sistema usa datos semanales descargados desde `yfinance`, produce salidas en CSV y se ejecuta cuando la semana bursátil ya ha cerrado. En la práctica, esto significa revisar entradas y salidas durante el fin de semana, no a lo largo de la sesión diaria.

Este proyecto no es solo una utilidad de terminal. Es una pequeña capa de ejecución para una estrategia que separa claramente dos momentos:

1. Búsqueda de nuevas entradas sobre el universo del S&P 500.
2. Seguimiento de posiciones abiertas para decidir si se mantienen o se cierran.

## Cómo funciona la estrategia

La lógica del sistema está pensada para usarse así:

1. Durante el fin de semana, una vez cerrada la semana bursátil de la Bolsa de Nueva York, se ejecuta el escáner de entrada para detectar acciones que cumplen los filtros.
2. Si se abre una operación, se registra en `posiciones.csv` con su `Ticker`, `Sector`, `Precio_Entrada` y `Fecha_Entrada`.
3. Mientras haya posiciones abiertas, se ejecuta también el escáner de salida cada fin de semana para comprobar si alguna posición debe cerrarse.

Como las señales están calculadas con velas semanales, ejecutarlo a diario no aporta una lectura más fiel del método y puede introducir ruido innecesario.

## Qué hace cada script

### Escáner de entrada

`weinstein_albert_scanner.py` descarga los componentes actuales del S&P 500, calcula indicadores como `WMA30`, `RSC Mansfield`, `VPM5` y la curva de `Coppock`, y filtra los valores que cumplen todas las condiciones de compra.

Uso recomendado:

- Ejecutarlo en fin de semana, después del cierre semanal de la bolsa.
- Revisar el CSV de salida como lista de candidatos, no como órdenes automáticas.

Salida principal:

- Muestra el progreso por consola.
- Genera un CSV con nombre similar a `weinstein_albert_scan_YYYYMMDD_HHMM.csv`.

### Escáner de salida

`weinstein_albert_exit_scanner.py` revisa una lista de posiciones abiertas y comprueba tres condiciones de salida:

- `RSC Mansfield` por debajo del umbral definido.
- `Trailing stop` basado en los últimos cierres semanales desde la fecha de entrada.
- `Coppock` bajista en el S&P 500.

Uso recomendado:

- Ejecutarlo en fin de semana mientras exista al menos una posición abierta.
- Actualizar `posiciones.csv` cuando abras o cierres operaciones.

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

También puedes instalar desde `requirements.txt` si existe:

```bash
pip install -r requirements.txt
```

## Cómo ejecutar el escáner de entrada

Con el entorno virtual activo y preferiblemente durante el fin de semana, después del cierre semanal de la NYSE:

```cmd
python weinstein_albert_scanner.py
```

El proceso puede tardar varios minutos porque descarga datos semanales de muchos tickers del S&P 500. Al finalizar, el CSV de resultados quedará guardado en la carpeta del proyecto.

## Cómo ejecutar el escáner de salida

Este script usa por defecto `posiciones.csv` en la carpeta del proyecto y está pensado para revisarse cada fin de semana mientras haya posiciones abiertas:

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

1. Espera al cierre de la semana bursátil y ejecuta `weinstein_albert_scanner.py` para detectar candidatos de entrada.
2. Si realizas una compra, registra la operación en `posiciones.csv` con la fecha de entrada.
3. Cada fin de semana, mientras haya posiciones abiertas, ejecuta `weinstein_albert_exit_scanner.py` para decidir si alguna posición debe cerrarse.

## Salidas generadas

- `weinstein_albert_scan_YYYYMMDD_HHMM.csv`
- `<archivo_entrada>_salidas_YYYYMMDD_HHMM.csv`

## Fuente de la estrategia

La fuente de información de donde se ha sacado la estrategia de trading algorítmico es: https://youtu.be/reQWjzedlX0?si=xSsagVeCSqrX7miV

## Solución de problemas

- Si aparece un error de `python` no reconocido, verifica que Python esté instalado y agregado al `PATH`.
- Si no se descargan datos, comprueba tu conexión a Internet.
- Si el escáner de salida indica columnas faltantes, revisa que `posiciones.csv` incluya `Ticker`, `Sector`, `Precio_Entrada` y `Fecha_Entrada`.

## Resumen operativo

- Entrada: una vez por semana, al cierre del mercado de NY y preferiblemente durante el fin de semana.
- Salida: una vez por semana, mientras existan posiciones abiertas.
- Decisión: el CSV no sustituye el criterio del operador, pero sí estandariza la lectura de la estrategia y evita revisar el sistema todos los días.

## Uso con scripts de ayuda

Se incluyen scripts de conveniencia en la carpeta `scripts/` para ejecutar los escáneres activando automáticamente el `venv` si existe.

- Windows (CMD/PowerShell):

```cmd
scripts\run_entry.bat        # ejecuta el escáner de entrada
scripts\run_exit.bat         # ejecuta el escáner de salida
```

- Unix/macOS (bash):

```bash
scripts/run_entry.sh "arg1 arg2"   # ejecuta el escáner de entrada
scripts/run_exit.sh "arg1 arg2"    # ejecuta el escáner de salida
```

Los scripts aceptan argumentos adicionales que se pasarán al script Python.

Si prefieres ejecutar manualmente, activa el entorno virtual y usa `python <script>.py` como se indica arriba.
