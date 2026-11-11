"""S81 core-lab (B1-B3): baseline_v2 (core ETFs, gradual and tax-aware), sleeves, the strategist's allocation proposal with the sleeve caps, the two-dimension index rule (after tax on both
sides), the always-present index candidates, probation slices (5% -> 10% -> 20%, withdrawal) and the throttle switch (A55). Synthetic data only."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab import core
from pflab.core import baseline_v2, loop, policy, rails, sleeves, state as st
from pflab.lab import alloc_lab, engine, probation, promotion, service, shadow, strategist, tools
from pflab.ledger import events as ev
from pflab.ledger import system
from pflab.paper import allocation, book
from pflab.pm import store
from tests.test_s80_core import calm_index
from tests.test_s80_lab import MOMENTUM, make_data

NOW = datetime(2026, 10, 30, 16, 0)
DAYS = [d.date() for d in pd.bdate_range("2025-08-01", "2026-10-30")]
STOCKS = [(f"INE00{i}A01011", f"STK{i}") for i in range(8)]
ETFS = {"MONIFTY500": ("INF000N5001", "Motilal Oswal Nifty 500 ETF", "EQUITY"), "NIFTYBEES": ("INF000N0501", "Nippon India ETF Nifty 50 BeES", "EQUITY"),
        "GOLDBEES": ("INF000GB001", "Nippon India ETF Gold BeES", "LISTED_NONEQUITY"), "MON100": ("INF000MN101", "Motilal Oswal Nasdaq 100 ETF", "LISTED_NONEQUITY")}


@pytest.fixture
def con(tmp_path, monkeypatch):
    """A paper book of eight stocks (each about 6% of the book, 47% together) and Rs 5 lakh of cash; the four core ETFs are in the store with prices but not held."""
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setenv("PFLAB_SANDBOX", "local")
    c = store.connect(tmp_path / "l.duckdb")
    for isin, sym in STOCKS:
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, 'synthetic', now())", [isin, sym, sym + " Ltd"])
    for sym, (isin, name, tc) in ETFS.items():
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'etf', ?, TRUE, ?, ?, 'synthetic', now())", [isin, tc, sym, name])
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha')")
    log = ev.EventLog()
    log.append(ev.Event(kind="deposit", account_id="ZER", date=date(2024, 1, 1), amount=2_000_000.0))
    for isin, _ in STOCKS:
        log.append(ev.Event(kind="buy", account_id="ZER", date=date(2025, 3, 3), isin=isin, qty=500, price=80.0))
    ev.save(c, log, NOW)
    allisins = [i for i, _ in STOCKS] + [v[0] for v in ETFS.values()]
    for n, isin in enumerate(allisins):
        for k, d in enumerate(DAYS):
            wob = 1.0 + (0.01 + 0.002 * (n % 3)) * (1 if k % 2 else -1)
            c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d, 100.0 * (1.0003 + 0.00002 * n) ** k * wob])
    system.switch(c, tmp_path, DAYS[-6], NOW)
    book.seed(c, DAYS[-6], NOW)
    book.catch_up(c, DAYS[-1], datetime.combine(DAYS[-1], datetime.min.time()) + timedelta(hours=21))
    return c


def _state(con, drop=0.0):
    return st.build(con, DAYS[-1], None, calm_index(drop))


# --- B1: baseline_v2 ----------------------------------------------------------------------------------------------------------------------------

def test_baseline_v2_buys_the_core_etfs_from_the_first_close_and_sells_nothing(con):
    s = _state(con)
    core_rows = {r["symbol"]: r for r in s["rows"] if r["symbol"] in ETFS}
    assert set(core_rows) == set(ETFS) and all(r["qty"] == 0 and r["sleeve"] == "core" and r["buyable"] for r in core_rows.values())
    assert all(r["sleeve"] == "longterm" for r in s["rows"] if r["symbol"].startswith("STK"))
    d = baseline_v2.decide(s)
    cur = {r["isin"]: r["weight"] for r in s["rows"]}
    for r in core_rows.values():
        assert d["weights"][r["isin"]] > 0                                          # it may BUY the core ETFs (baseline_v1 trades only names already held)
    for isin, _ in STOCKS:
        assert d["weights"][isin] == pytest.approx(cur[isin])                       # the held names stay: the longterm sleeve (47%) is above its 35% target, so nothing is bought or sold
    chk = rails.check(con, s, d)
    assert chk["orders"] and all(o["side"] == "buy" for o in chk["orders"])
    assert {o["symbol"] for o in chk["orders"]} <= set(ETFS)
    assert sum(o["value"] for o in chk["orders"]) <= 0.10 * s["value"] + 1.0         # the turnover cap still binds: the target is reached over several sessions


def test_the_path_is_gradual_and_tax_aware_cash_goes_to_the_core_and_no_stock_is_sold_to_reach_it(con):
    s = _state(con)
    d = baseline_v2.decide(s)
    cur = {r["isin"]: r["weight"] for r in s["rows"]}
    inc = {k: w - cur[k] for k, w in d["weights"].items()}
    assert all(v >= -1e-12 for v in inc.values())                                   # no sale at all
    free = (s["cash"] + s["bank"]) / s["value"]
    assert sum(v for v in inc.values()) <= free + 1e-9                              # no more than the new cash (the longterm sleeve's last 5 points wait as cash: A60, `longterm_buy_pct`)
    core_buy = sum(v for k, v in inc.items() if k in {r["isin"] for r in s["rows"] if r["sleeve"] == "core"})
    assert core_buy > 0.5 * free                                                    # and it all goes to the core first
    assert any("longterm names wait" in n or "cash is" in n for n in d["notes"])
    cap_core = 0.0
    for r in s["rows"]:
        if r["sleeve"] == "core":
            cap_core += d["weights"].get(r["isin"], 0.0)
    assert cap_core <= s["sleeve_target"]["core"] + 1e-9                            # never above the core's target


def test_the_gauge_cuts_equity_only_and_a_name_over_its_rail_is_trimmed_to_it(con):
    s = _state(con, drop=0.15)
    assert s["gauge"]["fired"]
    d = baseline_v2.decide(s)
    cur = {r["isin"]: r["weight"] for r in s["rows"]}
    for isin, _ in STOCKS:
        assert d["weights"][isin] == pytest.approx(cur[isin] * 0.75)
    assert all(d["weights"][r["isin"]] == pytest.approx(0.0) for r in s["rows"] if r["sleeve"] == "core")         # nothing held there and nothing is bought while the gauge is on
    s2 = _state(con)
    big = s2["rows"][0]
    big["value"] = 0.15 * s2["value"]
    d2 = baseline_v2.decide(s2)
    assert d2["weights"][big["isin"]] == pytest.approx(0.10) and any("over the 10% rail" in n for n in d2["notes"])


def test_the_loop_runs_baseline_v2_buys_the_core_etfs_and_tags_their_sleeve(con):
    assert policy.active_id() == "baseline_v2"
    r = loop.run(con, NOW, None, calm_index())
    assert r["status"] == "traded"
    sells = con.execute("SELECT reason FROM paper_decisions WHERE action IN ('SELL','REDUCE')").fetchall()
    assert all(x[0].startswith("exit manager") for x in sells)                   # the policy never sells to reach a sleeve share; only the exit manager's rail trims sell
    assert any(o["side"] == "buy" for o in r["orders"])
    assert con.execute("SELECT policy_id FROM core_runs_s80 WHERE day=?", [DAYS[-1]]).fetchone()[0] == "baseline_v2"
    assert con.execute("SELECT status FROM core_policies_s80 WHERE policy_id='baseline_v2'").fetchone()[0] == "champion"
    assert con.execute("SELECT status FROM core_policies_s80 WHERE policy_id='baseline_v1'").fetchone()[0] == "previous"
    tagged = {i: sl for i, sl in con.execute("SELECT isin, sleeve FROM sleeves_s81").fetchall()}
    assert tagged and "core" in set(tagged.values()) and set(tagged.values()) <= {"core", "longterm"}      # the bought ETFs are core; a name the exit manager trimmed keeps its longterm tag
    why = con.execute("SELECT reason FROM paper_decisions WHERE action IN ('BUY','ADD') ORDER BY decision_id DESC LIMIT 1").fetchone()[0]
    assert why.startswith("baseline_v2:")


def test_the_config_can_fall_back_to_baseline_v1(con, monkeypatch):
    real = core.settings
    monkeypatch.setattr(core, "settings", lambda: {**real(), "baseline_v2": {**real()["baseline_v2"], "version": "v1"}})
    assert policy.active_id() == "baseline_v1" and policy.universe(con) == []


def test_a_core_etf_the_store_does_not_know_is_named_not_guessed(con, monkeypatch):
    real = core.settings
    cfg = real()
    cfg["baseline_v2"]["international_etfs"] = ["NOSUCHETF"]
    s = st.build(con, DAYS[-1], None, calm_index(), cfg=cfg)
    d = baseline_v2.decide(s)
    assert any("no international ETF has a price" in n for n in d["notes"])


def test_the_default_target_is_core_60_longterm_40_with_gold_and_international_10_each():
    sh = sleeves.default_shares(core.settings())
    assert (sh["core"], sh["longterm"], sh["gold"], sh["international"]) == (0.60, 0.40, 0.10, 0.10) and "swing" not in sh and sh["index"] == pytest.approx(0.40)


# --- sleeves -----------------------------------------------------------------------------------------------------------------------------------

def test_sleeves_default_by_instrument_stick_once_and_add_up(con):
    isin_stock, isin_etf = STOCKS[0][0], ETFS["GOLDBEES"][0]
    assert sleeves.sleeve_of(con, isin_stock) == "longterm" and sleeves.sleeve_of(con, isin_etf) == "core"
    assert sleeves.set_sleeve(con, isin_stock, "core", DAYS[-1]) == "core"
    assert sleeves.set_sleeve(con, isin_stock, "longterm", DAYS[-1]) == "core"              # the first record stays
    assert sleeves.set_sleeve(con, isin_stock, "longterm", DAYS[-1], force=True) == "longterm"
    for gone in ("swing", "intraday"):                                                       # the swing sleeve is deleted (A60); intraday was dropped (A48)
        with pytest.raises(ValueError):
            sleeves.set_sleeve(con, isin_stock, gone)
    w = sleeves.sleeve_weights(con, "IN", DAYS[-1])
    assert w["longterm"] == pytest.approx(0.47, abs=0.03) and w["core"] == 0 and "swing" not in w
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-3)


# --- B2: the strategist's proposal and the sleeve caps -------------------------------------------------------------------------------------------

GOOD_CLASSES = {"equity": 70, "gold": 15, "international": 10, "cash": 5}
GOOD_SLEEVES = {"core": 60, "longterm": 40}
REASONS = "A larger core with some gold, because the longterm names are concentrated and the index owns the market after tax; re-examined weekly."


def test_the_sleeve_caps_refuse_a_bad_proposal_and_a_good_one_is_stored_as_a_lab_policy(con, tmp_path):
    for bad, why in (({"core": 50, "longterm": 30, "swing": 20.5}, "the swing sleeve is deleted"), ({"core": 39, "longterm": 60.5}, "longterm at 60.5% is over the 60% cap"),
                     ({"core": 29, "longterm": 71}, "core at 29% is under the 30% floor"), ({"core": 50, "longterm": 45}, "add up to 95%"),
                     ({"core": 20, "longterm": 60, "swing": 20}, "the swing sleeve is deleted")):
        r = alloc_lab.propose(con, tmp_path, NOW, {"equity": 100, "gold": 0, "international": 0, "cash": 0}, bad, REASONS)
        assert r["ok"] is False and why in r["problem"], (bad, r)
    r = alloc_lab.propose(con, tmp_path, NOW, {"equity": 70, "gold": 20, "international": 20, "cash": -10}, GOOD_SLEEVES, REASONS)           # a class below zero is refused by the rails
    assert r["ok"] is False and "below zero" in r["problem"]
    r = alloc_lab.propose(con, tmp_path, NOW, {"equity": 75, "gold": 15, "international": 10, "cash": 0}, {"core": 20, "longterm": 60, "swing": 20}, REASONS)
    assert r["ok"] is False and "swing sleeve is deleted" in r["problem"]
    r = alloc_lab.propose(con, tmp_path, NOW, {"equity": 50, "gold": 30, "international": 25, "cash": -5}, GOOD_SLEEVES, REASONS)
    assert r["ok"] is False
    r = alloc_lab.propose(con, tmp_path, NOW, {"equity": 30, "gold": 40, "international": 30, "cash": 0}, {"core": 60, "longterm": 40}, REASONS)       # gold + international exceed the core
    assert r["ok"] is False and "core holdings" in r["problem"]
    assert allocation.pending(con) == []                                           # nothing was stored for a bad proposal
    r = alloc_lab.propose(con, tmp_path, NOW, {"equity": 85, "gold": 5, "international": 5, "cash": 5}, GOOD_SLEEVES, REASONS, sectors={"Banks": 30})            # the 25% sector rail
    assert r["ok"] is False and "25%" in r["problem"]
    ok = alloc_lab.propose(con, tmp_path, NOW, GOOD_CLASSES, GOOD_SLEEVES, REASONS, sectors={"Banks": 20})
    assert ok["ok"] and ok["status"] == "proposed" and ok["variant"] == f"alloc_t{ok['target_id']}"
    assert allocation.active_target(con) is None and len(allocation.pending(con)) == 1          # a proposal is not active: adoption is the A50 rule
    assert sleeves.stored(con, ok["target_id"])["sleeves"] == {"core": 60.0, "longterm": 40.0}
    p = service.get(con, ok["variant"])
    assert p["status"] == "draft" and "'idx': 0.3" in p["code"] and "'longterm': 0.4" in p["code"]       # index = core 60 - gold 15 - international 10 - cash 5 = 30
    again = alloc_lab.propose(con, tmp_path, NOW, {"equity": 70, "gold": 15, "international": 10, "cash": 5}, GOOD_SLEEVES, REASONS + " (again)", sectors={"Banks": 20})
    assert again["ok"] and again["target_id"] != ok["target_id"] or again.get("reaffirmed")


def test_the_strategist_tool_stores_the_proposal_and_his_targets_are_never_touched(con, tmp_path):
    ctx = tools.make_ctx(con, tmp_path, None, NOW, 1)
    text, is_err = tools.run(ctx, "propose_allocation", {"classes": GOOD_CLASSES, "sleeves": GOOD_SLEEVES, "reasons": REASONS, "sectors": {}})
    assert not is_err and json.loads(text)["ok"] is True
    assert "propose_allocation" in {d["name"] for d in tools.definitions()} and all(len(d["description"]) < 480 for d in tools.definitions())
    text, is_err = tools.run(ctx, "propose_allocation", {"classes": GOOD_CLASSES, "sleeves": {"core": 40, "longterm": 30, "swing": 30}, "reasons": REASONS})
    assert is_err and "swing sleeve is deleted" in json.loads(text)["problem"]
    import inspect
    assert "targets.toml" not in inspect.getsource(alloc_lab) .replace("his `targets.toml`", "")   # the module never reads or writes his targets file


def test_the_first_message_of_a_session_shows_the_allocation_to_re_examine(con, tmp_path):
    alloc_lab.seed(con, tmp_path, NOW)
    msg = strategist._first_message(con, "the weekly session (re-examine the allocation)", 300.0)
    assert "ALLOCATION IN FORCE" in msg and "propose_allocation" in msg and "index_hold_s82" in msg and "alloc_default" in msg and "core >= 30%" in msg and "swing" not in msg


# --- B3: the two-dimension index rule ------------------------------------------------------------------------------------------------------------

def _score(cagr_liq, bench_liq, fall, ifall):
    return {"cagr_liq": cagr_liq, "bench_cagr_liq": bench_liq, "max_drawdown": fall, "bench_max_drawdown_net": ifall, "index_etf_cost": 0.002}


def test_the_index_rule_on_four_hand_made_score_pairs():
    A = service.index_rule(_score(0.115, 0.13, -0.38, -0.40))          # 1.5 points behind, a fall no deeper: pass by branch A
    assert A["ok"] and A["via"] == "A" and A["lag"] == pytest.approx(0.015)
    B = service.index_rule(_score(0.095, 0.13, -0.24, -0.40))          # 3.5 points behind but a fall 40% smaller: pass by branch B
    assert B["ok"] and B["via"] == "B" and B["fall_ratio"] == pytest.approx(0.6)
    R = service.index_rule(_score(0.085, 0.13, -0.20, -0.40))          # 4.5 points behind: fails on return even with half the fall
    assert not R["ok"] and "trails the index by 4.5%" in R["failed"][0]
    F = service.index_rule(_score(0.14, 0.13, -0.45, -0.40))           # ahead on return but a deeper fall, and not a third smaller: fails on the fall
    assert not F["ok"] and "deeper" in F["failed"][0]
    edge = service.index_rule(_score(0.11, 0.13, -0.40, -0.40))        # exactly 2.0 points behind with an equal fall: A holds (the limits are inclusive)
    assert edge["ok"]
    gap = service.index_rule(_score(0.095, 0.13, -0.27, -0.40))        # 3.5 points behind, a fall 32.5% smaller: not a third, fails
    assert not gap["ok"]
    assert not service.index_rule({"cagr": 0.1})["ok"]                 # a score without the after-tax figures cannot pass
    assert service.INDEX_RULE["a_max_lag"] == 0.02 and service.INDEX_RULE["b_max_lag"] == 0.04


def test_both_sides_are_compared_after_tax_and_charges():
    data = make_data()
    px = data["px"]
    bench = px["ETF:NIFTYBEES"]
    cfg = {"capital": 1_000_000.0}
    first = pd.Timestamp("2011-01-03")
    v = pd.Series(1_000_000.0 * (bench.loc[first:] / bench.loc[first:].iloc[0]), index=bench.loc[first:].index)
    ix = engine.index_after_tax(bench, v, {**engine.DEFAULT_CFG, **cfg})
    gross = float(bench.loc[first:].iloc[-1] / bench.loc[first:].iloc[0])
    years = (v.index[-1] - v.index[0]).days / 365.25
    end = 1_000_000.0 * (1 - 0.0003) * gross * (1 - 0.002) ** years
    gain = end * (1 - 0.0003) - 1_000_000.0
    tax = 0.125 * max(0.0, gain - 125_000.0) if (v.index[-1] - v.index[0]).days > 365 else 0.20 * max(0.0, gain)
    assert ix["bench_end_after_tax"] == pytest.approx(end * (1 - 0.0003) - tax, rel=2e-3)
    assert ix["index_tax_at_end"] == pytest.approx(tax, rel=2e-3) and ix["index_etf_cost"] == 0.002 and ix["index_charges"] > 0
    assert ix["bench_cagr_liq"] < ix["bench_cagr_net"]                                  # tax at the end lowers the index's own return
    # the policy side is liquidated the same way: a buy-and-hold of one stock pays the tax of its unrealised gain at the end
    one = [c for c in px.columns if not c.startswith("ETF:")][0]

    def hold(state, f, s, sl, params=None):
        return {one: 0.10}
    run = engine.replay(hold, {}, data, "2011-01-03", "2016-06-30")
    sc = engine.score(run, data, {})
    assert sc["cagr_liq"] < sc["cagr"] + 1e-12 and sc["policy_charges_at_end"] > 0
    assert sc["bench_cagr_liq"] < sc["bench_cagr"]                                      # the index side is after its ETF cost, charges and tax too
    assert sc["excess_liq"] == pytest.approx(sc["cagr_liq"] - sc["bench_cagr_liq"])
    assert sc["bench_max_drawdown_net"] is not None and sc["index_charges"] > 0
    assert service.index_rule(sc)["figures"]["index_tax_at_end"] is not None            # the figures travel in the score to the rule and to the screens


# --- the always-present candidates --------------------------------------------------------------------------------------------------------------

def test_the_index_candidates_are_seeded_once_and_are_valid_lab_policies(con, tmp_path):
    first = alloc_lab.seed(con, tmp_path, NOW)
    assert set(first) == {"index_hold_s82", "alloc_default"}
    assert alloc_lab.seed(con, tmp_path, NOW) == [] and alloc_lab.seed(con, tmp_path, NOW) == []
    assert con.execute("SELECT count(*) FROM core_policies_s80 WHERE policy_id IN ('index_hold_s82','alloc_default')").fetchone()[0] == 2
    from pflab.lab import policy_api
    for pid in ("index_hold_s82", "alloc_default"):
        p = service.get(con, pid)
        assert policy_api.validate(p["code"]) == [] and p["status"] == "draft"
    code = service.get(con, "index_hold_s82")["code"]                                    # S82 C3: the India core as the two broad index ETFs; JUNIORBEES is not broad; sleeves and international kept
    defaults_line = [ln for ln in code.splitlines() if ln.startswith("DEFAULTS =")][0]
    assert "'idx_syms': ['NIFTYBEES', 'MONIFTY500']" in defaults_line
    assert "'idx': 0.5" in code and "'gold': 0.0" in code
    assert "'intl': 0.1" in code and "'longterm': 0.4" in code
    assert "'idx': 0.4" in service.get(con, "alloc_default")["code"]


def test_the_allocation_variants_replay_in_the_lab_and_buy_the_core_etfs(con, tmp_path):
    data = make_data()
    px = data["px"].copy()
    for sym, key in (("MONIFTY500", "ETF:MONIFTY500"), ("MON100", "ETF:MON100")):                    # the replay's modelled ETFs (here: copies of a synthetic ETF)
        px[key] = data["px"]["ETF:NIFTYBEES"] * (1.0 + 0.0001 * len(key))
    meta = dict(data["meta"])
    for sym, key in (("MONIFTY500", "ETF:MONIFTY500"), ("MON100", "ETF:MON100")):
        meta[key] = {"symbol": sym, "etf": True, "sector": None, "tax": "EQUITY"}
    to = px * 0 + 5e8
    d2 = {**data, "px": px, "turnover": to, "meta": meta}
    alloc_lab.seed(con, tmp_path, NOW)
    from pflab.lab import policy_api
    for pid in ("index_hold_s82", "alloc_default"):
        fn, _ = policy_api.load(service.get(con, pid)["code"])
        run = engine.replay(fn, {}, d2, "2012-01-02", "2015-12-31")
        held = {k for k in run["book"].lots if run["book"].qty(k) > 0}
        assert run["failures"] == 0 and "ETF:MONIFTY500" in held
        sc = engine.score(run, d2, {})
        assert sc["cagr_liq"] is not None and sc["bench_cagr_liq"] is not None
    pure = alloc_lab.render_code({"idx": 0.98, "gold": 0.0, "intl": 0.0, "longterm": 0.0, "idx_syms": alloc_lab.broad_syms()})
    run = engine.replay(policy_api.load(pure)[0], {}, d2, "2012-01-02", "2015-12-31")
    assert not [k for k in run["book"].lots if run["book"].qty(k) > 0 and not k.startswith("ETF:")]      # a pure index book holds no stock


# --- adoption by the A50 rule --------------------------------------------------------------------------------------------------------------------

def _hist(con, pid, score, params=None):
    from pflab.pm.store import next_id
    con.execute("INSERT INTO lab_runs_s80 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [next_id(con, "lab_runs_s80", "run_id"), pid, "history", json.dumps(params or {}, sort_keys=True), NOW, None, json.dumps(score), "{}", "{}",
                                                                                 0.9, 0.05, 5, 1.0, False])


PASS = {**_score(0.125, 0.13, -0.35, -0.40), "cagr": 0.13, "sharpe_daily": 0.05, "dsr": 0.9}
BETTER = {**_score(0.15, 0.13, -0.35, -0.40), "cagr": 0.16, "sharpe_daily": 0.06, "dsr": 0.95}
FAIL = {**_score(0.08, 0.13, -0.45, -0.40), "cagr": 0.09, "sharpe_daily": 0.03, "dsr": 0.5}


def test_a_proposal_that_passes_the_index_rule_and_the_final_check_is_adopted(con, tmp_path, monkeypatch):
    alloc_lab.seed(con, tmp_path, NOW)
    _hist(con, "alloc_default", PASS)
    _hist(con, "index_hold_s82", PASS)
    ok = alloc_lab.propose(con, tmp_path, NOW, GOOD_CLASSES, GOOD_SLEEVES, REASONS)
    _hist(con, ok["variant"], BETTER)
    monkeypatch.setattr(promotion, "final_run", lambda *a, **k: {"score": BETTER, "baseline": {}})
    out = alloc_lab.tick(con, tmp_path, None, NOW)
    assert out["verdicts"] == [{"target_id": ok["target_id"], "outcome": "adopted"}]
    act = allocation.active_target(con)
    assert act["target_id"] == ok["target_id"] and alloc_lab.current_variant(con) == ok["variant"]
    sh = sleeves.target_shares(con, core.settings(), {"id": act["target_id"], "classes": act["classes"], "sectors": act["sectors"]})
    assert (sh["core"], sh["longterm"], sh["gold"], sh["international"], sh["cash"]) == (0.60, 0.40, 0.15, 0.10, 0.05) and sh["index"] == pytest.approx(0.30)
    s = _state(con)
    assert s["sleeve_target"]["source"].startswith("allocation target")                 # baseline_v2 now holds the adopted target
    assert con.execute("SELECT outcome FROM alloc_verdicts_s81").fetchone()[0] == "adopted"


def test_a_proposal_that_fails_or_is_not_above_the_current_allocation_is_not_adopted(con, tmp_path, monkeypatch):
    alloc_lab.seed(con, tmp_path, NOW)
    _hist(con, "alloc_default", PASS)
    _hist(con, "index_hold_s82", PASS)
    monkeypatch.setattr(promotion, "final_run", lambda *a, **k: {"score": BETTER, "baseline": {}})
    a = alloc_lab.propose(con, tmp_path, NOW, GOOD_CLASSES, GOOD_SLEEVES, REASONS)
    _hist(con, a["variant"], FAIL)
    out = alloc_lab.tick(con, tmp_path, None, NOW)
    assert out["verdicts"][0]["outcome"] == "not adopted" and allocation.active_target(con) is None
    b = alloc_lab.propose(con, tmp_path, NOW, {"equity": 60, "gold": 20, "international": 15, "cash": 5}, {"core": 65, "longterm": 35}, REASONS + " variant two")
    _hist(con, b["variant"], {**PASS, "cagr_liq": 0.120})                              # passes the rule but is below the current allocation's 12.5%
    out = alloc_lab.tick(con, tmp_path, None, NOW)
    assert out["verdicts"][0]["outcome"] == "not adopted" and any("not above the current" in r for r in out["verdicts"][0]["reasons"])
    c = alloc_lab.propose(con, tmp_path, NOW, {"equity": 60, "gold": 22, "international": 13, "cash": 5}, {"core": 65, "longterm": 35}, REASONS + " variant three")
    _hist(con, c["variant"], BETTER)
    monkeypatch.setattr(promotion, "final_run", lambda *a, **k: {"score": FAIL, "baseline": {}})   # passes the history, fails the once-only final check
    out = alloc_lab.tick(con, tmp_path, None, NOW)
    assert out["verdicts"][0]["outcome"] == "not adopted" and any("final check 2018-2021" in r for r in out["verdicts"][0]["reasons"])
    assert allocation.active_target(con) is None


def test_when_the_current_allocation_fails_the_index_rule_and_the_index_passes_the_system_owns_the_india_core_only(con, tmp_path):
    alloc_lab.seed(con, tmp_path, NOW)
    _hist(con, "alloc_default", FAIL)
    _hist(con, "index_hold_s82", PASS)
    out = alloc_lab.tick(con, tmp_path, None, NOW)
    assert out["adopted_index_only"]["adopted"] is True
    act = allocation.active_target(con)
    assert act["classes"] == {"equity": 90.0, "gold": 0.0, "international": 10.0, "cash": 0.0}      # gold moved into the index ETFs; the international share is KEPT (held in the US sub-book)
    assert sleeves.stored(con, act["target_id"])["sleeves"] == {"core": 60.0, "longterm": 40.0}     # the sleeve shares are KEPT: the longterm stocks are not sold for a sleeve share
    assert alloc_lab.current_variant(con) == "index_hold_s82" and "owns the index for the India core" in act["reasons"]
    assert alloc_lab.tick(con, tmp_path, None, NOW).get("adopted_index_only") is None       # once: the next tick finds the index already owned
    s = _state(con)
    sh = s["sleeve_target"]
    assert (sh["core"], sh["longterm"], sh["gold"], sh["international"]) == (0.60, 0.40, 0.0, 0.10) and sh["index"] == pytest.approx(0.50)


# --- B3: probation slices ------------------------------------------------------------------------------------------------------------------------

D0 = date(2026, 9, 1)


def _challenger(con, tmp_path, pid):
    service.add_variant(con, tmp_path, NOW, pid, MOMENTUM, "lean toward the strongest 12-1 momentum, sized by risk")
    con.execute("UPDATE core_policies_s80 SET status='challenger' WHERE policy_id=?", [pid])


def _days(con, pid, start, n, ret_v, ret_s):
    """`n` scored shadow sessions of `pid` and the champion's stand-in (baseline_lab) from `start` on."""
    service.ensure_baseline(con, NOW)
    for i in range(n):
        for p, r in ((pid, ret_v), (shadow.standin(con), ret_s)):
            con.execute("INSERT OR REPLACE INTO core_shadow_s80 VALUES (?,?,?,?,?)", [start + timedelta(days=i), p, "{}", r, NOW])


