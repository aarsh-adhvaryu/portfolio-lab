"""NSE corporate-actions feed: exact split and bonus factors.

Charter section 15, 2026-09-16: this supersedes the PREVCLOSE method of
section 9, which failed its mandated verification (NSE does not publish an
adjusted PREVCLOSE -- see docs/data/adjustment_method_finding.md).

Source: https://www.nseindia.com/api/corporates-corporateActions
        ?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY

Rows carry `isin` directly, so no symbol join is needed. The factor comes from
the free-text `subject` (NSE's PURPOSE field):

    Bonus a:b        a new shares for every b held -> factor b / (a + b)
    Face value X->Y  sub-division                  -> factor Y / X

A factor multiplies every price strictly before the ex-date. Both can land on
one ex-date ("Bonus 1:1 / Face Value Split From Rs 10/- To Rs 2/-"), in which
case they multiply.

Coverage is thin before 2006 (2004: 0 split/bonus rows, 2005: 1). That falls in
the section 11 warmup, which does no trading, but the first months of
development inherit it through the 252-session lookback.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import data_dir
from pflab.data.bhavcopy import HEADERS

API = "https://www.nseindia.com/api/corporates-corporateActions"
REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-actions"

# "Bonus 1:1", "Bonus 1 : 1", "Bonus - 1:2", "Bonus Issue 1:1", and the
# pre-2010 abbreviation "Bon-1:1" / "Bon 12:1".
_BONUS = re.compile(r"\bbon(?:us)?\b(?:\s*issue)?\s*[-:]?\s*(\d+)\s*:\s*(\d+)", re.I)
# The old-to-new face value, across every phrasing seen in the live feed:
#   "From Rs 10/- Per Share To Rs 2/- Per Share"   the common modern form
#   "From Rs 10 To Re 1"                           Re for the singular rupee
#   "Rs 10 To Rs 1"                                no "From"
#   "Rs 10/- Per To Rs 2/-"                        NSE drops "Share"
#   "From Rs 10/- Each To Rs 2/- Each"             "Each" instead of "Per Share"
#   "From 10/- To Face Value 2/-"                  no currency token at all
#   "Spl-Rs 5/ To 2/"                              abbreviated, currency on one side
# The currency is therefore optional, which is only safe because _IS_SPLIT
# gates this to rows that already say "split"; _plausible_face_values then
# rejects anything that is not a face-value pair.
_SPLIT = re.compile(
    r"(?:from\s*)?(?:rs|re)?\.?\s*([\d]+(?:\.\d+)?)\s*/?-?\s*"
    r"(?:each|per\s*(?:share)?)?\s*"
    r"to\s*(?:face\s*value\s*)?(?:rs|re)?\.?\s*([\d]+(?:\.\d+)?)", re.I)
# "Face Valus Split" is NSE's own typo; "Spl-" is the pre-2010 abbreviation.
_IS_SPLIT = re.compile(r"face\s*val\w*\s*split|sub[-\s]?division|\bspl\b\s*[-.]?\s*",
                       re.I)
# Indian face values are 1, 2, 5, 10 and occasionally 100. A pair outside this
# range is a dividend amount or a ratio that slipped through, not a split.
MAX_FACE_VALUE = 1000.0


def _plausible_face_values(old: float, new: float) -> bool:
    return 0 < new < old <= MAX_FACE_VALUE
# A bonus DEBENTURE issues debt, not shares: the share count does not change.
_DEBENTURE = re.compile(r"bonus\s+debenture", re.I)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({**HEADERS, "Accept": "*/*", "Referer": REFERER})
    try:
        s.get(REFERER, timeout=40)
    except Exception:
        pass
    return s


def fetch_year(s: requests.Session, year: int, timeout: int = 120) -> list:
    r = s.get(API, params={"index": "equities",
                           "from_date": f"01-01-{year}", "to_date": f"31-12-{year}"},
              timeout=timeout)
    r.raise_for_status()
    rows = r.json()
    return rows if isinstance(rows, list) else []


def collect(start_year: int = 2004, end_year: Optional[int] = None,
            root: Optional[Path] = None, sleep: float = 1.2,
            refresh: bool = False) -> Path:
    """Download the feed year by year into data/corporate_actions/raw/."""
    root = root or data_dir()
    end_year = end_year or date.today().year
    out_dir = root / "corporate_actions" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    s = _session()
    for y in range(start_year, end_year + 1):
        f = out_dir / f"{y}.json"
        if f.exists() and not refresh:
            continue
        rows = fetch_year(s, y)
        f.write_text(json.dumps(rows), encoding="utf-8")
        print(f"  {y}: {len(rows):5d} rows", flush=True)
        time.sleep(sleep)
    return out_dir


def load_raw(root: Optional[Path] = None) -> pd.DataFrame:
    root = root or data_dir()
    d = root / "corporate_actions" / "raw"
    rows = []
    for f in sorted(d.glob("*.json")):
        rows.extend(json.loads(f.read_text(encoding="utf-8")))
    if not rows:
        raise ValueError(f"no corporate-action files under {d}")
    df = pd.DataFrame(rows)
    df["ex_date"] = pd.to_datetime(df["exDate"], format="%d-%b-%Y",
                                   errors="coerce").dt.date
    df["subject"] = df["subject"].fillna("").str.strip()
    return df.dropna(subset=["ex_date"])


def parse_purpose(subject: str) -> list[tuple]:
    """(kind, factor) pairs implied by one PURPOSE string. Empty if none.

    A factor multiplies prices before the ex-date, so it is always < 1 for a
    bonus or a sub-division.
    """
    out: list[tuple] = []
    if not subject:
        return out
    text = subject.replace("\xa0", " ")

    if not _DEBENTURE.search(text):
        for a, b in _BONUS.findall(text):
            a, b = int(a), int(b)
            if a > 0 and b > 0:
                out.append(("bonus", b / (a + b)))

    if _IS_SPLIT.search(text):
        for old, new in _SPLIT.findall(text):
            # A sub-division always reduces the face value, so this also
            # rejects a dividend's "Rs 2 to Rs 5" style text and consolidations.
            if _plausible_face_values(float(old), float(new)):
                out.append(("split", float(new) / float(old)))
                break      # one sub-division per row; later matches are noise
    return out


def factors(root: Optional[Path] = None, raw: Optional[pd.DataFrame] = None,
            series: tuple = ("EQ",)) -> pd.DataFrame:
    """(isin, ex_date, factor) -- one row per security per ex-date."""
    df = raw if raw is not None else load_raw(root)
    if series:
        df = df[df["series"].isin(series)]
    df = df[df["isin"].notna() & df["isin"].ne("-")]
    recs = []
    for r in df.itertuples(index=False):
        for kind, f in parse_purpose(r.subject):
            recs.append({"isin": r.isin, "ex_date": r.ex_date, "factor": f,
                         "kind": kind, "subject": r.subject})
    if not recs:
        return pd.DataFrame(columns=["isin", "ex_date", "factor"])
    ev = pd.DataFrame(recs)
    # Two actions on one ex-date compound; identical duplicate rows do not.
    ev = ev.drop_duplicates(["isin", "ex_date", "kind", "factor"])
    out = ev.groupby(["isin", "ex_date"], as_index=False)["factor"].prod()
    return out.sort_values(["isin", "ex_date"]).reset_index(drop=True)


def events(root: Optional[Path] = None, raw: Optional[pd.DataFrame] = None,
           series: tuple = ("EQ",)) -> pd.DataFrame:
    """Every parsed action with its source text, for review."""
    df = raw if raw is not None else load_raw(root)
    if series:
        df = df[df["series"].isin(series)]
    recs = []
    for r in df.itertuples(index=False):
        for kind, f in parse_purpose(r.subject):
            recs.append({"isin": r.isin, "ex_date": r.ex_date, "kind": kind,
                         "factor": f, "subject": r.subject})
    return pd.DataFrame(recs)


PREVCLOSE_THRESHOLD = 0.02


def prevclose_factors(panel: pd.DataFrame, parsed: Optional[pd.DataFrame] = None,
                      threshold: float = PREVCLOSE_THRESHOLD) -> pd.DataFrame:
    """Factors NSE discloses through PREVCLOSE that the PURPOSE text does not.

    Demergers, schemes of arrangement and capital reductions carry no ratio in
    `subject` -- the row just says "Demerger" -- so `parse_purpose` cannot read
    them. The security is normally suspended for the event, and on the session
    it resumes NSE publishes an already-adjusted PREVCLOSE. Comparing that with
    the last traded close recovers the factor exactly:

        SUVEN  last trade 2020-01-20 close 304.20
               resumes    2020-02-03 close  26.95, prev_close 24.50
               factor = 24.50 / 304.20 = 0.0805

    This does NOT contradict the §15 finding that PREVCLOSE is unadjusted for
    bonuses and splits: those trade through without a suspension, and there
    NSE carries the raw prior close. The two cases are disjoint, and pairs
    already covered by `parsed` are excluded so nothing is adjusted twice.

    Without this, a held name that demerges registers as a -40%+ return, a
    fake band exit under §4 and a spurious STCG event under §8.
    """
    need = {"isin", "date", "close", "prev_close"}
    if not need <= set(panel.columns):
        raise ValueError(f"panel is missing {sorted(need - set(panel.columns))}")
    p = panel.sort_values(["isin", "date"], kind="mergesort")
    last = p.groupby("isin", sort=False)["close"].shift(1)
    ratio = p["prev_close"] / last
    hit = (last > 0) & (p["prev_close"] > 0) & ratio.notna() \
        & ((ratio - 1.0).abs() > threshold)
    out = pd.DataFrame({"isin": p.loc[hit, "isin"].values,
                        "ex_date": p.loc[hit, "date"].values,
                        "factor": ratio[hit].values,
                        # §9: a PREVCLOSE-derived factor reaches a held
                        # position as a cash credit, not a price move, so the
                        # engine must be able to tell the two kinds apart.
                        "source": "prevclose",
                        "prior_close": last[hit].values,
                        "adj_prev_close": p.loc[hit, "prev_close"].values})
    if parsed is not None and len(parsed):
        seen = set(zip(parsed["isin"], pd.to_datetime(parsed["ex_date"]).dt.date))
        keep = [(i, d) not in seen for i, d in zip(out["isin"], out["ex_date"])]
        out = out[keep]
    return out.sort_values(["isin", "ex_date"]).reset_index(drop=True)


def resolve_dividend_collisions(extra: pd.DataFrame, dividends: Optional[pd.DataFrame],
                                tol: float = 0.25) -> tuple:
    """§9: on an ex-date carrying both a PREVCLOSE factor and a dividend for
    one ISIN, only one applies.

    NSE adjusts PREVCLOSE for a large dividend, and the dividend feed credits
    the same cash, so keeping both double-counts. The dividend wins when the
    implied per-share drop is explained by it (within `tol`, relative); the
    factor wins otherwise, which is the demerger-plus-incidental-dividend case.
    Returns (kept_factors, report).
    """
    rep = {"coinciding": 0, "dividend_wins": 0, "factor_wins": 0}
    if extra.empty or dividends is None or len(dividends) == 0:
        return extra, rep
    d = dividends.copy()
    d["ex_date"] = pd.to_datetime(d["ex_date"]).dt.date
    m = extra.merge(d[["isin", "ex_date", "dividend_per_share"]],
                    on=["isin", "ex_date"], how="left")
    hit = m["dividend_per_share"].notna()
    rep["coinciding"] = int(hit.sum())
    if not hit.any():
        return extra, rep
    implied = m["prior_close"] - m["adj_prev_close"]
    explained = hit & (m["dividend_per_share"] > 0) & implied.gt(0) &         ((implied - m["dividend_per_share"]).abs() / m["dividend_per_share"] <= tol)
    rep["dividend_wins"] = int(explained.sum())
    rep["factor_wins"] = int(hit.sum() - explained.sum())
    # Where the factor wins, the dividend must go: the cash is already in the
    # PREVCLOSE adjustment, so crediting it again double-counts.
    loser = hit & ~explained
    rep["dividends_dropped"] = sorted(
        (i, str(x)) for i, x in zip(m.loc[loser, "isin"], m.loc[loser, "ex_date"]))
    return extra[~explained.values].reset_index(drop=True), rep


def combined_factors(panel: pd.DataFrame, parsed: Optional[pd.DataFrame] = None,
                     root: Optional[Path] = None,
                     dividends: Optional[pd.DataFrame] = None) -> tuple:
    """Parsed PURPOSE factors plus the PREVCLOSE-implied ones. (factors, report)."""
    parsed = factors(root) if parsed is None else parsed
    extra = prevclose_factors(panel, parsed)
    extra, rep = resolve_dividend_collisions(extra, dividends)
    rep.setdefault("dividends_dropped", [])
    # prior_close / adj_prev_close let the engine compute the §9 cash credit
    # directly: (prior_close - adj_prev_close) x shares held. They are null for
    # PURPOSE factors, which are share-count events, not cash events.
    keep = ["isin", "ex_date", "factor", "source", "prior_close", "adj_prev_close"]
    base = parsed.copy()
    base["source"] = "purpose"
    base["prior_close"] = pd.NA
    base["adj_prev_close"] = pd.NA
    both = pd.concat([base[keep], extra[keep]], ignore_index=True)
    rep["purpose"] = int(len(base))
    rep["prevclose"] = int(len(extra))
    return both.sort_values(["isin", "ex_date"]).reset_index(drop=True), rep


def write(f: pd.DataFrame, root: Optional[Path] = None) -> Path:
    root = root or data_dir()
    p = root / "corporate_actions" / "factors.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    f.to_parquet(p, index=False)
    return p


def load(root: Optional[Path] = None) -> pd.DataFrame:
    root = root or data_dir()
    return pd.read_parquet(root / "corporate_actions" / "factors.parquet")


def cash_credit_per_share(row) -> float:
    """§9: the per-share cash a held position receives on a PREVCLOSE factor.

    prior close minus the adjusted prev close. The engine multiplies by shares
    held, reduces the lot's cost basis in the same proportion as the price,
    and realises nothing -- it is not a sale, so no §8 tax event occurs.
    Returns 0.0 for a PURPOSE factor, which changes the share count instead.
    """
    if row.get("source") != "prevclose":
        return 0.0
    prior, adj = row.get("prior_close"), row.get("adj_prev_close")
    if prior is None or adj is None or pd.isna(prior) or pd.isna(adj):
        return 0.0
    return max(float(prior) - float(adj), 0.0)
