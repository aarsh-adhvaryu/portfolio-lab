"""S79b item 18A: `construct` (portfolio construction). Synthetic data only: the shrunk covariance against a known case and a direct loop of the formula, the optimiser
holding every rail, costs and tax lowering turnover, the pull toward the allocation target, determinism, the fallback when the optimiser fails, the protocol hash check, the
tool on a synthetic paper book, and the comparison engine on a synthetic panel."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import duckdb
import numpy as np
import pandas as pd
import pytest

from pflab import construct as C
from pflab.construct import compare, costs, optimiser as O, risk, run as R
from pflab.pm import store

NOW = datetime(2026, 11, 6, 21, 0)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


# --- the risk model ---------------------------------------------------------------------------------------------------------------
def _lw_loop(X):
    """Ledoit-Wolf 2004 written the long way (one outer product per day) to check the vectorised formula."""
    n, p = X.shape
    X = X - X.mean(0)
    S = sum(np.outer(x, x) for x in X) / n
    mu = np.trace(S) / p
    d2 = np.sum((S - mu * np.eye(p)) ** 2) / p
    b2 = sum(np.sum((np.outer(x, x) - S) ** 2) for x in X) / (n * n * p)
    b = min(b2, d2)
    s = b / d2
    return s * mu * np.eye(p) + (1 - s) * S, s


def test_ledoit_wolf_matches_the_formula_written_out():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(60, 12)) @ rng.normal(size=(12, 12)) * 0.01
    S, s = risk.ledoit_wolf(X)
    S2, s2 = _lw_loop(X)
    assert s == pytest.approx(s2) and np.allclose(S, S2)
    assert 0.0 <= s <= 1.0


def test_shrinkage_beats_the_sample_covariance_on_a_known_case():
    """True covariance = 0.0001 * I (40 names), only 50 days: the sample covariance is far off; the shrunk one is much nearer and its eigenvalues are tighter."""
    rng = np.random.default_rng(11)
    truth = np.eye(40) * 1e-4
    errs_s, errs_l, shr = [], [], []
    for _ in range(20):
        X = rng.normal(size=(50, 40)) * 0.01
        S = np.cov(X.T, bias=True)
        L, s = risk.ledoit_wolf(X)
        errs_s.append(np.sum((S - truth) ** 2))
        errs_l.append(np.sum((L - truth) ** 2))
        shr.append(s)
    assert np.mean(errs_l) < 0.5 * np.mean(errs_s)
    assert np.mean(shr) > 0.3                                    # a spherical truth with few days: mostly the target
    X = rng.normal(size=(20000, 5)) * np.array([0.002, 0.005, 0.01, 0.02, 0.04])      # a far-from-spherical truth with plenty of days: the sample is trusted
    assert risk.ledoit_wolf(X)[1] < 0.02


def test_shrunk_cov_is_point_in_time_and_drops_thin_names():
    idx = pd.bdate_range("2025-01-01", periods=400)
    rng = np.random.default_rng(1)
    px = pd.DataFrame({"A": 100 * np.exp(np.cumsum(rng.normal(0, .01, 400))), "B": 50 * np.exp(np.cumsum(rng.normal(0, .01, 400)))}, index=idx)
    px.loc[idx[:380], "B"] = np.nan                              # B has only 20 days
    r_cut = risk.daily_returns(px, idx[300].date(), 250)
    assert r_cut.index.max() <= idx[300] and list(r_cut.columns) == ["A"]
    m, src, _ = risk.cov_for(["A", "B"], r_cut, None, 0.5, 0.30)
    assert m.shape == (2, 2) and "no return history" in src["B"] and np.sqrt(m[1, 1]) == pytest.approx(0.30) and np.linalg.eigvalsh(m)[0] > 0


# --- the optimiser ----------------------------------------------------------------------------------------------------------------
def prob(n=4, **kw):
    names = [f"S{i}" for i in range(n)]
    cov = np.diag([0.04] * n)
    d = dict(names=names, w0=np.zeros(n), mu=np.full(n, 0.05), cov=cov, ub=np.full(n, 0.10), buy_cost=np.full(n, 0.001), sell_cost=np.full(n, 0.001),
             risk_aversion=2.5, turnover_penalty=0.0, frozen=np.zeros(n, bool), no_buy=np.zeros(n, bool), no_sell=np.zeros(n, bool))
    d.update(kw)
    return O.Problem(**d)


def test_a_twelve_percent_pick_is_cut_to_the_company_rail():
    n = 6
    mu = np.array([0.30, 0.05, 0.05, 0.05, 0.05, 0.05])               # the first name is wildly attractive: the unconstrained optimum is far over 10%
    p = prob(n, mu=mu, cov=np.diag([0.02] * n))
    r = O.solve(p)
    assert r["ok"] and r["weights"][0] == pytest.approx(0.10, abs=1e-6)
    assert any("S0: at its cap" in b for b in r["binding"])
    assert r["weights"].sum() <= 1.0 + 1e-9 and np.all(r["weights"] >= -1e-12)


def test_sector_cap_and_etf_cap_and_no_leverage():
    n = 8
    sector = np.array([1, 1, 1, 1, 0, 0, 0, 0], float)                # four names of one sector: 4 x 10% would be 40%
    ub = np.array([0.10] * 6 + [0.35, 0.35])
    mu = np.array([0.20] * 4 + [0.05] * 2 + [0.20, 0.20])
    p = prob(n, mu=mu, cov=np.diag([0.01] * n), ub=ub, groups={"sector IT": (sector, 0.25)})
    r = O.solve(p)
    w = r["weights"]
    assert r["ok"] and sector @ w <= 0.25 + 1e-7
    assert w[6] <= 0.35 + 1e-7 and w[7] <= 0.35 + 1e-7 and w.sum() <= 1.0 + 1e-9
    assert any("sector IT" in b for b in r["binding"])


def test_circuit_breaker_means_no_new_buying():
    w0 = np.array([0.05, 0.05, 0.0, 0.0])
    p = prob(4, w0=w0, no_buy=np.ones(4, bool), mu=np.array([0.01, 0.01, 0.2, 0.2]))
    r = O.solve(p)
    assert r["ok"] and np.all(r["weights"] <= w0 + 1e-9)


def test_a_holding_already_over_its_rail_is_not_forced_out_nor_added_to():
    w0 = np.array([0.15, 0.0, 0.0, 0.0])
    p = prob(4, w0=w0, ub=np.full(4, 0.10), mu=np.array([0.30, 0.05, 0.05, 0.05]))
    r = O.solve(p)
    assert r["ok"] and r["weights"][0] <= 0.15 + 1e-9                       # never added to
    p2 = prob(4, w0=w0, ub=np.full(4, 0.10), mu=np.array([-0.5, 0.05, 0.05, 0.05]))
    assert O.solve(p2)["weights"][0] < 0.15                                  # may be sold when the maths says so


def test_costs_and_tax_lower_turnover():
    n = 5
    w0 = np.array([0.33, 0.33, 0.34, 0.0, 0.0])                            # fully invested: a switch needs a sale
    mu = np.array([0.03, 0.03, 0.03, 0.09, 0.09])                          # an edge to switch toward the last two
    kw = dict(w0=w0, mu=mu, ub=np.full(n, 0.34), cov=np.diag([0.01] * n))
    cheap = O.solve(prob(n, **kw, sell_cost=np.full(n, 0.0), buy_cost=np.full(n, 0.0)))
    pd_ = prob(n, **kw, sell_cost=np.full(n, 0.20), buy_cost=np.full(n, 0.002))      # a sale costs 20 paise per rupee (tax on a big gain)
    dear = O.solve(pd_)
    t_cheap = np.abs(cheap["weights"] - w0).sum()
    t_dear = np.abs(dear["weights"] - w0).sum()
    assert t_cheap > 0.05 and t_dear < t_cheap
    assert O.utility(pd_, dear["weights"]) >= O.utility(pd_, w0) - 1e-9           # never worse than doing nothing


def test_drift_to_the_allocation_target_pulls_the_book():
    """Two classes. Equal expected returns; the target says 60% in class 'gold'. With the pull on, the book moves toward it; with the pull off it does not."""
    n = 4
    A = np.array([[0, 0, 1, 1.0], [1, 1, 0, 0.0]])                      # row 0: gold = names 2,3; row 1: equity = names 0,1
    base = dict(w0=np.array([0.30, 0.30, 0.0, 0.0]), ub=np.full(n, 0.35), mu=np.full(n, 0.03), buy_cost=np.full(n, 0.0005), sell_cost=np.full(n, 0.0005))
    off = O.solve(prob(n, **base))
    on = O.solve(prob(n, **base, target_A=A, target_b=np.zeros(2), target_t=np.array([0.60, 0.40]), target_lambda=5.0, target_band=0.02))
    g_off, g_on = off["weights"][2:].sum(), on["weights"][2:].sum()
    assert on["ok"] and abs(g_on - 0.60) < abs(g_off - 0.60) and g_on > g_off + 0.05
    inside = O.solve(prob(n, **base, target_A=A, target_b=np.zeros(2), target_t=np.array([0.01, 0.59]), target_lambda=5.0, target_band=0.02))
    assert inside["ok"]


def test_deterministic_and_seed_free():
    rng = np.random.default_rng(5)
    M = rng.normal(size=(8, 8)) * 0.1
    cov = M @ M.T + np.eye(8) * 0.02
    p = prob(8, mu=rng.normal(0.05, 0.03, 8), cov=cov, w0=np.full(8, 0.05))
    a, b = O.solve(p), O.solve(p)
    assert np.array_equal(a["weights"], b["weights"]) and a["binding"] == b["binding"]


def test_the_optimiser_failing_gives_the_current_weights_and_not_ok():
    w0 = np.array([0.1, 0.1, 0.0, 0.0])
    bad = prob(4, w0=w0, cov=np.full((4, 4), np.nan))
    r = O.solve(bad)
    assert not r["ok"] and np.array_equal(r["weights"], w0) and "non-finite" in r["message"]


def test_frozen_and_no_sell_names_do_not_move():
    w0 = np.array([0.08, 0.08, 0.0, 0.0])
    p = prob(4, w0=w0, mu=np.array([-0.5, -0.5, 0.3, 0.3]), frozen=np.array([True, False, False, False]), no_sell=np.array([False, True, False, False]))
    r = O.solve(p)
    assert r["weights"][0] == pytest.approx(0.08) and r["weights"][1] == pytest.approx(0.08)


# --- costs ------------------------------------------------------------------------------------------------------------------------
def test_charges_and_tax_estimates():
    assert costs.charge("equity", "buy", 100_000) > 0 and costs.charge("equity", "sell", 100_000) > costs.charge("equity", "buy", 100_000) * 0.5
    young = [(date(2026, 6, 1), 100.0, 100.0, "EQUITY")]
    old = [(date(2024, 1, 1), 100.0, 100.0, "EQUITY")]
    t_young, _ = costs.lots_tax(young, 200.0, 100.0, date(2026, 11, 6), "equity")
    t_old, _ = costs.lots_tax(old, 200.0, 100.0, date(2026, 11, 6), "equity")
    assert t_young == pytest.approx(0.20 * 10_000) and t_old == 0.0                    # short term 20%; long term under the Rs 1.25 lakh exemption
    assert costs.tax_rate(young, 200.0, date(2026, 11, 6), "equity") == pytest.approx(0.10)
    assert costs.tax_rate(young, 80.0, date(2026, 11, 6), "equity") == 0.0               # a loss is no cost
    c = costs.trade_cost(young, 200.0, 50.0, "sell", date(2026, 11, 6), "equity")
    assert c["tax"] > 0 and c["charges"] > 0 and costs.trade_cost(young, 200.0, 50.0, "buy", date(2026, 11, 6), "equity")["tax"] == 0


# --- the protocol and the counter ---------------------------------------------------------------------------------------------------
def test_protocol_registration_is_idempotent_and_counts(con):
    from pflab.learner import counter
    n0 = counter.n_tests(con)
    assert C.register(con, NOW) is True and C.register(con, NOW) is False
    assert counter.n_tests(con) == n0 + 1
    assert C.registered_sha(con) == C.protocol_sha()
    assert C.protocol_ok(con) == {"registered": True, "unchanged": True, "why": None}


def test_a_changed_protocol_blocks_the_run_and_the_adoption(con, monkeypatch, tmp_path):
    C.register(con, NOW)
    other = tmp_path / "p.md"
    other.write_text("amended after registration", encoding="utf-8")
    monkeypatch.setattr(C, "PROTOCOL", other)
    assert C.protocol_ok(con)["unchanged"] is False
    out = compare.run(con, NOW, panel=pd.DataFrame())
    assert out["ran"] is False and "changed" in out["why"]
    con.execute("INSERT INTO construct_runs_s85 VALUES (1,'IN','compare',?,?,TRUE,FALSE,?,'{}')", [date(2021, 12, 31), NOW, json.dumps({"verdict": "adopt"})])
    monkeypatch.setattr(C, "settings", lambda: {**C.DEFAULTS, "on": True, "adopt": True})
    assert C.adopted(con) is False                                                     # a changed protocol never adopts


def test_adoption_needs_the_switch_the_stored_verdict_and_the_protocol(con, monkeypatch):
    C.register(con, NOW)
    monkeypatch.setattr(C, "settings", lambda: {**C.DEFAULTS, "on": True, "adopt": True})
    assert C.adopted(con) is False                                                     # no comparison run yet
    con.execute("INSERT INTO construct_runs_s85 VALUES (1,'IN','compare',?,?,TRUE,FALSE,?,'{}')", [date(2021, 12, 31), NOW, json.dumps({"verdict": "loses"})])
    assert C.adopted(con) is False
    con.execute("INSERT INTO construct_runs_s85 VALUES (2,'IN','compare',?,?,TRUE,FALSE,?,'{}')", [date(2021, 12, 31), NOW, json.dumps({"verdict": "adopt"})])
    assert C.adopted(con) is True
    monkeypatch.setattr(C, "settings", lambda: {**C.DEFAULTS, "on": True, "adopt": False})
    assert C.adopted(con) is False
    assert R.construct_sizes(con, NOW, [{"id": 1, "action": "BUY", "isin": "X"}]) == {}


# --- the live path on a synthetic paper book ----------------------------------------------------------------------------------------
A, B, G, E = "INE000A01011", "INE000B01012", "INF000G01013", "INE000E01014"
DAYS = [d.date() for d in pd.bdate_range(end=pd.Timestamp(NOW.date()), periods=330)]


def walk(seed, vol=0.012, start=100.0):
    rng = np.random.default_rng(seed)
    return pd.Series(start * np.exp(np.cumsum(rng.normal(0.0004, vol, len(DAYS)))), index=pd.to_datetime(DAYS))


@pytest.fixture
def live(con):
    series = {A: walk(1), B: walk(2), G: walk(3, 0.008), E: walk(4)}
    for isin, cls, tc, sym, sec in ((A, "equity", "EQUITY", "AAA", "IT"), (B, "equity", "EQUITY", "BBB", "IT"), (G, "etf", "LISTED_NONEQUITY", "GOLDX", None),
                                    (E, "equity", "EQUITY", "EEE", "Banks")):
        con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, ?, 'synthetic', now())",
                    [isin, cls, tc, sym, sym + " Ltd", sec])
        for d, v in series[isin].items():
            con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d.date(), float(v)])
    day = DAYS[-1]
    con.execute("INSERT INTO paper_lots VALUES (1,?,?,?,?,?,?,?)", [A, "AAA", date(2025, 1, 10), 300.0, float(series[A].iloc[-300]), "EQUITY", "seed"])
    con.execute("INSERT INTO paper_lots VALUES (2,?,?,?,?,?,?,?)", [B, "BBB", date(2026, 8, 3), 200.0, float(series[B].iloc[-60]), "EQUITY", "seed"])
    con.execute("INSERT INTO paper_cash VALUES (1,?,?,?,?,?)", [DAYS[0], 400_000.0, "seed", "r", NOW])
    from pflab.paper import book
    book.mark(con, day)
    # the ensemble: a hedge forecast at horizon 20 for every name (tilt +4% a year for A, -6% for B)
    asof = day
    for isin, tilt in ((A, 0.04), (B, -0.06), (G, 0.0), (E, 0.02)):
        m = np.log1p(0.0) + tilt * 20 / 252
        sd = 0.012 * np.sqrt(20)
        q = {str(l): float(np.expm1(m + z * sd)) for l, z in ((0.05, -1.645), (0.1, -1.2816), (0.25, -0.6745), (0.5, 0.0), (0.75, 0.6745), (0.9, 1.2816), (0.95, 1.645))}
        con.execute("INSERT INTO forecasts_s79 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [abs(hash(isin)) % 10**6, "IN", "live", asof, isin, "S", 20, "hedge", json.dumps(q), 100.0, asof, "{}", NOW])
    return con, series


def test_advice_on_a_paper_book_respects_the_rails_and_labels_itself(live):
    con, series = live
    out = R.advise(con, NOW, root=None, closes=series)
    assert out["ok"] and out["adopted"] is False and out["status"].startswith("NOT ADOPTED")
    tw = {r["symbol"]: r for r in out["target_weights"]}
    assert all(r["target_pct"] <= 35.0 + 1e-6 for r in tw.values())
    stocks = [r for s, r in tw.items() if s != "GOLDX"]
    assert all(r["target_pct"] <= max(10.0, r["current_pct"]) + 1e-6 for r in stocks)
    assert tw["AAA"]["target_pct"] + tw["BBB"]["target_pct"] <= max(25.0, tw["AAA"]["current_pct"] + tw["BBB"]["current_pct"]) + 1e-6      # the IT sector
    assert out["cash_target_pct"] >= -1e-6 and "no_forecast_rule" in out["inputs"] and out["inputs"]["names_with_forecast"] == 4
    assert out["est_charges_total"] >= 0 and "ESTIMATES" in out["estimates"]
    assert tw["BBB"]["expected_excess_pct"] < tw["AAA"]["expected_excess_pct"]                        # the ensemble's tilt reaches mu
    again = R.advise(con, NOW, root=None, closes=series)
    assert json.dumps(again["target_weights"]) == json.dumps(out["target_weights"])                    # deterministic


def test_a_name_without_a_forecast_has_zero_expected_excess_and_is_held_where_it_is(live):
    con, series = live
    con.execute("DELETE FROM forecasts_s79 WHERE subject=?", [A])                                      # A is held: no forecast for it
    out = R.advise(con, NOW, root=None, closes=series)
    a = {r["symbol"]: r for r in out["target_weights"]}["AAA"]
    assert a["expected_excess_pct"] == 0.0 and "no forecast" in a["expected_source"]
    assert a["target_pct"] == a["current_pct"]                                                         # no view, no trade
    assert any("no forecast" in n for n in out["notes"]) and out["inputs"]["names_with_forecast"] == 3


def test_breaker_blocks_buying_in_the_advice(live, monkeypatch):
    con, series = live
    from pflab.paper import cadence
    monkeypatch.setattr(cadence, "breaker", lambda c: {"on": True, "drawdown": -0.15, "limit": -0.12})
    out = R.advise(con, NOW, root=None, closes=series)
    assert out["ok"] and all(t["side"] == "sell" for t in out["trades"]) and any("circuit breaker" in n for n in out["notes"])


def test_the_allocation_target_pulls_the_advice(live):
    con, series = live
    from pflab.paper import allocation
    base = R.advise(con, NOW, root=None, closes=series)
    r = allocation.propose_allocation(con, {"equity": 85, "gold": 5, "international": 0, "cash": 10}, "a test target with enough reasons given for the check to pass", NOW, sectors={})
    assert r["stored"]
    allocation.review_target(con, r["target_id"], "approve", "ok", NOW)
    pulled = R.advise(con, NOW, root=None, closes=series)
    gb = {x["symbol"]: x for x in base["target_weights"]}.get("GOLDX", {"target_pct": 0.0})["target_pct"]
    gp = {x["symbol"]: x for x in pulled["target_weights"]}.get("GOLDX", {"target_pct": 0.0})["target_pct"]
    assert pulled["ok"] and gp < gb and pulled["inputs"]["target_id"] == r["target_id"]


def test_optimiser_failure_falls_back_to_the_current_rules(live, monkeypatch):
    con, series = live
    monkeypatch.setattr(O, "solve", lambda p, **k: {"ok": False, "weights": p.w0, "message": "forced failure", "binding": []})
    out = R.advise(con, NOW, root=None, closes=series)
    assert out["ok"] is False and out["fallback"] == "the current sizing rules decide" and out["target_weights"] == []
    monkeypatch.setattr(O, "solve", lambda p, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert R.advise(con, NOW, root=None, closes=series)["ok"] is False


def test_construct_sizes_only_when_adopted_and_the_manager_hook_is_inert_otherwise(live, monkeypatch):
    con, series = live
    dec = [{"id": 1, "action": "BUY", "isin": E}]
    assert R.construct_sizes(con, NOW, dec, closes=series) == {}
    assert R.size_buy(con, NOW, 1, E, "BUY", closes=series) is None
    C.register(con, NOW)
    con.execute("INSERT INTO construct_runs_s85 VALUES (1,'IN','compare',?,?,TRUE,FALSE,?,'{}')", [date(2021, 12, 31), NOW, json.dumps({"verdict": "adopt"})])
    monkeypatch.setattr(C, "settings", lambda: {**C.DEFAULTS, "on": True, "adopt": True})
    s = R.construct_sizes(con, NOW, dec, closes=series)
    assert "1" in s and s["1"]["amount_rupees"] >= 0.0
    assert s["1"]["amount_rupees"] <= 0.10 * 1_000_000                                   # inside the 10% rail whatever the book is


def test_dossier_text_is_labelled_and_off_switch_silences_it(live, monkeypatch):
    con, series = live
    monkeypatch.setattr(R, "load_closes", lambda *a, **k: series)
    t = R.dossier_text(con, NOW)
    assert t.startswith("CONSTRUCT (NOT ADOPTED") and "current rules" in t
    monkeypatch.setattr(R, "settings", lambda: {**C.DEFAULTS, "on": False})
    assert R.dossier_text(con, NOW) == ""


# --- the tool ---------------------------------------------------------------------------------------------------------------------
def _ctx(con):
    return SimpleNamespace(con=con, now=NOW, rt=SimpleNamespace(data_root=None), call_ref=77)


def test_tool_works_with_no_input_and_no_book(con):
    from pflab.hq import tools as hq_tools
    t = hq_tools.TOOLS["construct"]
    assert t.name == "construct" and t.kind == "read" and t.required == ()
    out = t.fn(_ctx(con), {})
    assert isinstance(out, dict) and out["ok"] is False and "note" in out and out["fallback"]


def test_tool_off_switch(con, monkeypatch):
    from pflab.hq import tools as hq_tools
    monkeypatch.setattr(C, "settings", lambda: {**C.DEFAULTS, "on": False})
    assert hq_tools.TOOLS["construct"].fn(_ctx(con), {}) == {"off": True}


def test_tool_on_a_book_and_registered_as_a_read_tool(live, monkeypatch):
    con, series = live
    monkeypatch.setattr(R, "load_closes", lambda *a, **k: series)
    from pflab.hq import tools as hq_tools
    assert hq_tools.TOOLS["construct"].kind == "read"
    out = hq_tools.TOOLS["construct"].fn(_ctx(con), {})
    assert out["ok"] and out["call_id"] == 77 and out["target_weights"] and out["status"].startswith("NOT ADOPTED")
    assert con.execute("SELECT count(*) FROM learn_tests WHERE note='s79:construct'").fetchone()[0] == 1


# --- the comparison engine on a synthetic panel -----------------------------------------------------------------------------------------
def synth_panel(n_stocks=14, start="2010-01-04", end="2013-06-28", seed=0):
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    rows = []
    mk = rng.normal(0.0003, 0.008, len(idx))
    for j in range(n_stocks + 4):
        etf = j >= n_stocks
        sym = ["NIFTYBEES", "JUNIORBEES", "BANKBEES", "GOLDBEES"][j - n_stocks] if etf else f"STK{j}"
        beta = 1.0 if etf else rng.uniform(0.6, 1.4)
        r = beta * mk + rng.normal(0.0002, 0.012 if not etf else 0.002, len(idx))
        px = 100 * np.exp(np.cumsum(r))
        for d, p in zip(idx, px):
            rows.append((d, f"ETF:{sym}" if etf else f"INE{j:03d}A01010", sym, "ETF" if etf else "STK", p, 1e7 * (1 + j)))
    df = pd.DataFrame(rows, columns=["date", "key", "symbol", "kind", "adj_close", "turnover"])
    df["isin"] = df["key"]
    return df


def stub_sector(keys, day):
    return {k: (None if k.startswith("ETF:") else ("S" + str(int(k[3:6]) % 3))) for k in keys}


def test_rule_weights_respect_the_rails():
    keys = ["a", "b", "c", "e"]
    w = compare.rule_weights(keys, {"a": False, "b": False, "c": False, "e": True}, {"a": "X", "b": "X", "c": "X"})
    assert w["a"] + w["b"] + w["c"] <= 0.25 + 1e-12 and all(w[k] <= 0.10 + 1e-12 for k in "abc") and w["e"] <= 0.35
    w2 = compare.rule_weights(["a", "b"], {"a": False, "b": True}, {})
    assert w2["a"] == pytest.approx(0.10) and w2["b"] == pytest.approx(0.35)


def test_the_panel_refuses_the_spent_years():
    df = synth_panel(3, "2020-01-01", "2022-03-01")
    with pytest.raises(AssertionError):
        compare.to_wide(df)


def test_simulation_runs_both_arms_net_of_costs_and_is_deterministic(con):
    df = synth_panel()
    px, to, meta = compare.to_wide(df)
    P = dict(compare.PARAMS, n_liquid=10, n_picks=8, resamples=200)
    a = compare.simulate(px, to, meta, stub_sector, P)
    assert a["n_rebalances"] >= 12 and a["rule"]["charges"] > 0 and a["construct"]["charges"] > 0
    for arm in ("rule", "construct"):
        assert a[arm]["end_value"] > 0 and -1.0 < a[arm]["max_drawdown"] <= 0 and a[arm]["liquidation_value"] > 0
    assert a["optimiser_failures"] <= a["n_rebalances"] // 4
    b = compare.simulate(px, to, meta, stub_sector, P)
    assert a["construct"] == b["construct"] and a["rule"] == b["rule"]
    boot = compare.bootstrap_dS(a["construct_path"], a["rule_path"], P)
    assert 0.0 <= boot["p_one_sided"] <= 1.0 and boot["ci90"][0] <= boot["ci90"][1]
    assert boot == compare.bootstrap_dS(a["construct_path"], a["rule_path"], P)


def test_decision_rule_in_code():
    res = {"construct": {"max_drawdown": -0.20, "liquidation_cagr": 0.12}, "rule": {"max_drawdown": -0.21, "liquidation_cagr": 0.12}}
    assert compare.decide(res, {"dS": 0.15, "p_one_sided": 0.03})["verdict"] == "adopt"
    assert compare.decide(res, {"dS": 0.15, "p_one_sided": 0.20})["verdict"] == "inconclusive"
    assert compare.decide(res, {"dS": -0.05, "p_one_sided": 0.7})["verdict"] == "loses"
    worse = {"construct": {"max_drawdown": -0.30, "liquidation_cagr": 0.12}, "rule": {"max_drawdown": -0.21, "liquidation_cagr": 0.12}}
    assert compare.decide(worse, {"dS": 0.15, "p_one_sided": 0.01})["verdict"] == "inconclusive"
    cash = {"construct": {"max_drawdown": -0.05, "liquidation_cagr": 0.06}, "rule": {"max_drawdown": -0.21, "liquidation_cagr": 0.12}}
    assert compare.decide(cash, {"dS": 0.5, "p_one_sided": 0.01})["verdict"] == "inconclusive"          # Sharpe bought by sitting in cash does not count


def test_run_is_once_only_and_writes_the_verdict(con):
    C.register(con, NOW)
    P = dict(compare.PARAMS, n_liquid=10, n_picks=8, resamples=100)
    out = compare.run(con, NOW, panel=synth_panel(), sector_fn=stub_sector, P=P)
    assert out["ran"] and out["verdict"] in ("adopt", "loses", "inconclusive") and out["params"]["seed"] == 79
    assert C.verdict(con)["verdict"] == out["verdict"]
    again = compare.run(con, NOW, panel=synth_panel(), sector_fn=stub_sector, P=P)
    assert again["ran"] is False and "already" in again["why"]
