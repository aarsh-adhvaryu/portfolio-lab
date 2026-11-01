"""S75: the four paper-book styles (steady monthly, dip buyer, holder, diversified by his targets): same money, different use, forward only, synthetic prices."""
from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from pflab.plan import styles
from pflab.pm import store


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "s.duckdb")


def _days(start: date, n: int):
    d, out = start, []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _series(days, levels):
    return pd.Series({pd.Timestamp(d): float(v) for d, v in zip(days, levels)})


def _run(con, days, levels, gold=None, flows=None, targets=None, cost=0.0):
    flows = flows or {}
    styles.start(con, days[0], 100_000.0, levels[0], gold[0] if gold else None, targets)
    for i, d in enumerate(days[1:], 1):
        styles.step(con, d, flows.get(d, 0.0), levels[i], gold[i] if gold else None, index=_series(days[:i + 1], levels[:i + 1]), side_cost=cost, targets=targets)


def _units(con, b):
    return json.loads(con.execute("SELECT holdings_json FROM twin_days WHERE book=? ORDER BY day DESC LIMIT 1", [b]).fetchone()[0])


def _val(con, b):
    return con.execute("SELECT value FROM twin_days WHERE book=? ORDER BY day DESC LIMIT 1", [b]).fetchone()[0]


DAYS = _days(date(2026, 11, 2), 50)                       # two calendar months of sessions: Nov and Dec 2026 and a little of Jan
TGT = SimpleNamespace(buckets={"equity": SimpleNamespace(target=0.60), "gold": SimpleNamespace(target=0.10), "debt": SimpleNamespace(target=0.20), "cash": SimpleNamespace(target=0.10)})


def test_every_style_starts_with_the_value_the_index_book_has_and_nothing_before(con):
    assert styles.start(con, DAYS[0], 100_000.0, 100.0, 5000.0, TGT) == list(styles.STYLES)
    assert styles.start(con, DAYS[0], 100_000.0, 100.0, 5000.0, TGT) == []                     # idempotent
    for b in styles.STYLES:
        assert _val(con, b) == pytest.approx(100_000.0)
        assert con.execute("SELECT count(*) FROM twin_days WHERE book=?", [b]).fetchone()[0] == 1
    st = styles.status(con)
    assert set(st) == set(styles.STYLES) and st["HOLDER"]["sessions"] == 0


def test_the_holder_never_buys_again_and_money_added_waits_as_cash(con):
    levels = [100.0] * len(DAYS)
    _run(con, DAYS, levels, flows={DAYS[3]: 20_000.0})
    h = _units(con, "HOLDER")
    assert h["units"] == pytest.approx(1000.0)                                                  # the first night's purchase only
    cash = con.execute("SELECT cash FROM twin_days WHERE book='HOLDER' ORDER BY day DESC LIMIT 1").fetchone()[0]
    assert cash == pytest.approx(20_000.0, rel=0.05)                                            # the added money sat in cash (plus a little interest)


def test_a_withdrawal_larger_than_the_cash_never_sells_the_holder_and_is_said(con):
    levels = [100.0] * len(DAYS)
    _run(con, DAYS, levels, flows={DAYS[2]: -5_000.0})
    assert _units(con, "HOLDER")["units"] == pytest.approx(1000.0)
    assert styles.status(con)["HOLDER"]["shortfall"] == pytest.approx(5_000.0, rel=0.01)


def test_steady_puts_new_money_in_on_the_first_session_of_the_next_month(con):
    levels = [100.0] * len(DAYS)
    _run(con, DAYS, levels, flows={DAYS[3]: 30_000.0})                                          # 5 Nov: waits for the first session of December
    dec1 = next(d for d in DAYS if d.month == 12)
    before = con.execute("SELECT holdings_json FROM twin_days WHERE book='STEADY' AND day=?", [dec1 - timedelta(days=1)]).fetchone()
    assert json.loads(before[0])["units"] == pytest.approx(1000.0)
    assert _units(con, "STEADY")["units"] == pytest.approx(1300.0, rel=0.01)


