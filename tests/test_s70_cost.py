"""S70: what the paid tool loops cost. The conversation is cached on every turn; a cache read is priced per model."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from pflab.hq import egress, governor as gv, llm

NOW = datetime(2026, 11, 2, 12, 0)


def _reply(text="done"):
    msg = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn")
    return SimpleNamespace(message=msg, cost_inr=0.0, call_id=1)


def test_a_cache_read_is_priced_per_model():
    one_m = dict(input_tokens=0, output_tokens=0, usd_inr=1.0, cache_read=1_000_000)
    assert gv.cost_inr(gv.OPUS, **one_m) == pytest.approx(0.20)       # Opus 5.5: $0.20 a million (0.05 of $4.00)
    assert gv.cost_inr(gv.SONNET, **one_m) == pytest.approx(0.20)     # Sonnet 5.5: $0.20 a million (0.10 of $2.00)
    assert gv.cost_inr(gv.HAIKU, **one_m) == pytest.approx(0.01)
    # a loop of 8 turns on a 17,000-token prefix: reading it back from the cache is far cheaper than re-sending it
    uncached = 8 * gv.cost_inr(gv.OPUS, 17_000, 400, 90.0)
    cached = gv.cost_inr(gv.OPUS, 0, 400 * 8, 90.0, cache_read=7 * 17_000, cache_write=17_000) + gv.cost_inr(gv.OPUS, 0, 0, 90.0)
    assert cached < 0.5 * uncached
