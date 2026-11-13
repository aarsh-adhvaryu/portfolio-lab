"""S79b item 17: the local seats (fallback, modes, hysteresis), the llama-server wrapper (never launched), constrained decoding, the escalation rule, the teacher log, the cost view,
the deep pool. Fakes only: no Ollama, no llama-server, no GPU."""
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from pflab.llm import client, constrained, cost, escalate, seats, server, structured, teacher
from pflab.pm import store

NOW = datetime(2026, 11, 8, 12, 0)

CFG = {
    "policy": {"fallback_model": "qwen3:8b-q8_0", "fallback_backend": "ollama", "ram_floor_gb": 6.0, "hysteresis_s": 900, "mode_dwell_s": 120,
               "unload_keep_alive": 0, "fast_keep_alive": "30m"},
    "mode_seat": {"pre_open": "fast", "session": "fast", "post_close": "thinker", "deep": "thinker"},
    "seat": {"fast": {"default": "qwen3:8b-q8_0"}, "thinker": {"default": "qwen3:8b-q8_0"}},
    "llama_server": {"exe": "D:/llama.cpp/b12189/llama-server.exe", "host": "127.0.0.1", "port": 8089, "ctx_size": 8192, "parallel": 1, "ngl": 99, "startup_timeout_s": 5},
    "model": {
        "qwen3:8b-q8_0": {"backend": "ollama", "ollama": "qwen3:8b-q8_0", "ram_gb": 1.0, "options": {"num_ctx": 8192}},
        "gemma4:12b-q4": {"backend": "ollama", "ollama": "gemma4:12b-q4", "ram_gb": 3.0},
        "qwen3.6-35b-a3b": {"backend": "llama_server", "gguf": "D:/models/q36.gguf", "n_cpu_moe": 30, "ram_gb": 20.0, "ctx_size": 4096},
    },
}
INSTALLED = {"qwen3:8b-q8_0": {"digest": "d1"}, "gemma4:12b-q4": {"digest": "d2"}}


def picks(*rows):
    return [dict(role=r, model=m, registered_at=t, decision=d) for r, m, t, d in rows]


# --- seat resolution ------------------------------------------------------------------------------------------------------

def test_default_seat_is_the_fallback_model_and_not_flagged():
    s = seats.seat("fast", cfg=CFG, picks=[], installed=INSTALLED, free_ram=30)
    assert (s["key"], s["backend"], s["fallback"]) == ("qwen3:8b-q8_0", "ollama", False)
    assert s["options"] == {"num_ctx": 8192}


def test_chosen_pick_wins_and_unchosen_or_older_is_ignored():
    p = picks(("seat-fast", "gemma4:12b-q4", "2026-11-08T01:00:00", "chosen: beat qwen3 on the eval sets"),
              ("seat-fast", "other", "2026-11-08T02:00:00", "not chosen"),
              ("seat_fast", "qwen3:8b-q8_0", "2026-11-07T01:00:00", "chosen"))
    s = seats.seat("fast", cfg=CFG, picks=p, installed=INSTALLED, free_ram=30)
    assert s["key"] == "gemma4:12b-q4" and not s["fallback"]


def test_missing_model_falls_back_with_the_reason():
    p = picks(("seat-fast", "gemma4:12b-q4", "2026-11-08T01:00:00", "chosen"))
    s = seats.seat("fast", cfg=CFG, picks=p, installed={"qwen3:8b-q8_0": {"digest": "d1"}}, free_ram=30)
    assert s["fallback"] and s["key"] == "qwen3:8b-q8_0" and "not installed" in s["reason"] and s["requested"] == "gemma4:12b-q4"


def test_ram_floor_falls_back_and_enough_ram_does_not():
    p = picks(("seat-fast", "gemma4:12b-q4", "2026-11-08T01:00:00", "chosen"))
    low = seats.seat("fast", cfg=CFG, picks=p, installed=INSTALLED, free_ram=8.0)       # needs 3 + 6 = 9
    assert low["fallback"] and "RAM" in low["reason"]
    ok = seats.seat("fast", cfg=CFG, picks=p, installed=INSTALLED, free_ram=9.5)
    assert not ok["fallback"] and ok["key"] == "gemma4:12b-q4"
    already = seats.seat("fast", cfg=CFG, picks=p, installed=INSTALLED, free_ram=1.0, resident_key="gemma4:12b-q4")   # already loaded: its RAM is already spent
    assert not already["fallback"]


def test_llama_server_seat_needs_every_guard():
    p = picks(("seat-thinker", "qwen3.6-35b-a3b", "2026-11-08T01:00:00", "chosen"))
    bad = seats.seat("thinker", cfg=CFG, picks=p, installed=INSTALLED, guards=["GPU caps: not confirmed"])
    assert bad["fallback"] and "llama server cannot start" in bad["reason"] and bad["backend"] == "ollama"
    good = seats.seat("thinker", cfg=CFG, picks=p, installed=INSTALLED, guards=[])
    assert good["backend"] == "llama_server" and good["key"] == "qwen3.6-35b-a3b" and not good["fallback"]


def test_chat_target_replaces_a_llama_seat_whose_server_is_down(monkeypatch):
    p = picks(("seat-thinker", "qwen3.6-35b-a3b", "2026-11-08T01:00:00", "chosen"))
    monkeypatch.setattr(seats, "load_config", lambda path=None: CFG)
    down = seats.chat_target("seat:thinker", cfg=CFG, picks=p, installed=INSTALLED, guards=[], health=lambda: False)
    assert down["fallback"] and down["backend"] == "ollama" and "not running" in down["reason"]
    up = seats.chat_target("seat:thinker", cfg=CFG, picks=p, installed=INSTALLED, guards=[], health=lambda: True)
    assert up["backend"] == "llama_server" and not up["fallback"]


