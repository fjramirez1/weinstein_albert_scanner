# Condiciones de la estrategia (detallado)

Este documento amplía y explica con más detalle los criterios operativos usados por los escáneres del repositorio. Incluye definiciones, fórmulas, umbrales y ejemplos orientativos para facilitar el mantenimiento y la validación documental (sin tocar la implementación).

## 1. Definiciones clave

- **Universo del S&P 500**: el escáner trabaja con tickers/acciones negociables del índice, no con un conteo fijo de empresas únicas. El número de acciones puede ser variable y superar 500 cuando existen clases múltiples, por ejemplo GOOGL y GOOG en Alphabet.
- **RSC Mansfield (Sector)**: mide la fortaleza relativa del índice sectorial frente al S&P 500. Se calcula comparando la serie de precios del ETF sectorial con la del S&P 500 y aplicando la transformación "Mansfield" para detectar consistencia en la fortaleza.
- **RSC Mansfield (Activo / rsMan)**: mismo procedimiento aplicado a la acción frente al S&P 500. Valores positivos indican mejor comportamiento relativo.
- **VPM5 (Volumen Proporcional Medio 5 semanas)**: volumen estandarizado respecto a las últimas 52 semanas, suavizado con una SMA de 5 semanas. Indica si el volumen actual es atípico respecto al histórico.
- **WMA30 / MA30**: media móvil ponderada de 30 sesiones; referencia de tendencia de medio plazo.
- **Distancia % respecto a WMA30**: distancia relativa del precio al WMA30: Dist% = (Precio Actual − WMA30) / WMA30 (expresado en %).
- **Coppock semanal**: indicador de estado de mercado construido como WMA(10) de la suma de dos ROC semanales (12 semanas y 6 semanas). Se usa como filtro de mercado, tanto en el sentido alcista (entrada, F5) como en el sentido bajista (salida, S2) — son dos condiciones **independientes** calculadas sobre la misma curva, no una el complemento de la otra (ver sección 4).
- **MOM (Momentum relativo para desempate)**: medida relativa del precio sobre su WMA30: MOM = (C − WMA30) / WMA30.

## 2. Cálculos resumidos (cómo se obtienen)

- **VPM5**:
  1. Calcular `media52` y `desv52` del volumen semanal de las últimas 52 semanas.
  2. `VPM(t) = (Volumen(t) - media52) / desv52`.
  3. `VPM5(t) = SMA_5(VPM(t))`.

- **RSC Mansfield (general)**:
  1. Tomar series de precios semanales: `P_activo(t)` y `P_ref(t)` (S&P 500 o ETF sectorial).
  2. Calcular la serie relativa `R(t) = P_activo(t) / P_ref(t)`.
  3. Aplicar una suavización (SMA sobre 52 períodos) y la transformación Mansfield para medir consistencia. El resultado positivo indica fortaleza relativa sostenida.
  4. Si la SMA de la serie relativa es 0 en algún punto (caso degenerado, p.ej. precios relativos extremadamente pequeños), el código produce `NaN` en ese punto en vez de dividir por cero, para evitar valores infinitos aguas abajo.

- **Distancia % a WMA30**: `Dist% = 100 * (C - WMA30) / WMA30`.

- **Coppock semanal**: `Coppock(t) = WMA_10( ROC_12(P) + ROC_6(P) )`.

- **MOM (desempate)**: `MOM = (C - WMA30) / WMA30`. Se usa solo para ordenar candidatos que cumplen todos los filtros. La WMA30 se calcula una única vez por ticker y se reutiliza tanto para F4 (distancia) como para MOM, evitando recalcular la misma media móvil dos veces.

## 3. Filtros de entrada (todas deben cumplirse — AND)

1. **Fuerza del Sector (RSC Mansfield Sector >= +0.10)**
   - Objetivo: operar solo en sectores que muestran fortaleza relativa frente al S&P 500.
   - Cómputo: identificar el ETF/índice sectorial GICS asociado y calcular su RSC Mansfield semanal frente al S&P 500. Considerar el sector fuerte si RSC >= +0.10.

