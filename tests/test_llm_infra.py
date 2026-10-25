"""S21: client (fake transport), registry and pre-registration, budget, LangGraph loop, evaluation harness, smoke,
OKF validator, attestation. No Ollama needed."""
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest


from pflab.llm import client, evalset, graphs, guard, registry as reg, smoke
from pflab.pm import store


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


# --- client -----------------------------------------------------------------------------------------------------

class Fake:
    def __init__(self, reply="ok [F:x]", models=None, fail=False):
        self.calls, self.reply, self.fail = [], reply, fail
        self.models = models if models is not None else {"qwen3.5-9b-16k:latest": "abc123digest"}

    def __call__(self, method, path, payload, timeout):
        self.calls.append((method, path, payload))
        if self.fail:
            raise ConnectionError("refused")
        if path == "/api/tags":
            return {"models": [{"name": n, "digest": d, "size": 1, "details": {"parameter_size": "9B", "quantization_level": "Q4"}}
                               for n, d in self.models.items()]}
        return {"message": {"content": self.reply}, "prompt_eval_count": 12, "eval_count": 5}


def test_chat_sends_deterministic_options_and_reports_digest_and_tokens():
    f = Fake()
    r = client.chat("qwen3.5-9b-16k", [{"role": "user", "content": "hi"}], transport=f)
    assert (r.text, r.model, r.digest, r.tokens_in, r.tokens_out) == ("ok [F:x]", "qwen3.5-9b-16k:latest", "abc123digest", 12, 5)
    payload = f.calls[-1][2]
    assert payload["think"] is False and payload["stream"] is False
    assert payload["options"] == {"temperature": 0.0, "seed": client.SEED, "num_predict": 400}


def test_missing_model_and_unreachable_server_are_clear_errors():
    with pytest.raises(client.OllamaError, match="ollama pull qwen3.5:27b"):
        client.chat("qwen3.5:27b", [], transport=Fake())
    with pytest.raises(client.OllamaError, match="not reachable"):
        client.chat("x", [], transport=Fake(fail=True))


def test_resolve_accepts_a_name_without_latest():
    m = client.installed(Fake())
    assert client.resolve("qwen3.5-9b-16k", m) == "qwen3.5-9b-16k:latest" and client.resolve("nope", m) is None


# --- registry ------------------------------------------------------------------------------------------------------

def test_prompts_are_identified_by_their_exact_text():
    r = reg.PromptRegistry()
    s = r.register("p", "text")
    assert s == reg.sha("text") == r.sha_of("p") and r.register("p", "text") == s
    with pytest.raises(ValueError, match="different text"):
        r.register("p", "changed")


def test_the_research_pick_is_registered_before_any_evaluation():
    p = reg.pick_for("research")
    assert p["model"] == "qwen3.5:27b" and p["registered_at"] == datetime(2026, 10, 6, 17, 18, 20)
    assert not p["evaluated_at"] and not p["decision"]                       # nothing has been evaluated
    assert Path(__file__).parents[1].joinpath(p["protocol"]).exists()
    assert reg.pick_for("classify")["model"] == "qwen3.5-9b-16k"


def test_an_unregistered_or_later_registered_model_cannot_be_evaluated(tmp_path):
    f = tmp_path / "picks.toml"
    f.write_text('[[pick]]\nrole = "research"\nmodel = "m1"\nregistered_at = 2026-10-06T10:00:00\n')
    assert reg.require_registered("research", "m1", datetime(2026, 10, 6, 10, 0, 1), f)["model"] == "m1"
    with pytest.raises(reg.NotRegistered, match="not before this run"):
        reg.require_registered("research", "m1", datetime(2026, 10, 6, 9, 0), f)
    with pytest.raises(reg.NotRegistered, match="BEFORE evaluating"):
        reg.require_registered("research", "other", datetime(2027, 1, 1), f)
    with pytest.raises(reg.NotRegistered):
        reg.require_registered("classify", "m1", datetime(2027, 1, 1), f)


def test_runs_are_logged_with_digest_prompt_sha_and_sources(con):
    rid = reg.log_run(con, datetime(2026, 10, 7, 23, 0), "qwen3.5:27b", role="research", model_digest="d1", prompt_name="p",
                      prompt_sha="s1", sources=["sha-a", "sha-b"], guard_result="pass", attempts=2, tokens_in=100, tokens_out=50, seconds=12.5)
    row = con.execute("SELECT role, model_digest, prompt_sha, sources_json, guard_result, attempts, seconds FROM llm_runs WHERE run_id=?", [rid]).fetchone()
    assert row == ("research", "d1", "s1", '["sha-a", "sha-b"]', "pass", 2, 12.5)


# --- budget ----------------------------------------------------------------------------------------------------------



# --- LangGraph loop ----------------------------------------------------------------------------------------------------------

class Script:
    def __init__(self, *d):
        self.d, self.prompts = list(d), []

    def __call__(self, p):
        self.prompts.append(p)
        return self.d.pop(0)


FACTS = {"revenue_ttm": (5687490.0, "million")}
GOOD, BAD = "Revenue was 5,687,490 million [F:revenue_ttm].", "Revenue grew 12% [F:revenue_ttm]."


