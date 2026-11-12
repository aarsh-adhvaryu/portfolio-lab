"""S84 replay harness (tools/replays_s84*.py): the building blocks, synthetic and fast (no profile, no model, no network). The replays and drills themselves run from the tool:
`python tools/replays_s84_cli.py all`."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import replays_s84 as R  # noqa: E402
import replays_s84_model as M  # noqa: E402


def _bars(start: date, n: int, p0: float = 100.0) -> pd.DataFrame:
    days = [start + timedelta(days=i) for i in range(n)]
    px = [p0 + i for i in range(n)]
    return pd.DataFrame({"date": days, "open": px, "high": px, "low": px, "close": px, "adj_close": px, "volume": 1_000_000, "dividend": 0.0})


@pytest.fixture()
def con(tmp_path, monkeypatch):
    from pflab.pm import store
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path / "pm"))
    (tmp_path / "pm").mkdir()
    c = store.connect(tmp_path / "pm" / "ledger.duckdb")
    yield c
    c.close()


def test_the_world_is_shown_only_what_is_public_at_its_clock(tmp_path, monkeypatch):
    real, data = tmp_path / "real", tmp_path / "world"
    (real / "us" / "raw").mkdir(parents=True)
    (real / "indices").mkdir()
    (real / "global").mkdir()
    _bars(date(2026, 11, 2), 12).to_parquet(real / "us" / "raw" / "NVDA.parquet", index=False)
    _bars(date(2026, 11, 2), 12).rename(columns={"close": "close"}).to_parquet(real / "indices" / "NIFTY500_TRI.parquet", index=False)
    monkeypatch.setitem(R.REVEAL, "root", real)
    monkeypatch.setitem(R.REVEAL, "india", set())
    env = SimpleNamespace(data=data, clock=SimpleNamespace(t=datetime(2026, 11, 9, 7, 0)))
    cuts = R.reveal(env, datetime(2026, 11, 9, 7, 0))                           # Monday morning IST: the US closes through Friday 6 Nov, the NSE files through Friday
    us = pd.read_parquet(data / "us" / "raw" / "NVDA.parquet")
    assert cuts["us"] == "2026-11-06" and max(us["date"]) == date(2026, 11, 6)
    ix = pd.read_parquet(data / "indices" / "NIFTY500_TRI.parquet")
    assert max(ix["date"]) == date(2026, 11, 6) and cuts["india"] == "2026-11-06"
    R.reveal(env, datetime(2026, 11, 9, 21, 30))                                # the NSE files of Monday are in after 20:15; the US session of Monday is not closed yet
    assert max(pd.read_parquet(data / "indices" / "NIFTY500_TRI.parquet")["date"]) == date(2026, 11, 9)
    assert max(pd.read_parquet(data / "us" / "raw" / "NVDA.parquet")["date"]) == date(2026, 11, 6)
    R.reveal(env, datetime(2026, 11, 10, 7, 0))                                 # Tuesday morning: Monday's US session (closed 02:30 IST) is public
    assert max(pd.read_parquet(data / "us" / "raw" / "NVDA.parquet")["date"]) == date(2026, 11, 9)


def test_a_headline_is_in_the_graph_only_from_its_time(con):
    key = "ZZ0001045810"
    early = datetime(2026, 11, 9, 6, 0)
    env = SimpleNamespace(cur=lambda: con)
    assert R.release_headlines(env, early, key) == 0
    assert con.execute("SELECT count(*) FROM kg2_event").fetchone()[0] == 0
    assert R.release_headlines(env, datetime(2026, 11, 9, 7, 0), key) == 1
    r = con.execute("SELECT source, kind, severity, ts FROM kg2_event").fetchall()
    assert r[0][0] == R.SOURCE and r[0][2] == "high" and r[0][3] == R.HEADLINES[0]["ts"]
    assert r[0][1] in ("leadership_crisis", "fraud_investigation")             # the S84 kind when the classifier has it, else the stand-in
    assert R.release_headlines(env, datetime(2026, 11, 9, 8, 0), key) == 0      # once
    assert R.release_headlines(env, datetime(2026, 11, 13, 8, 0), key) == 2     # the rest of the week, each once
    assert [h["ts"] for h in R.HEADLINES] == sorted(h["ts"] for h in R.HEADLINES)


def test_a_shock_multiplies_the_held_back_closes_from_its_day_only(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    rows = pd.DataFrame({"isin": ["A"] * 4 + ["B"] * 4, "date": [date(2026, 10, 15) + timedelta(days=i) for i in range(4)] * 2, "close": [100.0] * 8})
    rows.to_parquet(base / "held_prices.parquet")
    R.shock_held_prices(base, [("A", date(2026, 10, 17), 0.5)])
    h = pd.read_parquet(base / "held_prices.parquet")
    h["date"] = pd.to_datetime(h["date"]).dt.date
    a = h[h["isin"] == "A"].sort_values("date")["close"].tolist()
    assert a == [100.0, 100.0, 50.0, 50.0] and set(h[h["isin"] == "B"]["close"]) == {100.0}


def test_a_position_is_injected_out_of_the_spy_shares_and_cash_keeping_the_value(con, tmp_path):
    from pflab.us import book, instruments as uins
    data = tmp_path / "data"
    (data / "us" / "raw").mkdir(parents=True)
    _bars(date(2026, 11, 2), 8, 700.0).to_parquet(data / "us" / "raw" / "SPY.parquet", index=False)
    _bars(date(2026, 11, 2), 8, 180.0).to_parquet(data / "us" / "raw" / "NVDA.parquet", index=False)
    now = datetime(2026, 11, 7, 9, 0)
    spy = uins.ensure(con, "SPY", "SPDR S&P 500 ETF", etf=True, now=now)
    con.execute("INSERT INTO us_lots_s81 VALUES (1,?,?,?,?,?,?,?,?)", [spy, "SPY", date(2026, 11, 2), 1.0, 700.0, None, None, "test"])
    book.add_cash(con, now, date(2026, 11, 2), 300.0, "test")
    day = date(2026, 11, 6)
    before = 1.0 * 704.0 + 300.0
    inj = R.inject_us_position(con, now, day, "NVDA", "ZZ0001045810", 0.08, data)
    assert inj["usd"] == pytest.approx(0.08 * before, rel=1e-6)
    pos = book.positions(con, day)
    px_nvda, px_spy = 184.0, 704.0
    value = book.cash(con, day) + pos["ZZ0001045810"] * px_nvda + pos[spy] * px_spy
    assert value == pytest.approx(before, rel=1e-6)                             # bought out of cash and SPY: the sub-book's value is unchanged
    assert pos["ZZ0001045810"] * px_nvda / value == pytest.approx(0.08, rel=1e-6)


def test_the_scripted_client_serves_a_tool_turn_then_text_and_counts_every_answer():
    calls = []

    def responder(call):
        calls.append(call)
        if call["tools"] and not call["has_tool_result"]:
            return {"tools": [("recall", {"symbol": "X"})]}
        return {"text": "Reading."}
    counter = {}
    cl = ScriptedClient = M.ScriptedClient(responder, counter)
    m1 = cl.beta.messages.create(model="claude-sonnet-5-5", messages=[{"role": "user", "content": "CASE #1 (x)"}], tools=[{"name": "recall"}], betas=["b"], fallbacks="default")
    assert m1.stop_reason == "tool_use" and m1.content[0].name == "recall"
    m2 = cl.messages.create(model="claude-sonnet-5-5", messages=[{"role": "user", "content": "CASE #1 (x)"}, {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "r"}]}], tools=[{"name": "recall"}])
    assert m2.content[0].text == "Reading." and counter["answers"] == 2
    assert cl.messages.count_tokens(model="m", messages=[]).input_tokens > 0


@pytest.mark.parametrize("name", ["nvda_held", "nvda_not_held", "ather"])
def test_every_scripted_answer_fits_the_closed_lists_and_carries_no_number(name):
    from pflab.think import session
    fn = M.SCENARIOS[name]
    syms = {"nvda_held": "NVDA", "nvda_not_held": "NVDA", "ather": "ATHERENERG"}[name]
    for sym in (syms, "SPY", "SYNFMCG"):
        for n in (1, 2):
            ans = fn({"symbol": sym, "case_id": 1}, n)
            assert session.validate_answer(json.loads(json.dumps(ans)), "Nifty 500 S&P 500 Nasdaq 100") == [], (name, sym, n)


def test_the_two_nvidia_scripts_differ_only_where_the_week_does():
    held = M.nvda_held_answers({"symbol": "NVDA"}, 1)
    not_held = M.nvda_not_held_answers({"symbol": "NVDA"}, 1)
    assert held["class"] == "damage" and held["choices"][0]["option"] == "sell"
    assert not_held["class"] == "unclear" and not_held["choices"][0]["option"] == "wait"
    assert M.nvda_not_held_answers({"symbol": "NVDA"}, 2)["choices"][0]["option"] == "buy_in_parts"     # the model's dip-buying; the rule has its own guards


def test_the_account_prints_a_day_in_plain_lines():
    tl = [{"t": "Mon 09 Nov 07:00", "signals": [("NVDA", "thesis_event", 3.0, 1.0, "examined")], "cases": [(1, "NVDA", "acted", "damage", "NVDA: leadership crisis")],
           "decisions": [(1, "NVDA", "sell", "sell", "sell", False, "a thesis break")], "us_orders": [(3, date(2026, 11, 9), "NVDA", "sell", 0.5, None, "open", None, "case #1")]}]
    txt = R.account(tl)
    assert txt.splitlines()[0] == "Mon 09 Nov 07:00" and "noticed: NVDA thesis_event" in txt and "case #1 on NVDA: acted (damage)" in txt and "US order #3 sell NVDA" in txt


def test_a_skip_is_stored_and_the_snapshot_sees_only_what_is_new(con):
    before = R._maxids(con)
    R.add_skip(con, "IN", "INE0LEZ01016", "ATHERENERG", "valuation", date(2026, 9, 21))
    assert con.execute("SELECT symbol, skipped_on FROM skips_s83").fetchall() == [("ATHERENERG", date(2026, 9, 21))]
    from pflab.think import cases
    cid = cases.open_case(con, datetime(2026, 11, 9, 7, 0), market="US", kind="thesis_event", isin="ZZ0001045810", symbol="NVDA", title="t")
    snap = R.snapshot_since(con, before)
    assert snap["cases"][0][0] == cid and "signals" not in snap
    assert R.snapshot_since(con, R._maxids(con)) == {}


def test_the_ather_skip_day_is_the_first_stored_day_near_1400():
    pan = pd.DataFrame({"symbol": ["ATHERENERG"] * 5, "date": [date(2026, 9, 18), date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 24)], "close": [1300.0, 1380.0, 1395.0, 1499.0, 1500.0]})
    assert R.ather_skip_day(pan) == date(2026, 9, 21)
