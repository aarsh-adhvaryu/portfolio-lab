"""S64 Phase 5 item 4: theme limits, the dip reserve and the opportunity pot (proposals apply only after his yes)."""
from datetime import date, datetime, timedelta

import duckdb
import numpy as np
import pandas as pd
import pytest

from pflab.agents import questions
from pflab.plan import pot, reserve
from pflab.pm import store
from pflab.risk import themes

NOW = datetime(2026, 10, 27, 21, 0)
ASOF = NOW.date()


@pytest.fixture
def con(tmp_path):
    c = duckdb.connect(str(tmp_path / "pm.duckdb"))
    store.migrate(c)
    return c


def test_worst_fall_is_from_the_trailing_high():
    idx = pd.bdate_range("2023-01-02", periods=600)
    s = pd.Series(100.0, index=idx)
    s.iloc[300:] = 60.0                                          # a 40% fall
    w = themes.worst_fall(s)
    assert w["worst_fall"] == pytest.approx(-0.40) and w["sessions"] == 600
    assert "error" in themes.worst_fall(s.iloc[:100])           # too little history


def test_the_limit_is_budget_over_worst_fall_capped_by_the_equity_targets(con, monkeypatch):
    idx = pd.bdate_range("2023-01-02", periods=600)
    s = pd.Series(100.0, index=idx)
    s.iloc[300:] = 50.0                                          # worst fall 50%
    monkeypatch.setattr(themes, "history", lambda *a, **k: (s, "test series"))
    p = themes.propose_limit(con, None, "ai_it", ASOF, equity_cap=0.65)
    assert p["limit"] == pytest.approx(0.20) and not p["capped"]                   # 10% / 50%
    q = themes.propose_limit(con, None, "ai_it", ASOF, equity_cap=0.15)
    assert q["limit"] == pytest.approx(0.15) and q["capped"] and q["uncapped"] == pytest.approx(0.20)


def test_a_proposal_waits_for_the_yes_and_is_applied_once(con):
    pid = themes.propose(con, "theme_limit", "ai_it", 0.2, {"x": 1}, "Limit for AI and IT: 20%.", NOW)
    assert pid and themes.propose(con, "theme_limit", "ai_it", 0.2, {}, "again", NOW) is None       # not asked twice
    assert themes.applied(con, "theme_limit", "ai_it") is None
    assert themes.resolve(con, NOW) == {"applied": 0, "declined": 0}                                 # no answer yet
    qid = con.execute("SELECT q_id FROM limit_proposals WHERE prop_id=?", [pid]).fetchone()[0]
    questions.answer(con, qid, "maybe later", NOW)
    assert themes.resolve(con, NOW) == {"applied": 0, "declined": 0}                                 # unclear: stays pending
    con.execute("UPDATE questions SET status='open' WHERE q_id=?", [qid])
    questions.answer(con, qid, "Yes, apply it.", NOW)
    assert themes.resolve(con, NOW) == {"applied": 1, "declined": 0}
    assert themes.applied(con, "theme_limit", "ai_it") == 0.2


def test_a_no_declines_and_it_may_be_proposed_again(con):
    pid = themes.propose(con, "pot_limit", "pot", 50_000, {}, "Pot.", NOW)
    questions.answer(con, con.execute("SELECT q_id FROM limit_proposals").fetchone()[0], "no", NOW)
    assert themes.resolve(con, NOW)["declined"] == 1 and themes.applied(con, "pot_limit", "pot") is None
    assert themes.propose(con, "pot_limit", "pot", 40_000, {}, "Pot.", NOW + timedelta(days=40)) is not None


def test_basket_proposal_activates_only_on_yes(con, monkeypatch, tmp_path):
    (tmp_path / "theme_baskets.toml").write_text('[theme.ai_it]\nbasket = ["AAA", "BBB"]\n[theme.defence]\nbasket = ["CCC"]\n'
                                                 '[theme.ev_auto_tech]\nbasket = ["DDD"]\n', encoding="utf-8")
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setattr(themes, "symbol_isins", lambda root, syms, asof: {s: f"INE{i:09d}" for i, s in enumerate(syms)})
    assert themes.seed_baskets(con, None, ASOF, NOW) == 3
    assert {s for (s,) in con.execute("SELECT DISTINCT status FROM theme_baskets").fetchall()} == {"proposed"}
    q = con.execute("SELECT q_id FROM limit_proposals WHERE key='defence'").fetchone()[0]
    questions.answer(con, q, "yes", NOW)
    themes.resolve(con, NOW)
    st = dict(con.execute("SELECT theme, status FROM theme_baskets GROUP BY theme, status").fetchall())
    assert st["defence"] == "active" and st["ai_it"] == "proposed"
    assert themes.seed_baskets(con, None, ASOF, NOW) == 0                                          # once


def test_breach_only_after_the_limit_is_applied(con):
    ex = {"ai_it": {"label": "AI and IT", "weight": 0.25, "value": 1.0, "holdings": []}}
    assert themes.breaches(con, ex) == []
    con.execute("INSERT INTO limit_proposals (prop_id, kind, key, value, status, proposed_at) VALUES (1,'theme_limit','ai_it','0.2','applied',?)", [NOW])
    assert "AI and IT is 25.0% of the portfolio, limit 20.0%" in themes.breaches(con, ex)[0]


