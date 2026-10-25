"""S15: exposures, risk statistics, report/CLI. Synthetic portfolios with hand-checkable numbers."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from pflab.calc import valuation as val
from pflab.ledger.book import Ledger
from pflab.ledger.events import Event, EventLog, save
from pflab.pm import prices, store
from pflab.risk import exposure as ex
from pflab.risk import report, stats

A = "ACC"


def d(m, day=1, y=2026):
    return date(y, m, day)


# --- buckets ---------------------------------------------------------------------------------

@pytest.mark.parametrize("args,expect", [
    (("equity", "EQUITY"), "equity"),
    (("etf", "EQUITY", "Exchange Traded Funds (ETFs) - Equity ETF"), "equity_fund"),
    (("mutual_fund", "EQUITY"), "equity_fund"),
    (("etf", "LISTED_NONEQUITY", "Exchange Traded Funds (ETFs) - Gold ETF"), "gold"),
    (("mutual_fund", "OTHER_MF", None, "XYZ Gold Fund of Fund"), "gold"),
    (("sgb", "SGB"), "gold"),
    (("gold_physical", "PHYSICAL_GOLD"), "gold"),
    (("bond", "LISTED_NONEQUITY"), "debt"),
    (("mutual_fund", "DEBT_MF"), "debt"),
    (("reit", "BUSINESS_TRUST"), "reit_invit"),
    (("etf", "REVIEW"), "unclassified"),
    ((None, None), "unclassified"),
])
def test_bucket(args, expect):
    assert ex.bucket(*args) == expect


# --- exposures --------------------------------------------------------------------------------------

INST = pd.DataFrame([
    dict(isin="INE000000011", asset_class="equity", tax_class="EQUITY", sector="Financial Services", issuer="INE000000", name="Bank A", category=None),
    dict(isin="INE000000029", asset_class="equity", tax_class="EQUITY", sector="IT", issuer="INE000001", name="Tech B", category=None),
    dict(isin="INE000000031", asset_class="equity", tax_class="EQUITY", sector=None, issuer="INE000002", name="Misc C", category=None),
    dict(isin="INF000000011", asset_class="mutual_fund", tax_class="EQUITY", sector=None, issuer=None, name="Flexi Fund", category="Equity Scheme - Flexi Cap Fund"),
    dict(isin="INF000000029", asset_class="etf", tax_class="LISTED_NONEQUITY", sector=None, issuer=None, name="Gold BeES", category="Exchange Traded Funds (ETFs) - Gold ETF"),
])
PRICES = {"INE000000011": 100.0, "INE000000029": 50.0, "INE000000031": 20.0, "INF000000011": 10.0, "INF000000029": 60.0}


def _valuation(extra=()):
    log = EventLog([Event("deposit", A, d(1), amount=100_000.0),
                    Event("buy", A, d(2), isin="INE000000011", qty=100, price=100.0),    # 10,000
                    Event("buy", A, d(2), isin="INE000000029", qty=100, price=50.0),     # 5,000
                    Event("buy", A, d(2), isin="INE000000031", qty=100, price=20.0),     # 2,000
                    Event("buy", A, d(2), isin="INF000000011", qty=500, price=10.0),     # 5,000
                    Event("buy", A, d(2), isin="INF000000029", qty=50, price=60.0),      # 3,000
                    *extra])
    led = Ledger.replay(log)
    return val.value_ledger(led, lambda i, a: val.PriceInfo(PRICES[i], a, "close") if i in PRICES else None, d(3))


def test_exposure_weights_sum_to_one_and_cash_is_a_bucket():
    v = _valuation()
    e = ex.exposures(v, INST)
    b = e["bucket"].set_index("bucket")["weight"]
    assert b.sum() == pytest.approx(1.0)
    assert b["cash"] == pytest.approx(75_000 / 100_000) and b["equity"] == pytest.approx(0.17)
    assert b["equity_fund"] == pytest.approx(0.05) and b["gold"] == pytest.approx(0.03)
    s = e["sector"].set_index("sector")["weight"]
    assert s["Financial Services"] == pytest.approx(0.10) and s["IT"] == pytest.approx(0.05)
    assert s["Unclassified"] == pytest.approx(0.02)                      # stock with no sector label
    assert s["fund:Equity Scheme - Flexi Cap Fund"] == pytest.approx(0.05)
    st = e["stock"].set_index("isin")["weight"]
    assert st["INE000000011"] == pytest.approx(0.10)
    iss = e["issuer"].set_index("issuer")["weight"]
    assert iss["INE000000"] == pytest.approx(0.10) and "INE000003" not in iss.index


def test_lookthrough_spreads_a_fund_and_keeps_the_remainder():
    v = _valuation()
    lt = pd.DataFrame([dict(fund_isin="INF000000011", isin="INE000000011", sector="Financial Services", issuer="INE000000", weight=0.30),
                       dict(fund_isin="INF000000011", isin="INE000000029", sector="IT", issuer="INE000001", weight=0.50)])
    e = ex.exposures(v, INST, lt)
    s = e["sector"].set_index("sector")["weight"]
    assert s["Financial Services"] == pytest.approx(0.10 + 0.05 * 0.30)
    assert s["IT"] == pytest.approx(0.05 + 0.05 * 0.50)
    assert s["fund:Equity Scheme - Flexi Cap Fund (unlooked remainder)"] == pytest.approx(0.05 * 0.20)
    assert e["stock"].set_index("isin")["weight"]["INE000000011"] == pytest.approx(0.10 + 0.015)


def test_unpriced_excluded_from_weights_and_reported():
    v = _valuation(extra=[Event("buy", A, d(2), isin="INE999999999", qty=1, price=10.0)])
    e = ex.exposures(v, INST)
    assert list(e["unpriced"]["isin"]) == ["INE999999999"]
    assert "INE999999999" not in set(e["stock"]["isin"])


# --- statistics -------------------------------------------------------------------------------------

def test_vol_drawdown_known_values():
    idx = pd.date_range("2026-01-01", periods=5, freq="B")
    nav = pd.Series([100.0, 120.0, 90.0, 110.0, 99.0], index=idx)
    assert stats.max_drawdown(nav) == pytest.approx(0.25)
    assert stats.drawdown_series(nav).iloc[2] == pytest.approx(0.25)
    r = pd.Series([0.01, -0.01] * 15)
    assert stats.volatility(r) == pytest.approx(float(np.std(r, ddof=1) * np.sqrt(252)))
    assert stats.volatility(pd.Series([0.01] * 30)) == pytest.approx(0.0, abs=1e-12)
    assert np.isnan(stats.volatility(pd.Series([0.01, 0.02])))           # too few observations


def test_beta_and_correlation_known_cases():
    rng = np.random.default_rng(1)
    idx = pd.date_range("2026-01-01", periods=60, freq="B")
    b = pd.Series(rng.normal(0, 0.01, 60), index=idx)
    assert stats.beta(2 * b, b) == pytest.approx(2.0)
    assert stats.beta(-0.5 * b + 0.001, b) == pytest.approx(-0.5)
    assert np.isnan(stats.beta(b.iloc[:5], b.iloc[:5]))
    assert np.isnan(stats.beta(b, b * 0))
    corr = stats.correlation(pd.DataFrame({"a": b, "b": 3 * b, "c": -b}))
    assert corr.loc["a", "b"] == pytest.approx(1.0) and corr.loc["a", "c"] == pytest.approx(-1.0)


def test_beta_aligns_on_shared_dates_only():
    idx = pd.date_range("2026-01-01", periods=40, freq="B")
    rng = np.random.default_rng(2)
    b = pd.Series(rng.normal(0, 0.01, 40), index=idx)
    p = (1.5 * b).iloc[10:]                                              # starts later
    assert stats.beta(p, b) == pytest.approx(1.5)


def test_concentration_known():
    c = stats.concentration(pd.Series([0.5, 0.5]))
    assert c["hhi"] == pytest.approx(0.5) and c["effective_n"] == pytest.approx(2.0) and c["top1"] == 0.5
    c = stats.concentration(pd.Series([0.4, 0.3, 0.2, 0.1]))
    assert c["hhi"] == pytest.approx(0.16 + 0.09 + 0.04 + 0.01) and c["top3"] == pytest.approx(0.9)
    c = stats.concentration(pd.Series([2.0, 2.0, 4.0, 0.0]))            # renormalised, zeros dropped
    assert c["n"] == 3 and c["top1"] == pytest.approx(0.5)
    assert np.isnan(stats.concentration(pd.Series([], dtype=float))["hhi"])


def test_summary_with_benchmark():
    idx = pd.date_range("2026-01-01", periods=80, freq="B")
    rng = np.random.default_rng(3)
    bench = pd.Series(1000 * np.cumprod(1 + rng.normal(0.0005, 0.01, 80)), index=idx)
    nav = pd.Series(100 * np.cumprod(1 + 1.2 * bench.pct_change().fillna(0)), index=idx)
    s = stats.summary(nav, bench)
    assert s["beta"] == pytest.approx(1.2, abs=1e-6) and s["obs"] == 79 and s["vol_annual"] > 0


# --- report and CLI -----------------------------------------------------------------------------------

def _store_with_portfolio(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    con.register("_i", INST.assign(valid_from=None, valid_to=None))
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, issuer,
                   sector, category, source, built_at)
                   SELECT isin, 'isin', asset_class, tax_class, TRUE, NULL, name, issuer, sector, category,
                   'synthetic', now() FROM _i""")
    days = list(pd.bdate_range("2026-01-02", "2026-03-31").date)
    rows = []
    for i, day in enumerate(days):
        for isin, p in PRICES.items():
            rows.append((day, isin, "EQ", p * (1 + 0.002 * ((i % 7) - 3))))
    prices.load_bhavcopy(con, pd.DataFrame(rows, columns=["date", "isin", "series", "close"]))
    log = EventLog([Event("deposit", A, days[0], amount=100_000.0),
                    Event("buy", A, days[1], isin="INE000000011", qty=100, price=100.0),
                    Event("buy", A, days[1], isin="INF000000029", qty=50, price=60.0),
                    Event("deposit", A, days[20], amount=10_000.0),
                    Event("buy", A, days[21], isin="INE000000029", qty=100, price=50.0)])
    save(con, log)
    return con, days


