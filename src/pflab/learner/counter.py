"""The test counter (S64 Phase 1; learner protocol amendment 4, 2026-10-26): every test ever run is one row of
`learn_tests`, and the development bar rises with how many have run, so the learner cannot fool itself by trying many
claims and keeping the lucky one.

    t_needed(N) = max(2.0, Phi^-1(1 - 0.05 / N))     one-sided Bonferroni over the N tests of the family "all"
                                                     (N counts this test too: N=20 -> 2.81, N=100 -> 3.29)
    validation stays at 1.65 (an independent replication); the deflated Sharpe ratio is recorded, never decides.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Optional, Sequence

import numpy as np

T_FLOOR = 2.0
ALPHA = 0.05
EULER = 0.5772156649015329


def n_tests(con, family: str = "all") -> int:
    """How many tests have run in the family (every row is in 'all')."""
    return int(con.execute("SELECT count(*) FROM learn_tests WHERE family=?", [family]).fetchone()[0])


def t_needed(n: int) -> float:
    """The development bar when `n` tests (this one included) have been run: never under the old 2.0."""
    from scipy.stats import norm
    n = max(int(n), 1)
    return float(max(T_FLOOR, norm.ppf(1 - ALPHA / n)))


def line(con) -> str:
    """For the status, the board and the brain: how many tests have run and the bar the next one faces."""
    n = n_tests(con)
    return f"Tests run {n}; the bar for the next one: development t >= {t_needed(n + 1):.2f}, validation t >= 1.65."


def deflated_sharpe(returns: Sequence[float], sr_trials: Sequence[float]) -> float:
    """Deflated Sharpe ratio (Bailey and Lopez de Prado, 2014, "The Deflated Sharpe Ratio", J. of Portfolio Management):
    the probability that the series' true Sharpe ratio is above what the best of N unskilled trials would show.

        SR0 = sqrt(Var[SR_trials]) * ((1 - g) * Phi^-1(1 - 1/N) + g * Phi^-1(1 - 1/(N e)))      g = Euler-Mascheroni
        DSR = Phi( (SR - SR0) * sqrt(T - 1) / sqrt(1 - skew * SR + (kurt - 1) / 4 * SR^2) )     kurt = raw (normal = 3)

    SR is per period (not annualised), like the trials. With fewer than two trials SR0 is 0. nan when the series is
    too short or flat."""
    from scipy.stats import kurtosis, norm, skew
    x = np.asarray([v for v in returns if v is not None and math.isfinite(v)], dtype=float)
    if len(x) < 4 or float(x.std(ddof=1)) == 0.0:
        return float("nan")
    sr = float(x.mean() / x.std(ddof=1))
    trials = np.asarray([v for v in sr_trials if v is not None and math.isfinite(v)], dtype=float)
    n = len(trials)
    sr0 = 0.0
    if n >= 2:
        sr0 = float(trials.std(ddof=1)) * ((1 - EULER) * norm.ppf(1 - 1 / n) + EULER * norm.ppf(1 - 1 / (n * math.e)))
    g3, g4 = float(skew(x)), float(kurtosis(x, fisher=False))
    den = 1 - g3 * sr + (g4 - 1) / 4 * sr * sr
    if den <= 0:
        return float("nan")
    return float(norm.cdf((sr - sr0) * math.sqrt(len(x) - 1) / math.sqrt(den)))


def sharpe_trials(con) -> list:
    """The development Sharpe ratios of the tests that have one (the DSR's trials)."""
    return [r[0] for r in con.execute("SELECT sr_dev FROM learn_tests WHERE sr_dev IS NOT NULL").fetchall()]


def record(con, now: datetime, origin: str, template: str, params: Optional[dict] = None, claim_id: Optional[int] = None,
           n_dev: Optional[int] = None, t_dev: Optional[float] = None, t_val: Optional[float] = None,
           sr_dev: Optional[float] = None, dsr: Optional[float] = None, threshold_dev: Optional[float] = None,
           passed: Optional[bool] = None, note: str = "", family: str = "all") -> int:
    """One row for one test run; returns its test_id. `origin` is learner, study or seed."""
    from pflab.pm.store import next_id
    if origin not in ("learner", "study", "seed"):
        raise ValueError("origin must be learner, study or seed")

    def clean(v):
        return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else v
    tid = next_id(con, "learn_tests", "test_id")
    con.execute("INSERT INTO learn_tests (test_id, ran_at, family, origin, claim_id, template, params_json, n_dev, t_dev, t_val, "
                "sr_dev, dsr, threshold_dev, passed, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [tid, now, family, origin, claim_id, template, json.dumps(params or {}, sort_keys=True), n_dev, clean(t_dev),
                 clean(t_val), clean(sr_dev), clean(dsr), clean(threshold_dev), passed, note[:300]])
    return tid


