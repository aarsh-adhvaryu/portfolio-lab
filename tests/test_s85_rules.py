"""S85 `rules` (E4, A69 door b): standing instructions. The typed kinds (`pause_buys`, `hold_name`, `no_new_names`, `cash_floor`), the intake that turns his words into a rule (a scripted model, code
checks), the tightening test, the Yes/No for money and for his targets, notes for the strategist, and every order site of the core reading the rules. Synthetic data only (rule 7)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab.core import card, exits, loop, picks, premium, rules_gate, session as core_session
from pflab.entrance import rules_intake
from pflab.hq import rules
from pflab.ledger import events as ev
from pflab.ledger import system
from pflab.paper import book
from pflab.pm import store

AAA, BBB, GLD, INTL = "INE000A01011", "INE000B01012", "INF000G01015", "INF000I01017"
NOW = datetime(2026, 10, 30, 16, 0)
DAYS = [d.date() for d in pd.bdate_range("2025-08-01", "2026-10-30")]
DAY = DAYS[-1]


def calm_index() -> pd.Series:
    idx = pd.bdate_range("2025-08-01", "2026-10-30")
    return pd.Series([1000.0 * 1.0003 ** n for n in range(len(idx))], index=idx)


def _build(tmp_path, monkeypatch, gold_qty):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setattr(premium, "rail_reasons", lambda state, targets, cfg=None: (dict(targets), {}))
    c = store.connect(tmp_path / "l.duckdb")
    for isin, cls, tc, sym, name in ((AAA, "equity", "EQUITY", "AAA", "AAA Ltd"), (BBB, "equity", "EQUITY", "BBB", "BBB Ltd"), (GLD, "etf", "LISTED_NONEQUITY", "GOLDBEES", "Goldbees Gold ETF"),
                                     (INTL, "etf", "LISTED_NONEQUITY", "NASDAQ100X", "Nasdaq 100 International ETF")):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, 'synthetic', now())", [isin, cls, tc, sym, name])
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha')")
    log = ev.EventLog()
    log.append(ev.Event(kind="deposit", account_id="ZER", date=date(2024, 1, 1), amount=2_000_000.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2024, 1, 10), isin=AAA, qty=300, price=80.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2025, 3, 3), isin=BBB, qty=300, price=40.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2025, 3, 4), isin=GLD, qty=gold_qty, price=50.0)) if gold_qty else None
    ev.save(c, log, NOW)
    for k, d in enumerate(DAYS):
        wob = 1.0 + (0.03 if k % 2 else -0.03)
        for isin, px in ((AAA, 100.0 * 1.0004 ** k * wob), (BBB, 50.0 * 1.0004 ** k * (1.0 + (0.004 if k % 2 else -0.004))), (GLD, 50.0 * 1.0003 ** k * (1.0 + (0.002 if k % 2 else -0.002))),
                         (INTL, 80.0 * 1.0003 ** k)):
            c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d, px])
    system.switch(c, tmp_path, DAYS[-6], NOW)
    book.seed(c, DAYS[-6], NOW)
    book.catch_up(c, DAY, datetime.combine(DAY, datetime.min.time()) + timedelta(hours=21))
    return c


@pytest.fixture
def con(tmp_path, monkeypatch):
    """A small book (Rs 5 lakh cash, a little gold and two shares) whose close wants to BUY gold; the NAV-premium rail is switched out (it has no NAV data here)."""
    return _build(tmp_path, monkeypatch, 200)


@pytest.fixture
def con_nogold(tmp_path, monkeypatch):
    return _build(tmp_path, monkeypatch, 0)


def make(con, kind, machine, text, until=None, now=NOW):
    out = rules.propose(con, now, kind, text, machine, until=until, source="test")
    assert out["made"], out
    return out


def gold_orders(con):
    return con.execute("SELECT count(*) FROM paper_orders WHERE isin=? AND side='buy'", [GLD]).fetchone()[0]


def form(**kw):
    """What a scripted model returns for the intake form (every key present, as the strict schema demands)."""
    f = {"kind": "none", "scope": "none", "value": "", "name": "", "market": "both", "until": "", "share_pct": 0, "terms": [], "amount_rupees": 0, "extra_rupees": 0, "below_high_pct": 0,
         "max_weight_pct": 0, "carry_over": False, "change_kind": "none", "change_key": "", "change_value": "", "loosens": False, "summary": ""}
    f.update(kw)
    return f


def says(**kw):
    seen = []

    def call(system, messages, schema):
        seen.append((system, messages, schema))
        return form(**kw)
    call.seen = seen
    return call


# --- the kinds, their states, Undo and Change date -------------------------------------------------------------------------------------------------------------------

def test_a_rule_of_the_new_kinds_defaults_to_thirty_days_and_lapses_by_date(con):
    r = make(con, "pause_buys", {"scope": "class", "value": "gold"}, "pause gold buys")
    assert r["until"] == NOW.date() + timedelta(days=30) and r["until_defaulted"] is True and r["status"] == "active"
    assert rules.blocks(con, NOW.date(), cls="gold", action="buy")["rule_id"] == r["rule_id"]
    assert rules.blocks(con, NOW.date() + timedelta(days=30), cls="gold", action="buy")                    # the last day it still holds
    assert rules.blocks(con, NOW.date() + timedelta(days=31), cls="gold", action="buy") is None             # lapsed by date
    assert rules.active(con, NOW.date() + timedelta(days=31)) == [] and len(rules.active(con)) == 1          # `active(con)` with no day is unchanged (the old kinds)
    assert rules.sweep(con, NOW.date() + timedelta(days=31)) == [r["rule_id"]]
    assert [x["state"] for x in rules.listing(con, NOW.date() + timedelta(days=31))] == ["expired"]


def test_undo_and_change_date(con):
    r = make(con, "pause_buys", {"scope": "class", "value": "gold"}, "pause gold buys until 20 Nov", until="2026-11-20")
    assert rules.change_date(con, r["rule_id"], "2026-11-10", NOW)["changed"] and rules.active(con)[0]["until"] == date(2026, 11, 10)
    assert rules.change_date(con, r["rule_id"], "2026-10-01", NOW)["changed"] is False                       # a date already past: use Undo
    assert rules.change_date(con, r["rule_id"], "2028-01-01", NOW)["changed"] is False
    assert rules.undo(con, r["rule_id"])["undone"] is True                                                   # the contract's form: undo(con, rule_id)
    assert rules.blocks(con, NOW.date(), cls="gold", action="buy") is None and rules.listing(con, NOW.date())[0]["state"] == "undone"
    assert rules.change_date(con, r["rule_id"], "2026-11-12", NOW)["changed"] is False                       # an undone rule has no date to change


def test_the_old_kinds_keep_working(con):
    a = rules.propose(con, NOW, "sector_exclusion", "No new tech until I say", {"terms": ["software"]}, name="no_new_tech")
    assert a["made"] and a["until"] is None and rules.active(con, NOW.date())[0]["until"] is None
    assert rules.undo(con, NOW, "no_new_tech")["undone"] is True                                              # the old form: undo(con, now, ref)
    m = rules.propose(con, NOW, "monthly_envelope", "I invest Rs 50,000 a month", {"amount_rupees": 50000})
    assert m["status"] == "pending" and m["needs_yes"] and rules.listing(con, NOW.date())[0]["state"] == "waiting_yes"


def test_blocks_knows_class_sleeve_name_new_name_and_the_protected_sales(con):
    make(con, "pause_buys", {"scope": "sleeve", "value": "longterm"}, "pause the longterm sleeve")
    make(con, "pause_buys", {"scope": "name", "isin": AAA, "symbol": "AAA"}, "pause AAA")
    make(con, "no_new_names", {}, "no new names")
    make(con, "hold_name", {"isin": BBB, "symbol": "BBB"}, "hold BBB")
    d = NOW.date()
    assert rules.blocks(con, d, sleeve="longterm", action="buy")["kind"] == "pause_buys"
    assert rules.blocks(con, d, symbol="AAA", action="buy")["kind"] == "pause_buys"
    assert rules.blocks(con, d, isin=GLD, sleeve="core", cls="gold", action="buy") is None                    # held already, not in a paused class
    assert rules.blocks(con, d, isin=GLD, sleeve="core", cls="gold", action="buy", new_name=True)["kind"] == "no_new_names"
    assert rules.blocks(con, d, isin=BBB, action="sell", order_kind="target")["kind"] == "hold_name"          # a wish to sell: held
    assert rules.blocks(con, d, isin=BBB, action="sell", order_kind="case")["kind"] == "hold_name"
    for k in ("stop", "thesis", "trim", "rail", "risk"):                                                      # a stop, a rail, a thesis break, a risk cut: never held
        assert rules.blocks(con, d, isin=BBB, action="sell", order_kind=k) is None
    assert rules.blocks(con, d, isin=AAA, action="sell", order_kind="target") is None                        # another name
    make(con, "pause_buys", {"scope": "class", "value": "international", "market": "US"}, "pause international in the US")
    assert rules.blocks(con, d, cls="international", action="buy", market="IN") is None
    assert rules.blocks(con, d, cls="international", action="buy", market="US")["machine"]["market"] == "US"


def test_a_bad_machine_form_is_refused_by_the_rule_store(con):
    for kind, m in (("pause_buys", {"scope": "class", "value": "crypto"}), ("pause_buys", {"scope": "sleeve", "value": "swing"}), ("pause_buys", {"scope": "name"}), ("hold_name", {}),
                    ("cash_floor", {"share_pct": 0}), ("cash_floor", {"share_pct": 95}), ("pause_buys", {"scope": "all", "market": "EU"})):
        assert rules.propose(con, NOW, kind, "some rule text", m)["made"] is False, (kind, m)
    assert rules.propose(con, NOW, "pause_buys", "pause gold", {"scope": "class", "value": "gold"}, until="2020-01-01")["made"] is False
    assert rules.propose(con, NOW, "pause_buys", "pause gold", {"scope": "class", "value": "gold"}, until="2031-01-01")["made"] is False


# --- the close reads the rules ---------------------------------------------------------------------------------------------------------------------------------------

def test_pause_gold_buys_the_next_close_buys_no_gold_and_says_why_and_undo_restores_it(con):
    r = make(con, "pause_buys", {"scope": "class", "value": "gold"}, "pause gold buys until 20 Nov", until="2026-11-20")
    out = loop.run(con, NOW, None, calm_index())
    assert out["status"] == "held" and gold_orders(con) == 0, out
    skipped = json.loads(con.execute("SELECT skipped_json FROM core_runs_s80 WHERE day=?", [DAY]).fetchone()[0])
    why = next(s["why"] for s in skipped if s["symbol"] == "GOLDBEES")
    assert why.startswith("not bought: your rule 'pause gold buys until 20 Nov'")                              # the rule's own words
    row = con.execute("SELECT rule_id, rule_name, site, side FROM rules_held_back_s85 WHERE symbol='GOLDBEES'").fetchone()
    assert row == (r["rule_id"], r["name"], "close", "buy")
    assert "pause gold buys until 20 Nov" in con.execute("SELECT note FROM core_runs_s80").fetchone()[0]       # the run's note carries it
    text = card.latest(con)
    assert "STANDING INSTRUCTIONS" in text and "pause gold buys until 20 Nov" in text and "held back today: buy GOLDBEES" in text
    assert "Held back by your rule 'pause gold buys until 20 Nov': 1 order(s) (GOLDBEES)." == rules_gate.report_line(con, DAY)
    assert rules.undo(con, r["rule_id"])["undone"]
    con.execute("DELETE FROM core_runs_s80 WHERE day=?", [DAY])                                                # the close after: Undo restores the old behaviour
    again = loop.run(con, NOW, None, calm_index())
    assert again["status"] == "traded" and gold_orders(con) == 1 and any(o["symbol"] == "GOLDBEES" for o in again["orders"])


def test_the_report_of_the_session_says_what_a_rule_held_back(con):
    make(con, "pause_buys", {"scope": "class", "value": "gold"}, "pause gold buys until 20 Nov", until="2026-11-20")
    loop.run(con, NOW, None, calm_index())
    assert "your rule 'pause gold buys until 20 Nov'" in core_session.report_day(con, DAY)


def test_no_new_names_stops_a_first_buy_but_not_a_name_already_held(con):
    make(con, "no_new_names", {}, "no new names this month")
    r = loop.run(con, NOW, None, calm_index())
    assert gold_orders(con) == 1, r                                                                           # gold is held already: more of it is not a new name
    assert con.execute("SELECT count(*) FROM rules_held_back_s85").fetchone()[0] == 0
    b = picks.propose(con, NOW, "IN", [{"symbol": "NASDAQ100X", "thesis": "x" * 80, "break_condition": "y" * 40}])
    assert b["refused"] and "no new names this month" in b["refused"][0]["reason"] or "ETF" in b["refused"][0]["reason"]
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES ('INE000C01013', 'isin', 'equity', 'EQUITY', TRUE, 'CCC', 'CCC Ltd', 'synthetic', now())")
    for d in DAYS[-5:]:
        con.execute("INSERT INTO prices VALUES ('INE000C01013', ?, 100.0, 'EQ', 'nse_bhavcopy', now())", [d])
    got = picks.propose(con, NOW, "IN", [{"symbol": "CCC", "thesis": "x" * 80, "break_condition": "y" * 40}])
    assert got["refused"] and "your rule 'no new names this month'" in got["refused"][0]["reason"] and not got["accepted"]


def test_a_new_name_is_held_back_at_the_close_by_no_new_names(con_nogold):
    con = con_nogold                                                                                          # gold is not held: its first buy would be a new name
    make(con, "no_new_names", {}, "no new names this month")
    out = loop.run(con, NOW, None, calm_index())
    assert gold_orders(con) == 0 and out["status"] == "held", out
    assert con.execute("SELECT rule_name, side FROM rules_held_back_s85").fetchone() == ("no_new_names_this_month", "buy")


def test_cash_floor_shrinks_buying_and_a_floor_above_the_cash_stops_it(con):
    make(con, "cash_floor", {"share_pct": 87}, "keep 87% in cash")
    out = loop.run(con, NOW, None, calm_index())
    spent = con.execute("SELECT amount, note FROM paper_orders WHERE isin=? AND side='buy'", [GLD]).fetchone()
    assert spent and spent[0] < 20000 and "your rule 'keep 87% in cash'" in con.execute("SELECT reason FROM paper_decisions").fetchone()[0], out
    assert con.execute("SELECT rule_name FROM rules_held_back_s85").fetchone()[0] == "keep_87_in_cash"
    con.execute("DELETE FROM paper_orders")
    con.execute("DELETE FROM core_runs_s80")
    rules.undo(con, rules.active(con)[0]["rule_id"])
    make(con, "cash_floor", {"share_pct": 89}, "keep 89% in cash")                                              # cash is 88.7% of the book: there is no room to buy at all
    out = loop.run(con, NOW, None, calm_index())
    assert out["status"] == "held" and gold_orders(con) == 0
    assert rules.cash_floor(con, DAY)["share"] == pytest.approx(0.89)


def test_hold_name_does_not_stop_a_stop_a_rail_trim_or_a_thesis_break_but_stops_a_target(con):
    exits.backfill_plans(con, DAY, "IN", NOW)
    px = book.close_on(con, AAA, DAY)[1]
    con.execute("UPDATE exit_plans_s81 SET stop=? WHERE isin=? AND status='open'", [px * 1.5, AAA])           # the close is far below the stop: it fires
    make(con, "hold_name", {"isin": AAA, "symbol": "AAA"}, "hold AAA, do not sell it")
    out = loop.run(con, NOW, None, calm_index())
    assert any(o["symbol"] == "AAA" and o["side"] == "sell" for o in out["orders"]), out                         # the stop still sells
    assert con.execute("SELECT count(*) FROM rules_held_back_s85 WHERE symbol='AAA'").fetchone()[0] == 0
    st = {"rows": [{"isin": AAA, "symbol": "AAA", "klass": "equity", "asset_class": "equity", "sleeve": "longterm", "qty": 300.0, "value": 1.0, "price": 1.0}], "value": 1e6, "cash": 0.0,
          "bank": 0.0, "cfg": {"rails": {"min_trade_rupees": 1000}}}
    chk = {"orders": [{"isin": AAA, "symbol": "AAA", "side": "sell", "qty": 10.0, "amount": None, "value": 5000.0, "kind": "target", "reason": "a take-profit"},
                      {"isin": AAA, "symbol": "AAA", "side": "sell", "qty": 10.0, "amount": None, "value": 5000.0, "kind": "thesis", "reason": "a thesis break"}], "skipped": []}
    res = rules_gate.apply_close(con, NOW, DAY, st, chk)
    assert [o["kind"] for o in res["orders"]] == ["thesis"] and res["skipped"][0]["why"].startswith("not sold: your rule 'hold AAA, do not sell it'")


def test_a_failure_reading_the_rules_holds_every_buy_and_never_lets_one_through(con, monkeypatch):
    monkeypatch.setattr(rules, "blocks", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("store busy")))
    out = loop.run(con, NOW, None, calm_index())
    assert gold_orders(con) == 0 and out["status"] == "held"


def test_the_session_loop_reads_the_rules_before_every_order(con):
    make(con, "pause_buys", {"scope": "class", "value": "gold"}, "pause gold buys")
    make(con, "hold_name", {"isin": AAA, "symbol": "AAA"}, "hold AAA")
    msg_buy = rules_gate.session_block(con, NOW, {"isin": GLD, "side": "buy", "kind": "entry", "amount": 10000.0, "reason": "x"}, "IN", 55.0)
    assert msg_buy and msg_buy.startswith("not bought: your rule 'pause gold buys'")
    assert rules_gate.session_block(con, NOW, {"isin": AAA, "side": "sell", "kind": "target", "qty": 5, "reason": "x"}, "IN", 100.0).startswith("not sold: your rule 'hold AAA'")
    assert rules_gate.session_block(con, NOW, {"isin": AAA, "side": "sell", "kind": "stop", "qty": 5, "reason": "x"}, "IN", 100.0) is None
    assert rules_gate.session_block(con, NOW, {"isin": BBB, "side": "buy", "kind": "entry", "amount": 10000.0, "reason": "x"}, "IN", 55.0) is None
    assert con.execute("SELECT count(*) FROM rules_held_back_s85 WHERE site='session'").fetchone()[0] == 2
    ctx = {"quotes": {GLD: 55.0}, "breaker": {}, "cfg": {"no_entry_minutes": 0}, "minutes_in": 60, "root": None}
    res = {"blocked": [], "fills": [], "queued": []}
    assert core_session._carry_out(con, NOW, {"market": "IN", "isin": GLD, "side": "buy", "qty": 10, "kind": "view", "reason": "tactical view"}, ctx, res) is None
    assert res["blocked"][0]["why"].startswith("not bought: your rule 'pause gold buys'")


def test_the_us_step_reads_the_rules(con):
    make(con, "pause_buys", {"scope": "class", "value": "international", "market": "US"}, "pause US buying")
    make(con, "hold_name", {"isin": "ZZ0000320193", "symbol": "AAPL", "market": "US"}, "hold AAPL")
    orders = [{"isin": "ZZ0000320193", "symbol": "AAPL", "side": "sell", "qty": 1.0, "amount": None, "value": 190.0, "note": "", "reason": "rebalance"},
              {"isin": "ZZ0000789019", "symbol": "MSFT", "side": "buy", "qty": None, "amount": 500.0, "value": 500.0, "note": "", "reason": "rebalance"},
              {"isin": "ZZ0000789019", "symbol": "MSFT", "side": "sell", "qty": 1.0, "amount": None, "value": 400.0, "note": "capped at 10.0% (rail 10%)", "reason": "rail"}]
    kept, lines = rules_gate.apply_us(con, NOW, NOW.date(), orders)
    assert [(o["symbol"], o["side"]) for o in kept] == [("MSFT", "sell")] and len(lines) == 2                   # the rail trim passes
    assert lines[0].startswith("not sold: your rule 'hold AAPL'") and lines[1].startswith("not bought: your rule 'pause US buying'")
    assert con.execute("SELECT count(*) FROM rules_held_back_s85 WHERE market='US'").fetchone()[0] == 2


# --- the intake: his words -> a typed rule ---------------------------------------------------------------------------------------------------------------------------

def test_pause_gold_buys_till_20_nov_is_parsed_made_and_acts_at_once(con):
    call = says(kind="pause_buys", scope="class", value="Gold", until="2026-11-20")
    p = rules_intake.parse(con, NOW, "pause gold buys till 20 Nov", gateway_call=call)
    assert not p["refused"] and p["kind"] == "pause_buys" and p["params"] == {"scope": "class", "value": "gold"} and p["until"] == date(2026, 11, 20) and p["needs_yes"] is False
    assert p["summary"] == "pause gold buys until 20 Nov" and rules.active(con) == []                           # parse alone writes nothing
    r = rules_intake.standing_instruction(con, NOW, "pause gold buys till 20 Nov", gateway_call=call)
    assert r["made"] and r["rule_id"] and "Undo" in r["message"] and "until 20 Nov" in r["message"] and r["until_defaulted"] is False
    assert rules.blocks(con, NOW.date(), cls="gold", action="buy")["text"] == "pause gold buys until 20 Nov"
    assert "Today is" in call.seen[0][0] and "pause_buys" in call.seen[0][0]                                    # the model is told today's date and the kinds


def test_code_reads_the_date_when_the_model_gives_none_and_defaults_to_thirty_days_when_nobody_does(con):
    p = rules_intake.parse(con, NOW, "pause gold buys till 20 Nov", gateway_call=says(kind="pause_buys", scope="class", value="gold"))
    assert p["until"] == date(2026, 11, 20) and p["until_defaulted"] is False
    p = rules_intake.parse(con, NOW, "pause gold buys till 5 Oct", gateway_call=says(kind="pause_buys", scope="class", value="gold"))      # a day and month already past mean next year
    assert p["until"] == date(2027, 10, 5)
    p = rules_intake.parse(con, NOW, "pause gold buys for now", gateway_call=says(kind="pause_buys", scope="class", value="gold"))
    assert p["until"] == NOW.date() + timedelta(days=30) and p["until_defaulted"] is True
    r = rules_intake.standing_instruction(con, NOW, "pause gold buys for now", gateway_call=says(kind="pause_buys", scope="class", value="gold"))
    assert "you gave no end date: I used 30 days" in r["message"]
    p = rules_intake.parse(con, NOW, "pause gold buys", gateway_call=says(kind="pause_buys", scope="class", value="gold", until="2026-10-01"))
    assert p["refused"] and "already past" in p["reason"]


def test_names_are_resolved_to_isins_by_code_never_by_the_model(con):
    p = rules_intake.parse(con, NOW, "do not sell AAA", gateway_call=says(kind="hold_name", name="aaa", summary="x"))
    assert p["params"] == {"isin": AAA, "symbol": "AAA"}
    p = rules_intake.parse(con, NOW, "do not sell Goldbees", gateway_call=says(kind="hold_name", name="Goldbees"))
    assert p["params"]["isin"] == GLD
    p = rules_intake.parse(con, NOW, "do not sell Zorp Industries", gateway_call=says(kind="hold_name", name="Zorp Industries"))
    assert p["refused"] and "do not know a listed name 'Zorp Industries'" in p["reason"]
    p = rules_intake.parse(con, NOW, "pause buying ltd", gateway_call=says(kind="pause_buys", scope="name", name="Ltd"))
    assert p["refused"] and "could be" in p["reason"] and "say which one" in p["reason"]                        # more than one match: ask


def test_a_class_outside_the_books_list_is_refused_and_a_synonym_is_read(con):
    p = rules_intake.parse(con, NOW, "pause crypto buys", gateway_call=says(kind="pause_buys", scope="class", value="crypto"))
    assert p["refused"] and "the class is one of" in p["reason"]
    p = rules_intake.parse(con, NOW, "pause nasdaq buys", gateway_call=says(kind="pause_buys", scope="class", value="nasdaq"))
    assert p["params"]["value"] == "international"


def test_a_cash_floor_takes_only_a_number_he_wrote(con):
    p = rules_intake.parse(con, NOW, "keep 15% of the book in cash", gateway_call=says(kind="cash_floor", share_pct=15))
    assert p["params"] == {"share_pct": 15.0} and not p["refused"]
    p = rules_intake.parse(con, NOW, "keep some cash in reserve", gateway_call=says(kind="cash_floor", share_pct=20))
    assert p["refused"] and "not in what you wrote" in p["reason"]                                                # a number the model made up


@pytest.mark.parametrize("words", ["turn off the circuit breaker", "ignore the 10% rail on AAA", "disable the kill switch", "remove the stop loss on BBB", "switch off the guards for a week"])
def test_a_rule_that_loosens_a_rail_the_kill_switch_or_a_stop_is_refused_with_the_reason(con, words):
    call = says(kind="pause_buys", scope="all")                                                                  # even a model that sees nothing wrong is overruled by code
    r = rules_intake.standing_instruction(con, NOW, words, gateway_call=call)
    assert r["refused"] and r["made"] is False and ("tighten" in r["reason"] or "kill switch" in r["reason"]) and call.seen == []
    assert rules.active(con) == [] and rules.pending(con) == []


def test_the_models_own_loosening_flag_and_a_looser_position_limit_are_refused(con):
    r = rules_intake.standing_instruction(con, NOW, "let me hold more in one share", gateway_call=says(kind="max_position", max_weight_pct=15, loosens=True))
    assert r["refused"] and "only tighten" in r["reason"]
    r = rules_intake.standing_instruction(con, NOW, "no holding above 15% of the book", gateway_call=says(kind="max_position", max_weight_pct=15))
    assert r["refused"] and "company rail is 10%" in r["reason"]
    r = rules_intake.standing_instruction(con, NOW, "no holding above 8% of the book", gateway_call=says(kind="max_position", max_weight_pct=8))
    assert not r["refused"] and r["needs_yes"] and r["state"] == "waiting_yes"                                     # tighter: but it is a limit, so it waits for his yes


def test_a_money_rule_waits_for_his_yes_and_is_applied_only_on_it(con):
    call = says(kind="monthly_envelope", amount_rupees=50000, carry_over=True, until="2027-01-31")
    r = rules_intake.standing_instruction(con, NOW, "I invest Rs 50,000 a month till January, unspent carries over", gateway_call=call)
    assert r["made"] and r["needs_yes"] and r["state"] == "waiting_yes" and "waits for your Yes" in r["message"]
    assert rules.active(con) == [] and len(rules.pending(con)) == 1
    r2 = rules_intake.standing_instruction(con, NOW, "I invest Rs 50,000 a month", gateway_call=says(kind="monthly_envelope", amount_rupees=60000))
    assert r2["refused"] and "not in what you wrote" in r2["reason"]
    assert rules.decide(con, NOW, r["rule_id"], True)["status"] == "active" and len(rules.active(con)) == 1


def test_change_my_target_becomes_a_yes_no_question_and_nothing_changes_without_yes(con, tmp_path):
    tg = tmp_path / "targets.toml"
    tg.write_text("[bucket.equity]\ntarget = 0.5\n", encoding="utf-8")
    call = says(kind="change_request", change_kind="targets", change_key="", change_value='{"equity": 0.55}')
    p = rules_intake.parse(con, NOW, "change my target for equity to 55%", gateway_call=call)
    assert p["needs_yes"] and p["kind"] == "change_request" and not p["refused"] and "nothing has changed" in p["reason"]
    assert con.execute("SELECT count(*) FROM rules_requests_s85").fetchone()[0] == 0                              # checking writes nothing
    r = rules_intake.standing_instruction(con, NOW, "change my target for equity to 55%", gateway_call=call)
    assert r["made"] and r["state"] == "waiting_yes" and r["question_id"] and r["proposal_id"] and "waits for your Yes or No" in r["message"]
    q = con.execute("SELECT status, text FROM questions WHERE q_id=?", [r["question_id"]]).fetchone()
    assert q[0] == "open" and "target weights" in q[1] and "55%" in q[1]
    assert con.execute("SELECT status FROM limit_proposals WHERE prop_id=?", [r["proposal_id"]]).fetchone()[0] == "pending"
    assert tg.read_text(encoding="utf-8") == "[bucket.equity]\ntarget = 0.5\n" and rules.active(con) == []     # nothing changed
    again = rules_intake.standing_instruction(con, NOW, "change my target for equity to 55%", gateway_call=call)
    assert again["duplicate"] is True and "already waiting" in again["message"]
    bad = rules_intake.parse(con, NOW, "make equity 70%", gateway_call=says(kind="change_request", change_kind="targets", change_value='{"equity": 0.55}'))
    assert bad["refused"] and "not a number you wrote" in bad["reason"]                                            # the weight must be his own number


def test_an_unfit_sentence_becomes_a_note_the_strategist_reads_once(con):
    r = rules_intake.standing_instruction(con, NOW, "I would rather the system were boring in an election month", gateway_call=says(kind="note"))
    assert r["kind"] == "note" and r["made"] and r["note_id"] and "kept it as a note" in r["message"] and rules.active(con) == []
    r2 = rules_intake.standing_instruction(con, NOW, "what is the weather", gateway_call=says(kind="none"))
    assert r2["kind"] == "note" and not r2["refused"]
    assert [n["text"] for n in rules_intake.unread_notes(con)][0].startswith("I would rather the system were boring")
    from pflab.lab import strategist
    first = strategist._first_message(con, "weekly", 100.0, NOW)
    assert "HIS NOTES TO YOU" in first and "boring in an election month" in first and "what is the weather" in first
    assert rules_intake.unread_notes(con) == []                                                                      # marked read
    assert "HIS NOTES TO YOU" not in strategist._first_message(con, "weekly", 100.0, NOW)


def test_the_strategist_is_told_the_rules_in_force(con):
    make(con, "pause_buys", {"scope": "class", "value": "gold"}, "pause gold buys until 20 Nov", until="2026-11-20")
    from pflab.lab import strategist
    assert "HOUSE RULES" in strategist._first_message(con, "weekly", 100.0, NOW) and "pause gold buys until 20 Nov" in strategist._first_message(con, "weekly", 100.0, NOW)


def test_the_gateway_failing_or_answering_nonsense_changes_nothing(con):
    def down(system, messages, schema):
        raise RuntimeError("API down")
    r = rules_intake.standing_instruction(con, NOW, "pause gold buys", gateway_call=down)
    assert r["refused"] and "nothing was changed" in r["reason"] and rules.active(con) == []
    r = rules_intake.standing_instruction(con, NOW, "pause gold buys", gateway_call=lambda s, m, sc: "no json here")
    assert r["refused"] and rules.active(con) == []


def test_the_same_instruction_twice_is_one_rule(con):
    call = says(kind="pause_buys", scope="class", value="gold", until="2026-11-20")
    a = rules_intake.standing_instruction(con, NOW, "pause gold buys till 20 Nov", gateway_call=call)
    b = rules_intake.standing_instruction(con, NOW, "pause gold buys till 20 Nov", gateway_call=call)
    assert a["made"] and b["refused"] and b["duplicate"] and len(rules.active(con)) == 1


def test_the_chat_tool_is_defined_and_runs(con):
    assert rules_intake.TOOL["name"] == "standing_instruction" and rules_intake.TOOL["input_schema"]["required"] == ["text"]
    r = rules_intake.run_tool(con, NOW, {"text": "keep 10% in cash"}, gateway_call=says(kind="cash_floor", share_pct=10))
    assert r["made"] and r["kind"] == "cash_floor" and rules.cash_floor(con, NOW.date())["share"] == pytest.approx(0.10)
    u = rules_intake.undo_by_words(con, NOW, r["rule_id"])
    assert u["undone"] and "Undone" in u["message"] and rules.cash_floor(con, NOW.date()) is None
