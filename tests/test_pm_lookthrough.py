"""S16: AMC portfolio parser and look-through. The workbooks are SYNTHETIC (built here with
openpyxl in two different layouts); no real AMC file is asserted against."""
from datetime import date

import openpyxl
import pandas as pd
import pytest

from pflab.calc import valuation as val
from pflab.ledger.book import Ledger
from pflab.ledger.events import Event, EventLog
from pflab.pm import lookthrough as lt
from pflab.pm import store
from pflab.risk import exposure as ex

FUND, FUND2, FUND3 = "INF000000011", "INF000000029", "INF000000037"


def book(sheets) -> bytes:
    import io
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


LAYOUT_A = [   # percent values, title with a date, subtotals, cash line
    ["Synthetic Flexi Cap Fund"], ["Monthly Portfolio Statement as on 31-Aug-2026"], [],
    ["Name of the Instrument", "ISIN", "Industry / Rating", "Quantity", "Market/Fair Value (Rs. in Lakhs)", "% to NAV"],
    ["Equity & Equity related"],
    ["Bank A Ltd", "INE111A01011", "Banks", 1000, 500.0, 40.0],
    ["Tech B Ltd", "INE222B01012", "IT - Software", 500, 300.0, 25.0],
    ["Bank A Ltd (second lot)", "INE111A01011", "Banks", 100, 50.0, 5.0],
    ["Sub Total", None, None, None, 850.0, 70.0],
    ["Debt Instruments"],
    ["Corp C 8.5% NCD 2030", "INE333C07013", "CRISIL AAA", 10, 100.0, 10.0],
    ["GOI 7.1% 2034", "IN0020230101", "Sovereign", 10, 100.0, 9.0],
    ["Sub Total", None, None, None, 200.0, 19.0],
    ["TREPS / Reverse Repo", None, None, None, 60.0, 8.0],
    ["Net Current Assets", None, None, None, 30.0, 3.0],
    ["Grand Total", None, None, None, 1000.0, 100.0],
]

LAYOUT_B = [   # fractions, different column order and names, no title date
    ["Scheme: Synthetic Index Fund"],
    ["Security", "ISIN Code", "Percentage of Net Assets", "Sector"],
    ["Bank A Ltd", "INE111A01011", 0.6, "Financial Services"],
    ["Tech B Ltd", "INE222B01012", 0.38, "Information Technology"],
    ["Cash", None, 0.02, None],
]


def test_parse_layout_a_percent_subtotals_cash_and_duplicates():
    pf = lt.parse_workbook(book({"Flexi": LAYOUT_A}))["Flexi"]
    assert pf.ok and pf.as_of == date(2026, 8, 31) and pf.total_pct == pytest.approx(100.0)
    h = pf.holdings.set_index("isin", drop=False)
    assert h.loc["INE111A01011", "pct"] == pytest.approx(45.0)                 # two lines added together
    assert h.loc["INE111A01011", "industry"] == "Banks" and h.loc["INE111A01011", "kind"] == "equity"
    assert h.loc["INE333C07013", "kind"] == "debt" and h.loc["IN0020230101", "kind"] == "govt"
    cash = pf.holdings[pf.holdings["isin"].isna()]
    assert sorted(cash["name"]) == ["Net Current Assets", "TREPS / Reverse Repo"] and cash["pct"].sum() == pytest.approx(11.0)
    assert "Sub Total" not in set(pf.holdings["name"]) and "Grand Total" not in set(pf.holdings["name"])


def test_parse_layout_b_fractions_become_percent():
    pf = lt.parse_workbook(book({"Index": LAYOUT_B}))["Index"]
    assert pf.ok and pf.as_of is None and pf.total_pct == pytest.approx(100.0)
    assert pf.holdings.set_index("isin").loc["INE111A01011", "pct"] == pytest.approx(60.0)
    assert pf.holdings.set_index("isin").loc["INE222B01012", "industry"] == "Information Technology"


