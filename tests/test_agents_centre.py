"""S37 the centre: routing, guarded answers, facts-only fallback. SYNTHETIC tools and fake models (no Ollama)."""
import json
from datetime import date

import pytest

from pflab.agents import centre, tools as T


@pytest.fixture
def fake_tools(monkeypatch):
    t = [T.Tool("networth", "ledger", "net worth", lambda con, d: {"net_worth": 1234567, "stocks_total": 400000}),
         T.Tool("fds", "fd", "fixed deposits", lambda con, d: {"fd_all_total": 800000}),
         T.Tool("tax", "tax", "tax", lambda con, d: (_ for _ in ()).throw(RuntimeError("no data")))]
    monkeypatch.setattr(T, "TOOLS", t)
    monkeypatch.setattr(T, "BY_NAME", {x.name: x for x in t})


class FakeReply:
    def __init__(self, text):
        self.text = text


def test_keyword_route():
    assert centre.keyword_route("how much tax will I pay?") == ["tax"]
    assert set(centre.keyword_route("when does my FD mature and what is the risk of a crash")) >= {"fds", "risk"}
    assert centre.keyword_route("hello") == ["networth"]


def test_model_route_is_bounded_to_the_menu(fake_tools):
    chat = lambda model, msgs, **kw: FakeReply(json.dumps({"tools": ["fds", "made_up", "fds"]}))
    assert centre.llm_route("my deposits?", chat) == ["fds"]


def test_a_guarded_answer_and_a_failing_agent(fake_tools):
    chat = lambda model, msgs, **kw: FakeReply(json.dumps({"tools": ["networth", "tax"]}))
    llm = lambda prompt: "Your net worth is 1234567 [F:net_worth]."
    a = centre.ask(None, "net worth?", date(2026, 10, 15), llm=llm, chat=chat)
    assert a.verified and a.tools == ["networth", "tax"] and a.router == "model"
    assert "tax.error" in a.facts                                   # reported, not hidden


def test_an_invented_number_never_reaches_the_answer(fake_tools):
    llm = lambda prompt: "Your net worth is 9999999 [F:net_worth]."
    a = centre.ask(None, "net worth?", date(2026, 10, 15), llm=llm, tools_override=["networth"])
    assert not a.verified and "9999999" not in a.text and "net_worth = 1234567" in a.text


def test_router_failure_falls_back_to_keywords(fake_tools):
    def boom(*a, **k):
        raise ConnectionError("ollama down")
    a = centre.ask(None, "what about my fixed deposits", date(2026, 10, 15), llm=lambda p: "x", chat=boom)
    assert a.router == "keywords" and a.tools == ["fds"]
