"""S79 item 12: bull-vs-bear debate on the local model (fake client), the guard, the disagreements only, the scored bear warnings."""
import json
from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from pflab import markets
from pflab.agents import debate as db
from pflab.llm.client import OllamaError, Reply
from pflab.pm import store

NOW = datetime(2026, 10, 23, 17, 0)           # a Friday
EV = {"calc.ret_20d": ("return over the last 20 sessions, %", 8.4), "calc.rsi14": ("14-session RSI", 72.1), "calc.below_high": ("% below the 252-session high", -3.2),
      "calc.w20": ("window length", 20)}
BULL_OK = "The 20 session return of 8.4% shows strength [F:calc.ret_20d]. The price sits only 3.2% under its high [F:calc.below_high]."
BEAR_OK = "The RSI of 72.1 says the move is stretched [F:calc.rsi14]. The 20 session return of 8.4% shows strength [F:calc.ret_20d]."
PAIR = {"disagreements": [{"topic": "is the move healthy", "bull": 1, "bear": 1}]}


class FakeChat:
    """Scripted local model: answers by who is asked (the system prompt) and by the schema asked for."""
    def __init__(self, bull=BULL_OK, bear=BEAR_OK, pair=PAIR, warn=None, down=False, stance=None):
        self.bull, self.bear, self.pair, self.down = bull, bear, pair, down
        self.stance = stance or {}                       # id -> stance; default: every bull sentence favourable, every bear sentence unfavourable
        self.warn = warn or {"warn": True, "kind": "fall", "horizon_sessions": 5, "threshold_pct": 3, "because": ["calc.rsi14"]}
        self.calls = []

    def __call__(self, model, messages, *, fmt=None, **kw):
        self.calls.append((messages[0]["content"][:30], messages[1]["content"], fmt is not None))
        if self.down:
            raise OllamaError("Ollama is not reachable at http://localhost:11434: refused")
        sys_ = messages[0]["content"]
        if fmt is None:
            seq = self.bull if "BULL analyst" in sys_ else self.bear
            text = seq.pop(0) if isinstance(seq, list) else seq
        elif "STANCE" in sys_:
            ids = [ln.split(".")[0] for ln in messages[1]["content"].splitlines() if ln[:1] in "BR" and "." in ln[:4]]
            text = json.dumps({"stances": [{"id": i, "stance": self.stance.get(i, "favourable" if i[0] == "B" else "unfavourable")} for i in ids]})
        elif "CONTRADICT" in sys_:
            seq = self.pair
            text = json.dumps(seq.pop(0) if isinstance(seq, list) else seq)
        else:
            text = json.dumps(self.warn)
        return Reply(text, model, "d", 10, 10, 0.1)


@pytest.fixture
def rt(tmp_path):
    import duckdb
    con = duckdb.connect(str(tmp_path / "l.duckdb"))
    # the schema up to 60 plus this item's own versions: other items' migrations (reserved ranges) are not this test's business
    store.migrate(con, [m for m in store.MIGRATIONS if m[0] <= 60 or m[0] in (75, 76)])
    return SimpleNamespace(cursor=lambda: con.cursor(), data_root=tmp_path, con=con)


def _series(end: date, n: int, f) -> pd.Series:
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    return pd.Series([f(i) for i in range(n)], index=idx, dtype=float)


class MutableFeed:
    def __init__(self, s, b):
        self.s, self.b = s, b

    def feed(self):
        return db.Feed(lambda isin, asof: self.s[self.s.index <= pd.Timestamp(asof)], lambda asof: self.b[self.b.index <= pd.Timestamp(asof)])


def test_migrations_create_both_tables(rt):
    cols = {r[0] for r in rt.con.execute("DESCRIBE bear_warnings_s79").fetchall()}
    assert {"warning_id", "debate_id", "market", "symbol", "claim", "direction", "horizon_sessions", "benchmark", "made_at", "resolved_at", "outcome", "hit"} <= cols
    cols = {r[0] for r in rt.con.execute("DESCRIBE debates_s79").fetchall()}
    assert {"debate_id", "market", "subject", "created_at", "bull_json", "bear_json", "disagreements_json", "evidence_ids", "status"} <= cols


def test_guard_drops_an_argument_with_an_uncited_number(rt):
    bad = "The return of 12.5% is far too strong [F:calc.ret_20d]. The price sits only 3.2% under its high [F:calc.below_high]."
    chat = FakeChat(bull=bad, bear=BEAR_OK)
    r = db.debate(rt, "IN", "ABC", EV, NOW, chat=chat)
    row = rt.con.execute("SELECT bull_json, bear_json, status FROM debates_s79").fetchone()
    bull, bear = json.loads(row[0]), json.loads(row[1])
    assert bull["text"] is None and bull["status"] == db.NO_ARGUMENT and bull["attempts"] == 2          # asked again once with the violations named
    assert any("12.5" in v[1] for v in bull["violations"])
    assert bear["text"] == BEAR_OK
    assert r["status"] == "one_side_missing" and r["disagreements"] == []                              # nothing to compare


