"""Live BSE filings for held and watched names: classify, dedup, alert (PLAN S20).

Source: the BSE announcements collector (`pflab.data.bse_announcements`, day files under
data/bse_announcements, keyed by the dissemination timestamp). A filing is flagged by
`pflab.data.red_flags.classify` (category first, regex second; frozen rules). Alerts are sent for
flagged filings of names on the watchlist only, once each: `alerts_sent` remembers the event id of
everything dispatched, so a re-run, a re-collected day or a duplicate posting does not alert again.

The watchlist ships empty (`configs/watchlist.toml`). While it is empty and no holdings are
passed, `dispatch` sends nothing: alerts are off until the investor names what to watch.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import pandas as pd

from pflab import _toml
from pflab.data import red_flags


def event_id(scrip_code, key_dt, flag: str, headline) -> str:
    """Stable id of one (announcement, flag) row (S63: moved here from the retired A1 feature store)."""
    import hashlib
    s = f"{str(scrip_code).strip()}|{pd.Timestamp(key_dt).isoformat()}|{flag}|{headline or ''}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:20]

WATCHLIST_PATH = Path(__file__).resolve().parents[3] / "configs" / "watchlist.toml"
ATTACH_URL = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{name}"


def load_watchlist(path: Optional[Path] = None) -> List[str]:
    """ISINs on the watchlist file (empty by default)."""
    doc = _toml.load(path or WATCHLIST_PATH)
    return [w["isin"] for w in doc.get("watch", [])]


def targets(holdings: Iterable[str] = (), watchlist: Iterable[str] = ()) -> List[str]:
    """Names to watch: current holdings plus the watchlist, once each."""
    return sorted(set(holdings) | set(watchlist))


def alerts_enabled(names: Sequence[str]) -> bool:
    return len(names) > 0


# --- scrip -> isin ------------------------------------------------------------------------------------

def resolve_isins(ann: pd.DataFrame, scrip_map: pd.DataFrame) -> pd.Series:
    """ISIN of each announcement's scrip at its dissemination date, from the date-ranged BSE map
    (`scrip_code`, `isin`, `valid_from`, `valid_to`). Never a join on scrip alone."""
    m = scrip_map.copy()
    m["scrip_code"] = m["scrip_code"].astype(str).str.strip()
    m["valid_from"] = pd.to_datetime(m["valid_from"])
    m["valid_to"] = pd.to_datetime(m["valid_to"])
    by = {k: g for k, g in m.groupby("scrip_code")}
    out = []
    for sc, t in zip(ann["scrip_code"].astype(str).str.strip(), pd.to_datetime(ann["t"])):
        g = by.get(sc)
        hit = None
        if g is not None:
            ok = g[(g["valid_from"] <= t) & (g["valid_to"] >= t)]
            hit = ok["isin"].iloc[0] if len(ok) else None
        out.append(hit)
    return pd.Series(out, index=ann.index, dtype="object")


# --- classify ------------------------------------------------------------------------------------------------

def _norm(h) -> str:
    return re.sub(r"\W+", " ", str(h or "").lower()).strip()


def classify_announcements(ann: pd.DataFrame, names: Sequence[str], scrip_map: pd.DataFrame) -> pd.DataFrame:
    """One row per (announcement, flag) for filings of `names`; plus one row with flag None for every
    other filing of those names (the daily digest). `ann` is the BSE day-file frame."""
    a = ann.copy()
    a["t"] = pd.to_datetime(a["dissem_dt"]).fillna(pd.to_datetime(a["news_dt"]))
    a["isin"] = resolve_isins(a, scrip_map)
    a = a[a["isin"].isin(set(names))]
    rows = []
    for r in a.itertuples():
        flags = red_flags.classify(r.headline or "", r.category or "", r.subcategory or "")
        base = dict(scrip_code=str(r.scrip_code).strip(), isin=r.isin, company=r.company, headline=r.headline,
                    category=r.category, subcategory=r.subcategory, t=r.t,
                    link=ATTACH_URL.format(name=r.attachment) if r.attachment else None)
        if flags:
            for f in flags:
                rows.append({**base, "flag": f, "event_id": event_id(r.scrip_code, r.t, f, r.headline)})
        else:
            rows.append({**base, "flag": None, "event_id": event_id(r.scrip_code, r.t, "", r.headline)})
    return pd.DataFrame(rows, columns=["scrip_code", "isin", "company", "headline", "category", "subcategory",
                                       "t", "link", "flag", "event_id"])


def dedup_content(ev: pd.DataFrame) -> pd.DataFrame:
    """BSE sometimes posts the same filing twice. Within a day, the same scrip, flag and headline is one event
    (the earliest posting wins)."""
    if ev.empty:
        return ev
    k = ev.assign(_h=ev["headline"].map(_norm), _d=pd.to_datetime(ev["t"]).dt.date)
    k = k.sort_values("t", kind="mergesort").drop_duplicates(["scrip_code", "flag", "_h", "_d"], keep="first")
    return k.drop(columns=["_h", "_d"]).sort_values("t", kind="mergesort").reset_index(drop=True)


# --- alerts -----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Alert:
    event_id: str
    isin: str
    company: str
    flag: str
    headline: str
    t: datetime
    link: Optional[str]
    context: List[str] = field(default_factory=list)

    def text(self) -> str:
        lines = [f"{self.company}: {self.flag.replace('_', ' ').title()}",
                 f"{self.headline}", f"Filed {self.t:%d-%b-%Y %H:%M} (BSE dissemination time)"]
        if self.link:
            lines.append(f"Filing: {self.link}")
        lines += self.context
        lines.append("A classification of the filing's text, not a judgement of its effect. You decide.")
        return "\n".join(lines)


def unsent(con, ev: pd.DataFrame) -> pd.DataFrame:
    """Flagged events whose event id has not been dispatched."""
    f = dedup_content(ev[ev["flag"].notna()])
    if f.empty:
        return f
    seen = {r[0] for r in con.execute("SELECT event_id FROM alerts_sent").fetchall()}
    return f[~f["event_id"].isin(seen)].reset_index(drop=True)


def dispatch(con, ev: pd.DataFrame, names: Sequence[str], send_fn: Callable[[Alert], None],
             context_fn: Optional[Callable[[pd.Series], List[str]]] = None, channel: str = "telegram",
             now: Optional[datetime] = None) -> List[Alert]:
    """Send each new flagged filing once. Returns what was sent. With no names to watch, sends nothing and
    records nothing. An event is recorded only after `send_fn` returns, so a failed send is retried."""
    if not alerts_enabled(names):
        return []
    sent = []
    for r in unsent(con, ev).itertuples():
        row = pd.Series(r._asdict())
        a = Alert(r.event_id, r.isin, r.company, r.flag, r.headline, r.t.to_pydatetime(), r.link,
                  context_fn(row) if context_fn else [])
        send_fn(a)
        con.execute("INSERT INTO alerts_sent VALUES (?,?,?,?,?,?)",
                    [r.event_id, r.flag, r.isin, now or datetime.now(), channel, r.headline])
        sent.append(a)
    return sent


# --- live collection -----------------------------------------------------------------------------------------------

def recent(days: int = 3, root: Optional[Path] = None, today: Optional[date] = None) -> pd.DataFrame:
    """Announcement day files of the last `days` days already on disk (collect them first with
    `pflab collect bse` or tools/collect_daily.py; this never downloads)."""
    from pflab.data import data_dir
    today = today or date.today()
    root = root or data_dir()
    frames = []
    for k in range(days):
        d = today - timedelta(days=k)
        p = root / "bse_announcements" / f"{d.year}" / f"{d.isoformat()}.parquet"
        if p.exists():
            frames.append(pd.read_parquet(p))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["scrip_code", "company", "headline", "category", "subcategory", "news_dt", "dissem_dt",
                 "attachment", "news_sub"])
