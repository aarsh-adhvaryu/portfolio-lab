"""S79b item K: the minute-bar history from Kite, as far back as the historical API returns (read only; this module only calls `historical_data` and `instruments`
through the wrapper in `ingest/kite.py`; no order method exists).

Storage: bulk history is parquet, one file per name, under `PFLAB_DATA_DIR/bars_1m/<market>/<NAME>.parquet` (columns ts, open, high, low, close, volume; ts is the
exchange's wall clock, no timezone; zstd). An index is `INDEX_<NAME>.parquet` and is keyed `INDEX:<NAME>` everywhere else. Next to each file a small `<NAME>.state.json` says
which 60-day windows were fetched (and up to which day) and which days came back short: a covered window is never fetched again, and a short day is STATED, never filled.
The store table `bars_1m` keeps only the last 60 sessions (`load_recent`); `read` serves any span from the table plus the parquet for later consumers.

Fetching: windows of 60 days on a fixed grid from FLOOR (Kite's minute limit), newest first, so a stop leaves a contiguous recent block; one shared rate limiter (about 3
requests a second, Kite's limit); a 429 or a network error backs off exponentially and is retried; a token error stops the whole run (logged out); a window that still fails is
left unrecorded, so the next run tries it again. Resumable and idempotent.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd

FLOOR = date(2015, 2, 2)                      # Kite's minute history starts about here (probed 2026-11-08: empty in 2014, present in 2015)
CHUNK_DAYS = 60
INDEX_PREFIX = "INDEX:"
COLS = ["ts", "open", "high", "low", "close", "volume"]
DEFAULT_MIN_INTERVAL = 0.36                   # ~2.8 requests a second across all workers
KEEP_SESSIONS = 60
SOURCE_MARKETS = ("IN",)


class KiteLoggedOut(RuntimeError):
    """The token is missing or was refused: stop and say so."""


class StopRun(RuntimeError):
    """The deadline or the STOP file: stop cleanly."""


# --- paths and keys ------------------------------------------------------------------------------------------------

def default_root() -> Path:
    from pflab.data import data_dir
    return data_dir() / "bars_1m"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.&-]+", "_", name.strip()).strip("_")


def file_stem(key: str) -> str:
    """'INDEX:NIFTY 50' -> 'INDEX_NIFTY_50'; a symbol stays as it is."""
    if key.startswith(INDEX_PREFIX):
        return "INDEX_" + _safe(key[len(INDEX_PREFIX):])
    return _safe(key)


def paths(root: Path, market: str, key: str) -> Tuple[Path, Path]:
    d = Path(root) / market
    stem = file_stem(key)
    return d / f"{stem}.parquet", d / f"{stem}.state.json"


# --- the time-ordered 60-day grid ------------------------------------------------------------------------------------

def chunk_bounds(k: int) -> Tuple[date, date]:
    s = FLOOR + timedelta(days=CHUNK_DAYS * k)
    return s, s + timedelta(days=CHUNK_DAYS - 1)


def chunk_of(d: date) -> int:
    return (d - FLOOR).days // CHUNK_DAYS


def chunks_newest_first(since: date, until: date) -> List[int]:
    return list(range(chunk_of(until), chunk_of(max(since, FLOOR)) - 1, -1))


# --- state ---------------------------------------------------------------------------------------------------------

def load_state(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"v": 1, "chunks": {}, "partial_days": {}, "rows": 0, "first_day": None, "last_day": None, "listed_from_chunk": None, "note": ""}


def save_state(p: Path, st: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def chunk_done(st: dict, k: int, last_closed: date) -> bool:
    """A window is covered when it was fetched through its last day, or through the last closed session when it runs past that."""
    if st.get("listed_from_chunk") is not None and k < st["listed_from_chunk"]:
        return True                                                    # before the first window that ever had data: nothing there
    thru = st["chunks"].get(str(k))
    if not thru:
        return False
    need = min(chunk_bounds(k)[1], last_closed)
    return date.fromisoformat(thru) >= need


# --- rate limit ----------------------------------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, min_interval: float = DEFAULT_MIN_INTERVAL, clock: Callable[[], float] = _time.monotonic,
                 sleep: Callable[[float], None] = _time.sleep):
        self.min_interval, self.clock, self.sleep = min_interval, clock, sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self.clock()
            t = max(now, self._next)
            self._next = t + self.min_interval
        if t > now:
            self.sleep(t - now)

    def penalty(self, seconds: float) -> None:
        """A 429 slows everybody down."""
        with self._lock:
            self._next = max(self._next, self.clock()) + seconds


# --- fetching ------------------------------------------------------------------------------------------------------

def _kind(e: Exception) -> str:
    n, msg = type(e).__name__, str(e).lower()
    if n == "TokenException" or "access_token" in msg or "token" in msg and ("invalid" in msg or "expired" in msg):
        return "token"
    if n == "PermissionException" or "insufficient permission" in msg or "historical" in msg and "subscri" in msg:
        return "permission"
    if "429" in msg or "too many" in msg:
        return "rate"
    if n in ("NetworkException", "ReadTimeout", "ConnectTimeout", "ConnectionError", "Timeout", "ChunkedEncodingError", "TimeoutError") or "timed out" in msg \
            or "connection" in msg or "502" in msg or "503" in msg or "504" in msg:
        return "network"
    return "other"


@dataclass
class Fetcher:
    kite: object
    limiter: RateLimiter = field(default_factory=RateLimiter)
    sleep: Callable[[float], None] = _time.sleep
    retries: int = 6
    deadline: Optional[datetime] = None
    stop_file: Optional[Path] = None
    now: Callable[[], datetime] = datetime.now
    n_requests: int = 0
    n_429: int = 0
    n_net: int = 0
    halt: Optional[str] = None

    def check_stop(self) -> None:
        if self.halt:
            raise StopRun(self.halt)
        if self.deadline is not None and self.now() >= self.deadline:
            raise StopRun("deadline")
        if self.stop_file is not None and Path(self.stop_file).exists():
            raise StopRun("stop file")

    def window(self, token: int, first: date, last: date) -> List[dict]:
        """One request: the 1-minute candles of first..last (inclusive). Backs off on 429 and network errors."""
        delay = 2.0
        for attempt in range(self.retries + 1):
            self.check_stop()
            self.limiter.wait()
            self.n_requests += 1
            try:
                return self.kite.historical_data(token, datetime.combine(first, time(9, 0)), datetime.combine(last, time(15, 40)), "minute") or []
            except Exception as e:                                    # classified below; nothing is swallowed silently
                kind = _kind(e)
                if kind == "token":
                    self.halt = "kite logged out"
                    raise KiteLoggedOut(f"{type(e).__name__}") from None
                if kind == "permission":
                    self.halt = "historical data refused"
                    raise PermissionError(f"historical data refused: {type(e).__name__}: {str(e)[:120]}") from None
                if kind not in ("rate", "network") or attempt == self.retries:
                    raise
                if kind == "rate":
                    self.n_429 += 1
                    self.limiter.penalty(delay)
                else:
                    self.n_net += 1
                self.sleep(delay)
                delay = min(delay * 2, 60.0)
        return []


def _empty() -> pd.DataFrame:
    return pd.DataFrame({"ts": pd.Series(dtype="datetime64[ns]"), **{c: pd.Series(dtype="float64") for c in COLS[1:]}})


def frame_of(rows: List[dict], market_open: time, market_close: time) -> pd.DataFrame:
    """Kite candles -> ts/open/high/low/close/volume, inside the session window only, no duplicates, sorted."""
    if not rows:
        return _empty()
    df = pd.DataFrame(rows)
    ts = pd.to_datetime(df["date"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_localize(None)
    df["ts"] = ts.dt.floor("min")
    tod = df["ts"].dt.time
    df = df[(tod >= market_open) & (tod < market_close)].drop_duplicates("ts").sort_values("ts")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype("float64")
    return df[COLS].reset_index(drop=True)


def write_parquet(p: Path, new: pd.DataFrame) -> pd.DataFrame:
    """Merge `new` into the file (a stored bar is kept, never changed) and write it atomically. Returns the merged frame."""
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        old = pd.read_parquet(p)
        df = pd.concat([old, new[~new["ts"].isin(old["ts"])]], ignore_index=True) if len(new) else old
    else:
        df = new
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    tmp = p.with_suffix(".tmp")
    df.to_parquet(tmp, index=False, compression="zstd", compression_level=5)
    os.replace(tmp, p)
    return df


def short_days(df: pd.DataFrame, expected: int, first: date, last: date) -> Dict[str, int]:
    """{day: bars} for the days in first..last that have fewer bars than a full session: stated, not filled. (A day with no bar is a holiday or no trade: not listed.)"""
    if df.empty:
        return {}
    d = df["ts"].dt.date
    cnt = df.groupby(d).size()
    return {str(k): int(v) for k, v in cnt.items() if first <= k <= last and v < expected}


def backfill_name(fetcher: Fetcher, root: Path, market: str, key: str, token: int, *, since: date, last_closed: date, expected: int,
                  market_open: time, market_close: time, flush_every: int = 12, log: Callable[[str], None] = lambda s: None) -> dict:
    """Fetch the missing 60-day windows of one name, newest first, since `since`. Returns a summary (counts, never a symbol)."""
    pq, sp = paths(root, market, key)
    st = load_state(sp)
    todo = [k for k in chunks_newest_first(since, last_closed) if not chunk_done(st, k, last_closed)]
    out = {"windows_todo": len(todo), "windows_fetched": 0, "rows_new": 0, "errors": 0, "stopped": None, "empty_windows": 0}
    pending: List[pd.DataFrame] = []
    pending_meta: List[Tuple[int, date, date, bool]] = []
    seen_data = bool(st.get("first_day"))
    empties_before_data = 0

    def flush() -> None:
        if not pending_meta:
            return
        full = [x for x in pending if len(x)]
        new = pd.concat(full, ignore_index=True) if full else _empty()
        if len(new) or pq.exists():
            merged = write_parquet(pq, new)
        else:
            merged = new
        for k, a, b, _ in pending_meta:
            st["chunks"][str(k)] = str(min(b, last_closed))
            st["partial_days"].update(short_days(new, expected, a, b))
        # a day recorded earlier as short stays stated only while it is short in the file
        if len(merged):
            st["first_day"], st["last_day"] = str(merged["ts"].iloc[0].date()), str(merged["ts"].iloc[-1].date())
        st["rows"] = int(len(merged))
        save_state(sp, st)
        out["rows_new"] += int(len(new))
        pending.clear()
        pending_meta.clear()

    try:
        for k in todo:
            a, b = chunk_bounds(k)
            bb = min(b, last_closed)
            try:
                rows = fetcher.window(token, a, bb)
            except (StopRun, KiteLoggedOut, PermissionError):
                raise
            except Exception as e:
                out["errors"] += 1
                log(f"  window {k} failed: {type(e).__name__}: {str(e)[:100]}")
                continue
            df = frame_of(rows, market_open, market_close)
            out["windows_fetched"] += 1
            if df.empty:
                out["empty_windows"] += 1
                if seen_data or empties_before_data >= 2:                # older than the listing: nothing earlier exists
                    st["listed_from_chunk"] = k + 1
                    pending_meta.append((k, a, b, False)); pending.append(df)
                    flush()
                    break
                empties_before_data += 1
            else:
                seen_data = True
            pending.append(df)
            pending_meta.append((k, a, b, not df.empty))
            if len(pending_meta) >= flush_every:
                flush()
        flush()
    except (StopRun, KiteLoggedOut, PermissionError) as e:
        flush()
        out["stopped"] = type(e).__name__ + (": " + str(e)[:80] if isinstance(e, (StopRun, PermissionError)) else "")
    return out


# --- what to fetch -----------------------------------------------------------------------------------------------------

def instrument_tokens(kite) -> Tuple[Dict[str, int], Dict[str, int]]:
    """({NSE tradingsymbol: token}, {index name: token}) from kite.instruments('NSE') (one call)."""
    eq: Dict[str, int] = {}
    ix: Dict[str, int] = {}
    for r in kite.instruments("NSE") or []:
        name, tok, seg = r.get("tradingsymbol"), r.get("instrument_token"), r.get("segment")
        if not (name and tok):
            continue
        if seg == "NSE":
            eq.setdefault(str(name).upper(), int(tok))
        elif seg == "INDICES":
            ix.setdefault(str(name).upper(), int(tok))
    return eq, ix


INDEX_WANTED = ["NIFTY 50", "NIFTY BANK", "NIFTY 500", "NIFTY 100", "NIFTY 200", "NIFTY NEXT 50", "NIFTY MIDCAP 100", "NIFTY MIDCAP 150", "NIFTY SMLCAP 100",
                "NIFTY IT", "NIFTY PHARMA", "NIFTY FMCG", "NIFTY AUTO", "NIFTY METAL", "NIFTY ENERGY", "NIFTY REALTY", "NIFTY PSU BANK", "NIFTY FIN SERVICE",
                "NIFTY INFRA", "NIFTY MEDIA", "INDIA VIX"]


def held_symbols(kite) -> List[str]:
    """The tradingsymbols the book holds, in memory only (the list is personal: it is never written or logged)."""
    return sorted({str(r.get("tradingsymbol")).upper() for r in (kite.holdings() or []) if r.get("tradingsymbol")})


def nifty500_symbols(data_dir: Optional[Path] = None) -> List[str]:
    """The current Nifty 500 members' symbols from the point-in-time membership table (to_date empty = still a member), most liquid first (the latest
    bhavcopy day's turnover), so a run that is stopped early has the deepest history on the names that matter most."""
    from pflab.data import data_dir as dd
    base = Path(data_dir or dd())
    p = base / "index_membership" / "NIFTY500.parquet"
    if not p.exists():
        return []
    m = pd.read_parquet(p)
    cur = m[m["to_date"].isna()] if "to_date" in m.columns else m
    syms = sorted({str(s).upper() for s in cur["symbol"].dropna()})
    try:
        yrs = sorted([q for q in (base / "bhavcopy").iterdir() if q.is_dir()])
        f = sorted(yrs[-1].glob("*.parquet"))[-1]
        b = pd.read_parquet(f, columns=["symbol", "series", "turnover"])
        rank = b[b["series"] == "EQ"].set_index(b["symbol"].astype(str).str.upper())["turnover"]
        syms.sort(key=lambda x: -float(rank.get(x, 0.0) or 0.0))
    except Exception:
        pass
    return syms


