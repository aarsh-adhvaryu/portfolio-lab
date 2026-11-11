"""Allocation in the lab (S81, A49-A50): the strategist OWNS the system's allocation; code checks it and the lab judges it like any policy.

    propose(...)     the strategist's `propose_allocation` tool: classes, sectors, sleeve shares and reasons. Code checks the rails (`paper/allocation.validate_target`) and the sleeve caps of his
                     answer (`core/sleeves.check_proposal`: longterm at most 60%, core at least 30%, summing to 100; the swing sleeve is deleted, A60); a good proposal is stored as a PROPOSED target
                     (`paper/allocation.propose_allocation`) with its sleeve shares, and stands in the lab as an allocation VARIANT (`alloc_t<id>`).
    seed(...)        the always-present candidates (idempotent): `index_hold` (the index ETFs only: "hold the index") and `alloc_default` (the system's starting target)
    tick(...)        runs the candidates' history replays, then adopts by the A50 rule: a proposal becomes the ACTIVE target when its history passes the two-dimension index rule (after tax and
                     charges on both sides) and is not below the current allocation's, and its once-only 2018-2021 check passes the same rule. When the current allocation itself fails the index
                     rule and the index-only variant passes, the system owns the index: an index-only target is adopted by code. Every verdict is stored with its figures.

An allocation variant is one fixed-split policy (`render_code`): the index ETFs, the gold ETF, the international ETF and risk-sized liquid stocks for the longterm sleeve, the fall gauge, and no sale for the sake of the split (positions above their share are held: the gradual, tax-aware path of baseline_v2). Replay models each ETF as its index
total-return series less a stated yearly cost where the ETF did not exist (`runner.CORE_SYNTH`).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from pflab import core
from pflab.core import sleeves
from pflab.lab import promotion, service

INDEX_HOLD, DEFAULT_ID = "index_hold", "alloc_default"
IDX_SYMS = ("MONIFTY500", "NIFTYBEES", "JUNIORBEES")         # the live baseline's index ETFs (configs/core.toml [baseline_v2] index_etfs): three, so the 35% ETF rail lets the whole book sit in the index
INDEX_ONLY_SYMS = IDX_SYMS

TEMPLATE = '''"""An allocation variant: a fixed split of the book (S81). Index ETFs, a gold ETF, an international ETF, risk-sized liquid stocks for the longterm sleeve;
the fall gauge cuts equity; nothing is sold to reach the split (a position above its share is held), as the live baseline does."""
from toolkit import inverse_vol, volatility, cap_and_fill, fall_gauge, rank_top

DEFAULTS = __DEFAULTS__


def decide(state, forecasts, sims, storylines, params=None):
    p = dict(DEFAULTS)
    p.update(params or {})
    prices, meta, caps, cur = state["prices"], state["meta"], state["caps"], state["weights"]
    sym = {meta[k]["symbol"]: k for k in state["universe"] if meta[k]["etf"]}
    stocks = [k for k in state["universe"] if not meta[k]["etf"]]
    out = {}

    def put(keys, budget):
        keys = [k for k in keys if k in prices.columns]
        if keys and budget > 0:
            out.update(cap_and_fill(inverse_vol(keys, volatility(prices[keys])), caps, 0.10, budget=budget))

    idx_keys = [sym[s] for s in p["idx_syms"] if s in sym]
    put(idx_keys, p["idx"])
    put([sym[s] for s in p["gold_syms"] if s in sym], p["gold"])
    put([sym[s] for s in p["intl_syms"] if s in sym], p["intl"])
    liquid = rank_top({k: float(state["turnover"][k].tail(250).median()) for k in stocks}, int(p["n_stocks"]))
    put(liquid, p["longterm"])
    equity = set(idx_keys) | set(stocks)
    if fall_gauge(state["index"]):
        w = {}
        for k, v in cur.items():
            w[k] = v * (1.0 - p["gauge_cut"]) if k in equity else v
        return w
    if p["drift_only"]:
        for k, v in cur.items():
            if v > out.get(k, 0.0):
                out[k] = v
    return out
'''

BASE = {"idx": 0.40, "gold": 0.10, "intl": 0.10, "longterm": 0.40, "n_stocks": 30, "gauge_cut": 0.25, "drift_only": True,
        "idx_syms": list(IDX_SYMS), "gold_syms": ["GOLDBEES"], "intl_syms": ["MON100"]}


def render_code(params: dict) -> str:
    p = {**BASE, **params}
    return TEMPLATE.replace("__DEFAULTS__", repr(dict(sorted(p.items()))))


def default_params(cfg: Optional[dict] = None) -> dict:
    """The starting target of `configs/core.toml [baseline_v2]` as a variant's parameters (fractions of the book)."""
    cfg = cfg or core.settings()
    sh = sleeves.default_shares(cfg)
    b = cfg["baseline_v2"]
    return {"idx": round(sh["index"], 4), "gold": round(sh["gold"], 4), "intl": round(sh["international"], 4), "longterm": round(sh["longterm"], 4),
            "idx_syms": list(b["index_etfs"]), "gold_syms": list(b["gold_etfs"]), "intl_syms": list(b["international_etfs"])}


