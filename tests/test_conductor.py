"""S53 conductor: market clock, sync check, asks, wake and closing notes, the fact sheet. Synthetic store and data
folder; nothing here touches the network, Telegram or the real PM store."""
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab.conductor import calendar as cl
from pflab.conductor import run as cr
from pflab.conductor import situation as st
from pflab.conductor import sync
from pflab.pm import store
from pflab.service import jobs
from pflab.service.schedule import Daily, Interval

CAL = cl.Calendar({date(2026, 10, 20): "Dussehra", date(2026, 11, 10): "Diwali Balipratipada"},
                  {date(2026, 11, 8): "Muhurat trading"}, (2026,))
FRI = datetime(2026, 10, 23, 21, 30)          # a Friday evening, after the evening jobs


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "ledger.duckdb")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv("PFLAB_BACKUP_DIR", raising=False)
    saved = dict(jobs.REGISTRY)
    jobs.REGISTRY.clear()
    yield
    jobs.REGISTRY.clear()
    jobs.REGISTRY.update(saved)


def ctx_of(con, tmp_path, now):
    return jobs.Ctx(con, now, tmp_path / "pm", tmp_path / "data", tmp_path, "python", None)


def register_collectors():
    for name in ("collect", "prices", "nav", "filings"):
        jobs.register(jobs.Job(name, Daily(19, 30), lambda c: {}))


def write_data(root, upto: date, global_upto: date = None):
    """Every source the sync check reads, up to `upto`."""
    (root / "bhavcopy" / "2026").mkdir(parents=True)
    (root / "bhavcopy" / "2026" / f"{upto}.parquet").write_bytes(b"")
    (root / "indices").mkdir()
    for f in ("INDIA_VIX", "NIFTY500_TRI"):
        pd.DataFrame({"date": [upto - timedelta(days=1), upto], "close": [1.0, 1.0]}).to_parquet(root / "indices" / f"{f}.parquet")
    for d in ("bse_announcements", "gkg"):
        (root / d).mkdir()
        (root / d / f"{upto + timedelta(days=1)}.parquet").write_bytes(b"")
    (root / "global").mkdir()
    pd.DataFrame({"date": [global_upto or upto], "close": [1.0]}).to_parquet(root / "global" / "X.parquet")


def write_store(con, upto: date, built: datetime):
    con.execute("INSERT INTO prices VALUES ('INE000A01010', ?, 10, 'EQ', 'test', ?)", [upto, built])
    con.execute("INSERT INTO navs VALUES ('INF000A01010', '1', ?, 10, 'test', ?)", [upto, built])
    con.execute("INSERT INTO gold_rates VALUES (?, 'pm', 'gold', 1, 'g', 'test', ?)", [upto, built])
    con.execute("INSERT INTO events (event_id, kind, account_id, trade_date, ingested_at) VALUES (1, 'buy', 'z', ?, ?)",
                [upto, built])


# --- market clock ---------------------------------------------------------------------------------------------

def test_modes_through_a_trading_day_and_on_closed_days():
    assert CAL.mode(datetime(2026, 10, 21, 8, 0)) == "pre_open"
    assert CAL.mode(datetime(2026, 10, 21, 9, 15)) == "market"
    assert CAL.mode(datetime(2026, 10, 21, 15, 30)) == "after_close"
    assert CAL.mode(datetime(2026, 10, 20, 11, 0)) == "closed"            # Dussehra
    assert CAL.mode(datetime(2026, 10, 24, 11, 0)) == "closed"            # Saturday


def test_next_and_previous_sessions_skip_weekends_and_holidays():
    assert CAL.next_trading_day(date(2026, 10, 23)) == date(2026, 10, 26)          # Fri -> Mon
    assert CAL.next_trading_day(date(2026, 11, 9)) == date(2026, 11, 11)           # Mon -> Wed over Diwali
    assert CAL.previous_trading_day(date(2026, 10, 21)) == date(2026, 10, 19)      # Wed -> Mon over Dussehra
    assert CAL.closed_after(date(2026, 10, 23)) == [date(2026, 10, 24), date(2026, 10, 25)]
    assert CAL.closed_after(date(2026, 10, 21)) == []


