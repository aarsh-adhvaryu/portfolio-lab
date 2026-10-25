"""BSE integrated filings (inline XBRL) and the template's bottom-line fix. SYNTHETIC documents and rows."""
from datetime import date, datetime

import pandas as pd

from pflab.fundamentals import integrated, pit
from pflab.plan import guards as gd
from pflab.pm import store

DOC = """<html xmlns='http://www.w3.org/1999/xhtml' xmlns:ix='http://www.xbrl.org/2013/inlineXBRL'
 xmlns:xbrli='http://www.xbrl.org/2003/instance' xmlns:xbrldi='http://xbrl.org/2006/xbrldi'
 xmlns:in-capmkt='http://www.sebi.gov.in/xbrl/2026-01-31/in-capmkt'><body><ix:header><ix:resources>
<xbrli:context id='OneD'><xbrli:entity><xbrli:identifier scheme='s'>999</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id='Prev'><xbrli:entity><xbrli:identifier scheme='s'>999</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:startDate>2025-04-01</xbrli:startDate><xbrli:endDate>2025-06-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id='Year'><xbrli:entity><xbrli:identifier scheme='s'>999</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:startDate>2025-04-01</xbrli:startDate><xbrli:endDate>2026-03-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id='Seg'><xbrli:entity><xbrli:identifier scheme='s'>999</xbrli:identifier>
 <xbrli:segment><xbrldi:explicitMember dimension='d'>x</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
 <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
</ix:resources></ix:header>
<ix:nonFraction name='in-capmkt:RevenueFromOperations' contextRef='Seg' scale='6' format='ixt3:numdotdecimalin'>9.00</ix:nonFraction>
<ix:nonFraction name='in-capmkt:RevenueFromOperations' contextRef='OneD' scale='6' format='ixt3:numdotdecimalin'>1,23,456.78</ix:nonFraction>
<ix:nonFraction name='in-capmkt:RevenueFromOperations' contextRef='Prev' scale='6'>50.00</ix:nonFraction>
<ix:nonFraction name='in-capmkt:FinanceCosts' contextRef='OneD' scale='6'>4,321.09</ix:nonFraction>
<ix:nonFraction name='in-capmkt:ProfitBeforeTax' contextRef='OneD' scale='6'>100.00</ix:nonFraction>
<ix:nonFraction name='in-capmkt:TaxExpense' contextRef='OneD' scale='6' sign='-'>19.26</ix:nonFraction>
<ix:nonFraction name='in-capmkt:ProfitLossForPeriod' contextRef='OneD' scale='5'>1,193.00</ix:nonFraction>
<ix:nonFraction name='in-capmkt:ProfitLossForPeriod' contextRef='Year' scale='6'>400.00</ix:nonFraction>
<ix:nonFraction name='in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations' contextRef='OneD'>12.34</ix:nonFraction>
<ix:nonNumeric name='in-capmkt:WhetherResultsAreAuditedOrUnaudited' contextRef='OneD'>Unaudited</ix:nonNumeric>
</body></html>"""


def test_parse_takes_the_quarter_without_dimensions_in_million_rupees():
    row = integrated.to_row(integrated.parse(DOC.encode()), "999")
    assert row["quarter_end"] == date(2026, 6, 30) and row["audited"] is False
    assert row["revenue"] == 123456.78                       # Indian grouping, not the segment or year-ago fact
    assert row["finance_costs"] == -4321.09                  # signed as BSE's template files it
    assert row["tax"] == 19.26                               # a tax credit (sign='-') stays a credit
    assert row["net_profit"] == 119.3                        # scale 5 -> Rs million; the yearly fact is ignored
    assert row["eps_basic"] == 12.34 and row["other_income"] is None


def test_filings_keep_standalone_quarters_at_their_first_filing_time():
    listing = {"Table": [
        {"Qtrid": 130.0, "Quarter_Name": "Consolidated-Jun-Qtr-2026", "filing_date_time": "2026-08-01T18:00:10", "xbrlurl": "/c"},
        {"Qtrid": 130.0, "Quarter_Name": "Standalone-Jun-Qtr-2026", "filing_date_time": "2026-08-01T17:58:57", "xbrlurl": "/a"},
        {"Qtrid": 130.0, "Quarter_Name": "Standalone-Jun-Qtr-2026", "filing_date_time": "2026-08-20T10:00:00", "xbrlurl": "/rev"},
        {"Qtrid": 129.5, "Quarter_Name": "Standalone-Mar-Yearly-2026", "filing_date_time": "2026-05-14T19:58:54", "xbrlurl": "/y"},
    ]}
    f = integrated.filings(listing)
    assert list(f["quarter_end"]) == [date(2026, 6, 30)] and f["url"].iloc[0].endswith("/a")
    assert f["filed_at"].iloc[0] == datetime(2026, 8, 1, 17, 58, 57)


def test_template_bottom_line_is_the_net_profit_line():
    lines = [("Type", "Audited"), ("Date End", "31-Mar-26"), ("Net Sales/Revenue From Operations", "5000.0"),
             ("Profit (+)/ Loss (-) from Ordinary Activities before Tax", "400.0"),
             ("Net Profit (+)/ Loss (-) from Ordinary Activities after Tax", "400.0"), ("Net Profit", "900.0"),
             ("Basic EPS for continuing operation", "0.45")]
    row = pit.parse_quarter([{"fld_desc": d, "Value": v} for d, v in lines], "1", 129)
    assert row["net_profit"] == 900.0 and row["pbt"] == 400.0


