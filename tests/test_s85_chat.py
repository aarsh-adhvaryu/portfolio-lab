"""S85 `chat` (E1 the shared conversation, E2 the intake and the router, E8 usage). Synthetic data and a scripted model only (rule 7): the gateway is replaced by `intake.gateway_call`."""
from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from pflab.entrance import intake, router, store, usage
from pflab.entrance import tools as chat_tools
from pflab.pm import store as pm

NOW = datetime(2026, 11, 13, 10, 0)


@pytest.fixture
def con(tmp_path):
    c = pm.connect(tmp_path / "ledger.duckdb")
    yield c
    c.close()


@pytest.fixture
def rt(con):
    bumps = []
    r = SimpleNamespace(cursor=con.cursor, clock=lambda: NOW, bump=lambda *t: bumps.append(t), settings={"brain": "normal"}, secrets=None, pm_dir=None, data_root=None, bumps=bumps)
    return r


class FakeGate:
    """A scripted gateway: `script` is a list of replies (dicts or exceptions) or a function."""

    def __init__(self, script=None, delay=0.0):
        self.script, self.delay, self.calls = list(script or []), delay, []

    def __call__(self, con, role, system, messages, **kw):
        self.calls.append({"role": role, "kw": kw, "messages": messages})
        if self.delay:
            time.sleep(self.delay)
        r = self.script.pop(0) if self.script else {"text": "Noted."}
        if isinstance(r, Exception):
            raise r
        out = {"text": "", "json": None, "tool_calls": [], "assistant_content": [], "cost_rupees": 0.25, "cached_tokens": 0, "engine": "anthropic", "model": kw.get("model") or "claude-haiku-5-5",
               "thinking": kw.get("thinking") or "low", "role": role, "call_id": 1, "warnings": [], "note": ""}
        out.update(r)
        return out


@pytest.fixture(autouse=True)
def _clean():
    intake.stop()
    intake.gateway_call = None
    intake.handler = None
    yield
    intake.stop()
    intake.gateway_call = None
    intake.handler = None


def wait_done(con, item_id, secs=10.0):
    end = time.time() + secs
    while time.time() < end:
        st = con.execute("SELECT state FROM intake_queue_s85 WHERE item_id=?", [item_id]).fetchone()[0]
        if st in ("done", "failed"):
            return st
        time.sleep(0.02)
    raise AssertionError("the item did not finish")


# --- the store -----------------------------------------------------------------------------------------------------------------------------------------

def test_one_conversation_across_channels(con):
    cid = store.latest_chat(con, NOW)
    assert store.latest_chat(con, NOW) == cid                                   # the same chat for every window
    store.add_message(con, cid, "me", "hello from the laptop", channel="laptop", now=NOW)
    store.add_message(con, cid, "me", "hello from the phone", channel="telegram", now=NOW)
    ms = store.messages(con, cid)
    assert [m["channel"] for m in ms] == ["laptop", "telegram"] and ms[1]["text"] == "hello from the phone"
    assert all(k in ms[0] for k in ("id", "role", "mode", "text", "status", "route", "meta", "report", "cost_inr", "at"))   # the old keys are all still there


def test_new_chat_everywhere_and_empty_chat_is_not_archived(con):
    c1 = store.latest_chat(con, NOW)
    assert store.new_chat(con, NOW, channel="telegram") == c1                     # nothing written yet: no empty chats pile up
    store.add_message(con, c1, "me", "pause gold buys please", now=NOW)
    c2 = store.new_chat(con, NOW + timedelta(minutes=1), channel="telegram")
    assert c2 != c1 and store.latest_chat(con, NOW) == c2                         # a new chat for every window
    titles = {c["id"]: c["title"] for c in store.chats(con)}
    assert titles[c2] == store.ACTIVE and titles[c1].startswith(store.EARLIER) and "pause gold" in titles[c1]
    assert [m["text"] for m in store.messages(con, c1)] == ["pause gold buys please"]   # nothing lost
    back = store.open_chat(con, c1, NOW)
    assert back == c1 and store.latest_chat(con, NOW) == c1


