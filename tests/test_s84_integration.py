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
        if "needs_decision" in props:                                                  # the desk's read of one agenda item
            return self._msg([text(json.dumps({"finding": "Nothing in the facts changes what the book holds.", "needs_decision": "none", "next_step": ""}))], p["model"])
        if "symbols" in props:                                                         # the desk's shortlist
            return self._msg([text(json.dumps({"symbols": [], "why": "nothing is worth a closer look"}))], p["model"])
        if "picks" in props:
            return self._msg([text(json.dumps({"picks": [], "skips": [], "learned_from": "nothing yet"}))], p["model"])
        if "action" in props:
            return self._msg([text(json.dumps({"action": "keep", "reason": "the thesis holds"}))], p["model"])
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
    """`n` more sessions after DAY for every name in the store (a flat tape with a small wobble, `isin_drift` a daily drift per name), -> the list of days added."""
    days = [d.date() for d in pd.bdate_range(DAY + timedelta(days=1), periods=n)]
    names = [r[0] for r in con.execute("SELECT DISTINCT isin FROM prices").fetchall()]
    last = {i: float(con.execute("SELECT close FROM prices WHERE isin=? AND date=?", [i, DAY]).fetchone()[0]) for i in names}
    for k, d in enumerate(days):
        for i in names:
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


# --- the second scenario: a name the book does not hold, after a market-wide fall -----------------------------------------------------------------------------------------------

ETF, VOLX = "INF000N01017", "INE000V01010"


def add_name(con, isin, sym, cls, drift, wob, sector=None, start=100.0):
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, ?, 'synthetic', now())",
                [isin, cls, "LISTED_NONEQUITY" if cls == "etf" else "EQUITY", sym, f"{sym} Ltd", sector])
    for k, d in enumerate(DAYS):
        con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d, start * (1.0 + drift) ** k * (1.0 + (wob if k % 2 else -wob))])


def falling_index(n_future=60):
    """A synthetic Nifty 500: calm, then 12% down in the last 3 sessions, then a steep recovery (so the fall is a signal on one day only)."""
    days = DAYS + [d.date() for d in pd.bdate_range(DAY + timedelta(days=1), periods=n_future)]
    lvl = [1000.0 * 1.0003 ** k for k in range(len(DAYS))]
    lvl[-3:] = [lvl[-4] * 0.96, lvl[-4] * 0.96 ** 2, lvl[-4] * 0.96 ** 3]
    for _ in range(n_future):
        lvl.append(lvl[-1] * 1.04)
    return pd.Series(lvl, index=pd.to_datetime(days))


