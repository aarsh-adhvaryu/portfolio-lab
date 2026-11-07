"""News tone (S79b item 15b, spec (a)).

Two sources:
  * GDELT's own tone: the Global Knowledge Graph files (data/gkg/YYYY-MM-DD.parquet: one row per article, its theme codes, its tone, an India flag) averaged per
    (market, theme, day); and the daily country-level tone of GDELT's world files (data/gdelt/world/daily_by_country.parquet) as a market-wide series.
  * The local FAST model (qwen3:8b-q8_0, grammar-constrained through `llm/structured.py`) reads a headline and returns TWO things only: a theme label from the
    closed list (or "none") and a tone class ("negative" | "neutral" | "positive"). CODE maps the class to -1/0/+1 and computes every figure. The guard
    (`validate_tag`) rejects any other key, any other value, any digit-bearing extra: an answer that is not exactly {theme, tone} is a failed tag, not a score.

Forward-only: the model's reading of a headline is dated by when it was MADE. A tag counts as a signal for day D only if it was made no later than the calendar
day after D (`is_live_tag`); a headline from the past read now is hindsight (the model has seen what came after) and is never used for a historical date
(`model_tone_by_day` leaves it out; `refuse_historical` raises). The pre-registered historical study uses the price-based parts only.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from pflab.sentiment import data_root, settings
from pflab.sentiment import themes as T

TONES = ("negative", "neutral", "positive")
TONE_VALUE = {"negative": -1.0, "neutral": 0.0, "positive": 1.0}
MODEL = "qwen3:8b-q8_0"
MAX_HEADLINE = 220

SYSTEM = ("You label one news headline for an investor in equities. Choose the single best theme from the closed list, or 'none' if no theme fits, and the tone of the "
          "headline for equity investors: negative, neutral or positive. Answer with JSON only: {\"theme\": <key>, \"tone\": <class>}. Never write anything else.")


class ForwardOnly(Exception):
    """A model-read tone was asked for a historical date."""


# --- the guard ------------------------------------------------------------------------------------------------------------------------

def schema(theme_keys: Iterable[str]) -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["theme", "tone"],
            "properties": {"theme": {"type": "string", "enum": list(theme_keys) + [T.NONE]}, "tone": {"type": "string", "enum": list(TONES)}}}


def validate_tag(theme_keys: Iterable[str]) -> Callable[[dict], Optional[str]]:
    keys = set(theme_keys) | {T.NONE}

    def _v(obj: dict) -> Optional[str]:
        if set(obj) != {"theme", "tone"}:
            return f"keys must be exactly theme and tone, got {sorted(obj)}"
        if obj["theme"] not in keys:
            return f"theme must be one of {sorted(keys)}"
        if obj["tone"] not in TONES:
            return f"tone must be one of {list(TONES)}"
        return None
    return _v


# --- headlines ------------------------------------------------------------------------------------------------------------------------

_ID = re.compile(r"^(?:[0-9a-f]{8,}|\d+|[a-z]?\d{5,}[a-z]?)$", re.I)


def slug_title(url: str) -> Optional[str]:
    """A headline recovered from an article URL's last path segment (GKG carries no title). None when it does not read as a sentence."""
    path = re.sub(r"^https?://[^/]+", "", str(url))
    parts = [x for x in re.split(r"[/?#]", path) if x]
    if not parts:
        return None
    best: List[str] = []
    for seg in parts:                                   # the path segment that reads most like a sentence (the last one is often just an id)
        seg = re.sub(r"\.(html?|php|aspx?|cms|ece|amp)$", "", seg, flags=re.I)
        words = [w for w in re.split(r"[-_+ ]+", seg) if w and not _ID.match(w) and re.search(r"[A-Za-z]", w)]
        if len(words) > len(best):
            best = words
    if len(best) < 4:
        return None
    return " ".join(best)[:MAX_HEADLINE]


def doc_key(market: str, day: date, headline: str) -> str:
    return hashlib.sha1(f"{market}|{day}|{re.sub(r'[^a-z0-9]+', ' ', headline.lower()).strip()}".encode()).hexdigest()[:16]


def _hits(text: str, theme: T.Theme) -> bool:
    t = f" {text.lower()} "
    return any(k in t for k in theme.keywords)


