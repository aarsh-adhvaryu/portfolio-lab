"""T8 LEARN: score, calibrate, recalibrate (S84, A65): code only, no model. `docs/protocols/s84_thinking_live_protocol.md` sections 5 to 7 are this file in words.

    score_due(con, day) -> int       at 5, 20 and 60 sessions after each decision: the result in rupees of EVERY option the case stored for the name, against doing nothing, after tax; the rule's
                                     track, the model's track and the options not taken. Rows in `think_scores_s84` (idempotent: a decision, horizon, track and option are scored once)
    calibrate(con, day) -> dict      how often each likelihood word came true; once a word has `calibration_min_scored` scored cases its probability is corrected (at most once a month, a step of
                                     at most `calibration_step` toward the observed rate, inside [floor, ceiling]) in `think_calibration_s84`
    scorecard(con) -> dict           {"scored", "vs_nothing_inr", "rule_track", "model_track", "by_word", "skips_ran", "skips_fell", "model_vs_rule", "text"}
    advisory(con, day) -> bool       the safe fallback: after `advisory_after_scored` scored decisions, the rule's track behind "do nothing" after tax -> the loop only reports (thesis-break sales act)
    protocol_ok(con), register(con, now)    the learner's registration (`learner/s84.py`)

How a result is valued. A decision stored its options with their worst, likely and best rupees (`think_options_s84`, from `odds.option_table`): three points on a curve of rupees against the move
of the price over the decision horizon, after tax and charges. The realised move (the close `h` sessions after the decision's day against the decision day's close, from the stored prices) is read
off that curve (straight lines between the three points, the end slopes beyond them), so each option is valued with the tax and charges the decision itself saw and without the lots the sale may
have since changed. "Do nothing" is the stored hold (a held name) or zero (a name not held). Every figure is an estimate.
The model's answer (its likelihood words) is read from the case's stored step (`payload` with the answer, under the key `answer` or as the payload itself).
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import numpy as np

from pflab import think
from pflab.think import cases, odds

HORIZONS = (5, 20, 60)
NOTHING = ("hold", "freeze", "wait", "nothing")
WARNING = "estimate: each option is valued on the curve its decision stored (worst, likely, best) at the realised move, after tax and charges"


def _cfg() -> dict:
    from pflab.think import rule
    return rule.cfg()


def _day(x) -> date:
    return x.date() if isinstance(x, datetime) else x


# --- the curve -----------------------------------------------------------------------------------------------------------------------------------------------------------------

def curve_value(m: float, pts: List[tuple]) -> float:
    """The rupees at move `m` on the curve through (move, rupees) points: straight lines between them, the end slopes beyond them, a flat line when the moves coincide."""
    pts = sorted(pts)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    if xs[-1] - xs[0] < 1e-12:
        return float(sum(ys) / len(ys))
    if m < xs[0]:
        k = (ys[1] - ys[0]) / (xs[1] - xs[0]) if xs[1] - xs[0] > 1e-12 else 0.0
        return float(ys[0] + k * (m - xs[0]))
    if m > xs[-1]:
        k = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2]) if xs[-1] - xs[-2] > 1e-12 else 0.0
        return float(ys[-1] + k * (m - xs[-1]))
    return float(np.interp(m, xs, ys))


def _moves(con, case: dict, isin, symbol, decided_on: date, root=None) -> Optional[List[float]]:
    """The three moves (10th, 50th, 90th percentile at the decision horizon) the decision saw, recomputed point in time as of its day. The history scan takes seconds on the real panel and the
    scoring and the calibration both need it every day, so the answer is kept once as a step `moves` of the case (dated the decision day: it is not "a step today"); a later call reads it back."""
    cid = case.get("case_id")
    key = {"isin": isin, "day": str(decided_on)}
    if cid is not None:
        try:
            for st in cases.steps(con, cid):
                if st["step"] == "moves":
                    p = json.loads(st.get("payload_json") or "{}")
                    if p.get("isin") == isin and p.get("day") == key["day"] and p.get("moves"):
                        return [float(x) for x in p["moves"]]
        except Exception:
            pass
    try:
        market = (case.get("market") or "IN").upper()
        kind, move, window = odds.case_kind_move(con, case)
        r = odds.base_rates(con, kind, move=move, isin=isin, asof=decided_on, market=market, symbol=symbol, window=window, root=root)
        mv = odds._scenario_moves(r, int(odds.PARAMS["outcome_horizon_sessions"]))
    except Exception:
        return None
    if cid is not None:
        try:
            cases.add_step(con, cid, datetime.combine(decided_on, datetime.min.time()) + timedelta(hours=23, minutes=59), "moves", payload={**key, "moves": mv, "basis": r.get("basis")})
        except Exception:
            pass
    return mv


def _path(con, market: str, isin, symbol, d0: date, day: date, root=None):
    """The closes from the decision day (or the last close before it) up to `day`: a Series indexed by Timestamp."""
    s = odds.closes(con, market, isin, symbol, day, 500, root)
    if (s is None or not len(s)) and str(isin or "").startswith(("MARKET:", "MACRO:")):      # S85: a market or macro case is scored on its index's path
        s = proxy_closes(con, isin, symbol, day, root)
    if s is None or not len(s):
        return s
    before = s[s.index <= np.datetime64(d0)]
    after = s[s.index > np.datetime64(d0)]
    if before.empty:
        return s.iloc[0:0]
    return s[s.index >= before.index[-1]]


def _answer_of(con, case_id: int) -> dict:
    """The model's validated answer, from the case's stored steps (the newest step that carries one)."""
    ans = {}
    for st in cases.steps(con, case_id):
        try:
            p = json.loads(st.get("payload_json") or "{}")
        except Exception:
            continue
        a = p.get("answer") if isinstance(p.get("answer"), dict) else p
        if isinstance(a, dict) and any(k in a for k in ("choices", "options", "names", "holdings")):
            ans = a
    return odds.norm_answer(ans) if ans else {"choices": []}


# --- scoring ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def _option_curves(con, case_id: int, isin: Optional[str]) -> Dict[str, dict]:
    """The stored rows of the name, one per option (the rule's rows first, then the model's, then the others): {option: {"worst","likely","best"}}."""
    out: Dict[str, dict] = {}
    rows = [o for o in cases.options(con, case_id) if (o["isin"] == isin or isin is None)]
    for track in ("rule", "model", "alt"):
        for o in rows:
            if o["track"] == track and o["option"] not in out:
                out[o["option"]] = {"worst": o["worst_inr"], "likely": o["likely_inr"], "best": o["best_inr"], "size_inr": o["size_inr"]}
    for o in rows:
        out.setdefault(o["option"], {"worst": o["worst_inr"], "likely": o["likely_inr"], "best": o["best_inr"], "size_inr": o["size_inr"]})
    return out


def _done(con) -> set:
    return {(int(d), int(h), t, o) for d, h, t, o in con.execute("SELECT decision_id, horizon_sessions, track, option FROM think_scores_s84").fetchall()}


def score_due(con, day, root=None) -> int:
    """Score every decision whose 5, 20 or 60 sessions have elapsed (idempotent). Returns the number of rows written. Never raises on one bad decision."""
    from pflab.pm.store import next_id
    day = _day(day)
    done, n = _done(con), 0
    for d in cases.decisions(con):
        try:
            n += _score_decision(con, d, day, done, root, next_id)
        except Exception:
            continue
    try:
        n += score_shadow(con, day, root)
    except Exception:
        pass
    try:                                                                      # S85 E7: his overrules, scored on the `user` track beside the loop's own choice
        from pflab.think import chat_hooks
        n += chat_hooks.score_user(con, day, root)
    except Exception:
        pass
    return n


SHADOW_BASE = 1_000_000_000                       # a shadow row scores under decision_id = SHADOW_BASE + shadow_id (tracks `shadow:<engine>` and `shadow_rule:<engine>`)


def score_shadow(con, day, root=None) -> int:
    """S85: the shadow engines' choices scored at 5, 20 and 60 sessions exactly like the model's and the rule's (their own tracks, one pair per engine). Idempotent."""
    from pflab.pm.store import next_id
    day = _day(day)
    try:
        rows = con.execute("SELECT shadow_id, case_id, engine, decided_on, isin, symbol, option, rule_option FROM think_shadow_s85 WHERE option IS NOT NULL").fetchall()
    except Exception:
        return 0
    done, n = _done(con), 0
    for sid, cid, eng, d0, isin, sym, opt, ropt in rows:
        d = {"decision_id": SHADOW_BASE + int(sid), "case_id": cid, "isin": isin, "symbol": sym, "decided_on": d0, "rule_option": ropt, "model_option": opt,
             "picks": [(f"shadow_rule:{eng}", ropt), (f"shadow:{eng}", opt)]}
        try:
            n += _score_decision(con, d, day, done, root, next_id)
        except Exception:
            continue
    return n


