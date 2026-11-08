"""S80 phase 1: the v2 core (`pflab/core`): the baseline policy, the rails around it, and the close loop that places the paper orders. Synthetic data only."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab import core
from pflab.core import loop, policy, rails, state as st
from pflab.ledger import events as ev
from pflab.ledger import system
from pflab.paper import allocation, book
from pflab.pm import store

AAA, BBB, GLD = "INE000A01011", "INE000B01012", "INF000G01015"
NOW = datetime(2026, 10, 30, 16, 0)
DAYS = [d.date() for d in pd.bdate_range("2025-08-01", "2026-10-30")]


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    c = store.connect(tmp_path / "l.duckdb")
    for isin, cls, tc, sym, name in ((AAA, "equity", "EQUITY", "AAA", "AAA Ltd"), (BBB, "equity", "EQUITY", "BBB", "BBB Ltd"), (GLD, "etf", "LISTED_NONEQUITY", "GLDBEES", "Goldbees Gold ETF")):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, 'synthetic', now())",
                  [isin, cls, tc, sym, name])
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha')")
    log = ev.EventLog()
    log.append(ev.Event(kind="deposit", account_id="ZER", date=date(2024, 1, 1), amount=2_000_000.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2024, 1, 10), isin=AAA, qty=3000, price=80.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2025, 3, 3), isin=BBB, qty=3000, price=40.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2025, 3, 4), isin=GLD, qty=2000, price=50.0))
    ev.save(c, log, NOW)
    for k, d in enumerate(DAYS):
        wob = 1.0 + (0.03 if k % 2 else -0.03)                      # AAA is the jumpy one (about 3% a day), BBB is calm
        for isin, px in ((AAA, 100.0 * 1.0004 ** k * wob), (BBB, 50.0 * 1.0004 ** k * (1.0 + (0.004 if k % 2 else -0.004))), (GLD, 50.0 * 1.0003 ** k * (1.0 + (0.002 if k % 2 else -0.002)))):
            c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d, px])
    system.switch(c, tmp_path, DAYS[-6], NOW)
    book.seed(c, DAYS[-6], NOW)
    book.catch_up(c, DAYS[-1], datetime.combine(DAYS[-1], datetime.min.time()) + timedelta(hours=21))
    return c


def calm_index(drop: float = 0.0) -> pd.Series:
    idx = pd.bdate_range("2025-08-01", "2026-10-30")
    lvl = [1000.0 * 1.0003 ** n for n in range(len(idx))]
    lvl[-1] = max(lvl) * (1 - drop)                                  # the last close is `drop` below the high
    return pd.Series(lvl, index=idx)


def test_settings_read_the_file_and_defaults():
    s = core.settings()
    assert s["core"]["on"] is True and s["rails"]["turnover_day"] == 0.10 and s["baseline"]["band_pts"] == 1.5
    assert core.missions_retired() is True


def test_risk_weights_split_by_inverse_risk_and_caps_stay_in_cash():
    w = policy.risk_weights(0.60, {"a": 1 / 0.40, "b": 1 / 0.20}, {"a": 0.10, "b": 0.10})
    assert w == {"a": pytest.approx(0.10), "b": pytest.approx(0.10)}          # both capped: the other 40% is NOT handed on
    w = policy.risk_weights(0.18, {"a": 1 / 0.40, "b": 1 / 0.20}, {"a": 0.10, "b": 0.10})
    assert w["b"] == pytest.approx(0.10) and w["a"] == pytest.approx(0.08)      # b hits its cap; a takes what is left of the budget, itself under its cap
    assert sum(w.values()) <= 0.18 + 1e-9
    w = policy.risk_weights(0.12, {"a": 1.0, "b": 2.0}, {"a": 0.5, "b": 0.5})
    assert w["b"] == pytest.approx(2 * w["a"]) and sum(w.values()) == pytest.approx(0.12)


def test_without_a_target_the_baseline_holds_the_class_mix_and_favours_the_calmer_name(con):
    s = st.build(con, DAYS[-1], None, calm_index())
    assert s["target"] is None and s["gauge"]["fired"] is False
    d = policy.decide(s)
    eq_now = sum(r["weight"] for r in s["rows"] if r["klass"] == "equity")
    assert sum(d["weights"][i] for i in (AAA, BBB) if i in d["weights"]) <= eq_now + 1e-9
    assert d["weights"][BBB] >= d["weights"][AAA]                              # BBB is the less volatile of the two
    assert s["vol"][AAA] > s["vol"][BBB]


def test_fall_gauge_cuts_equity_and_keeps_the_difference_in_cash(con):
    t = allocation.propose_allocation(con, {"equity": 12, "gold": 20, "international": 0, "cash": 68}, "x" * 60, NOW)   # a budget under the caps, so the cut shows
    allocation.review_target(con, t["target_id"], "approve", "ok", NOW)
    calm = policy.decide(st.build(con, DAYS[-1], None, calm_index()))
    s = st.build(con, DAYS[-1], None, calm_index(drop=0.15))
    assert s["gauge"]["fired"] is True
    cut = policy.decide(s)
    assert sum(cut["weights"][i] for i in (AAA, BBB)) < sum(calm["weights"][i] for i in (AAA, BBB)) - 1e-6
    assert cut["weights"][GLD] == pytest.approx(calm["weights"][GLD])           # gold is untouched


def test_rails_cap_a_company_at_ten_percent_and_never_borrow(con):
    s = st.build(con, DAYS[-1], None, calm_index())
    chk = rails.clip_weights(s, {AAA: 0.50, BBB: 0.50, GLD: 0.0})
    for i in (AAA, BBB):
        cur = next(r["weight"] for r in s["rows"] if r["isin"] == i)
        assert chk[i]["target"] <= max(0.10, cur) + 1e-9
    assert any("capped" in w for w in chk[AAA]["why"] + chk[BBB]["why"])


def test_circuit_breaker_blocks_buying_but_not_selling(con):
    s = st.build(con, DAYS[-1], None, calm_index())
    s["breaker"] = {"on": True, "drawdown": -0.2, "limit": -0.12}
    cur = {r["isin"]: r["weight"] for r in s["rows"]}
    out = rails.clip_weights(s, {AAA: cur[AAA] + 0.05, BBB: cur[BBB] - 0.05, GLD: cur[GLD]})
    assert out[AAA]["target"] == pytest.approx(cur[AAA]) and out[AAA]["why"]      # (AAA is already over its company rail here, so the rail speaks first: still no buy)
    s["rows"] = [dict(r, value=r["value"] * (0.02 / r["weight"] if r["isin"] == GLD else 1.0), weight=0.02 if r["isin"] == GLD else r["weight"]) for r in s["rows"]]
    small = rails.clip_weights(s, {GLD: 0.04})
    assert small[GLD]["target"] == pytest.approx(0.02) and "circuit breaker: no buying" in small[GLD]["why"]
    assert out[BBB]["target"] == pytest.approx(cur[BBB] - 0.05)


def test_band_minimum_and_turnover_cap_shape_the_orders(con):
    s = st.build(con, DAYS[-1], None, calm_index())
    cur = {r["isin"]: r["weight"] for r in s["rows"]}
    inband = rails.check(con, s, {"weights": {AAA: cur[AAA] + 0.005, BBB: cur[BBB], GLD: cur[GLD]}})
    assert inband["orders"] == [] and any("within the band" in x["why"] for x in inband["skipped"])
    s["cfg"]["rails"]["max_cost_share"] = 1.0                                   # keep the cost filter out of this check
    big = rails.check(con, s, {"weights": {AAA: 0.0, BBB: 0.0, GLD: 0.0}})
    cap = 0.10 * s["value"]
    assert sum(o["value"] for o in big["orders"]) <= cap + 1.0
    assert all(o["side"] == "sell" for o in big["orders"]) and big["orders"]


def test_the_loop_places_orders_records_decisions_and_runs_a_session_once(con):
    s = st.build(con, DAYS[-1], None, calm_index())
    r = loop.run(con, NOW, None, calm_index())
    assert r.get("status") in ("traded", "held"), r
    row = con.execute("SELECT policy_id, status FROM core_runs_s80 WHERE day=?", [DAYS[-1]]).fetchone()
    assert row == (policy.POLICY_ID, r["status"])
    n_orders = con.execute("SELECT count(*) FROM paper_orders WHERE status='open'").fetchone()[0]
    assert n_orders == len(r["orders"])
    if r["orders"]:
        d = con.execute("SELECT status, case_id, reason FROM paper_decisions ORDER BY decision_id DESC LIMIT 1").fetchone()
        assert d[0] == "executed" and d[1] is None and d[2].startswith(policy.POLICY_ID)
        assert con.execute("SELECT count(*) FROM paper_claims").fetchone()[0] >= 4          # the 7/28/84/182-day claims are registered
    assert loop.run(con, NOW, None, calm_index()) == {"skipped": f"session {DAYS[-1]} already done"}
    assert con.execute("SELECT count(*) FROM paper_acts WHERE loop='core_loop'").fetchone()[0] == 1
    assert s["value"] > 0


def test_the_loop_waits_while_orders_are_open_and_when_off(con, monkeypatch):
    book.place(con, NOW, None, AAA, "buy", amount=10000.0)
    assert "waiting" in loop.run(con, NOW, None, calm_index())
    monkeypatch.setattr(core, "settings", lambda: {"core": {"on": False, "retire_missions": True}, "rails": {}, "baseline": {}})
    assert loop.run(con, NOW, None, calm_index()) == {"off": True}


def test_a_silent_close_loop_is_found_only_while_it_is_on(con, monkeypatch):
    from pflab.paper import cadence
    late = datetime(2026, 11, 4, 12, 0)
    assert any(s.startswith("core_loop") for s in cadence.silent_loops(con, late))
    real = core.settings
    monkeypatch.setattr(core, "settings", lambda: {**real(), "core": {"on": False, "retire_missions": False}})
    assert not any(s.startswith("core_loop") for s in cadence.silent_loops(con, late))


def test_an_active_allocation_target_is_what_the_baseline_holds(con):
    t = allocation.propose_allocation(con, {"equity": 20, "gold": 20, "international": 0, "cash": 60}, "x" * 60, NOW)
    allocation.review_target(con, t["target_id"], "approve", "ok", NOW)
    s = st.build(con, DAYS[-1], None, calm_index())
    assert s["target"]["id"] == t["target_id"]
    d = policy.decide(s)
    assert sum(d["weights"][i] for i in (AAA, BBB)) <= 0.20 + 1e-9
    assert d["weights"][GLD] <= 0.20 + 1e-9


# --- the book card and the advisor layers (phase 1, items 4 and 5) -------------------------------------------------------------------------

def test_the_book_card_has_the_same_sections_every_close_and_stays_under_six_thousand_tokens(con):
    from pflab.core import card
    r = loop.run(con, NOW, None, calm_index())
    assert r["card_tokens"] and 100 < r["card_tokens"] < 6000
    text = card.latest(con)
    heads = [ln.split(":")[0] for ln in text.splitlines() if ln[:1].isupper()]
    assert heads[:1] == ["BOOK CARD, close of 2026-10-30 (written by code; the same layout every day)".split(":")[0]] or text.startswith("BOOK CARD, close of 2026-10-30")
    for h in ("BOOK:", "ALLOCATION TARGET:", "RISK:", "FORECAST:", "STORYLINES:", "POLICIES:", "LAST 10 DECISIONS", "CHANGED SINCE THE LAST CARD:"):
        assert h in text
    assert "baseline_v1" in text and "AAA" in text and "none yet" in text.split("STORYLINES:")[1].splitlines()[0]
    assert "first card" in text                                                  # no earlier card to compare with


def test_the_next_card_says_what_changed_and_a_rerun_replaces_the_day(con):
    from pflab.core import card
    s = st.build(con, DAYS[-1], None, calm_index())
    d = policy.decide(s)
    card.write(con, NOW, s, d, [])
    n = con.execute("SELECT count(*) FROM core_cards_s80").fetchone()[0]
    card.write(con, NOW, s, d, [])
    assert con.execute("SELECT count(*) FROM core_cards_s80").fetchone()[0] == n          # one row a day
    # a later close compared with this one
    con.execute("UPDATE core_cards_s80 SET day = ?", [DAYS[-2]])
    s2 = st.build(con, DAYS[-1], None, calm_index(drop=0.15))                            # the gauge now fires
    card.write(con, NOW, s2, policy.decide(s2), [{"symbol": "AAA"}])
    t = card.latest(con)
    assert "fall gauge FIRED" in t and "orders placed at this close: 1" in t


# --- a promoted lab policy in the live loop (phase 2) --------------------------------------------------------------------------------------------

CHAMPION_CODE = '''
def decide(state, forecasts, sims, storylines, params=None):
    return {k: params.get("w", 0.05) for k in state["universe"]}
'''


def _live_data(con):
    rows = con.execute("SELECT isin, date, close FROM prices").fetchall()
    df = pd.DataFrame(rows, columns=["isin", "date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    px = df.pivot_table(index="date", columns="isin", values="close", aggfunc="last").sort_index()
    px = px.rename(columns={GLD: "ETF:GLDBEES"})
    to = px * 0 + 5e8
    meta = {k: {"symbol": "GLDBEES" if k.startswith("ETF:") else k, "etf": k.startswith("ETF:"), "sector": None, "tax": "EQUITY"} for k in px.columns}
    return {"px": px, "turnover": to, "meta": meta, "index": px[AAA], "bench": px[AAA]}


def _make_champion(con, code=CHAMPION_CODE, params='{"w": 0.05}'):
    con.execute("INSERT INTO core_policies_s80 (policy_id, status, code_hash, created_at, promoted_at, code, params_json) VALUES ('lab_champ', 'champion', 'h', ?, ?, ?, ?)", [NOW, NOW, code, params])
    con.execute("INSERT INTO core_policies_s80 (policy_id, status, code_hash, created_at, code) VALUES ('baseline_v1', 'previous', 'x', ?, NULL)", [NOW])


def test_a_promoted_lab_policy_decides_the_close_and_goes_through_the_same_rails(con):
    _make_champion(con)
    r = loop.run(con, NOW, None, calm_index(), live_data=_live_data(con))
    assert r["status"] == "traded", r
    row = con.execute("SELECT policy_id FROM core_runs_s80 WHERE day=?", [DAYS[-1]]).fetchone()
    assert row[0] == "lab_champ"
    why = con.execute("SELECT reason FROM paper_decisions ORDER BY decision_id DESC LIMIT 1").fetchone()[0]
    assert why.startswith("lab_champ:") and "champion policy" in why
    for o in con.execute("SELECT symbol, side, amount, qty FROM paper_orders").fetchall():
        assert o[1] in ("buy", "sell")


def test_a_champion_that_fails_falls_back_to_the_baseline_for_that_close(con):
    _make_champion(con, "def decide(state, forecasts, sims, storylines, params=None):\n    return {}['x']\n")
    r = loop.run(con, NOW, None, calm_index(), live_data=_live_data(con))
    assert r.get("status") in ("traded", "held")
    assert con.execute("SELECT policy_id FROM core_runs_s80 WHERE day=?", [DAYS[-1]]).fetchone()[0] == "baseline_v1"
    assert con.execute("SELECT count(*) FROM paper_acts WHERE loop='core_loop' AND what LIKE '%the baseline decides this close%'").fetchone()[0] == 1
