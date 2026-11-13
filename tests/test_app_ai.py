"""S54b AI centre: chats run on a worker and keep their route; web search keeps only cited figures and adds the search
cost; old chats are tidied into memory; the endpoints answer."""
import time
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from pflab.agents import analyst as an
from pflab.agents import centre
from pflab.app import chat, runtime, server
from pflab.pm import store

NOW = datetime(2026, 10, 22, 11, 30)
CFG = {"model": an.MODEL, "cap": 1500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True}


@pytest.fixture
def rt(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


@pytest.fixture(autouse=True)
def _intake_clean():
    from pflab.entrance import intake
    intake.stop()
    yield
    intake.stop()
    intake.gateway_call = None


def wait_done(rt, chat_id, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        m = chat.messages(rt.cursor(), chat_id)
        if m and m[-1]["status"] not in ("working", "queued"):
            return m
        time.sleep(0.05)
    raise AssertionError("the worker did not finish")


def test_a_chat_answers_on_a_worker_and_shows_its_model_and_price(rt):
    """S85: the old ask road is gone; chat.post hands the question to the intake, which answers on the model the router picks (a scripted gateway here)."""
    from pflab.entrance import intake
    intake.gateway_call = lambda con, role, system, messages, **kw: {"text": "Net worth is in the ledger.", "tool_calls": [], "assistant_content": [], "cost_rupees": 0.4, "model": "claude-sonnet-5-5",
                                                                     "thinking": "medium", "engine": "anthropic"}
    r = chat.post(rt, 0, "What is my net worth?", "ask")
    m = wait_done(rt, r["chat_id"])
    assert [x["role"] for x in m] == ["me", "ai"] and m[1]["status"] == "done" and m[1]["text"] == "Net worth is in the ledger."
    assert m[1]["model"] == "claude-sonnet-5-5" and m[1]["cost_inr"] == 0.4 and "Sonnet 5.5" in m[1]["meta"]
    assert chat.listing(rt.cursor())[0]["title"] == "Assistant"                       # one conversation: a new question is not a new chat
    with pytest.raises(ValueError):
        chat.post(rt, r["chat_id"], "x", "telepathy")


def test_a_failed_answer_is_shown_not_hidden(rt, monkeypatch):
    from pflab.entrance import intake
    monkeypatch.setitem(intake.DEFAULTS, "retry_pause_s", 0.0)

    def boom(con, role, system, messages, **kw):
        raise RuntimeError("the provider is not reachable")
    intake.gateway_call = boom
    m = wait_done(rt, chat.post(rt, 0, "q", "ask")["chat_id"])
    assert m[1]["status"] == "failed" and "did not answer" in m[1]["text"]


class WebClient:
    def __init__(self, blocks, searches=2, stops=("end_turn",)):
        self.sent, self.blocks, self.searches, self.stops = [], blocks, searches, list(stops)
        self.messages = NS(count_tokens=lambda **k: NS(input_tokens=1000))
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.sent.append(kw)
        stop = self.stops.pop(0) if self.stops else "end_turn"
        return NS(content=self.blocks, stop_reason=stop,
                  usage=NS(input_tokens=1000, output_tokens=500, server_tool_use=NS(web_search_requests=self.searches)))


def cite(url, title="Page"):
    return NS(type="web_search_result_location", url=url, title=title, cited_text="...")


def test_web_search_keeps_cited_figures_prices_searches_and_keeps_a_note(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    blocks = [NS(type="server_tool_use", name="web_search", input={"query": "x"}),
              NS(type="text", text="The plant starts trials in December", citations=[cite("https://a.example/1", "A")]),
              NS(type="text", text=". Revenue will be 4,000 crore", citations=[]),
              NS(type="text", text=". No filing confirms it yet.", citations=[])]
    c = WebClient(blocks, stops=["pause_turn", "end_turn"])
    o = an.web_search(con, "Has the company's second plant started?", c, now=NOW, cfg=CFG, pv=an.Private())
    assert o.status == "done" and "December [W1]" in o.text and "4,000" not in o.text and "1 passage(s) removed" in o.text
    assert "[W1] A - https://a.example/1" in o.text
    assert len(c.sent) == 2 and c.sent[0]["tools"][0]["type"] == an.WEB_TOOL      # a paused turn is resumed
    tok_usd = (1000 * 4 + 500 * 20) / 1e6
    row = con.execute("SELECT status, cost_usd, note_doc FROM api_calls ORDER BY call_id").fetchone()
    assert row[0] == "done" and row[1] == pytest.approx(tok_usd + 2 * an.WEB_USD_PER_SEARCH) and row[2]
    # S85 (G3): through the door the resumed turn is paid for too (two calls' tokens and four searches here; the old path priced only the last turn)
    assert o.cost_inr == pytest.approx((2 * tok_usd + 4 * an.WEB_USD_PER_SEARCH) * 90.0)
    assert con.execute("SELECT count(*), round(sum(cost_inr), 4) FROM api_calls").fetchone() == (2, round((2 * tok_usd + 4 * an.WEB_USD_PER_SEARCH) * 90.0, 4))
    blocked = an.web_search(con, "should I sell 123456 rupees of it", c, now=NOW, cfg=CFG, pv=an.Private(amounts={123456.0}))
    assert blocked.status == "blocked"


def test_old_chats_are_summarised_into_memory_and_removed(rt):
    con = rt.cursor()
    old = chat.create(con, NOW - timedelta(days=40), "Statements for September")
    chat._add(con, old, "me", "ask", "What do you need for September?", "done", NOW - timedelta(days=40))
    fresh = chat.create(con, NOW, "today")
    assert chat.tidy(con, NOW) == 1
    assert [c["id"] for c in chat.listing(con)] == [fresh]
    mem = con.execute("SELECT text FROM memory WHERE source LIKE 'chat %'").fetchone()[0]
    assert "Statements for September" in mem and "What do you need for September?" in mem


def test_ai_endpoints(rt, monkeypatch):
    monkeypatch.setattr(an, "config", lambda: CFG)
    c = TestClient(server.create_app(rt))
    cid = c.post("/api/chats").json()["id"]
    d = c.get(f"/api/ai?chat={cid}").json()
    assert d["chat_id"] == cid and d["messages"] == [] and any(a["name"] == "Conductor" for a in d["agents"])
    assert d["spend"]["cap"] == 1500.0
    assert c.post(f"/api/chats/{cid}/messages", json={"text": "  ", "mode": "ask"}).status_code == 400
    from pflab.agents import questions as qs
    qid = qs.ask(rt.cursor(), "cleanup", "k1", "Merge these two transfers?", NOW)
    assert c.get("/api/ai").json()["questions"][0]["id"] == qid
    c.post(f"/api/questions/{qid}/answer", json={"text": "Merge"})
    assert c.get("/api/ai").json()["questions"] == []
    c.delete(f"/api/chats/{cid}")
    assert c.get("/api/ai").json()["chats"] == []