def _score_decision(con, d: dict, day: date, done: set, root, next_id) -> int:
    case = cases.get_case(con, d["case_id"]) or {}
    market = (case.get("market") or "IN").upper()
    isin, symbol, d0 = d["isin"] or case.get("isin"), d["symbol"] or case.get("symbol"), _day(d["decided_on"])
    s = _path(con, market, isin, symbol, d0, day, root)
    if s is None or len(s) < 2:
        return 0
    due = [h for h in HORIZONS if len(s) > h and not any(k[0] == int(d["decision_id"]) and k[1] == h for k in done)]
    if not due:                                                       # everything due is scored already: no scan of the history
        return 0
    curves = _option_curves(con, d["case_id"], isin)
    if not curves:
        return 0
    mv = _moves(con, case, isin, symbol, d0, root)
    if mv is None:
        return 0
    wrote = 0
    p0 = float(s.iloc[0])
    nothing_key = next((k for k in NOTHING if k in curves), None)
    for h in HORIZONS:
        if len(s) <= h:
            continue
        m = float(s.iloc[h]) / p0 - 1.0
        val = {o: curve_value(m, [(mv[0], c["worst"]), (mv[1], c["likely"]), (mv[2], c["best"])]) for o, c in curves.items()}
        base = val[nothing_key] if nothing_key else 0.0
        picks = d.get("picks") or [("rule", d["rule_option"]), ("model", d["model_option"])]
        for o, v in val.items():
            tracks = [t for t, opt in picks if opt == o and opt is not None] or ([] if d.get("picks") else ["alt"])
            for t in tracks:
                if (int(d["decision_id"]), h, t, o) in done:
                    continue
                con.execute("INSERT INTO think_scores_s84 VALUES (?,?,?,?,?,?,?,?)", [next_id(con, "think_scores_s84", "score_id"), d["decision_id"], h, t, o, float(v), float(v - base), day])
                done.add((int(d["decision_id"]), h, t, o))
                wrote += 1
        for t, opt in picks:                                          # a chosen option with no stored row (the model chose something the table did not hold): scored as nothing, said so
            if opt is not None and opt not in val and (int(d["decision_id"]), h, t, opt) not in done:
                con.execute("INSERT INTO think_scores_s84 VALUES (?,?,?,?,?,?,?,?)", [next_id(con, "think_scores_s84", "score_id"), d["decision_id"], h, t, opt, float(base), 0.0, day])
                done.add((int(d["decision_id"]), h, t, opt))
                wrote += 1
    return wrote


