"""S85 (G3): the remaining call sites on the one door (`llm/gateway.py`): the strategist, the analyst's doorbell, web search, trial notes and the workshop's calculation. Scripted fakes only."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from pflab.agents import analyst as an
from pflab.llm import gateway
from pflab.pm import store
from tests.test_analyst import CFG, FakeClient, doc, req
from tests.test_app_ai import WebClient, cite

NOW = datetime(2026, 10, 17, 21, 0)
ROOT = Path(an.__file__).resolve().parents[3]


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


def _rows(con):
    return con.execute("SELECT agent, engine, role, purpose, status, topic FROM api_calls ORDER BY call_id").fetchall()


def test_the_doorbell_asks_through_the_door_and_its_row_says_which_engine_and_role(con):
    c = FakeClient()
    o = an.ring(con, req(), c, now=NOW, cfg=CFG)
    assert o.status == "done" and o.text == "Revenue rose on the year. [D1]"
    (agent, engine, role, purpose, status, topic), = _rows(con)
    assert (agent, engine, status, purpose) == ("analyst", "claude", "done", "analyst ring") and role in ("quick", "read", "decide") and topic == "AAA"
    assert con.execute("SELECT note_doc FROM api_calls").fetchone()[0]                      # the note is linked to the row
    kw = [k for n, k in c.calls if n == "create"][0]
    assert kw["model"] == an.MODEL and kw["output_config"] == {"effort": "high"} and kw["messages"][0]["content"][0]["type"] == "document"


def test_the_doorbell_is_still_held_by_the_gate_before_the_door(con):
    c = FakeClient()
    o = an.ring(con, req("should I sell 123456 rupees of it"), c, now=NOW, cfg=CFG, pv=an.Private(amounts={123456.0}))
    assert o.status == "blocked" and c.calls == [] and _rows(con) == []


def test_the_door_refuses_what_his_cap_refuses(con):
    with pytest.raises(an.BudgetRefused):
        an.ring(con, req(), FakeClient(), now=NOW, cfg={**CFG, "cap": 0.0})
    assert con.execute("SELECT count(*) FROM api_calls WHERE status='sending'").fetchone()[0] == 0


def test_a_trial_note_goes_through_the_door_and_keeps_nothing(con):
    c = FakeClient()
    out = an.trial_note(con, req(), c, an.SONNET, now=NOW, cfg=CFG)
    assert out["model"] == an.SONNET and out["raw"] == "Revenue rose on the year. [D1]" and out["cost_inr"] > 0
    assert [k["model"] for n, k in c.calls if n == "create"] == [an.SONNET]
    assert con.execute("SELECT count(*) FROM kg_docs WHERE kind='analyst_note'").fetchone()[0] == 0
    assert _rows(con)[0][:2] == ("analyst", "claude")


def test_web_search_goes_through_the_door_with_the_web_tool_and_bills_every_search(con):
    blocks = [NS(type="text", text="The plant starts trials in December", citations=[cite("https://a.example/1", "A")])]
    c = WebClient(blocks, searches=3, stops=["end_turn"])
    o = an.web_search(con, "Has the company's second plant started?", c, now=NOW, cfg=CFG, pv=an.Private())
    assert o.status == "done" and "[W1] A - https://a.example/1" in o.text
    assert c.sent[0]["tools"][-1]["name"] == "web_search"
    usd = (1000 * 4 + 500 * 20) / 1e6 + 3 * an.WEB_USD_PER_SEARCH
    assert o.cost_inr == pytest.approx(usd * 90.0) and _rows(con)[0][:2] == ("analyst", "claude")


def test_a_web_call_on_an_engine_without_a_web_tool_stays_on_one_that_has_it(con, monkeypatch):
    assert not gateway.features_of(gateway.settings(), "openai").get("web_search")           # the OpenAI engine's table says it has no web tool here
    monkeypatch.setattr(gateway, "current_engine", lambda con=None, st=None: "openai")
    blocks = [NS(type="text", text="Nothing to report.", citations=[])]
    c = WebClient(blocks, searches=0)
    o = an.web_search(con, "Is there news on the second plant?", c, now=NOW, cfg=CFG, pv=an.Private())
    assert o.status == "done" and _rows(con)[0][1] == "claude"


def test_the_models_own_refusal_is_an_outcome_not_an_error(con):
    o = an.ring(con, req(), FakeClient(stop="refusal"), now=NOW, cfg=CFG)
    assert o.status == "refused" and o.call_id and con.execute("SELECT status FROM api_calls").fetchone()[0] == "refused"


def test_the_workshop_calculation_goes_through_the_door_and_only_its_gate_text_is_checked(con):
    reply = NS(content=[NS(type="text", text="{}")], stop_reason="end_turn", usage=NS(input_tokens=500, output_tokens=50))
    c = NS(messages=NS(count_tokens=lambda **k: NS(input_tokens=500)), beta=NS(messages=NS(create=lambda **k: reply)))
    text = an.write_calculation(con, "QUESTION:\nworst fall of the index?", "You write code.", c, cfg=CFG, pv=an.Private(), now=NOW, gate_text="QUESTION:\nworst fall of the index?")
    assert text == "{}" and _rows(con)[0][:2] == ("analyst", "claude")


# --- structure: nothing outside the door talks to a vendor SDK ---------------------------------------------------------------------------

def _py_files():
    for base in ("src", "tools"):
        for f in (ROOT / base).rglob("*.py"):
            yield f


def test_no_module_outside_llm_imports_a_vendor_sdk_by_any_spelling():
    pat = re.compile(r"(^\s*(import|from)\s+(anthropic|openai)\b)|__import__\(\s*['\"](anthropic|openai)|import_module\(\s*['\"](anthropic|openai)")
    hits = []
    for f in _py_files():
        rel = f.relative_to(ROOT).parts
        if rel[:3] == ("src", "pflab", "llm") and f.name in ("vendors.py",):
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if pat.search(line):
                hits.append(f"{'/'.join(rel)}:{n}")
    assert hits == []


def test_the_strategist_and_the_doorbell_call_no_client_method_themselves():
    for rel in ("src/pflab/lab/strategist.py", "src/pflab/core/checker.py", "src/pflab/think/session.py", "src/pflab/hq/converse.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"messages\.create|beta\.messages|\bllm\.call\(", text), rel
    ana = (ROOT / "src/pflab/agents/analyst.py").read_text(encoding="utf-8")
    assert "messages.create" not in ana.replace("messages.batches", "")                       # the batch API (submit/collect) is the one thing left on the client
    assert ana.count("count_tokens(") == 1                                                      # only the queue's estimate
