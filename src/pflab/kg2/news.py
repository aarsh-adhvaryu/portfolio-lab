"""The one-year news collection (S81 B7, A52): article level, with article text, capped, polite, resumable.

ROUTE (measured 2026-11-09, recorded in docs/s81_kg_notes.md): GDELT's DOC 2.0 API reaches back only about three months and is rate-limited per
query, and the 15-minute GKG 2.1 files are 3-4 MB each (96 a day, two feeds: about 105 GB for one year). The GDELT 1.0 GKG DAILY files
(`https://data.gdeltproject.org/gkg/YYYYMMDD.gkg.csv.zip`, 20-34 MB, about 50,000 rows a day, one row per article with its organisations, themes,
tone and URL) cover the whole year in about 9 GB of downloads, none of which is kept: each day is filtered to the scope's organisation names and
only those rows are stored (`<data>/news_s81/gkg1/YYYY-MM-DD.parquet`, the raw rows the graph is rebuilt from). Version 1 has a day, not a time:
an article is dated by its day and is usable from the NEXT day (point in time, conservative).

Linking rule at collection (the ISIN tag): an article row is kept for an ISIN only when one of the row's organisation tokens EQUALS one of the
company's aliases (whole token, no substring). The graph later also requires the article text, when it exists, to carry the name.

Article text: for the names marked `text` in the scope only, newest first: robots.txt is read per domain and obeyed, at most one request per domain
every `DOMAIN_DELAY` seconds, a small pool of threads across domains, a page that refuses (robots, 4xx, 5xx, timeout, not HTML, no text) is skipped
and counted, trafilatura 2.0.0 extracts the text, which stays on this PC (`news_s81/text/xx/<hash>.json`). Total size under `CAP_BYTES`.

Resumable: manifest `news_s81/manifest.sqlite` (days, urls). Files are written to a temp name and renamed, so a stop never leaves a half-written file.
Stop: create `news_s81/STOP`, or the run ends at `--until HH:MM` (local time). Logs counts only.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import sqlite3
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional
from urllib import robotparser
from urllib.parse import urlparse

import pandas as pd
import requests

from pflab.kg2 import scope as sc

UA = "pflab-research/1.0 (personal research, polite crawler; respects robots.txt)"
GKG1 = "https://data.gdeltproject.org/gkg/{day}.gkg.csv.zip"
KEEP = ["date", "url", "source", "isin", "org", "tone", "themes", "india", "numarts"]
CAP_BYTES = 20 * 10 ** 9
DOMAIN_DELAY = 3.0
TEXT_THREADS = 16
MAX_HTML = 3 * 10 ** 6
MAX_TEXT = 30000
MIN_TEXT = 200
DAY_RETRIES = 3


def news_dir(root: Path) -> Path:
    return Path(root) / "news_s81"


def rows_dir(root: Path) -> Path:
    return news_dir(root) / "gkg1"


def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]


def text_path(root: Path, h: str) -> Path:
    return news_dir(root) / "text" / h[:2] / f"{h}.json"


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    os.close(fd)
    try:
        df.to_parquet(tmp, index=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------ parsing one GKG 1.0 day

def parse_gkg1(zip_path: Path, day: date, alias_to_isin: Dict[str, str]) -> pd.DataFrame:
    """The day's rows whose organisation tokens equal an alias of the scope, one row per (url, isin). Deterministic order."""
    with zipfile.ZipFile(zip_path) as z:
        df = pd.read_csv(z.open(z.namelist()[0]), sep="\t", dtype=str, quoting=3, on_bad_lines="skip", encoding="latin-1",
                         usecols=["NUMARTS", "THEMES", "LOCATIONS", "ORGANIZATIONS", "TONE", "SOURCES", "SOURCEURLS"]).fillna("")
    return rows_from_frame(df, day, alias_to_isin)


