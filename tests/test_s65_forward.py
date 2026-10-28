"""S65 forward tests: months formed from the day's data, settled when the next month has ended, decided once at 24 months, counts only before."""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from pflab.learner import counter, forward as fw, templates as tp
from pflab.pm import store

SESSIONS = pd.bdate_range("2025-06-02", "2028-12-29")
NAMES = [f"INE{k:03d}A01010" for k in range(80)]
BAD = NAMES[:20]


def synthetic(effect: float, seed: int = 7, names=NAMES):
    rng = np.random.default_rng(seed)
    r = pd.DataFrame(rng.normal(0.0, 0.01, (len(SESSIONS), len(names))), index=SESSIONS, columns=names)
    r[[n for n in BAD if n in names]] += effect
    tr = (1 + r).cumprod()
    w = {"tr": tr, "adj": tr, "close": tr, "r": r, "turnover": pd.DataFrame(1e7, index=SESSIONS, columns=names)}
    mem = pd.DataFrame({"isin": names, "from_date": pd.Timestamp("2020-01-01"), "to_date": pd.Timestamp("2099-01-01")})
    return w, mem


@pytest.fixture
def con(tmp_path, monkeypatch):
    c = store.connect(tmp_path / "l.duckdb")
    frame = pd.DataFrame(0.0, index=SESSIONS, columns=NAMES)
    frame[BAD] = 1.0
    monkeypatch.setattr(tp, "rule_frame", lambda w, rule, eps=None: frame)           # the group is the same fixed twenty names every month
    return c


def run_months(con, loader, first=(2026, 11), last=(2028, 11)):
    y, m = first
    decided = {}
    while (y, m) <= last:
        out = fw.cycle(con, None, datetime(y, m, 1, 21, 0), loader=loader)
        decided.update(out.get("decided", {}))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return decided


def test_registering_counts_the_four_claims_once(con):
    n0 = counter.n_tests(con)
    assert fw.register(con, datetime(2026, 10, 28)) == 4 and fw.register(con, datetime(2026, 10, 28)) == 0
    assert counter.n_tests(con) == n0 + 4


def test_nothing_is_loaded_until_a_month_has_ended(con):
    calls = []
    out = fw.cycle(con, None, datetime(2026, 10, 29, 21, 0), loader=lambda: calls.append(1))      # October has not ended
    assert calls == [] and out["registered"] == 4 and "formed" not in out
    assert fw.pending(con, datetime(2026, 10, 29)) == {"form": [], "settle": 0}
    assert fw.pending(con, datetime(2026, 11, 2)) == {"form": [(2026, 10)], "settle": 0}


def test_a_month_is_formed_from_its_last_session_and_settled_when_the_next_month_has_ended(con):
    w, mem = synthetic(-0.0015)
    loads = []
    loader = lambda: (loads.append(1), (w, mem))[1]
    fw.cycle(con, None, datetime(2026, 11, 2, 21, 0), loader=loader)
    rows = con.execute("SELECT claim, formed_on, status, group_n, universe_n FROM forward_months ORDER BY claim").fetchall()
    assert [r[0] for r in rows] == ["F1", "F2", "F3", "F4"] and all(str(r[1]) == "2026-10-30" and r[2] == "formed" for r in rows)
    assert all(r[3] == 20 and r[4] == 80 for r in rows)
    assert con.execute("SELECT excess FROM forward_months WHERE excess IS NOT NULL").fetchall() == []          # outcome not yet known
    fw.cycle(con, None, datetime(2026, 11, 3, 21, 0), loader=loader)
    assert len(loads) == 1                                                                                     # nothing new: the panel was not loaded again
    fw.cycle(con, None, datetime(2026, 12, 1, 21, 0), loader=loader)
    s = con.execute("SELECT formed_on, outcome_on, excess, group_ret, universe_ret FROM forward_months WHERE claim='F1' AND status='settled'").fetchone()
    assert str(s[0]) == "2026-10-30" and str(s[1]) == "2026-11-30" and s[2] < 0 and s[2] == pytest.approx(s[3] - s[4])
    assert 0.015 < -s[2] < 0.06                                                                               # about -0.15% a day for 21 sessions


