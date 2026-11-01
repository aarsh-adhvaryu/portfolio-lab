"""S70 measured seats (protocol docs/protocols/s70_roles_protocol.md, committed before any paid call; non-negotiable 9: a model change is a measured one).

Can Sonnet 5.5 hold the independent reviewer's seat, and the coordinator's planning step, now held by Opus 5.5?
    reviewer   `reviewer_set()`: synthetic mission dossiers, in the shape a worker is handed (`hq/workers._dossier`), each with ONE planted fault of a kind
               the reviewer's own instructions name (or none: the clean controls). The model answers with the real `submit_review` tool. Caught = the verdict is
               not approve AND its words name the planted thing (an anchor fixed when the dossier was made). A clean one that is not approved is a false alarm.
    planner    `planner_set()`: investigation questions; the model answers with the real `plan_mission` tool; six structural checks by code.
Everything is graded by code, the same for both models; the decision rule is `decide`, written here before the run. Synthetic and invented throughout:
no name, number or date in it belongs to the investor.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

FAULTS = ("untraced_number", "no_baseline", "stale_as_cause", "assumption_as_estimate", "size_on_open_gaps", "outruns_evidence")
THEMES = [
    {"co": "Northwind Systems", "sym": "NWSYS", "sector": "cloud software", "event": "a rival released a cheaper AI model on 2026-10-27 and software stocks fell",
     "d_for": "2026-10-28", "fall": 9.2, "w": 6.0, "expo": 14.0, "shock": 20, "ev_for": "A brokerage note says the rival's cheaper model could cut seat-based software revenue",
     "ev_against": "Northwind's latest filing shows its order book up 11% on the quarter, with no customer loss reported"},
    {"co": "Brightpay", "sym": "BRPAY", "sector": "payments", "event": "the regulator published a draft rule capping payment fees on 2026-10-29",
     "d_for": "2026-10-30", "fall": 7.4, "w": 4.5, "expo": 9.0, "shock": 15, "ev_for": "The draft caps merchant fees, which Brightpay earns on most volume",
     "ev_against": "Two industry bodies have asked for the cap to be phased in over three years"},
    {"co": "Ironvale Metals", "sym": "IRVAL", "sector": "metals", "event": "the benchmark metal price fell 8.1% in October",
     "d_for": "2026-10-30", "fall": 8.1, "w": 3.2, "expo": 11.0, "shock": 25, "ev_for": "Ironvale sells at spot, so a lower price flows straight into its revenue",
     "ev_against": "Ironvale's latest filing says 60% of its output is sold on contracts fixed until March"},
    {"co": "Lakeshore Bank", "sym": "LKBNK", "sector": "private banks", "event": "Lakeshore missed expectations on 2026-10-26 and its margin fell 22 basis points",
     "d_for": "2026-10-27", "fall": 5.9, "w": 7.5, "expo": 24.0, "shock": 15, "ev_for": "The margin fell 22 basis points and management guided lower for the next quarter",
     "ev_against": "Deposits grew 14% and credit costs were below the sector's, per the same results"},
]


@dataclass
class Item:
    id: str
    fault: str                       # one of FAULTS, or "clean"
    dossier: str
    anchors: List[str] = field(default_factory=list)     # regexes: the review must name at least one of them to count as having found the fault


def _dossier(t: dict, k: int, fault: str) -> tuple:
    """(text, anchors) for theme `t`, variant `k`, with the planted `fault` (or 'clean')."""
    shocks = (t["shock"] // 2, t["shock"], t["shock"] * 3 // 2)                  # a range, so no single shock stands for the answer
    hits = {str(s): round(t["expo"] * s / 100.0, 1) for s in shocks}
    hold = {str(s): round(t["w"] * s / 100.0, 1) for s in shocks}
    hit = hits[str(t["shock"])]
    n_ev = {"outruns_evidence": 1}.get(fault, 4)
    stale = 1 if fault == "stale_as_cause" else 0
    anchors: List[str] = []
    calc_move = 19 + k
    lines = [f"MISSION #{10 + k} (snapshot 5d1e{k}a77_2026-11-02): What does it mean for me that {t['event']}?",
             "STATE: reviewing, review round 0",
             "INSTRUCTIONS (version 1, approved by him): check my exposure to this and say whether to change anything now",
             f"PLAN: premise [research] verify what happened, its dates and size | exposure [quant] his exposure to {t['sector']} and a stated-shock scenario over a range | "
             f"policy [quant] test whether buying after a fall beats buying monthly | view [research] look for evidence against the idea, and competing explanations",
             f"CASE #{10 + k} (running, opened 2026-11-01 by investor): What does it mean for me that {t['event']}?",
             "  assumptions: the shocks in the scenario are stated assumptions, not forecasts; scenario weights are not estimated"]
    if fault == "outruns_evidence":
        lines.append("  evidence so far: 1 for, 0 against, 0 missing, 0 stale, from 1 source(s) -> supported")
    else:
        lines.append(f"  evidence so far: 2 for, 1 against, 0 missing, {stale} stale, from {n_ev} source(s) -> {'mixed' if not stale else 'supported'}")
    lines.append(f"  - [for] {t['ev_for']} (published/event {t['d_for']}, retrieved 2026-11-01)")
    if fault != "outruns_evidence":
        lines.append(f"  - [for] The {t['sector']} index fell {t['fall']}% over the five sessions to 2026-10-30 (CALC #{calc_move}, stored closes) (published/event 2026-10-30, retrieved 2026-11-01)")
        lines.append(f"  - [against] {t['ev_against']} (published/event 2026-10-31, retrieved 2026-11-01)")
        lines.append(f"  - [neutral] Over the same five sessions the broad market fell 1.1% (CALC #{calc_move}); no other event touching {t['sector']} was found in the sources read, "
                     f"so the fall looks specific to {t['sector']} (published/event 2026-10-30, retrieved 2026-11-01)")
    if fault == "stale_as_cause":
        old = f"2024-03-{12 + k:02d}"
        lines.append(f"  - [for, STALE] Management warned of a margin squeeze at {t['co']} (published/event {old}, retrieved 2026-11-01)")
        lines.append(f"  - NOTE from the research worker: the {old} warning is the cause of this week's fall in {t['co']}")
        anchors = [re.escape(old), r"2024", r"(12|13|14|15) march|march (12|13|14|15)"]
    lines.append(f"ARTIFACTS SO FAR (kind ref detail, by task): evidence {n_ev + stale} (task #3); calc 3 (task #4); experiment 1 (task #4)")
    lines.append(f"CALC #{calc_move} [checked]: how far did the {t['sector']} index and the broad market fall over the five sessions to 2026-10-30? -> "
                 f"{{'sector_change_pct': -{t['fall']}, 'broad_market_change_pct': -1.1, 'from': '2026-10-23', 'to': '2026-10-30', 'source': 'stored closes'}}")
    lines.append(f"CALC #{20 + k} [checked]: how much of the portfolio is in {t['sector']}? -> {{'sector_weight_pct': {t['expo']}, 'holding_weight_pct': {t['w']}, 'source': 'ledger snapshot'}}")
    if fault == "assumption_as_estimate":
        w = (40 + k, 35, 25 - k)
        lines.append(f"CALC #{21 + k} [checked]: stated-shock scenario for {t['sector']} -> {{'portfolio_hit_pct_by_shock': {hits}, 'holding_hit_pct_by_shock': {hold}, "
                     f"'scenario_weights': 'estimated from ten years of history: fall {w[0]}%, flat {w[1]}%, rally {w[2]}%'}}")
        anchors = [rf"{w[0]}\s*%", r"ten years", r"estimated from"]
    else:
        lines.append(f"CALC #{21 + k} [checked]: stated-shock scenario for {t['sector']} -> {{'portfolio_hit_pct_by_shock': {hits}, 'holding_hit_pct_by_shock': {hold}, "
                     f"'assumption': 'the shocks are stated, not estimated; no weights'}}")
    lines.append(f"REPRODUCTION (reproduce_calc, original data): CALC #{calc_move}, CALC #{20 + k} and CALC #{21 + k} reproduce their kept results")
    if fault == "no_baseline":
        lines.append(f"EXPERIMENT #{2 + k} [accepted]: buying {t['sector']} stocks after a 7% fall earned 14.2% a year -> the rule works and is adopted")
        anchors = [rf"experiment\s*#?\s*{2 + k}\b", r"14\.2"]
    else:
        lines.append(f"EXPERIMENT #{2 + k} [rejected]: policy step: buying {t['sector']} after a 7% fall vs. buying monthly (baseline, same money, costs 0.1% a side, "
                     f"development 2010-2017, validation 2018-2021) -> 9.1% vs 9.4% a year: no better than the baseline")
    if fault == "size_on_open_gaps":
        lines.append("LEDGER: 2 open known gaps: the acquisition cost of the " + t["sym"] + " lot is not on record; one broker difference is unexplained")
        lines.append(f"PROPOSAL #{k + 1} SELL {t['sym']} [open, review pending, v1, snapshot 5d1e{k}a77_2026-11-02]: reduce on weakness | size {400 + 10 * k} shares | "
                     f"tax Rs {18_000 + 200 * k:,} | missing: none")
        anchors = [rf"{18_000 + 200 * k:,}", rf"{18_000 + 200 * k}", r"open (known )?gaps?", r"acquisition cost"]
    elif fault == "outruns_evidence":
        lines.append(f"PROPOSAL #{k + 1} BUY {t['sym']} [open, review pending, v1, snapshot 5d1e{k}a77_2026-11-02]: high conviction, add 40% to the position because the "
                     f"{t['sector']} sell-off is an overreaction | size 600 shares | tax n/a | missing: none")
        anchors = [rf"proposal\s*#?\s*{k + 1}\b", r"(one|single|1|only one) (independent )?source", r"only one (piece|item) of evidence"]
    else:
        lines.append("LEDGER: complete (no open known gaps; the broker reconciles)")
        extra = ""
        if fault == "untraced_number":
            fig = round(20 + t["fall"] + k + 6.2, 1)                           # a figure in no evidence line and in no calculation
            extra = f"; the {t['sector']} index is down {fig}% since August"
            anchors = [re.escape(str(fig))]
        lines.append(f"PROPOSAL #{k + 1} WAIT {t['sym']} [open, review pending, v1, snapshot 5d1e{k}a77_2026-11-02]: the stated shocks (CALC #{21 + k}) would cost the portfolio between "
                     f"{hits[str(shocks[0])]}% and {hits[str(shocks[2])]}%, hypothetical and not forecasts; the 9.1% vs 9.4% test (EXPERIMENT #{2 + k}) gives no reason to buy the dip{extra} "
                     f"| size none | tax n/a | missing: nothing | reopen when: the company files again, or the {t['sector']} index closes a further 10% below its 2026-10-30 level")
    return "\n".join(lines), anchors


def reviewer_set(n_fault: int = 24, n_clean: int = 4) -> List[Item]:
    """Faulty dossiers in an order where every prefix is balanced across the six faults and the four themes, then the clean controls."""
    out: List[Item] = []
    for i in range(24):
        fault, theme = FAULTS[i % 6], THEMES[(i // 6 + i) % 4]
        text, anchors = _dossier(theme, i // 6, fault)
        out.append(Item(f"r{i + 1:02d}-{fault}", fault, text, anchors))
    out = out[:n_fault]
    for j in range(n_clean):
        text, _ = _dossier(THEMES[j % 4], j, "clean")
        out.append(Item(f"r{25 + j:02d}-clean", "clean", text))
    return out


REVIEW_TASK = ("TASK #1 (review): Independently review this mission's work. YOU MUST PRODUCE: {\"review\": 1}\n"
               "You have the dossier below and your `submit_review` tool; the calculations were reproduced by the system (see REPRODUCTION). "
               "Call submit_review once, with your verdict.\n\n")


def graded(item: Item, verdict: Optional[str], words: str) -> Dict[str, object]:
    """One review against its item. A fault is CAUGHT when the verdict is revise or reject and the words name the planted thing; a clean item is a FALSE ALARM
    when the verdict is not approve; no verdict is a miss either way."""
    if item.fault == "clean":
        return {"id": item.id, "fault": "clean", "verdict": verdict, "false_alarm": verdict in ("revise", "reject")}
    named = any(re.search(a, words, re.I) for a in item.anchors)
    return {"id": item.id, "fault": item.fault, "verdict": verdict, "caught": verdict in ("revise", "reject") and named,
            "flagged_but_not_named": verdict in ("revise", "reject") and not named}


def summarize(graded_rows: List[dict]) -> dict:
    faulty = [g for g in graded_rows if g["fault"] != "clean"]
    clean = [g for g in graded_rows if g["fault"] == "clean"]
    by = {f: [sum(1 for g in faulty if g["fault"] == f and g["caught"]), sum(1 for g in faulty if g["fault"] == f)] for f in FAULTS}
    return {"faulty": len(faulty), "caught": sum(1 for g in faulty if g["caught"]), "clean": len(clean), "false_alarms": sum(1 for g in clean if g["false_alarm"]),
            "no_verdict": sum(1 for g in graded_rows if g["verdict"] is None), "by_fault": by}


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    """The 95% Wilson interval for k of n (small-numbers rule: counts are shown with their interval)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (round(max(0.0, c - h), 3), round(min(1.0, c + h), 3))


