"""Macro attribution (S79b item 15): split one session's index move into parts that add up, by code.

    index move (%) = crude + currency + us10y + nasdaq + flows + asia + unexplained          (IN; the US has no nasdaq and no flows part)

The index is the Nifty 500 total-return index for IN and the S&P 500 for US. Each part is `beta x the factor's move that session`.

METHOD (stated, fixed before any look at the results).  For the session M the betas come from a multivariate RIDGE regression of the index's daily
move on the factors' moves over the WINDOW (250) sessions BEFORE M; M itself and anything later is never in the fit (point in time: a later row never
changes an earlier attribution). Each factor is standardised on the window, the ridge penalty is RIDGE = 0.02 of the unit diagonal of the factors' correlation
matrix (just enough to keep correlated factors from swapping signs; a fixed constant, not tuned), the intercept is fitted and NOT shown as a part: it
lands in "unexplained". The beta of a factor is the standardised coefficient divided back by the factor's standard deviation, so the part is in the
index's own percent. unexplained = move - sum(parts), so the parts always add up to the move, by construction. A factor with no value for the session, or
fewer than MIN_N = 20 paired observations in the window, has NO part (pct is null, the reason is in `note`): it is "unavailable", never invented, and the
other betas are refitted without it. Under MIN_N the count is given and no conclusion is drawn.

Factors and the calendar (a part is an association worked by code, not a proof of cause; flows and the rupee also respond to the market):
  crude    Brent (IN) / WTI (US), percent move.      IN: the US/ICE session that closed before the NSE opened (`transmission.source_session`).
  currency USDINR (IN) / the dollar index (US), percent move, same calendar date.   (a rise in USDINR = a weaker rupee)
  us10y    10-year Treasury yield, change in basis points.   IN: the overnight US session. US: same date.
  nasdaq   Nasdaq composite, percent move, the overnight US session (IN only).
  flows    foreign portfolio net equity buying, Rs 1,000 crore, for the NSE session it describes (IN only). NSDL's history (2009-12 on) is reported on the NEXT
           business day; for the sessions it has not reported, NSE's provisional FII cash figure (collected from 2026-10) is used, out the same evening. Until one
           of them is in, this part is unavailable. `known_on` says when each became knowable.
  asia     the average percent move of Kospi, Taiex, Nikkei 225 and Hang Seng that closed on the same date (at least two must have a value).
Series are stitched from the long FRED history (data/macro) and the newer Yahoo history (data/global) where both exist; a missing file just removes that part.

Stored per session in `macro_attribution` (market, session, part, pct, beta, factor_move, unit, n, r2, as_of, ...) by `write`.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab import markets

WINDOW = 250
MIN_N = 20
RIDGE = 0.02
MAX_GAP_DAYS = 7
ASIA_KEYS = ("KR_KOSPI", "TW_TAIEX", "JP_NIKKEI225", "HK_HANGSENG")
ASIA_MIN = 2
INDEX_KEY = {"IN": ("indices", "NIFTY500_TRI"), "US": ("global", "US_SP500")}
INDEX_NAME = {"IN": "Nifty 500 TRI", "US": "S&P 500"}
METHOD = (f"ridge OLS on the {WINDOW} sessions before the session (lambda {RIDGE} of the standardised diagonal), intercept in 'unexplained', "
          f"factors with under {MIN_N} paired observations dropped")

# factor name -> (label, unit, kind, timing).  kind: pct | bps | flow.  timing: same | overnight | flow
FACTORS: Dict[str, Dict[str, tuple]] = {
    "IN": {"crude": ("Brent crude", "% move", "pct", "overnight"), "currency": ("USDINR (rupee per dollar)", "% move", "pct", "same"),
           "us10y": ("US 10-year yield", "bp change", "bps", "overnight"), "nasdaq": ("Nasdaq (overnight US)", "% move", "pct", "overnight"),
           "flows": ("foreign net equity buying", "Rs 1,000 cr", "flow", "flow"), "asia": ("Asian peers (Kospi, Taiex, Nikkei, Hang Seng)", "% move", "pct", "same")},
    "US": {"crude": ("WTI crude", "% move", "pct", "same"), "currency": ("dollar index", "% move", "pct", "same"),
           "us10y": ("US 10-year yield", "bp change", "bps", "same"), "asia": ("Asian peers (Kospi, Taiex, Nikkei, Hang Seng)", "% move", "pct", "same")},
}
PARTS_ORDER = ("crude", "currency", "us10y", "nasdaq", "flows", "asia")
# part -> [(folder, key, column), ...] first is the long history, the next ones extend it past its last date
SOURCES = {
    ("IN", "crude"): [("macro", "BRENT", "value"), ("global", "BRENT_FUT", "close")],
    ("US", "crude"): [("macro", "WTI", "value"), ("global", "WTI", "close")],
    ("IN", "currency"): [("macro", "USDINR", "value"), ("global", "FX_USDINR", "close")],
    ("US", "currency"): [("global", "DOLLAR_INDEX", "close")],
    ("IN", "us10y"): [("macro", "US10Y", "value"), ("global", "US_10Y_YIELD", "close")],
    ("US", "us10y"): [("macro", "US10Y", "value"), ("global", "US_10Y_YIELD", "close")],
    ("IN", "nasdaq"): [("global", "US_NASDAQ", "close"), ("macro", "US_NASDAQ", "value")],
}


# --- series --------------------------------------------------------------------------------------------------------------

def _read(root: Path, folder: str, key: str, col: str) -> Optional[pd.Series]:
    p = Path(root) / folder / f"{key}.parquet"
    if not p.exists():
        return None
    try:
        d = pd.read_parquet(p)
        if col not in d.columns:
            col = "close" if "close" in d.columns else ("value" if "value" in d.columns else None)
            if col is None:
                return None
        s = pd.Series(pd.to_numeric(d[col], errors="coerce").to_numpy(float), index=pd.to_datetime(d["date"]).dt.date)
    except Exception:
        return None
    s = s[s.notna() & (s > 0)]
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s if len(s) >= 2 else None


def level_series(root: Path, market: str, part: str) -> Optional[pd.Series]:
    """Levels for a factor: the first source with data, extended past its last date by the later sources rescaled at the join (a different feed of the same thing)."""
    srcs = SOURCES.get((market, part), [])
    base = None
    for folder, key, col in srcs:
        s = _read(root, folder, key, col)
        if s is None:
            continue
        if base is None:
            base = s
            continue
        later = s[s.index > base.index[-1]]
        if later.empty:
            continue
        ov = s[s.index <= base.index[-1]]
        if ov.empty:
            continue
        j = ov.index[-1]
        scale = base[base.index[-1]] / ov[j] if (base.index[-1] - j).days <= 5 else 1.0
        base = pd.concat([base, later * scale])
    return base


def moves_of(levels: Optional[pd.Series], kind: str) -> pd.Series:
    """Move per row date vs the previous row: percent (pct), basis points (bps). NaN where the previous row is more than MAX_GAP_DAYS back."""
    if levels is None or len(levels) < 2:
        return pd.Series(dtype=float)
    d = pd.to_datetime(pd.Series(list(levels.index)))
    gap = (d - d.shift(1)).dt.days.to_numpy()
    v = levels.to_numpy(float)
    prev = np.r_[np.nan, v[:-1]]
    m = (v / prev - 1.0) * 100.0 if kind == "pct" else (v - prev) * 100.0
    m = np.where(gap <= MAX_GAP_DAYS, m, np.nan)
    return pd.Series(m, index=levels.index)


def index_moves(root: Path, market: str) -> pd.Series:
    folder, key = INDEX_KEY[market]
    return moves_of(_read(root, folder, key, "close"), "pct")


def asia_moves(root: Path) -> pd.Series:
    """Average percent move of the Asian peers per date (needs at least ASIA_MIN of them that day)."""
    cols = [moves_of(_read(root, "global", k, "close"), "pct").rename(k) for k in ASIA_KEYS]
    cols = [c for c in cols if len(c)]
    if not cols:
        return pd.Series(dtype=float)
    df = pd.concat(cols, axis=1)
    return df.mean(axis=1).where(df.notna().sum(axis=1) >= ASIA_MIN)


def _nsdl_flows(root: Path, market: str = "IN") -> pd.Series:
    """NSDL's daily FPI equity net (Rs 1,000 crore) by the session it describes: the row dated D covers trading up to the previous business day, so the
    session is the one before D and the value is knowable at D."""
    p = Path(root) / "macro" / "FPI_DAILY.parquet"
    if market != "IN" or not p.exists():
        return pd.Series(dtype=float)
    try:
        f = pd.read_parquet(p)
        f = f[(f["asset"] == "Equity") & (f["route"] == "Sub-total")]
        rep = pd.to_datetime(f["report_date"]).dt.date.to_numpy()
        net = pd.to_numeric(f["net_cr"], errors="coerce").to_numpy(float) / 1000.0
    except Exception:
        return pd.Series(dtype=float)
    m = markets.get(market)
    out = {}
    for r, v in zip(rep, net):
        if not np.isfinite(v):
            continue
        try:
            out[m.previous_session(r)] = float(v)
        except Exception:
            continue
    s = pd.Series(out, dtype=float).sort_index()
    return s[~s.index.duplicated(keep="last")]


def _nse_flows(root: Path, market: str = "IN") -> pd.Series:
    """NSE's provisional FII cash net (data/flows/FII_DII_CASH.parquet, the S79b collector): the row dated D is session D itself, published the same evening.
    It holds only the latest ~20 sessions and grows from there, so it serves the sessions the NSDL file does not have yet."""
    p = Path(root) / "flows" / "FII_DII_CASH.parquet"
    if market != "IN" or not p.exists():
        return pd.Series(dtype=float)
    try:
        f = pd.read_parquet(p)
        s = pd.Series(pd.to_numeric(f["fii_net_cr"], errors="coerce").to_numpy(float) / 1000.0, index=pd.to_datetime(f["date"]).dt.date).dropna()
    except Exception:
        return pd.Series(dtype=float)
    return s[~s.index.duplicated(keep="last")].sort_index()


def flows_by_session(root: Path, market: str = "IN") -> pd.Series:
    """Foreign net equity buying in Rs 1,000 crore, indexed by the NSE SESSION it describes: NSDL's FPI equity history (2009-12 onward, knowable the next business
    day), then NSE's provisional FII cash figure for the sessions NSDL has not reported yet (knowable that evening; a slightly narrower measure: exchange cash only). Empty when neither file is there."""
    a, b = _nsdl_flows(root, market), _nse_flows(root, market)
    if len(b):
        b = b[~b.index.isin(a.index) & (b.index > (a.index[-1] if len(a) else date(1900, 1, 1)))]
    out = pd.concat([a, b]).sort_index()
    return out[~out.index.duplicated(keep="last")]