@pytest.mark.parametrize("drafts,ok,attempts", [([GOOD], True, 1), ([BAD, GOOD], True, 2), ([BAD, BAD, GOOD], True, 3), ([BAD, BAD, BAD], False, 3)])
def test_graph_matches_the_plain_loop(drafts, ok, attempts):
    a = graphs.run(Script(*drafts), "write", FACTS, {}, retries=2)
    b = guard.guarded_generate(Script(*drafts), "write", FACTS, {}, retries=2)
    assert (a.ok, a.attempts, a.text) == (b.ok, b.attempts, b.text) == (ok, attempts, GOOD if ok else None)


def test_graph_feeds_the_violations_back_and_never_returns_a_dropped_draft():
    s = Script(BAD, GOOD)
    out = graphs.run(s, "write", FACTS, {})
    assert "'12%'" in s.prompts[1] and s.prompts[1].startswith("write") and out.ok
    assert graphs.run(Script(BAD, BAD, BAD), "write", FACTS, {}, retries=2).text is None


# --- evaluation harness (pre-registered) -------------------------------------------------------------------------------------------

def test_the_task_set_is_fixed_by_its_seed():
    a, b = evalset.build(), evalset.build()
    assert len(a) == 40 and [t.prompt for t in a] == [t.prompt for t in b] and [t.facts for t in a] == [t.facts for t in b]
    assert evalset.build(seed=1)[0].prompt != a[0].prompt
    t = a[0]
    assert "FACTS:" in t.prompt and "SOURCES:" in t.prompt and "[S1]" in t.prompt and all(k in t.prompt for k in t.facts)
    assert 6 <= len(t.facts) <= 8 and set(t.sources) == {"S1", "S2"}


def perfect_llm_factory(model):
    def llm(prompt):
        return "The note uses no numbers [S1]. It cites its source [S2]. It stays inside the facts [F:price]."
    return llm


def test_evaluate_runs_only_for_a_registered_pick_and_logs_every_draft(con):
    now = datetime(2026, 10, 7, 12, 0)
    r = evalset.evaluate(con, "qwen3.5:27b", "research", perfect_llm_factory, evalset.build(n=5), now=now)
    assert (r.n, r.first_pass, r.within_retries, r.first_attempt_pass_rate) == (5, 5, 5, 1.0)
    assert con.execute("SELECT count(*) FROM llm_runs WHERE role='research'").fetchone()[0] == 5
    with pytest.raises(reg.NotRegistered):
        evalset.evaluate(con, "some-other-model:70b", "research", perfect_llm_factory, evalset.build(n=1), now=now)
    with pytest.raises(reg.NotRegistered, match="not before this run"):
        evalset.evaluate(con, "qwen3.5:27b", "research", perfect_llm_factory, evalset.build(n=1), now=datetime(2026, 10, 6, 17, 0))


def test_evaluate_counts_first_attempt_passes_separately_from_retries(con):
    def factory(model):
        def llm(prompt):          # wrong on the first try, right once the checker's feedback is in the prompt
            return "It stays inside the facts [F:price]." if "rejected by the checker" in prompt else "Revenue grew 12.345 [F:price]."
        return llm

    r = evalset.evaluate(con, "qwen3.5:27b", "research", factory, evalset.build(n=4), now=datetime(2026, 10, 7))
    assert (r.first_pass, r.within_retries) == (0, 4) and r.first_attempt_pass_rate == 0.0


# --- smoke -------------------------------------------------------------------------------------------------------------------------

def test_smoke_passes_and_logs_with_the_digest(con):
    f = Fake(reply="Revenue was 5,687,490 million rupees with a net margin of 6.9% [F:revenue_ttm] [F:net_margin].")
    r = smoke.run(con, "qwen3.5-9b-16k", transport=f)
    assert r["passed"] and r["guard_first_try"] and r["digest"] == "abc123digest" and r["tokens_out"] == 5
    row = con.execute("SELECT model_digest, guard_result, status, prompt_name FROM llm_runs").fetchone()
    assert row == ("abc123digest", "pass", "ok", "smoke_v1")


def test_smoke_records_a_guard_failure_without_failing_the_smoke(con):
    r = smoke.run(con, "qwen3.5-9b-16k", transport=Fake(reply="Revenue grew 12% [F:revenue_ttm]."))
    assert r["passed"] and not r["guard_first_try"]
    assert con.execute("SELECT guard_result FROM llm_runs").fetchone()[0].startswith("fail: ")


def test_smoke_fails_cleanly_for_a_model_that_is_not_installed(con):
    r = smoke.run(con, "qwen3.5:27b", transport=Fake())
    assert not r["passed"] and "ollama pull qwen3.5:27b" in r["reason"]
    assert con.execute("SELECT status, model FROM llm_runs").fetchone() == ("failed", "qwen3.5:27b")
    assert not smoke.run(con, "qwen3.5-9b-16k", transport=Fake(reply="  "))["passed"]


# --- OKF ---------------------------------------------------------------------------------------------------------------------------

def thesis_meta(**kw):
    m = {"type": "thesis", "title": "Acme thesis", "description": "d", "stale_after": date(2027, 1, 1),
         "sources": [{"id": "s1", "title": "FY26 annual report", "url": "https://example.com/ar"}]}
    m.update(kw)
    return m




def codes(rep, level=None):
    return {(i.concept, i.code) for i in rep.issues if level is None or i.level == level}




















# --- attestation ----------------------------------------------------------------------------------------------------------------------------