def test_reserve_size_restores_the_bottom_of_the_band():
    # investable 1000, equity 400 (target 0.40, soft 0.05); a 20% fall, beta 1: equity 320 of 920 = 34.8%; floor 35%
    s = reserve.size(1000, 400, 0.40, 0.05)
    assert s["weight_after_fall"] == pytest.approx(320 / 920)
    assert s["amount"] == pytest.approx(0.35 * 920 - 320)                                    # 2.0
    assert reserve.size(1000, 450, 0.40, 0.05)["amount"] == 0.0                              # already above the floor
    assert reserve.size(1000, 400, 0.40, 0.05, beta=0.0)["amount"] == 0.0                    # no fall, no need
    low = reserve.size(1000, 40, 0.40, 0.05)                                                 # equity still being built up
    assert low["below_floor_now"] and low["amount"] == 0.0


def test_pot_limit_is_five_percent_cut_to_the_room():
    assert pot.limit_amount(1_000_000, 500_000) == 50_000
    assert pot.limit_amount(1_000_000, 20_000) == 20_000
    assert pot.limit_amount(1_000_000, -5) == 0.0


def test_pot_ideas_need_an_applied_limit_and_stay_inside_it(con, monkeypatch):
    nums = {"buy_below": 90.0, "exit_above": 150.0, "stop_below": 70.0, "ref_close": 100.0, "how": "t"}
    monkeypatch.setattr(pot, "numbers", lambda *a, **k: nums)
    with pytest.raises(ValueError, match="no limit yet"):
        pot.add_idea(con, None, "INE000A01011", "AAA", "missed", ASOF, NOW)
    con.execute("INSERT INTO limit_proposals (prop_id, kind, key, value, status, proposed_at) VALUES (1,'pot_limit','pot','50000','applied',?)", [NOW])
    iid = pot.add_idea(con, None, "INE000A01011", "AAA", "missed", ASOF, NOW, amount=30_000)
    assert pot.used(con) == 30_000 and pot.room(con) == 20_000
    with pytest.raises(ValueError, match="already an open idea"):
        pot.add_idea(con, None, "INE000A01011", "AAA", "again", ASOF, NOW)
    pot.add_idea(con, None, "INE000B01011", "BBB", "ipo", ASOF, NOW)                       # takes the rest
    assert pot.room(con) == 0.0
    with pytest.raises(ValueError, match="full"):
        pot.add_idea(con, None, "INE000C01011", "CCC", "x", ASOF, NOW)
    assert iid == 1


def test_a_pot_idea_is_scored_at_its_horizon(con, monkeypatch):
    from pflab.hq import suggestions as sg
    con.execute("INSERT INTO pot_ideas (idea_id, made_at, isin, symbol, ref_close, amount, horizon_days, status) "
                "VALUES (1, ?, 'INE000A01011', 'AAA', 100.0, 10000, 30, 'open')", [NOW])
    monkeypatch.setattr(sg, "_close_on", lambda con, isin, day: (day, 130.0))
    monkeypatch.setattr(sg, "beta_at", lambda isin, day: 1.0)
    idx = pd.bdate_range(ASOF - timedelta(days=5), ASOF + timedelta(days=40))
    index = pd.Series(np.linspace(100, 110, len(idx)), index=idx)
    assert pot.score_due(con, NOW + timedelta(days=10), None, index) == 0                  # not due
    assert pot.score_due(con, NOW + timedelta(days=31), None, index) == 1
    ret, vs, st = con.execute("SELECT ret, ret_vs_market, status FROM pot_ideas").fetchone()
    assert ret == pytest.approx(0.30) and st == "closed" and 0.2 < vs < 0.3


def test_pit_proxy_history_includes_names_that_later_died_and_ignores_names_not_yet_members():
    idx = pd.bdate_range("2020-01-01", "2020-06-30")
    n = len(idx)
    r = pd.DataFrame({"A": [0.01] * n, "B": [0.01] * n, "C": [0.01] * n, "D": [0.01] * n, "E": [0.01] * n, "F": [0.01] * n,
                      "G": [0.01] * n}, index=idx)
    r.loc[idx[60]:, "A"] = float("nan")                                   # A is delisted in April: its fall is not in the data after
    r.loc[idx[40]:idx[60], "A"] = -0.20                                   # ...but it crashed first, while it was a member
    mem = pd.DataFrame({"isin": list("ABCDEFG"), "from_date": pd.Timestamp("2019-01-01"), "to_date": pd.Timestamp("2099-01-01")})
    mem.loc[mem["isin"] == "G", "from_date"] = pd.Timestamp("2021-01-01")      # G joins long after: never in this history
    labels = pd.DataFrame({"capture_date": pd.Timestamp("2019-06-01"), "isin": list("ABCDEFG"),
                           "industry": ["Capital Goods"] * 5 + ["Banks", "Capital Goods"]})
    s = themes.pit_proxy_history(mem, labels, r, ["capital goods"], min_names=5)
    assert s.index.min() > idx[0] and s.index.max() <= idx[-1]
    survivors_only = (1 + r[list("BCDE")].mean(axis=1)).cumprod()
    assert s.min() < survivors_only.reindex(s.index).min() or s.iloc[-1] < survivors_only.iloc[-1]       # A's crash is in
    assert themes.pit_proxy_history(mem, labels, r, ["capital goods"], min_names=6).empty                # too few live names: nothing invented