def flow_known_dates(root: Path, market: str = "IN") -> Dict[date, date]:
    """When each session's flow becomes knowable: the next business day for an NSDL figure, the session's own evening for NSE's provisional figure."""
    a, b = _nsdl_flows(root, market), _nse_flows(root, market)
    m = markets.get(market)
    out = {}
    for d in a.index:
        out[d] = m.next_session(d)
    for d in b.index:
        if d not in out and (len(a) == 0 or d > a.index[-1]):
            out[d] = d
    return out


def flows_known_on(market: str, session: date, root: Optional[Path] = None) -> date:
    if root is not None:
        k = flow_known_dates(root, market).get(session)
        if k is not None:
            return k
    return markets.get(market).next_session(session)


def overnight_map(market: str, sessions) -> Dict[date, date]:
    from pflab.quant import transmission as tr
    return {m: tr.source_session(market, m) for m in sessions}


class Design:
    """The index move and every factor's move, one row per index session (aligned to the market calendar of the index file)."""

    def __init__(self, root: Path, market: str = "IN", tail: Optional[int] = None):
        self.market = market
        y = index_moves(root, market)
        self.y = y.dropna() if tail is None else y.dropna().iloc[-int(tail):]
        self.dates: List[date] = list(self.y.index)
        specs = FACTORS.get(market, {})
        cols = {}
        omap = overnight_map(market, self.dates) if any(v[3] == "overnight" for v in specs.values()) else {}
        for name, (_label, _unit, kind, timing) in specs.items():
            if name == "asia":
                s = asia_moves(root)
            elif name == "flows":
                s = flows_by_session(root, market)
            else:
                s = moves_of(level_series(root, market, name), kind)
            if s is None or len(s) == 0:
                cols[name] = pd.Series(np.nan, index=self.dates)
                continue
            s = s[~s.index.duplicated(keep="last")]
            key = [omap.get(d, d) for d in self.dates] if timing == "overnight" else self.dates
            cols[name] = pd.Series(s.reindex(key).to_numpy(float), index=self.dates)
        self.X = pd.DataFrame(cols, index=self.dates)
        self.flow_known = flow_known_dates(root, market) if "flows" in specs else {}
        self.names = list(specs)
        self._yv = self.y.to_numpy(float)
        self._Xv = self.X.to_numpy(float)
        self._pos = {d: i for i, d in enumerate(self.dates)}

    def has(self, session: date) -> bool:
        return session in self._pos

    def attribute(self, session: date) -> dict:
        i = self._pos.get(session)
        if i is None:
            return {"market": self.market, "session": str(session), "note": f"no {INDEX_NAME[self.market]} move for {session} in the files on this PC"}
        lo = max(0, i - WINDOW)
        yw, Xw = self._yv[lo:i], self._Xv[lo:i]
        xm = self._Xv[i]
        total = float(self._yv[i])
        out = {"market": self.market, "session": str(session), "index": INDEX_NAME[self.market], "total_pct": round(total, 4), "window": f"{len(yw)} sessions before {session}",
               "method": METHOD, "parts": {}}
        avail = []
        for k, name in enumerate(self.names):
            label, unit, _kind, _t = FACTORS[self.market][name]
            part = {"label": label, "unit": unit, "pct": None, "beta": None, "factor_move": None, "n": 0, "note": ""}
            if not np.isfinite(xm[k]):
                part["note"] = "unavailable: no value for the factor that session" + (" (the foreign-flow report for it is not in yet)" if name == "flows" else "")
            else:
                part["factor_move"] = float(xm[k])
                ok = np.isfinite(yw) & np.isfinite(Xw[:, k])
                part["n"] = int(ok.sum())
                if part["n"] < MIN_N:
                    part["note"] = f"under {MIN_N} paired observations (n={part['n']}): no conclusion"
                else:
                    avail.append(k)
            out["parts"][name] = part
        r2 = None
        n_fit = 0
        while avail:                                           # drop the thinnest factor until the complete rows are enough
            ok = np.isfinite(yw) & np.isfinite(Xw[:, avail]).all(axis=1)
            n_fit = int(ok.sum())
            if n_fit >= MIN_N:
                break
            worst = min(avail, key=lambda k: int((np.isfinite(yw) & np.isfinite(Xw[:, k])).sum()))
            out["parts"][self.names[worst]]["note"] = f"too few rows where every factor is present (n={n_fit}): left out of the fit"
            avail.remove(worst)
        if avail:
            A, b = Xw[ok][:, avail], yw[ok]
            mu, sd = A.mean(axis=0), A.std(axis=0)
            keep = sd > 1e-12
            for j, k in enumerate(avail):
                if not keep[j]:
                    out["parts"][self.names[k]]["note"] = "the factor did not move in the window: no beta"
            avail = [k for j, k in enumerate(avail) if keep[j]]
            A, mu, sd = A[:, keep], mu[keep], sd[keep]
            if avail:
                Z = (A - mu) / sd
                yc = b - b.mean()
                n = len(b)
                c = np.linalg.solve(Z.T @ Z / n + RIDGE * np.eye(len(avail)), Z.T @ yc / n)
                beta = c / sd
                sst = float((yc ** 2).sum())
                sse = float(((yc - Z @ c) ** 2).sum())
                r2 = (1.0 - sse / sst) if sst > 0 else None
                for j, k in enumerate(avail):
                    p = out["parts"][self.names[k]]
                    p["beta"] = float(beta[j])
                    p["pct"] = float(beta[j] * xm[k])
                    p["n"] = n_fit
        if "flows" in out["parts"] and out["parts"]["flows"]["pct"] is not None and session in self.flow_known:
            out["parts"]["flows"]["known_on"] = str(self.flow_known[session])
        for p in out["parts"].values():                         # rounded first, so the figures shown add up exactly
            for k in ("pct", "beta", "factor_move"):
                if p[k] is not None:
                    p[k] = round(float(p[k]), 6)
        total_r = round(total, 6)
        explained = sum(p["pct"] for p in out["parts"].values() if p["pct"] is not None)
        out["total_pct"] = total_r
        out["unexplained_pct"] = round(total_r - explained, 6)
        out["explained_pct"] = round(explained, 6)
        out["r2_window"] = None if r2 is None else round(float(r2), 3)
        out["n_fit"] = int(n_fit)
        out["checks_out"] = abs(explained + out["unexplained_pct"] - total_r) < 1e-6
        return out


