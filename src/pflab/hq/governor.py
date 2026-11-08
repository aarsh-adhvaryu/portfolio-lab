"""The spend governor (S59, docs/BUILT.md "cost control comes first"; PLAN A16).

Every paid HQ call is priced before it is made (count_tokens for the input, the worst case for the output) and checked
against, in order:
    tokens     the agent's input and output limits for one pass
    passes     the agent's calls today under the brain setting (off / economy / normal)
    day        the layer's rupees today (a noisy day never spends the month)
    month      the layer's share of the monthly cap
    cap        the system's monthly cap and the investor's per-job limit (`analyst.check_budget`, api_budget.toml)
A call over any limit is not made; it is logged as `over_limit` with the reason (no cost), so the dashboard shows it.

Prices are Anthropic's list prices (claude-api skill, cached 2026-10-06), dollars per million tokens; cached input is
read at a tenth of the input price and written at 1.25 times it (five-minute cache); the batch API halves everything.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from pflab.agents import analyst as an

OPUS, SONNET, HAIKU = "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"
PRICES = {OPUS: (4.0, 20.0), SONNET: (2.0, 10.0), HAIKU: (0.10, 0.50)}
CACHE_READ, CACHE_WRITE, BATCH = 0.10, 1.25, 0.5
# S70: what a cache read costs as a share of the model's input price (Opus 5.5: $0.20 of $4.00; Sonnet 5.5: $0.20 of $2.00); any other model the old tenth
CACHE_READ_OF = {OPUS: 0.05, SONNET: 0.10, HAIKU: 0.10}
MODES = ("off", "economy", "normal")

BudgetRefused = an.BudgetRefused

# layer -> (share of the monthly cap, rupees a day). What is left of the cap (about a quarter) stays for the analyst's
# own paths (deep research, web search, the workshop), which only the cap limits, as before.
# S70: with the monthly cap at Rs 1,000 and the brain down to a pass a day, the workers (his investigations and the system's) get most of it
LAYERS: Dict[str, tuple] = {"readers": (0.06, 15.0), "workers": (0.55, 80.0), "brain": (0.15, 40.0)}


@dataclass(frozen=True)
class Limits:
    layer: str
    max_in: int                    # input tokens in one call
    max_out: int                   # max_tokens of one call (thinking counts as output)
    per_day: Dict[str, int]        # brain setting -> calls a day


LIMITS: Dict[str, Limits] = {
    "reader": Limits("readers", 24_000, 2_500, {"off": 150, "economy": 150, "normal": 400}),
    "gatekeeper": Limits("readers", 8_000, 600, {"off": 0, "economy": 30, "normal": 60}),
    "wording": Limits("readers", 12_000, 2_000, {"off": 200, "economy": 200, "normal": 400}),   # S61: live answers' drafts
    "router": Limits("readers", 6_000, 1_600, {"off": 300, "economy": 300, "normal": 600}),    # S61: the ask centre's routing
    "worker": Limits("workers", 60_000, 16_000, {"off": 20, "economy": 20, "normal": 40}),
    "brain": Limits("brain", 40_000, 6_000, {"off": 0, "economy": 2, "normal": 3}),   # S70: two passes a day (it was 4 and 8): the morning one and one for a case; its 15% of the month is the real guard
    "brain_rival": Limits("brain", 40_000, 6_000, {"off": 0, "economy": 4, "normal": 8}),
    "reflection": Limits("brain", 60_000, 12_000, {"off": 0, "economy": 1, "normal": 1}),
    "fetch": Limits("workers", 60_000, 4_000, {"off": 0, "economy": 10, "normal": 20}),
    # S68: the mission workers (hq/workers.py), each its own agent in the governor's table
    "w_coord": Limits("workers", 60_000, 8_000, {"off": 0, "economy": 24, "normal": 48}),
    "w_research": Limits("workers", 80_000, 8_000, {"off": 0, "economy": 60, "normal": 120}),
    "w_quant": Limits("workers", 80_000, 10_000, {"off": 0, "economy": 60, "normal": 120}),
    "w_review": Limits("workers", 80_000, 8_000, {"off": 0, "economy": 24, "normal": 48}),
    "w_assistant": Limits("workers", 80_000, 6_000, {"off": 0, "economy": 80, "normal": 200}),     # the conversation: his messages, never held by day limits
}
COUNTED = ("done", "sending", "queued", "submitted", "refused")


def layer_limits(cfg: dict, layer: str) -> tuple:
    """(share of the monthly cap, rupees a day) of a layer: the code's defaults, or api_budget.toml [policy.day_rupees] / [policy.share] (S68;
    read on every call, so an edit holds at once). Defaults equal the constants of S59-S67."""
    share, day = LAYERS[layer]
    p = (cfg or {}).get("policy") or {}
    return float((p.get("share") or {}).get(layer, share)), float((p.get("day_rupees") or {}).get(layer, day))


def passes_per_day(cfg: dict, agent: str, mode: str) -> int:
    """Calls (for the brain: passes) a day under the brain setting: the code's table, or [policy.passes.<agent>] in api_budget.toml (S68)."""
    m = mode if mode in MODES else "economy"
    over = (((cfg or {}).get("policy") or {}).get("passes") or {}).get(agent) or {}
    return int(over.get(m, LIMITS[agent].per_day.get(m, 0)))


