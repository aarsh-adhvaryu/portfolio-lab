"""S84 integration: the REAL modules of the thinking loop together (watch -> wire -> session -> odds -> rule -> act -> score -> calibrate), a synthetic store and synthetic bars, a SCRIPTED model
injected through the one door (`gateway.set_client`). No paid call. The modules were built in parallel against a written contract with fakes for each other; this file proves they meet.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from pflab import think
from pflab.agents import analyst as an
from pflab.core import exits
from pflab.llm import gateway
from pflab.paper import book
from pflab.think import cases, odds, reserve, rule, score, session, watch, wire

from tests.test_s80_core import AAA, BBB, GLD, DAYS, NOW, con  # noqa: F401  (the fixture: the S80 paper book on synthetic prices)

DAY = DAYS[-1]                                        # 2026-10-30, a Friday: the last stored close
CLOSE_AT = datetime.combine(DAY, datetime.min.time()) + timedelta(hours=16)


# --- the scripted model, injected through the door -------------------------------------------------------------------------------------------------------------------------------

def _cfg():
    return {"model": "claude-opus-5-5", "cap": 2500.0, "ask_above": 1000.0, "usd_inr": 90.0, "adopted": True, "policy": {}, "acceptance": {}, "paper": {}, "tijori_to_analyst": True, "counted_since": None}


class Client:
    """A scripted vendor client: `count_tokens`, and the beta create that the door sends to. What it answers is decided by what was asked: a request with tools is the Sonnet READ, a request with the answer's
    JSON schema is the structured answer, a request with the checker's schema is the big-trade check. `answer` is a dict (or a callable of the request) for the structured call."""

    def __init__(self, answer=None, *, read_tools=(), check="pass", boom=None):
        self.answer, self.read_tools, self.check, self.boom = answer, list(read_tools), check, boom
        self.sent, self.counted = [], []
        self.messages = SimpleNamespace(count_tokens=self._count, create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _count(self, **k):
        self.counted.append(k)
        return SimpleNamespace(input_tokens=3000)

    def _msg(self, blocks, model, stop="end_turn"):
        usage = SimpleNamespace(input_tokens=2000, output_tokens=400, cache_read_input_tokens=100, cache_creation_input_tokens=0)
        return SimpleNamespace(content=blocks, stop_reason=stop, model=model, usage=usage)

    def _create(self, **p):
        self.sent.append(p)
        if self.boom is not None:
            raise self.boom
        fmt = ((p.get("output_config") or {}).get("format") or {}).get("schema") or {}
        props = set((fmt.get("properties") or {}).keys())
        text = lambda t: SimpleNamespace(type="text", text=t)            # noqa: E731
        if "verdict" in props:
            return self._msg([text(json.dumps({"verdict": self.check, "reason": "a stale price" if self.check == "veto" else "fine"}))], p["model"])
        if "choices" in props:
            a = self.answer(p) if callable(self.answer) else self.answer
            return self._msg([text(json.dumps(a))], p["model"])
        if p.get("tools") and self.read_tools and not any(isinstance(m.get("content"), list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"]) for m in p["messages"]):
            blocks = [SimpleNamespace(type="tool_use", id=f"t{i}", name=n, input=a) for i, (n, a) in enumerate(self.read_tools)]
            return self._msg(blocks, p["model"], "tool_use")
        return self._msg([text("A board investigation was reported; the name has fallen hard and the cause is governance.")], p["model"])

    def roles(self):
        return [p["model"] for p in self.sent]


def answer(sym="BBB", option="hold", klass="damage", pending="the board's decision", worst="unlikely", likely="likely", best="unlikely", base="20", **kw):
    a = {"happened": "A board investigation of the chief executive was reported.", "sources": ["press reports"], "class": klass, "known": "", "pending": pending, "pending_date": "", "other_names": [],
         "choices": [{"symbol": sym, "option": option, "reason": "the thesis is in doubt"}],
         "likelihood": {"worst": worst, "likely": likely, "best": best, "base_rate_set": base, "reason": "own range"}}
    a.update(kw)
    return a


@pytest.fixture(autouse=True)
def _world(monkeypatch, tmp_path):
    """No real data, no real cap: the data dir is a scratch folder, the analyst's config is his cap stated, the watch has no index file."""
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(an, "config", lambda path=None: _cfg())
    monkeypatch.setattr(watch, "_index", lambda market, root=None: None)
    monkeypatch.setattr(wire, "_market_on", lambda m: m == "IN")
    yield
    gateway.set_client(None)
    session.DEPS.clear()


def script(client):
    gateway.set_client(client)
    return client


# --- the market ------------------------------------------------------------------------------------------------------------------------------------------------------------

def fall(con, isin, pct, day=DAY):
    """The close of `day` is `pct` under the close before it."""
    prev = con.execute("SELECT close FROM prices WHERE isin=? AND date<? ORDER BY date DESC LIMIT 1", [isin, day]).fetchone()[0]
    con.execute("UPDATE prices SET close=? WHERE isin=? AND date=?", [prev * (1.0 + pct), isin, day])


def extend(con, n, isin_drift=None):
    """`n` more sessions after DAY for every name (a flat tape with the small wobble the fixture uses), -> the list of days added."""
    days = [d.date() for d in pd.bdate_range(DAY + timedelta(days=1), periods=n)]
    last = {i: float(con.execute("SELECT close FROM prices WHERE isin=? AND date=?", [i, DAY]).fetchone()[0]) for i in (AAA, BBB, GLD)}
    for k, d in enumerate(days):
        for i in (AAA, BBB, GLD):
            last[i] *= (1.0 + (isin_drift or {}).get(i, 0.0))
            con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [i, d, last[i] * (1.0 + (0.002 if k % 2 else -0.002))])
    return days


def orders(con, side=None):
    return con.execute("SELECT isin, side, status, note FROM paper_orders" + (" WHERE side=?" if side else ""), [side] if side else []).fetchall()


# --- the first scenario ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_held_name_falls_ten_percent_the_loop_notices_thinks_decides_sells_and_later_scores_both_tracks(con, tmp_path):
    fall(con, BBB, -0.10)
    cl = script(Client(answer(option="hold", klass="damage"), read_tools=[("recall", {"symbol": "BBB"}), ("base_rates", {"kind": "move_1d"}), ("outcome_table", {"symbol": "BBB", "option": "sell"})]))
    r = wire.sweep(con, CLOSE_AT + timedelta(minutes=30), tmp_path / "data", only_market="IN")
    assert r["failed"] == [], r
    assert r["sessions"] == {"IN": [f"{DAY}:close"]}
    assert len(r["cases_opened"]) >= 1
    cid = next(c for c in r["cases_opened"] if cases.get_case(con, c)["isin"] == BBB)
    c = cases.get_case(con, cid)
    assert c["klass"] == "damage" and c["state"] == "acted", c
    # the model read with Sonnet, Opus decided (the exposure is over 2% of the book), every model call went through the door and is stored with its engine, model and level
    assert "claude-sonnet-5-5" in cl.roles() and "claude-opus-5-5" in cl.roles()
    ms = [s for s in c["steps"] if s["engine"]]
    assert ms and all(s["model"] and s["thinking"] for s in ms)
    # the answer is stored in a step payload under "answer", the way the scorer reads it
    ok = [s for s in c["steps"] if s["step"] == "answer_ok"][0]
    assert json.loads(ok["payload_json"])["answer"]["class"] == "damage"
    # the table: every option of the name, the model's own as track model, the rest alt; the rule's choice as track rule
    by = {}
    for o in c["options"]:
        by.setdefault(o["track"], []).append(o["option"])
    assert sorted(by["model"]) == ["hold"] and sorted(by["rule"]) == ["sell"] and set(by["alt"]) == set(think.OPTIONS) - {"hold"}
    assert "table" not in by
    rr = [o for o in c["options"] if o["track"] == "rule"][0]
    assert rr["chosen"] and rr["worst_inr"] < 0 < rr["best_inr"] or rr["expected_inr"] is not None
    # the rule acts: the sale went through the exit manager with the reason "case #N"
    d = c["decisions"][0]
    assert d["rule_option"] == "sell" and d["model_option"] == "hold" and d["differs"] and d["acted_option"] == "sell"
    sales = [o for o in orders(con, "sell") if o[0] == BBB]
    assert len(sales) == 1 and f"case #{cid}" in sales[0][3]
    assert con.execute("SELECT count(*) FROM exit_events_s81 WHERE isin=? AND kind='case' AND reason LIKE ?", [BBB, f"%Case #{cid}%"]).fetchone()[0] == 1
    # a Telegram text and a Today block
    tg = con.execute("SELECT status, kind, text FROM outbox WHERE dedup_key LIKE 'think_case:%'").fetchall()
    assert len(tg) == 1 and tg[0][0] == "pending" and tg[0][1] == "watch" and "BBB" in tg[0][2] and "sell" in tg[0][2]
    blk = wire.today_block(con, DAY)
    assert "BBB" in (blk["thinking"]["text"] or "") and blk["reserve"]
    lines = wire.report_lines(con, DAY)
    assert lines and any("BBB" in x for x in lines)
    # a second sweep the same day is idempotent: no second sale, no second case
    n_orders = len(orders(con))
    r2 = wire.sweep(con, CLOSE_AT + timedelta(minutes=45), tmp_path / "data", only_market="IN")
    assert len(orders(con)) == n_orders and r2["failed"] == []
    assert len(cases.decisions(con, cid)) == 1 and con.execute("SELECT count(*) FROM outbox WHERE dedup_key LIKE 'think_case:%'").fetchone()[0] == 1
    # the Today text reads well: the reserve is its own line, not glued to the case, and says rupees
    assert blk["thinking"]["text"].startswith("Thinking about: BBB (damage)") and "reserve" not in blk["thinking"]["text"].lower()
    assert "Holding instead" in tg[0][2]
    assert sum("reserve" in x.lower() for x in lines) == 1

    # ---- later: the book fills the sale, the price keeps falling; 25 sessions on the loop scores both tracks against every option not taken, 62 on it scores the 60-session look
    days = extend(con, 62, {BBB: -0.003})
    d25, d62 = days[24], days[61]
    probs0 = cases.probabilities(con)
    r25 = wire.sweep(con, datetime.combine(d25, datetime.min.time()) + timedelta(hours=16, minutes=30), tmp_path / "data", only_market="IN")
    assert r25["failed"] == [], r25
    assert r25["learned"]["scored"] > 0
    rows = con.execute("SELECT horizon_sessions, track, option, result_inr, vs_nothing_inr FROM think_scores_s84").fetchall()
    assert {h for h, *_ in rows} == {5, 20}                                                         # 25 sessions on: 5 and 20 are due, 60 is not
    tracks20 = {t for h, t, *_ in rows if h == 20}
    assert tracks20 == {"rule", "model", "alt"}
    rule20 = [r for r in rows if r[0] == 20 and r[1] == "rule"]
    model20 = [r for r in rows if r[0] == 20 and r[1] == "model"]
    assert [r[2] for r in rule20] == ["sell"] and [r[2] for r in model20] == ["hold"]
    assert rule20[0][4] > 0 and model20[0][4] == pytest.approx(0.0, abs=1e-6)                       # the name kept falling: the sale beat holding, holding is the baseline
    assert {r[2] for r in rows if r[0] == 20 and r[1] == "alt"} == set(think.OPTIONS) - {"hold", "sell"}
    assert cases.probabilities(con) == probs0                                                       # under 20 scored: calibration does not move
    sc = score.scorecard(con)
    assert sc["scored"] >= 1 and sc["rule_track"]["vs_nothing_inr"] > 0
    r62 = wire.sweep(con, datetime.combine(d62, datetime.min.time()) + timedelta(hours=16, minutes=30), tmp_path / "data", only_market="IN")
    assert r62["failed"] == [], r62
    assert {h for (h,) in con.execute("SELECT DISTINCT horizon_sessions FROM think_scores_s84").fetchall()} == {5, 20, 60}
    n_rows = con.execute("SELECT count(*) FROM think_scores_s84").fetchone()[0]
    wire.sweep(con, datetime.combine(d62, datetime.min.time()) + timedelta(hours=17), tmp_path / "data", only_market="IN")
    assert con.execute("SELECT count(*) FROM think_scores_s84").fetchone()[0] == n_rows            # scored once
    # ---- the calibration moves once 20 are scored: nine more decisions of the same kind are stored and scored
    for k in range(9):
        _seed_decided(con, cid, k)
    assert cases.probabilities(con) == probs0
    r = wire.sweep(con, datetime.combine(d62, datetime.min.time()) + timedelta(hours=18), tmp_path / "data", only_market="IN")
    assert r["failed"] == [] and r["learned"]["calibration"]["moved"], r
    p1 = cases.probabilities(con)
    for w in r["learned"]["calibration"]["moved"]:
        assert p1[w] != probs0[w] and abs(p1[w] - probs0[w]) <= 0.05 + 1e-9
    assert score.advisory(con, d62) in (True, False)


def _seed_decided(con, from_case, k):
    """Another decided case of the same kind on the same day (what `think_case` stores: the answer step, every option row, the decision), to reach 20 scored."""
    src = cases.get_case(con, from_case)
    sid = cases.record_signal(con, CLOSE_AT, market="IN", isin=BBB, symbol="BBB", signal="move_1d", value=-0.10, threshold=0.01, surprise=12.0, exposure_inr=1.0, score=12.0)
    nid = cases.open_case(con, CLOSE_AT, market="IN", kind=src["kind"], isin=BBB, symbol="BBB", title=f"BBB: seeded {k}", exposure_inr=1.0, score=1.0, signal_ids=[sid])
    ok = [s_ for s_ in src["steps"] if s_["step"] == "answer_ok"][0]
    cases.add_step(con, nid, CLOSE_AT, "answer_ok", payload=json.loads(ok["payload_json"]))
    for o in src["options"]:
        cases.add_option(con, nid, CLOSE_AT, track=o["track"], isin=o["isin"], symbol=o["symbol"], option=o["option"], worst_inr=o["worst_inr"], likely_inr=o["likely_inr"], best_inr=o["best_inr"],
                         expected_inr=o["expected_inr"], worst_pct_book=o["worst_pct_book"], size_inr=o["size_inr"], reason=o["reason"], chosen=o["chosen"])
    d = src["decisions"][0]
    cases.record_decision(con, nid, d["decided_on"], isin=BBB, symbol="BBB", rule_option=d["rule_option"], model_option=d["model_option"], acted_option=d["acted_option"], reason="seeded")


def _has(con, table):
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name=?", [table]).fetchone()[0])
