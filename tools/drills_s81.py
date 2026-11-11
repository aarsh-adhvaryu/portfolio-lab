"""S81 drills and the accelerated run for the v2 core, on a SYNTHETIC profile with an injectable clock (development only; never the investor's record).

    python tools/drills_s81.py list
    python tools/drills_s81.py run [--only smoke,kill9] [--jobs 6] [--out D:\\s81_scratch\\drills\\report.json] [--findings F.md] [--start 2026-10-15] [--run-name NAME]
    python tools/drills_s81.py steps                 # which accelerated-run steps are applicable in this tree, and which module each OFF waits for

It replaces tools/drills_s79.py (which needs the deleted agenda, situation, missions, workers and brain). The same contract: a JSON report and a findings markdown, one result per
drill (PASS | FAIL | OFF | ERROR) with its evidence. Each drill runs in its own child process on its own clone of one base profile.

The profile is built here from nothing: synthetic names (ISINs starting INE9S / INF9S), synthetic prices with a seed, the account re-seeded from invented Kite holdings, one allocation
target. The outside world is faked: no network (every request raises ConnectionError), a fake Ollama answering through `requests` (down on request), the fetching jobs replaced by
fakes (the prices job "arrives" the next sessions' closes from rows held back from the profile), a fake Telegram transport. The jobs, the close loop, the rails, the lab, the storylines,
the outbox and the web endpoints run for real. Nothing touches the app, the workshop's store, the secrets file or the real Kite token.

MORE STEPS: the accelerated run's pieces are `ACCELERATED_STEPS`, a list of (name, fn, applicable_fn). `applicable_fn(env)` returns (True, "") or (False, "waiting for module X"):
the step is then reported OFF with that sentence. `fn(env, c, phase)` is called with phase "setup" (before the sessions run: inject what the step needs) and "check" (after them:
assert on the store, the outbox and the act log). To add a step append one tuple; use `needs("pflab.core.exits", ...)` for the guard.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("S81_SRC") or (REPO / "src"))          # S81_SRC=<another checkout>\src runs the drills against that tree's code (its configs/ come with it)
for _p in (SRC, REPO / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
SCRATCH = Path(os.environ.get("S81_DRILLS_DIR", r"D:\s81_scratch\drills"))
DEFAULT_START = date(2026, 10, 15)           # a Thursday. Fri 16, Mon 19, [Tue 20 holiday], Wed 21 ... : ten sessions end Thu 29 Oct, with a weekend and a holiday inside
OLLAMA = "http://localhost:11434"
BASELINES = ("baseline_v1", "baseline_v2")      # the policy id in the decision rows is whichever baseline `[baseline_v2] version` names (baseline_v2 from S81)
SGB_ISIN = "IN0020230099"                     # the synthetic inherited Sovereign Gold Bond

# name, isin, sector, daily vol, drift, price at the seed day, quantity held, average cost, acquired (None: the seed day)
STOCKS = [("SYNFMCG1", "INE9S1A01011", "FMCG", 0.011, 0.0004, 2400.0, 50, 2000.0, date(2025, 3, 3)),
          ("SYNFMCG2", "INE9S2A01011", "FMCG", 0.016, 0.0003, 410.0, 300, 380.0, None),
          ("SYNCAPG1", "INE9S3A01011", "Capital Goods", 0.013, 0.0005, 3500.0, 20, 3100.0, None),
          ("SYNIT1", "INE9S4A01011", "IT", 0.021, 0.0002, 1500.0, 80, 600.0, date(2024, 6, 3)),
          ("SYNBANK1", "INE9S5A01011", "Banks", 0.015, 0.0003, 900.0, 0, 0.0, None),
          ("SYNAUTO1", "INE9S6A01011", "Auto", 0.018, 0.0004, 2100.0, 0, 0.0, None)]
# the core ETFs carry the public tickers the baseline's configuration names (configs/core.toml [baseline_v2]) but synthetic ISINs, names and prices; JUNIORBEES is in the store and not in the book
ETFS = [("NIFTYBEES", "INF9S1B01011", "Synthetic Nifty 50 Index ETF", 0.009, 0.0004, "EQUITY", 270.0, 400, 250.0),
        ("GOLDBEES", "INF9S2B01011", "Synthetic Gold ETF", 0.007, 0.0003, "LISTED_NONEQUITY", 70.0, 1500, 60.0),
        ("MON100", "INF9S3B01011", "Synthetic Nasdaq 100 International ETF", 0.011, 0.0004, "LISTED_NONEQUITY", 100.0, 500, 90.0),
        ("JUNIORBEES", "INF9S4B01011", "Synthetic Nifty Next 50 Index ETF", 0.010, 0.0004, "EQUITY", 240.0, 0, 0.0)]
N_HISTORY = 330                               # sessions before the start
N_AHEAD = 60                                  # sessions after it, held back until they "arrive"


# --- small things -----------------------------------------------------------------------------------------------------------------------

class FakeClock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def set(self, t: datetime) -> datetime:
        self.t = t
        return t


class ErrorCatcher(logging.Handler):
    """Every pflab log record at ERROR, kept (a loop that logged an exception was not 'handled' silently)."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records: List[str] = []

    def emit(self, record):
        if record.name.startswith("pflab") or record.name.startswith("root"):
            txt = f"{record.name}: {record.getMessage()}"
            if record.exc_info:
                txt += " | " + "".join(traceback.format_exception_only(record.exc_info[0], record.exc_info[1])).strip()
            self.records.append(txt[:400])


class Check:
    """Evidence and findings of one drill (or one step)."""

    def __init__(self, name: str):
        self.name, self.evidence, self.findings, self.world = name, [], [], []
        self.off_reason: Optional[str] = None
        self.steps: List[dict] = []

    def ok(self, cond: bool, msg: str, where: str = "", how: str = "") -> bool:
        self.evidence.append(("ok: " if cond else "FAIL: ") + msg)
        if not cond:
            self.findings.append({"what": msg, "where": where or "(see evidence)", "how": how or f"python tools/drills_s81.py run --only {self.name}"})
        return bool(cond)

    def note(self, msg: str) -> None:
        self.evidence.append(msg)

    def says(self, msg: str) -> None:
        if msg and msg not in self.world:
            self.world.append(msg)

    def off(self, why: str) -> None:
        self.off_reason = why
        self.evidence.append("OFF: " + why)

    def result(self, started: float, status: Optional[str] = None) -> dict:
        failed = any(e.startswith("FAIL:") for e in self.evidence)
        st = status or ("OFF" if self.off_reason and not failed and not any(e.startswith("ok:") for e in self.evidence) else "FAIL" if failed else "PASS")
        return {"name": self.name, "status": st, "passed": st == "PASS", "evidence": self.evidence, "world_says": " | ".join(self.world), "findings": self.findings,
                "steps": self.steps, "seconds": round(time.time() - started, 1)}


def dt(d: date, h: int, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m)


def module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def needs(*modules: str, why: str = "") -> Callable:
    """An applicable_fn for ACCELERATED_STEPS: (True, "") when every module is in this tree, else (False, 'waiting for module X ...')."""
    def fn(env=None):
        for m in modules:
            if not module_exists(m):
                return False, f"waiting for module {m}" + (f" ({why})" if why else "")
        return True, ""
    return fn


def source_of(modname: str) -> str:
    try:
        return Path(importlib.util.find_spec(modname).origin).read_text(encoding="utf-8")
    except Exception:
        return ""


# --- the outside world, faked -----------------------------------------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.ok = data, status, status < 400
        self.text, self.headers, self.content = json.dumps(data), {}, json.dumps(data).encode()

    def json(self):
        return self._d

    def raise_for_status(self):
        if not self.ok:
            import requests
            raise requests.exceptions.HTTPError(f"{self.status_code}")


def _gen(schema: dict, prompt: str):
    """A value that satisfies a JSON schema (enough for the local jobs); a 'quote' is a line of the prompt itself."""
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type")
    if isinstance(t, list):
        t = [x for x in t if x != "null"][0] if [x for x in t if x != "null"] else "null"
    if t == "object":
        out = {}
        for k, v in schema.get("properties", {}).items():
            out[k] = (([ln.strip() for ln in prompt.splitlines() if len(ln.strip()) > 8] or ["x"])[0][:120]) if k == "quote" else _gen(v, prompt)
        return out
    if t == "array":
        return [_gen(schema.get("items", {}), prompt)] if schema.get("minItems", 0) >= 1 else []
    if t == "integer":
        return int(schema.get("minimum", 1))
    if t == "number":
        return float(schema.get("minimum", 0.0))
    if t == "boolean":
        return True
    if t == "null":
        return None
    return "ok"


def fake_chat_text(payload: dict) -> str:
    """What the fake local model says. The storyline reader's structured question gets a valid answer (attach to the first open story, else open one, else ignore)."""
    import re
    msgs = payload.get("messages", [])
    user = msgs[-1]["content"] if msgs else ""
    fmt = payload.get("format")
    if fmt is not None and isinstance(fmt, dict) and "action" in (fmt.get("properties") or {}):
        ids = [int(x) for x in re.findall(r"^- #(\d+) ", user, flags=re.M)]
        if ids:
            return json.dumps({"action": "attach", "storyline_id": ids[0], "stance": "for", "strength": "moderate"})
        menu = re.findall(r"^- ([a-z0-9_]+): ", user.split("SIGNAL MENU")[-1], flags=re.M)
        if menu:
            return json.dumps({"action": "new", "new_claim": "Foreign selling is rotating money away from Indian shares, so the Nifty may fall", "direction": -1, "templates": menu[:1]})
        return json.dumps({"action": "ignore"})
    if fmt is not None:
        return json.dumps(_gen(fmt, user))
    return "The local model has nothing to add beyond the figures already shown; the data does not say why."


class Net:
    """No outside network at all, plus a fake Ollama at its usual address (down on request). Installed once per process."""

    def __init__(self):
        self.ollama_up = True
        self.chat_calls = 0
        self.blocked: List[str] = []
        self._orig: Dict[str, object] = {}

    def _tags(self):
        return {"models": [{"name": "qwen3:8b-q8_0", "digest": "fake-digest", "size": 1, "details": {"parameter_size": "8B", "quantization_level": "Q8_0"}},
                           {"name": "nomic-embed-text:latest", "digest": "fake-embed", "size": 1, "details": {}}]}

    def install(self) -> "Net":
        import requests
        net = self

        def request(self_, method, url, **kw):
            from pflab.llm import client
            if net.ollama_up and str(url).startswith(client.URL) and client.URL == OLLAMA:
                path = str(url)[len(OLLAMA):]
                if path.startswith("/api/tags"):
                    return FakeResponse(net._tags())
                if path.startswith("/api/chat"):
                    net.chat_calls += 1
                    return FakeResponse({"message": {"content": fake_chat_text(kw.get("json") or {})}, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 10})
                return FakeResponse({"embeddings": [[0.0] * 8]})
            net.blocked.append(str(url)[:80])
            raise requests.exceptions.ConnectionError(f"drill: network is down (getaddrinfo failed for {str(url)[:60]})")

        def urlopen(url, *a, **k):
            u = url if isinstance(url, str) else getattr(url, "full_url", str(url))
            if net.ollama_up and u.startswith(OLLAMA + "/api/tags"):
                import io
                return io.BytesIO(json.dumps(net._tags()).encode())
            net.blocked.append(u[:80])
            raise urllib.error.URLError("drill: network is down")

        def _loop(addr) -> bool:
            h = addr[0] if isinstance(addr, tuple) else str(addr)
            return str(h) in ("127.0.0.1", "localhost", "::1")

        def create_connection(address, *a, **k):
            if not _loop(address):
                net.blocked.append(str(address)[:60])
                raise ConnectionError("drill: network is down")
            return self._orig["create_connection"](address, *a, **k)

        self._orig = {"request": requests.sessions.Session.request, "urlopen": urllib.request.urlopen, "create_connection": socket.create_connection}
        requests.sessions.Session.request = request
        urllib.request.urlopen = urlopen
        socket.create_connection = create_connection
        return self

    def uninstall(self) -> None:
        import requests
        if self._orig:
            requests.sessions.Session.request = self._orig["request"]
            urllib.request.urlopen = self._orig["urlopen"]
            socket.create_connection = self._orig["create_connection"]
            self._orig = {}

    def ollama_down(self) -> None:
        from pflab.llm import client
        self.ollama_up = False
        client.URL = "http://127.0.0.1:9"

    def ollama_back(self) -> None:
        from pflab.llm import client
        self.ollama_up = True
        client.URL = OLLAMA


class FakeTelegram:
    """The transport under `telegram.make_sender`: every message that would have left the PC is kept here (nothing leaves it)."""

    def __init__(self):
        self.sent: List[str] = []
        self.up = True

    def __call__(self, url: str, payload: dict):
        if not self.up:
            return 500, {"ok": False, "description": "drill: telegram down"}
        self.sent.append(payload.get("text", ""))
        return 200, {"ok": True}


class CountingClient:
    """A stand-in for the paid SDK client: counts every request that would have reached the API. A drill that finds `created` above zero has found a paid call."""

    def __init__(self):
        self.created = 0
        self.counted = 0
        outer = self

        class _Msgs:
            def create(self, **kw):
                outer.created += 1
                raise RuntimeError("drill: a paid call was made")

            def count_tokens(self, **kw):
                outer.counted += 1

                class T:
                    input_tokens = 1500
                return T()

        class _Beta:
            class messages:
                @staticmethod
                def create(**kw):
                    outer.created += 1
                    raise RuntimeError("drill: a paid call was made")
        self.messages = _Msgs()
        self.beta = _Beta()


# --- the base profile (built once) and one clone per drill -------------------------------------------------------------------------------

def _sessions(first: date, n_back: int, n_ahead: int, start: date) -> Tuple[List[date], List[date]]:
    from pflab import markets
    m = markets.get("IN")
    back, d = [], m.previous_session(start)
    while len(back) < n_back:
        back.append(d)
        d = m.previous_session(d)
    ahead, d = [], start
    while len(ahead) < n_ahead:
        if m.is_session(d):
            ahead.append(d)
        d += timedelta(days=1)
    return sorted(back), ahead


def synth_prices(start: date) -> Tuple[list, list]:
    """(rows before `start`, rows from `start` on) of the prices table, for every synthetic security. Deterministic."""
    import numpy as np
    back, ahead = _sessions(start, N_HISTORY, N_AHEAD, start)
    days = back + ahead
    rng = np.random.default_rng(81)
    rows_b, rows_a = [], []
    specs = [(s[1], s[3], s[4], s[5], "EQ") for s in STOCKS] + [(e[1], e[3], e[4], e[6], "EQ") for e in ETFS]
    for isin, vol, drift, p_seed, series in specs:
        r = rng.normal(drift, vol, len(days))
        lvl = np.exp(np.cumsum(r))
        seed_i = len(back) - 1
        px = lvl / lvl[seed_i] * p_seed
        for d, p in zip(days, px):
            (rows_b if d < start else rows_a).append((isin, d, round(float(p), 4), series, "nse_bhavcopy"))
    for i, d in enumerate(days):                                                  # the inherited gold bond: a slow price
        (rows_b if d < start else rows_a).append((SGB_ISIN, d, round(6150.0 + 0.8 * (i - len(back) + 1), 2), "GB", "nse_bhavcopy"))
    return rows_b, rows_a


def build_base(base: Path, start: date) -> dict:
    """Instruments and prices (synthetic) -> the re-seed from invented Kite holdings on the session before `start` -> one allocation target. The prices from `start` on are held
    back in held_prices.parquet (they 'arrive' later, one session at a time)."""
    import pandas as pd
    from pflab import markets
    from pflab.paper import allocation, reseed
    from pflab.pm import store
    if base.exists():
        shutil.rmtree(base)
    (base / "pm" / "app").mkdir(parents=True)
    (base / "data").mkdir()
    os.environ["PFLAB_PM_DIR"] = str(base / "pm")
    os.environ["PFLAB_DATA_DIR"] = str(base / "data")
    con = store.connect(base / "pm" / "ledger.duckdb")
    now0 = datetime.now()
    for sym, isin, sector, *_ in STOCKS:
        con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, ?, 'synthetic drills', ?)",
                    [isin, sym, f"{sym} Limited", sector, now0])
    for sym, isin, name, _v, _d, tc, *_ in ETFS:
        con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'etf', ?, TRUE, ?, ?, 'synthetic drills', ?)",
                    [isin, tc, sym, name, now0])
    rows_b, rows_a = synth_prices(start)
    cols = ["isin", "date", "close", "series", "source"]
    before = pd.DataFrame(rows_b, columns=cols)
    before["fetched_at"] = now0
    con.register("_b", before)
    con.execute("INSERT INTO prices SELECT isin, date, close, series, source, fetched_at FROM _b")
    con.unregister("_b")
    after = pd.DataFrame(rows_a, columns=cols)
    after["fetched_at"] = now0
    after.to_parquet(base / "held_prices.parquet")
    m = markets.get("IN")
    prev = m.previous_session(start)
    holdings = [dict(isin=s[1], symbol=s[0], qty=s[6], avg_price=s[7], last_price=s[5], acq_date=s[8]) for s in STOCKS if s[6]]
    holdings += [dict(isin=e[1], symbol=e[0], qty=e[7], avg_price=e[8], last_price=e[6], acq_date=None) for e in ETFS if e[7]]
    holdings.append(dict(isin=SGB_ISIN, symbol="SGBSYN33", qty=6, avg_price=0.0, last_price=6150.0, acq_date=None))
    now = datetime.combine(prev, datetime.min.time()).replace(hour=21, minute=30)
    out = reseed.reseed(con, holdings, now, pm_dir=base / "pm", backup_dir=base / "backups")
    target = None
    try:
        t = allocation.propose_allocation(con, {"equity": 55, "gold": 20, "international": 10, "cash": 15},
                                          "A drill split with its reasons given in a few plain sentences about gold, shares and some cash for the rails.", now,
                                          sectors={"FMCG": 20, "Capital Goods": 15})
        allocation.review_target(con, t["target_id"], "approve", "drill: the independent review is simulated", now)
        target = t["target_id"]
    except Exception as e:                                                       # a tree whose allocation API changed: the drills then run on the policy's own default
        target = f"none ({type(e).__name__}: {str(e)[:80]})"
    sync_data_files(con, base / "data")
    con.execute("CHECKPOINT")
    meta = {"start": str(start), "seeded_on": str(out.get("seed_date")), "target_id": target, "isins": [h["isin"] for h in holdings]}
    con.close()
    (base / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def sync_data_files(con, data: Path) -> None:
    """The data folder's files, rebuilt from the prices the store has so far (so a file never holds a close the store does not: point in time): the three Nifty series the jobs read and
    `panel/prices.parquet`, the wide panel the lab and a promoted champion read (stocks only; the synthetic ETFs are not among the four names the lab's panel knows)."""
    import numpy as np
    import pandas as pd
    rows = con.execute("SELECT p.date, p.isin, p.close, i.symbol, i.asset_class FROM prices p JOIN instruments i USING (isin) WHERE p.source='nse_bhavcopy' AND i.asset_class IN ('equity','etf') ORDER BY p.date").fetchall()
    if not rows:
        return
    df = pd.DataFrame(rows, columns=["date", "isin", "close", "symbol", "kind"])
    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot_table(index="date", columns="isin", values="close", aggfunc="last").sort_index()
    idx = (wide / wide.iloc[0]).mean(axis=1) * 1000.0
    (data / "indices").mkdir(parents=True, exist_ok=True)
    for key, scale in (("NIFTY50_PRICE", 20.0), ("NIFTY50_TRI", 25.0), ("NIFTY500_TRI", 30.0), ("NIFTY500_PRICE", 15.0)):
        s = idx * scale / 1000.0
        pd.DataFrame({"date": s.index, "open": s.values, "high": s.values * 1.004, "low": s.values * 0.996, "close": s.values}).to_parquet(data / "indices" / f"{key}.parquet")
    last = idx.index.max()                                                     # the US benchmark: every weekday up to the latest Indian close that has arrived (its closes are in by the Indian morning)
    us_days = pd.bdate_range(idx.index.min(), last)
    wob = np.exp(np.cumsum(np.random.default_rng(7).normal(0.0, 0.006, len(us_days))))                           # its own moves: a series that is a copy of the Indian one makes every regression singular
    us = pd.Series(np.interp(us_days.values.astype("int64"), idx.index.values.astype("int64"), idx.values) * 4.5 * wob, index=us_days)
    (data / "global").mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": us.index, "open": us.values, "high": us.values * 1.004, "low": us.values * 0.996, "close": us.values}).to_parquet(data / "global" / "US_SP500.parquet")
    rng = np.random.default_rng(11)                                            # the US sub-book's inputs: bars of its 13 ETFs (data/us/raw) and the market USD/INR close (data/global/FX_USDINR)
    (data / "us" / "raw").mkdir(parents=True, exist_ok=True)
    for k, sym in enumerate(("SPY", "QQQ", "XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU")):
        r = np.random.default_rng(100 + k).normal(0.0004, 0.01, len(us_days))
        close = (50.0 + 30 * k) * np.exp(np.cumsum(r))
        div = np.where(us_days == pd.Timestamp("2026-10-22"), 1.2 if sym == "SPY" else 0.0, 0.0)           # one dividend on SPY: the withholding and its credit
        pd.DataFrame({"date": us_days, "open": close * 0.999, "high": close * 1.006, "low": close * 0.994, "close": close, "adj_close": close, "volume": 5e6, "dividend": div}).to_parquet(data / "us" / "raw" / f"{sym}.parquet")
    fxs = 83.0 * np.exp(np.cumsum(rng.normal(0.0001, 0.002, len(us_days))))
    pd.DataFrame({"date": us_days, "open": fxs, "high": fxs, "low": fxs, "close": fxs}).to_parquet(data / "global" / "FX_USDINR.parquet")
    st = df[(df["kind"] == "equity") | df["symbol"].isin(("NIFTYBEES", "JUNIORBEES", "BANKBEES", "GOLDBEES"))].copy()          # the lab's panel knows these four ETFs by name
    (data / "panel").mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": st["date"], "isin": st["isin"], "symbol": st["symbol"], "instrument_type": np.where(st["kind"] == "etf", "ETF", "STK"), "series": "EQ",
                  "adj_close": st["close"].astype(float), "close": st["close"].astype(float), "turnover": np.float64(5e7)}).to_parquet(data / "panel" / "prices.parquet")