def test_post_system_once_per_key_and_roles(con):
    a = store.post_system(con, NOW, "Morning plan: nothing to do.", kind="plan", key="plan:2026-11-13")
    assert a and store.post_system(con, NOW, "again", kind="plan", key="plan:2026-11-13") is None
    m = store.message(con, a)
    assert m["role"] == "ai" and m["channel"] == "system" and m["kind"] == "plan"
    assert store.post_system(con, NOW, "tablet only", kind="plan", key="x", channels=("telegram",)) is None
    with pytest.raises(ValueError):
        store.add_message(con, store.latest_chat(con, NOW), "robot", "x", now=NOW)
    b = store.post_system(con, NOW, "Q?", kind="card", key="q1", actions=[{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}])
    assert store.message(con, b)["actions"][0]["id"] == "yes"


def test_the_outbox_hook_mirrors_proactive_messages_but_not_answers(con):
    from pflab.service import telegram as tgm
    tgm.enqueue(con, "15:45 report: the book is flat.", "summary", dedup_key="s1", now=NOW)
    tgm.enqueue(con, "15:45 report: the book is flat.", "summary", dedup_key="s1", now=NOW)      # deduped by the outbox: not posted twice
    tgm.enqueue(con, "an answer", "reply", now=NOW)
    texts = [m["text"] for m in store.messages(con, store.latest_chat(con, NOW))]
    assert texts == ["15:45 report: the book is flat."]


def test_attachment_rows_and_prefs(con, tmp_path):
    cid = store.latest_chat(con, NOW)
    f = tmp_path / "note.txt"
    f.write_text("a note", encoding="utf-8")
    mid = store.add_message(con, cid, "me", "see file", attachments=[{"path": str(f), "name": "note.txt", "mime": "text/plain", "kind": "text"}], now=NOW)
    rows = store.attachments(con, mid)
    assert len(rows) == 1 and rows[0]["name"] == "note.txt" and rows[0]["sha"]
    assert store.message(con, mid)["attachments"][0]["name"] == "note.txt"
    assert store.get_prefs(con, cid) == {"model_key": None, "thinking": None}
    assert store.set_prefs(con, cid, "opus", "high")["model_key"] == "opus"
    assert store.set_prefs(con, cid, "auto")["model_key"] is None and store.get_prefs(con, cid)["thinking"] == "high"
    with pytest.raises(ValueError):
        store.set_prefs(con, cid, thinking="extreme")


# --- the router (one table) ----------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,atts,want", [
    ("thanks", [], "haiku"),
    ("ok, good morning", [], "haiku"),
    ("what is my cash?", [], "sonnet"),
    ("how are the picks doing", [], "sonnet"),
    ("is it true that the company lost its licence", [], "sonnet"),
    ("please read this https://example.com/a", [], "sonnet"),
    ("here you go", ["report.pdf"], "sonnet"),
    ("x" * 300, [], "sonnet"),
    ("should I sell the gold ETF?", [], "opus"),
    ("pause gold buys till 20 Nov", [], "opus"),
    ("do not buy that stock", [], "opus"),
    ("change the allocation to more international", [], "opus"),
    ("from now on keep 10% in cash", [], "opus"),
    ("make it a pick", [], "opus"),
])
def test_router_table(text, atts, want):
    r = router.route(text, atts)
    assert r["model_key"] == want and r["auto"] and r["why"].startswith("Auto:")
    assert r["role"] == router.MODELS[want][1] and r["thinking"] == router.MODELS[want][2]
    assert (r["tools"] == "none") == (want == "haiku")


def test_router_picker_overrides_auto():
    r = router.route("thanks", [], {"model_key": "opus", "thinking": "max"})
    assert (r["model_key"], r["thinking"], r["role"], r["auto"]) == ("opus", "max", "decide", False) and "your pick" in r["why"] and "Auto would have used Haiku" in r["why"]
    r = router.route("should I sell?", [], {"model_key": None, "thinking": "low"})          # thinking alone keeps Auto's model
    assert (r["model_key"], r["thinking"], r["auto"]) == ("opus", "low", True)
    r = router.route("thanks", [], {"model_key": "auto"})
    assert r["model_key"] == "haiku"
    with pytest.raises(ValueError):
        router.route("x", [], {"thinking": "extreme"})


# --- the intake ----------------------------------------------------------------------------------------------------------------------------------------

