"""US company filings from the SEC into the graph (S85 `sec`): the collector. Public data; nothing of the investor's leaves the PC except the SEC's own request header.

For the US names the system holds, picks, skips or watches (`[think] sec_scope = "book"`; "sp500" adds the index members, a later switch):
  1. the company's filing index (`data.sec.gov/submissions/CIK##########.json`: the `[sec] user_agent` from the secrets file goes in the request header, NEVER in a log, a message, a row or
     a file of the repo);
  2. the 8-Ks accepted in the look-back whose items include 5.02 (officers and directors), 4.01 (change of auditor) or 4.02 (non-reliance on financial statements);
  3. each such filing's main document, turned into text and cut into its items; written as the raw file `<data>/sec_8k/<accession>.json` and indexed in `sec_8k_s85` (a filing is never fetched twice);
  4. the graph reads those raw files (`kg2/sec_8k.py`: classification by code, event time = the SEC's acceptance time, A58 for a filing with none) and, when the graph is loaded, the new events
     are put in the store at once (`sync_store`), so the thinking loop sees them without waiting for the nightly rebuild, which makes the same rows.

Politeness: at most 4 requests a second (the SEC's limit is 10), a back-off on 429 / 5xx / timeouts (honouring Retry-After), a 403 with a good contact is read as the SEC's throttle (waits, then
stops the run), a 403 with no contact stops at once. A failure is a visible line in the result, never an exception for the scheduler.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import pandas as pd

from pflab.data import sec_edgar
from pflab.kg2 import sec_8k as kg

WANTED = kg.ITEMS
FORM = "8-K"
MIN_INTERVAL = 0.25                    # seconds between two requests: at most 4 a second (the SEC allows 10)
SUBMISSIONS = sec_edgar.SUBMISSIONS
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
SECTION_CAP = 6000
TEXT_CAP = 400_000                     # a document longer than this is cut before it is parsed (an 8-K with a 4 MB exhibit inline)
MAX_TRIES = 4                          # fetches of one filing's document
CIK_GAP_MINUTES = 90                   # a company is asked about at most this often
CIK_FAIL_BACKOFF_HOURS = 12            # after three failed asks in a row
DEFAULT_LOOKBACK_DAYS = 30
FIRST_LOOKBACK_DAYS = 90
IST_OFFSET = timedelta(hours=5, minutes=30)
SCOPES = ("book", "sp500")


class SecError(RuntimeError):
    """A request failed after its retries (the message never carries the request header)."""


class Blocked(RuntimeError):
    """The SEC refused us (no or a refused contact, or a throttle that did not lift): the run stops; the next run tries again."""


# ------------------------------------------------------------------ the client

class Client:
    """Politeness and safety around one HTTP session. `session` is anything with `.get(url, headers=, timeout=)` returning an object with `status_code`, `text` and `headers`;
    tests pass a fake together with `sleep` and `clock`, so nothing waits and nothing reaches the SEC."""

    def __init__(self, session=None, sleep: Callable = time.sleep, clock: Callable = time.monotonic, min_interval: float = MIN_INTERVAL, retries: int = 3,
                 backoff: float = 2.0, user_agent: Optional[Callable] = None, timeout: int = 60):
        self._session = session
        self._sleep, self._clock = sleep, clock
        self.min_interval, self.retries, self.backoff, self.timeout = float(min_interval), int(retries), float(backoff), timeout
        self._ua = user_agent or sec_edgar.user_agent
        self._last: Optional[float] = None
        self.requests = 0
        self.waited = 0.0
        self.log: List[str] = []                    # what happened, never a header

    def __repr__(self) -> str:                      # a client never shows its header
        return f"<sec_8k.Client requests={self.requests}>"

    def _pace(self) -> None:
        if self._last is not None:
            gap = self.min_interval - (self._clock() - self._last)
            if gap > 0:
                self._sleep(gap)
                self.waited += gap
        self._last = self._clock()

    def _scrub(self, text: object) -> str:
        s = str(text)
        try:
            ua = self._ua()
            if ua and len(ua) > 3:
                s = s.replace(ua, "<contact>")
        except Exception:
            pass
        return s

    def get(self, url: str) -> str:
        if self._session is None:
            import requests
            self._session = requests.Session()
        last = ""
        for k in range(self.retries + 1):
            self._pace()
            self.requests += 1
            ua = self._ua()
            if not ua or ua == sec_edgar.DEFAULT_USER_AGENT:
                raise Blocked("no SEC contact in the secrets file ([sec] user_agent): the SEC refuses a request without one")
            try:
                r = self._session.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=self.timeout)
            except Exception as e:                  # a timeout or a dropped connection
                last = f"{type(e).__name__}: {self._scrub(e)[:120]}"
                self.log.append(f"request failed ({last}); try {k + 1}")
                self._sleep(self.backoff * (2 ** k))
                continue
            code = int(getattr(r, "status_code", 0) or 0)
            if code == 200:
                return r.text
            if code == 403:
                self.log.append(f"the SEC answered 403; try {k + 1}")
                if k >= 1:
                    raise Blocked("the SEC kept answering 403 (its throttle, or a contact it does not accept): stopping this run")
                self._sleep(10.0 * (k + 1))
                continue
            if code in (429, 500, 502, 503, 504):
                wait = self.backoff * (2 ** k)
                try:
                    wait = max(wait, min(60.0, float((getattr(r, "headers", None) or {}).get("Retry-After", 0))))
                except (TypeError, ValueError):
                    pass
                last = f"HTTP {code}"
                self.log.append(f"the SEC answered {code}; waiting {wait:.0f}s; try {k + 1}")
                self._sleep(wait)
                continue
            raise SecError(f"HTTP {code} for {self._scrub(url)}")
        raise SecError(f"gave up after {self.retries + 1} tries ({last}) for {self._scrub(url)}")

    def get_json(self, url: str) -> dict:
        try:
            return json.loads(self.get(url))
        except ValueError as e:
            raise SecError(f"not JSON from {self._scrub(url)}: {e}")


# ------------------------------------------------------------------ text

_BLOCK = {"p", "div", "br", "tr", "td", "th", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6", "section", "ul", "ol", "pre"}
_ITEM_RX = re.compile(r"(?im)^[ \t]*item[ \t]+(\d{1,2}\.\d{2})\b[^\n]*$")
_END_RX = re.compile(r"(?im)^[ \t]*(?:signatures?|exhibit index|forward-looking statements?)\b[^\n]*$")


def html_to_text(html: str) -> str:
    """The visible text of a filing's HTML (inline XBRL included), one block element per line. lxml (pinned) does the parsing."""
    import lxml.html
    html = re.sub(r"^\s*<\?xml[^>]*\?>", "", str(html or "")[:TEXT_CAP * 4])          # inline-XBRL filings are XHTML with an XML declaration, which lxml.html refuses in a str
    if not html.strip():
        return ""
    try:
        root = lxml.html.fromstring(html)
    except Exception:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()[:TEXT_CAP]
    for el in list(root.iter()):
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag in ("script", "style", "head") or tag.endswith("header") and tag.startswith("ix:"):
            el.drop_tree()
    for el in root.iter():
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag.lower() in _BLOCK:
            el.tail = "\n" + (el.tail or "")
    out = []
    for ln in root.text_content().splitlines():
        ln = re.sub(r"[^\S\n]+", " ", ln).strip()          # every kind of space becomes one space: filings put a thin space inside "Item 5.02"
        if ln:
            out.append(ln)
    return "\n".join(out)[:TEXT_CAP]