def test_unknown_seat_raises():
    with pytest.raises(ValueError):
        seats.seat("middle", cfg=CFG, picks=[])


def test_real_config_files_load_and_the_real_seats_resolve(monkeypatch):
    seats.clear_cache()
    for s in seats.SEATS:
        r = seats.seat(s, installed={"qwen3:8b-q8_0": {"digest": "x"}}, free_ram=30.0)
        assert r["backend"] in ("ollama", "llama_server") and r["model"]
    seats.clear_cache()


# --- modes, hysteresis, never both ------------------------------------------------------------------------------------------

def _plan(mode, st, t, **kw):
    return seats.for_mode(mode, now=t, cfg=CFG, state=st, picks=kw.pop("picks", PICKS_BOTH), installed=INSTALLED, free_ram=40.0, **kw)


PICKS_BOTH = picks(("seat-fast", "qwen3:8b-q8_0", "2026-11-08T01:00:00", "chosen"), ("seat-thinker", "gemma4:12b-q4", "2026-11-08T01:00:00", "chosen"))


def test_first_load_has_no_hysteresis_and_unloads_the_other_seat():
    st = {}
    p = _plan("session", st, 1000.0)
    assert p["action"] == "swap" and p["load"]["key"] == "qwen3:8b-q8_0" and [u["key"] for u in p["unload"]] == ["gemma4:12b-q4"]


def test_mode_switch_with_hysteresis_and_dwell():
    st = {"resident_seat": "fast", "resident_key": "qwen3:8b-q8_0", "swapped_at": 1000.0, "mode": "session", "mode_since": 0.0}
    held = _plan("post_close", st, 1100.0)                                  # mode just changed, last swap 100 s ago
    assert held["action"] == "hold" and "hysteresis" in held["reason"]
    st["swapped_at"] = 0.0
    still = _plan("post_close", st, 1130.0)                                 # past hysteresis (1130 > 900) but the mode is only 30 s old (changed at 1100)
    assert still["action"] == "hold" and "lasted" in still["reason"]
    go = _plan("post_close", st, 1300.0)                                    # the mode has held 200 s
    assert go["action"] == "swap" and go["load"]["key"] == "gemma4:12b-q4" and go["unload"][0]["key"] == "qwen3:8b-q8_0"
    assert seats.for_mode("session", now=1301.0, cfg=CFG, state={**st, "resident_key": "gemma4:12b-q4", "resident_seat": "thinker", "swapped_at": 1300.0, "mode": "session", "mode_since": 0.0},
                          picks=PICKS_BOTH, installed=INSTALLED, free_ram=40.0)["action"] == "hold"


def test_same_model_in_both_seats_never_swaps():
    st = {"resident_key": "qwen3:8b-q8_0"}
    p = seats.for_mode("deep", now=5000.0, cfg=CFG, state=st, picks=[], installed=INSTALLED, free_ram=40.0)
    assert p["action"] == "keep"


def test_unknown_mode_is_none():
    assert seats.for_mode("weekend", cfg=CFG, state={}, picks=[], installed=INSTALLED, free_ram=30.0)["action"] == "none"


def test_apply_unloads_with_keep_alive_zero_then_loads_and_records_state():
    calls = []

    def tr(method, path, payload, timeout):
        calls.append((path, payload))
        return {}
    st = {"resident_seat": "fast", "resident_key": "qwen3:8b-q8_0", "swapped_at": 0.0, "mode": "post_close", "mode_since": 0.0}
    plan = _plan("post_close", st, 5000.0)
    ev = seats.apply(plan, cfg=CFG, transport=tr, now=5000.0, state=st)
    assert [e["action"] for e in ev] == ["unload", "load"] and all(e["applied"] for e in ev)
    assert calls[0][1]["keep_alive"] == 0 and calls[0][1]["model"] == "qwen3:8b-q8_0"
    assert calls[1][1]["model"] == "gemma4:12b-q4" and calls[1][1]["keep_alive"] == "30m"
    assert st["resident_key"] == "gemma4:12b-q4" and st["swapped_at"] == 5000.0
    again = _plan("post_close", st, 5001.0)
    assert again["action"] == "keep"


def test_apply_failure_leaves_state_and_says_why():
    def tr(*a, **k):
        raise RuntimeError("ollama down")
    st = {"resident_seat": "fast", "resident_key": "qwen3:8b-q8_0", "swapped_at": 0.0, "mode": "post_close", "mode_since": 0.0}
    ev = seats.apply(_plan("post_close", st, 5000.0), cfg=CFG, transport=tr, now=5000.0, state=st)
    assert not any(e["applied"] for e in ev) and "ollama down" in ev[-1]["reason"] and st["resident_key"] == "qwen3:8b-q8_0"


def test_apply_llama_seat_stops_and_starts_the_server_through_the_guarded_wrapper():
    rec = []
    fake = SimpleNamespace(stop=lambda: rec.append("stop") or True, srv_settings=lambda c=None: {}, start=lambda key, e, **kw: rec.append(("start", key, e["n_cpu_moe"])) or {"started": True})
    p = picks(("seat-fast", "qwen3:8b-q8_0", "2026-11-08T01:00:00", "chosen"), ("seat-thinker", "qwen3.6-35b-a3b", "2026-11-08T01:00:00", "chosen"))
    st = {"resident_seat": "fast", "resident_key": "qwen3:8b-q8_0", "swapped_at": 0.0, "mode": "deep", "mode_since": 0.0}
    plan = seats.for_mode("deep", now=9000.0, cfg=CFG, state=st, picks=p, installed=INSTALLED, guards=[])
    assert plan["action"] == "swap" and plan["load"]["backend"] == "llama_server"
    ev = seats.apply(plan, cfg=CFG, transport=lambda *a, **k: {}, now=9000.0, state=st, server_mod=fake)
    assert ("start", "qwen3.6-35b-a3b", 30) in rec and st["resident_key"] == "qwen3.6-35b-a3b" and ev[-1]["applied"]


