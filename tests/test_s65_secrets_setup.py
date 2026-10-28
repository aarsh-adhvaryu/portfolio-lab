r"""S65 Phase 7 item 1: the secrets file by command or form: values typed, never printed, names only back, a copy kept."""
import pytest
from fastapi.testclient import TestClient

from pflab import _toml
from pflab.app import runtime, server
from pflab.pm import secrets as sec
from pflab.pm import secrets_setup as ss
from pflab.pm import store

from datetime import datetime


def test_values_are_written_atomically_and_only_names_come_back(tmp_path):
    p = tmp_path / ".pflab" / "secrets.toml"
    done = ss.set_values({("telegram", "token"): "TOKEN-SECRET-123", ("telegram", "chat_id"): " 42 ", ("passwords", "BANK1_PW"): 'pa"ss\\word',
                          ("sec", "user_agent"): ""}, p)
    assert done == ["telegram.token", "telegram.chat_id", "passwords.BANK1_PW"]            # a blank value is skipped
    data = _toml.load(p)
    assert data["telegram"] == {"token": "TOKEN-SECRET-123", "chat_id": "42"} and data["passwords"]["BANK1_PW"] == 'pa"ss\\word'
    s = ss.status(p)
    assert s["telegram.token"] and s["passwords.BANK1_PW"] and not s["anthropic.api_key"]
    assert "TOKEN-SECRET-123" not in repr(s) and "TOKEN-SECRET-123" not in str(sec.load(p))


def test_an_update_keeps_the_other_values_and_a_copy_of_the_old_file(tmp_path):
    p = tmp_path / "secrets.toml"
    ss.set_values({("anthropic", "api_key"): "k1"}, p)
    ss.set_values({("kite", "api_key"): "a", ("anthropic", "api_key"): "k2"}, p)
    data = _toml.load(p)
    assert data["anthropic"]["api_key"] == "k2" and data["kite"]["api_key"] == "a"
    assert _toml.load(tmp_path / "secrets.toml.bak")["anthropic"]["api_key"] == "k1"


def test_unknown_names_and_unsafe_places_are_refused(tmp_path):
    p = tmp_path / "secrets.toml"
    with pytest.raises(ss.SetupError):
        ss.set_values({("kite", "nope"): "x"}, p)
    with pytest.raises(ss.SetupError):
        ss.set_values({("bad section", "api_key"): "x"}, p)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(ss.SetupError, match="outside the repo"):
        ss.set_values({("kite", "api_key"): "x"}, repo / "secrets.toml")


def test_the_prompt_asks_only_for_what_is_missing_and_never_says_a_value(tmp_path):
    p = tmp_path / "secrets.toml"
    ss.set_values({("telegram", "token"): "OLD-TOKEN"}, p)
    asked, said = [], []
    answers = iter(["chat-9", ""])                               # the token is set, so chat id comes first; Enter skips the password
    ss.prompt(["telegram"], ["BANK1_PW"], p, ask=lambda q: (asked.append(q), next(answers))[1], say=said.append)
    assert len(asked) == 2 and any("chat id" in q for q in asked) and any("BANK1_PW" in q for q in asked)
    assert "telegram.token: already set" in said and said[-1] == "set: telegram.chat_id"
    assert not any("OLD-TOKEN" in s or "chat-9" in s for s in said + asked)


def test_the_password_names_come_from_his_sources():
    src = {"bank": [{"account": "a", "file": "f", "password_env": "BANK1_PW"}, {"account": "b", "file": "g"}], "cas": {"password_env": "CAS_PW"}}
    assert ss.password_names(src) == ["BANK1_PW", "CAS_PW"]


def test_the_dashboard_form_is_write_only(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_SECRETS_FILE", str(tmp_path / "s.toml"))
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    rt = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: datetime(2026, 10, 28))
    c = TestClient(server.create_app(rt))
    assert c.post("/api/secrets", json={"section": "anthropic", "key": "api_key", "value": "sk-very-secret"}).json() == {"set": ["anthropic.api_key"]}
    assert c.post("/api/secrets", json={"section": "kite", "key": "bogus", "value": "x"}).status_code == 400
    got = c.get("/api/secrets")
    assert got.json()["status"]["anthropic.api_key"] is True and "sk-very-secret" not in got.text
