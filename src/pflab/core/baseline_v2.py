"""`baseline_v2` (S81, A48-A49): the baseline of the close loop, core + satellite. It needs no proven edge and acts from the first close.

    core      it may BUY the core ETFs (index, gold, international) up to the system's allocation target; the ETF list comes from `configs/core.toml [baseline_v2]`
              (symbols the store knows: Nifty 500 and Nifty 50 index ETFs, a gold ETF, a Nasdaq 100 ETF listed in India), each sized by risk and held to the 35% ETF rail
    longterm  the held stock names stay as they are: they are bought toward their risk size while the sleeve is under its target and never sold to reach a sleeve share
    swing     its share is held back as cash for the swing sleeve; baseline_v2 itself never trades it
    gauge     when the fall gauge fires every equity position (index ETFs and longterm names) is cut by `gauge_cut`, the difference kept in cash; gold and international stay

THE PATH TO THE TARGET IS GRADUAL AND TAX-AWARE (his answer, 2026-11-09): new cash (a top-up) and any sale proceeds go to the core ETFs first, then to longterm names under their risk
size; a position above its target is left alone (no sale for the sake of 60/35/5). Stocks are sold only for the exit manager's reasons (tax harvesting, a stop, a thesis break) and
by the rails (a name over its 10% rail is trimmed to it), never to reach a sleeve share.

`decide(state)` has the interface of `policy.decide`: -> {'weights': {isin: target fraction of the book}, 'notes': [...], 'classes': {class: fraction}, 'sleeves': {...}}.
"""
from __future__ import annotations

import hashlib
import inspect
from typing import Dict, List

POLICY_ID = "baseline_v2"
NOTE = "the baseline: buy and hold the core ETFs toward the allocation target, keep the longterm names, cut equity when the fall gauge fires; new cash goes to the core first"


def code_hash() -> str:
    return hashlib.sha256(inspect.getsource(__import__(__name__, fromlist=["x"])).encode("utf-8")).hexdigest()[:16]


def core_symbols(cfg: dict) -> Dict[str, List[str]]:
    b = cfg["baseline_v2"]
    return {"index": list(b["index_etfs"]), "gold": list(b["gold_etfs"]), "international": list(b["international_etfs"])}


def core_isins(con, cfg: dict) -> List[str]:
    """The ISINs of the configured core ETFs the store knows (a symbol the store does not know is left out: it is named in the card, never guessed)."""
    from pflab.paper import book
    out = []
    for syms in core_symbols(cfg).values():
        for s in syms:
            i = book.isin_of(con, s)
            if i and i not in out:
                out.append(i)
    return out


def _group(r: dict) -> str:
    """index / gold / international / cash for a core ETF row."""
    k = r["klass"]
    return "index" if k == "equity" else k


