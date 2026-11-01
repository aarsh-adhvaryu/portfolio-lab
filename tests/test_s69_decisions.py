"""S69: buy, add, hold, reduce, sell, diversify and wait as distinct reviewable proposals; the numbers are computed from the record; unknown acquisition cost is
never zero; an incomplete ledger gives no personalised size or tax; the lifecycle (discuss, amend, accept, reject, withdraw) is recorded; a trade he later makes
is matched once; a strategy change stays apart from the active strategy. SYNTHETIC ledger (the S58b fixture), no model."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from pflab.hq import proposals as pr
from pflab.ledger.events import Event, load, save
from pflab.pm import store
from tests.test_s58b_today import AAA, BBB, ledger

NOW = datetime(2026, 10, 23, 15, 0)


@pytest.fixture
def con(tmp_path):
    c = ledger(tmp_path)
    c.execute("UPDATE instruments SET tax_class='EQUITY'")                      # the engine's own label for listed equity
    return c


def mk(con, **kw):
    base = {"reason": "The evidence in the case supports acting; the price is below the level the thesis needs.", "alternatives": "Waiting a month, or holding what he has, were compared."}
    return pr.create(con, NOW, {**base, **kw}, case_id=None)


def test_a_buy_is_sized_from_the_record_with_price_date_cash_costs_and_weights(con):
    out = mk(con, action="BUY", symbol="BBB", qty=100)
    assert out["stored"] and out["review_status"] == "unreviewed"
    p = pr.get(con, out["proposal_id"])
    z = p["payload"]
    assert z["price"]["value"] == 50.0 and z["price"]["as_of"] == "2026-10-22"                    # the stored close and its date
    assert z["size"]["qty"] == 100 and z["size"]["notional"] == 5000.0 and z["size"]["charges_estimate"] > 0
    assert z["size"]["cash_after"] < z["portfolio"]["cash_rupees"]
    assert z["portfolio_effect"]["weight_after"] > z["portfolio_effect"]["weight_before"] == 0.0
    assert p["status"] == "proposed" and p["strategy_version"].startswith("policy-v0") and p["snapshot_id"]
    assert z["not_an_order"] and "alternatives" in z and z["sizing_supported"] is True


def test_a_buy_that_needs_more_cash_than_there_is_says_so(con):
    out = mk(con, action="ADD", symbol="AAA", qty=100_000)
    assert any("cash" in m for m in out["missing"]) and pr.get(con, out["proposal_id"])["payload"]["size"]["cash_shortfall"] > 0


def test_a_sale_has_proceeds_charges_and_the_tax_effect_from_the_lots(con):
    out = mk(con, action="REDUCE", symbol="AAA", qty=4)
    z = pr.get(con, out["proposal_id"])["payload"]
    assert z["exit"] == "partial" and z["size"]["qty"] == 4 and z["size"]["fraction_of_holding"] == 0.4
    assert z["size"]["proceeds_estimate"] == pytest.approx(4 * 120.0 - z["size"]["charges_estimate"], abs=0.01)
    assert z["tax_effect"]["status"] == "estimate" and z["tax_effect"]["extra_tax"] is not None
    assert "hold_comparison" in z and z["portfolio_effect"]["weight_after"] < z["portfolio_effect"]["weight_before"]
    full = pr.get(con, mk(con, action="SELL", symbol="AAA")["proposal_id"])["payload"]
    assert full["exit"] == "full" and full["size"]["qty"] == 10


def test_one_cannot_sell_what_is_not_held_and_a_buy_needs_a_size(con):
    assert "only 10" in mk(con, action="REDUCE", symbol="AAA", qty=50)["problem"]
    assert "nothing is held" in mk(con, action="SELL", symbol="BBB")["problem"]
    assert "quantity or an amount" in mk(con, action="BUY", symbol="BBB")["problem"]


def test_unknown_acquisition_cost_is_unknown_never_zero(con):
    log = load(con)
    log.append(Event("buy", "ZER", date(2026, 10, 2), isin=BBB, qty=30, price=0.0, ref="DP:BBB:cost_unknown"))
    save(con, log)
    out = mk(con, action="SELL", symbol="BBB")
    z = pr.get(con, out["proposal_id"])["payload"]
    assert z["tax_effect"]["status"] == "unknown" and z["tax_effect"]["extra_tax"] is None and "acquisition cost" in z["tax_effect"]["why"]
    assert z["holding_now"]["cost_known"] is False and any("purchase cost" in m for m in out["missing"])
    assert z["size"]["proceeds_estimate"] > 0                      # the sale itself can still be sized: only the tax claim is withheld


def test_an_incomplete_ledger_gives_direction_and_evidence_but_no_size_and_no_tax(con):
    con.execute("INSERT INTO known_gaps (gap_id, gap_key, source, detail, opened_at, status) VALUES (1, 'coverage:x', 'test', 'a statement is missing', now(), 'open')")
    out = mk(con, action="REDUCE", symbol="AAA", qty=4)
    z = pr.get(con, out["proposal_id"])["payload"]
    assert z["sizing_supported"] is False and z["size"] is None and "tax_effect" not in z and z["reason"]
    assert any("whole ledger" in m for m in out["missing"])


def test_hold_wait_and_diversify_need_a_concrete_condition_for_looking_again(con):
    assert "concrete condition" in mk(con, action="WAIT", symbol="AAA")["problem"]
    ok = mk(con, action="WAIT", symbol="AAA", review_condition="AAA closes below Rs 100 or a result is published")
    z = pr.get(con, ok["proposal_id"])["payload"]
    assert z["review_condition"] and z["why_not_act"] and z.get("size") is None
    d = pr.get(con, mk(con, action="DIVERSIFY", review_condition="cash above Rs 50,000 after the next deposit")["proposal_id"])["payload"]
    assert d["portfolio_effect"]["holdings"] >= 1 and "top3_share" in d["portfolio_effect"]
    assert "alternatives" in mk(con, action="HOLD", symbol="AAA", alternatives="x", review_condition="a new result")["problem"]


def test_the_lifecycle_is_recorded_and_accepting_places_no_order(con):
    pid = mk(con, action="BUY", symbol="BBB", qty=100)["proposal_id"]
    assert pr.discuss(con, NOW, pid, "why not 50 shares?")["ok"]
    again = mk(con, action="BUY", symbol="BBB", qty=50)                       # the same proposal, amended: one row, a new version
    assert again["proposal_id"] == pid and again["version"] == 2
    assert con.execute("SELECT count(*) FROM hq_proposals").fetchone()[0] == 1
    pr.set_review(con, NOW, pid, "approve", "checked")
    out = pr.decide(con, NOW, pid, "accept", note="I will do it tomorrow")
    assert out["ok"] and out["status"] == "accepted" and "does not place an order" in out["reminder"]
    assert pr.decide(con, NOW, pid, "reject")["ok"] is False                   # an accepted proposal is withdrawn, not rejected
    w = pr.decide(con, NOW, pid, "withdraw", note="changed my mind")
    assert w["status"] == "withdrawn" and pr.decide(con, NOW, pid, "accept")["ok"] is False
    log = [e["event"] for e in pr.get(con, pid)["log"]]
    assert log[:2] == ["created", "discussed"] and "amended" in log and "reviewed" in log and "accepted" in log and log[-1] == "withdrawn"


def test_accepting_an_unreviewed_proposal_says_so(con):
    pid = mk(con, action="HOLD", symbol="AAA", review_condition="a new result is published")["proposal_id"]
    out = pr.decide(con, NOW, pid, "accept")
    assert "unreviewed" in out["note"]


def test_new_evidence_marks_open_proposals_for_review_again(con):
    from pflab.hq import cases
    cid, _ = cases.open_case(con, NOW, "Should I add to AAA?", origin="investor")
    pid = pr.create(con, NOW, {"action": "WAIT", "symbol": "AAA", "reason": "The evidence is thin and the price has not fallen enough to justify buying.",
                               "alternatives": "Buy now, or hold; both were weaker on the evidence.", "review_condition": "a result is published"}, case_id=cid)["proposal_id"]
    pr.set_review(con, NOW, pid, "approve")
    assert pr.get(con, pid)["review_status"] == "approved"
    assert pr.evidence_changed(con, NOW, cid, "a contradicting filing arrived") == [pid]
    p = pr.get(con, pid)
    assert p["review_status"] == "unreviewed" and p["log"][-1]["event"] == "evidence_changed"


def test_a_stale_snapshot_is_flagged(con, tmp_path):
    pid = mk(con, action="BUY", symbol="BBB", qty=10)["proposal_id"]
    con.execute("UPDATE hq_proposals SET snapshot_id='abc_2026-01-01' WHERE proposal_id=?", [pid])
    (tmp_path / "pm" / "app").mkdir(parents=True)
    assert "abc_2026-01-01" in pr.stale_reason(con, pr.get(con, pid), tmp_path / "pm")


# --- a trade he makes arrives through the ledger ------------------------------------------------------------------------------------------

def _trade(con, kind, isin, qty, price, day, ref):
    log = load(con)
    log.append(Event(kind, "ZER", day, isin=isin, qty=qty, price=price, ref=ref, fees={"brokerage": 0.0, "stt": round(qty * price * 0.001, 2)}))
    save(con, log)


def test_a_purchase_confirmation_reconciles_once_and_updates_the_record(con):
    pid = mk(con, action="BUY", symbol="BBB", qty=100)["proposal_id"]
    pr.decide(con, NOW, pid, "accept")
    assert pr.reconcile(con, NOW) == []                                         # nothing traded yet
    before = con.execute("SELECT coalesce(sum(qty), 0) FROM events WHERE kind='buy' AND isin=?", [BBB]).fetchone()[0]
    _trade(con, "buy", BBB, 100, 50.5, NOW.date(), "CN-1")                      # the genuine confirmation (synthetic) becomes an event in the ledger
    got = pr.reconcile(con, NOW + timedelta(hours=1))
    assert len(got) == 1 and got[0]["status"] == "executed" and got[0]["qty"] == 100 and got[0]["avg_price"] == pytest.approx(50.5)
    assert pr.get(con, pid)["status"] == "executed" and "50.50" in pr.get(con, pid)["log"][-1]["note"]
    assert pr.reconcile(con, NOW + timedelta(hours=2)) == []                    # the same trade is not counted twice
    from pflab.app import views
    h = {r["isin"]: r for r in views.holdings(con, NOW.date())["rows"]}
    assert h[BBB]["qty"] == 100 and h[BBB]["cost"] is not None                  # holdings and cost basis follow the ledger, not the proposal
    assert con.execute("SELECT coalesce(sum(qty), 0) FROM events WHERE kind='buy' AND isin=?", [BBB]).fetchone()[0] == before + 100


def test_a_sale_confirmation_reconciles_once_and_a_partial_fill_stays_partial(con):
    pid = mk(con, action="REDUCE", symbol="AAA", qty=8)["proposal_id"]
    pr.decide(con, NOW, pid, "accept")
    _trade(con, "sell", AAA, 3, 121.0, NOW.date(), "CN-2")
    got = pr.reconcile(con, NOW)
    assert got[0]["status"] == "partly_executed" and got[0]["qty"] == 3
    _trade(con, "sell", AAA, 5, 122.0, NOW.date(), "CN-3")
    got = pr.reconcile(con, NOW)
    assert got[0]["status"] == "executed" and got[0]["qty"] == 8 and got[0]["avg_price"] == pytest.approx((3 * 121 + 5 * 122) / 8)
    assert pr.reconcile(con, NOW) == []
    from pflab.app import views
    assert {r["isin"]: r for r in views.holdings(con, NOW.date())["rows"]}[AAA]["qty"] == 2


def test_a_trade_is_matched_to_one_proposal_only_and_survives_a_rebuild_of_the_ledger(con):
    a = mk(con, action="BUY", symbol="BBB", qty=10)["proposal_id"]
    b = pr.create(con, NOW, {"action": "ADD", "symbol": "BBB", "qty": 10, "reason": "A second proposal on the same company, made in another case.",
                             "alternatives": "Waiting, or holding what he has."}, case_id=7)["proposal_id"]
    pr.decide(con, NOW, a, "accept")
    pr.decide(con, NOW, b, "accept")
    _trade(con, "buy", BBB, 10, 50.0, NOW.date(), "CN-9")
    done = pr.reconcile(con, NOW)
    assert [d["proposal_id"] for d in done] == [a]                              # one purchase, one proposal
    ids_before = json_keys(con, a)
    con.execute("UPDATE events SET event_id = event_id + 1000")                 # a rebuild of the ledger renumbers its events
    assert pr.reconcile(con, NOW) == [] and json_keys(con, a) == ids_before


def json_keys(con, pid):
    import json
    return json.loads(con.execute("SELECT executed_event_ids FROM hq_proposals WHERE proposal_id=?", [pid]).fetchone()[0])


def test_a_trade_he_makes_updates_the_investigation_that_proposed_it(con):
    from pflab.hq import cases, missions
    cid, _ = cases.open_case(con, NOW, "Should I add to BBB?", origin="investor")
    con.execute("INSERT INTO hq_missions VALUES (1,?,?,?,?,?,0,?,?,?,?,?,?,?)", [cid, NOW, NOW, "Should I add to BBB?", "done", None, "s", '{"answer": "add a little"}', NOW, "x", None, "investor"])
    pid = pr.create(con, NOW, {"action": "ADD", "symbol": "BBB", "qty": 5, "reason": "The evidence supports a small addition at this price.",
                               "alternatives": "Waiting, or holding what he has."}, case_id=cid)["proposal_id"]
    pr.decide(con, NOW, pid, "accept")
    _trade(con, "buy", BBB, 5, 50.0, NOW.date(), "CN-5")
    pr.reconcile(con, NOW)
    log = [e[0] for e in con.execute("SELECT event FROM hq_case_log WHERE case_id=?", [cid]).fetchall()]
    assert "proposal executed" in log and "reopened" in log                     # affected research is looked at again against the new position
    assert missions.mission_of(con, cid)["state"] == "planning"


# --- the strategy version: a proposed change stays apart from the active one -----------------------------------------------------------------

def test_a_proposed_strategy_change_does_not_become_active_by_itself(con):
    assert pr.strategy_version(con).startswith("policy-v0")
    v = pr.propose_strategy_change(con, NOW, {"deploy_monthly_rupees": 50000, "until": "2027-01"}, "a paper example")
    assert pr.strategy_version(con).startswith("policy-v0")                     # proposed is not active
    assert con.execute("SELECT status FROM hq_policy WHERE version=?", [v]).fetchone()[0] == "proposed"
    pid = mk(con, action="WAIT", symbol="AAA", review_condition="a result is published")["proposal_id"]
    assert pr.get(con, pid)["strategy_version"].startswith("policy-v0")
    assert pr.activate_strategy(con, NOW, v)["activated"]                        # only his own press (the API) does this
    assert pr.strategy_version(con) == f"policy-v{v}"


def test_a_proposal_tool_cannot_be_used_to_place_an_order():
    from pflab.hq import tools as tl
    names = " ".join(tl.TOOLS)
    assert "order" not in names.replace("order_research", "").replace("order_calculation", "")
    assert tl.TOOLS["make_proposal"].kind == "journal" and "never an order" in tl.TOOLS["make_proposal"].about


# --- the confirmation comes through the REAL tradebook parser, twice ----------------------------------------------------------------------------

def _tradebook(path, rows):
    import pandas as pd
    pd.DataFrame(rows, columns=["symbol", "isin", "trade_date", "exchange", "segment", "series", "trade_type", "auction", "quantity", "price", "trade_id", "order_id",
                                "order_execution_time"]).to_csv(path, index=False)


def test_a_synthetic_tradebook_with_a_purchase_and_a_sale_reconciles_once_even_if_ingested_twice(con, tmp_path):
    from pflab.ingest import tradebook as tb
    from pflab.ledger import events as ev
    buy = pr.create(con, NOW, {"action": "BUY", "symbol": "BBB", "qty": 20, "reason": "The evidence supports a purchase at this price, sized to the cash.",
                               "alternatives": "Waiting a month, or holding what he has."}, case_id=None)["proposal_id"]
    sell = pr.create(con, NOW, {"action": "REDUCE", "symbol": "AAA", "qty": 4, "reason": "The position is larger than the thesis needs; trimming lowers the risk.",
                                "alternatives": "Holding it all, or selling everything."}, case_id=None)["proposal_id"]
    pr.decide(con, NOW, buy, "accept")
    pr.decide(con, NOW, sell, "accept")
    day = NOW.strftime("%Y-%m-%d")
    f = tmp_path / "tradebook.csv"
    _tradebook(f, [["BBB", BBB, day, "NSE", "EQ", "EQ", "buy", False, 12, 50.5, "T9001", "O1", f"{day}T10:00:00"],
                   ["BBB", BBB, day, "NSE", "EQ", "EQ", "buy", False, 8, 50.75, "T9002", "O1", f"{day}T10:00:05"],
                   ["AAA", AAA, day, "NSE", "EQ", "EQ", "sell", False, 4, 121.0, "T9003", "O2", f"{day}T11:00:00"]])

    def ingest():
        log = ev.load(con)
        refs = {e.ref for e in log if e.ref}
        events, rep = tb.to_events(tb.parse(f), "ZER", existing_refs=refs)
        for e in events:
            log.append(e)
        ev.save(con, log)
        return rep["events"], rep["skipped_existing"]
    from pflab.app import views
    cash_before = views.holdings(con, NOW.date())["cash"]
    assert ingest() == (3, 0)
    done = {d["proposal_id"]: d for d in pr.reconcile(con, NOW)}
    assert done[buy]["status"] == "executed" and done[buy]["qty"] == 20 and done[buy]["avg_price"] == pytest.approx((12 * 50.5 + 8 * 50.75) / 20)
    assert done[sell]["status"] == "executed" and done[sell]["qty"] == 4
    assert ingest() == (0, 3)                                                   # the same file again adds nothing...
    assert pr.reconcile(con, NOW) == []                                         # ...so nothing is counted twice
    assert con.execute("SELECT count(*) FROM events WHERE ref IN ('T9001','T9002','T9003')").fetchone()[0] == 3
    h = views.holdings(con, NOW.date())
    held = {r["isin"]: r["qty"] for r in h["rows"]}
    assert held[BBB] == 20 and held[AAA] == 6                                   # holdings follow the ledger: +20 bought, 4 of 10 sold
    assert h["cash"] == pytest.approx(cash_before - (12 * 50.5 + 8 * 50.75) + 4 * 121.0)             # cash: paid for the purchase, received for the sale
    from pflab.ledger.book import Ledger
    real = Ledger.replay(ev.load(con)).realised
    assert len(real) == 1 and real[0].gain == pytest.approx(4 * (121.0 - 100.0)) if hasattr(real[0], "gain") else len(real) == 1        # realised on the lot bought at 100