def sections(text: str, listed: Iterable[str], cap: int = SECTION_CAP) -> Dict[str, dict]:
    """{item: {"text", "fallback"}} for the wanted items the filing lists. An item's text runs from its heading line to the next item heading, the signature or the exhibit index. An item
    listed by the SEC whose heading cannot be found gets the document's start instead, marked `fallback` (the classification then reads more than the item)."""
    heads = [(m.start(), m.group(1)) for m in _ITEM_RX.finditer(text)]
    out: Dict[str, dict] = {}
    for item in [i for i in listed if i in WANTED]:
        best = ""
        for k, (pos, name) in enumerate(heads):
            if name != item:
                continue
            ends = [len(text)]
            if k + 1 < len(heads):
                ends.append(heads[k + 1][0])
            m_end = _END_RX.search(text, pos + 1)
            if m_end:
                ends.append(m_end.start())
            seg = text[pos:min(ends)].strip()
            if len(seg) > len(best):
                best = seg
        if best:
            out[item] = {"text": best[:cap], "fallback": False}
        elif text.strip():
            out[item] = {"text": text.strip()[:cap], "fallback": True}
    return out


# ------------------------------------------------------------------ raw files and the index

def write_raw(root, rec: dict) -> Path:
    d = kg.raw_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{rec['accession']}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return p


