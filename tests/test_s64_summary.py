"""S64 Phase 5 item 1: Telegram only when it matters; the morning and evening summaries."""
from datetime import date, datetime

import duckdb
import pytest

from pflab.conductor import calendar as mcal
from pflab.pm import store
from pflab.service import summary
from pflab.service import telegram as tgm

NOW = datetime(2026, 10, 27, 9, 0)
CAL = mcal.Calendar()


@pytest.fixture
def con(tmp_path):
    c = duckdb.connect(str(tmp_path / "pm.duckdb"))
    store.migrate(c)
    return c


def status(con):
    return dict(con.execute("SELECT kind, status FROM outbox").fetchall())


def test_only_urgent_and_direct_kinds_go_at_once(con):
    for kind in ("watch", "market_state", "guard", "security", "crash", "reply", "reminder", "test", "job_failure", "summary",
                 "research", "filing", "conductor", "ready_plan", "brain", "tradecheck"):
        tgm.enqueue(con, f"a {kind} message", kind, now=NOW)
    s = status(con)
    assert {k for k, v in s.items() if v == "pending"} == {"watch", "market_state", "guard", "security", "crash", "reply",
                                                          "reminder", "test", "job_failure", "summary"}
    assert {k for k, v in s.items() if v == "held"} == {"research", "filing", "conductor", "ready_plan", "brain", "tradecheck"}


def test_flush_leaves_held_rows_alone(con):
    tgm.enqueue(con, "held one", "research", now=NOW)
    tgm.enqueue(con, "urgent one", "guard", now=NOW)
    sent = []
    out = tgm.flush(con, sent.append, NOW)
    assert sent == ["urgent one"] and out["sent"] == 1
    assert status(con) == {"research": "held", "guard": "sent"}


def nw(_con, d):
    return {"net_worth": 1_000_000.0 if d == date(2026, 10, 27) else 990_000.0}


def test_summary_carries_held_rows_and_marks_them_sent(con):
    tgm.enqueue(con, "Research digest: 2 new flags", "research", now=NOW)
    con.execute("INSERT INTO questions (q_id, created_at, agent, subject_key, text, status) VALUES (1, ?, 'a', 'k', 't', 'open')", [NOW])
    r = summary.send(con, date(2026, 10, 27), NOW, "morning", CAL, None, nw)
    assert r["sent"] and r["held_carried"] == 1
    text = con.execute("SELECT text FROM outbox WHERE kind='summary'").fetchone()[0]
    assert "Research digest: 2 new flags" in text and "+10,000 (+1.01%)" in text and "Needs from you: 1 open" in text
    assert status(con)["research"] == "sent" and status(con)["summary"] == "pending"
    assert summary.send(con, date(2026, 10, 27), NOW, "morning", CAL, None, nw)["sent"] is False     # once a day and kind


def test_summary_names_what_it_could_not_build(con):
    def broken(_c, _d):
        raise RuntimeError("no ledger")
    text = summary.build(con, date(2026, 10, 27), NOW, "evening", CAL, None, broken)["text"]
    assert "Left out" in text and "portfolio (RuntimeError)" in text


def test_new_suggestion_shows_its_range(con):
    con.execute("INSERT INTO hq_suggestions (sug_id, pass_id, model, made_at, kind, symbol, text, horizon_days, shadow, answer, "
                "price_low, price_high, max_buy, amount, wrong_if) VALUES (1, 1, 'm', ?, 'buy', 'ABC', 'Add ABC', 90, false, "
                "'none', 100, 120, 115, 20000, 'it closes under 80')", [NOW])
    text = summary.build(con, date(2026, 10, 27), NOW.replace(hour=21), "evening", CAL, None, nw)["text"]
    assert "ABC: Add ABC Range 100-120, highest buy 115, about Rs 20,000. Wrong if it closes under 80." in text