def test_workbook_with_several_sheets_skips_cover_pages():
    out = lt.parse_workbook(book({"Cover": [["AMC Name"], ["Disclaimer"]], "Flexi": LAYOUT_A, "Index": LAYOUT_B}))
    assert set(out) == {"Flexi", "Index"}
    with pytest.raises(lt.PortfolioError, match="no sheet"):
        lt.parse_workbook(book({"Cover": [["nothing here"]]}))


def test_weights_not_summing_to_100_are_refused():
    short = LAYOUT_A[:6]                                                         # only the first equity line: 40%
    pf = lt.parse_workbook(book({"S": short}))["S"]
    assert not pf.ok and "weights sum to 40.00%" in pf.issues[0]
    con_err = None
    try:
        lt.save(None, FUND, pf, date(2026, 8, 31), "sha")
    except lt.PortfolioError as e:
        con_err = e
    assert con_err is not None and "refused" in str(con_err)
    over = [LAYOUT_B[0], LAYOUT_B[1], ["Bank A Ltd", "INE111A01011", 0.7, "x"], ["Tech B", "INE222B01012", 0.5, "y"]]
    assert not lt.parse_workbook(book({"S": over}))["S"].ok                       # 120%


def test_sheet_without_a_percent_column_raises():
    with pytest.raises(lt.PortfolioError):
        lt.parse_sheet([["Security", "ISIN"], ["Bank A", "INE111A01011"]])


def test_kind_of():
    assert lt.kind_of("INE999G01012") == "equity" and lt.kind_of("INE002A07809") == "debt"
    assert lt.kind_of("IN0020230101") == "govt" and lt.kind_of("INF204K01XX1") == "fund_units"
    assert lt.kind_of(None, "Net Current Assets") == "cash" and lt.kind_of(None, "Misc") == "other"


# --- store, status, look-through rows ----------------------------------------------------------------------

@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    a = lt.parse_workbook(book({"Flexi": LAYOUT_A}))["Flexi"]
    b = lt.parse_workbook(book({"Index": LAYOUT_B}))["Index"]
    lt.save(c, FUND, a, None, lt.file_sha(b"a"))                    # as-of from the file: 2026-08-31
    lt.save(c, FUND2, b, date(2026, 6, 30), lt.file_sha(b"b"))      # no date in file: caller supplies
    return c


def test_lookthrough_rows_and_status(con):
    rows, st = lt.lookthrough(con, [FUND, FUND2, FUND3], date(2026, 9, 20), sector_of={"INE222B01012": "IT"})
    s = st.set_index("fund_isin")
    assert s.loc[FUND, "status"] == "look-through" and s.loc[FUND, "as_of"] == date(2026, 8, 31)
    assert s.loc[FUND2, "status"] == "look-through (stale)"          # 2026-06-30 is 82 days old
    assert s.loc[FUND3, "status"] == "category-only" and "no portfolio file" in s.loc[FUND3, "reason"]
    f1 = rows[rows["fund_isin"] == FUND]
    assert f1["weight"].sum() == pytest.approx(1.0)
    sec = f1.groupby("sector")["weight"].sum()
    assert sec["Banks"] == pytest.approx(0.45) and sec["IT"] == pytest.approx(0.25)      # master sector wins over the file's
    assert sec["Debt (via fund)"] == pytest.approx(0.19) and sec["Cash and equivalents (via fund)"] == pytest.approx(0.11)
    assert f1.set_index("isin").loc["INE333C07013", "issuer"] == "INE333C07"
    assert f1.set_index("isin").loc["IN0020230101", "issuer"] == "GOI"
    assert rows[rows["fund_isin"] == FUND2].groupby("sector")["weight"].sum()["Financial Services"] == pytest.approx(0.6)


