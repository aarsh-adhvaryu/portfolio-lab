"""The case store of the thinking loop (S84): the plain API every other `think` module uses. Tables are in `pm/mig_s79/m_think84.py`. Ids come from `store.next_id`.

A case is a situation thought through. States: noticed (stored, not examined), open (being thought through), waiting (a pending event or a look due), acted, closed, advisory (the loop is advisory
and the case only reports). `klass` is the model's class (`think.CLASSES`) once it has read the case. Every model step is stored with the engine, model, thinking level, cost and cached tokens.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from pflab import think

_SIG = ("signal_id", "case_id", "day", "ts", "market", "isin", "symbol", "signal", "value", "threshold", "surprise", "exposure_inr", "score", "detail_json", "status")
_CASE = ("case_id", "opened_on", "opened_at", "market", "kind", "isin", "symbol", "title", "state", "klass", "pending", "next_look_on", "next_look_cond", "exposure_inr", "exposure_pct",
         "score", "closed_on", "closed_reason", "opened_by", "summary", "names_json")


def _id(con, table: str, col: str) -> int:
    from pflab.pm.store import next_id
    return next_id(con, table, col)


def _rows(con, table: str, cols, where: str = "", args: Optional[list] = None, order: str = "") -> List[dict]:
    out = []
    for r in con.execute(f"SELECT {', '.join(cols)} FROM {table} {where} {order}", args or []).fetchall():
        d = dict(zip(cols, r))
        for k, v in list(d.items()):
            if isinstance(v, (date, datetime)):
                d[k + "_s"] = str(v)
        out.append(d)
    return out


# --- signals ------------------------------------------------------------------------------------------------------------------------------------------------------------------

def record_signal(con, now: datetime, *, market: str, isin: str, symbol: str, signal: str, value: float, threshold: float, surprise: float, exposure_inr: float, score: float,
                  detail: Optional[dict] = None, status: str = "new") -> int:
    sid = _id(con, "think_signals_s84", "signal_id")
    con.execute("INSERT INTO think_signals_s84 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [sid, None, now.date(), now, market, isin, symbol, signal, float(value), float(threshold), float(surprise),
                float(exposure_inr), float(score), json.dumps(detail or {}, default=str), status])
    return sid


def signals(con, *, day: Optional[date] = None, case_id: Optional[int] = None, status: Optional[str] = None) -> List[dict]:
    w, a = [], []
    for col, v in (("day", day), ("case_id", case_id), ("status", status)):
        if v is not None:
            w.append(f"{col}=?")
            a.append(v)
    return _rows(con, "think_signals_s84", _SIG, ("WHERE " + " AND ".join(w)) if w else "", a, "ORDER BY signal_id")


def set_signal(con, signal_id: int, *, status: Optional[str] = None, case_id: Optional[int] = None) -> None:
    if status is not None:
        con.execute("UPDATE think_signals_s84 SET status=? WHERE signal_id=?", [status, signal_id])
    if case_id is not None:
        con.execute("UPDATE think_signals_s84 SET case_id=? WHERE signal_id=?", [case_id, signal_id])


# --- cases --------------------------------------------------------------------------------------------------------------------------------------------------------------------

def open_case(con, now: datetime, *, market: str, kind: str, isin: Optional[str], symbol: Optional[str], title: str, exposure_inr: float = 0.0, exposure_pct: float = 0.0, score: float = 0.0,
              opened_by: str = "watch", signal_ids: Optional[List[int]] = None, state: str = "open", names: Optional[List[str]] = None) -> int:
    cid = _id(con, "think_cases_s84", "case_id")
    con.execute("INSERT INTO think_cases_s84 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [cid, now.date(), now, market, kind, isin, symbol, title[:300], state, None, None, None, None, float(exposure_inr), float(exposure_pct), float(score), None, None, opened_by, None,
                 json.dumps(names or [], default=str)])
    for sid in signal_ids or []:
        set_signal(con, sid, case_id=cid, status="joined" if state != "open" else "examined")
    return cid


def get_case(con, case_id: int) -> Optional[dict]:
    r = _rows(con, "think_cases_s84", _CASE, "WHERE case_id=?", [case_id])
    if not r:
        return None
    c = r[0]
    c["signals"] = signals(con, case_id=case_id)
    c["steps"] = steps(con, case_id)
    c["options"] = options(con, case_id)
    c["decisions"] = decisions(con, case_id)
    return c


def open_cases(con, market: Optional[str] = None, isin: Optional[str] = None) -> List[dict]:
    """Cases not closed (noticed cases are NOT included: they were never examined)."""
    w, a = ["state IN ('open','waiting','acted','advisory')"], []
    if market:
        w.append("market=?")
        a.append(market)
    if isin:
        w.append("isin=?")
        a.append(isin)
    return _rows(con, "think_cases_s84", _CASE, "WHERE " + " AND ".join(w), a, "ORDER BY score DESC, case_id")


def case_for(con, isin: str, kind: Optional[str] = None) -> Optional[dict]:
    """The open case on this name (a new signal on a name with an open case JOINS that case)."""
    for c in open_cases(con, isin=isin):
        if kind is None or c["kind"] == kind:
            return c
    return None


def cases_opened_on(con, day: date) -> int:
    return int(con.execute("SELECT count(*) FROM think_cases_s84 WHERE opened_on=? AND state <> 'noticed'", [day]).fetchone()[0])


def set_case(con, case_id: int, **fields) -> None:
    """Update any of: state, klass, pending, next_look_on, next_look_cond, exposure_inr, exposure_pct, score, summary, names_json, closed_on, closed_reason."""
    ok = {k: v for k, v in fields.items() if k in _CASE and k not in ("case_id", "opened_on", "opened_at")}
    if not ok:
        return
    con.execute("UPDATE think_cases_s84 SET " + ", ".join(f"{k}=?" for k in ok) + " WHERE case_id=?", list(ok.values()) + [case_id])


def close_case(con, case_id: int, day: date, reason: str) -> None:
    set_case(con, case_id, state="closed", closed_on=day, closed_reason=reason[:300])


def looks_due(con, day: date) -> List[dict]:
    """Cases whose next look is on or before `day` (a case with only a condition is reopened by the watch on a new signal, never by the date)."""
    return _rows(con, "think_cases_s84", _CASE, "WHERE state IN ('open','waiting','acted','advisory') AND next_look_on IS NOT NULL AND next_look_on <= ?", [day], "ORDER BY score DESC, case_id")


# --- steps, options, decisions ------------------------------------------------------------------------------------------------------------------------------------------

def add_step(con, case_id: int, now: datetime, step: str, *, engine: str = "", model: str = "", thinking: str = "", cost_rupees: float = 0.0, cached_tokens: int = 0,
             payload: Optional[dict] = None) -> int:
    sid = _id(con, "think_steps_s84", "step_id")
    con.execute("INSERT INTO think_steps_s84 VALUES (?,?,?,?,?,?,?,?,?,?)", [sid, case_id, now, step, engine, model, thinking, float(cost_rupees), int(cached_tokens), json.dumps(payload or {}, default=str)])
    return sid


def steps(con, case_id: int) -> List[dict]:
    return _rows(con, "think_steps_s84", ("step_id", "case_id", "step_at", "step", "engine", "model", "thinking", "cost_rupees", "cached_tokens", "payload_json"), "WHERE case_id=?", [case_id], "ORDER BY step_id")


def add_option(con, case_id: int, now: datetime, *, track: str, isin: Optional[str], symbol: Optional[str], option: str, worst_inr: float, likely_inr: float, best_inr: float, expected_inr: float,
               worst_pct_book: float, size_inr: float = 0.0, reason: str = "", chosen: bool = False) -> int:
    oid = _id(con, "think_options_s84", "option_id")
    con.execute("INSERT INTO think_options_s84 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [oid, case_id, track, isin, symbol, option, float(worst_inr), float(likely_inr), float(best_inr), float(expected_inr),
                float(worst_pct_book), float(size_inr), reason[:500], bool(chosen), now])
    return oid


def options(con, case_id: int) -> List[dict]:
    return _rows(con, "think_options_s84", ("option_id", "case_id", "track", "isin", "symbol", "option", "worst_inr", "likely_inr", "best_inr", "expected_inr", "worst_pct_book", "size_inr", "reason",
                                            "chosen", "created_at"), "WHERE case_id=?", [case_id], "ORDER BY option_id")


def record_decision(con, case_id: int, day: date, *, isin: Optional[str], symbol: Optional[str], rule_option: str, model_option: Optional[str], acted_option: str, order_refs: Optional[list] = None,
                    reason: str = "", advisory: bool = False) -> int:
    did = _id(con, "think_decisions_s84", "decision_id")
    con.execute("INSERT INTO think_decisions_s84 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [did, case_id, day, isin, symbol, rule_option, model_option, acted_option, bool(model_option and model_option != rule_option),
                json.dumps(order_refs or [], default=str), reason[:500], bool(advisory)])
    return did


def decisions(con, case_id: Optional[int] = None) -> List[dict]:
    cols = ("decision_id", "case_id", "decided_on", "isin", "symbol", "rule_option", "model_option", "acted_option", "differs", "order_refs_json", "reason", "advisory")
    return _rows(con, "think_decisions_s84", cols, "WHERE case_id=?" if case_id is not None else "", [case_id] if case_id is not None else [], "ORDER BY decision_id")


# --- freezes (a system-made "no new buying of X until <date or event>") ---------------------------------------------------------------------------------------------------

def add_freeze(con, now: datetime, *, isin: str, symbol: str, market: str, case_id: Optional[int], until: Optional[date] = None, until_event: Optional[str] = None, reason: str = "") -> int:
    fid = _id(con, "think_freezes_s84", "freeze_id")
    con.execute("INSERT INTO think_freezes_s84 VALUES (?,?,?,?,?,?,?,?,?,?)", [fid, isin, symbol, market, now.date(), until, until_event, case_id, True, reason[:300]])
    return fid


def release_freeze(con, freeze_id: int) -> None:
    con.execute("UPDATE think_freezes_s84 SET active=false WHERE freeze_id=?", [freeze_id])


def active_freezes(con, day: Optional[date] = None, market: Optional[str] = None) -> List[dict]:
    """Freezes in force on `day`: active, and (no date, or the date has not passed). A freeze with an event stays until a case releases it."""
    day = day or date.today()
    rows = _rows(con, "think_freezes_s84", ("freeze_id", "isin", "symbol", "market", "since", "until", "until_event", "case_id", "active", "reason"), "WHERE active", [], "ORDER BY freeze_id")
    return [r for r in rows if (market is None or r["market"] == market) and r["since"] <= day and (r["until"] is None or r["until"] >= day)]


def is_frozen(con, isin: str, day: Optional[date] = None) -> Optional[dict]:
    """The freeze on this name, or None. The baseline, the picks and the US step read this before any NEW buying."""
    try:
        for f in active_freezes(con, day):
            if f["isin"] == isin:
                return f
    except Exception:
        return None
    return None


# --- calibration (the likelihood word -> probability table; T8 corrects it) -----------------------------------------------------------------------------------------------

def probabilities(con) -> Dict[str, float]:
    """The word -> probability table: the stored rows over the starting values."""
    out = dict(think.WORD_P)
    try:
        for w, p in con.execute("SELECT word, probability FROM think_calibration_s84").fetchall():
            if w in out and p is not None:
                out[w] = float(p)
    except Exception:
        pass
    return out


def seed_calibration(con, day: date) -> int:
    n = 0
    for w, p in think.WORD_P.items():
        if not con.execute("SELECT 1 FROM think_calibration_s84 WHERE word=?", [w]).fetchone():
            con.execute("INSERT INTO think_calibration_s84 VALUES (?,?,?,?,?)", [w, p, 0, 0, day])
            n += 1
    return n


# --- what Today and the 15:45 report show --------------------------------------------------------------------------------------------------------------------------------

def thinking_block(con, day: Optional[date] = None, limit: int = 5) -> dict:
    """The "Thinking about" block: open cases (the largest first) with their class, pending question, next look and exposure; a plain line each. JSON-able."""
    day = day or date.today()
    rows = []
    for c in open_cases(con)[:limit]:
        look = f", looks again {c['next_look_on']}" if c.get("next_look_on") else (f", looks again on: {c['next_look_cond']}" if c.get("next_look_cond") else "")
        pend = f"; waiting for: {c['pending']}" if c.get("pending") else ""
        kl = f" ({c['klass'].replace('_', ' ')})" if c.get("klass") else ""
        rows.append({"case_id": c["case_id"], "symbol": c["symbol"], "state": c["state"], "klass": c["klass"], "pending": c["pending"], "next_look_on": c.get("next_look_on_s"),
                     "exposure_inr": c["exposure_inr"], "exposure_pct": c["exposure_pct"],
                     "line": f"{c['symbol'] or c['title']}{kl}: {c['title']}{pend}{look}"})
    noticed = int(con.execute("SELECT count(*) FROM think_cases_s84 WHERE opened_on=? AND state='noticed'", [day]).fetchone()[0])
    return {"open": rows, "noticed_not_examined_today": noticed, "text": ("Thinking about: " + " | ".join(r["line"] for r in rows)) if rows else "Thinking about: nothing open."}
