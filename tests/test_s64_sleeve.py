"""S64 Phase 6 item 6: the US sleeve study: joint history, mixes, the cost to set up, the proposal."""
from datetime import date, datetime

import duckdb
import numpy as np
import pandas as pd
import pytest

from pflab.pm import store
from pflab.risk import montecarlo as mc, sleeve

BASE = {"stocks": 0.38, "n500": 0.135, "mom50": 0.135, "gold": 0.15, "debt": 0.20, "cash": 0.0, "_source": "target"}


def histories(n=240, seed=1, us_mean=0.012, us_corr=0.3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2006-01-31", periods=n, freq="ME")
    common = rng.normal(0.008, 0.045, n)
    cols = {"stocks": common + rng.normal(0, 0.01, n), "n500": common + rng.normal(0, 0.005, n), "mom50": common + rng.normal(0, 0.01, n),
            "gold": rng.normal(0.007, 0.04, n), "debt": np.full(n, 0.0053), "cash": np.full(n, 0.0025),
            "us": us_corr * common + (1 - us_corr) * rng.normal(us_mean, 0.045, n)}
    R = pd.DataFrame(cols, index=idx)[list(sleeve.ASSETS)]
    didx = pd.bdate_range("2006-02-01", periods=n * 21)
    Rd = pd.DataFrame({k: np.full(len(didx), (1 + v.mean()) ** (1 / 21) - 1) + rng.normal(0, v.std() / np.sqrt(21) if v.std() > 0 else 0, len(didx))
                       for k, v in cols.items()}, index=didx)[list(sleeve.ASSETS)]
    return R, Rd


def test_weights_scale_the_base_and_sum_to_one():
    w = sleeve.weights(BASE, 0.10)
    assert w.sum() == pytest.approx(1.0) and w[-1] == pytest.approx(0.10) and w[0] == pytest.approx(0.38 * 0.9)
    assert sleeve.weights(BASE, 0.0)[-1] == 0.0 and len(w) == len(sleeve.ASSETS) == 7


def test_the_study_reports_each_share_and_a_better_us_makes_the_mix_better():
    R, Rd = histories(us_mean=0.015)
    out = sleeve.study(None, BASE, years=3, n=2000, investable=10_000_000.0, R=R, Rd=Rd)
    assert [r["share"] for r in out["rows"]] == [0.0, 0.10, 0.15, 0.20]
    zero, twenty = out["rows"][0], out["rows"][-1]
    assert twenty["median_cagr"] > zero["median_cagr"]                                  # the planted US edge flows through
    assert all(0 <= r["p_fall_beyond_35pct_any_day"] <= 1 and r["history_worst_fall_any_day"] < 0 for r in out["rows"])
    assert twenty["amount_inr"] == 2_000_000 and zero["amount_inr"] == 0
    assert out["us_alone"]["correlation_with_nifty500"] > 0.1 and "twenty years" in out["caveat"] and out["base_mix_source"] == "target"


def test_set_up_cost_tcs_above_ten_lakh_a_year_and_less_when_funded_over_two_years():
    c = sleeve.setup_cost(1_500_000)
    assert c["tcs_inr"] == 100_000 and c["tcs_if_split_over_two_financial_years_inr"] == 0         # 15 lakh: 5 lakh over; or 7.5 lakh a year
    assert c["brokerage_inr"] == 1_500 and c["currency_markup_inr"] == [6_000, 21_000] and "estimate" in c["label"]
    big = sleeve.setup_cost(2_400_000)
    assert big["tcs_inr"] == 280_000 and big["tcs_if_split_over_two_financial_years_inr"] == 80_000         # 12 lakh a year: 2 lakh over, twice
    assert sleeve.setup_cost(800_000)["tcs_inr"] == 0


def test_the_proposal_waits_for_his_yes_and_carries_the_table(tmp_path, monkeypatch):
    con = duckdb.connect(str(tmp_path / "pm.duckdb"))
    store.migrate(con)
    R, Rd = histories()
    monkeypatch.setattr(sleeve, "joint", lambda root: (R, Rd, None))
    monkeypatch.setattr(sleeve, "base_mix", lambda c, a: dict(BASE))
    monkeypatch.setattr(sleeve, "fx_split", lambda root: {"years": 33.7, "in_dollars": 0.108, "dollar_in_rupees": 0.0356, "in_rupees": 0.1474})
    pid = sleeve.propose(con, tmp_path, date(2026, 10, 27), datetime(2026, 10, 27), 10_000_000.0, years=3, n=1000)
    assert pid and sleeve.propose(con, tmp_path, date(2026, 10, 27), datetime(2026, 10, 27), 10_000_000.0, years=3, n=1000) is None
    text = con.execute("SELECT text FROM questions").fetchone()[0]
    assert "US sleeve" in text and "10%:" in text and "20%:" in text and "targets.toml yourself" in text and "two financial years" in text
    kind, status = con.execute("SELECT kind, status FROM limit_proposals").fetchone()
    assert (kind, status) == ("us_sleeve", "pending")
