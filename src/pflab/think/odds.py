"""T4 OUTCOMES in rupees (S84, A65/A66): code only, no model, no network. Every figure the thinking loop shows or decides on comes from here or from `rule.py`.

    base_rates(con, kind, *, move, isin, asof)             what such names did against their index over the next 5, 20 and 60 sessions (the system's own stored history, point in time),
                                                            with the count; under `base_rate_min_n` cases the name's own range from its volatility (basis "own range")
    outcomes(con, case, option, *, isin, asof, bet_inr)    worst, likely and best in rupees of ONE option, after the tax and charges of a sale (the tax engine, FIFO lots, the 12-month rule
                                                            through the holding period at the end of the horizon), the expected rupees and the share of the whole book
    option_table(con, case_id, answer, asof)               the menu for each name of the model's answer: its likelihood WORDS mapped through `cases.probabilities` to scenario weights
    bet_size(...)                                          A66: the size of one opportunity bet so that its bad case loses at most `bet_worst_pct_book` of the whole book

Worst / likely / best are the 10th, 50th and 90th percentile of the move over the decision horizon (20 sessions): the "worst" is a bad case (1 in 10), not the worst that can happen, and is
labelled so. The index's own drift over the horizon is taken as zero (labelled). Each option is valued as the position's value after tax and charges as if liquidated at the END of the horizon,
minus today's marked value (a sale realises its tax now; a hold pays it at the horizon on the lots' holding period then; a loss earns no credit). Every figure is an ESTIMATE and says so.

The model's answer (the shape `option_table` and `rule.decide` read; `norm_answer` accepts the usual spellings):
    {"class": "damage" | "market_fear" | "temporary" | "unclear", "pending": "the board's decision" | None, "pending_resolved_on": "2026-11-20" | None,
     "choices": [{"isin": ..., "symbol": ..., "option": one of think.OPTIONS, "words": {"worst": word, "likely": word, "best": word}, "base_rate_set": "history" | "own range" | an event kind,
                  "reason": "..."}]}
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab import think
from pflab.think import cases

PARAMS = {
    "outcome_horizon_sessions": 20,
    "worst_quantile": 0.10,
    "best_quantile": 0.90,
    "base_rate_horizons": [5, 20, 60],
    "base_rate_min_n": 20,
    "default_weights": [0.3, 0.4, 0.3],                 # Swanson's rule for a 10 / 50 / 90 split: used when the model gave no words
    "trim_fraction": 0.5,
    "history_min_turnover_inr": 50000000.0,              # a move counts as a case only for a name that traded at least this much that day (`[picks] min_liquidity_inr`: what the book could trade)
}
FALLBACK_VOL = 0.30                                      # a name with too little history: the same stated, deliberately high number `core/state.py` uses
MIN_OBS = 60                                             # closes needed for an own range
BAND = (0.7, 1.4)                                        # "a move of the same size": between 0.7 and 1.4 times the move, same sign
LOOKBACK_DAYS = 2000
MOVE_KINDS = ("move", "move_1d", "move_5d", "fall", "fall_10d", "rel_5d", "missed_run", "market_fall", "market_down", "shock")
Z90 = 1.2815515655446004
ESTIMATE = ("estimate: worst and best are the 10th and 90th percentile of the move over {h} sessions (a bad case, not the worst that can happen), valued after the tax and charges of the "
            "dated tax rows as if liquidated at the end of the horizon; the index's own drift is taken as zero; a loss earns no tax credit")
AMBIGUOUS = ("sell", "trim", "hold")


def settings() -> dict:
    s = think.settings()
    out = {**PARAMS, "base_rate_min_n": int(s.get("base_rate_min_n", PARAMS["base_rate_min_n"])), "bet_worst_pct_book": float(s["bet_worst_pct_book"])}
    try:
        from pflab.core import picks
        out["history_min_turnover_inr"] = float(picks.settings("IN")["min_liquidity_inr"])
    except Exception:
        pass
    return out


def _day(x) -> date:
    return x.date() if isinstance(x, datetime) else x


def _root(root):
    if root is not None:
        return root
    try:
        from pflab.data import data_dir
        return data_dir()
    except Exception:
        return None


def _panel(root) -> Optional[str]:
    """The long adjusted-close panel of the collectors (`data/panel/prices.parquet`, 2004 on), when it is there."""
    try:
        p = Path(_root(root)) / "panel" / "prices.parquet"
        return str(p) if p.exists() else None
    except Exception:
        return None


def _hist(con, root, asof: date, start: date, isins=None, stocks_only: bool = False) -> tuple:
    """(sql, params): rows (isin, date, close, turnover) from `start` to `asof`: the panel's adjusted closes up to its last day, then the store's own closes after it (the store holds only the recent
    weeks; the panel holds the history a base rate needs). Without a panel the store alone."""
    ph, ip = "", []
    if isins:
        ph, ip = " AND isin IN (" + ",".join("?" for _ in isins) + ")", list(isins)
    parts, params, pmax = [], [], None
    pan = _panel(root)
    if pan:
        try:
            pmax = con.execute("SELECT max(date) FROM read_parquet(?)", [pan]).fetchone()[0]
        except Exception:
            pan = None
    if pan:
        parts.append("SELECT isin, date, adj_close AS close, turnover FROM read_parquet(?) WHERE date <= ? AND date >= ? AND series = 'EQ' AND adj_close > 0" + (" AND instrument_type = 'STK'" if stocks_only else "") + ph)
        params += [pan, asof, start] + ip
    sw, sp = "", []
    if pan and pmax:                                         # the store fills the days after the panel ends, and every day of a name the panel does not have at all (a new listing)
        sw, sp = " AND (date > ? OR isin NOT IN (SELECT DISTINCT isin FROM read_parquet(?) WHERE date >= ?))", [pmax, pan, pmax - timedelta(days=30)]
    parts.append("SELECT isin, date, arg_max(close, fetched_at) AS close, NULL::DOUBLE AS turnover FROM prices WHERE date <= ? AND date >= ? AND close > 0" + (" AND isin LIKE 'INE%'" if stocks_only else "") + sw + ph + " GROUP BY isin, date")
    params += [asof, start] + sp + ip
    return " UNION ALL ".join(parts), params


# --- price series ---------------------------------------------------------------------------------------------------------------------------------------------------------

def closes(con, market: str, isin: Optional[str], symbol: Optional[str], asof: date, n: int = 320, root=None) -> pd.Series:
    """The name's last `n` closes up to `asof` (point in time), a Series indexed by Timestamp. India from the store's `prices`; US from the daily bars of `data/us/raw`."""
    asof = _day(asof)
    if (market or "IN").upper() == "US":
        try:
            from pflab.us import data as usd
            b = usd.bars(symbol, _root(root)) if symbol else None
            if b is None or b.empty:
                return pd.Series(dtype=float)
            b = b[b["date"] <= asof].tail(n)
            return pd.Series(b["close"].astype(float).to_numpy(), index=pd.to_datetime(b["date"]))
        except Exception:
            return pd.Series(dtype=float)
    if not isin:
        return pd.Series(dtype=float)
    sql, params = _hist(con, root, asof, asof - timedelta(days=int(n * 1.6) + 30), [isin])
    rows = con.execute(f"SELECT date, close FROM ({sql}) ORDER BY date DESC LIMIT ?", params + [int(n)]).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    rows.sort()
    return pd.Series([float(r[1]) for r in rows], index=pd.to_datetime([r[0] for r in rows]))


def daily_vol(s: pd.Series) -> Optional[float]:
    """The standard deviation of the daily log returns of the last 250 closes, None with too little history."""
    if s is None or len(s) < MIN_OBS:
        return None
    r = np.diff(np.log(s.tail(251).to_numpy(dtype=float)))
    r = r[np.isfinite(r)]
    return float(np.std(r, ddof=1)) if len(r) >= MIN_OBS - 1 else None


def own_range(con, market: str, isin: Optional[str], symbol: Optional[str], asof: date, horizons=(5, 20, 60), root=None, n_found: int = 0) -> dict:
    """The name's own range from its volatility: a zero-drift lognormal on its last 250 sessions (the stated 30% a year when it has too little history)."""
    s = closes(con, market, isin, symbol, asof, 260, root)
    dv = daily_vol(s)
    annual = (dv * math.sqrt(252.0)) if dv else FALLBACK_VOL
    d = dv if dv else FALLBACK_VOL / math.sqrt(252.0)
    out = {}
    for h in horizons:
        sig = d * math.sqrt(h)
        out[int(h)] = {"n": int(n_found), "p10": math.exp(-Z90 * sig) - 1.0, "p50": 0.0, "p90": math.exp(Z90 * sig) - 1.0}
    out["vol_annual"] = annual
    out["vol_source"] = "its own last 250 sessions" if dv else f"too little history: the stated {FALLBACK_VOL:.0%} a year"
    return out


