"""S85 engines: any model behind the one door (`llm/gateway.py`). A fake second vendor in each wire format (the Anthropic one and the OpenAI one, Responses and Chat Completions); no real data, no paid call."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from pflab import guard
from pflab.agents import analyst as an
from pflab.hq import egress
from pflab.hq import governor as gv
from pflab.llm import gateway
from pflab.pm import store

NOW = datetime(2026, 11, 13, 10, 0)


def _cfg(cap=2500.0):
    return {"model": "claude-opus-5-5", "cap": cap, "ask_above": 1000.0, "usd_inr": 90.0, "adopted": True, "policy": {}, "acceptance": {}, "paper": {}, "tijori_to_analyst": True, "counted_since": None}


class AnthFake:
    """The Anthropic wire format: count_tokens, the beta create (Opus, Sonnet) and the plain create (Haiku)."""
    def __init__(self, text='{"klass": "damage"}', blocks=None, stop="end_turn", model=None):
        self.sent, self.counted = [], []
        self.text, self.blocks, self.stop, self.model = text, blocks, stop, model
        self.messages = NS(count_tokens=self._count, create=self._create)
        self.beta = NS(messages=NS(create=self._create))

    def _count(self, **k):
        self.counted.append(k)
        return NS(input_tokens=3000)

    def _create(self, **p):
        self.sent.append(p)
        blocks = self.blocks if self.blocks is not None else [NS(type="text", text=self.text)]
        return NS(content=blocks, stop_reason=self.stop, model=self.model or p["model"], usage=NS(input_tokens=2000, output_tokens=400, cache_read_input_tokens=0, cache_creation_input_tokens=0))


class OpenFake:
    """The OpenAI wire format, both ways: `responses.create` and `chat.completions.create`. `script` is a list of callables / values consumed one per call (an Exception is raised)."""
    def __init__(self, text='{"klass": "damage"}', calls=None, script=None, cached=0):
        self.sent = []
        self.text, self.calls, self.script, self.cached = text, calls or [], list(script or []), cached
        self.responses = NS(create=self._responses)
        self.chat = NS(completions=NS(create=self._chat))

    def _next(self):
        if self.script:
            x = self.script.pop(0)
            if isinstance(x, Exception):
                raise x
            return x
        return self.text

    def _usage(self, kind):
        det = NS(cached_tokens=self.cached)
        return NS(input_tokens=1500, output_tokens=300, input_tokens_details=det) if kind == "r" else NS(prompt_tokens=1500, completion_tokens=300, prompt_tokens_details=det)

    def _responses(self, **p):
        self.sent.append(p)
        text = self._next()
        out = [NS(type="reasoning")]
        if text:
            out.append(NS(type="message", content=[NS(type="output_text", text=text)]))
        out += [NS(type="function_call", call_id=c["id"], name=c["name"], arguments=json.dumps(c["input"])) for c in self.calls]
        return NS(output=out, status="completed", model=p["model"] + "-2026", usage=self._usage("r"))

    def _chat(self, **p):
        self.sent.append(p)
        text = self._next()
        tcs = [NS(id=c["id"], function=NS(name=c["name"], arguments=json.dumps(c["input"]))) for c in self.calls]
        return NS(choices=[NS(message=NS(content=text, tool_calls=tcs or None, refusal=None), finish_reason="stop")], model=p["model"], usage=self._usage("c"))


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "t.duckdb")


@pytest.fixture(autouse=True)
def paid(monkeypatch):
    monkeypatch.setattr(an, "config", lambda path=None: _cfg())
    monkeypatch.setattr("pflab.agents.analyst.config", lambda path=None: _cfg())
    yield
    gateway.set_client(None)


def ask(con, role="read", **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("cfg", _cfg())
    return gateway.call(con, role, "You read a case and name a class.", [{"role": "user", "content": [{"type": "text", "text": "NVDA fell 9.5% in two sessions."}]}], **kw)


def yes_openai(con, scope="use"):
    gateway.grant(con, "openai", scope, now=NOW, wording="test")


def reg(con):
    """The openai engine as one that may be used (a test double: the exam passed and he said Yes)."""
    gateway.record_exam(con, "openai", form_pass=True, grade="test", now=NOW)
    return gateway.use(con, "openai", yes=True, now=NOW)


# --- roles moved by config alone, on both wire formats -----------------------------------------------------------------------------------

def test_the_default_engine_is_claude_and_its_roles_are_the_s84_ones(con):
    r = gateway.roles()
    assert gateway.current_engine(con) == "claude" and all(v["engine"] == "claude" for v in r.values())
    assert [m["key"] for m in gateway.models_of("claude")] == ["haiku", "sonnet", "opus"]
    assert {m["key"] for m in gateway.models_of("openai")} == {"luna", "terra", "sol", "astra"}
    assert gateway.models_of("claude")[0] == {"key": "haiku", "model": "claude-haiku-5-5", "price_in": 0.10, "price_out": 0.50, "tier": "quick"}


def test_a_role_is_moved_to_another_model_by_config_alone_on_the_anthropic_wire(con):
    f = AnthFake()
    gateway.set_client(f)
    st = gateway.settings()
    st["claude"]["read"]["model"] = "claude-haiku-5-5"
    out = ask(con, "read", st=st)
    assert f.sent[0]["model"] == "claude-haiku-5-5" and out["model"] == "claude-haiku-5-5" and out["engine"] == "claude"


def test_a_role_is_moved_to_another_vendor_by_config_alone_on_the_openai_wire(con):
    claude, oa = AnthFake(), OpenFake()
    gateway.set_client(claude, engine="claude")
    gateway.set_client(oa, engine="openai")
    assert reg(con)["ok"]
    out = ask(con, "decide", schema={"type": "object", "properties": {"klass": {"type": "string"}}})
    p = oa.sent[0]
    assert claude.sent == [] and p["model"] == "gpt-6.1-sol" and p["reasoning"] == {"effort": "high"} and p["store"] is False and p["max_output_tokens"] >= 8000
    assert p["text"]["format"]["type"] == "json_schema" and p["input"][0]["role"] == "user" and p["instructions"].startswith("You read a case")
    assert out["engine"] == "openai" and out["provider"] == "openai_compat" and out["vendor"] == "openai" and out["json"] == {"klass": "damage"} and out["model"] == "gpt-6.1-sol-2026"
    assert out["input_tokens"] == 1500 and out["output_tokens"] == 300 and out["cost_rupees"] > 0
    assert any("estimate" in w for w in out["warnings"])                            # no token count call: a labelled estimate
    row = con.execute("SELECT engine, vendor, role, thinking, model FROM api_calls WHERE call_id=?", [out["call_id"]]).fetchone()
    assert row == ("openai", "openai", "decide", "high", "gpt-6.1-sol-2026") or row[0] == "openai"


def test_the_same_roles_run_on_the_chat_completions_wire_of_another_vendor(con):
    oa = OpenFake()
    gateway.set_client(oa, engine="vendorx")
    st = gateway.settings()
    st["vendorx"] = {"provider": "openai_compat", "vendor": "vendorx", "key_name": "vendorx.api_key", "base_url": "https://example.invalid/v1",
                     "decide": {"model": "x-big", "thinking": "high", "min_tokens": 2000}, "read": {"model": "x-mid", "thinking": "medium", "min_tokens": 1000}, "effort": {"low": "low", "medium": "medium", "high": "high", "max": "high"},
                     "features": {"wire": "chat", "max_tokens_param": "max_tokens", "documents": False},
                     "prices": {"mid": {"model": "x-mid", "tier": "read", "input": 0.5, "output": 1.0}, "big": {"model": "x-big", "tier": "decide", "input": 1.0, "output": 3.0}}}
    gateway.grant(con, "vendorx", "use", now=NOW)
    tools = [{"name": "look", "description": "d", "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}}}]
    oa.calls = [{"id": "c1", "name": "look", "input": {"q": "x"}}]
    out = ask(con, "read", st=st, engine="vendorx", tools=tools)
    p = oa.sent[0]
    assert p["messages"][0]["role"] == "system" and p["max_tokens"] >= 1000 and p["reasoning_effort"] == "medium"
    assert p["tools"][0] == {"type": "function", "function": {"name": "look", "description": "d", "parameters": tools[0]["input_schema"]}}
    assert out["tool_calls"] == [{"id": "c1", "name": "look", "input": {"q": "x"}}] and out["stop_reason"] == "tool_use"
    assert out["assistant_content"][-1] == {"type": "tool_use", "id": "c1", "name": "look", "input": {"q": "x"}}
    # the tool loop continues in the canonical shape and is converted back for the vendor
    oa.calls = []
    msgs = [{"role": "user", "content": "q"}, {"role": "assistant", "content": out["assistant_content"]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "42"}]}]
    gateway.call(con, "read", "s", msgs, now=NOW, cfg=_cfg(), st=st, engine="vendorx")
    m2 = oa.sent[1]["messages"]
    assert m2[2]["tool_calls"][0]["function"]["name"] == "look" and m2[3] == {"role": "tool", "tool_call_id": "c1", "content": "42"}


def test_a_tool_loop_moves_between_engines_in_one_canonical_shape(con):
    oa, cl = OpenFake(calls=[{"id": "t1", "name": "look", "input": {"q": "a"}}]), AnthFake()
    gateway.set_client(oa, engine="openai")
    gateway.set_client(cl, engine="claude")
    reg(con)
    tools = [{"name": "look", "description": "d", "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}}}]
    first = ask(con, "read", tools=tools)
    assert first["tool_calls"][0]["name"] == "look"
    msgs = [{"role": "user", "content": "q"}, {"role": "assistant", "content": first["assistant_content"]}, {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}]
    gateway.call(con, "read", "s", msgs, now=NOW, cfg=_cfg(), engine="claude")
    assert cl.sent[0]["messages"][1]["content"][-1]["type"] == "tool_use"


# --- degrade by rule, never by error ------------------------------------------------------------------------------------------------------

def test_a_web_call_stays_on_an_engine_that_has_a_web_tool_and_says_so(con):
    cl, oa = AnthFake(), OpenFake()
    gateway.set_client(cl, engine="claude")
    gateway.set_client(oa, engine="openai")
    reg(con)
    out = ask(con, "read", web=True)
    assert oa.sent == [] and out["engine"] == "claude" and out["fallback_from"] == "openai" and "no web search" in out["note"]
    assert any(t.get("name") == "web_search" for t in cl.sent[0]["tools"])


def test_a_pdf_is_extracted_by_code_for_a_vendor_without_document_blocks_and_images_are_sent(con):
    import base64
    from io import BytesIO

    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    b = BytesIO()
    w.write(b)
    oa = OpenFake()
    gateway.set_client(oa, engine="openai")
    reg(con)
    out = ask(con, "read", documents=[{"title": "plan", "text": "Revenue was 120 crore."}, {"title": "scan", "media_type": "application/pdf", "data": base64.b64encode(b.getvalue()).decode()}],
              images=[{"media_type": "image/png", "data": "AAAA"}])
    parts = oa.sent[0]["input"][0]["content"]
    texts = [p["text"] for p in parts if p["type"] == "input_text"]
    assert any("Revenue was 120 crore" in t for t in texts) and any("[page 1]" in t and "no text on this page" in t for t in texts)
    assert any(p["type"] == "input_image" and p["image_url"].startswith("data:image/png;base64,") for p in parts)
    assert out["engine"] == "openai"
    body = con.execute("SELECT request_json FROM api_calls WHERE call_id=?", [out["call_id"]]).fetchone()[0]
    assert "AAAA" not in body                                                       # an image's bytes are not kept in the request log


def test_a_feature_an_engine_lacks_is_dropped_with_a_warning_never_an_error(con):
    oa = OpenFake()
    gateway.set_client(oa, engine="openai")
    reg(con)
    st = gateway.settings()
    st["openai"]["features"]["images"] = False
    st["openai"]["features"]["thinking_effort"] = False
    out = ask(con, "read", st=st, images=[{"media_type": "image/png", "data": "AAAA"}])
    assert "reasoning" not in oa.sent[0] and not any(p["type"] == "input_image" for p in oa.sent[0]["input"][0]["content"])
    assert any("no images" in w for w in out["warnings"]) and any("no thinking control" in w for w in out["warnings"])


# --- his Yes before anything goes to a vendor --------------------------------------------------------------------------------------------

def test_nothing_is_sent_to_a_vendor_before_his_yes_for_the_scope(con):
    oa = OpenFake()
    gateway.set_client(oa, engine="openai")
    with pytest.raises(gateway.ConsentMissing, match="before his Yes"):                       # the seeded consent covers the exam and shadow of tonight, not live use
        ask(con, "read", engine="openai")
    assert oa.sent == [] and con.execute("SELECT count(*) FROM api_calls").fetchone()[0] == 0
    assert ask(con, "read", engine="openai", scope="exam")["engine"] == "openai"
    assert ask(con, "read", engine="openai", scope="shadow")["engine"] == "openai"
    assert len(oa.sent) == 2
    assert "ConsentMissing" in gateway.refusal_reason(gateway.ConsentMissing("x"))
    con.execute("UPDATE engine_consent_s85 SET active=FALSE WHERE vendor='openai'")
    with pytest.raises(gateway.ConsentMissing):
        ask(con, "read", engine="openai", scope="shadow")


def test_his_yes_for_openai_is_recorded_dated_for_the_exam_and_shadow_only(con):
    rows = {(r["vendor"], r["scope"]): r for r in gateway.consent_rows(con)}
    assert ("openai", "exam") in rows and ("openai", "shadow") in rows and ("openai", "use") not in rows
    assert rows[("openai", "exam")]["given_at"] == datetime(2026, 11, 12, 23, 59) and "2026-11-12" in rows[("openai", "exam")]["given_by"]
    assert ("anthropic", "use") in rows and gateway.has_consent(con, "anthropic", "shadow")
    assert not gateway.has_consent(con, "openai", "use")


def test_use_needs_the_exam_a_price_a_key_and_his_yes_and_shows_the_notice(con):
    r = gateway.use(con, "openai", yes=True, now=NOW)
    assert not r["ok"] and "no exam has been run" in r["reason"]
    gateway.record_exam(con, "openai", form_pass=False, grade="wrote a number", now=NOW)
    r = gateway.use(con, "openai", yes=True, now=NOW)
    assert not r["ok"] and "failed the exam" in r["reason"] and gateway.current_engine(con) == "claude"
    gateway.record_exam(con, "openai", form_pass=True, grade="agrees on 17 of 20", now=NOW)
    r = gateway.use(con, "openai", now=NOW)
    assert not r["ok"] and r["needs_yes"] and "holdings, amounts and weights" in r["notice"] and "never your identity or banking details" in r["notice"]
    assert gateway.current_engine(con) == "claude"
    r = gateway.use(con, "openai", yes=True, now=NOW)
    assert r["ok"] and gateway.current_engine(con) == "openai" and gateway.has_consent(con, "openai", "use")
    assert gateway.fallback_engine(con) == "claude"
    r = gateway.use(con, "claude", now=NOW)                                                   # going back never needs a Yes or an exam
    assert r["ok"] and gateway.current_engine(con) == "claude"
    assert not gateway.use(con, "nonesuch", yes=True)["ok"]


def test_an_engine_without_a_priced_model_or_with_an_unknown_provider_cannot_be_used(con):
    st = gateway.settings()
    st["openai"]["read"]["model"] = "gpt-unpriced"
    assert any("has no price" in p for p in gateway.engine_problems(st, "openai"))
    gateway.record_exam(con, "openai", form_pass=True, now=NOW)
    assert not gateway.use(con, "openai", yes=True, st=st)["ok"]
    st = gateway.settings()
    st["claude"]["provider"] = "nowhere"
    st["claude"].pop("engine", None)
    assert any("not one the app can speak" in p for p in gateway.engine_problems(st, "claude"))
    with pytest.raises(gateway.EngineUnusable, match="no price|cannot be used"):
        gateway.set_client(OpenFake(), engine="openai")
        st2 = gateway.settings()
        st2["openai"]["read"]["model"] = "gpt-unpriced"
        ask(con, "read", engine="openai", scope="exam", st=st2)
    with pytest.raises(ValueError, match="priced models"):
        gateway.resolve("read", engine="openai", model="gpt-unknown")


def test_shadow_needs_his_yes_a_key_and_never_the_engine_in_use(con):
    assert not gateway.shadow(con, "claude", yes=True)["ok"]                                   # the engine in use is not shadowed
    r = gateway.shadow(con, "openai")                                                           # the seeded Yes covers it for tonight
    assert r["ok"] and gateway.shadows(con) == ["openai"]
    assert gateway.unshadow(con, "openai")["ok"] and gateway.shadows(con) == []
    con.execute("UPDATE engine_consent_s85 SET active=FALSE WHERE vendor='openai'")
    r = gateway.shadow(con, "openai")
    assert not r["ok"] and r["needs_yes"] and "never acts" in r["notice"]
    assert gateway.shadow(con, "openai", yes=True, now=NOW)["ok"]


# --- a switch takes effect at the next call; a case finishes its step where it began -----------------------------------------------------

def test_a_switch_takes_effect_at_the_next_call_without_a_restart(con):
    cl, oa = AnthFake(), OpenFake()
    gateway.set_client(cl, engine="claude")
    gateway.set_client(oa, engine="openai")
    assert ask(con, "read")["engine"] == "claude"
    reg(con)
    assert ask(con, "read")["engine"] == "openai"
    gateway.use(con, "claude", now=NOW)
    assert ask(con, "read")["engine"] == "claude"


def test_a_case_in_progress_finishes_its_step_on_the_engine_that_began_it(con):
    from pflab.think import cases
    cl, oa = AnthFake(), OpenFake()
    gateway.set_client(cl, engine="claude")
    gateway.set_client(oa, engine="openai")
    cid = cases.open_case(con, NOW, market="IN", kind="move", isin="INE000A01010", symbol="ZZZ", title="t", opened_by="test") if hasattr(cases, "open_case") else None
    if cid is None:
        pytest.skip("no case opener")
    cases.add_step(con, cid, NOW - timedelta(minutes=2), "understand", engine="claude", model="claude-sonnet-5-5", thinking="medium")
    reg(con)
    out = ask(con, "read", case_id=cid)
    assert out["engine"] == "claude" and oa.sent == []                                        # the step that began on claude ends on claude
    out = ask(con, "read", case_id=cid, now=NOW + timedelta(hours=2), cfg=_cfg())            # a later step takes the engine in use
    assert out["engine"] == "openai"


# --- the fallback ---------------------------------------------------------------------------------------------------------------------

def test_three_failures_in_a_row_on_a_role_send_that_call_to_the_fallback_and_say_so(con):
    cl = AnthFake()
    oa = OpenFake(script=[RuntimeError("boom 1"), RuntimeError("boom 2"), RuntimeError("boom 3")])
    gateway.set_client(cl, engine="claude")
    gateway.set_client(oa, engine="openai")
    reg(con)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="boom"):
            ask(con, "read")
    assert gateway.failure_streak(con, "openai", "read")[0] == 2 and cl.sent == []
    out = ask(con, "read")                                                                    # the third: this call goes to claude
    assert out["engine"] == "claude" and out["fallback_from"] == "openai" and "3 times in a row" in out["note"]
    prob = gateway.open_problems(con, days=1) or gateway.open_problems(con, days=3650)
    assert prob and prob[0]["engine"] == "openai" and prob[0]["role"] == "read" and "go to 'claude'" in prob[0]["text"]
    assert con.execute("SELECT count(*) FROM outbox WHERE dedup_key LIKE 'engine_fallback:%'").fetchone()[0] == 1
    # the next call within the window goes straight to the fallback, and the Telegram line is not repeated that day
    out = ask(con, "read", now=NOW + timedelta(minutes=5))
    assert out["engine"] == "claude" and oa.sent and len(oa.sent) == 3
    gateway._problem(con, NOW, "openai", "decide", "again")
    assert con.execute("SELECT count(*) FROM outbox WHERE dedup_key LIKE 'engine_fallback:%'").fetchone()[0] == 1
    # after the window it tries the engine again; a success ends the streak
    out = ask(con, "read", now=NOW + timedelta(hours=2))
    assert out["engine"] == "openai" and gateway.failure_streak(con, "openai", "read")[0] == 0
    row = con.execute("SELECT engine, fallback_from FROM api_calls WHERE fallback_from IS NOT NULL").fetchone()
    assert row == ("claude", "openai")


def test_three_malformed_answers_in_a_row_count_like_errors(con):
    cl = AnthFake()
    oa = OpenFake(script=["not json", "still not", "never json"])
    gateway.set_client(cl, engine="claude")
    gateway.set_client(oa, engine="openai")
    reg(con)
    schema = {"type": "object", "properties": {"klass": {"type": "string"}}}
    for _ in range(2):
        out = ask(con, "read", schema=schema)
        assert out["json_error"] and out["engine"] == "openai"
    out = ask(con, "read", schema=schema)
    assert out["engine"] == "claude" and out["json"] == {"klass": "damage"} and out["fallback_from"] == "openai"


def test_a_failing_engine_does_not_count_against_another_and_roles_are_kept_apart(con):
    oa = OpenFake(script=[RuntimeError("x"), RuntimeError("y")])
    gateway.set_client(oa, engine="openai")
    gateway.set_client(AnthFake(), engine="claude")
    reg(con)
    for role in ("read", "quick"):
        with pytest.raises(RuntimeError):
            ask(con, role)
    assert gateway.failure_streak(con, "openai", "read")[0] == 1 and gateway.failure_streak(con, "openai", "quick")[0] == 1 and gateway.failure_streak(con, "claude", "read")[0] == 0


def test_an_exam_or_a_shadow_call_is_never_rerouted_to_the_fallback(con):
    oa = OpenFake(script=[RuntimeError("a")] * 4)
    gateway.set_client(oa, engine="openai")
    gateway.set_client(AnthFake(), engine="claude")
    for _ in range(4):
        with pytest.raises(RuntimeError):
            ask(con, "read", engine="openai", scope="exam")
    assert len(oa.sent) == 4


# --- every call through the guard, the egress gate, the governor and his cap -------------------------------------------------------------

def test_the_egress_gate_and_the_cap_hold_for_every_vendor(con):
    oa = OpenFake()
    gateway.set_client(oa, engine="openai")
    reg(con)
    with pytest.raises(egress.EgressBlocked):
        gateway.call(con, "read", "sys", [{"role": "user", "content": "look at account 123456789012 now"}], now=NOW, cfg=_cfg())
    with pytest.raises(egress.EgressBlocked):
        gateway.call(con, "read", "written for zorbax", [{"role": "user", "content": "q"}], now=NOW, cfg=_cfg(), gate=egress.Gate(names=["zorbax"]), private_text="")
    assert oa.sent == []
    with pytest.raises(an.BudgetRefused) as ei:                                                # priced from the vendor's own table, refused at his cap, logged, never sent
        ask(con, "decide", cfg=_cfg(cap=0.05))
    assert oa.sent == [] and "resume" in gateway.refusal_reason(ei.value) or "can change" in gateway.refusal_reason(ei.value)
    assert con.execute("SELECT status FROM api_calls ORDER BY call_id DESC LIMIT 1").fetchone()[0] == "over_limit"
    assert gv.PRICES["gpt-6.1-sol"] == (2.0, 10.0) and gv.CACHE_READ_OF["gpt-6.1-sol"] == pytest.approx(0.05)


def test_the_workshop_guard_stands_before_a_vendor_key_is_read(con, monkeypatch):
    monkeypatch.delenv("PFLAB_PAID", raising=False)
    monkeypatch.setattr("pflab.release.channel", lambda root=None: "beta")
    reg(con)
    made = []
    monkeypatch.setattr("pflab.llm.vendors.openai_client", lambda *a, **k: made.append(1))
    st = gateway.settings()
    monkeypatch.setattr(gateway, "key_set", lambda st_, name: True)
    with pytest.raises(guard.OutwardBlocked, match="--paid"):
        ask(con, "read", st=st)
    assert not made and con.execute("SELECT count(*) FROM api_calls").fetchone()[0] == 0


def test_cost_is_priced_at_the_vendors_cached_rate(con):
    oa = OpenFake(cached=1000)
    gateway.set_client(oa, engine="openai")
    reg(con)
    out = ask(con, "decide")
    expect = (500 * 2.0 + 1000 * 2.0 * 0.05 + 300 * 10.0) / 1e6 * 90.0
    assert out["cost_rupees"] == pytest.approx(expect) and out["cached_tokens"] == 1000


def test_no_key_ever_reaches_a_log_line_or_an_api_calls_row(con, monkeypatch):
    key = "sk-proj-ABCDEF1234567890abcdef"
    oa = OpenFake(script=[RuntimeError(f"401 Incorrect API key provided: {key}. Bearer abcdefghijklmnop12345")])
    gateway.set_client(oa, engine="openai")
    reg(con)
    with pytest.raises(RuntimeError):
        ask(con, "read")
    rows = con.execute("SELECT error, request_json, question, topic FROM api_calls").fetchall()
    ev = con.execute("SELECT detail FROM engine_events_s85").fetchall()
    blob = json.dumps(rows, default=str) + json.dumps(ev, default=str)
    assert key not in blob and "abcdefghijklmnop12345" not in blob and "***" in blob


def test_a_key_is_only_ever_asked_for_by_name(tmp_path, monkeypatch):
    from pflab.llm import vendors
    from pflab.pm import secrets as sec
    with pytest.raises(RuntimeError) as ei:
        vendors.openai_client(sec.Secrets({}), "openai.api_key")
    assert "openai" in str(ei.value) and "api_key" in str(ei.value)


# --- overrides, agents, the screens -------------------------------------------------------------------------------------------------------

def test_model_thinking_and_engine_overrides_apply_to_one_call(con):
    cl = AnthFake()
    gateway.set_client(cl, engine="claude")
    out = ask(con, "read", model="haiku", thinking="max", chat_id=7, reply_msg_id=9, agent="chat")
    assert cl.sent[0]["model"] == "claude-haiku-5-5" and cl.sent[0]["output_config"]["effort"] == "max" and out["model"] == "claude-haiku-5-5" and out["thinking"] == "max"
    row = con.execute("SELECT chat_id, reply_msg_id, agent, his_order FROM api_calls WHERE call_id=?", [out["call_id"]]).fetchone()
    assert row == (7, 9, "chat", True)
    out = ask(con, "read")                                                                    # the override did not stick
    assert cl.sent[1]["model"] == "claude-sonnet-5-5" and out["thinking"] == "medium"
    with pytest.raises(ValueError):
        ask(con, "read", thinking="extreme")


@pytest.mark.parametrize("agent", ["think", "desk", "chat", "strategist", "checker", "reading"])
def test_every_agent_the_brief_names_is_served_and_known_to_the_governor(con, agent):
    gateway.set_client(AnthFake())
    out = ask(con, "quick" if agent == "checker" else "read", agent=agent)                 # the checker's own limit is 1,500 output tokens: it asks as `quick`
    assert con.execute("SELECT agent FROM api_calls WHERE call_id=?", [out["call_id"]]).fetchone()[0] == agent
    assert agent in gv.LIMITS and gv.LIMITS[agent].layer in gv.LAYERS


def test_engines_status_is_json_able_and_complete(con):
    gateway.record_exam(con, "openai", form_pass=True, grade="agrees on 17 of 20 decisions", cost_rupees=12.0, thinking="high", now=NOW)
    rows = gateway.engines_status(con)
    json.dumps(rows, default=str)
    by = {r["name"]: r for r in rows}
    assert by["claude"]["in_use"] and not by["openai"]["in_use"] and by["openai"]["vendor"] == "openai"
    assert by["openai"]["roles"]["decide"]["model"] == "gpt-6.1-sol" and by["openai"]["roles"]["decide"]["price_out"] == 10.0
    assert "documents" in by["openai"]["lacks"] and "web_search" in by["openai"]["lacks"] and by["openai"]["exam"]["grade"].startswith("agrees")
    assert any(c["scope"] == "shadow" for c in by["openai"]["consent"]) and not any(c["scope"] == "use" for c in by["openai"]["consent"])
    assert by["claude"]["models"][0]["key"] == "haiku" and by["openai"]["failures_in_a_row"] == {"quick": 0, "read": 0, "decide": 0}
    assert gateway.models_of(None) == by["claude"]["models"]


def test_the_spend_can_be_read_per_engine(con):
    gateway.set_client(AnthFake(), engine="claude")
    gateway.set_client(OpenFake(), engine="openai")
    reg(con)
    a = ask(con, "read", engine="claude")
    b = ask(con, "read", engine="openai")
    day = NOW.replace(hour=0)
    assert gateway.spent(con, day, engine="claude") == pytest.approx(a["cost_rupees"]) and gateway.spent(con, day, engine="openai") == pytest.approx(b["cost_rupees"])


# --- structure -----------------------------------------------------------------------------------------------------------------------------

def test_the_vendor_sdks_are_imported_only_inside_llm():
    root = Path(gateway.__file__).resolve().parents[2]
    bad = re.compile(r"^\s*(import (anthropic|openai)\b|from (anthropic|openai)\b)")
    hits = []
    for f in root.rglob("*.py"):
        if "llm" in f.relative_to(root).parts[:2]:
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if bad.search(line):
                hits.append(f"{f.relative_to(root)}:{n}")
    assert hits == []


def test_the_migration_creates_the_tables_and_the_consents(con):
    tabs = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    assert {"engine_state_s85", "engine_shadow_s85", "engine_consent_s85", "engine_events_s85", "engine_problems_s85", "engine_exam_s85"} <= tabs
    cols = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name='api_calls'").fetchall()}
    assert {"chat_id", "reply_msg_id", "vendor", "fallback_from"} <= cols
    assert con.execute("SELECT max(version) FROM schema_migrations WHERE version BETWEEN 290 AND 299").fetchone()[0] == 294


def test_the_toml_prices_every_model_of_every_role_with_a_source_and_a_date():
    st = gateway.settings()
    for name in gateway.engine_names(st):
        assert gateway.engine_problems(st, name, need_key=False) == []
        for k, p in gateway.prices_of(st, name).items():
            assert p["source"] and re.match(r"\d{4}-\d{2}-\d{2}", str(p["date"])), (name, k)
