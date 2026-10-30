"""S67 connector health from successful operations: success, expiry, failure and partial data, each with fakes. A token that exists is not a
working connector; one that has lapsed, a login that fails, and a mail run that got only some messages are each shown as what they are."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from pflab.app import runtime, system
from pflab.app import readiness as rd
from pflab.ingest import kite as km
from pflab.pm import store
from pflab.service import jobs, tasks  # noqa: F401  (registers the jobs)

NOW = datetime(2026, 11, 4, 21, 0)


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(system, "_ollama", lambda: {"up": True, "models": ["qwen3:8b-q8_0", "nomic-embed-text:latest"]})
    monkeypatch.setattr(system, "_docker", lambda: "not installed")
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def kite_state(rt):
    return {c["id"]: c for c in system.connectors(rt, NOW)}["kite"]


def test_kite_login_success_then_expiry_at_the_next_morning(rt, tmp_path, monkeypatch):
    tok = tmp_path / "kite_token.json"
    monkeypatch.setattr(km, "default_token_path", lambda: tok)
    con = rt.cursor()
    km.TokenStore(tok).save("tok", datetime(2026, 11, 4, 8, 0))                          # logged in this morning
    con.execute("INSERT INTO kite_snapshots (snap_id, taken_at, account_id, kind, amount) VALUES (1, ?, 'ZER', 'cash', 1)", [NOW - timedelta(hours=1)])
    assert kite_state(rt)["state"] == system.OK                                          # a login AND a read that worked
    monkeypatch.setattr(runtime, "token_valid", lambda now=None: km.TokenStore(tok).load(now or NOW) is not None)
    late = datetime(2026, 11, 5, 6, 30)                                                  # the token lapsed at 06:00
    cs = {c["id"]: c for c in system.connectors(rt, late)}
    assert cs["kite"]["state"] == system.WARN and "not logged in today" in cs["kite"]["line"] and cs["kite"]["action"] == "kite"