def candidates(con, root, market: str, day: date, themes: Optional[Dict[str, T.Theme]] = None, limit: int = 400) -> List[dict]:
    """The headlines of `day` worth reading: store documents (kg_docs titles) and GKG article slugs, kept only if a theme keyword or GKG code touches them.
    Each: {"doc_key","market","day","headline","source"}. Duplicates are dropped."""
    themes = themes if themes is not None else T.load_themes(market)
    out, seen = [], set()

    def add(headline: str, source: str) -> None:
        if not headline:
            return
        k = doc_key(market, day, headline)
        if k not in seen:
            seen.add(k)
            out.append({"doc_key": k, "market": market, "day": day, "headline": headline[:MAX_HEADLINE], "source": source})

    try:
        rows = con.execute("SELECT title FROM kg_docs WHERE title IS NOT NULL AND CAST(published_at AS DATE) = ? ORDER BY published_at DESC LIMIT 2000", [day]).fetchall()
        for (t,) in rows:
            if any(_hits(t, th) for th in themes.values()):
                add(t, "kg_docs")
    except Exception:
        pass
    g = gkg_day(root, day)
    if g is not None and len(g):
        g = g[g["india"].astype(bool)] if market == "IN" and "india" in g.columns else g
        for r in g.itertuples():
            t = slug_title(getattr(r, "url", ""))
            if not t:
                continue
            codes = str(getattr(r, "themes", "") or "")
            if any(_hits(t, th) or any(c in codes for c in th.gkg_codes) for th in themes.values()):
                add(t, "gkg")
    return out[:limit]


# --- GDELT's own tone ----------------------------------------------------------------------------------------------------------------

def gkg_day(root, day: date) -> Optional[pd.DataFrame]:
    p = Path(root) / "gkg" / f"{day}.parquet"
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p)
    except Exception:
        return None


def gkg_theme_tone(root, market: str, themes: Dict[str, T.Theme], start: date, end: date) -> pd.DataFrame:
    """Mean GKG article tone per (theme, day) and the article count n: articles whose theme list contains one of the theme's codes; IN uses the India-flagged
    articles, US all others. Columns: theme, day (Timestamp), tone, n."""
    rows = []
    base = Path(root) / "gkg"
    for f in sorted(base.glob("*.parquet")) if base.exists() else []:
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if not (start <= d <= end):
            continue
        try:
            g = pd.read_parquet(f, columns=["themes", "tone", "india"])
        except Exception:
            continue
        g = g[g["india"].astype(bool)] if market == "IN" else g[~g["india"].astype(bool)]
        th = g["themes"].fillna("")
        for k, t in themes.items():
            m = th.map(lambda s: any(c in s for c in t.gkg_codes)) if t.gkg_codes else pd.Series(False, index=g.index)
            sub = g.loc[m, "tone"].dropna()
            if len(sub):
                rows.append({"theme": k, "day": pd.Timestamp(d), "tone": float(sub.mean()), "n": int(len(sub))})
    return pd.DataFrame(rows, columns=["theme", "day", "tone", "n"])


def gdelt_group_tone(root, groups, start: date, end: date) -> Optional[pd.DataFrame]:
    """Per day, the article-weighted mean tone over the given GDELT groups (finance, energy, tech, regulation, conflict, trade) of the daily sample file
    `data/gdelt_s79b/daily_theme_tone.parquet` (agent D; a sample of about a quarter of the English articles, global). Columns: day, tone, n. None if absent."""
    p = Path(root) / "gdelt_s79b" / "daily_theme_tone.parquet"
    if not p.exists() or not groups:
        return None
    try:
        df = pd.read_parquet(p, columns=["date", "theme", "n_docs", "mean_tone"])
    except Exception:
        return None
    df = df[df["theme"].isin(list(groups))]
    df = df[(pd.to_datetime(df["date"]) >= pd.Timestamp(start)) & (pd.to_datetime(df["date"]) <= pd.Timestamp(end))]
    if df.empty:
        return None
    df = df.assign(day=pd.to_datetime(df["date"]), w=df["n_docs"].astype(float))
    g = df.groupby("day").apply(lambda x: pd.Series({"tone": np.average(x["mean_tone"], weights=x["w"]) if x["w"].sum() > 0 else np.nan, "n": x["w"].sum()}), include_groups=False)
    return g.dropna().reset_index()


COUNTRY = {"IN": "IN", "US": "US"}           # GDELT's FIPS country codes


def country_tone(root, market: str) -> Optional[pd.Series]:
    """GDELT's daily mean tone of events in the market's country (data/gdelt/world/daily_by_country.parquet), weighted by article count; None if absent."""
    p = Path(root) / "gdelt" / "world" / "daily_by_country.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p, columns=["date", "country", "n_articles", "mean_tone"], filters=[("country", "==", COUNTRY.get(market, market))])
    except Exception:
        return None
    if df.empty:
        return None
    df = df.assign(w=df["n_articles"].astype(float))
    s = df.groupby("date").apply(lambda g: np.average(g["mean_tone"], weights=g["w"]) if g["w"].sum() > 0 else np.nan, include_groups=False)
    s.index = pd.to_datetime(s.index)
    return s.dropna().sort_index()


