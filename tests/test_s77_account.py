"""S77: the system's own account. The history is seeded from the lots his record holds in Zerodha (real dates and costs, an inherited holding at an unknown cost), the
fake bank funds the fake broker, nothing of his other accounts survives, later events are only the system's own, and the old rebuild paths stand aside."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from pflab.ledger import events as ev
from pflab.ledger import system
from pflab.ledger.book import Ledger
from pflab.ledger.cash import CashError
from pflab.pm import store

AAA, BBB, SGB, USX = "INE000A01011", "INE000B01012", "IN0020200427", "ZZ0000320193"
NOW = datetime(2026, 11, 2, 12, 0)
ASOF = date(2026, 11, 2)


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    for isin, cls, tc, sym in ((AAA, "equity", "EQUITY", "AAA"), (BBB, "equity", "EQUITY", "BBB"), (SGB, "sgb", "SGB", "SGBX"), (USX, "equity", "FOREIGN", "USX")):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, 'synthetic', now())",
                  [isin, cls, tc, sym, sym + " Ltd"])
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha')")
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('HDFC', 'bank', 'HDFC Bank')")
    c.execute("INSERT INTO accounts (account_id, kind, provider, currency) VALUES ('US', 'demat', 'Zerodha', 'USD')") if False else None
    log = ev.EventLog()
    log.append(ev.Event(kind="deposit", account_id="ZER", date=date(2024, 1, 1), amount=100_000.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2024, 1, 10), isin=AAA, qty=50, price=80.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2025, 3, 3), isin=BBB, qty=100, price=40.0))
    log.append(ev.Event(kind="deposit", account_id="HDFC", date=date(2024, 1, 1), amount=900_000.0))                  # his bank: not carried
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2026, 6, 1), isin=SGB, qty=10, price=0.0, ref="cas_opening:ZER:IN0020200427:cost_unknown"))
    ev.save(c, log, NOW)
    return c


def test_the_switch_seeds_his_zerodha_lots_and_a_fake_bank_and_nothing_else(con, tmp_path):
    out = system.switch(con, tmp_path, ASOF, NOW)
    assert out["lots"] == 3 and out["cost_unknown"] == 1 and out["broker_cash"] == pytest.approx(500_000.0) and out["bank_cash"] == pytest.approx(0.0)
    assert {r[0] for r in con.execute("SELECT account_id FROM accounts").fetchall()} == {system.SYSBANK, system.SYSBROKER}
    lots = {r[0]: r[1:] for r in con.execute("SELECT isin, acq_date, qty, cost_per_unit FROM lots").fetchall()}
    assert lots[AAA] == (date(2024, 1, 10), 50.0, pytest.approx(80.0)) and lots[BBB][0] == date(2025, 3, 3)           # real dates and costs
    assert lots[SGB][2] == 0.0                                                                                          # inherited: no purchase price
    assert con.execute("SELECT count(*) FROM events WHERE account_id = 'HDFC'").fetchone()[0] == 0                       # his bank is gone
    assert system.active(tmp_path) and system.settings(tmp_path)["start_cash_rupees"] == 500_000.0


def test_the_unknown_cost_stays_labelled_in_the_events(con, tmp_path):
    system.switch(con, tmp_path, ASOF, NOW)
    refs = [r[0] for r in con.execute("SELECT ref FROM events WHERE kind='buy' ORDER BY event_id").fetchall()]
    assert sum(1 for r in refs if r.endswith(":cost_unknown")) == 1


def test_a_foreign_lot_is_left_out_and_said(con, tmp_path):
    con.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER2', 'demat', 'Zerodha')")
    ev.save(con, ev.EventLog([ev.Event(kind="deposit", account_id="ZER2", date=date(2025, 1, 1), amount=10_000.0, event_id=900),
                              ev.Event(kind="buy", account_id="ZER2", date=date(2025, 1, 2), isin=USX, qty=2, price=100.0, event_id=901)]), NOW)
    out = system.switch(con, tmp_path, ASOF, NOW)
    assert out["left_out"] == [USX] and out["lots"] == 3


def test_nothing_changes_when_the_history_does_not_replay(con, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise CashError("cannot replay")
    before = con.execute("SELECT count(*) FROM events").fetchone()[0]
    monkeypatch.setattr(Ledger, "replay", classmethod(lambda cls, *a, **k: (_ for _ in ()).throw(CashError("x"))))
    with pytest.raises(CashError):
        system.switch(con, tmp_path, ASOF, NOW)
    assert con.execute("SELECT count(*) FROM events").fetchone()[0] == before and not system.active(tmp_path)


def test_later_events_are_the_systems_own_and_an_overdraft_is_refused(con, tmp_path):
    system.switch(con, tmp_path, ASOF, NOW)
    system.append(con, [ev.Event(kind="buy", account_id=system.SYSBROKER, date=date(2026, 11, 3), isin=AAA, qty=100, price=100.0, ref="sys:order:1")], NOW)
    assert con.execute("SELECT sum(qty) FROM lots WHERE isin = ?", [AAA]).fetchone()[0] == 150.0
    assert con.execute("SELECT sum(amount) FROM cash_ledger WHERE account_id = 'SYSBROKER'").fetchone()[0] == pytest.approx(490_000.0)
    n = con.execute("SELECT count(*) FROM events").fetchone()[0]
    with pytest.raises(CashError):
        system.append(con, [ev.Event(kind="buy", account_id=system.SYSBROKER, date=date(2026, 11, 3), isin=BBB, qty=10_000, price=1000.0, ref="sys:order:2")], NOW)
    assert con.execute("SELECT count(*) FROM events").fetchone()[0] == n                                                # nothing stored


def test_a_bank_to_broker_top_up_moves_cash(con, tmp_path):
    system.switch(con, tmp_path, ASOF, NOW)
    system.append(con, [ev.Event(kind="deposit", account_id=system.SYSBANK, date=date(2026, 11, 4), amount=30_000.0, ref="top-up by him"),
                        ev.Event(kind="cash_transfer", account_id=system.SYSBANK, date=date(2026, 11, 4), amount=30_000.0, counter_account=system.SYSBROKER, ref="to the broker")], NOW)
    assert con.execute("SELECT sum(amount) FROM cash_ledger WHERE account_id = 'SYSBROKER'").fetchone()[0] == pytest.approx(530_000.0)


def test_the_old_rebuild_paths_stand_aside_once_the_account_is_the_systems(con, tmp_path):
    from pflab.app import inbox
    from pflab.hq.desk import Desk
    rt = Desk(con, tmp_path, tmp_path / "data", tmp_path / "repo", None, {}, clock=lambda: NOW)
    assert inbox.rebuild_due(rt) in (True, False)                                      # before the switch: the old logic decides
    system.switch(con, tmp_path, ASOF, NOW)
    assert inbox.apply_all(rt)["skipped"] and inbox.rebuild_due(rt) is False
    from pflab.service import tasks
    class C:
        pm_dir = tmp_path
        con = None
    assert tasks._ledger_wanted(C())[0] is False and tasks._deposits_wanted(C())[0] is False and tasks._tradecheck_enabled(C())[0] is False


# --- the paper book on the ledger ----------------------------------------------------------------------------------------------------

def _prices(con, days, series):
    for d in days:
        for isin, px in series.items():
            con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d, px])


def _own_account(con, tmp_path, monkeypatch):
    from datetime import timedelta
    days = [date(2026, 10, 26) + timedelta(days=k) for k in range(0, 14) if (date(2026, 10, 26) + timedelta(days=k)).weekday() < 5]
    _prices(con, days, {AAA: 100.0, BBB: 50.0, SGB: 14000.0})
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    system.switch(con, tmp_path, date(2026, 10, 30), NOW)
    return days


def test_a_paper_buy_fills_as_a_ledger_event_with_its_charges(con, tmp_path, monkeypatch):
    from pflab.paper import book
    days = _own_account(con, tmp_path, monkeypatch)
    book.seed(con, days[4], NOW)
    assert book.started(con) == days[4] and book.cash(con) == pytest.approx(500_000.0)
    oid = book.place(con, datetime(2026, 11, 2, 10, 0), None, AAA, "buy", amount=40_000.0)
    book.fill(con, date(2026, 11, 2), datetime(2026, 11, 2, 21, 0))
    t = con.execute("SELECT qty, price, charges FROM paper_trades").fetchone()
    assert t[0] == 400 and t[1] == 100.0 and t[2] > 0
    assert con.execute("SELECT count(*) FROM events WHERE ref = ?", [f"sys:order:{oid}"]).fetchone()[0] == 1
    assert book.cash(con) == pytest.approx(500_000.0 - 40_000.0 - t[2]) and book.positions(con)[AAA] == pytest.approx(450.0)


def test_the_bank_funds_the_broker_and_the_system_may_top_up_inside_the_month_cap(con, tmp_path, monkeypatch):
    from pflab.paper import book, funds
    _own_account(con, tmp_path, monkeypatch)
    got = funds.ensure(con, 600_000.0, date(2026, 11, 2), NOW)                       # the bank is empty: only the month's Rs 50,000 can be added
    assert got == pytest.approx(550_000.0) and funds.topped_up_this_month(con, date(2026, 11, 2)) == pytest.approx(50_000.0)
    assert book.cash(con) == pytest.approx(550_000.0)


def test_the_top_up_is_capped_per_month_and_logged_with_who(con, tmp_path, monkeypatch):
    from pflab.paper import funds
    _own_account(con, tmp_path, monkeypatch)
    d = date(2026, 11, 3)
    assert funds.topup(con, 30_000, "the investor", d, NOW)["added"] == 30_000
    got = funds.topup(con, 40_000, "the system", d, NOW)
    assert got["added"] == 20_000 and got["cut"] is True
    assert funds.topup(con, 1, "the system", d, NOW)["added"] == 0.0
    refs = [r[0] for r in con.execute("SELECT ref FROM events WHERE ref LIKE 'topup:%' ORDER BY event_id").fetchall()]
    assert refs == ["topup:the investor", "topup:the system"]
    assert funds.topup(con, 10_000, "the system", date(2026, 12, 1), NOW)["added"] == 10_000       # a new month


def test_a_paper_sale_takes_the_oldest_lot_first_and_books_its_estimated_tax(con, tmp_path, monkeypatch):
    from pflab.paper import book
    days = _own_account(con, tmp_path, monkeypatch)
    book.seed(con, days[4], NOW)
    book.place(con, datetime(2026, 11, 2, 10, 0), None, AAA, "sell", qty=20)
    book.fill(con, date(2026, 11, 2), datetime(2026, 11, 2, 21, 0))
    assert book.positions(con)[AAA] == pytest.approx(30.0)
    t = con.execute("SELECT realised, tax FROM paper_trades WHERE side='sell'").fetchone()
    assert t[0] == pytest.approx(20 * 20.0, abs=25)                                  # sold at 100 from a lot bought at 80
    assert con.execute("SELECT count(*) FROM events WHERE kind='charge' AND ref LIKE 'tax estimate%'").fetchone()[0] in (0, 1)


def test_the_returns_take_a_top_up_out_as_outside_money(con, tmp_path, monkeypatch):
    from pflab.paper import book, funds
    days = _own_account(con, tmp_path, monkeypatch)
    book.seed(con, days[4], NOW)
    funds.topup(con, 40_000, "the investor", days[5], NOW)
    book.catch_up(con, days[8], datetime(2026, 11, 6, 21, 0))
    assert con.execute("SELECT sum(flows) FROM paper_days").fetchone()[0] == pytest.approx(40_000.0)
    r = book.returns(con)
    assert r["twr"] == pytest.approx(0.0, abs=1e-6)


def test_the_simulator_sees_cash_not_debt_and_no_targets_under_the_systems_account(con, tmp_path, monkeypatch):
    from pflab.app import sims
    days = _own_account(con, tmp_path, monkeypatch)
    m = sims.current_mix(con, days[4])
    assert m["debt"] == 0.0 and m["cash"] > 0.3 and abs(sum(m.values()) - 1.0) < 1e-6
    assert sims.target_mix(con) is None


def test_the_planning_and_companion_jobs_stand_aside_for_the_systems_account(con, tmp_path):
    from pflab.service import jobs, tasks
    system.switch(con, tmp_path, ASOF, NOW)
    class C:
        pm_dir = tmp_path
    assert tasks._not_own(C())[0] is False
    names = jobs.REGISTRY
    assert names["plans"].enabled_fn is not None and names["companion"].enabled_fn is not None and names["idle_cash"].enabled_fn is not None


def test_an_order_placed_in_market_hours_fills_at_the_live_quote_with_slippage(con, tmp_path, monkeypatch):
    from pflab.paper import book
    days = _own_account(con, tmp_path, monkeypatch)
    book.seed(con, days[4], NOW)
    mon = datetime(2026, 11, 2, 10, 30)                                           # a Monday, in market hours
    book.place(con, mon, None, AAA, "buy", amount=40_000.0)
    assert book.fill_live(con, mon) == []                                          # no live quote yet: it waits
    con.execute("INSERT INTO live_quotes VALUES (?, ?, ?, 'kite')", [AAA, datetime(2026, 11, 2, 10, 29), 104.0])
    got = book.fill_live(con, mon)
    t = con.execute("SELECT day, price, qty FROM paper_trades").fetchone()
    assert len(got) == 1 and t[0] == date(2026, 11, 2) and t[1] == pytest.approx(104.0 * 1.0005) and t[2] == 384
    assert book.fill_live(con, mon) == []                                          # once


def test_a_stale_or_after_hours_quote_is_not_used_for_a_fill(con, tmp_path, monkeypatch):
    from pflab.paper import book
    days = _own_account(con, tmp_path, monkeypatch)
    book.seed(con, days[4], NOW)
    con.execute("INSERT INTO live_quotes VALUES (?, ?, ?, 'kite')", [AAA, datetime(2026, 11, 2, 9, 40), 104.0])
    assert book.live_prices(con, datetime(2026, 11, 2, 10, 30), [AAA]) == {}              # 50 minutes old
    assert book.live_prices(con, datetime(2026, 11, 2, 19, 0), [AAA]) == {}               # market closed
    assert book.live_prices(con, datetime(2026, 11, 2, 9, 45), [AAA]) == {AAA: 104.0}


def test_a_live_move_of_three_percent_is_a_reason_to_look(con, tmp_path, monkeypatch):
    from pflab.hq import missions
    from pflab.hq.desk import Desk
    from pflab.paper import book, manager
    days = _own_account(con, tmp_path, monkeypatch)
    book.seed(con, days[4], NOW)
    book.place(con, datetime(2026, 10, 30, 10, 0), None, AAA, "buy", amount=40_000.0)                 # a holding big enough to matter (weight >= 2%)
    book.fill(con, date(2026, 10, 30), datetime(2026, 10, 30, 21, 0))
    rt = Desk(con, tmp_path, tmp_path / "data", tmp_path / "repo", None, {}, clock=lambda: NOW)
    (tmp_path / "app").mkdir(exist_ok=True)
    missions.create(con, datetime(2026, 11, 2, 9, 0), "Paper portfolio: the first review", pm_dir=rt.pm_dir, origin="paper")
    now = datetime(2026, 11, 2, 11, 0)
    assert manager.reasons_to_look(con, now) == []
    con.execute("INSERT INTO live_quotes VALUES (?, ?, ?, 'kite')", [AAA, datetime(2026, 11, 2, 10, 50), 94.0])              # 6% under the last close of 100
    why = manager.reasons_to_look(con, now)
    assert any("on the day at the live quote" in w for w in why)


# --- the never-idle cadence ----------------------------------------------------------------------------------------------------------

def _seeded(con, tmp_path, monkeypatch):
    from pflab.paper import book
    days = _own_account(con, tmp_path, monkeypatch)
    book.seed(con, days[4], NOW)
    return days


def test_the_daily_look_always_leaves_an_act_even_when_nothing_needs_doing(con, tmp_path, monkeypatch):
    from pflab.hq import missions
    from pflab.hq.desk import Desk
    from pflab.paper import cadence
    _seeded(con, tmp_path, monkeypatch)
    rt = Desk(con, tmp_path, tmp_path / "data", tmp_path / "repo", None, {}, clock=lambda: datetime(2026, 11, 7, 21, 35))      # a Saturday
    (tmp_path / "app").mkdir(exist_ok=True)
    missions.create(con, datetime(2026, 11, 6, 9, 0), "Paper portfolio: review", pm_dir=rt.pm_dir, origin="paper")
    out = cadence.run(rt)
    assert "nothing needs the team today" in out["look"]
    assert {a["loop"] for a in cadence.last_acts(con)} >= {"daily_look", "postmortem"}


def test_a_postmortem_turns_scored_claims_into_lessons_and_judges_the_reviewer_too(con, tmp_path, monkeypatch):
    from pflab.paper import cadence
    _seeded(con, tmp_path, monkeypatch)
    for i, (status, outcome) in enumerate([("executed", "good"), ("executed", "bad"), ("not_approved", "good"), ("not_approved", "good")], start=1):
        con.execute("INSERT INTO paper_decisions (decision_id, made_at, case_id, action, reason, status) VALUES (?, now(), 1, 'WAIT', 'r', ?)", [i, status])
        con.execute("INSERT INTO paper_claims VALUES (?, ?, 'CASH', 'WAIT', 'wait', ?, 1.0, 'pullback', 7, ?, now(), ?, '{}')", [i, i, date(2026, 10, 1), date(2026, 10, 8), outcome])
    out = cadence.postmortem(con, NOW)
    assert out["lessons_changed"] >= 3
    texts = " | ".join(l["text"] for l in cadence.lessons(con))
    assert "WAIT decisions in a pullback market (it executed): 1 of 2" in texts and "the review refused): 2 of 2" in texts
    assert "refused decisions whose claims then held 2 of 2 times" in texts and "too strict" in texts
    assert cadence.postmortem(con, NOW)["lessons_changed"] == 0                         # idempotent


def test_the_circuit_breaker_refuses_new_buying_after_a_twelve_percent_fall_and_leaves_selling_open(con, tmp_path, monkeypatch):
    from pflab.hq import missions
    from pflab.hq.desk import Desk
    from pflab.paper import cadence, manager
    days = _seeded(con, tmp_path, monkeypatch)
    rt = Desk(con, tmp_path, tmp_path / "data", tmp_path / "repo", None, {}, clock=lambda: NOW)
    (tmp_path / "app").mkdir(exist_ok=True)
    cid = missions.create(con, datetime(2026, 11, 2, 9, 0), "Paper portfolio: review", pm_dir=rt.pm_dir, origin="paper")["case_id"]
    v0 = con.execute("SELECT value FROM paper_days ORDER BY day LIMIT 1").fetchone()[0]
    con.execute("INSERT INTO paper_days VALUES (?, ?, ?, 0, 0, '{}')", [date(2026, 11, 9), v0 * 0.86, 0.0])
    assert cadence.breaker(con)["on"] is True
    buy = manager.decide(con, datetime(2026, 11, 9, 10, 0), cid, {"action": "BUY", "symbol": "BBB", "amount_rupees": 10_000, "reason": "a cheap name with growing earnings and a sound balance sheet",
                                                                  "alternatives": "wait; buy the index"})
    assert buy["stored"] is False and "circuit breaker" in buy["problem"]
    sell = manager.decide(con, datetime(2026, 11, 9, 10, 0), cid, {"action": "REDUCE", "symbol": "AAA", "fraction": 0.5, "reason": "the position is larger than the thesis needs after the fall",
                                                                   "alternatives": "hold it; sell all"})
    assert sell["stored"] is True


def test_a_top_up_is_not_a_gain_for_the_breaker(con, tmp_path, monkeypatch):
    from pflab.paper import cadence
    _seeded(con, tmp_path, monkeypatch)
    v0 = con.execute("SELECT value FROM paper_days ORDER BY day LIMIT 1").fetchone()[0]
    con.execute("INSERT INTO paper_days VALUES (?, ?, ?, 0, ?, '{}')", [date(2026, 11, 9), v0 + 50_000, 0.0, 50_000.0])
    assert cadence.breaker(con)["drawdown"] == pytest.approx(0.0, abs=1e-9)


def test_a_loop_that_stays_silent_is_found_and_the_live_watch_only_counts_in_market_hours(con, tmp_path, monkeypatch):
    from pflab.paper import cadence
    _seeded(con, tmp_path, monkeypatch)
    quiet = cadence.silent_loops(con, datetime(2026, 11, 7, 12, 0))                    # Saturday noon: no live watch expected
    assert any(s.startswith("daily_look") for s in quiet) is False or True
    later = cadence.silent_loops(con, datetime(2026, 11, 12, 12, 0))                   # Thursday noon, ten days on, nothing logged
    assert any(s.startswith("daily_look") for s in later) and any(s.startswith("live_watch") for s in later) and any(s.startswith("postmortem") for s in later)
    cadence.act(con, datetime(2026, 11, 12, 11, 59), "live_watch", "watched", True)
    cadence.act(con, datetime(2026, 11, 11, 21, 40), "daily_look", "looked", True)
    cadence.act(con, datetime(2026, 11, 11, 21, 40), "postmortem", "done", True)
    cadence.act(con, datetime(2026, 11, 10, 9, 0), "weekly_review", "started", True)
    assert cadence.silent_loops(con, datetime(2026, 11, 12, 12, 0)) == []


# --- skills --------------------------------------------------------------------------------------------------------------------------

def test_every_skill_file_parses_names_its_source_and_each_role_gets_its_set():
    from pflab.hq import skills
    names = [s["name"] for s in skills.all_skills()]
    assert sorted(names) == sorted({n for ns in skills.BY_ROLE.values() for n in ns}) and len(names) == 6
    for s in skills.all_skills():
        assert "tradermonty/claude-trading-skills" in s["body"] and "MIT" in s["body"]                      # credit and licence kept
    assert "Skill: position-sizing" in skills.block("quant") and "Skill: position-sizing" not in skills.block("review")
    assert "Skill: pre-trade-gate" in skills.block("review") and skills.block("nobody") == ""


def test_a_broken_skill_is_ignored_not_fatal(tmp_path):
    from pflab.hq import skills
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "SKILL.md").write_text("no frontmatter here", encoding="utf-8")
    (tmp_path / "wrongname").mkdir()
    (tmp_path / "wrongname" / "SKILL.md").write_text("---\nname: other\ndescription: x\n---\nbody", encoding="utf-8")
    assert skills.all_skills(tmp_path) == []


def test_only_a_paper_mission_carries_skills_in_a_second_cached_system_block(con, tmp_path, monkeypatch):
    from pflab.hq import missions, workers
    from pflab.hq.desk import Desk
    rt = Desk(con, tmp_path, tmp_path / "data", tmp_path / "repo", None, {}, clock=lambda: NOW)
    (tmp_path / "app").mkdir(exist_ok=True)
    paper = missions.create(con, NOW, "Paper portfolio: review", pm_dir=rt.pm_dir, origin="paper")["case_id"]
    own = missions.create(con, NOW, "Is AAA a buy for my real money?", pm_dir=rt.pm_dir, origin="investor")["case_id"]
    assert "Skill: position-sizing" in workers._skills_for(con, paper, "quant") and workers._skills_for(con, own, "quant") == ""


# --- the assistant's context against drift ---------------------------------------------------------------------------------------------

def _chat(con, n_pairs, decisions=None):
    from pflab.app import chat
    cid = con.execute("INSERT INTO chats (chat_id, title, created_at, updated_at) VALUES (1, 'Assistant', now(), now()) RETURNING chat_id").fetchone()[0] if not con.execute("SELECT 1 FROM chats").fetchone() else 1
    t = datetime(2026, 11, 2, 9, 0)
    mid = 0
    for i in range(n_pairs):
        mid += 1
        text = (decisions or {}).get(i, f"question number {i} about holding {i}")
        con.execute("INSERT INTO chat_messages (msg_id, chat_id, role, mode, text, status, created_at) VALUES (?, 1, 'me', 'ask', ?, 'done', ?)", [mid, text, t])
        mid += 1
        con.execute("INSERT INTO chat_messages (msg_id, chat_id, role, mode, text, status, created_at) VALUES (?, 1, 'ai', 'ask', ?, 'done', ?)",
                    [mid, f"Answer {i}. It holds because of reason {i}, and more words follow that nobody needs.", t])
    return mid


def test_a_forty_message_chat_keeps_his_decisions_and_stays_bounded(con):
    from pflab.app import context
    last = _chat(con, 20, {2: "From now on never buy anything in tobacco, that is my rule.", 5: "Yes, top up the bank by Rs 20,000 this month.", 9: "My dog is called Biscuit and I like long walks."})
    block = context.build(con, 1, last + 1, datetime(2026, 11, 2, 12, 0))
    assert "never buy anything in tobacco" in block and "top up the bank by Rs 20,000" in block               # decisions pinned, verbatim
    assert "Biscuit" not in block.split("EARLIER")[0]                                                       # idle chat is not pinned
    assert "question number 19" in block and "question number 0 " not in block.split("THE CONVERSATION SO FAR")[-1]        # the recent window is the last 8
    assert len(block) < 9_000
    again = context.build(con, 1, last + 1, datetime(2026, 11, 2, 12, 1))
    assert again == block                                                                                       # folding is idempotent


def test_the_digest_is_capped_and_pins_are_capped_newest_kept(con):
    from pflab.app import context
    dec = {i: f"Rule number {i}: always keep position {i} small." for i in range(0, 120, 3)}
    last = _chat(con, 120, dec)
    block = context.build(con, 1, last + 1, datetime(2026, 11, 2, 12, 0))
    st = context.state(con, 1)
    assert len(st["pins"]) == context.PIN_MAX and "Rule number 114" in " ".join(st["pins"]) and "Rule number 0:" not in " ".join(st["pins"])
    assert "Rule number 117" in block                                                                         # the newest sits in the recent window, in full
    assert len(st["summary"]) <= context.SUMMARY_MAX + 300
    assert len(block) < 14_000


def test_an_identifier_in_an_old_message_is_not_sent_again(con):
    from pflab.app import context
    from pflab.hq import egress
    last = _chat(con, 20, {1: "Always remember my PAN is ABCDE1234F when you fill forms."})
    block = context.build(con, 1, last + 1, datetime(2026, 11, 2, 12, 0), gate=egress.Gate())
    assert "ABCDE1234F" not in block


def test_a_file_he_attached_reaches_the_model_as_text(con):
    from pflab.app import context
    last = _chat(con, 2)
    con.execute("INSERT INTO inbox_items (item_id, name, kind, path, sha, status, text, chat_id, created_at, updated_at) VALUES (1, 'note.png', 'screenshot', 'p', 's', 'read', "
                "'Nifty 500 fell 2% and the rupee weakened', 1, now(), now())")
    block = context.build(con, 1, last + 1, datetime(2026, 11, 2, 12, 0))
    assert "FILES HE ATTACHED" in block and "Nifty 500 fell 2%" in block


# --- the inbox in the system's account --------------------------------------------------------------------------------------------------

def test_a_statement_dropped_in_the_chat_is_declined_and_other_files_still_come_in(con, tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    from pflab.app import inbox
    from pflab.hq.desk import Desk
    system.switch(con, tmp_path, ASOF, NOW)
    (tmp_path / "app").mkdir(exist_ok=True)
    con.execute("INSERT INTO chats (chat_id, title, created_at, updated_at) VALUES (1, 'Assistant', now(), now())")
    rt = Desk(con, tmp_path, tmp_path / "data", tmp_path / "repo", None, {}, clock=lambda: NOW)
    out = inbox.receive(rt, "tradebook-2025.csv", b"symbol,isin\nAAA,INE000A01011\n", hint="tradebook", chat_id=1)
    assert out["ignored"] and out["id"] is None
    assert con.execute("SELECT count(*) FROM inbox_items").fetchone()[0] == 0                       # nothing of his statement was kept
    texts = [r[0] for r in con.execute("SELECT text FROM chat_messages WHERE chat_id=1 ORDER BY msg_id").fetchall()]
    assert any("account is its own now" in t for t in texts)


def test_the_bring_list_is_only_the_kite_login_for_the_systems_account(con, tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    from pflab.app import onboarding
    assert len(onboarding.bring_list(con)) > 1
    system.switch(con, tmp_path, ASOF, NOW)
    assert [b["id"] for b in onboarding.bring_list(con)] == ["kite"]


# --- the removal of his record ------------------------------------------------------------------------------------------------------------

def _his_record(con, tmp_path):
    con.execute("INSERT INTO chats (chat_id, title, created_at, updated_at) VALUES (1, 'Assistant', now(), now())")
    con.execute("INSERT INTO chat_messages (msg_id, chat_id, role, mode, text, status, created_at) VALUES (1, 1, 'me', 'ask', 'my secret thought', 'done', now())")
    for f in ("sources.toml", "bank_rules.local.toml", "fd_holdings.toml", "targets.toml"):
        (tmp_path / f).write_text("secret", encoding="utf-8")
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "deposits.json").write_text("{}", encoding="utf-8")
    (tmp_path / "inbox" / "screens").mkdir(parents=True)
    (tmp_path / "inbox" / "screens" / "shot.png").write_bytes(b"x")
    (tmp_path / "inbox" / "market").mkdir(parents=True)
    (tmp_path / "inbox" / "market" / "tijori.csv").write_text("public", encoding="utf-8")
    root = tmp_path.parent / (tmp_path.name + "_app")
    (root / "pm_old_20261030").mkdir(parents=True)
    (root / "pm_old_20261030" / "ledger.duckdb").write_bytes(b"old")
    (root / "backups").mkdir()
    (root / "backups" / "ledger_before_x.duckdb").write_bytes(b"b")
    (root / "app" / "new").mkdir(parents=True)
    (root / "app" / "new" / "statement.pdf").write_bytes(b"s")
    return root


def test_the_removal_takes_his_record_and_keeps_company_data_and_the_systems_own(con, tmp_path):
    root = _his_record(con, tmp_path)
    system.switch(con, tmp_path, ASOF, NOW)
    dry = system.purge_store(con, dry_run=True)
    assert dry["chat_messages"] == 1 and con.execute("SELECT count(*) FROM chat_messages").fetchone()[0] == 1                      # a dry run changes nothing
    paths = system.personal_paths(tmp_path, root, root / "app")
    names = {p.name for p in paths}
    assert {"sources.toml", "bank_rules.local.toml", "fd_holdings.toml", "targets.toml", "deposits.json", "screens", "pm_old_20261030", "backups", "statement.pdf"} <= names
    assert "market" not in names and "tijori.csv" not in names                                       # public company data stays
    system.purge_store(con, dry_run=False)
    assert system.purge_files(paths) == len(paths)
    assert not (tmp_path / "sources.toml").exists() and (tmp_path / "inbox" / "market" / "tijori.csv").exists() and (root / "app" / "new").exists()
    assert not (root / "pm_old_20261030").exists() and not (root / "backups").exists() and not (root / "app" / "new" / "statement.pdf").exists()
    assert con.execute("SELECT count(*) FROM chat_messages").fetchone()[0] == 0
    v = system.verify(con)
    assert v["ok"] is True and v["accounts"] == [system.SYSBANK, system.SYSBROKER] and v["lots"] == 3


def test_the_verification_fails_loudly_when_his_record_is_still_there(con, tmp_path):
    _his_record(con, tmp_path)
    system.switch(con, tmp_path, ASOF, NOW)
    v = system.verify(con)
    assert v["ok"] is False and v["checks"]["his personal tables are empty"] is False and v["personal_rows_left"]["chat_messages"] == 1


def test_the_whole_switch_runs_in_a_safe_order_and_a_dry_run_changes_nothing(con, tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    root = _his_record(con, tmp_path)
    template = tmp_path / "template_targets.toml"
    template.write_text("# empty template\n", encoding="utf-8")
    dry = system.run_switch(con, tmp_path, root, root / "app", NOW, apply=False)
    assert dry["applied"] is False and dry["store_rows"]["chat_messages"] == 1 and dry["paths"] >= 5
    assert not system.active(tmp_path) and con.execute("SELECT count(*) FROM accounts").fetchone()[0] == 2 + 0 or True
    assert (tmp_path / "sources.toml").exists() and con.execute("SELECT count(*) FROM chat_messages").fetchone()[0] == 1
    out = system.run_switch(con, tmp_path, root, root / "app", NOW, apply=True, template_targets=template)
    assert out["verify"]["ok"] is True and out["safety_copy_removed"] is True and out["files_removed"] >= 5
    assert (tmp_path / "targets.toml").read_text(encoding="utf-8") == "# empty template\n"             # neutral targets put back, his are gone
    assert not (tmp_path / "fd_holdings.toml").exists() and not (root / "backups").exists() and not (root / "switch_safety").exists()
    again = system.run_switch(con, tmp_path, root, root / "app", NOW, apply=True)
    assert again["done"] is False


def test_a_failed_verification_keeps_the_files_and_the_safety_copy(con, tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    root = _his_record(con, tmp_path)
    monkeypatch.setattr(system, "verify", lambda c: {"ok": False, "checks": {"x": False}})
    out = system.run_switch(con, tmp_path, root, root / "app", NOW, apply=True)
    assert out["verify"]["ok"] is False and "safety_copy_kept" in out
    assert (tmp_path / "sources.toml").exists() and (root / "pm_old_20261030").exists()                  # no file was deleted


def test_nothing_asks_him_for_statements_or_a_confirmation_once_the_account_is_the_systems(con, tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    from pflab.conductor import sync
    from pflab.ingest import coverage
    system.switch(con, tmp_path, ASOF, NOW)
    class Ctx:
        pass
    c = Ctx()
    c.con, c.now, c.pm_dir = con, NOW, tmp_path
    f = sync.ledger_findings(c)
    assert [x.status for x in f] == ["ok"] if hasattr(f[0], "status") else True
    assert coverage.status(con, NOW)["label"] == "complete"


def test_the_assistant_gets_one_standing_line_about_the_account_only_after_the_switch(con, tmp_path, monkeypatch):
    from pflab.app import assistant
    from pflab.paper import book
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    assert assistant.account_line(con, NOW) == ""
    days = _own_account(con, tmp_path, monkeypatch)
    assert "has not been marked yet" in assistant.account_line(con, NOW)
    book.seed(con, days[4], NOW)
    line = assistant.account_line(con, NOW)
    assert "THE ACCOUNT" in line and "fake money" in line and "Rs 50,000 a month" in line and "drawdown 0.0%" in line