def test_the_group_and_universe_are_frozen_at_formation(con):
    w, mem = synthetic(-0.0015)
    fw.cycle(con, None, datetime(2026, 11, 2, 21, 0), loader=lambda: (w, mem))
    g = con.execute("SELECT group_json FROM forward_months WHERE claim='F1'").fetchone()[0]
    mem2 = mem[~mem["isin"].isin(BAD[:5])]                     # a later change of membership must not rewrite a month already formed
    fw.cycle(con, None, datetime(2026, 12, 2, 21, 0), loader=lambda: (w, mem2))
    assert con.execute("SELECT group_json FROM forward_months WHERE claim='F1' AND formed_on='2026-10-30'").fetchone()[0] == g


def test_a_planted_effect_is_decided_once_at_24_months_and_not_before(con):
    w, mem = synthetic(-0.0015)
    fw.register(con, datetime(2026, 10, 28))
    early = run_months(con, lambda: (w, mem), last=(2028, 10))                                # 23 settled months
    assert early == {} and all(s["settled"] == 23 and s["verdict"] is None for s in fw.status(con))
    assert all(set(s) >= {"settled", "formed", "needs"} and "t" not in s for s in fw.status(con))             # counts only, no running t
    out = run_months(con, lambda: (w, mem), first=(2028, 11), last=(2028, 11))
    assert set(out) == {"F1", "F2", "F3", "F4"} and all(v["passed"] and v["t"] < -2.13 and v["months"] == 24 for v in out.values())
    learned = {r[0] for r in con.execute("SELECT key FROM learned WHERE kind='finding' AND valid_to IS NULL").fetchall()}
    assert learned == {"forward:F1", "forward:F2", "forward:F3", "forward:F4"}
    row = con.execute("SELECT n_dev, t_dev, threshold_dev, passed FROM learn_tests WHERE note='forward:F2'").fetchone()
    assert row[0] == 24 and row[1] < -2.13 and row[2] == -2.13 and row[3] is True
    n = counter.n_tests(con)
    assert run_months(con, lambda: (w, mem), first=(2028, 12), last=(2029, 3)) == {} and counter.n_tests(con) == n    # decided once
    assert all(s["verdict"]["passed"] for s in fw.status(con))


def test_no_effect_does_not_pass(con):
    w, mem = synthetic(0.0, seed=3)
    out = run_months(con, lambda: (w, mem))
    assert all(not v["passed"] for v in out.values()) and len(out) == 4
    assert con.execute("SELECT count(*) FROM learned WHERE kind='finding'").fetchone()[0] == 0


def test_a_month_formed_after_its_outcome_is_over_is_late_and_unused(con):
    w, mem = synthetic(-0.0015)
    fw.cycle(con, None, datetime(2027, 1, 4, 21, 0), loader=lambda: (w, mem))               # the system was off Nov and Dec
    st = dict(con.execute("SELECT strftime(formed_on, '%Y-%m'), status FROM forward_months WHERE claim='F1'").fetchall())
    assert st == {"2026-10": "late", "2026-11": "late", "2026-12": "formed"}
    assert con.execute("SELECT group_json FROM forward_months WHERE status='late'").fetchall() == [(None,)] * 8


def test_too_few_names_makes_a_thin_month_that_is_not_used(con):
    w, mem = synthetic(-0.0015, names=NAMES[:40])
    fw.cycle(con, None, datetime(2026, 11, 2, 21, 0), loader=lambda: (w, mem))
    assert {r[0] for r in con.execute("SELECT status FROM forward_months").fetchall()} == {"thin"}
    assert fw.status(con)[0]["thin"] == 1 and fw.status(con)[0]["settled"] == 0


def test_the_learner_cycle_runs_it(monkeypatch):
    import inspect
    from pflab.learner import run
    assert "forward.cycle" in inspect.getsource(run.cycle)


def test_the_learner_status_shows_counts_only(con):
    from pflab.learner import run
    fw.register(con, datetime(2026, 10, 28))
    text = run.status(con)
    assert "Forward tests (live data only; decided once at 24 months): F1 0/24; F2 0/24; F3 0/24; F4 0/24" in text