def test_a_draft_fixed_on_the_second_try_is_kept(rt):
    bad = "The return of 12.5% is far too strong [F:calc.ret_20d]."
    chat = FakeChat(bull=[bad, BULL_OK])
    db.debate(rt, "IN", "ABC", EV, NOW, chat=chat)
    bull = json.loads(rt.con.execute("SELECT bull_json FROM debates_s79").fetchone()[0])
    assert bull["text"] == BULL_OK and bull["attempts"] == 2
    assert any("rejected by the checker" in c[1] for c in chat.calls)


def test_a_text_without_any_citation_is_not_an_argument(rt):
    chat = FakeChat(bull="Momentum is clearly healthy here. [inf] Buyers keep stepping in on every dip. [inf]")
    db.debate(rt, "IN", "ABC", EV, NOW, chat=chat)
    assert json.loads(rt.con.execute("SELECT bull_json FROM debates_s79").fetchone()[0])["text"] is None


def test_both_sides_get_the_same_evidence_block(rt):
    chat = FakeChat()
    db.debate(rt, "IN", "ABC", EV, NOW, chat=chat)
    blocks = [c[1].split("EVIDENCE BLOCK")[1] for c in chat.calls[:2]]
    assert blocks[0] == blocks[1] and "[F:calc.rsi14]" in blocks[0]


def test_only_disagreements_are_returned_and_agreement_is_not(rt):
    r = db.debate(rt, "IN", "ABC", EV, NOW, chat=FakeChat(), case_id=7)
    assert r["status"] == "done" and len(r["disagreements"]) == 1
    d = r["disagreements"][0]
    assert d["bull_says"].startswith("The 20 session return") and d["bear_says"].startswith("The RSI of 72.1")
    assert d["bull_ids"] == ["calc.ret_20d"] and d["bear_ids"] == ["calc.rsi14"]
    assert "calc.below_high" not in r["evidence_used"]                       # the bull's other sentence was not a disagreement
    txt = db.disagreements_for_reviewer(rt.con, 7)
    assert "RSI of 72.1" in txt and "calc.rsi14" in txt and "14-session RSI = 72.1" in txt
    assert "only 3.2% under its high" not in txt                          # agreement/other points are not sent
    assert db.disagreements_for_reviewer(rt.con, "abc") != "" and db.disagreements_for_reviewer(rt.con, "ZZZ") == ""


def test_a_pair_that_reads_the_same_way_is_not_a_disagreement(rt):
    chat = FakeChat(stance={"R1": "favourable"})          # the model paired B1 with R1, but the two sentences both argue in favour
    r = db.debate(rt, "IN", "ABC", EV, NOW, chat=chat)
    assert r["status"] == "done" and r["disagreements"] == []


def test_agreement_gives_an_empty_handoff(rt):
    r = db.debate(rt, "IN", "ABC", EV, NOW, chat=FakeChat(pair={"disagreements": []}), case_id=3)
    assert r["status"] == "done" and r["disagreements"] == []
    assert db.disagreements_for_reviewer(rt.con, 3) == ""


def test_a_bad_pick_is_asked_again_then_the_extraction_fails_cleanly(rt):
    bad = {"disagreements": [{"topic": "x", "bull": 9, "bear": 1}]}
    chat = FakeChat(pair=[bad, bad])
    r = db.debate(rt, "IN", "ABC", EV, NOW, chat=chat)
    assert r["status"] == "extract_failed" and r["disagreements"] == [] and "bull must be" in r["extract_error"]
    ok = FakeChat(pair=[{"disagreements": [{"topic": "has 5 digits", "bull": 1, "bear": 1}], }, PAIR])
    r = db.debate(rt, "IN", "ABC", EV, NOW, chat=ok)
    assert r["status"] == "done" and len(r["disagreements"]) == 1                # the first try had a digit in the topic; the second was valid


def test_model_down_returns_skipped_and_writes_nothing(rt):
    r = db.debate(rt, "IN", "ABC", EV, NOW, chat=FakeChat(down=True))
    assert r == {"skipped": "local model unavailable"}
    assert rt.con.execute("SELECT count(*) FROM debates_s79").fetchone()[0] == 0