def test_guards_fill_quarters_the_template_lacks_from_filings(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    asof = date(2026, 10, 15)

    def filed(scrip, ends):
        rows = [{"scrip_code": scrip, "quarter_end": e, "audited": False, **{f: None for f in pit.FIELDS},
                 "net_profit": 10.0, "usable_from": (pd.Timestamp(e) + pd.Timedelta(days=40)).date(),
                 "date_source": "bse_filing"} for e in ends]
        return pd.DataFrame(rows)

    q = gd.quarters(con, "77", asof, fetch=lambda s, ids: pd.DataFrame(columns=pit.COLUMNS), filed=filed)
    assert len(q) == 9 and set(q["date_source"]) == {"bse_filing"}     # Sep-2026 is not filed until Nov: left out
    assert q["usable_from"].max() <= asof


def _qs(n, start="2024-09-30", np_=10.0, **kw):
    ends = [(pd.Timestamp(start) + pd.offsets.QuarterEnd(k)).date() for k in range(n)]
    return pd.DataFrame([{"scrip_code": "9", "quarter_end": e, "audited": False, **{f: None for f in pit.FIELDS},
                          "net_profit": np_, "pbt": np_ * 1.3, "finance_costs": -1.0, **kw,
                          "usable_from": (pd.Timestamp(e) + pd.Timedelta(days=40)).date(), "date_source": "bse_filing"}
                         for e in ends])


def test_consolidated_only_with_eight_consecutive_quarters_not_behind_standalone():
    std = _qs(9)
    assert pit.choose(std, _qs(7, start="2025-03-31"))[1] == "standalone"           # seven: not yet
    assert pit.choose(std, _qs(8, start="2024-12-31"))[1] == "consolidated"
    assert pit.choose(std, _qs(8))[1] == "standalone"                               # its newest is behind standalone
    gap = _qs(9).drop(index=4)
    assert pit.choose(std, gap)[1] == "standalone"
    assert pit.choose(std.iloc[0:0], _qs(8))[1] == "consolidated"                   # files only consolidated


def test_migration_22_keeps_every_row_as_standalone(tmp_path):
    import duckdb

    from pflab.pm import store as st
    con = duckdb.connect(str(tmp_path / "old.duckdb"))
    st.migrate(con, [m for m in st.MIGRATIONS if m[0] < 22])
    con.execute("INSERT INTO quarterly_results (scrip_code, quarter_end, net_profit, usable_from, date_source, source, "
                "fetched_at) VALUES ('1', DATE '2026-03-31', 5.0, DATE '2026-05-10', 'x', 'y', now())")
    assert st.migrate(con, [m for m in st.MIGRATIONS if m[0] <= 22]) == [22]
    assert con.execute("SELECT basis, net_profit FROM quarterly_results").fetchall() == [("standalone", 5.0)]
    pit.save(con, _qs(1, start="2026-03-31").assign(scrip_code="1"), "bse_filing", basis="consolidated")
    assert len(pit.load(con, "1")) == 1 and len(pit.load(con, "1", "consolidated")) == 1


def test_guards_judge_a_group_on_consolidated_figures_once_eight_quarters_exist(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    asof = date(2026, 10, 15)
    std = _qs(9, np_=10.0)
    std.loc[5:, "net_profit"] = 2.0                                   # standalone collapses (business moved out)
    pit.save(con, std, "bse_live")
    stocks = [{"symbol": "GRP", "isin": "INE000G01011", "scrip": "9"}]
    snap = pd.DataFrame(columns=["isin", "verdict", "desc"])
    run = lambda: gd.check_all(con, asof, stocks, lambda s, q: pd.DataFrame(columns=pit.COLUMNS), snap,
                               lambda i, d: -0.1)[0]
    g = run()
    assert g.verdict == "fail" and "F2 profit collapsed:" in g.reasons[0]           # standalone, as before
    pit.save(con, _qs(8, start="2024-12-31", np_=50.0), "bse_filing", basis="consolidated")
    assert run().verdict == "ok"
    weak = _qs(8, start="2024-12-31", np_=50.0, finance_costs=-100.0)       # (65 + 100) / 100 = 1.65
    con.execute("DELETE FROM quarterly_results WHERE basis='consolidated'")
    pit.save(con, weak, "bse_filing", basis="consolidated")
    assert "F3 interest cover (consolidated)" in run().reasons[0]


def test_guards_top_up_consolidated_beside_standalone(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    asof = date(2026, 10, 15)
    seen = []
    filed_cons = lambda s, ends: (seen.append(len(ends)), _qs(9, start="2024-06-30").assign(scrip_code=s))[1]
    gd.quarters(con, "9", asof, fetch=lambda s, ids: pd.DataFrame(columns=pit.COLUMNS),
                filed=lambda s, ends: _qs(9, start="2024-06-30").assign(scrip_code=s), filed_cons=filed_cons)
    assert seen == [10] and len(pit.load(con, "9", "consolidated")) == 9
    gd.quarters(con, "9", asof, fetch=lambda s, ids: pd.DataFrame(columns=pit.COLUMNS), filed_cons=filed_cons)
    assert seen == [10]                                                              # both current: no call


def test_correct_rewrites_figures_but_never_the_dates(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    row = {"scrip_code": "5", "quarter_end": date(2026, 3, 31), "audited": True, **{f: None for f in pit.FIELDS},
           "net_profit": 400.0}
    pit.save(con, pit.date_quarters(pd.DataFrame([row], columns=pit.COLUMNS), first_seen=date(2026, 10, 15)), "bse_live")
    assert pit.correct(con, pd.DataFrame([{**row, "net_profit": 900.0}])) == 1
    d = pit.load(con, "5")
    assert d["net_profit"].iloc[0] == 900.0 and d["usable_from"].iloc[0] == date(2026, 10, 15)