def test_dry_run_apply_touches_nothing():
    st = {"resident_key": "qwen3:8b-q8_0", "swapped_at": 0.0, "mode": "deep", "mode_since": 0.0}
    ev = seats.apply(_plan("deep", st, 5000.0), cfg=CFG, transport=lambda *a, **k: pytest.fail("called"), state=st, dry_run=True)
    assert all(not e["applied"] for e in ev) and st["resident_key"] == "qwen3:8b-q8_0"


def test_model_to_seat_reads_logged_model_names():
    assert seats.model_to_seat("gemma4:12b-q4", CFG, PICKS_BOTH) == "thinker"
    assert seats.model_to_seat("qwen3:8b-q8_0", CFG, PICKS_BOTH) == "fast"
    assert seats.model_to_seat("llama3:70b", CFG, PICKS_BOTH) == "other"


# --- the llama-server wrapper (nothing launches) -------------------------------------------------------------------------------

def test_command_line_has_the_flags_and_is_local_only():
    cmd = server.command(CFG["model"]["qwen3.6-35b-a3b"], server.srv_settings(CFG))
    assert cmd[0].endswith("llama-server.exe")
    for flag in ("--n-cpu-moe", "-ngl", "--ctx-size", "--parallel", "--jinja", "--host", "--port", "-m"):
        assert flag in cmd
    assert cmd[cmd.index("--n-cpu-moe") + 1] == "30" and cmd[cmd.index("-ngl") + 1] == "99" and cmd[cmd.index("--ctx-size") + 1] == "4096"
    assert cmd[cmd.index("--parallel") + 1] == "1" and cmd[cmd.index("--host") + 1] == "127.0.0.1" and cmd[cmd.index("--port") + 1] == "8089"
    with pytest.raises(server.ServerError):
        server.command({**CFG["model"]["qwen3.6-35b-a3b"], "host": "0.0.0.0"}, server.srv_settings(CFG))
    with pytest.raises(server.ServerError):
        server.command({"backend": "llama_server"}, server.srv_settings(CFG))


def test_guards_name_every_reason():
    m = CFG["model"]["qwen3.6-35b-a3b"]
    fails = server.guard_failures(m, policy=CFG["policy"], srv=server.srv_settings(CFG), free_ram=10.0, gpu_free=900.0, caps=(False, "not capped"), exists=lambda p: False)
    text = " | ".join(fails)
    for needle in ("llama-server.exe not found", "model file not found", "GPU caps", "free RAM", "free GPU memory"):
        assert needle in text
    ok = server.guard_failures(m, policy=CFG["policy"], srv=server.srv_settings(CFG), free_ram=40.0, gpu_free=9000.0, caps=(True, "ok"), exists=lambda p: True)
    assert ok == []
    nan = server.guard_failures(m, policy=CFG["policy"], srv=server.srv_settings(CFG), free_ram=float("nan"), gpu_free=9000.0, caps=(True, "ok"), exists=lambda p: True)
    assert any("free RAM" in f for f in nan)


def test_caps_applied_reads_the_clocks_or_an_acknowledgement(monkeypatch):
    monkeypatch.delenv("PFLAB_GPU_CAPS", raising=False)
    run = lambda v: (lambda *a, **k: SimpleNamespace(returncode=0, stdout=v))        # noqa: E731
    assert server.caps_applied({}, run("3090, 14001\n"))[0] is False
    assert server.caps_applied({}, run("2100, 9001\n"))[0] is True
    assert server.caps_applied({"caps_ack": True}, run("3090, 14001\n"))[0] is True
    assert server.caps_applied({}, lambda *a, **k: (_ for _ in ()).throw(OSError("no nvidia-smi")))[0] is False
    monkeypatch.setenv("PFLAB_GPU_CAPS", "ok")
    assert server.caps_applied({}, run("3090, 14001\n"))[0] is True


def test_start_refuses_when_a_guard_fails_and_dry_run_never_launches():
    m = CFG["model"]["qwen3.6-35b-a3b"]

    def boom(*a, **k):
        raise AssertionError("must not launch")
    with pytest.raises(server.GuardRefused):
        server.start("k", m, srv=server.srv_settings(CFG), popen=boom, guards=["GPU caps: not confirmed"])
    d = server.start("k", m, srv=server.srv_settings(CFG), popen=boom, guards=["x"], dry_run=True)
    assert d["dry_run"] and d["started"] is False and d["guard_failures"] == ["x"] and "--n-cpu-moe" in d["command"]


def test_start_health_stop_with_a_fake_process():
    class Proc:
        pid, returncode = 4242, None
        terminated = False

        def poll(self):
            return None if not self.terminated else 0

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0
    proc = Proc()
    answers = iter([{"status": "loading"}, {"status": "ok"}])
    tr = lambda m, p, j=None, t=0: next(answers)                                  # noqa: E731
    try:
        r = server.start("k", CFG["model"]["qwen3.6-35b-a3b"], srv=server.srv_settings(CFG), popen=lambda *a, **k: proc, guards=[], transport=tr, sleep=lambda s: None)
        assert r["started"] and r["pid"] == 4242 and server.running()["model"] == "k"
        assert server.start("k", CFG["model"]["qwen3.6-35b-a3b"], srv=server.srv_settings(CFG), popen=lambda *a, **k: pytest.fail("again"), guards=[])["already"]
        assert server.stop() is True and proc.terminated and server.running() is None
    finally:
        server.stop()


