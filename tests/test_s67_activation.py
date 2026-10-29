"""S67 local: the first-launch gate. A pending profile reaches no mailbox or broker and runs no job; only the icon's launcher opens it;
an active profile stays active. Synthetic profile folders only."""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from pflab import activation
from pflab.ingest import gmail, kite
from pflab.service import jobs


def test_a_profile_without_the_file_is_active_so_the_running_app_and_the_workshop_are_unchanged(tmp_path):
    assert activation.state(tmp_path) == "active" and not activation.is_pending(tmp_path)
    activation.guard("anything", tmp_path)


def test_a_new_profile_is_dormant_and_only_the_icon_opens_it(tmp_path):
    activation.write_pending(tmp_path, profile="p2")
    assert activation.is_pending(tmp_path)
    with pytest.raises(activation.ActivationPending):
        activation.guard("reading the mailbox", tmp_path)
    for via in ("", "installer", "verify", "cli", "task"):
        with pytest.raises(activation.ActivationPending):
            activation.activate(tmp_path, via=via)
    assert activation.is_pending(tmp_path)
    assert activation.activate(tmp_path, via="icon") is True and activation.state(tmp_path) == "active"
    assert activation.activate(tmp_path, via="icon") is False                   # a later click changes nothing
    assert json.loads(activation.path(tmp_path).read_text(encoding="utf-8"))["via"] == "icon"


def test_an_active_profile_is_never_armed_again_and_a_damaged_file_stays_closed(tmp_path):
    activation.write_pending(tmp_path)
    activation.activate(tmp_path, via="icon")
    with pytest.raises(ValueError):
        activation.write_pending(tmp_path)                                      # a fresh start makes a NEW profile
    assert activation.state(tmp_path) == "active"
    other = tmp_path / "other"
    other.mkdir()
    activation.path(other).write_text("{broken", encoding="utf-8")
    assert activation.is_pending(other)                                         # unreadable means closed, not open


def test_a_pending_profile_runs_no_job_and_reaches_no_mailbox_or_broker(tmp_path, monkeypatch):
    activation.write_pending(tmp_path)
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    ran = []
    ctx = SimpleNamespace(pm_dir=tmp_path, con=None, now=datetime(2026, 10, 29, 16, 0))
    fake = SimpleNamespace(name="probe", enabled_fn=None, fn=lambda c: ran.append(1) or {})
    r = jobs.run_job(ctx, fake)
    assert r.status == "skipped" and "first launch" in r.detail and ran == []
    with pytest.raises(activation.ActivationPending):
        gmail.session()
    assert kite.client(SimpleNamespace(get=lambda *a: "x")) is None
    activation.activate(tmp_path, via="icon")
    assert not activation.is_pending()                                          # the same folder, now opened by the icon