# --- base rates ----------------------------------------------------------------------------------------------------------------------------------------------------------

def _index_series(market: str, root=None) -> Optional[pd.Series]:
    try:
        from pflab.core import pick_score
        return pick_score.index_series((market or "IN").upper(), _root(root))
    except Exception:
        return None


def _idx_ret(ix: Optional[pd.Series], d0, d1) -> Optional[float]:
    if ix is None or not len(ix):
        return None
    a = ix[ix.index <= pd.Timestamp(d0)]
    b = ix[ix.index <= pd.Timestamp(d1)]
    if a.empty or b.empty or float(a.iloc[-1]) <= 0:
        return None
    return float(b.iloc[-1]) / float(a.iloc[-1]) - 1.0


def _pct(vals: List[float], n_min: int) -> dict:
    a = np.asarray(vals, dtype=float)
    if not len(a):
        return {"n": 0, "p10": None, "p50": None, "p90": None}
    q = np.percentile(a, [100 * PARAMS["worst_quantile"], 50, 100 * PARAMS["best_quantile"]])
    return {"n": int(len(a)), "p10": float(q[0]), "p50": float(q[1]), "p90": float(q[2])}


def _cluster(rows: List[tuple], gap_days: int = 14) -> List[tuple]:
    """One case per name per cluster: a later row within `gap_days` of the one kept is the same episode."""
    kept, last = [], {}
    for r in sorted(rows, key=lambda r: (r[0], r[1])):
        if r[0] in last and (r[1] - last[r[0]]).days < gap_days:
            continue
        last[r[0]] = r[1]
        kept.append(r)
    return kept