def _idx(con, accession: str) -> Optional[dict]:
    r = con.execute("SELECT status, tries FROM sec_8k_s85 WHERE accession=?", [accession]).fetchone()
    return {"status": r[0], "tries": r[1] or 0} if r else None


def _put_idx(con, f: dict, status: str, now: datetime, tries: int, note: str = "") -> None:
    con.execute("INSERT INTO sec_8k_s85 (accession, cik, isin, symbol, company, form, items_listed, filed, accepted_utc, status, tries, first_seen, fetched_at, wanted_items, note) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (accession) DO UPDATE SET status=excluded.status, tries=excluded.tries, fetched_at=excluded.fetched_at, note=excluded.note",
                [f["accession"], f["cik"], f["isin"], f.get("symbol"), f.get("company"), FORM, f.get("items_listed"), f.get("filed"), f.get("accepted_utc"), status, tries, now,
                 now if status == "stored" else None, ",".join(f.get("wanted") or []), note[:200]])


def _cik_row(con, cik: int) -> Optional[dict]:
    r = con.execute("SELECT last_checked, last_status, failures FROM sec_8k_cik_s85 WHERE cik=?", [cik]).fetchone()
    return {"last_checked": r[0], "last_status": r[1], "failures": r[2] or 0} if r else None


def _put_cik(con, e: dict, now: datetime, status: str, failures: int, seen: int) -> None:
    con.execute("INSERT INTO sec_8k_cik_s85 (cik, isin, symbol, last_checked, last_status, failures, filings_seen) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT (cik) DO UPDATE SET isin=excluded.isin, symbol=excluded.symbol, last_checked=excluded.last_checked, last_status=excluded.last_status, "
                "failures=excluded.failures, filings_seen=excluded.filings_seen", [e["cik"], e["isin"], e.get("symbol"), now, status[:200], failures, seen])


def _due(row: Optional[dict], now: datetime, force: bool) -> bool:
    if force or row is None or row["last_checked"] is None:
        return True
    age = now - row["last_checked"]
    if row["failures"] >= 3:
        return age >= timedelta(hours=CIK_FAIL_BACKOFF_HOURS)
    return age >= timedelta(minutes=CIK_GAP_MINUTES)


# ------------------------------------------------------------------ the filings of one company

def wanted_filings(j: dict, since_utc: datetime) -> pd.DataFrame:
    """The 8-Ks of a submissions document accepted at or after `since_utc` (naive UTC) that list at least one wanted item; columns accn, filed, accepted, doc, items, wanted."""
    df = sec_edgar.filings_from(j)
    if df.empty:
        return df.assign(wanted=[])
    df = df[df["form"] == FORM].copy()
    keep_time = df["accepted"].ge(pd.Timestamp(since_utc)) | (df["accepted"].isna() & df["filed"].ge(since_utc.date()))
    df = df[keep_time]
    df["wanted"] = [[i.strip() for i in str(x or "").split(",") if i.strip() in WANTED] for x in df["items"]]
    return df[df["wanted"].map(len) > 0].reset_index(drop=True)


