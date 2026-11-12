"""S84 replays and drills of the thinking loop (T9). Development only: a SYNTHETIC rupee profile (tools/drills_s81.py) with REAL bars and the real public headlines of the Nvidia week laid over it,
and a SCRIPTED model (no paid call) unless `real` is asked for.

    python tools/replays_s84.py data                       # real bars into S84_REPLAY_DATA (default D:\\s84_scratch\\replay\\data): a fresh Yahoo download of the US names, the app's/workshop's NSE bars (read only)
    python tools/replays_s84.py replay nvda_held           # (i)   NVDA held at 8% of the US sub-book: a case by the IST morning of 9 Nov, class "damage", the sale at the next US open
    python tools/replays_s84.py replay nvda_not_held       # (ii)  not held: an S&P 500 shock, "wait for the board's decision", no buy while pending or making new lows
    python tools/replays_s84.py replay ather               # (iii) Ather Energy, a missed run: a skip on the first day it closed near Rs 1,400, replayed to 11 Nov
    python tools/replays_s84.py drills                     # (iv)  the synthetic drills of the prompt's list
    python tools/replays_s84.py real --cap 60              # the ONE real path: a real Sonnet read and a real Opus decision on replay (i), on a copy of the app's store (see `real_main`)
    python tools/replays_s84.py all                        # every scripted replay and drill; the report goes to S84_REPLAY_OUT (default D:\\s84_scratch\\replay\\out)

Point in time is part of what is tested: the real bars and the headlines are REVEALED to the world a session at a time (a US bar after its close, an Indian bar after the NSE files arrive, a
headline at its IST time); the world never holds a row dated after its clock.
No name or amount of the investor's appears in any output of this tool: the rupee profile is the drills' own synthetic book, and the real path prints counts and classes only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("S81_SRC") or (REPO / "src"))
for _p in (SRC, REPO / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
REAL = Path(os.environ.get("S84_REPLAY_DATA", r"D:\s84_scratch\replay\data"))
OUT = Path(os.environ.get("S84_REPLAY_OUT", r"D:\s84_scratch\replay\out"))
WORK = Path(os.environ.get("S84_REPLAY_WORK", r"D:\s84_scratch\replay\work"))
APP_DATA = Path(os.environ.get("S84_APP_DATA", r"D:\PortfolioLabApp\data"))             # read only
WORKSHOP_DATA = Path(os.environ.get("S84_WORKSHOP_DATA", r"D:\portfolio_lab\data"))      # read only

NVDA = {"symbol": "NVDA", "name": "NVIDIA Corporation", "cik": 1045810}
NAMES_FILE = Path(os.environ.get("S84_REPLAY_NAMES", r"D:\s84_scratch\replay\names.json"))     # the Indian name of replay (iii) is kept OUT of git (it is on his list): {"symbol","isin","name","sector"}


def _names() -> dict:
    try:
        return json.loads(NAMES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"symbol": "SYNMISSED", "isin": "INE9S0A01011", "name": "SYNMISSED Limited", "sector": "Auto"}          # no file: a placeholder (the real-bars replay then cannot run)


ATHER = _names()
REAL_US = ("NVDA", "SPY", "QQQ", "XLK")                        # US bars laid over the profile (data/us/raw)
REAL_GLOBAL = {"^GSPC": "US_SP500", "^IXIC": "US_NASDAQ", "CL=F": "BRENT_FUT"}                  # data/global/<name>
SOURCE = "press reports"

# The real public headlines of the Nvidia week (the prompt of 2026-11-12), with the IST time each becomes visible. A US evening item is visible in the IST morning after it.
# kind/severity are what the (scripted) classifier gives them: `leadership_crisis` is the S84 kind (kgkind), `regulatory_action` a class action.
HEADLINES = [
    {"key": "n1", "ts": datetime(2026, 11, 9, 6, 30), "us_day": "Sun 8 Nov", "kind": "leadership_crisis", "severity": "high",
     "headline": "Nvidia chief executive tells staff of a relationship with a former executive of a company US officials suspect of spying for China; the board opens an investigation"},
    {"key": "n2", "ts": datetime(2026, 11, 10, 0, 30), "us_day": "Mon 9 Nov", "kind": "regulatory_action", "severity": "medium",
     "headline": "Shareholder class action filed against Nvidia over its disclosures about its chief executive"},
    {"key": "n3", "ts": datetime(2026, 11, 12, 3, 30), "us_day": "Wed 11 Nov (after hours)", "kind": "leadership_crisis", "severity": "high",
     "headline": "Nvidia chief executive faces reports of a second relationship and the board is said to be preparing to oust him; the shares trade about 8% lower after hours"},
]


def _drills():
    if "drills_s81" in sys.modules:
        return sys.modules["drills_s81"]
    spec = importlib.util.spec_from_file_location("drills_s81", REPO / "tools" / "drills_s81.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["drills_s81"] = m
    spec.loader.exec_module(m)
    return m


D = _drills()
from replays_s84_model import (NVDA_SYMBOL, Scenario, ScriptedClient, ScriptMsg, ather_answers, case_of, nvda_held_answers, nvda_not_held_answers, words)       # noqa: E402,F401


# --- real data ------------------------------------------------------------------------------------------------------------------------------------------------------------------

def build_real_data(out: Path = REAL, app_data: Path = APP_DATA, workshop: Path = WORKSHOP_DATA, fetch: Optional[Callable] = None) -> dict:
    """The real bars the replays lay over the profile, written ONLY under `out`: the US names from a fresh Yahoo download (the repo's own `data/us_prices.fetch`), the Nifty indices and the USD/INR
    close from the app's data (read only), and the missed-run name (NAMES_FILE) with a few auto peers in the panel's layout (the workshop's panel to its last day, then the app's bhavcopy files)."""
    import pandas as pd
    from pflab.data import us_prices as up
    fetch = fetch or up.fetch
    res: Dict[str, object] = {}
    for d in ("us/raw", "global", "indices", "panel"):
        (out / d).mkdir(parents=True, exist_ok=True)
    for sym, rel in {**{s: f"us/raw/{s}" for s in REAL_US}, **{k: f"global/{v}" for k, v in REAL_GLOBAL.items()}}.items():
        for attempt in range(3):
            try:
                df = fetch(sym)
                df.to_parquet(out / f"{rel}.parquet", index=False)
                res[sym] = (len(df), str(df["date"].min()), str(df["date"].max()))
                break
            except Exception as e:
                res[sym] = repr(e)[:120]
                time.sleep(2)
        time.sleep(0.4)
    if (app_data / "global" / "FX_USDINR.parquet").exists():
        shutil.copy(app_data / "global" / "FX_USDINR.parquet", out / "global" / "FX_USDINR.parquet")
    for k in ("NIFTY500_TRI", "NIFTY50_PRICE", "NIFTY50_TRI"):
        p = app_data / "indices" / f"{k}.parquet"
        if p.exists():
            shutil.copy(p, out / "indices" / f"{k}.parquet")
    syms = [ATHER["symbol"], "NIFTYBEES", "HEROMOTOCO", "BAJAJ-AUTO", "TVSMOTOR", "EICHERMOT", "M&M"]
    panel = pd.read_parquet(workshop / "panel" / "prices.parquet", filters=[("symbol", "in", syms)])
    panel = panel[panel["date"].astype(str) >= "2025-06-01"].copy()
    panel["date"] = pd.to_datetime(panel["date"]).dt.date
    last = max(panel["date"])
    extra = []
    for f in sorted((app_data / "bhavcopy" / "2026").glob("*.parquet")):
        d = pd.to_datetime(f.stem).date()
        if d > last:
            b = pd.read_parquet(f)
            b = b[b["symbol"].isin(syms) & (b["series"] == "EQ")].copy()
            b["date"] = d
            for c in panel.columns:
                if c not in b.columns:
                    b[c] = None
            b["adj_close"], b["adj_open"], b["adj_factor"], b["dividend"], b["instrument_type"] = b["close"], b["open"], 1.0, 0.0, "STK"
            extra.append(b[panel.columns])
    if extra:
        panel = pd.concat([panel] + extra, ignore_index=True)
    panel.sort_values(["symbol", "date"]).to_parquet(out / "panel" / "prices.parquet", index=False)
    res["panel"] = (len(panel), str(panel["date"].max()))
    return res


def _read(rel: str, root: Path = REAL):
    import pandas as pd
    p = root / rel
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


# --- the world: the drills' profile with real bars laid over it, revealed a session at a time ------------------------------------------------------------------------------------

REVEAL: Dict[str, object] = {"on": False, "now": None, "root": REAL, "india": {}}          # patched into sync_data_files and Env.step


def reveal(env, now: Optional[datetime] = None) -> dict:
    """Write the real files into the world's data folder, cut at what is public at `now` (point in time): a US bar from its close + 30 minutes, the Nifty from the NSE files' arrival, the USD/INR
    close of the latest US day. Returns the cut dates."""
    import pandas as pd
    from pflab.us import clock
    now = now or env.clock.t
    root: Path = REVEAL["root"]                                                    # type: ignore[assignment]
    us_to = clock.session_closed_by(now, 30)
    in_to = D.available_through(now)
    cuts = {"us": str(us_to), "india": str(in_to)}
    for sym in REAL_US:
        df = _read(f"us/raw/{sym}.parquet", root)
        if df is not None:
            p = env.data / "us" / "raw" / f"{sym}.parquet"
            p.parent.mkdir(parents=True, exist_ok=True)
            df[df["date"] <= us_to].to_parquet(p, index=False)
    for sym, name in REAL_GLOBAL.items():
        df = _read(f"global/{name}.parquet", root)
        if df is not None:
            (env.data / "global").mkdir(parents=True, exist_ok=True)
            df[df["date"] <= us_to].to_parquet(env.data / "global" / f"{name}.parquet", index=False)
    fx = _read("global/FX_USDINR.parquet", root)
    if fx is not None:
        fx[fx["date"] <= us_to].to_parquet(env.data / "global" / "FX_USDINR.parquet", index=False)
    for k in ("NIFTY500_TRI", "NIFTY50_PRICE", "NIFTY50_TRI"):
        df = _read(f"indices/{k}.parquet", root)
        if df is not None:
            (env.data / "indices").mkdir(parents=True, exist_ok=True)
            df[df["date"] <= in_to].to_parquet(env.data / "indices" / f"{k}.parquet", index=False)
    pan = _read("panel/prices.parquet", root)
    if pan is not None and REVEAL["india"]:
        keep = pan[(pan["symbol"].isin(list(REVEAL["india"]))) & (pan["date"] <= in_to)]                                   # type: ignore[arg-type]
        p = env.data / "panel" / "prices.parquet"
        have = pd.read_parquet(p) if p.exists() else None
        if have is not None:
            have = have[~have["symbol"].isin(list(REVEAL["india"]))]                                                       # type: ignore[arg-type]
            have["date"] = pd.to_datetime(have["date"]).dt.date
            keep = keep.assign(date=keep["date"])
            keep = pd.concat([have, keep[[c for c in have.columns if c in keep.columns]]], ignore_index=True)
        p.parent.mkdir(parents=True, exist_ok=True)
        keep.to_parquet(p, index=False)
    return cuts


_orig_sync = D.sync_data_files


def _sync_then_reveal(con, data: Path) -> None:
    _orig_sync(con, data)
    if REVEAL["on"] and REVEAL.get("env") is not None:
        reveal(REVEAL["env"], REVEAL["now"])                                      # type: ignore[arg-type]


D.sync_data_files = _sync_then_reveal
_orig_step = D.Env.step


def _step(self, t, **kw):
    """Every step of the world's clock first publishes what is public at that time (and only that), then runs the app's loops."""
    REVEAL["now"], REVEAL["env"] = t, self
    if REVEAL["on"]:
        from pflab.us import clock
        cut = (str(clock.session_closed_by(t, 30)), str(D.available_through(t)))
        if getattr(self, "_cut", None) != cut:
            reveal(self, t)
            self._cut = cut
    return _orig_step(self, t, **kw)


D.Env.step = _step


def add_india_name(base: Path, start: date, name: dict, rows) -> int:
    """The Indian name (instrument, its closes before `start` in the store, those from `start` on held back to arrive with the NSE files). `rows`: a DataFrame date/close."""
    import pandas as pd
    from pflab.pm import store
    con = store.connect(base / "pm" / "ledger.duckdb")
    now0 = datetime.now()
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, ?, 'replay', ?) "
                "ON CONFLICT DO NOTHING", [name["isin"], name["symbol"], name["name"], name["sector"], now0])
    r = rows.copy()
    r["isin"], r["series"], r["source"], r["fetched_at"] = name["isin"], "EQ", "nse_bhavcopy", now0
    before, after = r[r["date"] < start], r[r["date"] >= start]
    con.register("_b", before[["isin", "date", "close", "series", "source", "fetched_at"]])
    con.execute("INSERT INTO prices SELECT isin, date, close, series, source, fetched_at FROM _b")
    con.unregister("_b")
    held = pd.read_parquet(base / "held_prices.parquet")
    add = after[["isin", "date", "close", "series", "source", "fetched_at"]]
    pd.concat([held, add], ignore_index=True).to_parquet(base / "held_prices.parquet")
    con.execute("CHECKPOINT")
    con.close()
    return len(before) + len(after)


def shock_held_prices(base: Path, shocks) -> None:
    """Designed falls and rises in the synthetic closes held back from the profile: `shocks` = [(isin, from_day, factor)]: every close of the ISIN from `from_day` on is multiplied by `factor`
    (they arrive with the NSE files, a session at a time, so the world never knows before its clock)."""
    import pandas as pd
    p = base / "held_prices.parquet"
    held = pd.read_parquet(p)
    held["date"] = pd.to_datetime(held["date"]).dt.date
    for isin, frm, factor in shocks:
        m = (held["isin"] == isin) & (held["date"] >= frm)
        held.loc[m, "close"] = (held.loc[m, "close"] * float(factor)).round(4)
    held.to_parquet(p)


def make_world(name: str, start: date, *, india: Optional[dict] = None, run_root: Optional[Path] = None, rebuild: bool = False, shocks=None, tag: str = "", real_bars: bool = True):
    """A world for one replay: the drills' synthetic profile seeded on the session before `start`, the real bars of `REAL_US` and the Nifty indices laid over it (revealed by the clock), and the Indian
    `india` name (a dict like ATHER) added with its real closes. Returns the connected `Env` (the app is not opened: `open_world`)."""
    tag = f"{start:%Y%m%d}" + (f"_{india['symbol']}" if india else "") + (f"_{tag}" if tag else "")
    base = WORK / f"base_{tag}"
    if rebuild or not (base / "meta.json").exists():
        D.build_base(base, start)
        if india:
            pan = _read("panel/prices.parquet")
            rows = pan[pan["symbol"] == india["symbol"]][["date", "close"]]
            add_india_name(base, start, india, rows)
        if shocks:
            shock_held_prices(base, shocks)
    REVEAL["india"] = {india["symbol"]} if india else set()
    REVEAL["on"] = bool(real_bars)
    env = D.Env(name, run_root or (WORK / "runs"), base)
    REVEAL["env"], REVEAL["now"] = env, D.dt(start, 6)
    env.base_meta = SimpleNamespace(start=start, india=india)
    (env.data / "us").mkdir(parents=True, exist_ok=True)
    (env.data / "us" / "cik_map.json").write_text(json.dumps({NVDA["symbol"]: NVDA["cik"]}), encoding="utf-8")
    if real_bars:
        reveal(env, D.dt(start, 6))
    return env


def open_world(env, start: date) -> None:
    env.open_app(D.dt(start, 6))


def nvda_key(con) -> str:
    from pflab.us import instruments as uins
    return uins.key_for(con, NVDA["symbol"], {NVDA["symbol"]: NVDA["cik"]})


def add_headlines(con, key: str, headlines: Optional[list] = None, *, now: Optional[datetime] = None) -> int:
    """The real headlines as event rows of the graph (`kg2_event`), source "press reports": each row's `ts` is its IST visibility time, so a world at an earlier clock must not read it (the harness
    adds a headline only when its time has come, `release_headlines`; this function is the single writer). The kind is the S84 `leadership_crisis` when the classifier has it, else the nearest
    thesis kind with a note in the ref."""
    from pflab.kg2 import classify
    n = 0
    node = con.execute("SELECT 1 FROM kg2_node WHERE isin=?", [key]).fetchone()
    if not node:
        con.execute("INSERT INTO kg2_node VALUES (?,?,?,?,?,?)", [key, NVDA["name"], NVDA["symbol"], "replay", SOURCE, date(2026, 11, 6)])
    for h in headlines or HEADLINES:
        kind = h["kind"] if h["kind"] in classify.KINDS else ("fraud_investigation" if h["kind"] == "leadership_crisis" else "other")
        eid = f"press:{NVDA['symbol']}:{h['key']}"
        if con.execute("SELECT 1 FROM kg2_event WHERE event_id=?", [eid]).fetchone():
            continue
        con.execute("INSERT INTO kg2_event VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [eid, key, SOURCE, f"{eid}|{h['us_day']}" + ("" if kind == h["kind"] else "|kind stands in for leadership_crisis"), h["ts"], h["ts"].date(), kind, h["severity"],
                    h["headline"], "replay", "the headline names the company", eid, "press report time (IST)"])
        con.execute("INSERT INTO kg2_event_class VALUES (?,?,?,?,?,?)", [eid, kind, h["severity"], "scripted", "replay", h["ts"]])
        n += 1
    return n


def release_headlines(env, now: datetime, key: str) -> int:
    """Add the headlines whose time is on or before `now` (the world never holds a later one)."""
    due = [h for h in HEADLINES if h["ts"] <= now]
    return add_headlines(env.cur(), key, due) if due else 0


def inject_us_position(con, now: datetime, day: date, symbol: str, key: str, share: float, root: Path) -> dict:
    """NVDA held at `share` of the US sub-book on `day` (the pick the system would have bought): lots bought out of the sub-book's SPY shares and cash at the day's close, so the sub-book's value is
    unchanged. Returns the quantities. The shares are bought `day` itself; held for under 24 months, a sale is a short-term gain under the Indian rules (us/tax.py)."""
    from pflab.us import book, data as usdata, instruments as uins
    from pflab.pm.store import next_id
    uins.ensure(con, symbol, NVDA["name"], etf=False, ciks={symbol: NVDA["cik"]}, now=now)
    bars = usdata.load([symbol, "SPY"], root)
    px = usdata.last_on_or_before(bars[symbol], day)["close"]
    pos = book.positions(con, day)
    spy_key = next((k for k in pos if (uins.symbol_of(con, k) or "") == "SPY"), None)
    marks = {k: (usdata.last_on_or_before(bars.get(uins.symbol_of(con, k) or "", None), day) or {"close": 0.0})["close"] for k in pos}
    total = book.cash(con, day) + sum(q * marks[k] for k, q in pos.items())
    want_usd = share * total
    qty = want_usd / px
    cash = book.cash(con, day)
    take_cash = min(cash * 0.9, want_usd)
    need_from_spy = want_usd - take_cash
    if need_from_spy > 1e-6 and spy_key:
        spy_px = marks[spy_key]
        sell_q = min(pos[spy_key], need_from_spy / spy_px)
        left = sell_q
        for lot in con.execute("SELECT lot_id, qty FROM us_lots_s81 WHERE isin=? AND qty > 0 ORDER BY acq_date, lot_id", [spy_key]).fetchall():
            u = min(left, lot[1])
            con.execute("UPDATE us_lots_s81 SET qty=qty-? WHERE lot_id=?", [u, lot[0]])
            left -= u
            if left <= 1e-12:
                break
        take_cash += sell_q * spy_px
    book.add_cash(con, now, day, -take_cash, "replay_inject", f"{symbol} lot at the {day} close")
    lot_id = next_id(con, "us_lots_s81", "lot_id")
    con.execute("INSERT INTO us_lots_s81 VALUES (?,?,?,?,?,?,?,?,?)", [lot_id, key, symbol, day, qty, px, None, None, "replay"])
    return {"symbol": symbol, "key": key, "qty": round(qty, 4), "price": px, "usd": round(qty * px, 2), "share_target": share}


def add_skip(con, market: str, isin: str, symbol: str, why: str, day: date) -> int:
    """A skipped idea (S83 `skips_s83`): the system looked at the name and passed."""
    from pflab.pm.store import next_id
    sid = next_id(con, "skips_s83", "skip_id")
    con.execute("INSERT INTO skips_s83 VALUES (?,?,?,?,?,?,?)", [sid, market, isin, symbol, why, day, f"replay:{day}"])
    return sid


# --- the day loop and what it saw ---------------------------------------------------------------------------------------------------------------------------------------------------

THINK_TABLES = {"signals": ("think_signals_s84", "signal_id"), "cases": ("think_cases_s84", "case_id"), "decisions": ("think_decisions_s84", "decision_id"),
                "options": ("think_options_s84", "option_id"), "steps": ("think_steps_s84", "step_id"), "freezes": ("think_freezes_s84", "freeze_id")}


def _maxids(con) -> dict:
    out = {}
    for k, (t, c) in THINK_TABLES.items():
        try:
            out[k] = con.execute(f"SELECT coalesce(max({c}), 0) FROM {t}").fetchone()[0]
        except Exception:
            out[k] = 0
    for k, (t, c) in {"us_orders": ("us_orders_s81", "order_id"), "us_trades": ("us_trades_s81", "trade_id"), "paper_orders": ("paper_orders", "order_id"), "paper_trades": ("paper_trades", "trade_id")}.items():
        try:
            out[k] = con.execute(f"SELECT coalesce(max({c}), 0) FROM {t}").fetchone()[0]
        except Exception:
            out[k] = 0
    return out


def snapshot_since(con, before: dict) -> dict:
    """What appeared in the store since `before` (the maximum ids): signals, cases, decisions, options, orders, trades, freezes."""
    from pflab.think import cases
    out: Dict[str, list] = {}
    try:
        out["signals"] = [(s["symbol"], s["signal"], round(s["value"], 3), round(s["threshold"], 3), s["status"]) for s in cases.signals(con) if s["signal_id"] > before["signals"]]
        cs = [c for c in cases._rows(con, "think_cases_s84", cases._CASE, "WHERE case_id > ?", [before["cases"]])]
        out["cases"] = [(c["case_id"], c["symbol"], c["state"], c["klass"], c["title"][:90]) for c in cs]
        out["decisions"] = [(d["case_id"], d["symbol"], d["rule_option"], d["model_option"], d["acted_option"], d["advisory"], d["reason"][:160]) for d in cases.decisions(con) if d["decision_id"] > before["decisions"]]
        out["options"] = [(o["case_id"], o["track"], o["symbol"], o["option"], round(o["worst_inr"]), round(o["likely_inr"]), round(o["best_inr"]), round(o["expected_inr"]), round(o["worst_pct_book"], 4), round(o["size_inr"]), o["chosen"])
                          for o in cases._rows(con, "think_options_s84", ("option_id", "case_id", "track", "symbol", "option", "worst_inr", "likely_inr", "best_inr", "expected_inr", "worst_pct_book", "size_inr", "chosen"),
                                               "WHERE option_id > ?", [before["options"]])]
        out["freezes"] = [(f["symbol"], str(f["until"]), f["until_event"], f["reason"][:100]) for f in cases._rows(con, "think_freezes_s84", ("freeze_id", "symbol", "until", "until_event", "reason"), "WHERE freeze_id > ?", [before["freezes"]])]
    except Exception as e:
        out["error"] = [f"{type(e).__name__}: {str(e)[:120]}"]
    try:
        out["us_orders"] = con.execute("SELECT order_id, placed_day, symbol, side, qty, amount_usd, status, fill_day, reason FROM us_orders_s81 WHERE order_id > ?", [before["us_orders"]]).fetchall()
        out["us_trades"] = con.execute("SELECT trade_id, day, symbol, side, qty, price_usd, charges_usd, realised_inr, tax_inr FROM us_trades_s81 WHERE trade_id > ?", [before["us_trades"]]).fetchall()
    except Exception:
        pass
    try:
        out["paper_orders"] = con.execute("SELECT * FROM paper_orders WHERE order_id > ?", [before["paper_orders"]]).fetchall()
    except Exception:
        pass
    return {k: v for k, v in out.items() if v}


def think_hook(env, t: datetime) -> Optional[dict]:
    """The thinking loop after a step: the wire's sweep (idempotent per market and session: the app's `think_loop` job calls the same function), so the replay does not depend on which job slot the
    scheduler picked. Returns the sweep's summary, or None while the wire module is not in this tree."""
    try:
        from pflab.think import wire
    except ImportError:
        return None
    if getattr(env, "real", False):
        return real_hook(env, t)
    try:
        return wire.sweep(env.cur(), t, env.data)
    except Exception:
        env.exceptions.append(f"{t:%a %d %b %H:%M} think sweep: " + traceback.format_exc(limit=3).strip().splitlines()[-1][:300])
        return None


