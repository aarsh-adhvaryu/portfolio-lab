"""S67 local: the first real launch of a NEW empty profile (found live on 2026-10-30): the jobs that need holdings, a broker account or his targets
must wait and say so, not fail with KeyError / LookupError. Synthetic; no network."""
from __future__ import annotations

from datetime import datetime

import pytest

from pflab import activation
from pflab.kg import build as kb
from pflab.pm import fresh, store
from pflab.service import jobs, runner
import pflab.service.tasks  # noqa: F401  (registers the jobs)

NOW = datetime(2026, 10, 30, 10, 35)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path / "pm"))
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "data"))
    fresh.new_profile(tmp_path / "pm", None, "scratch")
    activation.activate(tmp_path / "pm", via="icon")
    con = store.connect(tmp_path / "pm" / "ledger.duckdb")
    return runner.make_ctx(con=con, now=NOW)


def test_the_universe_of_an_empty_profile_has_its_columns(ctx):
    u = kb.universe(ctx.con, [])
    assert u.empty and {"isin", "symbol", "name", "sector", "scrip", "aliases"} <= set(u.columns)
    assert u[u["isin"].astype(str).str.startswith("INE")].empty                      # what researcher and forecast do first


def test_a_profile_with_no_broker_account_waits_instead_of_failing(ctx):
    out = jobs.REGISTRY["tradecheck"].fn(ctx)
    assert out["skipped"] and "Use these accounts" in out["why"]
    assert jobs.run_job(ctx, jobs.REGISTRY["tradecheck"]).status in ("skipped", "failed")   # (no Kite login here: disabled) never an exception


def test_targets_not_set_is_waiting_for_him_not_a_failure(ctx, monkeypatch):
    from pflab.plan import targets as tg

    def not_set(*a, **k):
        raise tg.TargetsNotSet("no targets are set")
    monkeypatch.setattr(tg, "load", not_set)
    out = jobs.REGISTRY["companion"].fn(ctx)
    assert out["skipped"] and "not set" in out["why"]