def test_report_build_and_render(tmp_path):
    con, days = _store_with_portfolio(tmp_path)
    rep = report.build(con, days[-1], bench_loader=lambda: None)
    assert rep["total"] == pytest.approx(rep["invested"] + rep["cash"])
    assert rep["exposure"]["bucket"]["weight"].sum() == pytest.approx(1.0)
    assert rep["nav_stats"]["obs"] > 40 and rep["nav_stats"]["vol_annual"] > 0
    assert 0 <= rep["nav_stats"]["max_drawdown"] < 0.2
    text = report.render(rep)
    assert "By bucket:" in text and "Concentration: HHI" in text and "max drawdown" in text


def test_cli_risk_reproduces_report(tmp_path, monkeypatch, capsys):
    con, days = _store_with_portfolio(tmp_path)
    con.close()
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "nodata"))
    (tmp_path / "ledger.duckdb").exists() or (tmp_path / "l.duckdb").rename(tmp_path / "ledger.duckdb")
    from pflab import cli
    assert cli.main(["pm", "risk", "--asof", days[-1].isoformat()]) == 0
    out = capsys.readouterr().out
    con2 = store.connect(tmp_path / "ledger.duckdb")
    assert out.strip() == report.render(report.build(con2, days[-1], bench_loader=lambda: None)).strip()
