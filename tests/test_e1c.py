"""E1c — the momentum fund's construction through this engine (§3, §5).

All synthetic. Nothing here runs E1c on real data: the charter is DRAFT and
locks at its first development run, which is Aarsh's to start.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from conftest import flat_index, random_walk_panel
from pflab.backtest import engine
from pflab.eval import sweep as S
from pflab.eval.periods import Period
from pflab.portfolio.construct import (UndefinedWeight, buy_list_weighted,
                                       score_tilted_weights)
from pflab.signals.vol_scaled import vol_scaled_score_panel


# -- §3 the score -------------------------------------------------------
def _wide(seed=5, n=40, start="2010-01-01", end="2018-12-31"):
    sessions, names, panel = random_walk_panel(seed=seed, n_names=n,
                                               start=start, end=end)
    return panel.pivot_table(index="date", columns="isin", values="adj_close",
                             aggfunc="last")


def test_score_is_clipped_and_standardised():
    z = vol_scaled_score_panel(_wide())
    v = z.stack().dropna()
    assert len(v)
    assert v.max() <= 3.0 + 1e-12 and v.min() >= -3.0 - 1e-12
    # cross-sectional, so each date's own spread is standardised
    row = z.dropna(how="all").iloc[-1].dropna()
    assert abs(float(row.mean())) < 0.5      # centred, before clipping bites


def test_score_uses_no_future_data():
    """The whole panel and a truncated panel must agree wherever both are
    defined: every term is a backward shift or a rolling window ending at
    t-skip."""
    full = _wide(end="2018-12-31")
    cut = full.loc[full.index <= date(2016, 6, 30)]
    a = vol_scaled_score_panel(full).loc[cut.index]
    b = vol_scaled_score_panel(cut)
    pd.testing.assert_frame_equal(a, b)


def test_score_skips_the_most_recent_month():
    """Moving only the last 21 sessions cannot change a score dated before
    them -- that is what the skip is for."""
    full = _wide()
    bumped = full.copy()
    bumped.iloc[-10:] = bumped.iloc[-10:] * 1.5
    a = vol_scaled_score_panel(full).iloc[-1]
    b = vol_scaled_score_panel(bumped).iloc[-1]
    pd.testing.assert_series_equal(a, b)


# -- §3 the weights -----------------------------------------------------
def test_weights_sum_to_one_and_respect_the_cap():
    w = score_tilted_weights({f"n{i}": 1.0 + i for i in range(30)}, cap=0.05)
    assert abs(sum(w.values()) - 1.0) < 1e-12
    assert max(w.values()) <= 0.05 + 1e-12
    assert min(w.values()) > 0


def test_the_cap_redistributes_rather_than_truncates():
    w = score_tilted_weights({"a": 3.0, "b": 1.0, "c": 1.0, "d": 1.0, "e": 1.0},
                             cap=0.30)
    assert abs(sum(w.values()) - 1.0) < 1e-12
    assert abs(w["a"] - 0.30) < 1e-12
    # the excess went to the others in proportion to their own scores
    assert all(abs(w[k] - 0.175) < 1e-12 for k in "bcde")


def test_a_non_positive_score_gets_zero_weight():
    """§3 as amended after lock, 2026-09-21: weights proportional to
    max(score, 0). A non-positive name gets nothing; the rest share 100%."""
    s = {f"n{i}": 1.0 + 0.1 * i for i in range(30)}
    s["n0"], s["n1"] = -0.5, 0.0
    w = score_tilted_weights(s, cap=0.05)
    assert w["n0"] == 0.0 and w["n1"] == 0.0
    assert abs(sum(w.values()) - 1.0) < 1e-12
    assert max(w.values()) <= 0.05 + 1e-12


def test_the_halt_is_kept_only_when_nothing_is_positive():
    """The one case the amendment leaves undefined: no positive score at all."""
    with pytest.raises(UndefinedWeight, match="none of"):
        score_tilted_weights({f"n{i}": -0.1 * (i + 1) for i in range(30)})
    # NSE's normalisation stays unadopted but present
    w = score_tilted_weights({"a": -0.5, "b": 1.0, "c": 2.0}, cap=0.9,
                             on_negative="nse_normalised")
    assert abs(sum(w.values()) - 1.0) < 1e-12 and w["a"] > 0


def test_uncapped_names_stay_proportional_to_their_scores():
    """Water-filling: names at the cap are fixed and the rest keep their
    score ratios exactly."""
    s = {f"n{i}": float(i + 1) for i in range(30)}
    w = score_tilted_weights(s, cap=0.05)
    free = [n for n in w if w[n] < 0.05 - 1e-12]
    assert len(free) >= 2
    a, b = free[0], free[-1]
    assert abs(w[a] / w[b] - s[a] / s[b]) < 1e-9


def test_too_few_positive_names_leaves_the_rest_in_cash():
    """With fewer positive names than 1/cap, each sits at the cap and the
    remainder is not invented a home: it stays uninvested."""
    w = score_tilted_weights({"a": 1.0, "b": 2.0, "c": -1.0}, cap=0.05)
    assert w["a"] == 0.05 and w["b"] == 0.05 and w["c"] == 0.0
    assert abs(sum(w.values()) - 0.10) < 1e-12


def test_weighted_buys_chase_the_largest_shortfall_against_target():
    tw = {"a": 0.5, "b": 0.3, "c": 0.2}
    px = {"a": 100.0, "b": 100.0, "c": 100.0}
    # 'a' is already at its target; the money should go to b and c
    orders = buy_list_weighted(tw, {"a": 5000.0}, 5000.0, px, max_names=2)
    assert {n for n, _ in orders} == {"b", "c"}


# -- §3 through the engine ----------------------------------------------
@pytest.fixture
def e1c_config(base_config):
    return {**base_config,
            "strategy": {**base_config["strategy"],
                         "signal": "vol_scaled_6_12",
                         "rebalance": "semiannual",
                         "rebalance_months": [6, 12],
                         "selection_n": 10,
                         "weighting": "score_tilted",
                         "weight_cap": 0.25,
                         "trend_filter": "off"}}


def _run(cfg, cost_model, tax_policy, seed=61, n=40):
    sessions, names, panel = random_walk_panel(seed=seed, n_names=n,
                                               start="2010-01-01", end="2018-12-31")
    per = Period("t", date(2013, 1, 1), date(2018, 12, 31))
    return engine.run(cfg, per, panel, flat_index(sessions), cost_model, tax_policy)


def test_sells_happen_only_at_a_rebalance(e1c_config, cost_model, tax_policy):
    """§3: "Sells: at rebalance only. No band, no trend filter, no
    intra-month exits.\""""
    r = _run(e1c_config, cost_model, tax_policy)
    rebal = {d["month_end"] for d in r.decisions if d.get("rebalance")}
    assert rebal, "no rebalance ever happened"
    assert all(d.month in (6, 12) for d in rebal)
    for d in r.decisions:
        if not d.get("rebalance"):
            assert d["exits"] == [], f"{d['month_end']} sold outside a rebalance"


def test_between_rebalances_only_shortfall_buys(e1c_config, cost_model, tax_policy):
    r = _run(e1c_config, cost_model, tax_policy)
    non = [d for d in r.decisions if not d.get("rebalance")]
    assert non
    assert all(d["entries"] == [] for d in non)
    # but the targets carry over, so the SIP still has somewhere to go
    assert any(d["target_weights"] for d in non)


def test_there_is_one_lag_not_two(e1c_config, cost_model, tax_policy):
    """§3 as amended 2026-09-19: the score's skip of the most recent month IS
    the lag, so the score date is the rebalance month-end itself."""
    r = _run(e1c_config, cost_model, tax_policy)
    rebal = [d for d in r.decisions if d.get("rebalance")]
    assert rebal
    for d in rebal:
        assert d["score_date"] == d["month_end"]


def test_a_lag_when_asked_for_counts_month_ends_not_days(e1c_config, cost_model,
                                                         tax_policy):
    """§3 keeps "counted in month-end positions, never calendar days".

    One calendar month back from a month-end lands mid-month, BEFORE that
    month's own month-end session, so a date-based lag would silently skip a
    whole month. Counting positions cannot drift.
    """
    cfg = {**e1c_config,
           "strategy": {**e1c_config["strategy"], "score_lag_months": 1}}
    r = _run(cfg, cost_model, tax_policy)
    rebal = [d for d in r.decisions if d.get("rebalance")]
    assert rebal
    for d in rebal:
        assert d["score_date"] < d["month_end"]
        # exactly one month-end back, so never two months of distance
        assert (d["month_end"] - d["score_date"]).days <= 40


def test_it_holds_about_the_selected_number(e1c_config, cost_model, tax_policy):
    r = _run(e1c_config, cost_model, tax_policy)
    for d in r.decisions:
        if d.get("rebalance") and d["target_weights"]:
            assert len(d["target_weights"]) <= 10


def test_equal_weighting_is_the_s1_row(e1c_config, cost_model, tax_policy):
    cfg = {**e1c_config,
           "strategy": {**e1c_config["strategy"], "weighting": "equal"}}
    r = _run(cfg, cost_model, tax_policy)
    for d in r.decisions:
        tw = d.get("target_weights") or {}
        if d.get("rebalance") and tw:
            assert len(set(round(v, 12) for v in tw.values())) == 1


def test_unknown_settings_are_errors_not_silent_defaults(base_config, cost_model,
                                                         tax_policy):
    for key, bad in (("signal", "ema"), ("rebalance", "weekly"),
                     ("weighting", "cap_weighted")):
        cfg = {**base_config, "strategy": {**base_config["strategy"], key: bad}}
        if key == "weighting":
            cfg["strategy"]["rebalance"] = "semiannual"
        with pytest.raises(ValueError, match=key):
            _run(cfg, cost_model, tax_policy, n=20)


# -- §5 the sweep -------------------------------------------------------
def test_e1c_has_twelve_rows_plus_base():
    """Eleven at the draft, plus S12 added by the 2026-09-19 amendment."""
    rows = S.e1c_rows()
    assert list(rows)[0] == "base"
    assert len(rows) == 13
    assert [r for r in rows if r != "base"] == [f"S{i}" for i in range(1, 13)]


def test_s12_is_nses_standardisation_order():
    """§5 S12: z-score each window, then average. The charter's own order
    (average, then z-score) stays the base row."""
    w = _wide()
    a = vol_scaled_score_panel(w)                              # charter order
    b = vol_scaled_score_panel(w, order="z_then_average")      # NSE order
    assert not a.equals(b), "the two orders produced identical scores"
    for f in (a, b):
        v = f.stack().dropna()
        assert v.max() <= 3.0 + 1e-12 and v.min() >= -3.0 - 1e-12
    assert S.e1c_rows()["S12"] == {"strategy.score_order": "z_then_average"}


def test_an_unknown_score_order_is_an_error():
    with pytest.raises(ValueError, match="order"):
        vol_scaled_score_panel(_wide(), order="rank_then_average")


def test_s11_shortens_the_window_like_e1b_s13():
    per = Period("dev", date(2007, 1, 1), date(2016, 12, 31))
    p = S.period_for_row(per, "S11", S.e1c_rows())
    assert p is not per and p.start == date(2012, 1, 1)
    # and the E1c table must be used: E1b's S11 is a universe row, not a
    # window row, so the wrong table would silently leave the window alone
    assert S.period_for_row(per, "S11", S.e1b_rows()) is per


def test_s4_changes_the_cadence_without_changing_the_weighting(
        e1c_config, cost_model, tax_policy):
    """§5 S4 puts E1's monthly band back on the fund's score.

    §5 says each row "isolates one of E1's departures". If S4 also dropped
    the fund's score-tilted weights for equal ones it would be changing two
    things at once, and whatever it measured could not be attributed to the
    cadence.
    """
    cfg = {**e1c_config,
           "strategy": {**e1c_config["strategy"],
                        "rebalance": "monthly_band",
                        "n_hold": 30, "band_exit_rank": 60}}
    r = _run(cfg, cost_model, tax_policy)
    weighted = [d for d in r.decisions if d.get("target_weights")]
    assert weighted, "S4 lost the fund's weighting"
    for d in weighted:
        tw = d["target_weights"]
        assert abs(sum(tw.values()) - 1.0) < 1e-9
        # score-tilted, so not every name carries the same weight
        assert max(tw.values()) <= e1c_config["strategy"]["weight_cap"] + 1e-12
    assert any(len(set(round(v, 12) for v in d["target_weights"].values())) > 1
               for d in weighted), "weights are flat: the tilt was lost"


def test_e1_and_e1b_never_get_target_weights(base_config, cost_model, tax_policy):
    """The weighting branch must be unreachable for an equal-weight config,
    or E1's §5 equal-weight target would have quietly changed."""
    r = _run(base_config, cost_model, tax_policy)
    assert all("target_weights" not in d for d in r.decisions)