def cost_inr(model: str, input_tokens: int, output_tokens: int, usd_inr: float, cache_read: int = 0,
             cache_write: int = 0, batch: bool = False) -> float:
    pin, pout = PRICES.get(model, PRICES[OPUS])
    usd = (input_tokens * pin + cache_read * pin * CACHE_READ_OF.get(model, CACHE_READ) + cache_write * pin * CACHE_WRITE
           + output_tokens * pout) / 1e6
    return usd * (BATCH if batch else 1.0) * usd_inr


def agents_in(layer: str) -> List[str]:
    return [a for a, lim in LIMITS.items() if lim.layer == layer]


def _spent(con, agents: List[str], since: datetime) -> float:
    q = ",".join("?" * len(agents))
    return float(con.execute(f"SELECT coalesce(sum(cost_inr), 0) FROM api_calls WHERE agent IN ({q}) AND created_at >= ? "
                             f"AND status IN ({','.join('?' * len(COUNTED))})", [*agents, since, *COUNTED]).fetchone()[0])


def _spent_system(con, agents: List[str], since: datetime) -> float:
    """The system's own spend since `since` (not his questions): what the DAY limit is measured against."""
    q = ",".join("?" * len(agents))
    return float(con.execute(f"SELECT coalesce(sum(cost_inr), 0) FROM api_calls WHERE agent IN ({q}) AND created_at >= ? "
                             f"AND coalesce(his_order, FALSE) = FALSE AND status IN ({','.join('?' * len(COUNTED))})",
                             [*agents, since, *COUNTED]).fetchone()[0])


def calls_today(con, agent: str, now: datetime, since: Optional[datetime] = None) -> int:
    """Calls (for the brain: passes) today: the later turns of a tool loop belong to the pass its first turn opened. His questions are not
    counted (S68): the system's own passes a day are measured without them."""
    day = since or datetime(now.year, now.month, now.day)
    return int(con.execute(f"SELECT count(*) FROM api_calls WHERE agent = ? AND created_at >= ? AND coalesce(turn, 1) = 1 "
                           f"AND coalesce(his_order, FALSE) = FALSE AND status IN ({','.join('?' * len(COUNTED))})",
                           [agent, day, *COUNTED]).fetchone()[0])


