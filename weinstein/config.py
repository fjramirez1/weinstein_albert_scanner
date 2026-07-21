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

# ── Fallback Tiingo (tickers delistados que yfinance ya no sirve) ─────
# yfinance deja de servir histórico en cuanto un ticker se deslista por
# completo (quiebra, fusión, adquisición, exclusión de bolsa...). Esto
# NO se soluciona con más reintentos: es una ausencia permanente de la
# fuente para ese ticker. Se probó Stooq como respaldo, pero bloquea el
# acceso automatizado (robots.txt + 404 poco fiables, ver historial de
# incidencias en weinstein/data.py). Tiingo (https://api.tiingo.com)
# ofrece una REST API real con token, usada como respaldo de última
# instancia en `weinstein/data.py::download_weekly` (nunca como fuente
# primaria). Requiere la variable de entorno TIINGO_API_KEY (API key
# gratuita, ver https://www.tiingo.com); si no está definida, el
# fallback se desactiva solo con un aviso, sin fallar.
# Desactivar poniendo esto a False si se prefiere no depender de Tiingo.
TIINGO_FALLBACK_ENABLED = True
TIINGO_BASE_URL = "https://api.tiingo.com/tiingo/daily"

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
# Claves = nombres GICS REALES tal como los devuelve load_sp500_tickers()
# (fuente primaria CSV y fallback de Wikipedia usan esta nomenclatura).
SECTOR_TO_ETF: dict[str, str] = {
    "Communication Services":  "XLC",
    "Consumer Discretionary":  "XLY",
    "Consumer Staples":        "XLP",
    "Energy":                  "XLE",
    "Financials":               "XLF",
    "Health Care":              "XLV",
    "Industrials":              "XLI",
    "Materials":                 "XLB",
    "Real Estate":              "XLRE",
    "Information Technology":  "XLK",
    "Utilities":                "XLU",
}

# Alias por si alguna fuente usa nombres GICS antiguos o alternativos en
# vez de los canónicos de arriba. Clave = variante alternativa,
# valor = nombre canónico presente en SECTOR_TO_ETF. Se resuelve con
# resolve_sector_etf() en vez de SECTOR_TO_ETF.get() directo, para no
# depender de una coincidencia exacta.
_SECTOR_ALIASES: dict[str, str] = {
    "Consumer Cyclical":   "Consumer Discretionary",
    "Consumer Defensive":  "Consumer Staples",
    "Financial Services":  "Financials",
    "Healthcare":           "Health Care",
    "Basic Materials":      "Materials",
    "Technology":            "Information Technology",
    "Info Tech":             "Information Technology",
}


def resolve_sector_etf(sector_name: str | None) -> str | None:
    """
    Devuelve el ETF SPDR correspondiente a un nombre de sector, tolerando
    variantes de nomenclatura entre fuentes (CSV primario, fallback de
    Wikipedia, nombres GICS antiguos). Devuelve None si no se reconoce.
    """
    if not sector_name:
        return None
    if sector_name in SECTOR_TO_ETF:
        return SECTOR_TO_ETF[sector_name]
    canonical = _SECTOR_ALIASES.get(sector_name)
    if canonical:
        return SECTOR_TO_ETF.get(canonical)
    return None


