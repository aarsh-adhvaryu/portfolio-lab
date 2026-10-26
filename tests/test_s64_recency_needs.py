"""S64 Phase 5 item 2: age and staleness on what the brain reads; the Tijori ask the moment a company's detail is missing."""
from datetime import date, datetime

import duckdb
import pandas as pd
import pytest

from pflab.agents import needs
from pflab.hq import recency
from pflab.pm import store

TODAY = date(2026, 10, 27)


def test_policy_days_per_kind():
    assert recency.verdict("article", "2026-10-25", TODAY) == {"age_days": 2, "stale": False}
    assert recency.verdict("article", "2026-10-23", TODAY)["stale"] is True            # news: 3 days
    assert recency.verdict("filing", "2026-10-01", TODAY)["stale"] is False            # filings: 30
    assert recency.verdict("filing", "2026-09-20", TODAY)["stale"] is True
    assert recency.verdict("result", "2026-07-30", TODAY)["stale"] is False            # results: 100
    assert recency.verdict("web", "2026-10-18", TODAY)["stale"] is True                # web: 7
    assert recency.verdict("deal", "2026-01-01", TODAY) == {"age_days": 299, "stale": None}   # no policy: an age only


def test_undated_is_marked_and_never_fresh():
    items = recency.stamp([{"kind": "article", "published": None}, {"kind": "article", "published": "2026-10-27"}], None, TODAY)
    assert items[0]["stale"] == "undated" and items[0]["age_days"] is None
    assert recency.fresh(items) == [items[1]]


@pytest.fixture
def con(tmp_path):
    c = duckdb.connect(str(tmp_path / "pm.duckdb"))
    store.migrate(c)
    return c


def test_company_asked_once_a_month(con):
    now = datetime(2026, 10, 27, 10, 0)
    q = needs.ask_company_detail(con, "INE000A01010", "only 3 quarters of results, 8 needed", now, "ABC")
    assert q is not None
    assert needs.ask_company_detail(con, "INE000A01010", "again", now.replace(day=28), "ABC") is None     # same month
    assert needs.ask_company_detail(con, "INE000A01010", "next month", datetime(2026, 11, 2), "ABC") is not None
    text = con.execute("SELECT text FROM questions WHERE q_id=?", [q]).fetchone()[0]
    assert text.startswith("Please drop the Tijori sheet for ABC (missing: only 3 quarters")


def test_check_company_counts_quarters(con, tmp_path, monkeypatch):
    from pflab.data import bse_scrip_isin
    monkeypatch.setattr(bse_scrip_isin, "load", lambda root=None: pd.DataFrame({"scrip_code": ["500001", "500002"],
                                                                                 "isin": ["INE000A01010", "INE000B01010"]}))
    cols = [(r[0], r[1]) for r in con.execute("DESCRIBE quarterly_results").fetchall()]

    def add(scrip, qe):
        row = {c: (0 if t in ("DOUBLE", "BIGINT", "INTEGER") else None) for c, t in cols}
        row.update(scrip_code=scrip, basis="standalone", quarter_end=qe, usable_from=qe, fetched_at=datetime(2026, 1, 1),
                   source="t", date_source="t")
        row = {k: v for k, v in row.items() if v is not None}
        con.execute(f"INSERT INTO quarterly_results ({','.join(row)}) VALUES ({','.join('?' * len(row))})", list(row.values()))
    for k in range(3):                                                    # ABC has 3 quarters; DEF has 8
        add("500001", date(2025, 1 + k, 28))
    for k in range(8):
        add("500002", date(2024, 1 + k, 28))
    assert needs.quarter_count(con, None, "INE000A01010") == 3
    assert needs.check_company(con, None, "INE000A01010", datetime(2026, 10, 27), "ABC") is not None
    assert needs.check_company(con, None, "INE000B01010", datetime(2026, 10, 27), "DEF") is None     # enough quarters
    assert needs.check_company(con, None, "INE999Z01010", datetime(2026, 10, 27), "ZZZ") is not None  # no scrip: no data
