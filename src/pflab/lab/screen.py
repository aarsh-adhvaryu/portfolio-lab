"""What the strategist may look at to choose (S83 L2): a screen and a one-page card per name. Code only: every number comes from the store and the data folder, point in time (a row dated after
the decision day is never read), public market data only; nothing here is a model's number and nothing here trades.

    screen_stocks(con, now, market, filters=None, sort="momentum_126", n=40) -> {"rows": [...at most 40...], "note", "summary", ...}
    company_card(con, now, market, symbol) -> one page for one name from the same sources, plus (US) SEC company facts and what the rails would allow

INDIA (market "IN"): the liquid listed shares (median traded value over the last 60 sessions of at least Rs 5 crore, the picks floor) with trend and momentum, volatility, size, index
membership, sector, the last shareholding patterns, insider and bulk deals (context only), recent results and graph events, red flags, the stored price range, the open storylines that name
the sector or company and, where filed, P/E and growth. US (market "US"): the SEC ticker file's names (CIK keys) that clear the A62 floor from daily bars (`us/picks_floor.py`); bars for names
not yet held on disk are downloaded on demand from Yahoo (a cap per call, a short timeout, never a failure when the network is down), and company facts come from SEC XBRL.

WHAT THE LABELS MEAN. The numbers DESCRIBE the past. No rule on them is a signal: of the S64 rule tests only "a stock below its 200-day average earns less" passed (an AVOID reading); P/E above
50 narrowly failed and the others failed (docs/STUDIES.md). Insider and bulk-deal rows are context, never a signal (the S48 study failed). The history of single US stocks is survivorship-biased:
it is never evidence for a pick. Ranges are plain statistics, not forecasts to act on.
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

MAX_ROWS = 40
IN_FLOOR_INR = 50_000_000.0                          # Rs 5 crore a day (the picks floor, A61 L1): a name below it is never shown
SESSIONS_LIQ = 60
SHAREHOLDING_LAG_DAYS = 21                           # a quarter's pattern is public by 21 days after its end (SEBI's deadline); the files carry no usable filing date
DEALS_DAYS = 90
JUMP = 0.35                                          # a one-day move beyond this is flagged as a possible split or bonus the closes do not carry
US_FETCH_CAP = 20
BRIEF_LIMIT = 28000                                   # characters of a brief screen (lab/tools.py LIMITS cuts at 30,000)
US_TIMEOUT = 12
US_NOTE = "history of single US stocks is survivorship-biased: it is never evidence for a pick"
MOMENTUM_LABEL = "trend and momentum describe the past; no rule on them is a tested signal"
DEALS_LABEL = "context, never a signal (the S48 study failed)"
FIGURES_LABEL = "every number is code"
SORTS = {"momentum_63": ("ret_63", True), "momentum_126": ("ret_126", True), "momentum_252": ("ret_252", True), "low_volatility": ("vol_250", False),
         "traded_value": ("value_60", True), "market_cap": ("market_cap_cr", True), "promoter_change": ("promoter_change_pp", True), "near_52w_high": ("from_52w_high", True)}
FILTER_KEYS = ("min_traded_value_inr", "min_momentum", "max_volatility", "sector", "in_index", "exclude_held", "exclude_flagged", "symbols", "grow_universe", "fetch_cap", "include_suspect_prices")
INDEX_FILES = ("NIFTY100", "NIFTY200", "NIFTY500", "NIFTY_MIDCAP100")

# What the S64 rule tests said (docs/STUDIES.md; claims 18-24): used when the store holds no verdict of its own.
S64_VERDICTS = {"below_sma200": "passed", "pe_above_50": "failed", "pe_below_15": "failed", "near_52w_low_5": "failed", "volume_spike_2": "failed", "ath_fall_40": "failed", "rsi_below_30": "failed"}
RULE_WORDS = {"below_sma200": "a stock below its 200-day average earns less next month (about 0.6-0.75% a month): an AVOID reading",
              "pe_above_50": "a P/E above 50 earns less: narrowly failed its test", "pe_below_15": "a cheap P/E (under 15) earns more: failed its test",
              "near_52w_low_5": "near the 52-week low earns more: failed its test", "volume_spike_2": "a volume spike earns more: failed its test",
              "ath_fall_40": "40% below the high rebounds: failed its test", "rsi_below_30": "oversold (RSI under 30) bounces: failed its test"}


# --- small helpers ------------------------------------------------------------------------------------------------------------------

def _day(now) -> date:
    return now.date() if isinstance(now, datetime) else now


def _root(root) -> Path:
    if root is None:
        from pflab.data import data_dir
        root = data_dir()
    return Path(root)


def _num(x, nd: int = 1):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if math.isfinite(x) else None


def _pct(x, nd: int = 1):
    x = _num(x, 10) if x is not None else None
    return None if x is None else round(x * 100, nd)


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def _cut(s, n: int = 100) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _market(market: str) -> str:
    m = (market or "IN").strip().upper()
    if m not in ("IN", "US"):
        raise ValueError(f"market is IN or US, not {market!r}")
    return m


def rule_verdicts(con=None) -> Dict[str, dict]:
    """rule -> {"verdict": passed | failed | not tested, "source", "words"}: the store's own claim when it has one, else the S64 verdicts of docs/STUDIES.md. Only a PASSED rule is ever offered as a reading."""
    out = {}
    for rule, fallback in S64_VERDICTS.items():
        v, src = None, None
        try:
            from pflab.learner import rules
            st = rules.status(con, rule) if con is not None else {"label": "not tested"}
            if st.get("label") in ("passed", "failed"):
                v, src = st["label"], f"the learner's claim #{st.get('claim_id')}"
        except Exception:
            pass
        if v is None:
            v, src = fallback, "S64 rule tests, docs/STUDIES.md"
        out[rule] = {"verdict": v, "source": src, "words": RULE_WORDS[rule]}
    return out


def labels_text(verdicts: Dict[str, dict]) -> dict:
    """The legend of a screen: what is a reading and what is only a description."""
    passed = [r for r, v in verdicts.items() if v["verdict"] == "passed"]
    return {"figures": FIGURES_LABEL + ", point in time; ranges are plain statistics, not forecasts",
            "trend_and_momentum": MOMENTUM_LABEL,
            "rule_tests": {r: f"{v['verdict']}: {v['words']} ({v['source']})" for r, v in verdicts.items()},
            "only_reading": [RULE_WORDS[r] for r in passed], "insider_and_bulk_deals": DEALS_LABEL,
            "us_history": US_NOTE}


def _log(con, now, market: str, tool: str, args: dict, symbols: List[str]) -> None:
    """Best-effort record of what was looked at (`screen_log_s83`); a failed write never fails a screen."""
    try:
        from pflab.pm.store import next_id
        con.execute("INSERT INTO screen_log_s83 VALUES (?,?,?,?,?,?,?,?)",
                    [next_id(con, "screen_log_s83", "log_id"), now if isinstance(now, datetime) else datetime.combine(now, datetime.min.time()), _day(now), market, tool,
                     json.dumps(args, default=str)[:2000], len(symbols), json.dumps(symbols[:MAX_ROWS])])
    except Exception:
        pass


# --- price features ---------------------------------------------------------------------------------------------------------------

def features(c: pd.Series) -> dict:
    """Trend, momentum, volatility and range of one close series (sorted by date, already cut at the decision day). Missing history gives None, never a guess."""
    c = c.dropna()
    c = c[c > 0]
    n = len(c)
    out: dict = {"sessions": n, "price": None, "price_date": None, "ret_63": None, "ret_126": None, "ret_252": None, "vs_200dma": None, "vol_250": None,
                 "from_52w_high": None, "above_52w_low": None, "high_52w": None, "low_52w": None, "jump": None}
    if n < 2:
        return out
    px = float(c.iloc[-1])
    out["price"], out["price_date"] = px, str(pd.Timestamp(c.index[-1]).date())
    for k, h in (("ret_63", 63), ("ret_126", 126), ("ret_252", 252)):
        if n > h:
            out[k] = px / float(c.iloc[-1 - h]) - 1
    if n >= 200:
        out["vs_200dma"] = px / float(c.iloc[-200:].mean()) - 1
    r = c.pct_change().dropna()
    if len(r.tail(250)) >= 60:
        out["vol_250"] = float(r.tail(250).std() * math.sqrt(252))
    y = c.iloc[-250:]
    out["high_52w"], out["low_52w"] = float(y.max()), float(y.min())
    out["from_52w_high"], out["above_52w_low"] = px / out["high_52w"] - 1, px / out["low_52w"] - 1
    mj = float(r.tail(260).abs().max()) if len(r) else 0.0
    out["jump"] = mj if mj > JUMP else None
    return out


def _says_price(f: dict, unit: str = "") -> str:
    bits = []
    if f.get("ret_126") is not None:
        bits.append(f"{'up' if f['ret_126'] >= 0 else 'down'} {abs(f['ret_126']) * 100:.0f}% in 6 months")
    if f.get("vs_200dma") is not None:
        bits.append("above its 200-day average" if f["vs_200dma"] >= 0 else "below its 200-day average")
    if f.get("vol_250") is not None:
        bits.append(f"swings about {f['vol_250'] * 100:.0f}% a year")
    return ", ".join(bits)


# --- INDIA: data readers (every one degrades to empty and says so) -----------------------------------------------------------------------------

def _bhav_files(root: Path, start: date, day: date) -> List[str]:
    from pflab.data.bhavcopy import bhav_files
    out = []
    for f in bhav_files(root, start, day):
        try:
            d = date.fromisoformat(Path(f).stem)
        except ValueError:
            continue
        if start <= d <= day:
            out.append(f)
    return out


