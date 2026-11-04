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

# ETFs que sustituyen a un sectorial SPDR en el backtest antes de su
# lanzamiento (XLRE: octubre de 2015; XLC: junio de 2018). Sin ellos, F1
# nunca se cumple en esos sectores antes de esas fechas. La serie del
# sustituto se reescala para empalmar con la del ETF el primer día común
# (el RSC Mansfield no depende de la escala). Solo los usa el backtest:
# el escáner de producción mira el presente, donde todos los SPDR existen.
#   IYR (iShares U.S. Real Estate, 2000): inmobiliario/REIT, equivalente
#       directo de XLRE.
#   VOX (Vanguard Communication Services, 2004): antes de 2018 era sobre
#       todo telecos, mientras que XLC incluye Alphabet, Meta o Netflix;
#       es la mejor aproximación disponible, no un equivalente exacto.
SECTOR_ETF_PROXIES: dict[str, str] = {
    "XLRE": "IYR",
    "XLC": "VOX",
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
# Tickers que salieron del índice solo porque la empresa CAMBIÓ DE TICKER y
# que hoy siguen en él con el nuevo. En el universo histórico se sustituyen
# por el ticker actual (`sp500_historical.apply_ticker_aliases`): sus precios
# están bajo ese símbolo y así el backtest no puede tener dos posiciones en
# la misma empresa con nombres distintos. Solo renombres de la MISMA empresa;
# no fusiones de dos miembros (TYC/JCI fueron miembros a la vez y no se unen).
HISTORICAL_TICKER_ALIASES: dict[str, str] = {
    "AA":    "HWM",    # Alcoa Inc -> Arconic (ARNC, 2016) -> Howmet (2020); el AA actual es la Alcoa escindida
    "ARNC":  "HWM",    # Arconic Inc -> Howmet Aerospace (2020)
    "ACE":   "CB",     # ACE Ltd compró Chubb Corp (2016) y adoptó su nombre y ticker
    "CMCSK": "CMCSA",  # Comcast clase K convertida en clase A (2015)
    "KFT":   "MDLZ",   # Kraft Foods Inc -> Mondelez (2012), tras escindir Kraft Foods Group
    "PCS":   "TMUS",   # MetroPCS fue la entidad que pasó a ser T-Mobile US (2013)
    "SAI":   "LDOS",   # SAIC -> Leidos (2013)
}

# Delistados cuyo ticker usa hoy OTRA empresa (yfinance y Tiingo devuelven
# la nueva) pero que Tiingo conserva bajo un símbolo propio. Solo para el
# backtest (`backtest/data_cache.py`, `backtest/download_data.py`): sus
# precios se piden a Tiingo con ese símbolo y nunca a yfinance. El escáner
# de producción no lo usa (NE, por ejemplo, es hoy otra empresa cotizada).
# Fuente: supported_tickers.csv de Tiingo (bitácora 2026-11-04 (3)). Los
# reciclados sin símbolo propio (S, STI, CA, EMC, DOW antigua...) solo se
# podrían recuperar con el permaTicker de Tiingo, no disponible gratis.
TIINGO_PRICE_SYMBOLS: dict[str, str] = {
    "TE":   "TE1",     # TECO Energy (1993-2016); TE es hoy otra empresa
    "DTV":  "DTV1",    # DirecTV (2003-2015)
    "NE":   "NEBLQ",   # Noble Corp antigua (quebró en 2020); NE es la Noble actual
    "SHLD": "SHLDQ",   # Sears Holdings (quiebra 2018)
    "SLE":  "HSH",     # Sara Lee -> Hillshire Brands (2012)
    "SBNY": "SBNY",    # Signature Bank, ahora en OTC; yfinance da otra serie
    # permaTicker de Tiingo (identificador estable; sirve en la cuenta gratuita,
    # comprobado el 2026-11-04 con CA Inc). Sacados de /tiingo/fundamentals/meta
    # (`backtest/.cache/tiingo_fundamentals_meta.json`), solo cuando el nombre
    # identifica sin duda la empresa ANTIGUA (bitácora 2026-11-04 (5)).
    "APC":  "US000000000125",   # Anadarko Petroleum
    "APOL": "US000000000745",   # Apollo Education Group
    "AYE":  "US000000012420",   # Allegheny Energy
    "BMC":  "US000000008423",   # BMC Software
    "BRCM": "US000000000520",   # Broadcom Corp (antes de Avago)
    "BXLT": "US000000010496",   # Baxalta
    "CA":   "US000000000517",   # CA Inc
    "CBE":  "US000000008617",   # Cooper Industries
    "CEPH": "US000000012477",   # Cephalon
    "CPGX": "US000000011867",   # Columbia Pipeline Group
    "CVC":  "US000000000518",   # Cablevision Systems
    "DO":   "US000000000294",   # Diamond Offshore (la anterior a la quiebra de 2020)
    "EMC":  "US000000000529",   # EMC Corporation
    "FTR":  "US000000084388",   # Frontier Communications (antigua)
    "HAR":  "US000000000464",   # Harman International
    "LLTC": "US000000000901",   # Linear Technology
    "LXK":  "US000000009045",   # Lexmark International
    "MEE":  "US000000012809",   # Massey Energy
    "MI":   "US000000012821",   # Marshall & Ilsley
    "MOLX": "US000000009112",   # Molex
    "MON":  "US000000000296",   # Monsanto
    "NFX":  "US000000000459",   # Newfield Exploration
    "NOVL": "US000000012837",   # Novell
    "NYX":  "US000000009182",   # NYSE Euronext
    "PCP":  "US000000002279",   # Precision Castparts
    "POM":  "US000000002345",   # Pepco Holdings
    "S":    "US000000000188",   # Sprint Corp
    "SPLS": "US000000002661",   # Staples
    "STI":  "US000000000420",   # SunTrust Banks
    "TLAB": "US000000009465",   # Tellabs
    "TYC":  "US000000000418",   # Tyco International
    # Empresas antiguas de tickers que hoy usa otra empresa del índice (ver
    # HISTORICAL_TICKER_PERIOD_ALIASES): ticker propio con sufijo -AAAAMM.
    "SNDK-201605": "US000000000217",  # SanDisk Corp (comprada por WDC en 2016)
    "CEG-201203":  "US000000012475",  # Constellation Energy Group (fusión con Exelon, 2012)
    "HWM-201610":  "HWM",             # Alcoa Inc antes de separar Alcoa Corp (2016-11); Tiingo guarda su historia bajo HWM
}

# Tickers ACTUALES cuya empresa anterior con el mismo símbolo también estuvo
# en el índice. En las fechas anteriores al corte, el calendario de membresía
# usa un ticker propio (convención de Norgate: TICKER-AAAAMM, mes de salida)
# para no mezclar dos empresas en una serie; sus precios salen de
# TIINGO_PRICE_SYMBOLS. Dow Chemical (DOW) y Dell Inc (DELL) no están en el
# directorio gratuito de Tiingo: no recuperables.
HISTORICAL_TICKER_PERIOD_ALIASES: dict[str, list[tuple[str, str]]] = {
    "SNDK": [("2016-06-01", "SNDK-201605")],
    "CEG":  [("2012-04-01", "CEG-201203")],
    "HWM":  [("2016-11-01", "HWM-201610")],
}

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
    "DISCK": "Communication Services",  # Discovery clase C -> fusión -> WBD
    "PEAK": "Real Estate",              # Healthpeak Properties (símbolo antiguo)
    "FLIR": "Information Technology",   # FLIR Systems -> adquirida por Teledyne 2021
    "GPS":  "Consumer Discretionary",   # Gap Inc. -> excluida del índice
    "HFC":  "Energy",                   # HollyFrontier -> renombrada a HF Sinclair (DINO)
    "ADS":  "Financials",               # Alliance Data Systems -> renombrada/escindida -> Bread Financial (BFH)
    "RE":   "Financials",               # Everest Re -> renombrada a Everest Group (EG)
    "FBHS": "Industrials",              # Fortune Brands Home & Security -> renombrada a Fortune Brands Innovations (FBIN)

    # Consumer Discretionary (ampliación)
    "AAP":  "Consumer Discretionary",   # Advance Auto Parts -> excluida del índice 2023
    "BBWI": "Consumer Discretionary",   # Bath & Body Works -> excluida del índice
    "CZR":  "Consumer Discretionary",   # Caesars Entertainment -> excluida del índice
    "ETSY": "Consumer Discretionary",   # Etsy -> excluida del índice 2023
    "HBI":  "Consumer Discretionary",   # Hanesbrands -> excluida del índice
    "KMX":  "Consumer Discretionary",   # CarMax -> excluida del índice 2024
    "KSS":  "Consumer Discretionary",   # Kohl's -> excluida del índice
    "LKQ":  "Consumer Discretionary",   # LKQ Corporation -> excluida del índice 2025
    "MHK":  "Consumer Discretionary",   # Mohawk Industries -> excluida del índice
    "PENN": "Consumer Discretionary",   # PENN Entertainment -> excluida del índice
    "PVH":  "Consumer Discretionary",   # PVH Corp -> excluida del índice
    "UA":   "Consumer Discretionary",   # Under Armour clase C -> excluida del índice
    "UAA":  "Consumer Discretionary",   # Under Armour clase A -> excluida del índice
    "VFC":  "Consumer Discretionary",   # VF Corporation -> excluida del índice
    "WHR":  "Consumer Discretionary",   # Whirlpool -> excluida del índice 2024
    "BWA":  "Consumer Discretionary",   # BorgWarner (Auto Components) -> excluida del índice
    "NWL":  "Consumer Discretionary",   # Newell Brands (Household Durables) -> excluida del índice

    # Consumer Staples
    "CAG":  "Consumer Staples",         # Conagra Brands -> excluida del índice 2025
    "CPB":  "Consumer Staples",         # Campbell's -> excluida del índice
    "COTY": "Consumer Staples",         # Coty Inc. -> excluida del índice
    "LW":   "Consumer Staples",         # Lamb Weston -> excluida del índice 2025
    "K":    "Consumer Staples",         # Kellanova (antes Kellogg) -> pendiente adquisición Mars, excluida del índice

    # Energy (ampliación)
    "CTRA": "Energy",                   # Coterra Energy -> excluida del índice
    "FTI":  "Energy",                   # TechnipFMC -> excluida del índice
    "HES":  "Energy",                   # Hess Corporation -> adquirida por Chevron 2025
    "MRO":  "Energy",                   # Marathon Oil -> adquirida por ConocoPhillips 2024
    "NBL":  "Energy",                   # Noble Energy -> adquirida por Chevron 2020
    "NOV":  "Energy",                   # NOV Inc. -> excluida del índice

    # Financials (ampliación)
    "CMA":  "Financials",               # Comerica -> excluida del índice
    "DFS":  "Financials",               # Discover Financial Services -> adquirida por Capital One 2025
    "LNC":  "Financials",               # Lincoln National -> excluida del índice
    "UNM":  "Financials",               # Unum Group -> excluida del índice
    "ZION": "Financials",               # Zions Bancorporation -> excluida del índice
    "MKTX": "Financials",               # MarketAxess Holdings -> excluida del índice

    # Health Care (ampliación)
    "ABMD": "Health Care",              # Abiomed -> adquirida por Johnson & Johnson 2022
    "BIO":  "Health Care",              # Bio-Rad Laboratories -> excluida del índice
    "CTLT": "Health Care",              # Catalent -> adquirida por Novo Holdings 2024
    "HOLX": "Health Care",              # Hologic -> excluida del índice
    "ILMN": "Health Care",              # Illumina -> excluida del índice
    "MOH":  "Health Care",              # Molina Healthcare -> excluida del índice
    "OGN":  "Health Care",              # Organon & Co. -> spin-off de Merck, excluida del índice
    "PRGO": "Health Care",              # Perrigo -> excluida del índice
    "TFX":  "Health Care",              # Teleflex -> excluida del índice
    "XRAY": "Health Care",              # Dentsply Sirona -> excluida del índice

    # Industrials (ampliación)
    "AAL":  "Industrials",              # American Airlines Group -> excluida del índice
    "ALK":  "Industrials",              # Alaska Air Group -> excluida del índice
    "AMTM": "Industrials",              # Amentum Holdings -> spin-off de Jacobs Engineering
    "DXC":  "Information Technology",   # DXC Technology (IT Services) -> excluida del índice
    "FLS":  "Industrials",              # Flowserve -> excluida del índice
    "HRB":  "Consumer Discretionary",   # H&R Block (Diversified Consumer Services) -> excluida del índice
    "RHI":  "Industrials",              # Robert Half -> excluida del índice
    "VNT":  "Information Technology",   # Vontier (Electronic Equipment) -> spin-off de Fortive, excluida del índice

    # Information Technology (ampliación)
    "ANSS": "Information Technology",   # ANSYS -> adquirida por Synopsys 2024
    "EPAM": "Information Technology",   # EPAM Systems -> excluida del índice
    "ENPH": "Information Technology",   # Enphase Energy -> excluida del índice
    "FLT":  "Financials",               # FLEETCOR -> renombrada a Corpay (CPAY); Financials desde la reforma GICS de 2023
    "INFO": "Industrials",              # IHS Markit (Research & Consulting) -> fusión con S&P Global 2022
    "IPGP": "Information Technology",   # IPG Photonics -> excluida del índice
    "JNPR": "Information Technology",   # Juniper Networks -> adquirida por HPE 2025
    "MTCH": "Communication Services",   # Match Group (Interactive Media) -> excluida del índice
    "PAYC": "Industrials",             # Paycom Software (Human Resource Services desde la reforma GICS de 2023) -> excluida del índice 2026-03
    "QRVO": "Information Technology",   # Qorvo -> excluida del índice
    "SEDG": "Information Technology",   # SolarEdge Technologies -> excluida del índice

    # Materials
    "CE":   "Materials",                # Celanese -> excluida del índice
    "EMN":  "Materials",                # Eastman Chemical -> excluida del índice
    "FMC":  "Materials",                # FMC Corporation -> excluida del índice
    "SEE":  "Materials",                # Sealed Air -> excluida del índice

    # Communication Services (ampliación)
    "DISH": "Communication Services",   # DISH Network -> fusión con EchoStar 2023
    "IPG":  "Communication Services",   # Interpublic Group -> adquirida por Omnicom 2025
    "LUMN": "Communication Services",   # Lumen Technologies -> excluida del índice
    "WU":   "Information Technology",   # Western Union (Data Processing, GICS previo a 2023) -> excluida del índice

    # Real Estate (ampliación)
    "AIV":  "Real Estate",              # Apartment Investment and Management (Aimco) -> excluida del índice
    "DRE":  "Real Estate",              # Duke Realty -> adquirida por Prologis 2022
    "SLG":  "Real Estate",              # SL Green Realty -> excluida del índice
    "VNO":  "Real Estate",              # Vornado Realty Trust -> excluida del índice

    # ── Ampliación 2026-11-03 (universo histórico de 10 años, tarea D2) ──
    # Tickers que ya tienen precio (yfinance o Tiingo tras el arreglo de
    # fechas B1) pero no estaban mapeados. Criterio (unificado el 2026-11-04,
    # ver el bloque del tramo 2011-2016): sector con la estructura GICS
    # ACTUAL. Los medios que salieron antes de la reforma de sept-2018 (SNI,
    # TWX, TGNA) estaban entonces en Consumer Discretionary; se clasifican en
    # Communication Services y su ETF anterior a 2018 es el sustituto VOX.
    # Communication Services
    "EA":    "Communication Services",  # Electronic Arts -> privatizada 2026
    "LVLT":  "Communication Services",  # Level 3 (Telecom Services) -> adquirida por CenturyLink 2017
    "TFCF":  "Communication Services",  # 21st Century Fox clase A -> adquirida por Disney 2019
    "TFCFA": "Communication Services",  # 21st Century Fox -> adquirida por Disney 2019
    "TGNA":  "Communication Services",  # Tegna (Media; en su época, 2017, Consumer Discretionary) -> excluida del índice
    "SNDK-201605": "Information Technology",  # SanDisk Corp antigua -> comprada por Western Digital 2016
    "CEG-201203":  "Utilities",               # Constellation Energy Group antigua -> fusión con Exelon 2012
    "HWM-201610":  "Materials",               # Alcoa Inc (aluminio) antes de la separación de 2016
    "TRIP":  "Communication Services",  # TripAdvisor (Interactive Media) -> excluida del índice
    "VIAB":  "Communication Services",  # Viacom -> fusión con CBS 2019
    "WBD":   "Communication Services",  # Warner Bros. Discovery -> excluida del índice
    # Consumer Discretionary
    "AN":    "Consumer Discretionary",  # AutoNation -> excluida del índice
    "CPRI":  "Consumer Discretionary",  # Capri Holdings -> excluida del índice
    "FL":    "Consumer Discretionary",  # Foot Locker -> excluida del índice
    "GT":    "Consumer Discretionary",  # Goodyear -> excluida del índice
    "HOG":   "Consumer Discretionary",  # Harley-Davidson -> excluida del índice
    "JWN":   "Consumer Discretionary",  # Nordstrom -> excluida del índice
    "LEG":   "Consumer Discretionary",  # Leggett & Platt -> excluida del índice
    "M":     "Consumer Discretionary",  # Macy's -> excluida del índice
    "MAT":   "Consumer Discretionary",  # Mattel -> excluida del índice
    "POOL":  "Consumer Discretionary",  # Pool Corp -> excluida del índice
    "SIG":   "Consumer Discretionary",  # Signet Jewelers -> excluida del índice
    "SNI":   "Communication Services",  # Scripps Networks (Media; en su época Consumer Discretionary) -> adquirida por Discovery 2018
    "TWX":   "Communication Services",  # Time Warner (Media; en su época Consumer Discretionary) -> adquirida por AT&T 2018
    "URBN":  "Consumer Discretionary",  # Urban Outfitters -> excluida del índice
    "WYN":   "Consumer Discretionary",  # Wyndham Worldwide -> escindida 2018
    # Consumer Staples
    "DPS":   "Consumer Staples",        # Dr Pepper Snapple -> fusión con Keurig 2018
    "MJN":   "Consumer Staples",        # Mead Johnson -> adquirida por Reckitt 2017
    "RAI":   "Consumer Staples",        # Reynolds American -> adquirida por BAT 2017
    "TAP":   "Consumer Staples",        # Molson Coors -> excluida del índice
    "WBA":   "Consumer Staples",        # Walgreens Boots Alliance -> privatizada 2025
    "WFM":   "Consumer Staples",        # Whole Foods -> adquirida por Amazon 2017
    # Energy
    "ANDV":  "Energy",                  # Andeavor -> adquirida por Marathon Petroleum 2018
    "BHI":   "Energy",                  # Baker Hughes Inc -> fusión con GE Oil & Gas 2017
    "CHK":   "Energy",                  # Chesapeake Energy -> quiebra 2020
    "HP":    "Energy",                  # Helmerich & Payne -> excluida del índice
    "MUR":   "Energy",                  # Murphy Oil -> excluida del índice
    "RIG":   "Energy",                  # Transocean -> excluida del índice
    "RRC":   "Energy",                  # Range Resources -> excluida del índice
    "SE":    "Energy",                  # Spectra Energy -> fusión con Enbridge 2017
    "SWN":   "Energy",                  # Southwestern Energy -> excluida del índice
    # Financials
    "AMG":   "Financials",              # Affiliated Managers Group -> excluida del índice
    "BHF":   "Financials",              # Brighthouse Financial -> excluida del índice
    "JEF":   "Financials",              # Jefferies -> excluida del índice
    "LM":    "Financials",              # Legg Mason -> adquirida por Franklin Templeton 2020
    "NAVI":  "Financials",              # Navient -> excluida del índice
    "STI":   "Financials",              # SunTrust -> fusión con BB&T (Truist) 2019
    "XL":    "Financials",              # XL Group -> adquirida por AXA 2018
    # Health Care
    "AET":   "Health Care",             # Aetna -> adquirida por CVS 2018
    "AGN":   "Health Care",             # Allergan -> adquirida por AbbVie 2020
    "BCR":   "Health Care",             # C. R. Bard -> adquirida por Becton Dickinson 2017
    "ESRX":  "Health Care",             # Express Scripts -> adquirida por Cigna 2018
    "EVHC":  "Health Care",             # Envision Healthcare -> privatizada 2018
    "NKTR":  "Health Care",             # Nektar Therapeutics -> excluida del índice
    "PDCO":  "Health Care",             # Patterson Companies -> excluida del índice
    "STJ":   "Health Care",             # St. Jude Medical -> adquirida por Abbott 2017
    # Industrials
    "ARNC":  "Industrials",             # Arconic -> escindida 2020
    "AYI":   "Industrials",             # Acuity Brands -> excluida del índice
    "BLDR":  "Industrials",             # Builders FirstSource -> excluida del índice
    "COL":   "Industrials",             # Rockwell Collins -> adquirida por United Technologies 2018
    "DNB":   "Industrials",             # Dun & Bradstreet (Research & Consulting) -> excluida del índice en abril de 2017
    "FLR":   "Industrials",             # Fluor -> excluida del índice
    "LLL":   "Industrials",             # L3 Technologies -> fusión con Harris 2019
    "MBC":   "Industrials",             # MasterBrand (Building Products) -> excluida del índice
    "PBI":   "Industrials",             # Pitney Bowes -> excluida del índice
    "R":     "Industrials",             # Ryder System -> excluida del índice
    "SRCL":  "Industrials",             # Stericycle -> excluida del índice
    "CDAY":  "Industrials",             # Ceridian HCM -> renombrada a Dayforce (DAY) 2024 (Human Resource Services)
    "DAY":   "Industrials",             # Dayforce (antes Ceridian) -> excluida del índice
    # Information Technology
    "CA":    "Information Technology",  # CA Inc -> adquirida por Broadcom 2018
    "RHT":   "Information Technology",  # Red Hat -> adquirida por IBM 2019
    "TDC":   "Information Technology",  # Teradata -> excluida del índice
    "TSS":   "Information Technology",  # Total System Services -> adquirida por Global Payments 2019
    "TTD":   "Communication Services",  # The Trade Desk (Advertising desde la reforma GICS de 2023) -> excluida del índice 2026-09
    "YHOO":  "Information Technology",  # Yahoo -> Altaba 2017
    # Materials
    "BMS":   "Materials",               # Bemis -> adquirida por Amcor 2019
    "CTVA":  "Materials",               # Corteva -> excluida del índice
    "DWDP":  "Materials",               # DowDuPont -> escindida 2019
    "MON":   "Materials",               # Monsanto -> adquirida por Bayer 2018
    "OI":    "Materials",               # Owens-Illinois -> excluida del índice
    # Real Estate
    "AVB":   "Real Estate",             # AvalonBay Communities -> excluida del índice
    "GGP":   "Real Estate",             # GGP Inc. -> adquirida por Brookfield 2018
    "MAC":   "Real Estate",             # Macerich -> excluida del índice
    # Utilities
    "SCG":   "Utilities",               # SCANA -> adquirida por Dominion 2019
    # ── Ampliación 2026-11-04 (tramo 2011-2016 de la Fase 4b) ──
    # Salieron del índice entre 2011 y 2016 (y SOLS, 2025). Criterio: sector
    # con la ESTRUCTURA GICS ACTUAL (REIT → Real Estate, medios → Communication
    # Services), coherente con los constituyentes actuales, que usan su sector
    # de hoy en todo el histórico. Fuente: revisiones históricas de "List of
    # S&P 500 companies" (Wikipedia). "(media)" = confianza media.
    "AA":    "Materials",                # Alcoa Inc -> renombrada a ARNC (Arconic) al escindir la nueva Alcoa Corp; Arconic Inc se renombro HWM (Howmet Aerospace) en 2020 (media)
    "ACE":   "Financials",               # ACE Limited -> renombrada a CB (ACE compro Chubb Corp y adopto el nombre Chubb Ltd y el ticker CB)
    "ADT":   "Industrials",              # ADT Corp -> adquirida por Apollo Global Management (media)
    "AKS":   "Materials",                # AK Steel Holding -> degradada (cap. bursatil)
    "ALTR":  "Information Technology",   # Altera -> adquirida por Intel (INTC)
    "ANF":   "Consumer Discretionary",   # Abercrombie & Fitch -> degradada (cap. bursatil)
    "ANR":   "Energy",                   # Alpha Natural Resources -> degradada (cap. bursatil)
    "APOL":  "Consumer Discretionary",   # Apollo Group -> degradada (cap. bursatil)
    "ARG":   "Materials",                # Airgas -> adquirida por Air Liquide
    "ATI":   "Materials",                # Allegheny Technologies -> degradada (cap. bursatil)
    "AVP":   "Consumer Staples",         # Avon Products -> degradada (cap. bursatil)
    "AYE":   "Utilities",                # Allegheny Energy -> adquirida por FirstEnergy (FE)
    "BBBY":  "Consumer Discretionary",   # Bed Bath & Beyond -> degradada (cap. bursatil)
    "BEAM":  "Consumer Staples",         # Beam Inc (antes Fortune Brands) -> adquirida por Suntory
    "BIG":   "Consumer Discretionary",   # Big Lots -> degradada (cap. bursatil) (media)
    "BMC":   "Information Technology",   # BMC Software -> adquirida por Bain Capital/Golden Gate (capital riesgo)
    "BRCM":  "Information Technology",   # Broadcom Corp -> adquirida por Avago (AVGO, renombrada Broadcom)
    "BTU":   "Energy",                   # Peabody Energy -> degradada (cap. bursatil)
    "BXLT":  "Health Care",              # Baxalta -> adquirida por Shire
    "CAM":   "Energy",                   # Cameron International -> adquirida por Schlumberger (SLB)
    "CBE":   "Industrials",              # Cooper Industries -> adquirida por Eaton (ETN)
    "CCE":   "Consumer Staples",         # Coca-Cola Enterprises -> fusion con embotelladoras europeas -> Coca-Cola European Partners (CCEP, fuera del S&P 500)
    "CEPH":  "Health Care",              # Cephalon -> adquirida por Teva
    "CFN":   "Health Care",              # CareFusion -> adquirida por Becton Dickinson (BDX)
    "CLF":   "Materials",                # Cliffs Natural Resources -> degradada (cap. bursatil)
    "CMCSK": "Communication Services",   # Comcast Class K (acciones especiales sin voto) -> renombrada a CMCSA (clase K reclasificada en clase A)
    "CNX":   "Energy",                   # CONSOL Energy (luego CNX Resources) -> degradada (cap. bursatil)
    "COV":   "Health Care",              # Covidien -> adquirida por Medtronic (MDT)
    "CPGX":  "Energy",                   # Columbia Pipeline Group -> adquirida por TransCanada (TRP)
    "CPWR":  "Information Technology",   # Compuware -> degradada (cap. bursatil)
    "CSC":   "Information Technology",   # Computer Sciences Corp -> degradada tras escindir CSRA (CSC se fusiono en 2017 con HPE Enterprise Services -> DXC)
    "CSRA":  "Information Technology",   # CSRA Inc -> adquirida por General Dynamics (GD)
    "CVC":   "Communication Services",   # Cablevision Systems -> adquirida por Altice
    "CVH":   "Health Care",              # Coventry Health Care -> adquirida por Aetna (AET)
    "DF":    "Consumer Staples",         # Dean Foods -> degradada (cap. tras escindir WhiteWave)
    "DNR":   "Energy",                   # Denbury Resources -> degradada (cap. bursatil)
    "DO":    "Energy",                   # Diamond Offshore Drilling -> degradada (cap. bursatil)
    "DTV":   "Communication Services",   # DirecTV -> adquirida por AT&T (T)
    "DV":    "Consumer Discretionary",   # DeVry Inc -> degradada (cap. bursatil)
    "EMC":   "Information Technology",   # EMC Corp -> adquirida por Dell
    "ENDP":  "Health Care",              # Endo International -> degradada (cap. bursatil)
    "EP":    "Energy",                   # El Paso Corp -> adquirida por Kinder Morgan (KMI)
    "ESV":   "Energy",                   # Ensco plc -> degradada (cap. bursatil)
    "FDO":   "Consumer Staples",         # Family Dollar Stores -> adquirida por Dollar Tree (DLTR) (media)
    "FHN":   "Financials",               # First Horizon National -> degradada (cap. bursatil)
    "FII":   "Financials",               # Federated Investors -> degradada (cap. bursatil)
    "FOSL":  "Consumer Discretionary",   # Fossil Group -> degradada (cap. bursatil)
    "FRX":   "Health Care",              # Forest Laboratories -> adquirida por Actavis
    "FTR":   "Communication Services",   # Frontier Communications -> degradada (cap. bursatil)
    "GAS":   "Utilities",                # AGL Resources -> adquirida por Southern Co (SO)
    "GENZ":  "Health Care",              # Genzyme -> adquirida por Sanofi
    "GHC":   "Consumer Discretionary",   # Graham Holdings (antes Washington Post Co) -> degradada (cap. bursatil) (media)
    "GMCR":  "Consumer Staples",         # Keurig Green Mountain -> adquirida por JAB Holding
    "GME":   "Consumer Discretionary",   # GameStop -> degradada (cap. bursatil)
    "GNW":   "Financials",               # Genworth Financial -> degradada (cap. bursatil)
    "GR":    "Industrials",              # Goodrich Corp -> adquirida por United Technologies (UTX)
    "HAR":   "Consumer Discretionary",   # Harman International -> adquirida por Samsung
    "HCBK":  "Financials",               # Hudson City Bancorp -> adquirida por M&T Bank (MTB)
    "HNZ":   "Consumer Staples",         # H.J. Heinz Co -> adquirida por Berkshire Hathaway y 3G Capital
    "HOT":   "Consumer Discretionary",   # Starwood Hotels & Resorts -> adquirida por Marriott (MAR)
    "HSP":   "Health Care",              # Hospira -> adquirida por Pfizer (PFE)
    "IGT":   "Consumer Discretionary",   # International Game Technology -> degradada (cap. bursatil); adquirida por GTECH en 2015
    "ITT":   "Industrials",              # ITT Corp -> degradada tras escision en Xylem y Exelis (ITT pasa al MidCap 400)
    "JCP":   "Consumer Discretionary",   # J.C. Penney -> degradada (cap. bursatil)
    "JDSU":  "Information Technology",   # JDS Uniphase (luego Viavi) -> degradada (cap. bursatil)
    "JNS":   "Financials",               # Janus Capital Group -> degradada (cap. < 1.200 M$)
    "JOY":   "Industrials",              # Joy Global -> degradada (cap. bursatil); adquirida por Komatsu en 2017
    "KFT":   "Consumer Staples",         # Kraft Foods Inc -> renombrada a MDLZ (Mondelez International, tras escindir Kraft Foods Group)
    "KRFT":  "Consumer Staples",         # Kraft Foods Group -> fusion con H.J. Heinz Holding -> Kraft Heinz (KHC, entidad nueva, sigue en el indice)
    "LIFE":  "Health Care",              # Life Technologies -> adquirida por Thermo Fisher (TMO)
    "LLTC":  "Information Technology",   # Linear Technology -> adquirida por Analog Devices (ADI)
    "LO":    "Consumer Staples",         # Lorillard -> adquirida por Reynolds American (RAI)
    "LSI":   "Information Technology",   # LSI Corp -> adquirida por Avago (AVGO)
    "LXK":   "Information Technology",   # Lexmark International -> degradada (cap. bursatil)
    "MDP":   "Communication Services",   # Meredith Corp -> degradada (cap. bursatil) (media)
    "MEE":   "Energy",                   # Massey Energy -> adquirida por Alpha Natural Resources (ANR)
    "MFE":   "Information Technology",   # McAfee -> adquirida por Intel (INTC)
    "MHS":   "Health Care",              # Medco Health Solutions -> adquirida por Express Scripts (ESRX)
    "MI":    "Financials",               # Marshall & Ilsley -> adquirida por Bank of Montreal (BMO)
    "MMI":   "Information Technology",   # Motorola Mobility -> adquirida por Google (GOOG)
    "MNK":   "Health Care",              # Mallinckrodt -> degradada (cap. bursatil)
    "MOLX":  "Information Technology",   # Molex -> adquirida por Koch Industries
    "MWW":   "Industrials",              # Monster Worldwide -> degradada (cap. bursatil) (media)
    "NBR":   "Energy",                   # Nabors Industries -> degradada (cap. bursatil)
    "NE":    "Energy",                   # Noble Corp -> degradada (cap. bursatil)
    "NFX":   "Energy",                   # Newfield Exploration -> adquirida por Encana
    "NOVL":  "Information Technology",   # Novell -> adquirida por Attachmate (capital riesgo)
    "NSM":   "Information Technology",   # National Semiconductor -> adquirida por Texas Instruments (TXN)
    "NVLS":  "Information Technology",   # Novellus Systems -> adquirida por Lam Research (LRCX)
    "NYX":   "Financials",               # NYSE Euronext -> adquirida por IntercontinentalExchange (ICE)
    "PCL":   "Real Estate",              # Plum Creek Timber -> adquirida por Weyerhaeuser (WY)
    "PCP":   "Industrials",              # Precision Castparts -> adquirida por Berkshire Hathaway
    "PCS":   "Communication Services",   # MetroPCS Communications -> fusion inversa con T-Mobile USA: la entidad MetroPCS se renombro T-Mobile US (TMUS); excluida por free float; TMUS reingreso en 2019
    "PETM":  "Consumer Discretionary",   # PetSmart -> adquirida por BC Partners (capital riesgo)
    "PGN":   "Utilities",                # Progress Energy -> adquirida por Duke Energy (DUK)
    "PLL":   "Industrials",              # Pall Corp -> adquirida por Danaher (DHR)
    "POM":   "Utilities",                # Pepco Holdings -> adquirida por Exelon (EXC)
    "QEP":   "Energy",                   # QEP Resources -> degradada (cap. bursatil)
    "RDC":   "Energy",                   # Rowan Companies -> degradada (cap. bursatil)
    "RRD":   "Industrials",              # R.R. Donnelley & Sons -> degradada (cap. bursatil)
    "RSH":   "Consumer Discretionary",   # RadioShack -> degradada (cap. bursatil)
    "S":     "Communication Services",   # Sprint Nextel -> excluida: SoftBank compra ~78% y el free float cae bajo 50% (Sprint se fusiono con T-Mobile en 2020)
    "SAI":   "Industrials",              # SAIC (Science Applications International Corp) -> degradada (cap. bursatil); en sept-2013 escindio la nueva SAIC y la entidad se renombro Leidos (LDOS), que reingreso al indice en 2019 (media)
    "SHLD":  "Consumer Discretionary",   # Sears Holdings -> degradada (free float insuficiente)
    "SIAL":  "Materials",                # Sigma-Aldrich -> adquirida por Merck KGaA
    "SLE":   "Consumer Staples",         # Sara Lee Corp -> degradada tras escision (Sara Lee renombrada Hillshire Brands, HSH, fuera del indice; adquirida por Tyson en 2014)
    "SLM":   "Financials",               # SLM Corp (Sallie Mae) -> degradada tras escindir Navient (NAVI entra en su lugar)
    "SOLS":  "Materials",                # Solstice Advanced Materials -> degradada al SmallCap 600 (escindida de Honeywell; en el indice solo oct-dic 2025) (media)
    "SPLS":  "Consumer Discretionary",   # Staples Inc -> adquirida por Sycamore Partners
    "SUN":   "Energy",                   # Sunoco Inc -> adquirida por Energy Transfer Partners (ETP)
    "SVU":   "Consumer Staples",         # Supervalu -> degradada (cap. bursatil)
    "SWY":   "Consumer Staples",         # Safeway -> adquirida por Cerberus/Albertsons (capital riesgo)
    "TE":    "Utilities",                # TECO Energy -> adquirida por Emera
    "TEG":   "Utilities",                # Integrys Energy Group -> adquirida por Wisconsin Energy (WEC)
    "THC":   "Health Care",              # Tenet Healthcare -> degradada (cap. bursatil)
    "TIE":   "Materials",                # Titanium Metals -> adquirida por Precision Castparts (PCP)
    "TLAB":  "Information Technology",   # Tellabs -> degradada (cap. bursatil)
    "TWC":   "Communication Services",   # Time Warner Cable -> adquirida por Charter (CHTR)
    "TYC":   "Industrials",              # Tyco International -> fusion inversa con Johnson Controls: la entidad Tyco se renombro Johnson Controls International plc (JCI)
    "WFR":   "Information Technology",   # MEMC Electronic Materials (luego SunEdison) -> degradada (cap. bursatil)
    "WIN":   "Communication Services",   # Windstream Holdings -> degradada (cap. bursatil)
    "WPX":   "Energy",                   # WPX Energy -> degradada (cap. bursatil)
    "X":     "Materials",                # United States Steel -> degradada (cap. bursatil)
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