def test_a_slice_starts_at_5_percent_grows_to_10_and_20_while_not_worse_and_is_written_with_its_reason(con, tmp_path):
    _challenger(con, tmp_path, "var_a")
    g = probation.grant(con, NOW, D0, "var_a", {"index_rule": {"via": "A", "lag": 0.01, "fall": -0.3, "index_fall": -0.4}, "final": {"cagr": 0.12}})
    assert g["granted"] and g["share"] == 0.05 and "5% of the book at once" in g["why"]
    assert probation.slices(con, D0) == [{"policy_id": "var_a", "share": 0.05, "since": D0}]
    _days(con, "var_a", D0 + timedelta(days=1), 12, 0.0010, 0.0009)
    assert probation.review(con, NOW, D0 + timedelta(days=12)) == []                          # 12 sessions: not yet 20, but not worse: it stays
    _days(con, "var_a", D0 + timedelta(days=1), 22, 0.0010, 0.0009)
    ch = probation.review(con, NOW, D0 + timedelta(days=22))
    assert ch and ch[0]["change"] == "grow" and ch[0]["share"] == 0.10 and "not worse" in ch[0]["why"]
    assert probation.review(con, NOW, D0 + timedelta(days=22)) == []                          # idempotent for a day
    _days(con, "var_a", D0 + timedelta(days=1), 41, 0.0010, 0.0009)
    ch = probation.review(con, NOW, D0 + timedelta(days=41))
    assert ch and ch[0]["share"] == 0.20
    assert probation.slices(con, D0 + timedelta(days=41)) == [{"policy_id": "var_a", "share": 0.20, "since": D0}]
    assert probation.review(con, NOW, D0 + timedelta(days=42)) == []                          # 20% is the most
    kinds = [h["kind"] for h in probation.history(con, "var_a")]
    assert kinds == ["grant", "grow", "grow"] and all(h["reason"] for h in probation.history(con, "var_a"))
    assert probation.slices(con, D0 + timedelta(days=5)) == [{"policy_id": "var_a", "share": 0.05, "since": D0}]       # as of an earlier day the slice was smaller


