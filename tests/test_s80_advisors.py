"""S80 phase 1: the v1 advisor layers are switched off while the close loop is on (configs/core.toml [core] advisors_off), and come back when it is not."""
from __future__ import annotations

import pytest

from pflab import core
from pflab.hq import missions, service
from tests.test_s68_autonomy import con, rt  # noqa: F401  (the fixtures)


def _set(monkeypatch, advisors_off: bool, on: bool = True):
    real = core.settings
    monkeypatch.setattr(core, "settings", lambda: {**real(), "core": {"on": on, "retire_missions": True, "advisors_off": advisors_off}})


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(service, "_last", {})                        # the round's own rate limits are keyed by object id: start clean
    monkeypatch.setattr(missions, "scan", lambda r: seen.append("scan") or {})
    return seen


def test_with_the_switch_on_the_round_runs_no_advisor_layer(rt, calls, monkeypatch):
    _set(monkeypatch, True)
    assert service.paid_allowed(rt)                                  # paid work IS allowed: the silence below is the switch, not the money
    out = service.round_(rt)
    assert calls == [] and not out.get("failed")


def test_with_the_switch_off_or_the_loop_off_the_advisors_run_as_before(rt, calls, monkeypatch):
    _set(monkeypatch, False)
    service.round_(rt)
    assert "scan" in calls
    calls.clear()
    _set(monkeypatch, True, on=False)                               # the loop off brings v1 back whole
    rt.settings["scheduler"] = True
    service.round_(rt)
    assert "scan" in calls


def test_the_review_and_companion_jobs_skip_while_the_switch_holds(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from pflab.service import tasks  # noqa: F401  (registers every job)
    from pflab.service.jobs import REGISTRY
    for name in ("review", "companion"):
        ok, why = REGISTRY[name].enabled_fn(None)
        assert ok is False and "retired" in why
    _set(monkeypatch, False)
    for name in ("review", "companion"):
        ok, why = REGISTRY[name].enabled_fn(SimpleNamespace(pm_dir=tmp_path))
        assert "retired" not in why                                  # switched back on, the job's own check (if it has one) decides again
