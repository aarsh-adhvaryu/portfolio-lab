"""Sleeves (S81, A48): every position belongs to one sleeve.

    core      index, gold and international ETFs (the part of the book that owns the market)
    longterm  stock picks held months to years

(A60, 2026-11-10: the `swing` sleeve is deleted: its registered study failed. Rows already tagged `swing` in `sleeves_s81` stay for the record and read as `longterm`; the starting split is
core 60 / longterm 40.)

`sleeves_s81(market, isin, sleeve, opened_on)` holds the sleeve a position was opened in (set when its first order is placed; it stays until the position is gone and re-opened).
`sleeve_of` falls back to a default: ETFs, gold and international instruments are core, everything else is longterm. The sleeve SHARES of the book are a target
(`target_shares`: the starting default in `configs/core.toml [baseline_v2]`, or the adopted allocation's); they are never read from his `targets.toml`.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Dict, Optional

SLEEVES = ("core", "longterm")
CAPS = {"longterm_max": 60.0, "core_min": 30.0}          # his answer (2026-11-09), percent of the book, enforced on every proposed allocation


def default_sleeve(con, isin: str) -> str:
    """ETFs (index, gold, international, liquid) and gold or international instruments -> core; everything else -> longterm."""
    from pflab.paper import allocation, book
    m = book.inst(con, isin)
    if (m["asset_class"] or "").lower() in ("etf", "sgb", "gold_physical"):
        return "core"
    if allocation.class_of(m["asset_class"], m["name"], m["symbol"], isin) in ("gold", "international") and (m["asset_class"] or "").lower() != "equity":
        return "core"
    return "longterm"


def sleeve_of(con, isin: str, market: str = "IN") -> str:
    r = con.execute("SELECT sleeve FROM sleeves_s81 WHERE market=? AND isin=?", [market, isin]).fetchone()
    if not r:
        return default_sleeve(con, isin)
    return r[0] if r[0] in SLEEVES else "longterm"                # a row tagged with the deleted swing sleeve reads as longterm (A60)


def set_sleeve(con, isin: str, sleeve: str, day: Optional[date] = None, market: str = "IN", force: bool = False) -> str:
    """Record the sleeve a position opens in. The first record stays unless `force`. -> the sleeve in force."""
    if sleeve not in SLEEVES:
        raise ValueError(f"unknown sleeve {sleeve!r}: use {', '.join(SLEEVES)}")
    r = con.execute("SELECT sleeve FROM sleeves_s81 WHERE market=? AND isin=?", [market, isin]).fetchone()
    if r is None:
        con.execute("INSERT INTO sleeves_s81 VALUES (?,?,?,?)", [market, isin, sleeve, day or date.today()])
        return sleeve
    if force and r[0] != sleeve:
        con.execute("UPDATE sleeves_s81 SET sleeve=? WHERE market=? AND isin=?", [sleeve, market, isin])
        return sleeve
    return r[0]


def sleeve_weights(con, market: str = "IN", day: Optional[date] = None) -> Dict[str, float]:
    """Each sleeve's share of the book's value (fractions; `cash` is what is not invested). The book is the system's paper book (`paper/book.py`)."""
    from pflab.paper import book
    day = day or date.today()
    h = book.holdings(con, day)
    total = float(h["value"] or 0.0)
    out = {s: 0.0 for s in SLEEVES}
    out["cash"] = 0.0
    if total <= 0:
        return out
    for r in h["rows"]:
        out[sleeve_of(con, r["isin"], market)] += (r["value"] or 0.0) / total
    out["cash"] = (float(h["cash"]) + float(h.get("bank", 0.0))) / total
    return {k: round(v, 6) for k, v in out.items()}


def tag_order(con, isin: str, day: Optional[date], pid: str, market: str = "IN", sleeve: Optional[str] = None) -> str:
    """Called as an order is placed: tag the position with the sleeve the placing policy works in (`sleeve` when it says, else the default for the instrument)."""
    return set_sleeve(con, isin, sleeve or default_sleeve(con, isin), day, market)


