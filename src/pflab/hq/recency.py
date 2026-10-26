"""How old is what the brain reads (S64 Phase 5 item 2; the investor: "make sure the news is current or recent, not old").

`stamp` adds `age_days` and `stale` to every dated item a read tool returns. The policy is in days: news 3, filings 30,
results 100, web results 7. An item with no date is "undated". The brain's rule: a stale or undated item is never cited
as a cause of today. Kinds without a policy get an age and no verdict.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

POLICY: Dict[str, int] = {"news": 3, "article": 3, "filing": 30, "reading": 30, "result": 100, "web": 7}
UNDATED = "undated"


def _date(x) -> Optional[date]:
    if x is None or x == "":
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return datetime.fromisoformat(str(x)[:19]).date()
    except ValueError:
        return None


def verdict(kind: str, published, today: date) -> dict:
    """{'age_days': int or None, 'stale': True/False/'undated'/None}: None when the kind has no policy."""
    d = _date(published)
    if d is None:
        return {"age_days": None, "stale": UNDATED}
    age = (today - d).days
    limit = POLICY.get(kind)
    return {"age_days": age, "stale": (age > limit) if limit is not None else None}


def stamp(items: List[dict], kind: Optional[str], today: date, date_key: str = "published",
          kind_key: str = "kind") -> List[dict]:
    """Add age_days and stale to each item, in place; `kind` fixes the policy kind, else each item's own `kind_key`."""
    for it in items:
        it.update(verdict(kind or it.get(kind_key) or "", it.get(date_key), today))
    return items


def fresh(items: List[dict]) -> List[dict]:
    """The items that are neither stale nor undated (an item of a kind with no policy counts as fresh)."""
    return [i for i in items if i.get("stale") in (False, None)]
