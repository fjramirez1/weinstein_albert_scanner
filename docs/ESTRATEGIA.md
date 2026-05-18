# Condiciones de la estrategia (detallado)

Esta página contiene la descripción técnica completa de los filtros, cálculos y criterios usados por los scripts del repositorio. Está pensada para consultores o desarrolladores que quieran entender o ajustar las fórmulas.

## Condiciones de Entrada (todas deben cumplirse / AND)

1. Fuerza del sector positiva: `RSC Mansfield Sector >= +0.10`.
2. Volumen normalizado positivo: `VPM5 > 0`.
   - `VPM5` se calcula como la SMA de 5 semanas del VPM (volumen estandarizado) sobre las últimas 52 semanas.
3. Fuerza del valor positiva (RSC Mansfield activo).
4. Distancia respecto a la WMA30 menor que 8 %.
5. `Sp500alcista = True` según la curva de Coppock semanal:
   - Inicio alcista: Coppock sigue por debajo de 0, el valor previo fue el mínimo reciente y la curva empieza a girar al alza.
   - Continuación alcista: Coppock ya es positivo y sigue subiendo.

En conjunto, estos filtros seleccionan valores con fuerza relativa y volumen, cercanos a su media WMA30 y en un mercado alcista definido por la curva de Coppock.

### Momentum y desempate

- `Momentum (MOM)` se calcula como `(Precio Actual - WMA30) / WMA30`.
- Tras aplicar los filtros (AND), los candidatos se ordenan por `Momentum (MOM)` descendente y se limita la lista final a las N posiciones superiores (por defecto top 10), usando MOM como criterio de desempate.

## Cómo se calcula VPM5

1. Calcular la media (`media52`) y la desviación estándar (`desviacion52`) del volumen en las últimas 52 semanas.
2. Para cada semana `t`, calcular `VPM(t) = (Volumen(t) - media52) / desviacion52`.
3. Suavizar la serie `VPM(t)` con una SMA de 5 semanas: `VPM5(t) = SMA5(VPM(t))`.

Filtro operativo: considerar el valor solo si `VPM5 > 0`.

## Condiciones de Salida (cualquiera activa la salida / OR)

1. Pérdida de fuerza del valor: `RSC Mansfield del Activo < −0.5`.
2. Coppock bajista: el Coppock semanal del S&P 500 está por debajo de 0 y además es menor que el valor de la semana anterior.
3. Trailing stop: basado en los cierres semanales desde la fecha de entrada (implementación concreta en `weinstein_albert_exit_scanner.py`).

Si cualquiera de las condiciones se cumple, el escáner marca `SALIDA=True` y añade una explicación en la columna `Motivo`.

## Notas de implementación

- Las medias WMA/EMA y las funciones de RSC, Coppock y VPM están implementadas en `we_utils.py`.
- Los umbrales (`+0.10` para RSC sector, `-0.5` para RSC activo, `8%` distancia a WMA30) pueden ajustarse en el código si se desea experimentar.
- Las salidas se registran en `<archivo_entrada>_salidas_YYYYMMDD_HHMM.csv` con columnas que muestran la bandera de salida y el motivo.

## Referencias

- Material base: video explicativo y notas: https://youtu.be/reQWjzedlX0?si=xSsagVeCSqrX7miV
