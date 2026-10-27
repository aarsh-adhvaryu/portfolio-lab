"""S64 Phase 5 item 10: business at a glance from our own data."""
from datetime import date

import duckdb
import pandas as pd
import pytest

from pflab.hq import business
from pflab.pm import store


@pytest.fixture
def con(tmp_path):
    c = duckdb.connect(str(tmp_path / "pm.duckdb"))
    store.migrate(c)
    return c


def add_q(con, scrip, qe, rev, npf, eps=1.0):
    usable = date(qe.year + (1 if qe.month >= 11 else 0), (qe.month + 1) % 12 + 1, 15)          # filed about 45 days later
    con.execute("INSERT INTO quarterly_results (scrip_code, quarter_end, revenue, net_profit, eps_basic, pbt, tax, usable_from, "
                "date_source, source, fetched_at, basis) VALUES (?,?,?,?,?,?,?,?,'t','t',now(),'standalone')",
                [scrip, qe, rev, npf, eps, npf * 1.3, -npf * 0.3, usable])


def test_quarters_table_has_margins_and_year_on_year_and_leaves_gaps(con, tmp_path, monkeypatch):
    from pflab.fundamentals import pit
    monkeypatch.setattr(pit, "load_history", lambda scrip, root=None: pd.DataFrame())
    for qe, rev in ((date(2024, 9, 30), 1000.0), (date(2024, 12, 31), 1100.0), (date(2025, 6, 30), 1300.0),
                    (date(2025, 9, 30), 1200.0), (date(2025, 12, 31), 1210.0)):               # no 2025-03 on record
        add_q(con, "1", qe, rev, rev * 0.1)
    t = business.quarters_table(con, tmp_path, "1", date(2026, 6, 1))
    assert [r["quarter"] for r in t] == ["2024-09-30", "2024-12-31", "2025-06-30", "2025-09-30", "2025-12-31"]
    last = t[-1]
    assert last["revenue_cr"] == 121.0 and last["net_margin_pct"] == 10.0 and last["revenue_yoy_pct"] == pytest.approx(10.0)
    assert t[0]["revenue_yoy_pct"] is None                                       # no quarter a year earlier on record
    assert business.quarters_table(con, tmp_path, "1", date(2025, 1, 5))[-1]["quarter"] == "2024-09-30"     # point in time


def test_only_concall_and_presentation_titles_match():
    for t in ("Transcript of Earnings Call Q2", "Investor Presentation Q2 FY27", "Audio recording of the conference call"):
        assert business.DOC_WORDS.search(t), t
    for t in ("Board meeting outcome", "IT index surges 2.5%: a positive, says this analyst", "Zensar rebounded, says analyst"):
        assert not business.DOC_WORDS.search(t), t


def test_kpi_sheet_is_found_by_file_name(tmp_path):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "tijori_AAA_export.xlsx").write_text("x")
    assert business.kpi_sheet(tmp_path, "AAA") == "tijori_AAA_export.xlsx" and business.kpi_sheet(tmp_path, "BBB") is None
