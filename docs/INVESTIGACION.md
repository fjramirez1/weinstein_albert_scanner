# Investigación externa: fuentes de datos y estrategias parecidas

Resumen de lo que encontraron los agentes de investigación el 2026-11-04
(ver `docs/BITACORA.md`). No sustituye a nuestro backtest: cualquier idea
de aquí se prueba con el motor corregido antes de adoptarse.

## 1. Fuentes de datos gratuitas (el usuario no va a pagar)

El problema principal para ir hacia atrás son los **deslistados**, sobre
todo los de **ticker reutilizado** por otra empresa (S = Sprint/SentinelOne,
STI, CA, EMC, DOW antigua, SNDK, DELL, CEG...). yfinance no tiene
deslistados y, con un ticker reutilizado, devuelve la empresa nueva.

| Fuente | Qué aporta | Límites / problemas |
|---|---|---|
| **Tiingo gratis** (3 claves, ya en uso) | Deslistados sobre todo desde ~2009, con OHLCV | 50 peticiones/hora y clave; 500 símbolos únicos/mes. Con un ticker reutilizado sirve al dueño actual |
| **Tiingo por permaTicker** | Podría servir los reutilizados: `/tiingo/fundamentals/meta` da el permaTicker y luego `/tiingo/daily/<permaTicker>/prices` | **Sin verificar** en la cuenta gratuita. El repo Johnbrick123/sp500-data dice usarlo con el plan gratuito |
| Símbolos propios en Tiingo | Algunos reutilizados tienen otro símbolo: TE1, DTV1, NEBLQ, SHLDQ, HSH, SBNY | Ya en `TIINGO_PRICE_SYMBOLS` (`weinstein/config.py`) |
| **fja05680/sp500** (GitHub) | Membresía del S&P 500 desde 1996, más completa que Wikipedia antes de 2011 | Usar el fichero original (con sufijos `-YYYYMM`), no el "Updated" |
| **Johnbrick123/sp500-data** (GitHub) | Precios 1968-2026 de 1.895 tickers con muertos etiquetados `-YYYYMM` y mapeo a PERMNO/permaTicker | **Sin licencia**; el 65 % de las filas de muertos vienen de CRSP (no redistribuible, sin OHLC ni volumen); algún empalme erróneo (BTUUQ). Útil para validar, no como fuente única |
| Kaggle `ehallmar/daily-historical-stock-prices-1970-2018` | Foto de Yahoo de 2018, con S, STI, CA antes de su reutilización | Licencia "Unknown"; pega empresas distintas bajo el mismo ticker |
| QuantConnect (nube) | Datos sin sesgo de supervivencia desde 1998 | No se pueden descargar: habría que portar el backtest a su plataforma |
| Quandl WIKI | Incluía muertos | Ya no se sirve |
| EODHD / FMP / Polygon / Alpha Vantage gratis | — | Gratis no dan deslistados o solo 1-2 años |

**Conclusión:** sin pagar, la cobertura buena de precios llega hasta ~2009-2010. Para
1996-2009 solo hay cierres de CRSP de licencia dudosa o QuantConnect.

## 2. Proyectos y estudios parecidos

**No existe ningún repositorio público de Weinstein / RSC Mansfield con un
backtest de cartera riguroso** (membresía histórica, costes, ejecución
realista). Lo aprovechable son ideas y metodología.

### Lo que ya concuerda con nuestros resultados
- **Roskill (SSRN, 2026)**, el único estudio formal de Stage Analysis:
  - solo la etapa 2 da exceso (+2,3 %/año);
  - el método completo equivale a un filtro de media simple (mismo Sharpe);
  - la capa de fuerza relativa resulta inerte;
  - usar los miembros actuales infla la etapa 2 en 6,3 %/año.
- **MarketInOut (2026)**, Trend Template de Minervini en el S&P 500 con
  membresía histórica, 20 posiciones y comisiones: 7,9 %/año frente a
  8,2 % de SPY desde 2000. Tampoco bate al índice.
- **Timing con medias** (Zakamulin, Faber, CXO):
  - su valor se concentra en bajistas largos (2000-02, 2008); en crisis en
    V (2018, 2020) resta;
  - **un filtro de mercado no se puede juzgar sin 2000-2002 y 2008**, lo
    que explica lo visto en O2/O3.
- **High-volume return premium** (Gervais-Kaniel-Mingelgrin 2001,
  replicado en 41 países): un volumen anormalmente alto predice mejor
  rentabilidad el mes siguiente. **Respalda el hallazgo de que VPM5 es el
  ranking más robusto** (VPM5 es un z-score de volumen anormal).

### Lo que cuestiona nuestras reglas
- **F4 (< 8 % sobre la WMA30) va contra la evidencia.** Las acciones más
  alejadas por encima de su media larga (MAD de Avramov et al. 2021) y
  las cercanas a su máximo de 52 semanas (George-Hwang 2004) rinden más.
  F4 excluye justo esas. Nota: nuestro ranking MOM sí ordena de más a
  menos extendida, pero solo dentro del tope de F4.