def test_last_closed_session_waits_for_the_evening_jobs():
    assert CAL.last_closed_session(datetime(2026, 10, 21, 20, 0)) == date(2026, 10, 19)
    assert CAL.last_closed_session(datetime(2026, 10, 21, 21, 0)) == date(2026, 10, 21)
    assert CAL.last_closed_session(datetime(2026, 10, 24, 12, 0)) == date(2026, 10, 23)


def test_shipped_holiday_list_loads_and_is_dated():
    c = cl.load()
    assert c.has_year(2026) and not c.is_trading_day(date(2026, 10, 20)) and c.is_trading_day(date(2026, 10, 21))
    assert all(d.weekday() < 5 for d in c.holidays)                      # weekends are not listed as holidays
    assert c.next_trading_day(date(2026, 11, 23)) == date(2026, 11, 25)   # Guru Nanak Jayanti


# --- sync check -------------------------------------------------------------------------------------------------

def test_everything_in_step_is_ok(con, tmp_path):
    register_collectors()
    write_data(tmp_path / "data", date(2026, 10, 23))
    write_store(con, date(2026, 10, 23), FRI - timedelta(days=3))
    f = {x.name: x for x in sync.data_findings(ctx_of(con, tmp_path, FRI), CAL) + sync.ledger_findings(ctx_of(con, tmp_path, FRI))}
    assert {k: v.status for k, v in f.items()} == {k: "ok" for k in f}, sync.render(list(f.values()))


def test_stale_data_is_auto_when_a_job_fills_it_and_warn_when_none_does(con, tmp_path):
    jobs.register(jobs.Job("collect", Daily(19, 30), lambda c: {}))      # collect on; prices and nav jobs absent
    write_data(tmp_path / "data", date(2026, 10, 16), global_upto=date(2026, 9, 22))
    write_store(con, date(2026, 10, 16), FRI)
    f = {x.name: x for x in sync.data_findings(ctx_of(con, tmp_path, FRI), CAL)}
    assert f["data:NSE bhavcopy"].status == "auto" and "4 session(s) behind" in f["data:NSE bhavcopy"].detail   # Dussehra skipped
    assert f["data:prices (ledger)"].status == "warn" and "no job" in f["data:prices (ledger)"].detail
    assert f["data:foreign markets"].status == "warn"


def test_foreign_markets_are_filled_by_the_global_job_and_switched_off_jobs_are_not_warnings(con, tmp_path):
    jobs.register(jobs.Job("global", Daily(7, 30, weekdays_only=False), lambda c: {}))
    jobs.register(jobs.Job("tradecheck", Daily(16, 0), lambda c: {}, enabled_fn=lambda c: (False, "no Kite login today")))
    write_data(tmp_path / "data", date(2026, 10, 23), global_upto=date(2026, 9, 22))
    c = ctx_of(con, tmp_path, FRI)
    f = {x.name: x for x in sync.data_findings(c, CAL) + sync.service_findings(c, CAL)}
    assert f["data:foreign markets"].status == "auto" and "'global' job" in f["data:foreign markets"].detail
    # S58b: on a trading day a missing Kite login is asked for (the portfolio today needs it), not only shown as off
    assert f["kite login"].status == "ask" and "job:backup" not in f and f["backup"].status == "ask"


def test_global_download_never_shrinks_a_series(tmp_path):
    from pflab.data import global_markets as gm
    full = pd.DataFrame({"date": [date(2026, 10, d) for d in (14, 15, 16)], "close": [1.0, 2.0, 3.0]})
    gm.collect(tmp_path, ["US_SP500"], pause=0, get=lambda s: full)
    out = gm.collect(tmp_path, ["US_SP500"], pause=0, get=lambda s: full.tail(1))          # a cut history
    assert out["US_SP500"].startswith("kept the file") and len(pd.read_parquet(tmp_path / "global" / "US_SP500.parquet")) == 3
    longer = pd.concat([full, pd.DataFrame({"date": [date(2026, 10, 19)], "close": [4.0]})])
    assert gm.collect(tmp_path, ["US_SP500"], pause=0, get=lambda s: longer)["US_SP500"][0] == 4