def process_setup(run_dir: Path) -> None:
    """Everything a drill process must not do for real: the real home, secrets, Kite token, a worker pool, a paid call, the workshop's folders."""
    os.environ["PFLAB_SECRETS_FILE"] = str(run_dir / "secrets_absent.toml")
    os.environ["PFLAB_NO_POOL"] = "1"
    os.environ["PFLAB_DATA_DIR"] = str(run_dir / "data")
    for k in ("PFLAB_PAID", "PFLAB_LIVE", "PFLAB_SANDBOX"):
        os.environ.pop(k, None)
    from pflab.ingest import kite as km
    tok = run_dir / "kite_token.json"
    km.default_token_path = lambda: tok


class Env:
    """One drill's world: a clone of the base profile, a fake clock, a Runtime that is never started with threads, the fakes installed."""

    def __init__(self, name: str, run_root: Path, base: Path, connect: bool = True):
        self.name, self.dir, self.base = name, run_root / name, base
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        shutil.copytree(base / "pm", self.dir / "pm")
        shutil.copytree(base / "data", self.dir / "data")
        shutil.copy(base / "held_prices.parquet", self.dir / "held_prices.parquet")
        self.meta = json.loads((base / "meta.json").read_text(encoding="utf-8"))
        self.start = date.fromisoformat(self.meta["start"])
        self.pm, self.data = self.dir / "pm", self.dir / "data"
        os.environ["PFLAB_PM_DIR"] = str(self.pm)
        process_setup(self.dir)
        self.clock = FakeClock(dt(self.start, 6))
        self.catcher = ErrorCatcher()
        logging.getLogger().addHandler(self.catcher)
        self.exceptions: List[str] = []
        self.net = Net().install()
        self.tg = FakeTelegram()
        self.con = None
        self.rt = None
        self.arrived: List[str] = []
        self.failed_jobs: List[tuple] = []
        self.real_jobs: dict = {}
        self.real_docker_probe = self.real_sb_status = None
        if connect:
            self.connect()

    # --- store and runtime
    def connect(self) -> None:
        from pflab.app.runtime import Runtime
        from pflab.pm import secrets as sec, store
        for attempt in range(40):                                  # a killed process's file handle can outlive the kill by a moment on Windows
            try:
                self.con = store.connect(self.pm / "ledger.duckdb")
                break
            except Exception as e:
                if "being used by another process" not in str(e) or attempt == 39:
                    raise
                time.sleep(0.5)
        self.rt = Runtime(self.pm, self.data, REPO, con=self.con, secrets=sec.Secrets({"kite": {"api_key": "fk-7731-key", "api_secret": "fk-7731-secret"}}), clock=self.clock)
        _fakes(self)

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:
            pass
        self.net.uninstall()
        logging.getLogger().removeHandler(self.catcher)

    def cur(self):
        return self.con.cursor()

    # --- the app opening: Runtime.start without its threads (the same on-open code)
    def open_app(self, t: datetime) -> None:
        import pflab.app.runtime as rtm
        self.clock.set(t)

        class NoThread:
            def __init__(self, target=None, name=None, daemon=None, **kw):
                self.name = name or ""

            def start(self):
                pass

            def join(self, t=None):
                pass
        real = rtm.threading.Thread
        rtm.threading.Thread = NoThread
        try:
            self.rt.start()
        finally:
            rtm.threading.Thread = real

    def safe(self, label: str, fn: Callable, *a, **k):
        """A loop body, called the way the app's loop calls it: an exception is recorded (the loop survives), never swallowed unseen."""
        try:
            return fn(*a, **k)
        except Exception:
            self.exceptions.append(f"{self.clock.t:%a %d %b %H:%M} {label}: " + traceback.format_exc(limit=4).strip().splitlines()[-1][:300])
            return None

    def step(self, t: datetime, *, continuous: bool = True, hq: bool = False) -> dict:
        """One pass of the app's loops at fake time t: the heart, the scheduler (and the jobs it asks for next), the HQ round when asked. `continuous`: the heart has been beating
        (no wake)."""
        self.clock.set(t)
        rt = self.rt
        if continuous:
            rt._beat = t - timedelta(seconds=30)
        out = {"t": t, "catching_up": self.safe("beat", rt.beat)}
        self.safe("run_wanted", rt.run_wanted)
        out["jobs"] = self.safe("scheduler_once", rt.scheduler_once) or []
        self.safe("run_wanted", rt.run_wanted)
        if hq:
            from pflab.hq import service
            out["hq"] = self.safe("hq_round", service.round_, rt)
        for j in out["jobs"]:
            if j.status == "failed" and not j.detail.startswith("abandoned"):
                self.failed_jobs.append((f"{t:%a %d %b %H:%M}", j.job, j.detail[:200]))
        try:
            with open(self.dir / "progress.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} fake {t:%a %d %b %H:%M} jobs={[(j.job, j.status) for j in out['jobs']]} exc={len(self.exceptions)}\n")
        except OSError:
            pass
        return out

    def job_status(self, name: str) -> Optional[tuple]:
        return self.cur().execute("SELECT status, detail, started_at FROM job_runs WHERE job=? ORDER BY run_id DESC LIMIT 1", [name]).fetchone()

    def world(self) -> dict:
        from pflab.app import world, system
        system._CACHE.clear()
        return world.build(self.rt, self.clock.t)

    def client(self):
        """A TestClient on the real web app over this runtime (the endpoints the Today screen reads)."""
        from fastapi.testclient import TestClient
        from pflab.app.server import create_app
        return TestClient(create_app(self.rt))


# jobs replaced by fakes: they fetch, spawn collectors, send, call a paid model, need Docker or Kite, or take minutes. The rest of the registry runs for real. A name that is not in
# the registry of this tree is ignored (the list is by name so that a new job is real unless it is added here).
FAKE_JOBS = ("instruments", "collect", "nav", "filings", "live", "tradecheck", "kg", "analyst", "research", "global", "outbox", "backup", "us_fx", "ledger", "deposits", "backfill",
             "hq", "conductor", "learner", "security", "selfcheck", "comove", "scans", "companion", "outgoing", "sandbox", "twin", "bars_1m", "data_s79b",
             "implied_calibration", "idle_cash", "watches", "watches_close", "forecast", "forecast_loop", "seats_mode", "plans", "review", "guards", "macro_attribution",
             "benchmark_attr", "bear_resolve", "summary_morning", "summary_evening", "news_s81_topup", "us_prices_daily")
ARRIVAL_HOUR = (20, 15)            # NSE's files are in by the prices job's slot; a session's closes do not arrive before it


def available_through(now: datetime) -> date:
    """The latest session whose closes have arrived by `now` (same day 20:15 onwards)."""
    from pflab import markets
    m = markets.get("IN")
    d = now.date()
    if m.is_session(d) and (now.hour, now.minute) >= ARRIVAL_HOUR:
        return d
    return m.previous_session(d)


def arrive(env: "Env", upto: date) -> list:
    """Insert held-back price rows for the sessions after what the store has, through `upto`."""
    import pandas as pd
    con = env.cur()
    have = con.execute("SELECT max(date) FROM prices WHERE source='nse_bhavcopy'").fetchone()[0]
    held = pd.read_parquet(env.dir / "held_prices.parquet")
    held["date"] = pd.to_datetime(held["date"]).dt.date
    days = sorted({d for d in held["date"].unique() if (have is None or d > have) and d <= upto})
    for d in days:
        rows = held[held["date"] == d]
        con.register("_arr", rows)
        try:
            con.execute("INSERT INTO prices SELECT isin, date, close, series, source, fetched_at FROM _arr")
        finally:
            con.unregister("_arr")
        env.arrived.append(str(d))
    if days:
        sync_data_files(con, env.data)
    return [str(d) for d in days]


def _fakes(env: "Env") -> None:
    from dataclasses import replace
    import pkgutil
    import pflab.service as svc
    from pflab.service import jobs, tasks  # noqa: F401
    for m in pkgutil.iter_modules(svc.__path__):
        if m.name.startswith("tasks"):
            try:
                importlib.import_module(f"pflab.service.{m.name}")
            except Exception as e:  # a broken job module is itself a finding
                env.exceptions.append(f"import pflab.service.{m.name}: {type(e).__name__}: {e}")
    env.real_jobs = dict(jobs.REGISTRY)

    def fake(ctx):
        return {"drill_fake": "fetch/paid/heavy job replaced by a fake"}

    def prices(ctx):
        days = arrive(env, available_through(ctx.now))
        return {"drill_fake": "closes arrive from held rows", "days": days}
    for name, job in list(jobs.REGISTRY.items()):
        if name == "prices":
            jobs.REGISTRY[name] = replace(job, fn=prices)
        elif name in FAKE_JOBS:
            jobs.REGISTRY[name] = replace(job, fn=fake)
    from pflab.app import system
    from pflab.agents import sandbox as sb
    env.real_docker_probe, env.real_sb_status = system._docker_probe, sb.status
    system._docker_probe = lambda: "running"
    sb.status = lambda *a, **k: {"ok": True, "why": ""}


def run_real_job(env: "Env", name: str, data_root: Optional[Path] = None):
    from pflab.service import jobs
    ctx = jobs.Ctx(env.cur(), env.clock.t, env.pm, data_root or env.data, REPO, sys.executable, env.rt.secrets)
    return jobs.run_job(ctx, env.real_jobs[name])


# --- drills ---------------------------------------------------------------------------------------------------------------------------------

DRILLS: Dict[str, Callable] = {}
ORDER: List[str] = []


def drill(name: str, minutes: float = 20.0, connect: bool = True):
    def deco(fn):
        fn.drill_name, fn.minutes, fn.connect = name, minutes, connect
        DRILLS[name] = fn
        ORDER.append(name)
        return fn
    return deco


def day_times(d: date) -> List[datetime]:
    """The fake clock's steps of one day: a session day at 07 (pre_open), 10 and 13 (session), 16 (post_close), 18, 21 (the closes arrive), 23 (deep); a closed day twice."""
    from pflab import markets
    hours = [7, 10, 13, 16, 18, 21, 23] if markets.get("IN").is_session(d) else [9, 19]
    return [dt(d, h) for h in hours]


def run_days(env: "Env", first: date, last: date, on_step: Optional[Callable] = None, **kw) -> list:
    out, d = [], first
    while d <= last:
        for t in day_times(d):
            if t < env.clock.t:
                continue
            r = env.step(t, **kw)
            out.append(r)
            if on_step:
                env.safe("on_step", on_step, env, t, r)
        d += timedelta(days=1)
    return out


def run_until(env: "Env", first: date, stop: datetime, **kw) -> None:
    d = first
    while d <= stop.date():
        for t in day_times(d):
            if t > stop:
                return
            if t >= env.clock.t:
                env.step(t, **kw)
        d += timedelta(days=1)


def clean(env: "Env", c: Check, what: str = "the loops") -> None:
    c.ok(not env.exceptions, f"no unhandled exception in {what}: {env.exceptions[:3]}", "(the loop named in the evidence)")
    c.ok(not env.catcher.records, f"no error logged by pflab in {what}: {env.catcher.records[:3]}", "(the logger named in the evidence)")


def core_rows(con) -> list:
    return con.execute("SELECT day, policy_id, status, orders_json, note FROM core_runs_s80 ORDER BY day").fetchall()


def orders_of(con, day: date) -> list:
    """paper_orders placed on `day`'s evening: (order_id, decision_id, isin, side)."""
    return con.execute("SELECT order_id, decision_id, isin, side FROM paper_orders WHERE CAST(placed_at AS DATE) = ? ORDER BY order_id", [day]).fetchall()


def class_gap(con, day: date, classes: Optional[dict] = None) -> Optional[float]:
    """The distance (sum of absolute points) of the book's class mix from the active allocation target at `day`'s close, from paper_days (a number by code)."""
    from pflab.paper import allocation, book
    act = {"classes": classes} if classes else allocation.active_target(con)
    if not act:
        return None
    r = con.execute("SELECT value, cash, holdings_json FROM paper_days WHERE day=?", [day]).fetchone()
    if r is None:
        return None
    total, _cash, pos = float(r[0]), float(r[1]), json.loads(r[2] or "{}")
    mix = {"equity": 0.0, "gold": 0.0, "international": 0.0, "cash": 0.0}
    for isin, q in pos.items():
        px = book.close_on(con, isin, day)
        m = book.inst(con, isin)
        k = allocation.class_of(m["asset_class"], m["name"], m["symbol"], isin)
        mix[k] = mix.get(k, 0.0) + (q * px[1] / total * 100 if px else 0.0)
    mix["cash"] = max(0.0, 100.0 - sum(v for k, v in mix.items() if k != "cash"))
    return sum(abs(mix.get(k, 0.0) - float(act["classes"].get(k, 0.0))) for k in ("equity", "gold", "international", "cash"))


def pit_check(env: "Env", c: Check, days: list) -> None:
    """Point in time (rule 1): the state the loop sees at the close of D is the same with the later closes in the store as without them. The later rows are deleted inside a transaction
    that is rolled back, the state is built again, and everything the policy reads from prices (volatilities, the fall gauge, the weights) is compared."""
    from pflab import core
    from pflab.core import state as st
    from pflab.paper import manager
    cur = env.cur()
    index = manager._index(env.data)
    for d in days:
        try:
            a = st.build(cur, d, env.data, index, core.settings())
            cur.execute("BEGIN")
            try:
                cur.execute("DELETE FROM prices WHERE date > ?", [d])
                b = st.build(cur, d, env.data, index, core.settings())
            finally:
                cur.execute("ROLLBACK")
        except Exception as e:
            c.ok(False, f"the point-in-time check could not build the state at {d}: {type(e).__name__}: {str(e)[:160]}", "core/state.py")
            continue
        same_vol = a["vol"] == b["vol"]
        same_gauge = a["gauge"] == b["gauge"]
        same_rows = [(r["isin"], r["price"], r["value"]) for r in a["rows"]] == [(r["isin"], r["price"], r["value"]) for r in b["rows"]]
        c.ok(same_vol and same_gauge and same_rows, f"point in time: the state at the close of {d} is the same with and without the later closes (volatilities {same_vol}, gauge {same_gauge}, prices and values {same_rows})", "core/state.py (a feature at date M uses only rows dated <= M)")


def month_cap_check(con, c: Check, sessions: list) -> None:
    """The monthly turnover cap (40% of the book) held in every calendar month of the run, by the money traded in paper_trades."""
    from pflab import core
    cap = float(core.settings()["rails"]["turnover_month"])
    months = sorted({(d.year, d.month) for d in sessions})
    bad = []
    for y, mth in months:
        traded = con.execute("SELECT coalesce(sum(t.qty * t.price), 0) FROM paper_trades t LEFT JOIN paper_decisions d ON d.decision_id = t.decision_id WHERE t.day >= ? AND t.day < ? AND coalesce(d.reason, '') NOT LIKE 'exit manager%' AND coalesce(d.reason, '') NOT LIKE 'session loop%'", [date(y, mth, 1), date(y + (mth == 12), mth % 12 + 1, 1)]).fetchone()[0]   # the rebalance's own flow: the exit manager's sales are not cut by the cap (but they are taken off the rebalance's room)
        v = con.execute("SELECT value FROM paper_days WHERE day >= ? AND day < ? ORDER BY day LIMIT 1", [date(y, mth, 1), date(y + (mth == 12), mth % 12 + 1, 1)]).fetchone()
        if v and traded > cap * float(v[0]) * 1.10:
            bad.append(f"{y}-{mth:02d}: Rs {traded:,.0f} traded, over {cap:.0%} of the book (Rs {float(v[0]):,.0f})")
    c.ok(not bad, f"the monthly turnover cap held in {len(months)} month(s): {bad}", "core/rails.py month_traded")


def _has_col(con, table: str, col: str) -> bool:
    return bool(con.execute("SELECT 1 FROM information_schema.columns WHERE table_name=? AND column_name=?", [table, col]).fetchone())


def rails_check(con, c: Check, first: date, last: date) -> None:
    """Every marked day between `first` and `last`: no company over 10% (unless it was over at the start and not bought), no ETF over 35%, no sector over 25%, no negative cash,
    no negative quantity, no more than 10% of the book traded in a day. A number by code from paper_days and the trades."""
    from pflab.paper import book, rails
    days = con.execute("SELECT day, value, cash, holdings_json FROM paper_days WHERE day >= ? AND day <= ? ORDER BY day", [first, last]).fetchall()
    bad: List[str] = []
    start_w: Dict[str, float] = {}
    start_sec: Dict[str, float] = {}
    bought = {(r[0], r[1]) for r in con.execute("SELECT day, isin FROM paper_trades WHERE side='buy'").fetchall()}          # a rail is judged on a day the name was BOUGHT: a price that drifts over it is not a breach
    for i, (d, v, cash, pj) in enumerate(days):
        pos = json.loads(pj or "{}")
        sec: Dict[str, float] = {}
        sec_bought: set = set()
        for isin, q in pos.items():
            px = book.close_on(con, isin, d)
            m = book.inst(con, isin)
            if q < -1e-9:
                bad.append(f"{d}: {m['symbol']} quantity {q} (a short position)")
            w = (q * px[1] / v) if px and v else 0.0
            if i == 0:
                start_w[isin] = w
            lim = rails.MAX_ETF if m["asset_class"] == "etf" else rails.MAX_STOCK
            if m["asset_class"] in book.BUYABLE and w > lim + 0.003 and w > start_w.get(isin, 0.0) + 0.003 and (d, isin) in bought:
                bad.append(f"{d}: {m['symbol']} is {w:.1%}, over its {lim:.0%} rail and above where it started")
            if m["sector"] and m["asset_class"] != "etf":
                sec[m["sector"]] = sec.get(m["sector"], 0.0) + w
                if (d, isin) in bought:
                    sec_bought.add(m["sector"])
        if i == 0:
            start_sec = dict(sec)
        for s, w in sec.items():
            if w > rails.MAX_SECTOR + 0.003 and w > start_sec.get(s, 0.0) + 0.003 and s in sec_bought:
                bad.append(f"{d}: sector {s} is {w:.1%}, over {rails.MAX_SECTOR:.0%} and above where it started")
        if cash < -1.0:
            bad.append(f"{d}: cash is Rs {cash:,.0f} (borrowing)")
    for d, v, ex in con.execute("SELECT t.day, sum(t.qty * t.price), sum(t.qty * t.price) FILTER (WHERE coalesce(d.reason, '') LIKE 'exit manager%' OR coalesce(d.reason, '') LIKE 'session loop%') "
                                "FROM paper_trades t LEFT JOIN paper_decisions d ON d.decision_id = t.decision_id WHERE t.day >= ? AND t.day <= ? GROUP BY 1 ORDER BY 1", [first, last]).fetchall():
        val = con.execute("SELECT value FROM paper_days WHERE day=?", [d]).fetchone()
        if val and (v - float(ex or 0.0)) > 0.10 * float(val[0]) * 1.08:         # the REBALANCE's own flow is held to the cap; the exit manager's orders (harvesting has its own share limit) are not cut by it
            bad.append(f"{d}: Rs {v:,.0f} traded, over 10% of the book (Rs {float(val[0]):,.0f})")
    c.ok(not bad, f"the rails held on {len(days)} marked days (company 10%, ETF 35%, sector 25%, no borrowing, no short, turnover 10% a day): {bad[:4]}", "core/rails.py, paper/rails.py")