def plan(kite, data_dir: Optional[Path] = None, extra_indices: Iterable[str] = ()) -> List[dict]:
    """Tiers in priority order: [{tier, label, since, items:[(key, token)]}]. Holdings are resolved here and their names are not kept anywhere."""
    eq, ix = instrument_tokens(kite)
    held = [(s, eq[s]) for s in held_symbols(kite) if s in eq]
    held_set = {s for s, _ in held}
    idx = [(INDEX_PREFIX + n, ix[n]) for n in list(INDEX_WANTED) + list(extra_indices) if n in ix]
    n500 = [(s, eq[s]) for s in nifty500_symbols(data_dir) if s in eq and s not in held_set]
    return [dict(tier="held", since=FLOOR, items=held), dict(tier="index", since=FLOOR, items=idx), dict(tier="nifty500", since=FLOOR, items=n500)]


@dataclass
class RunConfig:
    root: Path
    market: str = "IN"
    workers: int = 3
    tiers: Tuple[str, ...] = ("held", "index", "nifty500")
    since_by_tier: Dict[str, date] = field(default_factory=dict)
    max_names_by_tier: Dict[str, int] = field(default_factory=dict)


def run(kite, cfg: RunConfig, *, deadline: Optional[datetime] = None, stop_file: Optional[Path] = None, now: Optional[datetime] = None,
        limiter: Optional[RateLimiter] = None, sleep: Callable[[float], None] = _time.sleep, log: Callable[[str], None] = print,
        data_dir: Optional[Path] = None, tiers_plan: Optional[List[dict]] = None) -> dict:
    """Run the tiers in order. Returns counts only. Names are logged for the index tier only (held names are personal)."""
    from pflab import markets
    m = markets.get(cfg.market)
    from pflab.quant.trajectory import expected_minutes
    expected = expected_minutes(m.open, m.close)
    now = now or datetime.now()
    last_closed = m.session_closed_by(now)
    fetcher = Fetcher(kite, limiter or RateLimiter(sleep=sleep), sleep=sleep, deadline=deadline, stop_file=stop_file)
    tp = tiers_plan if tiers_plan is not None else plan(kite, data_dir)
    summary: dict = {"market": cfg.market, "last_closed": str(last_closed), "tiers": {}, "stopped": None}
    lock = threading.Lock()
    for t in tp:
        if t["tier"] not in cfg.tiers:
            continue
        items = t["items"][: cfg.max_names_by_tier.get(t["tier"], len(t["items"]))]
        since = cfg.since_by_tier.get(t["tier"], t["since"])
        agg = {"names": len(items), "done": 0, "windows_fetched": 0, "rows_new": 0, "errors": 0, "empty_windows": 0}
        log(f"tier {t['tier']}: {len(items)} names since {since}")

        def work(it: Tuple[str, int], i: int) -> Optional[str]:
            key, tok = it
            try:
                fetcher.check_stop()
                r = backfill_name(fetcher, cfg.root, cfg.market, key, tok, since=since, last_closed=last_closed, expected=expected,
                                  market_open=m.open, market_close=m.close, log=(log if t["tier"] == "index" else (lambda s: None)))
            except StopRun:
                return "StopRun"
            except Exception as e:                                   # one name's failure (a disk or parquet error) must not end the run
                with lock:
                    agg["errors"] += 1
                    log(f"{datetime.now():%H:%M:%S} {t['tier']}#{i}: failed {type(e).__name__}: {str(e)[:100]}")
                return None
            with lock:
                for k in ("windows_fetched", "rows_new", "errors", "empty_windows"):
                    agg[k] += r[k]
                if r["stopped"] is None:
                    agg["done"] += 1
                tag = key if t["tier"] == "index" else f"{t['tier']}#{i}"
                if r["windows_fetched"] or r["stopped"] or r["errors"]:
                    log(f"{datetime.now():%H:%M:%S} {tag}: {r['windows_fetched']} windows, +{r['rows_new']} rows, errors {r['errors']}"
                        f"{', stopped ' + r['stopped'] if r['stopped'] else ''}; requests {fetcher.n_requests}, 429s {fetcher.n_429}")
            return r["stopped"]

        stopped = None
        with ThreadPoolExecutor(max_workers=cfg.workers) as ex:
            for res in ex.map(lambda a: work(*a), [(it, i) for i, it in enumerate(items)]):
                if res and stopped is None:
                    stopped = res
        summary["tiers"][t["tier"]] = agg
        if stopped:
            summary["stopped"] = stopped
            log(f"stopped: {stopped}")
            break
    summary.update(requests=fetcher.n_requests, rate_limited=fetcher.n_429, network_retries=fetcher.n_net)
    return summary


