"""S70: every call to the local model is kept in llm_runs (purpose, tokens, seconds, failures), so its real workload can be seen."""
from __future__ import annotations

from datetime import datetime

import pytest

from pflab.llm import client, registry
from pflab.pm import store

NOW = datetime(2026, 11, 2, 12, 0)
TAGS = {"models": [{"name": "qwen3:8b-q8_0", "digest": "abc123", "size": 1, "details": {"parameter_size": "8B", "quantization_level": "Q8_0"}}]}


def _transport(fail=False):
    def t(method, path, payload=None, timeout=0):
        if path == "/api/tags":
            return TAGS
        if fail:
            raise ConnectionError("Ollama went away")
        return {"message": {"content": "42"}, "prompt_eval_count": 17, "eval_count": 3}
    return t


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    client.set_sink(lambda d: registry.log_run(c, NOW, d["model"], role=d["purpose"] or None, model_digest=d.get("digest"), tokens_in=d["tokens_in"],
                                              tokens_out=d["tokens_out"], seconds=d["seconds"], status=d["status"], note=d["note"]))
    yield c
    client.set_sink(None)


def test_a_call_is_kept_with_what_it_was_for(con):
    r = client.chat("qwen3:8b-q8_0", [{"role": "user", "content": "17 + 25?"}], transport=_transport(), purpose="routing")
    assert r.text == "42"
    row = con.execute("SELECT role, model, model_digest, tokens_in, tokens_out, status FROM llm_runs").fetchone()
    assert row == ("routing", "qwen3:8b-q8_0", "abc123", 17, 3, "ok")


def test_a_failed_call_is_kept_and_still_raises(con):
    with pytest.raises(ConnectionError):
        client.chat("qwen3:8b-q8_0", [{"role": "user", "content": "x"}], transport=_transport(fail=True), purpose="experiment_code")
    row = con.execute("SELECT role, status, note FROM llm_runs").fetchone()
    assert row[0] == "experiment_code" and row[1] == "failed" and "Ollama went away" in row[2]


def test_a_broken_sink_never_breaks_the_call():
    client.set_sink(lambda d: 1 / 0)
    try:
        assert client.chat("qwen3:8b-q8_0", [{"role": "user", "content": "x"}], transport=_transport()).text == "42"
    finally:
        client.set_sink(None)


def test_without_a_sink_nothing_is_kept_and_nothing_changes():
    client.set_sink(None)
    assert client.chat("qwen3:8b-q8_0", [{"role": "user", "content": "x"}], transport=_transport()).text == "42"


def test_as_llm_passes_the_purpose_through(con):
    client.as_llm("qwen3:8b-q8_0", purpose="brief", transport=_transport())("hello")
    assert con.execute("SELECT role FROM llm_runs").fetchone()[0] == "brief"
