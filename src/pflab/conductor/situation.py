"""The fact sheet (S53): what the system believes now, each fact with its date and its source.

The local model reads this short sheet instead of a long history, so a small context window is enough and nothing it
says can be older than the sheet admits. Every value comes from code (a store query, a job's recorded output, a tool);
none from a model. Written each conductor pass to PFLAB_PM_DIR/reports/situation.json (for code) and situation.md
(for the investor and Obsidian).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from pflab.conductor.calendar import Calendar, describe_closed
from pflab.conductor.sync import Finding

Sheet = Dict[str, Dict[str, object]]


def _fact(value, as_of, source: str) -> Dict[str, object]:
    return {"value": value, "as_of": as_of, "source": source}


def _last_ok(con, job: str):
    return con.execute("SELECT started_at, detail FROM job_runs WHERE job=? AND status='ok' ORDER BY started_at DESC "
                       "LIMIT 1", [job]).fetchone()


def build(con, now: datetime, cal: Calendar, findings: List[Finding], networth_fn=None) -> Sheet:
    s: Sheet = {}
    d = now.date()
    s["market.mode"] = _fact(cal.mode(now), now, "configs/market_holidays.toml + clock")
    nxt = cal.next_trading_day(d) if cal.mode(now) in ("closed", "after_close") else d
    s["market.next_session"] = _fact(nxt, now, "configs/market_holidays.toml")
    shut = cal.closed_after(d) if cal.is_trading_day(d) else []
    if shut:
        s["market.closed_ahead"] = _fact(describe_closed(cal, shut), now, "configs/market_holidays.toml")
    for f in findings:
        if f.name.startswith("data:"):
            s[f.name] = _fact(f.detail, now, f"conductor sync ({f.status})")
    g = _last_ok(con, "guards")
    if g:
        det = json.loads(g[1] or "{}")
        s["market.state"] = _fact(det.get("market_state"), g[0], "guards job (Hawkes market state, S40)")
        s["market.dip_rule_active"] = _fact(det.get("dip_active"), g[0], "guards job (dip rule, S34)")
        s["list.names_not_ok"] = _fact(det.get("not_ok"), g[0], "guards job (safety checks, S35)")
    if networth_fn is not None:
        try:
            nw = networth_fn(con, d)
            px = con.execute("SELECT max(date) FROM prices").fetchone()[0]
            for k in ("net_worth", "investable", "stocks_share_of_investable", "gold_share_of_investable",
                      "debt_share_of_investable", "cash_share_of_investable"):
                if k in nw:
                    s[f"portfolio.{k}"] = _fact(nw[k], px, "ledger + prices (agents.tools.networth)")
        except Exception as e:                       # an empty or half-built ledger: say so, never guess
            s["portfolio"] = _fact(f"not available: {type(e).__name__}", now, "agents.tools.networth")
    qs = con.execute("SELECT q_id, text FROM questions WHERE status='open' ORDER BY q_id").fetchall()
    s["needs_from_investor"] = _fact([f"#{q} {t}" for q, t in qs], now, "questions table")
    bad = [f"{f.name}: {f.detail}" for f in findings if f.status == "warn"]
    s["warnings"] = _fact(bad, now, "conductor sync")
    pend = con.execute("SELECT count(*) FROM outbox WHERE status='pending'").fetchone()[0]
    s["messages.waiting"] = _fact(int(pend), now, "outbox table")
    return s


def _plain(v):
    return v.isoformat(sep=" ", timespec="minutes") if isinstance(v, datetime) else v.isoformat() \
        if isinstance(v, date) else v


def to_json(sheet: Sheet) -> str:
    return json.dumps({k: {kk: _plain(vv) for kk, vv in f.items()} for k, f in sheet.items()}, indent=1, default=str)


def to_markdown(sheet: Sheet, now: datetime) -> str:
    lines = [f"# Situation {now:%d %b %Y %H:%M}", "", "| fact | value | as of | source |", "|---|---|---|---|"]
    for k, f in sheet.items():
        v = f["value"]
        if isinstance(v, list):
            v = "; ".join(map(str, v)) if v else "none"
        lines.append(f"| {k} | {str(_plain(v)).replace('|', '/')} | {_plain(f['as_of'])} | {f['source']} |")
    return "\n".join(lines) + "\n"


def write(sheet: Sheet, reports: Path, now: datetime) -> Path:
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "situation.json").write_text(to_json(sheet), encoding="utf-8")
    p = reports / "situation.md"
    p.write_text(to_markdown(sheet, now), encoding="utf-8")
    return p


def load(reports: Path) -> Optional[dict]:
    p = reports / "situation.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
