"""The system's OWN benchmark (S79b item 18B, the investor's words 2026-11-08): a benchmark that matches the system's own allocation (equity / gold / international / cash),
re-weighted when its allocation changes, recorded point-in-time.

Weights   the ACTIVE allocation target of `paper/allocation.py` (the one whose `activated_at` day is before the session); before any target exists, the Kite-seed weights
          (the book's own class weights on its first marked day), labelled `kite_seed`. Between two targets the benchmark drifts with the markets (buy and hold) and is
          set back to the new target's weights on the first session after the change.
Classes   equity: Nifty 500 total-return index. Gold: COMEX gold in USD x USDINR (a rupee gold ETF also pays duty and a premium; not in the proxy). International: the US
          index in `intl_series` (a price index, no dividends) x USDINR. Cash: the annual cash-rate estimate of `data/riskfree` (index-futures carry, the median of the last
          three month-ends), accrued by calendar day, `cash_assumed_rate` when it is unreadable. Every label is returned with the numbers.
Record    `blended_benchmark_s79` (market, as_of, weights_json {start, end, source, target_weights}, level 100 on the first marked day, the day's class returns). Incremental:
          a stored day is never rewritten (a class series that is stale carries its last level, so the catch-up lands on the day its data arrives); `rebuild=True` rewrites.
Switch    `configs/s79b.toml [benchmark] on`. Off: nothing is written and `status` says {"off": true}.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

CLASSES = ("equity", "gold", "international", "cash")
CONFIG = Path(__file__).resolve().parents[3] / "configs" / "s79b.toml"
DEFAULTS = {"on": True, "equity_series": "NIFTY500_TRI", "gold_series": "GOLD", "intl_series": "US_NASDAQ", "cash_assumed_rate": 0.065, "min_sessions": 2}
STALE_DAYS = 5
LABELS = {
    "equity": "Nifty 500 total return index",
    "gold": "COMEX gold (USD) x USDINR: gold in rupees, without a rupee ETF's duty and premium",
    "international": "US index (price, no dividends) x USDINR: international in rupees",
    "cash": "cash-rate estimate from index-futures carry (data/riskfree), a liquid-fund proxy; the assumed rate when unreadable",
}


def settings(table: str = "benchmark") -> dict:
    out = dict(DEFAULTS) if table == "benchmark" else {"on": True, "apply_corporate_actions": True}
    try:
        from pflab import _toml
        out.update(_toml.load(CONFIG).get(table, {}))
    except Exception:
        pass
    return out


def on() -> bool:
    return bool(settings()["on"])


# --- the class series ---------------------------------------------------------------------------------------------------------------

def _load(kind: str, key: str, root: Optional[Path]) -> Optional[pd.Series]:
    from pflab.data import data_dir
    p = Path(root or data_dir()) / kind / f"{key}.parquet"
    if not p.exists():
        return None
    d = pd.read_parquet(p)
    col = "close" if "close" in d.columns else "value"
    s = pd.Series(d[col].astype(float).to_numpy(), index=pd.to_datetime(d["date"]).dt.normalize()).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s[s > 0]


def _best(key: str, root: Optional[Path]) -> Optional[pd.Series]:
    """The series called `key` in data/global or data/macro, whichever runs to the later date."""
    a, b = _load("global", key, root), _load("macro", key, root)
    if a is None or b is None:
        return a if a is not None else b
    return b if b.index.max() > a.index.max() else a


def _inr(usd: Optional[pd.Series], fx: Optional[pd.Series]) -> Optional[pd.Series]:
    if usd is None or fx is None:
        return None
    j = pd.concat([usd.rename("u"), fx.rename("fx")], axis=1).sort_index().ffill().dropna()
    j = j[j.index >= usd.index.min()]
    s = (j["u"] * j["fx"])
    return s[s.index <= max(usd.index.max(), fx.index.max())]


def class_levels(root: Optional[Path] = None, cfg: Optional[dict] = None) -> dict:
    """{'equity'|'gold'|'international': Series (rupee levels), 'cash_rate': fn(date) -> annual rate, 'through': {class: date}, 'labels': {...}}."""
    cfg = cfg or settings()
    fx = _load("macro", "USDINR", root)
    lv = {"equity": _load("indices", str(cfg["equity_series"]), root), "gold": _inr(_best(str(cfg["gold_series"]), root), fx),
          "international": _inr(_best(str(cfg["intl_series"]), root), fx)}
    assumed = float(cfg["cash_assumed_rate"])
    rate: Callable[[date], float] = lambda d: assumed
    try:
        from pflab.data import riskfree
        tbl = riskfree.monthly_table(root)
        if len(tbl):
            rate = lambda d: float(riskfree.at(tbl, d)[0])
    except Exception:
        pass
    return {**lv, "cash_rate": rate, "through": {c: (s.index.max().date() if s is not None and len(s) else None) for c, s in lv.items()}, "labels": dict(LABELS)}


def class_returns(levels: dict, d0: date, d1: date) -> Dict[str, float]:
    out = {}
    for c in ("equity", "gold", "international"):
        s = levels.get(c)
        if s is None or not len(s):
            out[c] = 0.0
            continue
        a0, a1 = s.asof(pd.Timestamp(d0)), s.asof(pd.Timestamp(d1))
        out[c] = float(a1 / a0 - 1.0) if pd.notna(a0) and pd.notna(a1) and a0 > 0 else 0.0
    rate = float(levels["cash_rate"](d0))
    out["cash"] = (1.0 + rate) ** (max((d1 - d0).days, 0) / 365.0) - 1.0
    return out


# --- the book's classes ---------------------------------------------------------------------------------------------------------------

def _class_of_isin(con, isin: str, cache: dict) -> str:
    if isin not in cache:
        from pflab.paper import allocation, book
        m = book.inst(con, isin)
        cache[isin] = allocation.class_of(m["asset_class"], m["name"], m["symbol"], isin)
    return cache[isin]


def _price(con, isin: str, day: date, cache: dict) -> Optional[float]:
    k = (isin, day)
    if k not in cache:
        from pflab.paper import book
        r = book.close_on(con, isin, day)
        cache[k] = r[1] if r else None
    return cache[k]


def _day_row(con, day: date) -> Optional[tuple]:
    r = con.execute("SELECT value, flows, holdings_json FROM paper_days WHERE day=?", [day]).fetchone()
    return (float(r[0]), float(r[1]), json.loads(r[2] or "{}")) if r else None


def book_weights(con, day: date, caches: Optional[dict] = None) -> Dict[str, float]:
    """The book's class weights (fractions, summing to 1) at the close of `day`; what no holding explains (cash, the fake bank) is `cash`."""
    ck = caches or {"cls": {}, "px": {}}
    row = _day_row(con, day)
    if not row or row[0] <= 0:
        return {c: (1.0 if c == "cash" else 0.0) for c in CLASSES}
    v, _, q = row
    vals = {c: 0.0 for c in CLASSES}
    for isin, qty in q.items():
        p = _price(con, isin, day, ck["px"])
        if p:
            vals[_class_of_isin(con, isin, ck["cls"])] += qty * p
    vals["cash"] = max(0.0, v - sum(vals[c] for c in CLASSES if c != "cash"))
    tot = sum(vals.values())
    return {c: vals[c] / tot for c in CLASSES}


