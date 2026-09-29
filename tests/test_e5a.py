"""E5-A (docs/strategies/E5-A.md): the A0 build.

The three mandatory lookahead tests come first:
  * a label that becomes observable after R cannot change the model fitted at R;
  * a price after M cannot change M's features;
  * two fits on the same inputs give identical model bytes.
Then the label mechanics (§4), the fallback (§5), the engine's precomputed
signal (§7), the sweep rows (§9), the verdict (§10) and the run identity.
Everything is synthetic; nothing reads PFLAB_DATA_DIR.
"""
import copy
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from conftest import flat_index, make_panel, random_walk_panel
from pflab import _toml
from pflab.backtest import engine
from pflab.eval import artifacts, classify, sweep as S
from pflab.eval.periods import Period, load_periods, truncate_end
from pflab.ranker import features as ft, labels as lb, model as mdl, store, walk
from pflab.signals.momentum import momentum_panel
from pflab.signals.vol_scaled import standardise, vol_scaled_ratios

SMALL = {"num_leaves": 4, "min_data_in_leaf": 5, "learning_rate": 0.1}


def _cfg(base_config):
    cfg = copy.deepcopy(base_config)
    cfg["strategy"].update({"signal": "precomputed", "fallback_signal": "vol_scaled_6_12",
                            "score_windows": [126, 252], "score_order": "average_then_z",
                            "delist_confirm_sessions": 250})
    cfg["e5a"] = {"family": "A0", "features": list(ft.A0_FEATURES),
                  "horizons": [1, 3, 12], "refit": "annual", "refit_month": 12,
                  "min_cross_sections": 12, "seed": mdl.SEED, "num_threads": 1,
                  "fixed": {"num_iterations": 20, "bagging_fraction": 0.8,
                            "bagging_freq": 1, "feature_fraction": 0.8},
                  "params": dict(SMALL)}
    return cfg


@pytest.fixture(scope="module")
def world():
    sessions, names, panel = random_walk_panel(seed=5, n_names=30, start="2011-01-01",
                                               end="2018-12-31", tick=0.05)
    base = {"strategy": {"lookback_sessions": 252, "skip_sessions": 21, "n_hold": 10,
                         "band_exit_rank": 20, "max_buys_per_month": 6,
                         "sip_amount": 50_000.0, "initial_cash": 0.0,
                         "cash_rate_annual": 0.06, "trend_filter": "sma10",
                         "delisting": "last_close"},
            "universe": {"series": ["EQ"], "min_sessions": 250, "top_n_by_turnover": 500,
                         "turnover_window": 126, "min_price": 10.0,
                         "max_adv_fraction": 0.01},
            "costs": {"multiplier": 1.0}}
    cfg = _cfg(base)
    uni = ft.universe_by_month(panel, cfg)
    feats = ft.a0_features(panel, cfg, uni)
    labels = lb.build_labels(panel, cfg, uni)
    return {"sessions": sessions, "panel": panel, "cfg": cfg, "base": base,
            "uni": uni, "feats": feats, "labels": labels, "fw": ft.to_wide(feats)}


def _dec_end(world, year):
    return max(m for m in world["uni"] if m.year == year and m.month == 12)


def _fit(world, labels, R, h=1):
    spec = walk.spec_from_config(world["cfg"])
    return mdl.fit(world["fw"], labels, h, R, spec.params, spec.features, 12)


# -- the three mandatory tests -------------------------------------------
@pytest.mark.parametrize("h", [1, 3, 12])
def test_a_label_observable_after_R_cannot_change_the_model_fitted_at_R(world, h):
    R = _dec_end(world, 2016)
    L = world["labels"]
    a = _fit(world, L, R, h)
    assert a.fitted, a.reason
    late = np.array([not (t is not None and t <= R) for t in L["target_observable_at"]])
    assert late.sum() > 0
    L2 = L.copy()
    rng = np.random.default_rng(0)
    L2.loc[late, "target"] = rng.uniform(-0.5, 0.5, int(late.sum()))
    L2.loc[late, "ret"] = rng.normal(0, 1, int(late.sum()))
    b = _fit(world, L2, R, h)
    assert b.text == a.text and b.sha256 == a.sha256


