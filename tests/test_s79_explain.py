"""S79 item 7: explain a move with explicit, tested tools. Synthetic minute bars and prices only.

Hand-built day: 375 one-minute bars of AAA on 2026-10-23, flat with a +-0.01 wobble, a +1.5 jump at 10:20 and a +1.0 jump at 14:00; prior close 99.0."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from pflab import markets
from pflab.agents import analyst as an
from pflab.hq import egress, explain, tools as tl
from pflab.hq.desk import Desk
from pflab.pm import store
from pflab.quant import align, breadth, decompose, trajectory as tj
from tests.test_s68_assistant import CFG

AAA = "INE000A01011"
DAY = date(2026, 10, 23)
NOW = datetime(2026, 10, 23, 16, 30)
IN = markets.get("IN")


def _minute_frame(day=DAY, drop=(), wobble=0.01):
    ts = pd.date_range(datetime.combine(day, time(9, 15)), periods=375, freq="min")
    close = []
    for t in range(375):
        base = 100.0 + (1.5 if t >= 65 else 0.0) + (1.0 if t >= 285 else 0.0)
        close.append(base + wobble * (t % 2))
    close = np.array(close)
    open_ = np.r_[100.0, close[:-1]]
    df = pd.DataFrame({"ts": ts, "open": open_, "high": close + 0.01, "low": close - 0.01, "close": close, "volume": 1000.0})
    return df[~df.index.isin(drop)].reset_index(drop=True)


def _put_bars(con, df, key=AAA, market="IN"):
    b = df.assign(market=market, isin=key)[["market", "isin", "ts", "open", "high", "low", "close", "volume"]]
    con.register("_b", b)
    con.execute("INSERT INTO bars_1m SELECT * FROM _b")
    con.unregister("_b")


# --- the data folder: bhavcopy, indices, sector map, BSE announcements --------------------------------------------------------------------

def _sessions(n, end=DAY):
    out, d = [], end
    while len(out) < n:
        out.append(d)
        d = IN.previous_session(d)
    return sorted(out)


def _bhav(root, d, rows):
    p = root / "bhavcopy" / f"{d.year}"
    p.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"date": str(d), "symbol": s, "series": "EQ", "isin": i, "open": c, "high": c, "low": c, "close": c, "prev_close": pc, "volume": 1000, "turnover": 0.0, "trades": 1}
                  for i, s, c, pc in rows]).to_parquet(p / f"{d}.parquet")


def _index(root, key, closes, dates):
    (root / "indices").mkdir(exist_ok=True)
    pd.DataFrame({"date": [str(d) for d in dates], "close": closes}).to_parquet(root / "indices" / f"{key}.parquet")


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "data"
    r.mkdir()
    return r


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, 'AAA', 'AAA Ltd', 'synthetic', now())", [AAA])
    return c


@pytest.fixture
def rt(con, root, tmp_path, monkeypatch):
    monkeypatch.setattr(an, "config", lambda: CFG)
    from pflab.hq import service
    monkeypatch.setattr(service, "gate", lambda r: egress.Gate())
    (tmp_path / "pm" / "app").mkdir(parents=True)
    return Desk(con, tmp_path / "pm", root, tmp_path / "repo", None, {"brain": "normal", "preset": "full", "telegram_send": False}, clock=lambda: NOW)


def _ctx(rt):
    return tl.Ctx(rt, None, "m", False, {}, egress.Gate(), NOW, role="research")


# --- trajectory ---------------------------------------------------------------------------------------------------------------------------

def test_trajectory_numbers_on_a_hand_built_day():
    r = tj.trajectory(_minute_frame(), 99.0, time(9, 15), time(15, 30))
    assert r["n_bars"] == 375 and r["expected_bars"] == 375 and r["gaps"]["missing"] == 0
    assert r["open"] == 100.0 and r["close"] == 102.5 and r["prior_close"] == 99.0
    assert r["gap_pct"] == pytest.approx(1.01, abs=0.005)                                  # 100 / 99 - 1
    assert r["day_pct"] == pytest.approx(3.54, abs=0.005)                                  # 102.5 / 99 - 1
    assert r["opening_drive"]["pct"] == pytest.approx(0.01, abs=0.005) and r["opening_drive"]["direction"] == "up"
    assert r["opening_drive"]["minutes_of_data"] == 30
    assert r["time_of_low"] == "09:15" and r["time_of_high"] == "14:00"                    # the first bar's low; the first bar at the top level
    assert r["high"] == 102.52 and r["low"] == 99.99
    assert r["close_location"] == pytest.approx(0.99, abs=0.01)
    assert r["day_type"] == "trend day" and "outer 25%" in r["day_type_rule"]


def test_a_range_day_is_called_a_range_day():
    df = _minute_frame(wobble=0.0)
    df["close"] = 100.0 + np.sin(np.arange(375) / 20.0)                                      # up and down, ends near where it began
    df["open"] = np.r_[100.0, df["close"].to_numpy()[:-1]]
    df["high"], df["low"] = df["close"] + 0.05, df["close"] - 0.05
    r = tj.trajectory(df, 100.0)
    assert r["day_type"] == "range day" and r["range_efficiency"] < tj.TREND_ER


def test_bursts_are_found_with_timestamps():
    r = tj.trajectory(_minute_frame(), 99.0)
    assert r["n_bursts"] == 2
    by = {b["start"]: b for b in r["bursts"]}
    assert set(by) == {"10:20", "14:00"}
    assert by["10:20"]["return_pct"] == pytest.approx(1.51, abs=0.01) and by["10:20"]["z"] > 4
    assert by["14:00"]["return_pct"] == pytest.approx(1.0, abs=0.01)
    assert tj.trajectory(_minute_frame(), 99.0, k=1000.0)["n_bursts"] == 0                 # the threshold is the caller's


def test_a_missing_minute_is_stated_not_invented_and_no_return_crosses_it():
    df = _minute_frame(drop=range(100, 105))                                                  # 10:55 - 10:59 gone
    r = tj.trajectory(df, 99.0)
    assert r["n_bars"] == 370 and r["gaps"]["missing"] == 5 and r["gaps"]["runs"] == ["10:55-10:59"]
    df2 = _minute_frame(drop=[65])                                                           # the jump minute itself is missing: its return cannot be taken
    ev = tj.burst_events(df2)
    assert all(e["start"] != "10:20" for e in ev)                                            # 10:21's return would span the gap, so it is not taken either
    assert tj.trajectory(df2, 99.0)["gaps"]["runs"] == ["10:20"]


def test_no_bar_after_the_day_or_after_the_clock_is_used(con):
    _put_bars(con, _minute_frame())
    _put_bars(con, _minute_frame(day=DAY + timedelta(days=3)).assign(close=500.0, open=500.0, high=501.0, low=499.0))
    full = tj.load_bars(con, "IN", AAA, DAY)
    assert len(full) == 375 and full["ts"].max().date() == DAY and full["close"].max() < 200
    early = tj.load_bars(con, "IN", AAA, DAY, asof=datetime(2026, 10, 23, 10, 0))
    assert early["ts"].max() == pd.Timestamp("2026-10-23 10:00") and len(early) == 46         # 09:15 .. 10:00
    r = tj.trajectory(early, 99.0, asof=datetime(2026, 10, 23, 10, 0))
    assert r["bursts"] == [] and r["last_bar"] == "10:00" and r["gaps"]["missing"] == 0     # the 10:20 jump has not happened yet, and unseen minutes are not "missing"


# --- align ----------------------------------------------------------------------------------------------------------------------------------

def _announcements(root, rows, day=DAY):
    p = root / "bse_announcements" / f"{day.year}"
    p.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"scrip_code": sc, "company": "AAA Ltd", "headline": h, "category": "Company Update", "subcategory": sub, "news_dt": pd.Timestamp(t), "dissem_dt": pd.Timestamp(t),
                   "attachment": "x.pdf", "news_sub": h} for sc, h, sub, t in rows]).to_parquet(p / f"{day}.parquet")
    (root / "bse_scrip_isin").mkdir(exist_ok=True)
    pd.DataFrame([{"scrip_code": "500001", "isin": AAA, "valid_from": pd.Timestamp("1990-01-01"), "valid_to": pd.Timestamp("2999-12-31"), "company": "AAA Ltd", "status": "Active",
                   "first_seen": None, "last_seen": None, "n_announcements": 1, "source": "t", "in_panel": True, "isin_role": "current"}]).to_parquet(root / "bse_scrip_isin" / "map.parquet")


def test_bursts_line_up_with_filings_and_the_unexplained_one_is_said(root, con):
    _announcements(root, [("500001", "Outcome of board meeting", "Board Meeting", "2026-10-23 10:05:30"),      # 15 minutes before the 10:20 burst
                          ("500001", "Late filing", "Other", "2026-10-23 10:31:00"),                          # after the burst: not its cause
                          ("999999", "Another company", "Other", "2026-10-23 10:10:00")])                     # not this name
    bursts = tj.burst_events(_minute_frame())
    ev = align.filings(root, AAA, datetime(2026, 10, 22, 15, 30), datetime(2026, 10, 23, 15, 30))
    assert [e["headline"] for e in ev] == ["Outcome of board meeting", "Late filing"]
    res = align.align(bursts, ev, DAY, datetime(2026, 10, 22, 15, 30))
    by = {b["at"]: b for b in res["bursts"]}
    assert by["10:20"]["explained"] and by["10:20"]["preceded_by"][0]["minutes_before"] == 15 and by["10:20"]["n_events_in_window"] == 1
    assert not by["14:00"]["explained"] and res["unexplained_at"] == ["14:00"] and res["n_unexplained"] == 1
    # news from the knowledge graph explains the 14:00 one
    con.execute("INSERT INTO kg_docs (doc_id, kind, title, source, published_at, ingested_at) VALUES ('d1','article','AAA wins a large order','wire',?,now())", [datetime(2026, 10, 23, 13, 50)])
    con.execute("INSERT INTO kg_edges (src, rel, dst, valid_from, source_kind, ingested_at) VALUES ('d1','about',?,now(),'t',now())", [f"company:{AAA}"])
    nw = align.news(con, AAA, datetime(2026, 10, 22, 15, 30), datetime(2026, 10, 23, 15, 30))
    res2 = align.align(bursts, ev + nw, DAY, datetime(2026, 10, 22, 15, 30))
    assert res2["n_unexplained"] == 0 and {b["at"]: b for b in res2["bursts"]}["14:00"]["preceded_by"][0]["kind"] == "news"


def test_an_opening_burst_takes_the_news_of_the_night():
    ev = [{"at": datetime(2026, 10, 22, 20, 0), "kind": "filing", "what": "Results", "headline": "Q2 results"}]
    burst = [{"ts": datetime(2026, 10, 23, 9, 20), "return_pct": 2.0, "z": 9.0, "minutes": 1}]
    res = align.align(burst, ev, DAY, datetime(2026, 10, 22, 15, 30))
    assert res["bursts"][0]["explained"] and res["bursts"][0]["window"] == "since the previous close"
    late = [{"ts": datetime(2026, 10, 23, 11, 0), "return_pct": 2.0, "z": 9.0, "minutes": 1}]
    assert not align.align(late, ev, DAY, datetime(2026, 10, 22, 15, 30))["bursts"][0]["explained"]      # the same night filing is not a cause at 11:00


# --- decompose and breadth on a synthetic file set -------------------------------------------------------------------------------------------

def _universe(root, n=300, own_shock=0.03, seed=7, extra_after=False):
    """AAA = 1.2 x market + 0.5 x (IT sector beyond 0.8 x market) + noise, with a +3% own shock on the last day."""
    rng = np.random.default_rng(seed)
    days = _sessions(n)
    m = rng.normal(0.0005, 0.01, n)
    sec_res = rng.normal(0.0, 0.008, n)
    sec = 0.8 * m + sec_res
    stock = 1.2 * m + 0.5 * sec_res + rng.normal(0, 0.001, n)
    stock[-1] += own_shock
    lv = lambda r: 100.0 * np.cumprod(1 + r)
    s_close = lv(stock)
    _index(root, "NIFTY500_TRI", lv(m), days)
    _index(root, "SECTOR_IT_TRI", lv(sec), days)
    (root / "index_membership").mkdir(exist_ok=True)
    pd.DataFrame([{"capture_date": date(2020, 1, 1), "index": "NIFTY500", "isin": AAA, "issuer": AAA[2:8], "industry": "Information Technology", "taxonomy": "C"}]).to_parquet(
        root / "index_membership" / "sector_map.parquet")
    for k, d in enumerate(days):
        _bhav(root, d, [(AAA, "AAA", float(s_close[k]), float(s_close[k - 1]) if k else float(s_close[0]))])
    return days, m, sec, stock


def test_decompose_splits_the_move_and_the_parts_add_up(root):
    days, m, sec, stock = _universe(root)
    r = decompose.decompose(root, AAA, DAY)
    assert r["total_pct"] == pytest.approx(stock[-1] * 100, abs=0.01)
    assert r["beta_market"] == pytest.approx(1.2, abs=0.12) and r["beta_sector"] == pytest.approx(0.5, abs=0.12)
    assert r["market_pct"] == pytest.approx(r["beta_market"] * m[-1] * 100, abs=0.02)
    assert r["market_pct"] + r["sector_pct"] + r["own_pct"] == pytest.approx(r["total_pct"], abs=0.02)
    assert r["own_pct"] == pytest.approx(3.0, abs=0.6)                                       # the +3% shock lands in the own part
    assert r["industry"] == "Information Technology" and r["sector_index"] == "SECTOR_IT_TRI"


def test_decompose_is_point_in_time_the_day_and_later_rows_do_not_enter_the_betas(root):
    _universe(root, own_shock=0.03)
    a = decompose.decompose(root, AAA, DAY)
    _universe(root, own_shock=-0.08)                                                          # the day's own move changes ...
    b = decompose.decompose(root, AAA, DAY)
    assert a["beta_market"] == b["beta_market"] and a["beta_sector"] == b["beta_sector"]      # ... the betas do not: the day is not in the fit
    assert a["own_pct"] != b["own_pct"]
    later = DAY + timedelta(days=3)
    _bhav(root, later, [(AAA, "AAA", 1.0, 100.0)])                                            # a crash AFTER the day
    assert decompose.decompose(root, AAA, DAY)["beta_market"] == a["beta_market"]


def test_decompose_says_so_when_there_is_no_history_or_no_price(root):
    _universe(root, n=30)
    r = decompose.decompose(root, AAA, DAY)
    assert r.get("beta_market") is None and "no beta" in r["note"]
    assert "no price" in decompose.decompose(root, "INE999Z01019", DAY)["note"]


def test_breadth_numbers_and_the_price_break_exclusion(root):
    days = _sessions(55)
    rows = {}
    for t, d in enumerate(days):
        a = 100.0 + t
        b = 200.0 - t
        c = 50.0 if t < 54 else 55.0
        dd = 80.0 if t < 30 else 40.0
        rows[d] = [("INE0000000A1", "A", a, a - 1 if t else a), ("INE0000000B1", "B", b, b + 1 if t else b),
                   ("INE0000000C1", "C", c, 50.0 if t else c), ("INE0000000D1", "D", dd, 40.0 if t == 30 else (80.0 if t < 30 else 40.0)), ("INE0000000E1", "E", 10.0, 10.0)]
        _bhav(root, d, rows[d])
    _bhav(root, DAY + timedelta(days=4), [("INE0000000A1", "A", 1.0, 99.0)])                  # a later file must not be read
    r = breadth.breadth(root, DAY)
    assert (r["traded"], r["advancers"], r["decliners"], r["unchanged"]) == (5, 2, 1, 2)
    assert r["net_advances"] == 1 and r["advance_decline_ratio"] == 2.0
    assert r["above_sma20"] == {"eligible": 5, "above": 2, "pct": 40.0}                       # A and C; D (flat since its split) and E are level with their average
    assert r["above_sma50"] == {"eligible": 4, "above": 2, "pct": 50.0}                       # D's split is inside the 50 sessions: left out, and counted
    assert r["new_high_50d"] == 2 and r["new_low_50d"] == 1 and r["excluded_for_a_price_break"] == 1
    assert "no NSE daily file" in breadth.breadth(root, DAY - timedelta(days=1) if not IN.is_session(DAY - timedelta(days=1)) else date(2026, 10, 24))["note"]
    assert "no daily-file source" in breadth.breadth(root, DAY, "US")["note"]


# --- the tools, their call ids and the citation check -----------------------------------------------------------------------------------------

def test_every_tool_is_a_read_tool_that_works_without_arguments_or_says_what_is_missing(rt, con):
    for name in explain.TOOL_NAMES:
        assert tl.TOOLS[name].kind == "read" and "market" in tl.TOOLS[name].params
    ctx = _ctx(rt)
    for name in explain.TOOL_NAMES:
        text, err = tl.run(ctx, name, {} if name == "breadth" else {"symbol": "AAA"})
        assert not err, (name, text)
        out = json.loads(text)
        assert out["call_ref"] is not None
    text, err = tl.run(ctx, "trajectory", {"symbol": "AAA", "market": "XX"})
    assert not err and "unknown market" in json.loads(text)["note"]


def test_the_tool_reports_its_own_journal_id_and_the_existing_guard_drops_an_uncited_number(rt, con):
    _put_bars(con, _minute_frame())
    ctx = _ctx(rt)
    text, err = tl.run(ctx, "trajectory", {"symbol": "AAA", "date": str(DAY)})
    out = json.loads(text)
    assert not err and out["n_bursts"] == 2 and out["time_of_high"] == "14:00"
    row = con.execute("SELECT tool, status FROM hq_tool_calls WHERE call_no=?", [out["call_ref"]]).fetchone()
    assert row == ("trajectory", "ran")                                                        # the id in the result IS the journal id
    t2, _ = tl.run(ctx, "trajectory", {"symbol": "AAA", "date": str(DAY), "k": 6})
    assert json.loads(t2)["call_ref"] == out["call_ref"] + 1
    good = "The high came at 14:00 and the day closed at 102.5."
    bad = "The stock gained 7.77 percent by noon."
    kept = tl._checked(ctx, good + " " + bad)
    assert good in kept and "7.77" not in kept and ctx.problems                                # the loop's own guard: numbers must be in something read this pass


def test_the_tools_use_minute_bars_of_the_day_asked_and_the_index(rt, con):
    _put_bars(con, _minute_frame())
    _put_bars(con, _minute_frame(), key="INDEX:NIFTY 50")
    ctx = _ctx(rt)
    out = json.loads(tl.run(ctx, "trajectory", {"symbol": "NIFTY 50", "date": str(DAY)})[0])
    assert out["n_bars"] == 375 and out["prior_close"] is None and "no prior close" in out["note_prior_close"]      # no yesterday's bars recorded: not guessed
    empty = json.loads(tl.run(ctx, "trajectory", {"symbol": "AAA", "date": "2026-10-22"})[0])
    assert empty["n_bars"] == 0 and "nothing is inferred" in empty["note"]
    future = json.loads(tl.run(ctx, "trajectory", {"symbol": "AAA", "date": "2027-01-04"})[0])
    assert "future" in future["note"]


def test_align_events_tool(rt, con, root):
    _announcements(root, [("500001", "Outcome of board meeting", "Board Meeting", "2026-10-23 10:05:30")])
    _put_bars(con, _minute_frame())
    out = json.loads(tl.run(_ctx(rt), "align_events", {"symbol": "AAA", "date": str(DAY)})[0])
    assert out["n_bursts"] == 2 and out["n_unexplained"] == 1 and out["unexplained_at"] == ["14:00"]
    assert out["events"][0]["headline"] == "Outcome of board meeting"
    assert "dissemination" in out["event_times"]
    nobars = json.loads(tl.run(_ctx(rt), "align_events", {"symbol": "AAA", "date": "2026-10-22"})[0])
    assert nobars["n_bursts"] == 0 and "no bursts to line up" in nobars["note"]


RESULTS = {7: json.dumps({"call_ref": 7, "day_pct": 3.54, "time_of_high": "14:00", "n_bursts": 2}), 8: json.dumps({"call_ref": 8, "advancers": 1234, "decliners": 800})}


def test_the_citation_check_rejects_an_uncited_or_wrong_number():
    text = ("The stock rose 3.54% on the day [call 7].\n"
            "It rose 3.55% on the day [call 7].\n"                                  # wrong digits
            "It rose 3.54% on the day.\n"                                           # no call cited
            "It rose 3.54% [call 99].\n"                                            # a call that was not made
            "1,234 names rose [call 7].\n"                                          # real figure, but from the other call
            "1,234 names rose and 800 fell [call 8].\n"                             # right call, thousands comma
            "That is a strong day.")                                                # no figure: needs no citation
    clean, rej, used = explain.check_citations(text, {k: v for k, v in RESULTS.items()})
    assert clean.split("\n") == ["The stock rose 3.54% on the day [call 7].", "1,234 names rose and 800 fell [call 8].", "That is a strong day."]
    assert len(rej) == 4 and used == [7, 8]
    assert "no call id" in rej[1]["why"] and "not made" in rej[2]["why"]


def test_explain_move_with_a_model_that_cites_correctly_and_one_that_does_not(rt, con, root):
    _universe(root)
    _put_bars(con, _minute_frame())
    _announcements(root, [("500001", "Outcome of board meeting", "Board Meeting", "2026-10-23 10:05:30")])

    def honest(system, user):
        cid = int(__import__("re").search(r"\[call (\d+)\] trajectory", user).group(1))
        high = json.loads(user.split(f"[call {cid}] trajectory: ")[1].split("\n")[0])["time_of_high"]
        return f"The high of the day came at {high} [call {cid}].\nIt was a busy day."

    ok = explain.explain_move(rt, "IN", "AAA", DAY, NOW, chat=honest)
    assert ok["source"] == "model" and ok["rejected"] == [] and ok["text"].startswith("The high of the day came at 14:00") and ok["call_ids"]
    assert ok["source_guard_dropped"] == 0

    def inventor(system, user):
        return "The stock gained 12.34% on heavy volume [call 1]."

    bad = explain.explain_move(rt, "IN", "AAA", DAY, NOW, chat=inventor)
    assert bad["source"] == "code" and bad["rejected"] and "12.34" not in bad["text"]

    assert not [r for r in bad["rejected"] if r.get("stage")]                              # the code paragraph itself meets the citation rule
    assert bad["text"].count("[call ") >= 4 and bad["source_guard_dropped"] == 0            # the code paragraph cites every figure and passes the loop's own guard
    assert "market part" in bad["text"].lower() and "no filing or news" in bad["text"]
    assert set(bad["calls"]) == set(explain.TOOL_NAMES) and all(bad["calls"].values())

    def away(system, user):
        raise ConnectionError("Ollama is not reachable")

    gone = explain.explain_move(rt, "IN", "AAA", DAY, NOW, chat=away)
    assert gone["source"] == "code" and "ConnectionError" in gone["model_error"] and gone["rejected"] == []


def test_the_code_paragraph_says_when_bars_are_missing(rt, con, root):
    _universe(root)
    res = explain.explain_move(rt, "IN", "AAA", DAY, NOW, chat=lambda s, u: "")
    assert res["source"] == "code" and "No minute bars were recorded" in res["text"] and res["rejected"] == []


def test_biggest_moves_ranks_held_and_watched_names_by_size(root, con, monkeypatch):
    other = "INE111A01012"
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, 'BBB', 'BBB', 'synthetic', now())", [other])
    third = "INE222A01013"
    _bhav(root, DAY, [(AAA, "AAA", 102.0, 100.0), (other, "BBB", 91.0, 100.0), (third, "CCC", 150.0, 100.0)])         # CCC is not watched
    from pflab.service import tasks_s79_bars as tb
    monkeypatch.setattr(tb, "wanted", lambda c, m, d: {AAA: "AAA", other: "BBB", "INDEX:NIFTY 50": "NIFTY 50"})
    out = explain.biggest_moves(con, "IN", DAY, 5, root=root)
    assert [(r["symbol"], r["move_pct"]) for r in out] == [("BBB", -9.0), ("AAA", 2.0)]
    assert explain.biggest_moves(con, "IN", DAY, 1, root=root)[0]["symbol"] == "BBB" and explain.biggest_moves(con, "US", DAY, 3, root=root) == []


# --- the minute-bar job ---------------------------------------------------------------------------------------------------------------------

IST = timezone(timedelta(hours=5, minutes=30))


class FakeKite:
    def __init__(self, drop=(), fail=()):
        self.calls, self.drop, self.fail = [], set(drop), set(fail)

    def instruments(self, exch):
        return [{"segment": "NSE", "tradingsymbol": "AAA", "instrument_token": 11}, {"segment": "NSE", "tradingsymbol": "FAIL", "instrument_token": 13},
                {"segment": "INDICES", "tradingsymbol": "NIFTY 50", "instrument_token": 12}]

    def historical_data(self, token, frm, to, interval):
        self.calls.append((token, frm.date(), interval))
        if token in self.fail:
            raise RuntimeError("Kite said no")
        assert interval == "minute"
        ts = pd.date_range(datetime.combine(frm.date(), time(9, 15)), periods=375, freq="min")
        return [{"date": t.to_pydatetime().replace(tzinfo=IST), "open": 100.0 + k * 0.01, "high": 101.0, "low": 99.0, "close": 100.0 + k * 0.01, "volume": 10}
                for k, t in enumerate(ts) if k not in self.drop]


def test_the_job_says_kite_logged_out_and_never_fails(con, tmp_path, root, monkeypatch):
    from pflab.app import settings
    from pflab.service import tasks_s79_bars as tb
    from pflab.service.jobs import Ctx
    monkeypatch.setattr(settings, "ability", lambda *a, **k: True)
    ctx = Ctx(con, NOW, tmp_path / "pm", root, tmp_path / "repo", secrets=None)
    assert tb._bars_1m(ctx) == {"skipped": "kite logged out"}
    assert con.execute("SELECT count(*) FROM bars_1m").fetchone()[0] == 0


def test_the_job_records_bars_states_gaps_and_is_idempotent(con, tmp_path, root, monkeypatch):
    from pflab.app import settings
    from pflab.service import tasks_s79_bars as tb
    from pflab.service.jobs import Ctx
    monkeypatch.setattr(settings, "ability", lambda *a, **k: True)
    monkeypatch.setattr(tb, "wanted", lambda c, m, d: {AAA: "AAA", "INDEX:NIFTY 50": "NIFTY 50", "INE333A01014": "NOPE", "INE444A01015": "FAIL"})
    kite = FakeKite(drop=range(100, 105), fail={13})
    ctx = Ctx(con, NOW, tmp_path / "pm", root, tmp_path / "repo", secrets=None)
    out = tb._bars_1m(ctx, kite=kite, sleep=lambda s: None)
    r = out["IN"]
    assert r["days"] == ["2026-10-21", "2026-10-22", "2026-10-23"] and r["partial"] == 6 and r["no_token"] == 3 and r["errors"] == 3 and r["full"] == 0
    assert out["US"] == {"skipped": "no minute-bar source for this market yet"}
    n = con.execute("SELECT count(*) FROM bars_1m WHERE isin=? AND CAST(ts AS DATE)=?", [AAA, DAY]).fetchone()[0]
    assert n == 370                                                                            # 375 minus the 5 the feed did not give: not filled
    run = con.execute("SELECT n_bars, expected, status, note FROM bars_1m_runs WHERE isin=? AND day=?", [AAA, DAY]).fetchone()
    assert run[:3] == (370, 375, "partial") and "5 of 375 minutes missing" in run[3]
    assert con.execute("SELECT status FROM bars_1m_runs WHERE isin='INE444A01015' AND day=?", [DAY]).fetchone()[0] == "error"
    assert con.execute("SELECT status FROM bars_1m_runs WHERE isin='INE333A01014' AND day=?", [DAY]).fetchone()[0] == "no_token"
    assert con.execute("SELECT min(ts), max(ts) FROM bars_1m WHERE isin=? AND CAST(ts AS DATE)=?", [AAA, DAY]).fetchone() == (pd.Timestamp("2026-10-23 09:15").to_pydatetime(), pd.Timestamp("2026-10-23 15:29").to_pydatetime())
    before = con.execute("SELECT count(*) FROM bars_1m").fetchone()[0]
    tb._bars_1m(ctx, kite=kite, sleep=lambda s: None)                                          # run again: the same rows, no duplicates, no change
    assert con.execute("SELECT count(*) FROM bars_1m").fetchone()[0] == before
    # a full day is not asked for again
    full = FakeKite()
    tb.record(con, full, "IN", [DAY - timedelta(days=10)], {AAA: "AAA"}, NOW, sleep=lambda s: None)
    assert len(full.calls) == 1
    tb.record(con, full, "IN", [DAY - timedelta(days=10)], {AAA: "AAA"}, NOW, sleep=lambda s: None)
    assert len(full.calls) == 1 and con.execute("SELECT status FROM bars_1m_runs WHERE isin=? AND day=?", [AAA, DAY - timedelta(days=10)]).fetchone()[0] == "full"


def test_the_job_is_registered_and_the_tables_exist(con):
    from pflab.service import jobs
    from pflab.service import tasks  # noqa: F401  (loads the S79 job modules)
    assert "bars_1m" in jobs.REGISTRY and jobs.REGISTRY["bars_1m"].redo_fn is not None
    cols = [r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name='bars_1m' ORDER BY ordinal_position").fetchall()]
    assert cols == ["market", "isin", "ts", "open", "high", "low", "close", "volume"]
    with pytest.raises(Exception):                                                              # the primary key: one bar per market, name and minute
        con.execute("INSERT INTO bars_1m VALUES ('IN','X','2026-10-23 09:15:00',1,1,1,1,1)")
        con.execute("INSERT INTO bars_1m VALUES ('IN','X','2026-10-23 09:15:00',1,1,1,1,1)")
