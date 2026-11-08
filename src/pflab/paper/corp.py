"""Corporate actions on the system's OWN book (S79b item 18E; found missing by the verification harness `paper/verify_book.py`).

Until now nothing applied a split, a bonus or a dividend to the system's ledger: the book is marked at RAW closes, so a 1:5 split cut its value by 80% (quantity unchanged) and
no dividend ever reached its cash. `apply_due` is called by `book.catch_up` for each session, before that session's fills, and appends ordinary `corp_action` / `dividend`
events to the ledger (`ledger/corporate_actions.py` is the one code path that changes lots; a replay re-applies them).

What it applies (only for names the book held on the day before the ex-date; only ex-dates after the book's first marked day, because the opening lots are Kite's holdings
as of then and already carry every earlier action):
  split, bonus        from the NSE feed's PURPOSE text (`ca.from_nse_feed`): lots keep their dates, a bonus is a nil-cost lot dated at the ex-date, fractions are paid in cash.
  dividend            quantity held at the ex-date (after that day's split or bonus) x the feed's per-share amount, credited as cash at the ex-date (gross; TDS and slab tax on
                      dividends are not modelled; the payment really arrives weeks later).
  price-drop actions  factors the collector derived from NSE's adjusted PREVCLOSE (demergers, schemes of arrangement): a factor below 1 that is not a standard ratio is a cash credit of
                      the price drop with the cost scaled down (value-neutral, the way the backtest engine treats it); a factor above 1 or a standard ratio is a share-count change.
  ISIN change         `instrument_alias` (old ISIN -> new ISIN from a date): the lots are re-keyed, dates and cost kept, nothing realised. A merger with a ratio is a human-entered
                      `ca.merger` event (the feed carries no ratio); a feed row that says merger or demerger with no price-drop factor is returned in `needs`.
Left alone on purpose (returned in `left`): buy-backs and rights, because the book never tendered or subscribed.
Idempotent: every event carries `ref = corp:<kind>:<isin>:<ex-date>` and an action already in the ledger is never applied twice. A late-arriving action (ex-date before the last
marked day) is applied and the marked days since are re-marked from a replay (`remark`). Switch: `configs/s79b.toml [verify_book] apply_corporate_actions`.
"""
from __future__ import annotations

import dataclasses
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from pflab.ledger import corporate_actions as ca
from pflab.ledger import events as ev
from pflab.ledger import system
from pflab.ledger.book import Ledger

_UNRATIOED = re.compile(r"amalgam|merger|demerger|arrangement|reconstruct|spin", re.I)
_LEFT = re.compile(r"buy ?back|rights", re.I)
_CACHE: dict = {}


def enabled() -> bool:
    from pflab.paper import benchmark
    return bool(benchmark.settings("verify_book").get("apply_corporate_actions", True)) and bool(benchmark.settings("verify_book").get("on", True))


def ref(kind: str, isin: str, ex: date) -> str:
    return f"corp:{kind}:{isin}:{ex}"


# --- the sources (the collectors' own files) ------------------------------------------------------------------------------------------------

def sources(root: Optional[Path] = None) -> dict:
    """{'raw': the NSE feed, 'dividends': (isin, ex_date, dividend_per_share), 'factors': the combined factor table}; cached until a file changes."""
    from pflab.data import data_dir
    from pflab.data import dividends as dv
    from pflab.data import nse_corporate_actions as nca
    root = Path(root or data_dir())
    files = list((root / "corporate_actions" / "raw").glob("*.json")) + [root / "corporate_actions" / "factors.parquet", root / "dividends" / "dividends.parquet"]
    key = (str(root), tuple((f.name, f.stat().st_mtime_ns) for f in files if f.exists()))
    if _CACHE.get("key") == key:
        return _CACHE["val"]
    out = {"raw": pd.DataFrame(columns=["isin", "ex_date", "subject", "series", "symbol", "_sym"]), "dividends": pd.DataFrame(columns=["isin", "ex_date", "dividend_per_share"]),
           "factors": pd.DataFrame(columns=["isin", "ex_date", "factor", "source", "prior_close", "adj_prev_close"])}
    try:
        out["raw"] = nca.load_raw(root)
        out["raw"]["_sym"] = out["raw"]["symbol"].astype(str).str.upper()
    except Exception:
        pass
    parts = []
    try:
        parts.append(dv.load(root))
    except Exception:
        pass
    try:
        if len(out["raw"]):
            parts.append(dv.from_feed(raw=out["raw"]))
    except Exception:
        pass
    parts = [p for p in parts if len(p)]
    if parts:
        d = pd.concat(parts, ignore_index=True)
        d["ex_date"] = pd.to_datetime(d["ex_date"]).dt.date
        out["dividends"] = d.groupby(["isin", "ex_date"], as_index=False)["dividend_per_share"].max()
    try:
        f = nca.load(root)
        f["ex_date"] = pd.to_datetime(f["ex_date"]).dt.date
        out["factors"] = f
    except Exception:
        pass
    _CACHE["key"], _CACHE["val"] = key, out
    return out