def check(con, agent: str, est_inr: float, n_in: int, n_out: int, now: datetime, mode: str, cfg: dict,
          approved: bool = False, turn: int = 1, his_order: bool = False) -> List[str]:
    """Raise BudgetRefused (or analyst.NeedsApproval) when the call may not be made; else the cap's warnings. A later
    turn of a pass (S60 tool loop) is not counted against passes a day again; every other limit holds per turn.
    `his_order` (2026-10-31: on the first night every question he asked after 23:15 was refused because the brain's own passes had used
    its day): his question is not held by the passes-a-day or rupees-a-day limits meant for the system's own work; the layer's monthly
    share and his cap still hold. Fallback: his_order=False everywhere restores the old rule."""
    lim = LIMITS[agent]
    if n_in > lim.max_in:
        raise BudgetRefused(f"{agent}: {n_in:,} input tokens, over its {lim.max_in:,} a call")
    if n_out > lim.max_out:
        raise BudgetRefused(f"{agent}: up to {n_out:,} output tokens, over its {lim.max_out:,} a call")
    window = an.acceptance(cfg, now)                         # S68: in the bounded acceptance window only the window's own cap holds
    n = passes_per_day(cfg, agent, mode)
    if n <= 0:
        raise BudgetRefused(f"{agent} does not run with the brain set to '{mode}'")
    tomorrow = datetime(now.year, now.month, now.day) + timedelta(days=1, minutes=5)
    next_month = (datetime(now.year, now.month, 1) + timedelta(days=32)).replace(day=1, minute=5)
    # S78 (2026-11-02: he reset the budget and the team's day limit still counted the morning's Rs 197): the day is counted from midnight or from his reset, whichever is later
    day_start = max(datetime(now.year, now.month, now.day), an.month_start(now, cfg))
    if not (his_order or window) and turn <= 1 and calls_today(con, agent, now, day_start) >= n:
        raise _refuse(f"{agent}: {n} calls today already (its limit under '{mode}')", tomorrow)
    share, day_cap = layer_limits(cfg, lim.layer)
    peers = agents_in(lim.layer)
    day = _spent_system(con, peers, day_start)                                   # his questions are not counted against the system's day
    # the day's rupees stop a pass from BEGINNING; a pass already begun (turn 2 on) is stopped only by the cap, never half-way by a day limit
    if not (his_order or window) and turn <= 1 and day + est_inr > day_cap:
        raise _refuse(f"the {lim.layer} have spent ~Rs {day:,.1f} today; this call up to ~Rs {est_inr:,.1f} "
                      f"would pass their Rs {day_cap:,.0f} a day", tomorrow)
    month = _spent(con, peers, an.month_start(now, cfg))
    if not window and month + est_inr > share * cfg["cap"]:
        raise _refuse(f"the {lim.layer} have spent ~Rs {month:,.0f} this month; their share is "
                      f"Rs {share * cfg['cap']:,.0f} of the Rs {cfg['cap']:,.0f} cap", next_month)
    try:
        return an.check_budget(con, est_inr, cfg, now, approved)
    except BudgetRefused as e:
        if getattr(e, "resume_at", None) is None:
            e.resume_at = acc_end(cfg, now) or next_month           # the cap resets with the month; a window's cap does not reset
        raise


def mode_pace(con, now: datetime, layer: str = "workers") -> Optional[str]:
    """S79 (A42): the clock's MODE sets a rupee pace per hour for the system's OWN optional work (the agenda). Returns why a paid item should wait, or None.
    It is not applied to his orders or to a mission already under way: they are held by the day and month limits only."""
    from pflab import markets
    if not markets.pace_spend():
        return None
    _m, md = markets.primary(now)
    hour = _spent_system(con, agents_in(layer), now - timedelta(hours=1))
    budget = markets.rupee_per_hour(md)
    return f"the {layer} have spent ~Rs {hour:,.1f} in the last hour; the {md} mode paces ~Rs {budget:,.0f} an hour" if hour >= budget else None


def acc_end(cfg: dict, now: datetime) -> Optional[datetime]:
    """When a refusal by the acceptance window's own cap can next change: never inside the window (a cap spent stays spent)."""
    w = an.acceptance(cfg, now)
    return (w["until"] + timedelta(minutes=1)) if w else None


def _refuse(why: str, resume_at: datetime) -> BudgetRefused:
    e = BudgetRefused(why)
    e.resume_at = resume_at                                  # S68: when this refusal can next be different; a waiting case looks again then
    return e


def log_refusal(con, agent: str, model: str, topic: str, question: str, why: str, now: datetime) -> int:
    from pflab.pm.store import next_id
    cid = next_id(con, "api_calls", "call_id")
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, "
                "status, cost_inr, finished_at, error, agent) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [cid, now, "live", model, topic, question[:500], "", "{}", "over_limit", 0.0, now, why[:500], agent])
    return cid


# --- every limit in force, in one view (S68) ---------------------------------------------------------------------------