def test_a_slice_that_is_worse_than_the_champion_is_withdrawn_automatically(con, tmp_path):
    _challenger(con, tmp_path, "var_b")
    probation.grant(con, NOW, D0, "var_b", {})
    _days(con, "var_b", D0 + timedelta(days=1), 14, 0.0000, 0.0010)                           # 14 sessions, 1.4% behind the champion's stand-in
    ch = probation.review(con, NOW, D0 + timedelta(days=14))
    assert ch and ch[0]["change"] == "withdraw" and "withdrawn" in ch[0]["why"] and "behind" in ch[0]["why"]
    assert probation.slices(con, D0 + timedelta(days=14)) == []
    assert probation.explain(con, D0 + timedelta(days=14), "var_b")["share"] == 0.0 and "withdrawn" in probation.explain(con, D0 + timedelta(days=14), "var_b")["why"]
    assert probation.grant(con, NOW, D0 + timedelta(days=15), "var_b", {})["granted"] is True       # (a new grant is code's call: promote_ready never repeats one)


def test_the_slices_share_the_satellite_room_and_the_loop_can_blend_them(con, tmp_path):
    for p in ("v1x", "v2x", "v3x", "v4x", "v5x"):
        _challenger(con, tmp_path, p)
    got = [probation.grant(con, NOW, D0, p, {})["granted"] for p in ("v1x", "v2x", "v3x", "v4x", "v5x")]
    assert got == [True, True, True, True, False]                                              # four 5% slices fill the 20% room
    assert probation.total_share(con, D0) == pytest.approx(0.20)
    now = probation.slices(con, D0)
    w = probation.blend({"A": 0.6, "B": 0.3}, {"v1x": {"C": 0.5, "D": 0.5}, "v2x": {"C": 1.0}}, now)
    assert w["A"] == pytest.approx(0.6 * 0.90) and w["C"] == pytest.approx(0.5 * 0.05 + 1.0 * 0.05) and sum(w.values()) == pytest.approx(0.6 * 0.9 + 0.3 * 0.9 + 0.10)
    assert probation.explain(con, D0, "v5x")["share"] == 0.0 and "no slice yet" in probation.explain(con, D0, "v5x")["why"]


