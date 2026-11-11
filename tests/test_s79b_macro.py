"""S79b item 15: macro attribution (the waves, rotation, crude-fall and wave-lens parts were deleted in A60: their study failed). Synthetic data only."""
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import duckdb
import numpy as np
import pandas as pd
import pytest

from pflab import markets
from pflab.pm import store
from pflab.quant import macro_attr as MA, transmission as tr

TRUE = {"crude": -0.05, "currency": -0.8, "us10y": -0.01, "nasdaq": 0.15, "flows": 0.05, "asia": 0.30}
NOW = datetime(2026, 11, 8, 3, 0)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


def _put(root: Path, folder: str, key: str, dates, levels, col="close"):
    p = root / folder / f"{key}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": list(dates), col: np.asarray(levels, float)}).to_parquet(p, index=False)


def _levels_from_pct(moves, start=100.0):
    return start * np.cumprod(1 + np.asarray(moves) / 100.0)


def make_world(root: Path, start=date(2023, 1, 2), end=date(2024, 12, 31), seed=3, noise=0.02, drop=(), garbage_after=None, n_days=None):
    """An index whose move is exactly TRUE betas x the factors (+ small noise). Overnight factors live on US sessions; the rest on India's."""
    rng = np.random.default_rng(seed)
    ind, us = markets.get("IN"), markets.get("US")
    in_days = ind.sessions_between(start, end)
    if n_days:
        in_days = in_days[:n_days]
    us_days = us.sessions_between(date(2022, 12, 1), end)
    f = {}
    f["crude"] = dict(zip(us_days, rng.normal(0, 1.6, len(us_days))))                  # percent
    f["us10y"] = dict(zip(us_days, rng.normal(0, 6.0, len(us_days))))                  # basis points
    f["nasdaq"] = dict(zip(us_days, rng.normal(0, 1.2, len(us_days))))
    f["currency"] = dict(zip(in_days, rng.normal(0, 0.25, len(in_days))))
    f["flows"] = dict(zip(in_days, rng.normal(0, 3.0, len(in_days))))                  # Rs 1,000 crore
    peers = {k: rng.normal(0, 0.5, len(in_days)) for k in MA.ASIA_KEYS}
    common = rng.normal(0, 1.0, len(in_days))
    asia = pd.DataFrame({k: common + v for k, v in peers.items()}, index=in_days).mean(axis=1)
    y = []
    for i, m in enumerate(in_days):
        u = tr.source_session("IN", m)
        y.append(TRUE["crude"] * f["crude"].get(u, 0.0) + TRUE["us10y"] * f["us10y"].get(u, 0.0) + TRUE["nasdaq"] * f["nasdaq"].get(u, 0.0)
                 + TRUE["currency"] * f["currency"][m] + TRUE["flows"] * f["flows"][m] + TRUE["asia"] * float(asia.iloc[i]) + rng.normal(0, noise))
    # files (a move series has a first row with no move: prepend a day)
    d0, d0u = ind.previous_session(in_days[0]), us.previous_session(us_days[0])

    def lv(days, mv, first):
        return [first] + list(_levels_from_pct(mv))

    _put(root, "indices", "NIFTY500_TRI", [d0] + in_days, [100.0] + list(_levels_from_pct(y)))
    if "crude" not in drop:
        _put(root, "global", "BRENT_FUT", [d0u] + us_days, [100.0] + list(_levels_from_pct([f["crude"][d] for d in us_days])))
    if "us10y" not in drop:
        _put(root, "global", "US_10Y_YIELD", [d0u] + us_days, [4.0] + list(4.0 + np.cumsum([f["us10y"][d] / 100.0 for d in us_days])))
    if "nasdaq" not in drop:
        _put(root, "global", "US_NASDAQ", [d0u] + us_days, [100.0] + list(_levels_from_pct([f["nasdaq"][d] for d in us_days])))
    if "currency" not in drop:
        _put(root, "global", "FX_USDINR", [d0] + in_days, [80.0] + list(_levels_from_pct([f["currency"][d] for d in in_days], 80.0)))
    if "asia" not in drop:
        for k in MA.ASIA_KEYS:
            lvl = _levels_from_pct((common + peers[k]))
            _put(root, "global", k, [d0] + in_days, [100.0] + list(lvl))
        # the average of the four peers' moves is `asia`: the peers' levels are built from common+peer so their moves are exactly those percentages, compounded
    if "flows" not in drop:
        rows = [{"report_date": ind.next_session(d), "asset": "Equity", "route": "Sub-total", "net_cr": f["flows"][d] * 1000.0} for d in in_days]
        p = root / "macro" / "FPI_DAILY.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(p, index=False)
    return in_days, f


# --- macro attribution --------------------------------------------------------------------------------------------------------------------

