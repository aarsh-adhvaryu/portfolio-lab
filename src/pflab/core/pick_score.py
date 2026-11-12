"""The pick scorecard (S83 L4, A61): every pick, every sale and every skipped idea is scored against the index over the same sessions at 1, 3, 6 and 12 months. Code only: no model,
no paid call, nothing reaches a broker.

    what is scored   `picks_s83` (written by the picks agent: the system's own picks and his Kite stocks, from the day proposed), the filled sales of `exit_events_s81` (India) and
                     `us_trades_s81` (US), and `skips_s83`. A missing table means nothing to score. Read defensively.
    the clock        a horizon is scored once it has ELAPSED: `start + h months` has passed and the market's index has a close on or after that date. The start is the first session AFTER the
                     day the pick was proposed (a pick proposed after the close cannot buy at that close). The end is the last close on or before the horizon date. A pick that ended
                     early (withdrawn, stopped, broken) is measured to the day it ended at every later horizon too (so a pick cut early never drops out of the record).
    the index        India: the Nifty 500 total return index (`paper/benchmark.py`, `NIFTY500_TRI`). US: SPY (dividends reinvested, `adj_close`) in rupees, price x USD/INR at the source
                     `us/fx.py` states for each date. Point in time: only closes up to the end date are read.
    after tax        a PICK is valued as if sold on the end date: its gain less sell charges, taxed at the rate of the tax engine's dated row for the holding period (`core/tax_rows.rates`;
                     India short-term 20% to 12 months, long-term 12.5% after; US: the slab rate to 24 months, 12.5% after, `us/tax.py`), buy charges counted in the cost. The yearly
                     long-term exemption is SHARED by all the year's sales, so no exemption is taken per pick (the row's figure is kept in the detail). A loss earns no tax credit here.
                     The INDEX is taxed and charged the same way over the same dates (an index fund is sold too), so `excess_pct` compares like with like; the raw index figure is kept in
                     `index_raw_pct`. A SALE is scored on the shares it sold, as if kept: what they would have netted on the end date after the engine's tax and charges (`exits._score_one`),
                     against the index over the same sessions: a positive excess means the sold shares went on to beat the index (selling cost something). A SKIP is price only.
                     Every after-tax figure is an ESTIMATE (surcharge and cess are not added; a US dividend is counted gross of its 25% withholding).
    the sleeve       `pick_sleeve_daily_s83`: the picks sleeve's day (India: the `longterm` sleeve; US: the sub-book's holdings other than SPY) after estimated tax, time-weighted (buys
                     and sales are flows), against the index taxed the same way from the sleeve's first day, with the worst fall of each so far. `sleeve_record` reads it.

Public: `score_all`, `scorecard`, `scorecard_text`, `sleeve_record`, `update_sleeve_daily`. Every function returns plain JSON-able values.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from dateutil.relativedelta import relativedelta

from pflab.core import tax_rows as tr
from pflab.tax import rules

HORIZONS = (1, 3, 6, 12)
MIN_RATE_N = 20                                     # under this many scored picks a result is "a count, not a rate"
NOTIONAL = 100_000.0                                # the notional position the charges and the tax are worked on (rupees, or dollars for the US)
ENDED = ("withdrawn", "stopped", "broken")
STALE_DAYS = 10                                     # a stock whose last close is older than this at the end date has no price there (suspended, delisted): not scored yet
MARKETS = ("IN", "US")
INDEX_NAMES = {"IN": "the Nifty 500's", "US": "the S&P 500's (SPY in rupees)"}
INDEX_LABELS = {"IN": "Nifty 500 total return index", "US": "S&P 500 (SPY, dividends reinvested) in rupees at the USD/INR source stated for each date"}
ESTIMATE = ("estimate: a pick and the index are each valued as if sold on the end date, after the sell charges and the tax rate of the dated row for the holding period; no yearly "
            "exemption per pick (it is shared by the year's sales); surcharge and cess not added")


def _root(root) -> Path:
    if root is None:
        from pflab.data import data_dir
        root = data_dir()
    return Path(root)


def _rows(con, sql: str, args=()) -> list:
    try:
        return con.execute(sql, list(args)).fetchall()
    except Exception:
        return []


def _d(x) -> Optional[date]:
    if x is None:
        return None
    return x.date() if isinstance(x, datetime) else x


# --- the series ---------------------------------------------------------------------------------------------------------------------

def index_series(market: str, root=None) -> Optional[pd.Series]:
    """The market's index level by date (US: SPY in USD, dividends reinvested; its rupee value needs the FX of each date)."""
    root = _root(root)
    if market == "US":
        return us_series("SPY", root)
    from pflab.paper import benchmark
    return benchmark._load("indices", str(benchmark.settings()["equity_series"]), root)


def us_series(symbol: str, root=None) -> Optional[pd.Series]:
    from pflab.us import data as usd
    b = usd.bars(symbol, _root(root))
    if b is None or b.empty:
        return None
    col = "adj_close" if "adj_close" in b.columns and b["adj_close"].notna().any() else "close"
    s = pd.Series(b[col].astype(float).to_numpy(), index=pd.to_datetime(b["date"])).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s[s > 0]


def _asof(s: Optional[pd.Series], day: date) -> Optional[Tuple[date, float]]:
    if s is None or not len(s):
        return None
    v = s[s.index <= pd.Timestamp(day)]
    return None if v.empty else (v.index[-1].date(), float(v.iloc[-1]))


def _first_after(s: pd.Series, day: date) -> Optional[date]:
    v = s[s.index > pd.Timestamp(day)]
    return None if v.empty else v.index[0].date()


def _fx(con, day: date, root) -> Optional[dict]:
    try:
        from pflab.us import fx as usfx
        return usfx.rate_for(con, day, root, max_age_days=10)
    except Exception:
        return None


def _factors(isin: str, root: Path) -> pd.DataFrame:
    p = root / "corporate_actions" / "factors.parquet"
    try:
        f = pd.read_parquet(p, filters=[("isin", "==", isin)])
        f = f[f["factor"] > 0]
        return f.assign(ex_date=pd.to_datetime(f["ex_date"]).dt.date)
    except Exception:
        return pd.DataFrame(columns=["isin", "ex_date", "factor"])


