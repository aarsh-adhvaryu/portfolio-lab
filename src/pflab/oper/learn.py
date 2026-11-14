"""S87 O5: the learning loop made visible. Every decision of the paper book is scored by the thinking loop's own scorer (`think/score.py`: 5, 20 and 60 sessions, after tax, against doing nothing; and the
picks' scorer `core/pick_score.py` against the index). This module adds the other half: the decisions HE logs on his real holdings (through the operator) are scored at the same horizons against the
Nifty 500, from the first session close on or after the day he logged them (point-in-time). A buy or a hold has no tax event until it is sold, so its excess is the same before and after tax; a SALE's
excess does not include the tax on the sale (the lot record is not read here): labelled in every line. Nothing here changes a rule: thresholds are tuned only after 40 scored decisions or 60 misses (the
learner's rule) and a rule changes only through a registered study that beats the baseline on unseen data, then probation."""
from __future__ import annotations

from datetime import date, datetime

HORIZONS = (5, 20, 60)
DDL = ["""CREATE TABLE IF NOT EXISTS operator_decisions_s87 (decision_id INTEGER PRIMARY KEY, logged_at TIMESTAMP NOT NULL, symbol VARCHAR NOT NULL, isin VARCHAR, action VARCHAR NOT NULL, note VARCHAR)""",
       """CREATE TABLE IF NOT EXISTS operator_decision_scores_s87 (decision_id INTEGER NOT NULL, horizon_sessions INTEGER NOT NULL, scored_on DATE NOT NULL, stock_return DOUBLE, index_return DOUBLE,
          excess DOUBLE, label VARCHAR, PRIMARY KEY (decision_id, horizon_sessions))"""]
ACTIONS = ("buy", "sell", "hold", "trim", "add", "skip")


def ensure(con) -> None:
    for d in DDL:
        con.execute(d)


def log_decision(con, now: datetime, symbol: str, action: str, note: str = "") -> str:
    from pflab.agents import tradecheck
    from pflab.pm.store import next_id
    ensure(con)
    action = action.lower().strip()
    if action not in ACTIONS:
        return f"action must be one of {', '.join(ACTIONS)}"
    sym = symbol.upper().strip()
    isin = tradecheck.isin_of(con, sym)
    if not isin:
        return f"{sym} is not a name the record knows (no ISIN): it cannot be scored"
    did = next_id(con, "operator_decisions_s87", "decision_id")
    con.execute("INSERT INTO operator_decisions_s87 VALUES (?,?,?,?,?,?)", [did, now, sym, isin, action, note[:300]])
    return f"Logged decision #{did}: {action} {sym}. It is scored against the index after 5, 20 and 60 sessions."


def _series(con, isin: str, root, asof: date):
    from pflab.hq import stocks
    return stocks.closes(con, root, isin, asof)


def _by_day(s):
    s = s.copy()
    s.index = [d.date() if hasattr(d, "date") else d for d in s.index]
    return s


def score_due(con, now: datetime, root=None) -> int:
    """Score every logged decision whose horizon has passed (once each). Returns the number of new scores."""
    from pflab.core import pick_score
    ensure(con)
    idx = pick_score.index_series("IN", root)
    if idx is None or len(idx) < 3:
        return 0
    idx = _by_day(idx)
    done = {(int(a), int(b)) for a, b in con.execute("SELECT decision_id, horizon_sessions FROM operator_decision_scores_s87").fetchall()}
    n = 0
    for did, at, isin, action in con.execute("SELECT decision_id, logged_at, isin, action FROM operator_decisions_s87").fetchall():
        d0 = at.date()
        try:
            s = _by_day(_series(con, isin, root, now.date()))
        except Exception:
            continue
        s = s[[d <= now.date() for d in s.index]]
        base_days = [d for d in s.index if d >= d0 and d in idx.index]
        if not base_days:
            continue
        b = base_days[0]
        later = [d for d in s.index if d > b and d in idx.index]
        for h in HORIZONS:
            if (int(did), h) in done or len(later) < h:
                continue
            e = later[h - 1]
            sr, ir = float(s[e] / s[b] - 1), float(idx[e] / idx[b] - 1)
            label = "a sale: the tax on the sale is not included" if action in ("sell", "trim") else "no tax event until it is sold: same before and after tax"
            con.execute("INSERT INTO operator_decision_scores_s87 VALUES (?,?,?,?,?,?,?)", [int(did), h, e, sr, ir, sr - ir, label])
            n += 1
    return n


def summary(con) -> dict:
    ensure(con)
    rows = con.execute("SELECT d.decision_id, d.symbol, d.action, cast(d.logged_at as date), s.horizon_sessions, s.excess, s.label FROM operator_decisions_s87 d LEFT JOIN operator_decision_scores_s87 s "
                       "ON s.decision_id = d.decision_id ORDER BY d.decision_id DESC, s.horizon_sessions LIMIT 60").fetchall()
    by: dict = {}
    for did, sym, act, day, h, ex, lab in rows:
        e = by.setdefault(int(did), {"decision": int(did), "symbol": sym, "action": act, "logged": str(day), "scores": {}})
        if h is not None:
            e["scores"][f"{h}_sessions"] = {"excess_vs_nifty500_pct": round(float(ex) * 100, 2), "note": lab}
    out = list(by.values())
    return {"decisions": out[:15], "n_logged": len(out), "n_scored": sum(1 for e in out if e["scores"]),
            "rule": "thresholds are tuned only after 40 scored decisions or 60 misses; a rule changes only through a registered study that beats the baseline on unseen data"}