def test_ledger_asks_when_empty_or_a_month_old_with_a_monthly_key(con, tmp_path):
    c = ctx_of(con, tmp_path, FRI)
    assert sync.ledger_findings(c)[0].ask_key == "conductor:ledger-empty"
    write_store(con, date(2026, 9, 1), datetime(2026, 9, 1, 10, 0))
    f = sync.ledger_findings(c)[0]
    assert f.status == "ask" and f.ask_key == "conductor:statements:2026-10" and "build_pm_ledger" in f.ask_text


def test_missing_backup_is_an_ask_and_a_missing_holiday_year_a_warning(con, tmp_path):
    out = {f.name: f for f in sync.service_findings(ctx_of(con, tmp_path, datetime(2027, 1, 5, 10, 0)), CAL)}
    assert out["backup"].status == "ask" and out["backup"].ask_key == "conductor:backup-target"
    assert out["market holidays"].status == "warn"
    dec = {f.name: f for f in sync.service_findings(ctx_of(con, tmp_path, datetime(2026, 12, 2, 10, 0)), CAL)}
    assert "2027" in dec["market holidays"].detail


# --- a pass ---------------------------------------------------------------------------------------------------------

def nw_none(con, d):
    raise ValueError("empty ledger")


def outbox(con):
    return con.execute("SELECT kind, text, dedup_key FROM outbox ORDER BY msg_id").fetchall()


def test_first_start_says_what_it_found_and_asks_once(con, tmp_path):
    register_collectors()
    c = ctx_of(con, tmp_path, datetime(2026, 11, 2, 10, 0))
    out = cr.conduct(c, CAL, nw_none)
    msgs = outbox(con)
    assert [m[2] for m in msgs if m[0] == "conductor"] == ["wake:first"]
    assert "First start" in msgs[-1][1] and "Needed from you" in msgs[-1][1]
    keys = {k for (k,) in con.execute("SELECT subject_key FROM questions WHERE status='open'").fetchall()}
    assert {"conductor:ledger-empty", "conductor:backup-target"} <= keys and len(out["asked"]) == len(keys)
    con.execute("INSERT INTO job_runs VALUES (99, 'conductor', ?, ?, ?, 'ok', '{}')", [c.now, c.now, c.now])
    again = cr.conduct(ctx_of(con, tmp_path, c.now + timedelta(minutes=15)), CAL, nw_none)
    assert again["asked"] == [] and again["sent"] == [] and len(outbox(con)) == len(msgs)    # nothing repeated


def test_an_ask_that_resolved_itself_is_dropped(con, tmp_path):
    c = ctx_of(con, tmp_path, datetime(2026, 11, 2, 10, 0))
    cr.conduct(c, CAL, nw_none)
    write_store(con, date(2026, 10, 30), datetime(2026, 11, 2, 11, 0))         # the investor rebuilt the ledger
    out = cr.conduct(ctx_of(con, tmp_path, datetime(2026, 11, 2, 12, 0)), CAL, nw_none)
    st_ = con.execute("SELECT status FROM questions WHERE subject_key='conductor:ledger-empty'").fetchone()[0]
    assert st_ == "dropped" and out["dropped"] == 1


def test_back_after_days_off_lists_the_catch_up(con, tmp_path):
    register_collectors()
    write_data(tmp_path / "data", date(2026, 10, 16))
    write_store(con, date(2026, 10, 16), datetime(2026, 10, 16, 22, 0))
    last = datetime(2026, 10, 16, 22, 0)
    con.execute("INSERT INTO job_runs VALUES (1, 'conductor', ?, ?, ?, 'ok', '{}')", [last, last, last])
    out = cr.conduct(ctx_of(con, tmp_path, datetime(2026, 10, 26, 9, 0)), CAL, nw_none)
    note = [t for k, t, key in outbox(con) if key.startswith("wake:")]
    assert out["offline_hours"] > 200 and note and "Back after 9 day(s)" in note[0]
    assert "Catching up by myself" in note[0] and "NSE bhavcopy" in note[0]


