"""S79b item 17: the seats' registered rules (decide_fast, pick_fast, decide_thinker) and the two counted tests. Synthetic arms."""
from datetime import datetime

import duckdb

from pflab.learner import counter, s79
from pflab.llm import s79_eval as se
from pflab.pm import store


def arm(routing=0.87, ans=1.0, f1=1.0, mat=0.78, p90=5.0, peak=10300.0, labels=None, ans_s=6.0):
    n = 50
    def items(sc, k):
        m = int(round(sc * k))
        return [True] * m + [False] * (k - m)
    labels = labels or ["ok"] * 5
    out = {
        "routing": {"score": routing, "n": 60, "items": items(routing, 60), "labels": labels, "call_seconds": [p90] * 60, "call_tokens_out": [30] * 60,
                    "call_median_s": p90 / 2, "gpu_peak_mib": peak, "gpu_peak_c": 70.0},
        "extraction": {"score": 1.0, "f1": f1, "n": 100, "items": [True] * 100, "labels": labels, "call_seconds": [p90] * 100, "call_tokens_out": [30] * 100,
                       "gpu_peak_mib": peak, "gpu_peak_c": 70.0},
        "materiality": {"score": mat, "n": 200, "items": items(mat, 200), "labels": labels, "call_seconds": [1.0] * 200, "call_tokens_out": [5] * 200,
                        "gpu_peak_mib": peak, "gpu_peak_c": 70.0},
    }
    for t in ("answers_20261017", "answers_20261018"):
        out[t] = {"score": ans, "n": n, "items": items(ans, n), "first_items": items(ans, n), "labels": labels, "call_seconds": [ans_s] * n,
                  "call_tokens_out": [150] * n, "task_seconds": [ans_s] * n, "gpu_peak_mib": peak, "gpu_peak_c": 70.0}
    return out


def test_fast_incumbent_vs_equal_is_not_replaced():
    assert not se.decide_fast(arm(), arm())["chosen"]            # not better overall


def test_fast_better_and_fast_wins():
    d = se.decide_fast(arm(), arm(routing=0.93, mat=0.82))
    assert d["chosen"] and all(d["checks"].values())


def test_fast_each_bound_blocks():
    base = arm()
    assert not se.decide_fast(base, arm(routing=0.93, mat=0.90, f1=0.97))["checks"]["not_worse_extraction_f1"]     # 0.97 < 1 - 0.01
    assert not se.decide_fast(base, arm(routing=0.99, mat=0.9, p90=9.0))["checks"]["latency_p90"]
    assert not se.decide_fast(base, arm(routing=0.99, mat=0.9, peak=11500.0))["checks"]["vram"]
    assert not se.decide_fast(base, arm(routing=0.99, mat=0.9, labels=["ok", "loop", "ok"]))["checks"]["failures_not_above"]
    assert not se.decide_fast(base, arm(routing=0.99, mat=0.9, ans=0.95))["checks"]["not_worse_answers_final"]
    cut = arm(routing=0.99, mat=0.9)
    cut.pop("materiality")
    assert se.decide_fast(base, cut)["checks"] == {"complete": False}


def test_pick_fast_best_of_passing():
    base = arm()
    r = se.pick_fast(base, {"a": arm(routing=0.93, mat=0.82), "b": arm(routing=0.97, mat=0.85), "c": arm(routing=0.5)})
    assert r["winner"] == "b" and not r["decisions"]["c"]["chosen"]
    assert se.pick_fast(base, {"c": arm(routing=0.5)})["winner"] is None


def test_thinker_bounds():
    base = arm()
    cand = arm(routing=1.0, mat=0.95, p90=20.0, ans_s=40.0)
    assert se.decide_thinker(base, cand, 8.0, 0)["chosen"]
    assert not se.decide_thinker(base, cand, 5.0, 0)["checks"]["ram_headroom"]
    assert not se.decide_thinker(base, cand, 8.0, 1)["checks"]["stable"]
    slow = arm(routing=1.0, mat=0.95, ans_s=120.0)
    assert not se.decide_thinker(base, slow, 8.0, 0)["checks"]["answers_p90"]
    assert not se.decide_thinker(base, arm(), 8.0, 0)["checks"]["beats_on_score"]


def test_seats_studies_count_once():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    n0 = counter.n_tests(c)
    got = s79.register_seats(c, datetime(2026, 11, 8, 3, 0))
    assert got == ["s79:seats_fast", "s79:seats_thinker"] and counter.n_tests(c) == n0 + 2
    assert s79.register_seats(c, datetime(2026, 11, 8, 3, 5)) == [] and counter.n_tests(c) == n0 + 2