# --- the weights history ---------------------------------------------------------------------------------------------------------------

def targets_history(con, market: str = "IN") -> List[dict]:
    """Every target that was ever active, oldest first: (effective day, id, weights as fractions). Point-in-time: a target counts from the day after its activation."""
    try:
        rows = con.execute("SELECT target_id, activated_at, classes_json FROM system_allocation_s79 WHERE market=? AND activated_at IS NOT NULL ORDER BY activated_at, target_id", [market]).fetchall()
    except Exception:
        return []
    out = []
    for tid, at, cj in rows:
        w = {c: float((json.loads(cj or "{}")).get(c, 0.0)) for c in CLASSES}
        tot = sum(w.values())
        if tot > 0:
            out.append({"target_id": int(tid), "effective": at.date() if hasattr(at, "date") else at, "weights": {c: w[c] / tot for c in CLASSES}})
    return out


def target_for(hist: List[dict], day: date) -> Optional[dict]:
    """The target in force for the session `day`: the latest one activated on a day before it."""
    cur = None
    for t in hist:
        if t["effective"] < day:
            cur = t
    return cur


def _state(con, market: str) -> Optional[dict]:
    r = con.execute("SELECT as_of, weights_json, level, target_id FROM blended_benchmark_s79 WHERE market=? ORDER BY as_of DESC LIMIT 1", [market]).fetchone()
    if not r:
        return None
    w = json.loads(r[1])
    return {"as_of": r[0], "w_end": w["end"], "level": float(r[2]), "target_id": r[3], "source": w.get("source")}


