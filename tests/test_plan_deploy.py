"""S17 additions: targets from PFLAB_PM_DIR, cash floor, FDs as locked debt, FD deployment schedule.
SYNTHETIC targets and deposits."""
from datetime import date

import pytest

from pflab.pm import fd as F
from pflab.plan import deploy, rebalance
from pflab.plan import targets as tg

DOC = {"meta": {"set_by": "test", "effective_from": date(2026, 10, 15), "cash_floor": 100_000.0},
       "bucket": {"equity": {"target": 0.6, "soft_band": 0.05, "hard_band": 0.15},
                  "debt": {"target": 0.4, "soft_band": 0.05, "hard_band": 0.6},
                  "cash": {"target": 0.0, "soft_band": 0.03, "hard_band": 1.0}}}


def test_own_targets_file_wins_and_floor_is_parsed(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    assert tg.default_path() == tg.DEFAULT_PATH                       # no own file yet: the empty template
    (tmp_path / "targets.toml").write_text('[meta]\nset_by = "x"\neffective_from = 2026-10-15\ncash_floor = 5.0\n'
                                           '[bucket.cash]\ntarget = 1.0\nsoft_band = 0.0\nhard_band = 0.0\n')
    assert tg.default_path() == tmp_path / "targets.toml" and tg.load().cash_floor == 5.0
    with pytest.raises(tg.TargetsInvalid, match="cash_floor"):
        tg.parse({**DOC, "meta": {**DOC["meta"], "cash_floor": -1}})


def dep(fd_id, maturity, purpose=""):
    return F.FD(fd_id=fd_id, principal=100_000.0, rate=0.08, term_start=date(2026, 1, 10), maturity=maturity,
                maturity_amount=0.0, anchor_date=date(2026, 10, 10), anchor_value=105_000.0, purpose=purpose)


def test_schedule_spreads_each_non_reserve_batch_and_skips_the_reserve():
    fds = [dep("A", date(2027, 1, 10)), dep("B", date(2027, 1, 10)), dep("R", date(2027, 1, 10), "reserve:phd")]
    tr = deploy.schedule(fds, 4, date(2026, 10, 15))
    total = sum(F.maturity_payout(f).value for f in fds[:2])
    assert [t.month for t in tr] == [date(2027, 2, 1), date(2027, 3, 1), date(2027, 4, 1), date(2027, 5, 1)]
    assert sum(t.amount for t in tr) == pytest.approx(total, abs=0.01) and {t.batch for t in tr} == {date(2027, 1, 10)}
    with pytest.raises(ValueError):
        deploy.schedule(fds, 0, date(2026, 10, 15))


def test_projection_moves_matured_debt_into_the_targets_and_never_below_zero():
    t = tg.parse(DOC)
    values = {"equity": 100_000.0, "debt": 900_000.0, "cash": 0.0}
    tr = [deploy.Tranche(date(2027, 2, 1), 250_000.0, date(2027, 1, 10), 1),
          deploy.Tranche(date(2027, 3, 1), 250_000.0, date(2027, 1, 10), 2)]
    rows = deploy.project(values, t, tr, date(2026, 10, 15), {date(2027, 1, 10): 480_000.0})
    assert rows[0]["alloc"]["equity"] == pytest.approx(250_000.0)           # all to the underweight
    last = rows[-1]["weights"]
    assert last["equity"] > 0.5 and last["cash"] == pytest.approx((500_000 - 500_000) / 1_020_000, abs=1e-9)


def test_cash_floor_and_fds_enter_bucket_values():
    import pandas as pd
    from pflab.calc.valuation import Valuation
    v = Valuation(date(2026, 10, 15), pd.DataFrame(columns=["account", "isin", "value"]),
                  pd.DataFrame([{"account": "BANK", "balance": 150_000.0, "blocked": 0.0, "available": 150_000.0,
                                 "dormant": False}]), 0.0, 150_000.0, 150_000.0, 150_000.0)
    inst = pd.DataFrame(columns=["isin", "asset_class", "tax_class", "category", "name", "sector"])
    vals = rebalance.bucket_values(v, inst, tg.parse(DOC), {"debt": 400_000.0})
    assert vals["cash"] == pytest.approx(50_000.0) and vals["debt"] == 400_000.0 and vals["equity"] == 0.0
