"""S58b reviewed measures and the workshop's rules for maths: each measure against hand-worked answers and a brute-force
second implementation; a question a measure answers never reaches a writer; new code must be confirmed by an
independent second writing, and two writings that disagree are disputed (the 2026-10-22 misread, replayed)."""
import json
import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from pflab.agents import analyst as an
from pflab.agents import workshop as wk
from pflab.calc import measures as ms
from pflab.pm import store


def series(closes, start=date(2020, 1, 1)):
    return pd.DataFrame({"date": [start + timedelta(days=i) for i in range(len(closes))], "close": closes})


def rand(n=400, seed=7):
    r = np.random.default_rng(seed).normal(0.0004, 0.012, n)
    return series(list(100 * np.cumprod(1 + r)))


# --- the measures ---------------------------------------------------------------------------------------------------

def test_drawdown_is_the_fall_from_a_peak_not_the_worst_day():
    s = series([1000.0, 1100.0, 900.0, 800.0, 1000.0])              # the 2026-10-22 test case, read correctly
    d = ms.drawdown(s)
    assert d["fall_pct"] == pytest.approx(300 / 1100 * 100) and d["fall_points"] == 300.0
    assert (d["peak_date"], d["trough_date"], d["recovered_on"]) == ("2020-01-02", "2020-01-04", None)
    assert ms.extreme_days(s)["worst_pct"] == pytest.approx(-200 / 1100 * 100)       # a different question
    d = ms.drawdown(series([100.0, 120.0, 90.0, 60.0, 150.0, 140.0]))
    assert d["fall_pct"] == pytest.approx(50.0) and d["recovered_on"] == "2020-01-05"


def test_drawdown_matches_a_brute_force_over_every_pair():
    s = rand()
    v = s["close"].to_numpy()
    brute = max(1 - v[j] / v[i] for i in range(len(v)) for j in range(i, len(v)))
    assert ms.drawdown(s)["fall_pct"] == pytest.approx(brute * 100)


def test_a_window_counts_its_peaks_from_its_own_start():
    s = series([200.0, 100.0, 110.0, 90.0, 120.0])
    assert ms.drawdown(s, start=date(2020, 1, 2))["fall_pct"] == pytest.approx((110 - 90) / 110 * 100)
    with pytest.raises(ValueError):
        ms.drawdown(s, start=date(2030, 1, 1))


def test_period_return_and_cagr():
    s = pd.DataFrame({"date": [date(2020, 1, 1), date(2021, 1, 1), date(2022, 1, 1)], "close": [100.0, 110.0, 121.0]})
    r = ms.period_return(s)
    assert r["return_pct"] == pytest.approx(21.0) and r["cagr_pct"] == pytest.approx(10.0, abs=0.01)
    # first two closes, 366 days apart (2020 is a leap year): a little over a year at 10%
    assert ms.period_return(s, end=date(2021, 6, 1))["cagr_pct"] == pytest.approx((1.1 ** (365.25 / 366) - 1) * 100)
    assert ms.period_return(series([100.0, 105.0]))["cagr_pct"] is None           # under a year: no yearly rate


def test_volatility_extremes_and_runs_against_second_implementations():
    s = rand()
    v = s["close"].to_numpy()
    r = v[1:] / v[:-1] - 1
    vol = ms.volatility(s)
    assert vol["daily_pct"] == pytest.approx(np.std(r, ddof=1) * 100)
    assert vol["annual_pct"] == pytest.approx(np.std(r, ddof=1) * math.sqrt(252) * 100)
    e = ms.extreme_days(s)
    assert e["worst_pct"] == pytest.approx(r.min() * 100) and e["best_pct"] == pytest.approx(r.max() * 100)
    w = ms.worst_run(s, sessions=5)
    assert w["worst_pct"] == pytest.approx(min(v[i + 5] / v[i] - 1 for i in range(len(v) - 5)) * 100)


def test_var_and_cvar_by_hand():
    closes = [100.0]
    for x in [-0.05, 0.01, -0.02, 0.03, -0.01, 0.02, 0.0, -0.03, 0.01, 0.02]:
        closes.append(closes[-1] * (1 + x))
    v = ms.var_cvar(series(closes), level=0.8)        # 10 returns; the lower 20% quantile is the 2nd smallest: -0.03
    assert v["var_pct"] == pytest.approx(3.0) and v["cvar_pct"] == pytest.approx(4.0) and v["tail_days"] == 2


