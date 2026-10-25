"""S52 live (quant/tfm2_live.py): inputs point in time, forecasts stored beside the registered baseline, scoring, the
registered switch to the baseline and back, and what the tickets, the researcher and the thesis tracker show."""
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from pflab.conductor.calendar import Calendar
from pflab.pm import store
from pflab.quant import tfm2 as tf
from pflab.quant import tfm2_live as fl

A, B = "INE000A01011", "INE000B01011"
CAL = Calendar()                                   # weekdays only


def bhav(root, end: date, n: int = 700, seed: int = 0):
    """Two stocks' daily turnover on n weekdays to `end` (B stops trading for the last 600 sessions)."""
    rng = np.random.default_rng(seed)
    d = pd.bdate_range(end=end, periods=n).date
    rows = []
    for k, i in enumerate((A, B)):
        lt = 18 + 0.3 * np.sin(np.arange(n) / 20) + rng.normal(0, 0.3, n)
        for j, x in enumerate(d):
            if i == B and j > 100:
                continue
            rows.append({"date": x, "symbol": f"S{k}", "series": "EQ", "isin": i, "turnover": float(np.exp(lt[j]))})
    df = pd.DataFrame(rows)
    for y, g in df.groupby([pd.Timestamp(x).year for x in df["date"]]):
        p = root / "bhavcopy" / str(y)
        p.mkdir(parents=True, exist_ok=True)
        g.to_parquet(p / "part.parquet", index=False)
    return list(d)


def quarters(con, scrip: str, n: int, last: date, usable_lag: int = 40):
    qe = pd.date_range(end=pd.Timestamp(last), periods=n, freq="QE").date
    for k, q in enumerate(qe):
        rev = 1000 * 1.02 ** k
        con.execute("INSERT INTO quarterly_results (scrip_code, quarter_end, revenue, net_profit, usable_from, date_source, "
                    "source, fetched_at, basis) VALUES (?,?,?,?,?,?,?,?,?)",
                    [scrip, q, rev, 0.1 * rev, q + timedelta(days=usable_lag), "announcement", "test", datetime(2026, 1, 1),
                     "standalone"])


def fake_tfm(shift: float = 0.0):
    """Deciles around the baseline's own level (+ shift), as TimesFM's output shapes."""
    calls = []

    def run(inputs):
        calls.append(inputs)
        z = np.linspace(-0.2, 0.2, 9)
        out = {"asof": inputs["asof"], "models": {"turnover": "T30C test", "revenue": "F25 test", "margin": "T25 test"},
               "turnover": {c["key"]: [list(c["baseline"] + shift + z)] * 5 for c in inputs["turnover"]},
               "revenue": {c["key"]: list(c["baseline"] + shift + z / 10) for c in inputs["revenue"]},
               "margin": {c["key"]: list(c["baseline"] + z / 100) for c in inputs["margin"]}}
        return out
    run.calls = calls
    return run