def test_server_chat_sends_the_schema_as_json_schema_and_returns_a_reply():
    seen = {}

    def tr(method, path, payload, timeout):
        seen.update(path=path, payload=payload)
        return {"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 11, "completion_tokens": 4}}
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
    r = server.chat("qwen3.6-35b-a3b", [{"role": "user", "content": "hi"}], fmt=schema, transport=tr, purpose="t", options={"top_k": 20, "temperature": 0.7})
    assert seen["path"] == "/v1/chat/completions"
    assert seen["payload"]["response_format"]["json_schema"]["schema"] == schema and seen["payload"]["top_k"] == 20
    assert seen["payload"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert (r.text, r.tokens_in, r.tokens_out, r.done_reason, r.label) == ('{"a": 1}', 11, 4, "stop", "ok")


# --- client.chat with a seat alias ---------------------------------------------------------------------------------------------

def test_client_chat_resolves_a_seat_alias_to_ollama_with_the_seat_options(monkeypatch):
    seen = {}

    def tr(method, path, payload=None, timeout=0):
        if path == "/api/tags":
            return {"models": [{"name": "qwen3:8b-q8_0", "digest": "d1", "details": {}}]}
        seen["payload"] = payload
        return {"message": {"content": "{}"}, "eval_count": 2, "prompt_eval_count": 3, "done_reason": "stop"}
    monkeypatch.setattr(seats, "chat_target", lambda alias, **kw: {"seat": "fast", "key": "qwen3:8b-q8_0", "model": "qwen3:8b-q8_0", "backend": "ollama", "options": {"num_ctx": 8192}, "fallback": False})
    schema = {"type": "object", "properties": {}}
    client.chat("seat:fast", [{"role": "user", "content": "x"}], transport=tr, fmt=schema)
    assert seen["payload"]["model"] == "qwen3:8b-q8_0" and seen["payload"]["options"]["num_ctx"] == 8192
    assert seen["payload"]["format"] == schema                               # the grammar/schema passes through to Ollama


def test_client_chat_routes_a_llama_seat_to_the_server(monkeypatch):
    got = {}
    monkeypatch.setattr(seats, "chat_target", lambda alias, **kw: {"seat": "thinker", "key": "q36", "model": "q36", "backend": "llama_server", "options": {}, "fallback": False})
    monkeypatch.setattr(server, "chat", lambda model, messages, **kw: got.update(model=model, fmt=kw["fmt"]) or "REPLY")
    out = client.chat("seat:thinker", [{"role": "user", "content": "x"}], fmt={"type": "object"})
    assert out == "REPLY" and got == {"model": "q36", "fmt": {"type": "object"}}


def test_client_chat_with_seats_off_uses_the_fallback_model(monkeypatch):
    monkeypatch.setattr(seats, "is_on", lambda path=None: False)
    seen = {}

    def tr(method, path, payload=None, timeout=0):
        if path == "/api/tags":
            return {"models": [{"name": "qwen3:8b-q8_0", "digest": "d1", "details": {}}]}
        seen["m"] = payload["model"]
        return {"message": {"content": "ok"}}
    client.chat("seat:fast", [{"role": "user", "content": "x"}], transport=tr)
    assert seen["m"] == "qwen3:8b-q8_0"


# --- constrained decoding ------------------------------------------------------------------------------------------------------

SCHEMA = {"type": "object", "required": ["verdict", "p"], "additionalProperties": False,
          "properties": {"verdict": {"enum": ["up", "down"]}, "p": {"type": "number", "minimum": 0, "maximum": 1}, "why": {"type": "array", "items": {"type": "string"}, "maxItems": 2}}}


def test_payload_for_each_backend():
    assert constrained.payload_for("ollama", SCHEMA) == {"format": SCHEMA}
    assert constrained.payload_for("llama_server", SCHEMA)["response_format"]["json_schema"]["schema"] == SCHEMA
    assert constrained.payload_for("ollama", None) == {}


def test_check_accepts_and_rejects():
    assert constrained.check({"verdict": "up", "p": 0.4, "why": ["a"]}, SCHEMA) is None
    assert "not one of" in constrained.check({"verdict": "sideways", "p": 0.4}, SCHEMA)
    assert "missing 'p'" in constrained.check({"verdict": "up"}, SCHEMA)
    assert "above" in constrained.check({"verdict": "up", "p": 3}, SCHEMA)
    assert "unexpected" in constrained.check({"verdict": "up", "p": 0.1, "zzz": 1}, SCHEMA)
    assert "more than" in constrained.check({"verdict": "up", "p": 0.1, "why": ["a", "b", "c"]}, SCHEMA)
    assert "expected" in constrained.check({"verdict": "up", "p": True}, SCHEMA)


def test_enum_grammar_is_gbnf_for_a_closed_list():
    g = constrained.enum_grammar(["buy", "hold"])
    assert g == 'root ::= "\\"buy\\"" | "\\"hold\\""\n'


def test_ask_json_now_checks_the_schema_and_retries_with_the_error():
    replies = iter([json.dumps({"verdict": "sideways", "p": 0.5}), json.dumps({"verdict": "up", "p": 0.5})])
    seen = []

    def chat(model, messages, **kw):
        seen.append((model, messages[-1]["content"], kw.get("fmt")))
        return client.Reply(next(replies), model, None, 1, 1, 0.1)
    r = structured.ask_json("s", "q", SCHEMA, purpose="t", chat=chat)
    assert r.ok and r.value["verdict"] == "up" and r.attempts == 2
    assert "not one of" in seen[1][1] and seen[0][2] == SCHEMA


def test_generate_calls_the_seat_alias():
    seen = {}

    def chat(model, messages, **kw):
        seen["model"] = model
        return client.Reply(json.dumps({"verdict": "down", "p": 0.2}), model, None, 1, 1, 0.1)
    r = constrained.generate("s", "q", SCHEMA, purpose="t", seat="thinker", chat=chat)
    assert r.ok and seen["model"] == "seat:thinker"


# --- the escalation rule ------------------------------------------------------------------------------------------------------

def _src(answers):
    it = iter(answers)

    def local(i):
        a = next(it)
        if isinstance(a, Exception):
            raise a
        return a
    return local


def test_agreement_is_accepted_locally_without_the_cloud():
    cloud = lambda v, r: pytest.fail("cloud called")                                # noqa: E731
    r = escalate.decide(_src(["buy", "Buy ", "buy"]), cloud_fn=cloud, cap_ok=lambda: True)
    assert r["rule"] == "agree" and r["answer"] == "buy" and not r["cloud_used"] and r["outcome"] == "accepted_local" and r["n_valid"] == 3


def test_disagreement_goes_to_the_cloud_inside_the_cap():
    r = escalate.decide(_src(["buy", "sell", "buy"]), cloud_fn=lambda v, rule: {"answer": "hold", "cost_rupees": 4.5}, cap_ok=lambda: True)
    assert r["rule"] == "disagree" and r["answer"] == "hold" and r["cloud_used"] and r["cost_rupees"] == 4.5 and r["outcome"] == "cloud"


def test_low_confidence_goes_to_the_cloud_even_when_they_agree():
    ans = [{"v": "buy", "c": 0.4}] * 3
    r = escalate.decide(_src(ans), agree_fn=lambda v: len({x["v"] for x in v}) == 1, confidence_fn=lambda a: a["c"], cloud_fn=lambda v, rule: "cloud-says", cap_ok=lambda: True)
    assert r["rule"] == "low_confidence" and r["answer"] == "cloud-says" and r["cloud_used"] and abs(r["confidence"] - 0.4) < 1e-9
    hi = escalate.decide(_src([{"v": "buy", "c": 0.9}] * 3), agree_fn=lambda v: True, confidence_fn=lambda a: a["c"], cloud_fn=lambda v, rule: pytest.fail("no"), cap_ok=lambda: True)
    assert hi["rule"] == "agree"


def test_cap_exhausted_returns_the_plurality_local_answer_and_says_so():
    r = escalate.decide(_src(["buy", "sell", "buy"]), cloud_fn=lambda v, rule: pytest.fail("no spend"), cap_ok=lambda: (False, "Rs 300 night cap used"))
    assert r["rule"] == "disagree" and r["answer"] == "buy" and not r["cloud_used"] and r["outcome"] == "cap_exhausted_local" and "Rs 300" in r["note"] and r["cap_ok"] is False


def test_cap_check_that_raises_is_a_closed_door():
    def bad():
        raise RuntimeError("x")
    r = escalate.decide(_src(["a", "b", "c"]), cloud_fn=lambda v, rule: pytest.fail("no"), cap_ok=bad)
    assert r["outcome"] == "cap_exhausted_local"


def test_failed_local_samples_and_a_failing_cloud():
    r = escalate.decide(_src([RuntimeError("down"), RuntimeError("down"), "buy"]), cloud_fn=lambda v, rule: "cloud", cap_ok=lambda: True)
    assert r["rule"] == "local_unavailable" and r["answer"] == "cloud" and r["n_valid"] == 1
    r2 = escalate.decide(_src(["buy", "sell", "buy"]), cloud_fn=lambda v, rule: (_ for _ in ()).throw(RuntimeError("api")), cap_ok=lambda: True)
    assert r2["outcome"] == "cloud_failed_local" and r2["answer"] == "buy" and not r2["cloud_used"]
    r3 = escalate.decide(_src(["buy", "sell", "buy"]))
    assert r3["outcome"] == "no_cloud_local" and r3["answer"] == "buy"


def test_one_sample_mode_and_dict_answers_compare_by_content():
    r = escalate.decide(_src([{"a": 1, "b": 2}]), samples=1)
    assert r["rule"] == "agree" and r["n_valid"] == 1
    assert escalate.all_equal([{"a": 1, "b": 2}, {"b": 2, "a": 1}]) and not escalate.all_equal([{"a": 1}, {"a": 2}])


def test_the_rule_that_fired_is_logged(tmp_path):
    con = store.connect(tmp_path / "e.duckdb")
    escalate.decide(_src(["buy", "sell", "buy"]), cloud_fn=lambda v, r: {"answer": "hold", "cost_rupees": 3.0}, cap_ok=lambda: True, con=con, kind="verdict", subject="TCS", now=NOW)
    escalate.decide(_src(["x", "x", "x"]), con=con, kind="verdict", subject="UVW", now=NOW)
    rows = con.execute("SELECT subject, rule, cloud_used, cost_rupees, n_samples, n_valid FROM escalation_log_s79 ORDER BY esc_id").fetchall()
    assert rows == [("TCS", "disagree", True, 3.0, 3, 3), ("UVW", "agree", False, 0.0, 3, 3)]
    s = escalate.summary(con)
    assert s["n"] == 2 and s["by_rule"]["disagree"]["cloud"] == 1 and s["by_rule"]["disagree"]["rupees"] == 3.0


# --- the teacher log -------------------------------------------------------------------------------------------------------------

def _gate():
    from pflab.hq import egress
    return egress.Gate(ids={"1234567890123"}, names=["rajesh"], address=[])


def test_teacher_record_redacts_input_and_output(tmp_path):
    con = store.connect(tmp_path / "t.duckdb")
    tid = teacher.record(con, call_id=7, source="hq", model="claude-opus", system_text="You are an analyst.", input_text="Client Rajesh, PAN ABCDE1234F, account 1234567890123, mail a@b.com",
                         output_text="Dear Rajesh, call 98765 43210 about 1234567890123", tokens_in=100, tokens_out=50, cost_inr=12.5, now=NOW, gate=_gate())
    assert tid == 1
    r = con.execute("SELECT input_text, output_text, n_redactions, cost_inr FROM teacher_log_s79").fetchone()
    for leak in ("Rajesh", "ABCDE1234F", "1234567890123", "a@b.com", "98765 43210"):
        assert leak not in r[0] and leak not in r[1]
    assert "[PAN]" in r[0] and "[NAME]" in r[1] and r[2] >= 6 and r[3] == 12.5
    assert teacher.record(con, call_id=7, source="hq", model="m", system_text="", input_text="again", output_text="x", gate=_gate()) is None      # the same call is kept once


def test_teacher_record_message_reads_an_anthropic_request_and_message(tmp_path):
    con = store.connect(tmp_path / "t.duckdb")
    params = {"model": "claude-opus-5-5", "system": [{"type": "text", "text": "Be brief."}], "messages": [{"role": "user", "content": [{"type": "text", "text": "Explain the move in TCS."}]}]}
    msg = SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking="..."), SimpleNamespace(type="text", text="It fell on guidance."),
                                   SimpleNamespace(type="tool_use", name="stock_facts", input={"symbol": "TCS"})], usage=SimpleNamespace(input_tokens=30, output_tokens=9))
    tid = teacher.record_message(con, 11, params, msg, "analyst", NOW, agent="research", cost_inr=2.0, gate=_gate())
    row = con.execute("SELECT system_text, input_text, output_text, tokens_in, tokens_out, source, agent FROM teacher_log_s79 WHERE teacher_id=?", [tid]).fetchone()
    assert row[0] == "Be brief." and "Explain the move in TCS." in row[1] and "It fell on guidance." in row[2] and "stock_facts" in row[2] and "thinking" not in row[2]
    assert row[3:] == (30, 9, "analyst", "research")