# --- smoke --------------------------------------------------------------------------------------------------------------------------------

TODAY_ENDPOINTS = ("/api/health", "/api/command", "/api/portfolio", "/api/core", "/api/paper", "/api/world", "/api/system", "/api/schedule", "/api/watchlist", "/api/release",
                   "/api/learner/ideas", "/api/investigations", "/api/assistant", "/api/selfcheck", "/api/settings", "/api/policy", "/api/hq", "/api/research", "/api/twin")


@drill("smoke", 8)
def drill_smoke(env: "Env", c: Check) -> None:
    """The world builds, a close loop runs on the synthetic profile, the Today screen's data endpoints answer."""
    from pflab.service import jobs, telegram
    c.note(f"registry: {len(jobs.REGISTRY)} jobs; {len(env.real_jobs) - len(jobs.REGISTRY)} difference after the fakes")
    c.ok(not env.exceptions, f"every job module imports ({env.exceptions[:2]})", "service/tasks*.py")
    for j in ("core_loop", "paper", "catch_up", "story_daily", "lab_close", "strategist", "kite_token", "voice"):
        c.ok(j in jobs.REGISTRY, f"job {j} is registered", "service/tasks_s79_*.py")
    env.open_app(dt(env.start, 6))
    r0 = env.step(dt(env.start, 7), hq=True)
    c.ok(not env.exceptions, f"one pre-open step ran without an exception ({len(r0['jobs'])} jobs due); the HQ round: {str(r0.get('hq'))[:100]}", "app/runtime.py")
    run_days(env, env.start, env.start)
    cur = env.cur()
    runs = core_rows(cur)
    from pflab import markets
    prev = markets.get("IN").previous_session(env.start)
    c.ok([r[0] for r in runs] == [prev, env.start], f"the close loop ran once for each close, the seed day's first: {[(str(r[0]), r[1], r[2]) for r in runs]}", "core/loop.py, service/tasks_s79_core.py")
    if runs:
        orders = [o for r in runs for o in json.loads(r[3] or "[]")]
        c.note(f"the loop placed {len(orders)} order(s): {[(o['symbol'], o['side'], o['rupees']) for o in orders][:6]}; last note: {str(runs[-1][4])[:160]}")
        n_dec = cur.execute("SELECT count(*) FROM paper_decisions").fetchone()[0]
        c.ok(n_dec == len(orders) == cur.execute("SELECT count(*) FROM paper_orders").fetchone()[0], f"one decision row and one paper order per order placed ({n_dec})", "core/loop.py _decision")
        c.ok(cur.execute("SELECT count(*) FROM core_cards_s80 WHERE day=?", [env.start]).fetchone()[0] == 1, "the book card was written", "core/card.py")
        c.ok(cur.execute("SELECT count(*) FROM paper_acts WHERE loop='core_loop' AND useful").fetchone()[0] >= 1, "the loop left an act (nothing is silent)", "core/loop.py")
    c.ok(cur.execute("SELECT count(*) FROM paper_days WHERE day=?", [env.start]).fetchone()[0] == 1, "the book was marked for the session", "paper/book.py mark")
    client = env.client()
    bad = []
    for ep in TODAY_ENDPOINTS:
        try:
            r = client.get(ep)
            body = r.json() if r.status_code == 200 else None
            if r.status_code != 200 or body is None:
                bad.append(f"{ep}: HTTP {r.status_code} {r.text[:120]}")
            elif ep == "/api/world" and body.get("errors"):
                bad.append(f"{ep}: sections failed {body['errors']}")
            elif ep == "/api/core" and body.get("left_out"):
                bad.append(f"{ep}: left out {body['left_out']}")
        except Exception as e:
            bad.append(f"{ep}: {type(e).__name__}: {str(e)[:120]}")
    c.ok(not bad, f"the Today screen's data endpoints answered ({len(TODAY_ENDPOINTS)}): {bad[:4]}", "app/server.py, core/screens.py, app/world.py")
    # the outbox: queued, held or sent, nothing leaves the PC
    n0 = cur.execute("SELECT count(*) FROM outbox").fetchone()[0]
    mid = telegram.enqueue(cur, "drill: smoke message", "test", dedup_key="drill:smoke", now=env.clock.t)
    again = telegram.enqueue(cur, "drill: smoke message", "test", dedup_key="drill:smoke", now=env.clock.t)
    out = telegram.flush(cur, _sender(env), env.clock.t)
    c.ok(mid is not None and again is None and out["sent"] >= 1 and "drill: smoke message" in env.tg.sent, f"the outbox queues once (dedup) and delivers through the fake transport ({out}); it held {n0} before", "service/telegram.py")
    jobs_not_failed(cur, c)
    clean(env, c)
    w = env.world()
    c.says(f"pulse: {w['pulse']['verdict']}")


def _sender(env: "Env"):
    from pflab.pm import secrets as sec
    from pflab.service import telegram
    s = sec.Secrets({"telegram": {"token": "fake-token-1", "chat_id": "1"}})
    return telegram.make_sender(s, transport=env.tg, sleep=lambda x: None)


# --- the accelerated run, with pluggable steps ----------------------------------------------------------------------------------------------

def step_main_assertions(env: "Env", c: Check, phase: str) -> None:
    """The standing assertions of the accelerated run (always on): the book trades toward its target, the card is written each close, the rails hold, scoring registers."""
    if phase != "check":
        return
    from pflab import markets
    m = markets.get("IN")
    cur = env.cur()
    seed = m.previous_session(env.start)
    sessions = m.sessions_between(seed, env.clock.t.date())                      # the seed day's close is the loop's first
    sessions = [d for d in sessions if d <= available_through(env.clock.t)]
    rows = core_rows(cur)
    days = [r[0] for r in rows]
    c.ok(days == sorted(set(days)) and set(days) == set(sessions), f"one close-loop row per session, in order: {len(days)} rows for {len(sessions)} sessions (missing {sorted(set(sessions) - set(days))}, extra {sorted(set(days) - set(sessions))})", "core/loop.py, service/ondemand.py")
    marked = [r[0] for r in cur.execute("SELECT day FROM paper_days WHERE day >= ? ORDER BY day", [seed]).fetchall()]
    c.ok(marked == sessions, f"the book was marked on every session once (missing {sorted(set(sessions) - set(marked))})", "paper/book.py catch_up")
    cards = {r[0] for r in cur.execute("SELECT day FROM core_cards_s80").fetchall()}
    c.ok(cards >= set(days), f"the book card was written at each close ({len(cards)} cards for {len(days)} closes)", "core/card.py")
    acts = cur.execute("SELECT count(*) FROM paper_acts WHERE loop='core_loop'").fetchone()[0]
    c.ok(acts >= len(days), f"each close left an act ({acts} acts for {len(days)} closes)", "core/loop.py")
    n_dec = cur.execute("SELECT count(*) FROM paper_decisions").fetchone()[0]
    n_ord = cur.execute("SELECT count(*) FROM paper_orders").fetchone()[0]
    c.ok(n_dec == n_ord, f"every decision has exactly one order ({n_dec} decisions, {n_ord} orders)", "core/loop.py")
    stuck = cur.execute("SELECT count(*) FROM paper_orders WHERE status='open' AND CAST(placed_at AS DATE) < ?", [days[-1] if days else env.start]).fetchone()[0]
    c.ok(stuck == 0, f"no order older than the last close is still open ({stuck})", "paper/book.py fill")
    filled = cur.execute("SELECT count(*) FROM paper_orders WHERE status='filled'").fetchone()[0]
    c.ok(filled > 0 or n_ord == 0, f"orders fill at the next close ({filled} of {n_ord} filled)", "paper/book.py fill")
    first_t = cur.execute("SELECT classes_json, CAST(activated_at AS DATE) FROM system_allocation_s79 WHERE activated_at IS NOT NULL ORDER BY target_id LIMIT 1").fetchone()
    nxt_t = cur.execute("SELECT CAST(activated_at AS DATE) FROM system_allocation_s79 WHERE activated_at IS NOT NULL ORDER BY target_id OFFSET 1 LIMIT 1").fetchone()
    first_cls = json.loads(first_t[0]) if first_t else None                    # the book is measured against the FIRST target, on the days it was in force (an adoption mid-run, and the exit manager's sales, move the mix on purpose)
    gaps = [(d, class_gap(cur, d, first_cls)) for d in marked if nxt_t is None or nxt_t[0] is None or d < nxt_t[0]]
    gaps = [(d, g) for d, g in gaps if g is not None]
    strict = getattr(env, "n_active_steps", 1) <= 1                          # with the exit manager's sales and an adopted target in the run, the mix moves on purpose: then only "not diverging" is asked
    if len(gaps) >= 2:
        c.ok(gaps[-1][1] < gaps[0][1] - 0.5 if strict else gaps[-1][1] <= gaps[0][1] + 5.0, f"the book moved toward its allocation target: distance {gaps[0][1]:.1f} points on {gaps[0][0]} to {gaps[-1][1]:.1f} points on {gaps[-1][0]}", "core/policy.py, core/rails.py (the target is held by class)")
    else:
        c.note("no allocation target is active in this profile: the distance to it was not measured")
    rails_check(cur, c, env.start - timedelta(days=5), env.clock.t.date())
    pit_check(env, c, [d for d in (sessions[min(4, len(sessions) - 1)], sessions[max(0, len(sessions) - 3)]) if d < sessions[-1]])
    month_cap_check(cur, c, sessions)
    claims = cur.execute("SELECT count(*), count(*) FILTER (WHERE outcome IS NOT NULL) FROM paper_claims").fetchone()
    c.ok(claims[0] >= n_dec * 1 and claims[1] >= 1 if n_dec else True, f"scoring registered: {claims[0]} claims for {n_dec} decisions, {claims[1]} already scored by the 7-day horizon", "paper/manager.py register, score_due")
    api = cur.execute("SELECT count(*) FROM api_calls WHERE status IN ('done','submitted','running','sending')").fetchone()[0]
    c.ok(api == 0, f"no paid call was made ({api})", "hq/governor.py, guard.py")
    jobs_not_failed(cur, c)


def jobs_not_failed(cur, c: Check) -> None:
    """No job recorded 'failed' for a reason that is not a lost network (each distinct failure is named with its first words)."""
    from pflab.service import jobs
    bad = cur.execute("SELECT job, detail FROM job_runs WHERE status='failed' AND detail NOT LIKE 'abandoned%' ORDER BY run_id").fetchall()
    real_bad = [(j, d) for j, d in bad if not jobs.offline(d or "")]
    seen = set()
    uniq = [(j, (d or "")[:160]) for j, d in real_bad if not (j in seen or seen.add(j))]
    c.ok(not real_bad, f"no job recorded failed for a reason that is not the network: {uniq[:6]} ({len(real_bad)} runs)", "service/jobs.py run_job: the job named in the evidence")


def _src_has(mod: str, *words: str) -> bool:
    s = source_of(mod)
    return bool(s) and all(w in s for w in words)


def step_tactical_view(env: "Env", c: Check, phase: str) -> None:
    """The tactical lane (v2, already in the tree): a view issued on the second session's afternoon is executed at the NEXT close through the rails, and scored against the Nifty 500 at
    its horizon (3 sessions)."""
    from pflab import markets
    from pflab.core import views
    m = markets.get("IN")
    fri = m.next_session(env.start)
    name, isin = STOCKS[4][0], STOCKS[4][1]                          # SYNBANK1: in the store, not in the book
    if phase == "tick":
        if getattr(env, "view_id", None) or env.clock.t < dt(fri, 16):
            return
        r = views.issue(env.cur(), env.clock.t, fri, direction=1, names=[name], share_of_budget=0.5, horizon_sessions=3, stop_pct=25.0,
                        reason="drill: a story says the banks lead the next leg up, so buy a little of the one the book does not hold")
        env.view_issue = r
        env.view_id = r.get("view_id") or -1
        return
    if phase != "check":
        return
    cur = env.cur()
    c.ok(getattr(env, "view_id", -1) > 0, f"the view was issued: {str(getattr(env, 'view_issue', ''))[:200]}", "core/views.py issue")
    nxt = m.next_session(fri)
    note = cur.execute("SELECT note, orders_json FROM core_runs_s80 WHERE day=?", [nxt]).fetchone()
    c.ok(note is not None and "tactical views merged" in (note[0] or ""), f"at the next close ({nxt}) the view was merged into the targets: {str(note[0])[:140] if note else None}", "core/loop.py, core/views.py merge")
    buys = cur.execute("SELECT count(*) FROM paper_decisions WHERE isin=? AND action IN ('BUY','ADD')", [isin]).fetchone()[0]
    filled = cur.execute("SELECT count(*) FROM paper_trades WHERE isin=? AND side='buy'", [isin]).fetchone()[0]
    c.ok(buys >= 1 and filled >= 1, f"{name} was bought through the rails for the view ({buys} decision(s), {filled} fill(s))", "core/loop.py, core/rails.py")
    v = cur.execute("SELECT status, outcome, scored_at, due_on FROM core_views_s80 WHERE view_id=?", [env.view_id]).fetchone()
    c.ok(v is not None and v[1] in ("good", "bad") and v[2] is not None, f"at its horizon ({v[3] if v else None}) the view was scored against the Nifty 500: {v[1] if v else None}", "core/views.py score_due")