def india_liquidity(root: Path, day: date) -> pd.DataFrame:
    """One row per listed share (INE key) that traded in the last sessions up to `day`: symbol, median_value_60 (rupees over the last 60 sessions, a session with no trade counting as 0),
    sessions_traded, last_session, series. Index: isin. Empty when no bhavcopy is held."""
    from pflab import _duck
    files = _bhav_files(root, day - timedelta(days=130), day)
    if not files:
        return pd.DataFrame(columns=["symbol", "median_value_60", "sessions_traded", "last_session", "series"])
    rel = f"read_parquet({files!r}, union_by_name=true)"
    sess = [pd.Timestamp(x).date() for x in _duck.sql(f"SELECT DISTINCT date FROM {rel} ORDER BY 1").df()["date"]][-SESSIONS_LIQ:]
    if not sess:
        return pd.DataFrame(columns=["symbol", "median_value_60", "sessions_traded", "last_session", "series"])
    tv = _duck.sql(f"SELECT date, isin, arg_max(symbol, turnover) AS symbol, arg_max(series, turnover) AS series, sum(turnover) AS t FROM {rel} "
                   f"WHERE date >= DATE '{sess[0]}' AND series IN ('EQ', 'BE') AND isin LIKE 'INE%' GROUP BY 1, 2").df()
    if tv.empty:
        return pd.DataFrame(columns=["symbol", "median_value_60", "sessions_traded", "last_session", "series"])
    tv["date"] = [pd.Timestamp(x).date() for x in tv["date"]]
    wide = tv.pivot_table(index="date", columns="isin", values="t", aggfunc="sum").reindex(sess)
    last = tv.sort_values("date").groupby("isin").tail(1).set_index("isin")
    out = pd.DataFrame({"median_value_60": wide.fillna(0.0).median(), "sessions_traded": wide.notna().sum()})
    out["symbol"], out["series"] = last["symbol"], last["series"]
    out["last_session"] = tv.groupby("isin")["date"].max()
    return out


def india_closes(con, root: Path, isins: List[str], day: date, days: int = 440) -> Dict[str, pd.Series]:
    """Adjusted closes up to `day`: the research panel (split-safe, to its last date) joined to the store's closes at their last shared date (as `app/research.closes`), many names at once."""
    from pflab import _duck
    isins = [i for i in dict.fromkeys(isins) if i]
    if not isins:
        return {}
    lo = day - timedelta(days=days)
    panel: Dict[str, pd.Series] = {}
    pf = root / "panel" / "prices.parquet"
    if pf.exists():
        for k in range(0, len(isins), 800):
            lst = ",".join(f"'{i}'" for i in isins[k:k + 800])
            d = _duck.sql(f"SELECT isin, date, adj_close FROM '{pf.as_posix()}' WHERE isin IN ({lst}) AND date >= DATE '{lo}' AND date <= DATE '{day}' AND adj_close > 0 ORDER BY date").df()
            for i, g in d.groupby("isin"):
                panel[i] = pd.Series(g["adj_close"].to_numpy(float), index=pd.to_datetime(g["date"]))
    store: Dict[str, pd.Series] = {}
    for k in range(0, len(isins), 800):
        chunk = isins[k:k + 800]
        ph = ",".join("?" * len(chunk))
        d = con.execute(f"SELECT isin, date, close FROM prices WHERE isin IN ({ph}) AND date >= ? AND date <= ? AND close > 0 ORDER BY date, source", chunk + [lo, day]).df()
        for i, g in d.groupby("isin"):
            g = g.drop_duplicates("date", keep="last")                      # the NSE row (it sorts after the BSE one) wins on a shared day
            store[i] = pd.Series(g["close"].to_numpy(float), index=pd.to_datetime(g["date"]))
    out = {}
    for i in isins:
        a, b = panel.get(i), store.get(i)
        if a is None and b is None:
            continue
        if a is None or a.empty:
            out[i] = b
        elif b is None or b.empty:
            out[i] = a
        else:
            common = a.index.intersection(b.index)
            if len(common):
                k = b.loc[common[-1]] / a.loc[common[-1]]
                out[i] = pd.concat([(a * k)[a.index <= common[-1]], b[b.index > common[-1]]])
            else:
                out[i] = pd.concat([a, b[b.index > a.index[-1]]])
        out[i] = out[i][~out[i].index.duplicated(keep="last")].sort_index()
    return out


def scrip_map(root: Path, day: date) -> Dict[str, str]:
    """isin -> BSE scrip code (the key of the shareholding, results and announcement files), the mapping valid on `day`."""
    from pflab import _duck
    p = root / "bse_scrip_isin" / "map.parquet"
    if not p.exists():
        return {}
    d = _duck.sql(f"SELECT isin, scrip_code FROM '{p.as_posix()}' WHERE isin <> '' AND valid_from <= TIMESTAMP '{day} 23:59:59' AND valid_to >= TIMESTAMP '{day} 00:00:00' "
                  f"ORDER BY last_seen").df()
    return dict(zip(d["isin"], d["scrip_code"].astype(str)))


def shareholding(root: Path, scrips: Dict[str, str], day: date) -> Dict[str, dict]:
    """isin -> the latest and the previous filed pattern: promoter (and pledged share of theirs), foreign institutions (FPI), domestic institutions (all institutions less FPI), shares outstanding.
    A quarter counts from SHAREHOLDING_LAG_DAYS after its end."""
    from pflab import _duck
    out: Dict[str, dict] = {}
    if not scrips:
        return out
    by_scrip = {s: i for i, s in scrips.items()}
    lst = ",".join(f"'{s}'" for s in by_scrip)
    cut = day - timedelta(days=SHAREHOLDING_LAG_DAYS)
    lo = day - timedelta(days=500)
    sp, ip = root / "bse_shareholding" / "summary.parquet", root / "bse_shareholding" / "institutions.parquet"
    summ = pd.DataFrame()
    if sp.exists():
        summ = _duck.sql(f"SELECT scrip_code, quarter_end, promoter_pct, pledged_pct_of_promoter, shares_outstanding_reported AS sh_rep, shares_outstanding_derived AS sh_der FROM '{sp.as_posix()}' "
                         f"WHERE status = 'ok' AND scrip_code IN ({lst}) AND quarter_end <= DATE '{cut}' AND quarter_end >= DATE '{lo}' ORDER BY quarter_end").df()
    inst = pd.DataFrame()
    if ip.exists():
        inst = _duck.sql(f"SELECT scrip_code, quarter_end, inst_pct, mf_pct, fpi_pct FROM '{ip.as_posix()}' WHERE status = 'ok' AND scrip_code IN ({lst}) "
                         f"AND quarter_end <= DATE '{cut}' AND quarter_end >= DATE '{lo}' ORDER BY quarter_end").df()
    for s, g in summ.groupby("scrip_code"):
        g = g.drop_duplicates("quarter_end", keep="last")
        a = g.iloc[-1]
        b = g.iloc[-2] if len(g) > 1 else None
        sh = a["sh_rep"] if pd.notna(a["sh_rep"]) and a["sh_rep"] > 0 else a["sh_der"]
        d = {"as_of_quarter": str(pd.Timestamp(a["quarter_end"]).date()), "promoter_pct": _num(a["promoter_pct"], 2), "pledged_pct_of_promoter": _num(a["pledged_pct_of_promoter"], 2),
             "promoter_change_pp": None if b is None or pd.isna(b["promoter_pct"]) or pd.isna(a["promoter_pct"]) else _num(a["promoter_pct"] - b["promoter_pct"], 2),
             "shares_outstanding": float(sh) if pd.notna(sh) and sh > 0 else None}
        out[by_scrip[s]] = d
    for s, g in inst.groupby("scrip_code"):
        g = g.drop_duplicates("quarter_end", keep="last")
        a = g.iloc[-1]
        b = g.iloc[-2] if len(g) > 1 else None
        d = out.setdefault(by_scrip[s], {})
        dii = a["inst_pct"] - a["fpi_pct"] if pd.notna(a["inst_pct"]) and pd.notna(a["fpi_pct"]) else None
        dii_b = b["inst_pct"] - b["fpi_pct"] if b is not None and pd.notna(b["inst_pct"]) and pd.notna(b["fpi_pct"]) else None
        d.update({"institutions_quarter": str(pd.Timestamp(a["quarter_end"]).date()), "fpi_pct": _num(a["fpi_pct"], 2), "dii_pct": _num(dii, 2), "mf_pct": _num(a["mf_pct"], 2),
                  "fpi_change_pp": None if b is None or pd.isna(b["fpi_pct"]) or pd.isna(a["fpi_pct"]) else _num(a["fpi_pct"] - b["fpi_pct"], 2),
                  "dii_change_pp": None if dii is None or dii_b is None else _num(dii - dii_b, 2)})
    return out


def memberships(root: Path, day: date) -> Dict[str, List[str]]:
    """isin -> the indices (Nifty 100, 200, 500, Midcap 100) it belonged to on `day` (the point-in-time table; half-open windows)."""
    from pflab.data import index_membership as im
    out: Dict[str, List[str]] = {}
    for ix in INDEX_FILES:
        try:
            t = im.load(ix, root)
        except Exception:
            continue
        for i in im.members_at(t, ix, day):
            out.setdefault(i, []).append(ix)
    return out


def sectors(con, root: Path, isins: List[str], day: date) -> Dict[str, Optional[str]]:
    """isin -> the industry label on `day` (the dated sector map, never a later capture), else the instruments table's own sector."""
    out: Dict[str, Optional[str]] = {}
    try:
        from pflab.data import sector_map
        t = sector_map.load(root)
        lab = sector_map.sector_at(t, isins, day, allow_later=False)
        out = {r.isin: r.industry for r in lab.itertuples() if isinstance(r.industry, str) and r.industry}
    except Exception:
        pass
    miss = [i for i in isins if i not in out]
    if miss:
        try:
            ph = ",".join("?" * len(miss))
            for i, s in con.execute(f"SELECT isin, sector FROM instruments WHERE isin IN ({ph}) AND sector IS NOT NULL", miss).fetchall():
                out[i] = s
        except Exception:
            pass
    return out