REAL_LIMIT = {"calls": int(os.environ.get("S84_REAL_CALLS", "5"))}


def web_stub(con, question, now):
    return {"text": "A web check is not available in this replay (no paid search is made).", "cost_rupees": 0.0}


def real_hook(env, t: datetime) -> Optional[dict]:
    """The real path's loop: the wire watches (no thinking, no follow-up); only the NVDA case is thought through, ONCE, by the real model (Sonnet reads, Opus decides); any other case stays open."""
    from pflab.think import cases, session, wire
    con = env.cur()
    res = wire.sweep(con, t, env.data, think_cases=False, follow=False)
    out = {"watched": res.get("sessions")}
    for c in cases.open_cases(con):
        if c["symbol"] == NVDA["symbol"] and not any(st["step"] == "answer_ok" for st in cases.steps(con, c["case_id"])) and not getattr(env, "real_done", None):
            r = session.think_case(con, t, c["case_id"], root=env.data, web=web_stub)
            env.real_done = {"case_id": c["case_id"], "at": f"{t:%a %d %b %H:%M}", "result": r}
            out["thought"] = [c["case_id"]]
    return out


def wide_watch_standin(env, t: datetime, key: str, symbol: str = "NVDA") -> Optional[int]:
    """The S85 wide watch (a shock in any S&P 500 company) does not exist tonight: the watch looks at a skipped or screened name for a missed run only, and no US news source feeds it. This stands for
    it in replay (ii): when a headline on the name has become public, the signal is recorded and a case is opened on it once, exactly as the watch does for a held name."""
    from pflab.think import cases
    con = env.cur()
    rows = con.execute("SELECT event_id, ts, kind, severity, headline FROM kg2_event WHERE isin=? AND ts <= ? ORDER BY ts", [key, t]).fetchall()
    if not rows:
        return None
    fresh = [r for r in rows if not con.execute("SELECT 1 FROM think_signals_s84 WHERE isin=? AND detail_json LIKE ?", [key, f"%{r[0]}%"]).fetchone()]
    if not fresh:
        return None
    sids = [cases.record_signal(con, t, market="US", isin=key, symbol=symbol, signal="thesis_event", value=3.0 if r[3] == "high" else 2.0, threshold=1.0, surprise=3.0 if r[3] == "high" else 2.0,
                                exposure_inr=0.0, score=0.0, detail={"ref": r[0], "kind": r[2], "severity": r[3], "text": r[4], "standin": "wide watch (S85)"}) for r in fresh]
    ex = cases.case_for(con, key)
    if ex:
        for sid in sids:
            cases.set_signal(con, sid, case_id=ex["case_id"], status="joined")
        return ex["case_id"]
    cid = cases.open_case(con, t, market="US", kind="thesis_event", isin=key, symbol=symbol, title=f"{symbol}: {fresh[0][2].replace('_', ' ')} ({fresh[0][3]}): {fresh[0][4][:120]}", score=1.0, opened_by="replay (wide watch stand-in)",
                          signal_ids=sids)
    try:
        from pflab.think import session
        session.think_case(con, t, cid, root=env.data)
    except Exception:
        env.exceptions.append(f"{t:%a %d %b %H:%M} think (stand-in case): " + traceback.format_exc(limit=3).strip().splitlines()[-1][:300])
    return cid