# --- what the book holds -------------------------------------------------------------------------------------------------------------------

def held_isins(con) -> set:
    """Every ISIN the system's broker account ever touched (a successor ISIN of a merger or ISIN change too)."""
    a = {r[0] for r in con.execute("SELECT DISTINCT isin FROM events WHERE account_id=? AND isin IS NOT NULL", [system.SYSBROKER]).fetchall()}
    b = {r[0] for r in con.execute("SELECT DISTINCT json_extract_string(params_json, '$.to_isin') FROM events WHERE kind='corp_action' AND account_id IN (?, '*')",
                                   [system.SYSBROKER]).fetchall() if r[0]}
    return a | b


def _qty_before(log: ev.EventLog, isin: str, ex: date, with_actions: bool = False) -> float:
    """Units of `isin` the broker held entering `ex` (with `with_actions`: after that day's corporate actions, before its trades)."""
    keep = [e for e in log.raw() if e.date < ex or (with_actions and e.date == ex and e.kind == "corp_action")]
    return float(Ledger.replay(ev.EventLog(keep)).holdings(isin, system.SYSBROKER))


def _snaps(f: float) -> bool:
    try:
        from pflab.backtest.engine import _snaps_to_standard_ratio
        return bool(_snaps_to_standard_ratio(f))
    except Exception:
        return False


def _exists(con, r: str) -> bool:
    return bool(con.execute("SELECT 1 FROM events WHERE ref=? LIMIT 1", [r]).fetchone())


def stale_isin_map(con, raw: pd.DataFrame, held: set) -> Dict[str, str]:
    """{old ISIN: held ISIN} for feed rows that carry a STALE ISIN. NSE's feed keeps the ISIN a company had before a face-value change (found on the real data: Nestle India's
    2025 bonus is listed under the ISIN that stopped trading in January 2024, while the exchange files and Kite use the new one). A feed ISIN is taken to be a held name's
    when (1) its symbol is the held name's symbol, and (2) the feed ISIN itself no longer trades (no close on or after the row's ex-date). The test is per row in `_restate`."""
    if not len(raw) or not held:
        return {}
    marks = ",".join("?" for _ in held)
    sym = {}
    for isin, symbol in con.execute(f"SELECT isin, upper(symbol) FROM instruments WHERE isin IN ({marks}) AND symbol IS NOT NULL", list(held)).fetchall():
        sym.setdefault(symbol, set()).add(isin)
    sym = {k: next(iter(v)) for k, v in sym.items() if len(v) == 1}
    cand = raw[~raw["isin"].isin(held) & raw["_sym"].isin(sym)]
    c = cand.drop_duplicates(["isin", "_sym"])
    return {i: sym[y] for i, y in zip(c["isin"], c["_sym"])}


def _restate(con, df: pd.DataFrame, amap: Dict[str, str]) -> pd.DataFrame:
    """`df` (isin, ex_date, ...) with a stale ISIN replaced by the held one on the rows that fall after the stale ISIN stopped trading."""
    if not amap or not len(df):
        return df
    df = df.copy()
    for old, new in amap.items():
        m = df["isin"] == old
        if not m.any():
            continue
        last = con.execute("SELECT max(date) FROM prices WHERE isin=?", [old]).fetchone()[0]
        mm = m & (df["ex_date"] > last) if last is not None else m
        df.loc[mm, "isin"] = new
    return df


def restated(con, s: dict, held: Optional[set] = None) -> dict:
    """The sources with stale feed ISINs replaced by the held ISIN (see `stale_isin_map`); 'isin_map' says which."""
    held = held if held is not None else held_isins(con)
    amap = stale_isin_map(con, s["raw"], held)
    return {"raw": _restate(con, s["raw"], amap), "factors": _restate(con, s["factors"], amap), "dividends": _restate(con, s["dividends"], amap), "isin_map": amap}