def test_tool_does_not_raise_when_the_model_is_down_or_args_are_missing(rt, monkeypatch):
    from pflab.hq import tools  # noqa: F401  (loads the S79 tool modules in the registry's own order)
    from pflab.hq.tools_s79 import t_debate
    s = _series(date(2026, 10, 23), 300, lambda i: 100 + i * 0.1)
    feed = MutableFeed(s, s).feed()
    monkeypatch.setattr(db, "default_feed", lambda rt_, m="IN": feed)
    monkeypatch.setattr(db, "_chat_default", lambda: FakeChat(down=True))
    ctx = SimpleNamespace(rt=rt, now=NOW, syms={"ABC": "INE000000001"}, case_ids=[], con=rt.con)
    tool = {t.name: t for t in t_debate.TOOLS}
    assert tool["debate"].kind == "read" and tool["bear_scorecard"].kind == "read"
    assert tool["debate"].fn(ctx, {"market": "IN", "symbol": "ABC"}) == {"skipped": "local model unavailable"}
    assert "skipped" in tool["debate"].fn(ctx, {})
    assert "skipped" in tool["debate"].fn(ctx, {"symbol": "NOPE"})
    assert tool["bear_scorecard"].fn(ctx, {})["resolved"] == 0
    monkeypatch.setattr(db, "_chat_default", lambda: FakeChat())
    out = tool["debate"].fn(ctx, {"symbol": "ABC", "topic": "buy more?"})
    assert out["status"] == "done" or out["status"] in ("one_side_missing", "no_guarded_argument", "extract_failed")


def test_build_evidence_is_point_in_time_and_made_by_code():
    s = _series(date(2026, 10, 23), 300, lambda i: 100 + i * 0.1)
    s2 = s.copy()
    s2.iloc[-1] = 9999.0                                      # a later row is never read when asof is earlier
    f = MutableFeed(s2, s2).feed()
    ev, why = db.build_evidence(f, "X", "ABC", date(2026, 10, 22))
    assert why is None and ev["calc.close_date"][1] == date(2026, 10, 22) and ev["calc.close"][1] < 200
    ev2, why2 = db.build_evidence(MutableFeed(s.iloc[:30], s.iloc[:30]).feed(), "X", "ABC", date(2026, 10, 23))
    assert ev2 == {} and "30" in why2


def _warn(rt, feed, kind, h, y=3, now=NOW):
    warn = {"warn": True, "kind": kind, "horizon_sessions": h, "threshold_pct": y, "because": ["calc.rsi14"]}
    r = db.debate(rt, "IN", "ABC", EV, now, isin="INE000000001", chat=FakeChat(warn=warn), feed=feed)
    return r["bear_warning"]


def test_warning_is_parsed_and_resolved_across_a_weekend(rt):
    mk = markets.get("IN")
    fri = date(2026, 10, 23)
    assert mk.is_session(fri) and not mk.is_session(date(2026, 10, 24))
    stock = _series(fri, 400, lambda i: 100.0 + 0.01 * i)
    bench = _series(fri, 400, lambda i: 1000.0 + 0.1 * i)
    stock.iloc[-1], bench.iloc[-1] = 100.0, 1000.0              # the reference closes on the Friday
    holder = MutableFeed(stock.copy(), bench.copy())
    w1 = _warn(rt, holder.feed(), "fall", 5, 3)
    w2 = _warn(rt, holder.feed(), "underperform", 5)
    assert w1["due_date"] == "2026-10-30" and w1["horizon_sessions"] == 5          # five SESSIONS ahead (calendar days would give Wednesday 28th)
    row = rt.con.execute("SELECT direction, benchmark, threshold_pct, ref_date, ref_close, bench_ref FROM bear_warnings_s79 WHERE warning_id=?", [w1["warning_id"]]).fetchone()
    assert row[0] == "fall" and row[1] == "NIFTY 500" and row[2] == 3.0 and row[3] == fri and row[4] == 100.0 and row[5] == 1000.0
    assert w1["claim"].startswith("ABC closes more than 3% below its close of 2026-10-23")
    feed_for = lambda m: holder.feed()
    # the weekend: nothing has happened, and Monday's close alone does not reach the target
    assert db.resolve_open(rt.con, datetime(2026, 10, 24, 12), feed_for)["waiting"] == 2
    new_idx = pd.bdate_range(date(2026, 10, 26), date(2026, 10, 30))
    holder.s = pd.concat([holder.s, pd.Series([99.0, 97.5, 98.0, 98.5, 99.2], index=new_idx)])           # dips 2.5% at worst: not more than 3%
    holder.b = pd.concat([holder.b, pd.Series([1005.0, 1010.0, 1012.0, 1015.0, 1020.0], index=new_idx)])  # benchmark up 2%, stock down 0.8%
    assert db.resolve_open(rt.con, datetime(2026, 10, 29, 12), feed_for)["waiting"] == 2           # the target session (Fri 30th) has not closed yet
    out = db.resolve_open(rt.con, datetime(2026, 10, 31, 12), feed_for)
    assert out["resolved"] == 2 and out["hits"] == 1
    r1 = rt.con.execute("SELECT outcome, hit, detail FROM bear_warnings_s79 WHERE warning_id=?", [w1["warning_id"]]).fetchone()
    r2 = rt.con.execute("SELECT outcome, hit, detail FROM bear_warnings_s79 WHERE warning_id=?", [w2["warning_id"]]).fetchone()
    assert r1[0] == "miss" and r1[1] is False and "-2.50%" in r1[2]
    assert r2[0] == "hit" and r2[1] is True and "benchmark +2.00%" in r2[2]
    assert db.resolve_open(rt.con, datetime(2026, 11, 1, 12), feed_for) == {"resolved": 0, "hits": 0, "void": 0, "waiting": 0}      # nothing is resolved twice


