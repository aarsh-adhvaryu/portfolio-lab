"""Prices, NAVs, gold marks and live quotes into the PM store (PLAN S8).

Sources: NSE bhavcopy (every series, so ETFs, SGBs, G-secs and listed bonds
get a close), AMFI `NAVAll.txt` and NAV history, IBJA gold rates, and the Kite
live quotes through an injected quote function (no key needed to test).

Staleness: a close is stale when more than one NSE session old; an AMFI NAV
when more than one business day old (PLAN §5). Nothing is silently carried
forward: `latest_price` always says how old the value is.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import pandas as pd

# bhavcopy series that carry a priced security. Everything with an ISIN.
LIVE_START, LIVE_END = time(9, 15), time(15, 30)   # NSE cash session, IST
QUOTE_BATCH = 500        # Kite quote(): up to 500 instruments per call
QUOTE_INTERVAL_S = 1.0   # Kite quote(): 1 request per second
PRICE_STALE_SESSIONS = 1
NAV_STALE_BUSINESS_DAYS = 1


# --- bhavcopy -----------------------------------------------------------------

def bhavcopy_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Normalised bhavcopy -> price rows: (isin, date, close, series). Rows without
    an ISIN or a positive close are dropped (suspended or untraded lines)."""
    d = df[["isin", "date", "close", "series"]].copy()
    d = d[d["isin"].notna() & (d["close"] > 0)]
    return d.drop_duplicates(["isin", "date", "series"], keep="last").reset_index(drop=True)


def load_bhavcopy(con, df: pd.DataFrame, source: str = "nse_bhavcopy",
                  now: Optional[datetime] = None) -> int:
    """Insert price rows, ignoring ones already stored. Returns rows added."""
    rows = bhavcopy_rows(df)
    # a security can trade in two series on one day: keep the one with the most recent listing row
    rows = rows.drop_duplicates(["isin", "date"], keep="last")
    rows["source"], rows["fetched_at"] = source, now or datetime.now()
    before = con.execute("SELECT count(*) FROM prices").fetchone()[0]
    con.register("_p", rows)
    con.execute("""INSERT INTO prices SELECT isin, date, close, series, source, fetched_at FROM _p
                   ON CONFLICT DO NOTHING""")
    con.unregister("_p")
    return con.execute("SELECT count(*) FROM prices").fetchone()[0] - before


# --- AMFI ----------------------------------------------------------------------

def navs_from_navall(amfi: pd.DataFrame) -> pd.DataFrame:
    """`instruments.parse_navall` output -> one NAV row per ISIN (both ISINs of a scheme)."""
    out = []
    for r in amfi.itertuples():
        if pd.isna(r.nav) or pd.isna(r.nav_date):
            continue
        for i in (r.isin_1, r.isin_2):
            if isinstance(i, str) and i:
                out.append((i, r.scheme_code, r.nav_date, float(r.nav)))
    return pd.DataFrame(out, columns=["isin", "scheme_code", "date", "nav"]).drop_duplicates(
        ["isin", "date"], keep="last")


def parse_nav_history(text: str) -> pd.DataFrame:
    """AMFI `DownloadNAVHistoryReport` text -> isin, scheme_code, date, nav. Rows with
    no ISIN (unclaimed-redemption pools) are dropped: nothing can hold them."""
    rows = []
    for line in text.splitlines():
        f = [x.strip() for x in line.split(";")]
        if len(f) < 8 or not f[0].isdigit():
            continue
        nav = pd.to_numeric(f[6], errors="coerce")
        dt = pd.to_datetime(f[7], format="%d-%b-%Y", errors="coerce")
        if pd.isna(nav) or pd.isna(dt):
            continue
        for i in (f[4], f[5]):
            if i and i != "-":
                rows.append((i, f[0], dt.date(), float(nav)))
    return pd.DataFrame(rows, columns=["isin", "scheme_code", "date", "nav"]).drop_duplicates(
        ["isin", "date"], keep="last").reset_index(drop=True)


