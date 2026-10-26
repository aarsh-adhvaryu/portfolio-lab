"""S64 Phase 3: forecasts without TimesFM (quant/forecast.py, quant/ranges_eval.py). The baselines for turnover and results
(as the S52 study registered them), the price ranges from a block bootstrap with a CAPM centre, scoring when due, the
rolling coverage, the calibration rule, and what the agents show. Synthetic data only."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from pflab.conductor.calendar import Calendar
from pflab.pm import store
from pflab.quant import forecast as fl
from pflab.quant import ranges_eval as ev

A, B = "INE000A01011", "INE000B01011"
CAL = Calendar()                                   # weekdays only


def bhav(root, end: date, n: int = 700, seed: int = 0):
    """Two stocks' daily turnover on n weekdays to `end` (B stops trading after its first 100 sessions)."""
    rng = np.random.default_rng(seed)
    d = pd.bdate_range(end=end, periods=n).date
    rows = []
    for k, i in enumerate((A, B)):
        lt = 18 + 0.3 * np.sin(np.arange(n) / 20) + rng.normal(0, 0.3, n)
        for j, x in enumerate(d):
            if i == B and j > 100:
                continue
            rows.append({"date": x, "symbol": f"S{k}", "series": "EQ", "isin": i, "turnover": float(np.exp(lt[j]))})
    df = pd.DataFrame(rows)
    for y, g in df.groupby([pd.Timestamp(x).year for x in df["date"]]):
        p = root / "bhavcopy" / str(y)
        p.mkdir(parents=True, exist_ok=True)
        g.to_parquet(p / "part.parquet", index=False)
    return list(d)


def quarters(con, scrip: str, n: int, last: date, usable_lag: int = 40):
    qe = pd.date_range(end=pd.Timestamp(last), periods=n, freq="QE").date
    for k, q in enumerate(qe):
        rev = 1000 * 1.02 ** k
        con.execute("INSERT INTO quarterly_results (scrip_code, quarter_end, revenue, net_profit, usable_from, date_source, "
                    "source, fetched_at, basis) VALUES (?,?,?,?,?,?,?,?,?)",
                    [scrip, q, rev, 0.1 * rev, q + timedelta(days=usable_lag), "announcement", "test", datetime(2026, 1, 1),
                     "standalone"])