def _event_history(con, kind: str, asof: date, horizons, ix, root=None, limit: int = 400) -> Dict[int, List[float]]:
    """What names did after an event of this kind (the graph's `kg2_event`): from the first close strictly after the event's day (the investor learns of it that day and acts at the next close),
    over each horizon, against the index when there is one."""
    out: Dict[int, List[float]] = {int(h): [] for h in horizons}
    try:
        if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='kg2_event'").fetchone()[0]:
            return out
        ev = con.execute("SELECT isin, ts FROM kg2_event WHERE kind=? AND ts IS NOT NULL AND isin IS NOT NULL AND ts <= ? ORDER BY ts DESC LIMIT ?",
                         [kind, datetime.combine(asof, datetime.max.time()), int(limit)]).fetchall()
        ev = _cluster([(i, _day(t)) for i, t in ev])
        if not ev:
            return out
        isins = sorted({e[0] for e in ev})
        sql, params = _hist(con, root, asof, min(e[1] for e in ev), isins)
        rows = con.execute(f"SELECT isin, date, close FROM ({sql}) ORDER BY isin, date", params).fetchall()
    except Exception:
        return out
    by: Dict[str, tuple] = {}
    for i, d, c in rows:
        by.setdefault(i, ([], []))
        by[i][0].append(d)
        by[i][1].append(float(c))
    for isin, day in ev:
        if isin not in by:
            continue
        ds, cs = by[isin]
        k = next((j for j, d in enumerate(ds) if d > day), None)
        if k is None:
            continue
        for h in horizons:
            if k + h < len(ds):
                r = cs[k + h] / cs[k] - 1.0
                ir = _idx_ret(ix, ds[k], ds[k + h])
                out[int(h)].append(r - ir if ir is not None else r)
    return out


def _move_history(con, move: float, asof: date, horizons, ix, window: int = 1, root=None, min_turnover: float = 0.0) -> Dict[int, List[float]]:
    """Indian equities (with a day's turnover of at least `min_turnover` rupees on the day of the move: the names the book could trade) whose trailing `window`-session move was between
    0.7 and 1.4 times `move` (same sign): what they did next, against the index."""
    out: Dict[int, List[float]] = {int(h): [] for h in horizons}
    lo, hi = sorted((move * BAND[0], move * BAND[1]))
    leads = ", ".join(f"LEAD(close, {int(h)}) OVER w / close - 1 AS f{int(h)}, LEAD(date, {int(h)}) OVER w AS d{int(h)}" for h in horizons)
    try:
        sql, params = _hist(con, root, asof, asof - timedelta(days=LOOKBACK_DAYS), None, True)
        rows = con.execute(f"""
            WITH p AS ({sql}),
            q AS (SELECT isin, date, close, turnover, close / LAG(close, {int(window)}) OVER w - 1 AS trail, {leads} FROM p WINDOW w AS (PARTITION BY isin ORDER BY date))
            SELECT isin, date, close, {", ".join(f"f{int(h)}, d{int(h)}" for h in horizons)} FROM q WHERE trail IS NOT NULL AND trail >= ? AND trail <= ? AND (turnover IS NULL OR turnover >= ?)
            """, params + [lo, hi, float(min_turnover)]).fetchall()
    except Exception:
        return out
    by = {(r[0], r[1]): r for r in rows}
    for isin, d in _cluster([(r[0], r[1]) for r in rows]):
        r = by[(isin, d)]
        for i, h in enumerate(horizons):
            f, dh = r[3 + 2 * i], r[4 + 2 * i]
            if f is None or dh is None:
                continue
            ir = _idx_ret(ix, d, dh)
            out[int(h)].append(float(f) - ir if ir is not None else float(f))
    return out