def step_allocation(env: "Env", c: Check, phase: str) -> None:
    """The strategist's tool proposes an allocation on the second afternoon; code checks it, stores it as lab policy `alloc_t<id>` and adopts it by the A50 rule; the loop then holds the new target.
    The lab's 2005-2017 replay needs Docker and the real panel, so the history scores the A50 rule reads are written by the drill (labelled); the proposal check, the storing, the rule and
    the adoption are the real code (`lab/alloc_lab.tick(run_final=False)`: the once-only 2018-2021 check is the lab's own)."""
    if phase == "setup":
        env.alloc0 = env.cur().execute("SELECT max(target_id) FROM system_allocation_s79").fetchone()[0]
        return
    if phase == "tick":
        from pflab import markets
        if getattr(env, "alloc_done", False) or env.clock.t < dt(markets.get("IN").next_session(env.start), 16):
            return
        env.alloc_done = True
        from pflab.lab import alloc_lab, tools as lt
        cur = env.cur()
        ctx = lt.make_ctx(cur, env.pm, env.data, env.clock.t, None)
        text, is_err = lt.run(ctx, "propose_allocation", {"classes": {"equity": 50, "gold": 15, "international": 10, "cash": 25}, "sleeves": {"core": 60, "longterm": 40},
                                                          "sectors": {}, "reasons": "The drill's strategist wants more cash and less gold while the book is far from its target: hold half in shares, some gold and international, a quarter in cash."})
        env.alloc_proposal = (text, is_err)
        if is_err:
            return
        pid = json.loads(text).get("variant")
        alloc_lab.seed(cur, env.pm, env.clock.t)

        def score(cagr):
            return {"cagr_liq": cagr, "bench_cagr_liq": 0.10, "max_drawdown": -0.30, "bench_max_drawdown_net": -0.35, "n_obs": 3000, "skew": 0.0, "kurt": 3.0,
                    "sharpe_daily": 0.05, "dsr": 0.95, "cagr": cagr, "bench_cagr": 0.10, "excess_cagr": cagr - 0.10, "sharpe": 0.8}
        for p, cagr in ((alloc_lab.INDEX_HOLD, 0.095), (alloc_lab.DEFAULT_ID, 0.101), (pid, 0.109)):
            rid = cur.execute("SELECT coalesce(max(run_id), 0) + 1 FROM lab_runs_s80").fetchone()[0]
            cur.execute("INSERT INTO lab_runs_s80 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [rid, p, "history", "{}", env.clock.t, None, json.dumps(score(cagr)), "{}", "{}", 0.95, 0.05, 3, 0.0, False])
        env.alloc_tick = alloc_lab.tick(cur, env.pm, env.data, env.clock.t, run_final=False)
        return
    cur = env.cur()
    text, is_err = getattr(env, "alloc_proposal", ("", True))
    c.ok(not is_err, f"the strategist's tool took the proposal: {text[:220]}", "lab/tools.py propose_allocation, lab/alloc_lab.py propose")
    n = cur.execute("SELECT count(*), count(*) FILTER (WHERE status='active') FROM system_allocation_s79 WHERE target_id > ?", [env.alloc0 or 0]).fetchone()
    c.ok(n[0] >= 1, f"the proposal was stored as a new target ({n[0]} new target rows)", "lab/alloc_lab.py")
    c.ok(n[1] >= 1, f"it was adopted by the A50 rule and is the active target ({n[1]} active): {str(getattr(env, 'alloc_tick', {}).get('verdicts'))[:160]}", "lab/alloc_lab.py tick")
    v = cur.execute("SELECT outcome FROM alloc_verdicts_s81 ORDER BY verdict_id DESC LIMIT 1").fetchone()
    c.ok(v is not None and v[0] == "adopted", f"the verdict is on record with its figures ({v})", "lab/alloc_lab.py _verdict")
    row = cur.execute("SELECT target_id, classes_json, reasons FROM system_allocation_s79 WHERE status='active' ORDER BY target_id DESC LIMIT 1").fetchone()
    c.ok(row is not None and row[0] > (env.alloc0 or 0) and len(row[2]) >= 40, f"the active target carries its classes and reasons ({row[1] if row else None})", "paper/allocation.py")
    runs = cur.execute("SELECT count(*) FROM core_runs_s80 WHERE json_extract_string(state_json, '$.target_id') = ?", [str(row[0]) if row else "0"]).fetchone()[0]
    c.ok(runs >= 1, f"the close loop held the adopted target at later closes ({runs} run(s) cite it)", "core/state.py, core/loop.py")


step_allocation.ticks = True


def step_core_etf_bought(env: "Env", c: Check, phase: str) -> None:
    """The book buys a core ETF it did not hold (baseline_v2): JUNIORBEES (in the store, not in the book), inside the ETF rail, sleeve 'core'."""
    if phase != "check":
        return
    cur = env.cur()
    unheld = [e[1] for e in ETFS if not e[7]]                      # the synthetic Nifty 50 ETF is in the store with prices but not in the book
    ph = ",".join("?" for _ in unheld)
    bought = cur.execute(f"SELECT t.day, t.symbol, t.qty, t.price FROM paper_trades t WHERE t.side='buy' AND t.isin IN ({ph})", unheld).fetchall()
    c.ok(bool(bought), f"a core ETF the book did not hold at the start was bought: {[(str(r[0]), r[1], r[2]) for r in bought][:3]}", "core/baseline_v2.py, core/rails.py")
    sleeves_mod = importlib.import_module("pflab.core.sleeves")
    if bought:
        isin = cur.execute("SELECT isin FROM instruments WHERE symbol=?", [bought[0][1]]).fetchone()[0]
        c.ok(sleeves_mod.sleeve_of(cur, isin, "IN") == "core", f"{bought[0][1]} is in the core sleeve", "core/sleeves.py sleeve_of")


def step_exit_plan(env: "Env", c: Check, phase: str) -> None:
    """An exit plan fires: a held share falls through its stop and the exit manager orders the sale at the close."""
    ex = importlib.import_module("pflab.core.exits")
    victim = STOCKS[1][1]
    if phase == "setup":
        # a 45% fall in SYNFMCG2 on the third session: the held-back closes of the following sessions are lowered
        import pandas as pd
        p = env.dir / "held_prices.parquet"
        h = pd.read_parquet(p)
        h["date"] = pd.to_datetime(h["date"]).dt.date
        from pflab import markets
        third = markets.get("IN").session_after(env.start, 2)
        h.loc[(h["isin"] == victim) & (h["date"] >= third), "close"] *= 0.55
        h.to_parquet(p)
        env.exit_day = third
        return
    cur = env.cur()
    wired = _src_has("pflab.core.loop", "exits")
    if not wired:
        c.ok(False, f"pflab.core.exits exists ({[n for n in dir(ex) if n in ('open_plan', 'check_close', 'check_quote', 'check_thesis')]}) but pflab.core.loop never calls it: the stop on {STOCKS[1][0]} after its 45% fall could not fire", "core/loop.py (the coordinator wires the exit manager in the loop)")
        return
    plan = cur.execute("SELECT plan_id, stop, status, closed_reason FROM exit_plans_s81 WHERE isin=? ORDER BY plan_id DESC LIMIT 1", [victim]).fetchone()
    c.ok(plan is not None, f"{STOCKS[1][0]} has an exit plan (stop {plan[1] if plan else None})", "core/exits.py backfill_plans / open_plan")
    ev = cur.execute("SELECT kind, status, day, reason FROM exit_events_s81 WHERE isin=? AND side='sell' AND kind='stop' ORDER BY event_id", [victim]).fetchall()
    c.ok(len(ev) == 1, f"the stop fired once and only once after the fall on {env.exit_day}: {[(r[0], r[1], str(r[2])) for r in ev]}", "core/exits.py check_close")
    sold = cur.execute("SELECT count(*) FROM paper_decisions WHERE isin=? AND action IN ('SELL','REDUCE')", [victim]).fetchone()[0]
    c.ok(sold >= 1, f"a sale decision for {STOCKS[1][0]} was placed by the loop with the exit's reason ({ev[0][3][:100] if ev else ''})", "core/loop.py")
    held = cur.execute("SELECT count(*) FROM paper_trades WHERE isin=? AND side='sell'", [victim]).fetchone()[0]
    c.ok(held >= 1, f"the sale filled at the next close ({held} sell trade(s))", "paper/book.py fill")


def step_harvest(env: "Env", c: Check, phase: str) -> None:
    """A harvesting sale and its buy-back: long-term gains booked up to the exemption, then the same name bought again at a reset cost."""
    if phase != "check":
        return
    cur = env.cur()
    if not cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name='exit_events_s81'").fetchone():
        c.off("pflab.core.exits exists but the exit_events_s81 table is not in this store (migration 114)")
        return
    sells = cur.execute("SELECT event_id, isin, day, status, reason FROM exit_events_s81 WHERE kind='harvest' AND side='sell' ORDER BY event_id").fetchall()
    if not sells:
        c.off("no harvesting sale was decided in these ten sessions (the synthetic long-term gains, about Rs 92,000, and the off-quarter share of the exemption did not call for one, or the loop does not call the exit manager yet): see the exit manager's own tests")
        return
    isin = sells[0][1]
    buys = cur.execute("SELECT event_id, day, status FROM exit_events_s81 WHERE kind='harvest' AND side='buy' AND isin=? ORDER BY event_id", [isin]).fetchall()
    c.ok(len(buys) >= 1, f"the harvesting sale on {sells[0][2]} was followed by a buy-back event ({[(str(b[1]), b[2]) for b in buys]})", "core/exits.py _rebuys")
    trades = cur.execute("SELECT side, day, qty, price FROM paper_trades WHERE isin=? AND side IN ('sell','buy') ORDER BY trade_id", [isin]).fetchall()
    sd = [t[1] for t in trades if t[0] == "sell"]
    bd = [t[1] for t in trades if t[0] == "buy" and sd and t[1] > sd[0]]
    c.ok(bool(sd) and bool(bd) and sd[0] < bd[0], f"the sale filled on {sd[:1]} and the buy-back on {bd[:1]}: never the same session (A54: speculative income)", "core/harvest.py")
    plan = cur.execute("SELECT entry_price, status, note FROM exit_plans_s81 WHERE isin=? ORDER BY plan_id DESC LIMIT 1", [isin]).fetchone()
    c.ok(plan is not None and plan[1] in ("open", "closed", "rebuy_pending"), f"the position has a plan after the buy-back: {plan[0] if plan else None} {plan[1] if plan else None} ({str(plan[2])[:100] if plan else ''})", "core/exits.py open_plan")
    new_lot = cur.execute("SELECT count(*) FROM lots WHERE account_id='SYSBROKER' AND isin=? AND acq_date >= ?", [isin, bd[0] if bd else date.max]).fetchone()[0]
    c.ok(new_lot >= 1, f"the buy-back is a NEW lot dated {bd[:1]}: the cost price is reset to that day's price ({new_lot} lot(s) since)", "paper/book.py, core/harvest.py")
    sc = cur.execute("SELECT count(*) FROM exit_scores_s81 WHERE isin=?", [isin]).fetchone()[0]
    c.note(f"scores registered for the harvest sale: {sc} (20 and 60 sessions after the sale; due later than this run)")


def step_view_entry(env: "Env", c: Check, phase: str) -> None:
    """A position the session carried in on a tactical view (the swing sleeve is deleted, A60), given its exit plan after the fill, closed by that plan the next session and scored later."""
    if phase != "check":
        return
    info = getattr(env, "replay_info", None)
    if not info:
        c.off("this step reads the view entry the session replay step opens and closes: waiting for module pflab.core.session (the replay step did not run)")
        return
    cur = env.cur()
    isin = info["entry_isin"]
    plan = cur.execute("SELECT plan_id, sleeve, status, closed_reason, stop, target FROM exit_plans_s81 WHERE isin=? ORDER BY plan_id DESC LIMIT 1", [isin]).fetchone()
    c.ok(plan is not None and plan[1] == "longterm" and plan[4] is not None, f"the view entry has an exit plan in the longterm sleeve (stop {plan[4] if plan else None}, target {plan[5] if plan else None})", "core/exits.py open_plan")
    c.ok(plan is not None and plan[2] == "closed", f"the plan closed with the exit ({plan[2] if plan else None}: {plan[3] if plan else None})", "core/exits.py")
    from pflab.core import sleeves
    c.ok(sleeves.sleeve_of(cur, isin, "IN") in sleeves.SLEEVES and "swing" not in sleeves.SLEEVES, f"{info['entry']} is recorded in a live sleeve ({sleeves.sleeve_of(cur, isin, 'IN')}); there is no swing sleeve", "core/sleeves.py")
    n = cur.execute("SELECT count(*) FROM exit_scores_s81 WHERE isin=?", [isin]).fetchone()[0]
    c.note(f"scores registered for the exit sale so far: {n} (a sale is scored against holding the same money at 20 and 60 sessions: not due inside this run)")


def step_thesis_break(env: "Env", c: Check, phase: str) -> None:
    """A thesis-break sale from a graph event: a filing event on a held name reaches the exit manager and the name is sold."""
    ev = importlib.import_module("pflab.kg.events")
    ex = importlib.import_module("pflab.core.exits")
    victim = STOCKS[2][1]
    if phase == "tick":
        # the filing is released on the second session, in the afternoon: it enters the graph's table only then (point in time), with its dissemination time
        if getattr(env, "thesis_done", False):
            return
        from pflab import markets
        fri = markets.get("IN").next_session(env.start)
        if env.clock.t < dt(fri, 16):
            return
        cur = env.cur()
        if not cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name='kg2_event'").fetchone():
            c.off("pflab.kg.events exists but the kg2_event table is not in this store (the graph's migration 126)")
            env.thesis_done = True
            return
        ts = dt(fri, 15, 10)
        cur.execute("INSERT INTO kg2_event (event_id, isin, source, ref, ts, event_date, kind, severity, headline, link_rule, link_proof, dedupe_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ["drill-thesis-1", victim, "bse_announcement", "drill:bse:1", ts, fri, "guidance_cut", "high", "SYNIT1 cuts its revenue guidance for the year and a large client leaves (drill)",
                     "isin_in_filing", "drill: the filing names the ISIN", "drill:thesis:1"])
        env.thesis_done = True
        return
    if phase != "check":
        return
    cur = env.cur()
    wired = _src_has("pflab.core.loop", "_thesis_events")
    if not wired:
        c.ok(False, f"pflab.kg.events and pflab.core.exits exist ({hasattr(ev, 'material_events')}, {hasattr(ex, 'check_thesis')}) but pflab.core.loop never calls check_thesis: a thesis break cannot become a sale", "core/loop.py")
        return
    if not getattr(env, "thesis_done", False):
        c.off("the thesis event was not injected (see its tick)")
        return
    e = cur.execute("SELECT kind, status, day, reason FROM exit_events_s81 WHERE isin=? AND kind='thesis' ORDER BY event_id", [victim]).fetchall()
    c.ok(len(e) == 1, f"the graph event led to one thesis exit on {STOCKS[2][0]}: {[(r[0], r[1], str(r[2])) for r in e]}", "kg/events.py, core/exits.py check_thesis, core/loop.py")
    n = cur.execute("SELECT count(*) FROM paper_decisions WHERE isin=? AND action IN ('SELL','REDUCE') AND lower(reason) LIKE '%thesis%'", [victim]).fetchone()[0]
    c.ok(n >= 1, f"the sale decision names the thesis break and its source ({n} decision(s); reason: {e[0][3][:120] if e else ''})", "core/exits.py")
    c.ok(e and "guidance" in e[0][3].lower(), "the reason (written by code) names the event's kind and its date", "core/exits.py")
step_thesis_break.ticks = True
step_tactical_view.ticks = True


def step_us_book(env: "Env", c: Check, phase: str) -> None:
    """A US sub-book close: the loop runs with market='US' on the US calendar and leaves its own core_runs row."""
    if phase != "check":
        return
    cur = env.cur()
    if not cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name='us_runs_s81'").fetchone():
        c.off("pflab.us exists but the us_runs_s81 table is not in this store (migration 134)")
        return
    wired = any(_src_has(m, "close_us") for m in ("pflab.core.loop", "pflab.service.tasks_s79_core", "pflab.service.tasks_s79_us"))
    n = cur.execute("SELECT count(*) FROM us_runs_s81").fetchone()[0]
    if not wired and n == 0:
        c.ok(False, "pflab.us.adapter.close_us exists but nothing in the close loop or the jobs calls it: the US sub-book never closes", "core/loop.py or a job (the coordinator wires it)")
        return
    c.ok(n >= 1, f"the US sub-book closed {n} US session(s)", "us/adapter.py close_us")
    rows = cur.execute("SELECT day, status, note FROM us_runs_s81 ORDER BY day").fetchall()
    days = [r[0] for r in rows]
    from pflab import markets
    us = markets.get("US")
    c.ok(days == sorted(set(days)) and all(us.is_session(d) for d in days), f"one run per US session, on the US calendar: {[str(d) for d in days]}", "us/adapter.py, conductor/us_calendar.py")
    c.note(f"US runs: {[(str(r[0]), r[1], str(r[2])[:60]) for r in rows][:4]}")
    d = cur.execute("SELECT count(*), count(*) FILTER (WHERE fx_source IS NOT NULL AND fx_rate > 0) FROM us_days_s81").fetchone()
    c.ok(d[0] == d[1], f"every US day marked carries its FX rate and its source ({d[1]} of {d[0]})", "us/book.py mark")


def step_session_replay(env: "Env", c: Check, phase: str) -> None:
    """A replayed market day through core/session.py: recorded minute bars through the same code as the live session loop."""
    if phase != "check":
        return
    import numpy as np
    import pandas as pd
    from pflab import markets
    from pflab.core import session
    from pflab.paper import book
    if not callable(getattr(session, "replay", None)):
        c.off("pflab.core.session exists but offers no replay() (the replay of recorded minute bars through the session loop)")
        return
    m = markets.get("IN")
    cur = env.cur()
    last = cur.execute("SELECT max(day) FROM paper_days").fetchone()[0]
    day = m.next_session(last)
    held = {i: q for i, q in book.positions(cur).items() if i in {s[1] for s in STOCKS} and q > 0}
    victims = {STOCKS[1][1], STOCKS[2][1]}                       # names another step may have sold on purpose
    harvested = {r[0] for r in cur.execute("SELECT DISTINCT isin FROM exit_events_s81 WHERE kind='harvest'").fetchall()} if module_exists("pflab.core.exits") else set()     # a harvested name is waiting on its buy-back plan
    free = [i for i in held if i not in victims and i not in harvested] or [i for i in held if i not in victims]
    swing_isin = STOCKS[5][1]                                    # SYNAUTO1: in the store, not in the book (SYNBANK1 is the first tactical view's); a second view brings it in (the name is kept from the old swing drill)
    if len(free) < 2:                                            # the earlier steps sold what they were for: the replay is given two fresh positions (paper buys at the last close, in the system's own ledger)
        from pflab.ledger import events as ev, system
        for s in (STOCKS[0], STOCKS[3], STOCKS[4]):
            if s[1] in free or s[1] in victims or len(free) >= 2:
                continue
            p0 = book.close_on(cur, s[1], last)
            if p0 is None:
                continue
            system.append(cur, [ev.Event(kind="buy", account_id=system.SYSBROKER, date=last, isin=s[1], qty=40.0, price=p0[1], ref=f"sys:drill:replay:{s[0]}", tax_class="EQUITY")], dt(last, 21, 45))
            free.append(s[1])
            held[s[1]] = 40.0
    if len(free) < 2 or book.close_on(cur, swing_isin, last) is None:
        c.off(f"the book holds {len(free)} share(s) the replay can use (it needs two held names and one unheld name with a price)")
        return
    stop_isin, thesis_isin = free[0], free[1]
    sym = {i: cur.execute("SELECT symbol FROM instruments WHERE isin=?", [i]).fetchone()[0] for i in (stop_isin, thesis_isin, swing_isin)}
    px = {i: book.close_on(cur, i, last)[1] for i in sym}
    bars_root = env.dir / "bars"

    def minute_bars(price, vol=10000.0):
        ts = pd.date_range(datetime.combine(day, datetime.min.time()).replace(hour=9, minute=15), periods=360, freq="min")
        close = np.array([price(i) for i in range(360)], dtype=float)
        open_ = np.concatenate([[close[0]], close[:-1]])
        return pd.DataFrame({"ts": ts, "open": open_, "high": np.maximum(open_, close) + 0.05, "low": np.minimum(open_, close) - 0.05, "close": close, "volume": float(vol)})

    day2 = m.next_session(day)

    def write(isin, fn, fn2=None):
        hist = [minute_bars(lambda i, b=px[isin]: b) .assign(ts=lambda d, k=k: d["ts"] - pd.Timedelta(days=k)) for k in range(1, 23)]          # 22 earlier flat days: the liquidity model's input
        (bars_root / "IN").mkdir(parents=True, exist_ok=True)
        more = [minute_bars(fn2).assign(ts=lambda d: d["ts"] + pd.Timedelta(days=(day2 - day).days))] if fn2 else []
        pd.concat(hist + [minute_bars(fn)] + more, ignore_index=True).to_parquet(bars_root / "IN" / f"{sym[isin]}.parquet", index=False)
    now0 = dt(last, 21, 40)
    if module_exists("pflab.core.exits"):                        # the long-term plans of the two held names: a stop 8% down for one, the default levels (with the thesis-break kinds) for the other
        from pflab.core import exits as _ex
        _ex.open_plan(cur, now0, "IN", stop_isin, "longterm", px[stop_isin], held[stop_isin], {"stop": px[stop_isin] * 0.92, "target": px[stop_isin] * 1.6})
        _ex.open_plan(cur, now0, "IN", thesis_isin, "longterm", px[thesis_isin], held[thesis_isin])
    else:
        c.off("pflab.core.exits is missing: no plan can be opened for the replay")
        return
    write(stop_isin, lambda i: px[stop_isin] if i < 105 else px[stop_isin] * 0.90)                                  # the 11:00 minute closes below the stop
    from pflab.core import views as _views
    vw = _views.issue(cur, now0, last, direction=1, names=[STOCKS[5][0]], share_of_budget=0.4, horizon_sessions=10, stop_pct=25.0,
                      reason="drill: the replayed day carries a second tactical view in, on a name the book does not hold")
    if not vw.get("ok"):
        c.off(f"the tactical view the replay needs could not be issued: {str(vw)[:160]}")
        return

    def open_entry_plan(t, res):                                 # the session no longer opens plans: the exit manager's own function does, right after the fill (stop 5% down, target 10% up)
        if not entry_plan and any(f["kind"] == "view" and f["side"] == "buy" for f in res.get("fills", [])):
            f = [x for x in res["fills"] if x["kind"] == "view"][0]
            entry_plan.append(_ex.open_plan(cur, t, "IN", swing_isin, "longterm", f["price"], f["qty"], {"stop": px[swing_isin] * 0.95, "target": px[swing_isin] * 1.10}))
    entry_plan: list = []
    write(swing_isin, lambda i: px[swing_isin] if i < 3 else (px[swing_isin] * 1.015 if i < 200 else px[swing_isin] * 1.12),      # flat near VWAP, then through its target at 12:35
          lambda i: px[swing_isin] * 1.12)                                                                                       # the next session: it stays there, and the held exit goes through at the open
    write(thesis_isin, lambda i: px[thesis_isin])
    ev = [{"isin": thesis_isin, "kind": "guidance_cut", "severity": "high", "ts": datetime.combine(day, datetime.min.time()).replace(hour=13, minute=20), "source": "bse_announcement",
           "ref": "drill:replay:1", "text": "the company cuts its revenue guidance and a large client leaves (drill)"}]
    n0 = cur.execute("SELECT count(*) FROM paper_orders").fetchone()[0]
    r = session.replay(cur, day, bars_root, isins=list(sym), events=ev, data_root=env.data, on_step=open_entry_plan)
    c.ok(r["steps"] > 50 and r["names"] == 3, f"the replayed day {day} ran {r['steps']} session checks over {r['names']} names", "core/session.py replay")
    fl = cur.execute("SELECT ts, symbol, side, qty, quote, price, half_spread_bps, slippage_bps, kind, flag FROM session_fills_s81 WHERE day=? ORDER BY fill_id", [day]).fetchall()
    c.note("fills: " + "; ".join(f"{f[0]:%H:%M} {f[2]} {f[1]} {f[8]} q{f[4]:.2f} p{f[5]:.2f}" for f in fl[:8]))
    stop = [f for f in fl if f[1] == sym[stop_isin] and f[8] == "stop"]
    c.ok(len(stop) == 1 and stop[0][2] == "sell" and stop[0][5] < stop[0][4] and stop[0][0].time() >= dt(day, 11, 0).time(), f"a stop hit mid-session on {sym[stop_isin]} was filled at the replayed quote plus slippage, never better: {[(f'{f[0]:%H:%M}', f[4], f[5]) for f in stop]}", "core/session.py, core/fills.py")
    entry = [f for f in fl if f[1] == sym[swing_isin] and f[8] == "view"]
    c.ok(len(entry) == 1 and entry[0][2] == "buy" and entry[0][0].time() >= dt(day, 9, 30).time() and entry[0][5] > entry[0][4],
         f"the view entry was carried out only after the first 15 minutes, filled above the quote: {[(f'{f[0]:%H:%M}', f[4], f[5]) for f in entry]}", "core/session.py timing")
    out = [f for f in fl if f[1] == sym[swing_isin] and f[2] == "sell"]
    queued = cur.execute("SELECT count(*) FROM session_queue_s81 WHERE status='queued'").fetchone()[0]
    c.ok(not out, f"the same-day exit (its target was reached at 12:35) was not carried out on the day of entry (sells today {len(out)}; the exit manager waits for the next session, {queued} queued by the guard)", "core/fills.py the no-same-day-round-trip guard")
    th = [f for f in fl if f[1] == sym[thesis_isin] and f[8] == "thesis"]
    c.ok(len(th) == 1 and th[0][0].time() >= dt(day, 13, 20).time(), f"a filing released at 13:20 broke the thesis and {sym[thesis_isin]} was sold in the session, not before it: {[(f'{f[0]:%H:%M}', f[4], f[5]) for f in th]}", "core/session.py events, core/exits.py check_thesis")
    # the Kite login lost mid-session: said once, the loop goes on with what needs no quote
    class TokenException(Exception):
        pass

    class LostKite:
        def __getattr__(self, name):
            raise TokenException("Incorrect `api_key` or `access_token`.")
    a1 = session.run_once(cur, dt(day, 14, 30), kite=LostKite(), data_root=env.data)
    a2 = session.run_once(cur, dt(day, 14, 35), kite=LostKite(), data_root=env.data)
    said = cur.execute("SELECT count(*), max(text) FROM session_said_s81 WHERE day=? AND key='kite'", [day]).fetchone()
    c.ok(a1.get("degraded") and a2.get("degraded") and said[0] == 1 and "login" in str(said[1]).lower(), f"the Kite login lost mid-session is said once ({said[0]} message: {str(said[1])[:110]}) and the loop degrades, never crashes", "core/session.py say_once")
    n1 = cur.execute("SELECT count(*) FROM paper_orders").fetchone()[0]
    c.ok(n1 >= n0, f"the replay placed paper orders through the book ({n1 - n0})", "core/fills.py")
    # the next session: the exit that was held fires at its start (no round trip: the shares are now a day old)
    r2 = session.replay(cur, day2, bars_root, isins=[swing_isin], data_root=env.data)
    f2 = cur.execute("SELECT ts, symbol, side, qty, quote, price, kind FROM session_fills_s81 WHERE day=? AND symbol=? ORDER BY fill_id", [day2, sym[swing_isin]]).fetchall()
    c.ok(any(f[2] == "sell" for f in f2) and swing_isin not in book.positions(cur), f"the held exit went through on {day2}: {[(f'{f[0]:%H:%M}', f[2], f[6], f[5]) for f in f2]}; the position is closed", "core/session.py queue, core/fills.py")
    env.replay_info = {"day": day, "day2": day2, "entry_isin": swing_isin, "entry": sym[swing_isin]}
    rep = session.report_day(cur, day)
    c.ok("Filled" in rep and "Session" in rep, f"the 15:45 self-report names what fired and filled: {rep.splitlines()[0][:80]} ... {len(rep.splitlines())} lines", "core/session.py report_day")
    card = session.card(cur, dt(day, 15, 45))
    c.ok(card["runs"] >= 50 and card["fills"], f"the Today card shows {card['runs']} checks and {len(card['fills'])} fills", "core/session.py card")