def _dividends(isin: str, root: Path) -> pd.DataFrame:
    p = root / "dividends" / "dividends.parquet"
    try:
        d = pd.read_parquet(p, filters=[("isin", "==", isin)])
        return d.assign(ex_date=pd.to_datetime(d["ex_date"]).dt.date)
    except Exception:
        return pd.DataFrame(columns=["isin", "ex_date", "dividend_per_share"])


def has_action(isin: str, d0: date, d1: date, root) -> bool:
    f = _factors(isin, _root(root))
    return bool(((f["ex_date"] > d0) & (f["ex_date"] <= d1) & ((f["factor"] - 1.0).abs() > 1e-9)).any()) if len(f) else False


# --- gross returns --------------------------------------------------------------------------------------------------------------------

def stock_return_in(con, isin: str, d0: date, d1: date, root=None) -> Optional[dict]:
    """The total return of an India-listed share from the close of `d0` to the close of `d1`: splits and bonuses from the corporate-action factors, cash dividends added. None when
    a close is missing or older than STALE_DAYS at either date."""
    from pflab.paper import book
    root = _root(root)
    a, b = book.close_on(con, isin, d0), book.close_on(con, isin, d1)
    if not a or not b or (d0 - a[0]).days > STALE_DAYS or (d1 - b[0]).days > STALE_DAYS:
        return None
    f = _factors(isin, root)
    in_win = f[(f["ex_date"] > d0) & (f["ex_date"] <= d1)] if len(f) else f
    big_f = float(in_win["factor"].prod()) if len(in_win) else 1.0
    div = _dividends(isin, root)
    div = div[(div["ex_date"] > d0) & (div["ex_date"] <= d1)] if len(div) else div
    cash = 0.0
    for r in div.itertuples(index=False):
        g = float(f[(f["ex_date"] >= r.ex_date) & (f["ex_date"] <= d1)]["factor"].prod()) if len(f) else 1.0
        cash += float(r.dividend_per_share) * g
    p0, p1 = a[1] * big_f, b[1]
    return {"ret": (p1 + cash) / p0 - 1.0, "p0": a[1], "p1": b[1], "p0_date": a[0], "p1_date": b[0], "factor": big_f, "dividends_per_share": cash}


def series_return(s: Optional[pd.Series], d0: date, d1: date) -> Optional[float]:
    a, b = _asof(s, d0), _asof(s, d1)
    if a is None or b is None or a[1] <= 0:
        return None
    return b[1] / a[1] - 1.0


def stock_return_us(symbol: str, d0: date, d1: date, root=None) -> Optional[dict]:
    s = us_series(symbol, root)
    a, b = _asof(s, d0), _asof(s, d1)
    if a is None or b is None or (d0 - a[0]).days > STALE_DAYS or (d1 - b[0]).days > STALE_DAYS:
        return None
    return {"ret": b[1] / a[1] - 1.0, "p0_date": a[0], "p1_date": b[0]}


def _inr_multiple(usd_ret: float, fx0: dict, fx1: dict) -> float:
    return (1.0 + usd_ret) * (fx1["rate"] / fx0["rate"]) - 1.0


# --- after tax -----------------------------------------------------------------------------------------------------------------------

def liquidation_in(gross: float, d0: date, d1: date, asset_class: str = "equity", tax_class: str = "EQUITY") -> Optional[dict]:
    """A notional position bought at the close of d0 that grew by `gross` by d1 and is sold there: sell charges, then the tax at the engine's rate for its bucket. None when no
    tax row covers d1. `net` is the return on the cost including the buy charges."""
    from pflab.paper import book
    try:
        rates = tr.rates(d1)
    except rules.RuleGap:
        return None
    n = NOTIONAL
    buy = book._charges(asset_class, "buy", n)
    v = n * (1.0 + gross)
    sell = book._charges(asset_class, "sell", max(v, 0.0))
    gain = v - n - sell
    bucket = book._bucket(tax_class, asset_class, d0, d1)
    rate = float(rates.get(bucket, rates["slab"]))
    tax = rate * max(0.0, gain)
    return {"net": (v - sell - tax) / (n + buy) - 1.0, "tax_pct": tax / n * 100.0, "charges_pct": (buy + sell) / n * 100.0, "bucket": bucket, "rate": rate,
            "rows": rates["rows"], "exemption_not_taken": rates["exemption"], "value_multiple": (v - sell - tax) / n}


def liquidation_us(gross_usd: float, fx0: dict, fx1: dict, d0: date, d1: date) -> Optional[dict]:
    """The same for the US route (dollars, rupees at the two FX rates, `us/tax.py` rates, `us/costs.py` charges and slippage). None when a row is missing."""
    try:
        from pflab.us import costs as uc, tax as ut, rows as urows
        n = NOTIONAL / 10.0
        buy = uc.charges("buy", 100.0, n / 100.0, d0)["total"] + n * uc.slippage_bps() / 1e4
        v = n * (1.0 + gross_usd)
        sell = uc.charges("sell", 100.0, v / 100.0, d1)["total"] + v * uc.slippage_bps() / 1e4
        cost_inr = n * fx0["rate"]
        gain_inr = (v - sell) * fx1["rate"] - cost_inr
        cls = ut.holding_class(d0, d1)
        rate = float(urows.value("cg_foreign_ltcg_rate")) if cls == "long" else ut.slab()
        tax = rate * max(0.0, gain_inr)
        out_inr = (v - sell) * fx1["rate"] - tax
        in_inr = (n + buy) * fx0["rate"]
        return {"net": out_inr / in_inr - 1.0, "tax_pct": tax / cost_inr * 100.0, "charges_pct": (buy + sell) / n * 100.0, "bucket": cls, "rate": rate,
                "rows": ["cg_foreign_ltcg_rate", "cg_foreign_stcg_rate"], "exemption_not_taken": 0.0, "value_multiple": out_inr / cost_inr}
    except Exception:
        return None