def test_an_undefined_weight_stops_the_whole_sweep(e1c_config, cost_model,
                                                   tax_policy, tmp_path,
                                                   monkeypatch):
    """A selection with nothing positive in it STOPS the run.

    Under standardisation within the universe the top name's z-score is
    positive by construction, so the case cannot be produced from real
    scores; the weight function is made to report it instead. What is tested
    is the plumbing: the sweep must not record it as one halted row and carry
    on, and the message must say when.
    """
    import pflab.portfolio.construct as K

    def _nothing_positive(scores, cap=0.05, on_negative="zero"):
        raise K.UndefinedWeight("none of 30 selected names has a positive score")

    monkeypatch.setattr(K, "score_tilted_weights", _nothing_positive)
    sessions, names, panel = random_walk_panel(seed=88, n_names=40,
                                               start="2010-01-01", end="2018-12-31")
    per = Period("t", date(2013, 1, 1), date(2018, 12, 31))
    idx = {"NIFTY50_PRICE": flat_index(sessions)}
    with pytest.raises(UndefinedWeight) as e:
        S.run_sweep(e1c_config, per, panel, idx, lambda m: cost_model.scaled(m),
                    tax_policy, out_dir=tmp_path, rows=["base", "S1"],
                    table=S.e1c_rows())
    assert "month-end" in str(e.value), "the halt must say WHEN"
    assert not (tmp_path / "summary.md").exists()