def policy_view(con, now: datetime, mode: str = "economy") -> dict:
    """The one view of what may refuse a paid call right now: each limit, its value, where it is set, why it exists and whether an edit
    holds at once. `policy` is 'acceptance' while the bounded window is open, else 'normal'; `window` carries its spend against its cap."""
    from pflab import release
    from pflab.hq import tools as tl
    cfg = an.config()
    win = an.acceptance(cfg, now)
    rows = []

    def add(name, value, where, why, live=True, applies="system work", lifted=False):
        rows.append({"limit": name, "value": value, "set_in": where, "why": why, "live": live, "applies_to": applies,
                     "state": "lifted by the acceptance window" if lifted else "in force"})
    cap_key = "dev_monthly_cap_rupees" if release.channel() == "beta" else "monthly_cap_rupees"
    add("monthly cap", f"Rs {cfg['cap']:,.0f}", f"api_budget.toml [api] {cap_key}", "his money; the whole system's month", applies="everything",
        lifted=bool(win))
    for lay in LAYERS:
        share, day = layer_limits(cfg, lay)
        add(f"{lay} layer, rupees a day", f"Rs {day:,.0f}", "api_budget.toml [policy.day_rupees] (default in hq/governor.py)",
            "a noisy day never spends the month; it stops a pass from beginning, never half-way", lifted=bool(win))
        add(f"{lay} layer, share of the month", f"{share:.0%} = Rs {share * cfg['cap']:,.0f}", "api_budget.toml [policy.share]",
            "keeps a quarter of the cap for the analyst's own paths", lifted=bool(win))
    for agent in LIMITS:
        add(f"{agent}, calls a day ({mode})", passes_per_day(cfg, agent, mode), "api_budget.toml [policy.passes.<agent>] / Settings brain setting",
            "calls (for the brain: passes) the system starts by itself; his questions are not counted", lifted=bool(win))
    for t in sorted(tl.DAILY):
        n = tl.daily_cap(con, t, now)
        add(f"tool {t}, a day", n, "api_budget.toml [policy.tool_caps] / learner proposals", "a noisy day never floods him or the cap",
            lifted=bool(win) and t in tl.WORK_TOOLS)
    add("one job asks first above", f"Rs {cfg['ask_above']:,.0f}", "api_budget.toml [api] ask_above_rupees", "a single job over this needs his yes",
        applies="everything")
    add("paid calls from the workshop", "off unless --paid", "src/pflab/guard.py", "the workshop sends nothing outward unless told",
        live=False, applies="the workshop only")
    out = {"policy": "acceptance" if win else "normal", "channel": release.channel(), "mode": mode, "limits": rows,
           "month_spent": round(an.month_spend_inr(con, now), 2), "cap": cfg["cap"], "window": None}
    if win:
        spent = an.window_spend(con, win["since"])
        out["window"] = {"since": str(win["since"])[:16], "until": str(win["until"])[:16], "cap": win["cap"], "spent": round(spent, 2),
                         "left": round(max(0.0, win["cap"] - spent), 2),
                         "note": "inside the window only its own cap holds; every call is tagged policy='acceptance'; it ends by itself"}
    return out


# --- spend per agent (the dashboard) ---------------------------------------------------------------------------------

def agent_of(agent: Optional[str], mode: str, model: str, topic: Optional[str]) -> str:
    """Calls made before S59 carry no agent: named from how they were made."""
    if agent:
        return agent
    if mode == "web":
        return "web search"
    if mode == "trial":
        return "comparison"
    if (topic or "").startswith("harness"):
        return "harness editor"
    if topic == "workshop":
        return "workshop (second writing)" if model == SONNET else "workshop"
    return "analyst (notes)" if model == SONNET else "analyst (research)"


def spend(con, now: datetime) -> dict:
    """This month's and today's spend per agent and per layer, with the limits, for the dashboard."""
    cfg = an.config()
    month0, day0 = an.month_start(now, cfg), datetime(now.year, now.month, now.day)
    rows = con.execute("SELECT agent, mode, model, topic, status, cost_inr, created_at FROM api_calls WHERE created_at >= ?",
                       [month0]).fetchall()
    per: Dict[str, dict] = {}
    for agent, mode, model, topic, status, inr, at in rows:
        a = agent_of(agent, mode, model, topic)
        d = per.setdefault(a, {"agent": a, "month": 0.0, "today": 0.0, "calls": 0, "over_limit": 0})
        if status == "over_limit":
            d["over_limit"] += 1
            continue
        if status in COUNTED:
            d["month"] += float(inr or 0)
            d["today"] += float(inr or 0) if at >= day0 else 0.0
            d["calls"] += 1
    layers = []
    for name in LAYERS:
        share, day_cap = layer_limits(cfg, name)
        peers = agents_in(name)
        layers.append({"layer": name, "month": _spent(con, peers, month0), "share": share * cfg["cap"],
                       "today": _spent(con, peers, day0), "day_cap": day_cap})
    total = an.month_spend_inr(con, now)
    return {"cap": cfg["cap"], "month": total, "left": max(0.0, cfg["cap"] - total),
            "agents": sorted(per.values(), key=lambda d: -d["month"]), "layers": layers, "since": f"{now:%Y-%m}-01"}