def morning_watch(env, t: datetime) -> Optional[dict]:
    """FINDING of the Nvidia replay (S84): `think/wire.sweep` watches a US market only for a SESSION that has closed since the last pass, so news of a Sunday evening (US) is not looked at in the IST
    morning of Monday but after Monday's session closes, on Tuesday morning. This hook stands for the fix: in the IST morning (the first step of a day at or after 06:30) it also runs the watch in
    mode `us_morning` (everything since the last US close, after-hours news included) and thinks the cases that opens. Idempotent per (name, signal, day), so a day with a session is not doubled."""
    if not (6, 30) <= (t.hour, t.minute) < (12, 0) or getattr(env, "_mw_day", None) == t.date():
        return None
    env._mw_day = t.date()
    try:
        from pflab.think import session, watch
        from pflab.us import clock
        # `watch.run(mode="us_morning")` on a morning with no new session treats the morning as a past one (its clock is the session's IST morning, a weekend morning: Saturday 08:00): the
        # Sunday-evening news is invisible. The pass itself, called with the real `now`, sees it.
        res = watch._us_pass(env.cur(), t, clock.session_closed_by(t, 30), t, quotes=None, root=env.data, cfg=watch.settings()) or {}
        for cid in res.get("cases_opened") or []:
            session.think_case(env.cur(), t, cid, root=env.data)
        return res
    except Exception:
        env.exceptions.append(f"{t:%a %d %b %H:%M} morning watch: " + traceback.format_exc(limit=3).strip().splitlines()[-1][:300])
        return None


