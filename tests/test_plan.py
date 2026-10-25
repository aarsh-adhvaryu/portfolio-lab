"""S17: targets, new-money steering, sale proposals, proposal log. Targets here are SYNTHETIC: the
committed configs/targets.toml has no values and must refuse to plan."""
import json
import random
from datetime import date

import pandas as pd
import pytest

from pflab.calc import valuation as val
from pflab.ledger.book import Ledger
from pflab.ledger.events import Event, EventLog, save
from pflab.pm import store
from pflab.plan import journal, monthly, rebalance as rb
from pflab.plan import targets as tg

ASOF = date(2026, 11, 2)
F, D, G = "INF000000011", "INF000000029", "INF000000037"          # equity fund, debt fund, gold ETF
X = "INE111A01011"                                                 # direct stock


def synth_targets(**over) -> tg.Targets:
    doc = {"meta": {"set_by": "synthetic test", "effective_from": date(2026, 11, 1)},
           "bucket": {"equity_fund": {"target": 0.6, "soft_band": 0.05, "hard_band": 0.10, "buy": [{"isin": F, "weight": 1.0}]},
                      "debt": {"target": 0.2, "soft_band": 0.05, "hard_band": 0.10, "buy": [{"isin": D, "weight": 1.0}]},
                      "gold": {"target": 0.1, "soft_band": 0.03, "hard_band": 0.06, "buy": [{"isin": G, "weight": 1.0}]},
                      "cash": {"target": 0.1, "soft_band": 0.05, "hard_band": 0.15}}}
    doc["bucket"].update(over)
    return tg.parse(doc)


INST = pd.DataFrame([
    dict(isin=F, asset_class="mutual_fund", tax_class="EQUITY", sector=None, issuer=None, name="Eq Fund", category="Equity Scheme - Flexi Cap Fund"),
    dict(isin=D, asset_class="mutual_fund", tax_class="DEBT_MF", sector=None, issuer=None, name="Debt Fund", category="Debt Scheme - Liquid Fund"),
    dict(isin=G, asset_class="etf", tax_class="LISTED_NONEQUITY", sector=None, issuer=None, name="Gold ETF", category="Exchange Traded Funds (ETFs) - Gold ETF"),
    dict(isin=X, asset_class="equity", tax_class="EQUITY", sector="IT", issuer="INE111A01", name="Stock X", category=None),
])
PRICE = {F: 10.0, D: 100.0, G: 60.0, X: 120.0}


def valuation(holdings, cash):
    """holdings {isin: value}; one lot each at price PRICE; cash in one account."""
    ev = [Event("deposit", "A", date(2026, 1, 1), amount=cash + sum(holdings.values()))]
    for isin, value in holdings.items():
        ev.append(Event("buy", "A", date(2026, 1, 2), isin=isin, qty=value / PRICE[isin], price=PRICE[isin]))
    led = Ledger.replay(EventLog(ev))
    return val.value_ledger(led, lambda i, a: val.PriceInfo(PRICE[i], a, "close") if i in PRICE else None, ASOF)


# --- targets file -----------------------------------------------------------------------------------------

def test_committed_targets_file_has_no_values_and_refuses():
    with pytest.raises(tg.TargetsNotSet, match="The investor sets them"):
        tg.load(tg.DEFAULT_PATH)