def test_chance_of_a_fall_against_a_loop():
    s = rand(300, seed=3)
    v = s["close"].to_numpy()
    hits = [min(v[i + 1:i + 21]) <= v[i] * 0.95 for i in range(len(v) - 20)]
    c = ms.chance_of_fall(s, fall_pct=5, sessions=20)
    assert c["chance_pct"] == pytest.approx(np.mean(hits) * 100) and c["independent_starts"] == (len(v) - 20) // 20


def test_relation_of_a_doubled_series():
    a = rand(200, seed=1)
    ra = a["close"].pct_change().fillna(0).to_numpy()
    b = a.assign(close=100 * np.cumprod(1 + 2 * ra))
    rel = ms.relation(b, a)
    assert rel["correlation"] == pytest.approx(1.0) and rel["beta"] == pytest.approx(2.0)


# --- the workshop: measures first ------------------------------------------------------------------------------------

def data_root(tmp_path):
    root = tmp_path / "data"
    (root / "indices").mkdir(parents=True)
    series([10.0, 12.0, 9.0, 6.0, 15.0]).to_parquet(root / "indices" / "X.parquet")
    return root


ROUTE = '{"measure": "drawdown", "series": "index:X", "second": null, "values": {"start": "2020-01-01", "end": "2020-12-31"}}'