def test_scores_are_standardised_within_the_universe(e1c_config, cost_model,
                                                     tax_policy):
    """E1c §3: "standardised across the universe".

    Adding names that are NOT in the universe -- priced below §2's Rs 10
    floor, with wild momentum -- must not move a single weight. The first
    implementation standardised across the whole panel, so such names
    shifted every z-score: the bug declared in §9 on 2026-09-21.
    """
    import numpy as np
    from conftest import make_panel
    sessions, names, panel = random_walk_panel(seed=61, n_names=40,
                                               start="2010-01-01", end="2018-12-31")
    rng = np.random.default_rng(7)
    extra_names = [f"INE9{i:02d}X01011" for i in range(25)]
    extra = make_panel(sessions, extra_names,
                       {n: (3.0 * np.exp(np.cumsum(rng.normal(0.002, 0.04,
                                                              len(sessions)))))
                        .clip(max=9.0) for n in extra_names})
    per = Period("t", date(2013, 1, 1), date(2018, 12, 31))
    a = engine.run(e1c_config, per, panel, flat_index(sessions), cost_model,
                   tax_policy)
    b = engine.run(e1c_config, per, pd.concat([panel, extra], ignore_index=True),
                   flat_index(sessions), cost_model, tax_policy)
    wa = [d.get("target_weights") for d in a.decisions if d.get("rebalance")]
    wb = [d.get("target_weights") for d in b.decisions if d.get("rebalance")]
    assert wa and wa == wb
    pd.testing.assert_frame_equal(a.trades, b.trades)