def test_submit_returns_at_once_and_acknowledges_while_a_slow_model_hangs(con, rt):
    gate = FakeGate([{"text": "Hello."}], delay=3.0)
    intake.gateway_call = gate
    intake.start(rt)
    t0 = time.monotonic()
    out = intake.submit(rt, "laptop", "thanks")
    took = time.monotonic() - t0
    assert took < 2.0 and set(out) >= {"chat_id", "msg_id", "item_id"}
    m = store.message(con, out["msg_id"])
    assert m["status"] in ("queued", "working") and m["text"].endswith("…")           # acknowledged in the chat before the model answers
    assert wait_done(con, out["item_id"]) == "done"
    m = store.message(con, out["msg_id"])
    assert m["text"] == "Hello." and m["status"] == "done" and m["model"] == "claude-haiku-5-5" and m["cost_inr"] == 0.25
    assert "Haiku 5.5" in m["meta"] and "Rs 0.25" in m["meta"] and "Auto" in m["meta"]


def test_reply_callback_gets_progress_and_the_final_answer(con, rt):
    intake.gateway_call = FakeGate([{"text": "Done."}])
    got = []
    intake.start(rt)
    out = intake.submit(rt, "telegram", "thanks", reply=lambda text, mid, final: got.append((text, mid, final)))
    wait_done(con, out["item_id"])
    time.sleep(0.2)
    assert got[0][0].endswith("…") and not got[0][2]                                    # the acknowledgement
    assert got[-1] == ("Done.", out["msg_id"], True) and sum(1 for g in got if g[2]) == 1


def test_the_picker_reaches_the_gateway_and_the_reply_shows_model_and_price(con, rt):
    gate = FakeGate([{"text": "As you like.", "model": "claude-opus-5-5", "thinking": "max"}])
    intake.gateway_call = gate
    intake.start(rt)
    out = intake.submit(rt, "laptop", "thanks", model="opus", thinking="max")
    wait_done(con, out["item_id"])
    kw = gate.calls[0]["kw"]
    assert kw["model"] == "claude-opus-5-5" and kw["thinking"] == "max" and gate.calls[0]["role"] == "decide" and kw["chat_id"] == out["chat_id"] and kw["reply_msg_id"] == out["msg_id"]
    assert "your pick" in store.message(con, out["msg_id"])["meta"]


def test_a_saved_choice_applies_to_the_next_messages(con, rt):
    gate = FakeGate([{"text": "a"}, {"text": "b"}])
    intake.gateway_call = gate
    intake.start(rt)
    cid = store.latest_chat(con, NOW)
    store.set_prefs(con, cid, "sonnet", "high")
    out = intake.submit(rt, "telegram", "thanks")
    wait_done(con, out["item_id"])
    assert gate.calls[0]["kw"]["model"] == "claude-sonnet-5-5" and gate.calls[0]["kw"]["thinking"] == "high"