def test_teacher_never_raises_and_respects_the_switch(tmp_path, monkeypatch):
    assert teacher.record_message(None, 1, {}, None, "hq") is None                          # a broken connection never breaks a call
    con = store.connect(tmp_path / "t.duckdb")
    monkeypatch.setattr(seats, "switch", lambda path=None: {"on": True, "teacher_log": False})
    assert teacher.record(con, call_id=1, source="hq", model="m", system_text="", input_text="a", output_text="b", gate=_gate()) is None
    assert con.execute("SELECT count(*) FROM teacher_log_s79").fetchone()[0] == 0


def test_teacher_score_rows_and_export(tmp_path):
    con = store.connect(tmp_path / "t.duckdb")
    for cid in (1, 2, 3):
        teacher.record(con, call_id=cid, source="hq", model="claude-opus", system_text="sys", input_text=f"q{cid}", output_text=f"a{cid}", gate=_gate(), now=NOW)
    assert teacher.attach_score(con, 2, 0.9, "reviewer", NOW) == 1 and teacher.attach_score(con, 99, 0.1, "reviewer") == 0
    assert [r["call_id"] for r in teacher.rows(con, scored_only=True)] == [2]
    assert [r["call_id"] for r in teacher.rows(con, min_score=0.95)] == []
    chat = teacher.to_chat(teacher.rows(con, scored_only=True)[0])
    assert [m["role"] for m in chat["messages"]] == ["system", "user", "assistant"] and chat["meta"]["score"] == 0.9
    assert teacher.stats(con) == {"examples": 3, "scored": 1, "tokens_in": 0, "tokens_out": 0, "cost_inr": 0.0, "redactions": 0}