# --- the scorecard ----------------------------------------------------------------------------------------------------------------------------------------------------------

def _track(con, track: str) -> dict:
    out = {"by_horizon": {}}
    for h in HORIZONS:
        r = con.execute("SELECT count(DISTINCT decision_id), coalesce(sum(vs_nothing_inr), 0) FROM think_scores_s84 WHERE track=? AND horizon_sessions=?", [track, h]).fetchone()
        out["by_horizon"][h] = {"n": int(r[0]), "vs_nothing_inr": float(r[1])}
    out["n"], out["vs_nothing_inr"] = out["by_horizon"][20]["n"], out["by_horizon"][20]["vs_nothing_inr"]
    right = con.execute("""SELECT count(*) FROM think_scores_s84 t WHERE t.track=? AND t.horizon_sessions=20 AND t.result_inr >= (SELECT max(result_inr) FROM think_scores_s84 u
                           WHERE u.decision_id=t.decision_id AND u.horizon_sessions=20) - 1e-9""", [track]).fetchone()[0]
    out["right"] = int(right)
    return out


def _skips(con, ran_pts: float) -> dict:
    """Skips that ran beside skips that fell: the passed-on names (`skips_s83`) scored at their longest horizon against the index (`pick_scores_s83`, kind skip)."""
    try:
        rows = con.execute("""SELECT s.ref_id, s.return_pct, s.index_return_pct FROM pick_scores_s83 s WHERE s.kind='skip' AND s.horizon_months = (SELECT max(horizon_months) FROM pick_scores_s83 x
                              WHERE x.kind='skip' AND x.ref_id=s.ref_id AND x.market=s.market) """).fetchall()
        total = int(con.execute("SELECT count(*) FROM skips_s83").fetchone()[0])
    except Exception:
        return {"skips_ran": 0, "skips_fell": 0, "skips_scored": 0, "skips_total": 0}
    ran = sum(1 for _r, a, b in rows if a is not None and b is not None and a - b >= ran_pts)
    fell = sum(1 for _r, a, b in rows if a is not None and b is not None and a - b < 0)
    return {"skips_ran": ran, "skips_fell": fell, "skips_scored": len(rows), "skips_total": total}