def red_flag_table(root: Path, day: date) -> Optional[pd.DataFrame]:
    """Red-flag events usable on `day` within the last 12 months (isin, flag, usable_from, headline); None when the table is not held."""
    p = root / "red_flag_events" / "events.parquet"
    if not p.exists():
        return None
    from pflab import _duck
    return _duck.sql(f"SELECT isin, flag, usable_from, any_value(headline) AS headline FROM '{p.as_posix()}' WHERE isin IS NOT NULL AND usable_from <= DATE '{day}' "
                     f"AND usable_from > DATE '{day - timedelta(days=366)}' GROUP BY isin, flag, usable_from ORDER BY usable_from DESC").df()


def _ann_files(root: Path, start: date, day: date) -> List[str]:
    out = []
    for y in range(start.year, day.year + 1):
        for p in sorted((root / "bse_announcements" / str(y)).glob("*.parquet")):
            try:
                d = date.fromisoformat(p.stem)
            except ValueError:
                continue
            if start <= d <= day:
                out.append(p.as_posix())
    return out


def announcements(root: Path, scrips: Dict[str, str], day: date, now: Optional[datetime], days: int = DEALS_DAYS, limit: int = 8) -> Dict[str, dict]:
    """isin -> {"last_result": date, "insider_sast": count, "recent": [headlines]} from the BSE announcement files, only those disseminated by `now` (no release time: left out)."""
    from pflab import _duck
    if not scrips:
        return {}
    files = _ann_files(root, day - timedelta(days=days), day)
    if not files:
        return {}
    by_scrip = {s: i for i, s in scrips.items()}
    lst = ",".join(f"'{s}'" for s in by_scrip)
    upto = now if isinstance(now, datetime) else datetime.combine(day, datetime.max.time())
    d = _duck.sql(f"SELECT scrip_code, category, subcategory, headline, dissem_dt FROM read_parquet({files!r}, union_by_name=true) WHERE scrip_code IN ({lst}) AND dissem_dt IS NOT NULL "
                  f"AND dissem_dt <= TIMESTAMP '{upto:%Y-%m-%d %H:%M:%S}' AND dissem_dt >= TIMESTAMP '{day - timedelta(days=days)} 00:00:00' ORDER BY dissem_dt DESC").df()
    out: Dict[str, dict] = {}
    for s, g in d.groupby("scrip_code"):
        cat = g["category"].fillna("")
        sub = g["subcategory"].fillna("")
        ins = g[cat.str.contains("insider|sast", case=False) & ~sub.str.contains("Trading Window")]
        res = g[cat.str.contains("^Result", case=False)]
        rest = g[~cat.str.contains("insider|sast", case=False)]
        out[by_scrip[s]] = {"last_result": str(pd.Timestamp(res["dissem_dt"].max()).date()) if len(res) else None, "insider_sast": int(len(ins)),
                            "recent": [f"{pd.Timestamp(r.dissem_dt):%Y-%m-%d} {r.category}: {_cut(r.headline, 90)}" for r in rest.head(limit).itertuples()]}
    return out


def deals(root: Path, symbols: Dict[str, str], day: date, days: int = DEALS_DAYS) -> Dict[str, dict]:
    """isin -> NSE bulk and block deals in the last `days`: count and the shares bought and sold (context only)."""
    out: Dict[str, dict] = {}
    if not symbols:
        return out
    lo = day - timedelta(days=days)
    frames = []
    for kind in ("bulk", "block"):
        for y, m in sorted({(lo.year, lo.month), (day.year, day.month)}):
            p = root / "nse_deals" / f"{kind}_{y}-{m:02d}.parquet"
            if p.exists():
                try:
                    frames.append(pd.read_parquet(p))
                except Exception:
                    pass
    if not frames:
        return out
    df = pd.concat(frames, ignore_index=True)
    df = df[(pd.to_datetime(df["date"]) >= pd.Timestamp(lo)) & (pd.to_datetime(df["date"]) <= pd.Timestamp(day))]
    sym2isin = {s: i for i, s in symbols.items()}
    df = df[df["symbol"].isin(sym2isin)]
    for s, g in df.groupby("symbol"):
        buy = float(g.loc[g["side"] == "BUY", "quantity"].sum())
        sell = float(g.loc[g["side"] == "SELL", "quantity"].sum())
        out[sym2isin[s]] = {"n": int(len(g)), "bought_shares": int(buy), "sold_shares": int(sell)}
    return out


def graph_events(con, isins: List[str], now, days: int = 90) -> Dict[str, List[dict]]:
    """isin -> material events of the knowledge graph (results misses, rating cuts, pledges ...) disseminated by `now`; {} while the graph is off or holds none."""
    out: Dict[str, List[dict]] = {}
    try:
        from pflab.kg.events import material_events
        upto = now if isinstance(now, datetime) else datetime.combine(now, datetime.max.time())
        for e in material_events(con, isins, upto - timedelta(days=days)):
            if e["ts"] is not None and e["ts"] <= upto:
                out.setdefault(e["isin"], []).append({"kind": e["kind"], "severity": e["severity"], "date": str(e["ts"])[:10], "text": _cut(e["text"], 90)})
    except Exception:
        pass
    return out


def stored_range(con, root: Path, isins: List[str], day: date) -> Dict[str, dict]:
    """isin -> the newest stored price range (10th, middle, 90th percentile) at 21, 63 and 252 sessions made on or before `day`, by the serving plain-statistics method."""
    out: Dict[str, dict] = {}
    if not isins:
        return out
    try:
        from pflab.quant import forecast as fc
        method, label = fc.serving_method(root)
        ph = ",".join("?" * len(isins))
        rows = con.execute(f"SELECT subject, use, as_of, target, q10, q50, q90 FROM forecasts WHERE subject IN ({ph}) AND model = ? AND as_of <= ? AND use IN ('price21','price63','price252') "
                           f"ORDER BY as_of DESC", [*isins, method, day]).fetchall()
        for sub, use, asof, target, q10, q50, q90 in rows:
            d = out.setdefault(sub, {"method": method, "label": f"80% range, an ESTIMATE from plain statistics ({label})"})
            h = use[len("price"):]
            if h not in d and q10 is not None:
                d[h] = {"low": _num(q10, 1), "middle": _num(q50, 1), "high": _num(q90, 1), "made": str(asof), "to": str(target)}
    except Exception:
        pass
    return out


def storyline_hits(con, market: str, rows: List[dict]) -> Dict[str, List[dict]]:
    """key -> the open storylines that name the name (an exposure row) or its sector or company in their claim. `rows`: dicts with key, symbol, name, sector."""
    out: Dict[str, List[dict]] = {}
    try:
        from pflab.story import store
        stories = store.listing(con, ("open",), market)
    except Exception:
        return out
    exp: Dict[int, Dict[str, float]] = {}
    for s in stories:
        try:
            exp[s["storyline_id"]] = {i: float(x) for i, x in con.execute("SELECT isin, exposure FROM storyline_exposure_s80 WHERE storyline_id=?", [s["storyline_id"]]).fetchall()}
        except Exception:
            exp[s["storyline_id"]] = {}
    for r in rows:
        key = r["key"]
        sec_words = [w for w in re.findall(r"[A-Za-z]{4,}", str(r.get("sector") or "")) if w.lower() not in ("services", "other", "and", "industry")]
        for s in stories:
            claim = str(s["claim"])
            why = None
            if key in exp[s["storyline_id"]]:
                why = f"its exposure to the story is {exp[s['storyline_id']][key]:+.2f}"
            elif r.get("symbol") and re.search(rf"\b{re.escape(str(r['symbol']))}\b", claim, re.I):
                why = "the claim names the company"
            elif r.get("name") and len(str(r["name"]).split()[0]) >= 5 and str(r["name"]).split()[0].lower() in claim.lower():
                why = "the claim names the company"
            elif sec_words and any(w.lower() in claim.lower() for w in sec_words):
                why = "the claim names its sector"
            if why:
                p = s["probability"] if s["probability"] is not None else s["prior"]
                out.setdefault(key, []).append({"id": s["storyline_id"], "claim": _cut(claim, 90), "direction": "up" if s["direction"] > 0 else "down", "probability": _num(p, 2), "why": why})
    return out


def fundamentals_light(con, root: Path, scrip: Optional[str], price: Optional[float], day: date, verdicts: Dict[str, dict]) -> Optional[dict]:
    """Filed P/E and EPS growth (point in time) with the verdict of the P/E rule beside them; None when nothing is filed. The full page is the company card's."""
    if not scrip or not price:
        return None
    try:
        from pflab.fundamentals import pit
        q = pit.load(con, scrip)
        if q.empty:
            q = pit.load(con, scrip, "consolidated")
        if q.empty:
            return None
        r = pit.ratios(pit.last_quarters(q, scrip, day))
        eps, g = r.get("eps_ttm"), r.get("eps_ttm_yoy")
        pe = pit.valuation_ratios(price, eps)["pe_ttm"]
        out = {"eps_ttm": _num(eps, 2), "eps_growth_yoy_pct": None if g is None else _num(g * 100, 1), "pe_ttm": _num(pe, 1)}
        if pe is not None and pe > 50:
            v = verdicts["pe_above_50"]
            out["pe_label"] = f"P/E above 50: that rule {v['verdict']} its test ({v['source']}): context, not a signal"
        return out
    except Exception:
        return None


# --- INDIA: the screen --------------------------------------------------------------------------------------------------------------

def _check_filters(filters, market: str) -> tuple:
    f = dict(filters or {})
    unknown = [k for k in f if k not in FILTER_KEYS]
    used = {k: v for k, v in f.items() if k in FILTER_KEYS}
    return used, unknown