def _accepted_iso(t) -> Optional[str]:
    return None if pd.isna(t) else pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%S")


def collect_one(con, root, e: dict, client: Client, now: datetime, since_utc: datetime, budget: Callable[[], bool]) -> dict:
    """One company: its index, then the documents of the new wanted 8-Ks. Raises Blocked / SecError for the caller to count."""
    res = {"seen": 0, "wanted": 0, "stored": 0, "failed": 0, "items": Counter()}
    j = client.get_json(SUBMISSIONS.format(cik=e["cik"]))
    company = j.get("name") or e.get("symbol") or ""
    df = wanted_filings(j, since_utc)
    res["seen"] = int(len(df))
    for f in df.itertuples():
        st = _idx(con, f.accn)
        if st and (st["status"] in ("stored", "no_text") or st["tries"] >= MAX_TRIES):
            continue
        res["wanted"] += 1
        if not budget():
            break
        rec_f = {"accession": f.accn, "cik": e["cik"], "isin": e["isin"], "symbol": e.get("symbol"), "company": company, "filed": str(f.filed), "accepted_utc": _accepted_iso(f.accepted),
                 "items_listed": str(f.items), "wanted": list(f.wanted)}
        tries = (st["tries"] if st else 0) + 1
        url = ARCHIVE.format(cik=int(e["cik"]), acc=str(f.accn).replace("-", ""), doc=f.doc) if f.doc else ""
        try:
            if not url:
                raise SecError("the index names no main document")
            body = client.get(url)
        except Blocked:
            _put_idx(con, rec_f, "fetch_failed", now, tries, "blocked")
            raise
        except SecError as ex:
            _put_idx(con, rec_f, "fetch_failed", now, tries, str(ex))
            res["failed"] += 1
            continue
        secs = sections(html_to_text(body), f.wanted)
        if not secs:
            _put_idx(con, rec_f, "no_text", now, tries, "no readable text in the document")
            continue
        rec = {"version": 1, **{k: rec_f[k] for k in ("accession", "cik", "isin", "symbol", "company", "filed", "accepted_utc", "items_listed")}, "form": FORM, "doc_url": url,
               "sections": {i: v["text"] for i, v in secs.items()}, "fallback_items": sorted(i for i, v in secs.items() if v["fallback"])}
        write_raw(root, rec)
        _put_idx(con, rec_f, "stored", now, tries, "")
        res["stored"] += 1
        res["items"].update(secs.keys())
    return res


# ------------------------------------------------------------------ who is asked about

def _cik_of(isin: str, symbol: str, ciks: Dict[str, int]) -> Optional[int]:
    from pflab.ledger import foreign as lf
    if lf.is_pseudo(isin or ""):
        return int(isin[2:])
    return ciks.get((symbol or "").upper())