def test_the_purge_is_not_vacuous(world):
    """Changing a label observable BY R does change the model."""
    R = _dec_end(world, 2016)
    L = world["labels"]
    a = _fit(world, L, R)
    early = np.array([t is not None and t <= R for t in L["target_observable_at"]])
    early &= (L["h"] == 1).to_numpy() & L["target"].notna().to_numpy()
    L2 = L.copy()
    L2.loc[early, "target"] = -L2.loc[early, "target"]
    assert _fit(world, L2, R).text != a.text


def test_a_price_after_M_cannot_change_Ms_features(world):
    panel, cfg = world["panel"], world["cfg"]
    M = max(m for m in world["uni"] if m <= date(2016, 6, 30))
    pert = panel.copy()
    fut = pd.to_datetime(pert["date"]).dt.date > M
    for col in ("open", "high", "low", "close", "prev_close", "adj_close", "adj_open"):
        pert.loc[fut, col] = pert.loc[fut, col] * 1.5
    pert.loc[fut, "turnover"] = pert.loc[fut, "turnover"] * 3.0
    fb = ft.a0_features(pert, cfg, ft.universe_by_month(pert, cfg))
    fa = world["feats"]
    a, b = fa[fa["month_end"] <= M], fb[fb["month_end"] <= M]
    assert artifacts.frame_sha(a) == artifacts.frame_sha(b)
    assert a.to_json(date_format="iso") == b.to_json(date_format="iso")
    # and the perturbation bites after M
    assert artifacts.frame_sha(fa[fa["month_end"] > M]) != \
        artifacts.frame_sha(fb[fb["month_end"] > M])


def test_two_fits_on_the_same_inputs_give_identical_model_bytes(world):
    R = _dec_end(world, 2017)
    for h in (1, 3, 12):
        a, b = _fit(world, world["labels"], R, h), _fit(world, world["labels"], R, h)
        assert a.fitted and a.text == b.text and a.sha256 == b.sha256


# -- labels (§4) ----------------------------------------------------------
def test_labels_on_a_truncated_panel_agree_where_observable(world):
    """A label observable by T is the same whether or not later data exists."""
    panel, cfg = world["panel"], world["cfg"]
    T = date(2016, 6, 30)
    tp = truncate_end(panel, Period("t", date(2012, 1, 1), T))
    Lt = lb.build_labels(tp, cfg, ft.universe_by_month(tp, cfg))
    Lf = world["labels"]
    cols = ["isin", "month_end", "h", "kind", "label_end", "observable_at", "ret",
            "target", "target_observable_at"]

    def sel(L):
        ok = [t is not None and t <= T for t in L["target_observable_at"]]
        return L.loc[ok, cols].reset_index(drop=True)
    a, b = sel(Lt), sel(Lf)
    assert len(a) > 1000
    pd.testing.assert_frame_equal(a, b)


def test_label_mechanics_dividends_write_down_resume_and_no_entry():
    sessions = list(pd.bdate_range("2015-01-01", "2016-12-31").date)
    k = len(sessions)
    names = ["INE000A01010", "INE000B01010", "INE000C01010", "INE000D01010"]
    px = {n: 100.0 * (1.0 + 0.001 * (j + 1)) ** np.arange(k) for j, n in enumerate(names)}
    mes = sorted(engine._month_ends(sessions))
    M = max(m for m in mes if m <= date(2015, 6, 30))
    s0 = sessions.index(M) + 1
    E = sessions.index(mes[mes.index(M) + 1]) + 1
    A, B, C, D = names
    divs = {(A, sessions[s0]): 5.0, (A, sessions[s0 + 3]): 2.0, (A, sessions[E]): 1.0}
    panel = make_panel(sessions, names, px, dividend=divs)
    drop = ((panel["isin"] == B) & (panel["date"] > sessions[s0 + 2])) | \
           ((panel["isin"] == C) & panel["date"].isin(sessions[E:E + 3])) | \
           ((panel["isin"] == D) & (panel["date"] == sessions[s0]))
    panel = panel[~drop].reset_index(drop=True)
    cfg = {"strategy": {"delist_confirm_sessions": 5},
           "universe": {"series": ["EQ"], "min_sessions": 20, "top_n_by_turnover": 500,
                        "turnover_window": 126, "min_price": 10.0}}
    uni = ft.universe_by_month(panel, cfg)
    assert set(uni[M]) == set(names)
    L = lb.build_labels(panel, cfg, uni, horizons=(1,))
    r = L[L["month_end"] == M].set_index("isin")

    assert r.at[A, "kind"] == "open" and r.at[A, "label_end"] == sessions[E]
    # the dividend going ex AT the buy session is not received; E's is
    assert r.at[A, "ret"] == pytest.approx((px[A][E] + 2.0 + 1.0) / px[A][s0] - 1.0)
    # rows stop two sessions after the buy: written down on the 5th missing
    assert r.at[B, "kind"] == "write_down"
    assert r.at[B, "label_end"] == sessions[s0 + 2 + 5]
    assert r.at[B, "ret"] == pytest.approx(-1.0)
    # no row at the exit session: sold at the first open it trades again
    assert r.at[C, "kind"] == "resumed" and r.at[C, "label_end"] == sessions[E + 3]
    assert r.at[C, "ret"] == pytest.approx(px[C][E + 3] / px[C][s0] - 1.0)
    # no open at the session after M: the engine could not have bought it
    assert r.at[D, "kind"] == "no_entry" and np.isnan(r.at[D, "ret"])
    assert r.at[D, "observable_at"] == sessions[s0]
    # percentile over the three defined labels, centred at 0; B is last
    assert r.at[B, "target"] == pytest.approx(1 / 6 - 0.5)
    assert r[["target"]].dropna().shape[0] == 3
    assert set(r["target_observable_at"]) == {sessions[E + 3]}
    for c in ("label_start",):
        assert r.at[A, c] == sessions[s0]


