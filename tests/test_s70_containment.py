"""S70 (A34): containment is four things (Docker, reviewed code, did not run, host), stored as such, and a warning about it is closed only by
evidence the system checks itself: never by an answer. Synthetic data; Docker is faked."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from pflab.agents import questions as qs, sandbox as sb, workshop
from pflab.app import system
from pflab.hq import cases, containment as ct
from pflab.pm import store
from pflab.quant import trusted
from pflab.service import jobs, tasks

NOW = datetime(2026, 11, 2, 12, 0)
AFTER = datetime(2026, 10, 31, 18, 0)           # after the host path was closed (v2026.10.30)
BEFORE = datetime(2026, 10, 20, 12, 0)


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


@pytest.fixture
def app(monkeypatch):
    """An installed app: the uncontained subprocess is refused by name."""
    monkeypatch.setattr(sb, "installed_app", lambda: True)


def _calc(con, status="checked", contained=None, check=None, at=AFTER, code="x = 1", result=None):
    cid = cases._id(con, "hq_calcs", "calc_id")
    con.execute("INSERT INTO hq_calcs (calc_id, case_id, created_at, question, code, code_sha, datasets_json, params_json, result_json, status, contained, attempts, check_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [cid, None, at, "q", code, "sha", "[]", "{}", json.dumps(result if result is not None else {"v": 1}), status, contained, 1, json.dumps(check or {})])
    return cid


def _probe(con, ok=True, marker=None, at=NOW):
    system.record_check(con, "sandbox", ok, at, (marker or sb.release_marker()) + "; all checks passed: network_closed" if ok else "failed: network_closed")


def _flag(con, cid):
    return con.execute("SELECT contained FROM hq_calcs WHERE calc_id=?", [cid]).fetchone()[0]


# --- what is stored -------------------------------------------------------------------------------------------------------------

def test_the_four_states():
    assert ct.state_of(True) == "docker" and ct.state_of(False) == "host"
    assert ct.state_of(None, reviewed=True) == "reviewed" and ct.state_of(None) == "not_run"
    assert ct.is_reviewed(json.dumps({"trusted": True})) and ct.is_reviewed(json.dumps({"measure": True})) and not ct.is_reviewed(json.dumps({}))


def test_the_writers_store_what_happened(con):
    inputs = {"x": pd.DataFrame({"a": [1.0]})}
    k = trusted.record(con, None, NOW, "exposure_shock", "q", {}, inputs, {"v": 1})
    assert _flag(con, k) is None                                                   # reviewed code: not "not contained"
    docker = SimpleNamespace(status="checked", run=SimpleNamespace(contained=True, result={"v": 1}, cross_checked=True, problems=[]), spec=None, writer="w", attempts=[], measure=None)
    never = SimpleNamespace(status="failed", run=None, spec=None, writer="w", attempts=[], measure=None)
    host = SimpleNamespace(status="checked", run=SimpleNamespace(contained=False, result={"v": 1}, cross_checked=False, problems=[]), spec=None, writer="w", attempts=[], measure=None)
    assert _flag(con, cases.record_calc(con, None, NOW, "q", docker)) is True
    assert _flag(con, cases.record_calc(con, None, NOW, "q", never)) is None        # nothing ran
    assert _flag(con, cases.record_calc(con, None, NOW, "q", host)) is False


def test_the_investigation_detail_says_where_each_calculation_ran(con):
    from pflab.hq import views
    cid, _ = cases.open_case(con, NOW, "a question to look into", origin="investor", subject=None, isin=None, key="k1")
    for flag, check in ((True, {}), (None, {"trusted": True}), (None, {}), (False, {})):
        k = _calc(con, contained=flag, check=check)
        con.execute("UPDATE hq_calcs SET case_id=? WHERE calc_id=?", [cid, k])
    got = [c["ran"] for c in views.case_detail(con, cid)["calculations"]]
    assert got == ["docker", "reviewed", "not_run", "host"]


# --- the old rule's mistakes are corrected by the evidence each row carries -------------------------------------------------------

def test_repair_corrects_reviewed_code_and_tries_that_never_ran_but_never_a_result(con, tmp_path, app):
    trusted_row = _calc(con, contained=False, check={"trusted": True})
    never_ran = _calc(con, status="failed", contained=False)
    old_failed = _calc(con, status="failed", contained=False, at=BEFORE)           # before the host path was closed: cannot be vouched for
    a_result = _calc(con, status="checked", contained=False)                       # a result of model code recorded on the host: examined, never repaired
    fixed = ct.repair_records(con, tmp_path, NOW)
    assert fixed["reviewed_code"] == 1 and fixed["never_ran"] == 1
    assert _flag(con, trusted_row) is None and _flag(con, never_ran) is None
    assert _flag(con, old_failed) is False and _flag(con, a_result) is False
    assert "records corrected" in system.latest_check(con, "containment-records")["detail"]


def test_the_workshop_keeps_its_host_rows_except_reviewed_code(con, tmp_path):
    never_ran = _calc(con, status="failed", contained=False)                       # the workshop may really run on the host: not assumed away
    reviewed = _calc(con, contained=False, check={"trusted": True})
    ct.repair_records(con, tmp_path, NOW)
    assert _flag(con, never_ran) is False and _flag(con, reviewed) is None


# --- the proof ------------------------------------------------------------------------------------------------------------------

def test_it_is_proven_only_when_every_check_holds_and_then_the_warning_closes(con, tmp_path, app):
    _calc(con, contained=None, check={"trusted": True})
    _calc(con, contained=True)
    _probe(con)
    qs.ask(con, "workshop", "workshop:uncontained:2026-10-31", "This calculation ran in the uncontained developer subprocess", NOW)
    res = ct.run(con, tmp_path, NOW)
    assert res["proven"] and res["closed"] == 1 and all(c["ok"] for c in res["checks"].values())
    q = con.execute("SELECT status, answer FROM questions").fetchone()
    assert q[0] == "dropped" and q[1].startswith("closed by evidence:") and "probe_passed_for_this_release" in q[1]
    assert system.latest_check(con, "containment")["ok"] is True


def test_answering_seen_proves_nothing(con, tmp_path, app):
    _calc(con, contained=True)
    qid = qs.ask(con, "workshop", "workshop:uncontained:2026-10-31", "ran uncontained", NOW)      # and no probe has passed for this release
    qs.answer(con, qid, "seen", NOW)
    res = ct.run(con, tmp_path, NOW)
    assert not res["proven"] and res["closed"] == 0 and res["checks"]["probe_passed_for_this_release"]["ok"] is False
    assert system.latest_check(con, "containment")["ok"] is False


def test_each_check_can_fail_alone(con, tmp_path, app, monkeypatch):
    _calc(con, contained=True)
    _probe(con)
    assert ct.validate(con, tmp_path, NOW)["proven"]
    # a failed probe
    _probe(con, ok=False)
    assert not ct.validate(con, tmp_path, NOW)["checks"]["probe_passed_for_this_release"]["ok"]
    # a probe of another release or another runner
    _probe(con, marker="release=v2026.10.31.15 runner=000000000000")
    assert not ct.validate(con, tmp_path, NOW)["checks"]["probe_passed_for_this_release"]["ok"]
    _probe(con)
    assert ct.validate(con, tmp_path, NOW)["proven"]
    # a result of model code recorded on the host
    bad = _calc(con, status="checked", contained=False)
    v = ct.validate(con, tmp_path, NOW)
    assert not v["proven"] and not v["checks"]["no_result_ran_on_the_host"]["ok"]
    con.execute("DELETE FROM hq_calcs WHERE calc_id=?", [bad])
    # a result of model code with no record of where it ran
    unknown = _calc(con, status="checked", contained=None)
    v = ct.validate(con, tmp_path, NOW)
    assert not v["proven"] and not v["checks"]["every_model_result_ran_in_docker"]["ok"]
    con.execute("DELETE FROM hq_calcs WHERE calc_id=?", [unknown])
    # the host path open in the app
    monkeypatch.setattr(sb, "host_refused", lambda: False)
    v = ct.validate(con, tmp_path, NOW)
    assert not v["proven"] and not v["checks"]["host_path_refused"]["ok"]


def test_the_host_path_is_asked_by_use_not_read_from_a_flag(monkeypatch):
    monkeypatch.setattr(sb, "installed_app", lambda: False)
    assert sb.host_refused() is False                                              # the workshop's explicit setting is allowed
    monkeypatch.setattr(sb, "installed_app", lambda: True)
    assert sb.host_refused() is True
    with pytest.raises(sb.SandboxUnavailable):
        sb.pick(want="local")


# --- the probe job and the scheduler ----------------------------------------------------------------------------------------------

def _ctx(con, tmp_path):
    return jobs.Ctx(con, NOW, tmp_path, tmp_path, tmp_path)


def test_the_probe_records_which_release_it_proved_and_validates(con, tmp_path, app, monkeypatch):
    monkeypatch.setattr(sb, "probe", lambda *a, **k: {"ok": True, "checks": {"network_closed": True}, "why": "contained"})
    _calc(con, contained=True)
    out = tasks._sandbox_probe(_ctx(con, tmp_path))
    assert out["proven"] is True and sb.release_marker() in system.latest_check(con, "sandbox")["detail"]


def test_a_stale_image_is_rebuilt_once_and_probed_again(con, tmp_path, app, monkeypatch):
    seen = []
    replies = [{"ok": False, "checks": {"runner_matches_release": False}, "why": "stale"}, {"ok": True, "checks": {"network_closed": True}, "why": "contained"}]
    monkeypatch.setattr(sb, "probe", lambda *a, **k: replies.pop(0))
    monkeypatch.setattr(sb, "rebuild_image", lambda root, *a, **k: (seen.append(root) or (True, "")))
    out = tasks._sandbox_probe(_ctx(con, tmp_path))
    assert out["image_rebuilt"] is True and len(seen) == 1 and system.latest_check(con, "sandbox")["ok"] is True


def test_a_failed_rebuild_leaves_the_proof_failed_and_says_so(con, tmp_path, app, monkeypatch):
    monkeypatch.setattr(sb, "probe", lambda *a, **k: {"ok": False, "checks": {"runner_matches_release": False}, "why": "stale"})
    monkeypatch.setattr(sb, "rebuild_image", lambda *a, **k: (False, "no daemon"))
    with pytest.raises(RuntimeError, match="not proven.*no daemon"):
        tasks._sandbox_probe(_ctx(con, tmp_path))
    assert system.latest_check(con, "sandbox")["ok"] is False


def test_a_proof_for_an_older_release_makes_the_job_due_again(con, tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "docker")
    job = jobs.REGISTRY["sandbox"]
    slot = job.schedule.latest_slot(NOW)
    con.execute("INSERT INTO job_runs VALUES (1, 'sandbox', ?, ?, ?, 'ok', '{}')", [slot, slot + timedelta(minutes=5), slot + timedelta(minutes=6)])
    ctx = _ctx(con, tmp_path)
    due, why = jobs.is_due(ctx, job)
    assert due and "no passing containment probe for this release" in why              # it ran this morning, but not for what is installed now
    _probe(con, at=slot + timedelta(minutes=5))
    due, why = jobs.is_due(ctx, job)
    assert not due and "done for slot" in why
    _probe(con, marker="release=v2026.10.31.15 runner=000000000000")
    assert jobs.is_due(ctx, job)[0]


def test_the_screen_does_not_call_an_earlier_release_proven(con, monkeypatch):
    monkeypatch.setattr(system, "_docker", lambda: "running")
    monkeypatch.setattr(system, "_sandbox_status", lambda: {"ok": True, "why": ""})
    _probe(con, marker="release=v2026.10.31.15 runner=000000000000", at=NOW - timedelta(hours=3))
    state, line = system.sandbox_line(con, NOW)
    assert state == system.WARN and "not yet proven for this release" in line
    _probe(con, at=NOW - timedelta(hours=1))
    assert system.sandbox_line(con, NOW)[0] == system.OK
    system.record_check(con, "containment", False, NOW, "NOT proven: no_result_ran_on_the_host FAILED")       # the probe passed but the records disagree
    state, line = system.sandbox_line(con, NOW)
    assert state == system.WARN and "records do not all agree" in line
    _probe(con, ok=False, at=NOW)
    assert system.sandbox_line(con, NOW)[0] == system.DOWN