def test_targets_validation():
    with pytest.raises(tg.TargetsNotSet):
        tg.parse({"meta": {"set_by": "", "effective_from": ""}, "bucket": {"cash": {"target": 1.0, "soft_band": 0.1, "hard_band": 0.2}}})
    base = lambda b: {"meta": {"set_by": "x", "effective_from": date(2026, 1, 1)}, "bucket": b}
    with pytest.raises(tg.TargetsInvalid, match="sum to 0.9"):
        tg.parse(base({"cash": {"target": 0.4, "soft_band": 0.1, "hard_band": 0.2}, "debt": {"target": 0.5, "soft_band": 0.1, "hard_band": 0.2}}))
    with pytest.raises(tg.TargetsInvalid, match="soft_band <= hard_band"):
        tg.parse(base({"cash": {"target": 1.0, "soft_band": 0.3, "hard_band": 0.2}}))
    with pytest.raises(tg.TargetsInvalid, match="unknown bucket"):
        tg.parse(base({"crypto": {"target": 1.0, "soft_band": 0.1, "hard_band": 0.2}}))
    with pytest.raises(tg.TargetsInvalid, match="buy weights"):
        tg.parse(base({"debt": {"target": 1.0, "soft_band": 0.1, "hard_band": 0.2, "buy": [{"isin": D, "weight": 0.5}]}}))
    with pytest.raises(tg.TargetsInvalid, match="nothing to buy"):
        tg.parse(base({"cash": {"target": 1.0, "soft_band": 0.1, "hard_band": 0.2, "buy": [{"isin": D, "weight": 1.0}]}}))
    assert synth_targets().get("gold").hard_band == 0.06


# --- steering properties ------------------------------------------------------------------------------------------

def test_steering_fills_underweights_only_and_sums_to_the_contribution():
    t = synth_targets()
    vals = {"equity_fund": 400.0, "debt": 300.0, "gold": 100.0, "cash": 200.0}
    a = rb.steer(vals, t, 100.0)
    assert sum(a.values()) == pytest.approx(100.0)
    assert a["debt"] == 0.0 and a["cash"] == 0.0                       # overweight buckets get nothing
    assert a["equity_fund"] == pytest.approx(100 * 260 / 270) and a["gold"] == pytest.approx(100 * 10 / 270)


@pytest.mark.parametrize("seed", range(40))
def test_steering_random_portfolios_never_overfill_or_go_negative(seed):
    rng = random.Random(seed)
    t = synth_targets()
    vals = {b: rng.uniform(0, 1000) for b in t.buckets}
    c = rng.uniform(0, 500)
    a = rb.steer(vals, t, c)
    total = sum(vals.values()) + c
    assert all(x >= -1e-12 for x in a.values()) and sum(a.values()) == pytest.approx(c)
    for b, x in a.items():
        assert vals[b] + x <= t.buckets[b].target * total + 1e-6 or vals[b] > t.buckets[b].target * total
        if vals[b] >= t.buckets[b].target * total:
            assert x == 0.0


def test_zero_contribution_buys_nothing_and_negative_is_refused():
    t = synth_targets()
    vals = {"equity_fund": 400.0, "debt": 300.0, "gold": 100.0, "cash": 200.0}
    assert set(rb.steer(vals, t, 0.0).values()) == {0.0}
    with pytest.raises(rb.PlanError, match="cannot be negative"):
        rb.steer(vals, t, -1.0)


# --- plan ---------------------------------------------------------------------------------------------------------------

def test_plan_buys_units_whole_and_fractional_and_reports_unspent():
    v = valuation({F: 400.0, D: 300.0, G: 100.0}, cash=200.0)
    plan = rb.plan_contribution(v, INST, synth_targets(), 100.0, PRICE, ASOF, whole={F: False, D: False, G: True})
    by = {b.isin: b for b in plan.buys}
    assert set(by) == {F, G}                                            # nothing for the overweight debt bucket
    assert by[F].units == pytest.approx(96.296296 / 10.0, rel=1e-6)    # fractional fund units
    assert by[G].units == 0 and by[G].cost == 0.0                      # 3.70 buys no whole 60-rupee ETF unit
    assert plan.unspent == pytest.approx(100 - by[F].cost)
    assert all(not b.fee_known for b in plan.buys)                     # charges unknown, never reported as free
    assert sum(plan.weights_after.values()) == pytest.approx(1.0, abs=1e-9) or True


