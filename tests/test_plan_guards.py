"""S35 guards: verdict precedence, results cache top-up, dip state, alert dedup. SYNTHETIC inputs."""
from datetime import date

import pandas as pd
import pytest

from pflab.fundamentals import pit
from pflab.plan import guards as gd
from pflab.pm import store

STOCKS = [{"symbol": s, "isin": f"INE00{s}01011"[:12], "scrip": c} for s, c in
          (("AAA", "1"), ("BBB", "2"), ("CCC", "3"), ("DDD", "4"), ("EEE", "5"))]


def fake_fetch(scrip, qids):
    rows = []
    for k, q in enumerate(qids):
        np_ = {"1": 10.0, "2": 10.0, "3": -5.0, "4": 10.0}.get(scrip)
        if np_ is None:
            continue                                       # EEE: nothing filed (data gap)
        rows.append({"scrip_code": scrip, "quarter_end": (pd.Timestamp("2024-09-30") + pd.offsets.QuarterEnd(k)).date(),
                     "audited": None, **{f: None for f in pit.FIELDS}, "net_profit": np_, "pbt": abs(np_) * 1.3,
                     "finance_costs": 1.0})
    return pd.DataFrame(rows, columns=pit.COLUMNS)


def test_verdict_precedence_and_cache(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    snap = pd.DataFrame([{"isin": STOCKS[1]["isin"], "verdict": "block", "desc": "GSM Stage II"},
                         {"isin": STOCKS[3]["isin"], "verdict": "caution", "desc": "LTASM Stage I"}])
    calls = []
    fetch = lambda s, q: (calls.append(s), fake_fetch(s, q))[1]
    g = {x.symbol: x for x in gd.check_all(con, date(2026, 10, 15), STOCKS, fetch, snap, lambda i, d: -0.1)}
    assert {k: v.verdict for k, v in g.items()} == {"AAA": "ok", "BBB": "block", "CCC": "fail", "DDD": "caution", "EEE": "unknown"}
    n = len(calls)
    gd.check_all(con, date(2026, 10, 15), STOCKS[:1], fetch, snap, lambda i, d: -0.1)
    assert len(calls) == n                                 # cached: the newest expected quarter is in the store


def test_market_dip_and_alert_dedup(tmp_path, monkeypatch):
    (tmp_path / "indices").mkdir()
    d = pd.bdate_range("2025-10-01", "2026-10-15")
    close = pd.Series(100.0, index=d); close[-20:] = 88.0
    pd.DataFrame({"date": d.date, "close": close.values}).to_parquet(tmp_path / "indices" / "NIFTY500_TRI.parquet")
    dip = gd.market_dip(date(2026, 10, 15), tmp_path)
    assert dip["active"] and dip["drawdown"] == pytest.approx(-0.12)
    con = store.connect(tmp_path / "l.duckdb")
    g = [gd.Guard("CCC", "INE00CCC0101", "fail", "clear", False, ["F1 loss-making"])]
    assert gd.queue_alerts(con, date(2026, 10, 15), g, dip, ["FD 1 matures soon"]) == 3
    assert gd.queue_alerts(con, date(2026, 10, 15), g, dip, ["FD 1 matures soon"]) == 0      # reported once


def _index(tmp_path, tail):
    (tmp_path / "indices").mkdir(exist_ok=True)
    d = pd.bdate_range("2026-01-01", "2026-10-15")
    close = pd.Series(100.0, index=d)
    close[-len(tail):] = tail
    pd.DataFrame({"date": d.date, "close": close.values}).to_parquet(tmp_path / "indices" / "NIFTY500_TRI.parquet")
    cfg = tmp_path / "hawkes.toml"
    cfg.write_text("[market]\nthreshold = -0.02\nmu = 0.01\nalpha = 0.7\nbeta = 0.05\npoisson_rate = 0.05\n"
                   "horizon = 10\nt1 = 0.40\nt2 = 0.60\n", encoding="utf-8")
    return d, cfg


def test_market_state_calm_elevated_high(tmp_path):
    d, cfg = _index(tmp_path, [97.0, 94.0, 94.0])            # two -3% sessions, then flat
    cl = gd.market_cluster(date(2026, 10, 15), tmp_path, cfg)
    # one fall alone stays calm (chance ~31%); the second makes it elevated (~46%) and that is the change
    assert cl["state"] == "elevated" and cl["previous"] == "calm" and cl["changed_on"] == d[-2].date()
    assert 0.40 <= cl["chance"] < 0.60 and cl["last_fall"] == d[-2].date()
    assert cl["normal"] == pytest.approx(1 - 2.718281828 ** -0.5, abs=1e-6)
    calm = gd.market_cluster(date(2026, 9, 30), tmp_path, cfg)
    assert calm["state"] == "calm" and calm["changed_on"] is None
    assert gd.market_cluster(date(2026, 10, 15), tmp_path, tmp_path / "missing.toml") is None
    _, cfg = _index(tmp_path, [97.0 * 0.97 ** k for k in range(5)])       # five falls in a row: crash-like
    assert gd.market_cluster(date(2026, 10, 15), tmp_path, cfg)["state"] == "high"


def test_volatility_chance_is_shown_beside_the_state(tmp_path):
    cfg = tmp_path / "ms.toml"
    cfg.write_text("[volatility]\nlam = 0.94\nwarm = 22\na = 11.58\nb = 1.376\n", encoding="utf-8")
    d = pd.bdate_range("2026-01-01", periods=120)
    calm = pd.Series(0.002 * (-1) ** pd.Series(range(120)).to_numpy(), index=d)
    stormy = calm.copy()
    stormy[-15:] = 0.03 * (-1) ** pd.Series(range(15)).to_numpy()
    lo, hi = gd.vol_chance(calm, cfg), gd.vol_chance(stormy, cfg)
    assert 0 < lo < hi < 1
    assert gd.vol_chance(calm, tmp_path / "missing.toml") is None
    cl = {"state": "calm", "date": d[-1].date(), "previous": None, "threshold": -0.02, "horizon": 10, "chance": 0.3,
          "normal": 0.4, "last_fall": None, "vol_chance": hi}
    assert f"from recent volatility {hi:.0%}" in gd.cluster_text(cl)
    dip = {"active": False, "date": d[-1].date(), "drawdown": -0.05}
    assert "from recent volatility" in gd.render([], dip, cl)


def test_market_state_messages_once_per_change_and_say_what_the_plan_does(tmp_path):
    d, cfg = _index(tmp_path, [97.0, 94.0, 94.0])
    cl = gd.market_cluster(date(2026, 10, 15), tmp_path, cfg)
    con = store.connect(tmp_path / "l.duckdb")
    dip = {"active": False, "date": date(2026, 10, 15), "drawdown": -0.06}
    assert gd.queue_alerts(con, date(2026, 10, 15), [], dip, [], cluster=cl) == 1
    assert gd.queue_alerts(con, date(2026, 10, 15), [], dip, [], cluster=cl) == 0        # same change: no repeat
    later = gd.market_cluster(date(2026, 10, 15), tmp_path, cfg, lookback=0)             # no change in the window
    assert later["changed_on"] is None and gd.queue_alerts(con, date(2026, 10, 15), [], dip, [], cluster=later) == 0
    txt = gd.cluster_text(cl, dip)
    assert "ELEVATED" in txt and "(was calm)" in txt and "dip rule off" in txt and gd.PLAN_NOTE in txt
    assert "ESTIMATE" in txt and "ELEVATED" in gd.render([], dip, cl)
    active = gd.cluster_text(cl, {**dip, "active": True, "drawdown": -0.12})
    assert "dip rule ACTIVE" in active and "extra quarter-tranche" in active
