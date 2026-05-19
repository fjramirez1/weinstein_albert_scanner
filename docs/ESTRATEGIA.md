# Condiciones de la estrategia (detallado)

Este documento amplía y explica con más detalle los criterios operativos usados por los escáneres del repositorio. Incluye definiciones, fórmulas, umbrales y ejemplos orientativos para facilitar el mantenimiento y la validación documental (sin tocar la implementación).

## 1. Definiciones clave

- **RSC Mansfield (Sector)**: mide la fortaleza relativa del índice sectorial frente al S&P 500. Se calcula comparando la serie de precios del ETF sectorial con la del S&P 500 y aplicando la transformación "Mansfield" para detectar consistencia en la fortaleza.
- **RSC Mansfield (Activo / rsMan)**: mismo procedimiento aplicado a la acción frente al S&P 500. Valores positivos indican mejor comportamiento relativo.
- **VPM5 (Volumen Proporcional Medio 5 semanas)**: volumen estandarizado respecto a las últimas 52 semanas, suavizado con una SMA de 5 semanas. Indica si el volumen actual es atípico respecto al histórico.
- **WMA30 / MA30**: media móvil ponderada (o simple según implementación) de 30 sesiones; referencia de tendencia de medio plazo.
- **Distancia % respecto a WMA30**: distancia relativa del precio al WMA30: Dist% = (Precio Actual − WMA30) / WMA30 (expresado en %).
- **Coppock semanal**: indicador de estado de mercado construido como WMA de la suma de dos ROC (periodos típicos usados: 14 y 11 semanas). Se usa como filtro de mercado (alcista / bajista).
- **MOM (Momentum relativo para desempate)**: medida relativa del precio sobre su MA30: MOM = (C − MA30) / MA30.

## 2. Cálculos resumidos (cómo se obtienen)

- **VPM5**:
  1. Calcular `media52` y `desv52` del volumen semanal de las últimas 52 semanas.
  2. `VPM(t) = (Volumen(t) - media52) / desv52`.
  3. `VPM5(t) = SMA_5(VPM(t))`.

- **RSC Mansfield (general)**:
  1. Tomar series de precios semanales: `P_activo(t)` y `P_ref(t)` (S&P 500 o ETF sectorial).
  2. Calcular la serie relativa `R(t) = P_activo(t) / P_ref(t)`.
  3. Aplicar una suavización (p. ej. SMA sobre 52 períodos) y/o la transformación Mansfield para medir consistencia. El resultado positivo indica fortaleza relativa sostenida.

- **Distancia % a WMA30**: `Dist% = 100 * (C - WMA30) / WMA30`.

- **Coppock semanal**: `Coppock(t) = WMA_k( ROC_n1(P) + ROC_n2(P) )` con n1=14, n2=11 y k=10 en la configuración típica.

- **MOM (desempate)**: `MOM = (C - MA30) / MA30`. Se usa solo para ordenar candidatos que cumplen todos los filtros.

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
   - Objetivo: evitar entradas en valores excesivamente sobrecomprados y favorecer entradas próximas a la tendencia de medio plazo.
   - Cómputo: Dist% (ver sección 2). Se exige Dist% < +8% (es decir, el precio no debe superar la WMA30 en más del 8%).

5. **Filtro de Mercado — Coppock Alcista (Sp500alcista = True)**
   - Objetivo: abrir posiciones largas solo cuando el mercado general muestra inicio o continuación de tendencia alcista.
   - Criterio operativo:
     - *Inicio de alcista desde negativo*: Coppock está en terreno negativo, ha marcado un mínimo reciente y comienza a girar al alza.
     - *Continuación de alcista positivo*: Coppock está por encima de 0 y sigue aumentando.
   - El flag `Sp500alcista` se activa en cualquiera de las dos situaciones anteriores.

> Idea operativa: todas las condiciones anteriores deben cumplirse para que una acción sea considerada candidata de compra.

## 4. Filtros de salida (cualquiera activa la salida — OR)