def run_window(env, first: date, last: date, *, key: Optional[str] = None, hook: Optional[Callable] = None, release: bool = True, only_from: Optional[datetime] = None) -> List[dict]:
    """Day by day, step by step: headlines released at their time, the app's loops, then the thinking loop; every step's news is kept. Returns the timeline."""
    out: List[dict] = []
    d = first
    while d <= last:
        for t in D.day_times(d):
            if only_from and t < only_from:
                continue
            if t < env.clock.t:
                continue
            if release and key:
                release_headlines(env, t, key)
            con = env.cur()
            before = _maxids(con)
            env.step(t)
            sw = think_hook(env, t)
            if hook:
                env.safe("hook", hook, env, t)
            if getattr(env, "morning_watch", False):
                morning_watch(env, t)
            if getattr(env, "standin_key", None):
                env.safe("standin", wide_watch_standin, env, t, env.standin_key)
            snap = snapshot_since(env.cur(), before)
            if snap or sw:
                out.append({"t": f"{t:%a %d %b %H:%M}", "sweep": {k: v for k, v in (sw or {}).items() if k in ("watched", "thought", "cases", "failed", "paused", "signals")}, **snap})
        d += timedelta(days=1)
    return out


# --- the three replays --------------------------------------------------------------------------------------------------------------------------------------------------------------