def test_a_fall_deeper_than_the_threshold_is_a_hit_even_if_it_recovers(rt):
    fri = date(2026, 10, 23)
    stock = _series(fri, 400, lambda i: 100.0)
    holder = MutableFeed(stock, stock.copy())
    w = _warn(rt, holder.feed(), "fall", 5, 5)
    idx = pd.bdate_range(date(2026, 10, 26), date(2026, 10, 30))
    holder.s = pd.concat([holder.s, pd.Series([99.0, 93.0, 97.0, 99.0, 101.0], index=idx)])
    db.resolve_open(rt.con, datetime(2026, 10, 31), lambda m: holder.feed())
    assert rt.con.execute("SELECT outcome FROM bear_warnings_s79 WHERE warning_id=?", [w["warning_id"]]).fetchone()[0] == "hit"


def test_a_warning_with_no_close_near_its_target_goes_void_not_guessed(rt):
    fri = date(2026, 10, 23)
    stock = _series(fri, 400, lambda i: 100.0)
    holder = MutableFeed(stock, stock.copy())
    w = _warn(rt, holder.feed(), "fall", 5, 3)
    assert db.resolve_open(rt.con, datetime(2026, 11, 3), lambda m: holder.feed())["waiting"] == 1
    assert db.resolve_open(rt.con, datetime(2026, 11, 12), lambda m: holder.feed())["void"] == 1
    assert rt.con.execute("SELECT outcome, hit FROM bear_warnings_s79 WHERE warning_id=?", [w["warning_id"]]).fetchone() == ("void", None)


def test_base_rate_is_the_stocks_own_history_and_needs_enough_windows():
    rng = np.random.default_rng(1)
    s = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, 700)), index=pd.bdate_range(end="2026-10-23", periods=700))
    p = db.base_rate("fall", 5, 3.0, s, s)
    assert 0.0 < p < 0.5
    assert db.base_rate("fall", 5, 3.0, s.iloc[-200:], s) is None
    b = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, 700)), index=s.index)
    assert 0.3 < db.base_rate("underperform", 5, 0.0, s, b) < 0.7


def _rows(con, n, hits, base=0.3, market="IN"):
    for i in range(n):
        h = i < hits
        con.execute("INSERT INTO bear_warnings_s79 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [1000 + i, 1, market, "ABC", "INE1", "c", "fall", 5, "NIFTY 500", 3.0, date(2026, 1, 5), 100.0, None, base, NOW, date(2026, 1, 12), NOW, "hit" if h else "miss", h, ""])


def test_scorecard_small_sample_gives_counts_and_no_conclusion(rt):
    _rows(rt.con, 19, 19)
    sc = db.bear_scorecard(rt.con, "IN")
    assert sc["resolved"] == 19 and sc["hits"] == 19 and sc["conclusion"] is None and "no conclusion" in sc["note"] and "hit_rate" not in sc


def test_scorecard_at_twenty_compares_with_the_base_rate(rt):
    _rows(rt.con, 40, 24, base=0.3)
    sc = db.bear_scorecard(rt.con, "IN")
    assert sc["resolved"] == 40 and sc["hit_rate"] == 0.6 and sc["base_rate"] == 0.3 and sc["z"] > 1.96 and "more often than chance" in sc["conclusion"]
    assert db.bear_scorecard(rt.con, "US")["resolved"] == 0                      # markets are kept apart
    rt.con.execute("DELETE FROM bear_warnings_s79")
    _rows(rt.con, 40, 12, base=0.3)
    assert db.bear_scorecard(rt.con, "IN")["conclusion"] == "no difference from chance shown"


def test_tools_are_registered_and_the_job_exists():
    from pflab.hq import tools
    from pflab.service import jobs, tasks   # noqa: F401  (importing tasks loads the S79 job modules)
    names = set(tools.TOOLS)
    assert {"debate", "bear_scorecard"} <= names
    assert "bear_resolve" in jobs.REGISTRY