def _paired(con) -> dict:
    """The model's track against the rule's, decision by decision at 20 sessions (vs nothing): the paired t against the learner's bar."""
    rows = con.execute("""SELECT a.decision_id, a.vs_nothing_inr, b.vs_nothing_inr FROM think_scores_s84 a JOIN think_scores_s84 b ON a.decision_id=b.decision_id AND a.horizon_sessions=b.horizon_sessions
                          WHERE a.track='model' AND b.track='rule' AND a.horizon_sessions=20 AND a.option <> b.option""").fetchall()
    diffs = [float(m) - float(r) for _d, m, r in rows]
    out = {"n": len(diffs), "sum_inr": float(sum(diffs)), "t": None, "bar": None, "beats": False}
    try:
        from pflab.learner import counter
        out["bar"] = counter.t_needed(counter.n_tests(con))
    except Exception:
        pass
    if len(diffs) >= 2:
        sd = float(np.std(diffs, ddof=1))
        if sd > 0:
            out["t"] = float(np.mean(diffs) / (sd / math.sqrt(len(diffs))))
            out["beats"] = bool(out["t"] > (out["bar"] if out["bar"] is not None else 2.0) and len(diffs) >= _cfg()["calibration_min_scored"])
    return out


def scorecard(con) -> dict:
    """{"scored", "vs_nothing_inr", "rule_track", "model_track", "by_word", "skips_ran", "skips_fell", "model_vs_rule", "calibration_n", "text"}. A count under 20 is a count, not a rate."""
    c = _cfg()
    rule_t, model_t = _track(con, "rule"), _track(con, "model")
    sk = _skips(con, float(think.settings()["missed_run_pts"]))
    by_word = {}
    try:
        for w, p, n, hits in con.execute("SELECT word, probability, n, hits FROM think_calibration_s84").fetchall():
            by_word[w] = {"probability": float(p), "n": int(n or 0), "hits": int(hits or 0), "hit_rate": (hits / n) if n and n >= c["calibration_min_scored"] else None}
    except Exception:
        pass
    pair = _paired(con)
    n = rule_t["n"]
    base = (f"Decisions scored at 20 sessions: {n}; the rule's choices against doing nothing: Rs {rule_t['vs_nothing_inr']:,.0f} after tax"
            + (f" ({rule_t['right']} of {n} were the best of the menu)" if n else "") + ("." if n >= c["calibration_min_scored"] else " (under 20: a count, not a rate)."))
    skips = (f" Skipped ideas that went on to beat their index by {think.settings()['missed_run_pts']:g} points or more: {sk['skips_ran']}; that fell: {sk['skips_fell']} (of {sk['skips_scored']} scored)."
             if sk["skips_total"] else "")
    model = (f" The model's own choices beat the rule's (paired t {pair['t']:.1f} over {pair['n']}): who decides is his choice." if pair["beats"] else "")
    return {"scored": n, "vs_nothing_inr": rule_t["vs_nothing_inr"], "rule_track": rule_t, "model_track": model_t, "by_word": by_word, **sk, "model_vs_rule": pair, "by_engine": by_engine(con, rule_t, model_t),
            "advisory": advisory(con, date.today()), "text": base + skips + model, "label": WARNING}