def install_cap(cap: float = 300.0) -> None:
    """The drills' trick: a cap with room for the real governor and the real egress gate; only the model is scripted (the scripted client is a test double, so the workshop's paid guard is not the road)."""
    from pflab.agents import analyst as an
    cfg = {"model": "claude-opus-5-5", "cap": float(cap), "ask_above": 1000.0, "usd_inr": 90.0, "adopted": True, "policy": {}, "acceptance": {}, "paper": {}, "tijori_to_analyst": True, "counted_since": None}
    an.config = lambda path=None: dict(cfg)


def arm(client) -> bool:
    """Put the scripted client behind the gateway; False while the gateway is not in this tree (the replay then shows only what code alone does)."""
    try:
        from pflab.llm import gateway
    except ImportError:
        return False
    gateway.set_client(client)
    return True


def disarm() -> None:
    try:
        from pflab.llm import gateway
        gateway.set_client(None)
    except Exception:
        pass


def _line(e: dict) -> List[str]:
    """One timeline entry as plain lines."""
    out = []
    for s in e.get("signals", []):
        out.append(f"  noticed: {s[0]} {s[1]} (value {s[2]} against {s[3]}), {s[4]}")
    for c in e.get("cases", []):
        out.append(f"  case #{c[0]} on {c[1]}: {c[2]}{' (' + c[3] + ')' if c[3] else ''}: {c[4]}")
    for o in e.get("options", []):
        out.append(f"  option [{o[1]}] case #{o[0]} {o[2]} {o[3]}: worst {o[4]:,} likely {o[5]:,} best {o[6]:,} expected {o[7]:,} (worst {100 * o[8]:.2f}% of the book, size {o[9]:,}){' <- chosen' if o[10] else ''}")
    for d in e.get("decisions", []):
        out.append(f"  decision case #{d[0]} {d[1]}: rule {d[2]}, model {d[3]}, acted {d[4]}{' (advisory)' if d[5] else ''}: {d[6]}")
    for f in e.get("freezes", []):
        out.append(f"  freeze {f[0]} until {f[1] if f[1] != 'None' else f[2]}: {f[3]}")
    for o in e.get("us_orders", []):
        out.append(f"  US order #{o[0]} {o[3]} {o[2]} placed {o[1]}: {o[6]}{' filled ' + str(o[7]) if o[7] else ''} ({o[8]})")
    for t in e.get("us_trades", []):
        out.append(f"  US fill #{t[0]} {t[2]} {t[3]} {t[4]:.4f} at USD {t[5]:.2f} on {t[1]} (tax estimate Rs {t[8] or 0:,.0f})")
    for o in e.get("paper_orders", []):
        out.append(f"  rupee order {o}")
    if e.get("error"):
        out.append("  ERROR " + "; ".join(e["error"]))
    return out