1. **Pérdida de fuerza del valor (RSC Mansfield del activo < −0.5)**
   - Si `rsMan < -0.5` la acción es marcada para salida inmediata: está rindiendo sustancialmente peor que el mercado.

2. **Coppock bajista (filtro de mercado)**
   - Si la curva de Coppock semanal está por debajo de 0 y desciende respecto a la semana anterior, el mercado muestra debilidad y se cierran posiciones largas.

3. **Trailing stop / Reglas adicionales**
   - El repositorio incluye reglas de gestión y trailing stops en `weinstein_albert_exit_scanner.py`; las salidas se combinan con las condiciones anteriores.

Si cualquiera de las condiciones se cumple, el escáner etiqueta la posición como `SALIDA=True` e incluye el `Motivo` en el CSV de salida.

## 5. Regla de desempate y selección final (ranking)

- Cuando hay más candidatos que posiciones disponibles (por ejemplo, límite `max_positions = 10`), se ordena por `MOM` descendente.
- `MOM = (C - MA30) / MA30` — cuanto mayor, más fuerte la tendencia reciente sobre la MA30.
- Seleccionar las `N` primeras por MOM para abrir posiciones.

## 6. Parámetros por defecto (valores usados en el código)

- `SECTOR_RSC_MIN = 0.10` (umbral RSC sector fuerte)
- `VPM_PERIOD = 52` y `VPM_SMOOTH = 5` (52 semanas para estadísticos de volumen, SMA5 para suavizar)
- `WMA30_PERIOD = 30` (periodo referencia MA30/WMA30)
- `MAX_DISTANCIA_WMA30 = 8.0` (%)
- `RSC_SALIDA_UMBRAL = -0.5` (umbral de salida por RSC del activo)
- `COPPOCK_ROC1 = 14`, `COPPOCK_ROC2 = 11`, `COPPOCK_WMA = 10` (configuración típica Coppock semanal)

Notas: los nombres y ubicaciones de las constantes están en el código; consulte las funciones y constantes en [we_utils.py](we_utils.py#L1-L200) y los puntos de aplicación en [weinstein_albert_scanner.py](weinstein_albert_scanner.py#L1-L500) y [weinstein_albert_exit_scanner.py](weinstein_albert_exit_scanner.py#L1-L350).

## 7. Ejemplos orientativos de CSV

Ejemplo (salida del escáner de entrada):

Ticker,Nombre,Sector,ETF Sector,Precio Actual,RSC Mansfield Activo,MOM,RSC Mansfield Sector,VPM5,Distancia % WMA30,Sp500_Coppock
CVX,Chevron Corporation,Energy,XLE,191.10,0.6133,0.0513,1.2554,0.2496,5.13,True

Ejemplo (salida del escáner de salidas):

Ticker,Sector,Precio Entrada,Precio Actual,Rentabilidad %,RSC Mansfield,S1 RSC < -0.5,S3 Coppock Bajista,SALIDA,Motivo
MSFT,Technology,415.00,421.92,1.67,-1.8943,True,False,True,"S1: RSC=-1.894 < -0.5"

## 8. Referencias de implementación (para quien edite el código)

- Cálculos y utilidades: [we_utils.py](we_utils.py#L1-L200) — funciones importantes: `rsc_mansfield()`, `vpm5()`, `wma()`, `coppock_curve()`, `calculate_mom()`, `sp500_alcista()`.
- Puntos de filtrado de entrada: [weinstein_albert_scanner.py](weinstein_albert_scanner.py#L1-L500) — búsqueda de candidatos y aplicación de filtros.
- Puntos de evaluación de salida: [weinstein_albert_exit_scanner.py](weinstein_albert_exit_scanner.py#L1-L350) — condiciones OR para cerrar posiciones.

## 9. Notas finales

- Este documento pretende ser complementario a la explicación de uso; no modifica la lógica del código ni los parámetros por defecto. Para ajustar umbrales o lógica, editar las constantes y funciones referenciadas en el código y mantener la coherencia con estas notas.
- Referencia original explicativa (video): https://youtu.be/reQWjzedlX0?si=xSsagVeCSqrX7miV