def candidates(cfg: Optional[dict] = None) -> Dict[str, dict]:
    idx_syms = list((cfg or core.settings())["baseline_v2"]["index_etfs"])
    return {INDEX_HOLD: {"params": {"idx": 0.98, "gold": 0.0, "intl": 0.0, "longterm": 0.0, "idx_syms": idx_syms},
                         "hypothesis": "Hold the index ETFs only (Nifty 500, Nifty 50 and Next 50 index ETFs), nothing else: the A50 benchmark made a candidate, so when nothing beats the index the system owns it."},
            DEFAULT_ID: {"params": default_params(cfg),
                         "hypothesis": "The system's starting allocation (core 60 with gold 10 and international 10, longterm 40), as a variant the lab can score like any policy."}}


def seed(con, pm_dir: Path, now: datetime) -> list:
    """Register the always-present candidates (once: a policy that exists is left alone). -> the ids added."""
    added = []
    for pid, c in candidates().items():
        if service.get(con, pid):
            continue
        r = service.add_variant(con, pm_dir, now, pid, render_code(c["params"]), c["hypothesis"])
        if r.get("ok"):
            added.append(pid)
    return added


def family(con) -> list:
    """Every allocation variant alive: the two candidates and the strategist's proposals (`alloc_t<id>`)."""
    return [r[0] for r in con.execute("SELECT policy_id FROM core_policies_s80 WHERE (policy_id IN (?,?) OR policy_id LIKE 'alloc_t%') AND status <> 'retired' ORDER BY policy_id", [INDEX_HOLD, DEFAULT_ID]).fetchall()]


# --- the strategist's tool ---------------------------------------------------------------------------------------------------------------------

def proposal_params(classes: dict, sleeves_pct: dict) -> dict:
    gold, intl, cash = (float(classes.get(k, 0.0)) for k in ("gold", "international", "cash"))
    core_pct = float(sleeves_pct["core"])
    return {"idx": round(max(0.0, core_pct - gold - intl - cash) / 100.0, 4), "gold": round(gold / 100.0, 4), "intl": round(intl / 100.0, 4),
            "longterm": round(float(sleeves_pct["longterm"]) / 100.0, 4)}


def propose(con, pm_dir: Path, now: datetime, classes: dict, sleeves_pct: dict, reasons: str, sectors: Optional[dict] = None, market: str = "IN", by: str = "the strategist") -> dict:
    """Check and store the strategist's allocation proposal. Never changes the active target by itself: adoption is `tick` (the A50 rule)."""
    from pflab.paper import allocation
    chk = sleeves.check_proposal(classes or {}, sleeves_pct or {})
    if not chk["ok"]:
        return {"ok": False, "problem": "; ".join(chk["problems"]), "caps": sleeves.CAPS}
    act = allocation.active_target(con, market)
    if act:
        same_cls = allocation._same(act["classes"], {k: float(v) for k, v in (classes or {}).items()}) and allocation._same(act["sectors"], {k: float(v) for k, v in (sectors or {}).items()})
        old = sleeves.stored(con, act["target_id"])
        if same_cls and old and any(abs(float(old["sleeves"].get(k, 0.0)) - float(chk["sleeves"][k])) > allocation.TOL for k in sleeves.SLEEVES):
            return {"ok": False, "problem": "the classes and sectors equal the active target and only the sleeve shares differ: move a class or sector weight by at least 0.1 point too, so it is a new target"}
    r = allocation.propose_allocation(con, classes, reasons, now, sectors=sectors, by=by, market=market)
    if not r.get("stored"):
        return {"ok": False, "problem": r.get("problem", "the proposal was not stored"), "rails": r.get("rails")}
    if r.get("reaffirmed"):
        return {"ok": True, "reaffirmed": True, "target_id": r["target_id"], "note": "the active target stands: this is its re-examination for the week (recorded with your reasons)"}
    tid = r["target_id"]
    pid = f"alloc_t{tid}"
    code = render_code({**default_params(), **proposal_params(r["classes"], chk["sleeves"])})
    v = service.add_variant(con, pm_dir, now, pid, code, ("allocation proposal #%d: " % tid) + " ".join(str(reasons).split())[:200])
    con.execute("INSERT OR REPLACE INTO allocation_sleeves_s81 VALUES (?,?,?,?,?)", [tid, market, json.dumps(chk["sleeves"], sort_keys=True), pid if v.get("ok") else None, now])
    return {"ok": True, "target_id": tid, "variant": pid if v.get("ok") else None, "classes": r["classes"], "sectors": r["sectors"], "sleeves": chk["sleeves"], "status": "proposed",
            "next": f"run_lab on {pid} (it is a plain policy: the lab replays it 2005-2017 after tax and charges); code adopts it when it passes the A50 rule against the index and the "
                    "once-only 2018-2021 check, and is not below the current allocation. Until then the current target stands."}