def account(timeline: List[dict]) -> str:
    lines: List[str] = []
    for e in timeline:
        body = _line(e)
        if body:
            lines.append(e["t"])
            lines += body
    return "\n".join(lines)


def _bars(sym: str):
    return _read(f"us/raw/{sym}.parquet")


def nvda_accounting(env, injected: Optional[dict]) -> dict:
    """What the sale did, in the real bars: the sale's fill against the last close before the news (6 Nov), the closes after, and the after-hours level the headline of 11 Nov names (about 8% under the
    11 Nov close: a stated level, not a bar)."""
    b = _bars("NVDA").set_index("date")
    c6, c9, c10, c11 = (float(b.loc[date(2026, 11, d), "close"]) for d in (6, 9, 10, 11))
    o9 = float(b.loc[date(2026, 11, 9), "open"])
    out = {"close_6_nov": c6, "open_9_nov": o9, "close_9_nov": c9, "close_10_nov": c10, "close_11_nov": c11, "after_hours_11_nov_estimate": round(c11 * 0.92, 2), "basis": "daily bars; the after-hours level is the headline's 'about 8% lower'"}
    con = env.cur()
    tr = con.execute("SELECT day, side, qty, price_usd FROM us_trades_s81 WHERE symbol='NVDA' ORDER BY trade_id").fetchall()
    out["trades"] = [(str(d), s, round(q, 4), round(p, 2)) for d, s, q, p in tr]
    sells = [(q, p) for d, s, q, p in tr if s == "sell"]
    if injected and sells:
        q = sum(x[0] for x in sells)
        p = sum(x[0] * x[1] for x in sells) / q
        out["sold_qty"] = round(q, 4)
        out["sale_price"] = round(p, 2)
        for lab, ref in (("close_11_nov", c11), ("after_hours_11_nov_estimate", c11 * 0.92), ("close_6_nov", c6)):
            out[f"vs_holding_to_{lab}_usd"] = round(q * (p - ref), 2)
            out[f"vs_holding_to_{lab}_pct_of_stake"] = round(100 * (p / ref - 1), 2)
        out["stake_usd_at_6_nov_close"] = injected["usd"]
    return out