def test_friday_evening_note_says_when_to_switch_on_once(con, tmp_path):
    con.execute("INSERT INTO job_runs VALUES (1, 'conductor', ?, ?, ?, 'ok', '{}')", [FRI - timedelta(minutes=15)] * 3)
    cr.conduct(ctx_of(con, tmp_path, FRI), CAL, nw_none)
    cr.conduct(ctx_of(con, tmp_path, FRI + timedelta(minutes=15)), CAL, nw_none)
    notes = [t for k, t, key in outbox(con) if key.startswith("closing:")]
    assert len(notes) == 1
    assert "Sat 24 Oct, Sun 25 Oct" in notes[0] and "Sun 25 Oct 18:00" in notes[0] and "Mon 26 Oct" in notes[0]


def test_holiday_note_names_the_holiday_and_no_note_before_the_evening_jobs(con, tmp_path):
    assert cr.closing_note(ctx_of(con, tmp_path, datetime(2026, 11, 9, 20, 0)), CAL) is None
    n = cr.closing_note(ctx_of(con, tmp_path, datetime(2026, 11, 9, 21, 5)), CAL)
    assert "Tue 10 Nov (Diwali Balipratipada)" in n and "Tue 10 Nov 18:00" in n and "Wed 11 Nov" in n
    assert cr.closing_note(ctx_of(con, tmp_path, datetime(2026, 11, 5, 21, 5)), CAL) is None      # Friday 6th trades
    fri = cr.closing_note(ctx_of(con, tmp_path, datetime(2026, 11, 6, 21, 5)), CAL)
    assert "Muhurat trading" in fri


def test_fact_sheet_carries_dates_and_sources_and_says_when_a_figure_is_missing(con, tmp_path):
    register_collectors()
    g = datetime(2026, 10, 23, 20, 45)
    con.execute("INSERT INTO job_runs VALUES (5, 'guards', ?, ?, ?, 'ok', ?)",
                [g, g, g, '{"market_state": "elevated", "dip_active": false, "not_ok": 2}'])
    cr.conduct(ctx_of(con, tmp_path, FRI), CAL, nw_none)
    sheet = st.load(tmp_path / "pm" / "reports")
    assert sheet["market.state"] == {"value": "elevated", "as_of": "2026-10-23 20:45",
                                     "source": "guards job (Hawkes market state, S40)"}
    assert sheet["market.next_session"]["value"] == "2026-10-26"
    assert sheet["portfolio"]["value"].startswith("not available")
    assert any("ledger" in q for q in sheet["needs_from_investor"]["value"])
    md = (tmp_path / "pm" / "reports" / "situation.md").read_text(encoding="utf-8")
    assert "| market.state | elevated | 2026-10-23 20:45 |" in md


def test_fact_sheet_takes_portfolio_figures_from_the_tool(con, tmp_path):
    write_store(con, date(2026, 10, 23), FRI)
    sheet = st.build(con, FRI, CAL, [], lambda c, d: {"net_worth": 1000, "investable": 800, "other": 1})
    assert sheet["portfolio.net_worth"]["value"] == 1000 and sheet["portfolio.net_worth"]["as_of"] == date(2026, 10, 23)
    assert "portfolio.other" not in sheet


def test_conductor_job_is_registered_last_and_runs_every_day():
    import importlib

    from pflab.service import tasks
    importlib.reload(tasks)
    assert list(jobs.REGISTRY)[-1] == "conductor" and "global" in jobs.REGISTRY
    s = jobs.REGISTRY["conductor"].schedule
    assert isinstance(s, Interval) and s.minutes == 15 and not s.weekdays_only
