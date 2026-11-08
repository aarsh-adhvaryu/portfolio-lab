"""Storylines as numbers the policy can read (S80 phase 3). Each open storyline becomes its probability, its direction and its exposure per holding; the policy reads

    storylines = {"open": [{id, claim, direction, probability, influence, score, exposure: {key: x}}], "market_tilt": float in [-1, 1], "tilts": {key: float in [-1, 1]}, "as_of": "YYYY-MM-DD"}

where score = direction * (2 * probability - 1) * influence, a market tilt is the sum of the scores of the storylines about the index, and a security's tilt is the sum over storylines of
score times its exposure. A storyline whose predictions keep failing has a low influence, so its tilt shrinks by itself. The policy may use the tilts ("tilt by probability x exposure");
such a policy must win in the lab like any other. NOTE: the lab replays 2005-2017 with EMPTY storylines (there is no storyline history before this layer existed), so a storyline-using
variant is judged there on its non-storyline self; its storyline part proves itself only in the live shadow.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Dict, Optional

from pflab.story import store


def policy_inputs(con, day: date, key_of: Optional[Callable[[str], Optional[str]]] = None, market: str = "IN") -> dict:
    """`key_of(isin) -> the policy's key for that security` (identity for stocks; an ETF's panel key differs); None drops the security."""
    out, tilts, market_tilt = [], {}, 0.0
    for s in store.listing(con, ("open",), market):
        p = float(s["probability"] if s["probability"] is not None else s["prior"])
        inf = float(s["influence"] if s["influence"] is not None else 0.5)
        score = s["direction"] * (2.0 * p - 1.0) * inf
        exp = {}
        for isin, x in con.execute("SELECT isin, exposure FROM storyline_exposure_s80 WHERE storyline_id=?", [s["storyline_id"]]).fetchall():
            k = key_of(isin) if key_of else isin
            if k:
                exp[k] = float(x)
                tilts[k] = tilts.get(k, 0.0) + score * float(x)
        if s["subject"] == "NIFTY500_TRI":
            market_tilt += score
        out.append({"id": s["storyline_id"], "claim": s["claim"], "direction": s["direction"], "probability": round(p, 4), "influence": round(inf, 4), "score": round(score, 4), "exposure": exp})
    clip = lambda x: max(-1.0, min(1.0, x))
    return {"open": out, "market_tilt": round(clip(market_tilt), 4), "tilts": {k: round(clip(v), 4) for k, v in tilts.items()}, "as_of": str(day)}


def summary_text(con, day: date, limit: int = 6) -> str:
    """For the book card: the open storylines with their probabilities, direction, influence and what their predictions have done so far."""
    from pflab.story import predict
    rows = store.listing(con, ("open",))
    if not rows:
        return "no open storyline"
    lines = []
    for s in rows[:limit]:
        pr = predict.record(con, s["storyline_id"])["predictions"]
        done = [p["outcome"] for p in pr if p["outcome"] in ("good", "bad")]
        lines.append(f"#{s['storyline_id']} ({'up' if s['direction'] > 0 else 'down'}) {s['claim'][:140]}: probability {float(s['probability'] if s['probability'] is not None else s['prior']):.0%}, "
                     f"influence {float(s['influence'] or 0.5):.2f}, opened {s['opened_on']}; predictions: {len(done)} scored ({sum(1 for o in done if o == 'good')} good), {len(pr) - len(done)} pending")
    return "\n  " + "\n  ".join(lines) + f"\n  record of finished stories: {store.record_text(con)}"