@pytest.fixture
def env(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    root = tmp_path / "data"
    u = pd.DataFrame([{"isin": A, "symbol": "AAA", "scrip": "500002"}, {"isin": B, "symbol": "BBB", "scrip": "500003"}])
    return con, root, u


def test_turnover_case_is_point_in_time_with_the_calendar_ahead():
    d = list(pd.bdate_range(end="2026-10-16", periods=700).date)
    lev = np.exp(18 + np.random.default_rng(1).normal(0, 0.3, 700))
    fut = fl.future_sessions(CAL, d[-1], fl.H5 + fl.FUTURE)
    c = fl.turnover_case(d, lev, fut)
    assert len(c["ctx"]) == fl.CTX5 and c["ctx"][-1] == pytest.approx(np.log(lev[-1]))      # up to the as-of session
    pf = np.asarray(c["pf"])
    assert pf.shape == (3, fl.CTX5 + fl.H5) and c["target"] == str(fut[4]) == "2026-10-23"
    assert pf[0, -5:].tolist() == [0, 1, 2, 3, 4]                                            # the next week's weekdays
    assert c["baseline_name"] == "har_cal" and abs(c["baseline"] - 18) < 0.5
    lev[-500:] = 0                                                                           # no trades lately
    assert fl.turnover_case(d, lev, fut) is not None and fl.turnover_case(d[:5], lev[:5], fut) is None


def test_results_case_needs_eight_quarters_and_uses_the_registered_baselines():
    qe = pd.date_range(end="2026-06-30", periods=12, freq="QE").date
    q = pd.DataFrame({"quarter_end": qe, "revenue": 1000 * 1.02 ** np.arange(12), "net_profit": 50 + np.arange(12)})
    c = fl.results_case(q)
    assert c["run"] == 12 and c["target"] == "2026-09-30" and c["inputs_last"] == "2026-06-30"
    x = np.log(q["revenue"].to_numpy())
    assert c["revenue"]["baseline"] == pytest.approx(x[-4] + np.mean(x[-4:] - x[-8:-4]))       # last year x growth
    assert c["margin"]["baseline"] == pytest.approx(q["net_profit"].iloc[-4] / q["revenue"].iloc[-4])
    assert fl.results_case(q.iloc[-7:])["run"] == 7 and "revenue" not in fl.results_case(q.iloc[-7:])
    gap = q.drop(index=8)                                                                    # a missing quarter breaks the run
    assert fl.results_case(gap)["run"] == 3


def test_run_stores_beside_the_baseline_scores_and_reports_a_failed_timesfm(env):
    con, root, u = env
    bhav(root, date(2026, 10, 9))
    quarters(con, "500002", 10, date(2026, 6, 30))
    quarters(con, "500003", 5, date(2026, 6, 30))
    fc = fake_tfm()
    r = fl.run(con, root, date(2026, 10, 9), u, CAL, fc, now=datetime(2026, 10, 9, 21))
    assert r["timesfm"] and r["turnover"] == 1 and r["revenue"] == 1 and r["skipped"] == 2   # B: no trades; 500003: 5 qtrs
    rows = con.execute("SELECT use, subject, target, model, point, baseline FROM tfm_forecasts ORDER BY use").fetchall()
    assert {(x[0], x[1], str(x[2])) for x in rows} == {("margin", "500002", "2026-09-30"),
                                                       ("revenue", "500002", "2026-09-30"),
                                                       ("turnover", A, "2026-10-16")}
    assert all(x[3] and x[4] is not None and x[5] is not None for x in rows)
    # a later night: the turnover target has traded, the September quarter is out; nothing is stored twice
    bhav(root, date(2026, 10, 30), n=715)
    quarters(con, "500002", 1, date(2026, 9, 30), usable_lag=20)
    r2 = fl.run(con, root, date(2026, 10, 30), u, CAL, None, now=datetime(2026, 10, 30, 21))
    assert not r2["timesfm"] and r2["error"] is None and r2["scored"] == 3
    s = con.execute("SELECT use, actual, loss_model, loss_baseline FROM tfm_forecasts WHERE as_of = DATE '2026-10-09'").fetchall()
    assert all(x[1] is not None and x[2] is not None and x[3] is not None for x in s)
    new = con.execute("SELECT use, model, baseline FROM tfm_forecasts WHERE as_of = DATE '2026-10-30'").fetchall()
    assert new and all(m is None and b is not None for _, m, b in new)                       # baseline-only rows
    # TimesFM failing is recorded, the baseline still stored
    def boom(_):
        raise RuntimeError("no GPU, no CPU")
    r3 = fl.run(con, root, date(2026, 11, 2), u, CAL, boom, now=datetime(2026, 11, 2, 21))
    assert r3["error"].startswith("RuntimeError") and not r3["timesfm"]


def test_scoreboard_switches_to_the_baseline_and_back_as_registered(env):
    con, _, _ = env
    d0 = date(2026, 1, 1)

    def put(k, lm, lb, use="turnover", target=None):
        fid = store.next_id(con, "tfm_forecasts", "forecast_id")
        a = d0 + timedelta(days=k)
        con.execute("INSERT INTO tfm_forecasts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [fid, use, A, a, target or a + timedelta(days=7), a, "T30C t", 0, 0, 0, 0, 0, "har_cal", 0, lm, lb,
                     datetime(2026, 3, 1), datetime(2026, 1, 1)])
    for k in range(29):
        put(k, 1.2, 1.0)
    assert fl.update_scoreboard(con, d0, datetime(2026, 3, 1)) == [] and fl.serving(con, "turnover") == "timesfm"
    put(29, 1.2, 1.0)                                                       # 30 matured dates: half the window
    msg = fl.update_scoreboard(con, d0 + timedelta(days=1), datetime(2026, 3, 2))
    assert fl.serving(con, "turnover") == "baseline" and "switched to the baseline" in msg[0]
    for k in range(30, 59):
        put(k, 0.5, 1.0)
    fl.update_scoreboard(con, d0 + timedelta(days=2), datetime(2026, 3, 3))
    assert fl.serving(con, "turnover") == "baseline"                       # ratio <= 1 but not yet a full window
    put(59, 0.5, 1.0)
    msg = fl.update_scoreboard(con, d0 + timedelta(days=3), datetime(2026, 3, 4))
    assert fl.serving(con, "turnover") == "timesfm" and "TimesFM resumes" in msg[0]
    # results: the last two quarters with results in; the pending quarter is outside the window
    for k, t in enumerate((date(2025, 12, 31), date(2026, 3, 31))):
        put(k, 2.0, 1.0, "revenue", t)
    w, n = fl.window(con, "revenue")
    assert n == 2 and len(w) == 2