def test_known_betas_recovered_and_parts_add_up(tmp_path):
    in_days, f = make_world(tmp_path)
    d = MA.Design(tmp_path, "IN")
    s = in_days[-30]
    a = d.attribute(s)
    for k, b in TRUE.items():
        assert a["parts"][k]["beta"] == pytest.approx(b, rel=0.08, abs=0.003), k
    assert a["checks_out"]
    parts = sum(p["pct"] for p in a["parts"].values())
    assert parts + a["unexplained_pct"] == pytest.approx(a["total_pct"], abs=1e-5)
    assert abs(a["unexplained_pct"]) < 0.25                        # the noise is 0.02 and the betas are right: nearly all of the move is explained
    u = tr.source_session("IN", s)
    assert a["parts"]["crude"]["pct"] == pytest.approx(a["parts"]["crude"]["beta"] * f["crude"][u], abs=1e-4)
    assert a["parts"]["flows"]["factor_move"] == pytest.approx(f["flows"][s], abs=1e-3)


def test_attribution_is_point_in_time(tmp_path):
    root_a, root_b = tmp_path / "a", tmp_path / "b"
    in_days, _ = make_world(root_a)
    make_world(root_b)
    s = in_days[300]
    base = MA.Design(root_a, "IN").attribute(s)
    # rewrite every row dated after the session in root_b: the attribution of the session must not move
    for sub, key in [("indices", "NIFTY500_TRI"), ("global", "BRENT_FUT"), ("global", "US_NASDAQ"), ("global", "US_10Y_YIELD"), ("global", "FX_USDINR"), ("global", "KR_KOSPI")]:
        p = root_b / sub / f"{key}.parquet"
        df = pd.read_parquet(p)
        later = pd.to_datetime(df["date"]).dt.date > in_days[301]
        df.loc[later, "close"] = df.loc[later, "close"] * np.linspace(1.0, 3.0, int(later.sum()))
        df.to_parquet(p, index=False)
    p = root_b / "macro" / "FPI_DAILY.parquet"
    fl = pd.read_parquet(p)
    fl.loc[pd.to_datetime(fl["report_date"]).dt.date > in_days[302], "net_cr"] = 99999.0
    fl.to_parquet(p, index=False)
    again = MA.Design(root_b, "IN").attribute(s)
    for k in TRUE:
        assert again["parts"][k]["pct"] == pytest.approx(base["parts"][k]["pct"], abs=1e-9), k
        assert again["parts"][k]["beta"] == pytest.approx(base["parts"][k]["beta"], abs=1e-9), k
    assert again["total_pct"] == base["total_pct"] and again["unexplained_pct"] == pytest.approx(base["unexplained_pct"], abs=1e-9)
    # and the cut-off world (rows after the session simply absent) gives the same answer too
    assert MA.Design(root_b, "IN").attribute(in_days[100])["parts"]["asia"]["pct"] == pytest.approx(MA.Design(root_a, "IN").attribute(in_days[100])["parts"]["asia"]["pct"], abs=1e-9)


def test_small_sample_gives_count_not_conclusion(tmp_path):
    in_days, _ = make_world(tmp_path, n_days=40)
    d = MA.Design(tmp_path, "IN")
    a = d.attribute(in_days[15])                                      # 14 sessions before it: under MIN_N
    assert all(p["pct"] is None for p in a["parts"].values())
    assert all(("under 20" in p["note"]) for p in a["parts"].values() if p["factor_move"] is not None)
    assert a["unexplained_pct"] == a["total_pct"]                      # nothing is explained, nothing invented
    b = d.attribute(in_days[35])
    assert b["parts"]["asia"]["pct"] is not None and b["parts"]["asia"]["n"] >= 20


def test_missing_series_is_unavailable_not_invented(tmp_path):
    in_days, _ = make_world(tmp_path, drop=("nasdaq", "flows", "crude"))
    a = MA.Design(tmp_path, "IN").attribute(in_days[-10])
    for k in ("nasdaq", "flows", "crude"):
        assert a["parts"][k]["pct"] is None and "unavailable" in a["parts"][k]["note"]
    assert a["parts"]["asia"]["pct"] is not None
    assert a["checks_out"]
    # no data at all for the market: the design is empty, not an error
    empty = MA.Design(tmp_path / "nothing", "IN")
    assert empty.dates == [] and "note" in empty.attribute(date(2024, 1, 2))


def test_flows_part_appears_only_when_the_report_is_in(tmp_path, con):
    in_days, _ = make_world(tmp_path)
    ind = markets.get("IN")
    p = tmp_path / "macro" / "FPI_DAILY.parquet"
    fl = pd.read_parquet(p)
    last = in_days[-1]
    full = fl.copy()
    fl = fl[pd.to_datetime(fl["report_date"]).dt.date <= last]            # the report of the last session (dated the next business day) is not in
    fl.to_parquet(p, index=False)
    r1 = MA.catch_up(con, tmp_path, "IN", last, now=NOW, backfill=5)
    assert r1["sessions_written"] == 5
    row = con.execute("SELECT pct, note FROM macro_attribution WHERE market='IN' AND session=? AND part='flows'", [last]).fetchone()
    assert row[0] is None and "unavailable" in row[1]
    full.to_parquet(p, index=False)                                       # the report arrives
    r2 = MA.catch_up(con, tmp_path, "IN", last, now=NOW, backfill=5)
    assert r2["sessions_written"] == 1
    row = con.execute("SELECT pct, as_of FROM macro_attribution WHERE market='IN' AND session=? AND part='flows'", [last]).fetchone()
    assert row[0] is not None and row[1] == ind.next_session(last)
    n = con.execute("SELECT count(*) FROM macro_attribution WHERE market='IN' AND session=?", [last]).fetchone()[0]
    assert n == 2 + len(MA.FACTORS["IN"])                                  # total + unexplained + one per factor
    again = MA.read(con, "IN", last)
    assert sum(p["pct"] for p in again["parts"].values() if p["pct"] is not None) + again["unexplained_pct"] == pytest.approx(again["total_pct"], abs=1e-5)
    # nothing left to do on a third run
    assert MA.catch_up(con, tmp_path, "IN", last, now=NOW, backfill=5)["sessions_written"] == 0


