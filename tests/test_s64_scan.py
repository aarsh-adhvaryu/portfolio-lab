"""S64 Phase 5 item 9: scanners from a closed set of conditions; information, labelled not tested."""
from datetime import date, datetime

import duckdb
import numpy as np
import pandas as pd
import pytest

from pflab.pm import store
from pflab.quant import scan

NOW = datetime(2026, 10, 27, 20, 40)
ASOF = NOW.date()


@pytest.fixture
def con(tmp_path):
    c = duckdb.connect(str(tmp_path / "pm.duckdb"))
    store.migrate(c)
    return c


def test_parse_accepts_only_the_closed_set():
    assert scan.parse("price_below_sma:200; volume_spike:2") == [{"name": "price_below_sma", "value": "200"},
                                                                  {"name": "volume_spike", "value": "2.0"}]
    assert scan.parse("alpha_negative")[0]["value"] is None
    for bad in ("magic:3", "price_below_sma:30", "rsi_below:abc", "buildup:sideways", "", "volume_spike:5000",
                ";".join(["alpha_negative"] * 7)):
        with pytest.raises(ValueError):
            scan.parse(bad)
    assert scan.text_of(scan.parse("near_52w_low:5; buildup:short covering")) == "near_52w_low:5.0; buildup:short covering"


def series(kind):
    idx = pd.bdate_range(end=pd.Timestamp(ASOF), periods=600)
    if kind == "falling":
        v = np.linspace(200, 100, 600)
    elif kind == "rising":
        v = np.linspace(100, 200, 600)
    else:                                                                    # a V: fell, then crossed back up through the 50-day
        v = np.concatenate([np.linspace(200, 100, 596), np.linspace(104, 116, 4)])
    return pd.Series(v, index=idx)


def test_indicators_and_conditions():
    f = scan.indicators(series("falling"), volume_ratio=2.6)
    assert f["close"] == pytest.approx(100.0) and f["above_low52_pct"] == pytest.approx(0.0, abs=0.5)
    assert f["from_ath_pct"] == pytest.approx(-50.0)
    h = lambda text, ind, facts=None: scan.holds(scan.parse(text)[0], ind, facts or {})            # noqa: E731
    assert h("price_below_sma:200", f)[0] is True and h("price_above_sma:50", f)[0] is False
    assert h("near_52w_low:5", f)[0] is True and h("near_52w_high:5", f)[0] is False
    assert h("ath_fall_at_least:40", f)[0] is True and h("volume_spike:2", f)[0] is True
    assert h("rsi_below:30", f)[0] is True
    up = scan.indicators(series("v"))
    assert h("cross_up_sma:20", up)[0] is True and h("cross_down_sma:20", up)[0] is False
    assert scan.holds(scan.parse("volume_spike:2")[0], scan.indicators(series("rising")), {})[0] is None      # no volume known
    assert scan.holds(scan.parse("alpha_negative")[0], f, {"alpha_ann": -0.05, "alpha_t": -2.1})[0] is True
    assert scan.holds(scan.parse("pe_above_median:1.5")[0], f, {"pe_ttm": 40, "pe_own_5y": {"median": 20}})[0] is True
    assert scan.holds(scan.parse("buildup:short covering")[0], f, {"buildup": {"class": "long build-up"}})[0] is False


def test_evaluate_needs_all_conditions_and_skips_the_unknown(con, monkeypatch):
    from pflab.app import research
    paths = {"AAA": series("falling"), "BBB": series("rising"), "CCC": series("falling").iloc[:10]}
    monkeypatch.setattr(research, "closes", lambda con_, root, isin, asof, years=2: paths[isin])
    isins = {"AAA": "AAA", "BBB": "BBB", "CCC": "CCC"}
    r = scan.evaluate(con, None, scan.parse("price_below_sma:200; near_52w_low:5"), "list", ASOF, isins)
    assert [h["symbol"] for h in r["hits"]] == ["AAA"] and r["checked"] == 3 and r["unknown"] == 1       # CCC: too little history
    assert "close" in r["hits"][0]["why"][0]
    n5 = scan.evaluate(con, None, scan.parse("alpha_negative; price_below_sma:200"), "nifty500", ASOF, isins)
    assert n5["skipped_conditions"] == ["alpha_negative"] and [h["symbol"] for h in n5["hits"]] == ["AAA"]   # needs facts: dropped


def test_starters_are_seeded_once_and_labelled_not_tested(con):
    assert scan.seed_starters(con, NOW) == 4 and scan.seed_starters(con, NOW) == 0
    rows = scan.listing(con)
    assert len(rows) == 4 and all(r["tested"] == "not tested" and "information, not evidence" in r["label"] for r in rows)
    with pytest.raises(ValueError, match="exists"):
        scan.make_scan(con, rows[0]["name"], "alpha_negative", "list", "x", NOW)
    with pytest.raises(ValueError, match="universe"):
        scan.make_scan(con, "z", "alpha_negative", "moon", "x", NOW)


def test_the_label_follows_the_learners_decision(con):
    sid = scan.make_scan(con, "s", "alpha_negative", "list", "x", NOW)
    con.execute("INSERT INTO learn_claims (claim_id, src_id, made_at, claim, template, status, decision) VALUES (7, 1, ?, 'c', 'scan_rule', 'tested', 'pass')", [NOW])
    con.execute("UPDATE scans SET claim_id=7 WHERE scan_id=?", [sid])
    assert scan.tested(con, sid) == "passed" and scan.listing(con)[0]["label"] == "tested: passed"


def test_hits_on_his_names_become_held_lines_never_telegram_at_once(con, monkeypatch):
    from pflab.app import research
    monkeypatch.setattr(research, "closes", lambda con_, root, isin, asof, years=2: series("falling"))
    monkeypatch.setattr(scan, "universe_isins", lambda con_, root, universe, asof: {"INE000A01011": "AAA"})
    scan.make_scan(con, "low", "near_52w_low:5", "list", "x", NOW)
    out = scan.run_all(con, None, ASOF, NOW)
    assert out["low"] == 1 and out["_summary_lines"] == 1
    assert con.execute("SELECT kind, status FROM outbox").fetchall() == [("scan", "held")]
    scan.run_all(con, None, ASOF, NOW)                                                       # same day: no second line
    assert con.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1
