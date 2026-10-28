"""S65 Phase 7 item 10: the Quicko pack: gains by schedule, the Schedule 112A CSV in the department's layout (with the 31-Jan-2018
grandfathering), income, the US rows, and the reconciliation against a tax P&L export. Hand-worked numbers."""
import csv
import io
from datetime import date, datetime

import pandas as pd
import pytest

from pflab.agents import questions
from pflab.ledger.events import Event, EventLog, save as save_events
from pflab.pm import store
from pflab.tax import quicko as qk

OLD, NEW, ST = "INE111A01011", "INE222B01012", "INE333C01013"      # bought 2017 (BE), 2024 (AE, long term), 2025 (short term)
ACC = "ZER"
FMV = {OLD: 200.0}


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    for isin, sym in ((OLD, "OLDCO"), (NEW, "NEWCO"), (ST, "STCO")):
        c.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                     VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, 'synthetic', now())""", [isin, sym, f"{sym} Ltd. (India) & Co"])
    ev = [Event("deposit", ACC, date(2017, 1, 1), amount=1e8),
          Event("buy", ACC, date(2017, 6, 1), isin=OLD, qty=50, price=100.0),                  # cost 5,000; FMV 200 -> 10,000
          Event("buy", ACC, date(2024, 1, 5), isin=NEW, qty=10, price=500.0, fees={"x": 20.0}),   # cost 5,020
          Event("buy", ACC, date(2025, 5, 2), isin=ST, qty=100, price=50.0),                   # cost 5,000
          Event("sell", ACC, date(2025, 10, 1), isin=OLD, qty=50, price=300.0),                # proceeds 15,000
          Event("sell", ACC, date(2025, 9, 1), isin=NEW, qty=10, price=800.0, fees={"x": 30.0}),  # proceeds 7,970
          Event("sell", ACC, date(2026, 2, 10), isin=ST, qty=100, price=60.0, fees={"x": 10.0}),  # proceeds 5,990 (short term)
          Event("dividend", ACC, date(2025, 8, 20), isin=NEW, amount=500.0, fees={"tds": 50.0}),
          Event("interest", ACC, date(2025, 12, 31), amount=1200.0)]
    save_events(c, EventLog(ev))
    return c


def test_gains_split_by_schedule_with_the_2018_value_in_the_112a_rows(con):
    p = qk.build(con, 2026, fmv_2018=FMV.get)
    s = p["schedules"]
    assert s["ST_111A"]["lines"] == 1 and s["ST_111A"]["gain"] == pytest.approx(990.0)               # 5,990 - 5,000
    assert s["LT_112A"]["lines"] == 2 and s["LT_112A"]["gain"] == pytest.approx(5_000 + (7_970 - 5_020))   # grandfathered + ordinary
    be, ae = p["schedule_112a"]
    assert (be["acquired"], be["isin"], be["qty"], be["price"]) == ("BE", OLD, 50.0, 300.0)
    assert (be["full_value"], be["cost"], be["fmv_per_unit"], be["fmv_total"]) == (15_000, 5_000.0, 200.0, 10_000)
    assert (be["lower_of_11_and_6"], be["cost_without_indexation"], be["deductions"], be["balance"]) == (10_000, 10_000, 10_000, 5_000)
    assert be["name"] == "OLDCO Ltd India Co"                                                          # no special characters
    assert (ae["acquired"], ae["isin"], ae["name"], ae["qty"], ae["price"]) == ("AE", "INNOTREQUIRD", "CONSOLIDATED", "", "")
    assert (ae["full_value"], ae["cost"], ae["balance"]) == (7_970, 5_020.0, 2_950)
    assert sum(r["balance"] for r in p["schedule_112a"]) == round(s["LT_112A"]["gain"])               # the CSV adds up to the schedule


def test_the_csv_has_the_departments_headings_in_its_order_and_no_forbidden_characters(con):
    p = qk.build(con, 2026, fmv_2018=FMV.get)
    cols = qk.layout()["columns"]
    assert [c["no"] for c in cols] == ["1a", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14"]
    assert qk.layout()["meta"]["verification"] == "primary" and qk.layout()["meta"]["source_url"].startswith("https://static.incometax.gov.in/")
    rows = list(csv.reader(io.StringIO(p["schedule_112a_csv"])))
    assert rows[0][0] == "Share/Unit acquired" and rows[0][1] == "ISIN Code" and rows[0][-1] == "Balance (6-13)"
    assert len(rows) == 3 and all(len(r) == 14 for r in rows)
    assert rows[1][:3] == ["BE", OLD, "OLDCO Ltd India Co"] and rows[2][:3] == ["AE", "INNOTREQUIRD", "CONSOLIDATED"]
    assert rows[2][3] == "" and rows[2][4] == "" and rows[2][9] == ""                                  # AE: quantity, price, FMV left blank
    for r in rows[1:]:
        assert not any(ch in cell for cell in r for ch in ",/-_()&@\\'\";:") or r[0] == "BE" and "." in r[7]   # a decimal point is not special
    assert p["schedule_112a_csv"].count("\r\n") == 3


def test_a_holding_before_2018_without_its_value_is_not_guessed(con):
    with pytest.raises(RuntimeError, match="FMV for grandfathering"):
        qk.build(con, 2026, fmv_2018=lambda isin: None)


def test_income_and_the_us_rows(con):
    from pflab.ledger import foreign as lf
    con.execute("INSERT INTO fx_rates VALUES (?, 'USDINR', 88.0, 't')", [date(2025, 10, 31)])
    lf.add_remittance(con, date(2025, 11, 3), 1000.0, 88_000.0, 0.0, "bank", source="t")
    lf.register_instrument(con, "SPY", "US:SPY", "SPY ETF", etf=True)
    lf.add_trade(con, date(2025, 11, 5), "SPY", "US:SPY", "buy", 1.0, 600.0, 1.0, source="t")
    p = qk.build(con, 2026, fmv_2018=FMV.get)
    d = p["income"]["dividends"]
    assert d["gross"] == 500.0 and d["tds"] == 50.0 and d["rows"][0]["isin"] == NEW
    assert p["income"]["bank_interest"]["gross"] == 1200.0 and p["income"]["fd_interest"]["interest"] == 0.0
    f = p["foreign"]
    assert len(f["trades"]) == 1 and f["trades"][0]["symbol"] == "SPY" and f["remittances"][0]["usd"] == 1000.0
    assert f["schedule_fa_holdings_on"] == "2025-12-31" and f["schedule_fa_holdings"][0]["symbol"] == "SPY"
    assert "not on record" in f["us_tax_withheld"] and "not on record" in f["form_67"]


def test_the_files_are_written(con, tmp_path):
    p = qk.build(con, 2026, fmv_2018=FMV.get)
    paths = qk.write_pack(p, tmp_path / "out")
    assert {x.name for x in paths} == {"schedule_112A_FY2026.csv", "sales_FY2026.csv", "dividends_FY2026.csv", "summary_FY2026.txt"}
    text = (tmp_path / "out" / "summary_FY2026.txt").read_text(encoding="utf-8")
    assert "nothing is filed from this" in text and "LT_112A" in text


def export(rows, header=("Symbol", "ISIN", "Entry Date", "Exit Date", "Quantity", "Buy Value", "Sell Value", "Profit", "Brokerage")) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Tax P&L statement", "", ""])
    w.writerow([])
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode()


def test_reconcile_matches_what_the_ledger_has_and_flags_what_it_does_not(con):
    p = qk.build(con, 2026, fmv_2018=FMV.get)
    ok = export([["OLDCO", OLD, "2017-06-01", "2025-10-01", 50, 5000, 15000, 5000, 0],
                 ["NEWCO", NEW, "2024-01-05", "2025-09-01", 10, 5000, 8000, 3000, 50],        # profit before 50 of charges: 2,950 after
                 ["STCO", ST, "2025-05-02", "2026-02-10", 100, 5000, 6000, 1000, 10],
                 ["OLDER", OLD, "2020-01-01", "2024-01-01", 1, 1, 2, 1, 0]])                 # an earlier year: left out
    r = qk.reconcile(p, ok, "taxpnl.csv")
    assert r["differences"] == [] and r["matched"] == 3
    bad = export([["OLDCO", OLD, "2017-06-01", "2025-10-01", 50, 5000, 15000, 4000, 0],      # Rs 1,000 off
                  ["NEWCO", NEW, "2024-01-05", "2025-09-01", 10, 5000, 8000, 3000, 50],
                  ["STCO", ST, "2025-05-02", "2026-02-10", 100, 5000, 6000, 1000, 10],
                  ["GHOST", "INE999Z01019", "2025-06-01", "2025-07-01", 1, 10, 20, 10, 0]])  # in the file, not in the ledger
    r = qk.reconcile(p, bad, "taxpnl.csv")
    assert {d["isin"]: d["unexplained"] for d in r["differences"]} == {OLD: pytest.approx(1000.0), "INE999Z01019": pytest.approx(-10.0)}
    con2 = con
    assert qk.ask_differences(con2, r, datetime(2026, 10, 28)) == 2 and qk.ask_differences(con2, r, datetime(2026, 10, 28)) == 0
    assert any("unexplained" in t for _, _, t in questions.open_questions(con2))


def test_an_export_without_the_columns_is_refused_with_a_reason(con):
    p = qk.build(con, 2026, fmv_2018=FMV.get)
    with pytest.raises(ValueError, match="ISIN column and a profit column"):
        qk.reconcile(p, b"a,b\n1,2\n", "x.csv")


CONSOLE = ("Symbol", "ISIN", "Entry Date", "Exit Date", "Quantity", "Buy Value", "Sell Value", "Profit", "Period of Holding", "Fair Market Value",
           "Taxable Profit", "Turnover", "Brokerage", "Exchange Transaction Charges", "IPFT", "SEBI Charges", "CGST", "SGST", "IGST", "Stamp Duty", "STT")


def test_the_console_layout_counts_its_own_charges_but_not_stt(con):
    """Checked on a real Console file: the ledger's gain differs from the file's profit by exactly Brokerage + Exchange charges + IPFT + SEBI +
    GST + Stamp Duty; STT (not deductible from capital gains) is in the file but not in the ledger's cost."""
    p = qk.build(con, 2026, fmv_2018=FMV.get)
    ours = {s["isin"]: s["gain"] for s in p["sales"]}
    # NEWCO: the file's profit 3,000 less 50 of deductible charges = our 2,950; its STT of 80 must not be subtracted again
    row = ["NEWCO", NEW, "2024-01-05", "2025-09-01", 10, 5000, 8000, 3000, 600, 0, 3000, 0, 10, 20, 0, 5, 0, 0, 10, 5, 80]
    exp = export([row, ["OLDCO", OLD, "2017-06-01", "2025-10-01", 50, 5000, 15000, 5000, 3000, 0, 5000, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                  ["STCO", ST, "2025-05-02", "2026-02-10", 100, 5000, 6000, 1000, 100, 0, 1000, 0, 10, 0, 0, 0, 0, 0, 0, 0, 0]], header=CONSOLE)
    r = qk.reconcile(p, exp, "taxpnl.csv")
    assert r["differences"] == [] and r["matched"] == 3 and ours[NEW] == pytest.approx(2950.0)
    new = next(x for x in r["rows"] if x["isin"] == NEW)
    assert new["export_charges"] == 50.0 and new["unexplained"] == pytest.approx(0.0)
