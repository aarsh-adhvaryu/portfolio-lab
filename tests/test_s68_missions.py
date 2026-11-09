"""S68 P2: one request becomes a mission carried by a coordinator, research and quant workers and an independent reviewer; tasks are done when
their promised artifacts exist; waits are named and cost no attempt; a restart loses nothing. A scripted model stands in for the API (labelled:
these are development tests, the live run is the acceptance). Synthetic data only."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from pflab.agents import analyst as an
from pflab.hq import board, cases, egress, governor as gv, roster, service
from pflab.hq.desk import Desk
from pflab.pm import store

NOW = datetime(2026, 10, 31, 15, 0)
CFG = {"model": an.MODEL, "cap": 2500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True, "tijori_to_analyst": True}


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


# --- a scripted model: answers by role, from the system prompt ---------------------------------------------------------------------------------

def _use(*calls, model=gv.SONNET):
    content = [SimpleNamespace(type="thinking", thinking="", signature="sig")]
    content += [SimpleNamespace(type="tool_use", id=f"tu{k}{id(c)}", name=n, input=i) for k, (n, i) in enumerate(calls) for c in [object()]]
    return SimpleNamespace(content=content, stop_reason="tool_use", model=model,
                           usage=SimpleNamespace(input_tokens=900, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0))


def _say(text, model=gv.SONNET):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn", model=model,
                           usage=SimpleNamespace(input_tokens=900, output_tokens=120, cache_read_input_tokens=0, cache_creation_input_tokens=0))


ROLE_MARK = {"ROLE coordinator": "coordinator", "ROLE research": "research", "ROLE quant": "quant", "ROLE review": "review"}


class Model:
    def __init__(self, scripts):
        self.scripts = {r: list(v) for r, v in scripts.items()}
        self.seen = []
        self.messages = SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(input_tokens=1000), create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        sys_text = kw["system"][0]["text"]
        role = next(r for m, r in ROLE_MARK.items() if m in sys_text)
        self.seen.append((role, kw))
        q = self.scripts[role]
        if not q:
            raise AssertionError(f"the {role} was asked again with nothing scripted")
        r = q.pop(0)
        if isinstance(r, Exception):
            raise r
        return r(kw) if callable(r) else r


@pytest.fixture
def rt(con, tmp_path, monkeypatch):
    monkeypatch.setattr(an, "config", lambda: CFG)
    monkeypatch.setattr(service, "gate", lambda r: egress.Gate())
    (tmp_path / "pm" / "app").mkdir(parents=True)
    d = Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, {"brain": "normal", "preset": "full", "telegram_send": False}, clock=lambda: NOW)
    return d


def _fake_calc(monkeypatch, status="checked"):
    from pflab.agents import workshop as wk

    def ask(con, question, *a, **k):
        spec = SimpleNamespace(code="result = {'x': 1}", alt_code="", datasets=[], test={}, params={})
        run = SimpleNamespace(result={"worst_fall_pct": -18.0, "months_to_recover": 14}, contained=True, cross_checked=True, problems=[])
        return SimpleNamespace(status=status, spec=spec, run=run, folder=None, attempts=[1], confirm={"status": "agrees"}, inputs=None)
    monkeypatch.setattr(wk, "ask", ask)


PLAN = [{"key": "verify", "role": "research", "goal": "Verify the event, its dates and size from sources; look for evidence against it.",
         "promise": {"evidence": 2}, "depends_on": []},
        {"key": "scenarios", "role": "quant", "goal": "Compare phased buying with holding cash across a sharp fall; assumptions visible.",
         "promise": {"calc": 1}, "depends_on": ["verify"]}]


def _happy_scripts(extra_review=None):
    return {
        "coordinator": [_use(("plan_mission", {"case_id": 1, "steps_json": json.dumps(PLAN), "approach": "verify then compute"}), model=gv.OPUS), _say("Planned.", gv.OPUS),
                        _use(("submit_answer", {"case_id": 1, "answer": "The evidence in the case shows the drop in evidence 1; calc 1 gives -18.0 under stated assumptions.",
                                                "limitations": "Weights are assumptions.", "monitor_next": "The next filing."}),
                             model=gv.OPUS),
                        _say("Answer written.", gv.OPUS)],
        "research": [_use(("case_evidence", {"case_id": 1, "stance": "for", "text": "A company filing reports the move.", "source_kind": "filing", "published": "2026-10-20"}),
                          ("case_evidence", {"case_id": 1, "stance": "against", "text": "The move reversed within two sessions per prices.", "source_kind": "observation"})),
                     _say("Two items recorded.")],
        "quant": [_use(("case_calculate", {"case_id": 1, "question": "Worst fall and recovery under phased buying versus cash"})), _say("Calculation done.")],
        "review": [_use(("reproduce_calc", {"calc_id": 1}), model=gv.OPUS),
                   _use(("submit_review", {"case_id": 1, "verdict": "approve", "findings": "Reproduced calc 1; evidence is sourced.", "checks": "reproduce_calc 1"}), model=gv.OPUS),
                   _say("Approved.", gv.OPUS)] if extra_review is None else extra_review,
    }


def _fake_calc_out():
    spec = SimpleNamespace(code="result = {'x': 1}", alt_code="", datasets=[], test={}, params={})
    run = SimpleNamespace(result={"worst_fall_pct": -18.0}, contained=True, cross_checked=True, problems=[])
    return SimpleNamespace(status="checked", spec=spec, run=run, folder=None, attempts=[1], confirm={"status": "agrees"}, inputs=None)


def tl_cap() -> int:
    from pflab.hq import tools
    return tools.TASK_CAPS["case_calculate"]

