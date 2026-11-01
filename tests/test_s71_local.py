"""S71: the one-door queue for the single GPU and the structured-answer helper for small local jobs. No model is called."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from pflab.llm import client, queue, structured


def test_waiting_calls_are_served_most_important_first():
    gate, order, hold = queue.Gate(), [], threading.Event()

    def holder():
        with gate.slot("front"):
            hold.wait(5)

    def waiter(purpose):
        with gate.slot(purpose):
            order.append(purpose)

    h = threading.Thread(target=holder)
    h.start()
    time.sleep(0.1)
    ts = []
    for p in ("learner_reading", "brief", "front", "routing"):          # arrive in this order while the card is busy
        t = threading.Thread(target=waiter, args=(p,))
        t.start()
        ts.append(t)
        time.sleep(0.05)
    assert gate.waiting() == 4
    hold.set()
    for t in [h] + ts:
        t.join(5)
    assert order == ["front", "routing", "brief", "learner_reading"]


def test_one_call_runs_at_a_time():
    gate, inside, peak = queue.Gate(), [0], [0]
    lock = threading.Lock()

    def work():
        with gate.slot("brief"):
            with lock:
                inside[0] += 1
                peak[0] = max(peak[0], inside[0])
            time.sleep(0.05)
            with lock:
                inside[0] -= 1
    ts = [threading.Thread(target=work) for _ in range(6)]
    [t.start() for t in ts]
    [t.join(10) for t in ts]
    assert peak[0] == 1


def test_a_call_that_waits_too_long_gives_up_and_leaves_the_queue_clean():
    gate, hold = queue.Gate(), threading.Event()
    h = threading.Thread(target=lambda: (gate.slot("front").__enter__(), hold.wait(5)))
    ctx = gate.slot("front")
    ctx.__enter__()                                                      # the card is busy
    try:
        with pytest.raises(queue.Busy):
            with gate.slot("learner_reading", wait_s=0.2):
                pass
        assert gate.waiting() == 0                                       # the one that gave up is not left in line
    finally:
        ctx.__exit__(None, None, None)
    with gate.slot("brief", wait_s=1):                                    # and the card is usable again
        pass


def test_a_failing_call_releases_the_card():
    gate = queue.Gate()
    with pytest.raises(ValueError):
        with gate.slot("brief"):
            raise ValueError("the model failed")
    with gate.slot("brief", wait_s=1):
        pass


def test_every_chat_call_goes_through_the_door(monkeypatch):
    seen = []
    real = queue.GATE.slot

    def spy(purpose="", wait_s=None):
        seen.append(purpose)
        return real(purpose, wait_s)
    monkeypatch.setattr(queue.GATE, "slot", spy)
    tags = {"models": [{"name": "qwen3:8b-q8_0", "digest": "d", "size": 1, "details": {}}]}
    t = lambda m, p, payload=None, timeout=0: tags if p == "/api/tags" else {"message": {"content": "ok"}, "prompt_eval_count": 1, "eval_count": 1}
    client.chat("qwen3:8b-q8_0", [{"role": "user", "content": "x"}], transport=t, purpose="front")
    assert seen == ["front"]


def test_a_busy_card_is_an_ollama_error_the_callers_already_handle(monkeypatch):
    monkeypatch.setattr(queue.GATE, "slot", lambda purpose="", wait_s=None: (_ for _ in ()).throw(queue.Busy("busy")))
    tags = {"models": [{"name": "qwen3:8b-q8_0", "digest": "d", "size": 1, "details": {}}]}
    t = lambda m, p, payload=None, timeout=0: tags
    with pytest.raises(client.OllamaError):
        client.chat("qwen3:8b-q8_0", [{"role": "user", "content": "x"}], transport=t)


# --- structured ------------------------------------------------------------------------------------------------------------------

def _chat(*texts):
    it = iter(texts)
    sent = []

    def c(name, messages, **kw):
        sent.append(messages[-1]["content"])
        return SimpleNamespace(text=next(it))
    c.sent = sent
    return c


def test_a_valid_answer_passes_first_time():
    c = _chat('{"x": 1}')
    r = structured.ask_json("s", "p", {"type": "object"}, lambda o: None if o.get("x") == 1 else "x must be 1", purpose="routing", chat=c)
    assert r.ok and r.value == {"x": 1} and r.attempts == 1


def test_a_rejected_answer_is_asked_again_once_with_the_error_named():
    c = _chat('{"x": 2}', '{"x": 1}')
    r = structured.ask_json("s", "p", {"type": "object"}, lambda o: None if o.get("x") == 1 else "x must be 1", purpose="routing", chat=c)
    assert r.ok and r.attempts == 2 and "x must be 1" in c.sent[1]


def test_two_bad_answers_give_no_value_and_say_why():
    r = structured.ask_json("s", "p", {"type": "object"}, lambda o: "no", purpose="routing", chat=_chat('{"x": 2}', '{"x": 3}'))
    assert not r.ok and r.value is None and r.error == "no" and r.attempts == 2
    r = structured.ask_json("s", "p", {"type": "object"}, purpose="routing", chat=_chat("not json", "[1, 2]"))
    assert not r.ok and r.error == "the reply was not a JSON object"


def test_an_unreachable_model_is_one_call_and_an_error_not_an_exception():
    calls = []

    def down(*a, **k):
        calls.append(1)
        raise ConnectionError("Ollama is not running")
    r = structured.ask_json("s", "p", {"type": "object"}, purpose="routing", chat=down)
    assert not r.ok and "ConnectionError" in r.error and len(calls) == 1