def _held_isins_in(con) -> set:
    try:
        from pflab.paper import book
        return {i for i, q in book.positions(con).items() if q > 1e-9}
    except Exception:
        return set()


def _rows_summary(market: str, shown: int, total: int, sort: str, floor_text: str) -> str:
    return (f"{shown} of {total} stocks that clear {floor_text} are shown, sorted by {sort.replace('_', ' ')}. Every number is code; the figures describe the past and none of them is a signal "
            "(only 'below the 200-day average earns less' passed its test, as an avoid reading).")


def screen_stocks(con, now, market: str, filters: Optional[dict] = None, sort: str = "momentum_126", n: int = MAX_ROWS, root=None, fetch: Optional[Callable] = None,
                  get: Optional[Callable] = None, detail: str = "full") -> dict:
    """At most 40 rows for the picks sleeve's choice. `filters` (all optional): min_traded_value_inr (India; never below the Rs 5 crore floor), min_momentum (126-session return as a fraction, 0.1 = +10%),
    max_volatility (250-session, fraction), sector (part of the label), in_index (NIFTY500, NIFTY200, NIFTY100, NIFTY_MIDCAP100; India), exclude_held, exclude_flagged (red flags in the last 12 months;
    India), symbols (only these), include_suspect_prices (names with a one-day jump beyond 35% in the last year, a possible unadjusted split, are left out unless this is true), grow_universe and
    fetch_cap (US: download up to fetch_cap more SEC-listed names' bars). `detail`: "full" (every field) or "brief" (what the strategist reads: nulls dropped, lists folded into short strings). `sort`: momentum_63, momentum_126, momentum_252, low_volatility,
    traded_value, market_cap, promoter_change (India), near_52w_high. `fetch`/`get`: the Yahoo bar downloader and the SEC JSON getter (a test passes fakes)."""
    market = _market(market)
    day = _day(now)
    n = max(1, min(int(n or MAX_ROWS), MAX_ROWS))
    used, unknown = _check_filters(filters, market)
    notes: List[str] = []
    if unknown:
        notes.append(f"ignored filters (not known): {', '.join(unknown)}; the known ones are {', '.join(FILTER_KEYS)}")
    if sort not in SORTS:
        notes.append(f"unknown sort {sort!r}: used momentum_126 (the others: {', '.join(SORTS)})")
        sort = "momentum_126"
    root = _root(root)
    res = _screen_in(con, now, day, root, used, sort, n, notes) if market == "IN" else _screen_us(con, now, day, root, used, sort, n, notes, fetch, get)
    res["rows"] = res["rows"][:MAX_ROWS]
    if detail == "brief":
        res["rows"] = [brief_row(r) for r in res["rows"]]
    res.update({"market": market, "asof": str(day), "sort": sort, "filters": used, "note": " | ".join(notes), "labels": labels_text(rule_verdicts(con))})
    if detail == "brief":                                        # a tool result is cut at a fixed size: drop whole rows (and say so) rather than let the JSON be cut in the middle
        shown = len(res["rows"])
        while res["rows"] and len(json.dumps(res, default=str)) > BRIEF_LIMIT:
            res["rows"].pop()
        if len(res["rows"]) < shown:
            res["note"] += f" | only {len(res['rows'])} of {shown} rows fit the result size: narrow the filters or use n"
    _log(con, now, market, "screen_stocks", {"filters": used, "sort": sort, "n": n}, [r["symbol"] for r in res["rows"]])
    return res


def _screen_in(con, now, day: date, root: Path, f: dict, sort: str, n: int, notes: List[str]) -> dict:
    verdicts = rule_verdicts(con)
    liq = india_liquidity(root, day)
    if liq.empty:
        notes.append("no NSE bhavcopy is held up to this day: nothing to screen")
        return {"rows": [], "summary": "no stock data is held for this day", "universe": 0}
    floor = max(IN_FLOOR_INR, float(f.get("min_traded_value_inr") or 0.0))
    last_session = max(liq["last_session"])
    cand = liq[(liq["median_value_60"] >= floor) & (liq["last_session"] >= last_session - timedelta(days=7))]
    universe = int(len(cand))
    notes.append(f"India: names with a median traded value of at least Rs {floor / 1e7:,.0f} crore a day over the last {SESSIONS_LIQ} sessions (the picks floor); data to {last_session}")
    mem = memberships(root, day)
    if f.get("in_index"):
        want = _norm(f["in_index"])
        keep = {i for i, ix in mem.items() if want in {_norm(x) for x in ix}}
        if not keep:
            notes.append(f"in_index {f['in_index']!r} matched no name (use one of {', '.join(INDEX_FILES)}) or the membership files are missing")
        cand = cand[cand.index.isin(keep)]
    if f.get("symbols"):
        syms = {str(s).strip().upper() for s in f["symbols"]}
        cand = cand[cand["symbol"].str.upper().isin(syms)]
    closes = india_closes(con, root, list(cand.index), day)
    held = _held_isins_in(con)
    flags_t = red_flag_table(root, day)
    if flags_t is None:
        notes.append("the red-flag table is not held: red flags were NOT checked")
        flagged = set()
    else:
        flagged = set(flags_t["isin"])
        notes.append(f"red flags are those usable on or before {day} in the last 12 months")
    recs = []
    for isin, r in cand.iterrows():
        c = closes.get(isin)
        ft = features(c[c.index <= pd.Timestamp(day)]) if c is not None else features(pd.Series(dtype=float))
        if ft["price"] is None:
            continue
        recs.append({"isin": isin, "symbol": str(r["symbol"]), "value_60": float(r["median_value_60"]), "days_traded": int(r["sessions_traded"]), **ft})
    scr = scrip_map(root, day)
    sh = shareholding(root, {i: scr[i] for i in (x["isin"] for x in recs) if i in scr}, day)
    sec = sectors(con, root, [x["isin"] for x in recs], day)
    for x in recs:
        s = sh.get(x["isin"], {})
        shares = s.get("shares_outstanding")
        x["market_cap_cr"] = shares * x["price"] / 1e7 if shares and x["price"] else None
        x["promoter_change_pp"] = s.get("promoter_change_pp")
        x["sector"] = sec.get(x["isin"])
        x["indices"] = sorted(mem.get(x["isin"], []))
        x["flagged"] = x["isin"] in flagged
        x["held"] = x["isin"] in held
    keep, suspect = [], []
    for x in recs:
        if x["jump"] and not f.get("include_suspect_prices"):
            suspect.append(x["symbol"])
            continue
        if f.get("min_momentum") is not None and not (x["ret_126"] is not None and x["ret_126"] >= float(f["min_momentum"])):
            continue
        if f.get("max_volatility") is not None and not (x["vol_250"] is not None and x["vol_250"] <= float(f["max_volatility"])):
            continue
        if f.get("sector") and not (x["sector"] and str(f["sector"]).lower() in x["sector"].lower()):
            continue
        if f.get("exclude_held") and x["held"]:
            continue
        if f.get("exclude_flagged") and x["flagged"]:
            continue
        keep.append(x)
    if suspect:
        notes.append(f"{len(suspect)} names left out because their closes show a one-day jump beyond {JUMP:.0%} in the last year (a split or bonus may be unadjusted, so their returns may be wrong); "
                     f"ask for one with company_card or set include_suspect_prices")
    key, desc = SORTS[sort]
    have = [x for x in keep if x.get(key) is not None]
    if len(have) < len(keep):
        notes.append(f"{len(keep) - len(have)} names have no {sort.replace('_', ' ')} (too little history or no stored figure) and are listed last or left out")
    have.sort(key=lambda x: (-x[key] if desc else x[key], x["symbol"]))
    top = have[:n] + ([x for x in keep if x.get(key) is None][: max(0, n - len(have))] if len(have) < n else [])
    rows = _rows_in(con, now, day, root, top, sh, scr, verdicts, notes)
    nm = f"Rs {floor / 1e7:,.0f} crore a day"
    return {"rows": rows, "universe": universe, "after_filters": len(keep),
            "summary": _rows_summary("IN", len(rows), len(keep), sort, nm)}