def test_s6_is_z_scored_raw_momentum():
    """§5 S6 as amended: raw 12-1 momentum through §3's z-score and clip."""
    from pflab.signals.vol_scaled import momentum_ratios, standardise
    w = _wide()
    d = w.index[-1]
    z = standardise([p.loc[d] for p in momentum_ratios(w)])
    assert abs(float(z.mean())) < 0.2 and z.max() <= 3.0 and (z > 0).any()
    assert S.e1c_rows()["S6"] == {"strategy.signal": "mom_12_1_z"}


def test_a_benchmark_ignores_the_experiments_stock_picking(base_config, e1c_config,
                                                           cost_model, tax_policy):
    """A benchmark shares the experiment's money (SIP, cash, delisting) and
    nothing about how it picks stocks.

    Found 2026-09-21: run_benchmark copied the experiment's strategy and
    patched E1's knobs, so under E1c's config it ran E1c's rules on one
    security -- whose z-score is undefined -- and never bought. Every
    benchmark read the cash rate.
    """
    sessions, _, _ = random_walk_panel(seed=3, n_names=2,
                                       start="2014-01-01", end="2018-12-31")
    # a realistic index level: near 100, a buy sized to all the cash plus its
    # costs no longer fits, and the engine (rightly) skips it
    idx = pd.DataFrame({"date": sessions,
                        "close": 10000 * (1.0003 ** np.arange(len(sessions)))})
    per = Period("t", date(2016, 1, 1), date(2018, 12, 31))
    a = engine.run_benchmark(base_config, per, idx, cost_model, tax_policy, name="X")
    b = engine.run_benchmark(e1c_config, per, idx, cost_model, tax_policy, name="X")
    assert (b.trades["side"] == "BUY").sum() > 0, "the benchmark never invested"
    pd.testing.assert_frame_equal(a.equity, b.equity)
    pd.testing.assert_frame_equal(a.trades, b.trades)


def test_the_short_window_companion_runs_the_stack(base_config, e1c_config,
                                                   cost_model, tax_policy, tmp_path):
    """S11's comparison is "E1 base re-run on that window": the STACK's
    config, not the experiment's with its universe switched."""
    sessions, names, panel = random_walk_panel(seed=62, n_names=40,
                                               start="2009-01-01", end="2016-12-31")
    per = Period("dev", date(2011, 1, 1), date(2016, 12, 31))
    idx = {"NIFTY50_PRICE": flat_index(sessions)}
    kw = dict(out_dir=None, rows=["S11"], table=S.e1c_rows())
    out = S.run_sweep(e1c_config, per, panel, idx, lambda m: cost_model.scaled(m),
                      tax_policy, stack_config=base_config, **kw)
    got = out["_S11_stack"]["metrics"]["paths"]["nav_liq"]["cagr"]
    p12 = S.period_for_row(per, "S11", S.e1c_rows())
    want = engine.run(base_config, p12, panel, flat_index(sessions),
                      cost_model.scaled(1.0), tax_policy)
    from pflab.eval import artifacts
    assert got == artifacts.metrics_of(want)["paths"]["nav_liq"]["cagr"]