# --- the target shares ---------------------------------------------------------------------------------------------------------------

def default_shares(cfg: dict) -> dict:
    """The system's starting target from `configs/core.toml [baseline_v2]`, as fractions of the book."""
    b = cfg["baseline_v2"]
    core, gold, intl = float(b["core_pct"]) / 100.0, float(b["gold_pct"]) / 100.0, float(b["international_pct"]) / 100.0
    return {"core": core, "longterm": float(b["longterm_pct"]) / 100.0, "gold": gold, "international": intl, "cash": 0.0,
            "index": max(0.0, core - gold - intl), "source": "the starting default"}


def stored(con, target_id: int) -> Optional[dict]:
    r = con.execute("SELECT sleeves_json, variant_policy FROM allocation_sleeves_s81 WHERE target_id=?", [int(target_id)]).fetchone()
    return None if r is None else {"sleeves": json.loads(r[0]), "variant_policy": r[1]}


def target_shares(con, cfg: dict, target: Optional[dict]) -> dict:
    """The shares the baseline holds the book to, as fractions of the book: the active allocation's (classes plus its sleeve shares) or the starting default when there is none
    (or the active one has no sleeve shares: an older, class-only target is not guessed at)."""
    if target and target.get("id") is not None:
        s = stored(con, target["id"])
        if s:
            sl = {k: float(s["sleeves"].get(k, 0.0)) / 100.0 for k in SLEEVES}
            cl = {k: float(target["classes"].get(k, 0.0)) / 100.0 for k in ("gold", "international", "cash")}
            return {**sl, **cl, "index": max(0.0, sl["core"] - cl["gold"] - cl["international"] - cl["cash"]), "source": f"allocation target #{target['id']}"}
    return default_shares(cfg)


def check_proposal(classes: dict, sleeves: dict) -> dict:
    """The sleeve caps of his answer, in code: longterm at most 60%, core at least 30%, the two summing to 100 (a `swing` entry is accepted only as zero: the swing sleeve is deleted,
    A60); gold, international and cash (core holdings) cannot add up to more than the core. -> {ok, problems, sleeves}. Percent of the book."""
    problems = []
    sl = {}
    if "swing" in (sleeves or {}):
        try:
            sw = float(sleeves["swing"])
        except (TypeError, ValueError):
            sw = float("nan")
        if sw != sw or abs(sw) > 1e-9:
            problems.append("the swing sleeve is deleted (its study failed, A60): give core and longterm only")
        sleeves = {k: v for k, v in sleeves.items() if k != "swing"}
    for k in SLEEVES:
        try:
            v = float(sleeves.get(k))
        except (TypeError, ValueError):
            problems.append(f"the {k} sleeve share is missing or not a number")
            continue
        if v != v or v < 0:
            problems.append(f"the {k} sleeve share must be zero or more")
            continue
        sl[k] = v
    if problems:
        return {"ok": False, "problems": problems, "sleeves": sl}
    extra = set(sleeves) - set(SLEEVES)
    if extra:
        problems.append(f"unknown sleeve(s) {sorted(extra)}: use {', '.join(SLEEVES)}")
    tot = sum(sl.values())
    if abs(tot - 100.0) > 0.05:
        problems.append(f"the sleeve shares add up to {tot:g}%, not 100%")
    if sl["longterm"] > CAPS["longterm_max"] + 1e-9:
        problems.append(f"longterm at {sl['longterm']:g}% is over the {CAPS['longterm_max']:g}% cap")
    if sl["core"] < CAPS["core_min"] - 1e-9:
        problems.append(f"core at {sl['core']:g}% is under the {CAPS['core_min']:g}% floor")
    in_core = sum(float((classes or {}).get(k, 0.0) or 0.0) for k in ("gold", "international", "cash"))
    if in_core > sl["core"] + 0.05:
        problems.append(f"gold, international and cash add up to {in_core:g}% but the core is {sl['core']:g}%: they are core holdings")
    return {"ok": not problems, "problems": problems, "sleeves": {k: round(v, 4) for k, v in sl.items()}}
