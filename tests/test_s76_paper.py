"""S76: the paper portfolio the system runs by itself. Synthetic record: the start copies his lots without FDs or the US sleeve, decisions are sized by code and
held to the rails, only what the review approves is executed at the close, tax by FIFO lots, money in and out on the same days, claims scored, the gate to his
real money, and the loop that opens the team's work by itself."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab.agents import analyst as an
from pflab.hq import missions
from pflab.paper import book, manager, rails
from pflab.pm import store
from tests.test_s68_autonomy import CFG, rt  # noqa: F401  (the fixture)

AAA, BBB, ETF, USX = "INE000A01011", "INE000B01012", "INF000E01013", "ZZ0000320193"
DAYS = [date(2026, 10, 26) + timedelta(days=k) for k in range(0, 80) if (date(2026, 10, 26) + timedelta(days=k)).weekday() < 5]


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "p.duckdb")
    for isin, cls, tc, sym, sec in ((AAA, "equity", "EQUITY", "AAA", "IT"), (BBB, "equity", "EQUITY", "BBB", "IT"), (ETF, "etf", "LISTED_NONEQUITY", "GOLDETF", None),
                                    (USX, "equity", "FOREIGN", "USX", None)):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, ?, 'synthetic', now())",
                  [isin, cls, tc, sym, sym + " Ltd", sec])
    c.execute("INSERT INTO accounts (account_id, kind) VALUES ('Z', 'demat')")
    c.execute("INSERT INTO accounts (account_id, kind, currency) VALUES ('US', 'demat', 'USD')")
    c.execute("INSERT INTO events (event_id, kind, account_id, trade_date, amount, ingested_at) VALUES (100, 'deposit', 'Z', ?, 100000, now())", [date(2024, 1, 1)])
    c.execute("INSERT INTO events (event_id, kind, account_id, trade_date, amount, ingested_at) VALUES (101, 'deposit', 'US', ?, 1000, now())", [date(2024, 1, 1)])
    ev = [(1, "buy", "Z", date(2024, 1, 10), AAA, 50, 80.0),(2, "buy", "Z", date(2026, 6, 1), AAA, 10, 95.0), (3, "buy", "Z", date(2025, 3, 3), BBB, 100, 40.0),
          (4, "buy", "US", date(2025, 3, 3), USX, 5, 100.0)]
    for eid, kind, acc, d, isin, q, px in ev:
        c.execute("INSERT INTO events (event_id, kind, account_id, trade_date, isin, qty, price, amount, ingested_at) VALUES (?,?,?,?,?,?,?,?, now())", [eid, kind, acc, d, isin, q, px, q * px])
    c.execute("INSERT INTO cash_ledger VALUES ('Z', ?, 100000, 'cash_transfer_in', 'r', 10)", [date(2024, 1, 1)])
    c.execute("INSERT INTO cash_ledger VALUES ('Z', ?, -8950, 'buy', 'r', 11)", [date(2024, 1, 10)])
    for i, d in enumerate(DAYS):
        for isin, px in ((AAA, 100.0), (BBB, 50.0), (ETF, 60.0)):
            c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d, px])
    return c


def _seed(con):
    return book.seed(con, DAYS[4], datetime(2026, 11, 2, 9, 0))


def _mission(con, rt, now=datetime(2026, 11, 2, 9, 30)):
    out = missions.create(con, now, "Paper portfolio: the first review of the portfolio", pm_dir=rt.pm_dir, origin="paper", budget="standard")
    return out["case_id"]


def _review(con, cid, outcome, at=datetime(2026, 11, 2, 11, 0)):
    from pflab.pm.store import next_id
    con.execute("INSERT INTO hq_case_reviews VALUES (?,?,?,?,?,?)", [next_id(con, "hq_case_reviews", "review_id"), cid, at, "{}", outcome, "n"])


def test_the_start_copies_his_lots_with_their_dates_and_costs_and_leaves_out_the_us_sleeve(con):
    out = _seed(con)
    assert out["new"] and out["lots"] == 3 and out["cash"] == pytest.approx(500_000.0)
    assert {x["isin"] for x in out["left_out"]} == {USX}
    lots = con.execute("SELECT isin, acq_date, qty, cost_per_unit FROM paper_lots ORDER BY acq_date").fetchall()
    assert lots[0][:3] == (AAA, date(2024, 1, 10), 50.0) and lots[0][3] == pytest.approx(80.0)
    h = book.holdings(con, DAYS[4])
    assert h["value"] == pytest.approx(500_000 + 60 * 100 + 100 * 50)
    assert _seed(con)["new"] is False                                                            # once


def test_a_buy_is_sized_by_code_and_cut_to_the_rails(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    r = manager.decide(con, datetime(2026, 11, 2, 10, 0), cid, {"action": "ADD", "symbol": "AAA", "amount_rupees": 50_000, "reason": "a long-term holding with cheap growth on its numbers",
                                                                   "alternatives": "wait for results; buy the index"})
    total = 500_000 + 6000 + 5000
    assert r["stored"] and r["amount_rupees"] == pytest.approx(0.10 * total - 6000) and "the rails" in r["sized"]
    r2 = manager.decide(con, datetime(2026, 11, 2, 10, 0), cid, {"action": "BUY", "symbol": "BBB", "amount_rupees": 30_000, "reason": "same sector as AAA but cheaper by a lot",
                                                                    "alternatives": "hold cash; buy the index"})
    assert r2["stored"] and r2["amount_rupees"] <= 0.25 * total - (6000 + 4210.0) - 5000 + 1                   # the IT sector at 25%, AAA's pending buy not yet bought
    bad = manager.decide(con, datetime(2026, 11, 2, 10, 0), cid, {"action": "BUY", "symbol": "USX", "amount_rupees": 1000, "reason": "a US name the paper book may not buy yet",
                                                                     "alternatives": "nothing else"})
    assert not bad["stored"]


def test_a_review_that_still_objects_adopts_a_wait_but_never_a_trade_and_both_are_scored(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    idx = pd.Series([1000.0 + i for i in range(len(DAYS))], index=pd.to_datetime(DAYS))
    manager.decide(con, datetime(2026, 11, 2, 10, 0), cid, {"action": "WAIT", "reason": "valuations are high and no candidate has the evidence to buy",
                                                              "alternatives": "buy the index now", "review_condition": "a 10% fall in the Nifty 500"}, idx)
    manager.decide(con, datetime(2026, 11, 2, 10, 0), cid, {"action": "SELL", "symbol": "BBB", "reason": "the thesis broke on the last two results of the company",
                                                              "alternatives": "hold; reduce half"})
    _review(con, cid, "revise")
    out = manager.execute(con, datetime(2026, 11, 2, 12, 0), cid)
    assert out == {"orders": 0, "adopted": 1, "not_approved": 1}
    assert dict(con.execute("SELECT action, status FROM paper_decisions").fetchall()) == {"WAIT": "executed", "SELL": "not_approved"}
    assert con.execute("SELECT count(*) FROM paper_orders").fetchone()[0] == 0                  # no trade without approval
    assert con.execute("SELECT count(*) FROM paper_claims").fetchone()[0] == 8                  # the refused one is scored too
    assert manager.execute(con, datetime(2026, 11, 2, 13, 0), cid) == {"orders": 0}              # once


def test_a_rejection_adopts_nothing(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    manager.decide(con, datetime(2026, 11, 2, 10, 0), cid, {"action": "WAIT", "reason": "valuations are high and no candidate has the evidence to buy",
                                                              "alternatives": "buy the index now", "review_condition": "a 10% fall in the Nifty 500"})
    _review(con, cid, "rejected")
    assert manager.execute(con, datetime(2026, 11, 2, 12, 0), cid) == {"orders": 0, "adopted": 0, "not_approved": 1}


def test_the_proposals_tool_shows_a_paper_mission_its_own_decisions(con, rt):
    from pflab.hq import tools as tl
    _seed(con)
    rt.cursor = lambda: con
    cid = _mission(con, rt)
    manager.decide(con, datetime(2026, 11, 2, 10, 0), cid, {"action": "WAIT", "reason": "valuations are high and no candidate has the evidence to buy",
                                                              "alternatives": "buy the index now", "review_condition": "a 10% fall in the Nifty 500"})
    ctx = tl.Ctx(rt, None, "m", False, {}, None, datetime(2026, 11, 2, 10, 5), role="review")
    out = tl.proposals_tool(ctx, {"case_id": cid})
    assert out["paper_decisions"][0]["action"] == "WAIT" and "paper" in out["note"]


def test_nothing_runs_until_the_review_approves_and_a_rejected_mission_trades_nothing(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    manager.decide(con, datetime(2026, 11, 2, 10, 0), cid, {"action": "SELL", "symbol": "BBB", "reason": "the thesis broke on the last two results",
                                                              "alternatives": "hold; reduce half"})
    assert manager.execute(con, datetime(2026, 11, 2, 12, 0), cid) == {"orders": 0, "adopted": 0, "not_approved": 1}      # no review at all: nothing runs
    assert con.execute("SELECT count(*) FROM paper_orders").fetchone()[0] == 0
    assert con.execute("SELECT status FROM paper_decisions").fetchone()[0] == "not_approved"


def test_an_approved_decision_fills_at_the_close_of_its_session_with_charges(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    manager.decide(con, datetime(2026, 11, 2, 10, 0), cid, {"action": "BUY", "symbol": "GOLDETF", "amount_rupees": 12_000, "reason": "gold as a diversifier for the long run",
                                                              "alternatives": "keep cash; buy more shares"})
    _review(con, cid, "approved")
    assert manager.execute(con, datetime(2026, 11, 2, 16, 0), cid)["orders"] == 1                  # after 15:30: the next session's close
    o = con.execute("SELECT placed_at, status FROM paper_orders").fetchone()
    assert book.fill_day(con, o[0], ETF, DAYS[-1]) == date(2026, 11, 3)
    assert book.fill_day(con, datetime(2026, 11, 2, 10, 0), ETF, DAYS[-1]) == date(2026, 11, 2)
    book.fill(con, date(2026, 11, 3), datetime(2026, 11, 3, 21, 0))
    t = con.execute("SELECT side, qty, price, charges FROM paper_trades").fetchone()
    assert t[0] == "buy" and t[1] == 200 and t[2] == 60.0 and t[3] > 0
    assert book.cash(con) == pytest.approx(500_000 - 12_000 - t[3])


def test_a_sale_takes_the_oldest_lots_first_and_its_tax_is_what_it_adds_to_the_year(con):
    _seed(con)
    oid = book.place(con, datetime(2026, 11, 2, 10, 0), None, AAA, "sell", qty=55)
    book.fill(con, date(2026, 11, 2), datetime(2026, 11, 2, 21, 0))
    t = con.execute("SELECT realised, tax, detail_json FROM paper_trades WHERE order_id=?", [oid]).fetchone()
    g = json.loads(t[2])["gains"]
    assert g["lt_eq"] == pytest.approx(50 * 20, abs=30) and g["st_eq"] == pytest.approx(5 * 5, abs=5)    # 50 old at 80, 5 newer at 95 (less the sale's charges)
    assert t[1] == pytest.approx(0.20 * g["st_eq"], abs=0.5)                                             # the long-term gain is under the Rs 1.25 lakh
    assert book.tax_of({"st_eq": -1000.0, "lt_eq": 200_000.0}) == pytest.approx(0.125 * (199_000 - 125_000))   # a short-term loss reduces long-term gains
    assert book.tax_of({"lt_eq": -5000.0, "st_eq": 10_000.0}) == pytest.approx(2000.0)                   # a long-term loss does not reduce a short-term gain


def test_the_paper_account_is_separate_and_none_of_his_real_money_reaches_it(con):
    _seed(con)
    con.execute("INSERT INTO cash_ledger VALUES ('Z', ?, 25000, 'cash_transfer_in', 'r', 12)", [date(2026, 11, 4)])
    book.catch_up(con, date(2026, 11, 6), datetime(2026, 11, 6, 21, 0))
    assert book.cash(con, date(2026, 11, 4)) == pytest.approx(500_000.0)                          # his deposit did not reach it
    r = book.returns(con)
    assert r["sessions"] == 5 and r["twr"] == pytest.approx(0.0, abs=1e-9)


def test_decisions_are_scored_against_the_market_and_keeping_cash_against_cash(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    idx = pd.Series([1000.0 + 10 * i for i in range(len(DAYS))], index=pd.to_datetime(DAYS))
    manager.decide(con, datetime(2026, 11, 2, 10, 0), cid, {"action": "HOLD", "symbol": "AAA", "reason": "the business is intact after the quarter's results",
                                                              "alternatives": "sell; reduce", "review_condition": "the next results"}, idx)
    manager.decide(con, datetime(2026, 11, 2, 10, 0), cid, {"action": "WAIT", "reason": "valuations are high across the market today; keep cash for now",
                                                              "alternatives": "buy the index now", "review_condition": "a 10% fall in the Nifty 500"}, idx)
    _review(con, cid, "approve")
    manager.execute(con, datetime(2026, 11, 2, 12, 0), cid)
    assert con.execute("SELECT count(*) FROM paper_claims").fetchone()[0] == 8
    n = manager.score_due(con, datetime(2026, 12, 3, 21, 0), idx)
    got = dict(con.execute("SELECT action || ':' || horizon_days, outcome FROM paper_claims WHERE outcome IS NOT NULL").fetchall())
    assert n == 4 and got["WAIT:7"] == "bad" and got["HOLD:28"] == "bad"                                # the market rose; the flat stock lagged it
    assert "decision(s)" in manager.record(con)["summary"]


def test_the_gate_opens_only_after_two_months_of_beating_the_index_with_a_smaller_fall(con):
    _seed(con)
    book.catch_up(con, DAYS[-1], datetime(2026, 12, 31, 21, 0))
    idx = pd.Series([1000.0 * (1 - 0.001 * i) for i in range(len(DAYS))], index=pd.to_datetime(DAYS))
    g = manager.gate(con, None, idx)
    assert book.returns(con)["sessions"] >= manager.GATE_SESSIONS and g["open"] is True                # flat beats a falling index, with no fall
    up = pd.Series([1000.0 * (1 + 0.002 * i) for i in range(len(DAYS))], index=pd.to_datetime(DAYS))
    assert manager.gate(con, None, up)["open"] is False


def test_the_gate_waits_for_enough_sessions(con):
    _seed(con)
    book.catch_up(con, DAYS[8], datetime(2026, 11, 5, 21, 0))
    assert manager.gate(con, None, pd.Series([1.0, 1.0], index=pd.to_datetime(DAYS[:2])))["open"] is False


def test_the_loop_starts_the_book_opens_the_first_review_alone_and_one_piece_of_work_at_a_time(con, rt, monkeypatch):
    rt.con = con
    monkeypatch.setattr(manager, "_index", lambda root: None)
    rt.clock = lambda: datetime(2026, 11, 2, 8, 0)
    from pflab.hq import desk
    monkeypatch.setattr(rt, "cursor", lambda: con)
    out = manager.tick(rt)
    assert out["seed"]["new"] and out["started"]
    cid = out["started"]
    m = missions.mission_of(con, cid)
    assert m["origin"] == "paper" and m["state"] == "planning"                                       # no approval step: the system decides alone
    manager.add_input(con, datetime(2026, 11, 2, 8, 5), "look into the AI bubble: should it invest in AI names and how much?")
    assert manager.tick(rt).get("working") == cid                                                   # one at a time: the input waits
    con.execute("UPDATE hq_missions SET state='done' WHERE case_id=?", [cid])
    out2 = manager.tick(rt)
    assert out2.get("started") and con.execute("SELECT status, case_id FROM paper_inputs").fetchone() == ("taken", out2["started"])
    assert "AI bubble" in missions.mission_of(con, out2["started"])["goal"]


def test_its_money_is_held_to_its_own_share(con, rt, monkeypatch):
    monkeypatch.setattr(rt, "cursor", lambda: con)
    monkeypatch.setattr(manager, "_index", lambda root: None)
    rt.clock = lambda: datetime(2026, 11, 2, 8, 0)
    monkeypatch.setattr(manager, "spend_month", lambda c, n: 495.0)
    out = manager.tick(rt)
    assert "held" in out and "started" not in out


def test_a_paper_mission_cannot_make_a_real_proposal_and_paper_order_needs_a_paper_mission(con, rt):
    from pflab.hq import tools as tl
    _seed(con)
    cid = _mission(con, rt)
    other = missions.create(con, datetime(2026, 11, 2, 9, 30), "Is AAA a buy for my real money?", pm_dir=rt.pm_dir, origin="investor")["case_id"]
    rt.cursor = lambda: con
    ctx = tl.Ctx(rt, None, "m", False, {}, None, datetime(2026, 11, 2, 10, 0), role="quant")
    r = tl.make_proposal(ctx, {"action": "ADD", "symbol": "AAA", "reason": "x" * 30, "alternatives": "y" * 20, "case_id": cid})
    assert not r["stored"] and "paper_decide" in r["problem"]
    r2 = tl.paper_decide(ctx, {"action": "ADD", "symbol": "AAA", "reason": "x" * 30, "alternatives": "y" * 20, "amount_rupees": 1000, "case_id": other})
    assert not r2["stored"]


def test_the_rails_flag_his_own_concentration_without_selling_it(con):
    _seed(con)
    con.execute("UPDATE paper_cash SET amount = 1000 WHERE kind='seed'")
    f = rails.flags(con, DAYS[4])
    assert any("AAA" in x for x in f) and any("IT sector" in x for x in f)
    assert book.positions(con)[AAA] == 60.0


def test_a_paper_mission_has_its_own_ceiling_whatever_the_flat_cap_says(con, rt, monkeypatch):
    monkeypatch.setattr(an, "config", lambda: {**CFG, "policy": {"mission_rupees": 1000}})
    cid = _mission(con, rt)
    other = missions.create(con, datetime(2026, 11, 2, 9, 30), "Is AAA a buy for my real money?", pm_dir=rt.pm_dir, origin="investor")["case_id"]
    assert missions.cap_of(con, cid) == manager.MISSION_RUPEES and missions.cap_of(con, other) == 1000        # (set in the file: the classes of the investor's own work are unchanged)


def test_the_paper_playbook_plans_research_beside_measures_then_one_decision_step(con, rt):
    from pflab.hq import playbooks
    steps, _ = playbooks.paper_steps("Paper portfolio: the weekly review")
    assert [s["key"] for s in steps] == ["changes", "ideas", "measure", "decide"]
    assert steps[-1]["promise"] == {"proposal": 1} and set(steps[-1]["depends_on"]) == {"changes", "ideas", "measure"}
    cid = _mission(con, rt)
    task = con.execute("SELECT task_id FROM hq_tasks WHERE case_id=? AND role='coordinator'", [cid]).fetchone()[0]
    out = playbooks.try_plan(con, cid, task, datetime(2026, 11, 2, 9, 31))
    assert out["name"] == "paper" and con.execute("SELECT count(*) FROM hq_tasks WHERE case_id=? AND role IN ('research','quant')", [cid]).fetchone()[0] == 4


def test_the_paper_settings_are_read_from_his_budget_file(tmp_path, monkeypatch):
    (tmp_path / "api_budget.toml").write_text("[api]\nmonthly_cap_rupees = 1500\n[paper]\nmonthly_rupees = 450\nmission_rupees = 90\non = \"on\"\n", encoding="utf-8")
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    cfg = an.config()
    assert cfg["paper"] == {"monthly_rupees": 450, "mission_rupees": 90, "on": "on"}
    monkeypatch.setattr(an, "config", lambda: cfg)
    assert manager.settings()["monthly_rupees"] == 450.0 and manager.settings()["mission_rupees"] == 90.0


def test_a_worker_cannot_ask_its_own_role_for_an_artifact(con, rt):
    from pflab.hq import tools as tl
    rt.cursor = lambda: con
    cid = _mission(con, rt)
    tid = missions.add_task(con, datetime(2026, 11, 2, 9, 40), cid, "quant", "measure the book")["task_id"]
    ctx = tl.Ctx(rt, None, "m", False, {}, None, datetime(2026, 11, 2, 9, 41), role="quant", task_id=tid)
    mine = tl.request_artifact(ctx, {"case_id": cid, "role": "quant", "what": "a calculation I could run myself"})
    assert mine["queued"] is False and "do this yourself" in mine["problem"]
    theirs = tl.request_artifact(ctx, {"case_id": cid, "role": "research", "what": "evidence on the sector's results"})
    assert theirs["queued"] is True


def test_a_share_with_no_sector_in_the_instruments_table_gets_the_sector_maps_industry(con, monkeypatch):
    con.execute("UPDATE instruments SET sector = NULL WHERE isin = ?", [AAA])
    book._SECTORS.clear()
    monkeypatch.setattr(book, "_industry", lambda isin: "COMPUTERS - SOFTWARE" if isin == AAA else None)
    assert book.inst(con, AAA)["sector"] == "COMPUTERS - SOFTWARE" and book.inst(con, ETF)["sector"] is None


def test_an_earlier_refused_wait_is_adopted_and_scored_once(con, rt):
    _seed(con)
    cid = _mission(con, rt)
    idx = pd.Series([1000.0 + i for i in range(len(DAYS))], index=pd.to_datetime(DAYS))
    manager.decide(con, datetime(2026, 11, 2, 10, 0), cid, {"action": "WAIT", "reason": "valuations are high and no candidate has the evidence to buy",
                                                              "alternatives": "buy the index now", "review_condition": "a 10% fall in the Nifty 500"}, idx)
    con.execute("UPDATE paper_decisions SET status='not_approved'")                            # as the first live run left it
    _review(con, cid, "revise")
    assert manager.sweep_stays(con, datetime(2026, 11, 3, 9, 0)) == 1 and manager.sweep_stays(con, datetime(2026, 11, 3, 9, 1)) == 0
    assert con.execute("SELECT status FROM paper_decisions").fetchone()[0] == "executed" and con.execute("SELECT count(*) FROM paper_claims").fetchone()[0] == 4