# --- the plan ---------------------------------------------------------------------------------------------------------------------------

def plan(con, upto: date, root: Optional[Path] = None, src: Optional[dict] = None) -> dict:
    """What is due on the book up to `upto`: {'share': [events], 'cash': [events], 'dividends': [(isin, ex, dps)], 'aliases': [events], 'left': [...], 'needs': [...]}.
    Nothing is written. An action already in the ledger (by ref) is not listed."""
    from pflab.paper import book
    start = book.started(con)
    out: dict = {"share": [], "cash": [], "dividends": [], "aliases": [], "left": [], "needs": []}
    if start is None:
        return out
    lo = start + timedelta(days=1)
    held = held_isins(con)
    s = restated(con, src if src is not None else sources(root), held)
    raw = s["raw"]
    if len(raw):
        r = raw[raw["isin"].isin(held) & (raw["ex_date"] >= lo) & (raw["ex_date"] <= upto)]
        for e in ca.from_nse_feed(r, held, since=lo):
            e = dataclasses.replace(e, ref=ref(e.params["action"], e.isin, e.date))
            if e.date <= upto and not _exists(con, e.ref) and all(e.ref != x.ref for x in out["share"]):
                out["share"].append(e)
        for row in r.itertuples(index=False):
            sub = str(row.subject)
            if _LEFT.search(sub):
                out["left"].append({"isin": row.isin, "symbol": row.symbol, "ex_date": str(row.ex_date), "subject": sub, "why": "the book neither tendered nor subscribed"})
            elif _UNRATIOED.search(sub):
                out["needs"].append({"isin": row.isin, "symbol": row.symbol, "ex_date": str(row.ex_date), "subject": sub, "why": "no ratio in the feed; applied only if a price-drop factor or an ISIN alias exists"})
    fac = s["factors"]
    covered = set()
    if len(fac):
        f = fac[fac["isin"].isin(held) & (fac["ex_date"] >= lo) & (fac["ex_date"] <= upto) & (fac["source"].fillna("purpose") == "prevclose")]
        for row in f.itertuples(index=False):
            fct = float(row.factor)
            covered.add((row.isin, row.ex_date))
            if fct > 1.0 or _snaps(fct):
                e = dataclasses.replace(ca.split(row.isin, row.ex_date, fct, source_doc_sha="nse_corporate_actions:prevclose"), ref=ref("split", row.isin, row.ex_date))
                if not _exists(con, e.ref) and not any(e.ref == x.ref for x in out["share"]):
                    out["share"].append(e)
                continue
            per = float(row.prior_close) - float(row.adj_prev_close) if pd.notna(row.prior_close) and pd.notna(row.adj_prev_close) else 0.0
            if per <= 0 or not 0 < fct <= 1:
                out["needs"].append({"isin": row.isin, "ex_date": str(row.ex_date), "why": "a price-drop factor without a usable price pair"})
                continue
            e = dataclasses.replace(ca.cash_credit(row.isin, row.ex_date, fct, per, source_doc_sha="nse_corporate_actions:prevclose"), ref=ref("cash_credit", row.isin, row.ex_date))
            if not _exists(con, e.ref):
                out["cash"].append(e)
    dv = s["dividends"]
    if len(dv):
        d = dv[dv["isin"].isin(held) & (dv["ex_date"] >= lo) & (dv["ex_date"] <= upto)]
        for row in d.itertuples(index=False):
            if (row.isin, row.ex_date) not in covered and not _exists(con, ref("dividend", row.isin, row.ex_date)):
                out["dividends"].append((row.isin, row.ex_date, float(row.dividend_per_share)))
    try:
        al = con.execute("SELECT alias, isin, since FROM instrument_alias WHERE since > ? AND since <= ?", [start, upto]).fetchall()
    except Exception:
        al = []
    for old, new, since in al:
        if old in held and old != new and not str(old).startswith(system.FOREIGN_PREFIXES):
            e = dataclasses.replace(ca.isin_change(old, since, new, source_doc_sha="instrument_alias"), ref=ref("isin_change", old, since))
            if not _exists(con, e.ref):
                out["aliases"].append(e)
    return out