# --- tools, jobs -------------------------------------------------------------------------------------------------------------

def _ctx(root, con, call_ref=7):
    return SimpleNamespace(rt=SimpleNamespace(data_root=root), con=con, asof=date(2024, 12, 31), call_ref=call_ref)


def test_tools_work_with_empty_args_and_on_missing_data(tmp_path, con):
    import pflab.hq.tools  # noqa: F401  (loads the tool table first, as the app does)
    from pflab.hq import tools_s79
    import pflab.hq.tools  # noqa: F401
    from pflab.hq.tools_s79 import t_macro as TW
    assert "macro_attribution" in tools_s79.names() and "wave_detector" not in tools_s79.names()
    make_world(tmp_path)
    TW._DESIGNS.clear()
    out = TW.macro_attribution(_ctx(tmp_path, con), {})
    assert out["call_ref"] == 7 and out["total_pct"] is not None and out["session"] == "2024-12-31"
    assert out["dominant"] and len(out["recent"]) == 5 and set(out["parts"]) == set(MA.FACTORS["IN"])
    assert sum(p["pct"] for p in out["parts"].values() if p["pct"] is not None) + out["unexplained_pct"] == pytest.approx(out["total_pct"], abs=1e-5)
    us = TW.macro_attribution(_ctx(tmp_path, con), {"market": "US"})
    assert "note" in us and "error" not in us                                  # no S&P 500 history here: a harmless note
    nothing = TW.macro_attribution(_ctx(tmp_path / "void", con), {})
    assert "error" not in nothing and "note" in nothing
    TW._DESIGNS.clear()


def test_switch_off_returns_off(tmp_path, con, monkeypatch):
    import pflab.hq.tools  # noqa: F401
    from pflab.hq.tools_s79 import t_macro as TW
    monkeypatch.setattr(MA, "settings", lambda: {"on": False})
    assert TW.macro_attribution(_ctx(tmp_path, con), {})["off"] is True


def test_jobs_registered_and_catch_up_all_missed_sessions(tmp_path, con):
    import pflab.service.tasks_s79_macro  # noqa: F401
    from pflab.service import jobs
    assert "macro_attribution" in jobs.REGISTRY and "wave_scan" not in jobs.REGISTRY
    in_days, _ = make_world(tmp_path)
    MA.write(con, MA.Design(tmp_path, "IN").attribute(in_days[-40]), NOW)
    r = MA.catch_up(con, tmp_path, "IN", in_days[-1], now=NOW, backfill=10)
    have = {x[0] for x in con.execute("SELECT DISTINCT session FROM macro_attribution WHERE market='IN'").fetchall()}
    assert set(in_days[-39:]) <= have                                          # every session missed since the last write
    assert r["latest"] == str(in_days[-1])


def test_nse_provisional_flow_fills_the_session_nsdl_has_not_reported(tmp_path, con):
    in_days, f = make_world(tmp_path)
    ind = markets.get("IN")
    last = in_days[-1]
    p = tmp_path / "macro" / "FPI_DAILY.parquet"
    fl = pd.read_parquet(p)
    fl[pd.to_datetime(fl["report_date"]).dt.date <= last].to_parquet(p, index=False)         # NSDL has not reported `last` yet
    (tmp_path / "flows").mkdir()
    pd.DataFrame({"date": [last], "fii_net_cr": [f["flows"][last] * 1000.0]}).to_parquet(tmp_path / "flows" / "FII_DII_CASH.parquet", index=False)
    assert MA.flows_by_session(tmp_path)[last] == pytest.approx(f["flows"][last], abs=1e-6)
    assert MA.flow_known_dates(tmp_path)[last] == last                                        # NSE's figure is out the same evening
    assert MA.flow_known_dates(tmp_path)[in_days[-2]] == last                                 # NSDL's the next business day
    a = MA.Design(tmp_path, "IN").attribute(last)
    assert a["parts"]["flows"]["pct"] is not None and a["parts"]["flows"]["known_on"] == str(last)
    MA.write(con, a, NOW)
    assert con.execute("SELECT as_of FROM macro_attribution WHERE market='IN' AND session=? AND part='flows'", [last]).fetchone()[0] == last
