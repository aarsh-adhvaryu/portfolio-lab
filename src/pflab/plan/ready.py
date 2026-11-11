"""S55 ready plans (PLAN A8): a plan kept current for each next sum of money, ready before the investor asks.

    the next money   the next FD tranche however far off, and any other due within TRIGGER_DAYS (his rule: a batch of
                     FDs goes in over `deploy_months` monthly tranches, targets.toml [meta]), and his next monthly amount
                     when he has given one (asked once)
    the plan         the tested S45 advisor for that amount: the bucket split, each fund or ETF to buy, each stock with
                     its quantity, the price range to buy it in (its buy zone, "around x to y": a description, not a
                     rule; CLAUDE.md 12), why it is chosen, and the trader's tickets. Priced at today's prices.
    kept current     rebuilt nightly and whenever the dashboard refreshes; a new version is stored only when the plan
                     changed, with what changed; a held message and a notification when the money is NOTIFY_DAYS away
    the outer ring   an idea beside the plan, not a rule (The investor 2026-10-20: "lets not cut the stocks, add another circle
                     outside ... as it grows in trees"): the plan's stock money into list names not held yet instead of
                     topping up held ones, with the numbers for both (names, the largest name's share of the stock
                     sleeve, sectors, the sleeve's chance of a fall beyond 35% within a year)

It proposes; the investor places every order himself. Nothing here changes targets, limits or the stock list.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

TRIGGER_DAYS = 60
NOTIFY_DAYS = 7
DEFAULT_DEPLOY_MONTHS = 10
RING_PATHS = 10_000
MONTHLY_KEY = "ready:monthly-amount"


@dataclass(frozen=True)
class Trigger:
    key: str
    kind: str              # fd_tranche | monthly | custom
    due: date
    amount: float
    source: str
    estimate: bool


def _meta() -> dict:
    from pflab import _toml
    from pflab.plan import targets as tg
    try:
        return _toml.load(tg.default_path()).get("meta", {}) or {}
    except Exception:
        return {}


MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
                                     start=1)}


def latest_monthly_answer(con) -> Optional[str]:
    """His newest answer to the monthly question or to its asking-again (S58b)."""
    row = con.execute("SELECT answer FROM questions WHERE (subject_key=? OR subject_key LIKE ?) AND status='answered' "
                      "AND answer IS NOT NULL AND answer <> '' ORDER BY answered_at DESC LIMIT 1",
                      [MONTHLY_KEY, MONTHLY_KEY + ":again:%"]).fetchone()
    return str(row[0]) if row else None


def monthly(con, asof: date, meta: Optional[dict] = None) -> tuple:
    """His monthly amount and the month it starts: targets.toml [meta] monthly_amount / monthly_from, else his answer
    to the question ("25,000 from January"; 0 = none). (None, None) until he has said."""
    import re

    from pflab.app.research import parse_amount
    meta = _meta() if meta is None else meta
    if meta.get("monthly_amount") is not None:
        start = date.fromisoformat(str(meta["monthly_from"])) if meta.get("monthly_from") else None
        return float(meta["monthly_amount"]), start
    a = latest_monthly_answer(con)
    if a is None:
        return None, None
    a = a.strip().lower()
    if a in ("0", "none", "no", "nothing", "not yet"):
        return 0.0, None
    amt = parse_amount(a)
    if amt is None:
        n = re.search(r"\d[\d,]*(?:\.\d+)?", a)
        amt = float(n.group(0).replace(",", "")) if n else None
    start = None
    mo = re.search(r"\b(" + "|".join(MONTHS) + r")[a-z]*\b", a)
    if mo:
        m = MONTHS[mo.group(1)]
        start = date(asof.year + (m <= asof.month), m, 1)                # the next such month
    return amt, start


def triggers(con, asof: date, meta: Optional[dict] = None, now: Optional[datetime] = None) -> List[Trigger]:
    from pflab.ledger import system as _sys
    if _sys.active():                                                      # S78: the system's own account has no FDs and no monthly amount of his to plan around
        return []
    from pflab.agents import questions as qs
    from pflab.pm import fd as fdm
    from pflab.plan import deploy
    meta = _meta() if meta is None else meta
    months = int(meta.get("deploy_months", DEFAULT_DEPLOY_MONTHS))
    out: List[Trigger] = []
    seen = set()
    for t in deploy.schedule(fdm.load(con), months, asof):              # the next tranche always, others in reach
        if (seen and t.month > asof + timedelta(days=TRIGGER_DAYS)) or t.month in seen:
            continue
        seen.add(t.month)
        out.append(Trigger(f"fd:{t.batch}:{t.n}", "fd_tranche", t.month, round(t.amount, 2),
                           f"tranche {t.n} of {months} from the FDs maturing {t.batch:%d %b %Y}", True))
    m, start = monthly(con, asof, meta)
    said = latest_monthly_answer(con) if m is None else None
    if m is None and said:                               # S58b: an answer with no amount in it is asked again, never lost
        qs.ask(con, "planner", f"{MONTHLY_KEY}:again:{len(said)}:{said[:20]}",
               f"I could not read an amount in your answer \"{said[:80]}\". How much will you add each month, and from "
               "which month? Write it like \"25000 from January\" (or 0 for nothing for now).", now)
    elif m is None:
        qs.ask(con, "planner", MONTHLY_KEY, "How much will you add each month, and from which month? (Answer 0 if "
               "nothing for now.) Ready plans for it are then kept current like the FD tranches.", now)
    elif m > 0:
        due = (asof.replace(day=1) + timedelta(days=32)).replace(day=1)
        due = max(due, start) if start else due
        out.append(Trigger(f"monthly:{due:%Y-%m}", "monthly", due, m, f"your monthly amount for {due:%b %Y}", False))
    return sorted(out, key=lambda t: t.due)


# --- the plan ----------------------------------------------------------------------------------------------------------

def _names(con, isins) -> Dict[str, str]:
    isins = list(isins)
    if not isins:
        return {}
    return {i: (s or n or i) for i, s, n in con.execute(
        f"SELECT isin, symbol, name FROM instruments WHERE isin IN ({','.join('?' * len(isins))})", isins).fetchall()}


def _sector_of(con, isins) -> Dict[str, str]:
    isins = list(isins)
    if not isins:
        return {}
    rows = con.execute("SELECT split_part(src, ':', 2), coalesce(n.name, dst) FROM kg_edges e LEFT JOIN kg_nodes n "
                       "ON n.node_id = e.dst WHERE e.rel='in_sector' AND e.valid_to IS NULL").fetchall()
    return {i: s for i, s in rows if i in set(isins)}


def build(con, asof: date, trig: Trigger, zones: Dict[str, dict], root: Path,
          fall_fn: Optional[Callable[[Dict[str, float]], dict]] = None, run=None) -> dict:
    """One ready plan. `zones`: isin -> buy zone (the watch list's); `run`: the advisor (tests pass a fake)."""
    from pflab.plan import advisor
    run = run or advisor.run
    text, adv, tk, plan, alloc = run(con, asof, trig.amount, with_plan=True)
    names = _names(con, {b.isin for b in plan.buys})
    buckets = [{"bucket": b, "rupees": round(float(r), 2)} for b, r in sorted(alloc.items(), key=lambda x: -x[1]) if r > 0.5]
    how = []
    for b in plan.buys:
        z = zones.get(b.isin) or _zone(con, root, b.isin, asof)
        how.append({"bucket": b.bucket, "isin": b.isin, "name": names.get(b.isin, b.isin), "units": b.units,
                    "cost": round(b.cost, 2), "range": _range(z), "verdict": z.get("verdict")})
    stocks = []
    for s in adv.buys:
        z = zones.get(s.isin) or {}
        stocks.append({"symbol": s.symbol, "isin": s.isin, "qty": s.qty, "price": s.price, "cost": round(s.cost, 2),
                       "range": _range(z), "verdict": z.get("verdict"), "tickets": tk.get(s.symbol, []),
                       "why": (f"holds {s.held_value / s.target_value:.0%} of its share of the stock bucket; passes the "
                               "guards today" if s.target_value > 0 else "passes the guards today")})
    out = {"key": trig.key, "kind": trig.kind, "due": str(trig.due), "amount": trig.amount, "source": trig.source,
           "estimate": trig.estimate, "buckets": buckets, "how": how, "stocks": stocks, "unspent": adv.unspent,
           "skipped": adv.skipped, "notes": adv.notes + list(plan.notes), "bucket_text": text}
    out["ring"] = ring(con, asof, adv, zones, fall_fn)
    return out


def _zone(con, root: Path, isin: str, asof: date) -> dict:
    """The buy zone of an ETF the bucket plan buys (gold ETF); none for a fund bought at its NAV."""
    from pflab.app import research as rs
    from pflab.plan import buyzone as bz
    try:
        return bz.zone(rs.closes(con, root, isin, asof), asof, paths=2_000)
    except Exception:
        return {}


def _range(z: dict) -> Optional[dict]:
    if not z or z.get("bottom") is None or z.get("top") is None:
        return None
    return {"low": round(float(z["bottom"]), 2), "high": round(float(z["top"]), 2), "price": z.get("price")}


def ring(con, asof: date, adv, zones: Dict[str, dict], fall_fn=None) -> dict:
    """The outer ring, as an idea: the plan's stock rupees into list names not held yet (in the order of the list: the buy zone failed its test, so it orders nothing),
    nothing topping up held names; its numbers beside the plan's."""
    from pflab.pm import today as nw
    from pflab.plan import guards as gd
    spend = sum(b.cost for b in adv.buys)
    pos = nw.build(con, asof)["positions"]
    eq = pos[(pos["bucket"] == "equity") & pos["value"].notna()].groupby("isin")["value"].sum()
    held = {i: float(v) for i, v in eq.items() if v > 0}
    lst = gd.stock_list()
    skipped = {k.split(" (")[0] for k in adv.skipped}                    # "SYMBOL (verdict)"
    ok = {s["isin"]: s["symbol"] for s in lst if s["isin"] not in held and s["symbol"] not in skipped}
    if spend <= 0:
        return {"shown": False, "why": "this plan buys no stocks"}
    if not ok:
        return {"shown": True, "possible": False,
                "why": "every name on your list that passes the guards is held already: a new ring needs new names on "
                       "your list (your call); the watch list checks any name you add"}
    order = sorted(ok, key=lambda i: ok[i])        # by symbol: the zone verdict (S54c, failed) never orders picks
    picks = order[: max(1, min(len(order), 3))]
    each = spend / len(picks)
    buys = []
    for i in picks:
        px = (zones.get(i) or {}).get("price")
        q = int(math.floor(each / px)) if px else 0
        buys.append({"symbol": ok[i], "isin": i, "qty": q, "price": px, "cost": round(q * px, 2) if px else 0.0,
                     "range": _range(zones.get(i) or {}), "verdict": (zones.get(i) or {}).get("verdict")})
    plan_after = dict(held)
    for b in adv.buys:
        plan_after[b.isin] = plan_after.get(b.isin, 0.0) + b.cost
    ring_after = dict(held)
    for b in buys:
        ring_after[b["isin"]] = ring_after.get(b["isin"], 0.0) + b["cost"]
    sectors = _sector_of(con, set(plan_after) | set(ring_after))
    out = {"shown": True, "possible": True, "buys": buys, "spend": round(sum(b["cost"] for b in buys), 2),
           "plan": _shape(plan_after, sectors), "ring": _shape(ring_after, sectors),
           "why": "the same stock money starts new names around the ones you hold instead of adding to them; nothing "
                  "is sold"}
    if fall_fn:
        out["plan"]["fall"], out["ring"]["fall"] = fall_fn(plan_after), fall_fn(ring_after)
    return out


def _shape(values: Dict[str, float], sectors: Dict[str, str]) -> dict:
    tot = sum(values.values()) or 1.0
    return {"names": len(values), "largest": max(values.values()) / tot if values else 0.0,
            "sectors": len({sectors[i] for i in values if i in sectors}), "sector_known": sum(i in sectors for i in values)}


def sleeve_fall(root: Path, paths: int = RING_PATHS, seed: int = 20261023) -> Callable[[Dict[str, float]], dict]:
    """The chance that the stock sleeve alone (these names at these values) falls more than 35% on some session within a
    year: daily one-year blocks of the names' own returns (the equal-weight Nifty 500 before a name listed). The same
    random blocks for every basket, so two baskets are compared on the same draws."""
    import numpy as np

    from pflab.app import sims
    from pflab.calc import smalln
    from pflab.risk import montecarlo as mc
    proxy = mc.history_daily(root)["stocks"]

    def fall(values: Dict[str, float]) -> dict:
        tot = sum(values.values())
        d, own = sims.mine_daily(root, {i: v / tot for i, v in values.items()}, proxy)
        p = mc.fall_any_day_block(d.to_numpy()[:, None], np.array([1.0]), 12, paths, np.random.default_rng(seed))
        return {"p": p, **smalln.tail(p, paths), "own_share": own}
    return fall


# --- kept current ------------------------------------------------------------------------------------------------------

def _hash(plan: dict) -> str:
    keep = {k: plan[k] for k in ("amount", "buckets", "how", "stocks", "unspent")}
    keep["stocks"] = [{k: s[k] for k in ("symbol", "qty")} for s in plan["stocks"]]
    keep["how"] = [{k: h[k] for k in ("isin", "units")} for h in plan["how"]]
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()[:16]


def changes(old: Optional[dict], new: dict) -> List[str]:
    """What changed since the last version, in words."""
    if not old:
        return ["first version"]
    out = []
    if abs(old["amount"] - new["amount"]) > 0.5:
        out.append(f"amount {old['amount']:,.0f} -> {new['amount']:,.0f}")
    a = {s["symbol"]: s["qty"] for s in old.get("stocks", [])}
    b = {s["symbol"]: s["qty"] for s in new.get("stocks", [])}
    for s in sorted(set(a) | set(b)):
        if a.get(s) != b.get(s):
            out.append(f"{s}: {a.get(s, 0)} -> {b.get(s, 0)} shares")
    ha = {h["isin"]: h["units"] for h in old.get("how", [])}
    hb = {h["isin"]: h["units"] for h in new.get("how", [])}
    names = {h["isin"]: h["name"] for h in old.get("how", []) + new.get("how", [])}
    for i in sorted(set(ha) | set(hb)):
        if ha.get(i) != hb.get(i):
            out.append(f"{names[i]}: {ha.get(i, 0):g} -> {hb.get(i, 0):g} units")
    return out or ["prices moved; the same buys"]


def refresh(con, asof: date, root: Path, now: datetime, zones: Dict[str, dict], extra: Optional[Trigger] = None,
            fall_fn=None, run=None) -> List[dict]:
    """Every trigger's plan rebuilt; a new version stored when it changed; a held message when the money is near."""
    from pflab.pm.store import next_id
    from pflab.service import telegram as tgm
    trigs = triggers(con, asof, now=now) + ([extra] if extra else [])
    if extra:                                                           # one re-plan at a time
        con.execute("UPDATE ready_plans SET status='past' WHERE status='current' AND trigger_key LIKE 'custom:%' "
                    "AND trigger_key <> ?", [extra.key])
    out = []
    for t in trigs:
        plan = build(con, asof, t, zones, root, fall_fn, run)
        h = _hash(plan)
        last = con.execute("SELECT plan_id, inputs_hash, plan_json FROM ready_plans WHERE trigger_key=? AND status='current'",
                           [t.key]).fetchone()
        if last and last[1] == h:
            con.execute("UPDATE ready_plans SET checked_at=? WHERE plan_id=?", [now, last[0]])
            out.append({**json.loads(last[2]), "plan_id": last[0], "checked_at": str(now)})
            continue
        plan["changes"] = changes(json.loads(last[2]) if last else None, plan)
        if last:
            con.execute("UPDATE ready_plans SET status='superseded' WHERE plan_id=?", [last[0]])
        pid = next_id(con, "ready_plans", "plan_id")
        con.execute("INSERT INTO ready_plans (plan_id, trigger_key, kind, due, amount, source, inputs_hash, plan_json, "
                    "status, created_at, checked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [pid, t.key, t.kind, t.due, t.amount, t.source, h, json.dumps(plan, default=str), "current", now, now])
        out.append({**plan, "plan_id": pid, "checked_at": str(now)})
        if t.kind != "custom" and (t.due - asof).days <= NOTIFY_DAYS:
            tgm.enqueue(con, f"Ready plan for {t.source} (about Rs {t.amount:,.0f}, {t.due:%d %b}): "
                             f"{len(plan['stocks'])} stock buys, {len(plan['how'])} fund/ETF buys. Open Research and "
                             "plans on the dashboard; you place every order.", "ready_plan",
                        dedup_key=f"ready:{t.key}", now=now)
    live = {t.key for t in trigs}
    for pid, key in con.execute("SELECT plan_id, trigger_key FROM ready_plans WHERE status='current'").fetchall():
        if key not in live and not key.startswith("custom:"):
            con.execute("UPDATE ready_plans SET status='past' WHERE plan_id=?", [pid])
    return out


def current(con, limit: int = 6) -> List[dict]:
    rows = con.execute("SELECT plan_id, plan_json, created_at, checked_at FROM ready_plans WHERE status='current' "
                       "ORDER BY due, plan_id DESC LIMIT ?", [limit]).fetchall()
    return [{**json.loads(j), "plan_id": p, "made": str(c)[:16], "checked": str(k)[:16]} for p, j, c, k in rows]


def custom(amount: float, asof: date) -> Trigger:
    return Trigger(f"custom:{asof}:{amount:.0f}", "custom", asof, float(amount), "the amount you gave", False)


__all__ = ["Trigger", "triggers", "build", "ring", "refresh", "current", "changes", "custom", "sleeve_fall"]
