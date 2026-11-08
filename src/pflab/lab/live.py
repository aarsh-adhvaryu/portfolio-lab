"""A promoted lab policy in the live close loop (S80 phase 2). The champion's `decide` runs in the main process (the doc: only a promoted policy runs there), but only after it has
been validated, in a worker thread with a time limit, on the same state the replay builds; its answer is cleaned (known securities only, finite non-negative weights) and then goes
through the same rails as the baseline's. If it fails or is too slow the close falls back to the baseline for that session and says so: the book never sits idle.
"""
from __future__ import annotations

import threading
from datetime import date
from typing import Dict, Optional

from pflab.lab import engine, policy_api, shadow

TIME_LIMIT_S = 60.0                         # "seconds, no network": a generous bound for a decision over about 1,000 sessions of 60 names


def _keys(con, data: dict) -> Dict[str, str]:
    """panel key -> ISIN of the book (stocks are keyed by ISIN already; an ETF's key is 'ETF:<symbol>')."""
    from pflab.paper import book
    out = {}
    for k, m in data["meta"].items():
        out[k] = (book.isin_of(con, m["symbol"]) or "") if m.get("etf") else k
    return {k: v for k, v in out.items() if v}


def decide(con, root, day: date, champion: dict, holdings: Dict[str, float], data: Optional[dict] = None) -> dict:
    """The champion's target weights by ISIN. `holdings`: the book's current weights by ISIN. Raises on any failure (the caller falls back)."""
    data = data if data is not None else shadow.live_panel(root, day)
    if not data.get("storylines"):
        data = {**data, "storylines": shadow.story_inputs(con, day, data)}
    k2i = _keys(con, data)
    i2k = {v: k for k, v in k2i.items()}
    prev = {i2k[i]: w for i, w in holdings.items() if i in i2k}
    fn, _ = policy_api.load(champion["code"])
    box: dict = {}

    def work():
        try:
            box["w"] = engine.decision_now(fn, champion["params"], data, day, prev)
        except Exception as e:                                               # reported to the caller, which falls back
            box["err"] = f"{type(e).__name__}: {str(e)[:300]}"
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(TIME_LIMIT_S)
    if t.is_alive():
        raise TimeoutError(f"the champion {champion['policy_id']} did not finish in {TIME_LIMIT_S:.0f} s")
    if "err" in box:
        raise RuntimeError(box["err"])
    return {k2i[k]: float(v) for k, v in box["w"].items() if k in k2i}