# --- one item at one horizon -------------------------------------------------------------------------------------------------------

def _target(start: date, h: int) -> date:
    return start + relativedelta(months=h)


def _window(idx: pd.Series, start: date, h: int, today: date, ended_on: Optional[date]) -> Optional[Tuple[date, date]]:
    """(target, end) when the horizon has elapsed (the target has passed and the index has a close on or after it), else None."""
    tgt = _target(start, h)
    if tgt > today or idx.index.max().date() < tgt:
        return None
    cap = tgt if (ended_on is None or ended_on >= tgt) else ended_on
    end = _asof(idx, cap)
    if end is None or end[0] <= start:
        return None
    return tgt, end[0]


def _record(kind, ref_id, market, isin, symbol, h, start, end, ret, idx_net, idx_raw, tax_charges, after_tax, today, detail) -> dict:
    return {"kind": kind, "ref_id": int(ref_id), "market": market, "isin": isin, "symbol": symbol, "horizon_months": h, "start_on": start, "end_on": end,
            "return_pct": None if ret is None else ret * 100.0, "index_return_pct": None if idx_net is None else idx_net * 100.0, "index_raw_pct": None if idx_raw is None else idx_raw * 100.0,
            "excess_pct": None if ret is None or idx_net is None else (ret - idx_net) * 100.0, "tax_charges_pct": tax_charges, "after_tax": bool(after_tax), "scored_on": today, "detail": detail}


def _gross_item(con, market: str, isin: Optional[str], symbol: str, start: date, end: date, root) -> Optional[Tuple[float, float, dict]]:
    """(item gross return, index gross return, detail) in the market's money from start to end, or None when something is missing."""
    idx = index_series(market, root)
    if market == "IN":
        s = stock_return_in(con, isin, start, end, root) if isin else None
        ir = series_return(idx, start, end)
        if s is None or ir is None:
            return None
        return s["ret"], ir, {"p0": s["p0"], "p1": s["p1"], "factor": s["factor"], "dividends_per_share": s["dividends_per_share"], "index": INDEX_LABELS["IN"]}
    fx0, fx1 = _fx(con, start, root), _fx(con, end, root)
    s = stock_return_us(symbol, start, end, root)
    ir = series_return(idx, start, end)
    if s is None or ir is None or fx0 is None or fx1 is None:
        return None
    det = {"usd_return_pct": s["ret"] * 100.0, "index_usd_return_pct": ir * 100.0, "fx_start": fx0["rate"], "fx_end": fx1["rate"], "fx_source_start": fx0["source"], "fx_source_end": fx1["source"],
           "index": INDEX_LABELS["US"]}
    return s["ret"], ir, {**det, "_fx": (fx0, fx1)}


def _finish(con, kind: str, market: str, isin, symbol, start: date, end: date, gross: float, igross: float, det: dict, price_only: bool) -> Tuple[float, float, float, Optional[float], bool, dict]:
    """-> (return, index return (taxed alike), raw index return, tax and charges in points, after_tax, detail). `price_only`: a skip, or tax rows missing."""
    fx = det.pop("_fx", None)
    if market == "IN":
        ac = "equity"
        if isin:
            from pflab.paper import book
            m = book.inst(con, isin)
            ac = m["asset_class"] or "equity"
            tc = m["tax_class"] or "EQUITY"
        else:
            tc = "EQUITY"
        raw_i = igross
        if price_only:
            return gross, igross, raw_i, None, False, det
        a, b = liquidation_in(gross, start, end, ac, tc), liquidation_in(igross, start, end, "etf", "EQUITY")
        rg = gross
    else:
        fx0, fx1 = fx
        rg = _inr_multiple(gross, fx0, fx1)
        raw_i = _inr_multiple(igross, fx0, fx1)
        if price_only:
            return rg, raw_i, raw_i, None, False, det
        a, b = liquidation_us(gross, fx0, fx1, start, end), liquidation_us(igross, fx0, fx1, start, end)
    if a is None or b is None:
        det["after_tax_note"] = "no tax row or rate for this date: price only"
        return rg, raw_i, raw_i, None, False, det
    det.update({"tax_rows": a["rows"], "tax_bucket": a["bucket"], "tax_rate": a["rate"], "exemption_not_taken": a["exemption_not_taken"], "tax_pct_of_cost": a["tax_pct"],
                "charges_pct_of_cost": a["charges_pct"], "index_tax_pct_of_cost": b["tax_pct"], "pre_tax_return_pct": rg * 100.0, "label": ESTIMATE})
    return a["net"], b["net"], raw_i, a["tax_pct"] + a["charges_pct"], True, det


def _start_for(idx: pd.Series, day: date) -> Optional[date]:
    return _first_after(idx, day)


# --- scoring -------------------------------------------------------------------------------------------------------------------------------

def _done(con) -> set:
    return {(k, m, int(r), int(h)) for k, m, r, h in _rows(con, "SELECT kind, market, ref_id, horizon_months FROM pick_scores_s83")}


def _insert(con, rec: dict) -> None:
    from pflab.pm.store import next_id
    con.execute("INSERT INTO pick_scores_s83 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [next_id(con, "pick_scores_s83", "score_id"), rec["kind"], rec["ref_id"], rec["market"], rec["isin"], rec["horizon_months"], rec["start_on"], rec["end_on"], rec["return_pct"],
                 rec["index_return_pct"], rec["excess_pct"], rec["tax_charges_pct"], rec["after_tax"], rec["scored_on"], rec["index_raw_pct"], rec["symbol"],
                 json.dumps(rec["detail"], default=str)])


def first_fill(con, market: str, isin: Optional[str], symbol: Optional[str] = None) -> Optional[date]:
    """The day of the first BUY fill of a name in the market's book (India `paper_trades`, US `us_trades_s81`), None when it was never bought (S84 F3)."""
    if market == "US":
        rows = _rows(con, "SELECT min(day) FROM us_trades_s81 WHERE side='buy' AND (isin=? OR upper(symbol)=upper(?))", [isin or "", symbol or ""])
    else:
        rows = _rows(con, "SELECT min(day) FROM paper_trades WHERE side='buy' AND isin=?", [isin or ""])
    return _d(rows[0][0]) if rows and rows[0][0] is not None else None