# --- the store table: the last 60 sessions ---------------------------------------------------------------------------

def _symbol_isin_map(data_dir: Optional[Path] = None) -> Dict[str, str]:
    """symbol -> ISIN from the newest bhavcopy day on disk (equity series only)."""
    from pflab.data import data_dir as dd
    base = Path(data_dir or dd()) / "bhavcopy"
    try:
        yrs = sorted([p for p in base.iterdir() if p.is_dir()])
        for y in reversed(yrs):
            fs = sorted(y.glob("*.parquet"))
            if fs:
                b = pd.read_parquet(fs[-1], columns=["symbol", "isin", "series"])
                b = b[b["series"].isin(["EQ", "BE", "BZ", "SM", "ST", "GB"]) & b["isin"].notna()]
                return dict(zip(b["symbol"].astype(str).str.upper(), b["isin"].astype(str)))
    except Exception:
        pass
    return {}


def _key_of_stem(stem: str, sym2isin: Dict[str, str]) -> Optional[str]:
    if stem.startswith("INDEX_"):
        return INDEX_PREFIX + stem[len("INDEX_"):].replace("_", " ")
    return sym2isin.get(stem.upper())


def load_recent(con, market: str, days: int = KEEP_SESSIONS, root: Optional[Path] = None, data_dir: Optional[Path] = None, prune: bool = True) -> dict:
    """Load the last `days` sessions of every parquet name into the store table `bars_1m` (idempotent: a stored bar is kept); drop table rows older than that.
    An index is keyed INDEX:<NAME> (names with '_' for spaces are restored to spaces); a stock by its ISIN (from the bhavcopy symbol map); a name with no ISIN is skipped and counted."""
    root = Path(root) if root else default_root()
    d = root / market
    out = {"files": 0, "rows": 0, "skipped_no_isin": 0, "pruned": 0}
    if not d.exists():
        return out
    sym2isin = _symbol_isin_map(data_dir)
    # INDEX_ stems lose their spaces; restore from the canonical names where they are known
    canon = {file_stem(INDEX_PREFIX + n): INDEX_PREFIX + n for n in INDEX_WANTED}
    cutoff: Optional[datetime] = None
    for f in sorted(d.glob("*.parquet")):
        stem = f.stem
        key = canon.get(stem) or _key_of_stem(stem, sym2isin)
        if key is None:
            out["skipped_no_isin"] += 1
            continue
        df = pd.read_parquet(f)
        if df.empty:
            continue
        sessions = sorted(df["ts"].dt.date.unique())[-days:]
        cut = datetime.combine(sessions[0], time(0, 0))
        cutoff = cut if cutoff is None else max(cutoff, cut)             # the newest per-name floor decides the table's floor
        b = df[df["ts"] >= cut].assign(market=market, isin=key)[["market", "isin", "ts", "open", "high", "low", "close", "volume"]]
        con.register("_bk_new", b)
        try:
            con.execute("INSERT INTO bars_1m SELECT market, isin, ts, open, high, low, close, volume FROM _bk_new ON CONFLICT DO NOTHING")
        finally:
            con.unregister("_bk_new")
        out["files"] += 1
        out["rows"] += len(b)
    if prune:
        try:
            from pflab import markets
            m = markets.get(market)
            last = con.execute("SELECT max(CAST(ts AS DATE)) FROM bars_1m WHERE market=?", [market]).fetchone()[0]
            if last is not None:
                first = m.session_after(last, -(days - 1)) if hasattr(m, "session_after") else last - timedelta(days=days * 2)
                n0 = con.execute("SELECT count(*) FROM bars_1m WHERE market=?", [market]).fetchone()[0]
                con.execute("DELETE FROM bars_1m WHERE market=? AND ts < ?", [market, datetime.combine(first, time(0, 0))])
                out["pruned"] = n0 - con.execute("SELECT count(*) FROM bars_1m WHERE market=?", [market]).fetchone()[0]
        except Exception:
            pass
    return out


