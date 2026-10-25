"""Lookahead and seal identity — Phase 2 task 2.4, CLAUDE.md non-negotiable 6.

(a) perturb every price after date T; every decision dated <= T must be
    byte-identical
(b) appending sessions after a period's end must not change the run id
"""
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from conftest import flat_index, random_walk_panel
from pflab.backtest import engine
from pflab.eval import artifacts
from pflab.eval.periods import Period, truncate_end


def _decisions_json(res, upto):
    keep = [d for d in res.decisions if d["month_end"] <= upto]
    return json.dumps(keep, sort_keys=True, default=str)


def _trades_json(res, upto):
    t = res.trades
    if len(t) == 0:
        return "[]"
    t = t[pd.to_datetime(t["date"]).dt.date <= upto]
    return t.to_json(orient="records", date_format="iso")


@pytest.mark.parametrize("scale", [1.5, 0.4])
def test_future_prices_cannot_change_past_decisions(base_config, cost_model,
                                                    tax_policy, scale):
    sessions, names, panel = random_walk_panel(seed=11, n_names=15,
                                               start="2014-01-01", end="2019-12-31")
    per = Period("t", date(2016, 1, 1), date(2019, 12, 31))
    T = date(2018, 6, 30)

    a = engine.run(base_config, per, panel, flat_index(sessions), cost_model, tax_policy)

    future = panel["date"] > T
    perturbed = panel.copy()
    for col in ("open", "high", "low", "close", "prev_close", "adj_close", "adj_open"):
        perturbed.loc[future, col] = perturbed.loc[future, col] * scale
    b = engine.run(base_config, per, perturbed, flat_index(sessions), cost_model, tax_policy)

    assert _decisions_json(a, T) == _decisions_json(b, T)
    assert _trades_json(a, T) == _trades_json(b, T)


def test_perturbing_the_future_does_change_the_future(base_config, cost_model, tax_policy):
    """Guard against a vacuous test: the perturbation must actually bite."""
    sessions, names, panel = random_walk_panel(seed=11, n_names=15,
                                               start="2014-01-01", end="2019-12-31")
    per = Period("t", date(2016, 1, 1), date(2019, 12, 31))
    T = date(2018, 6, 30)
    a = engine.run(base_config, per, panel, flat_index(sessions), cost_model, tax_policy)
    future = panel["date"] > T
    perturbed = panel.copy()
    for col in ("open", "high", "low", "close", "prev_close", "adj_close", "adj_open"):
        perturbed.loc[future, col] = perturbed.loc[future, col] * 1.5
    b = engine.run(base_config, per, perturbed, flat_index(sessions), cost_model, tax_policy)
    assert a.equity["total"].iloc[-1] != b.equity["total"].iloc[-1]


def test_truncate_end_is_what_the_engine_sees(base_config, cost_model, tax_policy):
    sessions, names, panel = random_walk_panel(seed=12, n_names=10,
                                               start="2014-01-01", end="2019-12-31")
    per = Period("t", date(2016, 1, 1), date(2017, 12, 31))
    truncated = truncate_end(panel, per)
    assert pd.to_datetime(truncated["date"]).dt.date.max() <= per.end
    r = engine.run(base_config, per, truncated, flat_index(sessions), cost_model, tax_policy)
    assert r.equity["date"].max() <= per.end


# -- seal identity ------------------------------------------------------
def test_appending_data_after_the_period_end_does_not_change_the_run_id(
        base_config, cost_model, tax_policy):
    """The sealed period is protected by the loader, not by discipline
    (principle 2). Data the engine never saw cannot move the run id."""
    # One generated panel; "short" is the prefix a run would have had if the
    # later sessions did not exist yet. Generating twice at different lengths
    # would draw different prices and test nothing.
    sessions, names, long_panel = random_walk_panel(seed=13, n_names=10,
                                                    start="2014-01-01", end="2021-12-31")
    short = long_panel[long_panel["date"] <= date(2017, 12, 31)]
    per = Period("t", date(2016, 1, 1), date(2017, 12, 31))

    a = truncate_end(short, per)
    b = truncate_end(long_panel, per)
    fa = artifacts.data_fingerprint(a)
    fb = artifacts.data_fingerprint(b)
    assert fa == fb, "truncated panels differ, so the seal leaks into the id"

    cfg = json.dumps(base_config, sort_keys=True)
    assert (artifacts.run_id(cfg, fa, "abc123", per.name)
            == artifacts.run_id(cfg, fb, "abc123", per.name))


def test_fingerprint_is_content_not_shape(base_config):
    """Two panels of identical shape but different prices must not collide."""
    _, _, a = random_walk_panel(seed=20, n_names=6, start="2016-01-01", end="2017-12-31")
    _, _, b = random_walk_panel(seed=21, n_names=6, start="2016-01-01", end="2017-12-31")
    assert len(a) == len(b)
    assert artifacts.data_fingerprint(a) != artifacts.data_fingerprint(b)


def test_run_id_changes_when_anything_real_changes(base_config):
    cfg = json.dumps(base_config, sort_keys=True)
    base = artifacts.run_id(cfg, "data", "commit", "development")
    assert base != artifacts.run_id(cfg + " ", "data", "commit", "development")
    assert base != artifacts.run_id(cfg, "data2", "commit", "development")
    assert base != artifacts.run_id(cfg, "data", "commit2", "development")
    assert base != artifacts.run_id(cfg, "data", "commit", "validation")


def test_results_are_identical_on_a_truncated_and_an_over_long_panel(
        base_config, cost_model, tax_policy):
    sessions, names, long_panel = random_walk_panel(seed=14, n_names=10,
                                                    start="2014-01-01", end="2021-12-31")
    short = long_panel[long_panel["date"] <= date(2017, 12, 31)]
    per = Period("t", date(2016, 1, 1), date(2017, 12, 31))
    a = engine.run(base_config, per, truncate_end(short, per),
                   flat_index(sessions), cost_model, tax_policy)
    b = engine.run(base_config, per, truncate_end(long_panel, per),
                   flat_index(sessions), cost_model, tax_policy)
    pd.testing.assert_frame_equal(a.equity, b.equity)