def pick_started(con, market: str, isin: Optional[str], symbol: Optional[str], source: Optional[str], state: Optional[str]) -> Tuple[bool, Optional[date]]:
    """(held yet, first fill). A pick's record starts at its FIRST FILL (S84 F3). A pick named and not bought is "named, not yet held" and is not in the record. His Kite stocks are held
    from the start of the book, and a pick whose state is 'held' holds shares (an old row with no trade of its own keeps the first session after it was proposed)."""
    ff = first_fill(con, market, isin, symbol)
    if ff is not None:
        return True, ff
    return (source == "kite" or state == "held"), None


def started_ids(con, market: str) -> set:
    """The pick ids of a market that have started their record (see `pick_started`)."""
    return {int(pid) for pid, isin, sym, src, st in _rows(con, "SELECT pick_id, isin, symbol, source, state FROM picks_s83 WHERE market=?", [market]) if pick_started(con, market, isin, sym, src, st)[0]}


def named_not_held(con, market: str) -> List[str]:
    """Symbols of the market's live picks (proposed or buying) that have not been bought yet."""
    out = []
    for isin, sym, src, st in _rows(con, "SELECT isin, symbol, source, state FROM picks_s83 WHERE market=? AND state IN ('proposed','buying') ORDER BY pick_id", [market]):
        if not pick_started(con, market, isin, sym, src, st)[0]:
            out.append(sym or isin)
    return out


def _score_picks_and_skips(con, today: date, root, done: set, out: dict) -> None:
    idxs = {m: index_series(m, root) for m in MARKETS}
    items = []
    for pid, mk, isin, sym, state, prop, chg, src in _rows(con, "SELECT pick_id, market, isin, symbol, state, proposed_on, state_changed_on, source FROM picks_s83"):
        held, ff = pick_started(con, mk or "IN", isin, sym, src, state)
        if not held:
            out["named_not_held"] += 1                                # S84 F3: a named, unbought pick has no record yet (its skip-style score is not a pick's)
            continue
        on = (ff - timedelta(days=1)) if ff is not None else _d(prop)    # the first session ON the first fill (the day before is "proposed on" for the first-session-after rule)
        items.append(("pick", int(pid), mk or "IN", isin, sym or isin, on, _d(chg) if state in ENDED else None))
    for sid, mk, isin, sym, on in _rows(con, "SELECT skip_id, market, isin, symbol, skipped_on FROM skips_s83"):
        items.append(("skip", int(sid), mk or "IN", isin, sym or isin, _d(on), None))
    for kind, ref, mk, isin, sym, on, ended in items:
        idx = idxs.get(mk)
        if idx is None or on is None:
            out["no_index_or_date"] += 1
            continue
        start = _start_for(idx, on)
        if start is None:
            out["waiting"] += 1
            continue
        for h in HORIZONS:
            if (kind, mk, ref, h) in done:
                continue
            w = _window(idx, start, h, today, ended)
            if w is None:
                out["waiting"] += 1
                continue
            g = _gross_item(con, mk, isin, sym, start, w[1], root)
            if g is None:
                out["unscorable"].append(f"{kind} {sym} {h}m: a price or rate is missing")
                continue
            ret, iret, raw_i, tcp, after, det = _finish(con, kind, mk, isin, sym, start, w[1], g[0], g[1], g[2], price_only=(kind == "skip"))
            det.update({"horizon_date": str(w[0]), "ended_early_on": str(ended) if ended and ended < w[0] else None, "start_rule": "a pick: its first fill; a skip: the first session after the day it was proposed"})
            rec = _record(kind, ref, mk, isin, sym, h, start, w[1], ret, iret, raw_i, tcp, after, today, det)
            _insert(con, rec)
            done.add((kind, mk, ref, h))
            out["scored"][kind] += 1


def _score_sales_in(con, today: date, root, done: set, out: dict) -> None:
    from pflab.core import exits
    from pflab.paper import book
    idx = index_series("IN", root)
    if idx is None:
        return
    for eid, plan_id, mk, isin, kind, trade_id, filled_on, dj in _rows(con, "SELECT event_id, plan_id, market, isin, kind, trade_id, filled_on, detail_json FROM exit_events_s81 "
                                                                        "WHERE side='sell' AND status='filled' AND trade_id IS NOT NULL AND market='IN' ORDER BY event_id"):
        start = _d(filled_on)
        if start is None:
            continue
        sym = book.inst(con, isin)["symbol"] or isin
        for h in HORIZONS:
            if ("sale", "IN", int(eid), h) in done:
                continue
            w = _window(idx, start, h, today, None)
            if w is None:
                out["waiting"] += 1
                continue
            if has_action(isin, start, w[1], root):
                out["unscorable"].append(f"sale {sym} {h}m: a split or bonus falls inside the window")
                continue
            px = book.close_on(con, isin, w[1])
            ir = series_return(idx, start, w[1])
            if px is None or (w[1] - px[0]).days > STALE_DAYS or ir is None:
                out["unscorable"].append(f"sale {sym} {h}m: a price is missing")
                continue
            try:
                s = exits._score_one(con, (eid, plan_id, mk, isin, kind, trade_id, filled_on, dj), h, w[1], px[1])
            except Exception as e:
                out["unscorable"].append(f"sale {sym} {h}m: {type(e).__name__}")
                continue
            proceeds = max(float(s["proceeds_after_tax"]), 1e-9)
            ret = s["hold_value"] / proceeds - 1.0
            b = liquidation_in(ir, start, w[1], "etf", "EQUITY")
            idx_net = b["net"] if b else ir
            det = {**s["detail"], "sold_for": "the sale's proceeds after tax and charges; the return is what the same shares would have netted by the end date after the engine's tax and charges",
                   "sale_kind": kind, "sale_vs_hold_pct": s["diff_pct"], "label": ESTIMATE if b else "index price only (no tax row)", "horizon_date": str(w[0])}
            tcp = (float(s["qty"]) * px[1] - s["hold_value"]) / proceeds * 100.0
            rec = _record("sale", eid, "IN", isin, sym, h, start, w[1], ret, idx_net, ir, tcp, True, today, det)
            _insert(con, rec)
            done.add(("sale", "IN", int(eid), h))
            out["scored"]["sale"] += 1