def load_navs(con, navs: pd.DataFrame, source: str, now: Optional[datetime] = None) -> int:
    n = navs.copy()
    n["source"], n["fetched_at"] = source, now or datetime.now()
    before = con.execute("SELECT count(*) FROM navs").fetchone()[0]
    con.register("_n", n)
    con.execute("""INSERT INTO navs SELECT isin, scheme_code, date, nav, source, fetched_at FROM _n
                   ON CONFLICT DO NOTHING""")
    con.unregister("_n")
    return con.execute("SELECT count(*) FROM navs").fetchone()[0] - before


def fetch_nav_history(start: date, end: date, session=None, chunk_days: int = 30) -> pd.DataFrame:
    """Download AMFI NAV history in chunks (the report is large: ~2.5 MB per 4 days)."""
    import requests
    s = session or requests
    out, d = [], start
    while d <= end:
        e = min(d + timedelta(days=chunk_days - 1), end)
        r = s.get("https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx",
                  params={"frmdt": d.strftime("%d-%b-%Y"), "todt": e.strftime("%d-%b-%Y")},
                  headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
        r.raise_for_status()
        out.append(parse_nav_history(r.text))
        d = e + timedelta(days=1)
    return pd.concat(out, ignore_index=True).drop_duplicates(["isin", "date"], keep="last") \
        if out else pd.DataFrame(columns=["isin", "scheme_code", "date", "nav"])


def nav_gaps(con, isin: str, max_gap_business_days: int = 4) -> List[tuple]:
    """Stretches where a fund's NAV series skips more than `max_gap_business_days`
    business days: (last_date_before, first_date_after, business_days_missing)."""
    ds = [r[0] for r in con.execute("SELECT DISTINCT date FROM navs WHERE isin=? ORDER BY date",
                                    [isin]).fetchall()]
    gaps = []
    for a, b in zip(ds, ds[1:]):
        missing = len(pd.bdate_range(a + timedelta(days=1), b - timedelta(days=1)))
        if missing > max_gap_business_days:
            gaps.append((a, b, missing))
    return gaps


# --- IBJA gold -----------------------------------------------------------------

_TAB = re.compile(r'<div id="tab-(am|pm)"')
_ROW = re.compile(r"<tr>\s*<td[^>]*data-label=\"(?:AM|PM)\"[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r'<td[^>]*data-label="([^"]+)"[^>]*>(.*?)</td>', re.S)
_METAL = {"Gold 999": "gold999", "Gold 995": "gold995", "Gold 916": "gold916", "Gold 750": "gold750",
          "Gold 585": "gold585", "Silver 999": "silver999", "Platinum 999": "platinum999"}


def parse_ibja(html: str) -> pd.DataFrame:
    """ibjarates.com page -> date, session (AM|PM), metal, rate, unit. Gold is Rs per
    10 g, silver Rs per kg, platinum as published; rates exclude 3% GST and making
    charges (page footnote). Reads the previous-days tables only."""
    out = []
    tabs = [(m.group(1).upper(), m.start()) for m in _TAB.finditer(html)]
    for k, (sess, start) in enumerate(tabs):
        end = tabs[k + 1][1] if k + 1 < len(tabs) else len(html)
        for row in re.finditer(r"<tr>(.*?)</tr>", html[start:end], re.S):
            cells = {lab: re.sub(r"<[^>]+>", "", val).strip() for lab, val in _CELL.findall(row.group(1))}
            ds = cells.get("AM") or cells.get("PM")
            if not ds:
                continue
            d = datetime.strptime(ds, "%d/%m/%Y").date()
            for label, metal in _METAL.items():
                if cells.get(label, "").replace(",", "").isdigit():
                    unit = "per_kg" if metal.startswith("silver") else "per_10g"
                    out.append((d, sess, metal, float(cells[label].replace(",", "")), unit))
    return pd.DataFrame(out, columns=["date", "session", "metal", "rate", "unit"])


def load_gold(con, rates: pd.DataFrame, source: str = "ibja", now: Optional[datetime] = None) -> int:
    r = rates.copy()
    r["source"], r["fetched_at"] = source, now or datetime.now()
    before = con.execute("SELECT count(*) FROM gold_rates").fetchone()[0]
    con.register("_g", r)
    con.execute("""INSERT INTO gold_rates SELECT date, session, metal, rate, unit, source, fetched_at
                   FROM _g ON CONFLICT DO NOTHING""")
    con.unregister("_g")
    return con.execute("SELECT count(*) FROM gold_rates").fetchone()[0] - before


def fetch_ibja(session=None) -> pd.DataFrame:
    import requests
    r = (session or requests).get("https://ibjarates.com/", headers={"User-Agent": "Mozilla/5.0"},
                                  timeout=60)
    r.raise_for_status()
    return parse_ibja(r.text)


def gold_mark(con, grams: float, purity: str = "gold999", asof: Optional[date] = None,
              session: str = "PM") -> dict:
    """Value of physical gold at the latest IBJA rate on or before `asof`
    (PM rate, else AM). Returns value, rate date and the staleness in business days."""
    asof = asof or date.today()
    row = con.execute("""SELECT date, session, rate FROM gold_rates WHERE metal=? AND date<=?
                         ORDER BY date DESC, CASE session WHEN ? THEN 0 ELSE 1 END LIMIT 1""",
                      [purity, asof, session]).fetchone()
    if row is None:
        raise LookupError(f"no IBJA {purity} rate on or before {asof}")
    d, sess, rate = row
    return {"value": grams / 10.0 * rate, "rate": rate, "rate_date": d, "session": sess,
            "stale": _business_days_between(d, asof) > NAV_STALE_BUSINESS_DAYS}


# --- staleness and lookup -------------------------------------------------------

def _business_days_between(a: date, b: date) -> int:
    """Weekdays strictly after `a` up to and including `b`."""
    return len(pd.bdate_range(a + timedelta(days=1), b)) if b > a else 0


def sessions_between(con, last: date, asof: date) -> int:
    """NSE sessions after `last` up to `asof`: known session dates from the price table,
    plus weekdays beyond the latest stored session (holidays there are unknown)."""
    if asof <= last:
        return 0
    known_max = con.execute("SELECT max(date) FROM prices").fetchone()[0]
    if known_max is None:
        return _business_days_between(last, asof)
    inside = con.execute("SELECT count(DISTINCT date) FROM prices WHERE date > ? AND date <= ?",
                         [last, min(asof, known_max)]).fetchone()[0]
    beyond = _business_days_between(known_max, asof) if asof > known_max else 0
    return inside + beyond


@dataclass(frozen=True)
class Quote:
    isin: str
    value: float
    date: date
    kind: str          # live | close | nav
    source: str
    stale: bool
    age: int           # sessions (close) or business days (nav) behind asof


def latest_price(con, isin: str, asof: date) -> Optional[Quote]:
    """Best available value for `isin` on or before `asof`, with its staleness; None if
    nothing exists. The newest date wins; on a tie live beats close beats NAV. A live quote
    counts only when it was taken on `asof` itself."""
    cands = []
    px = con.execute("SELECT date, close, source FROM prices WHERE isin=? AND date<=? "
                     "ORDER BY date DESC LIMIT 1", [isin, asof]).fetchone()
    if px:
        age = sessions_between(con, px[0], asof)
        cands.append(Quote(isin, px[1], px[0], "close", px[2], age > PRICE_STALE_SESSIONS, age))
    nv = con.execute("SELECT date, nav, source FROM navs WHERE isin=? AND date<=? "
                     "ORDER BY date DESC LIMIT 1", [isin, asof]).fetchone()
    if nv:
        age = _business_days_between(nv[0], asof)
        cands.append(Quote(isin, nv[1], nv[0], "nav", nv[2], age > NAV_STALE_BUSINESS_DAYS, age))
    lv = con.execute("SELECT ts, ltp, source FROM live_quotes WHERE isin=? AND ts<=? "
                     "ORDER BY ts DESC LIMIT 1", [isin, datetime.combine(asof, time(23, 59))]).fetchone()
    if lv and lv[0].date() == asof:
        cands.append(Quote(isin, lv[1], lv[0].date(), "live", lv[2], False, 0))
    if not cands:
        return None
    rank = {"live": 0, "close": 1, "nav": 2}
    cands.sort(key=lambda q: (-q.date.toordinal(), rank[q.kind]))
    return cands[0]


def coverage(con, isins: Iterable[str], asof: date) -> pd.DataFrame:
    """One row per ISIN: value, date, kind, stale, age. Missing ISINs have kind 'none'."""
    rows = []
    for i in isins:
        q = latest_price(con, i, asof)
        rows.append(dict(isin=i, value=q.value if q else None, date=q.date if q else None,
                         kind=q.kind if q else "none", stale=True if q is None else q.stale,
                         age=q.age if q else None))
    return pd.DataFrame(rows, columns=["isin", "value", "date", "kind", "stale", "age"])


def all_priced_fresh(con, isins: Iterable[str], asof: date) -> bool:
    """PLAN S8 acceptance test: every held ISIN has a price at most one session old."""
    cov = coverage(con, list(isins), asof)
    return bool((cov["kind"] != "none").all() and (~cov["stale"]).all())


# --- live poller ----------------------------------------------------------------

def market_open(ts: datetime) -> bool:
    """Mon-Fri 09:15-15:30 (IST wall time). NSE holidays are not known here: a poll on a
    holiday returns the previous close, which the staleness rules already flag."""
    return ts.weekday() < 5 and LIVE_START <= ts.time() <= LIVE_END


class LivePoller:
    """Polls `quote_fn(list_of_isins) -> {isin: ltp}` in batches while the market is open."""

    def __init__(self, con, isins: Sequence[str], quote_fn: Callable[[List[str]], Dict[str, float]],
                 source: str = "kite"):
        self.con, self.isins, self.quote_fn, self.source = con, list(isins), quote_fn, source

    def poll(self, now: datetime) -> int:
        """One round. Returns quotes stored (0 outside market hours)."""
        if not market_open(now):
            return 0
        n = 0
        for k in range(0, len(self.isins), QUOTE_BATCH):
            got = self.quote_fn(self.isins[k:k + QUOTE_BATCH])
            for isin, ltp in got.items():
                if ltp and ltp > 0:
                    self.con.execute("INSERT INTO live_quotes VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                                     [isin, now, float(ltp), self.source])
                    n += 1
        return n


# --- refresh ----------------------------------------------------------------------

def refresh(con, days: int = 30, root=None, network: bool = True) -> dict:
    """Load what is on disk and (if `network`) today's AMFI NAVs and IBJA rates.
    Bhavcopy files come from `tools/collect_daily.py`; this never downloads them."""
    from pflab.data import bhavcopy
    out = {}
    end = date.today()
    df = bhavcopy.load(end - timedelta(days=days), end, root=root, series=None)
    out["prices"] = load_bhavcopy(con, df) if len(df) else 0
    # BSE closes only for ISINs with no NSE price in the window (BSE-only listings): one price source per security
    from pflab.data import bse_bhavcopy
    bse = bse_bhavcopy.load(end - timedelta(days=days), end, root=root)
    nse = set(df["isin"].dropna()) if len(df) else set()
    nse |= {r[0] for r in con.execute("SELECT DISTINCT isin FROM prices WHERE source = 'nse_bhavcopy' AND date >= ?",
                                      [end - timedelta(days=days)]).fetchall()}
    bse = bse[~bse["isin"].isin(nse)] if len(bse) else bse
    out["bse_prices"] = load_bhavcopy(con, bse, source="bse_bhavcopy") if len(bse) else 0
    out["last_price_date"] = con.execute("SELECT max(date) FROM prices").fetchone()[0]
    if network:
        out.update(refresh_nav_gold(con, root))
    return out


def refresh_nav_gold(con, root=None) -> dict:
    """Today's AMFI NAVs and the IBJA gold rates (network)."""
    from pflab.pm import instruments as ins
    out = {}
    text, _sha = ins.fetch_amfi(root)
    out["navs"] = load_navs(con, navs_from_navall(ins.parse_navall(text)), "amfi_navall")
    try:
        out["gold_rates"] = load_gold(con, fetch_ibja())
    except Exception as e:  # IBJA is a scraped page: failure is reported, not fatal
        out["gold_rates"] = f"failed: {type(e).__name__}"
    return out


def ins_fetch_amfi(root=None):
    from pflab.pm import instruments as ins
    return ins.fetch_amfi(root)
