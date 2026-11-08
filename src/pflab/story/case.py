"""The 5-6 November 2026 case, rebuilt as a storyline (S80 phase 3 gate). On 5 Nov the Nifty 500 rose on record foreign buying while Asia and the US chip index fell, against what the
v1 situation report expected. As a storyline it reads: "Foreign money is rotating out of AI-heavy Asia into India", opened 5 Nov, its probability rising on the signals and the dated
evidence (the foreign flow, the Asia and chip moves), with its exposure pointing at banks and the other domestic-demand names, and predictions at 5 and 20 sessions that are scored when
they come due. Everything here is code over the collectors' files: no model.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pflab.story import adapters, predict, prob, store

CLAIM = "Foreign money is rotating out of AI-heavy Asia into India, which should lift the Nifty 500 over the next weeks"
TEMPLATES = ["fii_buying_strong", "asia_chip_weak", "chips_falling", "india_outperforms_asia", "fii_selling_contradicts", "india_lags_asia"]
DOMESTIC_EXPOSURE = {"bank": 0.6, "financ": 0.5, "insurance": 0.3, "consumer": 0.2, "auto": 0.2}


def rebuild(con, now: datetime, root=None, opened_on: date = date(2026, 11, 5), through: Optional[date] = date(2026, 11, 6), isins: Optional[List[str]] = None) -> dict:
    """Open the storyline on `opened_on`, attach the code-read evidence of each session from then to `through` (for what leans with it), set the exposure, register its predictions and
    compute its probability for every session in between, each from only what was known on that day."""
    from pflab import markets
    r = store.open_storyline(con, now, CLAIM, 1, opened_on, TEMPLATES, kind="flow_rotation", created_by="rebuild of the 5-6 Nov 2026 case")
    sid = r.get("storyline_id")
    if not r.get("ok") and not sid:
        return r
    cal = markets.get("IN")
    days, d = [], opened_on
    while d <= (through or opened_on):
        if cal.is_session(d):
            days.append(d)
        d = d.fromordinal(d.toordinal() + 1)
    path = []
    for day in days:
        for it in adapters.flows_items(root, day):
            if it["date"] != day and it["date"].toordinal() < day.toordinal() - 1:
                continue
            fii = it["text"]
            leans_for = "buyers" in fii
            store.add_evidence(con, now, sid, it["date"], "for" if leans_for else "against", it["text"], it["source_kind"], it["source_ref"], "moderate", "rule: foreign flow sign")
        path.append((str(day), round(prob.update(con, now, sid, day, root)["probability"], 4)))
    if isins:
        store.exposure_by_sector(con, sid, DOMESTIC_EXPOSURE, isins, "rule: domestic-demand sectors gain from foreign inflows", opened_on)
    n = predict.register(con, now, sid, opened_on, root)
    return {"ok": True, "storyline_id": sid, "probability_path": path, "predictions_registered": n, "exposure_names": len(isins or [])}