ACCELERATED_STEPS: List[Tuple[str, Callable, Callable]] = [
    ("standing", step_main_assertions, lambda env=None: (True, "")),
    ("tactical_view_issued_executed_scored", step_tactical_view, needs("pflab.core.views", why="the tactical lane")),
    ("allocation_proposed_and_adopted", step_allocation,
     lambda env=None: (True, "") if "propose_allocation" in source_of("pflab.lab.tools") else (False, "waiting for the lab tool propose_allocation in pflab.lab.tools (B2)")),
    ("core_etfs_bought", step_core_etf_bought, needs("pflab.core.sleeves", "pflab.core.baseline_v2", why="B1 baseline_v2 + the sleeves contract")),
    ("exit_plan_fires", step_exit_plan, needs("pflab.core.exits", why="B4 exit manager")),
    ("harvest_sale_and_buyback", step_harvest, needs("pflab.core.exits", why="B4 exit manager: harvesting")),
    ("thesis_break_sale", step_thesis_break, needs("pflab.kg.events", "pflab.core.exits", why="B7 knowledge graph events + B4 exits")),
    ("us_subbook_close", step_us_book, needs("pflab.us.adapter", why="B8 phase B, the US sub-book")),
    ("session_replay", step_session_replay, needs("pflab.core.session", why="B6b session loop")),
    ("view_entry_exit_closed", step_view_entry, needs("pflab.core.session", "pflab.core.exits", "pflab.core.sleeves", why="B5/B6b: entries by the session loop's tactical views, exits and scores by the exit manager")),   # after the replay it reads
]


def run_accelerated(env: "Env", c: Check, steps: Optional[List[Tuple[str, Callable, Callable]]] = None, n_sessions: int = 10) -> None:
    """`n_sessions` sessions with the app open all the time (the weekend and the holiday inside), the loop run for real, then every step's check. A step that is not applicable
    is reported OFF with the module it waited for; a step that raises is reported ERROR for itself and never stops the others."""
    from pflab import markets
    steps = ACCELERATED_STEPS if steps is None else steps
    m = markets.get("IN")
    last = env.start
    for _ in range(n_sessions - 1):
        last = m.next_session(last)
    c.note(f"sessions simulated: {n_sessions}, {env.start} to {last} (the weekend and the holiday in between are days off the market)")
    active = []
    for name, fn, applicable in steps:
        ok, why = applicable(env)
        sub = Check(f"{c.name}.{name}")
        if not ok:
            sub.off(why)
            c.steps.append({"name": name, "status": "OFF", "evidence": sub.evidence, "findings": []})
            continue
        active.append((name, fn, sub))
        try:
            fn(env, sub, "setup")
        except Exception:
            sub.evidence.append("ERROR: setup crashed: " + " | ".join(l.strip() for l in traceback.format_exc().strip().splitlines()[-4:])[:500])
            sub.crashed = True
    env.open_app(dt(env.start, 6))
    env.n_active_steps = len(active)
    from pflab.service import presence

    def tick(e, t, r):                                           # steps that inject something DURING the run (a filing released in the afternoon) declare `fn.ticks = True`
        for name, fn, sub in active:
            if getattr(fn, "ticks", False) and not getattr(sub, "crashed", False):
                try:
                    fn(e, sub, "tick")
                except Exception:
                    sub.evidence.append("ERROR: tick crashed: " + " | ".join(l.strip() for l in traceback.format_exc().strip().splitlines()[-4:])[:500])
                    sub.crashed = True
    run_days(env, env.start, last, on_step=tick)
    env.step(dt(last, 23, 30))
    for name, fn, sub in active:
        if getattr(sub, "crashed", False):
            c.steps.append({"name": name, "status": "ERROR", "evidence": sub.evidence, "findings": [{"what": sub.evidence[-1], "where": f"tools/drills_s81.py step {name}", "how": "run --only accelerated"}]})
            continue
        try:
            fn(env, sub, "check")
            res = sub.result(time.time())
        except Exception:
            sub.evidence.append("ERROR: check crashed: " + " | ".join(l.strip() for l in traceback.format_exc().strip().splitlines()[-4:])[:500])
            res = {"status": "ERROR", "evidence": sub.evidence, "findings": [{"what": sub.evidence[-1], "where": f"tools/drills_s81.py step {name}", "how": "run --only accelerated"}]}
        c.steps.append({"name": name, "status": res["status"], "evidence": res["evidence"], "findings": res["findings"]})
        for e in res["evidence"]:
            c.evidence.append(f"[{name}] {e}")
        c.findings += [dict(f, what=f"[{name}] {f['what']}") for f in res["findings"]]
    clean(env, c, "the accelerated run")
    w = env.world()
    c.ok(w["errors"] == {}, f"the World payload has no failed section ({w['errors']})", "app/world.py")
    c.says(f"pulse: {w['pulse']['verdict']}")
    presence.segments(env.cur())


@drill("accelerated", 20)
def drill_accelerated(env: "Env", c: Check) -> None:
    run_accelerated(env, c)
    bad = [s for s in c.steps if s["status"] in ("FAIL", "ERROR")]
    c.note(f"steps: {[(s['name'], s['status']) for s in c.steps]}")
    if not any(e.startswith("FAIL:") for e in c.evidence) and bad:
        c.ok(False, f"steps failed: {[s['name'] for s in bad]}", "tools/drills_s81.py ACCELERATED_STEPS")


@drill("accelerated_long", 20)
def drill_accelerated_long(env: "Env", c: Check) -> None:
    """The standing assertions over 30 sessions (six weeks, a month boundary, the 28-day claims coming due, the strategist's weekly trigger): what ten sessions cannot show."""
    run_accelerated(env, c, steps=[s for s in ACCELERATED_STEPS if s[0] == "standing"], n_sessions=30)
    cur = env.cur()
    n28 = cur.execute("SELECT count(*) FROM paper_claims WHERE horizon_days >= 28 AND outcome IS NOT NULL").fetchone()[0]
    c.ok(n28 >= 1, f"claims with a 28-day horizon were scored inside the run ({n28})", "paper/manager.py score_due")
    week = cur.execute("SELECT count(*) FROM job_runs WHERE job='strategist'").fetchone()[0]
    c.note(f"the strategist job ran {week} time(s) (each says why it did not start: no cloud client in the workshop)")
    wk = cur.execute("SELECT verdict, sent, details_json FROM week_check_s79 ORDER BY check_id DESC LIMIT 1").fetchone()
    crit = {} if not wk or not wk[2] else {x["name"]: x["status"] for x in json.loads(wk[2]).get("criteria", [])}
    c.ok(wk is not None and wk[0] != "fail", f"the app's check of its own first week after six weeks: {wk[0] if wk else 'not armed'} {crit} (it never ran with a gap, so the catch-up criterion is not tested)", "service/week_check.py")
    n_msg = cur.execute("SELECT count(*) FROM outbox WHERE dedup_key LIKE 'week_check:%'").fetchone()[0]
    c.ok(n_msg <= 1, f"the first-week verdict was queued for Telegram at most once ({n_msg})", "service/week_check.py")


@drill("kill_switch", 20)
def drill_kill_switch(env: "Env", c: Check) -> None:
    """`[core] kill = true` (the one kill switch): no order is placed and no AI session starts, while the book is still marked, fills still happen and the data still arrives; lifted, the loop
    closes the day it missed."""
    from pflab import core
    from pflab.core import loop
    real = core.settings
    env.open_app(dt(env.start, 6))
    cur = env.cur()
    core.settings = lambda: {**real(), "core": {**real()["core"], "kill": True}}
    try:
        c.ok(core.killed() and not core.on() and not core.strategist_on(), "the switch reads as killed: the loop and the strategist are off", "core/__init__.py")
        run_days(env, env.start, env.start)
        c.ok(core_rows(cur) == [], f"no close loop ran with the switch set: {[(str(r[0]), r[2]) for r in core_rows(cur)]}", "service/tasks_s79_core.py, core/loop.py")
        c.ok(loop.run(cur, env.clock.t, env.data) == {"off": True}, "loop.run itself answers off", "core/loop.py")
        c.ok(cur.execute("SELECT count(*) FROM paper_orders").fetchone()[0] == 0 and cur.execute("SELECT count(*) FROM paper_decisions").fetchone()[0] == 0, "no order and no decision was made", "core/loop.py")
        marked = [str(r[0]) for r in cur.execute("SELECT day FROM paper_days ORDER BY day").fetchall()]
        c.ok(str(env.start) in marked, f"the book is still marked for the session while killed: {marked[-2:]}", "paper/book.py catch_up")
        for job in ("core_loop", "story_daily", "lab_close", "strategist"):
            st = env.job_status(job)
            c.ok(st is None or st[0] != "ok", f"job {job} did not work while killed: {st[0] if st else 'never ran'}", f"service/tasks_s79_*.py {job}")
        sessions = cur.execute("SELECT count(*) FROM core_sessions_s80").fetchone()[0]
        api = cur.execute("SELECT count(*) FROM api_calls WHERE status IN ('done','submitted','running','sending')").fetchone()[0]
        c.ok(sessions == 0 and api == 0, f"no strategist session started and no paid call was made ({sessions}, {api})", "lab/strategist.py")
    finally:
        core.settings = real
    env.step(dt(env.start, 23, 30))
    rows = core_rows(env.cur())
    c.ok(env.start in [r[0] for r in rows], f"with the switch lifted the loop closed the day it had missed: {[(str(r[0]), r[2]) for r in rows]}", "core/loop.py")
    clean(env, c)


# --- the app off: Friday to Monday, ten days with a holiday ---------------------------------------------------------------------------------------

def off_drill(env: "Env", c: Check, resume: datetime, label: str) -> None:
    """The app is open Thursday morning to Friday 16:00, then off until `resume`, then opened again (a new process: Runtime.start's on-open code)."""
    from pflab import markets
    from pflab.core import loop
    from pflab.service import away, presence
    m = markets.get("IN")
    thu = env.start
    fri = m.next_session(thu)
    env.open_app(dt(thu, 6))
    run_until(env, thu, dt(fri, 16))
    cur = env.cur()
    runs0 = [r[0] for r in core_rows(cur)]
    last_beat = cur.execute("SELECT max(last_beat) FROM app_presence_s79").fetchone()[0]
    c.note(f"the app was open until {last_beat}; the loop had closed {[str(d) for d in runs0]}; the laptop is now off until {resume} ({label})")
    c.ok(runs0 == [m.previous_session(thu), thu], f"before the gap the loop closed the seed day and Thursday, not Friday ({[str(d) for d in runs0]})", "core/loop.py")
    # off: nothing runs. A new process opens the app.
    env.con.close()
    env.connect()
    env.open_app(resume)
    seg = env.cur().execute("SELECT off_from, off_to FROM app_presence_s79 ORDER BY seg_id DESC LIMIT 1").fetchone()
    c.ok(seg[0] is not None and seg[1] == resume, f"the gap is recorded as '{presence.describe(seg[0], seg[1]) if seg[0] else None}'", "service/presence.py")
    w0 = env.world()
    c.says(f"{w0['pulse'].get('catch_up', {}).get('off')} | catching up: {w0['pulse'].get('catching_up')}")
    c.ok(bool(w0["pulse"].get("catch_up", {}).get("off")), "the World screen says the app was off, from when to when", "app/world.py pulse.catch_up")
    steps = [env.step(resume, continuous=False)]                  # the first tick after opening: everything the gap made due starts now
    for t in [t for t in day_times(resume.date()) if resume < t < dt(resume.date(), 20)]:
        steps.append(env.step(t))
    cur = env.cur()
    closed = m.session_closed_by(resume)
    expected = [d for d in m.sessions_between(thu, closed)]
    marked = [r[0] for r in cur.execute("SELECT day FROM paper_days WHERE day >= ? ORDER BY day", [thu]).fetchall()]
    c.ok(marked == expected, f"every missed session was caught up and marked once, in order: {[str(d) for d in marked]} (expected {[str(d) for d in expected]})", "paper/book.py catch_up, service/tasks.py _paper")
    holiday = [d for d in (resume.date() - timedelta(days=k) for k in range(0, 16)) if not m.is_session(d) and d.weekday() < 5 and d >= fri]
    c.ok(not (set(holiday) & set(marked)), f"no weekday holiday was treated as a session (holidays in the gap: {[str(d) for d in holiday]})", "conductor/calendar.py, paper/book.py sessions_after")
    rows = core_rows(cur)
    days = [r[0] for r in rows]
    c.ok(days == sorted(set(days)) and days[-1] == closed and thu in days and fri not in days[:-1], f"the loop closed the latest session ({closed}) after the gap, once per day: {[str(d) for d in days]}", "core/loop.py, service/tasks_s79_core.py")
    c.note("design: after a gap the loop decides once, on the latest closed session; the missed sessions get their marks, fills and scoring (their positions are already the later ones: a replayed decision would not be point-in-time)")
    last_run = cur.execute("SELECT day, ran_at FROM core_runs_s80 ORDER BY day DESC LIMIT 1").fetchone()
    c.ok(last_run[1] >= resume, f"the post-gap close ran after the app opened ({last_run[1]})", "core/loop.py")
    pit = cur.execute("SELECT count(*) FROM paper_decisions WHERE ref_date IS NOT NULL AND ref_date > CAST(made_at AS DATE)").fetchone()[0]
    c.ok(pit == 0, f"point in time: no decision refers to a close dated after it was made ({pit})", "core/loop.py _decision")
    dup = cur.execute("SELECT count(*) FROM (SELECT decision_id FROM paper_orders GROUP BY 1 HAVING count(*) > 1)").fetchone()[0]
    ndec = cur.execute("SELECT count(*) FROM paper_decisions").fetchone()[0]
    nord = cur.execute("SELECT count(*) FROM paper_orders").fetchone()[0]
    c.ok(dup == 0 and ndec == nord, f"no double orders: {ndec} decisions, {nord} orders, {dup} decisions with two orders", "core/loop.py")
    again = loop.run(cur, env.clock.t, env.data)
    c.ok("skipped" in again or "waiting" in again, f"a second pass of the loop on the same session changes nothing ({again})", "core/loop.py")
    runs = dict(cur.execute("SELECT job, count(*) FROM job_runs WHERE started_at >= ? AND status='ok' GROUP BY 1", [resume]).fetchall())
    worst = max(runs.items(), key=lambda kv: kv[1]) if runs else ("-", 0)
    c.ok(worst[1] <= len(steps), f"nothing ran twice by stampede: the most runs of one job on the opening day was {worst[0]} x{worst[1]} in {len(steps)} ticks", "service/jobs.py tick, service/ondemand.py")
    digest = cur.execute("SELECT count(*) FROM away_digest_s79").fetchone()[0]
    c.ok(digest == 1 and away.maybe_send(cur, env.clock.t) is None, f"the 'while you were away' digest was written once ({digest}) and not again", "service/away.py")
    d = away.latest(cur)
    if d:
        c.says(d["text"].splitlines()[0])
        c.ok("off from" in d["text"].lower() or presence.describe(seg[0], seg[1])[:15] in d["text"], f"the digest names the gap: {d['text'].splitlines()[0][:140]}", "service/away.py")
    stale = cur.execute("SELECT count(*) FROM outbox WHERE kind='summary' AND dedup_key NOT LIKE 'away:%' AND dedup_key NOT LIKE 'week_check:%' AND created_at >= ?", [resume]).fetchone()[0]
    c.ok(stale <= 2, f"only the day's own summaries were queued after opening ({stale}), not the missed ones", "service/ondemand.py STALE_SLOT_H")
    api = cur.execute("SELECT count(*) FROM api_calls WHERE status IN ('done','submitted','running','sending')").fetchone()[0]
    c.ok(api == 0, f"no paid call ({api})", "hq/governor.py")
    made = [r[0] for r in cur.execute("SELECT as_of FROM forecasts_s79 WHERE source='live' AND market='IN' GROUP BY as_of ORDER BY min(forecast_id)").fetchall()]
    c.ok(made == sorted(made) and set(expected) <= set(made), f"every missed session was forecast and scored in order (forecast sessions: {[str(d) for d in made][-8:]}; missing {[str(d) for d in expected if d not in made]})", "service/catchup.py, fcast/run.py catch_up")
    odd = [str(d) for d in made if not m.is_session(d)]
    c.ok(not odd, f"no forecast is dated on a day that is not a session (found: {odd})", "fcast/run.py")
    sc = cur.execute("SELECT count(*), count(DISTINCT forecast_id) FROM forecast_scores_s79 WHERE source='live'").fetchone()
    c.ok(sc[0] == sc[1], f"no forecast was scored twice ({sc[0]} scores, {sc[1]} forecasts)", "fcast/score.py")
    stamped = cur.execute("SELECT count(*) FROM forecasts_s79 WHERE source='live' AND made_at > ?", [resume + timedelta(days=1)]).fetchone()[0]
    c.ok(stamped == 0, f"forecast rows carry the simulated time as made_at ({stamped} were stamped with the real wall clock)", "service/catchup.py (made_at)")
    cu = cur.execute("SELECT count(*) FROM catchup_s79 WHERE market='IN' AND state='done'").fetchone()[0]
    c.ok(cu >= 1, f"the catch-up state is on record for the screen ({cu} done row(s))", "service/catchup.py")
    jobs_not_failed(cur, c)
    clean(env, c, "the catch-up")
    w = env.world()
    c.ok(w["errors"] == {}, f"World payload sections all built ({w['errors']})", "app/world.py")
    c.says(f"pulse: {w['pulse']['verdict']}")
    # the rest of the opening day: its own close arrives at the usual time and the loop closes it once, in order after the gap's
    for t in [t for t in day_times(resume.date()) if t >= dt(resume.date(), 20)]:
        env.step(t)
    cur = env.cur()
    days2 = [r[0] for r in core_rows(cur)]
    own = resume.date() if m.is_session(resume.date()) else None
    c.ok(days2 == sorted(set(days2)) and (own is None or days2[-1] == own), f"after the gap the day's own close was closed once, in order: {[str(d) for d in days2][-4:]}", "core/loop.py")
    marked2 = [r[0] for r in cur.execute("SELECT day FROM paper_days WHERE day >= ? ORDER BY day", [thu]).fetchall()]
    c.ok(marked2 == sorted(set(marked2)) and (own is None or marked2[-1] == own), f"and marked once ({[str(d) for d in marked2][-3:]})", "paper/book.py")
    c.ok(cur.execute("SELECT count(*) FROM (SELECT decision_id FROM paper_orders GROUP BY 1 HAVING count(*) > 1)").fetchone()[0] == 0, "still no double orders", "core/loop.py")
    clean(env, c, "the day after opening")


