"""
Formato de la tabla de cambios del S&P 500 en Wikipedia (sin red: se mockea
`requests.get`). Desde 2026 vive en "Historical components of the S&P 500"
y trae una 7ª columna "Refs".
"""

from __future__ import annotations

from unittest.mock import Mock, patch

from backtest import sp500_historical as sh

_HTML = """
<html><body><table id="changes"><tbody>
<tr><th>Effective Date</th><th colspan="2">Added</th><th colspan="2">Removed</th><th>Reason</th><th>Refs</th></tr>
<tr><th>Ticker</th><th>Security</th><th>Ticker</th><th>Security</th></tr>
<tr><td>October 6, 2026</td><td>TWLO</td><td>Twilio</td><td>WBD</td><td>Warner Bros. Discovery</td><td>Acquired</td><td>[2]</td></tr>
<tr><td>March 23, 2015</td><td>SLG</td><td>SL Green Realty</td><td>NBR</td><td>Nabors Industries</td><td>Market cap</td></tr>
<tr><td>roto</td><td>X</td></tr>
</tbody></table></body></html>
"""


def test_acepta_filas_de_6_y_7_columnas_y_usa_la_nueva_url():
    resp = Mock(status_code=200, text=_HTML)
    resp.raise_for_status = Mock()
    with patch.object(sh.requests, "get", return_value=resp) as mock_get:
        df = sh._fetch_changes_table_raw()
    assert mock_get.call_args.args[0] == sh.SP500_CHANGES_URL
    assert list(df["Added_Ticker"]) == ["TWLO", "SLG"]
    assert list(df["Removed_Ticker"]) == ["WBD", "NBR"]
    assert list(df["Reason"]) == ["Acquired", "Market cap"]