def test_dip_buyer_holds_back_a_reserve_and_buys_it_only_on_a_fall_or_after_six_months(con):
    levels = [100.0] * len(DAYS)
    _run(con, DAYS, levels, flows={DAYS[1]: 10_000.0})
    h = _units(con, "DIP")
    assert h["units"] == pytest.approx(1000.0 + 10_000.0 * 0.60 / 100.0, rel=0.01)                 # 60% went in on 1 Dec
    assert h["reserve"] == pytest.approx(4_000.0, rel=0.02)                                         # 40% waits: no fall yet


def test_dip_reserve_is_released_by_a_fall(tmp_path):
    con = store.connect(tmp_path / "d.duckdb")
    levels = [100.0] * 30 + [85.0] * (len(DAYS) - 30)
    _run(con, DAYS, levels, flows={DAYS[1]: 10_000.0})
    h = _units(con, "DIP")
    assert h["reserve"] == 0.0 and h["units"] > 1000.0 + 10_000.0 * 0.60 / 100.0                   # the reserve bought at the lower level


def test_diversified_follows_his_targets_and_is_rebalanced_monthly(tmp_path):
    con = store.connect(tmp_path / "v.duckdb")
    levels = [100.0] * 20 + [120.0] * (len(DAYS) - 20)                                              # equity rises 20%
    gold = [5000.0] * len(DAYS)
    _run(con, DAYS, levels, gold=gold, targets=TGT)
    h = _units(con, "DIVERSIFIED")
    total = _val(con, "DIVERSIFIED")
    eq, gd = h["units"] * levels[-1], h["gold"] * gold[-1]
    assert eq / total == pytest.approx(0.60, abs=0.03) and gd / total == pytest.approx(0.10, abs=0.02)      # pulled back to target at the month start


def test_diversified_without_targets_or_gold_says_so_and_holds_cash(tmp_path):
    con = store.connect(tmp_path / "n.duckdb")
    styles.start(con, DAYS[0], 100_000.0, 100.0, None, None)
    assert "no targets" in styles.status(con)["DIVERSIFIED"]["note"]
    con2 = store.connect(tmp_path / "g.duckdb")
    styles.start(con2, DAYS[0], 100_000.0, 100.0, None, TGT)
    assert "gold" in styles.status(con2)["DIVERSIFIED"]["note"]
    assert _units(con2, "DIVERSIFIED")["units"] == pytest.approx(600.0)


def test_the_scoreboard_keeps_its_four_books_and_adds_the_styles_apart():
    from pflab.plan import twin
    assert twin.BOOKS == ("REAL", "SYSTEM", "EW", "N500") and set(styles.STYLES).isdisjoint(twin.BOOKS)


def test_the_nightly_run_starts_the_style_books_beside_the_four_and_status_shows_them(tmp_path):
    from tests import test_s65_twin as t
    from pflab.plan import twin
    con = store.connect(tmp_path / "t.duckdb")
    for d, amt, kind in ((date(2026, 10, 1), 100_000.0, "cash_transfer_in"), (date(2026, 10, 1), -50_000.0, "buy")):
        con.execute("INSERT INTO cash_ledger VALUES ('ZER', ?, ?, ?, 'r', 1)", [d, amt, kind])
    t.run(con, t.DAYS[0])
    assert set(styles.status(con)) == set(styles.STYLES)
    t.run(con, t.DAYS[5])
    st = twin.status(con)
    assert set(st["books"]) == set(twin.BOOKS) and set(st["styles"]) == set(styles.STYLES) and st["sessions"] == 5
    assert st["styles"]["HOLDER"]["sessions"] == 5
    # an install whose four books already exist gets the style books from its last night
    con.execute("DELETE FROM twin_days WHERE book IN ('STEADY','DIP','HOLDER','DIVERSIFIED')")
    t.run(con, t.DAYS[7])
    assert set(styles.status(con)) == set(styles.STYLES)