def rows_from_frame(df: pd.DataFrame, day: date, alias_to_isin: Dict[str, str]) -> pd.DataFrame:
    out: List[dict] = []
    df = df[df["ORGANIZATIONS"] != ""]
    for r in df.itertuples(index=False):
        toks = [t.strip().lower() for t in r.ORGANIZATIONS.split(";") if t.strip()]
        hits = [(t, alias_to_isin[t]) for t in dict.fromkeys(toks) if t in alias_to_isin]
        if not hits:
            continue
        urls = [u.strip() for u in r.SOURCEURLS.split("<UDIV>") if u.strip()]
        srcs = [s.strip() for s in r.SOURCES.split(";") if s.strip()]
        tone = pd.to_numeric(r.TONE.split(",")[0], errors="coerce")
        themes = ";".join(list(dict.fromkeys(t for t in r.THEMES.split(";") if t))[:15])
        india = "#IN#" in r.LOCATIONS
        try:
            numarts = int(r.NUMARTS)
        except ValueError:
            numarts = 1
        for i, u in enumerate(urls):
            for org, isin in hits:
                out.append({"date": day.isoformat(), "url": u, "source": srcs[i] if i < len(srcs) else urlparse(u).netloc,
                            "isin": isin, "org": org, "tone": float(tone) if pd.notna(tone) else float("nan"),
                            "themes": themes, "india": india, "numarts": numarts})
    res = pd.DataFrame(out, columns=KEEP)
    if res.empty:
        return res
    return res.drop_duplicates(["url", "isin"]).sort_values(["isin", "url", "org"], kind="mergesort").reset_index(drop=True)


def load_rows(root: Path, since: Optional[date] = None) -> pd.DataFrame:
    files = sorted(p for p in rows_dir(root).glob("*.parquet") if since is None or p.stem >= since.isoformat())
    if not files:
        return pd.DataFrame(columns=KEEP)
    return pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)


# ------------------------------------------------------------------ manifest

class Manifest:
    def __init__(self, root: Path):
        self.path = news_dir(root) / "manifest.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=60)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS days(day TEXT PRIMARY KEY, status TEXT, n_rows INTEGER, n_text_urls INTEGER, tries INTEGER DEFAULT 0, at TEXT);
            CREATE TABLE IF NOT EXISTS urls(h TEXT PRIMARY KEY, url TEXT, domain TEXT, day TEXT, isin TEXT, status TEXT, bytes INTEGER DEFAULT 0, at TEXT);
            CREATE INDEX IF NOT EXISTS urls_status ON urls(status, day);
        """)
        self.db.commit()

    def q(self, sql: str, args: tuple = ()):
        with self.lock:
            cur = self.db.execute(sql, args)
            rows = cur.fetchall()
            self.db.commit()
            return rows

    def many(self, sql: str, seq: Iterable[tuple]) -> None:
        with self.lock:
            self.db.executemany(sql, list(seq))
            self.db.commit()

    def day_done(self, day: date) -> bool:
        r = self.q("SELECT status FROM days WHERE day=?", (day.isoformat(),))
        return bool(r) and r[0][0] in ("done", "missing")

    def counts(self) -> dict:
        d = dict(self.q("SELECT status, COUNT(*) FROM days GROUP BY status"))
        u = dict(self.q("SELECT status, COUNT(*) FROM urls GROUP BY status"))
        b = self.q("SELECT COALESCE(SUM(bytes),0) FROM urls WHERE status='ok'")[0][0]
        return {"days": d, "urls": u, "text_bytes": int(b)}


def dir_bytes(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


# ------------------------------------------------------------------ the day collector

def download(session: requests.Session, day: date, tmp_dir: Path) -> Optional[Path]:
    """The day's zip to a temp file (streamed); None when GDELT has no such file (404)."""
    url = GKG1.format(day=day.strftime("%Y%m%d"))
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dest = tmp_dir / f"{day.isoformat()}.zip.part"
    r = session.get(url, timeout=(20, 120), stream=True)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    return dest