def test_a_cross_section_with_a_pending_label_has_no_target(world):
    L = world["labels"]
    last = max(world["uni"])
    tail = L[(L["month_end"] == last)]
    assert (tail["kind"] == "pending").all()
    assert tail["target"].isna().all() and not tail["xs_complete"].any()


def test_the_selector_takes_only_targets_observable_by_R(world):
    R = _dec_end(world, 2015)
    rows = mdl.training_rows(world["labels"], 3, R)
    assert len(rows) and all(t <= R for t in rows["target_observable_at"])
    assert all(o <= R for o in rows["observable_at"])
    assert rows["month_end"].max() < R


# -- features (§6) --------------------------------------------------------
def test_missing_is_not_zero_and_a_name_without_a_row_publishes_nothing(world):
    panel, cfg = world["panel"], world["cfg"]
    M = max(m for m in world["uni"] if m <= date(2015, 3, 31))
    victim = world["uni"][M][0]
    p2 = panel[~((panel["isin"] == victim) & (panel["date"] == M))]
    f = ft.a0_features(p2, cfg, ft.universe_by_month(p2, cfg))
    got = f[(f["month_end"] == M) & (f["isin"] == victim)]
    assert len(got) == len(ft.A0_FEATURES)
    assert got["value"].isna().all() and not got["available"].any()
    assert got["source_record_id"].isna().all()


def test_store_columns_and_publication_time(world):
    f = world["feats"]
    assert list(f.columns) == ft.STORE_COLUMNS
    row = f.iloc[0]
    assert row["usable_from"] == row["month_end"]
    assert row["published_at"] == pd.Timestamp(f"{row['month_end']} 15:30", tz="Asia/Kolkata")
    assert set(f["source"]) == {"panel", "stack:vol_scaled_6_12"}


def test_momentum_and_stack_score_features_are_the_stacks_own(world):
    panel, uni, fw = world["panel"], world["uni"], world["fw"]
    adj = engine._wide(panel, "adj_close")
    M = max(m for m in uni if m <= date(2016, 9, 30))
    elig = uni[M]
    parts = vol_scaled_ratios(adj, windows=(126, 252), skip=21)
    want = standardise([p.loc[M][p.columns.isin(elig)] for p in parts])
    got = fw.loc[M]["stack_score"].dropna()
    pd.testing.assert_series_equal(got.sort_index(), want.sort_index(),
                                   check_names=False)
    mom = momentum_panel(adj, 252, 21).loc[M].reindex(elig)
    np.testing.assert_array_equal(fw.loc[M]["mom_12_1"].reindex(elig).to_numpy(),
                                  mom.to_numpy())


# -- fallback (§5) and the walk-forward ------------------------------------
def test_refit_dates_annual_and_monthly(world):
    mes = sorted(world["uni"])
    spec = walk.spec_from_config(world["cfg"])
    m = max(x for x in mes if x <= date(2016, 12, 31))          # a December
    assert walk.refit_date(m, mes, spec) == _dec_end(world, 2015)
    jan = min(x for x in mes if x >= date(2017, 1, 1))
    assert walk.refit_date(jan, mes, spec) == m
    mon = walk.Spec(**{**spec.__dict__, "refit": "monthly"})
    assert walk.refit_date(jan, mes, mon) == m
    assert walk.refit_date(m, mes, mon) == max(x for x in mes if x < m)


