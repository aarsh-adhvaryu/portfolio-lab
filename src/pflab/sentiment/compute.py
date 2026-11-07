"""The sentiment table (S79b item 15b): per (market, theme, day) each component, its z-score against its own trailing history (strictly before the day: point in time) and
a transparent combined score.

Signs (a positive score is "risk-on", a negative one "risk-off"): news tone +, priced fear -, positioning +.
    tone_score  = mean of the z of tone_gdelt (GKG articles of the theme), tone_country (GDELT's country tone), tone_model (the local model's tags, forward-only)
    fear_score  = mean of (-z) of fear_vix, fear_pcr, fear_skew, proxy_vol (the realised volatility of the theme's primary price proxy)
    pos_score   = mean of z of pos_flow (FII cash), pos_fut (FII index futures), pos_dii (DII index futures), pos_oi (stock-futures build-up), pos_breadth
    combined    = mean of the group scores that exist; n_groups and n_comp say how many groups and components stood behind it.
No weights are fitted. A component with too little history shows its value and no z (the minimum is `z_min`, or `z_min_tone` for the short tone histories).

The PRICE-BASED score (fear_vix/pcr/skew + positioning, no tone, no proxy) is theme-independent and the only part that exists for history: `price_score` feeds the
lens and `extreme_sentiment_events` (pre-registered in docs/protocols/s79_wave_sentiment_protocol.md)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from pflab import sentiment as S
from pflab.sentiment import fear, positioning, themes as T, tone, zscore_pit, stale_align

SIGN = {"tone_gdelt": 1, "tone_country": 1, "tone_model": 1, "fear_vix": -1, "fear_pcr": -1, "fear_skew": -1, "proxy_vol": -1,
        "pos_flow": 1, "pos_fut": 1, "pos_dii": 1, "pos_dii_cash": 1, "pos_oi": 1, "pos_breadth": 1}
GROUPS = {"tone": ("tone_gdelt", "tone_country", "tone_model"), "fear": ("fear_vix", "fear_pcr", "fear_skew", "proxy_vol"),
          "pos": ("pos_flow", "pos_fut", "pos_dii", "pos_dii_cash", "pos_oi", "pos_breadth")}
PRICE_GROUPS = {"fear": ("fear_vix", "fear_pcr", "fear_skew"), "pos": GROUPS["pos"]}
SHORT_HISTORY = ("tone_gdelt", "tone_model", "pos_dii_cash")
COLUMNS = (["market", "theme", "day", "tone_gdelt", "tone_gdelt_z", "tone_gdelt_n", "tone_country", "tone_country_z", "tone_model", "tone_model_z", "tone_model_n",
            "fear_vix", "fear_vix_z", "fear_pcr", "fear_pcr_z", "fear_skew", "fear_skew_z", "proxy_vol", "proxy_vol_z",
            "pos_flow", "pos_flow_z", "pos_fut", "pos_fut_z", "pos_dii", "pos_dii_z", "pos_dii_cash", "pos_dii_cash_z", "pos_oi", "pos_oi_z", "pos_breadth", "pos_breadth_z",
            "tone_score", "fear_score", "pos_score", "combined", "n_groups", "n_comp", "computed_at"])


def _both(s: Optional[pd.Series], index: pd.DatetimeIndex, minp: Optional[int] = None, max_age: int = 4) -> Optional[pd.DataFrame]:
    """(value, z) of a native series on `index`: z against its own previous observations, then each stale-aligned (no print older than max_age days is carried)."""
    if s is None or not len(s):
        return None
    z = zscore_pit(s, min_periods=minp)
    return pd.DataFrame({"v": stale_align(s, index, max_age), "z": stale_align(z, index, max_age)}, index=index)


def _mean_signed(df: pd.DataFrame, comps: Iterable[str], use_sign: bool = True) -> pd.Series:
    cols = [c for c in comps if f"{c}_z" in df.columns]
    if not cols:
        return pd.Series(np.nan, index=df.index)
    m = pd.concat([df[f"{c}_z"] * (SIGN[c] if use_sign else 1) for c in cols], axis=1)
    return m.mean(axis=1, skipna=True)


def market_block(root, market: str, index: pd.DatetimeIndex, start: Optional[date] = None, with_breadth: bool = True) -> pd.DataFrame:
    """Theme-independent components on `index`: fear_*, pos_*, tone_country, each as value and `_z`."""
    idx = pd.DatetimeIndex(index)
    out = pd.DataFrame(index=idx)
    if not len(idx):
        return out
    start = start or (idx.min() - pd.Timedelta(days=500)).date()
    nat: Dict[str, pd.Series] = {}
    nat.update(fear.native(root, market))
    nat.update(positioning.native(root, market, start, idx.max().date(), with_breadth))
    ct = tone.country_tone(root, market)
    if ct is not None:
        nat["tone_country"] = ct
    st = S.settings()
    for k, s in nat.items():
        b = _both(s, idx, minp=int(st["z_min_tone"]) if k in SHORT_HISTORY else None, max_age=1 if k in SHORT_HISTORY else 4)
        if b is not None:
            out[k], out[f"{k}_z"] = b["v"], b["z"]
    return out


def price_score(root, market: str, index: pd.DatetimeIndex, start: Optional[date] = None, with_breadth: bool = True) -> pd.DataFrame:
    """The theme-independent PRICE-BASED score on `index`: columns fear_score, pos_score, score (mean of the groups present), n_groups, n_comp. Positive = risk-on.
    Replay-safe: nothing here reads the news tone or the model."""
    mb = market_block(root, market, index, start, with_breadth)
    out = pd.DataFrame(index=pd.DatetimeIndex(index))
    parts = []
    for g, comps in PRICE_GROUPS.items():
        out[f"{g}_score"] = _mean_signed(mb, comps)
        parts.append(out[f"{g}_score"])
    out["score"] = pd.concat(parts, axis=1).mean(axis=1, skipna=True)
    out["n_groups"] = pd.concat(parts, axis=1).notna().sum(axis=1)
    out["n_comp"] = sum(mb[f"{c}_z"].notna().astype(int) for g in PRICE_GROUPS.values() for c in g if f"{c}_z" in mb.columns) if len(mb.columns) else 0
    return out


def _theme_series(con, root, market: str, theme: T.Theme, start: date, end: date) -> Dict[str, pd.Series]:
    out: Dict[str, pd.Series] = {}
    g = tone.gdelt_group_tone(root, theme.gdelt_groups, start, end)               # agent D's sample of the GKG files, one series for the whole period...
    if g is None or len(g) < int(S.settings()["z_min_tone"]):                      # ...else the GKG files on this PC (market-specific, shorter)
        g = tone.gkg_theme_tone(root, market, {theme.key: theme}, start, end)
        g = g[g["theme"] == theme.key] if len(g) else g
    if g is not None and len(g):
        out["tone_gdelt"] = pd.Series(g["tone"].to_numpy(float), index=pd.DatetimeIndex(g["day"]))
        out["tone_gdelt_n"] = pd.Series(g["n"].to_numpy(float), index=pd.DatetimeIndex(g["day"]))
    try:
        m = tone.model_tone_by_day(con, market, theme.key, start, end)
    except Exception:
        m = pd.DataFrame()
    if len(m):
        out["tone_model"] = pd.Series(m["tone"].to_numpy(float), index=pd.DatetimeIndex(m["day"]))
        out["tone_model_n"] = pd.Series(m["n"].to_numpy(float), index=pd.DatetimeIndex(m["day"]))
    if theme.primary:
        px = T.load_proxy(root, theme.primary)
        if px is not None:
            rv = fear.realised_vol(px)
            if len(rv):
                out["proxy_vol"] = rv
    return out


def compute_range(con, root, market: str, days: List[date], themes: Optional[Dict[str, T.Theme]] = None, with_breadth: bool = True) -> pd.DataFrame:
    """The table rows for `days` (sessions of `market`) x every live theme of the market. Point in time; no model call (the model's tags already in the store are read)."""
    themes = themes if themes is not None else T.load_themes(market)
    days = sorted(set(days))
    if not days or not themes:
        return pd.DataFrame(columns=COLUMNS)
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    start = (idx.min() - pd.Timedelta(days=500)).date()
    mb = market_block(root, market, idx, start, with_breadth)
    now = datetime.now()
    rows = []
    st = S.settings()
    for k, th in themes.items():
        tb = _theme_series(con, root, market, th, start, idx.max().date())
        df = pd.DataFrame(index=idx)
        for c in mb.columns:
            df[c] = mb[c]
        for comp in ("tone_gdelt", "tone_model", "proxy_vol"):
            s = tb.get(comp)
            if s is None:
                continue
            b = _both(s, idx, minp=int(st["z_min_tone"]) if comp in SHORT_HISTORY else None, max_age=0 if comp in SHORT_HISTORY else 4)
            df[comp], df[f"{comp}_z"] = b["v"], b["z"]
        for nm in ("tone_gdelt_n", "tone_model_n"):
            s = tb.get(nm)
            df[nm] = stale_align(s, idx, 0) if s is not None else np.nan
        for g, comps in GROUPS.items():
            df[f"{g}_score"] = _mean_signed(df, comps)
        gs = df[["tone_score", "fear_score", "pos_score"]]
        df["combined"] = gs.mean(axis=1, skipna=True)
        df["n_groups"] = gs.notna().sum(axis=1)
        df["n_comp"] = sum(df[f"{c}_z"].notna().astype(int) for g in GROUPS.values() for c in g if f"{c}_z" in df.columns)
        df["market"], df["theme"], df["day"], df["computed_at"] = market, k, [d.date() for d in idx], now
        rows.append(df.reset_index(drop=True))
    out = pd.concat(rows, ignore_index=True)
    for c in COLUMNS:
        if c not in out.columns:
            out[c] = np.nan
    for c in ("tone_gdelt_n", "tone_model_n", "n_groups", "n_comp"):
        out[c] = out[c].astype("Int64")
    return out[COLUMNS]


def persist(con, df: pd.DataFrame) -> int:
    """Replace the rows of the table for the (market, theme, day) keys in `df`."""
    if df is None or not len(df):
        return 0
    con.register("_sent_new", df)
    try:
        con.execute("DELETE FROM sentiment_s79 WHERE (market, theme, day) IN (SELECT market, theme, day FROM _sent_new)")
        con.execute(f"INSERT INTO sentiment_s79 ({', '.join(COLUMNS)}) SELECT {', '.join(COLUMNS)} FROM _sent_new")
    finally:
        con.unregister("_sent_new")
    return int(len(df))


def stored(con, market: str, asof: date, theme: Optional[str] = None, n_days: int = 1) -> pd.DataFrame:
    """The latest stored rows on or before `asof`: the last `n_days` distinct days, optionally one theme."""
    try:
        q = "SELECT * FROM sentiment_s79 WHERE market=? AND day<=?" + (" AND theme=?" if theme else "")
        a = [market, asof] + ([theme] if theme else [])
        df = con.execute(q + " ORDER BY day DESC, theme", a).df()
    except Exception:
        return pd.DataFrame(columns=COLUMNS)
    if df.empty:
        return df
    keep = sorted(df["day"].unique())[-n_days:]
    return df[df["day"].isin(keep)]


# --- the events the pre-registered study uses -------------------------------------------------------------------------------------------

def extreme_sentiment_events(market: str, start: date, end: date, root=None, pct: Optional[float] = None, min_hist: int = 120) -> pd.DataFrame:
    """Days on which the PRICE-BASED score is beyond the `pct`-th (default 5) or (100-`pct`)-th EXPANDING percentile of its own earlier history (the percentile on date D
    is taken over scores dated strictly before D: point in time, no tuning). Columns: date, kind ("fear" = unusually risk-off, "greed" = unusually risk-on), score,
    threshold, n_hist, n_comp, first_of_cluster (True when no extreme of the same kind sits in the previous 5 rows). No news tone, no model: history-safe.
    The score exists from the first date the market's volatility index and the other components have a z-score (the n and range are printed by the study)."""
    root = S.data_root(root)
    pct = float(pct if pct is not None else S.settings()["extreme_pct"])
    base = fear.vix(root, market)
    cols = ["date", "kind", "score", "threshold", "n_hist", "n_comp", "first_of_cluster"]
    if base is None:
        return pd.DataFrame(columns=cols)
    idx = base.index[base.index <= pd.Timestamp(end)]
    ps = price_score(root, market, idx, with_breadth=True)
    sc = ps["score"]
    lo = sc.shift(1).expanding(min_periods=min_hist).quantile(pct / 100.0)
    hi = sc.shift(1).expanding(min_periods=min_hist).quantile(1.0 - pct / 100.0)
    nh = sc.shift(1).expanding().count()
    rows = []
    for kind, thr, mask in (("fear", lo, sc <= lo), ("greed", hi, sc >= hi)):
        m = mask.fillna(False) & thr.notna()
        flag = m.astype(int)
        prev = flag.shift(1).rolling(5, min_periods=1).max().fillna(0)
        for d in sc.index[m.to_numpy()]:
            if pd.Timestamp(start) <= d <= pd.Timestamp(end):
                rows.append({"date": d.date(), "kind": kind, "score": float(sc[d]), "threshold": float(thr[d]), "n_hist": int(nh[d]), "n_comp": int(ps.loc[d, "n_comp"]),
                             "first_of_cluster": bool(prev[d] == 0)})
    return pd.DataFrame(rows, columns=cols).sort_values("date").reset_index(drop=True)