def _score_sales_us(con, today: date, root, done: set, out: dict) -> None:
    idx = index_series("US", root)
    if idx is None:
        return
    for tid, day, isin, sym, px in _rows(con, "SELECT trade_id, day, isin, symbol, price_usd FROM us_trades_s81 WHERE side='sell' ORDER BY trade_id"):
        start = _d(day)
        for h in HORIZONS:
            if ("sale", "US", int(tid), h) in done:
                continue
            w = _window(idx, start, h, today, None)
            if w is None:
                out["waiting"] += 1
                continue
            g = _gross_item(con, "US", isin, sym, start, w[1], root)
            if g is None:
                out["unscorable"].append(f"sale {sym} {h}m (US): a price or rate is missing")
                continue
            ret, iret, raw_i, tcp, after, det = _finish(con, "sale", "US", isin, sym, start, w[1], g[0], g[1], g[2], price_only=True)
            det.update({"horizon_date": str(w[0]), "note": "a US sale is scored on price only (the engine's hold-after-tax valuation is for rupee lots)"})
            _insert(con, _record("sale", tid, "US", isin, sym, h, start, w[1], ret, iret, raw_i, None, False, today, det))
            done.add(("sale", "US", int(tid), h))
            out["scored"]["sale"] += 1


def score_all(con, now: datetime, root=None) -> dict:
    """Score whatever has become due (idempotent: an item and horizon already stored is never rewritten). -> {'scored': {pick, sale, skip}, 'waiting', 'unscorable': [...]}."""
    today = now.date() if isinstance(now, datetime) else now
    root = _root(root)
    out = {"scored": {"pick": 0, "sale": 0, "skip": 0}, "waiting": 0, "unscorable": [], "no_index_or_date": 0, "named_not_held": 0}
    done = _done(con)
    _score_picks_and_skips(con, today, root, done, out)
    for fn in (_score_sales_in, _score_sales_us):
        try:
            fn(con, today, root, done, out)
        except Exception as e:                                    # one market's sales failing never stops the others
            out["unscorable"].append(f"{fn.__name__}: {type(e).__name__}: {str(e)[:100]}")
    out["unscorable"] = out["unscorable"][:20]
    return out


# --- the sleeve ----------------------------------------------------------------------------------------------------------------------------

def _load_sleeve_state(con, market: str) -> Optional[dict]:
    r = _rows(con, "SELECT day, sleeve_value, worst_fall_sleeve, worst_fall_index, detail_json FROM pick_sleeve_daily_s83 WHERE market=? ORDER BY day DESC LIMIT 1", [market])
    if not r:
        return None
    d = json.loads(r[0][4] or "{}")
    return {"day": r[0][0], "gross": r[0][1], **d}


def _in_sleeve_day(con, day: date, qtys: Dict[str, float], rates: Optional[dict]) -> dict:
    from pflab.paper import book
    gross = at = 0.0
    for isin, q in qtys.items():
        px = book.close_on(con, isin, day)
        if not px or q <= 1e-9:
            continue
        m = book.inst(con, isin)
        ac = m["asset_class"]
        val = q * px[1]
        gross += val
        lots = [l for l in tr.lots(con, isin) if l["acq"] <= day]
        taken = tr.consume(lots, q)
        left = q - sum(t["take"] for t in taken)
        if left > 1e-6:
            cpu = (sum(t["take"] * t["cpu"] for t in taken) / max(sum(t["take"] for t in taken), 1e-9)) if taken else px[1]
            taken = taken + [{"acq": day, "take": left, "cpu": cpu, "tax_class": m["tax_class"]}]
        fee = book._charges(ac, "sell", val)
        tax = 0.0
        if rates is not None:
            for bucket, g in tr.sale_gains(taken, px[1], fee, ac, day).items():
                tax += float(rates.get(bucket, rates["slab"])) * max(0.0, g)
        at += val - fee - tax
    return {"gross": gross, "at": at}


def _sleeve_days_in(con, after: Optional[date], root) -> List[dict]:
    from pflab.core import sleeves
    from pflab.paper import benchmark, book
    idx = index_series("IN", root)
    cache: Dict[str, bool] = {}

    def in_sleeve(isin):
        if isin not in cache:
            cache[isin] = sleeves.sleeve_of(con, isin, "IN") == "longterm"
        return cache[isin]
    out = []
    for day, hj in _rows(con, "SELECT day, holdings_json FROM paper_days ORDER BY day"):
        if after is not None and day <= after:
            continue
        qtys = {i: float(q) for i, q in json.loads(hj or "{}").items() if in_sleeve(i)}
        try:
            rates = tr.rates(day)
        except rules.RuleGap:
            rates = None
        v = _in_sleeve_day(con, day, qtys, rates)
        flow = 0.0
        for isin, side, qty, price, ch, tx in _rows(con, "SELECT isin, side, qty, price, charges, tax FROM paper_trades WHERE day=?", [day]):
            if not in_sleeve(isin):
                continue
            flow += (qty * price + float(ch or 0.0)) if side == "buy" else -(qty * price - float(ch or 0.0) - float(tx or 0.0))
        income = sum(a for ref, a in benchmark._income_on(con, day).items() if in_sleeve(ref))
        lv = _asof(idx, day)
        out.append({"day": day, "gross": v["gross"], "at": v["at"], "flow": flow, "income": income, "idx": lv[1] if lv else None, "rates_missing": rates is None})
    return out