def advisory(con, day=None) -> bool:
    """The safe fallback (T8): True when the loop only reports (only thesis-break sales act). Forced by `[think] mode = "advisory"` (his to set); otherwise after `advisory_after_scored` scored
    decisions with the rule's track behind "do nothing" after tax at 20 sessions (the sum below zero); it is False again as soon as that sum is zero or above."""
    c = _cfg()
    if str(think.settings().get("mode", "live")) == "advisory":
        return True
    t = _track(con, "rule")
    return t["n"] >= int(c["advisory_after_scored"]) and t["vs_nothing_inr"] < 0.0


# --- calibration -----------------------------------------------------------------------------------------------------------------------------------------------------------

def _scenario_hit(scn: str, m: float, mv: List[float]) -> bool:
    mw, ml, mb = mv
    if scn == "worst":
        return m <= mw
    if scn == "best":
        return m >= mb
    return (mw + ml) / 2.0 <= m <= (ml + mb) / 2.0


def by_engine(con, rule_t: Optional[dict] = None, model_t: Optional[dict] = None) -> dict:
    """S85: two engines side by side: {engine: {"in_use": bool, "rule_track", "model_track", "by_word"}}. The in-use engine's tracks are `rule` and `model`; a shadow engine's are `shadow_rule:<e>` and
    `shadow:<e>` (the model's choice and what the rule does on its answer). The calibration words are per engine (`think_calibration_engine_s85`; claude's rows stay in `think_calibration_s84`)."""
    try:
        from pflab.llm import gateway
        cur = gateway.current_engine(con)
    except Exception:
        cur = "claude"
    out = {cur: {"in_use": True, "rule_track": rule_t or _track(con, "rule"), "model_track": model_t or _track(con, "model")}}
    try:
        engs = [r[0] for r in con.execute("SELECT DISTINCT engine FROM think_shadow_s85 ORDER BY engine").fetchall()]
    except Exception:
        engs = []
    for e in engs:
        if e != cur:
            out[e] = {"in_use": False, "rule_track": _track(con, f"shadow_rule:{e}"), "model_track": _track(con, f"shadow:{e}")}
    for e, row in out.items():
        words = {}
        try:
            rows = con.execute("SELECT word, probability, n, hits FROM think_calibration_engine_s85 WHERE engine=?", [e]).fetchall() if e != "claude" else                 con.execute("SELECT word, probability, n, hits FROM think_calibration_s84").fetchall()
            for w, p, n, hits in rows:
                words[w] = {"probability": float(p), "n": int(n or 0), "hits": int(hits or 0)}
        except Exception:
            pass
        row["by_word"] = words
    return out