def test_the_screen_shows_each_challengers_slice_and_why(con, tmp_path):
    from pflab.core import screens
    _challenger(con, tmp_path, "var_c")
    probation.grant(con, NOW, NOW.date(), "var_c", {"index_rule": {"via": "B", "lag": 0.03, "fall": -0.2, "index_fall": -0.4}})
    v = screens.policies(con, NOW.date())
    c = [x for x in v["challengers"] if x["policy"] == "var_c"][0]
    assert c["slice"] == 0.05 and "probation slice of 5%" in c["slice_why"]
    assert v["slices"] == [{"policy_id": "var_c", "share": 0.05, "since": str(NOW.date())}] and v["index_rule"]["b_max_lag"] == 0.04


# --- A55: the throttle switch --------------------------------------------------------------------------------------------------------------------

def _wasted(con):
    con.execute("INSERT INTO core_sessions_s80 (session_id, started_at, finished_at, reason, status, cost_inr) VALUES (9, ?, ?, 'x', 'wasted', 10)", [NOW - timedelta(days=1), NOW - timedelta(days=1)])


def test_the_budget_halving_rules_are_recorded_but_not_applied_before_the_throttle_date(con):
    s = core.settings()["strategist"]
    assert s["throttle_after"] == "2026-12-09" and s["session_rupees"] == 300.0
    _wasted(con)
    con.execute("INSERT INTO core_sessions_s80 (session_id, started_at, finished_at, reason, status, cost_inr) VALUES (2, ?, ?, 'old', 'done', 10)", [NOW - timedelta(days=90), NOW - timedelta(days=90)])
    before = strategist.session_budget(con, datetime(2026, 12, 8, 23, 0))
    assert before["rupees"] == 300.0 and before["throttle_applied"] is False
    assert any("recorded, NOT applied" in w for w in before["why"]) and len(before["why"]) == 2          # both rules are recorded (the wasted session, the weeks without a win)
    after = strategist.session_budget(con, datetime(2026, 12, 9, 0, 0))
    assert after["throttle_applied"] is True and after["rupees"] == 75.0                                    # 300 halved twice
    assert not any("NOT applied" in w for w in after["why"])
    assert core.throttle_active(date(2026, 12, 9)) and not core.throttle_active(date(2026, 12, 8))