def test_tool_loop_runs_a_registered_tool_and_only_sourced_numbers_pass(con, rt):
    seen = []
    chat_tools.register("ping_s85", {"name": "ping_s85", "description": "[read] test", "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}},
                        lambda ctx, a: (seen.append((a["n"], ctx.chat_id)) or {"pong": a["n"] + 1}))
    try:
        gate = FakeGate([{"text": "", "tool_calls": [{"id": "t1", "name": "ping_s85", "input": {"n": 41}}], "assistant_content": [{"type": "tool_use", "id": "t1", "name": "ping_s85", "input": {"n": 41}}]},
                         {"text": "The tool says 42. I also invented 777 here."}])
        intake.gateway_call = gate
        intake.start(rt)
        out = intake.submit(rt, "laptop", "what is the status of the queue?")
        assert wait_done(con, out["item_id"]) == "done"
        m = store.message(con, out["msg_id"])
        assert seen == [(41, out["chat_id"])]
        assert "42" in m["text"] and "777" not in m["text"] and "removed" in m["text"]
        assert m["cost_inr"] == 0.5                                                  # two calls
        names = [t["name"] for t in gate.calls[0]["kw"]["tools"]]
        assert "ping_s85" in names and "portfolio" in names and "add_rule" in names
        assert not set(names) & set(chat_tools.CORE_RETIRED)                          # the retired v1 tools are not offered
        assert gate.calls[1]["messages"][-1]["content"][0]["type"] == "tool_result"
    finally:
        chat_tools.REGISTRY.pop("ping_s85", None)


def test_haiku_route_offers_no_tools(con, rt):
    gate = FakeGate([{"text": "You are welcome."}])
    intake.gateway_call = gate
    intake.start(rt)
    out = intake.submit(rt, "laptop", "thanks")
    wait_done(con, out["item_id"])
    assert "tools" not in gate.calls[0]["kw"]


def test_api_down_gives_a_plain_line_after_one_retry(con, rt, monkeypatch):
    monkeypatch.setitem(intake.DEFAULTS, "retry_pause_s", 0.0)
    gate = FakeGate([ConnectionError("down"), ConnectionError("still down")])
    intake.gateway_call = gate
    intake.start(rt)
    out = intake.submit(rt, "laptop", "thanks")
    assert wait_done(con, out["item_id"]) == "failed"
    m = store.message(con, out["msg_id"])
    assert m["status"] == "failed" and "did not answer" in m["text"] and "loop is untouched" in m["text"]
    assert len(gate.calls) == 2                                                       # one retry, then the line
    assert con.execute("SELECT error FROM intake_queue_s85 WHERE item_id=?", [out["item_id"]]).fetchone()[0].startswith("ConnectionError")


def test_a_model_call_that_hangs_is_cut_by_its_timeout(con, rt, monkeypatch):
    monkeypatch.setitem(intake.DEFAULTS, "call_timeout_s", 0.3)
    monkeypatch.setitem(intake.DEFAULTS, "retry_pause_s", 0.0)
    intake.gateway_call = FakeGate([{"text": "late"}, {"text": "late"}], delay=2.0)
    intake.start(rt)
    out = intake.submit(rt, "laptop", "thanks")
    t0 = time.monotonic()
    assert wait_done(con, out["item_id"]) == "failed"
    assert time.monotonic() - t0 < 1.8
    assert "in time" in store.message(con, out["msg_id"])["text"]


def test_an_empty_message_is_refused_and_a_file_only_message_is_accepted(con, rt, tmp_path):
    intake.gateway_call = FakeGate([{"text": "I have the file."}])
    with pytest.raises(ValueError):
        intake.submit(rt, "laptop", "   ")
    f = tmp_path / "a.txt"
    f.write_text("hi", encoding="utf-8")
    intake.start(rt)
    out = intake.submit(rt, "telegram", "", attachments=[{"path": str(f), "name": "a.txt", "mime": "text/plain"}])
    wait_done(con, out["item_id"])
    um = store.message(con, out["user_msg_id"])
    assert um["kind"] == "file" and um["attachments"][0]["name"] == "a.txt"


def test_a_statement_is_refused_before_any_call_and_not_kept(con, rt, tmp_path):
    gate = FakeGate([{"text": "should not be called"}])
    intake.gateway_call = gate
    f = tmp_path / "tradebook-2026.csv"
    f.write_text("symbol,qty\nAAA,1\n", encoding="utf-8")
    intake.start(rt)
    out = intake.submit(rt, "laptop", "read this", attachments=[{"path": str(f), "name": "tradebook-2026.csv", "mime": "text/csv"}])
    wait_done(con, out["item_id"])
    m = store.message(con, out["msg_id"])
    assert gate.calls == [] and "not taken" in m["text"] and "did not store or send" in m["text"]
    assert not f.exists() and store.attachments(con, out["user_msg_id"]) == []


# --- the queue and the workers ------------------------------------------------------------------------------------------------------------------------

def test_queue_status_lists_open_and_recent_items(con, rt):
    intake.gateway_call = FakeGate([{"text": "x"}])
    intake.start(rt)
    out = intake.submit(rt, "laptop", "thanks")
    wait_done(con, out["item_id"])
    q = intake.queue_status(con)
    assert q[0]["item_id"] == out["item_id"] and q[0]["state"] == "done" and q[0]["price_inr"] == 0.25 and q[0]["model"] == "claude-haiku-5-5"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_crashed_worker_is_restarted_and_nothing_is_lost(con, rt, monkeypatch):
    class Crash(BaseException):
        pass
    monkeypatch.setitem(intake.DEFAULTS, "supervise_s", 0.05)
    calls = {"n": 0}

    def flaky(rt_, it, progress):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Crash()
        return {"text": "recovered", "status": "done"}
    intake.handler = flaky
    w = intake.start(rt)
    out = intake.submit(rt, "laptop", "thanks")
    assert wait_done(con, out["item_id"]) == "done"
    assert store.message(con, out["msg_id"])["text"] == "recovered" and w.restarts >= 1 and calls["n"] == 2


def test_an_item_left_working_by_a_stopped_process_is_resumed(con, rt):
    intake.stop()
    intake.handler = lambda r, it, p: {"text": "resumed answer", "status": "done"}
    cid = store.latest_chat(con, NOW)
    uid = store.add_message(con, cid, "me", "hello", now=NOW)
    aid = store.add_message(con, cid, "ai", "Looking into it…", status="working", now=NOW)
    con.execute("INSERT INTO intake_queue_s85 (item_id, chat_id, msg_id, reply_msg_id, channel, kind, state, attempts, created_at) VALUES (1,?,?,?,'laptop','chat','working',1,?)", [cid, uid, aid, NOW])
    intake.start(rt)
    assert wait_done(con, 1) == "done" and store.message(con, aid)["text"] == "resumed answer"


def test_an_item_that_keeps_failing_ends_with_a_plain_line(con, rt, monkeypatch):
    monkeypatch.setitem(intake.DEFAULTS, "max_attempts", 2)
    n = {"n": 0}

    def bad(r, it, p):
        n["n"] += 1
        raise RuntimeError("bug")
    intake.handler = bad
    intake.start(rt)
    out = intake.submit(rt, "laptop", "thanks")
    assert wait_done(con, out["item_id"]) == "failed"
    assert n["n"] == 2 and "send it again" in store.message(con, out["msg_id"])["text"]


def test_telegram_answer_goes_to_the_outbox_when_the_callback_was_lost(con, rt):
    intake.handler = lambda r, it, p: {"text": "the answer", "status": "done"}
    intake.start(rt)
    out = intake.submit(rt, "telegram", "thanks")                                      # no reply callback given
    wait_done(con, out["item_id"])
    time.sleep(0.1)
    rows = con.execute("SELECT kind, text FROM outbox ORDER BY msg_id").fetchall()
    assert ("reply", "the answer") in rows


def test_the_item_timeout_fails_a_hung_item_with_a_plain_line(con, rt, monkeypatch):
    monkeypatch.setitem(intake.DEFAULTS, "item_timeout_s", 0.3)
    intake.handler = lambda r, it, p: time.sleep(3) or {"text": "late"}
    intake.start(rt)
    out = intake.submit(rt, "laptop", "thanks")
    assert wait_done(con, out["item_id"]) == "failed"
    assert "took too long" in store.message(con, out["msg_id"])["text"]


# --- usage (E8) ---------------------------------------------------------------------------------------------------------------------------------------

def test_usage_reads_api_calls_by_purpose_chat_and_reply(con):
    def row(i, purpose, agent, cost, chat=None, reply=None, at=NOW):
        con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, status, input_tokens, output_tokens, cost_inr, agent, purpose, chat_id, reply_msg_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [i, at, "normal", "claude-sonnet-5-5", "t", "q", "sha", "{}", "done", 1000, 200, cost, agent, purpose, chat, reply])
    row(1, "chat", "chat", 1.5, chat=7, reply=70)
    row(2, "chat", "chat", 0.5, chat=7, reply=70)
    row(3, None, "strategist", 20.0)
    row(4, "", "checker", 2.0)
    row(5, "chat", "chat", 9.0, at=NOW - timedelta(days=1))
    d = NOW.date()
    t = usage.today(con, d)
    assert t["calls"] == 4 and t["cost_inr"] == pytest.approx(24.0) and t["tokens_in"] == 4000
    bp = {p["purpose"]: p for p in usage.by_purpose(con, d)}
    assert bp["chat"]["cost_inr"] == pytest.approx(2.0) and bp["strategist"]["calls"] == 1 and bp["checker"]["cost_inr"] == pytest.approx(2.0)
    assert usage.by_reply(con, 70) == {"calls": 2, "cost_inr": pytest.approx(2.0), "models": ["claude-sonnet-5-5"]}
    assert len(usage.by_chat(con, 7)) == 2
    assert "Rs 24.00 in 4 calls" in usage.line(con, d) and "strategist Rs 20.00" in usage.line(con, d)
    assert usage.view(con, d)["month_inr"] == pytest.approx(33.0)
