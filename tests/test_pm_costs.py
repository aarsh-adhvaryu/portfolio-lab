"""S4: estimated Zerodha charges by segment (rates verified against zerodha.com/charges on 2026-10-06)."""
from datetime import date, timedelta

import pandas as pd
import pytest

from pflab.pm import costs


def test_equity_delivery_buy_hand_check():
    amt, known = costs.estimate("equity_delivery", "buy", 100_000.0)
    txn, sebi = 100_000 * 0.0000307, 100_000 / 1e7 * 10
    expect = txn + sebi + (txn + sebi) * 0.18 + 100_000 * 0.001 + 100_000 * 0.00015
    assert known and amt == pytest.approx(expect) and amt == pytest.approx(118.74, abs=0.01)


def test_equity_delivery_sell_hand_check_with_dp_charge_per_scrip():
    amt, known = costs.estimate("equity_delivery", "sell", 100_000.0, n_scrips=2)
    txn, sebi = 100_000 * 0.0000307, 100_000 / 1e7 * 10
    assert known and amt == pytest.approx(txn + sebi + (txn + sebi) * 0.18 + 100 + 2 * 15.34)


def test_equity_futures_hand_check_brokerage_capped():
    sell, known = costs.estimate("equity_futures", "sell", 500_000.0)    # 0.03% = 150 > Rs 20 cap
    base = 20 + 500_000 * 0.0000183 + 0.5
    assert known and sell == pytest.approx(base * 1.18 + 250) and sell == pytest.approx(284.99, abs=0.01)
    buy, _ = costs.estimate("equity_futures", "buy", 500_000.0)
    assert buy == pytest.approx(base * 1.18 + 10)
    small, _ = costs.estimate("equity_futures", "buy", 10_000.0)           # 0.03% = 3 < cap
    assert small == pytest.approx((3 + 10_000 * 0.0000183 + 0.01) * 1.18 + 0.2)


def test_direct_mf_is_free_and_known():
    assert costs.estimate("mf_direct", "buy", 50_000.0) == (0.0, True)
    assert costs.estimate("mf_direct", "sell", 50_000.0) == (0.0, True)


def test_etf_and_sgb_are_estimates_flagged_unverified():
    for seg in ("etf", "sgb"):
        amt, known = costs.estimate(seg, "buy", 10_000.0)
        assert not known and amt > 0


def test_segments_and_errors():
    assert costs.segment_of("mutual_fund", "EQUITY") == "mf_direct" and costs.segment_of("etf", "") == "etf"
    assert costs.segment_of("equity", "EQUITY") == "equity_delivery" and costs.segment_of("sgb", "SGB") == "sgb"
    with pytest.raises(ValueError):
        costs.estimate("nope", "buy", 1.0)
    with pytest.raises(ValueError):
        costs.estimate("equity_delivery", "hold", 1.0)


def test_fee_fn_reads_segments_from_the_instrument_master():
    inst = pd.DataFrame([dict(isin="INF1", asset_class="mutual_fund", tax_class="EQUITY"),
                         dict(isin="INF2", asset_class="etf", tax_class="LISTED_NONEQUITY"),
                         dict(isin="INE1", asset_class="equity", tax_class="EQUITY")])
    fn = costs.fee_fn(inst)
    assert fn("INF1", "equity_fund", "buy", 10_000.0) == (0.0, True)
    assert fn("INF2", "gold", "sell", 10_000.0)[1] is False
    assert fn("INE1", "equity", "buy", 10_000.0)[1] is True and fn("UNKNOWN", "x", "buy", 10_000.0)[1] is True


def test_config_is_sourced_and_not_stale():
    c = costs.load()
    assert c["source"]["url"] == "https://zerodha.com/charges"
    assert (date.today() - c["source"]["verified_on"]) < timedelta(days=396)      # April re-verification reminder
    for seg in ("equity_delivery", "mf_direct", "etf", "sgb"):
        assert c[seg]["verification"] in ("primary", "unverified")
    assert c["etf"]["verification"] == "unverified" and c["sgb"]["verification"] == "unverified"