def test_the_fallback_until_twelve_cross_sections(world):
    mes = sorted(world["uni"])
    w = walk.Walk(world["fw"], world["labels"], world["uni"], mes)
    spec = walk.spec_from_config(world["cfg"])
    months = [m for m in mes if m.year >= 2013]
    res = w.score(spec, months)
    fb = [m for m in months if res["fallback"][m]]
    ok = [m for m in months if not res["fallback"][m]]
    assert fb and ok and max(fb) < min(ok)
    # the first model month's refit has >= 12 cross-sections for every horizon
    info = res["info"][min(ok)]
    assert all(x >= 12 for _, _, _, x, _ in info["fits"])
    # and never fits when the minimum is out of reach
    never = walk.Spec(**{**spec.__dict__, "min_cross_sections": 10_000})
    assert all(w.score(never, months)["fallback"].values())


def test_the_composite_is_the_mean_of_horizon_percentiles(world):
    mes = sorted(world["uni"])
    w = walk.Walk(world["fw"], world["labels"], world["uni"], mes)
    spec = walk.spec_from_config(world["cfg"])
    m = max(mes)
    res = w.score(spec, [m])
    assert not res["fallback"][m]
    pct = [res["predictions"][(m, h)].rank(pct=True) for h in (1, 3, 12)]
    want = pd.concat(pct, axis=1).mean(axis=1).sort_index()
    pd.testing.assert_series_equal(res["scores"][m], want)


def test_spec_needs_the_tuned_point(world):
    cfg = copy.deepcopy(world["cfg"])
    del cfg["e5a"]["params"]
    with pytest.raises(ValueError, match="tuned point"):
        walk.spec_from_config(cfg)


# -- the engine's precomputed signal (§7) ----------------------------------
def _window(world):
    return Period("t", date(2015, 1, 1), date(2018, 12, 31))


def test_an_all_fallback_run_is_the_stack(world, cost_model, tax_policy):
    per = _window(world)
    cfg = world["cfg"]
    stack = copy.deepcopy(cfg)
    stack["strategy"]["signal"] = "vol_scaled_6_12"
    del stack["e5a"]
    fb = {m: True for m in world["uni"] if per.start <= m <= per.end}
    idx = flat_index(world["sessions"])
    a = engine.run(cfg, per, world["panel"], idx, cost_model, tax_policy,
                   scores={"scores": {}, "fallback": fb})
    b = engine.run(stack, per, world["panel"], idx, cost_model, tax_policy)
    assert all(d["score_source"] == "fallback" for d in a.decisions)
    strip = [{k: v for k, v in d.items() if k != "score_source"} for d in a.decisions]
    assert json.dumps(strip, default=str) == json.dumps(b.decisions, default=str)
    pd.testing.assert_frame_equal(a.trades, b.trades)


def test_precomputed_scores_drive_the_ranking(world, cost_model, tax_policy):
    per = _window(world)
    months = [m for m in world["uni"] if per.start <= m <= per.end]
    # an arbitrary fixed ranking: reverse ISIN order
    sc = {m: pd.Series(np.arange(len(world["uni"][m]), dtype=float),
                       index=world["uni"][m]) for m in months}
    res = engine.run(world["cfg"], per, world["panel"], flat_index(world["sessions"]),
                     cost_model, tax_policy,
                     scores={"scores": sc, "fallback": {m: False for m in months}})
    d0 = res.decisions[0]
    assert d0["score_source"] == "model"
    top = list(sc[d0["month_end"]].sort_values(ascending=False).index[:10])
    assert set(d0["entries"]) == set(top)


def test_a_precomputed_name_outside_the_universe_is_refused(world, cost_model, tax_policy):
    per = _window(world)
    months = [m for m in world["uni"] if per.start <= m <= per.end]
    sc = {m: pd.Series(1.0, index=list(world["uni"][m]) + ["INE999Z99999"])
          for m in months}
    with pytest.raises(ValueError, match="not in the engine's universe"):
        engine.run(world["cfg"], per, world["panel"], flat_index(world["sessions"]),
                   cost_model, tax_policy,
                   scores={"scores": sc, "fallback": {m: False for m in months}})