# --- adoption (A50) ----------------------------------------------------------------------------------------------------------------------------

def current_variant(con, market: str = "IN") -> str:
    from pflab.paper import allocation
    act = allocation.active_target(con, market)
    if act:
        s = sleeves.stored(con, act["target_id"])
        if s and s.get("variant_policy"):
            return s["variant_policy"]
    return DEFAULT_ID


def _hist(con, pid: str) -> Optional[dict]:
    return service.latest_run(con, pid, "history")


def _verdict(con, now: datetime, target_id, pid: str, outcome: str, reasons: list, figures: dict) -> None:
    from pflab.pm.store import next_id
    con.execute("INSERT INTO alloc_verdicts_s81 VALUES (?,?,?,?,?,?,?)", [next_id(con, "alloc_verdicts_s81", "verdict_id"), target_id, pid, now, outcome, json.dumps(reasons), json.dumps(figures, default=str)])


def run_candidates(con, pm_dir: Path, root, now: datetime, data=None, box=None) -> list:
    """History replays for the family members that have none yet. Each is a trial in the deflated Sharpe, like any variant."""
    ran = []
    for pid in family(con):
        if _hist(con, pid) is None:
            r = service.run_lab(con, pm_dir, root, now, pid, n_shuffles=0, data=data, box=box)
            ran.append({"policy_id": pid, "ok": bool(r.get("ok")), "problem": r.get("problem")})
    return ran


def adopt_index_only(con, now: datetime, why: str) -> dict:
    """The system owns the index: an index-only target (core 100) becomes the ACTIVE target, by code, with the figures as its reasons."""
    from pflab.paper import allocation
    cls = {"equity": 100.0, "gold": 0.0, "international": 0.0, "cash": 0.0}
    sl = {"core": 100.0, "longterm": 0.0}
    r = allocation.propose_allocation(con, cls, why, now, sectors={}, by="the lab (A50 index rule)")
    if not r.get("stored") or r.get("reaffirmed"):
        return {"adopted": False, "problem": r.get("problem") or "an index-only target is already active"}
    con.execute("INSERT OR REPLACE INTO allocation_sleeves_s81 VALUES (?,?,?,?,?)", [r["target_id"], "IN", json.dumps(sl, sort_keys=True), INDEX_HOLD, now])
    a = allocation.review_target(con, r["target_id"], "approve", "adopted by code: the A50 rule (nothing else passes the index rule)", now)
    return {"adopted": bool(a.get("done")), "target_id": r["target_id"]}