def _sleeve_days_us(con, after: Optional[date], root) -> List[dict]:
    from pflab.us import book as ub, tax as ut
    spy = index_series("US", root)
    out = []
    lots_now = ub.open_lots(con)
    for day, fxr, hj in _rows(con, "SELECT day, fx_rate, holdings_json FROM us_days_s81 ORDER BY day"):
        if after is not None and day <= after:
            continue
        fxd = {"rate": float(fxr)} if fxr else _fx(con, day, root)
        if fxd is None:
            continue
        gross = at = 0.0
        for canon, h in (json.loads(hj or "{}")).items():
            sym = (h.get("symbol") or canon).upper()
            if sym == "SPY" or not h.get("close"):
                continue
            q, px = float(h["qty"]), float(h["close"])
            val_usd = q * px
            gross += val_usd * fxd["rate"]
            lots = [l for l in lots_now if (l["symbol"] or "").upper() == sym and l["acq_date"] <= day]
            sale_fee = 0.0
            try:
                from pflab.us import costs as uc
                sale_fee = uc.charges("sell", q, px, day)["total"]
            except Exception:
                pass
            parts, left = [], q
            for l in lots:
                take = min(l["qty"], left)
                if take <= 1e-9:
                    break
                left -= take
                parts.append(ut.lot_gain(take, l["cost_usd_per_share"], l["fx_tax_acq"] or fxd["rate"], take * px - sale_fee * take / q, fxd["rate"], l["acq_date"], day))
            tax = ut.sale(parts)["tax_inr"] if parts else 0.0
            at += (val_usd - sale_fee) * fxd["rate"] - tax
        flow = 0.0
        for side, qty, price, ch, sym, taxi in _rows(con, "SELECT side, qty, price_usd, charges_usd, symbol, tax_inr FROM us_trades_s81 WHERE day=?", [day]):
            if (sym or "").upper() == "SPY":
                continue
            flow += ((qty * price + ch) * fxd["rate"]) if side == "buy" else -((qty * price - ch) * fxd["rate"] - float(taxi or 0.0))
        income = 0.0
        for sym, gross_usd, withheld, resid in _rows(con, "SELECT symbol, gross_usd, withheld_usd, residual_tax_inr FROM us_dividends_s81 WHERE day=?", [day]):
            if (sym or "").upper() != "SPY":
                income += (gross_usd - withheld) * fxd["rate"] - float(resid or 0.0)
        lv = _asof(spy, day)
        out.append({"day": day, "gross": gross, "at": at, "flow": flow, "income": income, "idx": (lv[1] * fxd["rate"]) if lv else None, "rates_missing": False})
    return out


def update_sleeve_daily(con, now: datetime, root=None) -> dict:
    """Extend `pick_sleeve_daily_s83` to every marked day of each market not yet stored (incremental; a stored day is never rewritten). -> {market: days added}."""
    root = _root(root)
    out: Dict[str, object] = {}
    for market in MARKETS:
        st = _load_sleeve_state(con, market)
        if st is not None and not isinstance(st["start"], date):
            st["start"] = date.fromisoformat(str(st["start"])[:10])
        try:
            days = (_sleeve_days_in if market == "IN" else _sleeve_days_us)(con, st["day"] if st else None, root)
        except Exception as e:
            out[market] = f"failed: {type(e).__name__}: {str(e)[:100]}"
            continue
        added = 0
        for d in days:
            if st is None:
                if d["gross"] <= 0 or d["idx"] is None:
                    continue                                              # the sleeve starts on the first marked day it holds anything
                row = {"v_at": d["at"], "start": d["day"], "idx_start": d["idx"], "lvl_s": 1.0, "lvl_i": 1.0, "peak_s": 1.0, "peak_i": 1.0, "w_s": 0.0, "w_i": 0.0,
                       "idx_at_prev": _idx_after_tax(market, d["idx"], d["idx"], d["day"], d["day"]), "idx_raw_prev": d["idx"]}
                _store_day(con, market, d, row, 0.0, 0.0, 0.0)
                st = {"day": d["day"], **row}
                added += 1
                continue
            rs = ((d["at"] - d["flow"] + d["income"]) / st["v_at"] - 1.0) if st["v_at"] > 1e-9 else 0.0
            ia = _idx_after_tax(market, d["idx"], st["idx_start"], st["start"], d["day"]) if d["idx"] is not None else None
            ri = (ia / st["idx_at_prev"] - 1.0) if (ia is not None and st.get("idx_at_prev")) else 0.0
            raw = (d["idx"] / st["idx_raw_prev"] - 1.0) if (d["idx"] is not None and st.get("idx_raw_prev")) else 0.0
            lvl_s, lvl_i = st["lvl_s"] * (1.0 + rs), st["lvl_i"] * (1.0 + ri)
            peak_s, peak_i = max(st["peak_s"], lvl_s), max(st["peak_i"], lvl_i)
            row = {"v_at": d["at"], "start": st["start"], "idx_start": st["idx_start"], "lvl_s": lvl_s, "lvl_i": lvl_i, "peak_s": peak_s, "peak_i": peak_i,
                   "w_s": min(st["w_s"], lvl_s / peak_s - 1.0), "w_i": min(st["w_i"], lvl_i / peak_i - 1.0),
                   "idx_at_prev": ia if ia is not None else st.get("idx_at_prev"), "idx_raw_prev": d["idx"] if d["idx"] is not None else st.get("idx_raw_prev")}
            _store_day(con, market, d, row, rs, ri, raw)
            st = {"day": d["day"], **row}
            added += 1
        out[market] = added
    return out


def _idx_after_tax(market: str, level: float, start_level: float, start, day: date) -> Optional[float]:
    if isinstance(start, str):
        start = date.fromisoformat(start)
    m = level / start_level - 1.0
    if market == "IN":
        r = liquidation_in(m, start, day, "etf", "EQUITY")
    else:
        # the index level here is already in rupees (SPY x USD/INR): the tax is worked on the rupee gain, the charges are the US route's
        r = _liq_rupee_us(m, start, day)
    return None if r is None else r["value_multiple"]