def collect_day(root: Path, man: Manifest, day: date, session: requests.Session, scope: dict,
                dl: Callable = download) -> dict:
    """Download, filter and store one day; queue its text URLs. A failure leaves the day pending (retried next run)."""
    tmp = news_dir(root) / "_tmp"
    out = rows_dir(root) / f"{day.isoformat()}.parquet"
    z = None
    try:
        z = dl(session, day, tmp)
        if z is None:
            man.q("INSERT OR REPLACE INTO days(day,status,n_rows,n_text_urls,at) VALUES(?,?,?,?,?)",
                  (day.isoformat(), "missing", 0, 0, datetime.now().isoformat(timespec="seconds")))
            return {"day": day.isoformat(), "status": "missing"}
        df = parse_gkg1(z, day, sc.alias_index(scope))
        _atomic_parquet(df, out)
        tx = sc.text_isins(scope)
        want = df[df["isin"].isin(tx)].drop_duplicates("url") if len(df) else df
        man.many("INSERT OR IGNORE INTO urls(h,url,domain,day,isin,status,at) VALUES(?,?,?,?,?,?,?)",
                 [(url_hash(r.url), r.url, urlparse(r.url).netloc.lower(), day.isoformat(), r.isin, "pending", None)
                  for r in want.itertuples()])
        man.q("INSERT OR REPLACE INTO days(day,status,n_rows,n_text_urls,at) VALUES(?,?,?,?,?)",
              (day.isoformat(), "done", int(len(df)), int(len(want)), datetime.now().isoformat(timespec="seconds")))
        return {"day": day.isoformat(), "status": "done", "rows": int(len(df)), "text_urls": int(len(want))}
    except Exception as e:                                     # a failed day stays pending; counted, not hidden
        tries = (man.q("SELECT tries FROM days WHERE day=?", (day.isoformat(),)) or [(0,)])[0][0] + 1
        man.q("INSERT OR REPLACE INTO days(day,status,n_rows,n_text_urls,tries,at) VALUES(?,?,?,?,?,?)",
              (day.isoformat(), "failed", 0, 0, tries, datetime.now().isoformat(timespec="seconds")))
        return {"day": day.isoformat(), "status": "failed", "error": type(e).__name__}
    finally:
        if z is not None:
            try:
                Path(z).unlink()
            except OSError:
                pass


# ------------------------------------------------------------------ article text

class Politeness:
    """robots.txt per domain (cached) and one request per domain every `delay` seconds."""

    def __init__(self, session: requests.Session, delay: float = DOMAIN_DELAY):
        self.s, self.delay = session, delay
        self.robots: Dict[str, Optional[robotparser.RobotFileParser]] = {}
        self.next_ok: Dict[str, float] = {}
        self.lock = threading.Lock()

    def allowed(self, url: str) -> Optional[bool]:
        """True/False by robots.txt; None when robots.txt could not be read (try again later)."""
        p = urlparse(url)
        dom = p.netloc.lower()
        with self.lock:
            known = dom in self.robots
        if not known:
            rp: Optional[robotparser.RobotFileParser] = robotparser.RobotFileParser()
            try:
                r = self.s.get(f"{p.scheme}://{dom}/robots.txt", timeout=10, headers={"User-Agent": UA})
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                elif 400 <= r.status_code < 500:
                    rp.parse([])                                # no robots.txt: everything allowed
                else:
                    rp = None
            except requests.RequestException:
                rp = None
            with self.lock:
                self.robots[dom] = rp
        with self.lock:
            rp = self.robots.get(dom)
        if rp is None:
            with self.lock:
                self.robots.pop(dom, None)
            return None
        return rp.can_fetch(UA, url)

    def ready(self, dom: str) -> bool:
        with self.lock:
            return time.time() >= self.next_ok.get(dom, 0.0)

    def touch(self, dom: str) -> None:
        with self.lock:
            self.next_ok[dom] = time.time() + self.delay