def attribute_sessions(root: Path, market: str, sessions: Optional[List[date]] = None, start: Optional[date] = None, end: Optional[date] = None,
                       design: Optional[Design] = None) -> List[dict]:
    d = design or Design(root, market)
    if sessions is None:
        sessions = [x for x in d.dates if (start is None or x >= start) and (end is None or x <= end)]
    return [d.attribute(s) for s in sessions]


def attribute_session(root: Path, market: str, session: date, design: Optional[Design] = None) -> dict:
    return (design or Design(root, market)).attribute(session)


def dominant(a: dict) -> Optional[str]:
    """The part with the largest absolute size (or 'unexplained'), for the note."""
    best, name = abs(a.get("unexplained_pct") or 0.0), "unexplained"
    for k, p in (a.get("parts") or {}).items():
        if p.get("pct") is not None and abs(p["pct"]) > best:
            best, name = abs(p["pct"]), k
    return name


# --- the table -----------------------------------------------------------------------------------------------------------

def rows_of(a: dict, as_of: Optional[date] = None) -> List[tuple]:
    """Table rows (market, session, part, pct, beta, factor_move, unit, n, r2, window, method, note, as_of) of one attribution, 'total' and 'unexplained' included."""
    if "total_pct" not in a:
        return []
    m, s = a["market"], date.fromisoformat(a["session"])
    asof = as_of or s
    out = [(m, s, "total", a["total_pct"], None, None, "% move", a.get("n_fit"), a.get("r2_window"), a.get("window"), METHOD, "", asof)]
    for name in PARTS_ORDER:
        p = a["parts"].get(name)
        if p is None:
            continue
        pa = asof
        if name == "flows" and p["pct"] is not None:
            pa = max(asof, date.fromisoformat(p["known_on"]) if p.get("known_on") else flows_known_on(m, s))
        out.append((m, s, name, p["pct"], p["beta"], p["factor_move"], p["unit"], p["n"], a.get("r2_window"), a.get("window"), METHOD, p["note"], pa))
    out.append((m, s, "unexplained", a["unexplained_pct"], None, None, "% move", a.get("n_fit"), a.get("r2_window"), a.get("window"), METHOD, "move minus the parts", asof))
    return out


