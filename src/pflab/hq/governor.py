"""The spend governor (S59, docs/BRAIN.md "cost control comes first"; PLAN A16).

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
MODES = ("off", "economy", "normal")

BudgetRefused = an.BudgetRefused

# layer -> (share of the monthly cap, rupees a day). What is left of the cap (about a quarter) stays for the analyst's
# own paths (deep research, web search, the workshop), which only the cap limits, as before.
LAYERS: Dict[str, tuple] = {"readers": (0.06, 15.0), "workers": (0.30, 80.0), "brain": (0.40, 120.0)}


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
    "brain": Limits("brain", 40_000, 6_000, {"off": 0, "economy": 4, "normal": 8}),
    "brain_rival": Limits("brain", 40_000, 6_000, {"off": 0, "economy": 4, "normal": 8}),
    "reflection": Limits("brain", 60_000, 12_000, {"off": 0, "economy": 1, "normal": 1}),
    "fetch": Limits("workers", 60_000, 4_000, {"off": 0, "economy": 10, "normal": 20}),
}
COUNTED = ("done", "sending", "queued", "submitted", "refused")


def cost_inr(model: str, input_tokens: int, output_tokens: int, usd_inr: float, cache_read: int = 0,
             cache_write: int = 0, batch: bool = False) -> float:
    pin, pout = PRICES.get(model, PRICES[OPUS])
    usd = (input_tokens * pin + cache_read * pin * CACHE_READ + cache_write * pin * CACHE_WRITE + output_tokens * pout) / 1e6
    return usd * (BATCH if batch else 1.0) * usd_inr


def agents_in(layer: str) -> List[str]:
    return [a for a, lim in LIMITS.items() if lim.layer == layer]


def _spent(con, agents: List[str], since: datetime) -> float:
    q = ",".join("?" * len(agents))
    return float(con.execute(f"SELECT coalesce(sum(cost_inr), 0) FROM api_calls WHERE agent IN ({q}) AND created_at >= ? "
                             f"AND status IN ({','.join('?' * len(COUNTED))})", [*agents, since, *COUNTED]).fetchone()[0])


def calls_today(con, agent: str, now: datetime) -> int:
    """Calls (for the brain: passes) today: the later turns of a tool loop belong to the pass its first turn opened."""
    day = datetime(now.year, now.month, now.day)
    return int(con.execute(f"SELECT count(*) FROM api_calls WHERE agent = ? AND created_at >= ? AND coalesce(turn, 1) = 1 "
                           f"AND status IN ({','.join('?' * len(COUNTED))})", [agent, day, *COUNTED]).fetchone()[0])


def check(con, agent: str, est_inr: float, n_in: int, n_out: int, now: datetime, mode: str, cfg: dict,
          approved: bool = False, turn: int = 1) -> List[str]:
    """Raise BudgetRefused (or analyst.NeedsApproval) when the call may not be made; else the cap's warnings. A later
    turn of a pass (S60 tool loop) is not counted against passes a day again; every other limit holds per turn."""
    lim = LIMITS[agent]
    if n_in > lim.max_in:
        raise BudgetRefused(f"{agent}: {n_in:,} input tokens, over its {lim.max_in:,} a call")
    if n_out > lim.max_out:
        raise BudgetRefused(f"{agent}: up to {n_out:,} output tokens, over its {lim.max_out:,} a call")
    n = lim.per_day.get(mode if mode in MODES else "economy", 0)
    if n <= 0:
        raise BudgetRefused(f"{agent} does not run with the brain set to '{mode}'")
    if turn <= 1 and calls_today(con, agent, now) >= n:
        raise BudgetRefused(f"{agent}: {n} calls today already (its limit under '{mode}')")
    share, day_cap = LAYERS[lim.layer]
    peers = agents_in(lim.layer)
    day = _spent(con, peers, datetime(now.year, now.month, now.day))
    if day + est_inr > day_cap:
        raise BudgetRefused(f"the {lim.layer} have spent ~Rs {day:,.1f} today; this call up to ~Rs {est_inr:,.1f} "
                            f"would pass their Rs {day_cap:,.0f} a day")
    month = _spent(con, peers, datetime(now.year, now.month, 1))
    if month + est_inr > share * cfg["cap"]:
        raise BudgetRefused(f"the {lim.layer} have spent ~Rs {month:,.0f} this month; their share is "
                            f"Rs {share * cfg['cap']:,.0f} of the Rs {cfg['cap']:,.0f} cap")
    return an.check_budget(con, est_inr, cfg, now, approved)


def log_refusal(con, agent: str, model: str, topic: str, question: str, why: str, now: datetime) -> int:
    from pflab.pm.store import next_id
    cid = next_id(con, "api_calls", "call_id")
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, "
                "status, cost_inr, finished_at, error, agent) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [cid, now, "live", model, topic, question[:500], "", "{}", "over_limit", 0.0, now, why[:500], agent])
    return cid


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
    month0, day0 = datetime(now.year, now.month, 1), datetime(now.year, now.month, now.day)
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
    for name, (share, day_cap) in LAYERS.items():
        peers = agents_in(name)
        layers.append({"layer": name, "month": _spent(con, peers, month0), "share": share * cfg["cap"],
                       "today": _spent(con, peers, day0), "day_cap": day_cap})
    total = an.month_spend_inr(con, now)
    return {"cap": cfg["cap"], "month": total, "left": max(0.0, cfg["cap"] - total),
            "agents": sorted(per.values(), key=lambda d: -d["month"]), "layers": layers, "since": f"{now:%Y-%m}-01"}