2. **Volumen Normalizado Positivo (VPM5 > 0)**
   - Objetivo: confirmar interés del mercado en la acción.
   - Cómputo: ver sección 2 (VPM5). Se requiere VPM5 > 0 (volumen por encima de la media histórica en términos de desviaciones).

3. **Fuerza del Valor (rsMan > 0)**
   - Objetivo: seleccionar acciones que rinden mejor que el índice.
   - Cómputo: RSC Mansfield del activo frente al S&P 500; se exige rsMan > 0.

4. **Distancia al Precio Ponderado (< +8% respecto a WMA30)**
   - Objetivo: evitar entradas en valores excesivamente sobrecomprados respecto a la tendencia de medio plazo.
   - Cómputo: Dist% (ver sección 2). Se exige Dist% < +8%, es decir, el precio no debe superar la WMA30 en más del 8 %.
   - Nota: no existe cota inferior. Valores cuyo precio esté por debajo de la WMA30 (Dist% negativa) son válidos y no se filtran.

5. **Filtro de Mercado — Coppock Alcista (Sp500alcista = True)**
   - Objetivo: abrir posiciones largas solo cuando el mercado general muestra inicio o continuación de tendencia alcista.
   - Cómputo: Coppock semanal = WMA(10) de (ROC_12 + ROC_6) sobre el S&P 500.
   - Criterio operativo (implementado en `sp500_alcista()`):
     - *Inicio de alcista desde negativo*: Coppock está en terreno negativo, el valor de la semana anterior ha marcado el mínimo de las últimas 4 semanas (`COPPOCK_RECENT_LOOKBACK`) y el valor actual sube por encima de ese mínimo. Señala que el mercado podría estar comenzando una nueva fase alcista. Esta condición solo se cumple en la semana exacta de ese primer rebote — no en cualquier semana de recuperación posterior dentro de terreno negativo (ver nota en sección 4).
     - *Continuación de alcista positivo*: Coppock está por encima de 0 y sigue aumentando respecto a la semana anterior.
   - El flag `Sp500alcista` se activa en cualquiera de las dos situaciones anteriores.

> Idea operativa: todas las condiciones anteriores deben cumplirse para que una acción sea considerada candidata de compra.

## 4. Filtros de salida (cualquiera activa la salida — OR)

1. **Pérdida de fuerza del valor (RSC Mansfield del activo < −0.5)**
   - Si `rsMan < -0.5` la acción es marcada para salida inmediata: está rindiendo sustancialmente peor que el mercado.
   - En el CSV de salida esta condición se etiqueta como **S1** en la columna `Motivo`.

2. **Coppock bajista (filtro de mercado, condición propia — `Sp500bajista`)**
   - Objetivo: salir de posiciones largas cuando el mercado general (S&P 500) muestra debilidad o inicio/confirmación de tendencia bajista.
   - Cómputo (implementado en `sp500_bajista()`):
     - *Cruce a negativo*: el Coppock estaba en terreno positivo (o cero) la semana anterior y pasa a negativo esta semana. Señala el fin de una tendencia alcista.
     - *Confirmación de bajista*: el Coppock ya es negativo y sigue cayendo respecto a la semana anterior. Señala que la tendencia bajista se mantiene y se fortalece.
   - El flag `Sp500bajista` se activa en cualquiera de las dos situaciones anteriores.
   - En el CSV de salida esta condición se etiqueta como **S2** en la columna `Motivo`, y en la columna `S2 Coppock Bajista`, que refleja directamente el resultado de `sp500_bajista()`.

### `Sp500alcista` y `Sp500bajista` NO son complementarias

Es un error común asumir que "mercado bajista" es simplemente `not Sp500alcista`. **No lo es.** Existe un **tercer estado neutro** — ni alcista ni bajista — en el que ninguna de las dos condiciones se cumple. Dos ejemplos:

- **Rebote tardío en negativo**: el Coppock está en negativo y sube respecto a la semana anterior, pero el valor de la semana anterior ya no es el mínimo de las últimas 4 semanas (porque el suelo real quedó más atrás). Esto no cumple `Sp500alcista` (exige que sea *justo* el primer rebote desde ese mínimo), pero tampoco cumple `Sp500bajista` (el Coppock está subiendo, no cayendo).
- **Positivo mermando**: el Coppock está por encima de 0 pero cae respecto a la semana anterior. No es "continuación alcista" (`Sp500alcista` exige `current > previous`), pero tampoco ha cruzado a negativo, así que tampoco es `Sp500bajista`.

`sp500_bajista()` es la función que implementa esta condición como una condición de mercado propia, fiel a la definición de la fuente original: el estado neutro no fuerza salidas.

Si cualquiera de las condiciones S1/S2 se cumple, el escáner etiqueta la posición como `SALIDA=True` e incluye el `Motivo` en el CSV de salida. Los prefijos `S1`/`S2` usados en `Motivo` están centralizados en `weinstein/config.py` (`EXIT_REASON_S1_LABEL`, `EXIT_REASON_S2_LABEL`) para que sea la única fuente de verdad si alguna vez se renombran.

> **Nota sobre el histórico y la columna `Versión Lógica`**: `historial/` conserva CSVs generados con distintas versiones de la lógica de S2, con distinto esquema de columnas:
>
> - **v1**: columna `S3 Coppock Bajista` (CSVs con fecha anterior a `posiciones_salidas_20260619_1342.csv`).
> - **v2**: columna `S2 Coppock No Alcista`, calculada como `not sp500_alcista(...)` — colapsaba el estado neutro dentro de "salida" (bug ya corregido).
> - **v3** (actual): columna `S2 Coppock Bajista`, calculada como `sp500_bajista()`.
>
> Los CSVs v1 y v2 usaban esquemas de columna que, mirados de forma aislada, no permiten distinguir programáticamente entre sí (v2 no se diferenciaba de v3 por el nombre de columna, solo por la fecha). Para evitar que este problema se repita, desde esta versión cada CSV exportado (entradas y salidas) incluye una columna `Versión Lógica` con el valor de `SCANNER_LOGIC_VERSION` (`weinstein/config.py`), que se incrementa cada vez que cambia el significado de alguna condición. Los CSVs anteriores a la introducción de esta columna no la incluyen; para esos, identifica la versión por la fecha del archivo según la lista de arriba.

## 5. Regla de desempate y selección final (ranking)

- Cuando hay más candidatos que posiciones disponibles (por ejemplo, límite `max_positions = 10`), se ordena por `MOM` descendente.
- `MOM = (C - WMA30) / WMA30` — cuanto mayor, más fuerte la tendencia reciente sobre la WMA30.
- Seleccionar las `N` primeras por MOM para abrir posiciones.

## 6. Parámetros por defecto (valores usados en el código)

- `SECTOR_RSC_MIN = 0.10` (umbral RSC sector fuerte)
- `VPM_BASE_PERIOD = 52` y `VPM_SMOOTHING = 5` (52 semanas para estadísticos de volumen, SMA5 para suavizar)
- `WMA30_PERIOD = 30` (periodo referencia WMA30)
- `MAX_DISTANCIA_WMA30 = 8.0` (%) — cota superior; sin cota inferior
- `RSC_EXIT_THRESHOLD = -0.5` (umbral de salida por RSC del activo)
- `COPPOCK_ROC_LONG = 12`, `COPPOCK_ROC_SHORT = 6`, `COPPOCK_WMA_PERIOD = 10` (Coppock semanal)
- `COPPOCK_RECENT_LOOKBACK = 4` (ventana de mínimo reciente usada solo por `sp500_alcista()` / F5; `sp500_bajista()` / S2 no usa esta ventana, ver sección 4)
- `DOWNLOAD_MAX_RETRIES = 3`, `DOWNLOAD_RETRY_BACKOFF_S = 1.5` (reintentos con backoff ante fallos puntuales de descarga en yfinance)

