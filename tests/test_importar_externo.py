"""
Importador de deslistados desde el dataset externo (`backtest/importar_externo.py`):
solo filas de fuentes permitidas y con volumen, ajuste por adj_close y velas
semanales etiquetadas en viernes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import importar_externo as imp
from weinstein.config import HISTORICAL_DELISTED_SECTORS, HISTORICAL_TICKER_PERIOD_ALIASES


def _dataset(n_dias: int = 600) -> pd.DataFrame:
    fechas = pd.bdate_range("2010-01-04", periods=n_dias)
    close = np.linspace(10, 20, n_dias)
    base = pd.DataFrame({
        "date": fechas, "ticker": "OLD-201203", "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": 1000.0, "adj_close": close * 0.5, "dividends": 0.0, "stock_splits": 0.0,
        "source": "wiki",
    })
    crsp = base.iloc[:50].copy()
    crsp["source"], crsp["volume"], crsp["close"] = "crsp", np.nan, 999.0
    return pd.concat([base, crsp], ignore_index=True)


def test_serie_semanal_ajusta_y_agrega_por_semana():
    semanal, info = imp.serie_semanal(_dataset(), "OLD-201203")
    assert semanal is not None
    assert (semanal.index.dayofweek == 4).all()                     # etiqueta en viernes
    assert semanal["Close"].max() <= 10.0 + 1e-9                     # ajustado: adj_close = close / 2
    assert semanal["Volume"].iloc[1] == 5000.0                       # suma de 5 sesiones
    assert info["fuentes"] == {"wiki": 600}                          # filas de CRSP descartadas


def test_etiqueta_sin_historia_suficiente_no_se_importa():
    semanal, info = imp.serie_semanal(_dataset(n_dias=100), "OLD-201203")
    assert semanal is None
    assert info["velas"] < 70


def test_solo_fuentes_permitidas():
    d = _dataset()
    d["source"] = "crsp"
    semanal, info = imp.serie_semanal(d, "OLD-201203")
    assert semanal is None and info["filas_diarias"] == 0


def test_alias_por_fechas_tienen_sector():
    for lst in HISTORICAL_TICKER_PERIOD_ALIASES.values():
        for _corte, alias in lst:
            assert alias in HISTORICAL_DELISTED_SECTORS