def scope_entries(con, day: date, root, scope: str = "book", ciks: Optional[Dict[str, int]] = None, get_html: Optional[Callable] = None) -> List[dict]:
    """[{cik, isin, symbol, why}] for the US names to ask the SEC about: the sub-book's holdings, the picks, the skipped ideas and the watched names (the thinking loop's own scope, `think/watch.scope`),
    and with scope "sp500" the index members too. Funds are left out (they file no 8-K). The key is the pseudo-ISIN ZZ + CIK."""
    from pflab.ledger import foreign as lf
    from pflab.us import instruments as uins
    ciks = ciks if ciks is not None else uins.load_ciks(root)
    etf = set()
    try:
        etf = {r[0] for r in con.execute("SELECT isin FROM instruments WHERE market='US' AND asset_class='etf'").fetchall()}
    except Exception:
        pass
    out: Dict[int, dict] = {}

    def put(isin, symbol, why):
        cik = _cik_of(isin, symbol, ciks)
        if cik and cik not in out:
            out[cik] = {"cik": cik, "isin": lf.pseudo_isin(cik), "symbol": (symbol or "").upper() or None, "why": why}

    try:
        from pflab.think import watch
        for e in watch.scope(con, day, market="US", root=root):
            if e["isin"] in etf or str(e["isin"]).startswith(("STORY:", "MARKET:", "MACRO:")):
                continue
            put(e["isin"], e["symbol"], e["why"])
    except Exception:
        pass
    if scope == "sp500":
        from pflab.data import us_prices
        for sym in us_prices.sp500_symbols(get_html):
            put(None, sym.replace("-", "."), "S&P 500 member")
            put(None, sym, "S&P 500 member")
    return sorted(out.values(), key=lambda x: x["cik"])


def scope_setting() -> str:
    try:
        from pflab import think
        v = str(think.settings().get("sec_scope", "book")).strip().lower()
        return v if v in SCOPES else "book"
    except Exception:
        return "book"


# ------------------------------------------------------------------ the graph's store

def sync_store(con, root, now: datetime) -> dict:
    """Put the raw files' events that the loaded graph does not have yet into the store, with the same rows the nightly rebuild makes (same function, same as-of day), so the thinking loop sees a
    new 8-K at once. Only when the graph is on and its audit passed (otherwise nothing from the graph is readable, and this adds nothing). Never raises."""
    try:
        from pflab import markets
        from pflab.kg2 import audit, build as kb, switch
        asof = markets.get("IN").session_closed_by(now)
        if not (switch.on() and audit.last_passed(con, asof)):
            return {"graph_loaded": False}
        ev, nodes, _st = kg.events(root, asof)
        have = {r[0] for r in con.execute("SELECT event_id FROM kg2_event WHERE source LIKE ?", [kg.SOURCE_PREFIX + "%"]).fetchall()}
        new = [x for x in ev if x["event_id"] not in have]
        known = {r[0] for r in con.execute("SELECT isin FROM kg2_node").fetchall()}
        new_nodes = [n for n in nodes if n["isin"] not in known]
        from pflab.pm import store
        with store.transaction(con):
            for key, table, rows in (("node", "kg2_node", new_nodes), ("event", "kg2_event", new)):
                if rows:
                    df = pd.DataFrame(rows, columns=kb.TABLES[key])
                    con.register("_sec8k_df", df)
                    con.execute(f"INSERT INTO {table} ({', '.join(df.columns)}) SELECT {', '.join(df.columns)} FROM _sec8k_df")
                    con.unregister("_sec8k_df")
        return {"graph_loaded": True, "events_added": len(new), "nodes_added": len(new_nodes)}
    except Exception as e:
        return {"graph_loaded": None, "sync_problem": f"{type(e).__name__}: {str(e)[:160]}"}


# ------------------------------------------------------------------ the run