def _rows_in(con, now, day: date, root: Path, top: List[dict], sh: dict, scr: Dict[str, str], verdicts: Dict[str, dict], notes: List[str]) -> List[dict]:
    isins = [x["isin"] for x in top]
    ann = announcements(root, {i: scr[i] for i in isins if i in scr}, day, now if isinstance(now, datetime) else None)
    dl = deals(root, {x["isin"]: x["symbol"] for x in top}, day)
    ev = graph_events(con, isins, now)
    rng = stored_range(con, root, isins, day)
    names = {}
    try:
        ph = ",".join("?" * len(isins))
        names = dict(con.execute(f"SELECT isin, name FROM instruments WHERE isin IN ({ph})", isins).fetchall()) if isins else {}
    except Exception:
        pass
    flags_t = red_flag_table(root, day)
    st = storyline_hits(con, "IN", [{"key": x["isin"], "symbol": x["symbol"], "name": names.get(x["isin"]), "sector": x["sector"]} for x in top])
    if not ev:
        notes.append("graph events: none (the knowledge graph is off or holds none for these names)")
    out = []
    for x in top:
        i = x["isin"]
        s = sh.get(i, {})
        a = ann.get(i, {})
        d = dl.get(i)
        row = {"symbol": x["symbol"], "name": _cut(names.get(i), 40) or None, "isin": i, "sector": x["sector"] or "unknown", "indices": x["indices"],
               "price": _num(x["price"], 2), "price_date": x["price_date"], "return_63d_pct": _pct(x["ret_63"]), "return_126d_pct": _pct(x["ret_126"]), "return_252d_pct": _pct(x["ret_252"]),
               "vs_200dma_pct": _pct(x["vs_200dma"]), "below_200dma": None if x["vs_200dma"] is None else bool(x["vs_200dma"] < 0), "volatility_250d_pct": _pct(x["vol_250"]),
               "from_52w_high_pct": _pct(x["from_52w_high"]), "traded_value_inr": round(x["value_60"]), "traded_days_of_60": x["days_traded"],
               "market_cap_cr": None if x["market_cap_cr"] is None else round(x["market_cap_cr"]),
               "size": "unknown (no shares outstanding stored)" if x["market_cap_cr"] is None else "estimate: shares at the last filed quarter x the last close",
               "held": x["held"], "data_flags": []}
        if x["jump"]:
            row["data_flags"].append(f"a one-day move of {x['jump'] * 100:.0f}% in the last year: a split or bonus may not be adjusted, so its returns may be wrong")
        if s:
            row["shareholding"] = {k: s.get(k) for k in ("as_of_quarter", "promoter_pct", "promoter_change_pp", "pledged_pct_of_promoter", "fpi_pct", "fpi_change_pp", "dii_pct", "dii_change_pp")}
            row["shareholding"]["note"] = f"public {SHAREHOLDING_LAG_DAYS} days after the quarter ends; dii = all institutions less foreign"
        row["insider_sast_announcements_90d"] = a.get("insider_sast", 0) if ann else None
        row["bulk_block_deals_90d"] = d or {"n": 0}
        row["deals_label"] = DEALS_LABEL
        row["last_result_filed"] = a.get("last_result")
        row["recent_announcements"] = a.get("recent", [])[:2]
        row["events"] = ev.get(i, [])[:2]
        row["red_flags"] = [] if flags_t is None else [{"flag": r.flag, "usable_from": str(r.usable_from)[:10], "headline": _cut(r.headline, 80)} for r in flags_t[flags_t["isin"] == i].head(2).itertuples()]
        row["price_range_63d"] = (rng.get(i) or {}).get("63")
        if i in rng:
            row["price_range_label"] = rng[i]["label"]
        row["storylines"] = st.get(i, [])[:2]
        row["fundamentals"] = fundamentals_light(con, root, scr.get(i), x["price"], day, verdicts)
        lab = []
        if row["below_200dma"]:
            lab.append("below its 200-day average: the one tested rule that passed (such stocks earned less): an avoid reading")
        row["labels"] = lab
        row["says"] = f"{x['symbol']}: {_says_price(x)}; trades about Rs {x['value_60'] / 1e7:,.0f} crore a day" + (f"; flagged: {row['red_flags'][0]['flag']}" if row["red_flags"] else "")
        out.append(row)
    return out


# --- US: universe, bars on demand, SEC facts ------------------------------------------------------------------------------------------------

UNIVERSE_FILE = ("us", "sec_universe.json")


def us_universe(root: Path) -> List[dict]:
    """The SEC ticker file's names, in the file's own order (roughly largest company first): [{"ticker", "cik", "title"}]. Read from the cache `data/us/sec_universe.json`; if that is absent, from the
    CIK cache (`us/instruments.load_ciks`, alphabetical, no names); if that is absent too, from the symbols already under `data/us/raw`."""
    p = root.joinpath(*UNIVERSE_FILE)
    try:
        j = json.loads(p.read_text(encoding="utf-8"))
        if j:
            return j
    except Exception:
        pass
    from pflab.us import instruments as uins
    ciks = uins.load_ciks(root)
    if ciks:
        return [{"ticker": t, "cik": c, "title": None} for t, c in ciks.items()]
    raw = root / "us" / "raw"
    return [{"ticker": q.stem.upper(), "cik": None, "title": None} for q in sorted(raw.glob("*.parquet"))] if raw.exists() else []


def refresh_us_universe(root, get: Optional[Callable] = None) -> int:
    """Fetch SEC's ticker file once (the contact User-Agent of data/sec_edgar.py, from the secrets file: `us/instruments.refresh_ciks`) and cache the CIK map AND the file's order and titles. Returns the
    count; a failure raises and leaves the old caches."""
    from pflab.data import sec_edgar
    from pflab.us import instruments as uins
    root = _root(root)
    seen: dict = {}

    def grab(url):
        j = (get or sec_edgar.get_json)(url)
        seen["j"] = j
        return j
    n = uins.refresh_ciks(root, grab)
    rows = [{"ticker": str(v["ticker"]).upper(), "cik": int(v["cik_str"]), "title": v.get("title")} for v in seen["j"].values()]
    p = root.joinpath(*UNIVERSE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows), encoding="utf-8")
    return n


def us_download(symbols: List[str], root: Path, fetch: Optional[Callable] = None, cap: int = US_FETCH_CAP, timeout: int = US_TIMEOUT, pause: float = 0.4, recent_days: Optional[int] = None) -> dict:
    """Bars for `symbols` from the existing Yahoo source, written to `data/us/raw` (whole for a new name, the last `recent_days` appended for one on disk; at most `cap`; a short timeout; after three failures in a row it stops: the network is taken to be down).
    Never raises: {"fetched": [...], "failed": {sym: why}, "skipped": n, "network": "ok" | "down"}."""
    from pflab.data import us_prices
    get = fetch or (lambda sym, start=None: us_prices.fetch(sym, timeout=timeout, start=start))
    out = {"fetched": [], "failed": {}, "skipped": 0, "network": "ok"}
    bad_run = 0
    todo = list(dict.fromkeys(s.upper().replace(".", "-") for s in symbols))
    for k, sym in enumerate(todo):
        if k >= cap:
            out["skipped"] = len(todo) - k
            break
        if bad_run >= 3:
            out["network"] = "down"
            out["skipped"] = len(todo) - k
            break
        r = us_prices.collect([sym], root, pause=pause if fetch is None else 0.0, get=get, recent_days=recent_days).get(sym)
        if isinstance(r, tuple):
            out["fetched"].append(sym)
            bad_run = 0
        else:
            out["failed"][sym] = str(r)[:120]
            bad_run += 1
    if bad_run >= 3 and out["network"] != "down":
        out["network"] = "down"
    return out


def _fact_items(facts: dict, concept: str, unit: str, taxonomy: str = "us-gaap") -> List[dict]:
    return (((facts.get("facts") or {}).get(taxonomy) or {}).get(concept) or {}).get("units", {}).get(unit, []) or []


def _first_concept(facts: dict, concepts, unit: str = "USD", taxonomy: str = "us-gaap") -> List[dict]:
    best: List[dict] = []
    for c in concepts:
        items = _fact_items(facts, c, unit, taxonomy)
        if items and (not best or max(i.get("end", "") for i in items) > max(i.get("end", "") for i in best)):
            best = items
    return best


def _annual(items: List[dict], day: date) -> List[dict]:
    """Full-year values (10-K, about 365 days) filed on or before `day`: per period the latest filing."""
    rows = {}
    for i in items:
        try:
            if not (i.get("form", "").startswith("10-K") and date.fromisoformat(i["filed"]) <= day and 340 <= (date.fromisoformat(i["end"]) - date.fromisoformat(i["start"])).days <= 380):
                continue
        except Exception:
            continue
        k = (i["start"], i["end"])
        if k not in rows or i["filed"] >= rows[k]["filed"]:
            rows[k] = i
    return sorted(rows.values(), key=lambda i: i["end"])


def _instant(items: List[dict], day: date) -> Optional[dict]:
    ok = []
    for i in items:
        try:
            if date.fromisoformat(i["filed"]) <= day and i.get("end"):
                ok.append(i)
        except Exception:
            continue
    return max(ok, key=lambda i: (i["end"], i["filed"])) if ok else None