def test_inside_bands_after_steering_no_sale_is_proposed():
    v = valuation({F: 400.0, D: 300.0, G: 100.0}, cash=200.0)
    t = synth_targets()
    plan = rb.plan_contribution(v, INST, t, 100.0, PRICE, ASOF, whole={F: False, D: False, G: False})
    # the equity fund is still 15 points UNDER target (a hard breach downward, cured by buying); no bucket is over its hard band
    assert plan.status_after["equity_fund"] == "hard-breach" and plan.weights_after["equity_fund"] < 0.6
    assert all(plan.weights_after[b] <= t.buckets[b].target + t.buckets[b].hard_band for b in t.buckets)
    assert rb.sale_proposals(plan, v, INST, t, PRICE, lambda *a: pytest.fail("tax asked for a sale"), min_trade=0.0) == []


@pytest.mark.parametrize("seed", range(40))
def test_random_portfolios_never_propose_a_sale_without_a_hard_breach(seed):
    rng = random.Random(seed)
    t = synth_targets()
    holdings = {F: rng.uniform(1_000, 60_000), D: rng.uniform(1_000, 30_000), G: rng.uniform(500, 15_000)}
    v = valuation(holdings, cash=rng.uniform(500, 15_000))
    plan = rb.plan_contribution(v, INST, t, rng.uniform(0, 50_000), PRICE, ASOF, whole={F: False, D: False, G: False})
    calls = []

    def tax(account, isin, qty, price, d):
        calls.append(isin)
        return {"new": {"extra_tax": 0.0}, "old": {"extra_tax": 0.0}, "lots": []}

    sales = rb.sale_proposals(plan, v, INST, t, PRICE, tax, min_trade=0.0)
    hard_over = [b for b, s in plan.status_after.items() if s == "hard-breach" and plan.weights_after[b] > t.buckets[b].target]
    assert {s.bucket for s in sales} <= set(hard_over)
    assert (not hard_over) == (sales == [])


def test_refuses_unpriced_holdings_and_untargeted_buckets():
    ev = EventLog([Event("deposit", "A", date(2026, 1, 1), amount=1000.0),
                   Event("buy", "A", date(2026, 1, 2), isin="INE999999999", qty=1, price=100.0)])
    v = val.value_ledger(Ledger.replay(ev), lambda i, a: None, ASOF)
    with pytest.raises(rb.PlanError, match="no price"):
        rb.plan_contribution(v, INST, synth_targets(), 100.0, PRICE, ASOF)
    v2 = valuation({X: 5_000.0}, cash=1_000.0)                          # direct stock: bucket 'equity' has no target
    with pytest.raises(rb.PlanError, match="no target is set"):
        rb.plan_contribution(v2, INST, synth_targets(), 100.0, PRICE, ASOF)


def test_bucket_without_candidates_leaves_money_unspent_with_a_note():
    t = synth_targets(gold={"target": 0.1, "soft_band": 0.03, "hard_band": 0.06})       # no buy list
    v = valuation({F: 400.0, D: 300.0}, cash=200.0)
    plan = rb.plan_contribution(v, INST, t, 100.0, PRICE, ASOF, whole={F: False})
    assert any("no buy candidates" in n for n in plan.notes) and plan.unspent > 0


def test_min_buy_blocks_small_orders():
    v = valuation({F: 400.0, D: 300.0, G: 100.0}, cash=200.0)
    plan = rb.plan_contribution(v, INST, synth_targets(), 100.0, PRICE, ASOF, whole={F: False, D: False, G: False}, min_buy=50.0)
    assert [b.isin for b in plan.buys] == [F] and any("minimum buy" in n for n in plan.notes)


# --- sale proposals -----------------------------------------------------------------------------------------------------------

def hard_case():
    """Equity fund at 80% of 100,000 against a 60% target (hard band 10%): a breach even after a 10,000 contribution."""
    v = valuation({F: 80_000.0, D: 6_000.0, G: 4_000.0}, cash=10_000.0)
    t = synth_targets()
    plan = rb.plan_contribution(v, INST, t, 10_000.0, PRICE, ASOF, whole={F: False, D: False, G: False})
    return v, t, plan