Notas: los nombres y ubicaciones de las constantes están en el código; consulta directamente `weinstein/config.py`, que es la única fuente de verdad de umbrales y periodos. El universo se carga desde la fuente de constituyentes por ticker, así que su tamaño puede variar con rebalanceos y clases múltiples.

## 7. Ejemplos orientativos de CSV

Ejemplo (salida del escáner de entrada):

```
Ticker,Nombre,Sector,ETF Sector,Precio Actual,RSC Mansfield Activo,Momentum (MOM),RSC Mansfield Sector,VPM5,Distancia % WMA30,Dirección Coppock SP500
CVX,Chevron Corporation,Energy,XLE,191.10,0.6133,0.0513,1.2554,0.2496,5.13,↑ Alcista
```

Ejemplo (salida del escáner de salidas — columnas y orden reales generados por `weinstein/scanner_exit.py`):

```
Ticker,Sector,Precio Entrada,Precio Actual,Rentabilidad %,RSC Mansfield,S1 RSC < -0.5,S2 Coppock Bajista,SALIDA,Motivo,Versión Lógica
MSFT,Technology,415.00,421.92,1.67,-1.8943,True,False,True,"S1: RSC=-1.894 < -0.5",v3
```

Cuando la descarga de un ticker falla, el CSV incluye además una columna `Error` con el motivo (no forma parte del ejemplo anterior por brevedad, pero siempre está presente en la salida real).

La columna `S2 Coppock Bajista` refleja directamente el resultado de `sp500_bajista()` (ver sección 4). La columna `Versión Lógica` identifica con qué versión de la lógica de la estrategia (`SCANNER_LOGIC_VERSION` en `weinstein/config.py`) se generó el archivo — ver la nota sobre el histórico en la sección 4.

## 8. Referencias de implementación (para quien edite el código)

- Cálculos y utilidades: [`weinstein/indicators.py`](../weinstein/indicators.py) — funciones importantes: `rsc_mansfield()`, `vpm5()`, `wma()`, `coppock_curve()`, `sp500_alcista()`, `sp500_bajista()`, `momentum_vs_wma()`, `distancia_wma_pct()`.
- Acceso a datos: [`weinstein/data.py`](../weinstein/data.py) — `download_weekly()` (con reintentos y backoff), `load_sp500_tickers()`, `load_positions()`.
- Parámetros y umbrales: [`weinstein/config.py`](../weinstein/config.py) — única fuente de verdad para constantes de la estrategia.
- Puntos de filtrado de entrada: [`weinstein/scanner_entry.py`](../weinstein/scanner_entry.py) — búsqueda de candidatos y aplicación de filtros F1-F5.
- Puntos de evaluación de salida: [`weinstein/scanner_exit.py`](../weinstein/scanner_exit.py) — condiciones OR (S1-S2) para cerrar posiciones; ver docstring del módulo para el detalle completo.
- Exportación a CSV: [`weinstein/exporter.py`](../weinstein/exporter.py).
- Tests que documentan el comportamiento esperado: [`tests/test_indicators.py`](../tests/test_indicators.py) (F5 / `sp500_alcista`) y [`tests/test_sp500_bajista.py`](../tests/test_sp500_bajista.py) (S2 / `sp500_bajista`, incluyendo los casos del estado neutro descritos en la sección 4).

## 9. Notas finales

- Este documento pretende ser complementario a la explicación de uso; no modifica la lógica del código ni los parámetros por defecto. Para ajustar umbrales o lógica, editar las constantes y funciones referenciadas en el código y mantener la coherencia con estas notas.
- Referencia original explicativa (video): https://youtu.be/reQWjzedlX0?si=xSsagVeCSqrX7miV