"""Forward tests (S65; protocol docs/protocols/s65_forward_protocol.md, committed before the first formation month-end).

Four claims, F1 to F4, "this group of Nifty 500 members earns less over the next month than the other members", tested ONLY on the live
record as months complete: every year up to 2025 has been looked at, so nothing else is unseen. Each calendar month, after it ends, the
group and the universe of its last session are formed from that day's data and stored (`forward_months`); when the next month has ended
the outcome is filled in. At the first month-end with 24 settled valid months the claim is decided once (Newey-West t against its bar),
never earlier; before that only counts are shown. The four count in the learner's counter at registration.
The definitions are `templates.rule_frame` (unchanged), the universe the point-in-time Nifty 500 of that day with the history `rule_filter`
requires. Run by the learner's nightly cycle; it loads the panel only when a month needs forming or settling.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pflab.learner import counter, live
from pflab.learner import templates as tp

START = date(2026, 10, 30)            # the first formation month-end after the registration (2026-10-28)
MIN_MONTHS = 24
CLAIMS: Dict[str, dict] = {
    "F1": {"rule": "below_sma200", "bar": -1.65, "halves": False,
           "text": "Stocks trading below their 200-day average earn less over the next month than the other Nifty 500 stocks (forward confirmation of claim 21)."},
    "F2": {"rule": "volume_spike_2", "bar": -2.13, "halves": True,
           "text": "Stocks with a volume spike, traded value over twice the 20-day average, earn less over the next month than the other Nifty 500 stocks."},
    "F3": {"rule": "near_52w_low_5", "bar": -2.13, "halves": True,
           "text": "Stocks within 5% of their 52-week low earn less over the next month than the other Nifty 500 stocks."},
    "F4": {"rule": "ath_fall_40", "bar": -2.13, "halves": True,
           "text": "Stocks 40% or more below their all-time high earn less over the next month than the other Nifty 500 stocks."},
}
Loader = Callable[[], Tuple[Dict[str, pd.DataFrame], pd.DataFrame]]


def register(con, now: datetime) -> int:
    """Count the four claims in the learner's counter (once each). Returns how many were added."""
    have = {r[0] for r in con.execute("SELECT note FROM learn_tests").fetchall()}
    n = 0
    for cid, c in CLAIMS.items():
        if f"forward:{cid}" not in have:
            counter.record(con, now, "study", f"forward_{c['rule']}", {"claim": cid, "rule": c["rule"], "months": MIN_MONTHS},
                           note=f"forward:{cid}")
            n += 1
    return n


def _ym(d) -> Tuple[int, int]:
    return (d.year, d.month)


def _next_ym(ym: Tuple[int, int]) -> Tuple[int, int]:
    return (ym[0] + 1, 1) if ym[1] == 12 else (ym[0], ym[1] + 1)


def _complete(ym: Tuple[int, int], now: datetime) -> bool:
    return ym < _ym(now)


def _months_between(now: datetime) -> List[Tuple[int, int]]:
    out, ym = [], _ym(START)
    while _complete(ym, now):
        out.append(ym)
        ym = _next_ym(ym)
    return out


def default_loader(root: Path, now: datetime) -> Loader:
    def load():
        mem = tp.members(root)
        return tp.wide_panel(root, sorted(set(mem["isin"])), "2008-06-01", now.date().isoformat()), mem
    return load


def _month_end(sessions: pd.DatetimeIndex, ym: Tuple[int, int]) -> Optional[int]:
    pos = [i for i, t in enumerate(sessions) if (t.year, t.month) == ym]
    return pos[-1] if pos else None


def _universe(w: Dict[str, pd.DataFrame], mem: pd.DataFrame, i: int) -> List[str]:
    t = w["tr"].index[i]
    live_ = set(mem[(mem["from_date"] <= t) & (mem["to_date"] > t)]["isin"]) & set(w["tr"].columns)
    cols = sorted(live_)
    if i < tp.HISTORY:
        return []
    hist = w["adj"].iloc[i - tp.HISTORY + 1:i + 1][cols].notna().sum()
    return [c for c in cols if hist[c] >= 200 and pd.notna(w["tr"].iloc[i][c])]