@pytest.fixture
def env(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    root = tmp_path / "data"
    u = pd.DataFrame([{"isin": A, "symbol": "AAA", "scrip": "500002"}, {"isin": B, "symbol": "BBB", "scrip": "500003"}])
    return con, root, u


# --- baselines (turnover, results) --------------------------------------------------------------------------------------------

def test_turnover_case_is_point_in_time_and_names_its_baseline():
    d = list(pd.bdate_range(end="2026-10-16", periods=700).date)
    lev = np.exp(18 + np.random.default_rng(1).normal(0, 0.3, 700))
    fut = fl.future_sessions(CAL, d[-1], fl.H5 + fl.FUTURE)
    c = fl.turnover_case(d, lev, fut)
    assert c["target"] == str(fut[4]) == "2026-10-23" and c["inputs_last"] == "2026-10-16"
    assert c["baseline_name"] == "har_cal" and abs(c["baseline"] - 18) < 0.5
    lev[-500:] = 0                                                                           # no trades lately
    assert fl.turnover_case(d, lev, fut) is not None and fl.turnover_case(d[:5], lev[:5], fut) is None


def test_results_case_needs_eight_quarters_and_uses_the_registered_baselines():
    qe = pd.date_range(end="2026-06-30", periods=12, freq="QE").date
    q = pd.DataFrame({"quarter_end": qe, "revenue": 1000 * 1.02 ** np.arange(12), "net_profit": 50 + np.arange(12)})
    c = fl.results_case(q)
    assert c["run"] == 12 and c["target"] == "2026-09-30" and c["inputs_last"] == "2026-06-30"
    x = np.log(q["revenue"].to_numpy())
    assert c["revenue"]["baseline"] == pytest.approx(x[-4] + np.mean(x[-4:] - x[-8:-4]))
    assert c["margin"]["baseline"] == pytest.approx(q["net_profit"].iloc[-4] / q["revenue"].iloc[-4])
    assert fl.results_case(q.iloc[-7:])["run"] == 7 and "revenue" not in fl.results_case(q.iloc[-7:])
    assert fl.results_case(q.drop(index=8))["run"] == 3                                      # a missing quarter breaks the run


def test_run_stores_baselines_scores_them_and_stores_nothing_twice(env):
    con, root, u = env
    bhav(root, date(2026, 10, 9))
    quarters(con, "500002", 10, date(2026, 6, 30))
    quarters(con, "500003", 5, date(2026, 6, 30))
    r = fl.run(con, root, date(2026, 10, 9), u, CAL, now=datetime(2026, 10, 9, 21))
    assert r["turnover"] == 1 and r["revenue"] == 1 and r["serving"] == "stats_plain"
    rows = con.execute("SELECT use, subject, target, model, point, baseline FROM forecasts ORDER BY use").fetchall()
    assert {(x[0], x[1], str(x[2])) for x in rows} == {("margin", "500002", "2026-09-30"), ("revenue", "500002", "2026-09-30"),
                                                       ("turnover", A, "2026-10-16")}
    assert all(x[3] == "baseline" and x[4] is not None and x[5] is not None for x in rows)
    assert fl.run(con, root, date(2026, 10, 9), u, CAL, now=datetime(2026, 10, 9, 22))["scored"] == 0
    assert con.execute("SELECT count(*) FROM forecasts").fetchone()[0] == 3
    bhav(root, date(2026, 10, 30), n=715)                                  # the turnover target has traded, the quarter is out
    quarters(con, "500002", 1, date(2026, 9, 30), usable_lag=20)
    r2 = fl.run(con, root, date(2026, 10, 30), u, CAL, now=datetime(2026, 10, 30, 21))
    assert r2["scored"] == 3
    s = con.execute("SELECT actual, loss_model, loss_baseline FROM forecasts WHERE as_of = DATE '2026-10-09'").fetchall()
    assert all(x[0] is not None and x[1] is not None and x[2] is not None for x in s)


def test_the_baselines_are_dated_and_shown_to_the_agents(env):
    from pflab.agents import researcher as rs
    from pflab.plan import trader
    con, root, u = env
    bhav(root, date(2026, 10, 9))
    quarters(con, "500002", 10, date(2026, 6, 30))
    fl.run(con, root, date(2026, 10, 9), u, CAL, now=datetime(2026, 10, 9, 21))
    est = fl.turnover_estimate(con, A, date(2026, 10, 10))
    assert est and "HAR + calendar" in est[1]
    tk = trader.tickets("AAA", 100, 500.0, "", isin=A, turnover=fl.turnover_fn(con, date(2026, 10, 10)))
    assert tk[-1].startswith("Size check (ESTIMATE, HAR + calendar") and "of the expected daily turnover" in tk[-1]
    assert fl.turnover_estimate(con, A, date(2026, 10, 30)) is None                         # stale: not used
    lines = fl.results_lines(con, "500002", "AAA")
    assert any("revenue, quarter ending 2026-09-30: about Rs" in x and "ESTIMATE, last year x trailing growth" in x for x in lines)
    f = rs.forecast_flags(con, A, "AAA", "500002", datetime(2026, 10, 1), datetime(2026, 10, 10))
    assert [x.kind for x in f] == ["results_range"] and "net margin" in f[0].detail
    quarters(con, "500002", 1, date(2026, 9, 30), usable_lag=20)
    bhav(root, date(2026, 10, 30), n=715)
    fl.run(con, root, date(2026, 10, 30), u, CAL, now=datetime(2026, 10, 30, 21))
    f = rs.forecast_flags(con, A, "AAA", "500002", datetime(2026, 10, 25), datetime(2026, 10, 31))
    sur = [x for x in f if x.kind == "results_surprise"]
    assert sur and sur[0].happened_at == datetime(2026, 10, 20) and "against about" in sur[0].detail
    assert "turnover: 2 forecast(s)" in fl.show(con) and "not tested yet" in fl.show(con)


# --- price ranges --------------------------------------------------------------------------------------------------------------

def test_the_stationary_bootstrap_draws_in_blocks_of_about_ten():
    lr = np.arange(2000, dtype=float)                                  # consecutive values: a block continues by +1
    d = fl.stationary_bootstrap(lr, 400, 300, np.random.default_rng(1))
    cont = np.mean((d[:, 1:] - d[:, :-1]) == 1.0)
    assert 0.85 < cont < 0.95                                          # about 1 - 1/10, plus the odd chance continuation


def test_price_ranges_follow_the_volatility_and_the_capm_centre():
    rng = np.random.default_rng(2)
    lr = rng.normal(0.0004, 0.01, 750)
    res = fl.price_ranges(lr, 100.0, 0.12, (21, 63, 252), 8000, np.random.default_rng(3), methods=("stats_plain",))["stats_plain"]
    q10, q50, q90 = res[21]
    sd = 0.01 * np.sqrt(21)
    assert q50 == pytest.approx(100 * np.exp(np.log1p(0.12) / 252 * 21), rel=0.01)       # the centre is the CAPM return
    assert q90 / q50 == pytest.approx(np.exp(1.2816 * sd), rel=0.03) and q50 / q10 == pytest.approx(np.exp(1.2816 * sd), rel=0.03)
    assert res[252][2] - res[252][0] > res[63][2] - res[63][0] > q90 - q10          # wider with the horizon
    again = fl.price_ranges(lr, 100.0, 0.12, (21, 63, 252), 8000, np.random.default_rng(3), methods=("stats_plain",))["stats_plain"]
    assert again == res                                                               # seeded: the same night, the same range


def test_the_ewma_method_widens_when_volatility_has_just_risen():
    rng = np.random.default_rng(4)
    lr = np.r_[rng.normal(0, 0.008, 730), rng.normal(0, 0.03, 20)]                     # a calm history, a wild last month
    r = fl.price_ranges(lr, 100.0, 0.10, (21,), 6000, np.random.default_rng(5))
    plain, ew = r["stats_plain"][21], r["stats_ewma"][21]
    assert (ew[2] - ew[0]) > 1.4 * (plain[2] - plain[0])
    calm = rng.normal(0, 0.01, 750)
    rc = fl.price_ranges(calm, 100.0, 0.10, (21,), 6000, np.random.default_rng(5))
    assert (rc["stats_ewma"][21][2] - rc["stats_ewma"][21][0]) == pytest.approx(rc["stats_plain"][21][2] - rc["stats_plain"][21][0], rel=0.25)


def test_pinball_and_scoring_a_price_range_when_due(env):
    con, root, _ = env
    assert fl.pinball(100.0, (90.0, 100.0, 110.0)) == pytest.approx((0.1 * 10 + 0.0 + 0.1 * 10) / 3)   # inside: the two tails cost a little
    assert fl.pinball(120.0, (90.0, 100.0, 110.0)) == pytest.approx((0.1 * 30 + 0.5 * 20 + 0.9 * 10) / 3)
    assert fl.pinball(80.0, (90.0, 100.0, 110.0)) == pytest.approx((0.9 * 10 + 0.5 * 20 + 0.1 * 30) / 3)
    now = datetime(2026, 11, 30, 21)
    for k, y in enumerate((95.0, 120.0, 100.0, 85.0)):                                  # inside, above, inside, below
        fl._insert(con, now, use="price21", subject=A, asof=date(2026, 10, 1) + timedelta(days=k), target=date(2026, 10, 31),
                   inputs_last=date(2026, 10, 1), model="stats_plain", q10=90.0, q50=100.0, q90=110.0, point=100.0,
                   baseline=100.0, baseline_name="last_close")
    ys = iter((95.0, 120.0, 100.0, 85.0))
    assert fl.score(con, lambda use, subj, a, t: next(ys), now) == 4
    cv = fl.coverage(con, "stats_plain", 21)
    assert cv["n"] == 4 and cv["covered"] == 0.5 and fl.coverage(con, "stats_ewma", 21) is None
    loss = con.execute("SELECT loss_model FROM forecasts WHERE actual = 120").fetchone()[0]
    assert loss == pytest.approx(fl.pinball(120.0, (90.0, 100.0, 110.0)) / 100.0)       # relative to the price at the time


def test_store_prices_and_the_lines_the_brain_and_the_page_read(env, monkeypatch):
    from pflab.app import research
    con, root, u = env
    rng = np.random.default_rng(6)
    idx = pd.bdate_range(end="2026-10-09", periods=800)
    px = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, 800))), index=idx)
    monkeypatch.setattr(research, "closes", lambda con_, root_, isin, asof, years=4: px if isin == A else pd.Series(dtype=float))
    monkeypatch.setattr(fl, "drift_for", lambda root_, isin, asof, table=None, erp=None: (0.12, "test"))
    import pflab.data.riskfree as rf
    import pflab.risk.capm as capm
    monkeypatch.setattr(rf, "monthly_table", lambda root_=None: pd.DataFrame(columns=["rate", "label"]))
    monkeypatch.setattr(capm, "erp", lambda root_=None, table=None: 0.07)
    out = fl.store_prices(con, root, date(2026, 10, 9), u, datetime(2026, 10, 9, 21), paths=2000)
    assert out["stored"] == 6 and list(out["skipped"]) == [B]                           # 3 horizons x 2 methods; B has no prices
    assert fl.store_prices(con, root, date(2026, 10, 9), u, datetime(2026, 10, 9, 22), paths=2000)["stored"] == 0
    lines = fl.price_lines(con, A, "AAA", root)
    assert len(lines) == 3 and "stats_plain" in lines[0] and "not tested yet" in lines[0] and "none scored yet" in lines[0]
    fan = fl.fan(con, A, root)
    assert [r["sessions"] for r in fan["ranges"]] == [21, 63, 252] and fan["ranges"][0]["q10"] < fan["ranges"][0]["q90"]
    (root / "research").mkdir(parents=True)
    (root / "research" / "s64_ranges.json").write_text(json.dumps({"serve": "stats_ewma", "label": "calibrated: test"}))
    assert "stats_ewma" in fl.price_lines(con, A, "AAA", root)[0]                       # the served method's rows are read
    assert fl.serving_method(root) == ("stats_ewma", "calibrated: test")


