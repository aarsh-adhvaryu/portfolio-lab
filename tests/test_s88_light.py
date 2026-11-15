"""S88: the two roads. The router's rules, the light road's limits (no built-in tool, no preset prompt, its own five tools, at most 4 turns), escalation once and never a loop, the per-thread summary,
the path and token line, the one-word reply without a model call, and the full road's trimmed toolset. Scripted SDK."""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from pflab.llm import claude_plan as cp
from pflab.oper import light, pathrouter, session, tools as otools
from test_s87_claude_plan import FakeClient, assistant, result  # noqa: F401

NOW = datetime(2026, 11, 16, 10, 0)


@pytest.fixture
def con(tmp_path, monkeypatch):
    from pflab.pm import store
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "data"))
    FakeClient.seen, FakeClient.script, FakeClient.capture_tool = [], [], None
    monkeypatch.setattr(cp, "client_factory", FakeClient)
    monkeypatch.setattr(cp, "signin_fn", lambda: {"ok": True, "method": "claude.ai", "detail": ""})
    return store.connect(tmp_path / "t.duckdb")


# --- the router (rules only) ----------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("q", ["look into AAAA", "run a study of this", "backtest a trim rule", "compare CCCC and DDDD", "stress my book", "simulate a 20% fall", "do A and B move together?",
                               "build: the alarm is slow", "please fix the sync", "add a skill for taxes", "add a tool", "/full what is my book", "monthly review please"])
def test_full_triggers(q):
    assert pathrouter.choose(q)[0] == "full", q


def test_file_and_link_go_full_and_plain_goes_light():
    assert pathrouter.choose("what is this?", has_file=True)[0] == "full"
    assert pathrouter.choose(pathrouter.FILE_MARK + " (x)\n\nHIS MESSAGE:\nhi")[0] == "full"
    assert pathrouter.choose("read https://example.com/a")[0] == "full" and pathrouter.choose("see www.x.com")[0] == "full"
    for q in ("How is my book today?", "What did Nvidia do this week?", "Why did the paper book sell EEEE?", "What is my biggest risk right now?", "is the prefix fixed income ok"):
        assert pathrouter.choose(q)[0] == "light", q
    assert pathrouter.choose("/full how is my book")[2] == "how is my book"


@pytest.mark.parametrize("q", ["Thanks", "thanks!", "ok", "Okay.", "thank you", "got it"])
def test_one_word_replies_get_a_fixed_reply(q):
    assert pathrouter.choose(q)[0] == "ack"


# --- the roads --------------------------------------------------------------------------------------------------------------------------------------

def _ctx():
    return SimpleNamespace(source="the book is Rs 100", decisions=[], problems=[], results={}, images=[], con=None, now=NOW)


def _route():
    return {"role": "read", "model_key": "sonnet", "thinking": "medium", "auto": True, "why": "test", "tools": "all"}


def _dispatch(con, q, cid=5, first=None):
    from pflab.hq import passes
    ctx = _ctx()
    ctx.con = con
    pid = passes.record(con, NOW, "assistant", [], "m", "assistant", "running")
    return session.dispatch(SimpleNamespace(data_root=str(Path(".")), settings={}), con, NOW, ctx=ctx, pid=pid, first=first or f"HIS MESSAGE:\n{q}", r=_route(), model_id=None, cid=cid, aid=99, q=q,
                            progress=lambda s: None)


def test_ack_makes_no_model_call(con):
    out = _dispatch(con, "Thanks")
    assert out["text"] == pathrouter.ACK_REPLY and FakeClient.seen == [] and out["meta_obj"]["path"] == "ack" and out["meta_obj"]["tokens"] == 0


def test_light_road_limits_and_the_token_line(con):
    FakeClient.script = [result("", structured={"answer": "It is Rs 100.", "needs_full": False, "why": ""}, usage={"input_tokens": 50, "output_tokens": 20, "cache_read_input_tokens": 9000})]
    out = _dispatch(con, "How is my book today?")
    o = FakeClient.seen[-1]
    assert out["text"] == "It is Rs 100." and out["meta_obj"]["path"] == "quick" and "quick" in out["meta"] and "tokens" in out["meta"]
    assert o.tools == [] and o.setting_sources == [] and isinstance(o.system_prompt, str)
    assert list(o.mcp_servers) == ["light"] and o.max_turns == 4 and o.allowed_tools == ["mcp__light__*"] and not o.agents
    assert o.model == "claude-sonnet-5-5"                                                   # Auto means Sonnet on the quick road
    assert len(o.system_prompt.splitlines()) <= 40


def test_light_road_refuses_a_builtin_tool(con):
    FakeClient.script = [result("", structured={"answer": "x", "needs_full": False, "why": ""})]
    _dispatch(con, "How is my book today?")
    o = FakeClient.seen[-1]
    r = asyncio.run(o.can_use_tool("Bash", {"command": "ls"}, None))
    assert r.behavior == "deny"