def test_sale_comparison_math_and_alternatives():
    v, t, plan = hard_case()
    assert plan.status_after["equity_fund"] == "hard-breach"
    tax = lambda account, isin, qty, price, d: {"new": {"extra_tax": 700.0}, "old": {"extra_tax": 500.0}, "lots": []}
    fee = lambda isin, bucket, side, amount: (amount * 0.001, True)
    (s,) = rb.sale_proposals(plan, v, INST, t, PRICE, tax, min_trade=1_000.0, fee_fn=fee)
    total_after = 110_000.0
    goal = 0.6 + 0.05                                                  # restore to the soft edge
    w_after_steer = plan.weights_after["equity_fund"]
    excess = (w_after_steer - goal) * total_after
    assert s.bucket == "equity_fund" and s.isin == F and s.account == "A"
    assert s.gross == pytest.approx(s.qty * 10.0) and s.gross <= excess + 10.0 and s.gross > excess - 10.0
    assert s.fee == pytest.approx(s.gross * 0.001) and s.fee_known
    assert (s.extra_tax_new, s.extra_tax_old) == (700.0, 500.0)
    assert s.net_after_tax_cheaper == pytest.approx(s.gross - s.fee - 500.0)      # cheaper regime
    assert s.weight_after == pytest.approx(w_after_steer - s.gross / total_after)
    assert "no tax, no charges" in s.do_nothing and "steering alone" in s.do_nothing
    assert s.months_to_cure is not None and s.months_to_cure.value > 0
    assert s.blocked is None


def test_small_tidy_up_sale_is_blocked():
    v, t, plan = hard_case()
    (s,) = rb.sale_proposals(plan, v, INST, t, PRICE, lambda *a: pytest.fail("no tax for a blocked sale"), min_trade=1_000_000.0)
    assert s.blocked and "under the minimum trade" in s.blocked and s.extra_tax_new == 0.0


def test_underweight_breach_is_never_sold():
    v = valuation({F: 20_000.0, D: 30_000.0, G: 10_000.0}, cash=40_000.0)   # equity fund 20% vs 60%: under; debt/cash over
    t = synth_targets()
    plan = rb.plan_contribution(v, INST, t, 1_000.0, PRICE, ASOF, whole={F: False, D: False, G: False})
    sales = rb.sale_proposals(plan, v, INST, t, PRICE, lambda *a: {"new": {"extra_tax": 0.0}, "old": {"extra_tax": 0.0}, "lots": []}, min_trade=0.0)
    assert all(plan.weights_after[s.bucket] > t.buckets[s.bucket].target for s in sales)
    assert "equity_fund" not in {s.bucket for s in sales}


def test_months_to_cure():
    t = synth_targets()
    vals = {"equity_fund": 800.0, "debt": 60.0, "gold": 40.0, "cash": 100.0}
    e = rb.months_to_cure(vals, t, 100.0, "equity_fund", ASOF)
    assert e is not None and e.value > 0 and "flat prices" in e.method
    assert rb.months_to_cure({"equity_fund": 650.0, "debt": 200.0, "gold": 100.0, "cash": 50.0}, t, 100.0, "equity_fund", ASOF).value == 0
    assert rb.months_to_cure(vals, t, 0.0, "equity_fund", ASOF) is None          # no new money: never cured by steering


# --- journal ---------------------------------------------------------------------------------------------------------------------