def record_coverage(con, market: str, root: Optional[Path] = None, now: Optional[datetime] = None, data_dir: Optional[Path] = None) -> int:
    """Upsert one `bars_1m_history_s79` row per name on disk (from the state files). Returns the number of names."""
    root = Path(root) if root else default_root()
    d = root / market
    if not d.exists():
        return 0
    now = now or datetime.now()
    sym2isin = _symbol_isin_map(data_dir)
    n = 0
    for sp in sorted(d.glob("*.state.json")):
        st = load_state(sp)
        if not st.get("rows"):
            continue
        stem = sp.name[: -len(".state.json")]
        pq = d / f"{stem}.parquet"
        key = _key_of_stem(stem, sym2isin) if not stem.startswith("INDEX_") else None
        con.execute("DELETE FROM bars_1m_history_s79 WHERE market=? AND name=?", [market, stem])
        con.execute("INSERT INTO bars_1m_history_s79 VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [market, stem, key, st.get("first_day"), st.get("last_day"), int(st["rows"]), len(st.get("chunks") or {}), len(st.get("partial_days") or {}),
                     pq.stat().st_size if pq.exists() else 0, now])
        n += 1
    return n


# --- reading ---------------------------------------------------------------------------------------------------------

def read(market: str, key: str, start: date, end: date, root: Optional[Path] = None, con=None, data_dir: Optional[Path] = None) -> pd.DataFrame:
    """Minute bars of `key` (an ISIN, a symbol, or INDEX:<name>) for start..end inclusive, from the store table (if `con`) and the parquet history, merged,
    one row per ts, columns ts/open/high/low/close/volume. Missing minutes stay missing."""
    root = Path(root) if root else default_root()
    lo, hi = datetime.combine(start, time(0, 0)), datetime.combine(end + timedelta(days=1), time(0, 0))
    frames: List[pd.DataFrame] = []
    stems = []
    if key.startswith(INDEX_PREFIX):
        stems.append(file_stem(key))
    else:
        stems.append(file_stem(key))
        if re.match(r"^[A-Z]{2}[A-Z0-9]{9}\d$", key):                      # an ISIN: find its symbol
            inv = {v: k for k, v in _symbol_isin_map(data_dir).items()}
            if key in inv:
                stems.append(file_stem(inv[key]))
    for stem in stems:
        f = root / market / f"{stem}.parquet"
        if f.exists():
            df = pd.read_parquet(f, filters=[("ts", ">=", lo), ("ts", "<", hi)])
            frames.append(df[COLS])
            break
    if con is not None:
        try:
            t = con.execute("SELECT ts, open, high, low, close, volume FROM bars_1m WHERE market=? AND isin=? AND ts>=? AND ts<? ORDER BY ts",
                            [market, key, lo, hi]).fetchdf()
            if len(t):
                frames.append(t[COLS])
        except Exception:
            pass
    if not frames:
        return pd.DataFrame(columns=COLS)
    return pd.concat(frames, ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def coverage(root: Optional[Path] = None, market: str = "IN") -> dict:
    """Counts only: files, rows, bytes, earliest and latest day over all names (from the state files)."""
    root = Path(root) if root else default_root()
    d = root / market
    out = {"files": 0, "rows": 0, "bytes": 0, "first_day": None, "last_day": None, "partial_days": 0}
    if not d.exists():
        return out
    for sp in d.glob("*.state.json"):
        st = load_state(sp)
        if not st.get("rows"):
            continue
        out["files"] += 1
        out["rows"] += st["rows"]
        out["partial_days"] += len(st.get("partial_days") or {})
        if st.get("first_day") and (out["first_day"] is None or st["first_day"] < out["first_day"]):
            out["first_day"] = st["first_day"]
        if st.get("last_day") and (out["last_day"] is None or st["last_day"] > out["last_day"]):
            out["last_day"] = st["last_day"]
    out["bytes"] = sum(f.stat().st_size for f in d.glob("*.parquet"))
    return out