def extract_text(html: str, url: str) -> Optional[dict]:
    import trafilatura
    raw = trafilatura.extract(html, url=url, output_format="json", with_metadata=True, include_comments=False,
                              favor_precision=True)
    if not raw:
        return None
    d = json.loads(raw)
    text = (d.get("text") or d.get("raw_text") or "").strip()
    if len(text) < MIN_TEXT:
        return None
    return {"title": d.get("title") or "", "date": d.get("date") or "", "text": text[:MAX_TEXT]}


def fetch_one(root: Path, session: requests.Session, pol: Politeness, h: str, url: str) -> tuple:
    """-> (status, bytes). status: ok, robots, retry (robots unreadable), http, notext, notHTML, error."""
    allowed = pol.allowed(url)
    if allowed is None:
        return "retry", 0
    if not allowed:
        return "robots", 0
    pol.touch(urlparse(url).netloc.lower())
    try:
        r = session.get(url, timeout=(10, 25), headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}, stream=True)
        if r.status_code != 200:
            return "http", 0
        if "html" not in r.headers.get("Content-Type", "html").lower():
            return "notHTML", 0
        body = r.raw.read(MAX_HTML, decode_content=True)
        html = body.decode(r.encoding or "utf-8", errors="replace")
    except requests.RequestException:
        return "error", 0
    got = extract_text(html, url)
    if not got:
        return "notext", 0
    blob = json.dumps({"url": url, "fetched": datetime.now().isoformat(timespec="seconds"), **got}, ensure_ascii=False).encode("utf-8")
    _atomic_bytes(text_path(root, h), blob)
    return "ok", len(blob)


_cap_cache: dict = {"t": 0.0, "v": False}


def over_cap(root: Path, man: "Manifest", cap_bytes: int) -> bool:
    """Total size of what the collection holds (rows + text), checked at most once a minute."""
    if time.time() - _cap_cache["t"] > 60:
        used = man.q("SELECT COALESCE(SUM(bytes),0) FROM urls WHERE status='ok'")[0][0] + dir_bytes(rows_dir(root))
        _cap_cache.update(t=time.time(), v=used > cap_bytes)
    return bool(_cap_cache["v"])


def requeue_text(root: Path, man: "Manifest", scope: dict) -> int:
    """Queue the text of every collected row whose ISIN is (now) in the text scope: names added later (held, found) get their back-years too."""
    tx = sc.text_isins(scope)
    n = 0
    for p in sorted(rows_dir(root).glob("*.parquet")):
        df = pd.read_parquet(p, columns=["date", "url", "isin"])
        df = df[df["isin"].isin(tx)].drop_duplicates("url")
        if df.empty:
            continue
        before = man.q("SELECT COUNT(*) FROM urls WHERE day=?", (p.stem,))[0][0]
        man.many("INSERT OR IGNORE INTO urls(h,url,domain,day,isin,status,at) VALUES(?,?,?,?,?,?,?)",
                 [(url_hash(r.url), r.url, urlparse(r.url).netloc.lower(), p.stem, r.isin, "pending", None) for r in df.itertuples()])
        n += man.q("SELECT COUNT(*) FROM urls WHERE day=?", (p.stem,))[0][0] - before
    return n


def text_worker(root: Path, man: Manifest, session: requests.Session, pol: Politeness, stop: Callable[[], bool],
                claimed: set, claim_lock: threading.Lock, cap_bytes: int, fetch: Callable = fetch_one) -> int:
    n = 0
    while not stop():
        if over_cap(root, man, cap_bytes):
            return n
        batch = man.q("SELECT h,url,domain FROM urls WHERE status IN ('pending','retry') ORDER BY day DESC, h LIMIT 2000")
        pick = None
        with claim_lock:
            for h, url, dom in batch:
                if h not in claimed and pol.ready(dom):
                    claimed.add(h)
                    pick = (h, url, dom)
                    break
        if pick is None:
            time.sleep(0.5 if batch else 3.0)
            if not batch and stop():
                return n
            continue
        h, url, dom = pick
        status, nbytes = fetch(root, session, pol, h, url)
        if status == "retry":
            pol.touch(dom)
            pol.next_ok[dom] = time.time() + 600
        man.q("UPDATE urls SET status=?, bytes=?, at=? WHERE h=?",
              (status, nbytes, datetime.now().isoformat(timespec="seconds"), h))
        with claim_lock:
            claimed.discard(h)
        n += 1
    return n