def base_rates(con, kind: Optional[str], *, move: Optional[float] = None, isin: Optional[str] = None, asof, market: str = "IN", symbol: Optional[str] = None, window: int = 1, root=None, cache: Optional[dict] = None) -> dict:
    """{5: {n, p10, p50, p90}, 20: {...}, 60: {...}, "basis": "history" | "own range", ...}: the spread of what such names did against their index over the next 5, 20 and 60 sessions.
    `kind` is an event kind (read from the graph's events) or a move kind; `move` (a signed fraction over `window` sessions) selects names that moved alike. Point in time: nothing after
    `asof`. With fewer than `base_rate_min_n` cases at 20 sessions the count is said and the name's own range stands in (basis "own range", `history_n` keeps the count).
    `cache` is a dict the caller keeps for one case (the scan of the history takes a few seconds): the same question is answered from it."""
    asof = _day(asof)
    key = (kind, None if move is None else round(float(move), 6), isin, asof, (market or "IN").upper(), symbol, window)
    if cache is not None and key in cache:
        return cache[key]
    out = _base_rates(con, kind, move, isin, asof, market, symbol, window, root)
    if cache is not None:
        cache[key] = out
    return out


def _base_rates(con, kind, move, isin, asof, market, symbol, window, root) -> dict:
    hz = [int(h) for h in PARAMS["base_rate_horizons"]]
    min_n = settings()["base_rate_min_n"]
    ix = _index_series(market, root) if (market or "IN").upper() == "IN" else None
    hist: Dict[int, List[float]] = {h: [] for h in hz}
    how = None
    if kind and kind not in MOVE_KINDS:
        hist = _event_history(con, kind, asof, hz, ix, root)
        how = f"events of kind {kind}"
    if len(hist[20]) < min_n and move is not None and (market or "IN").upper() == "IN":
        h2 = _move_history(con, float(move), asof, hz, ix, window, root, settings()["history_min_turnover_inr"])
        if len(h2[20]) > len(hist[20]):
            hist, how = h2, f"names whose {window}-session move was {move:+.1%} (0.7 to 1.4 times, same sign)"
    out = {h: _pct(hist[h], min_n) for h in hz}
    n20 = out[20]["n"]
    out["history_n"] = n20
    out["index_adjusted"] = ix is not None
    out["kind"] = kind
    if n20 >= min_n:
        out["basis"] = "history"
        out["detail"] = f"{n20} cases of {how}; spread against {'the index' if ix is not None else 'nothing (no index series: raw returns)'} over the next 5, 20 and 60 sessions"
    else:
        own = own_range(con, market, isin, symbol, asof, hz, root, n_found=n20)
        for h in hz:
            out[h] = own[h]
        out["basis"] = "own range"
        out["vol_annual"], out["vol_source"] = own["vol_annual"], own["vol_source"]
        out["detail"] = f"only {n20} past cases (under {min_n}): the name's own range from its volatility ({own['vol_source']}, {own['vol_annual']:.0%} a year)"
    return out


# --- the position and the tax -----------------------------------------------------------------------------------------------------------------------------------------------

def whole_book(con, asof: date, root=None) -> float:
    try:
        from pflab.us import wholebook
        v = float(wholebook.whole_book_inr(con, asof, root)["whole_inr"])
        if v > 0:
            return v
    except Exception:
        pass
    try:
        from pflab.paper import book
        return float(book.holdings(con, asof)["value"] or 0.0)
    except Exception:
        return 0.0


def position(con, market: str, isin: Optional[str], symbol: Optional[str], asof: date, root=None) -> dict:
    """What the book holds of the name on `asof`: {held, qty, price, value_inr, ccy, fx, canon}. A name with no close has price None."""
    asof = _day(asof)
    market = (market or "IN").upper()
    if market == "US":
        out = {"held": False, "qty": 0.0, "price": None, "value_inr": 0.0, "ccy": "USD", "fx": None, "canon": None, "market": "US"}
        try:
            from pflab.us import book as usb, data as usd, fx as usfx, instruments as uins
            canon = uins.canonical(con, isin, asof) if isin else None
            out["canon"] = canon
            qty = float(usb.positions(con, asof).get(canon, 0.0)) if canon else 0.0
            b = usd.last_on_or_before(usd.bars(symbol, _root(root)), asof) if symbol else None
            f = usfx.rate_for(con, asof, root, max_age_days=10)
            out.update({"qty": qty, "held": qty > 1e-9, "price": b["close"] if b else None, "fx": float(f["rate"]) if f else None})
            if b and f:
                out["value_inr"] = qty * b["close"] * float(f["rate"])
        except Exception:
            pass
        return out
    from pflab.paper import book
    qty = float(book.positions(con).get(isin, 0.0)) if isin else 0.0
    px = book.close_on(con, isin, asof) if isin else None
    return {"held": qty > 1e-9, "qty": qty, "price": px[1] if px else None, "value_inr": qty * px[1] if px else 0.0, "ccy": "INR", "fx": 1.0, "canon": isin, "market": "IN"}


def _horizon_day(asof: date, h: int) -> date:
    return asof + timedelta(days=int(round(h * 7 / 5)))