def _sub_value(con) -> Optional[float]:
    r = con.execute("SELECT value_usd FROM us_days_s81 ORDER BY day DESC LIMIT 1").fetchone()
    return float(r[0]) if r else None


def replay_nvda(held: bool, *, client=None, scenario: Optional[Callable] = None, share: float = 0.08, run_root: Optional[Path] = None, rebuild: bool = False, morning: bool = True, real: bool = False) -> dict:
    """(i) held: NVDA at `share` of the sub-book from the 6 Nov close. (ii) not held: the system had looked at it and passed (a skip, so it is in the watch's scope). The Nvidia week, 6-12 Nov
    (the IST morning of the 12th handles the 11 Nov US session). A scripted model unless `client` is given."""
    start = date(2026, 11, 5)
    env = make_world("nvda_held" if held else "nvda_not_held", start, run_root=run_root, rebuild=rebuild)
    try:
        scen = Scenario("nvda_held" if held else "nvda_not_held", scenario or (nvda_held_answers if held else nvda_not_held_answers))
        env.real = bool(real)
        if real:
            cl = go_real(env)
        else:
            install_cap(300.0)
            cl = client or ScriptedClient(scen.responder(env.cur()), {})
            arm(cl)
        open_world(env, start)
        env.morning_watch = False
        run_window(env, start, date(2026, 11, 7), release=False)                               # the sub-book opens and buys its SPY; Friday's US close is handled on Saturday morning
        con = env.cur()
        key = nvda_key(con)
        inj = None
        if held:
            inj = inject_us_position(con, datetime(2026, 11, 7, 9, 30), date(2026, 11, 6), "NVDA", key, share, env.data)
        else:
            from pflab.us import instruments as uins
            uins.ensure(con, "NVDA", NVDA["name"], etf=False, ciks={"NVDA": NVDA["cik"]}, now=datetime(2026, 11, 7, 9, 30))
            add_skip(con, "US", key, "NVDA", "passed on 5 Nov: the picks sleeve preferred the index fund; the multiple was high for a first position", date(2026, 11, 5))
        env.morning_watch = morning
        env.standin_key = None if held else key
        tl = run_window(env, date(2026, 11, 8), date(2026, 11, 12), key=key, only_from=datetime(2026, 11, 8, 0, 0))
        res = {"replay": "nvda_held" if held else "nvda_not_held", "morning_watch": morning, "injected": inj, "timeline": tl, "account": account(tl), "model_calls": getattr(cl, "calls", []), "model_answers": scen.log,
               "accounting": nvda_accounting(env, inj), "exceptions": env.exceptions[:5], "errors": env.catcher.records[:5], "sub_book_usd": _sub_value(env.cur())}
        if real:
            res["real"] = {"thought": getattr(env, "real_done", None), "calls_made": getattr(env, "real_state", {}).get("n"),
                           "api_rows": [tuple(str(x) for x in r) for r in env.cur().execute("SELECT call_id, role, model, thinking, cached_tokens, cost_inr, status FROM api_calls ORDER BY call_id").fetchall()],
                           "answer_steps": [(st["step"], st["model"], st["thinking"], round(st["cost_rupees"], 2), st["payload_json"][:1800]) for c in env.cur().execute("SELECT case_id FROM think_cases_s84 WHERE symbol='NVDA'").fetchall()
                                            for st in __import__("pflab.think.cases", fromlist=["x"]).steps(env.cur(), c[0])]}
        return res
    finally:
        disarm()
        if getattr(env, "real_restore", None):
            env.real_restore()
        env.close()