# ------------------------------------------------------------------ the run

def run(root: Path, days_back: int = 365, until: Optional[datetime] = None, today: Optional[date] = None,
        log: Optional[Callable[[str], None]] = None, dl: Callable = download, fetch: Callable = fetch_one,
        text: bool = True, day_workers: int = 2, text_threads: int = TEXT_THREADS, cap_bytes: int = CAP_BYTES) -> dict:
    """Collect the last `days_back` days (newest first) and their article text until done, STOP, or `until`."""
    root = Path(root)
    nd = news_dir(root)
    nd.mkdir(parents=True, exist_ok=True)
    stopfile = nd / "STOP"
    t0 = time.time()
    logf = nd / "collect.log"

    def say(msg: str) -> None:
        line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
        with open(logf, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if log:
            log(line)

    def stop() -> bool:
        return stopfile.exists() or bool(until and datetime.now() >= until)

    man = Manifest(root)
    s = requests.Session()
    s.headers["User-Agent"] = UA
    today = today or date.today()
    days = [today - timedelta(days=i) for i in range(1, days_back + 1)]            # yesterday and back; newest first
    scope = sc.load(root)
    say(f"start: {len(scope['names'])} names, {len(sc.text_isins(scope))} with text, {len(days)} days, until={until}")
    pol = Politeness(s)
    if text:
        say(f"requeued {requeue_text(root, man, scope)} text urls for names new to the text scope")
    claimed: set = set()
    cl = threading.Lock()
    threads: List[threading.Thread] = []
    fin = threading.Event()                                    # set when the days and their pages are done: the text workers then end
    results = {"done": 0, "missing": 0, "failed": 0, "rows": 0}
    if text:
        for _ in range(text_threads):
            t = threading.Thread(target=text_worker, args=(root, man, s, pol, lambda: stop() or fin.is_set(), claimed, cl, cap_bytes, fetch), daemon=True)
            t.start()
            threads.append(t)

    def one(d: date) -> Optional[dict]:
        if stop() or man.day_done(d):
            return None
        return collect_day(root, man, d, requests.Session(), sc.load(root), dl)

    last = time.time()
    with ThreadPoolExecutor(max_workers=day_workers) as ex:
        it = iter(days)
        pending = set()
        import concurrent.futures as cf
        while True:
            while len(pending) < day_workers and not stop():
                d = next(it, None)
                if d is None:
                    break
                pending.add(ex.submit(one, d))
            if not pending:
                break
            done, pending = cf.wait(pending, timeout=30, return_when=cf.FIRST_COMPLETED)
            for f in done:
                r = f.result()
                if r:
                    results[r["status"]] = results.get(r["status"], 0) + 1
                    results["rows"] += r.get("rows", 0)
                    if r["status"] == "failed":
                        say(f"day {r['day']} failed ({r.get('error')})")
            if time.time() - last > 300:
                say(f"progress {json.dumps(man.counts())}")
                last = time.time()
    say(f"days finished: {json.dumps(results)}")
    if text:                                                    # keep fetching text after the days are done, until nothing is pending
        while not stop():
            c = man.counts()["urls"]
            if not (c.get("pending", 0) or c.get("retry", 0)) or not any(t.is_alive() for t in threads):
                break
            if time.time() - last > 300:
                say(f"progress {json.dumps(man.counts())}")
                last = time.time()
            time.sleep(5)
    fin.set()
    for t in threads:                                           # let each worker finish the page it holds (files are written atomically anyway)
        t.join(timeout=60)
    final = man.counts()
    say(f"stop: {'STOP file' if stopfile.exists() else 'until/finished'}; {json.dumps(final)}; "
        f"gkg1 bytes={dir_bytes(rows_dir(root))}; {int(time.time() - t0)}s")
    return {"results": results, "manifest": final}