@drill("off_fri_mon", 20)
def drill_off_fri_mon(env: "Env", c: Check) -> None:
    from pflab import markets
    m = markets.get("IN")
    fri = m.next_session(env.start)
    off_drill(env, c, dt(m.next_session(fri), 9), "Friday 16:00 to Monday 09:00")


@drill("off_10_days", 20)
def drill_off_10_days(env: "Env", c: Check) -> None:
    from pflab import markets
    m = markets.get("IN")
    fri = m.next_session(env.start)
    resume = dt(fri + timedelta(days=10), 9)                       # Mon 26 Oct 09:00: the Tue 20 Oct holiday is inside the gap
    gap_h = [d for d in (fri + timedelta(days=k) for k in range(1, 11)) if d.weekday() < 5 and not m.is_session(d)]
    c.note(f"weekday holidays inside the gap: {[str(d) for d in gap_h]}")
    c.ok(bool(gap_h), "the gap contains a weekday holiday (configs/market_holidays.toml)", "tools/drills_s81.py DEFAULT_START")
    off_drill(env, c, resume, "ten days off")


# --- the network is down ---------------------------------------------------------------------------------------------------------------------

FETCHING_JOBS = ("collect", "global", "us_fx", "nav", "filings", "instruments", "backfill", "data_s79b", "kg", "bars_1m", "comove", "macro_attribution", "kg2_nightly", "news_s81_topup", "us_prices_daily", "us_close")


@drill("net_down", 20)
def drill_net_down(env: "Env", c: Check) -> None:
    """Every request raises ConnectionError: the jobs that fetch run for real against an empty data folder and fail soft and say so; the loop still closes the book from stored prices."""
    import subprocess as sp
    from pflab import markets
    from pflab.service import jobs as _jobs
    m = markets.get("IN")
    env.open_app(dt(env.start, 6))
    env.step(dt(env.start, 7))
    t = dt(env.start, 21)
    env.clock.set(t)
    empty = env.dir / "empty_data"
    empty.mkdir(exist_ok=True)
    real_run = sp.run

    def shim(cmd, *a, **k):
        if isinstance(cmd, (list, tuple)) and any("collect_daily.py" in str(x) for x in cmd):
            return sp.CompletedProcess(cmd, 1, stdout="  bhavcopy           FAIL ConnectionError: HTTPSConnectionPool(host='nsearchives.nseindia.com'): NameResolutionError getaddrinfo failed\n", stderr="")
        return real_run(cmd, *a, **k)
    sp.run = shim
    rows = {}
    try:
        for name in FETCHING_JOBS:
            if name not in env.real_jobs:
                continue
            t0 = time.time()
            r = run_real_job(env, name, empty)
            rows[name] = (r.status, r.detail[:700], round(time.time() - t0, 1))
    finally:
        sp.run = real_run
    c.note(f"fetching jobs run for real: {sorted(rows)}")
    for name, (st, det, secs) in rows.items():
        offline_ok = st in ("skipped", "offline") and ("offline" in det or "waiting" in det or "already done" in det or "no holdings" in det or "login" in det.lower() or "kite" in det.lower())
        if st == "failed":
            try:
                parts = json.loads(det).get("failed") or {}
            except ValueError:
                parts = {"the job": det}
            hole = [p for p, why in parts.items() if not _jobs.offline(why) and any(w in str(why) for w in ("FileNotFoundError", "IOException", "not built", "No files found"))]
            other = [p for p, why in parts.items() if not _jobs.offline(why) and p not in hole]
            if not parts or other:
                c.ok(False, f"{name}: failed for a reason that is neither a lost connection nor the harness's empty data folder: {det[:400]}", f"service/jobs.py run_job; job {name}")
            else:
                c.note(f"{name}: failed in {secs}s: parts {sorted(parts)}; the offline ones said so, the others only lack the data files this empty folder has ({hole})")
            continue
        c.ok(offline_ok or st == "ok", f"{name}: {st} in {secs}s - {det[:600]}", f"service/jobs.py run_job; job {name}")
    jobfail = env.cur().execute("SELECT count(*) FROM outbox WHERE kind='job_failure' AND (text LIKE '%ConnectionError%' OR text LIKE '%getaddrinfo%' OR text LIKE '%NameResolution%')").fetchone()[0]
    c.ok(jobfail == 0, f"no 'job failed' alert was queued for a lost connection ({jobfail})", "app/runtime.py _after, service/jobs.py")
    w = env.world()
    jobs_view = {j["job"]: j for j in w["jobs"]}
    for name in rows:
        j = jobs_view.get(name)
        if j:
            c.says(f"{name}: {j['state']} ({(j['last'] or {}).get('detail') or j['why']})"[:140])
    bad = [(n, jobs_view[n]["state"]) for n in rows if n in jobs_view and jobs_view[n]["state"] == "down" and rows[n][0] in ("offline", "skipped")]
    c.ok(not bad, f"an offline job is not shown as down on the World screen ({bad})", "app/world.py")
    # the loop still closes the book from stored prices, with the network down the whole time
    run_days(env, env.start, env.start)
    cur = env.cur()
    runs = core_rows(cur)
    c.ok(env.start in [r[0] for r in runs] and all(r[2] in ("traded", "held") for r in runs), f"with the network down the loop still closed {env.start} from stored prices: {[(str(r[0]), r[2]) for r in runs]}", "core/loop.py")
    c.ok(cur.execute("SELECT count(*) FROM core_cards_s80").fetchone()[0] >= 1, "the book card was written from stored data", "core/card.py")
    c.ok(len(env.net.blocked) > 0, f"the requests really were refused ({len(env.net.blocked)}): {env.net.blocked[:2]}", "tools/drills_s81.py Net")
    c.ok(not env.exceptions, f"no exception escaped a loop: {env.exceptions[:3]}", "(named)")


# --- the local model is down ------------------------------------------------------------------------------------------------------------------

def seed_story_items(env: "Env", day: date) -> int:
    """Two dated attribution rows that the storyline adapters turn into evidence items (the table is the macro_attribution job's, filled here by hand)."""
    cur = env.cur()
    cols = [r[0] for r in cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='macro_attribution' ORDER BY ordinal_position").fetchall()]
    n = 0
    for part, pct in (("foreign flows", -0.6), ("US yield", -0.3)):
        vals = {"market": "IN", "session": day, "part": part, "pct": pct}
        row = [vals.get(k) if k in vals else (0.0 if k in ("pct", "total") else None) for k in cols]
        if "computed_at" in cols:
            row[cols.index("computed_at")] = env.clock.t
        cur.execute(f"INSERT INTO macro_attribution ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", row)
        n += 1
    return n


@drill("ollama_down", 20)
def drill_ollama_down(env: "Env", c: Check) -> None:
    """The local model is unreachable: the storyline reader leaves the items unread and says so; nothing crashes; the close loop still closes; when it is back the items are read."""
    from pflab.llm import client
    from pflab.story import adapters
    env.open_app(dt(env.start, 6))
    env.step(dt(env.start, 7))
    run_days(env, env.start, env.start)                  # Thursday's closes arrive, the loop runs
    t = dt(env.start, 22, 30)
    env.clock.set(t)
    ok_reply = client.chat("qwen3:8b-q8_0", [{"role": "user", "content": "hi"}])
    c.ok(bool(ok_reply.text), "the fake local model answers while it is up", "tools/drills_s81.py Net")
    n_items = seed_story_items(env, env.start)
    items = adapters.collect(env.cur(), env.data, env.start)
    c.ok(len(items) >= 1, f"the storyline adapters bring {len(items)} evidence item(s) from {n_items} attribution rows", "story/adapters.py")
    env.net.ollama_down()
    try:
        client.chat("qwen3:8b-q8_0", [{"role": "user", "content": "hi"}])
        c.ok(False, "the local client raised nothing with Ollama down", "llm/client.py")
    except client.OllamaError as e:
        c.ok("not reachable" in str(e), f"the client says so in words: {str(e)[:100]}", "llm/client.py")
    r = run_real_job(env, "story_daily")
    cur = env.cur()
    det = json.loads(r.detail) if r.detail.startswith("{") else {}
    rd = det.get("reader") or {}
    c.ok(r.status in ("ok", "skipped"), f"story_daily did not fail with the model away: {r.status} {r.detail[:200]}", "service/tasks_s79_story.py, story/reader.py")
    c.ok(rd.get("unavailable", 0) >= 1 and rd.get("read", 0) == 0, f"the reader left the items unread and said so (unavailable {rd.get('unavailable')}, read {rd.get('read')})", "story/reader.py process")
    unread = cur.execute("SELECT count(*) FROM storyline_reader_s80").fetchone()[0]
    c.ok(unread == 0, f"no item was marked read while the model was away ({unread})", "story/reader.py")
    c.ok(cur.execute("SELECT count(*) FROM storyline_evidence_s80").fetchone()[0] == 0 and cur.execute("SELECT count(*) FROM storylines_s80").fetchone()[0] == 0, "no storyline or evidence was invented without the model", "story/store.py")
    w = env.world()
    loc = [x for x in w["checks"] if x["name"] == "Local model"]
    c.ok(bool(loc) and loc[0]["state"] == "down", f"the World says so: {loc[0]['state'] if loc else None} - {loc[0]['detail'] if loc else ''}", "app/system.py connectors")
    c.says(loc[0]["detail"] if loc else "")
    body = env.client().get("/api/core").json()
    c.ok(body.get("storylines") == [] and not body.get("left_out"), f"/api/core still answers with the storylines empty ({body.get('left_out')})", "core/screens.py")
    # the close loop is not held up by the model: Friday closes with it still down
    fri = __import__("pflab.markets", fromlist=["x"]).get("IN").next_session(env.start)
    run_days(env, fri, fri)
    runs = [str(r[0]) for r in core_rows(cur)]
    c.ok(str(fri) in runs, f"the close loop closed {fri} with the model away ({runs})", "core/loop.py")
    # back up: the items are read at the next run
    env.net.ollama_back()
    env.clock.set(dt(fri, 23, 30))
    r2 = run_real_job(env, "story_daily")
    det2 = json.loads(r2.detail) if r2.detail.startswith("{") else {}
    rd2 = det2.get("reader") or {}
    c.ok(rd2.get("read", 0) >= 1 and rd2.get("unavailable", 0) == 0, f"with the model back the items were read ({rd2})", "story/reader.py")
    c.ok(cur.execute("SELECT count(*) FROM storyline_evidence_s80").fetchone()[0] >= 1, "and attached as dated evidence to a storyline, with its source", "story/store.py")
    clean(env, c)


# --- docker is down ---------------------------------------------------------------------------------------------------------------------------

SIMPLE_POLICY = '''
def decide(state, forecasts, sims, storylines, params=None):
    keys = list(state["universe"])[:5]
    return {k: 0.05 for k in keys}
'''


def synth_panel(env: "Env") -> dict:
    """A small panel for the lab and the live champion, built from this profile's own prices (keys: the stocks by ISIN, the ETFs as 'ETF:<symbol>')."""
    import pandas as pd
    cur = env.cur()
    rows = cur.execute("SELECT p.date, p.isin, p.close, i.symbol, i.asset_class FROM prices p JOIN instruments i USING (isin) WHERE i.asset_class IN ('equity','etf') ORDER BY p.date").fetchall()
    df = pd.DataFrame(rows, columns=["date", "isin", "close", "symbol", "kind"])
    df["date"] = pd.to_datetime(df["date"])
    df["key"] = df.apply(lambda r: "ETF:" + r["symbol"] if r["kind"] == "etf" else r["isin"], axis=1)
    px = df.pivot_table(index="date", columns="key", values="close", aggfunc="last").sort_index()
    meta = {}
    for k in px.columns:
        sym = df[df["key"] == k]["symbol"].iloc[0]
        meta[k] = {"symbol": sym, "etf": k.startswith("ETF:"), "sector": None, "tax": "EQUITY"}
    to = px * 1e7
    idx = px.mean(axis=1)
    return {"px": px, "turnover": to, "meta": meta, "index": idx, "bench": idx}


@drill("docker_down", 20)
def drill_docker_down(env: "Env", c: Check) -> None:
    """The sandbox is unavailable: a lab run is refused with the reason and nothing is half-recorded; the champion keeps deciding (the loop closes)."""
    import shutil as sh
    import subprocess as sp
    from pflab.agents import sandbox as sb
    from pflab.app import system
    from pflab.lab import service as lab
    env.open_app(dt(env.start, 6))
    env.step(dt(env.start, 7))
    t = dt(env.start, 12)
    env.clock.set(t)
    cur = env.cur()
    added = lab.add_variant(cur, env.pm, t, "drill_flat", SIMPLE_POLICY, "A flat five-name book for the drill: tests that a refused lab run is refused cleanly.")
    c.ok(added.get("ok"), f"a draft variant was stored for the lab run ({added})", "lab/service.py add_variant")
    real_run, real_which = sp.run, sh.which

    def shim(cmd, *a, **k):
        if isinstance(cmd, (list, tuple)) and cmd and str(cmd[0]) == "docker":
            return sp.CompletedProcess(cmd, 1, stdout=b"", stderr=b"error during connect: Docker Desktop is not running")
        return real_run(cmd, *a, **k)
    sp.run = shim
    sh.which = lambda n, *a, **k: "docker.exe" if n == "docker" else real_which(n, *a, **k)
    system._docker_probe = env.real_docker_probe
    sb.status = env.real_sb_status
    real_probe = sb.probe
    sb.probe = lambda *a, **k: real_probe(shim, *a[1:] if a else (), **k)
    try:
        system._CACHE.clear()
        st = sb.status(shim, force=True)
        c.ok(st["ok"] is False and "not running" in st["why"], f"sandbox status says: {st}", "agents/sandbox.py status")
        sb._cache.update({"at": time.time(), "ok": False, "why": st["why"]})
        state, words = system.sandbox_line(cur, t)
        c.ok(state != "ok" and "Docker" in words, f"System screen: {state} - {words}", "app/system.py sandbox_line")
        c.says(words)
        # the strategist's tool: a lab run is refused with the reason, as a result the model can read (never an exception through the session)
        from pflab.lab import tools as lt
        t0 = time.time()
        ctx = lt.make_ctx(cur, env.pm, env.data, t, None, data=synth_panel(env))
        text, is_err = lt.run(ctx, "run_lab", {"policy_id": "drill_flat", "n_shuffles": 1})
        c.ok(is_err and ("docker" in text.lower() or "sandbox" in text.lower()), f"the lab run was refused with the reason in {time.time() - t0:.1f}s: {text[:200]}", "lab/tools.py run, lab/runner.py pick_box")
        c.says(f"lab: {text[:100]}")
        c.ok(cur.execute("SELECT count(*) FROM lab_runs_s80 WHERE policy_id='drill_flat'").fetchone()[0] == 0, "nothing was recorded as a lab run (no half-written score)", "lab/service.py")
        c.ok(sb.available(shim, force=True) is False, "calculations are not available (sb.available is False): nothing is run outside a container", "agents/sandbox.py")
        # a challenger in shadow needs the sandbox too; the champion keeps deciding through the close, the lab job says why it could not work
        cur.execute("UPDATE core_policies_s80 SET status='challenger' WHERE policy_id='drill_flat'")
        env.clock.set(dt(env.start, 6, 30))
        run_days(env, env.start, env.start)
        rows = core_rows(cur)
        c.ok(env.start in [r[0] for r in rows] and all(r[1] in BASELINES for r in rows), f"the champion kept deciding with Docker down: {[(str(r[0]), r[1], r[2]) for r in rows]}", "core/loop.py")
        lc = cur.execute("SELECT status, detail FROM job_runs WHERE job='lab_close' AND detail LIKE '%andbox%' ORDER BY run_id DESC LIMIT 1").fetchone()
        c.ok(lc is not None and lc[0] == "skipped" and "docker" in lc[1].lower(), f"the lab_close job waited and named the reason instead of failing: {lc[0] if lc else 'it did not run'} - {(lc[1] if lc else '')[:140]}", "service/tasks_s79_lab.py")
        n_alerts = cur.execute("SELECT count(*) FROM outbox WHERE kind='job_failure' AND text LIKE '%lab_close%'").fetchone()[0]
        c.ok(n_alerts == 0, f"no 'job failed' alert was queued for Docker being down ({n_alerts})", "app/runtime.py _after")
        c.ok(cur.execute("SELECT count(*) FROM core_shadow_s80").fetchone()[0] == 0, "no half-written shadow row", "lab/shadow.py")
    finally:
        sp.run, sh.which = real_run, real_which
        sb.probe = real_probe
    clean(env, c)


# --- Kite is logged out -----------------------------------------------------------------------------------------------------------------------

@drill("kite_logged_out", 20)
def drill_kite_logged_out(env: "Env", c: Check) -> None:
    """No valid token: the Kite jobs skip and say so; the login question goes out once a day; only post-close work runs; the loop and the book still work."""
    from pflab import markets
    from pflab.app import runtime as rtm, system
    from pflab.ingest import kite as km
    from pflab.service import jobs
    m = markets.get("IN")
    thu = env.start
    fri = m.next_session(thu)
    cur = env.cur()
    env.open_app(dt(thu, 6))
    # Part A: no login at all on Thursday and Friday: Kite jobs skip and say so, the book closes from the daily files
    t = dt(thu, 10)
    env.clock.set(t)
    c.ok(not rtm.token_valid(t), "with no saved token Kite is not logged in", "ingest/kite.py")
    k1 = [x for x in system.connectors(env.rt, t) if x["id"] == "kite"][0]
    c.ok(k1["state"] != "ok" and "not logged in" in k1["line"], f"System screen: {k1['state']} - {k1['line']}", "app/system.py connectors")
    c.says(k1["line"])
    c.ok(env.rt.live_once() == 0, "the live poller does nothing, quietly, without a login", "app/runtime.py live_once")
    run_days(env, thu, fri)
    runs = [str(r[0]) for r in core_rows(cur)]
    c.ok(runs == [str(m.previous_session(thu)), str(thu), str(fri)], f"the loop and the book worked without a Kite login: closes {runs}", "core/loop.py")
    bars = [(r[0], r[1][:60]) for r in cur.execute("SELECT status, detail FROM job_runs WHERE job IN ('bars_1m','live','tradecheck') ORDER BY run_id").fetchall()] if "bars_1m" in env.real_jobs else []
    c.note(f"Kite jobs (faked in this tick; the real bars_1m is run below): {len(bars)} runs")
    r = run_real_job(env, "bars_1m") if "bars_1m" in env.real_jobs else None
    if r is not None:
        c.ok(r.status == "skipped" and "kite" in r.detail.lower(), f"bars_1m skipped and said why: {r.status} - {r.detail[:100]}", "service/tasks_s79_bars.py")
        c.says(f"bars_1m: {r.detail[:80]}")
    sess = importlib.util.find_spec("pflab.core.session") is not None
    if sess:
        from pflab.core import session
        n_fills0 = cur.execute("SELECT count(*) FROM session_fills_s81").fetchone()[0]
        r1 = session.run_once(cur, dt(fri, 11), data_root=env.data)            # in session hours, no quotes injected, no Kite client: the live path without a login
        r2 = session.run_once(cur, dt(fri, 11, 5), data_root=env.data)
        said = cur.execute("SELECT count(*), max(text) FROM session_said_s81 WHERE day=? AND key='kite'", [fri]).fetchone()
        c.ok(r1.get("degraded") and r2.get("degraded") and said[0] == 1 and "login" in str(said[1]).lower() and "post-close" in str(said[1]).lower(),
             f"the session loop says once that there is no Kite login and that only the post-close work runs ({said[0]} message: {str(said[1])[:150]})", "core/session.py say_once")
        c.ok(cur.execute("SELECT count(*) FROM session_fills_s81").fetchone()[0] == n_fills0, "and it made no fill without a quote", "core/session.py")
    else:
        c.note("OFF (part): pflab.core.session is not in this tree: the session loop's 'Kite is logged out, only post-close work runs' line waits for module pflab.core.session (B6b)")
    # Part B: a login on Saturday lapses on Sunday 06:00; one question a day, on Telegram at most once; the real job
    sat, sun = fri + timedelta(days=1), fri + timedelta(days=2)
    mon = m.next_session(fri)
    km.TokenStore().save("drill-token", dt(sat, 8))
    env.clock.set(dt(sat, 10))
    c.ok(rtm.token_valid(dt(sat, 10)), "a token saved Saturday 08:00 is valid Saturday 10:00", "ingest/kite.py")
    env.clock.set(dt(sun, 7))
    c.ok(not rtm.token_valid(dt(sun, 7)), "the token has lapsed Sunday 07:00 (Zerodha tokens end at 06:00)", "ingest/kite.py token_expiry")
    if "bars_1m" in env.real_jobs:                                  # a Kite job that skipped for a missing login inside the last 24 hours keeps the question wanted over the weekend
        run_real_job(env, "bars_1m")
    open_n, keys = [], []
    for tt in (dt(sun, 9), dt(sun, 12), dt(sun, 15), dt(mon, 9)):
        env.clock.set(tt)
        jobs.run_job(jobs.Ctx(cur, tt, env.pm, env.data, REPO, sys.executable, env.rt.secrets), jobs.REGISTRY["kite_token"])
        open_n.append(cur.execute("SELECT count(*) FROM questions WHERE subject_key LIKE 'kite_login:%' AND status='open'").fetchone()[0])
        keys.append(cur.execute("SELECT string_agg(subject_key, ',') FROM questions WHERE subject_key LIKE 'kite_login:%' AND status='open'").fetchone()[0])
    per_day = cur.execute("SELECT CAST(created_at AS DATE), count(*) FROM outbox WHERE kind='question' AND text LIKE 'Kite is logged out%' GROUP BY 1 ORDER BY 1").fetchall()
    c.ok(open_n == [1, 1, 1, 1] and f"kite_login:{sun}" in str(keys[0]) and f"kite_login:{mon}" in str(keys[3]),
         f"the login question appears once a day (Sunday 09:00, 12:00, 15:00 then Monday 09:00): open {open_n}, keys {keys[0]} -> {keys[3]}", "service/tasks_s79_kitelogin.py")
    c.ok(per_day and all(n == 1 for _d, n in per_day), f"it was queued for Telegram once a day, never twice in a day: {[(str(d), n) for d, n in per_day]}", "agents/voice.py, service/tasks_s79_kitelogin.py")
    from pflab.service import telegram
    out = telegram.flush(cur, _sender(env), env.clock.t)
    kite_msgs = [x for x in env.tg.sent if x.startswith("Kite is logged out")]
    c.ok(len(kite_msgs) == len(per_day), f"the fake Telegram received the login question {len(kite_msgs)} time(s), one per day ({out})", "service/telegram.py")
    w = env.world()
    c.says("Needs: " + "; ".join(str(n)[:90] for n in w.get("needs", []))[:240])
    clean(env, c)


# --- the monthly cap is reached ---------------------------------------------------------------------------------------------------------------

@drill("budget_exhausted", 20)
def drill_budget(env: "Env", c: Check) -> None:
    """The month's cap is spent: no paid call is made (the strategist's session, the checker and the reader's escalation are all refused), every local job still runs, the screen says so."""
    from pflab import guard
    from pflab.agents import analyst as an
    from pflab.core import checker
    from pflab.hq import governor as gv
    from pflab.lab import strategist
    from pflab.pm.store import next_id
    os.environ["PFLAB_PAID"] = "1"          # only so the workshop guard does not answer first; nothing paid is ever sent here: the client below counts and refuses
    (env.pm / "api_budget.toml").write_text("[api]\nmodel = \"claude-opus-5-5\"\nmonthly_cap_rupees = 2500\ndev_monthly_cap_rupees = 100\nask_above_rupees = 100\nusd_inr = 90.0\nadopted = true\n"
                                           "[egress]\nnames = [\"synthname\"]\naddress = []\n", encoding="utf-8")
    env.open_app(dt(env.start, 6))
    env.step(dt(env.start, 7))
    t = dt(env.start, 21)
    env.clock.set(t)
    cur = env.cur()
    cid = next_id(cur, "api_calls", "call_id")
    cur.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, status, cost_inr, finished_at, agent) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [cid, t - timedelta(hours=3), "live", "m", "drill", "q", "x", "{}", "done", 100.0, t - timedelta(hours=3), "strategist"])
    cfg = an.config()
    c.ok(guard.blocked("paid") is None, "(the workshop guard stands aside for this drill: PFLAB_PAID is set in the child only)", "guard.py")
    cl = CountingClient()
    try:
        gv.check(cur, "strategist", 5.0, 1000, 500, t, "normal", cfg)
        c.ok(False, "a paid call was allowed with the month's cap spent", "hq/governor.py check")
    except gv.BudgetRefused as e:
        c.ok(getattr(e, "resume_at", None) is not None, f"the governor refuses with a reason and a resume time: {str(e)[:110]} (resume {getattr(e, 'resume_at', None)})", "hq/governor.py")
    # the strategist's session: refused before any request
    s = strategist.run_session(cur, env.pm, env.data, t, "drill: the weekly session", client=cl, cfg=cfg)
    c.ok(cl.created == 0, f"the strategist made no paid request ({cl.created} created, {cl.counted} priced)", "lab/strategist.py, hq/llm.py")
    c.ok(s.get("status") in ("failed", "wasted") or "skipped" in s, f"the strategist's session ended with a stated reason: {str(s)[:200]}", "lab/strategist.py run_session")
    refused = cur.execute("SELECT count(*) FROM api_calls WHERE status='over_limit'").fetchone()[0]
    c.ok(refused >= 1, f"the refusal is on record ({refused} over_limit row(s))", "hq/governor.py log_refusal")
    # the checker: the trades stand, unchecked, and it says why
    big = {"isin": STOCKS[0][1], "symbol": STOCKS[0][0], "side": "buy", "qty": None, "amount": 150000.0, "value": 150000.0, "risk_cut": False, "charges": 0.0, "tax": 0.0, "note": "", "from_w": 0.05, "to_w": 0.15}
    state = {"value": 1_000_000.0}
    rv = checker.review(cur, t, env.start, state, [big], lambda: cl, cfg=cfg)
    c.ok(cl.created == 0 and rv["orders"] == [big] and rv["unchecked"], f"the checker made no paid request; the big trade stood, unchecked: {str(rv['unchecked'])[:120]}", "core/checker.py")
    # the local jobs all still run: the day's close, the storylines, the lab's shadow step
    run_days(env, env.start, env.start)
    rows = core_rows(cur)
    c.ok(env.start in [r[0] for r in rows] and all(r[2] in ("traded", "held") for r in rows), f"the close loop still closed the book with the cap spent: {[(str(r[0]), r[2]) for r in rows]}", "core/loop.py")
    for name in ("story_daily", "paper", "catch_up", "lab_close"):
        if name in env.real_jobs:
            r = run_real_job(env, name)
            c.ok(r.status in ("ok", "skipped"), f"local job {name} still runs: {r.status} {r.detail[:100]}", f"job {name}")
    c.ok(cl.created == 0, f"still no paid request after the local jobs ({cl.created})", "hq/llm.py")
    api = cur.execute("SELECT count(*) FROM api_calls WHERE status IN ('done','submitted','running','sending') AND call_id <> ?", [cid]).fetchone()[0]
    c.ok(api == 0, f"no paid call is on record besides the month's earlier spend ({api})", "hq/governor.py")
    w = env.world()
    sp = [n for n in w["guard_nodes"] if n["id"] == "spend"]
    c.ok(bool(sp) and sp[0]["state"] == "down", f"the screen says so: spend {sp[0]['state'] if sp else None} - {sp[0]['sub'] if sp else 'no spend node'}", "app/world.py guards_view")
    c.says(sp[0]["sub"] if sp else "")
    body = env.client().get("/api/core").json()
    c.ok(isinstance(body.get("spend"), dict), f"/api/core carries the spend by use (month Rs {body.get('spend', {}).get('month')})", "core/screens.py spend")
    clean(env, c)