# --- applying ---------------------------------------------------------------------------------------------------------------------------

def apply_due(con, upto: date, now: datetime, root: Optional[Path] = None, src: Optional[dict] = None) -> dict:
    """Append what is due to the ledger, oldest ex-date first. Returns {'applied': [...], 'dividends_rupees', 'left', 'needs', 'remarked'}."""
    if not system.active():
        return {"skipped": "not the system's own account"}
    if not enabled():
        return {"off": True}
    p = plan(con, upto, root, src)
    applied, divs, remark_from = [], 0.0, None
    last_marked = con.execute("SELECT max(day) FROM paper_days").fetchone()[0]
    todo = sorted(p["aliases"] + p["share"] + p["cash"], key=lambda e: (e.date, 0 if e.params["action"] == "isin_change" else 1))
    for e in todo:
        qty = _qty_before(ev.load(con), e.isin, e.date)
        if qty <= 1e-9:
            continue
        led = system.append(con, [e], now)
        applied.append({"kind": e.params["action"], "isin": e.isin, "ex_date": str(e.date), "ref": e.ref, "qty_before": round(qty, 6)})
        if e.params["action"] in ("split", "bonus"):
            fr = [f for f in led.lots.fractions if f.account_id == system.SYSBROKER and f.isin == e.isin]
            if fr:
                from pflab.paper import book
                px = book.close_on(con, e.isin, e.date)
                proceeds = round(sum(f.units for f in fr) * (px[1] if px else 0.0), 2)
                lieu = dataclasses.replace(ca.cash_in_lieu(system.SYSBROKER, e.isin, e.date, proceeds), ref=ref("cash_in_lieu", e.isin, e.date))
                if not _exists(con, lieu.ref):
                    system.append(con, [lieu], now)
                    applied.append({"kind": "cash_in_lieu", "isin": e.isin, "ex_date": str(e.date), "ref": lieu.ref, "rupees": proceeds})
        if last_marked is not None and e.date <= last_marked:
            remark_from = e.date if remark_from is None else min(remark_from, e.date)
    for isin, ex, dps in sorted(p["dividends"], key=lambda x: (x[1], x[0])):
        qty = _qty_before(ev.load(con), isin, ex, with_actions=True)
        if qty <= 1e-9 or dps <= 0:
            continue
        gross = round(qty * dps, 2)
        e = ev.Event(kind="dividend", account_id=system.SYSBROKER, date=ex, isin=isin, amount=gross, ref=ref("dividend", isin, ex), source_doc_sha="nse_corporate_actions",
                     params={"per_share": dps, "qty": qty, "note": "gross, credited at the ex-date; TDS and slab tax on dividends are not modelled"})
        system.append(con, [e], now)
        divs += gross
        applied.append({"kind": "dividend", "isin": isin, "ex_date": str(ex), "ref": e.ref, "rupees": gross, "qty": round(qty, 6), "per_share": dps})
        if last_marked is not None and ex <= last_marked:
            remark_from = ex if remark_from is None else min(remark_from, ex)
    out = {"applied": applied, "dividends_rupees": round(divs, 2), "left": p["left"], "needs": p["needs"]}
    if remark_from is not None:
        out["remarked"] = remark(con, remark_from)
    return out


def remark(con, from_day: date) -> int:
    """Re-mark the days since `from_day` from a replay of the ledger (an action reached the book after the days it concerns were marked). Flows are kept."""
    import json
    from pflab.paper import book
    log = ev.load(con)
    n = 0
    for (d,) in con.execute("SELECT day FROM paper_days WHERE day >= ? ORDER BY day", [from_day]).fetchall():
        led = Ledger.replay(log, upto=d)
        q = {isin: float(x) for (acc, isin), x in led.positions().items() if acc == system.SYSBROKER and x > 1e-9}
        invested = 0.0
        for isin, x in q.items():
            px = book.close_on(con, isin, d)
            invested += x * px[1] if px else 0.0
        cash, bank = float(led.cash_balance(system.SYSBROKER)), float(led.cash_balance(system.SYSBANK))
        con.execute("UPDATE paper_days SET value=?, cash=?, invested=?, holdings_json=? WHERE day=?",
                    [invested + cash + bank, cash, invested, json.dumps({k: round(v, 6) for k, v in sorted(q.items())}, sort_keys=True), d])
        n += 1
    return n