# --- the calibration rule ------------------------------------------------------------------------------------------------------

def _res(cov_plain, cov_ewma, t_dev, t_val):
    def cell(p, e, t):
        return {"stats_plain": {"covered": p, "n": 500, "pinball": 0.02}, "stats_ewma": {"covered": e, "n": 500, "pinball": 0.019},
                "dm": {"t": t, "mean_diff": 0.001, "n": 90, "p": 0.0}}
    return {"development": {h: cell(cov_plain, cov_ewma, t_dev) for h in ev.HORIZONS},
            "validation": {h: cell(cov_plain, cov_ewma, t_val) for h in ev.HORIZONS}}


def test_ewma_replaces_plain_only_with_coverage_and_the_raised_bar():
    d = ev.decide(_res(0.78, 0.80, 3.5, 2.0), t_dev_needed=2.85)
    assert d["serve"] == "stats_ewma" and d["ewma_replaces_plain"] and d["label"].startswith("calibrated")
    d = ev.decide(_res(0.78, 0.80, 2.5, 2.0), t_dev_needed=2.85)                         # t under the raised bar
    assert d["serve"] == "stats_plain" and not d["ewma_replaces_plain"]
    d = ev.decide(_res(0.78, 0.80, 3.5, 1.2), t_dev_needed=2.85)                         # validation under 1.65
    assert d["serve"] == "stats_plain"
    d = ev.decide(_res(0.78, 0.70, 5.0, 5.0), t_dev_needed=2.85)                         # ewma fails coverage
    assert d["serve"] == "stats_plain" and not d["coverage_pass"]["stats_ewma"]


def test_neither_method_covering_is_labelled_not_calibrated_with_the_figure():
    d = ev.decide(_res(0.62, 0.66, 5.0, 5.0), t_dev_needed=2.85)
    assert d["serve"] == "stats_plain" and d["label"] == "not calibrated: covered 62% in testing (the target is 80%)"
    assert ev.decide(_res(0.90, 0.88, 5.0, 5.0), 2.85)["coverage_pass"] == {"stats_plain": False, "stats_ewma": False}


def test_diebold_mariano_prefers_the_lower_loss():
    rng = np.random.default_rng(7)
    base = rng.normal(1.0, 0.1, 96)
    better = base - 0.05 + rng.normal(0, 0.02, 96)
    worse = base + 0.05 + rng.normal(0, 0.02, 96)
    assert ev.dm_one_sided(better, base, 2)["t"] > 3
    assert ev.dm_one_sided(worse, base, 2)["t"] < -3
    assert np.isnan(ev.dm_one_sided(base[:4], base[:4], 1)["t"])


def test_timesfm_is_gone_from_the_code():
    from pathlib import Path
    src = Path(fl.__file__).parent
    assert not list(src.glob("tfm2*.py")) and not (src / "vol_study.py").exists()