def test_what_the_agents_show(env, monkeypatch):
    from pflab.agents import researcher as rs
    from pflab.plan import trader
    con, root, u = env
    bhav(root, date(2026, 10, 9))
    quarters(con, "500002", 10, date(2026, 6, 30))
    fl.run(con, root, date(2026, 10, 9), u, CAL, fake_tfm(), now=datetime(2026, 10, 9, 21))
    est = fl.turnover_estimate(con, A, date(2026, 10, 10))
    assert est and "TimesFM 3.0 + calendar" in est[1]
    tk = trader.tickets("AAA", 100, 500.0, "", isin=A, turnover=fl.turnover_fn(con, date(2026, 10, 10)))
    assert tk[-1].startswith("Size check (ESTIMATE, TimesFM 3.0") and "of the expected daily turnover" in tk[-1]
    assert fl.turnover_estimate(con, A, date(2026, 10, 30)) is None                         # stale: not used
    con.execute("INSERT INTO tfm_scoreboard VALUES ('turnover', DATE '2026-10-09', 30, 60, 1.2, 'baseline', true, now())")
    assert "TimesFM off by its scoreboard" in fl.turnover_estimate(con, A, date(2026, 10, 10))[1]
    lines = fl.results_lines(con, "500002", "AAA")
    assert any("revenue, quarter ending 2026-09-30: range Rs" in x and "ESTIMATE, TimesFM 2.5 fine-tuned" in x for x in lines)
    f = rs.forecast_flags(con, A, "AAA", "500002", datetime(2026, 10, 1), datetime(2026, 10, 10))
    assert [x.kind for x in f] == ["results_range"] and "net margin" in f[0].detail
    # the result arrives: the surprise flag, dated by its dissemination
    quarters(con, "500002", 1, date(2026, 9, 30), usable_lag=20)
    bhav(root, date(2026, 10, 30), n=715)
    fl.run(con, root, date(2026, 10, 30), u, CAL, fake_tfm(), now=datetime(2026, 10, 30, 21))
    f = rs.forecast_flags(con, A, "AAA", "500002", datetime(2026, 10, 25), datetime(2026, 10, 31))
    sur = [x for x in f if x.kind == "results_surprise"]
    assert sur and sur[0].happened_at == datetime(2026, 10, 20) and "the range" in sur[0].detail
    assert "serving TimesFM 2.5 fine-tuned" in fl.show(con)


def test_turnover_is_dated_by_its_last_session_results_by_the_run_date(env):
    con, root, u = env
    bhav(root, date(2026, 10, 9))                                           # Friday
    quarters(con, "500002", 10, date(2026, 6, 30))
    rows = fl.rows_from(fl.build(con, root, date(2026, 10, 10), u, CAL), None)
    assert {(r["use"], r["asof"]) for r in rows} == {("turnover", "2026-10-09"), ("revenue", "2026-10-10"),
                                                       ("margin", "2026-10-10")}
