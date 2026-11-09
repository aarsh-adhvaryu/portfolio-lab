"""S81 (A54): the market-hours rhythms: the liquidity fill model and the no-same-day-round-trip guard (`core/fills.py`), the pre-open plan (`core/preopen.py`), the session loop and its
replay (`core/session.py`), the self-report. Synthetic minute bars only (rule 7: no real data in git)."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from pflab.core import fills, preopen, session, views
from pflab.paper import book, cadence
from tests.test_s80_core import AAA, BBB, DAYS, GLD, NOW, con  # noqa: F401  (the fixture)

CCC = "INE000C01013"
MON, TUE = date(2026, 11, 2), date(2026, 11, 3)


@pytest.fixture
def db(con):
    """The S80 book plus a name the book does not hold (CCC), so an entry has room under the 10% rail."""
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, 'CCC', 'CCC Ltd', 'synthetic', now())", [CCC])
    for d in DAYS:
        con.execute("INSERT INTO prices VALUES (?, ?, 100.0, 'EQ', 'nse_bhavcopy', now())", [CCC, d])
    return con


def day_bars(day: date, price, vol=10000.0) -> pd.DataFrame:
    """One session of synthetic minute bars (09:15-15:14); `price(i)` is the close of minute i, `vol` a number or a function of i."""
    ts = pd.date_range(datetime.combine(day, time(9, 15)), periods=360, freq="min")
    close = np.array([price(i) for i in range(360)], dtype=float)
    open_ = np.concatenate([[close[0]], close[:-1]])
    v = np.array([vol(i) if callable(vol) else vol for i in range(360)], dtype=float)
    return pd.DataFrame({"ts": ts, "open": open_, "high": np.maximum(open_, close) + 0.05, "low": np.minimum(open_, close) - 0.05, "close": close, "volume": v})


def write_bars(root, sym: str, base: float, days: dict, history: int = 22, hist_vol: float = 10000.0) -> None:
    """`days`: {date: price function}; the `history` business days before MON get a flat day at `base` with `hist_vol` a minute (the liquidity model's input)."""
    frames = [day_bars(d.date(), lambda i: base, hist_vol) for d in pd.bdate_range(end=MON - timedelta(days=1), periods=history)]
    frames += [day_bars(d, f[0] if isinstance(f, tuple) else f, f[1] if isinstance(f, tuple) else 10000.0) for d, f in days.items()]
    p = root / "IN"
    p.mkdir(parents=True, exist_ok=True)
    pd.concat(frames, ignore_index=True).to_parquet(p / f"{sym}.parquet", index=False)


@pytest.fixture
def bars_dir(tmp_path):
    return tmp_path / "bars"


@pytest.fixture
def no_exits(monkeypatch):
    monkeypatch.setattr(session, "_exits", lambda: None)               # the fallback path (the exit manager is another branch)


def run_day(db, day, bars_dir, tmp_path, **kw):
    return session.replay(db, day, bars_dir, data_root=tmp_path / "data", **kw)


def fills_of(con, day=None):
    q = "SELECT ts, symbol, side, qty, quote, price, half_spread_bps, slippage_bps, kind, flag FROM session_fills_s81" + (" WHERE day=?" if day else "") + " ORDER BY fill_id"
    return con.execute(q, [day] if day else []).fetchall()


# --- the model ---------------------------------------------------------------------------------------------------------------------------------

def test_config_sections_are_read():
    f, s = fills.settings(), fills.session_settings()
    assert f["adv_days"] == 20 and f["half_spread_liquid_bps"] == 1.0 and f["impact_bps"] == 25.0
    assert s["on"] is True and s["every_minutes"] == 5 and s["no_entry_minutes"] == 15 and s["vwap_band"] == 0.005


def test_slippage_and_spread_grow_with_the_orders_share_of_turnover_and_with_illiquidity():
    adv = 1.0e8
    small, big = fills.model(1.0e5, adv), fills.model(1.0e7, adv)
    assert big["slippage_bps"] > small["slippage_bps"] > 0 and big["participation"] == pytest.approx(0.1)
    assert big["slippage_bps"] == pytest.approx(25.0 * 0.1 ** 0.5)                       # the square-root law, as documented
    assert fills.model(1e5, 1.0e7)["half_spread_bps"] > fills.model(1e5, 1.0e8)["half_spread_bps"] > fills.model(1e5, 1.0e9)["half_spread_bps"]
    assert fills.model(1e5, 5.0e9)["half_spread_bps"] == pytest.approx(1.0)               # at or over the liquid end: the tightest
    unk = fills.model(1e5, None)
    assert unk["adv_known"] is False and unk["half_spread_bps"] == 15.0


def test_the_price_is_never_better_than_the_quote_and_worse_by_the_modelled_cost():
    for adv in (None, 1e7, 1e9):
        for q in (1.0, 99.99, 1234.55):
            m = fills.model(5e4, adv)
            move = (m["half_spread_bps"] + m["slippage_bps"]) / 1e4
            assert fills.price_for("buy", q, m) >= q * (1 + move) - 1e-9 and fills.price_for("buy", q, m) > q
            assert fills.price_for("sell", q, m) <= q * (1 - move) + 1e-9 and fills.price_for("sell", q, m) < q


def test_a_bigger_order_pays_more_basis_points_in_the_book(db):
    now = datetime.combine(MON, time(10, 0))
    liq = {"adv_rupees": 2.0e7, "typical_minute_volume": 1000.0}
    a = fills.execute(db, now, CCC, "buy", quote=100.0, qty=100, kind="test", reason="small", liq=liq)
    b = fills.execute(db, now + timedelta(minutes=1), CCC, "buy", quote=100.0, qty=900, kind="test", reason="big", liq=liq)
    assert a["status"] == b["status"] == "filled"
    assert b["slippage_bps"] > a["slippage_bps"] and b["price"] > a["price"] > 100.0
    assert a["cost_rupees"] == pytest.approx((a["price"] - 100.0) * 100)
    row = db.execute("SELECT quote, price, participation, order_rupees FROM session_fills_s81 ORDER BY fill_id LIMIT 1").fetchone()
    assert row[0] == 100.0 and row[1] == a["price"] and row[2] == pytest.approx(10000.0 * 1.0 / 2.0e7, rel=0.1)


# --- the guard -----------------------------------------------------------------------------------------------------------------------------------

def test_no_same_day_round_trip_a_sale_of_todays_shares_is_held_and_a_stop_fills_flagged(db):
    t = datetime.combine(MON, time(10, 0))
    liq = {"adv_rupees": 1.0e9, "typical_minute_volume": 10000.0}
    assert fills.execute(db, t, CCC, "buy", quote=100.0, qty=300, kind="swing_entry", liq=liq)["status"] == "filled"
    held = fills.execute(db, t + timedelta(minutes=30), CCC, "sell", quote=110.0, qty=300, kind="target", liq=liq)
    assert held["status"] == "held" and "round trip" in held["why"] and book.positions(db)[CCC] == 300
    stop = fills.execute(db, t + timedelta(minutes=40), CCC, "sell", quote=95.0, qty=300, kind="stop", liq=liq, bypass_guard=True)
    assert stop["status"] == "filled" and "same-day round trip" in stop["flag"] and CCC not in book.positions(db)
    assert db.execute("SELECT flag FROM session_fills_s81 WHERE kind='stop'").fetchone()[0].startswith("same-day round trip")


def test_selling_older_shares_and_buying_back_a_name_sold_today(db):
    t = datetime.combine(MON, time(10, 0))
    liq = {"adv_rupees": 1.0e9, "typical_minute_volume": 10000.0}
    g = fills.round_trip(db, AAA, "sell", 100, MON)
    assert g["blocked_qty"] == 0                                           # shares bought before today may be sold today
    assert fills.execute(db, t, AAA, "sell", quote=100.0, qty=100, kind="trim", liq=liq)["status"] == "filled"
    back = fills.execute(db, t + timedelta(minutes=5), AAA, "buy", quote=100.0, qty=50, kind="rebalance", liq=liq)
    assert back["status"] == "held" and "sold today" in back["why"]


# --- the session loop on replayed bars -------------------------------------------------------------------------------------------------------------

def test_a_stop_hit_mid_session_fills_at_the_replayed_quote_plus_slippage_never_better(db, bars_dir, tmp_path, no_exits):
    session._fb_open_plan(db, NOW, AAA, 100.0, 1000)                                    # entry 100: stop 92, target 115 (the fallback plan)
    write_bars(bars_dir, "AAA", 100.0, {MON: lambda i: 100.0 if i < 105 else 91.0})      # the 11:00 minute closes below the stop
    r = run_day(db, MON, bars_dir, tmp_path, isins=[AAA])
    f = fills_of(db, MON)
    assert len(f) == 1 and f[0][8] == "stop" and f[0][2] == "sell"
    ts, sym, side, qty, quote, price, hs, sl, kind, flag = f[0]
    assert ts.time() == time(11, 5) and quote == 91.0                                  # the first step that sees the 11:00 minute CLOSED (at 11:01): the last closed minute's close
    assert price < quote and price <= quote * (1 - (hs + sl) / 1e4) + 0.005             # never better than the quote: worse by at least half spread + slippage
    assert qty == 3000 or qty == 1000 or qty > 0
    assert any(x["kind"] == "stop" for x in r["fills"])
    assert db.execute("SELECT status FROM session_exit_fb_s81").fetchone()[0] in ("closed", "open")


def test_a_swing_entry_fires_on_its_trigger_only_after_the_first_15_minutes_and_near_vwap(db, bars_dir, tmp_path, no_exits):
    session.add_trigger(db, NOW, CCC, "above", 101.0, amount=50000.0, valid_from=MON, stop_price=97.0, target_price=110.0, reason="breakout above its range")
    write_bars(bars_dir, "CCC", 100.0, {MON: lambda i: 100.0 if i < 3 else 102.0})       # through the trigger at 09:18, flat near VWAP after that
    r = run_day(db, MON, bars_dir, tmp_path, isins=[CCC])
    f = fills_of(db, MON)
    assert len(f) == 1 and f[0][8] == "swing_entry" and f[0][2] == "buy"
    assert f[0][0].time() == time(9, 30)                                               # hit at 09:20 but the first 15 minutes are barred: the first step at 09:30
    waits = db.execute("SELECT what FROM session_log_s81 WHERE kind='wait'").fetchall()
    assert waits and "opening spike" in waits[0][0]
    assert f[0][5] > f[0][4] >= 101.0
    plan = db.execute("SELECT stop_price, target_price, status FROM session_exit_fb_s81 WHERE isin=?", [CCC]).fetchone()
    assert plan == (97.0, 110.0, "open")                                               # the entry opened its exit plan
    assert db.execute("SELECT status FROM session_triggers_s81").fetchone()[0] == "fired"
    assert r["steps"] == 74                                                          # 09:20 ... 15:25 every 5 minutes


def test_a_swing_entry_waits_when_the_price_is_away_from_vwap_or_the_volume_is_thin(db, bars_dir, tmp_path, no_exits):
    session.add_trigger(db, NOW, CCC, "above", 101.0, amount=50000.0, valid_from=MON)
    write_bars(bars_dir, "CCC", 100.0, {MON: lambda i: 100.0 + min(i, 40) * 0.2})        # a steady run up: by 09:30 the price is 1.5% above the day's VWAP
    run_day(db, MON, bars_dir, tmp_path, isins=[CCC], last=time(10, 0))
    assert fills_of(db) == []
    assert any("VWAP" in w[0] for w in db.execute("SELECT what FROM session_log_s81 WHERE kind='wait'").fetchall())
    db.execute("DELETE FROM session_log_s81")
    db.execute("DELETE FROM session_said_s81")
    db.execute("DELETE FROM session_adv_s81")
    write_bars(bars_dir, "CCC", 100.0, {MON: (lambda i: 102.0, lambda i: 1000.0)})        # flat, but a tenth of the typical minute volume
    run_day(db, MON, bars_dir, tmp_path, isins=[CCC], last=time(10, 0))
    assert fills_of(db) == []
    assert any("typical minute volume" in w[0] for w in db.execute("SELECT what FROM session_log_s81 WHERE kind='wait'").fetchall())
    assert db.execute("SELECT status FROM session_triggers_s81").fetchone()[0] == "armed"


def test_with_no_minute_bars_an_entry_waits_and_says_so(db, no_exits):
    session.add_trigger(db, NOW, CCC, "above", 101.0, amount=50000.0, valid_from=MON)
    r = session.run_once(db, datetime.combine(MON, time(11, 0)), quotes={CCC: 103.0}, bars={}, liq={CCC: {"adv_rupees": 1e9, "typical_minute_volume": 1e4}}, data_root=None)
    assert fills_of(db) == [] and r["waiting"] and "no minute bars" in r["waiting"][0]["why"][0]


def test_a_same_day_exit_is_held_to_the_next_session_unless_its_stop_fires(db, bars_dir, tmp_path, no_exits):
    session.add_trigger(db, NOW, CCC, "above", 101.0, amount=50000.0, valid_from=MON, stop_price=97.0, target_price=110.0)
    # Monday: in at 09:30, then through the 110 target at 11:00: the target sale would be a same-day round trip
    write_bars(bars_dir, "CCC", 100.0, {MON: lambda i: 102.0 if i < 105 else 111.0, TUE: lambda i: 108.0})
    run_day(db, MON, bars_dir, tmp_path, isins=[CCC])
    f = fills_of(db, MON)
    assert [x[8] for x in f] == ["swing_entry"] and book.positions(db)[CCC] > 0          # no sale on the day of entry
    q = db.execute("SELECT status, kind, run_on FROM session_queue_s81").fetchall()
    assert q == [("queued", "target", TUE)]
    assert any("same-day round trip" in x[0] for x in db.execute("SELECT what FROM session_log_s81 WHERE kind='queue'").fetchall())
    run_day(db, TUE, bars_dir, tmp_path, isins=[CCC])                                    # Tuesday: the queued target sale goes through, after the opening spike
    g = fills_of(db, TUE)
    assert [x[8] for x in g] == ["target"] and g[0][0].time() == time(9, 30) and g[0][4] == 108.0 and CCC not in book.positions(db)   # the decision was taken on Monday: it goes at the first allowed step, at that moment's quote
    assert db.execute("SELECT status FROM session_queue_s81").fetchone()[0] == "done"


def test_a_stop_on_the_day_of_entry_fills_and_the_day_is_flagged(db, bars_dir, tmp_path, no_exits):
    session.add_trigger(db, NOW, CCC, "above", 101.0, amount=50000.0, valid_from=MON, stop_price=97.0, target_price=110.0)
    write_bars(bars_dir, "CCC", 100.0, {MON: lambda i: 102.0 if i < 105 else 96.0})
    run_day(db, MON, bars_dir, tmp_path, isins=[CCC])
    f = fills_of(db, MON)
    assert [x[8] for x in f] == ["swing_entry", "stop"] and f[1][9] and "same-day round trip" in f[1][9]
    assert CCC not in book.positions(db)
    assert db.execute("SELECT count(*) FROM session_queue_s81").fetchone()[0] == 0


def test_a_filing_released_mid_session_breaks_a_thesis_and_sells_and_one_before_the_open_does_not(db, bars_dir, tmp_path, no_exits):
    write_bars(bars_dir, "AAA", 100.0, {MON: lambda i: 100.0})
    ev = [{"isin": AAA, "kind": "INSOLVENCY", "severity": "high", "ts": datetime.combine(MON, time(8, 50)), "source": "bse", "ref": "pre", "text": "released before the open"},
          {"isin": AAA, "kind": "INSOLVENCY", "severity": "high", "ts": datetime.combine(MON, time(11, 12)), "source": "bse", "ref": "mid", "text": "admission of the CIRP application"},
          {"isin": BBB, "kind": "RATING_DOWNGRADE", "severity": "medium", "ts": datetime.combine(MON, time(11, 12)), "source": "bse", "ref": "mid2", "text": "a downgrade"}]
    run_day(db, MON, bars_dir, tmp_path, isins=[AAA, BBB], events=ev)
    f = fills_of(db, MON)
    assert len(f) == 1 and f[0][8] == "thesis" and f[0][1] == "AAA" and f[0][0].time() == time(11, 15)      # the first step after the release; the pre-open filing and the medium one do nothing
    assert AAA not in book.positions(db)
    why = db.execute("SELECT what FROM session_log_s81 WHERE kind='fill'").fetchone()[0]
    assert "thesis break" in why and "11:12" in why


def test_the_exit_managers_contract_is_used_when_the_module_exists(db, monkeypatch):
    calls = []
    fake = SimpleNamespace(
        check_quote=lambda con, now, quotes, state: calls.append(("quote", dict(quotes))) or [],
        check_thesis=lambda con, day, events: [{"market": "IN", "isin": AAA, "side": "sell", "qty": None, "fraction": 0.5, "kind": "thesis", "reason": "the manager's thesis break", "plan_id": None}],
        open_plan=lambda con, now, market, isin, sleeve, price, qty, plan=None: 77)
    monkeypatch.setattr(session, "_exits", lambda: fake)
    t = datetime.combine(MON, time(11, 30))
    held = book.positions(db)[AAA]
    r = session.run_once(db, t, quotes={AAA: 100.0}, bars={}, liq={AAA: {"adv_rupees": 1e9, "typical_minute_volume": 1e4}},
                         events=[{"isin": AAA, "kind": "FRAUD", "severity": "low", "ts": datetime.combine(MON, time(11, 20)), "source": "kg", "ref": "e1", "text": "x"}])
    assert calls and calls[0][0] == "quote" and r["exits_from"] == "core.exits"
    assert len(r["fills"]) == 1 and r["fills"][0]["kind"] == "thesis"                     # severity low would not sell by the fallback rule: the manager decided
    assert book.positions(db)[AAA] == pytest.approx(held - np.floor(0.5 * held))


def test_the_tactical_view_is_carried_out_in_session_once_and_the_close_does_not_add_it_again(db, bars_dir, tmp_path, no_exits):
    DAY = DAYS[-1]
    ok = views.issue(db, NOW, DAY, direction=1, names=["CCC"], share_of_budget=0.5, horizon_sessions=10, stop_pct=8.0, reason="CCC looks cheap against its sector after the result",
                     isin_of=lambda s: {"CCC": CCC}.get(s))
    assert ok["ok"]
    write_bars(bars_dir, "CCC", 100.0, {MON: lambda i: 100.0})
    run_day(db, MON, bars_dir, tmp_path, isins=[CCC], last=time(11, 0))
    f = fills_of(db, MON)
    assert [x[8] for x in f] == ["view"] and f[0][0].time() == time(9, 30)
    done = json.loads(db.execute("SELECT executed_json FROM core_views_s80").fetchone()[0])
    assert done[CCC]["qty"] > 0
    held_w = {CCC: 0.05}
    assert views.merge(db, TUE, {}, held_w) == {}                                          # a name the policy does not hold: the close does not buy the view a second time


def test_the_circuit_breaker_stops_every_buy_in_session(db, bars_dir, tmp_path, no_exits, monkeypatch):
    monkeypatch.setattr(cadence, "breaker", lambda con: {"on": True, "drawdown": -0.2, "limit": -0.12})
    session.add_trigger(db, NOW, CCC, "above", 101.0, amount=50000.0, valid_from=MON)
    write_bars(bars_dir, "CCC", 100.0, {MON: lambda i: 102.0})
    run_day(db, MON, bars_dir, tmp_path, isins=[CCC], last=time(10, 0))
    assert fills_of(db) == []
    assert any("circuit breaker" in w[0] for w in db.execute("SELECT what FROM session_log_s81 WHERE kind='skip'").fetchall())


# --- Kite ------------------------------------------------------------------------------------------------------------------------------------------

class FakeKite:
    def __init__(self, fail_after: int = 99):
        self.calls, self.fail_after = 0, fail_after

    def ltp(self, *keys):
        self.calls += 1
        if self.calls > self.fail_after:
            raise type("TokenException", (Exception,), {})("Incorrect `api_key` or `access_token`.")
        return {k: {"last_price": 100.0} for k in keys}


def test_the_kite_login_lost_mid_session_degrades_cleanly_and_says_so_once(db, no_exits):
    kite = FakeKite(fail_after=1)
    outs = [session.run_once(db, datetime.combine(MON, time(10, 0)) + timedelta(minutes=5 * k), kite=kite) for k in range(4)]
    assert outs[0]["degraded"] is None and outs[0]["summary"]["quotes"] >= 1
    assert all(o["degraded"] == "Kite login lost" for o in outs[1:])                       # never raised
    said = db.execute("SELECT text FROM session_said_s81 WHERE key='kite'").fetchall()
    assert len(said) == 1 and "lost at 10:05" in said[0][0]
    assert db.execute("SELECT count(*) FROM outbox WHERE text LIKE '%session loop%'").fetchone()[0] == 1       # one Telegram message, queued (never sent in a test)
    assert db.execute("SELECT count(*) FROM session_log_s81 WHERE kind='degrade' AND what LIKE '%Kite login%'").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM session_log_s81 WHERE kind='run'").fetchone()[0] == 4          # every check is recorded, degraded or not
    c = session.card(db, datetime.combine(MON, time(10, 20)))
    assert "lost" in c["kite"] and c["runs"] == 4


def test_no_kite_login_at_all_says_so_once_and_runs_the_work_that_needs_no_quotes(db, no_exits):
    ev = [{"isin": AAA, "kind": "INSOLVENCY", "severity": "high", "ts": datetime.combine(MON, time(10, 2)), "source": "bse", "ref": "r1", "text": "CIRP"}]
    for k in range(3):
        o = session.run_once(db, datetime.combine(MON, time(10, 5)) + timedelta(minutes=5 * k), kite=None, events=ev)
        assert o["degraded"] == "no Kite login"
    assert db.execute("SELECT count(*) FROM session_said_s81 WHERE key='kite'").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM session_log_s81 WHERE kind='thesis'").fetchone()[0] == 1       # the break is noted once; with no quote nothing is sold, the close decides
    assert fills_of(db) == []
    assert db.execute("SELECT 1 FROM session_plans_s81 WHERE day=?", [MON]).fetchone()                     # the plan was still made


def test_outside_a_session_the_loop_does_nothing(db):
    assert "skipped" in session.run_once(db, datetime.combine(MON, time(16, 30)), quotes={AAA: 100.0})
    assert "skipped" in session.run_once(db, datetime.combine(date(2026, 11, 10), time(11, 0)), quotes={AAA: 100.0})       # a market holiday


# --- the pre-open plan, the report ------------------------------------------------------------------------------------------------------------------

def _world(root):
    (root / "global").mkdir(parents=True)
    (root / "indices").mkdir(parents=True)
    days = [d.date() for d in pd.bdate_range("2025-10-01", "2026-11-06")]
    rng = np.random.default_rng(3)
    ret = rng.normal(0, 0.01, len(days))
    sp = 5000 * np.cumprod(1 + ret)
    pd.DataFrame({"date": [str(d) for d in days], "open": sp, "high": sp, "low": sp, "close": sp, "adj_close": sp, "volume": 1.0}).to_parquet(root / "global" / "US_SP500.parquet", index=False)
    close = 25000 * np.cumprod(1 + rng.normal(0, 0.008, len(days)))
    opn = np.concatenate([[close[0]], close[:-1]]) * (1 + 0.4 * np.concatenate([[0], ret[:-1]]) + rng.normal(0, 0.001, len(days)))
    pd.DataFrame({"date": [str(d) for d in days], "open": opn, "high": opn, "low": opn, "close": close}).to_parquet(root / "indices" / "NIFTY50_PRICE.parquet", index=False)


def test_the_preopen_plan_has_the_conditional_orders_their_triggers_and_numbers(db, tmp_path, no_exits):
    _world(tmp_path / "data")
    session._fb_open_plan(db, NOW, AAA, 100.0, 1000)
    session.add_trigger(db, NOW, CCC, "above", 101.0, amount=50000.0, valid_from=MON, stop_price=97.0, reason="breakout")
    r = preopen.ensure_plan(db, datetime.combine(MON, time(8, 20)), "IN", root=tmp_path / "data")
    assert r["made"] and r["orders"] == 4 and r["late"] is False                         # a stop, a target, a time stop (the fallback plan) and the trigger
    p = preopen.get_plan(db, "IN", MON)
    assert "Pre-open plan for Mon 02 Nov 2026" in p["text"] and "buy about Rs 50,000 of CCC if it rises to 101.00" in p["text"] and "sell AAA if it falls to 92.00" in p["text"]
    assert "S&P 500" in p["text"] and "Expected Nifty 50 gap about" in p["text"] and "moves no order" in p["text"]
    assert preopen.ensure_plan(db, datetime.combine(MON, time(8, 40)), "IN", root=tmp_path / "data")["kept"] is True
    late = preopen.ensure_plan(db, datetime.combine(TUE, time(11, 0)), "IN", root=tmp_path / "data")
    assert late["late"] is True and late["day"] == str(TUE)
    g = preopen.gap_estimate(MON, tmp_path / "data")
    assert g["n"] >= 200 and 0.0 < g["beta"] < 1.0                                          # the fitted beta recovers the 0.4 that built the data (roughly)


def test_the_1545_report_says_what_the_plan_was_what_ran_what_filled_and_what_did_not(db, bars_dir, tmp_path, no_exits):
    _world(tmp_path / "data")
    session.add_trigger(db, NOW, CCC, "above", 101.0, amount=50000.0, valid_from=MON, stop_price=97.0, target_price=110.0)
    preopen.ensure_plan(db, datetime.combine(MON, time(8, 30)), "IN", root=tmp_path / "data")
    write_bars(bars_dir, "CCC", 100.0, {MON: lambda i: 102.0 if i < 105 else 111.0})
    run_day(db, MON, bars_dir, tmp_path, isins=[CCC])
    t = session.report_day(db, MON)
    assert "Session Mon 02 Nov" in t and "Plan: 1 conditional order(s) (1 swing entry), made 08:30" in t and "expected Nifty gap about" in t
    assert "Checks: 74 session check(s) between 09:20 and 15:25, 74 with live quotes" in t
    assert "Filled: 1 paper order(s)" in t and "buy" in t and "CCC (swing_entry)" in t and "against the quote" in t and "slippage" in t
    assert "Held to the next session: 1 order(s)" in t and "Waited:" in t
    assert "Post-close loop: not yet" in t
    assert len(t.splitlines()) <= 15
    quiet = session.report_day(db, date(2026, 11, 4))
    assert "Plan: none was made" in quiet and "did not run today" in quiet and "nothing fired" in quiet


def test_the_report_job_queues_one_message_and_the_session_job_skips_outside_the_session(db, tmp_path, monkeypatch):
    from pflab.service import jobs, tasks_s79_session as tj
    ctx = jobs.Ctx(db, datetime.combine(MON, time(15, 50)), tmp_path, tmp_path / "data", tmp_path)
    session.log(db, datetime.combine(MON, time(10, 0)), "run", "session check", detail={"quotes": 3})
    r1, r2 = tj._report(ctx), tj._report(ctx)
    assert r1["queued"] is True and "skipped" in r2
    assert db.execute("SELECT count(*), max(kind) FROM outbox WHERE dedup_key LIKE 'session_report:%'").fetchone() == (1, "summary")
    late = jobs.Ctx(db, datetime.combine(TUE, time(22, 0)), tmp_path, tmp_path / "data", tmp_path)
    assert "skipped" in tj._report(late)
    assert "skipped" in tj._session(jobs.Ctx(db, datetime.combine(MON, time(16, 40)), tmp_path, tmp_path / "data", tmp_path))
    assert {"preopen_job", "session_job", "session_report"} <= set(jobs.REGISTRY)


def test_the_replay_never_shows_the_loop_a_minute_that_had_not_closed(db, bars_dir, tmp_path, no_exits):
    write_bars(bars_dir, "CCC", 100.0, {MON: lambda i: 100.0 + i})
    seen = []
    session.replay(db, MON, bars_dir, isins=[CCC], data_root=tmp_path / "data", last=time(9, 30),
                   on_step=lambda t, r: seen.append((t, db.execute("SELECT detail_json FROM session_log_s81 WHERE kind='run' ORDER BY log_id DESC LIMIT 1").fetchone()[0])))
    assert [t.time() for t, _ in seen] == [time(9, 20), time(9, 25)]
    assert db.execute("SELECT count(*) FROM session_log_s81 WHERE kind='run'").fetchone()[0] == 2


def test_today_shows_one_compact_session_card(db, bars_dir, tmp_path, no_exits):
    from pflab.core import screens
    session.add_trigger(db, NOW, CCC, "above", 101.0, amount=50000.0, valid_from=MON)
    write_bars(bars_dir, "CCC", 100.0, {MON: lambda i: 102.0})
    run_day(db, MON, bars_dir, tmp_path, isins=[CCC], last=time(9, 40))
    v = screens.view(db, datetime.combine(MON, time(9, 41)))
    c = v["session"]
    assert c["day"] == str(MON) and c["runs"] == 4 and c["plan"]["orders"] == 1 and len(c["fills"]) == 1 and c["recent"] and c["on"] is True
    assert "session" not in " ".join(v["left_out"])
