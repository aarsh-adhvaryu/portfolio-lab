"""Every balance traced to its source (2026-10-31): for each bank account, Zerodha's cash, each demat's holdings and each bank's deposits, what the
record holds, what the source says, the file it came from and the date it runs to, and whether it is a fact or an estimate. The open differences
close the list. Read-only; the same facts the net worth uses (`calc.networth`), so the two can never disagree.
"""
from __future__ import annotations

from datetime import date
from typing import List


def _files(con) -> dict:
    """statement_periods.file_sha (16 hex) -> the name of the file he dropped."""
    return {sha[:16]: name for sha, name in con.execute("SELECT sha, name FROM inbox_items WHERE status <> 'removed'").fetchall()}


def build(con, asof: date) -> List[dict]:
    from pflab.calc import networth
    n = networth.build(con, asof)
    names = _files(con)
    per = {}
    for acc, kind, sha, first, last in con.execute("SELECT account_id, kind, file_sha, first_date, last_date FROM statement_periods "
                                                   "WHERE account_id <> '*' ORDER BY last_date").fetchall():
        per.setdefault(acc, []).append({"kind": kind, "file": names.get(str(sha or "")[:16], "a file no longer in the inbox"), "from": first, "to": last})
    rows = []
    v = n["valuation"]
    for c in v.cash.itertuples():
        src = per.get(c.account, [])
        last = max((p["to"] for p in src if p["to"]), default=None)
        rows.append({"what": "cash", "account": c.account, "value": float(c.balance), "basis": "fact" if src else "no statement",
                     "as_of": str(last) if last else None, "sources": sorted({p["file"] for p in src})})
    pos = n["positions"]
    for acc, g in pos.groupby("account"):
        src = [p for p in per.get(acc, []) if p["kind"] in ("cas", "tradebook")]
        last = max((p["to"] for p in src if p["to"]), default=None)
        rows.append({"what": "holdings", "account": acc, "value": float(g["value"].dropna().sum()), "basis": "units: fact; prices: market",
                     "as_of": str(last) if last else None, "n": int(len(g)), "unpriced": int(g["value"].isna().sum()),
                     "sources": sorted({p["file"] for p in src})})
    f = n["fds"]
    src_of = {fid: s for fid, s in con.execute("SELECT fd_id, source FROM fds").fetchall()}
    for bank, g in (f.groupby("bank") if len(f) else []):
        rows.append({"what": "deposits", "account": bank, "value": float(g["value"].sum()), "n": int(len(g)),
                     "basis": "estimate" if g["estimate"].any() else "fact", "as_of": str(min(g["as_of"])) if g["as_of"].notna().any() else None,
                     "method": sorted(set(g["method"])), "sources": sorted({src_of.get(i, "?") for i in g["fd_id"]})})
    for x in n.get("fd_excluded") or []:
        rows.append({"what": "deposit left out", "account": x["bank"], "value": None, "basis": x["why"], "as_of": str(x["maturity"]), "sources": []})
    for k, d in con.execute("SELECT gap_key, detail FROM known_gaps WHERE status='open' AND source IN ('ledger', 'deposits')").fetchall():
        rows.append({"what": "difference", "account": k.split(":")[-1], "value": None, "basis": d, "as_of": None, "sources": []})
    rows.append({"what": "net worth", "account": "all", "value": float(n["net_worth"]), "basis": "estimate" if n["fd_estimated"] else "fact",
                 "as_of": str(asof), "sources": []})
    return rows


def render(rows: List[dict]) -> str:
    out = []
    for r in rows:
        val = f"Rs {r['value']:,.2f}" if r.get("value") is not None else ""
        extra = (f", {r['n']} item(s)" if r.get("n") else "") + (f", {r['unpriced']} unpriced" if r.get("unpriced") else "")
        out.append(f"{r['what']:<17} {str(r['account'])[:30]:<30} {val:>20}  [{r['basis']}{extra}]" + (f" to {r['as_of']}" if r.get("as_of") else ""))
        for s in r.get("sources") or []:
            out.append(f"{'':<17}   from: {s}")
        for m in r.get("method") or []:
            out.append(f"{'':<17}   method: {m}")
    return "\n".join(out)