- **Nuestra "Coppock" no es la original:** usamos ROC(12) + ROC(6)
  semanales con WMA(10), unas 4-5 veces más rápida. La original es mensual,
  ROC(14) + ROC(11) con WMA(10) meses, que en semanas es ≈ ROC(61) +
  ROC(48) con WMA(43). Coppock la diseñó **solo como señal de compra** tras
  bajistas, y nosotros la usamos también como salida (S2). No hay estudios
  académicos que la respalden.
- **Momentum en grandes compañías debilitado desde 2000**, y la rotación
  sectorial con ETF peor después de 2010, lo que afecta a F1.
- **Momentum crashes** (Daniel-Moskowitz 2016): en los rebotes tras
  bajistas, exigir RSC > 0 compra defensivas mientras rebotan las
  castigadas.
- **Stops ajustados restan** (Lo-Remorov, Clare et al.); las salidas lentas
  reducen el drawdown con poco coste.
- **10 posiciones**: por la asimetría de rentabilidades (Bessembinder), la
  mediana de una cartera pequeña queda por debajo del índice aun sin
  habilidad. MarketInOut usa 20 y Clenow 20-30.

### Lecciones de metodología
- **Potencia estadística:** con ~10 años, el error estándar del alfa anual
  ronda el 4 %, así que un exceso menor de ~7-8 %/año no se distingue de
  cero en una sola trayectoria. Medir también las señales de forma
  transversal: correlación de rango semanal señal → rentabilidad futura
  (IC) y diferencial entre quintiles.
- **Benchmarks justos:** además de SPY, **RSP** (S&P 500 de igual peso,
  comparable a 10 posiciones con igual peso; rinde 2-4 pp/año menos que SPY
  en la última década) y la distribución de **carteras aleatorias** del
  mismo universo, que ya usamos con rankings aleatorios; conviene subir a
  cientos de semillas.
- **Sobreajuste:** llevar la cuenta de variantes probadas, Deflated Sharpe
  Ratio, PBO con CSCV y walk-forward. Robustez al parámetro antes que un
  óptimo puntual.
- **Sesgos pendientes:**
  - rentabilidad de deslistado: cerrar al último precio sobrestima las
    quiebras;
  - sector actual aplicado al pasado: es una decisión consciente, ver
    `config.py`.

## 3. Hipótesis a probar cuando el rango esté ampliado

1. **F4 y el ranking:**
   - quitar F4;
   - ordenar por MAD (WMA10/WMA40 semanal) o por cercanía al máximo de
     52 semanas;
   - combinar con VPM5 por rangos.
   Medir antes el IC de cada señal.
2. **Filtro de mercado lento y solo de entrada**, juzgado con 2008 dentro:
   - Coppock con los parámetros originales en semanas (61/48/43);
   - SPY sobre su media de 43 semanas;
   - momentum absoluto de 12 meses;
   - amplitud (porcentaje de miembros sobre su WMA30).
   Probar también quitar S2.
3. **Benchmarks y tamaño:** RSP y carteras aleatorias como referencias;
   N = 10 / 20 / 30.
4. **Fuerza relativa:**
   - momentum 12-1 (sin el último mes) o RS rating de IBD en lugar del
     RSC Mansfield;
   - ver si F1 aporta algo.
5. **Salidas más lentas:**
   - S1 a −1,0;
   - cierre bajo la WMA30;
   - tenencia mínima de 13-26 semanas.

**Escala del RSC:** `rsc_mansfield` multiplica por 10 (la definición clásica
usa ×100). F1 ≥ 0,10 equivale a un ratio un 1 % sobre su SMA52 y S1 < −0,5
a un 5 % por debajo. Hay que confirmar con el vídeo (V1) que Albert usa la
misma escala.

## Fuentes principales

- Datos: https://github.com/fja05680/sp500 · https://github.com/Johnbrick123/sp500-data ·
  https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip ·
  https://www.tiingo.com/documentation/general/changelog
- Roskill: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7429238
- MarketInOut: https://www.marketinout.com/blog/minervini-trend-template-backtest-markets
- MAD: https://ideas.repec.org/a/wly/revfec/v39y2021i2p127-145.html
- Volumen: https://econpapers.repec.org/RePEc:bla:jfinan:v:56:y:2001:i:3:p:877-919
- Timing: https://www.cxoadvisory.com/technical-trading/market-timing-with-moving-averages-over-the-very-long-run
- Momentum crashes: https://www.nber.org/system/files/working_papers/w20439/w20439.pdf
- Stops: https://dspace.mit.edu/handle/1721.1/107017
- Bessembinder: https://wpcarey.asu.edu/department-finance/faculty-research/do-stocks-outperform-treasury-bills
- PBO/CSCV: https://papers.ssrn.com/abstract=2326253
