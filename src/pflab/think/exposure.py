"""S85 L1 (2): exposure THROUGH FUNDS. The thinking loop asked "how much of this company do we hold?" and counted only the shares. A company that is 8% of the Nifty 500 is also in the book
when the book holds a Nifty 500 index ETF. Code only: no model, no cost.

    fund_exposure(con, day, isin, root=None) -> {"direct_inr", "via_funds_inr", "funds": [{"name", "weight", "inr"}], "total_inr", "total_pct_book", "uncovered": [...], "basis", "coverage"}
    via_funds(con, day, root=None) -> {isin: rupees through funds}      the whole map at once (cached for the day)
    index_weights(index, day, root=None, con=None) -> DataFrame[isin, symbol, weight, basis]   an INDEX'S weights, a labelled PROXY (see below)
    apply_to_scope(con, day, rows, whole, cfg, root)                    the watch's scope: direct + through funds (a hook in `watch.scope`)
    case_text(con, day, case) -> str                                    one sentence for a case's first message ("through funds the book holds about Rs ... of it")

Where the weights come from (nothing is guessed, every figure says what it is):
  1. a fund's own PORTFOLIO FILE in the store (`fund_holdings`: the AMC's monthly file, `pm/lookthrough.py`), the latest dated on or before the day: exact `pct_nav`.
  2. an INDEX FUND (`FUND_INDEX`: symbol -> index): the index's weights. The system stores index MEMBERSHIP, not index weights, so the weight is a PROXY: India = free-float market value
     (shares outstanding x (1 - promoter share) x the last close; the shareholding pattern as filed and public by the day), US = the median dollar traded value of the last 60 sessions.
     NIFTYBEES and JUNIORBEES: the Nifty 100's 50 largest and the 50 after them by the same proxy (the Nifty 50 and Next 50 lists are not stored). Labelled "proxy" everywhere it is shown.
  3. nothing: the fund counts as ZERO and is listed in `uncovered` with the reason (a gold fund holds no company; an international fund with no member list is not covered).
Point in time: the membership window, the shareholding lag (21 days) and every close are dated on or before `day`.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

FUND_INDEX = {"MONIFTY500": "NIFTY500", "NIFTYBEES": "NIFTY50", "JUNIORBEES": "NIFTYNEXT50", "SPY": "SP500"}   # fund symbol -> the index it tracks (his funds are not named here: the stored ETF set)
GOLD = ("GOLDBEES",)
LIQ_SESSIONS = 60
_CACHE: Dict[tuple, tuple] = {}
_MAX_CACHE = 8


def _root(root) -> Path:
    if root is None:
        from pflab.data import data_dir
        root = data_dir()
    return Path(root)


def _cache(key: tuple, build, ttl: Optional[float] = None):
    """A small cache; `ttl` (seconds) for what the book's own fills can change (the funds held), none for an index's weights of a past day."""
    import time
    hit = _CACHE.get(key)
    if hit is not None and (ttl is None or time.time() - hit[0] < ttl):
        return hit[1]
    v = build()
    if len(_CACHE) >= _MAX_CACHE:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = (time.time(), v)
    return v


def clear_cache() -> None:
    _CACHE.clear()


def settings() -> dict:
    from pflab import think
    s = think.settings()
    out = {"fund_exposure": bool(s.get("fund_exposure", True)), "fund_index": dict(FUND_INDEX)}
    extra = s.get("fund_index")
    if isinstance(extra, dict):
        out["fund_index"].update({str(k).upper(): str(v).upper() for k, v in extra.items()})
    return out


# --- an index's weights (a proxy) ---------------------------------------------------------------------------------------------------------------------------------------------

def _members_in(index: str, day: date, root: Path) -> pd.DataFrame:
    from pflab.data import index_membership as im
    t = im.load(index, root)
    ids = im.members_at(t, index, day)
    cur = t[t["isin"].isin(ids)].drop_duplicates("isin", keep="last")
    return cur[["isin", "symbol"]].reset_index(drop=True)


def _caps_in(con, root: Path, isins: List[str], day: date) -> Dict[str, float]:
    """The free-float market value proxy of each name (rupees): shares outstanding x (1 - promoter share) x the last close. A name with no shares figure is left out (the caller fills it)."""
    from pflab.lab import screen
    out: Dict[str, float] = {}
    try:
        px = screen.india_closes(con, root, isins, day, days=40)
        scr = screen.scrip_map(root, day)
        sh = screen.shareholding(root, {i: scr[i] for i in isins if i in scr}, day)
    except Exception:
        return out
    for i in isins:
        s, d = px.get(i), sh.get(i)
        if s is None or not len(s) or not d or not d.get("shares_outstanding"):
            continue
        ff = 1.0 - (float(d["promoter_pct"]) / 100.0 if d.get("promoter_pct") is not None else 0.0)
        out[i] = float(d["shares_outstanding"]) * max(ff, 0.05) * float(s.iloc[-1])
    return out


def _weights_in(con, index: str, day: date, root: Path) -> pd.DataFrame:
    base = {"NIFTY50": "NIFTY100", "NIFTYNEXT50": "NIFTY100"}.get(index, index)
    m = _members_in(base, day, root)
    if m.empty:
        return pd.DataFrame(columns=["isin", "symbol", "weight", "basis"])
    caps = _caps_in(con, root, list(m["isin"]), day)
    known = [v for v in caps.values() if v > 0]
    fill = float(np.median(known)) if known else 1.0
    m["cap"] = [caps.get(i, fill) for i in m["isin"]]
    n_missing = int(sum(1 for i in m["isin"] if i not in caps))
    m = m.sort_values("cap", ascending=False).reset_index(drop=True)
    if index == "NIFTY50":
        m = m.head(50)
    elif index == "NIFTYNEXT50":
        m = m.iloc[50:100]
    m["weight"] = m["cap"] / m["cap"].sum() if m["cap"].sum() > 0 else 0.0
    m["basis"] = (f"proxy: free-float market value from the shareholding pattern and the last close; {n_missing} of {len(m)} names had no shares figure and take the median"
                  + ("; the 50 largest of the Nifty 100 stand in for the Nifty 50" if index == "NIFTY50" else "; ranks 51-100 of the Nifty 100 stand in for the Nifty Next 50" if index == "NIFTYNEXT50" else ""))
    return m[["isin", "symbol", "weight", "basis"]]


def us_members(root: Path) -> List[str]:
    """The S&P 500 universe as the system stores it: the symbols under `data/us/raw` (the backfill of today's members) less the ETFs. Today's list: survivorship-biased, labelled."""
    from pflab.data import us_prices
    from pflab.lab import screen
    return [s for s in screen._us_cached_symbols(root) if s not in us_prices.ETFS and s != "SPY"]


def _weights_us(con, day: date, root: Path) -> pd.DataFrame:
    from pflab import _duck
    syms = us_members(root)
    p = root / "us" / "prices.parquet"
    if not syms or not p.exists():
        return pd.DataFrame(columns=["isin", "symbol", "weight", "basis"])
    lo = day - timedelta(days=100)
    lst = ",".join(f"'{s}'" for s in syms)
    d = _duck.sql(f"SELECT symbol, median(turnover) AS v FROM '{p.as_posix()}' WHERE symbol IN ({lst}) AND date >= DATE '{lo}' AND date <= DATE '{day}' AND turnover > 0 GROUP BY symbol").df()
    if d.empty:
        return pd.DataFrame(columns=["isin", "symbol", "weight", "basis"])
    ciks = {}
    try:
        from pflab.us import instruments as uins
        ciks = uins.load_ciks(root)
    except Exception:
        pass
    from pflab.us import instruments as uins
    d["isin"] = [uins.key_for(con, s, ciks) if con is not None else f"US:{s}" for s in d["symbol"]]
    d["weight"] = d["v"] / d["v"].sum()
    d["basis"] = "proxy: median dollar traded value over the last 60 sessions of the stored S&P 500 universe (today's members: survivorship-biased)"
    return d[["isin", "symbol", "weight", "basis"]].sort_values("weight", ascending=False).reset_index(drop=True)


def index_weights(index: str, day: date, root=None, con=None) -> pd.DataFrame:
    """[isin, symbol, weight (adds to 1), basis] for NIFTY500, NIFTY100, NIFTY50, NIFTYNEXT50 or SP500 on `day` (a PROXY, see the module text). An unknown index or missing data gives an empty frame."""
    root = _root(root)

    def build():
        try:
            return _weights_us(con, day, root) if index == "SP500" else _weights_in(con, index, day, root)
        except Exception:
            return pd.DataFrame(columns=["isin", "symbol", "weight", "basis"])
    return _cache(("w", index, day, str(root)), build)


# --- the funds the book holds -------------------------------------------------------------------------------------------------------------------------------------------------

def _whole(con, day: date, root=None) -> float:
    from pflab.think import watch
    return watch._whole_inr(con, day, root)


def _is_gold(symbol: str) -> bool:
    """A gold fund holds no company: the configured gold ETFs (`[baseline_v2] gold_etfs`) or a symbol that says gold."""
    sym = str(symbol).upper()
    try:
        from pflab import core
        listed = [str(x).upper() for x in (core.settings().get("baseline_v2") or {}).get("gold_etfs", [])]
    except Exception:
        listed = []
    return sym in GOLD or sym in listed or "GOLD" in sym or "GLD" in sym


def _held_funds(con, day: date, root=None) -> List[dict]:
    """The funds the book holds on `day`: [{isin, symbol, name, value_inr, market}] (India ETFs and funds by their INF ISIN; US ETFs by the stored symbol map)."""
    from pflab.think import watch
    out = []
    for r in watch._held_in(con, day):
        if str(r["isin"]).startswith("INF") or str(r.get("asset_class") or "").lower() in ("etf", "mutual_fund", "equity_fund"):
            out.append({"isin": r["isin"], "symbol": r["symbol"], "name": r["symbol"], "value_inr": float(r["value_inr"]), "market": "IN"})
    fi = settings()["fund_index"]
    for r in watch._us_held(con, day, root):
        if str(r["symbol"]).upper() in fi:
            out.append({"isin": r["isin"], "symbol": r["symbol"], "name": r["symbol"], "value_inr": float(r["value_inr"]), "market": "US"})
    return out


def _portfolio_file(con, fund_isin: str, day: date) -> Optional[dict]:
    try:
        r = con.execute("SELECT max(as_of) FROM fund_holdings WHERE fund_isin=? AND as_of <= ?", [fund_isin, day]).fetchone()
        if not r or r[0] is None:
            return None
        rows = con.execute("SELECT isin, pct_nav FROM fund_holdings WHERE fund_isin=? AND as_of=? AND isin IS NOT NULL", [fund_isin, r[0]]).fetchall()
    except Exception:
        return None
    w = {i: float(p) / 100.0 for i, p in rows if p is not None and float(p) > 0}
    return {"weights": w, "as_of": str(r[0]), "basis": f"the fund's own portfolio file of {r[0]}"} if w else None


def fund_weights(con, day: date, root=None) -> dict:
    """{"funds": {fund_isin: {symbol, name, value_inr, market, weights: {isin: weight of the fund's value}, basis}}, "uncovered": [{"symbol", "inr", "why"}], "whole_inr"}. Cached per day and store."""
    root = _root(root)

    def build():
        funds: Dict[str, dict] = {}
        unc: List[dict] = []
        for f in _held_funds(con, day, root):
            pf = _portfolio_file(con, f["isin"], day)
            if pf:
                funds[f["isin"]] = {**f, "weights": pf["weights"], "basis": pf["basis"]}
                continue
            idx = settings()["fund_index"].get(str(f["symbol"]).upper())
            if idx:
                w = index_weights(idx, day, root, con)
                if len(w):
                    funds[f["isin"]] = {**f, "weights": dict(zip(w["isin"], w["weight"])), "basis": f"{idx} weights ({w['basis'].iloc[0]})"}
                    continue
                unc.append({"symbol": f["symbol"], "inr": f["value_inr"], "why": f"no member data for {idx}"})
                continue
            unc.append({"symbol": f["symbol"], "inr": f["value_inr"], "why": "gold: holds no company" if _is_gold(f["symbol"]) else "no holdings data (no portfolio file, not a stored index)"})
        return {"funds": funds, "uncovered": unc}
    out = dict(_cache(("f", day, str(root)), build, ttl=600.0))
    out["whole_inr"] = _whole(con, day, root)
    return out


def via_funds(con, day: date, root=None) -> Dict[str, float]:
    """isin -> rupees the book holds in it THROUGH funds (a labelled estimate)."""
    fw = fund_weights(con, day, root)
    out: Dict[str, float] = {}
    for f in fw["funds"].values():
        for i, w in f["weights"].items():
            out[i] = out.get(i, 0.0) + float(w) * f["value_inr"]
    return out


def _direct(con, day: date, isin: str, root=None) -> float:
    from pflab.think import watch
    for r in watch._held_in(con, day):
        if r["isin"] == isin:
            return float(r["value_inr"])
    for r in watch._us_held(con, day, root):
        if r["isin"] == isin:
            return float(r["value_inr"])
    return 0.0


def fund_exposure(con, day: date, isin: str, root=None) -> dict:
    """The book's exposure to one company, direct and through funds, in rupees and as a share of the whole book (estimates; the proxy and what is not covered are stated)."""
    fw = fund_weights(con, day, root)
    whole = float(fw["whole_inr"] or 0.0)
    rows = []
    for f in fw["funds"].values():
        w = float(f["weights"].get(isin, 0.0))
        if w > 0:
            rows.append({"name": f["name"], "symbol": f["symbol"], "weight": w, "inr": w * f["value_inr"], "basis": f["basis"]})
    rows.sort(key=lambda r: -r["inr"])
    direct = _direct(con, day, isin, root)
    via = float(sum(r["inr"] for r in rows))
    held = len(fw["funds"]) + len(fw["uncovered"])
    return {"direct_inr": direct, "via_funds_inr": via, "funds": rows, "total_inr": direct + via, "total_pct_book": (direct + via) / whole if whole > 0 else 0.0,
            "uncovered": list(fw["uncovered"]), "coverage": f"{len(fw['funds'])} of {held} held funds have holdings data" if held else "the book holds no fund",
            "basis": "estimate: " + ("; ".join(sorted({r['basis'] for r in rows})) if rows else "no held fund holds this company, as far as the stored data shows")}


def apply_to_scope(con, day: date, rows: List[dict], whole: float, cfg: dict, root=None) -> None:
    """The watch's scope with the funds in: a held name's exposure is its shares PLUS what the funds hold of it; a name not held but inside a held fund counts at that (real, estimated) rupee figure
    instead of the stand-in. Every row gets `via_funds_inr`. No held fund, no work. Never raises (the scope is the caller's)."""
    if not settings()["fund_exposure"]:
        return
    try:
        if not _held_funds(con, day, root):
            return
        via = via_funds(con, day, root)
    except Exception:
        return
    for e in rows:
        v = float(via.get(e["isin"], 0.0))
        e["via_funds_inr"] = v
        if v <= 0:
            continue
        if e.get("held"):
            e["direct_inr"] = float(e["exposure_inr"])
            e["exposure_inr"] = float(e["exposure_inr"]) + v
            e["exposure_basis"] = "held (shares plus through funds: estimate)"
        else:
            e["exposure_inr"] = max(float(e["exposure_inr"]), v)
            e["exposure_basis"] = "through funds the book holds (estimate; the name itself is not held)"
        e["exposure_pct"] = e["exposure_inr"] / whole if whole > 0 else 0.0


def case_text(con, day: date, case: dict, root=None) -> str:
    """A sentence for the case's first message: the part of the exposure that comes through funds, with the estimate and the funds with no data named. Empty when the book holds no fund."""
    isin = case.get("isin")
    if not isin or str(isin).startswith(("MARKET:", "MACRO:", "STORY:")) or not settings()["fund_exposure"]:
        return ""
    try:
        if not _held_funds(con, day, root):
            return ""
        x = fund_exposure(con, day, isin, root)
    except Exception:
        return ""
    unc = ("; funds with no holdings data (counted as zero): " + ", ".join(u["symbol"] for u in x["uncovered"])) if x["uncovered"] else ""
    if x["via_funds_inr"] <= 0:
        return f" Through funds the book holds none of it as far as the stored data shows ({x['coverage']}){unc}."
    names = ", ".join(f"{r['symbol']} ({r['weight']:.1%})" for r in x["funds"][:3])
    return f" Through funds (exposure_via_funds_inr) the book holds about Rs {x['via_funds_inr']:,.0f} of it ({names}; an estimate from index weights proxied by free-float value){unc}."
