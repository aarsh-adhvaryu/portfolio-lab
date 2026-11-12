"""S43: memory, questions, the trade-check agent and the two-way bot. SYNTHETIC store, FAKE Kite and Telegram."""
from datetime import date, datetime

import pytest

from pflab.agents import memory as mem
from pflab.agents import questions as qs
from pflab.agents import tradecheck as tc
from pflab.ledger.events import Event, EventLog, save
from pflab.pm import store
from pflab.service import bot

AAA = "INE000A01011"
NOW = datetime(2026, 10, 17, 16, 0)


def _store(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha (synthetic)')")
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'AAA', 'Aaa Limited', 'synthetic', now())""", [AAA])
    save(con, EventLog([Event("deposit", "ZER", date(2026, 10, 1), amount=100_000.0),
                        Event("buy", "ZER", date(2026, 10, 1), isin=AAA, qty=10, price=100.0, ref="T1")]))
    return con


class FakeKite:
    """Kite's real shapes (2026-10-17): settled `quantity` plus `t1_quantity`; `available.cash` reads 0 while
    `live_balance` holds the balance."""
    def __init__(self, trades=(), holdings=10.0, cash=99_000.0, t1=0.0):
        self._t, self._h, self._c, self._t1 = list(trades), holdings, cash, t1

    def trades(self):
        return self._t

    def holdings(self):
        return [{"isin": AAA, "tradingsymbol": "AAA", "exchange": "NSE", "quantity": self._h - self._t1,
                 "t1_quantity": self._t1, "average_price": 100.0, "last_price": 101.0}]

    def margins(self):
        return {"equity": {"available": {"cash": 0, "opening_balance": self._c, "live_balance": self._c}, "net": self._c}}

    def place_order(self, *a, **k):                    # present on the fake; the agent must never reach it
        raise AssertionError("the trade check placed an order")


def trade(tid, d, qty=5, price=110.0, side="BUY"):
    return {"trade_id": tid, "order_id": "O" + tid, "fill_timestamp": datetime(d.year, d.month, d.day, 10, 0),
            "tradingsymbol": "AAA", "exchange": "NSE", "transaction_type": side, "quantity": qty, "average_price": price}


# ---- memory and questions ---------------------------------------------------------------------------------

def test_memory_keeps_history_when_a_decision_changes(tmp_path):
    con = _store(tmp_path)
    a = mem.remember(con, "decision", "keep the target mix", subject="mix", valid_from=date(2026, 10, 16), now=NOW)
    b = mem.remember(con, "decision", "keep the mix at the any-day figure", subject="mix", supersedes=a,
                     valid_from=date(2026, 10, 17), now=NOW)
    now_rows = mem.recall(con, subject="mix", asof=date(2026, 10, 17))
    assert [m.mem_id for m in now_rows] == [b]
    assert [m.mem_id for m in mem.recall(con, subject="mix", asof=date(2026, 10, 16))] == [a]   # what held then
    assert {m.mem_id for m in mem.recall(con, words="mix keep", include_past=True, asof=date(2026, 10, 17))} == {a, b}
    with pytest.raises(ValueError):
        mem.remember(con, "decision", "again", supersedes=a)                  # already superseded
    with pytest.raises(ValueError):
        mem.remember(con, "guess", "x")
    assert mem.as_sources(now_rows)["S1"].startswith(f"#{b} 2026-10-17 decision [mix]")


def test_a_question_is_asked_once_and_its_answer_becomes_memory(tmp_path):
    con = _store(tmp_path)
    q = qs.ask(con, "trade-check", "holding:X", "Why does Kite show more?", NOW)
    assert q and qs.ask(con, "trade-check", "holding:X", "Why does Kite show more?", NOW) is None
    mid = qs.answer(con, q, "a gift from my father", NOW)
    assert qs.open_questions(con) == [] and "gift" in mem.recall(con, kinds=["answer"], asof=NOW.date())[0].text
    assert mem.recall(con, kinds=["answer"], asof=NOW.date())[0].mem_id == mid
    with pytest.raises(ValueError):
        qs.answer(con, q, "again")


# ---- trade check ------------------------------------------------------------------------------------------

def test_todays_trade_is_staged_and_holdings_agree_until_it_settles(tmp_path):
    con = _store(tmp_path)
    d = date(2026, 10, 17)
    r = tc.check(con, FakeKite([trade("T2", d)], holdings=10), d, now=NOW)
    assert r.staged == 1 and r.breaks.empty and r.asked == [] and r.pending[0]["trade_id"] == "T2"
    assert r.cash == {"kite_available": 99_000.0, "ledger": pytest.approx(100_000.0 - 1_000.0)}
    r2 = tc.check(con, FakeKite([], holdings=15, t1=5), date(2026, 10, 19), now=NOW)   # staged T2 = Kite's T1
    assert r2.staged == 0 and r2.breaks.empty


def test_an_unstaged_recent_buy_is_named_as_such_and_a_cash_gap_is_asked(tmp_path):
    """Real case 2026-10-17: a buy from the day before (kite.trades() only returns today's) shows as T1."""
    con = _store(tmp_path)
    r = tc.check(con, FakeKite([], holdings=15, t1=5, cash=93_500.0), date(2026, 10, 17), now=NOW)
    assert len(r.breaks) == 1 and r.breaks.iloc[0]["note"].startswith("a recent buy of 5 (T1")
    texts = [t for _, _, t in qs.open_questions(con)]
    assert any("recent buy of 5" in t and "AAA" in t for t in texts)
    assert any("cash balance is 93,500.00, the ledger's 99,000.00" in t for t in texts) and len(r.asked) == 2


def test_a_holding_difference_becomes_one_question(tmp_path):
    con = _store(tmp_path)
    d = date(2026, 10, 17)
    r = tc.check(con, FakeKite([], holdings=12), d, now=NOW)
    assert len(r.breaks) == 1 and len(r.asked) == 1
    assert tc.check(con, FakeKite([], holdings=12), d, now=NOW).asked == []         # not asked twice
    assert "Kite holds 12" in qs.open_questions(con)[0][2]
    assert con.execute("SELECT count(*) FROM recon_breaks WHERE run_id='tradecheck:2026-10-17'").fetchone()[0] == 2


def test_a_trade_missing_for_days_is_asked_about_then_resolved_by_the_rebuild(tmp_path):
    con = _store(tmp_path)
    tc.check(con, FakeKite([trade("T2", date(2026, 10, 16))], holdings=10), date(2026, 10, 16), now=NOW)
    r = tc.check(con, FakeKite([], holdings=15), date(2026, 10, 21), now=NOW)
    assert r.asked and "T2" in qs.open_questions(con)[0][2]
    # the rebuild brings the tradebook in: same trade, its own ref (matched on date, isin, side, qty, price)
    save(con, EventLog([Event("deposit", "ZER", date(2026, 10, 1), amount=100_000.0, event_id=1),
                        Event("buy", "ZER", date(2026, 10, 1), isin=AAA, qty=10, price=100.0, ref="T1", event_id=2),
                        Event("buy", "ZER", date(2026, 10, 16), isin=AAA, qty=5, price=110.0, ref="TB-9", event_id=3)]))
    r3 = tc.check(con, FakeKite([], holdings=15, cash=98_450.0), date(2026, 10, 22), now=NOW)
    assert r3.resolved == 1 and r3.pending == [] and r3.breaks.empty and qs.open_questions(con) == []


# ---- the bot ----------------------------------------------------------------------------------------------

def upd(uid, text, chat=42):
    return {"update_id": uid, "message": {"chat": {"id": chat}, "text": text}}


def test_bot_answers_only_the_investor_and_never_flushes_held_alerts(tmp_path):
    con = _store(tmp_path)
    from pflab.service import telegram as tgm
    held = tgm.enqueue(con, "a held alert", "guard", now=NOW)
    sent = []
    n = bot.process(con, [upd(1, "/help"), upd(2, "hello", chat=99), upd(3, "/memory")], "42", sent.append,
                    lambda t: bot.handle(con, t, NOW.date(), ask=lambda q, tl: "asked", tradecheck=lambda: "tc", now=NOW), NOW)
    assert n == 2 and sent[0].startswith("Ask me anything") and sent[1] == "Nothing kept on that yet."
    assert con.execute("SELECT status FROM outbox WHERE msg_id=?", [held]).fetchone()[0] == "pending"
    rows = con.execute("SELECT update_id, accepted, command FROM bot_updates ORDER BY 1").fetchall()
    assert rows == [(1, True, "/help"), (2, False, None), (3, True, "/memory")]       # no text of the stranger kept
    assert bot.process(con, [upd(3, "/memory")], "42", sent.append, lambda t: "x", NOW) == 0   # each update once
    assert bot.next_offset(con) == 4


def test_bot_commands_route_to_agents_memory_and_questions(tmp_path):
    con = _store(tmp_path)
    calls = []
    h = lambda t: bot.handle(con, t, NOW.date(), ask=lambda q, tl: calls.append((q, tl)) or "facts",
                             tradecheck=lambda: "checked", now=NOW)
    assert h("/networth").startswith("I don't know that command") and calls == []                  # S85: the v1 agent commands are retired
    assert h("why did my portfolio fall?") == "facts" and calls[-1] == ("why did my portfolio fall?", None)
    assert h("/decide gold: stay at the target") .startswith("Kept as decision")
    assert mem.recall(con, subject="gold", asof=NOW.date())[0].text == "stay at the target"
    q = qs.ask(con, "trade-check", "k", "Which account?", NOW)
    assert f"#{q}" in h("/questions") and h(f"/answer {q} the Zerodha one").startswith("Thanks")
    assert h("/tradecheck") == "checked" and h("/sell everything").startswith("I don't know that command")


def test_bot_run_once_polls_with_the_offset_and_redacts_the_token(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    db = tmp_path / "l.duckdb"
    _store(tmp_path).close()

    class S:
        def get(self, s, k):
            return {"token": "SECRET-TOKEN", "chat_id": "42"}[k]

        def redact(self, t):
            return str(t).replace("SECRET-TOKEN", "***")

    seen = []

    def transport(url, payload):
        seen.append(payload)
        return 200, {"ok": True, "result": [upd(7, "/help")]}
    sent = []
    assert bot.run(S(), connect=lambda: store.connect(db), once=True, transport=transport, send=sent.append,
                   clock=lambda: NOW, lock_path=tmp_path / "bot.lock") == 1
    assert seen[0]["timeout"] == 0 and "offset" not in seen[0] and sent[0].startswith("Ask me anything")
    bad = lambda url, payload: (401, {"ok": False, "description": "Unauthorized " + url})
    with pytest.raises(RuntimeError) as e:
        bot.run(S(), connect=lambda: store.connect(db), once=True, transport=bad, send=sent.append,
                lock_path=tmp_path / "bot.lock")
    assert "SECRET-TOKEN" not in str(e.value)