# --- a promoted lab policy raises ---------------------------------------------------------------------------------------------------------------

RAISING_POLICY = '''
def decide(state, forecasts, sims, storylines, params=None):
    return {k: 1.0 / 0 for k in state["universe"]}
'''


def _promote(env: "Env", policy_id: str, code: str, t: datetime) -> None:
    from pflab.lab import service as lab
    cur = env.cur()
    r = lab.add_variant(cur, env.pm, t, policy_id, code, "A drill champion whose decide raises, to prove the baseline takes over for that close.")
    assert r.get("ok"), r
    cur.execute("UPDATE core_policies_s80 SET status='champion', promoted_at=? WHERE policy_id=?", [t, policy_id])


@drill("failing_champion", 20)
def drill_failing_champion(env: "Env", c: Check) -> None:
    """A promoted lab policy raises: the baseline decides that close and the act says so; also with the champion's inputs missing."""
    from pflab import markets
    from pflab.core import loop
    from pflab.paper import book
    m = markets.get("IN")
    env.open_app(dt(env.start, 6))
    thu = env.start
    cur = env.cur()
    _promote(env, "drill_boom", RAISING_POLICY, dt(thu, 6))
    # (1) the champion's own code raises: the loop is called the way the job calls it, with the champion's panel supplied (so the failure is the policy's, not the data's)
    for t in day_times(thu)[:-2]:
        env.step(t)
    arrive(env, thu)
    book.catch_up(cur, thu, dt(thu, 21, 10))
    r = loop.run(cur, dt(thu, 21, 30), env.data, live_data=synth_panel(env))
    c.ok("status" in r, f"the loop answered for {thu} with a raising champion: {str(r)[:160]}", "core/loop.py")
    row = cur.execute("SELECT policy_id, status, note FROM core_runs_s80 WHERE day=?", [thu]).fetchone()
    c.ok(row is not None and row[0] in BASELINES, f"the baseline decided that close: policy {row[0] if row else None}, {row[1] if row else None}", "core/loop.py (the champion fallback)")
    act = cur.execute("SELECT what FROM paper_acts WHERE loop='core_loop' AND what LIKE '%drill_boom%failed%' ORDER BY act_id DESC LIMIT 1").fetchone()
    c.ok(act is not None, f"the act says the champion failed and the baseline decided: {act[0][:180] if act else 'no such act'}", "core/loop.py cadence.act")
    c.says(act[0][:120] if act else "")
    c.ok("ZeroDivisionError" in (act[0] if act else ""), "the act names the error", "core/loop.py")
    decisions = cur.execute("SELECT count(*) FROM paper_decisions").fetchone()[0]
    c.note(f"the baseline placed {decisions} decision(s) that close")
    # (2) next day through the real job path: the champion's inputs (the panel on disk) are missing: the same fallback
    fri = m.next_session(thu)
    run_days(env, fri, fri)
    row2 = cur.execute("SELECT policy_id FROM core_runs_s80 WHERE day=?", [fri]).fetchone()
    acts2 = cur.execute("SELECT count(*) FROM paper_acts WHERE loop='core_loop' AND what LIKE '%drill_boom%failed%'").fetchone()[0]
    c.ok(row2 is not None and row2[0] in BASELINES and acts2 >= 2, f"through the job (no panel on disk) the baseline also decided {fri}: policy {row2[0] if row2 else None}, failure acts {acts2}", "core/loop.py, lab/live.py")
    c.ok(cur.execute("SELECT status FROM core_policies_s80 WHERE policy_id='drill_boom'").fetchone()[0] == "champion", "the failing champion is still the champion on record (only the lab's rollback rule demotes one)", "lab/promotion.py rollback_check")
    clean(env, c)


# --- a probation slice is withdrawn -----------------------------------------------------------------------------------------------------------

@drill("probation_withdrawn", 20)
def drill_probation(env: "Env", c: Check) -> None:
    """A probation slice whose live record is worse than the champion's is withdrawn (A50c); a slice whose record is not worse stays or grows. OFF, naming the module, when
    pflab.lab.probation is not in this tree."""
    if not module_exists("pflab.lab.probation"):
        c.off("waiting for module pflab.lab.probation (B3, the probation slice, A50c; it also needs the probation_s81 table of migration 109)")
        return
    from pflab import markets
    from pflab.lab import probation as pb, service as lab, shadow
    m = markets.get("IN")
    env.open_app(dt(env.start, 6))
    cur = env.cur()
    t = dt(env.start, 22)
    lab.ensure_baseline(cur, t)
    for pid in ("drill_worse", "drill_better"):
        r = lab.add_variant(cur, env.pm, t, pid, SIMPLE_POLICY, f"A drill variant ({pid}) on a probation slice, judged by its live record against the champion's stand-in.")
        c.ok(r.get("ok"), f"{pid} was stored ({r.get('problem', 'ok')})", "lab/service.py add_variant")
        cur.execute("UPDATE core_policies_s80 SET status='challenger' WHERE policy_id=?", [pid])
    cfg = pb.cfg()
    start_share = float(cfg["start_share"])
    gate = int(cfg["sessions_to_grow"][0])
    n = max(gate, int(cfg["min_sessions_to_judge"])) + 1
    d0 = m.previous_session(env.start)
    verdict = {"history": {"cagr": 0.12}, "final": {"cagr": 0.10}}
    g = {pid: pb.grant(cur, t, d0, pid, verdict) for pid in ("drill_worse", "drill_better")}
    c.ok(all(x["granted"] for x in g.values()) and all(abs(x["share"] - start_share) < 1e-9 for x in g.values()), f"each variant was granted the start slice of {start_share:.0%} at once: {[(k, v.get('share')) for k, v in g.items()]}", "lab/probation.py grant")
    c.ok(abs(pb.total_share(cur, d0) - 2 * start_share) < 1e-9, f"the slices together take {pb.total_share(cur, d0):.0%} of the book", "lab/probation.py total_share")
    # the live record: `n` sessions after the grant; the champion's stand-in earns +0.1% a day, the worse variant -0.4%, the better +0.3%
    standin = shadow.standin(cur)
    days, d = [], d0

    def write_day(d):
        for pid, ret in ((standin, 0.001), ("drill_worse", -0.004), ("drill_better", 0.003)):
            cur.execute("INSERT OR REPLACE INTO core_shadow_s80 VALUES (?,?,?,?,?)", [d, pid, "{}", ret, dt(d, 22)])
    for _ in range(3):
        d = m.next_session(d)
        days.append(d)
        write_day(d)
    early = pb.review(cur, dt(days[2], 22), days[2])
    c.ok(early == [], f"three sessions in nothing is judged yet (min_sessions_to_judge {cfg['min_sessions_to_judge']}): {early}", "lab/probation.py review")
    for _ in range(n - 3):
        d = m.next_session(d)
        days.append(d)
        write_day(d)
    last = days[-1]
    c.note(f"{n} scored shadow sessions written after the grant, {days[0]} to {last}; the stand-in is {standin}")
    changes = {x["policy_id"]: x for x in pb.review(cur, dt(last, 22), last)}
    w, b = changes.get("drill_worse"), changes.get("drill_better")
    c.ok(w is not None and w["change"] == "withdraw" and w["share"] == 0.0 and "withdrawn" in w["why"], f"the worse variant's slice was withdrawn by code, with its reason: {w['why'][:180] if w else None}", "lab/probation.py review")
    c.ok(b is None or b["change"] == "grow", f"the variant that is not worse was not withdrawn ({b['why'][:120] if b else 'it holds its slice until the next gate'})", "lab/probation.py review")
    sl = {s["policy_id"]: s["share"] for s in pb.slices(cur, last)}
    c.ok("drill_worse" not in sl and "drill_better" in sl, f"the slices in force on {last}: {sl}", "lab/probation.py slices")
    c.ok(pb.review(cur, dt(last, 23), last) == [], "a second review of the same day changes nothing", "lab/probation.py review idempotence")
    ex = pb.explain(cur, last, "drill_worse")
    c.ok(ex["share"] == 0.0 and "withdrawn" in ex["why"], f"the screen's explanation: slice {ex['share']:.0%}, {ex['why'][:140]}", "lab/probation.py explain")
    c.says(f"drill_worse: {ex['why'][:110]}")
    kinds = [h["kind"] for h in pb.history(cur, "drill_worse")]
    c.ok(kinds == ["grant", "withdraw"], f"the history of the withdrawn slice: {kinds}", "lab/probation.py history")
    body = env.client().get("/api/core").json()
    text = json.dumps(body.get("policies"), default=str)
    c.ok("drill_worse" in text and ("withdrawn" in text or "slice" in text), "/api/core (the Today screen) shows each challenger's slice and why", "core/screens.py policies")
    if _src_has("pflab.core.loop", "probation"):
        nxt = m.next_session(last)                                              # the withdrawal is dated `last` (sixteen sessions after the start): run the app up to the close after it
        env.clock.set(dt(env.start, 6, 30))
        run_days(env, env.start, nxt)
        early = cur.execute("SELECT note FROM core_runs_s80 WHERE day=?", [m.next_session(env.start)]).fetchone()
        run = cur.execute("SELECT note FROM core_runs_s80 WHERE day=?", [nxt]).fetchone()
        c.ok(early is not None and "drill_worse" in (early[0] or ""), f"while the slice was in force its policy traded its share: {str(early[0])[-110:] if early else None}", "core/loop.py probation blend")
        c.ok(run is not None and "drill_worse" not in (run[0] or ""), f"the close after the withdrawal did not trade the withdrawn slice: {str(run[0])[-140:] if run else None}", "core/loop.py")
    else:
        c.note("pflab.core.loop does not call lab.probation yet (no slice trades in the close loop): the loop-level assertion waits for the coordinator's wiring")
    clean(env, c)


# --- kill -9 -----------------------------------------------------------------------------------------------------------------------------------