def write(con, a: dict, now: Optional[datetime] = None, as_of: Optional[date] = None) -> int:
    rows = rows_of(a, as_of)
    if not rows:
        return 0
    now = now or datetime.now()
    m, s = rows[0][0], rows[0][1]
    con.execute("DELETE FROM macro_attribution WHERE market=? AND session=?", [m, s])
    for r in rows:
        con.execute("INSERT INTO macro_attribution (market, session, part, pct, beta, factor_move, unit, n, r2, window_desc, method, note, as_of, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [*r, now])
    return len(rows)


def read(con, market: str, session: date) -> Optional[dict]:
    """The stored attribution of a session (same shape as `attribute`), or None."""
    rs = con.execute("SELECT part, pct, beta, factor_move, unit, n, r2, window_desc, note, as_of FROM macro_attribution WHERE market=? AND session=?",
                     [market, session]).fetchall()
    if not rs:
        return None
    parts, total, unexp, r2, win = {}, None, None, None, None
    for part, pct, beta, fm, unit, n, r, w, note, as_of in rs:
        r2, win = r, w
        if part == "total":
            total = pct
        elif part == "unexplained":
            unexp = pct
        else:
            parts[part] = {"pct": pct, "beta": beta, "factor_move": fm, "unit": unit, "n": n, "note": note, "known_on": str(as_of)}
    return {"market": market, "session": str(session), "total_pct": total, "unexplained_pct": unexp, "parts": parts, "r2_window": r2, "window": win}


def missing_sessions(con, root: Path, market: str, upto: date, backfill: int = 60, design: Optional[Design] = None) -> List[date]:
    """Sessions to (re)write: closed sessions without rows (the last `backfill` of them when the table is empty), and recent ones whose flows part was
    empty but whose foreign-flow report has since arrived."""
    d = design or Design(root, market)
    have = {r[0] for r in con.execute("SELECT DISTINCT session FROM macro_attribution WHERE market=?", [market]).fetchall()}
    cand = [x for x in d.dates if x <= upto]
    if not have:
        return cand[-backfill:]
    recent = cand[-backfill:]
    todo = [x for x in cand[-250:] if x not in have and (x > max(have) or x >= recent[0])]       # every missed session since the last write (up to a year), and holes in the recent window
    if "flows" in d.names:
        fl = d.X["flows"]
        pend = {r[0] for r in con.execute("SELECT session FROM macro_attribution WHERE market=? AND part='flows' AND pct IS NULL", [market]).fetchall()}
        todo += [x for x in pend if x in d._pos and math.isfinite(fl.iloc[d._pos[x]])]
    return sorted(set(todo))


def catch_up(con, root: Path, market: str, upto: date, now: Optional[datetime] = None, backfill: int = 60) -> dict:
    d = Design(root, market)
    todo = missing_sessions(con, root, market, upto, backfill, d)
    n = 0
    for s in todo:
        n += 1 if write(con, d.attribute(s), now) else 0
    return {"market": market, "sessions_written": n, "latest": str(todo[-1]) if todo else None, "index_through": str(d.dates[-1]) if d.dates else None}
