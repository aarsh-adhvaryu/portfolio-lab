"""S61 the model slider (PLAN A19): one model per job, measured defaults, his settings win; the ask centre's chain;
the scoring rules of docs/STUDIES.md on synthetic results."""
from __future__ import annotations

import importlib.util
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from pflab.agents import centre
from pflab.app import settings as st
from pflab.hq import governor as gv, models, passes as brain

REPO = Path(__file__).resolve().parents[1]



def test_a_job_takes_his_setting_else_the_measured_default_else_its_own(tmp_path):
    p = tmp_path / "models.toml"
    assert models.choice("web", {"models": {}}, p) == "opus" and models.choice("answers", {}, p) == "cascade"
    p.write_text('[defaults]\nweb = "sonnet"\nbrain = "haiku"\nnope = "opus"\n', encoding="utf-8")
    assert models.decided(p) == {"web": "sonnet"}                         # not a choice of the job / not a job: ignored
    assert models.choice("web", {}, p) == "sonnet"
    assert models.choice("web", {"models": {"web": "opus"}}, p) == "opus"  # his choice wins
    assert models.choice("web", {"models": {"web": "haiku"}}, p) == "sonnet"   # not allowed for the job: ignored
    assert models.model_id("brain", {"models": {"brain": "sonnet"}}) == gv.SONNET
    assert {r["job"] for r in models.listing({"models": {}})} == set(models.JOBS)


def test_settings_keep_only_valid_choices_and_default_takes_one_back(tmp_path):
    s = st.save(tmp_path, {"models": {"web": "sonnet", "routing": "opus", "made_up": "haiku"}})
    assert s["models"] == {"web": "sonnet"}
    s = st.save(tmp_path, {"models": {"answers": "haiku"}})
    assert s["models"] == {"web": "sonnet", "answers": "haiku"}
    s = st.save(tmp_path, {"models": {"web": "default"}})
    assert s["models"] == {"answers": "haiku"} and st.load(tmp_path)["models"] == {"answers": "haiku"}


def test_the_brain_and_its_rival_follow_the_slider(monkeypatch):
    monkeypatch.setattr(models, "model_id", lambda job, settings=None: gv.SONNET)
    assert brain.pair() == (gv.SONNET, gv.OPUS)
    monkeypatch.setattr(models, "model_id", lambda job, settings=None: gv.OPUS)
    assert brain.pair() == (gv.OPUS, gv.SONNET)
    monkeypatch.setattr(models, "model_id", lambda job, settings=None: (_ for _ in ()).throw(OSError("no file")))
    assert brain.pair() == (gv.OPUS, gv.SONNET) and brain.slider("fetch", gv.SONNET) == gv.SONNET   # unreadable: fallback


def test_the_ask_centre_tries_each_model_of_the_chain_until_one_passes_the_guard(monkeypatch):
    facts = {"networth.total": "1,00,000"}
    monkeypatch.setattr(centre, "keyword_route", lambda q: ["networth"])
    tool = SimpleNamespace(name="networth", uses_question=False, run=lambda con, asof: dict(facts))
    monkeypatch.setattr(centre.T, "BY_NAME", {"networth": tool})
    calls = []

    def bad(prompt):
        calls.append("local")
        return "Your net worth is 9,99,999 [F:networth.total]."      # a number not in the facts: the guard fails

    def good(prompt):
        calls.append("haiku")
        return "Your net worth is 1,00,000 [F:networth.total]."
    monkeypatch.setattr(models, "road", lambda con, settings=None: None)
    monkeypatch.setattr(models, "router", lambda con, settings=None, r=None: (None, None))
    monkeypatch.setattr(models, "answer_chain", lambda con, system, settings=None, r=None: [("local", bad), ("haiku", good)])
    a = centre.ask(None, "what is my net worth", date(2026, 10, 25))
    assert a.verified and a.answered_by == "haiku" and calls[0] == "local" and "haiku" in calls
    monkeypatch.setattr(models, "answer_chain", lambda con, system, settings=None, r=None: [("local", bad)])
    a = centre.ask(None, "what is my net worth", date(2026, 10, 25))
    assert not a.verified and "1,00,000" in a.text                    # the facts are the last word




def test_claude_answers_get_the_facts_with_ids_as_tokens(monkeypatch):
    from pflab.hq import egress, llm
    sent = []

    def fake_call(con, agent, p, client, **kw):
        egress.check(kw["private_text"], kw["gate"])               # the road's own check passes
        sent.append(p["messages"][0]["content"])
        return SimpleNamespace(text="The first to mature is [ID-A] on 2027-01-30.")
    monkeypatch.setattr(llm, "call", fake_call)
    r = models.Road(None, None, egress.Gate(ids={"FD1234567890", "SB12345678"}))
    out = models.claude_llm(r, gv.HAIKU)("fd.next = FD1234567890 matures 2027-01-30; fd.other = FD1234567890; SB12345678")
    assert "FD1234567890" not in sent[0] and sent[0].count("[ID-A]") == 2 and "[ID-B]" in sent[0]
    assert not any(ch.isdigit() for ch in "".join(set(sent[0].split()) - set("2027-01-30;".split())) if ch in "[]") \
        and "2027-01-30" in sent[0]
    assert out == "The first to mature is FD1234567890 on 2027-01-30."      # the real id back on this PC


