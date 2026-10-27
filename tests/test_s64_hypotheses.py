"""S64 Phase 5 item 3: cause hypotheses in the graph, tested by code where the cause is a macro series."""
from datetime import date, datetime, timedelta

import duckdb
import numpy as np
import pandas as pd
import pytest

from pflab.kg import hypotheses as hy
from pflab.pm import store

NOW = datetime(2026, 10, 27, 20, 0)
ISIN = "INE000A01011"


@pytest.fixture
def con(tmp_path):
    c = duckdb.connect(str(tmp_path / "pm.duckdb"))
    store.migrate(c)
    c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, symbol, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', 'AAA', 't', now())", [ISIN])
    return c


def rec(con, series="BRENT", days=10, symbol="AAA", cause="oil prices rising on the war"):
    return hy.record(con, 1, symbol, cause, "the stock fell", ["market_context"], NOW.date() + timedelta(days=days), series, NOW)


def test_record_keeps_the_row_and_the_graph_edge(con):
    hid = rec(con)
    assert con.execute("SELECT status, subject FROM kg_hypotheses WHERE hyp_id=?", [hid]).fetchone() == ("open", "AAA")
    e = con.execute("SELECT src, rel, dst FROM kg_edges WHERE source_ref=?", [f"hyp:{hid}"]).fetchone()
    assert e[1] == "seems_caused_by" and e[2].startswith("cause:oil prices")


def test_check_by_is_within_ninety_days_and_series_is_known(con):
    with pytest.raises(ValueError):
        rec(con, days=91)
    with pytest.raises(ValueError):
        rec(con, days=0)
    with pytest.raises(ValueError):
        rec(con, series="GOLD")


def series_pair(beta, n=400, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-01", periods=n)
    f = pd.Series(rng.normal(0, 0.01, n), index=idx - pd.Timedelta(days=1))        # known the evening before
    r = beta * f.to_numpy() + rng.normal(0, 0.01, n)
    close = pd.Series(100 * np.exp(np.cumsum(r)), index=idx)
    return close, f


def test_beta_test_finds_a_real_relation_and_not_a_missing_one():
    close, f = series_pair(1.5)
    t = hy.beta_test(close, f, date(2026, 6, 30))
    assert t["t"] > 4 and t["beta"] == pytest.approx(1.5, abs=0.5)
    close2, f2 = series_pair(0.0, seed=5)
    assert abs(hy.beta_test(close2, f2, date(2026, 6, 30))["t"]) < 3


def test_a_due_macro_hypothesis_is_confirmed_or_refuted_by_code(con, monkeypatch):
    close, f = series_pair(1.5)
    monkeypatch.setattr(hy, "macro_returns", lambda root, series: f)
    hid = rec(con, days=10)
    later = NOW + timedelta(days=11)
    out = hy.check_due(con, None, later, closes_fn=lambda isin, d: close)
    assert out["confirmed"] == 1
    st, why = con.execute("SELECT status, why FROM kg_hypotheses WHERE hyp_id=?", [hid]).fetchone()
    assert st == "confirmed" and "not proof of one day's cause" in why
    assert con.execute("SELECT valid_to FROM kg_edges WHERE source_ref=?", [f"hyp:{hid}"]).fetchone()[0] is None   # kept
    # a refuted one leaves the graph
    close2, f2 = series_pair(0.0, seed=5)
    monkeypatch.setattr(hy, "macro_returns", lambda root, series: f2)
    h2 = rec(con, cause="rupee weakness", series="USDINR")
    out = hy.check_due(con, None, NOW + timedelta(days=11), closes_fn=lambda isin, d: close2)
    assert out["refuted"] == 1
    assert con.execute("SELECT valid_to FROM kg_edges WHERE source_ref=?", [f"hyp:{h2}"]).fetchone()[0] is not None


def test_a_non_macro_hypothesis_goes_to_the_brain_then_expires(con):
    hid = rec(con, series=None, cause="a new competitor drug")
    out = hy.check_due(con, None, NOW + timedelta(days=11))
    assert out["review"] == 1 and [h["hyp_id"] for h in hy.due_for_the_brain(con)] == [hid]
    hy.decide(con, hid, "refuted", "the competitor's filing says otherwise", NOW + timedelta(days=12))
    assert con.execute("SELECT status FROM kg_hypotheses").fetchone()[0] == "refuted"
    h2 = rec(con, series=None, cause="x")
    out = hy.check_due(con, None, NOW + timedelta(days=10 + 31))
    assert out["expired"] == 1
    with pytest.raises(ValueError):
        hy.decide(con, h2, "confirmed", "late", NOW)                                  # already closed
