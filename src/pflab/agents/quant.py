"""The quant researcher (S46, PLAN A7): map an idea to a tested study template and run it.

Templates:
    event_study  "how do stocks move after <a kind of filing>": the filing kind is read from the idea by code (the
                 registered materiality subcategories and the frozen red-flag rules); runs on Nifty 500 names,
                 2015-2018 and 2019-2021 shown apart (2022-2025 are spent), so a pattern that holds in only one half
                 is visible
    drift        "is <rule> still working": the drift checks of every adopted rule
A template run is exploratory: it informs, and anything to be adopted gets its own pre-registered study.
"""
from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from pflab.data import red_flags
from pflab.llm.eval12 import MATERIAL

FLAG_WORDS = {"RATING_DOWNGRADE": r"downgrad|rating cut", "DEFAULT": r"default", "AUDITOR_RESIGNATION": r"auditor",
              "INSOLVENCY": r"insolven|nclt|cirp", "FRAUD": r"fraud", "RESULTS_DELAY": r"delay.{0,20}result",
              "PROMOTER_ENCUMBRANCE": r"pledg|encumb", "FORENSIC_AUDIT": r"forensic",
              "REGULATORY_ACTION": r"sebi order|penalt|regulator"}
SUB_WORDS = {"Financial Results": r"result", "Credit Rating": r"rating", "Acquisition": r"acqui",
             "Award of Order / Receipt of Order": r"order win|orders? (won|received)|receipt of order|new order",
             "Dividend": r"dividend", "Change in Management": r"management|ceo|cfo",
             "Resignation of Director": r"director.{0,15}resign|resign.{0,15}director"}
HALVES = (("2015-01-01", "2018-12-31"), ("2019-01-01", "2021-12-31"))


def route(idea: str) -> Tuple[str, Dict[str, object]]:
    """(template, parameters). Red-flag wording beats a plain subcategory ('rating downgrade' is not any rating)."""
    s = idea.lower()
    if re.search(r"still work|drift|re-?test|still valid", s):
        return "drift", {}
    for flag, rx in FLAG_WORDS.items():
        if re.search(rx, s):
            pos = [p.pattern for p in red_flags._C[flag][0]]
            return "event_study", {"label": flag.replace("_", " ").lower(), "headline_regex": "|".join(pos)}
    for sub, rx in SUB_WORDS.items():
        if sub in MATERIAL and re.search(rx, s):
            return "event_study", {"label": sub, "subcategories": [sub]}
    return "none", {}


def run(idea: str, root=None) -> str:
    from pflab.data import data_dir
    from pflab.quant import drift
    from pflab.quant import event_study as es
    root = root or data_dir()
    tpl, prm = route(idea)
    if tpl == "drift":
        return "Drift checks of the adopted rules:\n" + drift.render(drift.run_all(root))
    if tpl == "event_study":
        parts = [f"Template: event study of '{prm['label']}' filings (exploratory; to adopt anything, register it first)."]
        for a, b in HALVES:
            res = es.run(root, a, b, prm.get("subcategories", ()), prm.get("headline_regex", ""))
            parts.append(es.render(res, f"{a[:4]}-{b[:4]}"))
        return "\n".join(parts)
    return ("No tested template fits this idea yet. Templates: how stocks moved after a kind of filing (results, "
            "ratings, downgrades, defaults, auditor exits, orders, dividends, acquisitions, management changes, pledges), "
            "or whether an adopted rule still works. A new kind of study needs a protocol first.")