def go_real(env, cap: float = 70.0):
    """The ONE real path: the real gateway and client (the key from the secrets file, never printed), the real governor and egress gate with a scratch cap, the workshop's paid guard satisfied by
    PFLAB_PAID; the drills' network block is lifted only around a model call; at most REAL_LIMIT["calls"] calls in all; the app's `think_loop` job is replaced by a fake (the hook thinks one case)."""
    from dataclasses import replace
    from pflab.llm import gateway
    from pflab.service import jobs
    os.environ.pop("PFLAB_SECRETS_FILE", None)
    os.environ["PFLAB_PAID"] = "1"
    install_cap(cap)
    gateway.set_client(None)
    import pflab.think as think_pkg                                                  # the stake is under 1% of the whole book (8% of a 10% sub-book): Opus is asked to DECIDE by lowering the line
    orig_settings = think_pkg.settings
    think_pkg.settings = lambda: {**orig_settings(), "opus_exposure_share": 0.005}
    for jn in ("think_loop", "strategist"):                                         # the app's own jobs would think every case / hold a desk session with the real model: only the hook thinks, once
        job = jobs.REGISTRY.get(jn)
        if job is not None:
            jobs.REGISTRY[jn] = replace(job, fn=lambda ctx: {"replay": "the real path thinks one case itself"})
    from pflab.think import session as sess_mod
    orig_think = sess_mod.think_case

    def only_nvda(con, now, case_id, **kw):                                         # the close loop's own hooks call think_case too: any case but NVDA is left open, no call
        row = con.execute("SELECT symbol FROM think_cases_s84 WHERE case_id=?", [case_id]).fetchone()
        if not row or row[0] != NVDA["symbol"]:
            return {"case_id": case_id, "skipped": "the real path thinks only the NVDA case"}
        return orig_think(con, now, case_id, **kw)
    sess_mod.think_case = only_nvda
    try:
        from pflab.think import desk as desk_mod
        orig_desk = desk_mod.run_desk
        desk_mod.run_desk = lambda *a, **k: {"skipped": "no desk in the real replay"}
    except ImportError:
        desk_mod = orig_desk = None
    eng = gateway.ENGINES["anthropic"]
    orig = eng.send
    state = {"n": 0}

    def send(*a, **k):
        if state["n"] >= REAL_LIMIT["calls"]:
            raise RuntimeError(f"the real path allows {REAL_LIMIT['calls']} model calls in all")
        state["n"] += 1
        env.net.uninstall()
        try:
            return orig(*a, **k)
        finally:
            env.net.install()
    eng.send = send
    env.real_state = state
    env.real_restore = lambda: (setattr(eng, "send", orig), setattr(think_pkg, "settings", orig_settings), setattr(sess_mod, "think_case", orig_think),
                                (setattr(desk_mod, "run_desk", orig_desk) if desk_mod else None))
    return SimpleNamespace(calls=[])


def ather_skip_day(pan=None) -> date:
    pan = pan if pan is not None else _read("panel/prices.parquet")
    a = pan[(pan["symbol"] == ATHER["symbol"]) & (pan["date"] >= date(2026, 9, 1))].sort_values("date")
    near = a[(a["close"] / 1400.0 - 1.0).abs() <= 0.02]
    return near["date"].iloc[0]


def replay_ather(*, run_root: Optional[Path] = None, last: date = date(2026, 11, 11), rebuild: bool = False) -> dict:
    """(iii) a skip on the first stored day Ather Energy closed near Rs 1,400, replayed to 11 Nov: the case opens when the name is 20 points ahead of the Nifty 500."""
    from pflab import markets
    pan = _read("panel/prices.parquet")
    skip_day = ather_skip_day(pan)
    m = markets.get("IN")
    start = skip_day if m.is_session(skip_day) else m.next_session(skip_day)
    env = make_world("ather", start, india=ATHER, run_root=run_root, rebuild=rebuild)
    try:
        scen = Scenario("ather", ather_answers)
        install_cap(300.0)
        cl = ScriptedClient(scen.responder(env.cur()), {})
        arm(cl)
        open_world(env, start)
        add_skip(env.cur(), "IN", ATHER["isin"], ATHER["symbol"], "valuation: trailing earnings negative and the price already well up: not worth it yet", start)
        tl = run_window(env, start, last, release=False)
        a = pan[pan["symbol"] == ATHER["symbol"]].set_index("date")["close"]
        ix = _read("indices/NIFTY500_TRI.parquet").set_index("date")["close"]
        ahead = {str(d): round(100 * ((a.loc[d] / a.loc[start]) - (ix.loc[:d].iloc[-1] / ix.loc[:start].iloc[-1])), 1) for d in a.index if d >= start and d <= last}
        return {"replay": "ather", "skip_day": str(start), "skip_close": float(a.loc[start]), "last_close": float(a.loc[last]), "points_ahead_of_nifty500_by_day": ahead, "timeline": tl, "account": account(tl),
                "model_answers": scen.log, "exceptions": env.exceptions[:5], "errors": env.catcher.records[:5]}
    finally:
        disarm()
        env.close()
