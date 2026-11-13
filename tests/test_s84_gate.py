"""S84 gate: the one door for model calls (`llm/gateway.py`). A scripted fake stands in for the vendor client (rule 7: no real data, no paid call)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from pflab import guard
from pflab.agents import analyst as an
from pflab.hq import egress
from pflab.hq import governor as gv
from pflab.llm import gateway
from pflab.pm import store

NOW = datetime(2026, 11, 12, 16, 0)


def _cfg(cap=2500.0):
    return {"model": "claude-opus-5-5", "cap": cap, "ask_above": 1000.0, "usd_inr": 90.0, "adopted": True, "policy": {}, "acceptance": {}, "paper": {}, "tijori_to_analyst": True, "counted_since": None}


class Fake:
    """A scripted client: `count_tokens`, the beta create (Opus, Sonnet) and the plain create (Haiku). Records every request."""
    def __init__(self, blocks=None, stop="end_turn", cache_read=0, cache_write=0, model="claude-opus-5-5"):
        self.sent, self.counted = [], []
        self.blocks = blocks if blocks is not None else [SimpleNamespace(type="text", text='{"klass": "damage"}')]
        self.stop, self.cache_read, self.cache_write, self.model = stop, cache_read, cache_write, model
        self.messages = SimpleNamespace(count_tokens=self._count, create=self._create_plain)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _count(self, **k):
        self.counted.append(k)
        return SimpleNamespace(input_tokens=3000)

    def _create(self, **p):
        self.sent.append(p)
        usage = SimpleNamespace(input_tokens=2000, output_tokens=400, cache_read_input_tokens=self.cache_read, cache_creation_input_tokens=self.cache_write)
        return SimpleNamespace(content=self.blocks, stop_reason=self.stop, model=p.get("model", self.model), usage=usage)

    _create_plain = _create


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "t.duckdb")


@pytest.fixture
def paid(monkeypatch):
    monkeypatch.setattr(an, "config", lambda path=None: _cfg())
    return an


@pytest.fixture
def fake():
    f = Fake()
    gateway.set_client(f)
    yield f
    gateway.set_client(None)


def ask(con, role="read", fake_=None, **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("cfg", _cfg())
    return gateway.call(con, role, "You read a case and name a class from the closed list.", [{"role": "user", "content": [{"type": "text", "text": "NVDA fell 9.5% in two sessions."}]}], **kw)


# --- roles and the thinking scale -----------------------------------------------------------------------------------------------------

def test_the_roles_map_to_the_models_and_levels_in_the_config():
    r = gateway.roles()
    assert (r["decide"]["model"], r["decide"]["thinking"]) == ("claude-opus-5-5", "high")
    assert (r["read"]["model"], r["read"]["thinking"]) == ("claude-sonnet-5-5", "medium")
    assert (r["quick"]["model"], r["quick"]["thinking"]) == ("claude-sonnet-5-5", "low")
    assert all(v["engine"] == "claude" and v["note"] == "" for v in r.values())
    st = gateway.settings()
    assert st["default"] == "claude" and st["claude"]["effort"] == {"low": "low", "medium": "medium", "high": "high", "max": "max"}


def test_the_core_toml_holds_the_same_table_the_code_defaults_to():
    from pflab import _toml
    cfg = _toml.load(gateway.CONFIG)["engines"]["claude"]
    for role in gateway.ROLES:
        assert cfg[role]["model"] == gateway.DEFAULTS["claude"][role]["model"] and cfg[role]["thinking"] == gateway.DEFAULTS["claude"][role]["thinking"]


def test_a_role_that_is_not_configured_falls_back_to_the_next_one_up_with_a_note():
    st = gateway.settings()
    st["claude"]["quick"]["enabled"] = False
    r = gateway.resolve("quick", st)
    assert r["role_used"] == "read" and r["role"] == "quick" and "'quick'" in r["note"] and r["model"] == "claude-sonnet-5-5" and r["thinking"] == "medium"
    st["claude"]["read"]["enabled"] = False
    r = gateway.resolve("quick", st)
    assert r["role_used"] == "decide" and r["model"] == "claude-opus-5-5"
    st["claude"]["decide"]["enabled"] = False
    with pytest.raises(ValueError):
        gateway.resolve("quick", st)
    assert "decide" not in gateway.roles(st)
    with pytest.raises(ValueError):
        gateway.resolve("loud")


def test_a_level_off_the_scale_is_refused_and_the_scale_is_mapped_by_a_table(con, paid, fake):
    st = gateway.settings()
    st["claude"]["read"]["thinking"] = "extreme"
    with pytest.raises(ValueError):
        gateway.resolve("read", st)
    st = gateway.settings()
    st["claude"]["effort"]["max"] = "xhigh"                                              # the table is data: the vendor's word for the top of the scale
    st["claude"]["decide"]["thinking"] = "max"
    ask(con, "decide", st=st)
    assert fake.sent[0]["output_config"]["effort"] == "xhigh"


def test_the_request_asks_for_adaptive_thinking_with_effort_and_never_a_budget_or_a_forced_tool(con, paid, fake):
    for role, effort in (("decide", "high"), ("read", "medium"), ("quick", "low")):
        ask(con, role)
        p = fake.sent[-1]
        assert p["thinking"] == {"type": "adaptive"} and p["output_config"]["effort"] == effort and "budget_tokens" not in json.dumps(p)
        assert "tool_choice" not in p and "temperature" not in p
    assert [p["model"] for p in fake.sent] == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-sonnet-5-5"]
    with pytest.raises(ValueError):
        ask(con, "read", tool_choice="any")
    ask(con, "read", tool_choice="none")
    assert fake.sent[-1]["tool_choice"] == {"type": "none"}


def test_thinking_counts_as_output_so_a_small_max_tokens_is_raised_to_the_roles_floor(con, paid, fake):
    ask(con, "decide", max_tokens=1500)
    ask(con, "quick", max_tokens=300)
    ask(con, "quick", max_tokens=6000)
    assert [p["max_tokens"] for p in fake.sent] == [8000, 1500, 6000]


# --- the call: what comes back, and what is logged ------------------------------------------------------------------------------------

def test_cost_cached_tokens_engine_model_and_level_come_back_and_are_logged(con, paid):
    f = Fake(cache_read=1800, cache_write=0)
    gateway.set_client(f)
    try:
        out = ask(con, "decide", case_id=41, purpose="understand", schema={"type": "object", "properties": {"klass": {"type": "string"}}, "required": ["klass"], "additionalProperties": False})
    finally:
        gateway.set_client(None)
    assert out["engine"] == "claude" and out["model"] == "claude-opus-5-5" and out["thinking"] == "high" and out["role"] == "decide" and out["role_used"] == "decide"
    assert out["cached_tokens"] == 1800 and out["cost_rupees"] > 0 and out["json"] == {"klass": "damage"} and out["stop_reason"] == "end_turn" and not out["truncated"]
    expect = gv.cost_inr("claude-opus-5-5", 2000, 400, 90.0, 1800, 0)
    assert out["cost_rupees"] == pytest.approx(expect)
    row = con.execute("SELECT agent, role, engine, thinking, cached_tokens, case_id, purpose, status, cost_inr, model FROM api_calls WHERE call_id=?", [out["call_id"]]).fetchone()
    assert row[:8] == ("think", "decide", "claude", "high", 1800, 41, "understand", "done") and row[8] == pytest.approx(expect) and row[9] == "claude-opus-5-5"
    assert f.sent[0]["output_config"]["format"]["type"] == "json_schema"
    assert gateway.spent(con, NOW.replace(hour=0), case_id=41) == pytest.approx(expect) and gateway.spent(con, NOW.replace(hour=0), agent="desk") == 0.0


def test_a_schema_answer_that_is_not_json_says_so_and_never_raises(con, paid):
    gateway.set_client(Fake(blocks=[SimpleNamespace(type="text", text="the board has not met")]))
    try:
        out = ask(con, "read", schema={"type": "object"})
    finally:
        gateway.set_client(None)
    assert out["json"] == {} and "not valid JSON" in out["json_error"] and out["text"] == "the board has not met"


def test_no_schema_means_no_parsing(con, paid, fake):
    out = ask(con, "read")
    assert out["json"] is None and out["text"].startswith("{")


def test_tool_calls_pass_through_and_the_assistant_turn_can_be_appended(con, paid):
    blocks = [SimpleNamespace(type="text", text="I will look it up."), SimpleNamespace(type="tool_use", id="tu_1", name="recall", input={"symbol": "NVDA"})]
    gateway.set_client(Fake(blocks=blocks, stop="tool_use"))
    tools = [{"name": "recall", "description": "what we know", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}}}]
    try:
        out = ask(con, "read", tools=tools)
    finally:
        gateway.set_client(None)
    assert out["tool_calls"] == [{"id": "tu_1", "name": "recall", "input": {"symbol": "NVDA"}}] and out["stop_reason"] == "tool_use"
    kinds = [b["type"] for b in out["assistant_content"]]
    assert kinds == ["text", "tool_use"] and out["assistant_content"][1]["input"] == {"symbol": "NVDA"}


def test_a_tool_loop_is_one_pass_for_the_governor_and_a_new_conversation_is_a_new_pass(con, paid, fake):
    msgs = [{"role": "user", "content": "first"}]
    ask_ = lambda m: gateway.call(con, "read", "sys", m, now=NOW, cfg=_cfg())
    ask_(msgs)
    msgs += [{"role": "assistant", "content": "x"}, {"role": "user", "content": "second turn"}]
    ask_(msgs)
    assert [r[0] for r in con.execute("SELECT turn FROM api_calls ORDER BY call_id").fetchall()] == [1, 2]


def test_a_scripted_fake_is_injectable_by_argument_or_by_set_client(con, paid):
    a, b = Fake(), Fake()
    ask(con, "read", client=a)
    assert len(a.sent) == 1
    gateway.set_client(b)
    try:
        ask(con, "read")
        ask(con, "read", client=a)                                                           # an explicit client wins over the injected one
    finally:
        gateway.set_client(None)
    assert len(b.sent) == 1 and len(a.sent) == 2


def test_a_model_that_refuses_raises_and_is_recorded(con, paid):
    gateway.set_client(Fake(blocks=[], stop="refusal"))
    try:
        with pytest.raises(RuntimeError, match="declined"):
            ask(con, "decide")
    finally:
        gateway.set_client(None)
    assert con.execute("SELECT status FROM api_calls").fetchone()[0] == "refused"


# --- the caching ----------------------------------------------------------------------------------------------------------------------

def test_the_fixed_part_is_marked_cacheable_and_the_callers_inputs_are_not_changed(con, paid, fake):
    tools = [{"name": "a", "description": "x", "input_schema": {"type": "object"}}, {"name": "b", "description": "y", "input_schema": {"type": "object"}}]
    system = "A long fixed system text."
    messages = [{"role": "user", "content": [{"type": "text", "text": "the book card", "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": "the question"}]}]
    gateway.call(con, "read", system, messages, tools=tools, now=NOW, cfg=_cfg())
    p = fake.sent[0]
    assert p["system"] == [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    assert "cache_control" in p["tools"][-1] and "cache_control" not in p["tools"][0] and p["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in tools[-1] and isinstance(system, str)                    # copies: the caller's lists are as they were
    blob = json.dumps(p)
    assert blob.count("cache_control") <= gateway.MAX_BREAKPOINTS


def test_the_door_never_asks_for_more_cache_markers_than_the_vendor_allows(con, paid, fake):
    system = [{"type": "text", "text": f"block {i}", "cache_control": {"type": "ephemeral"}} for i in range(3)]
    tools = [{"name": "a", "description": "x", "input_schema": {"type": "object"}}]
    gateway.call(con, "read", system, [{"role": "user", "content": "q"}], tools=tools, now=NOW, cfg=_cfg())
    assert json.dumps(fake.sent[0]).count("cache_control") <= gateway.MAX_BREAKPOINTS


def test_caching_can_be_switched_off_in_the_settings(con, paid, fake):
    st = gateway.settings()
    st["claude"]["cache"] = False
    gateway.call(con, "read", "sys", [{"role": "user", "content": "q"}], tools=[{"name": "a", "description": "x", "input_schema": {"type": "object"}}], now=NOW, cfg=_cfg(), st=st)
    assert "cache_control" not in json.dumps(fake.sent[0])


# --- the old road is the road: the guard, the egress gate, the governor and his cap -----------------------------------------------------

def test_the_workshop_without_paid_is_refused_before_anything_is_sent(con, paid, monkeypatch):
    monkeypatch.delenv("PFLAB_PAID", raising=False)
    monkeypatch.setattr("pflab.release.channel", lambda root=None: "beta")
    boom = []
    monkeypatch.setattr("anthropic.Anthropic", lambda *a, **k: boom.append(1))
    with pytest.raises(guard.OutwardBlocked, match="--paid"):
        ask(con, "read")
    assert not boom and con.execute("SELECT count(*) FROM api_calls").fetchone()[0] == 0
    assert "OutwardBlocked" in gateway.refusal_reason(guard.OutwardBlocked("x"))


def test_the_egress_gate_refuses_what_never_leaves_and_the_fake_is_never_called(con, paid, fake):
    with pytest.raises(egress.EgressBlocked, match="phone|account"):
        gateway.call(con, "read", "sys", [{"role": "user", "content": "please look at account 123456789012 now"}], now=NOW, cfg=_cfg())
    gate = egress.Gate(names=["zorbax"])
    with pytest.raises(egress.EgressBlocked, match="name"):
        gateway.call(con, "read", "sys", [{"role": "user", "content": "the holder zorbax asks"}], now=NOW, cfg=_cfg(), gate=gate)
    with pytest.raises(egress.EgressBlocked):                                              # the whole body is read as well: a system text that names him is caught
        gateway.call(con, "read", "written for zorbax", [{"role": "user", "content": "q"}], now=NOW, cfg=_cfg(), gate=gate, private_text="")
    assert fake.sent == [] and fake.counted == []
    assert gateway.refusal_reason(egress.EgressBlocked("not sent: his name")).startswith("EgressBlocked")


def test_the_governor_refuses_when_the_cap_is_reached_and_logs_it_without_sending(con, paid, fake):
    cfg = _cfg(cap=0.5)                                                                    # far below one decide call
    with pytest.raises(an.BudgetRefused) as ei:
        ask(con, "decide", cfg=cfg)
    assert fake.sent == [] and len(fake.counted) == 1                                      # priced (count_tokens), never sent
    row = con.execute("SELECT status, agent FROM api_calls").fetchone()
    assert row == ("over_limit", "think")
    why = gateway.refusal_reason(ei.value)
    assert why.startswith("BudgetRefused") and "can change at" in why


def test_a_month_already_spent_refuses_the_next_call_and_the_desk_is_its_own_agent(con, paid, fake):
    cfg = _cfg(cap=100.0)
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, status, cost_inr, agent) VALUES (1, ?, 'live', 'x', 't', 'q', '', '{}', 'done', 99.99, 'checker')", [NOW])
    with pytest.raises(an.BudgetRefused, match="cap|share"):
        ask(con, "read", cfg=cfg, agent="desk")
    assert fake.sent == []
    ok = ask(con, "read", cfg=_cfg(), agent="desk")
    assert con.execute("SELECT agent FROM api_calls WHERE call_id=?", [ok["call_id"]]).fetchone()[0] == "desk"
    assert gateway.spent(con, NOW.replace(hour=0), agent="desk") > 0 and gateway.spent(con, NOW.replace(hour=0), agent="think") == 0.0


def test_the_brain_setting_off_stops_the_door_like_every_other_paid_call(con, paid, fake):
    with pytest.raises(an.BudgetRefused, match="off"):
        ask(con, "read", mode="off")
    assert fake.sent == []


def test_an_agent_the_governor_does_not_know_is_refused_up_front(con, paid, fake):
    with pytest.raises(ValueError):
        ask(con, "read", agent="somebody")
    assert fake.sent == []


def test_a_call_over_the_input_limit_is_refused_by_the_governor(con, paid):
    class Big(Fake):
        def _count(self, **k):
            return SimpleNamespace(input_tokens=gv.LIMITS["think"].max_in + 1)
    f = Big()
    gateway.set_client(f)
    try:
        with pytest.raises(an.BudgetRefused, match="input tokens"):
            ask(con, "read")
    finally:
        gateway.set_client(None)
    assert f.sent == []


def test_the_governor_knows_the_new_agents_and_the_layer_they_belong_to():
    assert gv.LIMITS["think"].layer == "thinking" == gv.LIMITS["desk"].layer and "thinking" in gv.LAYERS
    assert gv.LIMITS["think"].per_day["off"] == 0 and gv.LIMITS["think"].per_day["normal"] >= 100


def test_a_refusal_reason_is_none_for_an_ordinary_error():
    assert gateway.refusal_reason(KeyError("x")) is None


# --- nothing else talks to a client --------------------------------------------------------------------------------------------------

def test_nothing_in_the_thinking_package_or_the_door_talks_to_a_client_directly():
    root = Path(gateway.__file__).resolve().parents[1]
    files = [root / "think" / f for f in sorted(p.name for p in (root / "think").glob("*.py"))] + [root / "llm" / "gateway.py"]
    bad = re.compile(r"messages\.create|import anthropic|from anthropic|make_client|beta\.messages|\bllm\.call\(")
    hits = []
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if bad.search(line) and not line.lstrip().startswith("#") and f.name != "gateway.py":
                hits.append(f"{f.name}:{n}")
    assert hits == []
    # the door itself reaches the vendor only through hq/llm.call (egress, price, governor, record) and the analyst's guarded client maker
    text = (root / "llm" / "gateway.py").read_text(encoding="utf-8")
    assert "messages.create" not in text and "import anthropic" not in text and "llm.call(" in text and "an.make_client" in text


def test_an_engine_can_be_added_behind_the_same_door(con, paid, fake):
    class Other(gateway.AnthropicEngine):
        name = "other"
    st = gateway.settings()
    st["claude"]["engine"] = "other"
    with pytest.raises(ValueError, match="not registered"):
        ask(con, "read", st=st)
    gateway.ENGINES["other"] = Other()
    try:
        out = ask(con, "read", st=st)
    finally:
        del gateway.ENGINES["other"]
    assert out["provider"] == "other" and out["engine"] == "claude"


def test_the_migration_adds_the_gateway_columns_to_the_calls_table(con):
    cols = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name='api_calls'").fetchall()}
    assert {"role", "engine", "thinking", "cached_tokens", "case_id", "purpose"} <= cols
    assert con.execute("SELECT max(version) FROM schema_migrations WHERE version BETWEEN 210 AND 214").fetchone()[0] == 210