def _formation(con, w, mem, ym: Tuple[int, int], now: datetime, late: bool) -> int:
    """Form one month for every claim not yet formed for it. Returns rows written."""
    sessions = w["tr"].index
    i = _month_end(sessions, ym)
    if i is None:
        return 0
    when = sessions[i].date()
    cols = None if late else _universe(w, mem, i)
    n = 0
    for cid, c in CLAIMS.items():
        if con.execute("SELECT 1 FROM forward_months WHERE claim=? AND formed_on=?", [cid, when]).fetchone():
            continue
        if late:
            con.execute("INSERT INTO forward_months (claim, formed_on, status, formed_at) VALUES (?,?,?,?)", [cid, when, "late", now])
            n += 1
            continue
        if len(cols) < tp.RULE_MIN_UNIVERSE:
            con.execute("INSERT INTO forward_months (claim, formed_on, status, universe_n, formed_at) VALUES (?,?,?,?,?)",
                        [cid, when, "thin", len(cols), now])
            n += 1
            continue
        sig = tp.rule_frame(w, c["rule"]).iloc[i][cols]
        group = sorted(sig[sig == 1.0].index)
        status = "formed" if len(group) >= tp.RULE_MIN_GROUP else "thin"
        con.execute("INSERT INTO forward_months (claim, formed_on, status, group_json, universe_json, group_n, universe_n, formed_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    [cid, when, status, json.dumps(group) if status == "formed" else None, json.dumps(cols), len(group), len(cols), now])
        n += 1
    return n


def _settle(con, w, now: datetime) -> int:
    sessions = w["tr"].index
    tr, tr_f = w["tr"], w["tr"].ffill()
    n = 0
    for cid, formed, gj, uj in con.execute("SELECT claim, formed_on, group_json, universe_json FROM forward_months WHERE status='formed' "
                                           "ORDER BY formed_on").fetchall():
        nxt = _next_ym(_ym(formed))
        if not _complete(nxt, now):
            continue
        i, j = _month_end(sessions, _ym(formed)), _month_end(sessions, nxt)
        if i is None or j is None:
            continue
        cols = json.loads(uj)
        fwd = (tr_f.iloc[j][cols] / tr.iloc[i][cols] - 1).dropna()
        grp = [g for g in json.loads(gj) if g in fwd.index]
        if len(grp) < tp.RULE_MIN_GROUP:
            con.execute("UPDATE forward_months SET status='thin', outcome_on=?, settled_at=? WHERE claim=? AND formed_on=?",
                        [sessions[j].date(), now, cid, formed])
        else:
            g, u = float(fwd[grp].mean()), float(fwd.mean())
            con.execute("UPDATE forward_months SET status='settled', outcome_on=?, group_ret=?, universe_ret=?, excess=?, settled_at=? "
                        "WHERE claim=? AND formed_on=?", [sessions[j].date(), g, u, g - u, now, cid, formed])
        n += 1
    return n


def _decide(con, now: datetime) -> Dict[str, dict]:
    """Decide each claim once, at its 24th settled valid month (the first 24 are used)."""
    out = {}
    for cid, c in CLAIMS.items():
        row = con.execute("SELECT test_id, t_dev, passed FROM learn_tests WHERE note=?", [f"forward:{cid}"]).fetchone()
        if not row or row[1] is not None or row[2] is not None:
            continue
        ex = [r[0] for r in con.execute("SELECT excess FROM forward_months WHERE claim=? AND status='settled' ORDER BY formed_on LIMIT ?",
                                        [cid, MIN_MONTHS]).fetchall()]
        if len(ex) < MIN_MONTHS:
            continue
        m, t, n = tp.nw_t(ex, lags=1)
        ok = bool(np.isfinite(t) and t <= c["bar"])
        if ok and c["halves"]:
            ok = float(np.mean(ex[:12])) < 0 and float(np.mean(ex[12:])) < 0
        con.execute("UPDATE learn_tests SET n_dev=?, t_dev=?, threshold_dev=?, passed=? WHERE test_id=?",
                    [n, float(t) if np.isfinite(t) else None, c["bar"], ok, row[0]])
        why = f"forward, {n} live months: mean excess {m:+.2%} a month, t {t:.2f} (bar {c['bar']})"
        if ok:
            live.put(con, "finding", f"forward:{cid}", f"{c['text']} Tested forward on live data: {why} (protocol s65_forward, {cid})",
                     json.dumps({"claim": cid, "rule": c["rule"]}), f"forward {cid}", now)
        out[cid] = {"passed": ok, "t": float(t) if np.isfinite(t) else None, "months": n, "mean": float(m), "why": why}
    return out


def pending(con, now: datetime) -> dict:
    """What needs the panel: months to form, months to settle (from the table and the date alone)."""
    have = {_ym(r[0]) for r in con.execute("SELECT DISTINCT formed_on FROM forward_months").fetchall()}
    to_form = [ym for ym in _months_between(now) if ym not in have]
    to_settle = [r for r in con.execute("SELECT formed_on FROM forward_months WHERE status='formed'").fetchall()
                 if _complete(_next_ym(_ym(r[0])), now)]
    return {"form": to_form, "settle": len(to_settle)}


def cycle(con, root: Path, now: datetime, loader: Optional[Loader] = None) -> dict:
    """The nightly step: register, form the months that ended, settle the outcomes that are in, decide what has 24 months."""
    out: dict = {"registered": register(con, now)}
    todo = pending(con, now)
    if todo["form"] or todo["settle"]:
        w, mem = (loader or default_loader(root, now))()
        out["formed"] = 0
        for ym in todo["form"]:
            late = _complete(_next_ym(ym), now)           # the outcome month is already over: never formed after the fact
            out["formed"] += _formation(con, w, mem, ym, now, late)
        out["settled"] = _settle(con, w, now)
    decided = _decide(con, now)
    if decided:
        out["decided"] = decided
    return out


def status(con) -> List[dict]:
    """Counts only until a claim's decision month; then its verdict (never a running t)."""
    rows = []
    for cid, c in CLAIMS.items():
        counts = dict(con.execute("SELECT status, count(*) FROM forward_months WHERE claim=? GROUP BY 1", [cid]).fetchall())
        t = con.execute("SELECT t_dev, passed, n_dev FROM learn_tests WHERE note=?", [f"forward:{cid}"]).fetchone()
        verdict = None if not t or t[1] is None else {"passed": bool(t[1]), "t": t[0], "months": t[2], "bar": c["bar"]}
        rows.append({"id": cid, "rule": c["rule"], "settled": counts.get("settled", 0), "formed": counts.get("formed", 0),
                     "thin": counts.get("thin", 0), "late": counts.get("late", 0), "needs": MIN_MONTHS, "verdict": verdict})
    return rows
