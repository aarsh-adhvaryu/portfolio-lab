"""The synthetic drills of T9 (the prompt's list), run on the drills' synthetic profile with a SCRIPTED model and designed price shocks (`replays_s84.shock_held_prices`): a fall or a headline
arrives on its session, never before. Each drill returns a `Check` (evidence ok/FAIL), as in tools/drills_s81.py.

    missed_exit      a held name falls after its exit was missed: the case opens after the fall, freezes, waits, and later buys in parts or does nothing, by the rule
    bet_sizing       a bet whose worst case does not fit 1% of the whole book is sized down, or refused when it cannot be
    disagree         the model says hold, the rule says sell: the rule acts, both choices are stored and scored
    follow_up        a case is looked at again by its date, and another by an event that arrives
    failing          the thinking session fails, then the cap is reached: the case stays open, a thesis-break sale still acts, nothing else changes
    calibration      after 20 scored cases the word table moves, in bounded steps; before, it does not
    advisory         the loop turns advisory when the rule's track is behind "do nothing" after 20 scored decisions, and off again when ahead
    three_cases      four names shocked on one day: three cases are thought through, the fourth is logged as noticed
"""
from __future__ import annotations

import json
import traceback
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional

import replays_s84 as R
from replays_s84_model import Scenario, ScriptedClient, words

D = R.D
START = date(2026, 10, 15)                       # a Thursday: Fri 16, Mon 19, [Tue 20 holiday], Wed 21 ...
FMCG1, FMCG2, CAPG1, IT1 = (D.STOCKS[i][1] for i in (0, 1, 2, 3))
PICK1, PICK2 = D.PICK_STOCKS[0][1], D.PICK_STOCKS[1][1]
SYM = {s[1]: s[0] for s in D.STOCKS + D.PICK_STOCKS}


def sessions(n: int, start: date = START) -> List[date]:
    from pflab import markets
    m, d, out = markets.get("IN"), start, []
    for _ in range(n):
        out.append(d)
        d = m.next_session(d)
    return out


