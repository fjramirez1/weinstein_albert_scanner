"""
Empalme de ETFs sectoriales con sus sustitutos anteriores a su lanzamiento
(`SECTOR_ETF_PROXIES`, `splice_sector_proxy`): XLRE antes de 2015 y XLC
antes de 2018.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.portfolio_backtest import splice_sector_proxy
from weinstein.config import SECTOR_ETF_PROXIES, SECTOR_TO_ETF


def _serie(inicio: str, valores: list[float]) -> pd.Series:
    return pd.Series(valores, index=pd.date_range(inicio, periods=len(valores), freq="W-FRI"), dtype=float)


def test_alarga_hacia_atras_reescalando_el_sustituto():
    proxy = _serie("2020-01-03", [10, 11, 12, 13, 14])
    etf = _serie("2020-01-24", [26, 28])          # empieza en la 4.ª semana del proxy
    out = splice_sector_proxy(etf, proxy)
    assert list(out.index) == list(proxy.index)
    assert out.iloc[:3].tolist() == pytest.approx([20, 22, 24])  # proxy x 2 (26 / 13)
    assert out.iloc[3:].tolist() == [26, 28]       # desde el empalme, el ETF real


def test_sin_dias_comunes_o_sin_alguna_serie():
    etf = _serie("2021-01-01", [1, 2])
    proxy = _serie("2010-01-01", [5, 6])
    assert splice_sector_proxy(etf, proxy) is etf
    assert splice_sector_proxy(etf, None) is etf
    assert splice_sector_proxy(None, proxy) is proxy
    assert splice_sector_proxy(None, None) is None


def test_los_sustitutos_cubren_etfs_del_mapa():
    assert set(SECTOR_ETF_PROXIES) <= set(SECTOR_TO_ETF.values())
    assert not set(SECTOR_ETF_PROXIES.values()) & set(SECTOR_TO_ETF.values())