def tally_engine(con, day, engine: str, root=None) -> Dict[str, dict]:
    """`tally` for a shadow engine: its own stated words against what happened at 20 sessions."""
    out = {w: {"n": 0, "hits": 0} for w in think.WORDS}
    day = _day(day)
    for sid, cid, d0, isin, sym, wj in con.execute("SELECT shadow_id, case_id, decided_on, isin, symbol, words_json FROM think_shadow_s85 WHERE engine=? AND option IS NOT NULL", [engine]).fetchall():
        if not con.execute("SELECT 1 FROM think_scores_s84 WHERE decision_id=? AND horizon_sessions=20 LIMIT 1", [SHADOW_BASE + int(sid)]).fetchone():
            continue
        try:
            words = json.loads(wj or "{}")
        except Exception:
            continue
        case = cases.get_case(con, cid) or {}
        d0 = _day(d0)
        s = _path(con, (case.get("market") or "IN").upper(), isin, sym, d0, day, root)
        mv = _moves(con, case, isin, sym, d0, root)
        if s is None or len(s) <= 20 or mv is None:
            continue
        m = float(s.iloc[20]) / float(s.iloc[0]) - 1.0
        for scn in ("worst", "likely", "best"):
            w = words.get(scn)
            if w in out:
                out[w]["n"] += 1
                out[w]["hits"] += int(_scenario_hit(scn, m, mv))
    return out


def calibrate_engines(con, day, root=None) -> dict:
    """The shadow engines' own likelihood tables: each starts from the default table and is moved like claude's (`calibrate`): at most once a month, a step of at most `calibration_step` toward its
    observed rate, inside [floor, ceiling], only after `calibration_min_scored` cases. -> {engine: {word: {n, hits, p_before, p_after, moved}}}"""
    day, c = _day(day), _cfg()
    out = {}
    try:
        engs = [r[0] for r in con.execute("SELECT DISTINCT engine FROM think_shadow_s85").fetchall()]
    except Exception:
        return out
    for e in engs:
        if e == "claude":
            continue
        t = tally_engine(con, day, e, root)
        out[e] = {}
        for w in think.WORDS:
            row = con.execute("SELECT probability, updated_on FROM think_calibration_engine_s85 WHERE engine=? AND word=?", [e, w]).fetchone()
            if row is None:
                con.execute("INSERT INTO think_calibration_engine_s85 VALUES (?,?,?,?,?,?)", [e, w, think.WORD_P[w], 0, 0, day - timedelta(days=60)])
                row = (think.WORD_P[w], day - timedelta(days=60))
            p0, last = float(row[0]), row[1]
            n, hits = t[w]["n"], t[w]["hits"]
            p1, did = p0, False
            if n >= int(c["calibration_min_scored"]) and (last is None or (day - last).days >= 30):
                step = max(-c["calibration_step"], min(c["calibration_step"], hits / n - p0))
                p1 = min(c["calibration_ceiling"], max(c["calibration_floor"], p0 + step))
                did = abs(p1 - p0) > 1e-12
            con.execute("UPDATE think_calibration_engine_s85 SET probability=?, n=?, hits=?, updated_on=? WHERE engine=? AND word=?", [p1, n, hits, day if did else last, e, w])
            out[e][w] = {"n": n, "hits": hits, "p_before": p0, "p_after": p1, "moved": did}
    return out


def tally(con, day, root=None) -> Dict[str, dict]:
    """For each likelihood word the model used, over the decisions scored at 20 sessions: how many times it stood for a scenario (n) and how many times the scenario came true (hits)."""
    out = {w: {"n": 0, "hits": 0} for w in think.WORDS}
    seen = set()
    for d in cases.decisions(con):
        if (d["case_id"], d["isin"]) in seen:
            continue
        seen.add((d["case_id"], d["isin"]))
        if not con.execute("SELECT 1 FROM think_scores_s84 WHERE decision_id=? AND horizon_sessions=20 LIMIT 1", [d["decision_id"]]).fetchone():
            continue
        case = cases.get_case(con, d["case_id"]) or {}
        ans = _answer_of(con, d["case_id"])
        ch = next((c for c in ans["choices"] if c.get("isin") == d["isin"]), None) or (ans["choices"][0] if ans["choices"] else None)
        if not ch or not ch.get("words"):
            continue
        d0 = _day(d["decided_on"])
        market = (case.get("market") or "IN").upper()
        s = _path(con, market, d["isin"], d["symbol"], d0, day, root)
        mv = _moves(con, case, d["isin"], d["symbol"], d0, root)
        if s is None or len(s) <= 20 or mv is None:
            continue
        m = float(s.iloc[20]) / float(s.iloc[0]) - 1.0
        for scn, w in ch["words"].items():
            if w in out:
                out[w]["n"] += 1
                out[w]["hits"] += int(_scenario_hit(scn, m, mv))
    return out


