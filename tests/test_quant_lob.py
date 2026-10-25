"""S41 order book: matching engine rules on hand-built books; the flow simulator's invariants. SYNTHETIC."""
import numpy as np
import pytest

from pflab.quant import lob
from pflab.quant.lob import BUY, SELL


def test_price_time_priority_and_partial_fills():
    b = lob.Book()
    first = b.limit(SELL, 101, 50, "a")
    second = b.limit(SELL, 101, 50, "b")
    b.limit(SELL, 102, 100, "c")
    assert b.best(SELL) == 101 and b.depth(SELL) == [(101, 100), (102, 100)]
    got = b.market(BUY, 70, "me")
    assert got == 70
    assert [(f.maker, f.qty, f.price) for f in b.fills] == [(first, 50, 101), (second, 20, 101)]
    assert b.orders[second].qty == 30 and first not in b.orders


def test_a_crossing_limit_fills_then_rests_the_rest():
    b = lob.Book()
    b.limit(SELL, 101, 40)
    b.limit(SELL, 103, 40)
    oid = b.limit(BUY, 102, 100, "me")                # takes 40 at 101, rests 60 at 102 (not 103)
    assert [(f.price, f.qty) for f in b.fills] == [(101, 40)]
    assert b.orders[oid].qty == 60 and b.best(BUY) == 102 and b.best(SELL) == 103 and b.spread() == 1


def test_market_order_beyond_the_book_and_cancel():
    b = lob.Book()
    b.limit(BUY, 99, 30)
    oid = b.limit(BUY, 98, 30)
    assert b.cancel(oid) == 30 and b.cancel(oid) == 0 and b.depth(BUY) == [(99, 30)]
    assert b.market(SELL, 100) == 30                  # immediate-or-cancel: the rest is dropped
    assert b.best(BUY) is None and b.mid() is None and not b.orders
    with pytest.raises(ValueError):
        b.limit(BUY, 100, 0)


def test_walk_the_ladder():
    ladder = [(100.0, 10), (100.5, 10), (101.0, 100)]
    assert lob.walk(ladder, 15) == (pytest.approx((10 * 100 + 5 * 100.5) / 15), 15)
    avg, got = lob.walk(ladder, 500)
    assert got == 120                                  # the ladder ran out


@pytest.fixture(scope="module")
def run():
    probes = [(t, side, k) for t in range(100, 1700, 50) for side in (BUY, SELL) for k in (0, 3)]
    return lob.simulate(lob.Flow(), 1800.0, np.random.default_rng(7), probes)


def test_simulation_keeps_a_valid_book_and_conserves_quantity(run):
    s = run.snapshots.dropna()
    assert (s["spread"] >= 1).all() and (s["ask"] > s["bid"]).all()          # never crossed
    assert len(run.markets) > 50 and (run.markets["filled"] <= run.markets["qty"]).all()
    taken = run.markets["filled"].sum()
    assert sum(f.qty for f in run.fills) == taken                            # every fill is a market order's


def test_same_seed_same_run():
    a = lob.simulate(lob.Flow(), 300.0, np.random.default_rng(1))
    b = lob.simulate(lob.Flow(), 300.0, np.random.default_rng(1))
    assert a.snapshots.equals(b.snapshots) and len(a.fills) == len(b.fills)


def test_measures_show_the_textbook_shapes(run):
    m = lob.measures(run)
    assert m["spread_mean"] >= 1 and m["depth5_mean"] > 0
    imp = m["impact_10s"]
    assert imp["300-1000000000"] > imp["0-100"]                              # bigger orders move the mid more
    fc = m["fill_chance"]
    assert fc[0] > fc[3]                                                     # at the best fills more often


def test_market_orders_cluster_like_their_hawkes_process(run):
    t = run.markets["t"].to_numpy()
    counts = np.histogram(t, bins=np.arange(0, 1801, 30))[0]
    assert counts.var() > 1.5 * counts.mean()                               # overdispersed, unlike Poisson
