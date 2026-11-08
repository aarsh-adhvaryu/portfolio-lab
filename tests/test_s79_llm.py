"""S79 item 13: sampling plumbing (fake transport), failure reading, the GPU duty cycle, the comparison rules, migration 77."""
import pytest

from pflab.llm import client, diag, duty, s79_eval as se


class Fake:
    def __init__(self, reply="ok [F:x]", done_reason="stop", eval_count=5):
        self.calls, self.reply, self.dr, self.ec = [], reply, done_reason, eval_count

    def __call__(self, method, path, payload, timeout):
        self.calls.append((method, path, payload))
        if path == "/api/tags":
            return {"models": [{"name": n, "digest": "d", "size": 1, "details": {}} for n in ("qwen3:8b-q8_0", "qwen3:30b-a3b", "qwen3.5-9b-16k:latest")]}
        return {"message": {"content": self.reply}, "prompt_eval_count": 3, "eval_count": self.ec, "done_reason": self.dr}


def opts(model="qwen3:8b-q8_0", **kw):
    f = Fake()
    client.chat(model, [{"role": "user", "content": "hi"}], transport=f, **kw)
    return f.calls[-1][2]["options"]


# --- sampling plumbing ---------------------------------------------------------------------------------------------

def test_default_call_keeps_the_old_options_exactly():
    assert opts() == {"temperature": 0.0, "seed": client.SEED, "num_predict": 400}
    assert opts(sampling="off") == {"temperature": 0.0, "seed": client.SEED, "num_predict": 400}


def test_auto_sampling_text_json_and_think_kinds():
    t = opts(sampling="auto")
    assert (t["temperature"], t["top_p"], t["top_k"], t["min_p"], t["presence_penalty"]) == (0.7, 0.8, 20, 0.0, 1.5)
    assert t["seed"] == client.SEED and t["num_predict"] == 400
    th = opts(sampling="auto", think=True)
    assert (th["temperature"], th["top_p"], th["presence_penalty"]) == (0.6, 0.95, 1.0)
    j = opts(sampling="auto", fmt={"type": "object"})
    assert j["top_k"] == 20 and j["presence_penalty"] == client.SAMPLING["json"]["presence_penalty"]


def test_overrides_and_caller_temperature_and_other_families():
    o = opts(sampling={"presence_penalty": 0.5})
    assert o["presence_penalty"] == 0.5 and o["top_k"] == 20 and o["temperature"] == 0.7
    assert opts(sampling={"temperature": 0.2})["temperature"] == 0.2
    assert opts(sampling="auto", temperature=0.3)["temperature"] == 0.3            # his own non-zero temperature wins
    assert opts("qwen3.5-9b-16k", sampling="auto") == {"temperature": 0.0, "seed": client.SEED, "num_predict": 400}   # not the qwen3 family
    assert opts("qwen3:30b-a3b", sampling="auto")["top_p"] == 0.8
    with pytest.raises(ValueError):
        opts(sampling="nope")


def test_adopted_kinds_apply_by_default_only_to_their_kind(monkeypatch):
    monkeypatch.setattr(client, "DEFAULT_KINDS", {"text"})
    assert opts()["presence_penalty"] == 1.5
    assert "presence_penalty" not in opts(fmt={"type": "object"})
    assert "presence_penalty" not in opts(sampling="off")
    assert "presence_penalty" not in opts("qwen3.5-9b-16k")


def test_reply_carries_done_reason_and_label_and_sink_note():
    seen = []
    client.set_sink(seen.append)
    try:
        r = client.chat("qwen3:8b-q8_0", [], transport=Fake(reply="cut off here", done_reason="length", eval_count=400), num_predict=400)
        ok = client.chat("qwen3:8b-q8_0", [], transport=Fake())
    finally:
        client.set_sink(None)
    assert (r.done_reason, r.label) == ("length", "truncated") and (ok.done_reason, ok.label) == ("stop", "ok")
    assert [d["note"] for d in seen] == ["truncated", ""]


# --- failure reading ----------------------------------------------------------------------------------------------

def test_classify_failures():
    loop = "The fund rose. " * 30
    assert diag.classify("fine short answer [F:x].", 6, 400, "stop") == "ok"
    assert diag.classify("", 0, 400, "stop") == "empty"
    assert diag.classify("half a sentence", 400, 400, "length") == "truncated"
    assert diag.classify("x " * 5, 400, 400, "stop") == "truncated"
    assert diag.classify(loop, 90, 400, "stop") == "loop"
    assert diag.classify("not json {", 5, 60, "stop", fmt=True) == "format"
    assert diag.classify('{"label": "material"}', 5, 20, "stop", fmt=True) == "ok"
    long_ok = " ".join(f"word{i}" for i in range(80))
    assert diag.classify(long_ok, 100, 400, "stop") == "ok"
    assert diag.rates(["ok", "loop"])["loop"] == 0.5


# --- the duty cycle -----------------------------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def test_duty_cycle_holds_the_share_under_the_duty():
    c = Clock()
    d = duty.DutyCycle(duty=0.5, window_s=100, clock=c.now, sleep=c.sleep)
    shares = []
    for _ in range(10):                                          # a 10 s call as often as allowed
        with d.slot():
            c.t += 10
        shares.append(d.share())
    assert max(shares) <= 0.5 + 1e-9                             # in every window the model held the card for at most the duty
    assert sum(c.slept) > 0                                      # it did wait


