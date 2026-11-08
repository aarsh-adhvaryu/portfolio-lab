"""S79b item K: the Kite minute-bar backfill (60-day windows, resume, idempotency, 429 backoff, partial days stated, not invented), the parquet + 60-session table,
`read`, the logged-out question once a day, and no token or holding in any log. A fake Kite client; nothing real."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from pflab.ingest import kite_backfill as kb
from pflab.pm import store

NOW = datetime(2026, 11, 8, 1, 0)              # Sunday night: the last closed session is Friday 2026-11-06
LAST = date(2026, 11, 6)
TOKEN = "SECRETTOKEN0123456789"
HELD = "ZQXHELDNAME"


class FakeKite:
    """historical_data(token, from, to, 'minute'): full sessions on weekdays, tz-aware like Kite, plus pre-open bars that must be dropped."""

    def __init__(self, *, listed_from: date = date(2000, 1, 1), short: dict = None, fail: list = None, access_token: str = TOKEN):
        self.calls = []
        self.listed_from, self.short, self.fail = listed_from, short or {}, list(fail or [])
        self.access_token = access_token

    def holdings(self):
        return [dict(tradingsymbol=HELD, exchange="NSE", isin="INE000A01011", quantity=10, t1_quantity=0, average_price=10.0, last_price=11.0)]

    def instruments(self, ex="NSE"):
        return [dict(tradingsymbol=HELD, instrument_token=11, segment="NSE"), dict(tradingsymbol="OTHER", instrument_token=12, segment="NSE"),
                dict(tradingsymbol="NIFTY 50", instrument_token=13, segment="INDICES"), dict(tradingsymbol="NIFTY BANK", instrument_token=14, segment="INDICES")]

    def historical_data(self, token, frm, to, interval):
        self.calls.append((token, frm, to))
        assert interval == "minute"
        assert (to.date() - frm.date()).days < 60, "Kite allows at most 60 days per minute request"
        if self.fail:
            e = self.fail.pop(0)
            if e is not None:
                raise e
        rows = []
        d = frm.date()
        while d <= to.date():
            if d.weekday() < 5 and d >= self.listed_from:
                n = self.short.get(d, 375)
                base = datetime.combine(d, time(9, 15))
                rows.append(dict(date=pd.Timestamp(datetime.combine(d, time(9, 5))).tz_localize("Asia/Kolkata").to_pydatetime(), open=1, high=1, low=1, close=1, volume=0))
                for i in range(n):
                    ts = pd.Timestamp(base + timedelta(minutes=i)).tz_localize("Asia/Kolkata").to_pydatetime()
                    rows.append(dict(date=ts, open=100.0 + i, high=101.0 + i, low=99.0 + i, close=100.5 + i, volume=10.0 + i))
            d += timedelta(days=1)
        return rows


class Boom(Exception):
    pass


def _cfg(tmp_path, since=date(2026, 6, 1), **kw):
    return kb.RunConfig(root=tmp_path / "bars", since_by_tier={"index": since, "held": since, "nifty500": since}, workers=1, **kw)


def _plan():
    return [dict(tier="index", since=kb.FLOOR, items=[("INDEX:NIFTY 50", 13)]), dict(tier="held", since=kb.FLOOR, items=[(HELD, 11)])]


def _run(kite, tmp_path, logs=None, **kw):
    lim = kb.RateLimiter(0.0, sleep=lambda s: None)
    return kb.run(kite, _cfg(tmp_path), now=NOW, limiter=lim, sleep=kw.pop("sleep", lambda s: None), log=(logs.append if logs is not None else (lambda s: None)),
                  tiers_plan=kw.pop("tiers_plan", _plan()), **kw)


def test_windows_are_on_a_60_day_grid_and_never_longer():
    a, b = kb.chunk_bounds(5)
    assert (b - a).days == 59 and a == kb.FLOOR + timedelta(days=300)
    ks = kb.chunks_newest_first(date(2026, 6, 1), LAST)
    assert ks == sorted(ks, reverse=True) and kb.chunk_bounds(ks[0])[0] <= LAST <= kb.chunk_bounds(ks[0])[1]
    assert kb.chunk_bounds(ks[-1])[0] <= date(2026, 6, 1)
    assert all((kb.chunk_bounds(k)[1] - kb.chunk_bounds(k)[0]).days < 60 for k in ks)


def test_fetch_stores_session_bars_only_and_states_the_coverage(tmp_path):
    k = FakeKite()
    res = _run(k, tmp_path)
    assert res["stopped"] is None and res["tiers"]["index"]["names"] == 1
    pq, sp = kb.paths(tmp_path / "bars", "IN", "INDEX:NIFTY 50")
    assert pq.name == "INDEX_NIFTY_50.parquet"
    df = pd.read_parquet(pq)
    assert list(df.columns) == kb.COLS and df["ts"].is_monotonic_increasing and df["ts"].is_unique
    assert df["ts"].dt.time.min() == time(9, 15) and df["ts"].dt.time.max() == time(15, 29)       # the 09:05 pre-open bar was dropped
    assert df["ts"].dt.tz is None
    assert str(df["ts"].dt.date.max()) == "2026-11-06" and not any(d.weekday() > 4 for d in df["ts"].dt.date.unique())
    cov = kb.coverage(tmp_path / "bars")
    assert cov["files"] == 2 and cov["rows"] == len(df) * 2 and cov["last_day"] == "2026-11-06"


def test_resume_and_idempotent_never_refetches_a_covered_window(tmp_path):
    k = FakeKite()
    _run(k, tmp_path)
    n1 = len(k.calls)
    assert n1 > 0
    k2 = FakeKite()
    res = _run(k2, tmp_path)
    assert len(k2.calls) == 0 and res["tiers"]["index"]["windows_fetched"] == 0
    pq, _ = kb.paths(tmp_path / "bars", "IN", HELD)
    assert pd.read_parquet(pq)["ts"].is_unique


def test_a_stop_in_the_middle_resumes_with_the_missing_windows_only(tmp_path):
    full = FakeKite()
    _run(full, tmp_path / "full")
    total = len(full.calls)
    stop = tmp_path / "STOP"
    k = FakeKite()
    real = k.historical_data

    def hd(*a):
        out = real(*a)
        if len(k.calls) == 3:
            stop.write_text("x")
        return out
    k.historical_data = hd
    res = kb.run(k, _cfg(tmp_path), now=NOW, limiter=kb.RateLimiter(0.0, sleep=lambda s: None), sleep=lambda s: None, log=lambda s: None, tiers_plan=_plan(), stop_file=stop)
    assert res["stopped"].startswith("StopRun")
    done = len(k.calls)
    stop.unlink()
    k2 = FakeKite()
    res2 = _run(k2, tmp_path)
    assert res2["stopped"] is None
    assert done + len(k2.calls) == total                         # nothing fetched twice, nothing skipped
    pq, _ = kb.paths(tmp_path / "bars", "IN", "INDEX:NIFTY 50")
    assert pd.read_parquet(pq)["ts"].is_unique


def test_429_backs_off_exponentially_then_succeeds_and_slows_the_others(tmp_path):
    sleeps = []
    k = FakeKite(fail=[Boom("429 Too many requests"), Boom("Too many requests"), Boom("Connection timed out"), None])
    res = _run(k, tmp_path, sleep=sleeps.append, tiers_plan=_plan()[:1])
    assert res["rate_limited"] == 2 and res["network_retries"] == 1 and res["tiers"]["index"]["errors"] == 0
    assert sleeps[:3] == [2.0, 4.0, 8.0]
    assert kb.coverage(tmp_path / "bars")["rows"] > 0


def test_a_window_that_keeps_failing_is_left_unrecorded_and_retried_next_run(tmp_path):
    k = FakeKite(fail=[Boom("something odd")] + [None] * 100)
    res = _run(k, tmp_path, tiers_plan=_plan()[:1])
    assert res["tiers"]["index"]["errors"] == 1
    _, sp = kb.paths(tmp_path / "bars", "IN", "INDEX:NIFTY 50")
    missing_k = max(kb.chunks_newest_first(date(2026, 6, 1), LAST))
    assert str(missing_k) not in kb.load_state(sp)["chunks"]
    k2 = FakeKite()
    _run(k2, tmp_path, tiers_plan=_plan()[:1])
    assert len(k2.calls) == 1                                        # only the failed window


def test_a_refused_token_stops_the_run_and_says_logged_out(tmp_path):
    class TokenException(Exception):
        pass
    k = FakeKite(fail=[TokenException("Incorrect `api_key` or `access_token`.")])
    logs = []
    res = _run(k, tmp_path, logs)
    assert res["stopped"] and "KiteLoggedOut" in " ".join(logs)
    assert len(k.calls) == 1                                          # no second request after the token was refused


def test_partial_days_are_stated_not_invented(tmp_path):
    bad = date(2026, 10, 20)
    k = FakeKite(short={bad: 100})
    _run(k, tmp_path, tiers_plan=_plan()[:1])
    pq, sp = kb.paths(tmp_path / "bars", "IN", "INDEX:NIFTY 50")
    df = pd.read_parquet(pq)
    assert int((df["ts"].dt.date == bad).sum()) == 100                # exactly what came back
    assert kb.load_state(sp)["partial_days"] == {str(bad): 100}
    assert (df["ts"].dt.date.value_counts() == 375).sum() == len(df["ts"].dt.date.unique()) - 1


def test_before_the_listing_nothing_is_fetched_again(tmp_path):
    k = FakeKite(listed_from=date(2026, 8, 1))
    cfg = _cfg(tmp_path, since=date(2025, 1, 1))
    cfg.since_by_tier = {"index": date(2020, 1, 1)}
    res = kb.run(k, cfg, now=NOW, limiter=kb.RateLimiter(0.0, sleep=lambda s: None), sleep=lambda s: None, log=lambda s: None, tiers_plan=_plan()[:1])
    pq, sp = kb.paths(tmp_path / "bars", "IN", "INDEX:NIFTY 50")
    st = kb.load_state(sp)
    assert st["listed_from_chunk"] is not None and st["first_day"] >= "2026-06-01"
    n = len(k.calls)
    assert n < 12                                                      # it stopped going back once the windows came back empty
    k2 = FakeKite(listed_from=date(2026, 8, 1))
    kb.run(k2, cfg, now=NOW, limiter=kb.RateLimiter(0.0, sleep=lambda s: None), sleep=lambda s: None, log=lambda s: None, tiers_plan=_plan()[:1])
    assert len(k2.calls) == 0


def test_no_token_and_no_holding_in_any_log(tmp_path):
    logs = []
    k = FakeKite(fail=[Boom("429 Too many requests"), None])
    kb.run(k, _cfg(tmp_path), now=NOW, limiter=kb.RateLimiter(0.0, sleep=lambda s: None), sleep=lambda s: None, log=logs.append, data_dir=tmp_path)
    text = "\n".join(logs)
    assert "tier held" in text and TOKEN not in text and HELD not in text
    # the plan was built from the holdings in memory: the held tier took the symbol's token, the symbol itself is only a parquet file name
    assert (tmp_path / "bars" / "IN" / f"{HELD}.parquet").exists()


def test_plan_resolves_holdings_indices_and_constituents(tmp_path):
    (tmp_path / "index_membership").mkdir()
    pd.DataFrame({"symbol": ["OTHER", "GONE", HELD], "to_date": [pd.NaT, pd.Timestamp("2020-01-01"), pd.NaT]}).to_parquet(tmp_path / "index_membership" / "NIFTY500.parquet")
    t = {x["tier"]: x["items"] for x in kb.plan(FakeKite(), tmp_path)}
    assert t["held"] == [(HELD, 11)] and ("INDEX:NIFTY 50", 13) in t["index"] and t["nifty500"] == [("OTHER", 12)]     # a held name is not fetched twice


# --- the store table and the reader ---------------------------------------------------------------------------

@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


def test_migration_100_exists(con):
    assert con.execute("SELECT count(*) FROM bars_1m_history_s79").fetchone()[0] == 0


def test_load_recent_keeps_60_sessions_and_read_merges_table_and_parquet(tmp_path, con):
    _run(FakeKite(), tmp_path, tiers_plan=_plan()[:1])
    root = tmp_path / "bars"
    out = kb.load_recent(con, "IN", 60, root=root, data_dir=tmp_path)
    assert out["files"] == 1
    days = con.execute("SELECT count(DISTINCT CAST(ts AS DATE)) FROM bars_1m WHERE isin='INDEX:NIFTY 50'").fetchone()[0]
    assert days == 60
    before = con.execute("SELECT count(*) FROM bars_1m").fetchone()[0]
    kb.load_recent(con, "IN", 60, root=root, data_dir=tmp_path)
    assert con.execute("SELECT count(*) FROM bars_1m").fetchone()[0] == before            # idempotent
    # read: a span older than the table comes from the parquet, the recent span from both, one row per minute
    old = kb.read("IN", "INDEX:NIFTY 50", date(2026, 6, 1), date(2026, 6, 5), root=root)
    assert len(old) == 5 * 375
    recent = kb.read("IN", "INDEX:NIFTY 50", date(2026, 11, 2), date(2026, 11, 6), root=root, con=con)
    assert len(recent) == 5 * 375 and recent["ts"].is_unique
    assert kb.read("IN", "NOSUCH", date(2026, 6, 1), date(2026, 6, 5), root=root).empty
    assert kb.record_coverage(con, "IN", root, NOW, tmp_path) == 1
    assert con.execute("SELECT n_rows > 0 AND short_days = 0 FROM bars_1m_history_s79").fetchone()[0]


# --- the logged-out question --------------------------------------------------------------------------------------

class Sec:
    def __init__(self, ok=True):
        self.ok = ok

    def has(self, a, b):
        return self.ok


class NoToken:
    def load(self, now):
        return None


class HasToken:
    def load(self, now):
        return "x"


def _ctx(con, now, secrets=None):
    from pflab.service.jobs import Ctx
    return Ctx(con=con, now=now, pm_dir=Path("."), data_root=Path("."), repo=Path("."), secrets=secrets if secrets is not None else Sec())


def _monday():
    from pflab import markets
    return markets.get("IN").next_session(date(2026, 11, 7))


def test_logged_out_question_once_a_day_and_closed_when_a_token_appears(con):
    from pflab.service import tasks_s79_kitelogin as kl
    day = _monday()
    c9 = _ctx(con, datetime.combine(day, time(9, 0)))
    r = kl._kite_token(c9, NoToken())
    assert r["token"] == "missing" and r["asked"] is True
    row = con.execute("SELECT subject_key, text, status FROM questions").fetchone()
    assert row[0] == f"kite_login:{day}" and "Log in to Kite" in row[1] and "tools\\kite_login.py" in row[1] and row[2] == "open"
    t = con.execute("SELECT urgent, default_answer, options_json FROM question_terms_s79").fetchone()
    assert t[0] is True and "without Kite" in t[1]
    assert con.execute("SELECT count(*) FROM outbox WHERE kind='question'").fetchone()[0] == 1       # went out on Telegram with buttons
    again = kl._kite_token(_ctx(con, datetime.combine(day, time(9, 30))), NoToken())
    assert again["asked"] is False and con.execute("SELECT count(*) FROM questions").fetchone()[0] == 1
    nxt = datetime.combine(day + timedelta(days=1), time(9, 0))
    from pflab import markets
    if markets.get("IN").is_session(nxt.date()):
        kl._kite_token(_ctx(con, nxt), NoToken())
        st = dict(con.execute("SELECT subject_key, status FROM questions").fetchall())
        assert st[f"kite_login:{day}"] == "dropped" and st[f"kite_login:{nxt.date()}"] == "open"
    ok = kl._kite_token(_ctx(con, datetime.combine(day, time(10, 0))), HasToken())
    assert ok["token"] == "valid" and ok["closed_questions"] >= 1
    assert con.execute("SELECT count(*) FROM questions WHERE status='open'").fetchone()[0] == 0


def test_no_question_when_kite_is_not_needed_or_not_set_up_or_switched_off(con, monkeypatch):
    from pflab.service import tasks_s79_kitelogin as kl
    sat = datetime(2026, 11, 7, 11, 0)                                       # a Saturday and no Kite job asked for a login
    assert kl._kite_token(_ctx(con, sat), NoToken())["asked"] is False
    day = _monday()
    assert kl._kite_token(_ctx(con, datetime.combine(day, time(6, 30))), NoToken())["asked"] is False           # before 08:00 the phone is not woken
    assert kl._kite_token(_ctx(con, datetime.combine(day, time(9, 0)), Sec(False)), NoToken())["asked"] is False  # no API key: nothing to log in to
    assert con.execute("SELECT count(*) FROM questions").fetchone()[0] == 0
    monkeypatch.setattr(kl, "settings", lambda: {"on": False})
    assert kl._kite_token(_ctx(con, datetime.combine(day, time(9, 0))), NoToken()) == {"off": True}


def test_a_kite_job_that_skipped_for_no_login_makes_a_weekend_question_due(con):
    from pflab.service import tasks_s79_kitelogin as kl
    sat = datetime(2026, 11, 7, 11, 0)
    con.execute("INSERT INTO job_runs (run_id, job, started_at, finished_at, status, detail) VALUES (1, 'bars_1m', ?, ?, 'ok', ?)", [sat - timedelta(hours=2), sat - timedelta(hours=2), '{"skipped": "kite logged out"}'])
    assert kl._kite_token(_ctx(con, sat), NoToken())["asked"] is True


def test_kite_jobs_degrade_to_a_stated_skip_when_logged_out(con):
    from pflab.service import tasks as tk
    from pflab.service.jobs import REGISTRY
    import pflab.service.tasks_s79_bars as tb
    c = _ctx(con, NOW, Sec(False))
    assert tb._bars_1m(c) == {"skipped": "kite logged out"}
    ok, why = REGISTRY["live"].enabled_fn(c)
    assert ok is False and "Kite login" in why
    ok2, why2 = REGISTRY["tradecheck"].enabled_fn(c)
    assert ok2 is False and why2
    assert REGISTRY["kite_token"].schedule.minutes == 30


# --- reseed on the real shape of Kite's holdings -----------------------------------------------------------------

def test_reseed_merges_a_share_held_on_nse_and_bse_and_ignores_zero_lines(con):
    from pflab.paper import reseed
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES ('INE000A01011','isin','equity','EQUITY',TRUE,'AAA','AAA Ltd','s',now())")
    rows = [dict(tradingsymbol="AAA", exchange="NSE", isin="INE000A01011", quantity=10, t1_quantity=2, average_price=100.0, last_price=110.0),
            dict(tradingsymbol="AAA", exchange="BSE", isin="INE000A01011", quantity=5, t1_quantity=0, average_price=106.0, last_price=110.0),
            dict(tradingsymbol="ZERO", exchange="NSE", isin="INE000Z01019", quantity=0, t1_quantity=0, average_price=5.0, last_price=5.0)]
    hs = reseed.normalise(con, rows)
    assert len(hs) == 1 and hs[0]["isin"] == "INE000A01011" and hs[0]["qty"] == 17.0
    assert abs(hs[0]["avg_price"] - (12 * 100.0 + 5 * 106.0) / 17.0) < 1e-9