def _sale_in(con, isin: str, qty: float, price: float, day: date, extra: Optional[dict] = None, extra_day: Optional[date] = None, skip: float = 0.0) -> dict:
    """Charges and the tax of selling `qty` at `price` on `day` (the exit manager's own estimate: FIFO lots, the book's buckets, the year's other gains). Rupees. `extra` are gains already
    taken in the same financial year by another part of the same plan (a trim's sale now, when the rest is valued at the horizon): they count in the year's base, so the yearly exemption
    is not used twice."""
    try:
        from pflab.core import exits, tax_rows as tr
        if not extra:
            est = exits._estimate(con, isin, qty, price, day)
            return {"charges": float(est["charges"]), "tax": float(est["tax"] or 0.0), "note": est.get("tax_note"), "gain": float(est["gain"]), "gains": est["gains"]}
        from pflab.paper import book
        from pflab.tax import rules
        ac = book.inst(con, isin)["asset_class"]
        taken = tr.consume(tr.lots(con, isin), skip + qty)                          # the lots the part sold now already used come first in the queue
        left = skip
        rest = []
        for t in taken:
            cut = min(t["take"], left)
            left -= cut
            if t["take"] - cut > 1e-9:
                rest.append({**t, "take": t["take"] - cut})
        fee = book._charges(ac, "sell", qty * price)
        gains = tr.sale_gains(rest, price, fee, ac, day)
        tax, note = 0.0, None
        try:
            base = tr.year_gains(con, day)
            if extra_day is not None and tr.fy_label(extra_day) == tr.fy_label(day):
                base = tr.add(base, extra)
            tax = max(0.0, tr.tax_of(tr.add(base, gains), day) - tr.tax_of(base, day))
        except rules.RuleGap as e:
            note = f"tax not estimated ({e})"
        return {"charges": float(fee), "tax": float(tax), "note": note, "gain": float(sum(gains.values())), "gains": gains}
    except Exception as e:
        return {"charges": qty * price * 0.0012, "tax": 0.0, "note": f"tax not estimated ({type(e).__name__})", "gain": 0.0, "gains": {}}


def _sale_us(con, pos: dict, symbol: str, qty: float, price: float, day: date, root=None) -> dict:
    """The same for the US sub-book (price in dollars; charges and tax returned in rupees)."""
    fx = pos["fx"] or 0.0
    try:
        from pflab.us import book as usb, costs, tax as ustax
        ch = costs.charges("sell", qty, price, day)["total"] + qty * price * costs.slippage_bps() / 1e4
        try:
            t = usb.plan_sale(con, pos["canon"], qty, price, ch, day, root)
            if not t.get("no_rate"):
                return {"charges": ch * fx, "tax": float(t["tax_inr"]), "note": None, "gain": float(t["gain_inr"])}
        except Exception:
            pass
        parts, left = [], qty
        for l in usb._lots_of(con, pos["canon"], day):
            take = min(l["qty"], left)
            if take <= 1e-9:
                break
            parts.append(ustax.lot_gain(take, l["cost_usd_per_share"], l["fx_tax_acq"] or fx, take * price - ch * take / max(qty, 1e-9), fx, l["acq_date"], day))
            left -= take
        t = ustax.sale(parts)
        return {"charges": ch * fx, "tax": float(t["tax_inr"]), "note": "estimate: the tax FX rates were not stored, today's rate stands in", "gain": float(t["gain_inr"])}
    except Exception as e:
        return {"charges": qty * price * fx * 0.004, "tax": 0.0, "note": f"tax not estimated ({type(e).__name__})", "gain": 0.0}


def _sale(con, pos: dict, symbol, isin, qty: float, price: float, day: date, root=None, extra=None, extra_day=None, skip: float = 0.0) -> dict:
    if pos["market"] == "US":
        return _sale_us(con, pos, symbol, qty, price, day, root)
    return _sale_in(con, isin, qty, price, day, extra, extra_day, skip)


def _buy_net(con, market: str, isin, gross: float, asof: date, h: int, fx: Optional[float]) -> dict:
    """A rupee invested today, sold at the end of the horizon after a move of `gross`: the net multiple after the buy and sell charges and the short-term tax (`pick_score.liquidation_*`),
    price only (labelled) when no tax row covers the date."""
    from pflab.core import pick_score as ps
    d1 = _horizon_day(asof, h)
    try:
        if (market or "IN").upper() == "US":
            f = {"rate": fx or 1.0}
            r = ps.liquidation_us(gross, f, f, asof, d1)
        else:
            from pflab.paper import book
            r = ps.liquidation_in(gross, asof, d1, (book.inst(con, isin)["asset_class"] or "equity"), (book.inst(con, isin)["tax_class"] or "EQUITY")) if isin else None
    except Exception:
        r = None
    if r is None:
        return {"net": gross - 0.003, "tax_pct": 0.0, "note": "price only less 0.3% charges: no tax row or no rate for this date"}
    return {"net": float(r["net"]), "tax_pct": float(r["tax_pct"]), "note": None}