def parse_company_facts(facts: dict, day: date) -> dict:
    """The few numbers a pick needs from an SEC XBRL `companyfacts` document, as known on `day` (a value counts from the date its filing was filed): revenue and net income of the last two full
    years, long-term debt, shares outstanding. Missing items are absent, never guessed. Values in USD (shares in shares)."""
    out: dict = {"source": "SEC XBRL company facts (official, free)"}
    rev = _annual(_first_concept(facts, ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax")), day)
    ni = _annual(_first_concept(facts, ("NetIncomeLoss", "ProfitLoss")), day)
    if rev:
        out["revenue_fy"] = {"end": rev[-1]["end"], "usd": rev[-1]["val"], "filed": rev[-1]["filed"]}
        if len(rev) > 1 and rev[-2]["val"]:
            out["revenue_growth_pct"] = round((rev[-1]["val"] / rev[-2]["val"] - 1) * 100, 1)
    if ni:
        out["net_income_fy"] = {"end": ni[-1]["end"], "usd": ni[-1]["val"], "filed": ni[-1]["filed"]}
        if rev and rev[-1]["end"] == ni[-1]["end"] and rev[-1]["val"]:
            out["net_margin_pct"] = round(ni[-1]["val"] / rev[-1]["val"] * 100, 1)
    debt = _instant(_first_concept(facts, ("LongTermDebt", "LongTermDebtNoncurrent", "DebtInstrumentCarryingAmount")), day)
    if debt:
        out["long_term_debt"] = {"end": debt["end"], "usd": debt["val"], "filed": debt["filed"]}
    sh = _instant(_fact_items(facts, "EntityCommonStockSharesOutstanding", "shares", "dei") or _first_concept(facts, ("WeightedAverageNumberOfSharesOutstandingBasic",), "shares"), day)
    if sh:
        out["shares_outstanding"] = {"end": sh["end"], "shares": sh["val"], "filed": sh["filed"]}
    out["entity"] = facts.get("entityName")
    return out


def us_facts(cik: Optional[int], root: Path, day: date, get: Optional[Callable] = None, allow_network: bool = False, max_age_days: int = 7) -> dict:
    """SEC company facts for one CIK as of `day`: the cached file when present (always, in a screen); in a card (`allow_network`) refreshed when older than `max_age_days`, the old file kept on a failure."""
    if not cik:
        return {"note": "no CIK known for this symbol: no SEC facts"}
    from pflab.data import sec_edgar
    p = root / "us" / "sec" / f"facts_{int(cik):010d}.json"
    note = None
    stale = (not p.exists()) or (time.time() - p.stat().st_mtime > max_age_days * 86400)
    if allow_network and stale:
        try:
            facts = sec_edgar.company_facts(int(cik), root, get=get or sec_edgar.get_json, refresh=True)
        except Exception as e:
            note = f"SEC facts could not be fetched ({type(e).__name__}: {str(e)[:100]})" + ("; the cached file is used" if p.exists() else "")
            facts = None
        if facts is not None:
            return parse_company_facts(facts, day)
    if p.exists():
        try:
            out = parse_company_facts(json.loads(p.read_text(encoding="utf-8")), day)
            if note:
                out["note"] = note
            return out
        except Exception as e:
            return {"note": f"cached SEC facts unreadable ({type(e).__name__})"}
    return {"note": note or "no SEC facts cached for this name yet (the card fetches them)"}


def _us_cached_symbols(root: Path) -> List[str]:
    raw = root / "us" / "raw"
    return sorted(q.stem.upper() for q in raw.glob("*.parquet")) if raw.exists() else []


def _us_features(df: pd.DataFrame, day: date) -> dict:
    d = df[df["date"] <= day]
    col = "adj_close" if "adj_close" in d.columns else "close"
    c = pd.Series(d[col].to_numpy(float), index=pd.to_datetime(d["date"]))
    return features(c)


def _screen_us(con, now, day: date, root: Path, f: dict, sort: str, n: int, notes: List[str], fetch, get) -> dict:
    from pflab.data import us_prices
    from pflab.us import data as usdata, instruments as uins, picks_floor as pf
    verdicts = rule_verdicts(con)
    notes.append(US_NOTE)
    uni = us_universe(root)
    meta = {u["ticker"].upper(): u for u in uni}
    etfs = set(us_prices.ETFS)
    cached = [s for s in _us_cached_symbols(root) if s not in etfs]
    named = [str(s).strip().upper().replace(".", "-") for s in (f.get("symbols") or [])]
    fetch_report = None
    want = []
    if named:
        want = [s for s in named if s not in cached]
    elif f.get("grow_universe"):
        have = set(cached)
        want = [u["ticker"].upper().replace(".", "-") for u in uni if u["ticker"].upper().replace(".", "-") not in have and u["ticker"].upper() not in etfs]
    if want:
        cap = max(1, min(int(f.get("fetch_cap") or US_FETCH_CAP), 40))
        fetch_report = us_download(want, root, fetch, cap=cap)
        cached = [s for s in _us_cached_symbols(root) if s not in etfs]
        msg = f"downloaded bars for {len(fetch_report['fetched'])} name(s) on demand"
        if fetch_report["failed"]:
            msg += f"; {len(fetch_report['failed'])} failed ({next(iter(fetch_report['failed'].values()))[:60]})"
        if fetch_report["skipped"]:
            msg += f"; {fetch_report['skipped']} not tried (cap {cap} per call)"
        if fetch_report["network"] == "down":
            msg += "; the network looks down: only cached bars were screened"
        notes.append(msg)
    sec_listed = any(u.get("cik") for u in uni)
    if not sec_listed:
        notes.append("the SEC ticker file is not cached (data/us/sec_universe.json): the universe is the symbols already under data/us/raw; no names or SEC facts for most of them")
    pool = [s for s in (named if named else cached) if s in set(cached)]
    notes.append(f"US: {len(pool)} names with bars on disk" + (f" of {len(uni)} SEC-listed" if sec_listed else "") + "; each must clear the A62 floor (price at least USD 5, median daily traded value at least USD 2 million over 60 sessions)")
    held = set(us_prices.held_symbols(con))
    ciks = uins.load_ciks(root)
    sort_ok = SORTS[sort][0] in ("ret_63", "ret_126", "ret_252", "vol_250", "value_60", "from_52w_high")
    if not sort_ok:
        notes.append(f"sort {sort} is not available for the US: used momentum_126")
    key, desc = SORTS[sort] if sort_ok else SORTS["momentum_126"]

    def build() -> List[dict]:
        out = []
        for sym in pool:
            df = usdata.bars(sym, root)
            if df is None or df.empty:
                continue
            fl = pf.floor_from_bars(sym, df, day, max_age_days=None)         # the age of the last bar is handled below (refresh, or flag)
            if not fl["ok"]:
                continue
            ft = _us_features(df, day)
            if ft["price"] is None:
                continue
            u = meta.get(sym) or meta.get(sym.replace("-", ".")) or {}
            out.append({"symbol": sym, "cik": u.get("cik") or ciks.get(sym), "title": u.get("title"), "value_60": fl["median_value_usd"], "held": sym in held,
                        "stale_days": (day - date.fromisoformat(fl["last_bar"])).days, **ft})
        return out
    recs = build()
    stale = [x for x in recs if x["stale_days"] > pf.STALE_DAYS and x.get(key) is not None]
    if stale:
        stale.sort(key=lambda x: (-x[key] if desc else x[key], x["symbol"]))
        cap = max(1, min(int(f.get("fetch_cap") or US_FETCH_CAP), 40))
        rep = us_download([x["symbol"] for x in stale], root, fetch, cap=cap, recent_days=15)
        fetch_report = rep if fetch_report is None else {**fetch_report, "refreshed": rep}
        recs = build()
        left = sum(1 for x in recs if x["stale_days"] > pf.STALE_DAYS)
        msg = f"{len(stale)} names had bars older than {pf.STALE_DAYS} days; refreshed the {len(rep['fetched'])} that would rank first (cap {cap} per call)"
        if rep["network"] == "down" or (rep["failed"] and not rep["fetched"]):
            msg += "; the network looks down, so cached bars were used"
        if left:
            msg += f"; {left} still have old bars and are flagged (the daily collection refreshes every held and picked name)"
        notes.append(msg)
    universe = len(recs)
    keep, suspect = [], []
    for x in recs:
        if x["jump"] and not f.get("include_suspect_prices"):
            suspect.append(x["symbol"])
            continue
        if f.get("min_momentum") is not None and not (x["ret_126"] is not None and x["ret_126"] >= float(f["min_momentum"])):
            continue
        if f.get("max_volatility") is not None and not (x["vol_250"] is not None and x["vol_250"] <= float(f["max_volatility"])):
            continue
        if f.get("exclude_held") and x["held"]:
            continue
        keep.append(x)
    if suspect:
        notes.append(f"{len(suspect)} names left out because their closes show a one-day jump beyond {JUMP:.0%} in the last year (an unadjusted split may make their returns wrong); set include_suspect_prices to see them")
    for k in ("sector", "in_index", "exclude_flagged", "min_traded_value_inr"):
        if f.get(k):
            notes.append(f"filter {k} does not apply to the US screen (no US sector or index table, no US red-flag table) and was ignored")
    have = [x for x in keep if x.get(key) is not None]
    have.sort(key=lambda x: (-x[key] if desc else x[key], x["symbol"]))
    if len(have) < len(keep):
        notes.append(f"{len(keep) - len(have)} names have no {sort.replace('_', ' ')} (too little history) and are listed last")
    top = have[:n] + sorted((x for x in keep if x.get(key) is None), key=lambda x: x["symbol"])[: max(0, n - len(have))]
    rows = _rows_us(con, now, day, root, top, ciks, notes)
    return {"rows": rows, "universe": universe, "after_filters": len(keep), "fetch": fetch_report,
            "summary": _rows_summary("US", len(rows), len(keep), sort, "the A62 floor (USD 5, USD 2 million a day)") + " " + US_NOTE + "."}


def _us_filings(root: Path, cik: Optional[int], now, limit: int = 3) -> List[str]:
    if not cik:
        return []
    p = root / "us" / "sec" / f"submissions_{int(cik):010d}.parquet"
    if not p.exists():
        return []
    try:
        d = pd.read_parquet(p)
        upto = pd.Timestamp(now if isinstance(now, datetime) else datetime.combine(now, datetime.max.time()))
        d = d[(d["accepted"] <= upto) & d["form"].isin(["8-K", "10-Q", "10-K", "6-K", "20-F"])].sort_values("accepted", ascending=False).head(limit)
        return [f"{pd.Timestamp(r.accepted):%Y-%m-%d} {r.form}" for r in d.itertuples()]
    except Exception:
        return []


def _rows_us(con, now, day: date, root: Path, top: List[dict], ciks: Dict[str, int], notes: List[str]) -> List[dict]:
    from pflab.us import instruments as uins, picks_floor as pf
    out = []
    keys = {}
    for x in top:
        keys[x["symbol"]] = uins.key_for(con, x["symbol"], ciks) if x.get("cik") else "US:" + x["symbol"]
    ev = graph_events(con, [k for k in keys.values() if k.startswith("ZZ")], now)
    for x in top:
        sym = x["symbol"]
        fa = us_facts(x.get("cik"), root, day)
        shares = (fa.get("shares_outstanding") or {}).get("shares")
        row = {"symbol": sym, "name": _cut(x.get("title") or fa.get("entity"), 40) or None, "cik": x.get("cik"), "key": keys[sym], "sector": "unknown (not stored for US names; no US sector rail)",
               "price": _num(x["price"], 2), "price_date": x["price_date"], "return_63d_pct": _pct(x["ret_63"]), "return_126d_pct": _pct(x["ret_126"]), "return_252d_pct": _pct(x["ret_252"]),
               "vs_200dma_pct": _pct(x["vs_200dma"]), "below_200dma": None if x["vs_200dma"] is None else bool(x["vs_200dma"] < 0), "volatility_250d_pct": _pct(x["vol_250"]),
               "from_52w_high_pct": _pct(x["from_52w_high"]), "range_52w": [_num(x["low_52w"], 2), _num(x["high_52w"], 2)], "traded_value_usd": round(x["value_60"]),
               "market_cap_usd": None if not shares else round(shares * x["price"]), "size": "unknown (no SEC shares figure cached)" if not shares else "estimate: SEC shares outstanding x the last close",
               "floor": "clears the A62 floor" if x["stale_days"] <= 10 else f"price and traded value clear the A62 floor, but the last bar is {x['price_date']} ({x['stale_days']} days old): refresh before picking", "tradable": pf.tradable_note(sym, root), "held": x["held"], "facts": {k: v for k, v in fa.items() if k != "source"} or None,
               "recent_filings": _us_filings(root, x.get("cik"), now), "events": ev.get(keys[sym], [])[:2], "red_flags": "not checked (no US red-flag table)", "data_flags": [],
               "history_warning": US_NOTE, "labels": []}
        if x["jump"]:
            row["data_flags"].append(f"a one-day move of {x['jump'] * 100:.0f}% in the last year: check for an unadjusted split")
        if row["below_200dma"]:
            row["labels"].append("below its 200-day average: the one tested rule that passed (on Indian stocks): an avoid reading")
        row["says"] = f"{sym}: {_says_price(x)}; trades about USD {x['value_60'] / 1e6:,.0f} million a day"
        out.append(row)
    return out


# --- the brief form (what the strategist reads) ---------------------------------------------------------------------------------------------------

def brief_row(r: dict) -> dict:
    """A screen row folded for a tool result: no nulls, no empty lists, the nested parts as short strings. Every figure is the full row's."""
    o: dict = {}
    for k in ("symbol", "name", "sector", "indices", "price", "price_date", "return_63d_pct", "return_126d_pct", "return_252d_pct", "vs_200dma_pct", "volatility_250d_pct", "from_52w_high_pct",
              "market_cap_cr", "last_result_filed", "range_52w"):
        v = r.get(k)
        if v not in (None, [], "", {}):
            o[k] = v
    if r.get("traded_value_inr") is not None:
        o["traded_value_cr"] = round(r["traded_value_inr"] / 1e7, 1)                    # rupees crore a day (60-session median)
    if r.get("traded_value_usd") is not None:
        o["traded_value_usd_m"] = round(r["traded_value_usd"] / 1e6, 1)
    if r.get("market_cap_usd"):
        o["market_cap_usd_m"] = round(r["market_cap_usd"] / 1e6)
    if r.get("tradable") and not str(r["tradable"]).startswith("assumed"):
        o["tradable"] = r["tradable"]
    if r.get("held"):
        o["held"] = True
    if str(r.get("sector", "")).startswith("unknown"):
        o["sector"] = "unknown"
    s = r.get("shareholding")
    if isinstance(s, dict):
        bits = []
        for lab, k, d in (("promoter", "promoter_pct", "promoter_change_pp"), ("FPI", "fpi_pct", "fpi_change_pp"), ("DII", "dii_pct", "dii_change_pp")):
            if s.get(k) is not None:
                bits.append(f"{lab} {s[k]}%" + (f" ({s[d]:+.1f}pp)" if s.get(d) is not None else ""))
        if s.get("pledged_pct_of_promoter"):
            bits.append(f"{s['pledged_pct_of_promoter']}% of promoter pledged")
        if bits:
            o["holders"] = ", ".join(bits) + f" at {s.get('as_of_quarter')}"
    if r.get("insider_sast_announcements_90d"):
        o["insider_sast_90d"] = r["insider_sast_announcements_90d"]
    d = r.get("bulk_block_deals_90d")
    if isinstance(d, dict) and d.get("n"):
        o["bulk_block_90d"] = f"{d['n']} deals, {d['bought_shares']:,} bought / {d['sold_shares']:,} sold"
    if r.get("events"):
        o["events"] = [f"{e['date']} {e['kind']} ({e['severity']})" for e in r["events"]]
    if isinstance(r.get("red_flags"), list) and r["red_flags"]:
        o["red_flags"] = [f"{e['usable_from']} {e['flag']}" for e in r["red_flags"]]
    if isinstance(r.get("price_range_63d"), dict):
        g = r["price_range_63d"]
        o["range_63d_80pct"] = [g["low"], g["middle"], g["high"]]
    if r.get("storylines"):
        o["storylines"] = [f"#{e['id']} {e['direction']} p={e['probability']} ({e['why']})" for e in r["storylines"]]
    f = r.get("fundamentals")
    if isinstance(f, dict):
        o["pe_ttm"], o["eps_growth_yoy_pct"] = f.get("pe_ttm"), f.get("eps_growth_yoy_pct")
        if f.get("pe_label"):
            o["pe_label"] = f["pe_label"]
        o = {k: v for k, v in o.items() if not (k in ("pe_ttm", "eps_growth_yoy_pct") and v is None)}
    elif isinstance(r.get("facts"), dict):
        fa = r["facts"]
        bits = []
        if fa.get("revenue_fy"):
            bits.append(f"revenue USD {fa['revenue_fy']['usd'] / 1e6:,.0f}m" + (f" ({fa['revenue_growth_pct']:+.0f}%)" if fa.get("revenue_growth_pct") is not None else ""))
        if fa.get("net_income_fy"):
            bits.append(f"net income USD {fa['net_income_fy']['usd'] / 1e6:,.0f}m")
        if fa.get("long_term_debt"):
            bits.append(f"debt USD {fa['long_term_debt']['usd'] / 1e6:,.0f}m")
        if bits:
            o["sec_facts"] = ", ".join(bits)
    if r.get("recent_filings"):
        o["recent_filings"] = r["recent_filings"]
    if r.get("data_flags"):
        o["data_flags"] = r["data_flags"]
    if r.get("labels"):
        o["labels"] = r["labels"]
    return o


# --- the card -----------------------------------------------------------------------------------------------------------------------------

def company_card(con, now, market: str, symbol: str, root=None, get: Optional[Callable] = None, fetch: Optional[Callable] = None) -> dict:
    """One page for one name from the same sources as the screen, with the longer lists, the full valuation facts (India), SEC company facts and filings (US), the liquidity, the 52-week range and what
    the rails would allow. Never raises for a missing source: the section says it is missing."""
    market = _market(market)
    day = _day(now)
    root = _root(root)
    sym = (symbol or "").strip().upper()
    card = _card_in(con, now, day, root, sym) if market == "IN" else _card_us(con, now, day, root, sym, get, fetch)
    card.update({"market": market, "asof": str(day), "labels": labels_text(rule_verdicts(con))})
    if card.get("ok", True):
        card["what_we_already_know"] = what_we_know(con, now, card.get("isin") or card.get("key"), sym, market)
    _log(con, now, market, "company_card", {"symbol": sym}, [sym])
    return card


def what_we_know(con, now, isin: Optional[str], sym: str, market: str) -> dict:
    """S84 (T2x): the card's "what we already know" section: the paid notes, graph events, storylines, pick or skip and earlier cases `think/recall` holds on the name, point-in-time; each item the
    card hands over is a row in `knowledge_use_s84` (read by a card). Never raises: a failure is said in the section."""
    try:
        from pflab.think import recall
        at = now if isinstance(now, datetime) else datetime.combine(now, datetime.max.time())
        r = recall.recall(con, at, isin=isin, symbol=sym, limit_chars=2500)
        recall.mark_used(con, r["items"], by_kind="card", by_ref=f"{market}:{sym}", day=at.date())
        return {"n": r["n"], "text": r["text"] or "nothing stored about this name yet", "ids": [f"{i['kind']} {i['id']}" for i in r["items"]]}
    except Exception as e:
        return {"n": 0, "text": f"not available ({type(e).__name__})", "ids": []}


def fit_card(card: dict, limit: int) -> dict:
    """Shrink a card to `limit` characters of JSON by dropping its longest optional parts in a fixed order (and saying which): the whole JSON stays valid."""
    dropped = []
    steps = [("fundamentals", "rules_of_thumb"), ("fundamentals", "in_plain_words"), ("recent_announcements", None), ("fundamentals", "pe_own_5y"), ("sec_facts", None), ("events", None)]
    for a, b in steps:
        if len(json.dumps(card, default=str)) <= limit:
            break
        if b is None and a in card:
            card[a] = card[a][:3] if isinstance(card[a], list) else card[a]
            dropped.append(a + " (cut)")
        elif isinstance(card.get(a), dict) and b in card[a]:
            card[a].pop(b)
            dropped.append(f"{a}.{b}")
    if dropped:
        card["trimmed_to_fit"] = dropped
    return card


def _resolve_in(con, root: Path, day: date, sym: str) -> Optional[str]:
    from pflab.paper import book
    liq = india_liquidity(root, day)
    if not liq.empty:
        m = liq[liq["symbol"].str.upper() == sym]
        if len(m):
            return str(m.sort_values("median_value_60").index[-1])
    return book.isin_of(con, sym)


def _card_in(con, now, day: date, root: Path, sym: str) -> dict:
    from pflab.paper import book, rails
    verdicts = rule_verdicts(con)
    isin = _resolve_in(con, root, day, sym)
    if not isin:
        return {"ok": False, "problem": f"{sym!r} is not a listed share the store or the bhavcopy knows"}
    meta = book.inst(con, isin)
    liq = india_liquidity(root, day)
    closes = india_closes(con, root, [isin], day).get(isin)
    c = closes[closes.index <= pd.Timestamp(day)] if closes is not None else pd.Series(dtype=float)
    ft = features(c)
    scr = scrip_map(root, day)
    scrip = scr.get(isin)
    sh = shareholding(root, {isin: scrip} if scrip else {}, day).get(isin, {})
    shares = sh.get("shares_outstanding")
    mem = memberships(root, day).get(isin, [])
    sec = sectors(con, root, [isin], day).get(isin)
    ann = announcements(root, {isin: scrip} if scrip else {}, day, now if isinstance(now, datetime) else None, days=180, limit=10).get(isin, {})
    dl = deals(root, {isin: sym}, day, days=180).get(isin)
    ft_flags = red_flag_table(root, day)
    held_q = book.positions(con).get(isin, 0.0)
    h = book.holdings(con, day) if held_q > 1e-9 else None
    w = next((r["weight"] for r in h["rows"] if r["isin"] == isin), None) if h else None
    room = None
    try:
        room = rails.buy_room(con, isin, day)
    except Exception:
        pass
    liq_row = liq.loc[isin] if (not liq.empty and isin in liq.index) else None
    card = {"ok": True, "symbol": sym, "isin": isin, "name": meta.get("name"), "sector": sec or meta.get("sector") or "unknown", "indices": sorted(mem),
            "price": {"last": _num(ft["price"], 2), "date": ft["price_date"], "return_63d_pct": _pct(ft["ret_63"]), "return_126d_pct": _pct(ft["ret_126"]), "return_252d_pct": _pct(ft["ret_252"]),
                      "vs_200dma_pct": _pct(ft["vs_200dma"]), "volatility_250d_pct": _pct(ft["vol_250"]), "range_52w": [_num(ft["low_52w"], 2), _num(ft["high_52w"], 2)],
                      "from_52w_high_pct": _pct(ft["from_52w_high"]), "sessions": ft["sessions"]},
            "liquidity": None if liq_row is None else {"median_traded_value_inr_60d": round(float(liq_row["median_value_60"])), "days_traded_of_60": int(liq_row["sessions_traded"]),
                                                       "clears_picks_floor": bool(liq_row["median_value_60"] >= IN_FLOOR_INR), "floor_inr": IN_FLOOR_INR},
            "size": {"market_cap_cr": None if not (shares and ft["price"]) else round(shares * ft["price"] / 1e7), "label": "estimate: shares at the last filed quarter x the last close" if shares else "unknown"},
            "shareholding": sh or "not held for this name", "bulk_block_deals_180d": dl or {"n": 0}, "insider_sast_announcements_180d": ann.get("insider_sast"), "deals_label": DEALS_LABEL,
            "last_result_filed": ann.get("last_result"), "recent_announcements": ann.get("recent", []),
            "events": graph_events(con, [isin], now, days=365).get(isin, [])[:8],
            "red_flags": "table not held" if ft_flags is None else [{"flag": r.flag, "usable_from": str(r.usable_from)[:10], "headline": _cut(r.headline, 100)} for r in ft_flags[ft_flags["isin"] == isin].head(8).itertuples()],
            "price_range": stored_range(con, root, [isin], day).get(isin) or "no stored range for this name (only held and listed names get one each night)",
            "storylines": storyline_hits(con, "IN", [{"key": isin, "symbol": sym, "name": meta.get("name"), "sector": sec}]).get(isin, []),
            "held": {"qty": held_q, "weight_pct": _pct(w, 2)} if h else False,
            "rails": {"one_stock_max_pct": 10.0, "one_sector_max_pct": 25.0, "buy_room_inr_now": None if room is None else round(room), "note": "his limits; the room is what a buy could add today before a rail binds"},
            "data_flags": []}
    if ft["jump"]:
        card["data_flags"].append(f"a one-day move of {ft['jump'] * 100:.0f}% in the last year: a split or bonus may not be adjusted")
    try:
        from pflab.hq import valuation
        card["fundamentals"] = valuation.facts(con, root, isin, sym, c, day)
        card["fundamentals"]["rule_verdicts"] = "see labels.rule_tests: only 'below the 200-day average earns less' passed; every other rule of thumb listed is untested folklore or failed"
    except Exception as e:
        card["fundamentals"] = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    card["says"] = f"{sym}: {_says_price(ft)}" + (f"; trades about Rs {liq_row['median_value_60'] / 1e7:,.0f} crore a day" if liq_row is not None else "")
    return card


def _card_us(con, now, day: date, root: Path, sym: str, get, fetch) -> dict:
    from pflab.data import sec_edgar, us_prices
    from pflab.us import data as usdata, instruments as uins, picks_floor as pf
    sym = sym.replace(".", "-")
    notes = [US_NOTE]
    df = usdata.bars(sym, root)
    if df is None or df.empty:
        rep = us_download([sym], root, fetch, cap=1)
        df = usdata.bars(sym, root)
        notes.append("bars downloaded on demand" if rep["fetched"] else f"no bars on disk and the download failed ({next(iter(rep['failed'].values()), 'network down')[:80]})")
    if df is None or df.empty:
        return {"ok": False, "problem": f"no daily bars for {sym}: it cannot be checked against the floor", "note": " | ".join(notes)}
    last = df["date"].iloc[-1]
    if (day - last).days > pf.STALE_DAYS:                                   # old bars: append the last days before judging the floor
        rep = us_download([sym], root, fetch, cap=1, recent_days=15)
        df = usdata.bars(sym, root)
        notes.append("old bars refreshed on demand" if rep["fetched"] else f"the bars are old (last {last}) and could not be refreshed ({next(iter(rep['failed'].values()), 'network down')[:80]})")
    ciks = uins.load_ciks(root)
    u = next((x for x in us_universe(root) if x["ticker"].upper() == sym or x["ticker"].upper().replace(".", "-") == sym), {})
    cik = u.get("cik") or ciks.get(sym)
    fl = pf.floor_from_bars(sym, df, day)
    ft = _us_features(df, day)
    facts = us_facts(cik, root, day, get=get, allow_network=True)
    shares = (facts.get("shares_outstanding") or {}).get("shares")
    filings = []
    if cik:
        try:
            sub = sec_edgar.submissions(int(cik), root, get=get or sec_edgar.get_json, refresh=True)
        except Exception as e:
            p = root / "us" / "sec" / f"submissions_{int(cik):010d}.parquet"
            sub = pd.read_parquet(p) if p.exists() else None
            notes.append(f"SEC filings could not be fetched ({type(e).__name__})" + ("; the cached list is used" if sub is not None else ""))
        if sub is not None and len(sub):
            upto = pd.Timestamp(now if isinstance(now, datetime) else datetime.combine(now, datetime.max.time()))
            s = sub[(sub["accepted"] <= upto) & sub["form"].isin(sec_edgar.FORMS)].sort_values("accepted", ascending=False).head(8)
            filings = [f"{pd.Timestamp(r.accepted):%Y-%m-%d %H:%M} UTC {r.form}" for r in s.itertuples()]
    key = uins.key_for(con, sym, ciks) if cik else "US:" + sym
    held = sym in set(us_prices.held_symbols(con))
    sub_book = _us_subbook(con, day)
    card = {"ok": True, "symbol": sym, "name": u.get("title") or facts.get("entity"), "cik": cik, "key": key, "sector": "unknown (not stored; no US sector rail)",
            "price": {"last": _num(ft["price"], 2), "date": ft["price_date"], "return_63d_pct": _pct(ft["ret_63"]), "return_126d_pct": _pct(ft["ret_126"]), "return_252d_pct": _pct(ft["ret_252"]),
                      "vs_200dma_pct": _pct(ft["vs_200dma"]), "volatility_250d_pct": _pct(ft["vol_250"]), "range_52w": [_num(ft["low_52w"], 2), _num(ft["high_52w"], 2)],
                      "from_52w_high_pct": _pct(ft["from_52w_high"]), "sessions": ft["sessions"], "note": "returns use dividend-adjusted closes"},
            "liquidity": {"median_traded_value_usd_60d": None if fl["median_value_usd"] is None else round(fl["median_value_usd"]), "sessions": fl["sessions"], "floor": fl["reason"], "clears_a62_floor": fl["ok"]},
            "tradable": pf.tradable_note(sym, root), "size": {"market_cap_usd": None if not shares else round(shares * ft["price"]), "label": "estimate: SEC shares outstanding x the last close" if shares else "unknown"},
            "sec_facts": facts, "recent_filings": filings, "events": graph_events(con, [key], now, days=365).get(key, [])[:8], "red_flags": "not checked (no US red-flag table)",
            "held": held, "rails": _us_rails(con, day, sub_book, fl, held), "history_warning": US_NOTE, "note": " | ".join(notes)}
    card["says"] = f"{sym}: {_says_price(ft)}; {'clears' if fl['ok'] else 'does NOT clear'} the A62 floor"
    return card


def _us_subbook(con, day: date) -> Optional[float]:
    """The US sub-book's latest marked value in USD on or before `day`, else its starting dollars, else None."""
    for q, a in (("SELECT value_usd FROM us_days_s81 WHERE day <= ? ORDER BY day DESC LIMIT 1", [day]), ("SELECT start_usd FROM us_account_s81 ORDER BY account_id LIMIT 1", [])):
        try:
            r = con.execute(q, a).fetchone()
            if r and r[0]:
                return float(r[0])
        except Exception:
            continue
    return None


def _us_rails(con, day: date, sub_book: Optional[float], fl: dict, held: bool) -> dict:
    n = None
    try:
        n = int(con.execute("SELECT count(DISTINCT symbol) FROM us_lots_s81 WHERE qty > 0 AND symbol <> 'SPY'").fetchone()[0])
    except Exception:
        pass
    return {"one_stock_max_pct_of_subbook": 10.0, "max_value_usd_now": None if sub_book is None else round(0.10 * sub_book), "subbook_usd": None if sub_book is None else round(sub_book),
            "spy_at_least_pct": 30.0, "max_stocks": 12, "stocks_held_now": n, "room_for_another_stock": None if n is None else bool(held or n < 12), "floor_ok": fl["ok"],
            "note": "A62 rails as shares of the sub-book; no US sector rail"}