JOB_KILL_SCRIPT = '''
import sys, os, time, threading
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, r"@SRC@")
os.environ["PFLAB_PM_DIR"] = r"@PM@"
from pflab.pm import store
from pflab.service import jobs, presence
from pflab.service.jobs import Ctx, Job
from pflab.service.schedule import Interval
con = store.connect()
now = datetime.fromisoformat("@NOW@")
presence.start(con, now, os.getpid())
presence.beat(con, now + timedelta(minutes=1))
con.execute("CREATE TABLE IF NOT EXISTS drill_wal(id INTEGER, note VARCHAR)")
con.execute("INSERT INTO drill_wal SELECT i, 'committed' FROM range(1000) t(i)")
tx = con.cursor()
tx.execute("BEGIN")
tx.execute("INSERT INTO drill_wal SELECT 1000 + i, 'uncommitted' FROM range(1000) t(i)")
job = Job("catch_up", Interval(5, weekdays_only=False), lambda c: time.sleep(900) or {})
ctx = Ctx(con.cursor(), now + timedelta(minutes=1), Path(r"@PM@"), Path(r"@DATA@"), Path(r"@REPO@"))
threading.Thread(target=lambda: jobs.run_job(ctx, job), daemon=True).start()
while not con.cursor().execute("SELECT 1 FROM job_runs WHERE job='catch_up' AND status='running'").fetchone():
    time.sleep(0.1)
print("RUNNING", flush=True)
time.sleep(900)
'''

# The close loop is run in a child process whose `book.place` stalls after `@AFTER@` orders (or whose card write stalls): the parent kills it with taskkill /F at that moment.
LOOP_KILL_SCRIPT = '''
import sys, os, time, json
from datetime import datetime, date
from pathlib import Path
sys.path.insert(0, r"@SRC@")
os.environ["PFLAB_PM_DIR"] = r"@PM@"
os.environ["PFLAB_DATA_DIR"] = r"@DATA@"
os.environ["PFLAB_NO_POOL"] = "1"
from pflab.pm import store
from pflab.paper import book, cadence
from pflab.core import loop, card
con = store.connect()
AFTER, WHERE = int("@AFTER@"), "@WHERE@"
placed = {"n": 0}
real_place = book.place
def place(*a, **k):
    oid = real_place(*a, **k)
    placed["n"] += 1
    if WHERE == "orders" and placed["n"] >= AFTER:
        print("STALLED", placed["n"], flush=True)
        time.sleep(900)
    return oid
book.place = place
real_write = card.write
def write(*a, **k):
    if WHERE == "card":
        print("STALLED card", flush=True)
        time.sleep(900)
    return real_write(*a, **k)
card.write = write
now = datetime.fromisoformat("@NOW@")
print("STARTED", flush=True)
r = loop.run(con, now, Path(r"@DATA@"))
print("DONE", json.dumps(r, default=str)[:300], flush=True)
'''


def _run_child(script: Path, ready: Tuple[str, ...], timeout: float = 120.0) -> Tuple[subprocess.Popen, str]:
    p = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(REPO))
    line, t0 = "", time.time()
    while time.time() - t0 < timeout:
        line = p.stdout.readline().strip()
        if any(line.startswith(r) for r in ready) or p.poll() is not None:
            break
    return p, line


def _kill9(p: subprocess.Popen) -> bool:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, text=True)
    try:
        p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        return False
    return True


def prepare_close(env: "Env", day: date) -> None:
    """Everything the loop waits for on `day`: the closes arrived, the book marked. Leaves the store closed (a child will hold it)."""
    from pflab.paper import book
    arrive(env, day)
    book.catch_up(env.cur(), day, dt(day, 21, 10))
    release_store(env)


def release_store(env: "Env") -> None:
    """Close every connection of this process to the store (the runtime's cursors with it), so a child process can hold it."""
    import gc
    try:
        env.con.close()
    except Exception:
        pass
    env.con = None
    env.rt = None
    gc.collect()


@drill("kill9", 20, connect=True)
def drill_kill9(env: "Env", c: Check) -> None:
    """(1) a process holding the store is killed with a job 'running' and a transaction open: the store reopens, committed rows stay, the dead run is reaped. (2) the close loop is killed
    mid-orders: the restarted app recovers: one core_runs row for the day, no double orders, no decision without its order, nothing half-written."""
    from pflab.core import loop
    from pflab.service import jobs
    now = dt(env.start, 10)
    # ---- part 1: the job and the transaction
    env.con.close()
    env.con = None
    gc = env.dir / "gc.py"
    gc.write_text(JOB_KILL_SCRIPT.replace("@REPO@", str(REPO)).replace("@SRC@", str(SRC)).replace("@PM@", str(env.pm)).replace("@DATA@", str(env.data)).replace("@NOW@", now.isoformat()), encoding="utf-8")
    p, line = _run_child(gc, ("RUNNING",), 90)
    c.ok(line == "RUNNING", f"the child process holds the store, a job is 'running' and a transaction is open (pid {p.pid})", "tools/drills_s81.py JOB_KILL_SCRIPT")
    if line != "RUNNING":
        c.note("child stderr: " + (p.stderr.read() if p.poll() is not None else "")[-300:])
        return
    c.ok(_kill9(p), f"killed with taskkill /F (exit {p.returncode})", "")
    t1 = time.time()
    try:
        env.connect()
        c.ok(True, f"the store reopened after the kill in {time.time() - t1:.1f} s (WAL replayed)", "pm/store.py")
    except Exception as e:
        c.ok(False, f"the store did not reopen after kill -9: {type(e).__name__}: {str(e)[:160]}", "pm/store.py connect / DuckDB WAL")
        return
    cur = env.cur()
    n_ok = cur.execute("SELECT count(*) FROM drill_wal WHERE note='committed'").fetchone()[0]
    n_un = cur.execute("SELECT count(*) FROM drill_wal WHERE note='uncommitted'").fetchone()[0]
    c.ok(n_ok == 1000 and n_un == 0, f"mid-write recovery: {n_ok} committed rows kept, {n_un} uncommitted rows gone", "DuckDB WAL")
    c.ok(cur.execute("SELECT count(*) FROM job_runs WHERE job='catch_up' AND status='running'").fetchone()[0] == 1, "the dead process left its job 'running'", "")
    resume = now + timedelta(minutes=25)
    env.open_app(resume)
    row = cur.execute("SELECT status, detail FROM job_runs WHERE job='catch_up' ORDER BY run_id LIMIT 1").fetchone()
    c.ok(row[0] == "failed" and "abandoned" in (row[1] or ""), f"on start the dead run is marked: {row}", "service/jobs.py reap_at_start")
    ctx = jobs.Ctx(cur, resume, env.pm, env.data, REPO, sys.executable, env.rt.secrets)
    due, why = jobs.is_due(ctx, jobs.REGISTRY["catch_up"])
    c.ok(due, f"the job is due again at once: {why}", "service/jobs.py is_due")
    w = env.world()
    c.says(w["pulse"].get("catch_up", {}).get("off") or "")
    c.ok(bool(w["pulse"].get("catch_up", {}).get("off")), "the World says the app was off from the last beat to now", "app/world.py")
    # ---- part 2: the close loop killed in the middle of placing its orders
    cur = ctx = w = None
    thu = env.start
    env.clock.set(dt(thu, 6))
    for t in day_times(thu)[:5]:                                    # 07 .. 18: before the closes arrive
        env.step(t)
    n_dec0 = env.cur().execute("SELECT count(*) FROM paper_decisions").fetchone()[0]          # the seed day's own close (placed at 07:00) is already in the store
    n_ord0 = env.cur().execute("SELECT count(*) FROM paper_orders").fetchone()[0]
    prepare_close(env, thu)
    when = dt(thu, 21, 30)
    sc = env.dir / "loopkill.py"
    sc.write_text(LOOP_KILL_SCRIPT.replace("@REPO@", str(REPO)).replace("@SRC@", str(SRC)).replace("@PM@", str(env.pm)).replace("@DATA@", str(env.data)).replace("@NOW@", when.isoformat()).replace("@AFTER@", "1").replace("@WHERE@", "orders"), encoding="utf-8")
    p, line = _run_child(sc, ("STALLED", "DONE"), 180)
    if not line.startswith("STALLED"):
        c.note(f"the loop did not stall after its first order (it placed fewer than two orders, or crashed): '{line}' {(p.stderr.read() if p.poll() is not None else '')[-300:]}")
        if p.poll() is None:
            _kill9(p)
        c.ok(False, "the loop placed at least two orders on the synthetic profile (so a kill can fall between them)", "tools/drills_s81.py base profile (holdings vs allocation target)")
        return
    c.ok(_kill9(p), f"the close loop was killed with taskkill /F after its first order ({line})", "")
    env.connect()
    env.open_app(dt(thu, 21, 40))
    cur = env.cur()
    day_runs = cur.execute("SELECT count(*) FROM core_runs_s80 WHERE day=?", [thu]).fetchone()[0]
    n_dec1 = cur.execute("SELECT count(*) FROM paper_decisions").fetchone()[0]
    n_ord1 = cur.execute("SELECT count(*) FROM paper_orders").fetchone()[0]
    new_dec, new_ord = n_dec1 - n_dec0, n_ord1 - n_ord0
    c.note(f"after the kill: {day_runs} core_runs row(s) for {thu}, {new_dec} new decision(s), {new_ord} new order(s)")
    half = (new_dec != new_ord) or (new_ord > 0 and day_runs == 0)
    c.ok(not half, f"nothing half-written survived the kill: {new_dec} decisions, {new_ord} orders, {day_runs} run row(s) for {thu} (a decision without its order, or orders with no run record, is a half-written close)", "core/loop.py (placing the orders and the run row must be one transaction)")
    # the restarted app finishes the day
    r = env.safe("loop", loop.run, env.cur(), dt(thu, 21, 45), env.data)
    c.note(f"the restarted app's loop pass: {str(r)[:200]}")
    runs = [str(x[0]) for x in core_rows(env.cur())]
    seed = str(__import__("pflab.markets", fromlist=["x"]).get("IN").previous_session(thu))
    c.ok(runs == [seed, str(thu)], f"after the restart the loop has closed {thu} exactly once (the seed day's close before it): {runs}", "core/loop.py")
    ords2 = env.cur().execute("SELECT isin, side, count(*) FROM paper_orders WHERE placed_at >= ? GROUP BY 1, 2 HAVING count(*) > 1", [dt(thu, 21)]).fetchall()
    dec2 = env.cur().execute("SELECT count(*) FROM paper_decisions").fetchone()[0]
    ordn = env.cur().execute("SELECT count(*) FROM paper_orders").fetchone()[0]
    c.ok(not ords2 and dec2 == ordn, f"no double orders after the restart: duplicates {ords2}; {dec2} decisions, {ordn} orders", "core/loop.py")
    c.ok(env.cur().execute("SELECT count(*) FROM core_runs_s80").fetchone()[0] == 2, "two core_runs rows in all (the seed day and Thursday): one per day", "core/loop.py")
    # the next day goes on as normal
    fri = __import__("pflab.markets", fromlist=["x"]).get("IN").next_session(thu)
    env.clock.set(dt(thu, 23))
    run_days(env, fri, fri)
    runs = [str(x[0]) for x in core_rows(env.cur())]
    c.ok(runs == [seed, str(thu), str(fri)], f"the next close ran as normal: {runs}", "core/loop.py")
    # ---- part 3: killed after the run row is written, during the card
    cur = r = None
    mon =__import__("pflab.markets", fromlist=["x"]).get("IN").next_session(fri)
    env.clock.set(dt(fri, 23, 30))
    for t in day_times(mon)[:5]:
        env.step(t)
    prepare_close(env, mon)
    sc.write_text(LOOP_KILL_SCRIPT.replace("@REPO@", str(REPO)).replace("@SRC@", str(SRC)).replace("@PM@", str(env.pm)).replace("@DATA@", str(env.data)).replace("@NOW@", dt(mon, 21, 30).isoformat()).replace("@AFTER@", "99").replace("@WHERE@", "card"), encoding="utf-8")
    p, line = _run_child(sc, ("STALLED", "DONE"), 180)
    if line.startswith("STALLED"):
        c.ok(_kill9(p), "the close loop was killed during the card write (after its run row)", "")
        env.connect()
        env.open_app(dt(mon, 21, 40))
        cur = env.cur()
        n = cur.execute("SELECT count(*) FROM core_runs_s80 WHERE day=?", [mon]).fetchone()[0]
        c.ok(n == 1, f"the run row for {mon} survived the kill ({n})", "core/loop.py")
        r = env.safe("loop", loop.run, cur, dt(mon, 21, 45), env.data)
        c.ok(r is not None and "skipped" in r, f"the restarted loop does not decide {mon} again: {str(r)[:120]}", "core/loop.py")
        card_n = cur.execute("SELECT count(*) FROM core_cards_s80 WHERE day=?", [mon]).fetchone()[0]
        c.note(f"the book card for {mon} after the kill: {card_n} (a card lost to a kill between the run row and the card is rewritten by the next close's card, which is compared with the last)")
    else:
        c.note(f"the card stage was not reached: '{line}'")
        if p.poll() is None:
            _kill9(p)
    clean(env, c)


# --- the child and the parent -----------------------------------------------------------------------------------------------------------------

def child_main(a) -> int:
    started = time.time()
    run_root, base = Path(a.run_dir), Path(a.base)
    res = {"name": a.drill, "status": "ERROR", "passed": False, "evidence": [], "world_says": "", "findings": [], "steps": [], "seconds": 0}
    c = Check(a.drill)
    env = None
    try:
        env = Env(a.drill, run_root, base, connect=getattr(DRILLS[a.drill], "connect", True))
        DRILLS[a.drill](env, c)
        res = c.result(started)
        res["exceptions"] = env.exceptions[:20]
        res["logged_errors"] = env.catcher.records[:20]
    except BaseException:
        tb = traceback.format_exc()
        res = c.result(started, "ERROR")
        res["evidence"].append("ERROR: the drill itself crashed: " + " | ".join(l.strip() for l in tb.strip().splitlines()[-5:])[:600])
        res["findings"].append({"what": "drill crashed: " + tb.strip().splitlines()[-1][:200], "where": "tools/drills_s81.py or the system under test", "how": f"python tools/drills_s81.py run --only {a.drill}",
                                "trace": tb[-1800:]})
    Path(a.out).write_text(json.dumps(res, default=str, indent=1), encoding="utf-8")
    sys.stdout.flush()
    os._exit(0)


def parent_run(a) -> int:
    run_root = SCRATCH / (a.run_name or datetime.now().strftime("run_%m%d_%H%M"))
    run_root.mkdir(parents=True, exist_ok=True)
    start = date.fromisoformat(a.start) if a.start else DEFAULT_START
    base = run_root / "base"
    t0 = time.time()
    print(f"[drills] building the base profile at {base} (start Thursday {start}) ...", flush=True)
    r = subprocess.run([sys.executable, str(Path(__file__)), "base", "--base", str(base), "--start", str(start)], capture_output=True, text=True, cwd=str(REPO))
    if r.returncode != 0 or not (base / "meta.json").exists():
        print(r.stdout[-1500:], r.stderr[-2500:])
        print("[drills] FAILED to build the base profile")
        return 2
    print(f"[drills] base ready in {time.time() - t0:.0f} s", flush=True)
    names = [n for n in (a.only.split(",") if a.only else list(ORDER))]
    names = [n for n in names if n in DRILLS]

    def one(n: str) -> dict:
        out = run_root / f"{n}.json"
        t1 = time.time()
        cmd = [sys.executable, str(Path(__file__)), "child", "--drill", n, "--base", str(base), "--run-dir", str(run_root), "--out", str(out)]
        timeout = float(getattr(DRILLS[n], "minutes", 20.0)) * 60
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO), timeout=timeout)
            res = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"name": n, "status": "ERROR", "passed": False, "evidence": [f"ERROR: child exit {p.returncode}: {(p.stderr or p.stdout)[-400:]}"],
                                                                                    "world_says": "", "findings": [{"what": "drill child produced no result", "where": "tools/drills_s81.py", "how": f"run --only {n}"}], "steps": [], "seconds": 0}
        except subprocess.TimeoutExpired:
            res = {"name": n, "status": "FAIL", "passed": False, "evidence": [f"FAIL: the drill did not finish in {timeout / 60:.0f} minutes (something stalled)"], "world_says": "",
                   "findings": [{"what": f"drill {n} stalled for more than {timeout / 60:.0f} minutes", "where": "see progress.log in the drill's folder", "how": f"python tools/drills_s81.py run --only {n}"}], "steps": [], "seconds": timeout}
        res["seconds"] = round(time.time() - t1, 1)
        print(f"[drills] {res['status']:5s} {n:20s} {res['seconds']:6.1f}s  {res['evidence'][-1][:100] if res['evidence'] else ''}", flush=True)
        return res
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, int(a.jobs))) as ex:       # each drill has its own clone of the profile: they can run side by side
        results = list(ex.map(one, names))
    report(results, a)
    return 0 if all(r["status"] in ("PASS", "OFF") for r in results) else 1


def report(results: list, a) -> None:
    out = Path(a.out) if a.out else SCRATCH / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "results": results}, default=str, indent=1), encoding="utf-8")
    print("\n%-20s %-6s %7s  %s" % ("drill", "result", "seconds", "what the World screen says"))
    for r in results:
        print("%-20s %-6s %7.1f  %s" % (r["name"], r["status"], r["seconds"], (r.get("world_says") or "")[:110]))
        for e in r["evidence"]:
            if e.startswith("FAIL") or e.startswith("ERROR") or e.startswith("OFF"):
                print("      " + e[:200])
        for s in r.get("steps", []):
            print("      step %-34s %s%s" % (s["name"], s["status"], ("  " + [e for e in s["evidence"] if e.startswith("OFF")][0][:120]) if s["status"] == "OFF" and any(e.startswith("OFF") for e in s["evidence"]) else ""))
    frag = Path(a.findings) if getattr(a, "findings", None) else out.with_suffix(".md")
    lines = ["## Drills and accelerated run (tools/drills_s81.py, %s)" % datetime.now().strftime("%Y-%m-%d %H:%M"), "",
             "| drill | result | seconds | evidence |", "|---|---|---|---|"]
    for r in results:
        why = next((e[:110] for e in r["evidence"] if e.startswith("OFF")), "") if r["status"] == "OFF" else f"{sum(1 for e in r['evidence'] if e.startswith('ok:') or '] ok:' in e[:70])} checks ok"
        lines.append(f"| {r['name']} | {r['status']} | {r['seconds']} | {why.replace('|', '/')} |")
    steps = [(r["name"], s) for r in results for s in r.get("steps", [])]
    if steps:
        lines += ["", "| accelerated step | result | note |", "|---|---|---|"]
        for _n, s in steps:
            note = next((e[:150] for e in s["evidence"] if e.startswith("OFF") or e.startswith("FAIL") or e.startswith("ERROR")), "")
            lines.append(f"| {s['name']} | {s['status']} | {note.replace('|', '/')} |")
    lines.append("")
    n = 0
    for r in results:
        for f in r.get("findings", []):
            n += 1
            lines += [f"### D{n}. [{r['name']}] {f['what']}", f"- where: {f['where']}", f"- how to reproduce: `{f['how']}`", ""]
    frag.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {out} and {frag}")


def steps_listing() -> int:
    for name, _fn, applicable in ACCELERATED_STEPS:
        ok, why = applicable(None)
        print(f"{name:36s} {'ON ' if ok else 'OFF'}  {why}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run")
    r.add_argument("--only", default="")
    r.add_argument("--out", default="")
    r.add_argument("--findings", default="")
    r.add_argument("--start", default="")
    r.add_argument("--run-name", dest="run_name", default="")
    r.add_argument("--jobs", type=int, default=6, help="drills run side by side (each on its own clone)")
    sp.add_parser("list")
    sp.add_parser("steps")
    b = sp.add_parser("base")
    b.add_argument("--base", required=True)
    b.add_argument("--start", required=True)
    ch = sp.add_parser("child")
    for k in ("--drill", "--base", "--run-dir", "--out"):
        ch.add_argument(k, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "list":
        print("\n".join(f"{n} ({getattr(DRILLS[n], 'minutes', 20)} min)" for n in ORDER))
        return 0
    if a.cmd == "steps":
        return steps_listing()
    if a.cmd == "base":
        print(json.dumps(build_base(Path(a.base), date.fromisoformat(a.start))))
        return 0
    if a.cmd == "child":
        return child_main(a)
    return parent_run(a)


if __name__ == "__main__":
    sys.exit(main())