# --- outcomes --------------------------------------------------------------------------------------------------------------------------------------------------------------

def norm_answer(answer: Optional[dict]) -> dict:
    """The model's answer in one shape: {"class", "pending", "pending_resolved_on", "choices": [{isin, symbol, option, words, base_rate_set, reason}]}. Unknown words are dropped (never guessed)."""
    a = dict(answer or {})
    klass = a.get("class", a.get("klass"))
    ch = a.get("choices", a.get("options", a.get("names", a.get("holdings"))))
    if isinstance(ch, dict):
        ch = [dict(v, isin=k) if isinstance(v, dict) else {"isin": k, "option": v} for k, v in ch.items()]
    out = []
    for c in ch or []:
        if not isinstance(c, dict):
            continue
        w = c.get("words", c.get("likelihood", a.get("words", a.get("likelihood")))) or {}
        w = {k: v for k, v in (w.items() if isinstance(w, dict) else []) if k in ("worst", "likely", "best") and v in think.WORDS}
        opt = c.get("option", c.get("choice"))
        out.append({"isin": c.get("isin"), "symbol": c.get("symbol"), "option": opt if opt in think.OPTIONS else None, "words": w,
                    "base_rate_set": c.get("base_rate_set", c.get("base_rates", a.get("base_rate_set"))), "reason": c.get("reason", "")})
    return {"class": klass if klass in think.CLASSES else None, "pending": a.get("pending") or None, "pending_resolved_on": a.get("pending_resolved_on"), "choices": out}


def weights(words: Optional[dict], probs: Optional[Dict[str, float]] = None) -> List[float]:
    """The three scenario weights (worst, likely, best): the words' probabilities normalised to add to one; 30 / 40 / 30 when a word is missing."""
    if not words or any(words.get(k) not in think.WORD_P for k in ("worst", "likely", "best")):
        return list(PARAMS["default_weights"])
    p = probs or think.WORD_P
    v = [float(p.get(words[k], think.WORD_P[words[k]])) for k in ("worst", "likely", "best")]
    s = sum(v)
    return [x / s for x in v] if s > 0 else list(PARAMS["default_weights"])


def case_kind_move(con, case: Optional[dict]) -> tuple:
    """(kind, move, window) of a case: its kind, and the signed move of its signals (a `fall` is negative, a `run` positive, a `move` as stored; a value beyond +-150% is points and is
    divided by 100). Move None when no signal carries one."""
    if not case:
        return None, None, 1
    kind, move, window = case.get("kind"), None, 1
    best = 0.0
    for s in case.get("signals") or []:
        name, v = str(s.get("signal") or ""), s.get("value")
        if v is None:
            continue
        v = float(v)
        if abs(v) > 1.5:
            v /= 100.0
        if "fall" in name or "down" in name:
            v = -abs(v)
        elif "run" in name:
            v = abs(v)
        elif not ("move" in name or "ret" in name or "shock" in name):
            continue
        if abs(v) > best:
            best, move = abs(v), v
            window = 10 if name.endswith("10d") else (5 if name.endswith("5d") else (20 if name.endswith("20d") else 1))
    return kind, move, window


def _scenario_moves(rates: dict, h: int) -> List[float]:
    r = rates.get(h) or rates.get(20)
    return [float(r["p10"]), float(r["p50"]), float(r["p90"])]


def bet_size(con, case: dict, isin: Optional[str], asof: date, *, market: Optional[str] = None, symbol: Optional[str] = None, rates: Optional[dict] = None, root=None) -> dict:
    """A66: the size of ONE bet so that its bad case loses at most `bet_worst_pct_book` of the WHOLE book: limit / the bad case's loss per rupee (after the charges and tax of getting out).
    {size_inr, limit_inr, worst_per_inr, worst_move, fits, basis}. A bad case with no loss at all has no size from this limit (size None)."""
    asof = _day(asof)
    case = _as_case(con, case)
    market = (market or case.get("market") or "IN").upper()
    h = int(PARAMS["outcome_horizon_sessions"])
    r = _unit_buy(con, case, isin, asof, market=market, symbol=symbol, rates=rates, root=root)
    whole = whole_book(con, asof, root)
    limit = settings()["bet_worst_pct_book"] * whole
    w = r["worst_per_inr"]
    size = None if w >= -1e-9 else limit / abs(w)
    return {"size_inr": size, "limit_inr": limit, "worst_per_inr": w, "likely_per_inr": r["likely_per_inr"], "best_per_inr": r["best_per_inr"], "worst_move": r["moves"][0], "whole_book_inr": whole,
            "basis": r["basis"], "rates": r["rates"], "horizon": h}


def _as_case(con, case) -> dict:
    if isinstance(case, int):
        case = cases.get_case(con, case)
    return case or {}