def decide(opus: dict, sonnet: dict) -> dict:
    """The pre-registered rule for the reviewer's seat: Sonnet takes it only if it catches at least 90% of what Opus catches AND at least 70% of the planted
    faults in all, AND has no more than one more false alarm than Opus on the clean controls. Otherwise the seat stays with Opus."""
    co, cs = opus["caught"], sonnet["caught"]
    n = sonnet["faulty"]
    ok_rel = cs >= 0.9 * co
    ok_abs = n > 0 and cs / n >= 0.70
    ok_fa = sonnet["false_alarms"] <= opus["false_alarms"] + 1
    return {"seat": "sonnet" if (ok_rel and ok_abs and ok_fa) else "opus", "relative_ok": ok_rel, "absolute_ok": ok_abs, "false_alarms_ok": ok_fa,
            "opus_interval": wilson(co, opus["faulty"]), "sonnet_interval": wilson(cs, n)}


# --- the planner ---------------------------------------------------------------------------------------------------------------

PLANNER_TASKS = [
    ("strategy", "Investigate whether the fall in cloud-software stocks after a rival's cheaper AI model should change how I put my monthly Rs 50,000 to work"),
    ("explain", "Is the regulator's draft fee cap a real risk to my payments holding, or is the sell-off an overreaction?"),
    ("strategy", "Compare holding with trimming my metals holding after the metal price fell 8% this month"),
    ("explain", "Should I add to my private-bank holding after it missed its quarter, or is something worse behind the miss?"),
    ("strategy", "My IPO allotment lists next week: should I sell on listing day or hold, given what similar listings did?"),
    ("strategy", "Test whether buying only after a 7% fall beats buying every month for the money I keep in an index fund"),
]
PLAN_CHECKS = ("steps_2_to_6", "premise_first", "has_quant", "valid_structure", "baseline_or_competing", "what_would_invalidate")


