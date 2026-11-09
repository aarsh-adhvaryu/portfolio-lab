"""Challengers in shadow (S80 phase 2): at every close each challenger, and the champion's stand-in, decide on the SAME live inputs in the sandbox; their target weights are stored
(`core_shadow_s80`) and scored on the next session, so the only evidence that is not history builds up day by day.

The champion's stand-in is the policy whose scorecard stands for the champion in the lab: the champion itself when it is a lab policy, else `baseline_lab` (the live baseline's lab
reading). Each shadow book starts from its own previous weights (the state the policy sees as `weights`), so a policy that trades in bands behaves as it would live. A shadow return is
the day's return of its weights from one close to the next, plus cash at the stated rate, minus charges at the stated rate on what it traded. No tax: shadow books are compared
with each other on the same footing, and the champion's REAL tax shows in the book, not here.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from pflab.lab import runner, service

SHADOW_COST = 0.0012                      # per rupee traded, a stated flat charge rate
CASH_RATE = 0.065
LIVE_ROWS_DAYS = 1500                     # calendar days of history handed to a live decision (about 1,000 sessions)


def live_panel(root, day: date, n_names: int = 400) -> dict:
    """The panel up to `day` for LIVE use (the spent 2022-2025 window is live data here, not evidence)."""
    return runner.build_panel(root, n_names=n_names, start=day - timedelta(days=LIVE_ROWS_DAYS), end=day)


def story_inputs(con, day: date, data: dict) -> dict:
    """The open storylines as numbers for the policies (`story/numbers.py`), keyed the way the panel is (a stock by ISIN, an ETF as 'ETF:<symbol>')."""
    try:
        from pflab.paper import book
        from pflab.story import numbers
        etf = {m["symbol"]: k for k, m in data["meta"].items() if m.get("etf")}
        keys = set(data["meta"])

        def key_of(isin: str):
            if isin in keys:
                return isin
            sym = book.inst(con, isin).get("symbol")
            return etf.get(sym)
        return numbers.policy_inputs(con, day, key_of=key_of)
    except Exception:
        return {}


def champion_row(con) -> Optional[dict]:
    r = con.execute("SELECT policy_id FROM core_policies_s80 WHERE status='champion' ORDER BY promoted_at DESC NULLS LAST LIMIT 1").fetchone()
    return service.get(con, r[0]) if r else None


def standin(con) -> str:
    """The lab policy that stands for the champion: itself if it is a lab policy, else the baseline reference."""
    c = champion_row(con)
    return c["policy_id"] if c and c["policy_id"] not in ("baseline_v1", "baseline_v2") and c["code"] else service.BASELINE_ID


def members(con) -> List[dict]:
    """Challengers plus the champion's stand-in: the shadow field."""
    ids = [r[0] for r in con.execute("SELECT policy_id FROM core_policies_s80 WHERE status='challenger' ORDER BY policy_id").fetchall()]
    sid = standin(con)
    if sid not in ids:
        ids.append(sid)
    return [service.get(con, i) for i in ids]


def last_weights(con, policy_id: str, before: date) -> Dict[str, float]:
    r = con.execute("SELECT weights_json FROM core_shadow_s80 WHERE policy_id=? AND day < ? ORDER BY day DESC LIMIT 1", [policy_id, before]).fetchone()
    return json.loads(r[0]) if r and r[0] else {}


def run_shadow(con, pm_dir: Path, root, now: datetime, day: date, data: Optional[dict] = None, box=None, time_limit: int = 600) -> dict:
    """Decide for every member on the close of `day`, store the weights, then score the earlier rows that `day`'s close completes. Idempotent for a day already stored."""
    service.ensure_baseline(con, now)
    field = members(con)
    todo = [m for m in field if not con.execute("SELECT 1 FROM core_shadow_s80 WHERE day=? AND policy_id=?", [day, m["policy_id"]]).fetchone()]
    out: Dict[str, object] = {"day": str(day), "members": [m["policy_id"] for m in field], "decided": 0, "errors": {}}
    data = data if data is not None else live_panel(root, day)
    if todo:
        res = runner.run(data, [{"id": m["policy_id"], "code": m["code"]} for m in todo], None, {}, None, n_shuffles=0, n_mc=0, time_limit=time_limit, box=box,
                         now_spec={"mode": "now", "day": str(day), "storylines": story_inputs(con, day, data), "params": {m["policy_id"]: m["params"] for m in todo}, "prev": {m["policy_id"]: last_weights(con, m["policy_id"], day) for m in todo}})
        if res.get("error"):
            out["error"] = res["error"]
            return out
        for m in todo:
            w = (res.get("results") or {}).get(m["policy_id"], {}).get("weights")
            if w is None:
                out["errors"][m["policy_id"]] = (res.get("errors") or {}).get(m["policy_id"], "no answer")[-300:]
                continue
            con.execute("INSERT OR REPLACE INTO core_shadow_s80 VALUES (?,?,?,?,?)", [day, m["policy_id"], json.dumps({k: round(v, 6) for k, v in w.items()}), None, None])
            out["decided"] += 1
    out["scored"] = score(con, now, data["px"])
    return out


def score(con, now: datetime, px) -> int:
    """Score every shadow row whose next session's close is in `px`: the weights' return from its day's close to the next close, net of charges on what changed."""
    import pandas as pd
    n = 0
    rf = (1 + CASH_RATE) ** (1 / 252) - 1
    rows = con.execute("SELECT day, policy_id, weights_json FROM core_shadow_s80 WHERE ret IS NULL ORDER BY day").fetchall()
    idx = px.index
    for day, pid, wj in rows:
        later = idx[idx > pd.Timestamp(day)]
        if len(later) == 0 or pd.Timestamp(day) not in idx:
            continue
        nxt = later[0]
        w = json.loads(wj or "{}")
        prev = con.execute("SELECT weights_json FROM core_shadow_s80 WHERE policy_id=? AND day < ? ORDER BY day DESC LIMIT 1", [pid, day]).fetchone()
        pw = json.loads(prev[0]) if prev and prev[0] else {}
        ret = sum(v * (float(px.at[nxt, k]) / float(px.at[pd.Timestamp(day), k]) - 1.0) for k, v in w.items() if k in px.columns and px.at[pd.Timestamp(day), k] == px.at[pd.Timestamp(day), k]
                  and px.at[nxt, k] == px.at[nxt, k])
        ret += (1.0 - sum(w.values())) * rf
        ret -= SHADOW_COST * sum(abs(w.get(k, 0.0) - pw.get(k, 0.0)) for k in set(w) | set(pw))
        con.execute("UPDATE core_shadow_s80 SET ret=?, scored_at=? WHERE day=? AND policy_id=?", [float(ret), now, day, pid])
        n += 1
    return n


def record(con, challenger_id: str, against: Optional[str] = None) -> dict:
    """The live shadow record of a challenger against the champion's stand-in on the sessions both have been scored: sessions, cumulative returns, the cumulative excess."""
    against = against or standin(con)
    rows = con.execute("SELECT a.day, a.ret, b.ret FROM core_shadow_s80 a JOIN core_shadow_s80 b ON a.day=b.day AND b.policy_id=? WHERE a.policy_id=? AND a.ret IS NOT NULL AND b.ret IS NOT NULL "
                       "ORDER BY a.day", [against, challenger_id]).fetchall()
    ca = cb = 1.0
    for _, a, b in rows:
        ca *= 1 + a
        cb *= 1 + b
    return {"sessions": len(rows), "challenger_return": ca - 1, "champion_standin_return": cb - 1, "excess": (ca - 1) - (cb - 1), "against": against}