def calibrate(con, day, root=None) -> dict:
    """Recompute each word's count and hits from the scored decisions and, for a word with at least `calibration_min_scored` cases and no correction in the last 30 days, move its probability
    toward the observed rate by at most `calibration_step`, inside [floor, ceiling]. -> {"words": {word: {n, hits, p_before, p_after, moved}}, "moved": [words]}"""
    day, c = _day(day), _cfg()
    cases.seed_calibration(con, day - timedelta(days=60))
    t = tally(con, day, root)
    out, moved = {}, []
    for w in think.WORDS:
        row = con.execute("SELECT probability, updated_on FROM think_calibration_s84 WHERE word=?", [w]).fetchone()
        p0, last = float(row[0]), row[1]
        n, hits = t[w]["n"], t[w]["hits"]
        p1, did = p0, False
        if n >= int(c["calibration_min_scored"]) and (last is None or (day - last).days >= 30):
            obs = hits / n
            step = max(-c["calibration_step"], min(c["calibration_step"], obs - p0))
            p1 = min(c["calibration_ceiling"], max(c["calibration_floor"], p0 + step))
            did = abs(p1 - p0) > 1e-12
        con.execute("UPDATE think_calibration_s84 SET n=?, hits=?, probability=?, updated_on=? WHERE word=?", [n, hits, p1, day if did else last, w])
        out[w] = {"n": n, "hits": hits, "p_before": p0, "p_after": p1, "moved": did}
        if did:
            moved.append(w)
    try:
        engines = calibrate_engines(con, day, root)
    except Exception:
        engines = {}
    return {"words": out, "moved": moved, "engines": engines}


# --- registration ----------------------------------------------------------------------------------------------------------------------------------------------------------

def protocol_ok(con) -> dict:
    from pflab.learner import s84
    return s84.protocol_ok(con)


def register(con, now: datetime) -> list:
    from pflab.learner import s84
    return s84.register_thinking_live(con, now)


# --- S85 replay3: a price path for a market or macro case ------------------------------------------------------------------------------------------------------------------------

PROXY_NOTE = "a market or macro case is scored on the close of the index (or series) it names: MARKET:IN the Nifty 500 total return index, MARKET:US SPY, MACRO:<series> the stored series"


def proxy_closes(con, isin, symbol, asof, root=None):
    """The closes (a Series indexed by Timestamp, dated on or before `asof`) of the index or series a MARKET:/MACRO: pseudo-name stands for; an empty Series when it has none stored.
    MARKET:<IN|US> is the watch's own index (`watch._index`: the Nifty 500 total return index, SPY); MACRO:<KEY> is the stored series of `story.series`. Point in time: nothing after `asof`."""
    import pandas as pd
    key = str(isin or "")
    s = None
    try:
        if key.startswith("MARKET:"):
            from pflab.think import watch
            s = watch._index(key.split(":", 1)[1].upper(), root)
        elif key.startswith("MACRO:"):
            from pflab.story import series
            s = series.load(key.split(":", 1)[1], root)
    except Exception:
        s = None
    if s is None or not len(s):
        return pd.Series(dtype=float)
    s = s.copy()
    s.index = pd.to_datetime(s.index).normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s[s.index <= pd.Timestamp(_day(asof))].dropna()
