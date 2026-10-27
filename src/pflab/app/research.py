"""S54c: the watch list, the ready plan, price watches and "check my idea", computed in the background and cached
(PFLAB_PM_DIR/app/cache), because a guard check and 100,000 simulated paths per name take seconds, not milliseconds.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from pflab.plan import buyzone as bz

GROWTH_CLIP = (0.0, 0.30)          # TTM earnings growth used for the fair price: 0-30% (a single year is noisy)


def cache_path(rt, name: str) -> Path:
    return rt.pm_dir / "app" / "cache" / f"{name}.json"


def read_cache(rt, name: str) -> Optional[dict]:
    p = cache_path(rt, name)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except ValueError:
        return None


def write_cache(rt, name: str, data: dict) -> None:
    p = cache_path(rt, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, default=str, indent=1), encoding="utf-8")
    tmp.replace(p)


def closes(con, root: Path, isin: str, asof: date, years: int = 4) -> pd.Series:
    """Daily closes: the research panel's adjusted closes, joined to the store's closes at their last shared date
    (the panel ends mid-September 2026; the store's prices start in August), split-safe."""
    from pflab import _duck
    if isin.startswith(("ZZ", "US:")):                                 # S64 Phase 6: a US instrument; dollars, total-return adjusted
        up = root / "us" / "prices.parquet"
        if not up.exists():
            return pd.Series(dtype=float)
        d = _duck.sql(f"SELECT date, adj_close FROM '{up.as_posix()}' WHERE isin = '{isin}' AND date >= DATE "
                      f"'{asof - timedelta(days=365 * years)}' AND date <= DATE '{asof}' ORDER BY date").df()
        return pd.Series(d["adj_close"].to_numpy(float), index=pd.to_datetime(d["date"]))
    p = root / "panel" / "prices.parquet"
    a = pd.Series(dtype=float)
    if p.exists():
        d = _duck.sql(f"SELECT date, adj_close FROM '{p.as_posix()}' WHERE isin = '{isin}' AND date >= DATE "
                       f"'{asof - timedelta(days=365 * years)}' AND date <= DATE '{asof}' ORDER BY date").df()
        a = pd.Series(d["adj_close"].to_numpy(float), index=pd.to_datetime(d["date"]))
    s = con.execute("SELECT date, close FROM prices WHERE isin=? AND date<=? ORDER BY date", [isin, asof]).df()
    b = pd.Series(s["close"].to_numpy(float), index=pd.to_datetime(s["date"])) if len(s) else pd.Series(dtype=float)
    if a.empty:
        return b
    if b.empty:
        return a
    common = a.index.intersection(b.index)
    if len(common):
        k = b.loc[common[-1]] / a.loc[common[-1]]
        a = a * k
        return pd.concat([a[a.index <= common[-1]], b[b.index > common[-1]]])
    return pd.concat([a, b[b.index > a.index[-1]]])


def names(con, stock_list: List[dict]) -> List[dict]:
    """The list's names and every held equity (ISIN-keyed)."""
    from pflab.pm import today as nw
    out = {s["isin"]: {"isin": s["isin"], "symbol": s["symbol"], "scrip": s.get("scrip"), "on_list": True} for s in stock_list}
    pos = nw.build(con, date.today())["positions"]
    for r in pos.itertuples():
        if r.isin not in out and str(r.isin).startswith("INE") and r.bucket == "equity":
            out[r.isin] = {"isin": r.isin, "symbol": r.symbol, "scrip": None, "on_list": False}
    return list(out.values())


def compute_watch(rt, now: Optional[datetime] = None, paths: int = bz.PATHS) -> dict:
    from pflab.app import views
    from pflab.fundamentals import pit
    from pflab.plan import guards as gd
    from pflab.quant import forecast as fl
    now = now or rt.clock()
    asof = now.date()
    con = rt.cursor()
    lst = gd.stock_list()
    ns = names(con, lst)
    guards = {g.isin: g for g in gd.check_all(con, asof, [n for n in ns if n["on_list"]])}
    rows = []
    for n in ns:
        g = guards.get(n["isin"])
        scrip = n["scrip"] or fl.scrip_of(rt.data_root, n["isin"], asof)
        eps, growth, quarters = None, None, 0
        if scrip:
            q = pit.load(con, str(scrip))
            quarters = int(len(q))
            if len(q):
                r = pit.ratios(pit.last_quarters(q, str(scrip), asof))
                eps = r.get("eps_ttm")
                g_ = r.get("eps_ttm_yoy")
                growth = None if g_ is None else min(max(g_, GROWTH_CLIP[0]), GROWTH_CLIP[1])
        z = bz.zone(closes(con, rt.data_root, n["isin"], asof), asof, eps, growth, g.verdict if g else "ok", paths=paths)
        flags7 = con.execute("SELECT count(*) FROM research_flags WHERE isin=? AND happened_at >= ?",
                             [n["isin"], now - timedelta(days=7)]).fetchone()[0]
        asks = []
        if quarters < 8:
            asks.append(f"Only {quarters} quarters of results on record: a Tijori export of its quarterly financials "
                        "(into Inbox and files) would let the system set a results range and check margins.")
        rows.append({**n, "scrip": scrip, "zone": z, "guard": g.verdict if g else "not checked",
                     "reasons": g.reasons if g else [], "quarters": quarters, "flags_7d": int(flags7),
                     "results": fl.results_lines(con, scrip, n["symbol"]) if scrip else [], "asks": asks,
                     "name": views._clean((con.execute("SELECT name FROM instruments WHERE isin=?", [n["isin"]]).fetchone() or [None])[0])})
    order = {"IN ZONE": 0, "ABOVE ZONE": 1, "RICH": 2, "NO DATA": 3, "NO": 4}
    rows.sort(key=lambda r: (order.get(r["zone"].get("verdict"), 9), r["symbol"] or ""))
    out = {"at": now.isoformat(timespec="seconds"), "paths": paths, "rows": rows}
    write_cache(rt, "watch", out)
    rt.bump("watch", "command")
    return out


def zones_by_isin(rt) -> Dict[str, dict]:
    return {r["isin"]: r["zone"] for r in (read_cache(rt, "watch") or {}).get("rows", [])}


def compute_plan(rt, amount: Optional[float] = None, now: Optional[datetime] = None) -> dict:
    """S55: every ready plan kept current (the next FD tranches, the monthly amount), plus a re-plan for `amount`.
    A failure is kept for the screen, never hidden."""
    from pflab.plan import ready
    now = now or rt.clock()
    out = {"at": now.isoformat(timespec="seconds")}
    try:
        extra = ready.custom(amount, now.date()) if amount else None
        plans = ready.refresh(rt.cursor(), now.date(), rt.data_root, now, zones_by_isin(rt), extra,
                              fall_fn=ready.sleeve_fall(rt.data_root))
        out["plans"] = len(plans)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"[:400]
    write_cache(rt, "plan", out)
    rt.bump("research", "notifications")
    return out


def hold_off(watch: Optional[dict], con, now: datetime) -> List[dict]:
    """Names on the list not to buy now, with the reason: a guard, a price above its zone, results within reach."""
    out = []
    pending = {s: str(t) for s, t in con.execute(
        "SELECT subject, max(target) FROM forecasts WHERE use='revenue' AND scored_at IS NULL GROUP BY subject").fetchall()}
    for r in (watch or {}).get("rows", []):
        if not r.get("on_list"):
            continue
        z = r["zone"]
        q_end = pending.get(str(r.get("scrip")))
        if z.get("verdict") == "NO":
            out.append({"symbol": r["symbol"], "kind": "guard",
                        "why": z["headline"] + ("; " + "; ".join(r["reasons"][:2]) if r["reasons"] else "")})
        elif q_end and (now.date() - date.fromisoformat(q_end[:10])).days >= 30:
            out.append({"symbol": r["symbol"], "kind": "results",
                        "why": f"results for the quarter ended {q_end[:10]} are due; its range is ready"})
        elif z.get("verdict") in ("ABOVE ZONE", "RICH"):
            out.append({"symbol": r["symbol"], "kind": "zone", "why": f"{z['headline']} (now {z['price']:,.2f})"})
    return out


# --- price watches ----------------------------------------------------------------------------------------------------

def add_watch(con, isin: str, symbol: str, kind: str, level: float, note: str, now: datetime) -> int:
    from pflab.pm.store import next_id
    if kind not in ("below", "above") or not level or level <= 0:
        raise ValueError("a watch is 'below' or 'above' a positive price")
    wid = next_id(con, "watches", "watch_id")
    con.execute("INSERT INTO watches (watch_id, isin, symbol, kind, level, note, created_at) VALUES (?,?,?,?,?,?,?)",
                [wid, isin, symbol, kind, float(level), note, now])
    return wid


def check_watches(rt, now: Optional[datetime] = None) -> List[str]:
    """Each active watch against the latest price (live in market hours, else the close): a hit once a day becomes a
    message and a notification."""
    now = now or rt.clock()
    hits = check_watches_con(rt.cursor(), now, rt.data_root)
    if hits:
        rt.bump("notifications", "watch", "command")
    return hits


def ticket_text(con, wid: int, price: float, root: Optional[Path]) -> str:
    """The ready ticket for a watch made by a suggestion (S64): the amount over the price, entered by the investor; a GTT is
    an order and is never placed."""
    from pflab.plan import trader
    r = con.execute("SELECT sug_id, symbol, amount, max_buy, wrong_if FROM hq_suggestions WHERE watch_id=?", [wid]).fetchone()
    if not r or not r[2] or price <= 0:
        return ""
    qty = int(r[2] // price)
    if qty < 1:
        return ""
    isin = con.execute("SELECT isin FROM hq_suggestions WHERE watch_id=?", [wid]).fetchone()[0]
    nudge = None
    if root is not None and isin:
        from pflab.plan import nudges
        nudge = nudges.fn(con, root, con.execute("SELECT max(date) FROM prices").fetchone()[0] or date.today())
    lines = trader.tickets(r[1], qty, price, trader.decision(root), isin=isin, nudge=nudge)
    nl = "\n"
    return (f"{nl}Suggestion #{r[0]}: about Rs {r[2]:,.0f}, highest buy {r[3]:,.2f}." + (f" Wrong if {r[4]}." if r[4] else "")
            + f"{nl}Ticket (you enter it yourself; nothing is placed):{nl}" + nl.join(lines))


def check_watches_con(con, now: datetime, root: Optional[Path] = None) -> List[str]:
    from pflab.pm import prices
    from pflab.service import telegram as tgm
    hits = []
    for wid, isin, sym, kind, level, last in con.execute(
            "SELECT watch_id, isin, symbol, kind, level, last_hit_at FROM watches WHERE active").fetchall():
        if last is not None and last.date() == now.date():
            continue
        q = prices.latest_price(con, isin, now.date())
        if q is None:
            continue
        if (kind == "below" and q.value <= level) or (kind == "above" and q.value >= level):
            text = f"Watch: {sym or isin} at {q.value:,.2f} is {kind} {level:,.2f} ({'live' if q.kind == 'live' else 'close ' + str(q.date)})"
            try:
                text += ticket_text(con, wid, q.value, root)
            except Exception:                                    # the hit is told even if the ticket cannot be made
                pass
            con.execute("UPDATE watches SET last_hit_at=?, hits = hits + 1 WHERE watch_id=?", [now, wid])
            tgm.enqueue(con, text, "watch", dedup_key=f"watch:{wid}:{now.date()}", now=now)
            hits.append(text)
    return hits


# --- check my idea ------------------------------------------------------------------------------------------------------

_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|k|cr|crore)?|([\d,]+(?:\.\d+)?)\s*(lakh|lac|k|cr|crore)\b", re.I)


def parse_amount(text: str) -> Optional[float]:
    m = _AMOUNT.search(text)
    if not m:
        return None
    num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    x = float(num.replace(",", ""))
    mult = {"lakh": 1e5, "lac": 1e5, "k": 1e3, "cr": 1e7, "crore": 1e7}.get((unit or "").lower(), 1.0)
    return x * mult


def idea(rt, text: str, now: Optional[datetime] = None) -> dict:
    """A name (and optionally an amount) from the investor's words, checked against the zone, the guard, the weight cap and the
    equity target. Code computes every number; the answer says yes, wait or no and shows the working."""
    from pflab import _toml
    from pflab.pm import today as nw
    from pflab.plan import targets as tg
    now = now or rt.clock()
    con = rt.cursor()
    watch = read_cache(rt, "watch") or {"rows": []}
    words = {w.upper() for w in re.findall(r"[A-Za-z][A-Za-z0-9&-]{1,20}", text)}
    row = next((r for r in watch["rows"] if (r["symbol"] or "").upper() in words), None)
    if row is None:
        return {"answer": "No name from the watch list or your holdings was found in that. Add it to the watch list first "
                          "(it is studied tonight), then ask again.", "verdict": None}
    amount = parse_amount(text)
    n = nw.build(con, now.date())
    held = float(n["positions"].loc[n["positions"]["isin"] == row["isin"], "value"].sum()) if len(n["positions"]) else 0.0
    investable = n["investable"] or 1.0
    try:
        max_w = float(_toml.load(tg.default_path()).get("stocks", {}).get("max_weight", 0.10))
    except Exception:
        max_w = 0.10
    z = row["zone"]
    lines = [f"{row['symbol']}: {z.get('headline', '')}."]
    if z.get("price"):
        lines.append(f"Price {z['price']:,.2f}; zone {z.get('bottom', 0):,.0f}-{z.get('top', 0):,.0f}; chance of touching "
                     f"{z.get('top', 0):,.0f} within {z.get('horizon', bz.HORIZON)} sessions: {z['touch_top']['text']}.")
    # buying at once is what the study supports (above the zone too); valuation is a caution, not tested
    verdict = {"IN ZONE": "yes", "ABOVE ZONE": "yes", "RICH": "check", "NO": "no"}.get(z.get("verdict"), "check")
    if amount:
        w_after = (held + amount) / (investable + amount)
        lines.append(f"With ₹{amount:,.0f} more it would be {w_after:.1%} of investable assets (cap {max_w:.0%}).")
        if w_after > max_w:
            verdict = "no"
            lines.append("That passes your single-stock cap.")
    if row.get("reasons"):
        lines.append("Guard: " + "; ".join(row["reasons"][:3]) + ".")
    lines.append("An ESTIMATE from the buy-zone description (not a tested signal); the decision is yours.")
    return {"answer": " ".join(lines), "verdict": verdict, "symbol": row["symbol"], "amount": amount}
