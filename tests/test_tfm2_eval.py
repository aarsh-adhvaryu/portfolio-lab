"""S52 evaluation end to end on synthetic markets: prepare -> fake forecast files -> the registered rules. An oracle that
knows the true variance must pass and noise must fail; any misalignment of forecasts and targets would break that."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.quant import tfm2 as tf
from pflab.quant import tfm2_eval as ev
from pflab.quant import tfm2_prep as pp

W, A, B = 2e-6, 0.08, 0.90


def garch_market(seed, start="2003-01-01", end="2020-06-30"):
    rng = np.random.default_rng(seed)
    d = pd.bdate_range(start, end)
    n = len(d)
    s2 = np.full(n + 1, W / (1 - A - B))
    r = np.zeros(n)
    for t in range(n):
        r[t] = np.sqrt(s2[t]) * rng.standard_normal()
        s2[t + 1] = W + A * r[t] ** 2 + B * s2[t]
    c = 100 * np.exp(np.cumsum(r))
    df = pd.DataFrame({"date": d.date, "open": c, "high": c, "low": c, "close": c})   # H == L: the r^2 fallback
    return df, s2


def oracle_q1(s2, idx, h=10):
    """Deciles of the true expected log-variance path (GARCH forecast) plus a small symmetric spread."""
    lr = W / (1 - A - B)
    ks = np.arange(h)
    path = lr + (A + B) ** ks[None, :] * (s2[idx + 1][:, None] - lr)
    z = np.linspace(-0.2, 0.2, 9)
    return np.log(path)[:, :, None] + z[None, None, :]


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    root = tmp_path_factory.mktemp("tfm2")
    (root / "inputs").mkdir()
    rng = np.random.default_rng(0)
    for k, m in enumerate(tf.MARKETS):
        df, s2 = garch_market(k)
        a = pp.q1_arrays(df, None, False, tf.fold_of(m))
        np.savez(root / "inputs" / f"q1_{m}.npz", **a)
        idx = a["idx"]
        good = oracle_q1(s2[-len(a["dates"]) - 1:], idx)
        ew = tf.vs.ewma(np.nan_to_num(a["r"]))[idx]
        noise = np.log(np.maximum(ew, 1e-10))[:, None, None] + rng.normal(0, 0.8, (len(idx), 10, 1)) + \
            np.linspace(-0.2, 0.2, 9)[None, None, :]
        for cand, q in (("T25", good), ("T30", noise), ("F25", good + 0.05)):
            p = root / "forecasts" / "q1" / cand / "log_512"
            p.mkdir(parents=True, exist_ok=True)
            np.savez(p / f"{m}.npz", dates=a["dates"][idx], q=q.astype(np.float32))
    return root


def test_q1_oracle_passes_noise_fails_and_the_choice_is_made_on_development(root):
    q1 = ev.q1_evaluate(root)
    c = q1["candidates"]
    assert c["T25"]["passes"] and not c["T30"]["passes"]
    assert c["T25"]["dm_val"]["p"] < 0.01 and sum(c["T25"]["markets_better"].values()) >= 7
    passing = [k for k in c if c[k]["passes"]]
    assert q1["adopt"] == min(passing, key=lambda k: c[k]["val_qlike"]) and "T30" not in passing   # the registered pick
    assert q1["baseline"] in ("ewma094", "har_r2", "har_logv")
    assert c["T25"]["holdout_rows"] == 0                     # no 2026 here: the holdout condition is not applied
    # the fine-tuned candidate and the combination built on it are judged fold by fold
    assert {"F25", "C"} <= set(c) and c["F25"]["passes"] and isinstance(c["C"]["passes"], bool)
    assert np.isfinite(c["C"]["val_qlike"]) and set(c["C"]["markets_better"]) == set(tf.MARKETS)
    q2 = ev.q2_evaluate(q1)
    assert set(q2) >= {"T25", "T30", "F25", "C", "adopt"}
    assert q2["T25"]["auc_val_diff"]["diff"] > q2["T30"]["auc_val_diff"]["diff"]
    assert ev.to_json({k: v for k, v in q1.items() if not k.startswith("_")})       # the results file can be written


def test_describe_uses_the_frozen_choices_and_scores_no_rule(root):
    df, s2 = garch_market(99)
    a = pp.q1_arrays(df, None, False, "")
    np.savez(root / "inputs" / "q1_NIFTY50.npz", **a)
    p = root / "forecasts" / "q1" / "T25" / "log_512"
    np.savez(p / "NIFTY50.npz", dates=a["dates"][a["idx"]], q=oracle_q1(s2[-len(a["dates"]) - 1:], a["idx"]).astype(np.float32))
    q1 = ev.q1_evaluate(root)
    res = {"q1": {k: v for k, v in q1.items() if not k.startswith("_")}}
    d = ev.describe(root, res)
    n = d["nifty_q1_q2"]
    assert set(n) == {"dev", "val", "desc", "holdout"} and n["holdout"]["rows"] == 0
    v = n["val"]["T25"]
    assert np.isfinite(v["qlike_ratio"]) and 0.5 < v["auc"] <= 1
    assert abs(v["qlike_ratio"] - v["qlike"] / n["val"]["baseline_qlike"]) < 0.05
    assert "F25" not in n["val"] and "T30" not in n["val"]     # no out-of-market model; no file, no row
    assert set(d["q1_q2_2020_2021"]) >= {"T25", "T30"} and "passes" not in json_keys(d)
    (root / "inputs" / "q1_NIFTY50.npz").unlink()
    (p / "NIFTY50.npz").unlink()


def json_keys(o):
    if isinstance(o, dict):
        return set(o) | set().union(*(json_keys(v) for v in o.values()))
    return set()


def test_dev_choice_reads_only_development(root):
    c = ev.q1_dev_choice(root)
    assert c["F25_input"] == "log" and c["T25_dev_config"] == "log_512"


def test_q3_coverage_rule_rejects_an_overconfident_range_and_q4_is_scored(tmp_path):
    (tmp_path / "inputs").mkdir()
    rng = np.random.default_rng(1)
    for k, m in enumerate(tf.MARKETS[:4]):
        df, _ = garch_market(10 + k, end="2020-12-31")
        a = pp.q3_arrays(df)
        np.savez(tmp_path / "inputs" / f"q3_{m}.npz", **a)
        lnc, idx = a["lnc"], a["idx"]
        q = np.full((len(idx), 3, 9), np.nan, np.float32)
        for hi, h in enumerate(tf.RANGE_H):
            ok = idx + h < len(lnc)
            y = lnc[idx[ok] + h] - lnc[idx[ok]]
            q[ok, hi, :] = y[:, None] + np.linspace(-0.01, 0.01, 9)[None, :]        # centred on the outcome: too sure
        p = tmp_path / "forecasts" / "q3" / "T25"
        p.mkdir(parents=True, exist_ok=True)
        np.savez(p / f"{m}.npz", dates=a["dates"][idx], q=q)
    out = ev.q34_evaluate(tmp_path)
    r = out["q3"]["63"]["T25"]
    assert r["val_pinball"] < r["baseline_val_pinball"] and r["coverage_val"] == 1.0 and not r["passes"]
    assert "passes" in out["q3b"] and out["q4"]["chosen_on_dev"] == "T25" and out["q4"]["T25"]["oos_r2"]["val"] > 0.9


def test_q5_and_q6_align_forecasts_with_their_rows(tmp_path):
    (tmp_path / "inputs").mkdir()
    rng = np.random.default_rng(2)
    d = pd.bdate_range("2006-01-01", "2020-12-31")
    for k in range(3):
        s = pd.Series(np.exp(15 + np.cumsum(rng.normal(0, 0.05, len(d)))), index=d.date)
        a = pp.q5_arrays(s)
        np.savez(tmp_path / "inputs" / f"q5_S{k}.npz", **a)
        idx = a["idx"]
        truth = np.stack([a["lt"][t + 1:t + 6] for t in idx])
        p = tmp_path / "forecasts" / "q5" / "T30"
        p.mkdir(parents=True, exist_ok=True)
        np.savez(p / f"S{k}.npz", dates=a["dates"][idx], q=np.repeat(truth[:, :, None], 9, axis=2))
    q5 = ev.q5_evaluate(tmp_path)
    assert q5["T30"]["val_mse"] < 1e-8 and q5["T30"]["share_stocks_better"] == 1.0
    f = tmp_path / "forecasts" / "q5" / "T30" / "S0.npz"
    d0 = dict(np.load(f))
    d0["q"] = d0["q"].copy()
    d0["q"][: len(d0["q"]) // 2] = np.nan                  # dates it could not forecast: dropped for both sides
    np.savez(f, **d0)
    q5b = ev.q5_evaluate(tmp_path)
    assert q5b["T30"]["val_mse"] < 1e-8 and np.isfinite(q5b["T30"]["baseline_val_mse"])
    quarters = {}
    for k in range(40):
        qe = pd.date_range("2010-03-31", "2019-12-31", freq="QE").date
        rev = np.exp(5 + np.cumsum(rng.normal(0.02, 0.1, len(qe))))
        quarters[str(500000 + k)] = pd.DataFrame({"quarter_end": qe, "revenue": rev, "net_profit": rev * 0.1})
    t = pp.q6_table(quarters)
    np.savez(tmp_path / "inputs" / "q6.npz", **t)
    rows = np.flatnonzero(t["forecastable"])
    for target in ("ln_revenue", "margin"):
        p = tmp_path / "forecasts" / "q6" / "T25"
        p.mkdir(parents=True, exist_ok=True)
        y = t[target][rows] + rng.normal(0, 0.001, len(rows))
        np.savez(p / f"{target}.npz", rows=rows, q=np.repeat(y[:, None], 9, axis=1))
    q6 = ev.q6_evaluate(tmp_path)
    assert q6["ln_revenue"]["T25"]["passes"] and q6["ln_revenue"]["adopt"] == "T25"
    assert q6["ln_revenue"]["T25"]["company_t"]["n"] == 40


def test_q6_rows_use_only_earlier_unbroken_quarters():
    qe = list(pd.date_range("2010-03-31", periods=20, freq="QE").date)
    del qe[12]
    q = pd.DataFrame({"quarter_end": qe, "revenue": np.arange(1, 20) * 10.0, "net_profit": 1.0})
    t = pp.q6_table({"500002": q})
    fc = np.flatnonzero(t["forecastable"])
    assert fc.min() == 8 and 12 not in fc                     # 8 quarters of history; the row after the gap waits
    assert all(t["run_start"][i] < i for i in fc)
    assert t["run_start"][fc[fc > 12][0]] >= 12 if (fc > 12).any() else True


def test_json_is_clean():
    s = ev.to_json({"a": np.float64("nan"), "b": np.bool_(True), "c": {1: np.int64(3)}})
    assert '"a": null' in s and '"b": true' in s and '"1": 3' in s
