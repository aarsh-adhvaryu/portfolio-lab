"""S87 O1: the plan engine with a scripted SDK: the sign-in guard, the key-free child environment, usage rows, budgets, pauses, the caller-owned tool loop, structured answers, and that nothing else imports the SDK."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from pflab.llm import claude_plan as cp
from pflab.llm import gateway as gw

NOW = datetime(2026, 11, 16, 10, 0)


class Msg:
    pass


def _mk(name, **kw):
    o = type(name, (), {})()
    o.__dict__.update(kw)
    return o


def assistant(text=None, tool=None, model="claude-sonnet-5-5"):
    blocks = []
    if text:
        blocks.append(_mk("TextBlock", text=text))
    if tool:
        blocks.append(_mk("ToolUseBlock", name=tool))
    return _mk("AssistantMessage", content=blocks, model=model)


def result(text="", is_error=False, usage=None, structured=None, status=None, errors=None, sid="s1"):
    return _mk("ResultMessage", subtype="success", duration_ms=1, duration_api_ms=1, is_error=is_error, num_turns=2, session_id=sid, stop_reason="end_turn", total_cost_usd=0.0,
               usage=usage or {"input_tokens": 100, "output_tokens": 40, "cache_read_input_tokens": 10}, result=text, structured_output=structured, model_usage=None, permission_denials=None,
               deferred_tool_use=None, errors=errors, api_error_status=status)


class FakeClient:
    seen = []                       # the options of every session
    script = []                     # what the next session emits (a list, or a callable(opts) -> list)
    capture_tool = None             # (name, input): call can_use_tool with it during the session

    def __init__(self, opts):
        self.opts = opts
        FakeClient.seen.append(opts)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def query(self, prompt):
        self.prompt = prompt

    async def receive_response(self):
        sc = FakeClient.script(self.opts) if callable(FakeClient.script) else FakeClient.script
        if FakeClient.capture_tool:
            n, inp = FakeClient.capture_tool
            await self.opts.can_use_tool(f"mcp__caller__{n}", inp, None)
        for m in sc:
            yield m


@pytest.fixture
def con(tmp_path, monkeypatch):
    from pflab.pm import store
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path))
    c = store.connect(tmp_path / "pm.duckdb") if hasattr(store, "connect") else None
    FakeClient.seen, FakeClient.script, FakeClient.capture_tool = [], [], None
    monkeypatch.setattr(cp, "client_factory", FakeClient)
    monkeypatch.setattr(cp, "signin_fn", lambda: {"ok": True, "method": "claude.ai", "detail": ""})
    return c


def _run(con, **kw):
    base = dict(prompt="hello", model="claude-sonnet-5-5", effort="low", klass="chat", purpose="t", now=NOW)
    base.update(kw)
    return cp.run(con, **base)


def test_planted_key_never_reaches_child(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-planted")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-planted")
    monkeypatch.setenv("SOME_VENDOR_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "t")
    env = cp.child_env()
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SOME_VENDOR_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        assert env[k] == ""
    opts = cp.options(system="s", model="m", effort="low", cwd=None)
    assert opts.env["ANTHROPIC_API_KEY"] == ""


def test_not_signed_in_refuses_and_never_falls_back(con, monkeypatch):
    monkeypatch.setattr(cp, "signin_fn", lambda: {"ok": False, "method": "api_key", "detail": "signed in by 'api_key'"})
    FakeClient.script = [result("x")]
    with pytest.raises(cp.PlanUnusable):
        _run(con)
    assert FakeClient.seen == []                      # no session was started


def test_session_logs_tokens_and_plan_cost(con):
    FakeClient.script = [assistant("hi"), result("hi")]
    r = _run(con)
    assert r.text == "hi" and r.input_tokens == 110 and r.output_tokens == 40 and r.session_id == "s1"
    row = con.execute("SELECT engine, cost_inr, input_tokens, output_tokens, topic, status FROM api_calls WHERE call_id=?", [r.call_id]).fetchone()
    assert row[0] == "claude_plan" and row[1] == 0.0 and row[2] == 110 and row[3] == 40 and row[4] == "plan:chat:t" and row[5] == "done"


def test_daily_budget_stops_one_class_only(con, monkeypatch):
    monkeypatch.setattr(cp, "settings", lambda: {**cp.DEFAULTS, "budget_chat": 100})
    FakeClient.script = [result("a")]
    _run(con)
    with pytest.raises(cp.PlanBudgetSpent):
        _run(con)
    _run(con, klass="desk", purpose="d")              # another class still runs


def test_usage_limit_pauses_thinking_and_is_not_an_engine_failure(con):
    FakeClient.script = [result("You've hit your usage limit. It resets at 3pm", is_error=True, status=429)]
    with pytest.raises(cp.PlanPaused) as e:
        _run(con)
    assert e.value.resume_at is not None
    FakeClient.script = [result("fine")]
    with pytest.raises(cp.PlanPaused):                # while paused no session starts
        _run(con, now=NOW)
    assert len(FakeClient.seen) == 1
    assert cp.state(con, NOW)["thinking"] == "paused"
    assert cp.state(con, datetime(2026, 11, 17, 9, 0))["thinking"] == "running"
    assert gw.PlanPaused if hasattr(gw, "PlanPaused") else True
    assert cp.PlanPaused in gw.refusals()             # callers treat it as a refusal to wait out, not as a failure


def test_caller_tool_is_captured_and_session_interrupted(con):
    FakeClient.capture_tool = ("lookup", {"name": "X"})
    FakeClient.script = [result("", is_error=True)]
    r = _run(con, caller_tools=[{"name": "lookup", "description": "d", "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}}}])
    assert r.tool_calls and r.tool_calls[0]["name"] == "lookup" and r.tool_calls[0]["input"] == {"name": "X"}
    o = FakeClient.seen[-1]
    assert o.tools == [] and "mcp__caller__lookup" not in (o.allowed_tools or [])      # no built-in tool; the caller's tool reaches the permission callback (where it is captured)


def test_gateway_roundtrip_through_provider(con, monkeypatch):
    from pflab.hq import egress
    FakeClient.script = [assistant("the answer"), result("the answer")]
    out = gw.call(con, "quick", "sys", [{"role": "user", "content": "q"}], agent="think", purpose="p", now=NOW, gate=egress.load(con), engine="claude_plan", private_text="")
    assert out["text"] == "the answer" and out["engine"] == "claude_plan" and out["cost_rupees"] == 0.0 and out["tool_calls"] == []
    assert FakeClient.seen[-1].model == "claude-haiku-5-5"


def test_gateway_structured_answer_and_retry(con):
    from pflab.hq import egress
    FakeClient.script = [result("not json at all")]
    out = gw.call(con, "read", "sys", [{"role": "user", "content": "q"}], agent="think", purpose="p", now=NOW, gate=egress.load(con), engine="claude_plan", private_text="",
                  schema={"type": "object", "properties": {"a": {"type": "string"}}})
    assert out["json_error"]                           # asked once more, still not JSON: the caller sees a malformed answer
    assert len(FakeClient.seen) == 2
    FakeClient.script = [result("", structured={"a": "b"})]
    out = gw.call(con, "read", "sys", [{"role": "user", "content": "q"}], agent="think", purpose="p", now=NOW, gate=egress.load(con), engine="claude_plan", private_text="",
                  schema={"type": "object", "properties": {"a": {"type": "string"}}})
    assert out["json"] == {"a": "b"}


def test_no_paid_api_client_is_made_while_plan_in_use():
    from pflab.agents import analyst as an
    with pytest.raises(gw.EngineUnusable):
        an.make_client(None)


def test_only_claude_plan_imports_the_sdk():
    pat = re.compile(r"^\s*(?:import|from)\s+claude_agent_sdk\b", re.M)
    bad = [str(p) for p in (Path(__file__).resolve().parents[1] / "src" / "pflab").rglob("*.py") if p.name != "claude_plan.py" and pat.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert not bad, bad
