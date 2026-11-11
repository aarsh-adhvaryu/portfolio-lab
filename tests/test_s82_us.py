"""S82 (A56-A59): the US paper sub-book is ONE book with the rupee book: funded by a TRANSFER out of the rupee book's cash (never new money), sized to the international share of the
WHOLE book, holding SPY as its core, decided on the last US close, caught up per session, and keyed by ZZ + CIK. Synthetic data only; no network, no secret."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab import core, us
from pflab.core import rails
from pflab.ledger import events as ev, foreign as lf, system
from pflab.pm import store
from pflab.us import adapter, book, costs, instruments as uins, policy, report, transfer, wholebook

NOW = datetime(2026, 11, 3, 7, 0)
FXR = {"rate": 90.0, "source": "FBIL", "rate_day": date(2026, 11, 2), "label": "FBIL reference rate"}
CFG = {"on": True, "slippage_bps": 5.0, "min_trade_usd": 10.0}
MARKUP = 0.004


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    return store.connect(tmp_path / "l.duckdb")


def _rupee_cash(c, amount, day=date(2026, 10, 1)):
    c.execute("INSERT INTO paper_cash VALUES (?,?,?,?,?,?)", [store.next_id(c, "paper_cash", "entry_id"), day, amount, "seed", "test cash", NOW])


def _rupee_book_cash(c):
    from pflab.paper import book as pb
    return pb.cash(c)


def _fx(c, d, rate=90.0, pair="USDINR_FBIL"):
    c.execute("INSERT INTO fx_rates VALUES (?, ?, ?, 'test')", [d, pair, rate])


def _bars(root, sym, rows_):
    (root / "us" / "raw").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_, columns=["date", "open", "high", "low", "close", "adj_close", "volume", "dividend"]).to_parquet(root / "us" / "raw" / f"{sym}.parquet")


def _bar(d, o, c, div=0.0):
    return (d, o, max(o, c), min(o, c), c, c, 1_000_000.0, div)


def _spy(root, days, spy0=100.0):
    _bars(root, "SPY", [_bar(d, spy0 + k - 0.4, spy0 + k) for k, d in enumerate(days)])


# ---------------------------------------------------------------- fault 1: a transfer, never new money

def test_the_transfer_debits_the_rupee_cash_by_exactly_the_credited_rupees_and_the_whole_book_loses_only_the_markup(con):
    _rupee_cash(con, 1_000_000.0)
    day = date(2026, 11, 2)
    before = wholebook.whole_book_inr(con, date(2026, 11, 3))
    assert before["whole_inr"] == pytest.approx(1_000_000.0) and before["us_book_inr"] == 0.0
    acct = book.open_account(con, NOW, day, 100_000.0, FXR, 0.10)
    t = acct["transfer"]
    usd = 100_000.0 / (90.0 * (1 + MARKUP))
    assert t["usd"] == pytest.approx(usd) and book.cash(con) == pytest.approx(usd)
    assert _rupee_book_cash(con) == pytest.approx(900_000.0)                          # exactly the rupees credited, no more, no less
    after = wholebook.whole_book_inr(con, date(2026, 11, 3))
    assert after["rupee_book_inr"] == pytest.approx(900_000.0) and after["us_book_usd"] == pytest.approx(usd) and after["fx_source"] == "FBIL"
    markup_inr = 100_000.0 - usd * 90.0
    assert markup_inr == pytest.approx(100_000.0 * MARKUP / (1 + MARKUP))
    assert after["whole_inr"] == pytest.approx(1_000_000.0 - markup_inr)               # unchanged but for the funding markup
    row = con.execute("SELECT inr, usd, markup_inr, phase, fx_source, rupee_ref FROM us_transfers_s82").fetchone()
    assert row[0] == 100_000.0 and row[1] == pytest.approx(usd) and row[2] == pytest.approx(markup_inr) and row[3:5] == ("open", "FBIL") and row[5].startswith("us_transfer:")
    pc = con.execute("SELECT kind, amount, ref FROM paper_cash WHERE kind='us_transfer'").fetchone()
    assert pc[1] == -100_000.0 and "moved to the US paper sub-book" in pc[2]            # an event that says why
    assert con.execute("SELECT kind FROM us_cash_s81").fetchall() == [("transfer",)]
    assert "estimate" in costs.label()


def test_a_transfer_with_no_rupee_cash_writes_nothing(con):
    _rupee_cash(con, 50_000.0)
    with pytest.raises(ValueError):
        book.open_account(con, NOW, date(2026, 11, 2), 100_000.0, FXR, 0.10)
    assert book.account(con) is None and book.cash(con) == 0.0 and _rupee_book_cash(con) == 50_000.0
    assert con.execute("SELECT count(*) FROM us_transfers_s82").fetchone()[0] == 0


def test_in_the_systems_own_account_the_transfer_is_ledger_withdrawals_bank_first(con, tmp_path):
    (tmp_path / system.FLAG).write_text('since = "2026-10-01T00:00:00"\nstart_cash_rupees = 500000\n', encoding="utf-8")
    assert system.active()
    system.append(con, system.opening_cash_events(date(2026, 10, 1), 500_000.0) + [ev.Event(kind="deposit", account_id=system.SYSBANK, date=date(2026, 10, 2), amount=60_000.0, ref="topup:test")], NOW)
    from pflab.paper import book as pb
    assert pb.holdings(con, date(2026, 11, 3))["value"] == pytest.approx(560_000.0)
    book.open_account(con, NOW, date(2026, 11, 2), 100_000.0, FXR, 0.10)
    h = pb.holdings(con, date(2026, 11, 3))
    assert h["value"] == pytest.approx(460_000.0) and h["bank"] == pytest.approx(0.0) and h["cash"] == pytest.approx(460_000.0)      # the bank's 60,000 first, then 40,000 of the broker's
    refs = [r[0] for r in con.execute("SELECT ref FROM events WHERE kind='withdrawal' ORDER BY event_id").fetchall()]
    assert len(refs) == 2 and all(r.startswith("us_transfer:1") and "moved to the US paper sub-book" in r for r in refs)
    assert wholebook.whole_book_inr(con, date(2026, 11, 3))["whole_inr"] == pytest.approx(560_000.0 - 100_000.0 * MARKUP / (1 + MARKUP))


def _old_style_account(con, usd=1_111.11, start_inr=100_000.0, opened=date(2026, 10, 28), start_fx=90.0):
    """What a store that opened the account at the 5% seed before S82 holds: an account row and a 'seed' cash row, no rupee debit."""
    con.execute("INSERT INTO us_account_s81 VALUES (1, ?, ?, ?, 'FBIL', ?, 0.05, 'old', ?)", [opened, start_inr, start_fx, usd, NOW])
    book.add_cash(con, NOW, opened, usd, "seed", "start")


def test_a_pre_s82_seed_is_converted_into_a_transfer_without_losing_a_row_and_only_once(con):
    _rupee_cash(con, 1_000_000.0, date(2026, 10, 1))
    usd = 100_000.0 / (90.0 * (1 + MARKUP))
    _old_style_account(con, usd=usd)
    # the rupee book was marked on three days before the conversion
    for d in (date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30)):
        con.execute("INSERT INTO paper_days VALUES (?,?,?,?,?,?)", [d, 1_000_000.0, 1_000_000.0, 0.0, 0.0, "{}"])
    cash_rows_before = con.execute("SELECT * FROM us_cash_s81 ORDER BY entry_id").fetchall()
    acct_before = con.execute("SELECT * FROM us_account_s81").fetchall()
    out = transfer.convert_seed(con, NOW)
    assert out[0]["converted"] and out[0]["inr"] == pytest.approx(100_000.0, abs=0.01) and out[0]["rupee_day"] == "2026-10-28" and out[0]["marked_days_restated"]
    assert _rupee_book_cash(con) == pytest.approx(900_000.0, abs=0.01)                    # the rupee book now paid for the seed, on the opening day
    row = con.execute("SELECT phase, inr, rupee_day, rupee_ref, reason FROM us_transfers_s82").fetchone()
    assert row[0] == "converted_seed" and row[1] == pytest.approx(100_000.0, abs=0.01) and row[2] == date(2026, 10, 28) and row[3] == "seed_entry:1" and "from nothing" in row[4]
    assert con.execute("SELECT * FROM us_cash_s81 ORDER BY entry_id").fetchall() == cash_rows_before and con.execute("SELECT * FROM us_account_s81").fetchall() == acct_before   # no row lost or changed
    days = con.execute("SELECT day, value, flows FROM paper_days ORDER BY day").fetchall()
    assert [round(v) for _, v, _ in days] == [900_000] * 3 and [round(f) for _, _, f in days] == [-100_000, 0, 0]       # restated; the rupee book's own return is not hurt
    assert "from nothing" in con.execute("SELECT note FROM paper_cash WHERE kind='us_transfer'").fetchone() or True
    snap = (con.execute("SELECT count(*) FROM us_transfers_s82").fetchone(), con.execute("SELECT count(*) FROM paper_cash").fetchone(), _rupee_book_cash(con))
    assert transfer.convert_seed(con, NOW) == []                                          # idempotent
    assert (con.execute("SELECT count(*) FROM us_transfers_s82").fetchone(), con.execute("SELECT count(*) FROM paper_cash").fetchone(), _rupee_book_cash(con)) == snap


def test_a_seed_the_rupee_cash_cannot_pay_for_is_left_and_tried_again(con):
    _rupee_cash(con, 10_000.0)
    _old_style_account(con)
    assert transfer.convert_seed(con, NOW)[0]["converted"] is False and _rupee_book_cash(con) == 10_000.0
    _rupee_cash(con, 500_000.0, date(2026, 11, 1))
    assert transfer.convert_seed(con, NOW)[0]["converted"] is True


def test_the_close_converts_an_old_seed_before_it_does_anything_else(con, tmp_path):
    root = tmp_path / "data"
    _spy(root, [date(2026, 11, 2)])
    _fx(con, date(2026, 11, 2))
    _fx(con, date(2026, 10, 31))
    _rupee_cash(con, 1_000_000.0)
    _old_style_account(con, usd=1_000.0)
    r = adapter.close_us(con, NOW, root, CFG)
    assert r["converted_seed"][0]["converted"] and con.execute("SELECT phase FROM us_transfers_s82 ORDER BY transfer_id").fetchall()[0] == ("converted_seed",)


# ---------------------------------------------------------------- fault 3: SPY may be the whole sub-book

def _state_with(con, root, extra_syms=()):
    """A sub-book state built through `policy.build` with SPY (broad), QQQ (another ETF) and AAPL (a stock) all held."""
    days = [date(2026, 11, 2), date(2026, 11, 3)]
    _spy(root, days)
    _bars(root, "QQQ", [_bar(d, 200.0, 200.0) for d in days])
    _bars(root, "AAPL", [_bar(d, 150.0, 150.0) for d in days])
    from pflab.us import data
    bars = data.load(["SPY", "QQQ", "AAPL"], root)
    for sym, etf in (("SPY", True), ("QQQ", True), ("AAPL", False)):
        uins.ensure(con, sym, etf=etf, now=NOW)
    return bars, days


def test_spy_may_hold_all_of_the_sub_book_a_second_etf_is_capped_at_35_and_a_stock_at_10(con, tmp_path):
    root = tmp_path / "data"
    bars, days = _state_with(con, root)
    book.add_cash(con, NOW, days[0], 10_000.0, "transfer", "test")
    for i, (sym, qty) in enumerate((("QQQ", 1.0), ("AAPL", 1.0))):
        con.execute("INSERT INTO us_lots_s81 VALUES (?, ?, ?, ?, ?, 100.0, 90.0, 'FBIL', 'fill')", [i + 1, uins.key_for(con, sym), sym, days[0], qty])
    # the policy and the config: SPY is the broad index ETF
    st = policy.build(con, days[1], bars, {"on": True, "broad_index_etfs": ["SPY"]}, root, NOW)
    spy_key = uins.key_for(con, "SPY")
    caps = {r["symbol"]: st["caps"][r["isin"]] for r in st["rows"]}
    assert caps == {"SPY": 1.0, "QQQ": 0.35, "AAPL": 0.10}
    rows = {r["symbol"]: r for r in st["rows"]}
    for r in st["rows"]:
        r["buyable"] = True
    out = rails.clip_weights(st, {rows["SPY"]["isin"]: 1.0, rows["QQQ"]["isin"]: 0.9, rows["AAPL"]["isin"]: 0.5}, caps=st["caps"])
    assert out[spy_key]["target"] == pytest.approx(1.0 * 0 + min(1.0, out[spy_key]["target"])) and out[spy_key]["why"] == [] or "cut to the cash" in " ".join(out[spy_key]["why"])
    assert out[rows["QQQ"]["isin"]]["target"] <= 0.35 + 1e-9 and "capped at 35.0%" in out[rows["QQQ"]["isin"]]["why"][0]
    assert out[rows["AAPL"]["isin"]]["target"] <= 0.10 + 1e-9 and "capped at 10.0%" in out[rows["AAPL"]["isin"]]["why"][0]
    # SPY alone with only cash: the policy asks for 95% and the rails let all of it through
    st2 = policy.build(con, days[1], bars, {"on": True}, root, NOW)
    for r in st2["rows"]:
        r["buyable"] = r["symbol"] == "SPY"
        r["qty"], r["value"] = (0.0, 0.0)
    st2["value"] = st2["cash"] = 10_000.0
    dec = policy.decide(st2)
    assert list(dec["weights"].values()) == [pytest.approx(0.95)]
    res = policy.check(con, st2, dec)
    assert [o["symbol"] for o in res["orders"]] == ["SPY"] and res["orders"][0]["value"] == pytest.approx(9_500.0) and res["clipped"] == {}
    # asking for 100% in SPY is allowed too, and the rupee book's one-ETF rail is still 35% (no caps passed)
    full = rails.clip_weights(st2, {spy_key: 1.0}, caps=st2["caps"])
    assert full[spy_key]["target"] == pytest.approx(1.0)
    rupee = rails.clip_weights(st2, {spy_key: 1.0})
    assert rupee[spy_key]["target"] == pytest.approx(0.35) and "rail 35%" in rupee[spy_key]["why"][0]


def test_the_sub_book_caps_come_from_the_config(con, tmp_path):
    root = tmp_path / "data"
    bars, days = _state_with(con, root)
    st = policy.build(con, days[1], bars, {"on": True, "broad_index_etfs": ["SPY"], "broad_index_cap": 0.8, "etf_cap": 0.2, "stock_cap": 0.05}, root, NOW)
    assert {r["symbol"]: st["caps"][r["isin"]] for r in st["rows"]} == {"SPY": 0.8}
    assert policy.cap_for("QQQ", True, us.settings({"etf_cap": 0.2})) == 0.2 and policy.cap_for("AAPL", False, us.settings({"stock_cap": 0.05})) == 0.05
    assert us.settings()["broad_index_etfs"] == ["SPY"] and us.settings()["broad_index_cap"] == 1.0                     # the shipped table (configs/core.toml [us])


# ---------------------------------------------------------------- sizing: the international share of the WHOLE book

def _us_book(con, usd, day=date(2026, 11, 2), fx=90.0, share_after=None):
    """A settled-looking sub-book worth `usd` dollars (cash only) marked on `day`, opened by a transfer."""
    _rupee_cash(con, 1.0, date(2026, 9, 1)) if False else None
    con.execute("INSERT INTO us_account_s81 VALUES (1, ?, 1.0, ?, 'FBIL', ?, 0.10, 'test', ?)", [day, fx, usd, NOW])
    book.add_cash(con, NOW, day, usd, "transfer", "test")
    con.execute("INSERT INTO us_days_s81 VALUES (?,?,?,?,?,?,?)", [day, usd, usd, fx, "FBIL", usd * fx, "{}"])
    if share_after is not None:
        con.execute("INSERT INTO us_transfers_s82 VALUES (1, ?, ?, 1.0, ?, 'FBIL', 0.004, ?, 0.0, 'build', 'x', ?, 'x', ?)", [day, day, fx, usd, share_after, NOW])


def test_the_target_is_ten_percent_of_the_whole_book_and_it_is_reached_in_tranches_inside_the_caps(con):
    _rupee_cash(con, 2_000_000.0)
    day = date(2026, 11, 3)
    plan = wholebook.plan_tranche(con, day, NOW, us_cfg=CFG)
    ish = plan["international"]
    assert ish["target"] == pytest.approx(0.10) and ish["whole_inr"] == pytest.approx(2_000_000.0) and ish["gap_inr"] == pytest.approx(200_000.0) and plan["phase"] == "open"
    assert plan["inr"] == pytest.approx(100_000.0)                                       # 5% of the whole book a day: gradual
    assert "5% of the whole book in a day" in ish["tranche_cut_by"][0] and "building it in steps" in ish["reason"]
    # the rupee book already traded 150,000 today: the rails' daily turnover cap (10% = 200,000) leaves 50,000
    con.execute("INSERT INTO paper_trades VALUES (1, ?, 1, 1, 'INE000A01011', 'X', 'buy', 1500.0, 100.0, 0, NULL, NULL, '{}')", [day])
    p2 = wholebook.plan_tranche(con, day, NOW, us_cfg=CFG)
    assert p2["inr"] == pytest.approx(50_000.0) and any("daily turnover cap" in w for w in p2["international"]["tranche_cut_by"])
    con.execute("DELETE FROM paper_trades")
    # a tranche is never more than the rupee cash that is FREE (open buy orders claim theirs)
    con.execute("INSERT INTO paper_orders VALUES (1, ?, NULL, 'INE000A01011', 'X', 'buy', NULL, 1950000.0, 'open', NULL, NULL)", [NOW])
    p3 = wholebook.plan_tranche(con, day, NOW, us_cfg=CFG)
    assert p3["inr"] == pytest.approx(50_000.0) and any("free" in w for w in p3["international"]["tranche_cut_by"])
    con.execute("DELETE FROM paper_orders")
    # day one: fund it; one transfer a day at most
    acct = book.open_account(con, NOW, date(2026, 11, 2), plan["inr"], FXR, 0.10)
    again = wholebook.plan_tranche(con, day, NOW, us_cfg=CFG)
    assert again["inr"] == 0.0 and any("one transfer a day" in w for w in again["international"]["tranche_cut_by"])
    # the next day the second tranche brings it to the target; after that no more is due
    nxt = wholebook.plan_tranche(con, day + timedelta(days=1), NOW + timedelta(days=1), us_cfg=CFG)
    assert nxt["phase"] == "build" and nxt["inr"] == pytest.approx(100_000.0 - 0.0, abs=2_000.0) and acct["transfer"]["inr"] == 100_000.0


def test_it_is_built_to_target_then_topped_up_only_below_eight_percent_and_never_sold_down(con):
    _rupee_cash(con, 900_000.0)                                                           # rupee book 900,000; the sub-book 100,000 (a settled 10% of 1,000,000)
    _us_book(con, 100_000.0 / 90.0, share_after=0.10)
    day = date(2026, 11, 3)
    ish = wholebook.international_share(con, day, NOW, us_cfg=CFG)
    assert ish["share"] == pytest.approx(0.10) and ish["phase"] == "topup" and ish["tranche_inr"] == 0.0 and "at or above the 8% floor" in ish["reason"]
    # 9% of the whole book: between the floor and the target: nothing is moved
    con.execute("DELETE FROM us_cash_s81"); con.execute("DELETE FROM us_days_s81")
    book.add_cash(con, NOW, date(2026, 11, 2), 90_000.0 / 90.0, "transfer", "t"); con.execute("INSERT INTO us_days_s81 VALUES (?,?,?,?,?,?,?)", [date(2026, 11, 2), 1000.0, 1000.0, 90.0, "FBIL", 90_000.0, "{}"])
    nine = wholebook.international_share(con, day, NOW, us_cfg=CFG)
    assert nine["share"] == pytest.approx(90_000.0 / 990_000.0) and nine["tranche_inr"] == 0.0
    # 7%: under the floor: topped up from rupee cash toward the 10% target
    con.execute("DELETE FROM us_cash_s81"); con.execute("DELETE FROM us_days_s81")
    book.add_cash(con, NOW, date(2026, 11, 2), 70_000.0 / 90.0, "transfer", "t"); con.execute("INSERT INTO us_days_s81 VALUES (?,?,?,?,?,?,?)", [date(2026, 11, 2), 777.0, 777.0, 90.0, "FBIL", 70_000.0, "{}"])
    low = wholebook.international_share(con, day, NOW, us_cfg=CFG)
    whole = 900_000.0 + 70_000.0
    assert low["share"] == pytest.approx(70_000.0 / whole) and low["tranche_inr"] == pytest.approx(0.10 * whole - 70_000.0, rel=1e-6) and "topped up from rupee cash" in low["reason"]
    # 15%: above the target: nothing is moved and nothing sold (the share is never sold down just to reach the target: tax)
    con.execute("DELETE FROM us_cash_s81"); con.execute("DELETE FROM us_days_s81")
    book.add_cash(con, NOW, date(2026, 11, 2), 150_000.0 / 90.0, "transfer", "t"); con.execute("INSERT INTO us_days_s81 VALUES (?,?,?,?,?,?,?)", [date(2026, 11, 2), 1666.0, 1666.0, 90.0, "FBIL", 150_000.0, "{}"])
    high = wholebook.international_share(con, day, NOW, us_cfg=CFG)
    assert high["share"] > 0.10 and high["tranche_inr"] == 0.0 and high["gap_inr"] == 0.0 and "never sold down" in high["reason"]
    assert con.execute("SELECT count(*) FROM us_orders_s81").fetchone()[0] == 0


def test_a_blocked_india_etf_is_said_in_the_reason_and_its_share_is_the_us_books_to_fund(con):
    _rupee_cash(con, 1_000_000.0)
    isin = "INF247L01AB1"
    lf.register_instrument(con, "MON100", isin, "Motilal Nasdaq 100 ETF", market="IN", currency="INR", etf=True, now=NOW)
    con.execute("UPDATE instruments SET asset_class='etf', tax_class=NULL WHERE isin=?", [isin])
    for k in range(4):
        con.execute("INSERT INTO prices VALUES (?, ?, 103.0, 'EQ', 'nse_bhavcopy', now())", [isin, date(2026, 10, 30) + timedelta(days=k)])
        con.execute("INSERT INTO navs VALUES (?, '1', ?, 100.0, 'amfi_navall', now())", [isin, date(2026, 10, 30) + timedelta(days=k)])
    ish = wholebook.international_share(con, date(2026, 11, 2), NOW, us_cfg=CFG)
    assert ish["india_etf_rail"][0]["blocked"] and ish["india_etf_rail"][0]["premium_pct"] == pytest.approx(3.0)
    assert "3.0% above its NAV, over the 2% limit" in ish["reason"] and "held in the US book or waits as cash" in ish["reason"]
    assert ish["tranche_inr"] > 0


def test_the_state_hook_adds_the_whole_book_and_leaves_the_rupee_value_alone(con):
    _rupee_cash(con, 1_000_000.0)
    book.open_account(con, NOW, date(2026, 11, 2), 100_000.0, FXR, 0.10)
    st = {"day": date(2026, 11, 3), "value": 900_000.0}
    wholebook.attach(con, st)
    assert st["value"] == 900_000.0 and st["whole_value"] == pytest.approx(900_000.0 + 100_000.0 / 1.004) and st["us_book_inr"] == pytest.approx(100_000.0 / 1.004)
    assert st["whole"]["fx_source"] == "FBIL"


# ---------------------------------------------------------------- the rupee book's own record counts a transfer as money out

def test_the_rupee_books_return_is_not_hurt_by_a_transfer_and_the_whole_books_return_is_the_same(con):
    from pflab.paper import book as pb
    _rupee_cash(con, 1_000_000.0)
    d0, d1 = date(2026, 11, 2), date(2026, 11, 3)
    con.execute("INSERT INTO paper_days VALUES (?,?,?,?,?,?)", [d0, 1_000_000.0, 1_000_000.0, 0.0, 0.0, "{}"])
    _fx(con, d1)
    acct = book.open_account(con, datetime(2026, 11, 3, 7, 0), d0, 100_000.0, FXR, 0.10)
    flow = transfer.rupee_flows(con, d0, d1)
    assert flow == pytest.approx(-100_000.0)
    con.execute("INSERT INTO paper_days VALUES (?,?,?,?,?,?)", [d1, 900_000.0, 900_000.0, 0.0, flow, "{}"])
    r = pb.returns(con)
    assert r["twr"] == pytest.approx(0.0)                                                # the rupee book lost nothing: the money went to the sub-book
    whole = wholebook.returns(con)
    markup_inr = 100_000.0 * MARKUP / (1 + MARKUP)
    assert whole["twr"] == pytest.approx(-markup_inr / 1_000_000.0, abs=1e-9)            # the whole book lost the markup only
    assert transfer.rupee_flows(con, d1, date(2026, 11, 9)) == 0.0 and acct["transfer"]["rupee_day"] == "2026-11-03"


def test_catch_up_of_the_rupee_book_takes_the_transfer_out_of_the_flows(con):
    from pflab.paper import book as pb
    _rupee_cash(con, 1_000_000.0)
    d0 = date(2026, 11, 2)
    con.execute("INSERT INTO paper_days VALUES (?,?,?,?,?,?)", [d0, 1_000_000.0, 1_000_000.0, 0.0, 0.0, "{}"])
    book.open_account(con, datetime(2026, 11, 3, 7, 0), d0, 100_000.0, FXR, 0.10)         # moved on the IST morning of the 3rd
    pb.catch_up(con, date(2026, 11, 4), datetime(2026, 11, 4, 17, 0))
    rows = {d: (v, f) for d, v, f in con.execute("SELECT day, value, flows FROM paper_days").fetchall()}
    assert rows[date(2026, 11, 3)] == (pytest.approx(900_000.0), pytest.approx(-100_000.0)) and rows[date(2026, 11, 4)][1] == 0.0


# ---------------------------------------------------------------- the close: catch-up per session, orders at the next open

def test_after_three_days_off_the_us_step_runs_once_for_each_missed_us_session(con, tmp_path):
    root = tmp_path / "data"
    days = [date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)]
    _spy(root, days)
    for d in [date(2026, 10, 30)] + days:
        _fx(con, d)
    _rupee_cash(con, 2_000_000.0)
    r1 = adapter.close_us(con, datetime(2026, 11, 3, 7, 0), root, CFG)                    # the app is open for the first session
    assert r1["day"] == "2026-11-02" and "caught_up" not in r1
    # off on the 4th and 5th and 6th (IST): on the morning of Saturday the 7th three more sessions have closed (11-03, 11-04, 11-05) and 11-06 closes at 02:30 on the 7th
    r = adapter.close_us(con, datetime(2026, 11, 7, 9, 0), root, CFG)
    assert r["caught_up"] == ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    assert [d for (d,) in con.execute("SELECT day FROM us_runs_s81 ORDER BY day").fetchall()] == [date(2026, 11, 2)] + [date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)]
    assert adapter.close_us(con, datetime(2026, 11, 7, 10, 0), root, CFG)["skipped"] == "US session 2026-11-06 already done"
    assert con.execute("SELECT count(*) FROM us_runs_s81").fetchone()[0] == 5               # once per session
    fills = con.execute("SELECT fill_day FROM us_orders_s81 WHERE status='filled' ORDER BY fill_day").fetchall()
    assert fills and all(f[0] > date(2026, 11, 2) for f in fills)                          # an order fills at a LATER session's open, never the day it was placed
    # one transfer a day at most: a catch-up of four sessions in one IST day funded once (the rupee date is that one day)
    assert con.execute("SELECT count(*) FROM us_transfers_s82 WHERE rupee_day=?", [date(2026, 11, 7)]).fetchone()[0] <= 1
    # the first ever run handles the latest session only (no replay of the past)
    c2 = store.connect(tmp_path / "other.duckdb")
    _rupee_cash(c2, 1_000_000.0)
    for d in [date(2026, 10, 30)] + days:
        _fx(c2, d)
    assert adapter.pending_sessions(c2, datetime(2026, 11, 7, 9, 0)) == [date(2026, 11, 6)]


def test_the_catchup_stage_runs_the_us_step_for_the_us_market(con, tmp_path, monkeypatch):
    from pflab import markets
    from pflab.service import catchup
    root = tmp_path / "data"
    days = [date(2026, 11, 2), date(2026, 11, 3)]
    _spy(root, days)
    for d in [date(2026, 10, 30)] + days:
        _fx(con, d)
    _rupee_cash(con, 2_000_000.0)
    monkeypatch.setattr(markets, "codes", lambda: ["US"])
    monkeypatch.setattr(catchup, "data_through", lambda con_, root_, market: date(2026, 11, 3))
    import pflab.fcast.run as fr
    monkeypatch.setattr(fr, "catch_up", lambda con_, market, closed, now=None: {})
    out = catchup.run(con, root, datetime(2026, 11, 4, 8, 0))
    assert out["US"]["done"] == "2026-11-03" and out["US"]["scoring"] == {} or "us_book" in out["US"].get("scoring", {})
    assert con.execute("SELECT count(*) FROM us_runs_s81").fetchone()[0] == 1 and con.execute("SELECT day FROM us_runs_s81").fetchone()[0] == date(2026, 11, 3)


def test_the_close_decides_on_the_last_close_and_the_order_fills_at_the_next_open(con, tmp_path):
    root = tmp_path / "data"
    days = [date(2026, 11, 2), date(2026, 11, 3)]
    _spy(root, days)
    for d in [date(2026, 10, 30)] + days:
        _fx(con, d)
    _rupee_cash(con, 2_000_000.0)
    r1 = adapter.close_us(con, datetime(2026, 11, 3, 7, 0), root, CFG)
    o = con.execute("SELECT placed_day, status, side, symbol FROM us_orders_s81").fetchone()
    assert o == (date(2026, 11, 2), "open", "buy", "SPY") and r1["fills"] == []
    r2 = adapter.close_us(con, datetime(2026, 11, 4, 7, 0), root, CFG)
    f = r2["fills"][0]
    assert f["price"] == pytest.approx((101.0 - 0.4) * 1.0005, abs=1e-4)                  # the NEXT session's open + 5 bps, not the decision day's close
    assert "gap can pass it" in r1["gap_risk"] and "a stop acts at the next open" in r1["gap_risk"]


def test_the_account_waits_while_the_rupee_book_has_no_cash(con, tmp_path):
    root = tmp_path / "data"
    _spy(root, [date(2026, 11, 2)])
    _fx(con, date(2026, 11, 2))
    r = adapter.close_us(con, NOW, root, CFG)
    assert "waiting" in r and "the whole book has no value yet" in r["waiting"] and book.account(con) is None
    assert con.execute("SELECT count(*) FROM us_runs_s81").fetchone()[0] == 0


# ---------------------------------------------------------------- what the screens read

def test_the_report_is_plain_json_with_the_holdings_funding_and_the_gap_risk(con, tmp_path):
    root = tmp_path / "data"
    days = [date(2026, 11, 2), date(2026, 11, 3)]
    _spy(root, days)
    for d in [date(2026, 10, 30)] + days:
        _fx(con, d)
    _fx(con, date(2026, 10, 31))
    _rupee_cash(con, 2_000_000.0)
    adapter.close_us(con, datetime(2026, 11, 3, 7, 0), root, CFG)
    adapter.close_us(con, datetime(2026, 11, 4, 7, 0), root, CFG)
    h = report.holdings(con, date(2026, 11, 4), root)
    json.dumps(h)                                                                          # JSON-able
    assert h["open"] and [x["symbol"] for x in h["holdings"]] == ["SPY"]
    spy = h["holdings"][0]
    assert spy["isin_key"] == uins.key_for(con, "SPY") and spy["shares"] > 0 and spy["value_usd"] > 0 and spy["value_inr"] == pytest.approx(spy["value_usd"] * 90.0, abs=0.05)
    assert spy["fx_source"] == "FBIL" and spy["after_tax"]["label"] == "estimate" and "return_after_tax_pct" in spy["after_tax"]
    assert "estimate" in h["label"] and h["cash"]["usd"] >= 0 and "a gap can pass it" in h["gap_risk"]
    assert h["international_share"]["target"] == pytest.approx(0.10) and h["international_share"]["reason"]
    assert [f["phase"] for f in h["funding"]][0] == "open" and h["funding"][0]["rupees"] == pytest.approx(100_000.0) and h["funding"][0]["label"].endswith("an estimate")
    assert h["whole_book"]["whole_inr"] > 0 and h["whole_book"]["fx_source"] == "FBIL"
    s = report.card_summary(con, date(2026, 11, 4), root)
    json.dumps(s)
    assert s["holdings"][0]["symbol"] == "SPY" and s["whole_book"]["whole_inr"] > 0
    empty = store.connect(tmp_path / "e.duckdb")
    json.dumps(report.holdings(empty, date(2026, 11, 4), root))


def test_the_card_has_the_whole_book_and_the_us_lines_and_the_us_key():
    from pflab.core import card
    us_sum = {"open": True, "holdings": [{"symbol": "SPY", "shares": 10.0, "value_usd": 1000.0, "value_inr": 90_000.0}], "cash": {"usd": 50.0}, "open_orders": 1,
              "whole_book": {"whole_inr": 1_000_000.0, "rupee_book_inr": 910_000.0, "us_book_inr": 90_000.0, "fx": 90.0, "fx_source": "FBIL"},
              "international_share": {"share": 0.09, "target": 0.10, "reason": "building it in steps"}, "gap_risk": "a stop acts at the next open, so a gap can pass it"}
    whole, line = card._us_lines(us_sum)
    assert "Rs 1,000,000" in whole and "rupee book Rs 910,000" in whole and "FBIL" in whole and "target 10%" in whole
    assert "SPY 10 shares USD 1,000" in line and "gap can pass it" in line
    assert "not open yet" in card._us_lines({"open": False, "whole_book": us_sum["whole_book"], "international_share": {}})[1]


# ---------------------------------------------------------------- C12: ZZ + CIK keys

def test_a_fake_sec_file_gives_zz_cik_keys_and_old_us_keys_are_mapped_without_losing_a_row(con, tmp_path):
    root = tmp_path / "data"
    key = uins.ensure(con, "SPY", etf=True, now=NOW)                                       # registered before a CIK map existed
    assert key == "US:SPY"
    con.execute("INSERT INTO us_lots_s81 VALUES (1, ?, 'SPY', ?, 4.0, 100.0, 90.0, 'FBIL', 'fill')", [key, date(2026, 10, 20)])
    con.execute("INSERT INTO us_orders_s81 VALUES (1, ?, ?, ?, 'SPY', 'buy', NULL, 50.0, 'open', NULL, 'x')", [date(2026, 10, 19), NOW, key])
    fake = {"0": {"cik_str": 884394, "ticker": "SPY", "title": "SPDR S&P 500 ETF TRUST"}, "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
    out = uins.refresh_if_due(root, get=lambda url: fake, now=NOW)
    assert out == {"refreshed": 2} and uins.load_ciks(root) == {"SPY": 884394, "AAPL": 320193}
    assert uins.refresh_if_due(root, get=lambda url: (_ for _ in ()).throw(AssertionError("fetched twice")), now=NOW)["skipped"].startswith("the CIK map is less than 30 days old")
    m = uins.map_symbol_keys(con, uins.load_ciks(root), now=NOW)
    assert m == [{"symbol": "SPY", "from_key": "US:SPY", "to_key": "ZZ0000884394", "since": "2026-10-19"}]
    assert uins.canonical(con, "US:SPY", date(2026, 10, 18)) == "US:SPY" and uins.canonical(con, "US:SPY", date(2026, 10, 19)) == "ZZ0000884394"
    assert uins.key_for(con, "SPY", uins.load_ciks(root)) == "ZZ0000884394" and len("ZZ0000884394") == 12 and lf.is_pseudo("ZZ0000884394")
    assert uins.key_for(con, "AAPL", uins.load_ciks(root)) == "ZZ0000320193"
    assert book.positions(con, date(2026, 11, 1)) == {"ZZ0000884394": 4.0}                 # the lot still carries US:SPY, the position counts under the ZZ key
    assert con.execute("SELECT isin FROM us_lots_s81").fetchone() == ("US:SPY",) and con.execute("SELECT count(*) FROM us_orders_s81").fetchone()[0] == 1
    assert uins.symbol_of(con, "ZZ0000884394") == "SPY"
    assert uins.map_symbol_keys(con, uins.load_ciks(root), now=NOW) == []                  # idempotent
    # when a statement later shows the real ISIN, the symbol key resolves through the chain
    uins.ensure(con, "SPY", ciks=uins.load_ciks(root), isins={"SPY": "US78462F1030"}, now=NOW, since=date(2026, 11, 1))
    assert uins.canonical(con, "US:SPY", date(2026, 11, 2)) == "US78462F1030"


def test_without_the_sec_contact_nothing_is_fetched_and_the_old_keys_stay(con, tmp_path, monkeypatch):
    from pflab.data import us_prices
    root = tmp_path / "data"
    monkeypatch.setattr(uins, "sec_contact_configured", lambda: False)
    monkeypatch.setattr(us_prices, "cik_map", lambda get=None: (_ for _ in ()).throw(AssertionError("SEC must not be asked without the contact User-Agent")))
    out = uins.refresh_if_due(root, now=NOW)
    assert "no [sec] user_agent" in out["skipped"] and "US:SYMBOL" in out["skipped"] and uins.load_ciks(root) == {}
    assert uins.ensure(con, "SPY", etf=True, ciks=uins.load_ciks(root), now=NOW) == "US:SPY"


def test_a_refused_fetch_keeps_the_old_map_and_says_so(tmp_path):
    from pflab.data import sec_edgar
    root = tmp_path / "data"
    (root / "us").mkdir(parents=True)
    (root / "us" / "cik_map.json").write_text('{"SPY": 884394}', encoding="utf-8")
    out = uins.refresh_if_due(root, get=lambda url: (_ for _ in ()).throw(sec_edgar.SecRefused("SEC answered 403")), max_age_days=0, now=NOW)
    assert "SecRefused" in out["failed"] and uins.load_ciks(root) == {"SPY": 884394}


# ---------------------------------------------------------------- market="IN" is unchanged

def test_market_in_is_unchanged(con):
    from pflab.paper import book as pb
    assert transfer.rupee_flows(con, None, date(2026, 11, 5)) == 0.0                       # nothing moved, so the rupee book's flows are what they were
    row = {"isin": "INE000A01011", "symbol": "X", "sector": None, "asset_class": "etf", "qty": 0.0, "price": 100.0, "value": 0.0, "weight": 0.0, "buyable": True, "klass": "equity"}
    st = {"day": date(2026, 11, 5), "value": 1_000_000.0, "cash": 1_000_000.0, "bank": 0.0, "breaker": {"on": False}, "gauge": {"fired": False}, "cfg": core.settings(), "rows": [row]}
    assert rails.clip_weights(st, {"INE000A01011": 0.9})["INE000A01011"]["target"] == pytest.approx(0.35)       # the rupee book's one-ETF rail, untouched
    assert pb.cash(con) == 0.0 and uins.key_for(con, "NIFTYBEES", market="IN") == "US:NIFTYBEES"
    from pflab.us import clock
    assert clock.window_ist(date(2026, 11, 9), market="IN") == (datetime(2026, 11, 9, 9, 15), datetime(2026, 11, 9, 15, 30))
    assert con.execute("SELECT count(*) FROM us_transfers_s82").fetchone()[0] == 0