def test_asof_picks_the_latest_file_on_or_before(con):
    lt.save(con, FUND, lt.parse_workbook(book({"Index": LAYOUT_B}))["Index"], date(2026, 9, 30), "x")
    _, st = lt.lookthrough(con, [FUND], date(2026, 9, 5))
    assert st.iloc[0]["as_of"] == date(2026, 8, 31)
    _, st = lt.lookthrough(con, [FUND], date(2026, 10, 5))
    assert st.iloc[0]["as_of"] == date(2026, 9, 30)
    _, st = lt.lookthrough(con, [FUND], date(2026, 8, 1))
    assert st.iloc[0]["status"] == "category-only"


def test_save_replaces_the_same_fund_and_date(con):
    n = con.execute("SELECT count(*) FROM fund_holdings WHERE fund_isin=?", [FUND]).fetchone()[0]
    lt.save(con, FUND, lt.parse_workbook(book({"Flexi": LAYOUT_A}))["Flexi"], date(2026, 8, 31), "again")
    assert con.execute("SELECT count(*) FROM fund_holdings WHERE fund_isin=?", [FUND]).fetchone()[0] == n


def test_save_needs_a_date_when_the_file_has_none(tmp_path):
    c = store.connect(tmp_path / "x.duckdb")
    with pytest.raises(lt.PortfolioError, match="as-of"):
        lt.save(c, FUND2, lt.parse_workbook(book({"Index": LAYOUT_B}))["Index"], None, "s")


# --- feeds the risk exposures ----------------------------------------------------------------------------------------

def test_lookthrough_spreads_a_held_fund_in_exposures(con):
    inst = pd.DataFrame([dict(isin="INE111A01011", asset_class="equity", tax_class="EQUITY", sector="Financial Services",
                              issuer="INE111A01", name="Bank A", category=None),
                         dict(isin=FUND, asset_class="mutual_fund", tax_class="EQUITY", sector=None, issuer=None,
                              name="Flexi", category="Equity Scheme - Flexi Cap Fund")])
    log = EventLog([Event("deposit", "A", date(2026, 9, 1), amount=100_000.0),
                    Event("buy", "A", date(2026, 9, 2), isin="INE111A01011", qty=100, price=100.0),     # 10,000 direct
                    Event("buy", "A", date(2026, 9, 2), isin=FUND, qty=1000, price=10.0)])              # 10,000 in the fund
    v = val.value_ledger(Ledger.replay(log), lambda i, a: val.PriceInfo({"INE111A01011": 100.0, FUND: 10.0}[i], a, "close"),
                         date(2026, 9, 3))
    rows, _ = lt.lookthrough(con, [FUND], date(2026, 9, 3))
    e = ex.exposures(v, inst, rows)
    s = e["sector"].set_index("sector")["weight"]
    assert s["Banks"] == pytest.approx(0.45 * 10_000 / 100_000)
    assert s["Financial Services"] == pytest.approx(0.10)
    assert e["stock"].set_index("isin")["weight"]["INE111A01011"] == pytest.approx(0.10 + 0.045)
    iss = e["issuer"].set_index("issuer")["weight"]
    assert iss["INE111A01"] == pytest.approx(0.10 + 0.045) and iss["INE333C07"] == pytest.approx(0.01)   # NCD issuer is its own


def test_cli_lookthrough_loads_a_file(tmp_path, monkeypatch, capsys):
    from pflab import cli
    f = tmp_path / "synthetic_portfolio.xlsx"
    f.write_bytes(book({"Flexi": LAYOUT_A}))
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    assert cli.main(["pm", "lookthrough", "--fund", FUND, "--file", str(f)]) == 0
    assert "as of 2026-08-31" in capsys.readouterr().out
    g = tmp_path / "synthetic_two.xlsx"
    g.write_bytes(book({"Flexi": LAYOUT_A, "Index": LAYOUT_B}))
    assert cli.main(["pm", "lookthrough", "--fund", FUND2, "--file", str(g)]) == 2
    assert "pass --sheet" in capsys.readouterr().out