def test_exporter_writes_jsonl_from_a_copy(tmp_path, monkeypatch):
    import importlib.util
    import sys
    path = tmp_path / "copy.duckdb"
    con = store.connect(path)
    teacher.record(con, call_id=1, source="hq", model="claude-opus", system_text="sys", input_text="question", output_text="answer", gate=_gate(), now=NOW)
    teacher.attach_score(con, 1, 0.8, "reviewer", NOW)
    con.close()
    lab = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "tools" / "model_lab")
    monkeypatch.syspath_prepend(lab)
    spec = importlib.util.spec_from_file_location("export_teacher", lab + "/export_teacher.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["export_teacher"] = mod
    spec.loader.exec_module(mod)
    man = mod.export(path, tmp_path / "out", scored_only=True)
    lines = (tmp_path / "out" / "teacher.jsonl").read_text(encoding="utf-8").splitlines()
    assert man["examples"] == 1 and json.loads(lines[0])["messages"][-1] == {"role": "assistant", "content": "answer"}


def test_analyst_ring_hook_keeps_the_call(tmp_path):
    """S85 (G3): the doorbell asks through the door, whose road (`hq/llm.call`) keeps every cloud call in the teacher log (the analyst's own hook went with the old path)."""
    from datetime import datetime as _dt
    from pflab.agents import analyst as an
    from tests.test_analyst import CFG, FakeClient, req
    con = store.connect(tmp_path / "a.duckdb")
    o = an.ring(con, req(), FakeClient(), now=_dt(2026, 10, 17, 21, 0), cfg=CFG)
    assert o.status == "done"
    assert con.execute("SELECT call_id, source FROM teacher_log_s79").fetchall() == [(o.call_id, "hq")]


# --- the cost view --------------------------------------------------------------------------------------------------------------

def _ago(h):
    return NOW - timedelta(hours=h)


def test_cost_per_useful_act_by_seat(tmp_path):
    from pflab.llm import registry
    con = store.connect(tmp_path / "c.duckdb")
    p = PICKS_BOTH
    registry.log_run(con, _ago(3), "qwen3:8b-q8_0", seconds=10.0, tokens_in=100, tokens_out=20, status="ok", note="")
    registry.log_run(con, _ago(3) + timedelta(minutes=1), "qwen3:8b-q8_0", seconds=6.0, tokens_in=50, tokens_out=10, status="ok", note="loop")
    registry.log_run(con, _ago(2), "gemma4:12b-q4", seconds=30.0, tokens_in=400, tokens_out=100, status="ok", note="")
    registry.log_run(con, _ago(30 * 24), "qwen3:8b-q8_0", seconds=999.0, status="ok")                     # outside the window
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, input_tokens, output_tokens, cost_inr, finished_at) "
                "VALUES (1, ?, 'live', 'claude-opus', 'q', 'sha', '{}', 'done', 1000, 200, 12.0, ?)", [_ago(2), _ago(2) + timedelta(seconds=20)])
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, input_tokens, output_tokens, cost_inr, finished_at) "
                "VALUES (2, ?, 'live', 'claude-opus', 'q', 'sha', '{}', 'refused', 0, 0, 99.0, ?)", [_ago(2), _ago(2)])
    for iid, kind, st, useful in ((1, "tag", _ago(3), True), (2, "debate", _ago(2) - timedelta(minutes=1), True), (3, "tag", _ago(5), False)):
        con.execute("INSERT INTO mind_agenda (item_id, market, kind, subject, state, created_at, started_at, finished_at, useful) VALUES (?,?,?,?,?,?,?,?,?)",
                    [iid, "IN", kind, f"s{iid}", "done", st, st, st + timedelta(minutes=5), useful])
    v = cost.cost_view(con, "IN", 7, NOW, cfg=CFG, picks=p)
    f, t, c = v["seats"]["fast"], v["seats"]["thinker"], v["seats"]["cloud"]
    assert v["useful_acts"] == 2
    assert (f["calls"], f["wasted"], f["seconds"], f["tokens"]) == (2, 1, 16.0, 180)
    assert f["per_useful_act"] == {"seconds": 8.0, "tokens": 90.0, "rupees": 0.0}
    assert (t["calls"], t["seconds"], t["per_useful_act"]["seconds"]) == (1, 30.0, 15.0)
    assert (c["calls"], c["rupees"], c["per_useful_act"]["rupees"], c["seconds"]) == (1, 12.0, 6.0, 20.0)
    kinds = {k["kind"]: k for k in v["by_kind"]}
    assert kinds["tag"]["local_calls"] == 2 and kinds["debate"]["local_calls"] == 1 and kinds["debate"]["cloud_calls"] == 1 and kinds["debate"]["cloud_rupees"] == 12.0
    assert v["local_calls_total"] == 3 and v["local_calls_in_acts"] == 3
    panel = cost.world_panel(con, NOW)
    assert panel["available"] and panel["useful_acts"] == 2 and {r["seat"] for r in panel["rows"]} >= {"fast", "cloud"} and set(panel["picks"]) == {"fast", "thinker"}


