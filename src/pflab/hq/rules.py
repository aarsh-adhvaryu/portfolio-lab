"""House rules (S72): what he tells the system to do from now on, kept in his words, versioned, read by every agent and enforced where code can enforce it.

This is the system's CLAUDE.md. A message like "no new tech until I say" or "always include a 0.5% charge in cost tests" is not an answer to one question: it changes how the
system works from now on, so it must outlive the conversation, reach every agent, be visible, and be undoable. Kinds:

    pause_buys         (S85) no buying of a class (gold, international, index, stocks, all), a sleeve (core, longterm) or one name until a date. Code-enforced in the close, the session loop, the picks, the
                       US step and the thinking loop's cases; every order held back names the rule.
    hold_name          (S85) one name is not sold until a date except by a stop, a rail trim, a thesis break or the fall gauge's risk cut.
    no_new_names       (S85) no name that is not already held or picked enters the book until a date.
    cash_floor         (S85) at least a share of the book stays cash: buying stops short of it (it never forces a sale).
    sector_exclusion   no NEW buying in the named sectors or themes (a BUY or ADD proposal there is refused with the rule's name; holding and selling are untouched). Code-enforced.
    max_position       a ceiling on one holding's share of the portfolio. MONEY: it is a limit.
    monthly_envelope   the sum for shares each month, how long it runs, whether unspent carries over (plan/envelope.py). MONEY: an amount.
    dip_tranche        an extra sum when the market is a stated share below its high (plan/envelope.py). MONEY: an amount.
    method             how work is to be done (include costs, a source not to be used, a baseline to show). Every agent is told; checked by the reviewer.
    note               anything else he wants all agents to know and keep.

His decision (2026-11-01): a rule that touches no money takes effect AT ONCE with an Undo; a rule about an amount, limit or target waits for his yes (`status='pending'` until
`decide`); targets, limits and the stock list themselves still change only through `plan/prefs.py`. An Undo restores the version it replaced. Every version is kept.
`active_text` is what the agents read (their prompts carry it, so a change reaches the next task); `render` keeps `pm/house_rules.md` as a readable copy.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

NEW_KINDS = ("pause_buys", "hold_name", "no_new_names", "cash_floor")                        # S85 (E4): the kinds the v2 loop understands; each only ever tightens
KINDS = ("sector_exclusion", "max_position", "monthly_envelope", "dip_tranche", "method", "note") + NEW_KINDS
MONEY = ("max_position", "monthly_envelope", "dip_tranche")
BUYING = ("BUY", "ADD")
CLASSES = ("gold", "international", "index", "stocks", "all")                                 # the book's classes a pause_buys may name (index = the core's index ETFs, stocks = single shares)
SLEEVES = ("core", "longterm")
MARKETS = ("IN", "US")
DEFAULT_DAYS = 30                                                                             # no end date given = 30 days (shown to him)
MAX_DAYS = 400
PROTECTED_SELLS = ("stop", "thesis", "trim", "rail", "risk", "gauge")                         # a hold_name never stops these sales: a stop, a rail trim, a thesis break, a risk cut


def _id(con) -> int:
    from pflab.pm.store import next_id
    return next_id(con, "hq_rules", "rule_id")


def check(kind: str, machine: dict) -> Optional[str]:
    """What is wrong with a rule's machine form, or None."""
    if kind not in KINDS:
        return f"kind is one of {', '.join(KINDS)}"
    m = machine or {}
    if kind == "sector_exclusion":
        terms = m.get("terms")
        if not isinstance(terms, list) or not terms or not all(isinstance(t, str) and 2 <= len(t.strip()) <= 40 for t in terms):
            return "a sector exclusion names at least one sector or theme word (terms), 2 to 40 characters each"
    elif kind == "max_position":
        v = m.get("max_weight_pct")
        if not isinstance(v, (int, float)) or not 1 <= v <= 50:
            return "max_weight_pct is a number from 1 to 50"
    elif kind == "monthly_envelope":
        a = m.get("amount_rupees")
        if not isinstance(a, (int, float)) or not 1000 <= a <= 10 ** 8:
            return "amount_rupees is a number from 1,000 to 10 crore"
        if m.get("until") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(m["until"])):
            return "until is a date YYYY-MM-DD"
        if m.get("carry_over") is not None and not isinstance(m["carry_over"], bool):
            return "carry_over is true or false"
    elif kind == "dip_tranche":
        a, d = m.get("extra_rupees"), m.get("below_high_pct")
        if not isinstance(a, (int, float)) or not 1000 <= a <= 10 ** 8 or not isinstance(d, (int, float)) or not 3 <= d <= 60:
            return "extra_rupees is 1,000 to 10 crore and below_high_pct is 3 to 60"
    elif kind == "pause_buys":
        scope, val = m.get("scope"), str(m.get("value") or "").lower()
        if scope not in ("class", "sleeve", "name", "all"):
            return "pause_buys scope is class, sleeve, name or all"
        if scope == "class" and val not in CLASSES:
            return f"the class is one of {', '.join(CLASSES)}"
        if scope == "sleeve" and val not in SLEEVES:
            return f"the sleeve is one of {', '.join(SLEEVES)}"
        if scope == "name" and not (m.get("isin") or m.get("symbol")):
            return "a name rule needs the name's ISIN or symbol"
    elif kind == "hold_name":
        if not (m.get("isin") or m.get("symbol")):
            return "hold_name needs the name's ISIN or symbol"
    elif kind == "cash_floor":
        v = m.get("share_pct")
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not 1 <= v <= 90:
            return "share_pct is a number from 1 to 90 (the share of the book kept in cash)"
    if kind in NEW_KINDS and m.get("market") not in (None, "", *MARKETS):
        return "market is IN or US (or left out for both)"
    return None