def test_the_throttle_date_is_a_config_switch(con, monkeypatch):
    real = core.settings
    monkeypatch.setattr(core, "settings", lambda: {**real(), "strategist": {**real()["strategist"], "throttle_after": "2026-01-01"}})
    _wasted(con)
    assert strategist.session_budget(con, NOW)["rupees"] == 150.0


def test_the_migrations_create_the_s81_tables(con):
    names = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    assert {"sleeves_s81", "probation_s81", "allocation_sleeves_s81", "alloc_verdicts_s81"} <= names
    versions = {r[0] for r in con.execute("SELECT version FROM schema_migrations").fetchall()}
    assert {108, 109, 110, 111, 112} <= versions


# --- the replay's modelled ETFs and the once-only final check -------------------------------------------------------------------------------------

def test_a_core_etf_without_history_is_modelled_as_its_index_less_a_stated_yearly_cost(tmp_path):
    from pflab.lab import runner
    (tmp_path / "indices").mkdir()
    (tmp_path / "global").mkdir()
    idx = pd.bdate_range("2010-01-04", periods=2600)
    lvl = pd.Series(1000.0 * 1.0004 ** pd.Series(range(len(idx))).to_numpy(), index=idx)
    pd.DataFrame({"date": idx, "close": lvl.to_numpy()}).to_parquet(tmp_path / "indices" / "NIFTY500_TRI.parquet")
    for k, mult in (("US_NASDAQ", 1.0003), ("FX_USDINR", 1.0001)):
        pd.DataFrame({"date": idx, "adj_close": 100.0 * mult ** pd.Series(range(len(idx))).to_numpy()}).to_parquet(tmp_path / "global" / f"{k}.parquet")
    out = runner.core_synth_series(tmp_path, idx)
    assert set(out) == {"ETF:MONIFTY500", "ETF:MON100"}
    s, why = out["ETF:MONIFTY500"]
    years = (idx[-1] - idx[0]).days / 365.25
    assert s.iloc[-1] / s.iloc[0] == pytest.approx((lvl.iloc[-1] / lvl.iloc[0]) * (1 - 0.0020) ** years, rel=1e-6)      # the index total-return less 0.20% a year
    assert "estimate" in why and "no price history" in why and runner.CORE_SYNTH["ETF:MON100"]["cost"] == 0.0060
    assert out["ETF:MON100"][0].iloc[-1] > 0


def test_the_final_check_setting_of_no_monte_carlo_no_longer_raises():
    """The once-only 2018-2021 check runs `evaluate` with n_shuffles=0 and n_mc=0; the Monte Carlo used to raise on empty arrays, so the check could never run for real."""
    data = make_data()

    def hold(state, f, s, sl, params=None):
        return {"ETF:NIFTYBEES": 0.5}
    res = engine.evaluate(hold, [{}], data, "2011-01-03", "2014-12-31", None, n_shuffles=0, n_mc=0)
    assert res["runs"][0]["mc"] == {} and res["runs"][0]["score"]["cagr_liq"] is not None
    assert engine.monte_carlo(data["px"]["ETF:NIFTYBEES"], 0) == {}