# --- the model's tags ----------------------------------------------------------------------------------------------------------------

def tag_batch(con, items: List[dict], *, limit: Optional[int] = None, chat=None, themes: Optional[Dict[str, T.Theme]] = None, now: Optional[datetime] = None,
              model: Optional[str] = None) -> dict:
    """Tag headlines one call at a time (resumable: a headline already in sentiment_tags_s79 is skipped; the first model failure stops the batch and the rest
    wait for the next run). Returns {"tagged","skipped","failed","stopped","remaining"}."""
    from pflab.llm import structured
    st = settings()
    limit = int(limit if limit is not None else st["tag_limit"])
    themes = themes if themes is not None else T.load_themes()
    keys = list(themes)
    desc = "; ".join(f"{k} = {themes[k].label}" for k in keys)
    sch, val = schema(keys), validate_tag(keys)
    now = now or datetime.now()
    have = {r[0] for r in con.execute("SELECT doc_key FROM sentiment_tags_s79").fetchall()} if items else set()
    todo = [i for i in items if i["doc_key"] not in have]
    out = {"tagged": 0, "skipped": len(items) - len(todo), "failed": 0, "stopped": None, "remaining": 0}
    for n, it in enumerate(todo):
        if out["tagged"] + out["failed"] >= limit:
            out["remaining"] = len(todo) - n
            break
        r = structured.ask_json(SYSTEM, f"Themes: {desc}, none.\nHeadline: {it['headline']}", sch, val, purpose="sentiment_tag", model=model or MODEL,
                                retries=1, num_predict=40, num_ctx=1024, chat=chat)
        if not r.ok:
            out["failed"] += 1
            if r.error and ("Error" in r.error[:40] or "refused" in r.error or "Busy" in r.error or "timed out" in r.error):     # the model could not be reached: stop, do not hammer it
                out["stopped"] = r.error[:120]
                out["remaining"] = len(todo) - n - 1
                break
            continue
        con.execute("INSERT OR IGNORE INTO sentiment_tags_s79 VALUES (?,?,?,?,?,?,?,?,?)",
                    [it["doc_key"], it["market"], it["day"], it["headline"], it.get("source"), r.value["theme"], r.value["tone"], model or MODEL, now])
        out["tagged"] += 1
    return out


def is_live_tag(day, tagged_at) -> bool:
    """A tag is a signal for `day` only if it was made by the end of the next calendar day. Anything later is hindsight."""
    d = day.date() if isinstance(day, datetime) else day
    t = tagged_at.date() if isinstance(tagged_at, datetime) else (tagged_at.date() if hasattr(tagged_at, "date") else tagged_at)
    return t <= d + timedelta(days=1)


def refuse_historical(day, today) -> None:
    """Raise ForwardOnly if `day` is more than one calendar day before `today`: the model-read tone does not exist for a past date (it can only be made live)."""
    d = day.date() if isinstance(day, datetime) else day
    t = today.date() if isinstance(today, datetime) else today
    if d < t - timedelta(days=1):
        raise ForwardOnly(f"model-read news tone is forward-only: {d} is historical (today {t})")


def model_tone_by_day(con, market: str, theme: Optional[str] = None, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
    """Per (theme, day): mean of the tone classes (-1/0/+1) of the LIVE tags and their count. Hindsight tags (made more than a day after their date) are left out.
    Columns: theme, day (Timestamp), tone, n."""
    q = "SELECT theme, day, tone_class, tagged_at FROM sentiment_tags_s79 WHERE market=? AND theme <> ?"
    a: list = [market, T.NONE]
    if theme:
        q += " AND theme=?"
        a.append(theme)
    if start:
        q += " AND day >= ?"
        a.append(start)
    if end:
        q += " AND day <= ?"
        a.append(end)
    try:
        df = con.execute(q, a).df()
    except Exception:
        df = pd.DataFrame(columns=["theme", "day", "tone_class", "tagged_at"])
    if df.empty:
        return pd.DataFrame(columns=["theme", "day", "tone", "n"])
    keep = [is_live_tag(d, t) for d, t in zip(df["day"], df["tagged_at"])]
    df = df[np.array(keep, dtype=bool)]
    if df.empty:
        return pd.DataFrame(columns=["theme", "day", "tone", "n"])
    df = df.assign(v=df["tone_class"].map(TONE_VALUE), day=pd.to_datetime(df["day"]))
    g = df.groupby(["theme", "day"]).agg(tone=("v", "mean"), n=("v", "size")).reset_index()
    return g