def test_a_name_not_held_after_a_market_fall_is_bought_in_three_parts_from_the_reserve(con, tmp_path, monkeypatch):
    add_name(con, ETF, "NIFTYBEES", "etf", 0.0010, 0.002)
    ix = falling_index()
    monkeypatch.setattr(watch, "_index", lambda market, root=None: ix if market == "IN" else None)
    market_answer = answer("NIFTYBEES", "buy_in_parts", "market_fear", pending="", worst="very unlikely", likely="even", best="likely")

    def by_case(p):                                         # the held names the index fall also flags (they fell less than the market) are held; the market's own case buys the ETF
        text = json.dumps(p["messages"][0]["content"])
        if "Nifty 500" in text:
            return market_answer
        sym = re.search(r"market IN, kind \w+\): (\w+)", text.replace("\n", " ")).group(1)
        return answer(sym, "hold", "market_fear", pending="", worst="unlikely", likely="likely", best="unlikely")
    cl = script(Client(by_case, check="pass"))
    now0 = CLOSE_AT + timedelta(minutes=30)
    r = wire.sweep(con, now0, tmp_path / "data", only_market="IN")
    assert r["failed"] == [], r
    cid = next(c for c in r["cases_opened"] if cases.get_case(con, c)["isin"] == "MARKET:IN")
    c = cases.get_case(con, cid)
    assert c["kind"] == "market" and c["klass"] == "market_fear" and c["state"] == "acted"
    assert "claude-opus-5-5" in cl.roles()                                                  # a chance that could spend the reserve is decided by Opus
    d = c["decisions"][0]
    assert d["symbol"] == "NIFTYBEES" and d["rule_option"] == "buy_in_parts" and d["acted_option"] == "buy_in_parts", d
    res = reserve.reserve_status(con, "IN", DAY)
    buys = [o for o in orders(con, "buy") if o[0] == ETF]
    assert len(buys) == 1 and f"case #{cid}" in buys[0][3]
    amt1 = con.execute("SELECT amount FROM paper_orders WHERE isin=? AND side='buy'", [ETF]).fetchone()[0]
    rr = [o for o in c["options"] if o["track"] == "rule"][0]
    assert rr["option"] == "buy_in_parts" and rr["size_inr"] == pytest.approx(amt1, rel=1e-6) and rr["expected_inr"] > 0
    whole = odds.whole_book(con, DAY)
    assert abs(rr["worst_pct_book"]) <= 0.01 / 3 + 1e-9                                      # a part's share of a bet whose bad case loses at most 1% of the whole book
    # the model's own row (track model) is the table's buy_in_parts row: sized by the 1% limit over the bad case, before the reserve and the rails
    mrow = [o for o in c["options"] if o["track"] == "model"][0]
    assert mrow["option"] == "buy_in_parts" and mrow["size_inr"] > 0 and abs(mrow["worst_pct_book"]) <= 0.01 + 1e-9
    # parts two and three come at the follow-ups at least 5 sessions apart; the table is never re-bought past three
    days = extend(con, 20, {ETF: 0.01})                                                  # the ETF recovers: no new lows
    parts_days = [DAY]
    for step in (5, 12):                                                                      # five sessions on (the NSE has no session on 10 Nov), then five more
        nowk = datetime.combine(days[step - 1], datetime.min.time()) + timedelta(hours=16, minutes=30)
        rk = wire.sweep(con, nowk, tmp_path / "data", only_market="IN")
        assert rk["failed"] == [], rk
        parts_days.append(days[step - 1])
    buys = [o for o in orders(con, "buy") if o[0] == ETF]
    assert len(buys) == 3, (buys, [(s["step"], s["payload_json"][:200]) for s in cases.get_case(con, cid)["steps"] if s["step"] in ("part", "looked", "failed")])
    part_steps = [json.loads(s["payload_json"]) for s in cases.get_case(con, cid)["steps"] if s["step"] == "part"]
    assert [p["n"] for p in part_steps] == [1, 2, 3]
    gaps = [(date.fromisoformat(b["day"]) - date.fromisoformat(a["day"])).days for a, b in zip(part_steps, part_steps[1:])]
    assert all(g >= 5 for g in gaps)
    assert sum(p["inr"] for p in part_steps) <= res["reserve_inr"] * 0.5 + 1.0              # a market-wide fall may put up to half the reserve into the index ETF
    # every reserve buy went past the independent check
    assert con.execute("SELECT count(*) FROM think_steps_s84 WHERE case_id=? AND step='big_trade_check'", [cid]).fetchone()[0] >= 3
    # a fourth part is never bought
    rk = wire.sweep(con, datetime.combine(days[16], datetime.min.time()) + timedelta(hours=17), tmp_path / "data", only_market="IN")
    assert len([o for o in orders(con, "buy") if o[0] == ETF]) == 3


def open_case_on(con, isin, sym, kind="move", signal="move_1d", value=-0.30, exposure=0.0, now=None):
    now = now or CLOSE_AT + timedelta(minutes=30)
    sid = cases.record_signal(con, now, market="IN", isin=isin, symbol=sym, signal=signal, value=value, threshold=0.03, surprise=2.0, exposure_inr=exposure, score=2.0 * max(exposure, 1.0))
    return cases.open_case(con, now, market="IN", kind=kind, isin=isin, symbol=sym, title=f"{sym} moved {value:.0%} in a day", exposure_inr=exposure, score=2.0, signal_ids=[sid], opened_by="watch", state="open")