# The past studies, one row per primary test, read from docs/research/*_results.md (verdict and t where the document
# states one; None where it does not). (note key, study, pass?, t dev, t val, what). Idempotent by the note key.
SEED = (
    ("hawkes:market_clustering", "hawkes", True, None, None, "Hawkes clustering of big Nifty falls (LR p 1e-25)"),
    ("hawkes:dip_tranche_wait", "hawkes", False, None, None, "waiting on a dip in elevated state (further falls fewer)"),
    ("height:big_fall_after_high", "height", False, None, None, "height of the ride warns of a 15% fall"),
    ("early_warning:first_fall", "early_warning", False, None, None, "combined early warning of first falls"),
    ("dip_rule:market_dip_fsafe", "dip_rule", True, None, None, "extra buys on a 10% market dip into Fsafe stocks"),
    ("buyzone:wait_for_zone", "buyzone", False, -0.04, -0.91, "waiting for the buy zone vs buying at once (1 month)"),
    ("pairs:primary_rule", "pairs", False, 1.82, 0.71, "pairs trading, entry |z| 2, exit 0"),
    ("timesfm:q1_volatility", "timesfm", False, None, -3.54, "TimesFM volatility vs EWMA (DM t, validation)"),
    ("timesfm:q2_fall_ranking", "timesfm", False, None, None, "TimesFM ranking of -2% falls vs Hawkes"),
    ("timesfm2:q1", "timesfm2", False, None, None, "S52 Q1 volatility over 10 sessions"),
    ("timesfm2:q2", "timesfm2", False, None, None, "S52 Q2 chance of a -2% session"),
    ("timesfm2:q3", "timesfm2", False, None, None, "S52 Q3 ranges over 3, 6, 12 months"),
    ("timesfm2:q3b", "timesfm2", False, None, None, "S52 Q3b volatility-aware normal vs bootstrap at one year"),
    ("timesfm2:q4", "timesfm2", False, None, None, "S52 Q4 return forecast (Clark-West)"),
    ("timesfm2:q5", "timesfm2", True, None, None, "S52 Q5 turnover over 5 sessions"),
    ("timesfm2:q6", "timesfm2", True, None, None, "S52 Q6 results ranges (revenue, net margin)"),
    ("market_state_vol:hawkes_vs_ewma", "market_state_vol", False, None, None, "Hawkes chance vs plain volatility on ten indices"),
    ("s48:arm1_insiders", "s48", False, 1.19, 1.58, "promoter and insider net buying, 3-month excess"),
    ("s48:arm2_institutions", "s48", False, -0.10, -0.42, "institutional holding change, 3-month excess"),
    ("s48:arm4_deals", "s48", False, -2.84, 0.06, "non-promoter bulk and block buying, 3-month excess"),
    ("memory_compare:hybrid_retrieval", "memory_compare", True, None, None, "hybrid retrieval vs words, test recall@5"),
)


def seed(con, now: Optional[datetime] = None) -> int:
    """Insert the past studies' primary tests and the learner's already-decided claims; returns rows added. A row whose
    note key is already there is skipped, so it can be run any number of times."""
    now = now or datetime.now()
    have = {r[0] for r in con.execute("SELECT note FROM learn_tests WHERE origin='seed'").fetchall()}
    added = 0
    for key, study, ok, t_dev, t_val, what in SEED:
        if f"{key}" in have:
            continue
        record(con, now, "seed", study, {"key": key}, t_dev=t_dev, t_val=t_val, passed=ok, note=key)
        added += 1
    for cid, t, prm, dec, res in con.execute(
            "SELECT claim_id, template, params_json, decision, result_json FROM learn_claims WHERE status IN ('passed','failed') "
            "ORDER BY claim_id").fetchall():
        key = f"claim:{cid}"
        if key in have:
            continue
        try:
            r = json.loads(res or "{}")
        except Exception:
            r = {}
        dev, val = r.get("development") or {}, r.get("validation") or {}
        record(con, now, "seed", t, json.loads(prm or "{}"), claim_id=cid, n_dev=dev.get("n"), t_dev=dev.get("t"),
               t_val=val.get("t"), passed=dec == "pass", note=key)
        added += 1
    return added
