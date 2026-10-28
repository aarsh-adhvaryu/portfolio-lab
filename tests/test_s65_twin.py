"""S65 the scoreboard: four paper books, the same money on the same days; SYSTEM follows only the brain's own suggestions."""
import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab.plan import twin
from pflab.pm import store

AAA, BBB = "INE000A01011", "INE000B01012"
DAYS = [date(2026, 11, 2) + timedelta(days=k) for k in range(0, 100) if (date(2026, 11, 2) + timedelta(days=k)).weekday() < 5]
COST = 0.001


def lv_stock(isin, d):
    k = DAYS.index(d) if d in DAYS else 0
    return {AAA: 100.0 * (1.01 ** k), BBB: 50.0}.get(isin)


def levels(isins, d):
    return {i: lv_stock(i, d) for i in isins if lv_stock(i, d)}


def idx_at(d):
    k = DAYS.index(d)
    return {"EW": 1000.0 * (1.005 ** k), "N500": 2000.0}


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    for d, amt, kind in ((date(2026, 10, 1), 100_000.0, "cash_transfer_in"), (date(2026, 10, 1), -50_000.0, "buy")):
        c.execute("INSERT INTO cash_ledger VALUES ('ZER', ?, ?, ?, 'r', 1)", [d, amt, kind])
    return c


def real(d):
    return {"value": 100_000.0, "cash": 50_000.0, "holdings": {AAA: 50_000.0}}


def suggest(con, sid, made, kind, isin, amount=None, shadow=False):
    con.execute("INSERT INTO hq_suggestions (sug_id, model, made_at, kind, isin, symbol, text, horizon_days, shadow, amount) "
                "VALUES (?, 'm', ?, ?, ?, 'X', 't', 30, ?, ?)", [sid, made, kind, isin, shadow, amount])


def run(con, upto):
    return twin.run(con, None, datetime.combine(upto, datetime.min.time()), sessions=DAYS, levels=levels, idx_at=idx_at,
                    real_fn=real, side_cost=COST)


def book(con, b, d):
    r = con.execute("SELECT value, cash, holdings_json FROM twin_days WHERE book=? AND day=?", [b, d]).fetchone()
    return r[0], r[1], json.loads(r[2])


def test_the_first_night_starts_every_book_from_his_real_book(con):
    assert run(con, DAYS[0]) == {"started": str(DAYS[0])}
    for b in twin.BOOKS:
        assert book(con, b, DAYS[0])[0] == pytest.approx(100_000.0)
    v, cash, h = book(con, "SYSTEM", DAYS[0])
    assert cash == 50_000.0 and h["units"] == {AAA: pytest.approx(500.0)}                       # a copy of REAL in total-return units
    assert book(con, "EW", DAYS[0])[2]["units"] == pytest.approx(100.0)                           # all his money in the index
    assert twin.status(con)["sessions"] == 0 and "values only" in twin.status(con)["note"]


def test_money_added_reaches_every_book_on_the_same_day(con):
    run(con, DAYS[0])
    con.execute("INSERT INTO cash_ledger VALUES ('ZER', ?, 20000, 'cash_transfer_in', 'r', 2)", [DAYS[2]])
    con.execute("INSERT INTO cash_ledger VALUES ('ZER', ?, -300, 'charge', 'r', 3)", [DAYS[2]])         # not money added
    run(con, DAYS[3])
    assert book(con, "SYSTEM", DAYS[2])[1] == pytest.approx(70_000.0)
    ew_units = book(con, "EW", DAYS[2])[2]["units"]
    assert ew_units == pytest.approx(100.0 + 20_000.0 / idx_at(DAYS[2])["EW"])
    assert book(con, "N500", DAYS[2])[0] == pytest.approx(120_000.0)                              # flat index: the money itself
    assert con.execute("SELECT flows FROM twin_days WHERE book='REAL' AND day=?", [DAYS[2]]).fetchone()[0] == 20_000.0


