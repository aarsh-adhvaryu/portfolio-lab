from datetime import date

import pytest

from pflab.data import fpi_flows as F

# Structure copied from NSDL's real answer for 31-Mar-2012 (rowspans,
# parenthesised negatives, conversion rate on the first row of each date).
PAGE = """<table><tr><th colspan='8'>Daily Trends in FPI Investments up to 31-Mar-2012</th></tr>
<tr><th>Reporting <br/>Date</th><th>Debt/Equity</th><th>Investment Route</th>
<th>Gross Purchases(Rs Crore)</th><th>Gross Sales(Rs Crore)</th><th>Net Investment (Rs Crore)</th>
<th>Net Investment US($) million</th><th>Conversion <br/>(1 USD TO INR)*</th></tr>
<tr><td rowspan='7'>01-Mar-2012</td><td rowspan='3'>Equity</td><td>Stock Exchange</td>
<td>3678.60</td><td>3026.90</td><td>651.70</td><td>133.15</td><td rowspan='7'> Rs.48.9408</td></tr>
<tr><td>Primary market &amp; others</td><td>0.70</td><td>1.90</td><td>(1.20)</td><td>(0.25)</td></tr>
<tr><td>Sub-total</td><td>3679.30</td><td>3028.80</td><td>650.50</td><td>132.91</td></tr>
<tr><td rowspan='4'>Debt-VRR&nbsp;</td><td>Stock Exchange</td><td>189.90</td><td>101.70</td><td>88.20</td><td>18.03</td></tr>
<tr><td>Primary market & others</td><td>955.20</td><td>4.80</td><td>950.40</td><td>194.19</td></tr>
<tr><td>Sub-total</td><td>1,145.10</td><td>106.50</td><td>1038.60</td><td>212.22</td></tr>
<tr class='total'><td>Total</td><td>4824.40</td><td>3135.30</td><td>1689.10</td><td>345.13</td></tr>
<tr><td rowspan='2'>02-Mar-2012</td><td rowspan='1'>Equity</td><td>Sub-total</td>
<td>2436.90</td><td>2160.90</td><td>(21.60)</td><td>(4.39)</td><td rowspan='2'> Rs.49.1545</td></tr>
<tr class='total'><td>Total</td><td>2436.90</td><td>2160.90</td><td>(21.60)</td><td>(4.39)</td></tr>
</table>
<table><tr><th>Daily Trends in FPI Derivative Trades on 30-Mar-2012</th></tr>
<tr><td>01-Mar-2012</td><td>Index Futures</td><td>62891.00</td><td>1709.21</td></tr></table>"""


def test_parse_reads_cash_table_only():
    df = F.parse(PAGE)
    assert len(df) == 9
    assert set(df["report_date"]) == {date(2012, 3, 1), date(2012, 3, 2)}
    assert list(df["asset"].unique()) == ["Equity", "Debt-VRR", "Total"]
    row = df[(df["asset"] == "Equity") & (df["route"] == "Primary market & others")].iloc[0]
    assert (row["net_cr"], row["net_usd_mn"], row["usd_inr"]) == (-1.2, -0.25, 48.9408)
    assert df[(df["asset"] == "Debt-VRR") & (df["route"] == "Sub-total")]["gross_purchase_cr"].iloc[0] == 1145.10
    day2 = df[df["report_date"] == date(2012, 3, 2)]
    assert day2["usd_inr"].eq(49.1545).all() and day2["net_cr"].eq(-21.6).all()


def test_parse_refuses_page_without_table():
    with pytest.raises(ValueError, match="no 'Daily Trends"):
        F.parse("<html>maintenance</html>")


def test_parse_refuses_short_row():
    bad = PAGE.replace("<td>(1.20)</td><td>(0.25)</td>", "")
    with pytest.raises(ValueError, match="expected 4 numbers"):
        F.parse(bad)