def test_scores_are_refused_for_any_other_signal(world, cost_model, tax_policy):
    with pytest.raises(ValueError, match="not 'precomputed'"):
        engine.run(world["base"], _window(world), world["panel"],
                   flat_index(world["sessions"]), cost_model, tax_policy,
                   scores={"scores": {}, "fallback": {}})
    with pytest.raises(ValueError, match="needs scores="):
        engine.run(world["cfg"], _window(world), world["panel"],
                   flat_index(world["sessions"]), cost_model, tax_policy)


# -- the sweep (§9) --------------------------------------------------------
def test_e5a_rows_are_section_9():
    rows = S.e5a_rows()
    assert list(rows) == ["base", "S1", "S2", "S3", "S4", "S5", "S6", "S7"]
    cfg = {"e5a": {"params": dict(SMALL), "horizons": [1, 3, 12]}, "costs": {}}
    s4 = S.apply_row(cfg, "S4", rows)["e5a"]["params"]
    assert s4 == {"num_leaves": 15, "min_data_in_leaf": 500, "learning_rate": 0.03}
    assert S.apply_row(cfg, "S1", rows)["e5a"]["horizons"] == [1]
    assert S.apply_row(cfg, "S5", rows)["e5a"]["seed"] == 20270927
    assert S.apply_row(cfg, "S6", rows)["e5a"]["refit"] == "monthly"
    assert S.apply_row(cfg, "S7", rows)["costs"]["multiplier"] == 2.0


def test_the_sweep_writes_and_hashes_every_model(world, cost_model, tax_policy, tmp_path):
    per = Period("t", date(2013, 1, 1), date(2018, 12, 31))     # 2013 falls back
    prov = walk.SweepScores(world["feats"], world["labels"], per)
    idx = {"NIFTY50_PRICE": flat_index(world["sessions"])}
    man = {"run_id": "x", "config_sha": "c", "data_fingerprint": "d", "code": "k",
           "period": "t", "rows": ["base", "S7"]}
    out = S.run_sweep(world["cfg"], per, world["panel"], idx,
                      lambda m: cost_model.scaled(m), tax_policy, out_dir=tmp_path,
                      rows=["base", "S7"], table=S.e5a_rows(), experiment="E5-A",
                      manifest=man, score_provider=prov)
    assert out["base"]["error"] is None and out["S7"]["error"] is None
    written = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    models = written["e5a"]["models"]
    assert models and written["e5a"]["lightgbm"] == mdl.lightgbm_version()
    for rel, sha in models.items():
        assert artifacts.file_sha(tmp_path / rel) == sha
    # S7 (costs x2) fits nothing of its own: same models, same scores
    assert len(prov.walk.fits) == len({(f.h, f.refit) for f in prov.walk.fits.values()})
    x = json.loads((tmp_path / "extras.json").read_text(encoding="utf-8"))["base"]["e5a"]
    assert x["decisions"] == 72 and 0 < x["fallback_decisions"] < 72
    assert "E5-A §11" in (tmp_path / "summary.md").read_text(encoding="utf-8")


# -- the store --------------------------------------------------------------
def test_store_round_trip_and_refusals(world, tmp_path):
    per = Period("t", date(2011, 1, 1), date(2018, 12, 31))
    meta = {"period": "t", "period_end": str(per.end), "panel_fingerprint": "abc",
            "identity": store.identity(world["cfg"]), "builder_sha": store.builder_sha()}
    store.write(tmp_path, world["feats"], world["labels"], meta)
    f, L, m = store.load(tmp_path)
    assert artifacts.frame_sha(f) == artifacts.frame_sha(world["feats"])
    assert list(L["label_end"]) == list(world["labels"]["label_end"])
    store.check(m, world["cfg"], per, "abc")
    with pytest.raises(store.StaleStore, match="fingerprint"):
        store.check(m, world["cfg"], per, "xyz")
    with pytest.raises(store.StaleStore, match="code has changed"):
        store.check({**m, "builder_sha": "0" * 64}, world["cfg"], per, "abc")
    other = copy.deepcopy(world["cfg"])
    other["universe"]["top_n_by_turnover"] = 200
    with pytest.raises(store.StaleStore, match="universe"):
        store.check(m, other, per, "abc")
    (tmp_path / store.LABELS).write_bytes(b"tampered")
    with pytest.raises(store.StaleStore):
        store.load(tmp_path)