def decide(state: dict) -> dict:
    from pflab.core import policy
    cfg = state["cfg"]
    cut = float(cfg["baseline"]["gauge_cut"])
    total = float(state["value"])
    rows = state["rows"]
    notes: List[str] = []
    if total <= 0:
        return {"weights": {}, "notes": ["the book has no value"], "classes": {}, "sleeves": {}}
    sh = state["sleeve_target"]
    notes.append(f"target ({sh['source']}): core {sh['core']:.0%} (index {sh['index']:.0%}, gold {sh['gold']:.0%}, intl {sh['international']:.0%}), longterm {sh['longterm']:.0%}, swing {sh['swing']:.0%}")
    cur = {r["isin"]: r["value"] / total for r in rows}
    no_buy = set(state.get("no_buy") or ())                       # B8: an international ETF trading far above its NAV is skipped
    gauge = bool(state["gauge"]["fired"])
    weights: Dict[str, float] = {}
    inc_core: Dict[str, float] = {}
    inc_lt: Dict[str, float] = {}
    # --- core: each group's budget split by risk among the buyable ETFs; a position above its target stays ---------------------------------------------------------------
    for grp in ("index", "gold", "international"):
        members = [r for r in rows if r["sleeve"] == "core" and r["buyable"] and _group(r) == grp]
        if not members:
            if sh[grp] > 0:
                notes.append(f"no {grp} ETF has a price: {sh[grp]:.0%} stays cash")
            continue
        inv = {r["isin"]: 1.0 / max(state["vol"].get(r["isin"], 0.30), 0.05) for r in members}
        caps = {r["isin"]: policy.cap_of(r) for r in members}
        want = policy.risk_weights(sh[grp], inv, caps)
        for r in members:
            k = r["isin"]
            t = want.get(k, 0.0)
            if gauge:
                weights[k] = cur[k] * (1.0 - cut)                           # a risk cut: equity only (gold and international are not equity)
                if grp != "index":
                    weights[k] = cur[k]
                continue
            weights[k] = max(cur[k], t)                                    # never sold to reach the target
            if k in no_buy:
                weights[k] = cur[k]
            elif t > cur[k]:
                inc_core[k] = t - cur[k]
    # --- longterm: the held names; bought toward their risk size while the sleeve is under its share, never sold for a sleeve share ---------------------------------------------
    lt = [r for r in rows if r["sleeve"] == "longterm" and r["buyable"]]
    lt_now = sum(cur[r["isin"]] for r in lt)
    if lt:
        budget = max(sh["longterm"], 0.0) if lt_now < sh["longterm"] else lt_now
        inv = {r["isin"]: 1.0 / max(state["vol"].get(r["isin"], 0.30), 0.05) for r in lt}
        caps = {r["isin"]: policy.cap_of(r) for r in lt}
        want = policy.risk_weights(budget, inv, caps)
        for r in lt:
            k = r["isin"]
            if gauge:
                weights[k] = cur[k] * (1.0 - cut)
                continue
            t = want.get(k, 0.0)
            hi = caps[k]
            if cur[k] > hi + 1e-9:                                         # over the company rail: trimmed to it (a rail trim, an A51 reason)
                weights[k] = hi
                notes.append(f"{r['symbol']} {cur[k]:.1%} is over the {hi:.0%} rail: trim to the rail")
            else:
                weights[k] = max(cur[k], t if lt_now < sh["longterm"] else cur[k])
                if weights[k] > cur[k]:
                    inc_lt[k] = weights[k] - cur[k]
    if gauge:
        notes.append(f"fall gauge fired ({state['gauge']['why']}): equity cut by {cut:.0%}, the difference kept in cash; no buying")
        return {"weights": weights, "notes": notes, "classes": _classes(sh), "sleeves": _sleeves(sh)}
    # --- the path: new cash and sale proceeds go to the core first, then to longterm; the swing share is held back --------------------------------------------------------------------
    sales = sum(max(0.0, cur[k] - w) for k, w in weights.items())
    free = max(0.0, (state["cash"] + state.get("bank", 0.0)) / total) + sales
    swing_now = sum(cur[r["isin"]] for r in rows if r["sleeve"] == "swing")
    reserve = max(0.0, sh["swing"] - swing_now) if cfg["baseline_v2"].get("swing_reserve", True) else 0.0
    free_buy = max(0.0, free - reserve)
    core_need = sum(inc_core.values())
    if core_need > free_buy and core_need > 0:
        f = free_buy / core_need
        for k, v in inc_core.items():
            weights[k] = cur[k] + v * f
        for k in inc_lt:
            weights[k] = cur[k]
        notes.append(f"cash {free:.1%} (swing {reserve:.1%} held back): {f:.0%} of the core gap bought now, longterm names wait")
    else:
        left = free_buy - core_need
        lt_need = sum(inc_lt.values())
        if lt_need > left:
            f = left / lt_need if lt_need > 0 else 0.0
            for k, v in inc_lt.items():
                weights[k] = cur[k] + v * f
            notes.append(f"core gap covered; {f:.0%} of the longterm gap bought with the cash left")
        elif core_need or lt_need:
            notes.append("cash covers the whole gap to the target")
    if not inc_core and not inc_lt:
        notes.append("nothing to buy: at or above target everywhere (positions above target are held, not sold)")
    return {"weights": weights, "notes": notes, "classes": _classes(sh), "sleeves": _sleeves(sh)}


def _classes(sh: dict) -> Dict[str, float]:
    return {"equity": sh["index"] + sh["longterm"] + sh["swing"], "gold": sh["gold"], "international": sh["international"], "cash": sh["cash"]}


def _sleeves(sh: dict) -> Dict[str, float]:
    return {"core": sh["core"], "longterm": sh["longterm"], "swing": sh["swing"]}