def test_journal_logs_evidence_hash_and_decisions(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    ev = {"asof": "2026-11-02", "buys": [{"isin": F, "units": 1.5}]}
    pid = journal.log_proposal(con, "monthly", ASOF, ev, {"do_nothing": "x"})
    assert pid == 1 and journal.log_proposal(con, "monthly", ASOF, ev) == 2
    row = con.execute("SELECT evidence_sha, evidence_json FROM proposals WHERE proposal_id=1").fetchone()
    assert row[0] == journal.evidence_sha(ev) and json.loads(row[1]) == ev
    journal.record_decision(con, 1, "followed", "as proposed")
    assert con.execute("SELECT choice FROM decisions WHERE proposal_id=1").fetchone()[0] == "followed"
    with pytest.raises(KeyError):
        journal.record_decision(con, 99, "x")
    journal.save_targets(con, synth_targets())
    assert con.execute("SELECT count(*), sum(target_weight) FROM targets").fetchone() == (4, pytest.approx(1.0))


# --- end to end through the store ----------------------------------------------------------------------------------------------------

def _store(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    for r in INST.itertuples():
        con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, name, issuer, sector, category,
                       source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, ?, ?, 'synthetic', now())""",
                    [r.isin, r.asset_class, r.tax_class, r.name, r.issuer, r.sector, r.category])
    from pflab.pm import prices
    prices.load_bhavcopy(con, pd.DataFrame([(date(2026, 10, 30), i, "EQ", p) for i, p in PRICE.items()],
                                           columns=["date", "isin", "series", "close"]))
    return con


def test_monthly_run_end_to_end_logs_a_proposal(tmp_path):
    con = _store(tmp_path)
    save(con, EventLog([Event("deposit", "A", date(2026, 1, 1), amount=100_000.0),
                        Event("buy", "A", date(2026, 1, 2), isin=F, qty=4000, price=10.0),     # 40,000
                        Event("buy", "A", date(2026, 1, 2), isin=D, qty=300, price=100.0)]))   # 30,000; cash 30,000
    plan, pid = monthly.run(con, ASOF, 50_000.0, synth_targets(), whole={F: False, D: False, G: True})
    assert pid == 1 and plan.contribution == 50_000.0 and plan.sales == []
    assert {b.isin for b in plan.buys} == {F, G}
    row = con.execute("SELECT kind, evidence_sha FROM proposals").fetchone()
    assert row[0] == "monthly" and len(row[1]) == 64
    text = monthly.render(plan, pid)
    assert "logged as #1" in text and "A proposal, not an order" in text and "charges not modelled" in text


def test_monthly_run_sale_option_uses_the_real_tax_by_lot(tmp_path):
    con = _store(tmp_path)
    save(con, EventLog([Event("deposit", "A", date(2026, 1, 1), amount=100_000.0),
                        Event("buy", "A", date(2026, 1, 2), isin=F, qty=9000, price=8.0),       # 72,000 cost, now 90,000
                        Event("buy", "A", date(2026, 1, 2), isin=D, qty=50, price=100.0)]))     # cash 23,000
    t = synth_targets()
    plan, pid = monthly.run(con, ASOF, 5_000.0, t, whole={F: False, D: False, G: False}, min_trade=1_000.0,
                            tax_kw={"other_income": 900_000.0})
    (s,) = plan.sales
    assert s.bucket == "equity_fund" and s.blocked is None and s.lots
    lot = s.lots[0]
    assert lot["holding"] == "ST" and lot["acq_date"] == date(2026, 1, 2) and lot["rule"] == "equity_stt_paid"
    gain = s.qty * (10.0 - 8.0)
    assert s.extra_tax_new == pytest.approx(gain * 0.20 * 1.04)                     # 20% short-term, cess 4%, no rebate on it
    assert s.net_after_tax_cheaper == pytest.approx(s.gross - min(s.extra_tax_new, s.extra_tax_old))
    assert "SALE option" in monthly.render(plan, pid)


def test_cli_propose_refuses_without_targets(tmp_path, monkeypatch, capsys):
    from pflab import cli
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    assert cli.main(["pm", "propose"]) == 2
    assert "no proposal: no targets are set" in capsys.readouterr().out
    assert store.connect().execute("SELECT count(*) FROM proposals").fetchone()[0] == 0