def collect(con, root, entries: List[dict], now: datetime, *, client: Optional[Client] = None, lookback_days: Optional[int] = None, max_requests: int = 400,
            max_seconds: float = 900.0, force: bool = False, clock: Callable = time.monotonic) -> dict:
    """Ask the SEC about `entries` (each {cik, isin, symbol}). Bounded by requests and seconds. Returns counts and plain `problems` lines; never raises for the SEC's sake."""
    client = client or Client()
    first = con.execute("SELECT count(*) FROM sec_8k_cik_s85").fetchone()[0] == 0
    days = int(lookback_days if lookback_days is not None else (FIRST_LOOKBACK_DAYS if first else DEFAULT_LOOKBACK_DAYS))
    since_utc = (now - IST_OFFSET) - timedelta(days=days)                       # `now` is IST wall time; the SEC's acceptance times are UTC
    t0 = clock()
    out = {"companies": len(entries), "asked": 0, "not_due": 0, "filings_wanted": 0, "stored": 0, "by_item": Counter(), "failed_documents": 0, "problems": [], "stopped": None}

    def budget() -> bool:
        return client.requests < max_requests and (clock() - t0) < max_seconds

    for e in entries:
        row = _cik_row(con, e["cik"])
        if not _due(row, now, force):
            out["not_due"] += 1
            continue
        if not budget():
            out["stopped"] = "the request or time budget of this run is used up; the rest next run"
            break
        try:
            r = collect_one(con, root, e, client, now, since_utc, budget)
        except Blocked as ex:
            out["problems"].append(f"{e.get('symbol') or e['cik']}: {ex}")
            out["stopped"] = "the SEC refused: the run stopped, the next run tries again"
            break
        except SecError as ex:
            fails = (row["failures"] if row else 0) + 1
            _put_cik(con, e, now, f"failed: {str(ex)[:150]}", fails, 0)
            out["problems"].append(f"{e.get('symbol') or e['cik']}: {str(ex)[:150]}")
            continue
        except Exception as ex:                                                  # a surprise in one company never stops the others
            fails = (row["failures"] if row else 0) + 1
            _put_cik(con, e, now, f"failed: {type(ex).__name__}", fails, 0)
            out["problems"].append(f"{e.get('symbol') or e['cik']}: {type(ex).__name__}: {client._scrub(ex)[:120]}")
            continue
        _put_cik(con, e, now, "ok", 0, r["seen"])
        out["asked"] += 1
        out["filings_wanted"] += r["wanted"]
        out["stored"] += r["stored"]
        out["failed_documents"] += r["failed"]
        out["by_item"].update(r["items"])
    out["by_item"] = dict(out["by_item"])
    out["requests"] = client.requests
    out["client_notes"] = client.log[-5:]
    return out


def due_window(con, now: datetime, last_success: Optional[datetime]) -> Optional[str]:
    """None when the collector should run now, else why not. The SEC takes filings on weekdays from 06:00 to 22:00 New York time: inside that window (US market open or not) it runs; outside it
    runs only when the app has been closed for a while (the app just started: catch up)."""
    gap = (now - last_success) if last_success else None
    if gap is None or gap >= timedelta(hours=6):
        return None
    try:
        from zoneinfo import ZoneInfo
        from datetime import timezone
        ny = (now.replace(tzinfo=ZoneInfo("Asia/Kolkata"))).astimezone(ZoneInfo("America/New_York"))
    except Exception:
        return None
    if ny.weekday() >= 5 or not (6 <= ny.hour < 22):
        return "the SEC takes no filings now (weekend or night in New York); the last run is recent"
    return None


def run_job(con, root, now: datetime, *, client: Optional[Client] = None, scope: Optional[str] = None, get_html: Optional[Callable] = None, entries: Optional[List[dict]] = None,
            last_success: Optional[datetime] = None, force: bool = False) -> dict:
    """The job's body: the names in scope, the SEC, the store. Returns a small dict for the job record; a refusal or a failure is a line in `problems`, never an exception."""
    why = due_window(con, now, last_success)
    if why and not force:
        return {"skipped": why}
    from pflab import markets
    scope = scope or scope_setting()
    day = markets.get("US").last_session_on_or_before(now.date())
    try:
        ents = entries if entries is not None else scope_entries(con, day, root, scope, get_html=get_html)
    except Exception as e:
        return {"problems": [f"the list of US names could not be made: {type(e).__name__}: {str(e)[:120]}"]}
    if not ents:
        return {"skipped": "no US name to ask about (nothing held, picked, skipped or watched in the US, or no CIK known yet)", "scope": scope}
    r = collect(con, root, ents, now, client=client, force=force)
    r["scope"] = scope
    r["graph"] = sync_store(con, root, now) if r["stored"] else {"graph_loaded": None}
    return r
