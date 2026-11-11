"""S82 (kg agent, A58): a filing with a date but no release time is used from the NEXT TRADING DAY's open, in the graph, its readers and the exit manager; the time is stored as
DERIVED; live news is stored at its publication time. Synthetic data only (rule 7).

Calendar facts the tests rely on (configs/markets.toml + market_holidays.toml): Fri 2026-10-30 -> Mon 2026-11-02; Sat/Sun -> Mon; Tue 2026-10-20 and Tue 2026-11-10 are holidays.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import duckdb
import pandas as pd
import pytest

from pflab.core import exits, session
from pflab.kg import build as kold
from pflab.kg import events as kev
from pflab.kg import graph as g
from pflab.kg2 import audit, build as kb, filing_time as ft
from pflab.pm import store

# fixtures of the S81 graph tests and of the exit manager's tests (the store, the book, the plans)
from test_s81_exits import CALM, DAY as EXIT_DAY, WIN, _state, con as xcon          # noqa: F401  (the fixture is used by name)
from test_s81_kg import A, B_NEW, GROUPS, _filing, _w, root               # noqa: F401

OPEN = (9, 15)
AUDITOR = "Resignation of Statutory Auditors of the Company"


def _at(d: date, h=9, m=15) -> datetime:
    return datetime(d.year, d.month, d.day, h, m)


# ------------------------------------------------------------------ the rule itself

def test_derived_time_is_the_next_trading_open():
    fri, sat, sun, mon = date(2026, 10, 30), date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 2)
    for d in (fri, sat, sun):                                                                  # Friday after the close, and the two shut days: the Monday open
        ts, rule, own = ft.filing_time(pd.NaT, pd.NaT, d)
        assert ts == _at(mon) and rule == "next_open_no_release_time" and own == d
    mon_ts, _, _ = ft.filing_time(None, None, mon)
    assert mon_ts == _at(date(2026, 11, 3))                                                     # a Monday filing is used from Tuesday, never the same day


def test_a_holiday_is_skipped():
    assert ft.next_open(date(2026, 10, 19)) == _at(date(2026, 10, 21))                           # Tue 20 Oct is a market holiday
    assert ft.next_open(date(2026, 10, 20)) == _at(date(2026, 10, 21))                           # a filing dated on the holiday itself
    assert ft.next_open(date(2026, 11, 9)) == _at(date(2026, 11, 11))                            # Tue 10 Nov is a holiday too


def test_a_filing_with_a_release_time_keeps_it_unchanged():
    ts, rule, own = ft.filing_time(pd.Timestamp("2026-10-30 18:42:10"), pd.NaT, date(2026, 10, 30))
    assert ts == datetime(2026, 10, 30, 18, 42, 10) and rule == "release_time" and own == date(2026, 10, 30)


def test_a_later_news_date_wins_and_a_row_with_no_date_is_placed_nowhere():
    ts, rule, own = ft.filing_time(pd.NaT, pd.Timestamp("2026-11-03 10:00"), date(2026, 11, 2))
    assert own == date(2026, 11, 3) and ts == _at(date(2026, 11, 4))
    assert ft.filing_time(pd.NaT, pd.NaT, None) == (None, None, None)


# ------------------------------------------------------------------ the graph build

def _add_file(root, day: date, rows):
    _w(root, f"bse_announcements/{day.year}/{day.isoformat()}.parquet", pd.DataFrame(rows))


def test_the_graph_enters_a_no_time_filing_at_the_next_open_with_the_rule_stored(root):
    _add_file(root, date(2026, 6, 12), [_filing("500001", "Receives show cause notice from the regulator", pd.NaT, news_dt=pd.NaT)])      # a Friday
    out = kb.build(root, date(2026, 6, 30), groups=GROUPS)
    ev = out["event"]
    r = ev[ev["headline"].str.contains("show cause")].iloc[0]
    assert r["ts"] == datetime(2026, 6, 15, 9, 15) and r["ts_rule"] == "next_open_no_release_time"       # Friday 12 June -> Monday 15 June
    assert r["event_date"] == date(2026, 6, 12) and r["isin"] == A
    assert r["link_rule"] == "filing:scrip_isin_on_filing_date_no_release_time" and "no release time" in r["link_proof"]
    timed = ev[(ev["source"] == "bse_announcement") & ev["headline"].str.contains("Resignation of Statutory")].iloc[0]
    assert timed["ts_rule"] == "release_time" and timed["ts"] == datetime(2026, 6, 10, 11, 0)               # a filing WITH a time is unchanged
    assert set(ev[ev["source"] == "gdelt_gkg1"]["ts_rule"]) == {"article_day_next_day"}                    # older stored news keeps its next-day rule
    assert out["stats"]["derived_time_used"] >= 2 and ev["ts_rule"].notna().all()


def test_a_filing_dated_after_the_build_day_is_not_in_the_graph_and_one_dated_on_it_is_held_for_the_next_open(root):
    day = date(2026, 6, 16)                                                                              # a Tuesday
    _add_file(root, day, [_filing("500001", "Receives show cause notice from the regulator", pd.NaT, news_dt=pd.NaT)])
    before = kb.build(root, date(2026, 6, 15), groups=GROUPS)["event"]
    assert not before["headline"].str.contains("show cause").any()                                         # dated after that build's day: nothing
    on = kb.build(root, day, groups=GROUPS)["event"]
    r = on[on["headline"].str.contains("show cause")].iloc[0]
    assert r["ts"] == _at(date(2026, 6, 17)) and r["event_date"] == day                                    # in the build of its own day, usable from the next open


def test_a_derived_twin_of_a_timed_filing_is_dropped(root):
    _add_file(root, date(2026, 6, 12), [_filing("500001", "Receives show cause notice from the regulator", pd.Timestamp("2026-06-12 11:00")),
                                         _filing("500001", "RECEIVES show cause notice from the regulator!", pd.NaT, news_dt=pd.NaT)])
    out = kb.build(root, date(2026, 6, 30), groups=GROUPS)
    ev = out["event"]
    assert (ev["headline"].str.lower().str.contains("show cause")).sum() == 1 and out["stats"]["derived_dropped_twin_of_timed"] == 1


def test_the_rebuild_is_byte_identical_with_derived_rows(root):
    _add_file(root, date(2026, 6, 12), [_filing("500001", "Receives show cause notice from the regulator", pd.NaT, news_dt=pd.NaT)])
    a, b = kb.build(root, date(2026, 6, 30), groups=GROUPS), kb.build(root, date(2026, 6, 30), groups=GROUPS)
    assert kb.hash_tables(a) == kb.hash_tables(b)


# ------------------------------------------------------------------ the audit

def _audit_con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


def test_audit_passes_with_derived_rows_and_catches_a_wrong_derived_time(root):
    _add_file(root, date(2026, 6, 30), [_filing("500001", "Receives show cause notice from the regulator", pd.NaT, news_dt=pd.NaT)])    # dated on the build day
    day = date(2026, 6, 30)
    out = kb.build(root, day, groups=GROUPS)
    c = _audit_con()
    res = audit.run_audit(c, root, day, graph=out, store=False)
    names = {k["name"]: k for k in res["checks"]}
    assert names["point_in_time"]["passed"] and names["derived_time_rule"]["passed"], names["point_in_time"]
    assert names["info_filings_with_derived_time"]["value"] >= 2
    assert names["filing_link_rate"]["passed"]
    # the same graph with one derived time moved to the same day (a look-ahead the other way) must fail the rule
    bad = {k: (v.copy() if isinstance(v, pd.DataFrame) else v) for k, v in out.items()}
    i = bad["event"].index[bad["event"]["ts_rule"] == "next_open_no_release_time"][0]
    bad["event"].at[i, "ts"] = datetime(2026, 6, 30, 9, 15)
    res2 = audit.run_audit(c, root, day, graph=bad, store=False)
    assert not {k["name"]: k for k in res2["checks"]}["derived_time_rule"]["passed"] and not res2["passed"]
    # an event dated after the build day still fails the point-in-time check
    bad2 = {k: (v.copy() if isinstance(v, pd.DataFrame) else v) for k, v in out.items()}
    j = bad2["event"].index[bad2["event"]["ts_rule"] == "next_open_no_release_time"][0]
    bad2["event"].at[j, "event_date"] = date(2026, 7, 1)
    assert not {k["name"]: k for k in audit.run_audit(c, root, day, graph=bad2, store=False)["checks"]}["point_in_time"]["passed"]


def test_migration_156_adds_ts_rule_and_leaves_old_rows(tmp_path):
    c = duckdb.connect(str(tmp_path / "m.duckdb"))
    store.migrate(c)
    cols = [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='kg2_event'").fetchall()]
    assert "ts_rule" in cols
    c.execute("INSERT INTO kg2_event (event_id, isin, source, ref, ts, event_date, kind, severity, headline, link_rule, link_proof, dedupe_key) "
              "VALUES ('old', ?, 'bse_announcement', 'r', ?, ?, 'other', 'low', 'h', 'x', 'p', 'k')", [A, datetime(2026, 6, 1, 10), date(2026, 6, 1)])
    store.migrate(c)                                                                                  # idempotent; the old row is untouched
    assert c.execute("SELECT ts_rule FROM kg2_event WHERE event_id='old'").fetchone()[0] is None


# ------------------------------------------------------------------ the readers: the thesis-break drill

def _drill_graph(root, filing_day: date):
    """A graph of the synthetic raw files built on `filing_day` and loaded into a store: one filing (an auditor's resignation, no release time) on the name the book holds."""
    _add_file(root, filing_day, [_filing("500001", AUDITOR + " (no time)", pd.NaT, news_dt=pd.NaT)])
    return kb.build(root, filing_day, groups=GROUPS)


def test_material_events_holds_a_derived_filing_back_until_its_time(root):
    c = _audit_con()
    d = date(2026, 10, 30)
    kb.load_store(c, _drill_graph(root, d), d)
    since = datetime(2026, 10, 25)
    nxt = _at(date(2026, 11, 2))
    assert kev.material_events(c, [A], since, until=nxt - timedelta(minutes=1)) == []                   # before the Monday open: nothing
    assert kev.material_events(c, [A], since, until=d) == []                                           # the filing's own day (a date bound = that day's end): nothing
    seen = kev.material_events(c, [A], since, until=nxt)
    assert len(seen) == 1 and seen[0]["ts"] == nxt and seen[0]["ts_rule"] == "next_open_no_release_time" and seen[0]["kind"] == "auditor_resignation"


def test_drill_the_thesis_check_sees_nothing_that_day_and_the_exit_fires_the_next_trading_day(xcon, root):
    """Held name WIN (= A). A filing dated Fri 30 Oct with no release time: at the Friday session the thesis check sees nothing; on Monday 2 Nov it sees it and sells."""
    con = xcon
    exits.backfill_plans(con, EXIT_DAY)
    assert EXIT_DAY == date(2026, 10, 30) and WIN == A
    kb.load_store(con, _drill_graph(root, EXIT_DAY), EXIT_DAY)
    stored = con.execute("SELECT ts, ts_rule FROM kg2_event WHERE headline LIKE '%no time%'").fetchall()
    assert stored == [(_at(date(2026, 11, 2)), "next_open_no_release_time")]
    # the loop's own reader (core/loop.py `_thesis_events`: since = five days back, no upper bound) hands the manager the row; the manager's point-in-time rule holds it back
    evs = kev.material_events(con, [WIN], datetime(2026, 10, 25))
    assert len(evs) == 1
    assert exits.check_thesis(con, EXIT_DAY, evs, prices={WIN: 100.0}) == []                           # Friday: not before the Monday open
    monday = date(2026, 11, 2)
    o = exits.check_thesis(con, monday, evs, prices={WIN: 100.0})
    assert len(o) == 1 and o[0]["kind"] == "thesis" and o[0]["isin"] == WIN and o[0]["side"] == "sell"
    assert "auditor_resignation" in o[0]["reason"]
    assert exits.check_thesis(con, monday, evs, prices={WIN: 100.0}) == []                              # the same event never sells twice


def test_drill_the_post_close_manager_orders_the_thesis_sale_on_the_next_trading_day_only(xcon, root):
    """The same filing through the exit manager's whole post-close pass (`check_close`, what the loop runs): nothing on Friday's close, a thesis sale on Monday's."""
    con = xcon
    exits.backfill_plans(con, EXIT_DAY)
    kb.load_store(con, _drill_graph(root, EXIT_DAY), EXIT_DAY)
    evs = kev.material_events(con, [WIN], datetime(2026, 10, 25))
    fri = [o for o in exits.check_close(con, EXIT_DAY, None, _state(con), events=evs) if o["kind"] == "thesis"]
    assert fri == []
    for r in con.execute("SELECT event_id FROM exit_events_s81").fetchall():                          # Friday's other orders (rails, levels) are not the point: clear them
        con.execute("DELETE FROM exit_events_s81 WHERE event_id=?", [r[0]])
    mon = date(2026, 11, 2)
    th = [o for o in exits.check_close(con, mon, {WIN: 100.0}, _state(con, mon), events=evs) if o["kind"] == "thesis"]
    assert len(th) == 1 and th[0]["isin"] == WIN


def test_the_session_reads_a_derived_filing_at_the_open_not_before(root):
    """The session loop's filings fallback: a no-time filing of the previous trading day is due at the open (09:15); a no-time filing dated today is not."""
    prev = date(2026, 6, 12)                                                                           # Friday; the next session is Monday 15 June
    mon = date(2026, 6, 15)
    _add_file(root, prev, [_filing("500001", "Forensic audit appointed by the board", pd.NaT, news_dt=pd.NaT)])
    _add_file(root, mon, [_filing("500001", "Forensic audit ordered, filed today", pd.NaT, news_dt=pd.NaT)])
    open_dt = _at(mon)
    ev = session._filing_events([A], open_dt, open_dt + timedelta(minutes=5), root)
    heads = " ".join(e["text"] for e in ev)
    assert "appointed by the board" in heads and "filed today" not in heads
    assert all(e["ts"] == open_dt and e["ts_rule"] == "next_open_no_release_time" for e in ev)
    assert session._filing_events([A], open_dt - timedelta(hours=2), open_dt - timedelta(minutes=1), root) == []        # before the open: nothing
    keep, src = session.session_events(None, [A], open_dt, open_dt + timedelta(minutes=5), root)         # no store: the fallback; ts == open is inside [open, now]
    assert src.startswith("bse_announcements") and len(keep) >= 1


# ------------------------------------------------------------------ live news

def test_live_news_keeps_its_publication_time_and_an_item_with_none_gets_the_next_day_rule(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    now = datetime(2026, 11, 3, 6, 0)
    gkg = pd.DataFrame([
        {"date": pd.Timestamp("2026-11-02 10:00:00"), "url": "https://x/with-time", "source": "x", "tone": 1.0, "isins": "", "themes": "", "orgs": "", "persons": "", "india": True, "quotes": "",
         "file_day": date(2026, 11, 2)},
        {"date": pd.NaT, "url": "https://x/no-time", "source": "x", "tone": 0.0, "isins": "", "themes": "", "orgs": "", "persons": "", "india": True, "quotes": "", "file_day": date(2026, 11, 2)},
        {"date": pd.NaT, "url": "https://x/no-time-no-day", "source": "x", "tone": 0.0, "isins": "", "themes": "", "orgs": "", "persons": "", "india": True, "quotes": "", "file_day": None},
    ])
    kold.articles(c, gkg, now=now)
    rows = dict(c.execute("SELECT url, published_at FROM kg_docs WHERE kind='article'").fetchall())
    assert rows["https://x/with-time"] == datetime(2026, 11, 2, 15, 30)                                   # GDELT's 10:00 UTC is 15:30 IST: stored as the publication time, in IST
    assert rows["https://x/no-time"] == datetime(2026, 11, 3, 0, 0)                                       # no time of its own: usable from the next day
    assert "https://x/no-time-no-day" not in rows                                                         # no time and no day: nothing to place it by


def test_gkg_load_adds_the_collection_day(tmp_path):
    from pflab.data import gdelt_gkg as gk
    p = tmp_path / "gkg"
    p.mkdir()
    pd.DataFrame([{"date": pd.Timestamp("2026-11-02 10:00"), "source": "x", "url": "u", "isins": "A", "themes": "", "persons": "", "orgs": "", "tone": 0.0, "quotes": "", "india": True}]
                 ).to_parquet(p / "2026-11-02.parquet")
    df = gk.load(date(2026, 11, 1), tmp_path)
    assert list(df["file_day"]) == [date(2026, 11, 2)]
    assert list(gk.load(date(2026, 12, 1), tmp_path).columns)[-1] == "file_day"


def test_the_new_scripts_have_no_control_characters():
    from pathlib import Path
    for rel in ("src/pflab/kg2/filing_time.py", "src/pflab/kg2/build.py", "src/pflab/kg2/audit.py", "src/pflab/kg/events.py", "src/pflab/pm/mig_s79/m_kg82.py", "tests/test_s82_kg.py"):
        text = (Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8")
        assert not [ch for ch in text if ord(ch) < 32 and ch not in "\n\r\t"], rel


# ------------------------------------------------------------------ the study readers

def test_stamp_missing_fills_only_rows_with_no_time():
    df = pd.DataFrame({"t": [pd.Timestamp("2026-06-10 10:00"), pd.NaT, pd.NaT], "filename": ["x/2026/2026-06-10.parquet", "x/2026/2026-06-12.parquet", "x/odd.parquet"]})
    out = ft.stamp_missing(df)
    assert list(out.columns) == ["t"]
    assert out["t"].iloc[0] == pd.Timestamp("2026-06-10 10:00")                                       # a row with a time is untouched
    assert out["t"].iloc[1] == pd.Timestamp("2026-06-15 09:15")                                       # Friday's file -> Monday's open
    assert pd.isna(out["t"].iloc[2])                                                                  # no file day: stays null
    assert ft.file_day_of("D:/data/bse_announcements/2026/2026-06-12.parquet") == date(2026, 6, 12)


def test_event_study_events_includes_a_no_time_filing_at_the_next_open(root):
    from pflab.quant import event_study as es
    _add_file(root, date(2026, 6, 12), [_filing("500001", "Forensic audit appointed by the board", pd.NaT, news_dt=pd.NaT, sub="Forensic Audit")])
    ev = es.events(root, "2026-06-01", "2026-06-30", headline_regex="forensic audit")
    row = ev[ev["headline"].str.contains("appointed by the board")]
    assert len(row) == 1 and row["t"].iloc[0] == pd.Timestamp("2026-06-15 09:15")
    assert len(es.events(root, "2026-06-01", "2026-06-14", headline_regex="forensic audit")) == 0       # not before its time