# -- the verdict (§10) --------------------------------------------------------
def _crit(cagr, dd, rows=None, turnover=1.0):
    base = {"cagr": cagr, "max_drawdown": dd, "turnover_annual": turnover, "error": None}
    r = {"base": base}
    for k, v in (rows or {}).items():
        r[k] = {"cagr": v, "max_drawdown": dd, "turnover_annual": turnover, "error": None}
    return {"rows": r, "benchmarks": {"B2": {"cagr": 0.10, "max_drawdown": -0.3},
                                      "B5": {"cagr": 0.12, "max_drawdown": -0.3}}}


def _sweep(d, crit, period):
    d.mkdir(parents=True)
    (d / "criteria.json").write_text(json.dumps(crit), encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps({"period": period}), encoding="utf-8")
    return d


def test_classify_e5a_a0_and_the_exploratory_guard(tmp_path):
    rows = {f"S{i}": 0.16 for i in range(1, 8)}
    c_dev = _sweep(tmp_path / "cd", _crit(0.16, -0.3, rows), "e5a_development")
    c_val = _sweep(tmp_path / "cv", _crit(0.16, -0.3, rows), "validation")
    s_dev = _sweep(tmp_path / "sd", _crit(0.14, -0.3), "e5a_development")
    s_val = _sweep(tmp_path / "sv", _crit(0.14, -0.3), "validation")
    out = classify.classify_e5a(c_dev, c_val, s_dev, s_val)
    assert out["verdict"] == "ADOPT" and out["gate"]["stack"] == "E1 + E1d"
    assert "mandate" in out and "charter_c1_c4" not in out
    ex = _sweep(tmp_path / "ex", _crit(0.16, -0.3, rows), "e5a_exploratory")
    with pytest.raises(ValueError, match="never counted"):
        classify.classify_e5a(ex, c_val, s_dev, s_val)


def test_a_family_is_compared_row_by_row_with_a0(tmp_path):
    a0 = {f"S{i}": 0.14 for i in range(1, 8)}
    a0["S4"] = 0.20                          # A0's S4 is strong ...
    fam = {f"S{i}": 0.16 for i in range(1, 8)}
    fam["S4"] = 0.16                         # ... so the family's S4 loses to it
    mk = lambda n, c, r, p: _sweep(tmp_path / n, _crit(c, -0.3, r), p)
    out = classify.classify_e5a(
        mk("fd", 0.16, fam, "e5a_development"), mk("fv", 0.16, fam, "validation"),
        mk("sd", 0.14, None, "e5a_development"), mk("sv", 0.14, None, "validation"),
        a0_dev_dir=mk("ad", 0.14, a0, "e5a_development"),
        a0_val_dir=mk("av", 0.14, a0, "validation"), candidate="A3")
    inc = out["incremental"]["development"]
    assert inc["rows"]["S4"]["holds"] is False and inc["rows"]["S1"]["holds"] is True
    assert out["incremental"]["verdict"] == "ADOPT"          # 7 of 8 >= 2/3
    assert out["joins_stack"] is True and out["family_evidence"] == "ADOPT"


# -- run identity, periods, config ---------------------------------------------
def test_periods_and_config_follow_the_charter():
    p = load_periods("configs/evaluation_periods.toml")
    assert (p["e5a_exploratory"].start, p["e5a_exploratory"].end) == \
        (date(2007, 1, 1), date(2010, 12, 31))
    assert (p["e5a_development"].start, p["e5a_development"].end) == \
        (date(2011, 1, 1), date(2016, 12, 31))
    a, d = _toml.load("configs/e5a_a0.toml"), _toml.load("configs/e1d.toml")
    own = {"id", "charter", "signal", "fallback_signal"}
    sa = {k: v for k, v in a["strategy"].items() if k not in own}
    sd = {k: v for k, v in d["strategy"].items() if k not in own}
    assert sa == sd
    assert a["strategy"]["fallback_signal"] == d["strategy"]["signal"]
    assert a["universe"] == d["universe"]
    for k in ("costs", "tax", "benchmarks", "hooks"):
        assert a[k] == d[k]
    assert a["stack"]["config"] == "configs/e1d.toml"


def test_the_run_fingerprint_covers_e1d_toml():
    from pflab.backtest import runner
    cfg = _toml.load("configs/e1.toml")
    per = Period("development", date(2007, 1, 1), date(2016, 12, 31))
    fp = runner.input_fingerprints(cfg, per, {}, None, None)
    assert fp["stack_config_e1d"] == artifacts.file_sha("configs/e1d.toml")
    assert fp["stack_config"] == artifacts.file_sha("configs/e1.toml")