def test_light_tools_are_five_and_small():
    names = [t[0] for t in light.tools_for(_ctx())]
    assert names == ["book_card", "today_card", "name_card", "decisions_card", "graph_name"]
    assert len(light.compact('{"a": [' + ",".join(["1.23456"] * 900) + "]}")) <= light.TOOL_CHARS + 20


def test_escalation_happens_once_with_the_summary_and_never_loops(con):
    seq = iter([[result("", structured={"answer": "", "needs_full": True, "why": "needs a correlation study"})], [result("Full answer.", sid="F1")]])
    FakeClient.script = lambda opts: next(seq)
    out = _dispatch(con, "Are these two related?")
    assert out["text"] == "Full answer." and out["meta_obj"]["path"] == "full" and "quick road passed it on" in out["meta"]
    assert len(FakeClient.seen) == 2 and isinstance(FakeClient.seen[0].system_prompt, str) and FakeClient.seen[1].system_prompt == session.PRESET
    FakeClient.seen.clear()                                                                  # the full road has no way back
    FakeClient.script = [result("done", sid="F2")]
    _dispatch(con, "look into CCCC", cid=6)
    assert len(FakeClient.seen) == 1 and FakeClient.seen[0].system_prompt == session.PRESET


def test_a_failing_quick_road_goes_to_full_once_and_a_plan_limit_pauses(con):
    seq = iter([[result("boom", is_error=True, status=500)], [result("Full answer.")]])
    FakeClient.script = lambda opts: next(seq)
    out = _dispatch(con, "How is my book today?")
    assert out["text"] == "Full answer." and len(FakeClient.seen) == 2
    FakeClient.seen.clear()
    FakeClient.script = [result("usage limit reached. resets at 3pm", is_error=True, status=429)]
    out = _dispatch(con, "What is my biggest risk right now?", cid=8)
    assert "paused" in out["text"].lower() and len(FakeClient.seen) == 1


def test_thread_summary_is_kept_per_thread_and_rewritten_every_ten(con, monkeypatch):
    msgs = [{"msg_id": i, "role": "user" if i % 2 else "assistant", "text": f"line {i} " + "x" * 200, "status": "done"} for i in range(1, 31)]
    monkeypatch.setattr("pflab.entrance.store.messages", lambda c, cid: msgs if cid == 1 else [])
    s, recent = light.history(con, 1, 99, "now?")
    assert len(recent.splitlines()) == 6 and recent.splitlines()[-1].startswith("You: line 30")
    assert len(s.splitlines()) == 10 and "line 24" in s and all(len(x) <= 120 for x in s.splitlines())
    assert con.execute("SELECT n_older FROM oper_thread_summary_s88 WHERE chat_id=1").fetchone()[0] == 24
    assert light.history(con, 2, 99, "now?") == ("", "")                                      # another thread: its own
    msgs.extend({"msg_id": 40 + i, "role": "user", "text": f"new {i}", "status": "done"} for i in range(3))
    s2, _ = light.history(con, 1, 99, "now?")
    assert s2 == s                                                                           # fewer than ten new messages: kept as it was
    msgs.extend({"msg_id": 60 + i, "role": "user", "text": f"newer {i}", "status": "done"} for i in range(8))
    s3, _ = light.history(con, 1, 99, "now?")
    assert s3 != s                                                                           # ten more: rewritten


def test_full_road_offers_a_trimmed_toolset_with_a_door_to_the_rest():
    items = otools.items(_ctx())
    names = [i[0] for i in items]
    assert "more_tools" in names and len(names) < 35 and "paper_book" in names
    full = otools.items(_ctx(), core_only=False)
    assert len(full) > len(items)
    more = [i for i in items if i[0] == "more_tools"][0]
    rest = [n for n, *_ in full if n not in names]
    assert rest and rest[0] in more[1] + more[3]({"name": "?"})


def test_full_road_loads_only_the_skills_a_request_needs_and_resets_a_long_session(con):
    assert pathrouter.skills_for("do A and B move together") == ["pair_study"] and pathrouter.skills_for("look into CCCC") == ["case_review"]
    assert pathrouter.skills_for("anything else") == []
    session.put_session(con, 9, "OLD", NOW)
    session.put_hist(con, 9, 70000, NOW)
    FakeClient.script = [result("ok", sid="NEW")]
    _dispatch(con, "look into CCCC", cid=9)
    o = FakeClient.seen[-1]
    assert o.resume is None and o.skills == ["case_review"]                                  # past 60k tokens: a fresh session
    assert session.get_session(con, 9) == "NEW" and session.hist_tokens(con, 9) < 70000
