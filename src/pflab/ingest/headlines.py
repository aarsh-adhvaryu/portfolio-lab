"""Fast headlines for what the book is exposed to (S86, the alarm lane): the collector. Public data about public companies; nothing about the investor leaves the PC except a company's name
in a search (his holdings, amounts and weights never go into a request).

Sources (measured first, `docs/s86_alarm_notes.md`; at least two independent free ones are ON, because one quiet feed is how the system goes blind):
    google_news   Google News RSS search per company name ("<name>" when:6h): minute timestamps, the outlet, any country
    yahoo         Yahoo Finance's per-ticker RSS (the host the US prices already use): US tickers and Indian ones (SYMBOL.NS)
    gdelt_doc     GDELT DOC 2.0 article search per name: 15-minute freshness, no key, but ONE request every 5 seconds is its rule: held names only, a few a run, a 429 stops it for the run
The exchanges' own feeds (BSE every 15 minutes, the SEC) are the `filings` and `sec_8k` jobs; the lane reads them through the graph and `core/session._filing_events`.

One name per request, paced per host, a back-off on 429 / 5xx / timeouts (never a long sleep inside a bounded run: the source is marked and skipped until it has waited), a refusal is a line
in `problems`, never an exception for the scheduler. Items are deduplicated by (ISIN, near-identical title); each keeps its source, outlet, publication time and FIRST-SEEN time (the time it counts
from: point in time, `ts_rule` seen_time). Raw lines: `<data>/headlines_s86/<first-seen day>.jsonl`; index: `headlines_s86`.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus

from pflab.kg2 import headlines as kg
from pflab.kg2 import scope as sc

SOURCES = ("google_news", "yahoo", "gdelt_doc")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
GNEWS = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:{lang}"
YAHOO = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region={region}&lang=en-{region}"
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=ArtList&format=json&maxrecords=30&timespan={span}&sort=DateDesc"
MIN_INTERVAL = {"google_news": 1.0, "yahoo": 0.7, "gdelt_doc": 5.5}       # seconds between two requests to one host (GDELT asks for one every five)
IST_OFFSET = timedelta(hours=5, minutes=30)
OTHER_GAP_MINUTES = 55                 # names that are not held (watched, picked, named) are asked about this often; held names every run
FAIL_BACKOFF_MIN = (15, 30, 60, 120)   # after the 1st, 2nd, ... failure in a row
GDELT_MAX_PER_RUN = 6
MAX_ITEMS_PER_NAME = 40


class Blocked(RuntimeError):
    """A source refused us (429 or a block): the source stops for this run."""


# ------------------------------------------------------------------ the client

class Client:
    """Politeness around one HTTP session. `session` is anything with `.get(url, headers=, timeout=)` returning an object with `status_code`, `text` and `headers`; tests pass a fake plus `sleep` and
    `clock`, so nothing waits and nothing reaches the net."""

    def __init__(self, session=None, sleep: Callable = time.sleep, clock: Callable = time.monotonic, timeout: int = 20, intervals: Optional[dict] = None):
        self._session, self._sleep, self._clock, self.timeout = session, sleep, clock, timeout
        self.intervals = dict(MIN_INTERVAL, **(intervals or {}))
        self._last: Dict[str, float] = {}
        self.requests: Dict[str, int] = {}
        self.log: List[str] = []

    def __repr__(self) -> str:
        return f"<headlines.Client requests={self.requests}>"

    def get(self, source: str, url: str) -> str:
        if self._session is None:
            import requests
            self._session = requests.Session()
        gap = self.intervals.get(source, 1.0) - (self._clock() - self._last.get(source, -1e9))
        if gap > 0:
            self._sleep(min(gap, 8.0))
        self._last[source] = self._clock()
        self.requests[source] = self.requests.get(source, 0) + 1
        try:
            r = self._session.get(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}, timeout=self.timeout)
        except Exception as e:
            raise RuntimeError(f"{type(e).__name__}: {str(e)[:100]}")
        code = int(getattr(r, "status_code", 0) or 0)
        if code == 200:
            return r.text
        if code in (403, 429):
            raise Blocked(f"{source} answered {code} (a limit): waiting before the next ask")
        raise RuntimeError(f"HTTP {code} from {source}")


# ------------------------------------------------------------------ parsing

def _ist(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt + IST_OFFSET


def parse_rss(text: str, source: str) -> List[dict]:
    """[{title, url, outlet, published (naive IST)}] from an RSS document. lxml with entities and the network switched off."""
    import lxml.etree as ET
    out: List[dict] = []
    try:
        root = ET.fromstring((text or "").encode("utf-8"), ET.XMLParser(resolve_entities=False, no_network=True, recover=True, huge_tree=False))
    except Exception:
        return out
    if root is None:
        return out
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        pub = None
        try:
            pub = _ist(parsedate_to_datetime((it.findtext("pubDate") or "").strip()))
        except Exception:
            pass
        outlet = (it.findtext("source") or "").strip()
        if not outlet and source == "google_news" and " - " in title:
            outlet = title.rsplit(" - ", 1)[1].strip()
        out.append({"title": title, "url": (it.findtext("link") or "").strip(), "outlet": outlet or ("Yahoo Finance" if source == "yahoo" else ""), "published": pub})
    return out


def parse_gdelt(text: str) -> List[dict]:
    try:
        arts = json.loads(text).get("articles") or []
    except Exception:
        return []
    out = []
    for a in arts:
        t = (a.get("title") or "").strip()
        if not t:
            continue
        pub = None
        try:
            pub = _ist(datetime.strptime(str(a.get("seendate")), "%Y%m%dT%H%M%SZ"))
        except Exception:
            pass
        out.append({"title": t, "url": a.get("url") or "", "outlet": a.get("domain") or "", "published": pub})
    return out


# ------------------------------------------------------------------ who is asked about

def _short(name: str) -> str:
    return sc.norm_name(name)


def _aliases(name: str, symbol: str, market: str) -> Tuple[List[str], List[str]]:
    """(alias strings to find in a normalised title, ticker words to find in the raw title)."""
    al = []
    n = _short(name)
    if len(n) >= 4:
        al.append(n)
        first = n.split()[0]
        if len(first) >= 5 and first not in al:                                    # "nvidia corp" -> "nvidia": the distinctive first word
            al.append(first)
    tick = [symbol.upper()] if symbol and len(symbol) >= 3 and market == "US" else []
    return al, tick


def scope_entries(con, day, root, cap: int = 60) -> List[dict]:
    """The names the lane watches: every name `think/watch.scope` returns (the book's holdings in India and the US sub-book, the picks, skipped ideas, screened names, names he suggested), both
    markets. Each: {isin, symbol, market, name, held, red_ok, exposure_pct, why, aliases, tickers}. Names the book does not hold or pick are asked about hourly and can only raise an AMBER."""
    from pflab.think import watch
    names: Dict[str, str] = {}
    try:
        for n in sc.load(root).get("names", []):
            if n.get("name"):
                names[n["isin"]] = n["name"]
    except Exception:
        pass
    out: List[dict] = []
    for e in watch.scope(con, day, root=root):
        if str(e["isin"]).startswith(("STORY:", "MARKET:", "MACRO:")):
            continue
        name = names.get(e["isin"]) or _db_name(con, e["isin"]) or ""
        al, tick = _aliases(name, e["symbol"], e["market"])
        if not al and not tick:
            sym_alias = _short(e["symbol"] or "")
            al = [sym_alias] if len(sym_alias) >= 4 else []
        why = str(e.get("why") or "")
        red_ok = bool(e["held"]) or "pick" in why or "you" in why or "reserve" in why
        out.append({"isin": e["isin"], "symbol": e["symbol"], "market": e["market"], "name": name or e["symbol"], "held": bool(e["held"]), "red_ok": red_ok,
                    "exposure_pct": float(e.get("exposure_pct") or 0.0), "exposure_inr": float(e.get("exposure_inr") or 0.0), "why": why, "aliases": al, "tickers": tick})
    out.sort(key=lambda x: (not x["held"], not x["red_ok"], -x["exposure_inr"], x["symbol"] or ""))
    return out[:cap]


def _db_name(con, isin: str) -> Optional[str]:
    try:
        r = con.execute("SELECT name FROM instruments WHERE isin=?", [isin]).fetchone()
        return r[0] if r and r[0] else None
    except Exception:
        return None


def linked_by(title: str, e: dict) -> Optional[str]:
    """'title' when the company's name (or a US ticker) is in the headline, else None."""
    n = kg.norm_title(title)
    n = " " + n + " "
    for a in e["aliases"]:
        if " " + a + " " in n or a in n and len(a) >= 6:
            return "title"
    for t in e["tickers"]:
        if re.search(rf"(?<![A-Za-z]){re.escape(t)}(?![A-Za-z])", title):
            return "title"
    return None


def queries(e: dict, source: str, when: str) -> Optional[str]:
    name = e["name"] if e["aliases"] or e["tickers"] else e["symbol"]
    short = _short(name) or (e["symbol"] or "").lower()
    if source == "google_news":
        us = e["market"] == "US"
        q = quote_plus(f"\"{short}\" when:{when}")
        return GNEWS.format(q=q, hl="en-US" if us else "en-IN", gl="US" if us else "IN", lang="en" if us else "en")
    if source == "yahoo":
        sym = (e["symbol"] or "").upper()
        if not sym:
            return None
        return YAHOO.format(sym=quote_plus(sym if e["market"] == "US" else sym + ".NS"), region="US" if e["market"] == "US" else "IN")
    if source == "gdelt_doc":
        return GDELT.format(q=quote_plus(f"\"{short}\" sourcelang:english"), span="1d" if when in ("1h", "2h", "6h", "12h", "1d") else "7d")
    return None


# ------------------------------------------------------------------ the store

def _src_row(con, source: str, isin: str) -> Optional[dict]:
    r = con.execute("SELECT last_checked, last_status, failures FROM headline_src_s86 WHERE source=? AND isin=?", [source, isin]).fetchone()
    return {"last_checked": r[0], "last_status": r[1], "failures": r[2] or 0} if r else None


def _put_src(con, source: str, isin: str, now: datetime, status: str, failures: int, seen: int) -> None:
    con.execute("INSERT INTO headline_src_s86 VALUES (?,?,?,?,?,?) ON CONFLICT (source, isin) DO UPDATE SET last_checked=excluded.last_checked, last_status=excluded.last_status, "
                "failures=excluded.failures, items_seen=excluded.items_seen", [source, isin, now, status[:200], failures, seen])


def _due(row: Optional[dict], e: dict, now: datetime, force: bool) -> bool:
    if force or row is None or row["last_checked"] is None:
        return True
    age = now - row["last_checked"]
    if row["failures"]:
        return age >= timedelta(minutes=FAIL_BACKOFF_MIN[min(row["failures"], len(FAIL_BACKOFF_MIN)) - 1])
    return True if e["held"] or e["red_ok"] and e["exposure_inr"] > 0 else age >= timedelta(minutes=OTHER_GAP_MINUTES)


def _write_raw(root, lines: List[dict]) -> None:
    by: Dict[str, List[dict]] = {}
    for r in lines:
        by.setdefault(str(r["first_seen"])[:10], []).append(r)
    d = kg.raw_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    for day, rows in sorted(by.items()):
        with open(d / f"{day}.jsonl", "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def keep(con, root, e: dict, source: str, items: List[dict], now: datetime) -> List[dict]:
    """The new items of one ask: linked to the name, not seen before (by ISIN and near-identical title), stored. Returns the stored ones (dicts as in the raw lines)."""
    new: List[dict] = []
    for it in items[:MAX_ITEMS_PER_NAME]:
        link = linked_by(it["title"], e)
        if link is None and source != "yahoo":
            continue                                                    # a search hit that does not name the company is not about it
        iid = kg.item_id(e["isin"], it["title"])
        pub = it["published"]
        if pub is not None and pub > now:
            pub = now                                                   # a clock skew never puts a headline in the future
        row = {"id": iid, "isin": e["isin"], "symbol": e["symbol"], "market": e["market"], "title": it["title"][:400], "url": it["url"][:500], "outlet": it["outlet"][:80], "source": source,
               "published": pub.isoformat(sep=" ") if pub else None, "first_seen": now.isoformat(sep=" "), "linked": link or "feed"}
        if con.execute("INSERT INTO headlines_s86 (item_id, isin, symbol, market, title, url, outlet, source, published, first_seen, in_graph) VALUES (?,?,?,?,?,?,?,?,?,?,false) "
                       "ON CONFLICT (item_id) DO NOTHING RETURNING item_id", [iid, e["isin"], e["symbol"], e["market"], row["title"], row["url"], row["outlet"], source, pub, now]).fetchone():
            new.append(row)
    if new:
        _write_raw(root, new)
    return new


# ------------------------------------------------------------------ the run

def collect(con, root, entries: List[dict], now: datetime, *, client: Optional[Client] = None, sources: Iterable[str] = SOURCES, when: str = "6h", max_seconds: float = 110.0,
            max_requests: int = 300, force: bool = False, clock: Callable = time.monotonic) -> dict:
    """Ask each source about each name (held names first), bounded by seconds and requests. -> {items: [new items], by_source: {src: {asked, ok, failed, items, refused}}, problems, stopped}."""
    client = client or Client()
    t0 = clock()
    out = {"items": [], "by_source": {s: {"asked": 0, "ok": 0, "failed": 0, "items": 0, "refused": 0} for s in sources}, "problems": [], "stopped": None}
    held_off: Dict[str, str] = {}                                         # a source that refused: skipped for the rest of this run
    gdelt_n = 0
    for e in entries:
        for src in sources:
            if src in held_off:
                continue
            if clock() - t0 > max_seconds or sum(client.requests.values()) >= max_requests:
                out["stopped"] = "the run's time or request budget is used up; the rest next run"
                return _tally(out, client)
            if src == "gdelt_doc" and (not e["held"] or gdelt_n >= GDELT_MAX_PER_RUN):
                continue
            row = _src_row(con, src, e["isin"])
            if not _due(row, e, now, force):
                continue
            url = queries(e, src, "7d" if (row is None and src == "google_news" and when == "6h") else when)      # a name asked about for the first time: its week, so the norm has a baseline
            if not url:
                continue
            gdelt_n += src == "gdelt_doc"
            b = out["by_source"][src]
            b["asked"] += 1
            try:
                text = client.get(src, url)
                items = parse_gdelt(text) if src == "gdelt_doc" else parse_rss(text, src)
                got = keep(con, root, e, src, items, now)
            except Blocked as ex:
                b["refused"] += 1
                held_off[src] = str(ex)
                out["problems"].append(f"{src}: {ex}")
                _put_src(con, src, e["isin"], now, f"refused: {str(ex)[:120]}", (row["failures"] if row else 0) + 1, 0)
                continue
            except Exception as ex:
                b["failed"] += 1
                _put_src(con, src, e["isin"], now, f"failed: {str(ex)[:120]}", (row["failures"] if row else 0) + 1, 0)
                if b["failed"] <= 2:
                    out["problems"].append(f"{src} for {e['symbol']}: {str(ex)[:120]}")
                continue
            b["ok"] += 1
            b["items"] += len(items)
            _put_src(con, src, e["isin"], now, "ok", 0, len(items))
            out["items"] += got
    return _tally(out, client)


def _tally(out: dict, client: Client) -> dict:
    out["requests"] = dict(client.requests)
    return out
