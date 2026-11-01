"""House rules (S72): what he tells the system to do from now on, kept in his words, versioned, read by every agent and enforced where code can enforce it.

This is the system's CLAUDE.md. A message like "no new tech until I say" or "always include a 0.5% charge in cost tests" is not an answer to one question: it changes how the
system works from now on, so it must outlive the conversation, reach every agent, be visible, and be undoable. Kinds:

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
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

KINDS = ("sector_exclusion", "max_position", "monthly_envelope", "dip_tranche", "method", "note")
MONEY = ("max_position", "monthly_envelope", "dip_tranche")
BUYING = ("BUY", "ADD")


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
    return None


def sectors_matching(con, terms: List[str]) -> List[str]:
    """The sector labels in the instrument master that a list of words covers (whole words, case-insensitive): shown to him when a rule is made, so he sees what it means."""
    labels = [r[0] for r in con.execute("SELECT DISTINCT sector FROM instruments WHERE sector IS NOT NULL AND asset_class = 'equity' ORDER BY 1").fetchall()]
    pats = [re.compile(r"\b" + re.escape(t.strip().lower()) + r"\b") for t in terms]
    return [s for s in labels if any(p.search(s.lower()) for p in pats)]


def active(con) -> List[dict]:
    cols = ("rule_id", "kind", "name", "text", "machine", "version", "status", "by", "at")
    rows = con.execute("SELECT rule_id, kind, name, text, machine_json, version, status, by_who, created_at FROM hq_rules WHERE status = 'active' ORDER BY rule_id").fetchall()
    return [{**dict(zip(cols, r)), "machine": json.loads(r[4] or "{}")} for r in rows]


def pending(con) -> List[dict]:
    rows = con.execute("SELECT rule_id, kind, name, text, machine_json, version, created_at FROM hq_rules WHERE status = 'pending' ORDER BY rule_id").fetchall()
    return [{"rule_id": r[0], "kind": r[1], "name": r[2], "text": r[3], "machine": json.loads(r[4] or "{}"), "version": r[5], "at": r[6]} for r in rows]


def version(con) -> int:
    """Changes whenever any rule is made, decided or undone: tasks and proposals record the version they ran under."""
    return int(con.execute("SELECT coalesce(max(rule_id), 0) + coalesce(count(*) FILTER (WHERE status IN ('undone', 'superseded')), 0) FROM hq_rules").fetchone()[0])


def _name(text: str) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", text.lower())[:6])[:40] or "rule"


def propose(con, now: datetime, kind: str, text: str, machine: Optional[dict] = None, *, name: str = "", by: str = "the investor (chat)", source: str = "") -> dict:
    """Make a rule. Not about money: active now (an earlier rule of the same name becomes superseded, restorable by Undo). About money: pending his yes."""
    text = " ".join((text or "").split())[:600]
    if len(text) < 6:
        return {"made": False, "why": "say what the rule is, in a sentence"}
    err = check(kind, machine or {})
    if err:
        return {"made": False, "why": err}
    name = re.sub(r"[^a-z0-9_]+", "_", (name or _name(text)).lower()).strip("_")[:40]
    prev = con.execute("SELECT rule_id, version, status, text FROM hq_rules WHERE name = ? AND status IN ('active', 'pending') ORDER BY rule_id DESC LIMIT 1", [name]).fetchone()
    if prev and prev[3] == text and prev[2] in ("active", "pending"):
        return {"made": False, "duplicate": True, "rule_id": prev[0], "why": "that rule is already recorded"}
    money = kind in MONEY
    rid, ver = _id(con), (int(prev[1]) + 1 if prev else 1)
    status = "pending" if money else "active"
    if prev and not money:
        con.execute("UPDATE hq_rules SET status = 'superseded' WHERE rule_id = ?", [prev[0]])
    con.execute("INSERT INTO hq_rules (rule_id, kind, name, text, machine_json, version, status, by_who, created_at, source, supersedes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [rid, kind, name, text, json.dumps(machine or {}), ver, status, by, now, source[:300], prev[0] if prev else None])
    covers = sectors_matching(con, (machine or {}).get("terms", [])) if kind == "sector_exclusion" else []
    return {"made": True, "rule_id": rid, "name": name, "kind": kind, "version": ver, "status": status, "needs_yes": money,
            "covers": covers, "replaces": prev[0] if prev else None}


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


def undo(con, now: datetime, ref) -> dict:
    """Undo a rule by id or name: it becomes `undone`, and the version it replaced (if any) is active again."""
    row = (con.execute("SELECT rule_id, name, supersedes FROM hq_rules WHERE rule_id = ? AND status IN ('active', 'pending')", [int(ref)]).fetchone()
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


def active_text(con) -> str:
    """What every agent reads: the active rules in his words (empty when there are none)."""
    rs = active(con)
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