def add_event(con, isin: str, kind: str, severity: str, ts: datetime, headline: str, key: str, source: str = "bse_announcement") -> None:
    """A graph event (`kg2_event`) with its dissemination time (point in time: the drill adds it when its time has come)."""
    if con.execute("SELECT 1 FROM kg2_event WHERE event_id=?", [key]).fetchone():
        return
    con.execute("INSERT INTO kg2_event (event_id, isin, source, ref, ts, event_date, kind, severity, headline, link_rule, link_proof, dedupe_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [key, isin, source, f"drill:{key}", ts, ts.date(), kind, severity, headline, "isin_in_filing", "drill: the filing names the ISIN", key])
    try:
        con.execute("INSERT INTO kg2_event_class VALUES (?,?,?,?,?,?)", [key, kind, severity, "scripted", "drill", ts])
    except Exception:
        pass


def sale_orders(con, isin: str, like: str = "%") -> list:
    """The rupee book's sell orders of a name (the paper book's own table), reason matched by `like`."""
    try:
        return con.execute("SELECT order_id, isin, side, qty, status, reason FROM paper_orders WHERE isin=? AND side IN ('sell','SELL') AND reason LIKE ?", [isin, like]).fetchall()
    except Exception:
        return []


def buy_orders(con, isin: str) -> list:
    try:
        return con.execute("SELECT order_id, isin, side, qty, status, reason FROM paper_orders WHERE isin=? AND side IN ('buy','BUY')", [isin]).fetchall()
    except Exception:
        return []


class World:
    """A drill's world: profile, shocks, scripted model, the loop. `events` = [(ts, isin, kind, severity, headline, key)] added when their time has come."""

    def __init__(self, name: str, answers: Callable, *, shocks=None, events=None, tag: str = "", check: str = "pass", fail: Optional[str] = None, cap: float = 300.0, start: date = START):
        self.name, self.start, self.events = name, start, list(events or [])
        self.env = R.make_world(name, start, shocks=shocks, tag=tag or name, real_bars=False)
        self.scen = Scenario(name, answers, check=check)
        R.install_cap(cap)
        self.client = ScriptedClient(self.scen.responder(self.env.cur()), {}, fail=fail)
        self.armed = R.arm(self.client)
        R.open_world(self.env, start)
        self.timeline: List[dict] = []

    def run(self, last: date, first: Optional[date] = None) -> List[dict]:
        def hook(env, t):
            for ts, isin, kind, sev, head, key in self.events:
                if ts <= t:
                    add_event(env.cur(), isin, kind, sev, ts, head, key)
        tl = R.run_window(self.env, first or self.start, last, release=False, hook=hook)
        self.timeline += tl
        return tl

    @property
    def con(self):
        return self.env.cur()

    def close(self) -> None:
        R.disarm()
        self.env.close()


def _evidence_clean(w: World, c) -> None:
    c.ok(not w.env.exceptions, f"no unhandled exception in the loops: {w.env.exceptions[:2]}", "think/wire.py")
    c.ok(not w.env.catcher.records, f"no error logged by pflab: {w.env.catcher.records[:2]}", "(the logger named)")


def _answer(klass: str, option: str, symbol: str, *, pending: str = "", pending_date: str = "", worst: str = "unlikely", likely: str = "likely", best: str = "unlikely") -> dict:
    return {"happened": f"{symbol} fell sharply on its session (drill).", "sources": ["the stored closes", "the drill's headline row"], "class": klass,
            "known": "The fall is in the stored closes.", "pending": pending, "pending_date": pending_date, "other_names": [],
            "choices": [{"symbol": symbol, "option": option, "reason": f"scripted: {option} for {symbol}"}], "likelihood": words(worst, likely, best)}


# --- the drills ----------------------------------------------------------------------------------------------------------------------------------------------------------------------

def drill_three_cases(c) -> None:
    """Four held names fall 25% on the same session: three cases are thought through, the fourth is stored as noticed."""
    S = sessions(8)
    fall = S[4]
    w = World("three_cases", lambda case, n: _answer("market_fear", "hold", case.get("symbol") or "X"), shocks=[(i, fall, 0.75) for i in (FMCG1, FMCG2, CAPG1, IT1)])
    try:
        w.run(S[7])
        con = w.con
        from pflab.think import cases
        sig = cases.signals(con)
        names = {s["symbol"] for s in sig}
        c.ok(len(names) >= 4, f"the watch noticed all four fallen names ({sorted(names)})", "think/watch.py")
        by_day = {}
        for cs in cases._rows(con, "think_cases_s84", cases._CASE):
            by_day.setdefault(str(cs["opened_on"]), {}).setdefault("noticed" if cs["state"] == "noticed" else "examined", []).append(cs["symbol"])
        worst_day = max(by_day.items(), key=lambda kv: len(kv[1].get("noticed", [])) + len(kv[1].get("examined", [])), default=(None, {}))
        c.note(f"cases by day: {by_day}")
        c.ok(all(len(v.get("examined", [])) <= 3 for v in by_day.values()), "never more than 3 new cases thought through in a day", "think/watch.py max_cases_per_day")
        c.ok(len(worst_day[1].get("examined", [])) == 3 and len(worst_day[1].get("noticed", [])) >= 1, f"on the day of the fall 3 cases were examined and the rest stored as noticed ({worst_day[1]})", "think/watch.py")
        blk = cases.thinking_block(con, date.fromisoformat(worst_day[0])) if worst_day[0] else {}
        c.ok(blk.get("noticed_not_examined_today", 0) >= 1, f"the Today block counts the noticed case ({blk.get('noticed_not_examined_today')})", "think/cases.py thinking_block")
        _evidence_clean(w, c)
    finally:
        w.close()


def drill_missed_exit(c) -> None:
    """A held name drops 22% over two sessions and no exit stood: the case opens after the fall, freezes (unclear, something pending), waits, and later the rule decides."""
    S = sessions(16)
    fall = S[3]
    pend_date = S[8].isoformat()

    def answers(case, n):
        if n == 1:
            return _answer("unclear", "wait", case["symbol"], pending="the next quarterly result", pending_date=pend_date)
        return _answer("temporary", "buy_in_parts", case["symbol"])
    w = World("missed_exit", answers, shocks=[(IT1, fall, 0.88), (IT1, S[4], 0.89)])
    try:
        w.run(S[15])
        from pflab.think import cases
        con = w.con
        cs = [x for x in cases._rows(con, "think_cases_s84", cases._CASE) if x["isin"] == IT1]
        c.ok(bool(cs), f"a case opened on the fallen name ({[(x['case_id'], x['state'], x['klass']) for x in cs]})", "think/watch.py")
        if cs:
            case = cs[0]
            c.ok(case["opened_on"] >= fall, f"it opened on or after the fall ({case['opened_on']} >= {fall})", "think/watch.py")
            d = cases.decisions(con, case["case_id"])
            c.note(f"decisions: {[(x['decided_on'].isoformat(), x['rule_option'], x['model_option'], x['acted_option']) for x in d]}")
            c.ok(bool(d) and d[0]["rule_option"] == "freeze", f"first decision: freeze while the result is pending (the rule said {d[0]['rule_option'] if d else None})", "think/rule.py")
            fr = [f for f in cases._rows(con, "think_freezes_s84", ("freeze_id", "isin", "since", "until", "until_event", "active"), "WHERE isin=?", [IT1])]
            c.ok(bool(fr), f"a freeze on the name was stored ({[(f['since'].isoformat(), f['active']) for f in fr]})", "think/session.py act")
            first_freeze_day = fr[0]["since"] if fr else None
            during = [b for b in buy_orders(con, IT1)]
            c.ok(not during, f"no buy order for the frozen name at any time ({during[:2]})", "core/baseline_v2.py / think freeze hook")
            c.ok(len(d) >= 2, f"it was looked at again and decided again ({len(d)} decisions)", "think/session.py follow_up")
            if len(d) >= 2:
                c.ok(d[-1]["rule_option"] in ("hold", "buy_in_parts", "nothing", "wait", "freeze"), f"the later decision is the rule's, by its guards: {d[-1]['rule_option']} ({d[-1]['reason'][:120]})", "think/rule.py")
        _evidence_clean(w, c)
    finally:
        w.close()


def drill_disagree(c) -> None:
    """The model says hold on a damage case; the rule sells (a thesis break). The rule acts; both are stored."""
    S = sessions(10)
    fall = S[3]
    ts = D.dt(fall, 15, 40)
    w = World("disagree", lambda case, n: _answer("damage", "hold", case["symbol"], pending="a regulator's decision"), shocks=[(CAPG1, fall, 0.78)],
              events=[(ts, CAPG1, "regulatory_action", "high", "SYNCAPG1 receives a regulator's show-cause notice over its accounts (drill)", "drill-regulator-1")])
    try:
        w.run(S[9])
        from pflab.think import cases
        con = w.con
        d = [x for x in cases.decisions(con) if x["isin"] == CAPG1]
        c.ok(bool(d), f"a decision was stored for the name ({len(d)})", "think/session.py")
        if d:
            x = d[0]
            c.ok(x["model_option"] == "hold" and x["rule_option"] == "sell" and x["differs"], f"model {x['model_option']}, rule {x['rule_option']}, differs {x['differs']}", "think/rule.py")
            c.ok(x["acted_option"] == "sell", f"the rule acted: {x['acted_option']}", "think/session.py act")
            opts = cases.options(con, x["case_id"])
            c.ok({"model", "rule"} <= {o["track"] for o in opts}, f"both tracks are stored ({sorted({o['track'] for o in opts})})", "think/session.py")
            c.ok(bool(sale_orders(con, CAPG1)), f"the sale exists as an order ({sale_orders(con, CAPG1)[:1]})", "think/session.py act")
        _evidence_clean(w, c)
    finally:
        w.close()


def drill_failing(c) -> None:
    """The model fails, then the cap is reached: the case stays open, a thesis-break sale (the exit manager) still acts, nothing else is bought or sold."""
    S = sessions(12)
    fall = S[3]
    ts = D.dt(S[4], 15, 20)
    w = World("failing", lambda case, n: _answer("market_fear", "hold", case["symbol"]), shocks=[(FMCG2, fall, 0.75)], fail="the model API is down (drill)",
              events=[(ts, IT1, "guidance_cut", "high", "SYNIT1 cuts its revenue guidance and a large client leaves (drill)", "drill-thesis-fail")])
    try:
        w.run(S[6])
        from pflab.think import cases
        con = w.con
        cs = [x for x in cases._rows(con, "think_cases_s84", cases._CASE) if x["isin"] == FMCG2]
        c.ok(bool(cs) and all(x["state"] in ("open", "noticed") for x in cs), f"the case stays open when the model fails ({[(x['state']) for x in cs]})", "think/session.py")
        failed = [s for x in cs for s in cases.steps(con, x["case_id"]) if s["step"] == "failed"]
        c.ok(bool(failed), "a stored 'failed' step says why", "think/session.py")
        c.ok(not cases.decisions(con, cs[0]["case_id"]) if cs else True, "no decision and no order came from the failed case", "think/session.py")
        c.ok(R.D.Check is not None and bool(con.execute("SELECT 1 FROM exit_events_s81 WHERE isin=? AND kind='thesis'", [IT1]).fetchone()), "the exit manager's thesis-break sale still acted while the model was down", "core/exits.py")
        # the cap reached: the same scripted client, but the governor has no room
        R.arm(ScriptedClient(w.scen.responder(con), {}))
        R.install_cap(0.0)
        w.run(S[11], first=S[7])
        steps = [s for x in cases._rows(con, "think_cases_s84", cases._CASE) if x["isin"] == FMCG2 for s in cases.steps(con, x["case_id"])]
        c.ok(any(s["step"] == "failed" for s in steps) and not cases.decisions(con, cs[0]["case_id"]), "with the cap reached the case stays open and nothing was decided", "hq/governor.py, think/session.py")
        _evidence_clean(w, c)
    finally:
        w.close()


def drill_follow_up(c) -> None:
    """One case is looked at again by its date, another by an event that arrives."""
    S = sessions(14)
    fall = S[3]
    pend = S[7].isoformat()
    ts = D.dt(S[8], 11, 0)

    def answers(case, n):
        if case["isin"] == FMCG1:
            return _answer("unclear", "wait", case["symbol"], pending="the quarterly result", pending_date=pend if n == 1 else "")
        return _answer("unclear", "wait", case["symbol"], pending="a board decision", likely="even")
    w = World("follow_up", answers, shocks=[(FMCG1, fall, 0.72), (FMCG2, fall, 0.72)],
              events=[(ts, FMCG2, "regulatory_action", "medium", "SYNFMCG2 is asked by the regulator to explain a disclosure (drill)", "drill-follow-event")])
    try:
        w.run(S[13])
        from pflab.think import cases
        con = w.con
        for isin, label in ((FMCG1, "by its date"), (FMCG2, "by an event")):
            cs = [x for x in cases._rows(con, "think_cases_s84", cases._CASE) if x["isin"] == isin and x["state"] != "noticed"]
            c.ok(bool(cs), f"a case exists for the name looked at {label}", "think/watch.py")
            if cs:
                n = w.scen.n.get(cs[0]["case_id"], 0)
                c.ok(n >= 2, f"the case was thought through again {label} ({n} answers)", "think/session.py follow_up / think/watch.py join")
        _evidence_clean(w, c)
    finally:
        w.close()


def drill_bet_sizing(c) -> None:
    """A bet whose worst case does not fit 1% of the whole book is sized down; one that cannot be sized to the minimum trade is refused."""
    S = sessions(6)
    w = World("bet_sizing", lambda case, n: _answer("temporary", "buy_in_parts", case.get("symbol") or "X"), tag="bet_sizing")
    try:
        w.run(S[3])
        from pflab.think import cases, odds, rule
        con = w.con
        asof = S[3]
        out = []
        for isin, free in ((PICK1, 10_000_000.0), (PICK1, 3_000.0), (PICK2, 0.0)):
            cid = cases.open_case(con, D.dt(asof, 16), market="IN", kind="dip", isin=isin, symbol=SYM[isin], title=f"a chance on {SYM[isin]} (drill)", opened_by="drill")
            ans = _answer("temporary", "buy_in_parts", SYM[isin])
            r = rule.decide(con, cid, ans, asof, reserve_free_inr=free)
            out.append((SYM[isin], free, r["rule_option"], r.get("refused"), round(r["size_inr"]), r.get("guards", [])[:2]))
            oc = (r.get("outcome") or {})
            if r["rule_option"] == "buy_in_parts":
                whole = odds.whole_book(con, asof)
                c.ok(oc.get("worst_inr", 0) >= -0.01 * whole * (1 + 1e-6), f"the bet's worst case Rs {oc.get('worst_inr', 0):,.0f} fits 1% of the whole book (Rs {0.01 * whole:,.0f}) with a reserve of Rs {free:,.0f}", "think/rule.py _buy")
        c.note(f"decisions: {out}")
        c.ok(any(o[2] == "buy_in_parts" for o in out), "with room a bet is sized and placed", "think/rule.py")
        c.ok(out[-1][2] in ("nothing", "wait") and out[-1][3], f"with no free reserve the bet is refused ({out[-1][2]}, refused {out[-1][3]})", "think/rule.py")
        _evidence_clean(w, c)
    finally:
        w.close()


def _seed_scored_cases(con, n: int, beats: bool, asof: date) -> List[int]:
    """`n` closed cases with a decision each, dated far enough back in the profile's own history for 5, 20 and 60 sessions to have passed (the synthetic closes exist), rule track `beats` doing nothing
    or not. Decided through the case store's plain API (the same rows the loop writes)."""
    from pflab.think import cases
    ids = []
    held = [FMCG1, FMCG2, CAPG1, IT1]
    from pflab import markets
    m = markets.get("IN")
    d = asof
    for _ in range(90):
        d = m.previous_session(d)
    for k in range(n):
        isin = held[k % 4]
        day = d
        for _ in range(k):
            day = m.next_session(day)
        cid = cases.open_case(con, D.dt(day, 16), market="IN", kind="dip", isin=isin, symbol=SYM[isin], title=f"seeded case {k} (drill)", opened_by="drill")
        opt = "sell" if beats else "hold"
        cases.add_option(con, cid, D.dt(day, 16), track="rule", isin=isin, symbol=SYM[isin], option=opt, worst_inr=-1000.0, likely_inr=500.0, best_inr=1500.0, expected_inr=400.0, worst_pct_book=0.002, size_inr=20000.0, chosen=True)
        cases.add_option(con, cid, D.dt(day, 16), track="model", isin=isin, symbol=SYM[isin], option="hold", worst_inr=-1000.0, likely_inr=500.0, best_inr=1500.0, expected_inr=400.0, worst_pct_book=0.002, chosen=True)
        cases.record_decision(con, cid, day, isin=isin, symbol=SYM[isin], rule_option=opt, model_option="hold", acted_option=opt, reason="seeded")
        cases.close_case(con, cid, day + timedelta(days=1), "seeded")
        ids.append(cid)
    return ids


def drill_calibration_and_advisory(c_cal, c_adv) -> None:
    """The word table does not move before 20 scored cases and moves after them, in bounded steps; the advisory fallback switches on when the rule's track is behind "do nothing" after 20 and off when ahead."""
    S = sessions(4)
    w = World("calibration", lambda case, n: _answer("market_fear", "hold", case.get("symbol") or "X"), tag="calibration")
    try:
        w.run(S[1])
        from pflab.think import cases, score
        con = w.con
        asof = S[1]
        cases.seed_calibration(con, asof)
        before = dict(cases.probabilities(con))
        _seed_scored_cases(con, 10, True, asof)
        n10 = score.score_due(con, asof)
        score.calibrate(con, asof)
        c_cal.ok(cases.probabilities(con) == before, "with fewer than 20 scored decisions the word table did not move", "think/score.py calibrate")
        c_adv.ok(not score.advisory(con, asof), "with fewer than 20 scored decisions the loop is not advisory", "think/score.py advisory")
        _seed_scored_cases(con, 14, True, asof)
        score.score_due(con, asof)
        sc = score.scorecard(con)
        c_cal.note(f"scorecard after 24 seeded decisions: {sc}")
        r = score.calibrate(con, asof)
        after = cases.probabilities(con)
        steps = {k: round(abs(after[k] - before[k]), 4) for k in before}
        c_cal.ok(any(v > 0 for v in steps.values()) or r.get("moved") is False, f"after 20+ scored decisions the word table was corrected ({steps})", "think/score.py calibrate")
        c_cal.ok(all(v <= 0.05 + 1e-9 for v in steps.values()) and all(0.02 <= p <= 0.98 for p in after.values()), "each step is at most 0.05 and stays inside [0.02, 0.98]", "think/score.py calibrate")
        c_adv.note(f"advisory with the rule ahead: {score.advisory(con, asof)}")
        w2 = None
        _evidence_clean(w, c_cal)
    finally:
        w.close()