def update(con, market: str = "IN", upto: Optional[date] = None, now: Optional[datetime] = None, levels: Optional[dict] = None, rebuild: bool = False,
           root: Optional[Path] = None) -> dict:
    """Extend the recorded benchmark to every marked day of the book up to `upto`. Returns {'added', 'last', 'level'} (idempotent)."""
    if not on():
        return {"off": True}
    now = now or datetime.now()
    days = [r[0] for r in con.execute("SELECT day FROM paper_days WHERE day <= ? ORDER BY day", [upto or date.max]).fetchall()]
    if not days:
        return {"started": False, "added": 0}
    if rebuild:
        con.execute("DELETE FROM blended_benchmark_s79 WHERE market=?", [market])
    st = _state(con, market)
    hist = targets_history(con, market)
    lv = levels or class_levels(root)
    caches = {"cls": {}, "px": {}}
    added, rows = 0, []
    if st is None:
        t = target_for(hist, days[0])
        w0 = dict(t["weights"]) if t else book_weights(con, days[0], caches)
        src = f"target #{t['target_id']}" if t else "kite_seed"
        st = {"as_of": days[0], "w_end": w0, "level": 100.0, "target_id": t["target_id"] if t else None, "source": src}
        rows.append((days[0], {"start": w0, "end": w0, "source": src, "target_weights": t["weights"] if t else None}, 100.0, None, {}, st["target_id"], True))
    for d1 in [d for d in days if d > st["as_of"]]:
        d0 = st["as_of"]
        t = target_for(hist, d1)
        rebal = bool(t and t["target_id"] != st["target_id"])
        w = dict(t["weights"]) if rebal else dict(st["w_end"])
        if rebal:
            st["target_id"] = t["target_id"]
        src = f"target #{st['target_id']}" if st["target_id"] is not None else "kite_seed"
        rc = class_returns(lv, d0, d1)
        rb = sum(w[c] * rc[c] for c in CLASSES)
        level = st["level"] * (1.0 + rb)
        w_end = {c: w[c] * (1.0 + rc[c]) / (1.0 + rb) for c in CLASSES}
        stale = sorted(c for c, th in (lv.get("through") or {}).items() if th is None or th < d1 - timedelta(days=STALE_DAYS))
        rows.append((d1, {"start": w, "end": w_end, "source": src, "target_weights": t["weights"] if t else None}, level, rb, {**rc, "stale": stale}, st["target_id"], rebal))
        st.update({"as_of": d1, "w_end": w_end, "level": level, "source": src})
    for d, wj, level, rb, rcj, tid, rebal in rows:
        con.execute("INSERT OR REPLACE INTO blended_benchmark_s79 VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [market, d, json.dumps(wj, sort_keys=True), float(level), rb, json.dumps(rcj, sort_keys=True), wj["source"], tid, bool(rebal), now])
        added += 1
    return {"added": added, "last": str(st["as_of"]), "level": round(st["level"], 4), "source": st["source"]}


def _bench_rows(con, market: str) -> Dict[date, dict]:
    out = {}
    for d, wj, lvl, rb, rcj, tid in con.execute("SELECT as_of, weights_json, level, day_return, class_ret_json, target_id FROM blended_benchmark_s79 WHERE market=? ORDER BY as_of", [market]).fetchall():
        out[d] = {"w": json.loads(wj), "level": float(lvl), "ret": rb, "rc": json.loads(rcj or "{}"), "target_id": tid}
    return out


# --- the monthly attribution -----------------------------------------------------------------------------------------------------------

def _trades_on(con, day: date) -> List[tuple]:
    return con.execute("SELECT isin, side, qty, price, charges, tax FROM paper_trades WHERE day=?", [day]).fetchall()


def _income_on(con, day: date) -> Dict[str, float]:
    try:
        from pflab.ledger import system
        if not system.active():
            return {}
        return {r[0]: float(r[1]) for r in con.execute(
            "SELECT ref, sum(amount) FROM cash_ledger WHERE account_id=? AND date=? AND kind IN ('dividend','corp_action','interest') GROUP BY ref", [system.SYSBROKER, day]).fetchall()}
    except Exception:
        return {}


def day_parts(con, d0: date, d1: date, bench: dict, caches: dict) -> Optional[dict]:
    """The book's day d0 -> d1 against the benchmark, in fractions of the book's value at d0. Parts: allocation, selection (Brinson-Fachler by class), costs (charges and
    slippage), tax (estimate), and `resid` (what the accounts leave unexplained, e.g. interest). allocation + selection - costs - tax + resid = book - benchmark, exactly."""
    a, b = _day_row(con, d0), _day_row(con, d1)
    if not a or not b or a[0] <= 0:
        return None
    v0, (v1, flow1, q1), q0 = a[0], (b[0], b[1], b[2]), a[2]
    ck = caches
    wp = book_weights(con, d0, ck)
    wb, rc = bench["w"]["start"], {c: float(bench["rc"].get(c, 0.0)) for c in CLASSES}
    rb = float(bench["ret"] or 0.0)
    trades = _trades_on(con, d1)
    income = _income_on(con, d1)
    flows_close = {}
    slip = charges = tax = 0.0
    for isin, side, qty, px, ch, tx in trades:
        cl = _price(con, isin, d1, ck["px"]) or float(px)
        sgn = 1.0 if side == "buy" else -1.0
        flows_close[isin] = flows_close.get(isin, 0.0) + sgn * qty * cl
        slip += sgn * qty * (float(px) - cl)
        charges += float(ch or 0.0)
        tax += float(tx or 0.0)
    pnl = {c: 0.0 for c in CLASSES}
    for isin in set(q0) | set(q1) | set(flows_close) | set(income):
        p0, p1 = _price(con, isin, d0, ck["px"]), _price(con, isin, d1, ck["px"])
        x0 = q0.get(isin, 0.0) * (p0 or 0.0)
        x1 = q1.get(isin, 0.0) * (p1 or 0.0)
        pnl[_class_of_isin(con, isin, ck["cls"])] += x1 - x0 - flows_close.get(isin, 0.0) + income.get(isin, 0.0)
    r_net = (v1 - flow1) / v0 - 1.0
    contrib = {c: pnl[c] / v0 for c in CLASSES}
    alloc = {c: (wp[c] - wb[c]) * (rc[c] - rb) for c in CLASSES}
    sel = {c: contrib[c] - wp[c] * rc[c] for c in CLASSES}
    costs, tx_r = (charges + slip) / v0, tax / v0
    resid = (r_net - rb) - (sum(alloc.values()) + sum(sel.values()) - costs - tx_r)
    return {"r_net": r_net, "r_bench": rb, "wp": wp, "wb": wb, "rc": rc, "alloc": alloc, "sel": sel, "contrib": contrib, "costs": costs, "tax": tx_r, "resid": resid}


def attribute(con, market: str = "IN", now: Optional[datetime] = None) -> dict:
    """Month by month (calendar months of the book's marked days): the book's result against the benchmark, split into allocation (class weights against the benchmark's,
    held at the month's first weights), selection (what the book's holdings in a class did against the class index), timing (the weights moving inside the month, trades
    and drift), costs (charges and slippage), tax (the estimate on the sales) and an explicit residual (untracked cash effects and the compounding between daily and
    monthly returns). Parts and residual add to the excess exactly; each is in points of the month's opening value. Stored in `attribution_s79`; idempotent."""
    if not on():
        return {"off": True}
    now = now or datetime.now()
    bench = _bench_rows(con, market)
    days = [d for (d,) in con.execute("SELECT day FROM paper_days ORDER BY day").fetchall() if d in bench]
    if len(days) < int(settings()["min_sessions"]):
        return {"months": [], "note": "fewer than two marked days"}
    caches = {"cls": {}, "px": {}}
    months: Dict[date, dict] = {}
    for d0, d1 in zip(days, days[1:]):
        p = day_parts(con, d0, d1, bench[d1], caches)
        if p is None:
            continue
        key = date(d1.year, d1.month, 1)
        m = months.setdefault(key, {"gp": 1.0, "gb": 1.0, "first": p, "start": d0, "end": d1, "n": 0, "alloc": 0.0, "sel": 0.0, "timing": 0.0, "costs": 0.0, "tax": 0.0, "untracked": 0.0,
                                    "by": {c: {"alloc": 0.0, "sel": 0.0, "timing": 0.0, "wp": 0.0, "wb": 0.0, "gb": 1.0} for c in CLASSES}})
        g = m["gp"]
        f = m["first"]
        for c in CLASSES:
            static = (f["wp"][c] - f["wb"][c]) * (p["rc"][c] - p["r_bench"])
            tim = p["alloc"][c] - static
            m["alloc"] += g * static
            m["timing"] += g * tim
            m["sel"] += g * p["sel"][c]
            b = m["by"][c]
            b["alloc"] += g * static
            b["timing"] += g * tim
            b["sel"] += g * p["sel"][c]
            b["wp"] += p["wp"][c]
            b["wb"] += p["wb"][c]
            b["gb"] *= 1.0 + p["rc"][c]
        m["costs"] -= g * p["costs"]
        m["tax"] -= g * p["tax"]
        m["untracked"] += g * p["resid"]
        m["gp"] *= 1.0 + p["r_net"]
        m["gb"] *= 1.0 + p["r_bench"]
        m["end"], m["n"] = d1, m["n"] + 1
    out = []
    for key in sorted(months):
        m = months[key]
        book_r, bench_r = m["gp"] - 1.0, m["gb"] - 1.0
        excess = book_r - bench_r
        resid = excess - (m["alloc"] + m["sel"] + m["timing"] + m["costs"] + m["tax"])
        nxt = date(key.year + (key.month == 12), key.month % 12 + 1, 1)
        partial = not any(d >= nxt for d in days)
        detail = {"by_class": {c: {"allocation": round(b["alloc"], 6), "selection": round(b["sel"], 6), "timing": round(b["timing"], 6), "avg_book_weight": round(b["wp"] / max(m["n"], 1), 4),
                                    "avg_bench_weight": round(b["wb"] / max(m["n"], 1), 4), "bench_return": round(b["gb"] - 1.0, 6)} for c, b in m["by"].items()},
                  "untracked": round(m["untracked"], 8), "compounding": round(resid - m["untracked"], 8), "partial": partial,
                  "labels": {"costs": "charges and slippage on the month's fills (code, from the fills)", "tax": "estimate: FIFO lots at the sale, cess and surcharge not added",
                             "residual": "untracked cash effects plus the compounding between daily and monthly returns"}}
        row = {"market": market, "month": str(key), "period_start": str(m["start"]), "period_end": str(m["end"]), "sessions": m["n"], "book_return": book_r, "bench_return": bench_r,
               "excess": excess, "allocation": m["alloc"], "selection": m["sel"], "timing": m["timing"], "costs": m["costs"], "tax": m["tax"], "residual": resid, "partial": partial,
               "detail": detail}
        con.execute("INSERT OR REPLACE INTO attribution_s79 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [market, key, m["start"], m["end"], m["n"], book_r, bench_r, excess, m["alloc"], m["sel"], m["timing"], m["costs"], m["tax"], resid, json.dumps(detail, sort_keys=True), now])
        out.append(row)
    return {"months": out}


# --- what the tool, the panel and the dossier read ----------------------------------------------------------------------------------------

def refresh(con, market: str = "IN", upto: Optional[date] = None, now: Optional[datetime] = None, levels: Optional[dict] = None, root: Optional[Path] = None) -> dict:
    """The job's body: extend the benchmark, then recompute the attribution."""
    if not on():
        return {"off": True}
    u = update(con, market, upto, now, levels, root=root)
    if u.get("started") is False:
        return {"waiting": "the book has no marked day yet"}
    a = attribute(con, market, now)
    return {"benchmark": u, "months": len(a.get("months", []))}


def _stored_months(con, market: str, limit: int = 12) -> List[dict]:
    keys = ("month", "period_start", "period_end", "sessions", "book_return", "bench_return", "excess", "allocation", "selection", "timing", "costs", "tax", "residual", "detail_json")
    out = []
    for r in con.execute(f"SELECT {', '.join(keys)} FROM attribution_s79 WHERE market=? ORDER BY month DESC LIMIT {int(limit)}", [market]).fetchall():
        d = dict(zip(keys, r))
        det = json.loads(d.pop("detail_json") or "{}")
        d.update({"month": str(d["month"]), "period_start": str(d["period_start"]), "period_end": str(d["period_end"]), "partial": bool(det.get("partial")), "by_class": det.get("by_class", {})})
        out.append(d)
    return out[::-1]


def status(con, market: str = "IN", day: Optional[date] = None) -> dict:
    """The book against its own benchmark since the start, the weights in force, the monthly attribution (stored). Keys are documented in the `benchmark` tool."""
    if not on():
        return {"off": True}
    rows = con.execute("SELECT as_of, level, weights_json, source, target_id FROM blended_benchmark_s79 WHERE market=? ORDER BY as_of", [market]).fetchall()
    if not rows:
        return {"started": False, "market": market, "note": "the benchmark is recorded once the book has a marked day (the benchmark job)"}
    from pflab.paper import cadence
    path = cadence.level_path(con)
    last = rows[-1]
    if day is not None:
        rows = [r for r in rows if r[0] <= day] or rows[:1]
        last = rows[-1]
    book_lv = {d: g for d, g in path}
    d_last = last[0]
    book_ret = (book_lv.get(d_last, 1.0) / book_lv[rows[0][0]] - 1.0) if rows[0][0] in book_lv else None
    bench_ret = float(last[1]) / float(rows[0][1]) - 1.0
    w = json.loads(last[2])
    cur = _stored_months(con, market, 12)
    peak, worst = 1.0, 0.0
    for d, g in path:
        if d <= d_last:
            peak = max(peak, g)
            worst = min(worst, g / peak - 1.0)
    rcj = con.execute("SELECT class_ret_json FROM blended_benchmark_s79 WHERE market=? AND as_of=?", [market, d_last]).fetchone()
    stale = (json.loads(rcj[0] or "{}").get("stale") or []) if rcj else []
    res = {"market": market, "started": True, "since": str(rows[0][0]), "as_of": str(d_last), "sessions": len(rows) - 1,
            "book": {"return": book_ret, "level": book_lv.get(d_last)}, "benchmark": {"return": bench_ret, "level": float(last[1]), "weights_start_of_day": w["start"],
                                                                                 "weights_now": w["end"], "source": last[3], "target_id": last[4], "labels": dict(LABELS)},
            "excess": None if book_ret is None else book_ret - bench_ret, "monthly": cur, "latest_month": cur[-1] if cur else None, "stale_classes": stale,
            "worst_fall_book": worst,
            "notes": ["returns are time-weighted with top-ups taken out (outside money is not a gain)", "tax is an estimate (FIFO lots, cess and surcharge not added)",
                      "residual = untracked cash effects + the compounding between daily and monthly returns"]}
    if market == "IN":                                   # S82 (A57): the whole book is the rupee book plus the US sub-book in rupees; its own value and return, not recomputed here
        try:
            from pflab.us import wholebook
            res["whole_book"] = {**wholebook.whole_book_inr(con, day or d_last), "return": wholebook.returns(con)}
            if (res["whole_book"]["return"] or {}).get("twr") is not None:
                res["whole_book"]["excess"] = res["whole_book"]["return"]["twr"] - bench_ret       # the whole book against the same benchmark
        except Exception as e:
            res["whole_book"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    return res


def dossier_text(con, day: Optional[date] = None, market: str = "IN") -> str:
    """One block for the weekly review: the result against its own benchmark and last month's split. Empty when there is nothing recorded."""
    try:
        s = status(con, market, day)
    except Exception:
        return ""
    if not s.get("started") or s.get("book", {}).get("return") is None:
        return ""
    lm = s.get("latest_month")
    bit = ""
    if lm:
        bit = (f" Month {lm['month'][:7]}{' (so far)' if lm['partial'] else ''}: book {lm['book_return']:+.2%} vs benchmark {lm['bench_return']:+.2%}; allocation {lm['allocation']:+.2%}, "
               f"selection {lm['selection']:+.2%}, timing {lm['timing']:+.2%}, costs {lm['costs']:+.2%}, tax (estimate) {lm['tax']:+.2%}, residual {lm['residual']:+.2%}.")
    return (f"RESULT VS ITS OWN BENCHMARK (the blend of its allocation target: {s['benchmark']['source']}): since {s['since']} the book {s['book']['return']:+.2%} vs the benchmark "
            f"{s['benchmark']['return']:+.2%} (excess {s['excess']:+.2%}).{bit} Read it for what the allocation and the selection each added or cost.")