# ── Sector histórico de tickers delistados (universo "historical") ────
# Mapeo manual y estático de Symbol -> Sector GICS para tickers que ya
# NO pertenecen al S&P 500 actual y por tanto no aparecen en
# `load_sp500_tickers()` (fusionados, quebrados, adquiridos, excluidos
# por rebalanceo, etc.). Sin esta tabla, `_build_historical_universe_rows`
# en `backtest/portfolio_backtest.py` no tiene forma de asignarles un
# sector, caen a "Unknown", `resolve_sector_etf()` devuelve None, y F1
# (RSC sector) los excluye SIEMPRE — sesgo documentado con cifras
# exactas en `backtest/portfolio_backtest.py::_build_historical_universe_rows`
# y en `backtest/BACKTEST.md` sección 4.
#
# Alcance deliberadamente acotado: cubre solo los tickers delistados que
# además tienen histórico de precio suficiente en la caché (evaluables
# por F2-F5 si F1 pudiera resolverse) — no tiene sentido mantener sector
# de tickers que jamás van a poder simularse por falta de datos de
# precio (esos se reportan aparte, ver `tickers_historicos_sin_precio`).
#
# El sector asignado es el sector GICS que la empresa tenía en su
# ÚLTIMA clasificación conocida antes de salir del índice (fuente:
# Wikipedia "List of S&P 500 companies" / "Selected changes..." y perfil
# de empresa correspondiente). Reclasificaciones GICS intermedias durante
# la vida de la empresa en el índice no se modelan (limitación conocida,
# igual que la propia tabla de altas/bajas no captura reclasificaciones
# sectoriales sin entrada/salida de índice) — es una aproximación
# deliberada, más precisa que "Unknown" pero no un histórico GICS
# punto-en-el-tiempo completo (alternativa 2 evaluada y descartada por
# falta de fuente fiable sin coste/API key, ver BACKTEST.md sección 4).
#
# Mantenimiento: si un ticker nuevo sale del índice y aparece con
# Sector="Unknown" en una ejecución con `universe="historical"`, añadir
# aquí su símbolo y sector GICS (con la empresa/fuente en el comentario)
# en vez de dejarlo caer a Unknown en silencio.
HISTORICAL_DELISTED_SECTORS: dict[str, str] = {
    # Consumer Discretionary
    "TWTR": "Communication Services",   # Twitter -> adquirida por X Corp (privada) 2022
    "ATVI": "Communication Services",   # Activision Blizzard -> adquirida por Microsoft 2023
    "SGEN": "Health Care",              # Seagen -> adquirida por Pfizer 2023
    "CELG": "Health Care",              # Celgene -> adquirida por Bristol-Myers Squibb 2019
    "XLNX": "Information Technology",   # Xilinx -> adquirida por AMD 2022
    "ETFC": "Financials",               # E*TRADE -> adquirida por Morgan Stanley 2020
    "WLTW": "Financials",               # Willis Towers Watson -> renombrada a WTW (alias ya cubierto en data.py)
    "FISV": "Information Technology",   # Fiserv -> renombrada a FI
    "ANTM": "Health Care",              # Anthem -> renombrada a Elevance Health (ELV)
    "FB":   "Communication Services",   # Facebook -> renombrada a Meta Platforms (META)
    "DISCA": "Communication Services",  # Discovery -> fusión con WarnerMedia -> WBD
    "VIAC": "Communication Services",   # ViacomCBS -> renombrada a Paramount Global (PARA)
    "CTXS": "Information Technology",   # Citrix Systems -> privatizada 2022
    "PBCT": "Financials",               # People's United Financial -> adquirida por M&T Bank 2022
    "CERN": "Health Care",              # Cerner -> adquirida por Oracle 2022
    "XRX":  "Information Technology",   # Xerox Holdings -> excluida del índice
    "NLSN": "Industrials",              # Nielsen Holdings -> privatizada 2022
    "PXD":  "Energy",                   # Pioneer Natural Resources -> adquirida por ExxonMobil 2024
    "FRC":  "Financials",               # First Republic Bank -> quiebra/adquisición por JPMorgan 2023
    "SIVB": "Financials",               # SVB Financial Group -> quiebra 2023
    "SBNY": "Financials",               # Signature Bank -> quiebra 2023
    "APC":  "Energy",                   # Anadarko Petroleum -> adquirida por Occidental 2019
    "CXO":  "Energy",                   # Concho Resources -> adquirida por ConocoPhillips 2021
    "WCG":  "Health Care",              # WellCare Health Plans -> adquirida por Centene 2020
    "RTN":  "Industrials",              # Raytheon -> fusión con United Technologies -> RTX
    "UTX":  "Industrials",              # United Technologies -> fusión -> Raytheon Technologies (RTX)
    "TIF":  "Consumer Discretionary",   # Tiffany & Co. -> adquirida por LVMH 2021
    "ALXN": "Health Care",              # Alexion Pharmaceuticals -> adquirida por AstraZeneca 2021
    "MXIM": "Information Technology",   # Maxim Integrated -> adquirida por Analog Devices 2021
    "XEC":  "Energy",                   # Cimarex Energy -> fusión con Cabot Oil & Gas -> Coterra (CTRA)
    "COG":  "Energy",                   # Cabot Oil & Gas -> fusión -> Coterra (CTRA)
    "VAR":  "Health Care",              # Varian Medical Systems -> adquirida por Siemens Healthineers 2021
    "KSU":  "Industrials",              # Kansas City Southern -> adquirida por Canadian Pacific 2021
    "KEYS": "Information Technology",   # Keysight Technologies (por si aparece con símbolo alternativo)
    "DISCK": "Communication Services",  # Discovery clase C -> fusión -> WBD
    "PEAK": "Real Estate",              # Healthpeak Properties (símbolo antiguo)
    "FLIR": "Information Technology",   # FLIR Systems -> adquirida por Teledyne 2021
    "GPS":  "Consumer Discretionary",   # Gap Inc. -> excluida del índice
    "HFC":  "Energy",                   # HollyFrontier -> renombrada a HF Sinclair (DINO)
    "ADS":  "Financials",               # Alliance Data Systems -> renombrada/escindida -> Bread Financial (BFH)
    "RE":   "Financials",               # Everest Re -> renombrada a Everest Group (EG)
    "FBHS": "Industrials",              # Fortune Brands Home & Security -> renombrada a Fortune Brands Innovations (FBIN)
}


def resolve_historical_sector(symbol: str, current_sector_map: dict[str, str]) -> str:
    """
    Resuelve el sector GICS de un ticker para el universo histórico.

    Orden de resolución:
      1. Si el ticker está en los constituyentes ACTUALES del S&P 500
         (`current_sector_map`, típicamente `load_sp500_tickers()`), se
         usa ese sector — es la fuente más fiable disponible.
      2. Si no (ticker delistado), se busca en `HISTORICAL_DELISTED_SECTORS`
         (mapeo manual documentado arriba).
      3. Si tampoco aparece ahí, se devuelve "Unknown" — igual que el
         comportamiento anterior, pero ahora solo para tickers realmente
         no cubiertos por ninguna de las dos fuentes, en vez de para
         cualquier ticker delistado.

    Pure/testeable: no hace I/O, solo combina dos diccionarios ya
    cargados por el llamador.
    """
    if symbol in current_sector_map:
        return current_sector_map[symbol]
    return HISTORICAL_DELISTED_SECTORS.get(symbol, "Unknown")


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