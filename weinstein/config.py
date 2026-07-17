"""
Parámetros globales de la estrategia Weinstein-Albert.

Editar este módulo para ajustar umbrales o periodos sin tocar
la lógica de los escáneres.
"""

# ── Índice de referencia ──────────────────────────────────────────────
SP500_INDEX = "^GSPC"

# URL pública con los constituyentes del S&P 500 (fallback: Wikipedia).
SP500_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies"
    "/master/data/constituents.csv"
)

# URL de la página de Wikipedia usada tanto para el fallback de
# constituyentes actuales (weinstein/data.py) como para la tabla de
# cambios históricos (backtest/sp500_historical.py).
SP500_WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# ── Descarga de datos ─────────────────────────────────────────────────
DOWNLOAD_PERIOD_ENTRY = "6y"
DOWNLOAD_PERIOD_EXIT  = "5y"
MIN_BARS              = 70       # mínimo de velas semanales requeridas

# Reintentos con backoff para descargas yfinance (robustez ante fallos
# puntuales de red o rate-limiting).
DOWNLOAD_MAX_RETRIES     = 3
DOWNLOAD_RETRY_BACKOFF_S = 1.5    # segundos, se multiplica por el nº de intento

# ── Indicadores técnicos ──────────────────────────────────────────────
WMA30_PERIOD     = 30
RSC_SMA_PERIOD   = 52    # ventana de la SMA en el cálculo RSC Mansfield
VPM_BASE_PERIOD  = 52    # semanas para estadísticos de volumen
VPM_SMOOTHING    = 5     # periodos de la SMA que suaviza el VPM

# Coppock semanal: WMA(10) de (ROC_12 + ROC_6)
COPPOCK_ROC_LONG        = 12
COPPOCK_ROC_SHORT       = 6
COPPOCK_WMA_PERIOD      = 10
# Ventana usada SOLO por sp500_alcista() (F5) para detectar el mínimo
# reciente del "inicio de tendencia alcista". sp500_bajista() (S2) no usa
# esta ventana: su condición de bajista no depende de un mínimo/máximo
# reciente, solo de la comparación con la semana inmediatamente anterior
# (ver weinstein/indicators.py::sp500_bajista y docs/ESTRATEGIA.md sec. 4).
COPPOCK_RECENT_LOOKBACK = 4

# ── Filtros de entrada (AND) ──────────────────────────────────────────
SECTOR_RSC_MIN      = 0.10    # F1: RSC Mansfield sector >= umbral
MAX_DISTANCIA_WMA30 = 8.0     # F4: precio no supera WMA30 en más de X %
MAX_CANDIDATES       = 10      # número máximo de candidatos en el ranking

# ── Filtros de salida (OR) ────────────────────────────────────────────
RSC_EXIT_THRESHOLD = -0.5     # S1: RSC Mansfield activo < umbral → salida

# Etiquetas de las condiciones de salida. Única fuente de verdad para los
# prefijos usados en la columna "Motivo" del CSV de salidas — si el nombre
# de una condición cambia, basta con actualizarlo aquí.
EXIT_REASON_S1_LABEL = "S1: RSC"
# S2 refleja sp500_bajista() (condición de mercado bajista propia, ver
# weinstein/indicators.py y docs/ESTRATEGIA.md sec. 4) — NO es el
# complemento lógico de sp500_alcista().
EXIT_REASON_S2_LABEL = "S2: Coppock SP500 bajista"
EXIT_REASON_NONE     = "—"

# ── Versión de la lógica del escáner ──────────────────────────────────
# Se añade como columna en cada CSV exportado (entradas y salidas) para
# poder distinguir programáticamente, sin ambigüedad, con qué versión de
# la lógica se generó cada archivo histórico. Incrementar este valor
# cada vez que cambie el significado/cálculo de alguna condición (F1-F5,
# S1-S2), no solo su nombre de columna o etiqueta.
#
# Historial de versiones:
#   v1 -> S2 calculada como "S3 Coppock Bajista" (esquema de columna antiguo)
#   v2 -> S2 calculada como `not sp500_alcista(...)` (bug, columna ya
#         renombrada a "S2 Coppock No Alcista")
#   v3 -> S2 calculada como `sp500_bajista()` (condición propia, corregida);
#         columna renombrada a "S2 Coppock Bajista"
# Los CSVs generados antes de introducir esta constante no la incluyen;
# para esos, consulta la fecha del archivo y el historial en README/
# docs/ESTRATEGIA.md para saber a qué versión corresponden.
SCANNER_LOGIC_VERSION = "v3"

# ── Mapeo sector GICS → ETF sectorial SPDR ───────────────────────────
SECTOR_TO_ETF: dict[str, str] = {
    "Communication Services": "XLC",
    "Consumer Cyclical":      "XLY",
    "Consumer Defensive":     "XLP",
    "Energy":                 "XLE",
    "Financial Services":     "XLF",
    "Healthcare":             "XLV",
    "Industrials":            "XLI",
    "Basic Materials":        "XLB",
    "Real Estate":            "XLRE",
    "Technology":             "XLK",
    "Utilities":              "XLU",
}

# ── Rutas por defecto ─────────────────────────────────────────────────
DEFAULT_POSITIONS_CSV = "posiciones.csv"
HISTORY_ENTRIES_DIR   = "historial/entradas"
HISTORY_EXITS_DIR     = "historial/salidas"

# ── Backtest de estrategia completa ───────────────────────────────────
# Parámetros específicos del motor de backtest (backtest/strategy_backtest.py).
# Separados de los umbrales de la estrategia en sí para no mezclar
# "cómo se simula" con "qué significa cada filtro".
BACKTEST_PERIOD_DEFAULT       = "10y"   # histórico a descargar por ticker
BACKTEST_MIN_BARS             = RSC_SMA_PERIOD + WMA30_PERIOD + 10  # barras mínimas para poder evaluar F1-F5/S1-S2
BACKTEST_MAX_WORKERS          = 20      # hilos concurrentes para descargar tickers