def _liq_rupee_us(rupee_gain: float, d0: date, d1: date) -> Optional[dict]:
    try:
        from pflab.us import costs as uc, tax as ut, rows as urows
        n = NOTIONAL
        v = n * (1.0 + rupee_gain)
        sell = uc.charges("sell", 100.0, max(v, 1.0) / 100.0, d1)["total"] + max(v, 0.0) * uc.slippage_bps() / 1e4
        gain = v - n - sell
        cls = ut.holding_class(d0, d1)
        rate = float(urows.value("cg_foreign_ltcg_rate")) if cls == "long" else ut.slab()
        tax = rate * max(0.0, gain)
        return {"value_multiple": (v - sell - tax) / n}
    except Exception:
        return None


def _store_day(con, market: str, d: dict, row: dict, rs: float, ri: float, raw: float) -> None:
    detail = {k: (str(v) if isinstance(v, date) else v) for k, v in row.items()}
    detail.update({"flow": d["flow"], "income": d["income"], "tax_rates_missing": d.get("rates_missing", False)})
    con.execute("INSERT OR REPLACE INTO pick_sleeve_daily_s83 VALUES (?,?,?,?,?,?,?,?,?,?)",
                [market, d["day"], d["gross"], d["idx"], rs, ri, row["w_s"], row["w_i"], raw, json.dumps(detail, default=str)])


def sleeve_record(con, market: str, day: Optional[date] = None, window: Optional[int] = None) -> dict:
    """The sleeve against the index since its start (or the last `window` sessions): {'sessions', 'sleeve_return_after_tax', 'index_return', 'points_a_year', 'worst_fall_sleeve',
    'worst_fall_index', ...}. Both returns are after the estimated tax and charges (the index taxed the same way); `points_a_year` is the difference of the two annualised, in
    percentage points, and None under 20 sessions (too early to annualise). Fractions, not percent."""
    q = "SELECT day, sleeve_return_after_tax, index_return, index_return_raw FROM pick_sleeve_daily_s83 WHERE market=?" + (" AND day <= ?" if day else "") + " ORDER BY day"
    rows = _rows(con, q, [market] + ([day] if day else []))
    empty = {"market": market, "sessions": 0, "since": None, "sleeve_return_after_tax": None, "index_return": None, "index_return_raw": None, "points_a_year": None,
             "excess_points": None, "worst_fall_sleeve": None, "worst_fall_index": None, "label": ESTIMATE}
    if len(rows) < 2:
        return empty
    if window:
        rows = rows[-(int(window) + 1):]
    base = rows[0][0]
    gs = gi = gr = 1.0
    ps = pi = 1.0
    ws = wi = 0.0
    for _, rs, ri, rr in rows[1:]:
        gs *= 1.0 + (rs or 0.0)
        gi *= 1.0 + (ri or 0.0)
        gr *= 1.0 + (rr or 0.0)
        ps, pi = max(ps, gs), max(pi, gi)
        ws, wi = min(ws, gs / ps - 1.0), min(wi, gi / pi - 1.0)
    n = len(rows) - 1
    span = max((rows[-1][0] - base).days, 1)
    pa = (((gs ** (365.0 / span)) - 1.0) - ((gi ** (365.0 / span)) - 1.0)) * 100.0 if n >= 20 else None
    return {"market": market, "sessions": n, "since": str(base), "to": str(rows[-1][0]), "sleeve_return_after_tax": gs - 1.0, "index_return": gi - 1.0, "index_return_raw": gr - 1.0,
            "points_a_year": pa, "excess_points": (gs - gi) * 100.0, "worst_fall_sleeve": ws, "worst_fall_index": wi, "label": ESTIMATE,
            "note": None if n >= 20 else f"{n} session(s) so far: too early to annualise"}


# --- the scorecard ---------------------------------------------------------------------------------------------------------------------------

def _sentence(kind: str, sym: str, h: int, ret: Optional[float], idx: Optional[float], after: bool, market: str, excess: Optional[float]) -> str:
    when = f"{h} month{'s' if h != 1 else ''}"
    nm = INDEX_NAMES.get(market, "the index")
    if ret is None or idx is None:
        return f"{kind.upper()} {sym}, {when}: not scored"
    tail = "after estimated tax" if after else "price only"
    if kind == "sale":
        verdict = "selling cost something" if (excess or 0) > 0 else "selling was right"
        return f"SALE {sym}, {when} after: the shares sold went {ret:+.1f}% against {nm} {idx:+.1f}% ({tail}); {verdict}"
    if kind == "skip":
        verdict = "a chance missed" if (excess or 0) > 0 else "skipping was right"
        return f"SKIP {sym}, {when}: it went {ret:+.1f}% against {nm} {idx:+.1f}% ({tail}); {verdict}"
    return f"PICK {sym}, {when}: {ret:+.1f}% against {nm} {idx:+.1f}% ({tail})"


def _summ(rows: list) -> dict:
    n = len(rows)
    ahead = sum(1 for r in rows if (r["excess_pct"] or 0.0) > 0)
    out = {"scored": n, "ahead": ahead, "ahead_rate": (ahead / n) if n >= MIN_RATE_N else None,
           "mean_excess_pct": (sum(r["excess_pct"] or 0.0 for r in rows) / n) if n else None,
           "mean_return_pct": (sum(r["return_pct"] or 0.0 for r in rows) / n) if n else None,
           "mean_index_pct": (sum(r["index_return_pct"] or 0.0 for r in rows) / n) if n else None}
    if n < MIN_RATE_N:
        out["note"] = "a count, not a rate"
    return out


def _score_rows(con, market: str, kind: str, day: Optional[date]) -> List[dict]:
    cols = ("score_id", "ref_id", "isin", "symbol", "horizon_months", "start_on", "end_on", "return_pct", "index_return_pct", "excess_pct", "tax_charges_pct", "after_tax", "scored_on")
    q = f"SELECT {', '.join(cols)} FROM pick_scores_s83 WHERE market=? AND kind=?" + (" AND scored_on <= ?" if day else "") + " ORDER BY score_id"
    return [dict(zip(cols, r)) for r in _rows(con, q, [market, kind] + ([day] if day else []))]


