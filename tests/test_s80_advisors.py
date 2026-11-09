"""S80 phase 1: the v1 advisor layers are switched off while the close loop is on (configs/core.toml [core] advisors_off), and come back when it is not."""
from __future__ import annotations

import pytest

from pflab import core


def _set(monkeypatch, advisors_off: bool, on: bool = True):
    real = core.settings
    monkeypatch.setattr(core, "settings", lambda: {**real(), "core": {"on": on, "retire_missions": True, "advisors_off": advisors_off}})


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