def test_system_follows_only_the_brains_own_suggestions_at_the_next_close(con):
    run(con, DAYS[0])
    suggest(con, 1, datetime.combine(DAYS[1], datetime.min.time()).replace(hour=19), "add", BBB, amount=10_000.0)
    suggest(con, 2, datetime.combine(DAYS[1], datetime.min.time()).replace(hour=19), "add", BBB, amount=99_000.0, shadow=True)   # a rival
    run(con, DAYS[3])
    t = con.execute("SELECT day, isin, side, rupees, units, charges, sug_id FROM twin_trades").fetchall()
    assert t == [(DAYS[2], BBB, "add", 10_000.0, pytest.approx((10_000.0 - 10.0) / 50.0), pytest.approx(10.0), 1)]
    v, cash, h = book(con, "SYSTEM", DAYS[2])
    assert cash == pytest.approx(40_000.0) and h["units"][BBB] == pytest.approx(199.8)
    assert v == pytest.approx(40_000.0 + 199.8 * 50.0 + 500.0 * lv_stock(AAA, DAYS[2]))


def test_a_buy_is_limited_to_the_books_cash_and_a_trim_without_an_amount_sells_a_quarter(con):
    run(con, DAYS[0])
    suggest(con, 1, datetime.combine(DAYS[1], datetime.min.time()), "add", BBB, amount=80_000.0)
    suggest(con, 2, datetime.combine(DAYS[1], datetime.min.time()), "trim", AAA)
    suggest(con, 3, datetime.combine(DAYS[1], datetime.min.time()), "trim", "INE999Z01019", amount=5000.0)
    run(con, DAYS[2])
    t = {r[0]: r[1:] for r in con.execute("SELECT sug_id, rupees, note FROM twin_trades ORDER BY sug_id").fetchall()}
    assert t[1][0] == pytest.approx(50_000.0)                                                    # all the cash, not 80,000
    assert t[2][0] == pytest.approx(0.25 * 500.0 * lv_stock(AAA, DAYS[2]))
    assert t[3] == (0.0, "no price: not filled")


def test_runs_catch_up_and_never_repeat_a_day(con):
    run(con, DAYS[0])
    out = run(con, DAYS[5])
    assert out["sessions"] == 5 and run(con, DAYS[5])["sessions"] == 0
    assert con.execute("SELECT count(*) FROM twin_days WHERE book='SYSTEM'").fetchone()[0] == 6


def test_a_comparison_only_after_sixty_sessions_and_described_not_claimed(con):
    run(con, DAYS[0])
    run(con, DAYS[30])
    s = twin.status(con)
    assert s["sessions"] == 30 and "vs_equal_weight" not in s
    run(con, DAYS[65])
    s = twin.status(con)
    assert s["sessions"] == 65 and set(s["vs_equal_weight"]) == {"REAL", "SYSTEM", "N500"}
    assert "descriptive" in s["note"] and "pre-registered" in s["note"]


def test_no_broker_account_means_nothing_starts(tmp_path):
    c = store.connect(tmp_path / "e.duckdb")
    assert "no broker account" in twin.run(c, None, datetime(2026, 11, 3), sessions=DAYS, levels=levels, idx_at=idx_at, real_fn=real,
                                            side_cost=COST)["skipped"]
    assert twin.status(c)["started"] is False


def test_the_picture_and_the_dashboard_carry_the_scoreboard(con, tmp_path):
    from fastapi.testclient import TestClient
    from pflab.app import runtime, server
    run(con, DAYS[0])
    rt = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: datetime(2026, 11, 3, 10))
    d = TestClient(server.create_app(rt)).get("/api/twin").json()
    assert d["started"] and set(d["books"]) == set(twin.BOOKS)
    import inspect
    from pflab.hq import picture
    assert '"scoreboard"' in inspect.getsource(picture)