def _unit_buy(con, case, isin, asof, *, market, symbol, rates=None, root=None) -> dict:
    h = int(PARAMS["outcome_horizon_sessions"])
    case = _as_case(con, case)
    kind, move, window = case_kind_move(con, case)
    if rates is None:
        rates = base_rates(con, kind, move=move, isin=isin, asof=asof, market=market, symbol=symbol, window=window, root=root)
    moves = _scenario_moves(rates, h)
    pos = position(con, market, isin, symbol, asof, root) if market == "US" else {"fx": 1.0}
    nets = [_buy_net(con, market, isin, m, asof, h, pos.get("fx"))["net"] - 0.0 for m in moves]
    # net is the multiple of the cost minus one: the rupee result of a rupee bet
    return {"worst_per_inr": nets[0], "likely_per_inr": nets[1], "best_per_inr": nets[2], "moves": moves, "basis": rates["basis"], "rates": rates}


def _outcome_row(case, option, isin, symbol, vals, w, size, tax, whole, basis, h, rates, notes) -> dict:
    exp = sum(wi * vi for wi, vi in zip(w, vals))
    return {"isin": isin, "symbol": symbol, "option": option, "worst_inr": float(vals[0]), "likely_inr": float(vals[1]), "best_inr": float(vals[2]), "expected_inr": float(exp),
            "worst_pct_book": float(vals[0] / whole) if whole > 0 else 0.0, "tax_inr": float(tax), "size_inr": float(size), "basis": basis, "horizon_sessions": h, "weights": w,
            "moves": rates.get("_moves"), "label": ESTIMATE.format(h=h), "notes": [n for n in notes if n]}


def outcomes(con, case, option: str, *, isin: Optional[str] = None, asof, bet_inr: Optional[float] = None, words: Optional[dict] = None, rates: Optional[dict] = None,
             market: Optional[str] = None, symbol: Optional[str] = None, root=None, cache: Optional[dict] = None) -> dict:
    """Worst, likely and best in rupees of one option, the expected rupees (the words' weights, 30/40/30 without them) and the share of the whole book. `case` is the case dict or its id.
    {"worst_inr", "likely_inr", "best_inr", "expected_inr", "worst_pct_book", "tax_inr", "size_inr", "basis", ...}. A buy with no `bet_inr` is sized by A66 (`bet_size`), before the reserve
    and the rails (`rule.decide` applies those)."""
    asof = _day(asof)
    if isinstance(case, int):
        case = cases.get_case(con, case)
    case = case or {}
    if option not in think.OPTIONS:
        raise ValueError(f"unknown option {option!r}")
    isin = isin or case.get("isin")
    market = (market or case.get("market") or "IN").upper()
    symbol = symbol or case.get("symbol")
    h = int(PARAMS["outcome_horizon_sessions"])
    probs = cases.probabilities(con)
    w = weights(words, probs)
    kind, move, window = case_kind_move(con, case)
    if rates is None:
        rates = base_rates(con, kind, move=move, isin=isin, asof=asof, market=market, symbol=symbol, window=window, root=root, cache=cache)
    moves = _scenario_moves(rates, h)
    rates = {**rates, "_moves": moves}
    whole = whole_book(con, asof, root)
    pos = position(con, market, isin, symbol, asof, root)
    notes = [rates.get("detail")]
    basis = rates["basis"]
    if option == "buy_in_parts":
        if bet_inr is None:
            b = bet_size(con, case, isin, asof, market=market, symbol=symbol, rates=rates, root=root)
            bet = b["size_inr"] if b["size_inr"] is not None else 0.0
        else:
            bet = float(bet_inr)
        u = _unit_buy(con, case, isin, asof, market=market, symbol=symbol, rates=rates, root=root)
        vals = [bet * u["worst_per_inr"], bet * u["likely_per_inr"], bet * u["best_per_inr"]]
        tax = bet * _buy_net(con, market, isin, moves[1], asof, h, pos.get("fx"))["tax_pct"] / 100.0
        notes.append("a buy counts the whole bet as bought today (the three parts only lower what is at risk at once); a short-term tax at the horizon, no credit for a loss")
        return _outcome_row(case, option, isin, symbol, vals, w, bet, tax, whole, basis, h, rates, notes)
    if not pos["held"] or not pos["price"]:
        z = [0.0, 0.0, 0.0]
        return _outcome_row(case, option, isin, symbol, z, w, 0.0, 0.0, whole, basis, h, rates, notes + ["not held: nothing at stake in this option"])
    qty, px, v0, fx = pos["qty"], pos["price"], pos["value_inr"], pos["fx"] or 1.0
    d_h = _horizon_day(asof, h)

    def liquidated(q: float, m: float, extra=None, skip: float = 0.0) -> tuple:
        """After-tax liquidation value in rupees of q shares if the price moved by m and they are sold at the end of the horizon, and the tax in it."""
        if q <= 1e-9:
            return 0.0, 0.0
        p1 = px * (1.0 + m)
        s = _sale(con, pos, symbol, isin, q, p1, d_h, root, extra, asof, skip)
        return q * p1 * fx - s["charges"] - s["tax"], s["tax"]

    def sold_now(q: float) -> tuple:
        s = _sale(con, pos, symbol, isin, q, px, asof, root)
        if s.get("note"):
            notes.append(s["note"])
        return q * px * fx - s["charges"] - s["tax"], s["tax"], s.get("gains")
    if option == "sell":
        proceeds, tax, _g = sold_now(qty)
        vals, size = [proceeds - v0] * 3, v0
    elif option == "trim":
        f = float(PARAMS["trim_fraction"])
        proceeds, tax0, g0 = sold_now(qty * f)
        liq = [liquidated(qty * (1 - f), m, g0, qty * f) for m in moves]
        vals, size, tax = [proceeds + l[0] - v0 for l in liq], v0 * f, tax0
    else:                                                      # hold, freeze, wait, nothing: the position stays and pays its tax at the end of the horizon
        liq = [liquidated(qty, m) for m in moves]
        vals, size, tax = [l[0] - v0 for l in liq], 0.0, liq[1][1]
        guard = _guard(con, isin, qty, px, asof) if pos["market"] == "IN" else None
        if guard:
            notes.append(guard)
    return _outcome_row(case, option, isin, symbol, vals, w, size, tax, whole, basis, h, rates, notes)


