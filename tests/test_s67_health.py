"""S67 connector health from successful operations: success, expiry, failure and partial data, each with fakes. A token that exists is not a
working connector; one that has lapsed, a login that fails, and a mail run that got only some messages are each shown as what they are."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from pflab.app import runtime, system
from pflab.app import readiness as rd
from pflab.ingest import gmail, kite as km
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


def test_gmail_expiry_is_a_failed_run_and_a_warning_not_a_green_dot(rt, monkeypatch):
    monkeypatch.setattr(gmail, "connected", lambda: True)

    class Expired(Exception):
        pass

    def session():
        raise Expired("invalid_grant: Token has been expired or revoked (testing-mode tokens last 7 days)")
    monkeypatch.setattr(gmail, "session", session)
    con = rt.cursor()
    ctx = jobs.Ctx(con, NOW, rt.pm_dir, rt.data_root, rt.repo, "python", None)
    res = jobs.run_job(ctx, jobs.REGISTRY["mail"])
    assert res.status == "failed" and "invalid_grant" in res.detail
    gm = {c["id"]: c for c in system.connectors(rt, NOW)}["gmail"]
    assert gm["state"] == system.WARN and "invalid_grant" in gm["line"] and "showing what was read before" in gm["line"]
    assert {f["name"]: f for f in system.freshness(rt, NOW)}["Email"]["latest"] is None            # nothing was ever read: the failure shows nothing as read
    assert rd._mail(rt, NOW)["state"] == rd.PARTIAL


def test_a_mail_run_that_got_only_some_messages_is_partial_data_and_says_so(rt, monkeypatch):
    from tests.test_s65_gmail import FakeGmail, LEDGER, TRADEBOOK
    from pflab.app import inbox as ib
    from pflab.ingest import sniff
    monkeypatch.setattr(ib, "_start", lambda rt_, iid: None)
    monkeypatch.setattr(sniff, "passwords_from_secrets", lambda: [])
    real = ib.receive

    def flaky(rt_, name, data, *a, **k):
        if name == "ledger.xlsx":
            raise OSError("disk is full")
        return real(rt_, name, data, *a, **k)
    monkeypatch.setattr(ib, "receive", flaky)
    g = FakeGmail({"m1": (("Console", "Mon"), [("tb.csv", TRADEBOOK, False)]), "m2": (("bank", "Tue"), [("ledger.xlsx", LEDGER, False)])})
    monkeypatch.setattr(gmail, "connected", lambda: True)
    monkeypatch.setattr(gmail, "session", lambda: g)
    monkeypatch.setattr("pflab.ingest.mail_read.run", lambda rt_, sess, model: {"emails": 0})
    con = rt.cursor()
    ctx = jobs.Ctx(con, NOW, rt.pm_dir, rt.data_root, rt.repo, "python", None)
    res = jobs.run_job(ctx, jobs.REGISTRY["mail"])
    out = json.loads(res.detail)
    assert res.status == "ok" and out["kept"] == 1 and out["errors"] == 1                           # one message came, one did not
    gm = {c["id"]: c for c in system.connectors(rt, NOW)}["gmail"]
    assert gm["state"] == system.WARN and "message(s) could not be read" in gm["line"]
    assert rd._mail(rt, NOW)["state"] == rd.PARTIAL and rd.gaps(con, "mail")