def tick(con, pm_dir: Path, root, now: datetime, data=None, box=None, run_final: bool = True) -> dict:
    """Seed, replay what has no run, adopt by the A50 rule. Cheap when nothing is pending (a few queries); idempotent."""
    from pflab.paper import allocation
    out: dict = {"seeded": seed(con, pm_dir, now)}
    out["ran"] = run_candidates(con, pm_dir, root, now, data=data, box=box)
    cur_id = current_variant(con)
    cur = _hist(con, cur_id)
    idx = _hist(con, INDEX_HOLD)
    out["current"] = cur_id
    if cur is not None:
        ir = service.index_rule(cur["score"])
        out["current_vs_index"] = {"ok": ir["ok"], "via": ir.get("via"), **ir.get("figures", {})}
        if (not ir["ok"] and idx is not None and cur_id != INDEX_HOLD and service.index_rule(idx["score"])["ok"]
                and core.settings()["baseline_v2"].get("index_fallback", True)):
            why = (f"After tax and charges the current allocation ({cur_id}) fails the index rule over 2005-2017 ({'; '.join(ir['failed'])}) while holding the index ETFs passes it: "
                   "the system owns the index until a proposal beats it.")
            out["adopted_index_only"] = adopt_index_only(con, now, why)
            _verdict(con, now, (out["adopted_index_only"] or {}).get("target_id"), INDEX_HOLD, "adopted", [why], ir.get("figures", {}))
            cur_id = current_variant(con)
            cur = _hist(con, cur_id)
    out["verdicts"] = []
    for t in allocation.pending(con):
        s = sleeves.stored(con, t["target_id"])
        pid = (s or {}).get("variant_policy")
        if not pid:
            continue
        h = _hist(con, pid)
        if h is None:
            continue
        reasons, fig = [], {}
        ir = service.index_rule(h["score"])
        reasons += ir["failed"]
        fig["history"] = ir.get("figures", {})
        if cur is not None and cur["score"].get("cagr_liq") is not None and h["score"].get("cagr_liq") is not None and h["score"]["cagr_liq"] <= cur["score"]["cagr_liq"]:
            reasons.append(f"its history return after tax {h['score']['cagr_liq']:.1%} is not above the current allocation's {cur['score']['cagr_liq']:.1%}")
        if not reasons and run_final:
            f = promotion.final_run(con, pm_dir, root, now, pid, {}, data=data, box=box)
            if f.get("error"):
                reasons.append("the final check could not run: " + f["error"])
            else:
                fi = service.index_rule(f["score"])
                fig["final"] = fi.get("figures", {})
                reasons += [f"final check 2018-2021: {x}" for x in fi["failed"]]
        if reasons:
            allocation.review_target(con, t["target_id"], "reject", "; ".join(reasons)[:580], now)
            _verdict(con, now, t["target_id"], pid, "not adopted", reasons, fig)
            out["verdicts"].append({"target_id": t["target_id"], "outcome": "not adopted", "reasons": reasons[:3]})
        else:
            allocation.review_target(con, t["target_id"], "approve", "adopted by the A50 rule: passes the index rule on 2005-2017 and on the once-only 2018-2021 check, above the current allocation", now)
            _verdict(con, now, t["target_id"], pid, "adopted", [], fig)
            out["verdicts"].append({"target_id": t["target_id"], "outcome": "adopted"})
            cur_id = pid
            cur = h
    return out


def status_text(con, now: datetime) -> str:
    """A few lines for the strategist's first message: the allocation in force, what waits, and how the candidates stand against the index."""
    from pflab.paper import allocation
    act = allocation.active_target(con)
    cfg = core.settings()
    sh = sleeves.target_shares(con, cfg, {"id": act["target_id"], "classes": act["classes"], "sectors": act["sectors"]} if act else None)
    lines = [f"ALLOCATION IN FORCE ({sh['source']}): core {sh['core']:.0%} (index {sh['index']:.0%}, gold {sh['gold']:.0%}, international {sh['international']:.0%}), longterm {sh['longterm']:.0%}. "
             f"Caps: longterm <= {sleeves.CAPS['longterm_max']:g}%, core >= {sleeves.CAPS['core_min']:g}%. "
             "You own it: re-examine it this week; call propose_allocation to change it, or the same split again to record that it stands."]
    for pid in family(con):
        h = _hist(con, pid)
        if h is None:
            lines.append(f"- {pid}: no history run yet")
            continue
        ir = service.index_rule(h["score"])
        f = ir.get("figures", {})
        lines.append(f"- {pid}: {'passes' if ir['ok'] else 'fails'} the index rule" + (f" ({f['policy_return_after_tax']:.1%} a year after tax against the index's {f['index_return_after_tax']:.1%}; worst fall {f['policy_worst_fall']:.1%} against {f['index_worst_fall']:.1%})" if f else ""))
    pend = allocation.pending(con)
    if pend:
        lines.append("WAITING for the A50 check: " + ", ".join(f"#{t['target_id']}" for t in pend))
    return "\n".join(lines)