def as_date(v) -> Optional[date]:
    """A date from a date, a datetime or 'YYYY-MM-DD'; None when it is none of them."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def state_of(status: str, until: Optional[date], day: Optional[date] = None) -> str:
    """active | waiting_yes | undone | expired | superseded | declined (an active rule past its date reads as expired)."""
    if status == "pending":
        return "waiting_yes"
    if status == "active" and until is not None and day is not None and until < day:
        return "expired"
    return status


def sectors_matching(con, terms: List[str]) -> List[str]:
    """The sector labels in the instrument master that a list of words covers (whole words, case-insensitive): shown to him when a rule is made, so he sees what it means."""
    labels = [r[0] for r in con.execute("SELECT DISTINCT sector FROM instruments WHERE sector IS NOT NULL AND asset_class = 'equity' ORDER BY 1").fetchall()]
    pats = [re.compile(r"\b" + re.escape(t.strip().lower()) + r"\b") for t in terms]
    return [s for s in labels if any(p.search(s.lower()) for p in pats)]


def active(con, day=None) -> List[dict]:
    """The active rules. With `day` (S85), a rule whose end date is before that day has lapsed and is left out (nothing is written: `sweep` marks them expired)."""
    cols = ("rule_id", "kind", "name", "text", "machine", "version", "status", "by", "at", "until")
    rows = con.execute("SELECT rule_id, kind, name, text, machine_json, version, status, by_who, created_at, until FROM hq_rules WHERE status = 'active' ORDER BY rule_id").fetchall()
    d = as_date(day)
    out = [{**dict(zip(cols, r)), "machine": json.loads(r[4] or "{}")} for r in rows]
    if d is not None:
        out = [r for r in out if r["until"] is None or r["until"] >= d]
    for r in out:
        r["state"] = "active"
    return out


def pending(con) -> List[dict]:
    rows = con.execute("SELECT rule_id, kind, name, text, machine_json, version, created_at, until FROM hq_rules WHERE status = 'pending' ORDER BY rule_id").fetchall()
    return [{"rule_id": r[0], "kind": r[1], "name": r[2], "text": r[3], "machine": json.loads(r[4] or "{}"), "version": r[5], "at": r[6], "until": r[7], "state": "waiting_yes"} for r in rows]


def listing(con, day=None, limit: int = 40) -> List[dict]:
    """For the Settings screen: every rule newest first with its state (active, waiting_yes, expired, undone, ...), its end date and what it is in plain words."""
    d = as_date(day) or date.today()
    rows = con.execute("SELECT rule_id, kind, name, text, machine_json, version, status, created_at, until FROM hq_rules ORDER BY rule_id DESC LIMIT ?", [int(limit)]).fetchall()
    out = []
    for r in rows:
        rec = {"rule_id": r[0], "kind": r[1], "name": r[2], "text": r[3], "machine": json.loads(r[4] or "{}"), "version": r[5], "state": state_of(r[6], r[8], d), "at": r[7], "until": r[8]}
        rec.update(plain=describe(rec), can_undo=r[6] in ("active", "pending"), can_change_date=r[1] in NEW_KINDS and r[6] == "active")
        out.append(rec)
    return out


def sweep(con, day) -> List[int]:
    """Mark the rules past their end date `expired` (they already stopped acting: `active(con, day)` leaves them out). -> the ids."""
    d = as_date(day) or date.today()
    ids = [r[0] for r in con.execute("SELECT rule_id FROM hq_rules WHERE status = 'active' AND until IS NOT NULL AND until < ?", [d]).fetchall()]
    for i in ids:
        con.execute("UPDATE hq_rules SET status = 'expired', decided_at = ?, decided_by = 'expired by date' WHERE rule_id = ?", [datetime.combine(d, datetime.min.time()), i])
    return ids


def describe(r: dict) -> str:
    """A rule in plain words, with its end date."""
    m, u = r.get("machine") or {}, r.get("until")
    end = f" until {u:%d %b}" if isinstance(u, date) else ""
    k = r.get("kind")
    where = f" in {m['market']}" if m.get("market") else ""
    if k == "pause_buys":
        what = {"class": f"{m.get('value')} buys", "sleeve": f"buying in the {m.get('value')} sleeve", "name": f"buying {m.get('symbol') or m.get('isin')}", "all": "all buying"}.get(m.get("scope"), "buying")
        return f"pause {what}{where}{end}"
    if k == "hold_name":
        return f"hold {m.get('symbol') or m.get('isin')}: no sale except a stop, a rail or a thesis break{end}"
    if k == "no_new_names":
        return f"no new names{where}{end}"
    if k == "cash_floor":
        return f"keep at least {float(m.get('share_pct') or 0):g}% of the book in cash{where}{end}"
    return str(r.get("text") or "")


def label(r: dict) -> str:
    """How an order held back names the rule: his own words (the rule's text)."""
    return f"your rule '{' '.join(str(r.get('text') or r.get('name') or '').split())[:90]}'"


def version(con) -> int:
    """Changes whenever any rule is made, decided or undone: tasks and proposals record the version they ran under."""
    return int(con.execute("SELECT coalesce(max(rule_id), 0) + coalesce(count(*) FILTER (WHERE status IN ('undone', 'superseded')), 0) FROM hq_rules").fetchone()[0])


def _name(text: str) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", text.lower())[:6])[:40] or "rule"


def propose(con, now: datetime, kind: str, text: str, machine: Optional[dict] = None, *, name: str = "", by: str = "the investor (chat)", source: str = "", until=None) -> dict:
    """Make a rule. Not about money: active now (an earlier rule of the same name becomes superseded, restorable by Undo). About money: pending his yes.
    S85: a rule of the new kinds ends on `until` (a date; none given = DEFAULT_DAYS from today, said in the answer as `until_defaulted`)."""
    text = " ".join((text or "").split())[:600]
    if len(text) < 6:
        return {"made": False, "why": "say what the rule is, in a sentence"}
    err = check(kind, machine or {})
    if err:
        return {"made": False, "why": err}
    until_d, defaulted = as_date(until), False
    if until not in (None, "") and until_d is None:
        return {"made": False, "why": "the end date is not a date (YYYY-MM-DD)"}
    if kind in NEW_KINDS:
        if until_d is None:
            until_d, defaulted = now.date() + timedelta(days=DEFAULT_DAYS), True
        if until_d < now.date():
            return {"made": False, "why": f"{until_d:%d %b %Y} is already past"}
        if until_d > now.date() + timedelta(days=MAX_DAYS):
            return {"made": False, "why": f"a rule runs at most {MAX_DAYS} days; ask again nearer the time"}
    name = re.sub(r"[^a-z0-9_]+", "_", (name or _name(text)).lower()).strip("_")[:40]
    prev = con.execute("SELECT rule_id, version, status, text FROM hq_rules WHERE name = ? AND status IN ('active', 'pending') ORDER BY rule_id DESC LIMIT 1", [name]).fetchone()
    if prev and prev[3] == text and prev[2] in ("active", "pending"):
        return {"made": False, "duplicate": True, "rule_id": prev[0], "why": "that rule is already recorded"}
    money = kind in MONEY
    rid, ver = _id(con), (int(prev[1]) + 1 if prev else 1)
    status = "pending" if money else "active"
    if prev and not money:
        con.execute("UPDATE hq_rules SET status = 'superseded' WHERE rule_id = ?", [prev[0]])
    con.execute("INSERT INTO hq_rules (rule_id, kind, name, text, machine_json, version, status, by_who, created_at, source, supersedes, until) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [rid, kind, name, text, json.dumps(machine or {}), ver, status, by, now, source[:300], prev[0] if prev else None, until_d])
    covers = sectors_matching(con, (machine or {}).get("terms", [])) if kind == "sector_exclusion" else []
    return {"made": True, "rule_id": rid, "name": name, "kind": kind, "version": ver, "status": status, "needs_yes": money,
            "covers": covers, "replaces": prev[0] if prev else None, "until": until_d, "until_defaulted": defaulted}


def decide(con, now: datetime, rule_id: int, yes: bool, by: str = "the investor (chat)") -> dict:
    """His yes or no to a rule about money. A yes makes it active (and an earlier rule of the same name superseded); a no discards it."""
    r = con.execute("SELECT name, status FROM hq_rules WHERE rule_id = ?", [rule_id]).fetchone()
    if r is None or r[1] != "pending":
        return {"decided": False, "why": "no rule with that id waits for a yes"}
    if not yes:
        con.execute("UPDATE hq_rules SET status = 'declined', decided_at = ?, decided_by = ? WHERE rule_id = ?", [now, by, rule_id])
        return {"decided": True, "status": "declined"}
    con.execute("UPDATE hq_rules SET status = 'superseded' WHERE name = ? AND status = 'active'", [r[0]])
    con.execute("UPDATE hq_rules SET status = 'active', decided_at = ?, decided_by = ? WHERE rule_id = ?", [now, by, rule_id])
    return {"decided": True, "status": "active"}


def undo(con, a, b=None) -> dict:
    """Undo a rule by id or name: it becomes `undone`, and the version it replaced (if any) is active again. `undo(con, rule_id)` or `undo(con, now, ref)`."""
    now, ref = (datetime.now(), a) if b is None else (a, b)
    row =(con.execute("SELECT rule_id, name, supersedes FROM hq_rules WHERE rule_id = ? AND status IN ('active', 'pending')", [int(ref)]).fetchone()
           if str(ref).isdigit() else
           con.execute("SELECT rule_id, name, supersedes FROM hq_rules WHERE name = ? AND status IN ('active', 'pending') ORDER BY rule_id DESC LIMIT 1", [str(ref)]).fetchone())
    if row is None:
        return {"undone": False, "why": "no active or waiting rule with that id or name"}
    con.execute("UPDATE hq_rules SET status = 'undone', decided_at = ? WHERE rule_id = ?", [now, row[0]])
    restored = None
    if row[2] is not None and con.execute("SELECT status FROM hq_rules WHERE rule_id = ?", [row[2]]).fetchone()[0] == "superseded":
        con.execute("UPDATE hq_rules SET status = 'active' WHERE rule_id = ?", [row[2]])
        restored = int(row[2])
    return {"undone": True, "rule_id": int(row[0]), "name": row[1], "restored": restored}


def active_text(con, day=None) -> str:
    """What every agent reads: the active rules in his words (empty when there are none); with `day`, the ones that have not lapsed by then."""
    rs = active(con, day)
    if not rs:
        return ""
    return (f"HOUSE RULES (version {version(con)}; he made these, they bind all your work until he undoes them):\n"
            + "\n".join(f"- [{r['name']}] {r['text']}" for r in rs))


def render(con, pm_dir: Path) -> Path:
    """The readable copy: pm/house_rules.md."""
    rs, pend = active(con), pending(con)
    lines = ["# House rules", "", "Made by you in the conversation; every agent reads them. Undo from the conversation or the screen.", ""]
    lines += [f"- **{r['name']}** ({r['kind']}, v{r['version']}, {str(r['at'])[:10]}): {r['text']}" for r in rs] or ["(none yet)"]
    if pend:
        lines += ["", "## Waiting for your yes (about money)", ""] + [f"- **{r['name']}** ({r['kind']}): {r['text']}" for r in pend]
    p = Path(pm_dir) / "house_rules.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# --- enforcement ------------------------------------------------------------------------------------------------------------------

def sector_of(con, isin: str) -> str:
    r = con.execute("SELECT sector FROM instruments WHERE isin = ?", [isin]).fetchone()
    return (r[0] or "") if r else ""


def violation(con, action: str, isin: Optional[str]) -> Optional[str]:
    """The reason a proposal may not be made under the active rules, or None. A BUY or ADD in an excluded sector is refused; every other action is untouched."""
    if (action or "").upper() not in BUYING or not isin:
        return None
    sector = sector_of(con, isin).lower()
    if not sector:
        return None
    for r in active(con):
        if r["kind"] == "sector_exclusion":
            for t in r["machine"].get("terms", []):
                if re.search(r"\b" + re.escape(t.strip().lower()) + r"\b", sector):
                    return f"house rule '{r['name']}' ({r['text'][:120]}) forbids new buying in {sector_of(con, isin)}"
    return None


# --- S85: Undo with a date, and what the loop reads -----------------------------------------------------------------------------------

def change_date(con, rule_id: int, until, now: Optional[datetime] = None) -> dict:
    """Change the end date of an active rule of the new kinds (his 'Change date'). A date already past, or further than MAX_DAYS, is refused."""
    now = now or datetime.now()
    r = con.execute("SELECT kind, status, until FROM hq_rules WHERE rule_id = ?", [int(rule_id)]).fetchone()
    if r is None or r[1] != "active" or r[0] not in NEW_KINDS:
        return {"changed": False, "why": "no active rule of that kind with that id"}
    d = as_date(until)
    if d is None:
        return {"changed": False, "why": "the date is not a date (YYYY-MM-DD)"}
    if d < now.date():
        return {"changed": False, "why": f"{d:%d %b %Y} is already past: use Undo to end the rule"}
    if d > now.date() + timedelta(days=MAX_DAYS):
        return {"changed": False, "why": f"a rule runs at most {MAX_DAYS} days"}
    con.execute("UPDATE hq_rules SET until = ? WHERE rule_id = ?", [d, int(rule_id)])
    return {"changed": True, "rule_id": int(rule_id), "was": r[2], "until": d}


def _classes(cls) -> set:
    if cls is None:
        return set()
    if isinstance(cls, str):
        return {cls.lower()}
    return {str(c).lower() for c in cls}


def _names(m: dict) -> set:
    return {str(x).upper() for x in (m.get("isin"), m.get("symbol")) if x}


def blocks(con, day, *, isin: Optional[str] = None, symbol: Optional[str] = None, sleeve: Optional[str] = None, cls=None, action: str = "buy", order_kind: Optional[str] = None,
           new_name: bool = False, market: Optional[str] = None) -> Optional[dict]:
    """The active rule that stops this order, or None (the first one by id). `action` buy: `pause_buys` (the class, the sleeve, the name or all; `cls` may be one class or several) and,
    when `new_name`, `no_new_names`. `action` sell: `hold_name`, unless `order_kind` is a stop, a rail trim, a thesis break or a risk cut (PROTECTED_SELLS). A rule with a market
    stops only that market's orders. The kill switch and the rails sit above rules and are not read here."""
    act, c, who = (action or "buy").lower(), _classes(cls), {str(x).upper() for x in (isin, symbol) if x}
    for r in active(con, day):
        m, k = r["machine"], r["kind"]
        if m.get("market") and market and m["market"] != market:
            continue
        if act == "buy":
            if k == "no_new_names" and new_name:
                return r
            if k == "pause_buys":
                sc, val = m.get("scope"), str(m.get("value") or "").lower()
                if sc == "all" or (sc == "class" and val in c) or (sc == "sleeve" and sleeve and val == str(sleeve).lower()) or (sc == "name" and who & _names(m)):
                    return r
        elif act == "sell" and k == "hold_name" and who & _names(m) and str(order_kind or "").lower() not in PROTECTED_SELLS:
            return r
    return None


def cash_floor(con, day, market: Optional[str] = None) -> Optional[dict]:
    """The strongest active cash floor: {"share": fraction of the book, "rule": rule} or None. It only ever limits buying."""
    best = None
    for r in active(con, day):
        if r["kind"] != "cash_floor" or (r["machine"].get("market") and market and r["machine"]["market"] != market):
            continue
        s = float(r["machine"].get("share_pct") or 0.0) / 100.0
        if best is None or s > best["share"]:
            best = {"share": s, "rule": r}
    return best


def held_back(con, day, limit: int = 20) -> List[dict]:
    """The orders the rules held back on `day` (what the card and the 15:45 report say)."""
    cols = ("held_id", "day", "market", "isin", "symbol", "side", "rule_id", "rule_name", "rule_text", "site", "order_kind", "value", "note")
    rows = con.execute("SELECT " + ", ".join(cols) + " FROM rules_held_back_s85 WHERE day = ? ORDER BY held_id LIMIT ?", [as_date(day), int(limit)]).fetchall()
    return [dict(zip(cols, r)) for r in rows]