def _guard(con, isin: str, qty: float, price: float, day: date) -> Optional[str]:
    """The 12-month guard's sentence when selling now would be held back (a lot in gain turns long-term within the guard window), else None."""
    try:
        from pflab.core import exits
        return exits.guard_hold(con, day, isin, qty, price, exits.settings())
    except Exception:
        return None


def applicable(held: bool) -> List[str]:
    """The options that mean something for a name: all seven when it is held, the four without a position when it is not."""
    return list(think.OPTIONS) if held else ["freeze", "wait", "buy_in_parts", "nothing"]


def option_table(con, case_id: int, answer: dict, asof, *, root=None, kind: Optional[str] = None, move: Optional[float] = None, cache: Optional[dict] = None) -> List[dict]:
    """The menu with its rupees for each name of the model's answer: one row per (name, option), the model's own choice flagged (`track` "model", `chosen` true; the rest "alt"). The
    answer's likelihood WORDS go through `cases.probabilities` (the store's table) to scenario weights; everything else is code. A choice with no isin takes the case's."""
    asof = _day(asof)
    case = cases.get_case(con, case_id) or {}
    ans = norm_answer(answer)
    k0, m0, window = case_kind_move(con, case)
    probs = cases.probabilities(con)
    rows, by_name = [], {}
    for c in ans["choices"] or [{"isin": case.get("isin"), "symbol": case.get("symbol"), "option": None, "words": {}, "base_rate_set": None, "reason": ""}]:
        isin, symbol = c.get("isin") or case.get("isin"), c.get("symbol") or case.get("symbol")
        market = case.get("market") or "IN"
        pos = position(con, market, isin, symbol, asof, root)
        bset = c.get("base_rate_set")
        k = kind or (bset if bset and bset not in ("history", "own range", "own_range") else k0)
        key = (isin, k, bset == "own range")
        if key not in by_name:
            r = base_rates(con, k, move=move if move is not None else m0, isin=isin, asof=asof, market=market, symbol=symbol, window=window, root=root, cache=cache)
            if bset in ("own range", "own_range") and r["basis"] != "own range":
                own = own_range(con, market, isin, symbol, asof, PARAMS["base_rate_horizons"], root, n_found=r["history_n"])
                r = {**r, **{h: own[h] for h in PARAMS["base_rate_horizons"]}, "basis": "own range", "detail": "the model chose the name's own range (from its volatility)"}
            by_name[key] = r
        for opt in applicable(pos["held"]):
            try:
                o = outcomes(con, case, opt, isin=isin, asof=asof, words=c.get("words"), rates=by_name[key], market=market, symbol=symbol, root=root)
            except Exception as e:
                o = {"isin": isin, "symbol": symbol, "option": opt, "error": f"{type(e).__name__}: {e}", "worst_inr": 0.0, "likely_inr": 0.0, "best_inr": 0.0, "expected_inr": 0.0,
                     "worst_pct_book": 0.0, "size_inr": 0.0, "tax_inr": 0.0, "basis": by_name[key]["basis"]}
            o.update({"track": "model" if opt == c.get("option") else "alt", "chosen": opt == c.get("option"), "words": c.get("words"), "held": pos["held"],
                      "position_inr": pos["value_inr"], "probabilities": {w: probs[w] for w in think.WORDS}})
            rows.append(o)
    return rows