def test_a_bet_is_sized_down_to_one_percent_of_the_book_and_refused_when_it_cannot_fit(con, tmp_path):
    add_name(con, VOLX, "VOLX", "equity", 0.002, 0.06, sector="Auto", start=200.0)
    script(Client(answer("VOLX", "buy_in_parts", "temporary", pending="", worst="very unlikely", likely="even", best="likely"), check="pass"))
    cid = open_case_on(con, VOLX, "VOLX")
    now = CLOSE_AT + timedelta(minutes=40)
    r = session.think_case(con, now, cid, root=tmp_path / "data")
    assert r["ok"], r
    c = cases.get_case(con, cid)
    mrow = [o for o in c["options"] if o["track"] == "model"][0]
    whole = odds.whole_book(con, DAY)
    assert mrow["option"] == "buy_in_parts" and mrow["size_inr"] > 0
    assert abs(mrow["worst_pct_book"]) == pytest.approx(0.01, rel=1e-3)                             # the bet's size is the 1% limit over the bad case's loss: its worst case loses 1% of the whole book
    assert mrow["size_inr"] < 0.5 * reserve.reserve_status(con, "IN", DAY)["reserve_inr"]            # sized DOWN by the limit, not by the reserve or the rail
    d = c["decisions"][0]
    assert d["rule_option"] == "buy_in_parts" and d["acted_option"] == "buy_in_parts"
    part = con.execute("SELECT amount FROM paper_orders WHERE isin=? AND side='buy'", [VOLX]).fetchone()[0]
    assert part == pytest.approx(mrow["size_inr"] / 3, rel=1e-3)
    # the act itself refuses a decision whose stored worst case is over 1% of the book, whatever the rule said
    out = session.act(con, now, cid, {"isin": VOLX, "symbol": "VOLX", "market": "IN", "option": "buy_in_parts", "size_inr": 90000.0, "parts": 3, "worst_pct_book": -0.02, "reason": "too big"})
    assert len(out) == 1 and out[0].startswith("no order: the worst case would lose 2.00%")
    assert len([o for o in orders(con, "buy") if o[0] == VOLX]) == 1
    # a name whose bad case is so wide that no part is worth buying: the rule refuses, nothing is bought
    add_name(con, "INE000W01011", "WILDX", "equity", 0.0, 0.45, sector="Pharma", start=50.0)
    script(Client(answer("WILDX", "buy_in_parts", "temporary", pending="", worst="very unlikely", likely="even", best="likely"), check="pass"))
    cid2 = open_case_on(con, "INE000W01011", "WILDX")
    r2 = session.think_case(con, now, cid2, root=tmp_path / "data")
    assert r2["ok"], r2
    d2 = cases.get_case(con, cid2)["decisions"][0]
    assert d2["rule_option"] == "nothing" and d2["acted_option"] == "nothing" and not [o for o in orders(con, "buy") if o[0] == "INE000W01011"], d2


# --- the third scenario: the model and the rule disagree; the rule acts ----------------------------------------------------------------------------------------------------------

def test_the_model_says_sell_the_rule_says_hold_the_rule_acts_and_both_are_stored_and_scored(con, tmp_path):
    script(Client(answer("BBB", "sell", "market_fear", pending="", worst="even", likely="even", best="even"), check="pass"))
    cid = open_case_on(con, BBB, "BBB", exposure=150000.0)
    r = session.think_case(con, CLOSE_AT + timedelta(minutes=40), cid, root=tmp_path / "data")
    assert r["ok"], r
    c = cases.get_case(con, cid)
    d = c["decisions"][0]
    assert d["model_option"] == "sell" and d["rule_option"] == "hold" and d["differs"] and d["acted_option"] == "hold", d
    assert "the model chose sell, the rule chose hold; the rule acts" in d["reason"]
    assert not [o for o in orders(con, "sell") if o[0] == BBB]                                      # the rule's choice acts: no sale
    tr = {o["track"]: o["option"] for o in c["options"] if o["chosen"]}
    assert tr == {"model": "sell", "rule": "hold"}
    assert {o["option"] for o in c["options"] if o["track"] == "alt"} == set(think.OPTIONS) - {"sell"}      # the rule's hold is also an alt row: the options not taken
    # 25 sessions later BOTH tracks are scored against everything not taken
    days = extend(con, 25, {BBB: -0.01})
    assert score.score_due(con, days[-1]) > 0
    rows = con.execute("SELECT track, option, vs_nothing_inr FROM think_scores_s84 WHERE horizon_sessions=20").fetchall()
    assert {(t, o) for t, o, _ in rows if t in ("model", "rule")} == {("model", "sell"), ("rule", "hold")}
    assert [v for t, o, v in rows if t == "model"][0] > 0 and [v for t, o, v in rows if t == "rule"][0] == pytest.approx(0.0, abs=1e-6)       # the price kept falling: the model's sale would have beaten the rule's hold
    sc = score.scorecard(con)
    assert sc["model_track"]["vs_nothing_inr"] > sc["rule_track"]["vs_nothing_inr"]


# --- the fourth scenario: the thinking session fails ------------------------------------------------------------------------------------------------------------------------------