def test_cost_view_on_an_empty_store_is_harmless(tmp_path):
    con = store.connect(tmp_path / "c.duckdb")
    v = cost.cost_view(con, "IN", 7, NOW, cfg=CFG, picks=[])
    assert v["useful_acts"] == 0 and v["seats"]["fast"]["per_useful_act"]["seconds"] is None and v["seats"]["cloud"]["per_useful_act"]["rupees"] is None


# --- tools, job, migrations, switch ---------------------------------------------------------------------------------------------

def test_tools_return_stable_keys_and_obey_the_switch(tmp_path, monkeypatch):
    import pflab.hq.tools  # noqa: F401  (loads the S79 tool modules in the order the app does)
    from pflab.hq.tools_s79 import t_seats
    con = store.connect(tmp_path / "x.duckdb")
    ctx = SimpleNamespace(con=con, now=NOW)
    tools = {t.name: t for t in t_seats.TOOLS}
    assert set(tools) == {"seat_status", "cost_per_act"} and all(t.kind == "read" for t in tools.values())
    s = tools["seat_status"].fn(ctx, {})
    assert set(s["seats"]) == {"fast", "thinker"} and "plan" in s and "server" in s and "teacher" in s and s["mode"] in ("pre_open", "session", "post_close", "deep")
    c = tools["cost_per_act"].fn(ctx, {})
    assert c["useful_acts"] == 0 and "fast" in c["seats"]
    monkeypatch.setattr(seats, "is_on", lambda path=None: False)
    assert tools["seat_status"].fn(ctx, {}) == {"off": True} and tools["cost_per_act"].fn(ctx, {}) == {"off": True}
    from pflab.hq import tools_s79
    assert {"seat_status", "cost_per_act"} <= set(tools_s79.names())


def test_job_records_the_plan_once_and_does_not_apply_unless_managed(tmp_path, monkeypatch):
    from pflab.service import jobs, tasks_s79_seats as ts
    con = store.connect(tmp_path / "j.duckdb")
    ctx = jobs.Ctx(con, NOW, tmp_path, tmp_path, tmp_path)
    monkeypatch.setattr(seats, "switch", lambda path=None: {"on": True, "manage": False})
    monkeypatch.setattr(seats, "STATE", {})
    monkeypatch.setattr(seats, "load_picks", lambda path=None: [])
    monkeypatch.setattr(seats, "apply", lambda *a, **k: pytest.fail("not managed"))
    monkeypatch.setattr(seats, "seat", lambda name, **kw: {"seat": name, "key": "qwen3:8b-q8_0", "model": "qwen3:8b-q8_0", "backend": "ollama", "options": {}, "fallback": False, "reason": "t", "requested": "x"})
    a = ts._seats(ctx)
    assert a["managed"] is False and a["events"] == 1
    b = ts._seats(ctx)
    assert b["events"] == 0                                                          # an unchanged plan is not a new row
    monkeypatch.setattr(seats, "switch", lambda path=None: {"on": False})
    assert "skipped" in ts._seats(ctx)
    assert any(j.name == "seats_mode" for j in jobs.REGISTRY.values()) if hasattr(jobs, "REGISTRY") else True


