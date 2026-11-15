"""S91: five-minute candles. Exchange-local times, a forming candle flagged, gaps kept (never filled), duplicates collapsed, an expired login / a refusal / a flaky network each a stated state
that never blanks what is stored, a weekend request, a late reopening, the job, and the Stock endpoint. A fake Kite only (AAAA); real bars are checked in the live drill."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pflab.app import runtime, server
from pflab.ingest import intraday5 as i5
from pflab.pm import store

FRI, MON = date(2026, 11, 13), date(2026, 11, 16)
ISIN = "ISIN_A"


def rows_for(day: date, upto: int = 75, skip=(), tz: bool = True):
    out = []
    for k in range(upto):
        if k in skip:
            continue
        t = datetime.combine(day, time(9, 15)) + timedelta(minutes=5 * k)
        t = pd.Timestamp(t).tz_localize("Asia/Kolkata") if tz else t
        p = 100 + k * 0.1
        out.append({"date": t.to_pydatetime(), "open": p, "high": p + 0.5, "low": p - 0.5, "close": p + 0.2, "volume": 1000 + k})
    return out


class FakeKite:
    def __init__(self, days=(FRI,), fail=None, skip=()):
        self.days, self.fail, self.skip, self.calls = days, list(fail or []), skip, []

    def instruments(self, ex):
        return [{"tradingsymbol": "AAAA", "instrument_token": 111, "segment": "NSE"}]

    def historical_data(self, token, frm, to, interval):
        self.calls.append((token, frm, to, interval))
        if self.fail:
            raise self.fail.pop(0)
        out = []
        for d in self.days:
            if frm.date() <= d <= to.date():
                upto = 75 if datetime.combine(d, time(15, 30)) <= self.until else max(0, int((self.until - datetime.combine(d, time(9, 15))).total_seconds() // 300) + 1)
                out += rows_for(d, upto, self.skip)
        return out

    until = datetime(2099, 1, 1)


class TokenException(Exception):
    pass


class PermissionException(Exception):
    pass


class NetworkException(Exception):
    pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    pm, data = tmp_path / "pm", tmp_path / "data"
    (data / "indices").mkdir(parents=True)
    monkeypatch.setenv("PFLAB_DATA_DIR", str(data))
    monkeypatch.setenv("PFLAB_PM_DIR", str(pm))
    i5._LAST.clear(); i5._BUSY.clear(); i5._TOK.update(at=0.0, eq={})
    rt = runtime.Runtime(pm, data, tmp_path, con=store.connect(tmp_path / "l.duckdb"), clock=lambda: datetime(2026, 11, 15, 12, 0))
    return rt, rt.cursor()


def test_frame_is_exchange_local_on_the_grid_inside_the_window_without_duplicates():
    rows = rows_for(FRI, 75) + rows_for(FRI, 3)                                           # duplicates
    rows.append({"date": pd.Timestamp("2026-11-13 08:00", tz="Asia/Kolkata").to_pydatetime(), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1})      # before the open
    rows.append({"date": pd.Timestamp("2026-11-13 15:30", tz="Asia/Kolkata").to_pydatetime(), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1})      # at the close
    utc = [{**r, "date": pd.Timestamp(r["date"]).tz_convert("UTC").to_pydatetime()} for r in rows_for(FRI, 2)]                                                 # UTC stamps are converted to IST
    f = i5.frame_of(rows)
    assert len(f) == 75 and f["ts"].iloc[0] == pd.Timestamp("2026-11-13 09:15") and f["ts"].iloc[-1] == pd.Timestamp("2026-11-13 15:25")
    assert i5.frame_of(utc)["ts"].iloc[0] == pd.Timestamp("2026-11-13 09:15")


def test_a_weekend_request_serves_friday_whole_and_asks_kite_once(env):
    rt, con = env
    now = datetime(2026, 11, 15, 12, 0)                                                   # Sunday
    k = FakeKite(days=(date(2026, 11, 11), date(2026, 11, 12), FRI))
    r = i5.refresh(rt, con, ISIN, "AAAA", now, kite=k)
    assert r["state"] == "ok" and r["rows"] == 225 and k.calls and k.calls[0][3] == "5minute"
    c = i5.candles(con, ISIN, now)
    assert c["sessions"][-1] == "2026-11-13" and c["latest_closed"] == "2026-11-13 15:25" and not any(b["partial"] for b in c["bars"]) and c["gaps"] == 0
    n = len(k.calls)
    again = i5.refresh(rt, con, ISIN, "AAAA", now, kite=k, force=True)                    # Friday is stored whole and the market is shut: nothing to ask
    assert again["state"] in ("fresh", "ok") and (again["state"] == "fresh") == (len(k.calls) == n)


def test_the_forming_candle_is_flagged_and_never_the_latest_closed(env):
    rt, con = env
    now = datetime(2026, 11, 16, 9, 22)
    k = FakeKite(days=(MON,)); k.until = now
    i5.refresh(rt, con, ISIN, "AAAA", now, kite=k)
    c = i5.candles(con, ISIN, now)
    by = {b["t"]: b for b in c["bars"] if b["d"] == "2026-11-16"}
    assert by["09:15"]["partial"] is False and by["09:20"]["partial"] is True and c["latest_closed"] == "2026-11-16 09:15"
    assert by["09:15"]["slot"] == 0 and by["09:20"]["slot"] == 1


def test_reopening_late_fetches_the_completed_bars_in_one_request(env):
    rt, con = env
    now = datetime(2026, 11, 16, 11, 7)
    k = FakeKite(days=(FRI, MON)); k.until = now
    r = i5.refresh(rt, con, ISIN, "AAAA", now, kite=k)
    assert r["state"] == "ok" and len(k.calls) == 1                                        # one request per name brings the sessions
    c = i5.candles(con, ISIN, now)
    mon = [b for b in c["bars"] if b["d"] == "2026-11-16"]
    assert mon[-1]["t"] == "11:05" and mon[-1]["partial"] is True and mon[-2]["partial"] is False and c["latest_closed"] == "2026-11-16 11:00"


def test_a_missing_candle_stays_a_gap_and_is_counted(env):
    rt, con = env
    now = datetime(2026, 11, 15, 12, 0)
    k = FakeKite(days=(date(2026, 11, 11), date(2026, 11, 12), FRI), skip=(10, 11, 12))
    i5.refresh(rt, con, ISIN, "AAAA", now, kite=k)
    c = i5.candles(con, ISIN, now)
    slots = {b["slot"] for b in c["bars"]}
    assert {10, 11, 12}.isdisjoint(slots) and c["gaps"] == 9 and len(c["bars"]) == 216            # nothing was invented to fill them


def test_duplicates_collapse_across_refreshes(env):
    rt, con = env
    now = datetime(2026, 11, 15, 12, 0)
    k = FakeKite()
    i5.refresh(rt, con, ISIN, "AAAA", now, kite=k, force=True)
    i5.refresh(rt, con, ISIN, "AAAA", now, kite=k, force=True)
    assert con.execute("SELECT count(*) FROM bars_5m_s91 WHERE isin=?", [ISIN]).fetchone()[0] == 75


def test_an_expired_login_a_refusal_and_a_flaky_network_are_states_that_keep_what_is_stored(env):
    rt, con = env
    now = datetime(2026, 11, 15, 12, 0)
    i5.refresh(rt, con, ISIN, "AAAA", now, kite=FakeKite(), force=True)
    before = con.execute("SELECT count(*) FROM bars_5m_s91").fetchone()[0]
    r = i5.refresh(rt, con, ISIN, "AAAA", now, kite=FakeKite(fail=[TokenException("Incorrect `api_key` or `access_token`")]), force=True)
    assert r["state"] == "needs_login" and "log in" in r["why"]
    r = i5.refresh(rt, con, ISIN, "AAAA", now, kite=FakeKite(fail=[PermissionException("Insufficient permission for that call")]), force=True)
    assert r["state"] == "refused" and "plan" in r["why"]
    r = i5.refresh(rt, con, ISIN, "AAAA", now, kite=FakeKite(fail=[NetworkException("timed out")] * 5), force=True, sleep=lambda s: None)
    assert r["state"] == "network"
    ok = FakeKite(fail=[NetworkException("timed out"), NetworkException("502 bad gateway")])
    r = i5.refresh(rt, con, ISIN, "AAAA", now, kite=ok, force=True, sleep=lambda s: None)       # intermittent: two failures, then it works
    assert r["state"] == "ok" and len(ok.calls) == 3
    assert con.execute("SELECT count(*) FROM bars_5m_s91").fetchone()[0] == before                 # nothing stored was blanked
    assert i5.refresh(rt, con, ISIN, "ZZZZ", now, kite=FakeKite(), force=True)["state"] == "unknown_name"


def test_no_kite_login_means_a_stated_wait_and_the_throttle_holds(env, monkeypatch):
    rt, con = env
    now = datetime(2026, 11, 16, 10, 0)
    monkeypatch.setattr(i5, "_client", lambda rt_, now_: None)
    r = i5.refresh(rt, con, ISIN, "AAAA", now)
    assert r["state"] == "needs_login"
    k = FakeKite(days=(MON,)); k.until = now
    i5.refresh(rt, con, ISIN, "AAAA", now, kite=k, force=True)
    n = len(k.calls)
    assert i5.refresh(rt, con, ISIN, "AAAA", now, kite=k)["state"] == "fresh" and len(k.calls) == n    # asked again within the minute: no second request


def test_minute_bars_fill_in_a_session_that_has_no_five_minute_candles(env):
    rt, con = env
    now = datetime(2026, 11, 15, 12, 0)
    for k in range(75 * 5):
        t = datetime.combine(FRI, time(9, 15)) + timedelta(minutes=k)
        con.execute("INSERT INTO bars_1m VALUES ('IN', ?, ?, 10, 11, 9, 10.5, 100)", [ISIN, t])
    c = i5.candles(con, ISIN, now)
    assert len(c["bars"]) == 75 and {b["src"] for b in c["bars"]} == {"built from minute bars"} and c["bars"][0]["v"] == 500


def test_the_job_refreshes_held_names_and_says_why_when_kite_is_out(env):
    from pflab.service import tasks_s91_candles as job
    rt, con = env
    from pflab.app import s89
    s89.ensure(con)
    con.execute("INSERT INTO mine_in_s89 VALUES ('AAAA', ?, 'NSE', 10, 100, 110, 0, now())", [ISIN])
    ctx = SimpleNamespace(con=con, now=datetime(2026, 11, 15, 12, 0), secrets=None, settings=None)
    assert "kite logged out" in job._run(ctx)["skipped"]
    out = job._run(ctx, kite=FakeKite(), sleep=lambda s: None)
    assert out["names"] == 1 and out["states"] == {"ok": 1} and out["latest_closed"] == "2026-11-13 15:25"
    assert job.names(con) == {ISIN: "AAAA"}


def test_the_stock_endpoint_serves_five_minute_candles_with_their_freshness(env, monkeypatch):
    rt, con = env
    c = TestClient(server.create_app(rt))
    idx = pd.bdate_range("2025-06-02", periods=300)
    daily = pd.DataFrame({"date": pd.to_datetime(idx), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0})
    monkeypatch.setattr("pflab.agents.tradecheck.isin_of", lambda con_, s: ISIN if s == "AAAA" else None)
    monkeypatch.setattr("pflab.quant.candles.daily", lambda root, isin, end, bars=120: daily)
    monkeypatch.setattr(i5, "refresh_async", lambda *a, **k: None)
    monkeypatch.setattr(rt, "clock", lambda: datetime(2026, 11, 15, 12, 0))
    e = c.get("/api/stock/AAAA?tf=5min").json()
    assert e["tf"] == "5min" and "Kite login" in e["empty"] or "five-minute" in e["empty"]                    # nothing stored yet: a plain reason, not an empty chart
    i5.refresh(rt, con, ISIN, "AAAA", datetime(2026, 11, 15, 12, 0), kite=FakeKite(), force=True)
    j = c.get("/api/stock/AAAA?tf=5min").json()
    assert j["tf"] == "5min" and len(j["bars"]) == 75 and j["forecast"] is None and j["intraday"]["latest_closed"] == "2026-11-13 15:25" and j["bars"][0]["t"] == "09:15"
    assert c.get("/api/stock/AAAA").json()["tf"] == "day" and c.get("/api/stock/AAAA?tf=week").json()["tf"] == "week"