def test_a_question_a_measure_answers_never_reaches_a_writer(tmp_path, monkeypatch):
    root = data_root(tmp_path)
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(an, "config", lambda: {"adopted": False})
    writer_calls = []
    out = wk.ask(con, "What was the largest fall of X from a peak in 2020?", tmp_path / "pm", root, date(2026, 10, 24),
                 local=lambda p: ROUTE if p.startswith("Pick the one") else writer_calls.append(p) or "{}",
                 now=datetime(2026, 10, 24, 15, 0))
    assert out.status == "checked" and out.measure == "drawdown" and writer_calls == []
    assert out.run.result["fall_pct"] == pytest.approx(50.0)
    assert "drawdown of index:X (start 2020-01-01, end 2020-12-31)" in wk.render(out)
    meta = json.loads((out.folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["label"] == "reviewed measure" and not (out.folder / "code.py").exists()
    with pytest.raises(ValueError):
        wk.promote(tmp_path / "pm", out.folder.name, by="investor")


@pytest.mark.parametrize("reply", ['{"measure": "none"}', '{"measure": "drawdown", "series": "index:NOPE"}',
                                   '{"measure": "drawdown", "series": "index:X", "values": {"start": "soon"}}',
                                   '{"measure": "relation", "series": "index:X"}', "no json"])
def test_a_route_that_does_not_check_out_goes_on_to_the_writers(tmp_path, reply):
    root = data_root(tmp_path)
    cat = wk.catalogue(root)
    con = store.connect(tmp_path / "l.duckdb")
    assert wk.from_measures("q", cat, lambda n: {k: wk.load_dataset(k, con, root, date(2026, 10, 24)) for k in n},
                            lambda p: reply) is None


@pytest.mark.parametrize("q,name,fits", [
    ("Nifty 50's largest fall in 2020", "index:NIFTY50_PRICE", True),
    ("Nifty 50's largest fall in 2020", "index:NIFTY50_TRI", False),
    ("How often has the Nifty 500 TRI fallen 10%?", "index:NIFTY50_TRI", False),     # 2026-10-24: misread by the model
    ("How often has the Nifty 500 TRI fallen 10%?", "index:NIFTY500_TRI", True),
    ("Bank Nifty volatility this year", "index:SECTOR_BANK_PRICE", True),
    ("Nifty 200 Momentum 30 total return since 2015", "index:NIFTY200_MOMENTUM30_TRI", True),
    ("Nifty 50 P/E today", "index:NIFTY50_VALUATION", True),
    ("Nifty 50 worst day", "index:NIFTY50_VALUATION", False),
    ("Nifty 500 TRI fallen 10% within a month", "index:SECTOR_IT_TRI", False),        # IT is not inside "within"
    ("S&P 500 worst day", "global:US_SP500", True)])
def test_the_series_must_be_the_one_the_question_names(q, name, fits):
    assert wk.series_fits(q, name) is fits


def test_a_misread_series_is_corrected_when_one_fits(tmp_path):
    root = data_root(tmp_path)
    for n in ("NIFTY50_TRI", "NIFTY500_TRI"):
        series([10.0, 12.0, 9.0, 6.0, 15.0]).to_parquet(root / "indices" / f"{n}.parquet")
    con = store.connect(tmp_path / "l.duckdb")
    out = wk.from_measures("Largest fall of the Nifty 500 TRI?", wk.catalogue(root),
                           lambda n: {k: wk.load_dataset(k, con, root, date(2026, 10, 24)) for k in n},
                           lambda p: '{"measure": "drawdown", "series": "index:NIFTY50_TRI", "values": {}}')
    assert out.spec.datasets == ["index:NIFTY500_TRI"] and "corrected from index:NIFTY50_TRI" in wk.render(out)


def test_a_world_series_for_a_named_nse_index_is_corrected(tmp_path):
    """S59 thorough test: 'NIFTY 50 ... in 2023' was answered on global:US_SP500 (world series were never checked)."""
    root = data_root(tmp_path)
    (root / "global").mkdir(exist_ok=True)
    series([10.0, 12.0, 9.0, 6.0, 15.0]).to_parquet(root / "indices" / "NIFTY50_PRICE.parquet")
    series([10.0, 11.0, 12.0, 13.0, 14.0]).to_parquet(root / "global" / "US_SP500.parquet")
    con = store.connect(tmp_path / "l.duckdb")
    frames = lambda n: {k: wk.load_dataset(k, con, root, date(2026, 10, 24)) for k in n}   # noqa: E731
    out = wk.from_measures("Largest fall of the NIFTY 50?", wk.catalogue(root), frames,
                           lambda p: '{"measure": "drawdown", "series": "global:US_SP500", "values": {}}')
    assert out.spec.datasets == ["index:NIFTY50_PRICE"] and "corrected from global:US_SP500" in wk.render(out)
    out = wk.from_measures("Largest fall of the S&P 500?", wk.catalogue(root), frames,
                           lambda p: '{"measure": "drawdown", "series": "global:US_SP500", "values": {}}')
    assert out.spec.datasets == ["global:US_SP500"]                                  # no NSE index named: kept


# --- the workshop: new code confirmed by an independent second writing ---------------------------------------------

def writing(code, expected):
    return json.dumps({"datasets": ["index:X"], "code": code, "explain": "as written",
                       "test": {"data": {"index:X": [{"date": "2020-01-01", "close": 1000.0}, {"date": "2020-01-02", "close": 1100.0},
                                                     {"date": "2020-01-03", "close": 900.0}, {"date": "2020-01-04", "close": 800.0},
                                                     {"date": "2020-01-05", "close": 1000.0}]},
                                "expected": {"largest_fall": expected}, "tol": 1e-6}})


FROM_PEAK = ("def compute(data):\n    c = data['index:X']['close']\n"
             "    return {'largest_fall': float((1 - c / c.cummax()).max())}\n")
ONE_DAY = ("def compute(data):\n    c = data['index:X']['close']\n"
           "    return {'largest_fall': float(-(c / c.shift(1) - 1).min())}\n")


def test_two_writings_that_disagree_are_disputed_never_reused_or_promoted(tmp_path, monkeypatch):
    root = data_root(tmp_path)
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(an, "config", lambda: {"adopted": False})
    replies = iter([writing(ONE_DAY, 200 / 1100), writing(FROM_PEAK, 300 / 1100)])  # each passes its own example

    def local(p):
        return '{"measure": "none"}' if not p.startswith("QUESTION:") else next(replies)
    q = "What was the largest fall of X from a peak?"
    out = wk.ask(con, q, tmp_path / "pm", root, date(2026, 10, 24), local=local, now=datetime(2026, 10, 24, 15, 0))
    assert out.status == "disputed" and out.confirm["status"] == "disagrees"
    assert "DISAGREE" in wk.render(out) and "largest_fall" in out.confirm["detail"]
    assert wk.find(tmp_path / "pm", q) is None
    with pytest.raises(ValueError):
        wk.promote(tmp_path / "pm", out.folder.name, by="investor")
    assert con.execute("SELECT count(*) FROM memory WHERE source LIKE 'workshop %'").fetchone()[0] == 0


def test_two_writings_that_agree_are_confirmed_and_reused_for_the_same_question(tmp_path, monkeypatch):
    root = data_root(tmp_path)
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(an, "config", lambda: {"adopted": False})
    local = lambda p: '{"measure": "none"}' if not p.startswith("QUESTION:") else writing(FROM_PEAK, 300 / 1100)  # noqa: E731
    q = "What was the largest fall of X from a peak?"
    out = wk.ask(con, q, tmp_path / "pm", root, date(2026, 10, 24), local=local, now=datetime(2026, 10, 24, 15, 0))
    assert out.status == "checked" and out.confirm["status"] == "agrees" and "agrees" in wk.render(out)
    again = wk.ask(con, q, tmp_path / "pm", root, date(2026, 10, 24), local=local, now=datetime(2026, 10, 24, 15, 1))
    assert again.reused_from == out.folder.name