def _longest(rows: List[dict]) -> List[dict]:
    best: Dict[int, dict] = {}
    for r in rows:
        if r["ref_id"] not in best or r["horizon_months"] > best[r["ref_id"]]["horizon_months"]:
            best[r["ref_id"]] = r
    return list(best.values())


def scorecard(con, market: str = "IN", day: Optional[date] = None) -> dict:
    """The scorecard of one market as a JSON-able dict (see the module docstring). Under 20 scored picks `ahead_rate` is None and `note` says 'a count, not a rate'."""
    live = started_ids(con, market)
    picks = [r for r in _score_rows(con, market, "pick", day) if int(r["ref_id"]) in live]          # S84 F3: only picks that have been bought (a score stored before the fix for an unbought one stays out)
    heads = _longest(picks)
    src = {int(i): s for i, s in _rows(con, "SELECT pick_id, source FROM picks_s83 WHERE market=?", [market])}
    by_source = {}
    for s in ("system", "kite"):
        sub = [r for r in heads if src.get(r["ref_id"]) == s]
        if sub:
            by_source[s] = _summ(sub)
    top = _summ(heads)
    sk = _longest(_score_rows(con, market, "skip", day))
    sa = _longest(_score_rows(con, market, "sale", day))
    skips = {**_summ(sk), "missed_chances": sum(1 for r in sk if (r["excess_pct"] or 0) > 0), "meaning": "a skip is price only; 'ahead' = the idea beat the index (a chance missed)"}
    sales = {**_summ(sa), "sold_right": sum(1 for r in sa if (r["excess_pct"] or 0) <= 0), "meaning": "'ahead' = the shares sold went on to beat the index (selling cost something)"}
    allr = [(r, k) for k in ("pick", "sale", "skip") for r in _score_rows(con, market, k, day) if k != "pick" or int(r["ref_id"]) in live]
    allr.sort(key=lambda t: (t[0]["scored_on"] or date.min, t[0]["score_id"]), reverse=True)
    recent = [{"kind": k, "symbol": r["symbol"], "horizon_months": r["horizon_months"], "excess_pct": r["excess_pct"],
               "sentence": _sentence(k, r["symbol"] or r["isin"] or "?", r["horizon_months"], r["return_pct"], r["index_return_pct"], bool(r["after_tax"]), market, r["excess_pct"])} for r, k in allr[:5]]
    sl = sleeve_record(con, market, day)
    by_h = {h: _summ([r for r in picks if r["horizon_months"] == h]) for h in HORIZONS}
    out = {"market": market, "as_of": str(day) if day else None, "index": INDEX_LABELS[market], "picks_scored": top["scored"], "picks_ahead": top["ahead"], "ahead_rate": top["ahead_rate"],
           "mean_excess_pct": top["mean_excess_pct"], "by_horizon": by_h, "by_source": by_source,
           "sleeve": {"return_vs_index_points_a_year": sl["points_a_year"], "worst_fall_sleeve": sl["worst_fall_sleeve"], "worst_fall_index": sl["worst_fall_index"], "sessions": sl["sessions"],
                      "sleeve_return_after_tax": sl["sleeve_return_after_tax"], "index_return": sl["index_return"], "excess_points": sl["excess_points"], "since": sl["since"]},
           "recent": recent, "skips": skips, "sales": sales, "named_not_held": named_not_held(con, market), "label": ESTIMATE}
    if top["scored"] < MIN_RATE_N:
        out["note"] = "a count, not a rate"
    return out


def scorecard_text(con, market: str = "IN") -> str:
    """The scorecard in plain words (the strategist's first message, the reports)."""
    sc = scorecard(con, market)
    nm = "India" if market == "IN" else "US"
    idx = INDEX_NAMES[market].replace("'s", "")
    nnh = ("  named, not yet held (no record until bought): " + ", ".join(sc["named_not_held"])) if sc.get("named_not_held") else ""
    if not sc["picks_scored"] and not sc["skips"]["scored"] and not sc["sales"]["scored"]:
        return f"{nm} picks: nothing has been scored yet (a pick is scored once 1 month has passed since its first purchase)." + ("\n" + nnh if nnh else "")
    lines = []
    if sc["picks_scored"]:
        r = sc["ahead_rate"]
        lines.append(f"{nm} picks: {sc['picks_ahead']} of {sc['picks_scored']} scored picks are ahead of {idx} after estimated tax" + (f" ({r:.0%})." if r is not None else " (a count, not a rate: under 20 scored)."))
        for h, b in sc["by_horizon"].items():
            if b["scored"]:
                lines.append(f"  at {h} month{'s' if h != 1 else ''}: {b['ahead']} of {b['scored']} ahead, on average {b['mean_excess_pct']:+.1f} points against the index")
        for s, b in sc["by_source"].items():
            lines.append(f"  {'the system own picks' if s == 'system' else 'his Kite stocks'}: {b['ahead']} of {b['scored']} ahead")
    sl = sc["sleeve"]
    if sl["sessions"]:
        pa = sl["return_vs_index_points_a_year"]
        lines.append(f"  the picks sleeve since {sl['since']}: {sl['sleeve_return_after_tax'] * 100:+.1f}% after estimated tax against {sl['index_return'] * 100:+.1f}% for the index"
                     + (f" ({pa:+.1f} points a year)" if pa is not None else " (too early to put on a yearly basis)")
                     + f"; worst fall {sl['worst_fall_sleeve'] * 100:.1f}% against the index's {sl['worst_fall_index'] * 100:.1f}%")
    if sc["sales"]["scored"]:
        lines.append(f"  sales scored: {sc['sales']['scored']}, {sc['sales']['sold_right']} where selling was right")
    if sc["skips"]["scored"]:
        lines.append(f"  ideas skipped and scored: {sc['skips']['scored']}, {sc['skips']['missed_chances']} would have beaten the index")
    for r in sc["recent"][:3]:
        lines.append("  " + r["sentence"])
    if nnh:
        lines.append(nnh)
    lines.append("  (estimates: tax at the engine's rates, no yearly exemption taken per pick)")
    return "\n".join(lines)
