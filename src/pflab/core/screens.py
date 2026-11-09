"""What the Today screen shows of the v2 core (S80 phase 4): the spend by use, the champion against the plain baseline, the challengers, and the open storylines.

Everything is read from the store; every number was made by code elsewhere (`lab.strategist.spend_report`, `lab.service`, `paper.benchmark`, `story.predict`). A part that
cannot be read is left out and named in `left_out`; nothing is guessed.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional


def _score(run: Optional[dict]) -> Optional[dict]:
    if not run:
        return None
    s = run.get("score") or {}
    return {k: (round(float(s[k]), 4) if s.get(k) is not None else None) for k in ("cagr", "excess_cagr", "sharpe", "dsr", "max_drawdown") if k in s}


def spend(con, now: datetime) -> dict:
    from pflab.lab import strategist
    r = strategist.spend_report(con, now)
    return {"month": r["month_rupees"], "lab_runs": r["lab_runs"], "challengers_added": r["challengers_added"], "promotions": r["promotions"],
            "runs_per_100_rupees": r["lab_runs_per_100_rupees"], "challengers_per_100_rupees": r["challengers_per_100_rupees"],
            "promotions_per_100_rupees": r["promotions_per_100_rupees"], "next_session_budget": r.get("budget")}


def policies(con, day: date) -> dict:
    from pflab.lab import service as lab, shadow
    from pflab.paper import benchmark
    champ = shadow.champion_row(con)
    base = lab.latest_run(con, lab.BASELINE_ID, "history")
    ch = lab.latest_run(con, champ["policy_id"], "history", champ["params"]) if champ and champ.get("code") else None
    promoted = con.execute("SELECT promoted_at FROM core_policies_s80 WHERE status='champion' ORDER BY promoted_at DESC NULLS LAST LIMIT 1").fetchone()
    out = {"champion": champ["policy_id"] if champ else None, "since": str(promoted[0])[:10] if promoted and promoted[0] else None,
           "champion_history": _score(ch), "baseline_history": _score(base), "challengers": []}
    for (pid,) in con.execute("SELECT policy_id FROM core_policies_s80 WHERE status='challenger' ORDER BY policy_id").fetchall():
        try:
            rec = shadow.record(con, pid)
            hist = lab.latest_run(con, pid, "history")
            out["challengers"].append({"policy": pid, "history": _score(hist), "shadow_sessions": rec.get("sessions"), "shadow_excess": rec.get("excess")})
        except Exception:
            out["challengers"].append({"policy": pid, "history": None, "shadow_sessions": None, "shadow_excess": None})
    try:
        b = benchmark.status(con, "IN", day)
        if b.get("started") and b.get("book", {}).get("return") is not None:
            out["book_vs_benchmark"] = {"book": b["book"]["return"], "benchmark": b["benchmark"]["return"], "excess": b.get("excess"), "since": str(b.get("since")), "worst_fall": b.get("worst_fall_book")}
    except Exception:
        pass
    runs = con.execute("SELECT count(*), count(*) FILTER (WHERE status='traded') FROM core_runs_s80").fetchone()
    out["closes_run"], out["closes_with_trades"] = int(runs[0]), int(runs[1])
    return out


def storylines(con, limit: int = 6) -> list:
    from pflab.story import predict, store
    rows = []
    for s in store.listing(con, ("open",))[:limit]:
        pr = predict.record(con, s["storyline_id"])["predictions"]
        done = [p["outcome"] for p in pr if p["outcome"] in ("good", "bad")]
        rows.append({"id": s["storyline_id"], "claim": s["claim"], "direction": "up" if s["direction"] > 0 else "down",
                     "probability": float(s["probability"] if s["probability"] is not None else s["prior"]), "influence": float(s["influence"] or 0.5),
                     "opened_on": str(s["opened_on"]), "scored": len(done), "good": sum(1 for o in done if o == "good"), "pending": len(pr) - len(done)})
    return rows


def view(con, now: datetime) -> dict:
    out: dict = {"left_out": []}
    for name, fn in (("spend", lambda: spend(con, now)), ("policies", lambda: policies(con, now.date())), ("storylines", lambda: storylines(con))):
        try:
            out[name] = fn()
        except Exception as e:
            out[name] = None
            out["left_out"].append(f"{name} ({type(e).__name__})")
    return out