def test_a_failing_thinking_session_leaves_the_case_open_and_the_close_and_the_thesis_sale_go_on(con, tmp_path):
    from pflab.core import loop
    from tests.test_s80_core import calm_index
    fall(con, BBB, -0.10)
    t = datetime.combine(DAY, datetime.min.time()) + timedelta(hours=11)
    con.execute("INSERT INTO kg2_event (event_id, isin, source, ref, ts, event_date, kind, severity, headline, link_rule, link_proof, dedupe_key, ts_rule) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ["bse:fraud1:" + BBB, BBB, "bse_announcement", "fraud1", t, DAY, "fraud_investigation", "high", "the chief executive is under investigation", "t", "t", "bse:fraud1", "release_time"])
    script(Client(answer(), boom=RuntimeError("the vendor is down")))
    r = wire.sweep(con, CLOSE_AT + timedelta(minutes=30), tmp_path / "data", only_market="IN")                # the thinking pass: every model call raises
    assert r["failed"] and all("thinking failed" in x for x in r["failed"]), r                               # visible, not raised
    assert r["sessions"] == {"IN": [f"{DAY}:close"]}                                                         # the session was still watched and marked
    cid = next(c for c in r["cases_opened"] if cases.get_case(con, c)["isin"] == BBB)
    c = cases.get_case(con, cid)
    assert c["state"] == "open" and "thinking failed" in (c["summary"] or "") and any(s["step"] == "failed" for s in c["steps"]) and c["decisions"] == []
    assert not orders(con, "sell")                                                                          # the thinking placed nothing
    assert "Thinking failed on" in wire.today_block(con, DAY)["thinking"]["text"]
    # the close itself: the exit manager reads the filing and sells the name (a thesis break), as it does without any thinking
    res = loop.run(con, NOW, tmp_path / "data", calm_index())
    assert res.get("status") in ("traded", "held"), res
    sells = [o for o in orders(con, "sell") if o[0] == BBB]
    assert len(sells) == 1 and con.execute("SELECT count(*) FROM exit_events_s81 WHERE isin=? AND kind='thesis'", [BBB]).fetchone()[0] == 1, (res, sells)
    # the failed case's next look is the next session: the vendor is back, the follow-up thinks the same case through (nothing was lost; no paid retry every half hour)
    script(Client(answer("BBB", "sell", "damage", pending="the board's decision")))
    nxt = extend(con, 3)[0]
    assert str(cases.get_case(con, cid)["next_look_on"]) <= str(nxt)
    r2 = wire.sweep(con, datetime.combine(nxt, datetime.min.time()) + timedelta(hours=16, minutes=30), tmp_path / "data", only_market="IN")
    c2 = cases.get_case(con, cid)
    assert c2["klass"] == "damage" and c2["decisions"] and r2["follow_up"]["rethought"] >= 1, (r2, c2)


# --- the fifth scenario: advisory mode -----------------------------------------------------------------------------------------------------------------------------------------

def test_in_advisory_mode_cases_open_and_report_and_only_the_damage_sale_acts(con, tmp_path, monkeypatch):
    real = think.settings
    monkeypatch.setattr(think, "settings", lambda: {**real(), "mode": "advisory"})
    # a held name with a damage answer: the thesis-break sale still acts
    script(Client(answer("BBB", "hold", "damage", pending="the board's decision"), check="pass"))
    c1 = open_case_on(con, BBB, "BBB", exposure=150000.0)
    r1 = session.think_case(con, CLOSE_AT + timedelta(minutes=40), c1, root=tmp_path / "data")
    assert r1["ok"] and r1["advisory"] is True
    d1 = cases.get_case(con, c1)["decisions"][0]
    assert d1["rule_option"] == "sell" and d1["acted_option"] == "sell" and d1["advisory"] is True and len([o for o in orders(con, "sell") if o[0] == BBB]) == 1
    # a chance: the rule would buy in parts; advisory reports it and orders nothing
    add_name(con, ETF, "NIFTYBEES", "etf", 0.0010, 0.002)
    script(Client(answer("NIFTYBEES", "buy_in_parts", "market_fear", pending="", worst="very unlikely", likely="even", best="likely"), check="pass"))
    c2 = open_case_on(con, "MARKET:IN", "Nifty 500", kind="market", signal="market_down_20d", value=-0.12, exposure=500000.0)
    r2 = session.think_case(con, CLOSE_AT + timedelta(minutes=41), c2, root=tmp_path / "data")
    assert r2["ok"] and r2["advisory"] is True
    d2 = cases.get_case(con, c2)["decisions"][0]
    assert d2["rule_option"] == "buy_in_parts" and d2["acted_option"].startswith("advisory") and not [o for o in orders(con, "buy") if o[0] == ETF]
    assert cases.get_case(con, c2)["state"] == "advisory"
    assert not cases.active_freezes(con, DAY)                                                              # nothing acts in advisory: no system freeze either


def test_the_loop_turns_advisory_by_itself_when_the_rule_is_behind_doing_nothing_after_20_scored(con, tmp_path):
    script(Client(answer("BBB", "hold", "damage", pending="the board's decision"), check="pass"))
    cid = open_case_on(con, BBB, "BBB", exposure=150000.0)
    assert session.think_case(con, CLOSE_AT + timedelta(minutes=40), cid, root=tmp_path / "data")["advisory"] is False
    days = extend(con, 25, {BBB: 0.01})                                                                     # the name RECOVERED: the sale was worse than holding
    for k in range(19):
        _seed_decided(con, cid, k)
    d25 = days[-1]
    assert score.score_due(con, d25) > 0 and score.scorecard(con)["rule_track"]["vs_nothing_inr"] < 0
    assert score.advisory(con, d25) is True
    add_name(con, ETF, "NIFTYBEES", "etf", 0.0010, 0.002)
    script(Client(answer("NIFTYBEES", "buy_in_parts", "temporary", pending="", worst="very unlikely", likely="even", best="likely"), check="pass"))
    at = datetime.combine(d25, datetime.min.time()) + timedelta(hours=16)
    c3 = open_case_on(con, ETF, "NIFTYBEES", now=at)
    r3 = session.think_case(con, at + timedelta(minutes=5), c3, root=tmp_path / "data")
    assert r3["ok"] and r3["advisory"] is True
    assert not [o for o in orders(con, "buy") if o[0] == ETF]


# --- the desk, recall and the gateway on the real modules -------------------------------------------------------------------------------------------------------------------------

def test_the_desk_works_the_agenda_with_the_real_gateway_recall_and_session_and_never_thinks_a_case_twice_in_a_day(con, tmp_path):
    from pflab.think import desk, recall
    fall(con, BBB, -0.10)
    cl = script(Client(answer(option="hold", klass="damage")))
    # a paid note on the name written yesterday: recall finds it, the case reads it, the desk counts it as used
    recall.write_back(con, CLOSE_AT - timedelta(days=1), isin=BBB, symbol="BBB", title="an earlier read", text="the order book was the thesis", source="analyst", cost_rupees=12.0)
    r = wire.sweep(con, CLOSE_AT + timedelta(minutes=30), tmp_path / "data", only_market="IN")
    assert r["failed"] == [], r
    cid = next(c for c in r["cases_opened"] if cases.get_case(con, c)["isin"] == BBB)
    n_answers = len([x for x in cases.steps(con, cid) if x["step"] == "answer_ok"])
    first = [p for p in cl.sent if "choices" in json.dumps(p.get("output_config") or {})][0]
    assert "the order book was the thesis" in json.dumps(first["messages"])                         # recall reached the case's first message
    assert con.execute("SELECT count(*) FROM knowledge_use_s84 WHERE used_by_kind='case' AND used_by_ref=?", [str(cid)]).fetchone()[0] >= 1       # and is counted as used
    n_calls = len(cl.sent)
    out = desk.run_desk(con, CLOSE_AT + timedelta(minutes=45), "india_close", root=tmp_path / "data")
    assert out["status"] in ("done", "budget", "quiet"), out
    assert out.get("items", 0) >= 1
    # the desk's calls went through the same door: agent `desk` in the governor's log, role read, one case thought once only (a step today stops a second think)
    rows = con.execute("SELECT agent, role, case_id FROM api_calls WHERE agent='desk'").fetchall()
    assert rows and all(r_[1] in ("read", "decide", "quick") for r_ in rows)
    assert len([x for x in cases.steps(con, cid) if x["step"] == "answer_ok"]) == n_answers
    assert len(cases.decisions(con, cid)) == 1
    assert desk.plan_text(con, DAY) and "desk" in wire.today_block(con, DAY)["plan"].lower() or wire.today_block(con, DAY)["plan"]
    # a second run of the same slot is a no-op, and a quiet agenda costs nothing
    assert "already ran" in desk.run_desk(con, CLOSE_AT + timedelta(minutes=50), "india_close", root=tmp_path / "data").get("skipped", "")


def test_every_thinking_module_reaches_the_model_only_through_the_gateway_and_the_job_and_the_live_test_are_registered(con, tmp_path):
    import inspect
    import pathlib
    from pflab.app import runtime, world
    from pflab.learner import s84
    from pflab.service import jobs, tasks
    tasks.load_all() if hasattr(tasks, "load_all") else None
    # (h) the model is called through `gateway.call` only, with the agent `think` or `desk`
    root = pathlib.Path(think.__file__).parent
    for f in root.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        assert not re.search(r"messages\.create|import anthropic|make_client|beta\.messages|llm\.call\(", src), f.name
    for f, agent in (("session.py", "think"), ("desk.py", "desk")):
        src = (root / f).read_text(encoding="utf-8")
        assert f'agent="{agent}"' in src
    # (i) the app's start registers the thinking live test, once; the job is registered and belongs to a world node
    assert "register_thinking_live" in inspect.getsource(runtime)
    n = len(s84.register_thinking_live(con, NOW))
    assert s84.register_thinking_live(con, NOW) == [] and n >= 0
    assert con.execute("SELECT count(*) FROM learner_tests WHERE note LIKE 's84:thinking_live%'").fetchone()[0] <= 1 if _has(con, "learner_tests") else True
    assert "think_loop" in jobs.REGISTRY
    assert any("think_loop" in jobs_ for _g, _t, jobs_ in [(g[0], g[1], g[2]) for g in world.ROUTINES])


def test_not_yet_clear_with_something_pending_freezes_the_name_and_the_baseline_and_the_picks_read_the_freeze(con, tmp_path):
    from pflab.core import state as core_state
    from tests.test_s80_core import calm_index
    script(Client(answer("BBB", "wait", "unclear", pending="the board's decision", worst="unlikely", likely="even", best="unlikely"), check="pass"))
    cid = open_case_on(con, BBB, "BBB", exposure=150000.0)
    r = session.think_case(con, CLOSE_AT + timedelta(minutes=40), cid, root=tmp_path / "data")
    assert r["ok"], r
    d = cases.get_case(con, cid)["decisions"][0]
    assert d["rule_option"] == "freeze" and d["model_option"] == "wait" and d["acted_option"] == "freeze"
    assert cases.is_frozen(con, BBB, DAY) and BBB in cases.frozen_isins(con, DAY, "IN")
    st = core_state.build(con, DAY, None, calm_index())
    assert BBB in st["frozen"]                                                                  # the baseline reads it: no new buying of the name
    assert not [o for o in orders(con, "sell") if o[0] == BBB]                                  # a freeze is not a sale
    # the look a few sessions on closes the question: nothing pending is answered, no signal joined: the freeze is released when the case closes
    days = extend(con, 70)
    out = wire.sweep(con, datetime.combine(days[-1], datetime.min.time()) + timedelta(hours=16, minutes=30), tmp_path / "data", only_market="IN")
    assert out["failed"] == [], out
    assert cases.get_case(con, cid)["state"] == "closed" and not cases.is_frozen(con, BBB, days[-1])


def test_the_history_is_scanned_once_per_case_and_once_per_decision_when_scoring(con, tmp_path, monkeypatch):
    calls = []
    real = odds._base_rates
    monkeypatch.setattr(odds, "_base_rates", lambda *a, **k: calls.append(a[1:3]) or real(*a, **k))
    script(Client(answer("BBB", "hold", "damage", pending="the board's decision"), check="pass"))          # no read tools: the model's own tool loop would ask for its own table
    cid = open_case_on(con, BBB, "BBB", exposure=150000.0)
    assert session.think_case(con, CLOSE_AT + timedelta(minutes=40), cid, root=tmp_path / "data")["ok"]
    assert len(calls) == 1, calls                                                                          # the table and the rule share one cache dict
    days = extend(con, 25)
    calls.clear()
    assert score.score_due(con, days[-1]) > 0
    n_first = len(calls)
    assert n_first == 1                                                                                    # one scan for the decision, kept as a `moves` step
    score.calibrate(con, days[-1])
    score.score_due(con, days[-1])
    assert len(calls) == n_first                                                                           # the calibration and a second scoring read it back: no further scan
    assert [s for s in cases.steps(con, cid) if s["step"] == "moves"] and not any(s["step"] == "moves" and str(s["step_at"])[:10] == str(days[-1]) for s in cases.steps(con, cid))
