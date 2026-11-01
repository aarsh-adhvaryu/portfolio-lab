"""S70: what the paid tool loops cost. The conversation is cached on every turn; a cache read is priced per model."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from pflab.hq import egress, governor as gv, llm, workers

NOW = datetime(2026, 11, 2, 12, 0)


def _reply(text="done"):
    msg = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn")
    return SimpleNamespace(message=msg, cost_inr=0.0, call_id=1)


def test_every_worker_turn_carries_the_automatic_cache_marker(monkeypatch):
    sent = []

    def fake_call(con, agent, params, client, **kw):
        sent.append(params)
        return _reply()
    monkeypatch.setattr(llm, "call", fake_call)
    rt = SimpleNamespace(clock=lambda: NOW)
    for turns in (1, 3):
        sent.clear()
        workers.converse(rt, None, None, [{"role": "user", "content": [{"type": "text", "text": "go"}]}], system="S", tools=[],
                         model=gv.SONNET, agent="w_research", effort="low", max_out=100, client=None, gate=egress.Gate(), cfg={},
                         mode="economy", his=False, private_first="", question="q", max_turns=turns)
        assert sent and all(p["cache_control"] == {"type": "ephemeral"} for p in sent)
        assert all(str(p).count("cache_control") <= 4 for p in sent)          # system block + the automatic one: inside the API's four


def test_the_role_parameters_carry_it_too():
    p = workers._params("review", [], last=False)
    assert p["cache_control"] == {"type": "ephemeral"} and p["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_a_cache_read_is_priced_per_model():
    one_m = dict(input_tokens=0, output_tokens=0, usd_inr=1.0, cache_read=1_000_000)
    assert gv.cost_inr(gv.OPUS, **one_m) == pytest.approx(0.20)       # Opus 5.5: $0.20 a million (0.05 of $4.00)
    assert gv.cost_inr(gv.SONNET, **one_m) == pytest.approx(0.20)     # Sonnet 5.5: $0.20 a million (0.10 of $2.00)
    assert gv.cost_inr(gv.HAIKU, **one_m) == pytest.approx(0.01)
    # a loop of 8 turns on a 17,000-token prefix: reading it back from the cache is far cheaper than re-sending it
    uncached = 8 * gv.cost_inr(gv.OPUS, 17_000, 400, 90.0)
    cached = gv.cost_inr(gv.OPUS, 0, 400 * 8, 90.0, cache_read=7 * 17_000, cache_write=17_000) + gv.cost_inr(gv.OPUS, 0, 0, 90.0)
    assert cached < 0.5 * uncached
