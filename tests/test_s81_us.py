"""S81 B8 (A53): the premium-to-NAV rail on India-listed international ETFs (phase A) and the paper US sub-book in dollars (phase B). Synthetic data only; every tax and cost figure
below is worked by hand from the rows in configs/us/tax_s81.toml (the arithmetic is written out in the test)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab import core, us
from pflab.core import premium, rails
from pflab.ledger import foreign as lf
from pflab.pm import store
from pflab.us import adapter, book, clock, costs, data, fx as usfx, instruments as uins, rows, tax as ustax

INTL = "INF769K01HP3"            # an international ETF's ISIN (synthetic row; the real one is in the AMFI file)
DOM = "INE000A01011"
NOW = datetime(2026, 11, 9, 12, 0)


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    c = store.connect(tmp_path / "l.duckdb")
    return c


def _prices(c, isin, start, closes, source="nse_bhavcopy"):
    for k, v in enumerate(closes):
        c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', ?, now())", [isin, start + timedelta(days=k), v, source])


def _navs(c, isin, start, navs, source="amfi_navall"):
    for k, v in enumerate(navs):
        c.execute("INSERT INTO navs VALUES (?, '1', ?, ?, ?, now())", [isin, start + timedelta(days=k), v, source])


# ---------------------------------------------------------------- phase A: the premium series and the rail

def test_premium_series_is_close_over_nav_on_the_same_date_only(con):
    d0 = date(2026, 11, 2)
    _prices(con, INTL, d0, [102.0, 103.0, 150.0])                      # closes on 11-02, 11-03, 11-04
    _navs(con, INTL, d0, [100.0, 100.0])                               # a NAV for 11-02 and 11-03 only
    s = premium.premium_series(con, INTL, d0, date(2026, 11, 10))
    assert list(s["date"]) == [d0, d0 + timedelta(days=1)]             # 11-04 has no NAV: it is not a row
    assert list(s["premium_pct"].round(6)) == [2.0, 3.0]
    s2 = premium.premium_series(con, INTL, d0, d0)                      # point in time: nothing after `end`
    assert len(s2) == 1


def test_premium_at_uses_the_latest_pair_and_calls_an_old_nav_unknown(con):
    d0 = date(2026, 11, 2)
    _prices(con, INTL, d0, [102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0])
    _navs(con, INTL, d0, [100.0, 100.0])
    ok = premium.premium_at(con, INTL, date(2026, 11, 5), max_age_days=5)
    assert ok["known"] and ok["premium_pct"] == pytest.approx(3.0) and ok["as_of"] == date(2026, 11, 3) and ok["age_days"] == 2
    old = premium.premium_at(con, INTL, date(2026, 11, 10), max_age_days=5)
    assert old["known"] is False and "days old" in old["why"]
    none = premium.premium_at(con, "INF000000000", date(2026, 11, 10))
    assert none["known"] is False


def _state(prem, weight=0.0, klass="international", asset="etf"):
    total = 1_000_000.0
    return {"day": date(2026, 11, 5), "value": total, "cash": 500_000.0, "bank": 0.0, "breaker": {"on": False}, "gauge": {"fired": False}, "cfg": core.settings(),
            "premium": prem,
            "rows": [{"isin": INTL, "symbol": "MASP500", "sector": None, "asset_class": asset, "qty": 0.0 if weight == 0 else 100.0, "price": 100.0, "value": weight * total, "weight": weight,
                      "buyable": True, "klass": klass}]}


def test_rail_stops_buying_above_the_limit_and_says_why():
    st = _state({INTL: {"known": True, "premium_pct": 3.4, "as_of": date(2026, 11, 4)}})
    out, notes = premium.premium_rail(st, {INTL: 0.10})
    assert out[INTL] == pytest.approx(0.0) and len(notes) == 1
    assert "3.4% above its NAV" in notes[0] and "limit 2.0%" in notes[0] and "MASP500" in notes[0]


def test_rail_scales_the_purchase_between_the_taper_and_the_limit():
    st = _state({INTL: {"known": True, "premium_pct": 1.5, "as_of": date(2026, 11, 4)}}, weight=0.04)
    out, notes = premium.premium_rail(st, {INTL: 0.10})                 # wants +6 points; at 1.5% the share allowed is (2.0 - 1.5) / (2.0 - 1.0) = 50%
    assert out[INTL] == pytest.approx(0.04 + 0.06 * 0.5) and "cut to 50%" in notes[0]
    low, notes2 = premium.premium_rail(_state({INTL: {"known": True, "premium_pct": 0.4, "as_of": date(2026, 11, 4)}}), {INTL: 0.10})
    assert low[INTL] == 0.10 and notes2 == []                          # a small premium: untouched
    assert premium.scale(1.0, 1.0, 2.0) == 1.0 and premium.scale(2.0, 1.0, 2.0) == 0.0 and premium.scale(5.0, 1.0, 2.0) == 0.0


def test_rail_never_blocks_a_sale_or_a_hold_and_skips_an_unknown_premium():
    st = _state({INTL: {"known": True, "premium_pct": 40.0, "as_of": date(2026, 11, 4)}}, weight=0.08)
    out, notes = premium.premium_rail(st, {INTL: 0.02})                 # a sale at a big premium is fine
    assert out[INTL] == 0.02 and notes == []
    out, notes = premium.premium_rail(st, {INTL: 0.08})                 # a hold
    assert out[INTL] == 0.08 and notes == []
    unk = _state({INTL: {"known": False, "premium_pct": None, "why": "no NAV and close of the same date on record"}})
    out, notes = premium.premium_rail(unk, {INTL: 0.10})
    assert out[INTL] == 0.0 and "unknown" in notes[0]
    out, notes = premium.premium_rail(_state({}), {INTL: 0.10})        # never looked up: also unknown
    assert out[INTL] == 0.0 and notes
    out, _ = premium.premium_rail(unk, {INTL: 0.10}, {"premium": {"unknown": "allow"}})
    assert out[INTL] == 0.10


def test_rail_ignores_other_classes_and_can_be_switched_off():
    dom = _state({}, klass="equity", asset="equity")
    out, notes = premium.premium_rail(dom, {INTL: 0.10})
    assert out[INTL] == 0.10 and notes == []
    inter = _state({INTL: {"known": True, "premium_pct": 30.0, "as_of": date(2026, 11, 4)}})
    out, notes = premium.premium_rail(inter, {INTL: 0.10}, {"premium": {"on": False}})
    assert out[INTL] == 0.10 and notes == []
    assert premium.settings()["max_premium_pct"] == 2.0 and premium.settings()["taper_from_pct"] == 1.0       # the shipped defaults (configs/core.toml [premium])


def test_rails_check_places_no_buy_of_a_dear_international_etf_and_records_the_reason(con):
    _prices(con, INTL, date(2026, 11, 2), [100.0, 100.0, 100.0, 100.0])
    _navs(con, INTL, date(2026, 11, 2), [80.0, 80.0, 80.0, 80.0])       # 25% over NAV
    st = _state({})
    st["day"] = date(2026, 11, 5)
    out = rails.check(con, st, {"weights": {INTL: 0.10}})
    assert out["orders"] == []
    assert INTL in out["clipped"] and any("premium rail" in w and "25.0% above its NAV" in w for w in out["clipped"][INTL]["why"])
    assert out["clipped"][INTL]["was"] == 0.10                          # the policy's own wish stays visible
    # the same ETF at its NAV: the order is placed as before
    con.execute("DELETE FROM navs")
    _navs(con, INTL, date(2026, 11, 2), [100.0, 100.0, 100.0, 100.0])
    st2 = _state({})
    out2 = rails.check(con, st2, {"weights": {INTL: 0.10}})
    assert [o["side"] for o in out2["orders"]] == ["buy"] and out2["orders"][0]["amount"] == pytest.approx(100_000.0)


def test_market_in_rails_are_unchanged_when_nothing_is_international(con):
    """A domestic-only book gets the same clip, orders and skips with the rail on or off, and no premium query is made."""
    st = _state({}, klass="equity", asset="equity")
    a = rails.check(con, st, {"weights": {INTL: 0.30}})
    off = _state({}, klass="equity", asset="equity")
    off["cfg"] = {**core.settings(), "premium": {"on": False}}
    b = rails.check(con, off, {"weights": {INTL: 0.30}})
    assert a["orders"] == b["orders"] and a["skipped"] == b["skipped"] and a["clipped"] == b["clipped"]
    assert st["premium"] == {}                                           # attach() found nothing to look up
    assert "premium" not in core.settings() and "us" not in core.settings()      # the shared settings table is untouched
    assert us.on() is False and premium.settings()["unknown"] == "skip"


# ---------------------------------------------------------------- phase B: the US calendar in IST

@pytest.mark.parametrize("session, open_ist, close_ist", [
    (date(2026, 10, 30), datetime(2026, 10, 30, 19, 0), datetime(2026, 10, 31, 1, 30)),     # EDT (UTC-4): 9:30 -> 19:00 IST, 16:00 -> 01:30 IST next day
    (date(2026, 11, 2), datetime(2026, 11, 2, 20, 0), datetime(2026, 11, 3, 2, 30)),        # EST (UTC-5), the first session after DST ended on 2026-11-01
    (date(2027, 3, 12), datetime(2027, 3, 12, 20, 0), datetime(2027, 3, 13, 2, 30)),        # the Friday before DST starts on 2027-03-14
    (date(2027, 3, 15), datetime(2027, 3, 15, 19, 0), datetime(2027, 3, 16, 1, 30)),        # the Monday after
    (date(2026, 11, 27), datetime(2026, 11, 27, 20, 0), datetime(2026, 11, 27, 23, 30)),    # the day after Thanksgiving: 13:00 early close = 23:30 IST
])
def test_us_session_in_ist_follows_daylight_saving(session, open_ist, close_ist):
    assert clock.window_ist(session) == (open_ist, close_ist)
    assert clock.handling_day(session) == close_ist.date()


def test_us_close_is_handled_in_the_ist_morning_and_weekends_and_holidays_are_shut():
    assert clock.window_ist(date(2026, 11, 26)) is None                  # Thanksgiving
    assert clock.window_ist(date(2026, 11, 28)) is None                  # Saturday
    # Monday 2026-11-02 closes at 02:30 IST on the 3rd; the daily bar is settled 30 minutes later
    assert clock.session_closed_by(datetime(2026, 11, 3, 2, 45)) == date(2026, 10, 30)
    assert clock.session_closed_by(datetime(2026, 11, 3, 3, 0)) == date(2026, 11, 2)
    # Friday 2026-11-06 closes Saturday 02:30 IST; on Sunday and Monday morning the latest closed session is still Friday's
    assert clock.session_closed_by(datetime(2026, 11, 8, 12, 0)) == date(2026, 11, 6)
    assert clock.session_closed_by(datetime(2026, 11, 9, 5, 0)) == date(2026, 11, 6)
    assert clock.mode(datetime(2026, 11, 2, 20, 30)) == "session"


def test_the_holiday_file_matches_the_nyse_page_read_on_2026_11_09():
    cal = clock.market().calendar
    for d in (date(2026, 11, 26), date(2026, 12, 25), date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5),
              date(2027, 9, 6), date(2027, 11, 25), date(2027, 12, 24)):
        assert not cal.is_trading_day(d), d
    assert set(cal.early) >= {date(2026, 11, 27), date(2026, 12, 24), date(2027, 11, 26)}


# ---------------------------------------------------------------- phase B: FX at the stated rate

def _fx(c, pair, d, rate):
    c.execute("INSERT INTO fx_rates VALUES (?, ?, ?, 'test')", [d, pair, rate])


def test_fx_prefers_fbil_then_market_close_then_fred_and_states_the_source(con, tmp_path):
    root = tmp_path / "data"
    (root / "global").mkdir(parents=True)
    pd.DataFrame({"date": [date(2026, 11, 4), date(2026, 11, 5)], "close": [93.0, 94.0]}).to_parquet(root / "global" / "FX_USDINR.parquet")
    _fx(con, "USDINR", date(2026, 11, 5), 95.0)
    got = usfx.rate_for(con, date(2026, 11, 5), root)
    assert got["rate"] == 94.0 and got["source"] == "MARKET" and "estimate" in got["label"] and "FBIL" in got["label"]
    _fx(con, "USDINR_FBIL", date(2026, 11, 4), 93.5)
    got = usfx.rate_for(con, date(2026, 11, 5), root)                   # an FBIL rate one day old beats the market close
    assert got["rate"] == 93.5 and got["source"] == "FBIL" and got["age_days"] == 1 and got["label"] == "FBIL reference rate"
    assert usfx.rate_for(con, date(2026, 11, 20), root) is None         # nothing within 4 days


def test_fx_falls_back_to_fred_and_the_tax_rate_is_labelled_an_estimate(con, tmp_path):
    _fx(con, "USDINR", date(2026, 10, 30), 94.94)
    got = usfx.rate_for(con, date(2026, 11, 2), tmp_path / "none")
    assert got["source"] == "FRED" and got["rate"] == 94.94 and "estimate" in got["label"]
    t = usfx.tax_rate(con, date(2026, 11, 20), tmp_path / "none")       # the month-end before 2026-11-20 is 2026-10-31; the latest rate on or before it is the 30th
    assert t["rate"] == 94.94 and t["tax_date"] == date(2026, 10, 31) and "SBI TT buying rate" in t["label"] and t["label"].startswith("estimate")


def test_the_tax_rate_is_the_month_end_before_the_event():
    assert usfx.tax_date(date(2027, 2, 19)) == date(2027, 1, 31)
    assert usfx.tax_date(date(2027, 1, 5)) == date(2026, 12, 31)
    assert usfx.tax_date(date(2026, 3, 1)) == date(2026, 2, 28)


def test_the_start_converts_five_percent_of_the_book_at_the_stated_rate(con):
    fxr = {"rate": 90.0, "source": "FBIL", "rate_day": date(2026, 11, 2), "label": "FBIL reference rate"}
    a = book.open_account(con, NOW, date(2026, 11, 2), 2_000_000.0, fxr, 0.05)
    # 5% of 20,00,000 = 1,00,000 rupees; at 90.0 with the 0.4% funding markup: 100000 / (90 x 1.004)
    assert a["start_inr"] == pytest.approx(100_000.0) and a["start_usd"] == pytest.approx(100_000.0 / (90.0 * 1.004)) and a["fx_source"] == "FBIL"
    assert book.cash(con) == pytest.approx(a["start_usd"]) and "FBIL reference rate" in a["note"] and "0.40%" in a["note"]
    with pytest.raises(ValueError):
        book.open_account(con, NOW, date(2026, 11, 2), 2_000_000.0, fxr, 0.05)


# ---------------------------------------------------------------- phase B: costs, a US buy and sale, tax and withholding

def test_costs_by_hand():
    c = costs.charges("buy", 10, 100.0, date(2026, 11, 3))              # value 1000: brokerage 1.00, IGST 0.18, IFSCA 0.05 (0.005%); no SEC fee or TAF on a buy
    assert c == {"brokerage": 1.0, "igst": 0.18, "ifsca_fee": 0.05, "sec_fee": 0.0, "finra_taf": 0.0, "total": 1.23}
    s = costs.charges("sell", 10, 100.0, date(2026, 11, 3))             # SEC fee 20.60 per million of 1000 = 0.0206; TAF paused 1 Oct - 31 Dec 2026
    assert s["sec_fee"] == pytest.approx(0.0206) and s["finra_taf"] == 0.0 and s["total"] == pytest.approx(1.23 + 0.0206)
    t = costs.charges("sell", 10, 100.0, date(2027, 2, 3))              # after the pause: 10 shares x 0.000195 = 0.00195
    assert t["finra_taf"] == pytest.approx(0.00195)
    small = costs.charges("buy", 0.001, 10.0, date(2026, 11, 3))        # brokerage has a USD 0.01 minimum
    assert small["brokerage"] == 0.01
    big = costs.charges("buy", 1000, 1000.0, date(2026, 11, 3))         # and a USD 10 maximum
    assert big["brokerage"] == 10.0
    assert costs.charges("sell", 10, 100.0, date(2026, 3, 1))["sec_fee"] == 0.0     # the SEC fee was 0.00 before 2026-04-04
    assert "estimate" in costs.label() and "cost_sec_fee_per_million (primary" in costs.label()


def test_dividend_withholding_and_credit_by_hand():
    d = ustax.dividend(100.0, 90.0)                                      # US keeps 25% = USD 25 (treaty Art. 10(2)(b)); gross Rs 9,000; India at the 30% slab = Rs 2,700
    assert d["withheld_usd"] == 25.0 and d["net_usd"] == 75.0 and d["gross_inr"] == 9000.0
    assert d["india_tax_inr"] == pytest.approx(2700.0) and d["withheld_inr"] == 2250.0                  # US tax in rupees: 25 x 90
    assert d["credit_inr"] == pytest.approx(2250.0) and d["residual_tax_inr"] == pytest.approx(450.0)  # the credit is the lower: all of the US tax; India collects the 450 rest
    low = ustax.dividend(100.0, 90.0, slab_rate=0.20)                    # a 20% slab: India's tax (1,800) is below the US tax (2,250): credit 1,800, 450 of US tax is lost
    assert low["credit_inr"] == pytest.approx(1800.0) and low["residual_tax_inr"] == pytest.approx(0.0) and low["excess_us_tax_inr"] == pytest.approx(450.0)
    no_form = ustax.dividend(100.0, 90.0, w8ben=False)                   # no W-8BEN: 30% withheld (Rs 2,700), the whole of India's tax: credit 2,700, nothing more to pay
    assert no_form["withheld_usd"] == 30.0 and no_form["credit_inr"] == pytest.approx(2700.0) and no_form["residual_tax_inr"] == pytest.approx(0.0)
    assert "estimate" in d["label"] and "dtaa_dividend_withholding_individual (primary" in d["label"]


def test_gains_classes_rates_and_set_off_by_hand():
    assert ustax.holding_class(date(2025, 1, 15), date(2027, 1, 15)) == "short"       # exactly 24 months is NOT more than 24 months
    assert ustax.holding_class(date(2025, 1, 15), date(2027, 1, 16)) == "long"
    assert ustax.holding_class(date(2024, 2, 29), date(2026, 2, 28)) == "short"        # leap-day purchase: 24 months on is 2026-02-28
    assert ustax.holding_class(date(2024, 2, 29), date(2026, 3, 1)) == "long"
    p = ustax.lot_gain(10, 100.123, 85.0, 1300.0, 90.0, date(2026, 6, 10), date(2026, 12, 15))   # cost 10 x 100.123 x 85 = 85,104.55; proceeds 1300 x 90 = 117,000
    assert p["cost_inr"] == pytest.approx(85_104.55) and p["gain_inr"] == pytest.approx(31_895.45) and p["class"] == "short"
    assert ustax.sale([p])["tax_inr"] == pytest.approx(0.30 * 31_895.45)               # slab 30% (no 20% rate, no exemption: no STT on a foreign share)
    lt = dict(p, **{"class": "long"})
    assert ustax.sale([lt])["tax_inr"] == pytest.approx(0.125 * 31_895.45)             # 12.5%, no indexation, no exemption
    # a short-term loss of 10,000 offsets a long-term gain of 40,000: tax 12.5% x 30,000 = 3,750
    assert ustax.fy_tax(-10_000.0, 40_000.0) == pytest.approx(3750.0)
    # a long-term loss offsets nothing: the short-term gain is taxed in full, the loss earns nothing
    assert ustax.fy_tax(20_000.0, -50_000.0) == pytest.approx(0.30 * 20_000.0)
    # the second sale of a year adds only what it adds to the year's tax
    q = ustax.sale([dict(p, gain_inr=-5_000.0)], ytd_st=10_000.0)
    assert q["tax_inr"] == 0.0 and ustax.fy_tax(5_000.0, 0.0) < ustax.fy_tax(10_000.0, 0.0)


def _bars(root, sym, rows_):
    (root / "us" / "raw").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_, columns=["date", "open", "high", "low", "close", "adj_close", "volume", "dividend"]).to_parquet(root / "us" / "raw" / f"{sym}.parquet")


def _bar(d, o, c, div=0.0):
    return (d, o, max(o, c), min(o, c), c, c, 1_000_000.0, div)


def test_a_us_buy_a_dividend_and_a_long_term_sale_with_the_tax_and_credit_worked_by_hand(con, tmp_path):
    root = tmp_path / "data"
    key = uins.ensure(con, "SPY", etf=True, ciks={"SPY": 884394}, now=NOW)
    assert key == "ZZ0000884394"
    b_buy, b_div, b_sell = date(2025, 1, 15), date(2025, 6, 12), date(2027, 2, 19)
    _bars(root, "SPY", [_bar(b_buy, 100.0, 100.0), _bar(date(2025, 6, 11), 110.0, 110.0), _bar(b_div, 111.0, 111.0, div=0.5), _bar(b_sell, 130.0, 131.0)])
    bars = data.load(["SPY"], root)
    for d, r in ((date(2024, 12, 31), 85.0), (date(2025, 5, 31), 86.0), (date(2025, 6, 12), 87.0), (date(2027, 1, 31), 90.0), (b_sell, 91.0)):
        _fx(con, "USDINR_FBIL", d, r)
    book.open_account(con, NOW, b_buy, 1_000_000.0, {"rate": 90.0, "source": "FBIL", "rate_day": b_buy, "label": "FBIL reference rate"}, 0.01)
    con.execute("DELETE FROM us_cash_s81")                              # only the cash below matters: start the test with exactly USD 5,000
    book.add_cash(con, NOW, date(2025, 1, 10), 5000.0, "seed", "test")
    # BUY: an order of USD 1,000 placed the day before fills at the open of 2025-01-15 (slippage 0): value + charges = 1,000, charges = 0.123% of the value (0.1% + 18% IGST + 0.005%)
    book.place(con, NOW, date(2025, 1, 14), key, "SPY", "buy", amount_usd=1000.0, reason="test")
    fills = book.fill_orders(con, NOW, b_buy, bars, 0.0)
    qty = 1000.0 / (100.0 * 1.00123)
    assert fills[0]["qty"] == pytest.approx(qty, abs=1e-5) and fills[0]["price"] == 100.0
    lot = book.open_lots(con)[0]
    assert lot["cost_usd_per_share"] == pytest.approx(100.123, abs=1e-6) and lot["fx_tax_acq"] == 85.0       # the rate of 2024-12-31 (the month-end before the purchase)
    assert book.cash(con) == pytest.approx(5000.0 - 1000.0, abs=1e-6)
    # DIVIDEND on 2025-06-12: USD 0.50 a share on the shares held at the previous close
    divs = book.apply_dividends(con, NOW, b_div, bars, w8ben=True, root=root)
    gross = qty * 0.5                                                      # fx at the month-end before (2025-05-31) = 86
    assert divs[0]["gross_usd"] == pytest.approx(gross, abs=1e-4) and divs[0]["withheld_usd"] == pytest.approx(gross * 0.25, abs=1e-4)
    row = con.execute("SELECT gross_inr, india_tax_inr, credit_inr, residual_tax_inr FROM us_dividends_s81").fetchone()
    assert row[0] == pytest.approx(gross * 86.0, rel=1e-6) and row[1] == pytest.approx(gross * 86.0 * 0.30, rel=1e-6)
    assert row[2] == pytest.approx(gross * 0.25 * 86.0, rel=1e-6) and row[3] == pytest.approx(gross * 86.0 * 0.05, rel=1e-6)
    cash_after_div = 4000.0 + gross - gross * 0.25 - (gross * 86.0 * 0.05) / 87.0              # residual rupee tax taken out in dollars at the day's rate (87)
    assert book.cash(con, b_div) == pytest.approx(cash_after_div, abs=1e-3)
    assert book.apply_dividends(con, NOW, b_div, bars, root=root) == []           # once only
    # SALE of all shares, order placed 2027-02-18, filled at the open of 2027-02-19 = 130.0 (slippage 0): held 25 months: LONG-TERM (24 months on is 2027-01-15)
    held = book.positions(con)[key]
    book.place(con, NOW, date(2027, 2, 18), key, "SPY", "sell", qty=held, reason="test")
    sell = book.fill_orders(con, NOW, b_sell, bars, 0.0, root=root)[0]
    v = qty * 130.0
    ch = v * (0.001 + 0.001 * 0.18 + 0.00005 + 20.60 / 1e6) + qty * 0.000195                    # brokerage + IGST + IFSCA + SEC fee + FINRA TAF (the pause ended 2026-12-31)
    gain = (v - ch) * 90.0 - qty * 100.123 * 85.0                                               # proceeds at the 2027-01-31 rate (90), cost at the 2024-12-31 rate (85)
    assert sell["charges_usd"] == pytest.approx(ch, abs=1e-4) and sell["gain_inr"] == pytest.approx(gain, abs=0.05)
    assert sell["tax_inr"] == pytest.approx(0.125 * gain, abs=0.02)                              # long-term: 12.5%, no exemption, nothing to set off
    tr = con.execute("SELECT detail_json FROM us_trades_s81 WHERE side='sell'").fetchone()[0]
    assert '"long"' in tr and "estimate" in tr and "excludes surcharge and cess" in tr
    assert book.open_lots(con) == [] and book.positions(con) == {}
    fy = book.realised_fy(con, ustax.fy_of(b_sell))
    assert fy["long_term_gain_inr"] == pytest.approx(gain, abs=0.05) and fy["capital_gains_tax_inr"] == pytest.approx(0.125 * gain, abs=0.02) and fy["fy"] == "2026-27"
    kinds = [r[0] for r in con.execute("SELECT DISTINCT kind FROM us_cash_s81").fetchall()]
    assert {"buy", "sell", "fee", "dividend", "withholding", "india_tax", "seed"} <= set(kinds)


def test_no_shorting_no_borrowing_and_an_order_waits_for_its_bar(con, tmp_path):
    root = tmp_path / "data"
    key = uins.ensure(con, "SPY", etf=True, now=NOW)
    d1, d2 = date(2026, 11, 3), date(2026, 11, 4)
    _bars(root, "SPY", [_bar(d1, 100.0, 100.0), _bar(d2, 100.0, 101.0)])
    bars = data.load(["SPY"], root)
    _fx(con, "USDINR_FBIL", date(2026, 10, 30), 90.0)
    book.add_cash(con, NOW, d1, 100.0, "seed")
    book.place(con, NOW, d1, key, "SPY", "buy", amount_usd=5000.0, reason="more than the cash")
    f = book.fill_orders(con, NOW, d2, bars, 5.0, root=root)[0]
    assert f["price"] == pytest.approx(100.0 * 1.0005)                          # a buy fills ABOVE the open: never better than it
    assert f["qty"] * f["price"] + f["charges_usd"] <= 100.0 + 1e-9 and book.cash(con) >= -1e-9
    book.place(con, NOW, d2, key, "SPY", "sell", qty=1000.0, reason="more than held")
    book.fill_orders(con, NOW, date(2026, 11, 5), {"SPY": bars["SPY"]}, 5.0, root=root)      # no bar for 11-05 yet: the order waits
    assert [o["side"] for o in book.open_orders(con)] == ["sell"]
    with pytest.raises(ValueError):
        book.plan_sale(con, key, 1000.0, 100.0, 0.0, d2, root)


def test_a_split_in_the_data_rescales_the_lots_and_says_so(con, tmp_path):
    root = tmp_path / "data"
    key = uins.ensure(con, "QQQ", etf=True, now=NOW)
    d1, d2 = date(2026, 11, 3), date(2026, 11, 4)
    _fx(con, "USDINR_FBIL", date(2026, 10, 30), 90.0)
    book.add_cash(con, NOW, d1, 1000.0, "seed")
    con.execute("INSERT INTO us_lots_s81 VALUES (1, ?, 'QQQ', ?, 10.0, 100.0, 90.0, 'FBIL', 'fill')", [key, d1])
    con.execute("INSERT INTO us_days_s81 VALUES (?, 1000.0, 0.0, 90.0, 'FBIL', 90000.0, ?)", [d1, '{"%s": {"symbol": "QQQ", "qty": 10.0, "close": 100.0}}' % key])
    _bars(root, "QQQ", [_bar(d1, 50.0, 50.0), _bar(d2, 50.0, 51.0)])              # the data now shows 2-for-1: yesterday's close is restated 100 -> 50
    ev = book.detect_splits(con, NOW, d2, data.load(["QQQ"], root))
    assert ev == [{"symbol": "QQQ", "kind": "split", "ratio": 2.0}]
    lot = book.open_lots(con)[0]
    assert lot["qty"] == pytest.approx(20.0) and lot["cost_usd_per_share"] == pytest.approx(50.0)
    assert con.execute("SELECT kind FROM us_events_s81").fetchone()[0] == "split"
    assert book._split_ratio(100 / 33.4) == 3.0 and book._split_ratio(100 / 300.0) == pytest.approx(1 / 3.0) and book._split_ratio(1.7) is None


# ---------------------------------------------------------------- ISIN / pseudo-ISIN

def test_keys_real_isin_else_zz_plus_cik_else_the_symbol_key_and_alias_from_a_date(con):
    k1 = uins.ensure(con, "AAPL", name="Apple", ciks={"AAPL": 320193}, now=NOW)
    assert k1 == "ZZ0000320193" and len(k1) == 12 and lf.is_pseudo(k1)
    k2 = uins.ensure(con, "NEWFUND", etf=True, ciks={}, now=NOW)                  # no CIK in SEC's file: the symbol key the panel already uses
    assert k2 == "US:NEWFUND"
    uins.ensure(con, "MSFT", ciks={"MSFT": 789019}, now=NOW)                         # held first under its pseudo-ISIN ...
    k3 = uins.ensure(con, "MSFT", ciks={"MSFT": 789019}, isins={"MSFT": "US5949181045"}, now=NOW, since=date(2026, 11, 1))   # ... then a statement shows the real ISIN
    assert uins.ensure(con, "ORCL", isins={"ORCL": "US68389X1054"}, ciks={"ORCL": 1341439}, now=NOW) == "US68389X1054"      # a real ISIN known at the start IS the key
    assert k3 == "ZZ0000789019" and uins.canonical(con, k3, date(2026, 10, 31)) == k3 and uins.canonical(con, k3, date(2026, 11, 2)) == "US5949181045"
    assert uins.key_for(con, "AAPL", ciks={"AAPL": 1}) == k1                        # a registered symbol keeps its key (never re-keyed by a changed map)
    row = con.execute("SELECT market, currency, tax_class, asset_class FROM instruments WHERE isin=?", [k2]).fetchone()
    assert row == ("US", "USD", "FOREIGN", "etf")
    assert uins.symbol_of(con, k1) == "AAPL" and uins.symbol_of(con, "US:ZZZ") == "ZZZ"


def test_a_position_under_the_pseudo_key_and_one_under_the_real_isin_are_one_position(con):
    k = uins.ensure(con, "MSFT", ciks={"MSFT": 789019}, now=NOW)
    uins.ensure(con, "MSFT", ciks={"MSFT": 789019}, isins={"MSFT": "US5949181045"}, now=NOW, since=date(2026, 11, 1))
    con.execute("INSERT INTO us_lots_s81 VALUES (1, ?, 'MSFT', ?, 4.0, 100.0, 90.0, 'FBIL', 'fill')", [k, date(2026, 10, 1)])
    con.execute("INSERT INTO us_lots_s81 VALUES (2, 'US5949181045', 'MSFT', ?, 6.0, 110.0, 90.0, 'FBIL', 'fill')", [date(2026, 11, 3)])
    assert book.positions(con, date(2026, 10, 15)) == {k: 4.0}                      # before the alias begins, the pseudo key is the key
    assert book.positions(con, date(2026, 11, 5)) == {"US5949181045": 10.0}         # after it, both lots are one position
    assert book.positions(con, date(2026, 11, 3), before=True) == {"US5949181045": 4.0}


# ---------------------------------------------------------------- the whole close function

def _synthetic_us(root, days, spy0=100.0, qqq0=200.0):
    spy, qqq = [], []
    for k, d in enumerate(days):
        spy.append(_bar(d, spy0 + k - 0.4, spy0 + k))
        qqq.append(_bar(d, qqq0 + 2 * k - 0.8, qqq0 + 2 * k))
    _bars(root, "SPY", spy)
    _bars(root, "QQQ", qqq)


CFG = {"on": True, "universe": ["SPY", "QQQ"], "invested_share": 0.95, "slippage_bps": 5.0, "min_trade_usd": 10.0}


def test_close_us_is_off_by_default_and_touches_nothing(con):
    assert adapter.close_us(con, NOW) == {"off": True}
    assert con.execute("SELECT count(*) FROM us_account_s81").fetchone()[0] == 0 and con.execute("SELECT count(*) FROM us_runs_s81").fetchone()[0] == 0
    assert adapter.state_us(con, date(2026, 11, 9)) == {"open": False, "on": False}


def test_close_us_runs_two_sessions_end_to_end(con, tmp_path):
    root = tmp_path / "data"
    days = [date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)]
    _synthetic_us(root, days)
    for d in (date(2026, 10, 31), date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)):
        _fx(con, "USDINR_FBIL", d, 90.0)
    # session 1: Monday 2026-11-02 closes 02:30 IST on the 3rd (EST); the loop runs in the IST morning
    r1 = adapter.close_us(con, datetime(2026, 11, 3, 7, 0), root, CFG, book_value_inr=2_000_000.0)
    assert r1["day"] == "2026-11-02" and r1["fx"]["source"] == "FBIL" and r1["fx"]["rate"] == 90.0
    start_usd = 100_000.0 / (90.0 * 1.004)                                          # 5% of the system's book, at the stated rate, less the funding markup
    assert r1["opened"]["start_usd"] == pytest.approx(start_usd, abs=0.01) and r1["value_usd"] == pytest.approx(start_usd, abs=0.01)
    assert {o["symbol"] for o in r1["orders"]} == {"SPY", "QQQ"} and all(o["side"] == "buy" for o in r1["orders"])
    assert all("us_baseline_v1" in o["reason"] for o in r1["orders"]) and r1["fills"] == []
    assert sum(o["usd"] for o in r1["orders"]) == pytest.approx(0.70 * start_usd, abs=0.02)   # a fresh account deploys at once: 35% in each ETF (the ETF rail), the rest stays cash
    assert adapter.close_us(con, datetime(2026, 11, 3, 8, 0), root, CFG)["skipped"] == "US session 2026-11-02 already done"
    # session 2: the orders fill at Tuesday's open plus 5 bps; never better than the open
    r2 = adapter.close_us(con, datetime(2026, 11, 4, 7, 0), root, CFG)
    assert r2["day"] == "2026-11-03" and len(r2["fills"]) == 2
    opens = {"SPY": 101.0 - 0.4, "QQQ": 202.0 - 0.8}
    for f in r2["fills"]:
        assert f["price"] == pytest.approx(opens[f["symbol"]] * 1.0005, abs=1e-4) and f["charges_usd"] > 0
    assert book.cash(con) >= 0 and set(book.positions(con).values()) != {0}
    st = adapter.state_us(con, date(2026, 11, 3))
    assert st["open"] and st["marked"]["day"] == "2026-11-03" and {p["symbol"] for p in st["positions"]} == {"SPY", "QQQ"}
    assert st["fx"]["source"] == "FBIL" and st["account"]["fx_source"] == "FBIL" and "estimates" in st["label"]
    assert con.execute("SELECT count(*) FROM us_runs_s81").fetchone()[0] == 2
    # a session with no bars yet is waited for, not guessed
    assert "waiting" in adapter.close_us(con, datetime(2026, 11, 10, 7, 0), root, CFG)


def test_a_settled_book_keeps_the_churn_caps_and_a_fresh_account_does_not(con):
    from pflab.us import policy
    cfgs = us.settings({"on": True, "universe": ["SPY", "QQQ"], "min_trade_usd": 10.0})
    total = 10_000.0

    def state(spy_value, cash):
        rows = [{"isin": "US:SPY", "symbol": "SPY", "sector": None, "asset_class": "etf", "qty": spy_value / 100.0, "price": 100.0, "value": spy_value, "weight": spy_value / total, "buyable": True,
                 "klass": "us_equity"},
                {"isin": "US:QQQ", "symbol": "QQQ", "sector": None, "asset_class": "etf", "qty": 0.0, "price": 200.0, "value": 0.0, "weight": 0.0, "buyable": True, "klass": "us_equity"}]
        return {"day": date(2026, 11, 3), "market": "US", "value": total, "cash": cash, "bank": 0.0, "rows": rows, "breaker": {"on": False}, "gauge": {"fired": False}, "cfg": core.settings(),
                "settings": cfgs}

    settled = state(6000.0, 4000.0)                                      # 60% invested: SPY is over its 35% ETF rail, QQQ is wanted
    out = policy.check(con, settled, {"weights": {"US:SPY": 0.35, "US:QQQ": 0.35}})
    assert sum(o["value"] for o in out["orders"]) == pytest.approx(0.10 * total, rel=1e-6)      # the 10%-a-day turnover cap applies
    assert any("turnover cap" in o["note"] for o in out["orders"])
    assert out["orders"][0]["side"] == "sell" and "us_baseline_v1" in out["orders"][0]["reason"]   # sells first
    fresh = state(0.0, 10_000.0)                                         # nothing invested yet: the whole 35% + 35% goes in at once
    out = policy.check(con, fresh, {"weights": {"US:SPY": 0.35, "US:QQQ": 0.35}})
    assert sum(o["value"] for o in out["orders"]) == pytest.approx(0.70 * total, rel=1e-6) and all(o["side"] == "buy" for o in out["orders"])


def test_the_indian_paper_book_tables_are_not_touched_by_the_us_close(con, tmp_path):
    root = tmp_path / "data"
    _synthetic_us(root, [date(2026, 11, 2)])
    _fx(con, "USDINR_FBIL", date(2026, 11, 2), 90.0)
    _fx(con, "USDINR_FBIL", date(2026, 10, 31), 90.0)
    before = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("paper_trades", "paper_lots", "paper_cash", "paper_orders", "us_trades", "lots")}
    adapter.close_us(con, datetime(2026, 11, 3, 7, 0), root, CFG, book_value_inr=1_000_000.0)
    after = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in before}
    assert before == after


def test_every_us_row_has_a_source_a_date_and_a_level():
    for fid, r in rows.rows().items():
        assert r["verification"] in rows.LEVELS and r["verified_on"] and r["fy"], fid
        assert r["source_title"], fid
        if r["verification"] != "estimate":
            assert r["source_url"].startswith("https://"), fid
        else:
            assert r.get("verify"), f"{fid}: an estimate must say what would verify it"
    assert rows.fact("dtaa_dividend_withholding_individual")["verification"] == "primary"
    assert rows.fact("fx_ttbr_stand_in")["verification"] == "estimate"