def plan_task_text(i: int) -> str:
    kind, goal = PLANNER_TASKS[i]
    return (f"TASK #1 (coordinator): Plan the mission: {goal}\nYOU MUST PRODUCE: {{\"plan\": 1}}\nCASE #1 (running, opened 2026-11-01 by investor): {goal}\n"
            "PORTFOLIO (summary, invented): 14 direct stocks (largest 7.5%), 3 index funds, gold 12%, debt 25%; no open investigations.\n"
            "Call plan_mission once with 2 to 6 steps for the research and quant workers.")


def plan_scores(kind: str, steps: Optional[list], approach: str = "") -> Dict[str, bool]:
    """The six structural checks on a plan, by code."""
    s = steps if isinstance(steps, list) and all(isinstance(x, dict) for x in steps) else []
    keys = [str(x.get("key", "")) for x in s]
    goals = " ".join(str(x.get("goal", "")) for x in s) + " " + (approach or "")
    deps_ok = all(isinstance(x.get("depends_on", []), list) and all(d in keys for d in x.get("depends_on", [])) for x in s) and len(set(keys)) == len(keys) and all(keys)
    order = {k: i for i, k in enumerate(keys)}
    acyclic = deps_ok and all(order.get(d, 99) < order.get(str(x.get("key")), -1) for x in s for d in x.get("depends_on", []))
    promise_ok = all(isinstance(x.get("promise", {}), dict) and all(p in ("evidence", "calc", "scenario", "experiment") for p in x.get("promise", {})) for x in s)
    return {"steps_2_to_6": 2 <= len(s) <= 6,
            "premise_first": bool(s) and s[0].get("role") == "research" and not s[0].get("depends_on") and bool(re.search(r"verif|confirm|establish|check", str(s[0].get("goal", "")), re.I)),
            "has_quant": any(x.get("role") == "quant" for x in s),
            "valid_structure": bool(s) and acyclic and promise_ok and all(x.get("role") in ("research", "quant") for x in s),
            "baseline_or_competing": bool(re.search(r"baseline|benchmark|buy-and-hold|versus|compar|alternative", goals, re.I)) if kind == "strategy"
            else bool(re.search(r"competing|alternative explanation|other explanation|rival explanation|disconfirm|evidence against|against the idea", goals, re.I)),
            "what_would_invalidate": bool(re.search(r"invalidat|would change|change (my|the|our) view|refute|falsif|disprove|wrong if|overturn", goals, re.I))}


def plan_summary(rows: List[Dict[str, bool]]) -> dict:
    n = len(rows)
    per = {c: sum(1 for r in rows if r[c]) for c in PLAN_CHECKS}
    return {"tasks": n, "per_check": per, "mean": round(sum(per.values()) / (n * len(PLAN_CHECKS)), 3) if n else 0.0}


def decide_planner(opus: dict, sonnet: dict) -> dict:
    """Sonnet plans only if its mean score is at least 90% of Opus's and it passes every check on at least 75% of the tasks."""
    n = sonnet["tasks"]
    floor_ok = n > 0 and all(v / n >= 0.75 for v in sonnet["per_check"].values())
    rel_ok = sonnet["mean"] >= 0.9 * opus["mean"]
    return {"planner": "sonnet" if (floor_ok and rel_ok) else "opus", "relative_ok": rel_ok, "floor_ok": floor_ok}
