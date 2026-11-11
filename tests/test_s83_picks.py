"""S83 L1 and L5: the picks (`core/picks.py`), the withdraw exit, the share rule (`core/pick_share.py`) and its registration. Synthetic data only."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pflab import core
from pflab.core import exits, loop, pick_share, picks, state as st
from pflab.ledger import events as ev
from pflab.ledger import system
from pflab.learner import s83
from pflab.paper import book
from pflab.pm import store

AAA, BBB, CCC, DDD, FFF, GLD = "INE000A01011", "INE000B01012", "INE000C01013", "INE000D01014", "INE000F01016", "INF000G01015"
START = date(2026, 10, 30)
NOW = datetime(2026, 10, 30, 16, 0)
DAYS = [d.date() for d in pd.bdate_range("2025-08-01", "2026-12-31")]
UPTO = [d for d in DAYS if d <= START]
INDEX = pd.Series([1000.0 * 1.0003 ** n for n in range(len(DAYS))], index=pd.bdate_range("2025-08-01", "2026-12-31"))
PROTOCOL = Path(__file__).resolve().parents[1] / "docs" / "protocols" / "s83_picks_live_protocol.md"


def _price(isin: str, k: int) -> float:
    wob = {AAA: 0.03, BBB: 0.004, CCC: 0.006, DDD: 0.006, FFF: 0.004, GLD: 0.002}[isin]
    base = {AAA: 100.0, BBB: 50.0, CCC: 80.0, DDD: 60.0, FFF: 100.0, GLD: 50.0}[isin]
    drift = {AAA: 1.0004, BBB: 1.0004, CCC: 1.0003, DDD: 1.0003, FFF: 1.0006, GLD: 1.0003}[isin]
    return base * drift ** k * (1.0 + (wob if k % 2 else -wob))


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "data"))
    c = store.connect(tmp_path / "l.duckdb")
    for isin, cls, tc, sym, name, sector in ((AAA, "equity", "EQUITY", "AAA", "AAA Ltd", "Tech"), (BBB, "equity", "EQUITY", "BBB", "BBB Ltd", "Banks"), (CCC, "equity", "EQUITY", "CCC", "CCC Ltd", "Pharma"),
                                             (DDD, "equity", "EQUITY", "DDD", "DDD Ltd", "Tech"), (FFF, "equity", "EQUITY", "FFF", "FFF Ltd", "Autos"),
                                             (GLD, "etf", "LISTED_NONEQUITY", "GLDBEES", "Goldbees Gold ETF", None)):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, ?, 'synthetic', now())",
                  [isin, cls, tc, sym, name, sector])
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha')")
    log = ev.EventLog()
    log.append(ev.Event(kind="deposit", account_id="ZER", date=date(2024, 1, 1), amount=2_000_000.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2024, 1, 10), isin=AAA, qty=800, price=80.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2025, 3, 3), isin=BBB, qty=1500, price=40.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2025, 3, 4), isin=GLD, qty=2000, price=50.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2025, 11, 5), isin=FFF, qty=300, price=100.0))          # turns long-term on 2026-11-05: inside the 12-month guard on 2026-10-30
    ev.save(c, log, NOW)
    for k, d in enumerate(DAYS):
        for isin in (AAA, BBB, CCC, DDD, FFF, GLD):
            c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d, _price(isin, k)])
    system.switch(c, tmp_path, UPTO[-6], NOW)
    book.seed(c, UPTO[-6], NOW)
    book.catch_up(c, START, datetime.combine(START, time(21, 0)))
    monkeypatch.setattr(picks, "traded_value_source", lambda c_, m_, i_, s_, d_: (2e9, 60))              # liquid unless a test says otherwise
    return c


TEXT = "A steady compounder with a net cash balance sheet and a widening margin; the next two quarters of results should confirm it."
BRK = "Two quarters of falling margin or a promoter pledge"


def item(sym: str, **kw) -> dict:
    return {"symbol": sym, "thesis": TEXT, "break_condition": BRK, "storylines": [], **kw}


def step(con, day: date, tiny_turnover: float = None, monkeypatch=None) -> dict:
    """One session: the book fills the open orders and is marked, then the close loop runs."""
    now = datetime.combine(day, time(16, 0))
    book.catch_up(con, day, now)
    return loop.run(con, now, None, INDEX)


def small_turnover(monkeypatch, day_cap: float = 0.03):
    real = core.settings

    def patched():
        s = real()
        s["rails"] = {**s["rails"], "turnover_day": day_cap}
        return s
    monkeypatch.setattr(core, "settings", patched)


# --- propose: every refusal says why ----------------------------------------------------------------------------------------------------

def test_refused_picks_say_why_and_a_good_one_is_accepted(con, monkeypatch):
    monkeypatch.setattr(picks, "traded_value_source", lambda c_, m_, i_, s_, d_: (1e7 if s_ == "DDD" else 2e9, 60))
    out = picks.propose(con, NOW, "IN", [item("NOSUCH"), {**item("CCC"), "thesis": "too short"}, item("GLDBEES"), item("DDD")], session_ref="s1")
    why = {r["symbol"]: r["reason"] for r in out["refused"]}
    assert "not a listed share" in why["NOSUCH"]
    assert "thesis" in why["CCC"] and "60" in why["CCC"]
    assert "ETF" in why["GLDBEES"]
    assert "liquidity floor" in why["DDD"] and "crore" in why["DDD"]
    assert out["accepted"] == []
    ok = picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s1")
    assert [a["symbol"] for a in ok["accepted"]] == ["CCC"] and ok["refused"] == []
    row = con.execute("SELECT market, symbol, source, state, session_ref FROM picks_s83 WHERE symbol='CCC'").fetchone()
    assert row == ("IN", "CCC", "system", "proposed", "s1")
    again = picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s2")
    assert "already a pick" in again["refused"][0]["reason"]


def test_a_sector_rail_refuses_a_pick_in_a_full_sector_and_a_thin_record_cannot_pass_the_floor(con, monkeypatch):
    from pflab.paper import rails as hard
    monkeypatch.setattr(hard, "MAX_SECTOR", 0.05)                       # his rail is 25%; Tech (AAA, 28% of the book) is far over 5% too
    out = picks.propose(con, NOW, "IN", [item("DDD")], session_ref="s1")                                   # DDD is also Tech
    assert out["accepted"] == [] and "Tech sector" in out["refused"][0]["reason"] and "rail" in out["refused"][0]["reason"]
    monkeypatch.setattr(picks, "traded_value_source", lambda *a: (2e9, 12))
    out = picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s1")
    assert "cannot be checked" in out["refused"][0]["reason"]


def test_learned_from_is_required_once_five_picks_have_a_score(con):
    assert picks.needs_learned(con, "IN") is False                      # the score agent's table is absent: read defensively
    con.execute("CREATE TABLE IF NOT EXISTS pick_scores_s83 (pick_id BIGINT, horizon_months INTEGER, excess DOUBLE)")
    for i in range(1, 6):
        con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, state, proposed_on) VALUES (?, 'IN', ?, ?, 'system', 'held', ?)", [100 + i, f"X{i}", f"X{i}", START])
        con.execute("INSERT INTO pick_scores_s83 VALUES (?, 1, 0.01)", [100 + i])
    assert picks.needs_learned(con, "IN") is True
    out = picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s9")
    assert out["accepted"] == [] and "scorecard" in out["refused"][0]["reason"]
    out = picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s9", learned_from="Small caps I picked on momentum alone lagged the index at three months, so I now require a margin trend.")
    assert [a["symbol"] for a in out["accepted"]] == ["CCC"]
    assert con.execute("SELECT learned_from FROM picks_s83 WHERE symbol='CCC'").fetchone()[0].startswith("Small caps")


def test_his_kite_stocks_are_adopted_once_and_a_thesis_is_added_to_one(con):
    first = picks.adopt_kite_holdings(con, NOW)
    assert len(first) == 3                                              # AAA, BBB, FFF (the gold ETF is not a stock)
    assert picks.adopt_kite_holdings(con, NOW) == []
    rows = con.execute("SELECT symbol, source, thesis, state FROM picks_s83 ORDER BY symbol").fetchall()
    assert [r[0] for r in rows] == ["AAA", "BBB", "FFF"] and all(r[1] == "kite" and r[2] == picks.KITE_THESIS and r[3] == "held" for r in rows)
    out = picks.propose(con, NOW, "IN", [item("BBB")], session_ref="s1")                                   # held, but a thesis for a Kite stock is allowed
    assert out["accepted"][0]["symbol"] == "BBB" and out["refused"] == []
    r = con.execute("SELECT source, thesis, state FROM picks_s83 WHERE symbol='BBB'").fetchone()
    assert r == ("kite", TEXT, "held") and con.execute("SELECT count(*) FROM picks_s83").fetchone()[0] == 3


# --- sizing and buying ---------------------------------------------------------------------------------------------------------------

def test_an_accepted_pick_is_bought_over_several_sessions_inside_the_turnover_caps_then_held(con, monkeypatch):
    small_turnover(monkeypatch, 0.03)
    picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s1")
    s = st.build(con, START, None, INDEX)
    assert CCC in {r["isin"] for r in s["rows"]} and s["picks"]["weights"][CCC] == pytest.approx(0.10, abs=1e-6)           # sized by risk, at the stock rail
    kite = {AAA, BBB, FFF}
    assert all(s["picks"]["weights"][k] == pytest.approx(next(r["value"] for r in s["rows"] if r["isin"] == k) / s["value"]) for k in kite)   # his stocks keep what they hold
    days = [d for d in DAYS if d >= START][:14]
    seen_states, bought = [], []
    for d in days:
        r = step(con, d)
        if isinstance(r.get("skipped"), str):                                                 # an exchange holiday: the session before it has already been done
            continue
        assert r.get("status") in ("traded", "held"), r
        seen_states.append(con.execute("SELECT state FROM picks_s83 WHERE symbol='CCC'").fetchone()[0])
        for o in r.get("orders", []):
            if o["symbol"] == "CCC":
                bought.append(o["rupees"])
                total = float(con.execute("SELECT value FROM paper_days ORDER BY day DESC LIMIT 1").fetchone()[0])
                assert o["rupees"] <= 0.03 * total * 1.02 + 1.0          # inside the day's turnover cap
    assert len(bought) >= 3, (bought, seen_states)                       # gradual: several sessions
    assert seen_states[0] == "buying" and seen_states[-1] == "held", seen_states
    w = {r["isin"]: r["weight"] for r in book.holdings(con, days[-1])["rows"]}
    assert w[CCC] >= 0.10 - 0.015 - 1e-6
    assert con.execute("SELECT count(*) FROM paper_trades WHERE isin=? AND side='sell'", [CCC]).fetchone()[0] == 0


def test_a_pick_is_never_sold_to_reach_a_share_and_no_new_pick_is_taken_while_it_shrinks(con, monkeypatch):
    small_turnover(monkeypatch, 0.10)
    picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s1")
    for d in [d for d in DAYS if d >= START][:8]:
        step(con, d)
    held = {r["isin"]: r["weight"] for r in book.holdings(con, START + timedelta(days=12))["rows"]}[CCC]
    assert held > 0.05
    con.execute("INSERT INTO sleeve_share_s83 VALUES (1, 'IN', ?, 0.40, 0.20, 'behind the Nifty 500: the share falls', '{}')", [START])      # a shrink to 20%: below what the book holds
    s = st.build(con, START + timedelta(days=12), None, INDEX)
    assert s["picks"]["weights"][CCC] >= held - 1e-9                       # never below what it holds
    r = step(con, [d for d in DAYS if d > START + timedelta(days=12)][0])
    assert not [o for o in r.get("orders", []) if o["symbol"] == "CCC" and o["side"] == "sell"]
    out = picks.propose(con, NOW, "IN", [item("DDD")], session_ref="s2")
    assert out["accepted"] == [] and "no new picks until the next judgment" in out["refused"][0]["reason"]


# --- withdraw ------------------------------------------------------------------------------------------------------------------------

def test_a_withdrawn_pick_inside_the_twelve_month_guard_waits_and_goes_when_the_guard_lets_go(con):
    picks.adopt_kite_holdings(con, NOW)
    exits.backfill_plans(con, START, "IN", NOW)
    r = picks.withdraw(con, NOW, "IN", "FFF", "the results no longer support the margin story I wrote", "s2")
    assert r["ok"] and r["held"] and "12-month tax guard" in r["will"]
    orders = exits.check_close(con, START, None, None, now=NOW)
    assert not [o for o in orders if o["isin"] == FFF]                    # its oldest lot turns long-term on 2026-11-05 and is in gain: it waits
    g = con.execute("SELECT kind, status, reason FROM exit_events_s81 WHERE isin=? AND status='guarded'", [FFF]).fetchone()
    assert g[0] == "withdraw" and "12-month guard" in g[2]
    later = date(2026, 11, 6)
    orders = exits.check_close(con, later, None, None, now=datetime.combine(later, time(15, 45)))
    w = [o for o in orders if o["isin"] == FFF]
    assert len(w) == 1 and w[0]["kind"] == "withdraw" and w[0]["side"] == "sell" and "Withdrawn pick" in w[0]["reason"]
    assert "withdraw" in exits.KINDS


def test_a_stop_fires_for_a_withdrawn_pick_even_inside_the_guard(con):
    picks.adopt_kite_holdings(con, NOW)
    exits.backfill_plans(con, START, "IN", NOW)
    picks.withdraw(con, NOW, "IN", "FFF", "the results no longer support the margin story I wrote", "s2")
    px = book.close_on(con, FFF, START)[1]
    con.execute("UPDATE exit_plans_s81 SET stop=? WHERE isin=? AND status='open'", [px * 1.5, FFF])
    orders = exits.check_close(con, START, None, None, now=NOW)
    o = [x for x in orders if x["isin"] == FFF]
    assert len(o) == 1 and o[0]["kind"] == "stop"                         # the stop is not weighed against the guard, and the withdrawal does not sell the name twice


def test_a_withdrawn_pick_that_was_never_bought_is_just_dropped(con):
    picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s1")
    r = picks.withdraw(con, NOW, "IN", "CCC", "I no longer believe the margin trend I wrote about", "s2")
    assert r["ok"] and not r["held"]
    assert [p["symbol"] for p in picks.active(con, "IN") if p["source"] == "system"] == []
    assert not picks.withdraw(con, NOW, "IN", "CCC", "I no longer believe the margin trend I wrote about", "s2")["ok"]
    assert not picks.withdraw(con, NOW, "IN", "CCC", "short", "s2")["ok"]


def test_a_skipped_idea_is_a_price_record_only(con):
    assert picks.skip_idea(con, NOW, "IN", "DDD", "The margin story is real but the price already reflects it", "s1")["ok"]
    assert con.execute("SELECT market, symbol, isin FROM skips_s83").fetchall() == [("IN", "DDD", DDD)]
    assert not picks.skip_idea(con, NOW, "IN", "NOSUCH", "A name nobody lists", "s1")["ok"]
    assert con.execute("SELECT count(*) FROM picks_s83").fetchone()[0] == 0 and con.execute("SELECT count(*) FROM paper_orders").fetchone()[0] == 0


# --- the share rule ------------------------------------------------------------------------------------------------------------------

def _bought_pick(con):
    con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, state, proposed_on) VALUES (1, 'IN', ?, 'CCC', 'system', 'held', ?)", [CCC, START])


def rec(sessions=60, pts=3.0):
    return lambda con_, m_, d_: {"sessions": sessions, "sleeve_return_after_tax": 0.05, "index_return": 0.03, "points_a_year": pts, "worst_fall_sleeve": -0.1, "worst_fall_index": -0.08}


def test_the_share_rule_moves_up_and_down_five_points_and_never_sells(con):
    assert pick_share.share(con, "IN")["share"] == pytest.approx(0.40)
    _bought_pick(con)
    before = con.execute("SELECT count(*) FROM paper_orders").fetchone()[0]
    assert pick_share.judge(con, NOW, "IN", START, rec(30))["judged"] is False                     # under 60 sessions: no judgment
    j = pick_share.judge(con, NOW, "IN", START, rec(60, +3.0))
    assert j["judged"] and j["result"] == "ahead" and pick_share.share(con, "IN")["share"] == pytest.approx(0.45)
    assert pick_share.judge(con, NOW, "IN", START, rec(60, +3.0))["judged"] is False               # idempotent: not due again
    assert pick_share.judge(con, NOW, "IN", START, rec(119, -5.0))["judged"] is False               # 60 further sessions are needed
    j = pick_share.judge(con, NOW, "IN", START + timedelta(days=90), rec(120, -2.5))
    assert j["result"] == "behind" and pick_share.share(con, "IN")["share"] == pytest.approx(0.40)
    assert pick_share.share(con, "IN")["shrinking"] is True
    j = pick_share.judge(con, NOW, "IN", START + timedelta(days=180), rec(180, -1.5))               # behind by less than 2 points: level
    assert j["result"] == "level" and pick_share.share(con, "IN")["share"] == pytest.approx(0.40) and pick_share.share(con, "IN")["shrinking"] is False
    assert con.execute("SELECT count(*) FROM sleeve_share_s83 WHERE market='IN'").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM paper_orders").fetchone()[0] == before                  # a share never trades
    assert json.loads(con.execute("SELECT figures_json FROM sleeve_share_s83 ORDER BY change_id LIMIT 1").fetchone()[0])["points_a_year"] == 3.0


def test_the_share_stays_inside_its_bounds_and_waits_for_a_system_pick(con):
    assert "no pick of the system" in pick_share.judge(con, NOW, "IN", START, rec(60, 3.0))["why"]
    _bought_pick(con)
    for i in range(6):
        pick_share.judge(con, NOW, "IN", START + timedelta(days=i), rec(60 * (i + 1), +9.0))
    assert pick_share.share(con, "IN")["share"] == pytest.approx(0.60)                                # at most 60%
    for i in range(6, 14):
        pick_share.judge(con, NOW, "IN", START + timedelta(days=i), rec(60 * (i + 1), -9.0))
    assert pick_share.share(con, "IN")["share"] == pytest.approx(0.20)                                # at least 20%
    assert pick_share.judge(con, NOW, "IN", START, lambda *a: (_ for _ in ()).throw(RuntimeError("no record")))["judged"] is False
    assert pick_share.judge(con, NOW, "US", START, rec(60, 3.0))["judged"] is False                   # US is off by default


def test_the_report_line_tells_a_move_in_plain_words(con):
    _bought_pick(con)
    assert pick_share.report_line(con, START) is None
    pick_share.judge(con, NOW, "IN", START, rec(60, 3.0))
    line = pick_share.report_line(con, START)
    assert "India picks share raised from 40% to 45%" in line and "ahead of the Nifty 500" in line
    assert pick_share.report_line(con, START + timedelta(days=1)) is None


def test_the_us_share_starts_at_half_and_moves_in_the_same_steps(con, monkeypatch):
    real = pick_share.settings
    monkeypatch.setattr(pick_share, "settings", lambda m=None: ({**real(m), "on": True} if m else real(m)))
    con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, state, proposed_on) VALUES (2, 'US', 'ZZ0000000001', 'AAPL', 'system', 'held', ?)", [START])
    assert pick_share.share(con, "US")["share"] == pytest.approx(0.50)
    assert pick_share.judge(con, NOW, "US", START, rec(60, 4.0))["new"] == pytest.approx(0.55)
    for i in range(1, 6):
        pick_share.judge(con, NOW, "US", START + timedelta(days=i), rec(60 * (i + 1), 4.0))
    assert pick_share.share(con, "US")["share"] == pytest.approx(0.70)                                # at most 70%: SPY keeps 30%
    for i in range(6, 16):
        pick_share.judge(con, NOW, "US", START + timedelta(days=i), rec(60 * (i + 1), -4.0))
    assert pick_share.share(con, "US")["share"] == pytest.approx(0.30)


def test_the_rules_numbers_are_the_protocols_text_and_the_configs():
    text = PROTOCOL.read_text(encoding="utf-8")
    block = json.loads(re.findall(r"```json rule\n(.*?)\n```", text, re.S)[0])
    for m in ("IN", "US"):
        for k in ("start_share", "min_share", "max_share", "step"):
            assert block[m][k] == pick_share.RULE[m][k], (m, k)
    assert block["US"]["spy_floor"] == pick_share.RULE["US"]["spy_floor"] == pick_share.settings("US")["us_spy_floor"]
    assert block["judge_every_sessions"] == pick_share.RULE["judge_every_sessions"] == pick_share.settings("IN")["judge_every_sessions"]
    assert block["min_sessions_of_record"] == pick_share.RULE["min_sessions_of_record"]
    assert block["window_sessions"] == pick_share.RULE["window_sessions"] == pick_share.settings("IN")["window_sessions"]
    assert block["behind_points_a_year"] == pick_share.RULE["behind_points_a_year"] == pick_share.settings("IN")["behind_points"]
    assert block["min_system_picks_bought"] == pick_share.RULE["min_system_picks_bought"]
    for m in ("IN", "US"):                                                                   # the config file and the code defaults say what the protocol says
        c = pick_share.settings(m)
        assert (c["start_share"], c["min_share"], c["max_share"], c["step"]) == tuple(pick_share.RULE[m][k] for k in ("start_share", "min_share", "max_share", "step"))
        d = core.DEFAULTS["picks"]["in" if m == "IN" else "us"]
        assert (d["start_share"], d["min_share"], d["max_share"], d["step"]) == (c["start_share"], c["min_share"], c["max_share"], c["step"])
    assert pick_share.settings("IN")["on"] is True and pick_share.settings("US")["on"] is False
    assert pick_share.settings("IN")["min_liquidity_inr"] == 50_000_000 and pick_share.settings("US")["us_max_stocks"] == 12


def test_registration_counts_the_two_tests_once_and_catches_a_changed_protocol(con, tmp_path, monkeypatch):
    n0 = con.execute("SELECT count(*) FROM learn_tests").fetchone()[0]
    assert not s83.protocol_ok(con)["registered"]
    assert s83.register_picks_live(con, NOW) == ["s83:picks_live:IN", "s83:picks_live:US"]
    assert s83.register_picks_live(con, NOW) == []
    assert con.execute("SELECT count(*) FROM learn_tests").fetchone()[0] == n0 + 2
    rows = con.execute("SELECT origin, template, params_json FROM learn_tests WHERE note LIKE 's83:picks_live:%' ORDER BY note").fetchall()
    assert [r[1] for r in rows] == ["picks_live_s83:IN", "picks_live_s83:US"] and all(r[0] == "study" for r in rows)
    assert json.loads(rows[0][2])["protocol_sha256"] == s83.protocol_sha()
    assert s83.protocol_ok(con)["unchanged"]
    copy = tmp_path / "protocol.md"
    copy.write_bytes(PROTOCOL.read_bytes() + b"\nan edit\n")
    monkeypatch.setattr(s83, "PROTOCOL", copy)
    assert not s83.protocol_ok(con)["unchanged"]


# --- the US rails --------------------------------------------------------------------------------------------------------------------

def _us_on(monkeypatch):
    real = pick_share.settings
    monkeypatch.setattr(pick_share, "settings", lambda m=None: ({**real(m), "on": True} if m == "US" else real(m)))


def _bars(tmp_path, sym, price, volume, n=80):
    d = tmp_path / "data" / "us" / "raw"
    d.mkdir(parents=True, exist_ok=True)
    days = [x.date() for x in pd.bdate_range(end="2026-10-29", periods=n)]
    pd.DataFrame({"date": days, "open": price, "high": price, "low": price, "close": price, "adj_close": price, "volume": volume, "dividend": 0.0}).to_parquet(d / f"{sym}.parquet")


def test_us_picks_obey_the_floor_the_stock_count_and_the_spy_floor(con, monkeypatch, tmp_path):
    _us_on(monkeypatch)
    _bars(tmp_path, "GOOD", 50.0, 500_000)
    _bars(tmp_path, "PENNY", 3.0, 5_000_000)
    _bars(tmp_path, "THIN", 40.0, 10_000)
    _bars(tmp_path, "SPY", 500.0, 5_000_000)
    out = picks.propose(con, NOW, "US", [item("NOBARS"), item("SPY"), item("PENNY"), item("THIN"), item("GOOD")], session_ref="u1")
    why = {r["symbol"]: r["reason"] for r in out["refused"]}
    assert "no stored daily bars" in why["NOBARS"] and "a fund" in why["SPY"] and "USD 5" in why["PENNY"] and "USD 2,000,000" in why["THIN"]
    assert [a["symbol"] for a in out["accepted"]] == ["GOOD"]
    assert con.execute("SELECT isin, source, state FROM picks_s83 WHERE symbol='GOOD'").fetchone()[1:] == ("system", "proposed")
    for i in range(11):                                                   # 12 stocks in all
        con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, state, proposed_on) VALUES (?, 'US', ?, ?, 'system', 'held', ?)", [50 + i, f"US:S{i}", f"S{i}", START])
    _bars(tmp_path, "MORE", 50.0, 500_000)
    out = picks.propose(con, NOW, "US", [item("MORE")], session_ref="u2")
    assert "at most 12" in out["refused"][0]["reason"]


def test_us_sizing_never_takes_spy_under_thirty_percent(con, monkeypatch):
    _us_on(monkeypatch)
    for i in range(12):
        con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, state, proposed_on) VALUES (?, 'US', ?, ?, 'system', 'proposed', ?)", [50 + i, f"US:S{i}", f"S{i}", START])
    con.execute("INSERT INTO sleeve_share_s83 VALUES (1, 'US', ?, 0.65, 0.70, 'ahead of SPY', '{}')", [START])
    rows = [{"isin": f"US:S{i}", "symbol": f"S{i}", "value": 0.0, "price": 50.0, "buyable": True, "sector": None, "asset_class": "equity", "qty": 0.0} for i in range(12)]
    rows.append({"isin": "US:SPY", "symbol": "SPY", "value": 500.0, "price": 500.0, "buyable": True, "sector": None, "asset_class": "etf", "qty": 1.0})
    state = {"value": 1000.0, "rows": rows, "vol": {f"US:S{i}": 0.25 + 0.01 * i for i in range(12)}, "gauge": {"fired": False}, "cfg": core.settings()}
    w = picks.target_weights(con, state, "US")
    assert len(w) == 12 and sum(w.values()) <= 0.70 + 1e-9 and max(w.values()) <= 0.10 + 1e-9
    con.execute("UPDATE sleeve_share_s83 SET new_share=0.95")             # even a share set too high cannot take SPY under its floor
    assert sum(picks.target_weights(con, state, "US").values()) <= 0.70 + 1e-9
    pk = con.execute("SELECT count(*) FROM picks_s83 WHERE market='US'").fetchone()[0]
    assert pk == 12