def test_duty_cycle_off_and_first_call_and_front_cap(monkeypatch):
    c = Clock()
    d = duty.DutyCycle(duty=0.1, window_s=100, clock=c.now, sleep=c.sleep, enabled=False)
    for _ in range(5):
        with d.slot():
            c.t += 10
    assert c.slept == []                                         # off switch
    d2 = duty.DutyCycle(duty=0.1, window_s=100, clock=c.now, sleep=c.sleep)
    for _ in range(2):
        with d2.slot():
            c.t += 10
    c.slept.clear()
    with d2.slot("front"):                                       # a person is waiting: held back at most MAX_FRONT_WAIT_S
        pass
    assert c.slept == [duty.MAX_FRONT_WAIT_S]
    monkeypatch.setenv("PFLAB_GPU_DUTY", "off")
    n = len(c.slept)
    with d2.slot():
        pass
    assert len(c.slept) == n


def test_duty_reads_the_mode_from_markets_config_and_set_mode_turns_it_on():
    d = duty.DutyCycle(mode="session")
    assert d.duty == pytest.approx(0.4)
    d.set_mode("deep")
    assert d.duty == pytest.approx(0.85)
    old = duty.THROTTLE.enabled
    try:
        duty.THROTTLE.enabled = False
        duty.set_mode("post_close")
        assert duty.THROTTLE.enabled and duty.THROTTLE.duty == pytest.approx(0.7)
    finally:
        duty.THROTTLE.enabled = old
        duty.THROTTLE.set_mode("session")


# --- the registered rules ------------------------------------------------------------------------------------------

def arm(routing=0.97, ans=1.0, ext=1.0, mat=0.8, fails=(), n_ans=50, ans_s=6.0, call_s=1.0, tok=60, route_s=3.0, labels_json=None):
    def task(name, n, score, kind, labels=None, **extra):
        items = [i < int(round(score * n)) for i in range(n)]
        lab = labels if labels is not None else ["ok"] * n
        return {"task": name, "n": n, "score": score, "items": items, "labels": lab, "kind": kind, "call_seconds": [call_s] * len(lab),
                "call_tokens_out": [tok] * len(lab), **extra}
    a = lambda s: task(f"answers_{s}", n_ans, ans, "text", labels=list(fails) + ["ok"] * (n_ans - len(fails)), first=ans, median_s=ans_s,
                       p90_s=ans_s, task_seconds=[ans_s] * n_ans, first_items=[True] * n_ans)
    return {"routing": task("routing", 60, routing, "json", labels=labels_json, call_median_s=route_s),
            "answers_20261017": a(20261017), "answers_20261018": a(20261018),
            "extraction": task("extraction", 100, ext, "json", f1=ext), "materiality": task("materiality", 200, mat, "json")}


def test_sampling_rule_adopts_only_what_does_not_lose_and_reduces_failures():
    a = arm(fails=["loop", "loop", "truncated"])
    b = arm(fails=[])
    d = se.decide_sampling(a, b)
    assert d["adopt_kinds"] == ["text"]                           # json kinds had no failures to reduce
    assert se.decide_sampling(arm(), arm())["adopt_kinds"] == []  # nothing to reduce: not adopted
    worse = arm(ans=0.9, fails=[])
    assert se.decide_sampling(a, worse)["adopt_kinds"] == []      # fewer failures but loses answers
    jb = arm(labels_json=["ok"] * 59 + ["format"])
    assert se.decide_sampling(jb, arm())["adopt_kinds"] == ["json"] or se.decide_sampling(jb, arm())["json"]["fewer_failures"]


def test_moe_rule_needs_a_significant_win_thresholds_latency_and_no_loss():
    base = arm(routing=0.80, mat=0.70, ans=0.98)
    good = arm(routing=0.97, mat=0.90, ans=1.0)
    d = se.decide_moe(base, good)
    assert d["checks"]["beats_on_score"] and d["chosen"], d["checks"]
    slow = arm(routing=0.97, mat=0.90, ans=1.0, ans_s=25.0)
    assert not se.decide_moe(base, slow)["chosen"] and not se.decide_moe(base, slow)["checks"]["latency_bound"]
    same = arm(routing=0.80, mat=0.70, ans=0.98)
    assert not se.decide_moe(base, same)["checks"]["beats_on_score"]
    assert se.sign_p([True] * 8, [False] * 8) < 0.01 and se.sign_p([True, False], [True, False]) == 1.0


def test_recorder_adds_the_arms_sampling_and_keeps_labels():
    seen = []

    class R:
        label, tokens_out, seconds, done_reason, text = "loop", 7, 1.5, "stop", "x"

    def chat(model, messages, **kw):
        seen.append(kw)
        return R()

    rec = se.Recorder(chat, se.sampling_choice("C", ["text"]))
    rec.task = "t"
    rec("m", [], num_predict=5)
    rec("m", [], fmt={"type": "object"}, num_predict=5)
    assert [k["sampling"] for k in seen] == ["auto", "off"]
    assert rec.calls[0]["label"] == "loop" and rec.calls[1]["kind"] == "json"


def test_migration_77_creates_the_table_and_rows_store(tmp_path):
    from pflab.pm import store
    con = store.connect(tmp_path / "m.duckdb")
    n = se.store_rows(con, "sampling", "A", "qwen3:8b-q8_0", {"routing": 0.9, "text_fail_rate": 0.1, "answers_final": 1.0})
    assert n == 3
    assert con.execute("select count(*) from llm_s79_eval where market='IN'").fetchone()[0] == 3