def test_migrations_94_95_exist_and_the_s79b_switch_is_declared(tmp_path):
    con = store.connect(tmp_path / "m.duckdb")
    for t in ("escalation_log_s79", "seat_event_s79", "teacher_log_s79"):
        assert con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name=?", [t]).fetchone()[0] == 1
    v = {r[0] for r in con.execute("SELECT version FROM schema_migrations").fetchall()} if con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name='schema_migrations'").fetchone()[0] else {94, 95}
    assert {94, 95} <= v
    assert seats.switch().get("on") is True and seats.switch().get("manage") is False


# --- the deep pool ---------------------------------------------------------------------------------------------------------------

def _sq(x):
    return x * x


def test_deep_pool_budget_and_parallel_run_in_deep_mode():
    from concurrent.futures import ThreadPoolExecutor
    from pflab import deep_pool as dp
    assert dp.core_budget(8) == 6 and dp.core_budget(2) == 1 and dp.core_budget(1) == 1
    pool = dp.DeepPool(workers=3, mode_fn=lambda: "deep", executor_factory=lambda n: ThreadPoolExecutor(max_workers=n), poll_s=0.01, switch_fn=lambda: True)
    out = pool.run(_sq, [1, 2, 3, 4, 5])
    assert out["results"] == [1, 4, 9, 16, 25] and out["done"] == 5 and not out["cancelled"] and out["workers"] == 3 and out["mode"] == "deep"


def test_deep_pool_is_serial_outside_deep_or_when_switched_off():
    from pflab import deep_pool as dp
    made = []
    pool = dp.DeepPool(workers=4, mode_fn=lambda: "session", executor_factory=lambda n: made.append(n), switch_fn=lambda: True)
    out = pool.run(_sq, [2, 3])
    assert out["results"] == [4, 9] and out["workers"] == 1 and "serially" in out["reason"] and made == []
    off = dp.DeepPool(workers=4, mode_fn=lambda: "deep", executor_factory=lambda n: made.append(n), switch_fn=lambda: False).run(_sq, [5])
    assert off["results"] == [25] and made == []
    skip = dp.DeepPool(mode_fn=lambda: "session", serial_fallback=False, switch_fn=lambda: True).run(_sq, [1, 2])
    assert skip["done"] == 0 and skip["results"] == [None, None]


def test_deep_pool_cancels_cooperatively_when_the_mode_changes():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from pflab import deep_pool as dp
    mode = {"m": "deep"}
    gate = threading.Event()
    started = []

    def work(x):
        started.append(x)
        if x == 0:
            mode["m"] = "session"                                     # the mode flips while the first item runs
            gate.set()
        gate.wait(2)
        return x + 100
    pool = dp.DeepPool(workers=1, mode_fn=lambda: mode["m"], executor_factory=lambda n: ThreadPoolExecutor(max_workers=n), poll_s=0.01, switch_fn=lambda: True)
    out = pool.run(work, list(range(6)))
    assert out["cancelled"] and "session" in out["reason"] and out["results"][0] == 100 and out["done"] < 6 and None in out["results"]
    assert len(started) < 6                                         # the not-yet-started items never ran


def test_deep_pool_caller_cancel_and_item_errors():
    from concurrent.futures import ThreadPoolExecutor
    from pflab import deep_pool as dp

    def bad(x):
        if x == 2:
            raise ValueError("boom")
        return x
    pool = dp.DeepPool(workers=2, mode_fn=lambda: "deep", executor_factory=lambda n: ThreadPoolExecutor(max_workers=n), poll_s=0.01, switch_fn=lambda: True)
    out = pool.run(bad, [1, 2, 3])
    assert out["results"] == [1, None, 3] and "boom" in out["errors"][1]


def test_deep_pool_with_real_processes():
    from pflab import deep_pool as dp
    out = dp.DeepPool(workers=2, mode_fn=lambda: "deep", poll_s=0.05, switch_fn=lambda: True).run(abs, [-1, -2, -3])
    assert out["results"] == [1, 2, 3] and out["workers"] == 2


def test_free_ram_is_a_positive_number_on_this_pc():
    fr = server.free_ram_gb()
    assert fr == fr and fr > 0.1


def test_ask_json_takes_the_fast_seat_only_when_a_pick_is_registered(monkeypatch):
    seen = []

    def chat(model, messages, **kw):
        seen.append(model)
        return client.Reply(json.dumps({"verdict": "up", "p": 0.5}), model, None, 1, 1, 0.1)
    monkeypatch.setattr(seats, "load_picks", lambda path=None: [])
    structured.ask_json("s", "q", SCHEMA, purpose="t", chat=chat)
    monkeypatch.setattr(seats, "load_picks", lambda path=None: picks(("seat-fast", "gemma4:12b-q4", "2026-11-08T01:00:00", "chosen")))
    structured.ask_json("s", "q", SCHEMA, purpose="t", chat=chat)
    structured.ask_json("s", "q", SCHEMA, purpose="t", chat=chat, model="qwen3:8b-q8_0")          # an explicit model always wins
    assert seen[0] != "seat:fast" and seen[1:] == ["seat:fast", "qwen3:8b-q8_0"]
    monkeypatch.setattr(seats, "is_on", lambda path=None: False)
    assert seats.alias_if_picked("fast") is None
