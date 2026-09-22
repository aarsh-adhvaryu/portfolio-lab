"""Firm-level red-flag classifier for BSE announcements (E2-A).

Revised 2026-09-16 against a 41,128-announcement sample (see
docs/data/red_flag_sample.md), then frozen for the E2-A charter.

Two structural choices, both from that review:

1. **Category first, regex second.** BSE's `category` and `subcategory` fields
   are cleaner than the headline, which is often just "as attached". A rule
   fires only inside the categories where its event can occur, so headline
   regexes never have to carry the whole load.
2. **Negative matches are part of the rule.** The first draft's
   `\\bsebi\\b.*order` matched "secured order amounting to Rs ...", a purchase
   order, and bare `\\bnclt\\b` matched every merger scheme. Both are excluded
   explicitly rather than by hoping the corpus stays clean.
"""
from __future__ import annotations

import re
from typing import List

# Rule = (any_of, none_of, categories). `categories` None means "any".
# Matching is over headline + category + subcategory, lowercased.
RULES = {
    # A scheme of arrangement is not insolvency: JSW Energy and GE Power both
    # appear under NCLT in the sample and neither was insolvent.
    "INSOLVENCY": (
        [r"\bcirp\b", r"corporate insolvency", r"\bibc\b",
         r"resolution professional", r"\bliquidation\b", r"liquidator",
         r"admission of (the )?application", r"insolvency and bankruptcy"],
        [r"scheme of (arrangement|amalgamation|merger)", r"\bdemerger\b"],
        None,
    ),
    # Require SEBI/SAT as the actor. "Order" alone is a purchase order.
    # Every positive here names a specific enforcement act. Loose stems are
    # what broke the first two drafts: bare `order` matched purchase orders,
    # and `attach` matched "please find attached" in ordinary LODR filings,
    # which begin "Pursuant to Regulation 30 of SEBI (LODR)..." and so already
    # contain the word SEBI.
    "REGULATORY_ACTION": (
        [r"\b(sebi|sat|securities appellate tribunal)\b.{0,60}"
         r"(passed an order|order passed|adjudication order|show cause notice|"
         r"imposed a penalty|penalty of rs|debarr|impounded|interim order)",
         r"(adjudication order|show cause notice|penalty imposed|order passed|"
         r"interim order).{0,60}\b(by|from) (the )?(sebi|sat|securities)",
         r"enforcement directorate", r"\bcbi\b", r"\bsfio\b",
         r"serious fraud investigation", r"provisional attachment"],
        [r"bagging", r"secured (an )?order", r"receipt of order", r"work order",
         r"purchase order", r"\bawarded?\b", r"letter of intent", r"\bloa\b",
         r"please find attached", r"annual secretarial compliance"],
        None,
    ),
    "FORENSIC_AUDIT": ([r"forensic audit"], [], None),
    "AUDITOR_RESIGNATION": (
        [r"resignation of (the )?(statutory |joint )?auditor",
         r"auditor.{0,40}resign", r"resign.{0,40}auditor"],
        [], None,
    ),
    "DEFAULT": (
        [r"default in (payment|repayment)",
         r"delay in (the )?payment of (interest|principal|instal)",
         r"\bdefault\b.{0,60}(interest|principal|debenture|loan|ncd|facility)",
         r"regulation 51.{0,40}default", r"disclosure of default"],
        [r"no default", r"nil default"], None,
    ),
    "RATING_DOWNGRADE": (
        [r"\bdowngrad", r"revision in (the )?credit rating",
         r"rating.{0,40}(revised downward|downgrade)",
         r"credit rating.{0,40}\bd\b\s*$"],
        [r"upgrad"], None,
    ),
    # Kept as its own flag on purpose. SEBI requires a "reasons for
    # encumbrance" disclosure only when pledging crosses 50% of promoter
    # holding or 20% of share capital, so it IS the distress-level event.
    # Ordinary SAST 31(1) creation/release is a different, much larger
    # population and is deliberately NOT flagged.
    "PROMOTER_ENCUMBRANCE": (
        [r"reasons for encumbrance", r"reason.{0,20}for.{0,20}encumbrance"],
        [r"release of pledge", r"revocation of pledge"], None,
    ),
    "RESULTS_DELAY": (
        [r"delay.{0,40}(financial )?results",
         r"(unable|inability) to (submit|publish).{0,40}results",
         r"extension.{0,40}(submission|publication).{0,40}results"],
        [], None,
    ),
    "FRAUD": (
        [r"\bfraud\b", r"misappropriat", r"embezzl", r"whistle.?blower",
         r"siphon"],
        [r"fraud.{0,20}(prevention|awareness|policy)"], None,
    ),
}

_C = {k: ([re.compile(p, re.I) for p in pos],
          [re.compile(p, re.I) for p in neg],
          cats)
      for k, (pos, neg, cats) in RULES.items()}


def classify(headline: str, category: str = "", subcategory: str = "") -> List[str]:
    parts = [x for x in (headline, category, subcategory) if isinstance(x, str)]
    text = " ".join(parts)
    cat = " ".join(x for x in (category, subcategory) if isinstance(x, str)).lower()
    out = []
    for flag, (pos, neg, cats) in _C.items():
        if cats is not None and not any(c in cat for c in cats):
            continue
        if any(p.search(text) for p in pos) and not any(n.search(text) for n in neg):
            out.append(flag)
    return out
