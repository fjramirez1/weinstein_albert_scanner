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
COPPOCK_RECENT_LOOKBACK = 4    # ventana para detectar mínimo reciente

# ── Filtros de entrada (AND) ──────────────────────────────────────────
SECTOR_RSC_MIN      = 0.10    # F1: RSC Mansfield sector >= umbral
MAX_DISTANCIA_WMA30 = 8.0     # F4: precio no supera WMA30 en más de X %
MAX_CANDIDATES      = 10      # número máximo de candidatos en el ranking

# ── Filtros de salida (OR) ────────────────────────────────────────────
RSC_EXIT_THRESHOLD = -0.5     # S1: RSC Mansfield activo < umbral → salida

# Etiquetas de las condiciones de salida. Única fuente de verdad para los
# prefijos usados en la columna "Motivo" del CSV de salidas — si el nombre
# de una condición cambia (p.ej. renombrados anteriores S3 -> S2), basta
# con actualizarlo aquí.
EXIT_REASON_S1_LABEL = "S1: RSC"
EXIT_REASON_S2_LABEL = "S2: Coppock SP500 no alcista"
EXIT_REASON_NONE     = "—"

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
