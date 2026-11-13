"""S85 replay3: three more replays of the thinking loop, in the S84 harness (tools/replays_s84*.py), with a SCRIPTED model (no paid call). Development only.

    python tools/replays_s85.py select                      # choose the episodes by code from the stored data (tools/replays_s85_select.py), write the choice down
    python tools/replays_s85.py drills [--only NAME]        # replay_march2020, replay_governance, replay_rotation: each runs its world day by day and checks what the loop did
Reports (JSON + the day-by-day account) go to S85_REPLAY_OUT (default D:\\s85_scratch\\replay3\\out).

THE WORLDS. The S84 world is the drills' synthetic rupee profile (invented names, no holding of his) seeded on the session before the start. Here the profile is seeded on a REAL past date and its
names are given REAL closes from the stored panel, rescaled to the profile's own seed price (`lay_real`: the shape is real, the rupee amounts are the profile's): a stand-in holding carries the closes of the
real name it stands for, and the real Nifty 500 total-return index, cut at what the world's clock has made public (`replays_s84.reveal`, REVEAL root = a folder of real series), is what the watch reads.
No number is ever in a scripted answer (rule 8). Every episode is a DRILL, never a result: history is not evidence (CLAUDE.md rule 2; March 2020 and the others are before the spent 2022-2025
period but the live rules still say a replay proves the machinery, not the edge).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import replays_s84 as R  # noqa: E402
import replays_s85_select as SEL  # noqa: E402
from replays_s84_model import Scenario, ScriptedClient, words  # noqa: E402

D = R.D
SCR = Path(os.environ.get("S85_REPLAY_SCRATCH", r"D:\s85_scratch\replay3"))
OUT = Path(os.environ.get("S85_REPLAY_OUT", str(SCR / "out")))
REAL_DIR = SCR / "real"                                   # real series, copied from the workshop's data folder (read only there)
R.WORK = SCR / "work"
R.OUT = OUT

# the profile's names and the real names whose closes they carry (public large caps, standing in for the profile's holdings by sector)
STOCK_REAL = {"INE9S1A01011": "HINDUNILVR", "INE9S2A01011": "ITC", "INE9S3A01011": "LT", "INE9S5A01011": "HDFCBANK", "INE9S6A01011": "MARUTI",
              "INE9S7A01011": "SUNPHARMA", "INE9S8A01011": "PIDILITIND"}          # SYNIT1 (INE9S4A01011) is not named here: `liquid_in_industry` picks its stand-in by code (no real name of the investor's list is written in the tools)
ETF_REAL = {"INF9S1B01011": "NIFTYBEES", "INF9S2B01011": "GOLDBEES", "INF9S4B01011": "JUNIORBEES"}
SYN = {s[1]: s[0] for s in D.STOCKS + D.PICK_STOCKS}


# --- real data -------------------------------------------------------------------------------------------------------------------------------------------------------------------

def prepare_real_dir() -> Path:
    """The real index series the world's clock reveals (copied once)."""
    (REAL_DIR / "indices").mkdir(parents=True, exist_ok=True)
    for k in ("NIFTY500_TRI", "NIFTY50_PRICE", "NIFTY50_TRI"):
        dst = REAL_DIR / "indices" / f"{k}.parquet"
        if not dst.exists():
            shutil.copy(SEL.DATA / "indices" / f"{k}.parquet", dst)
    return REAL_DIR


_PANEL: Dict[tuple, object] = {}


def panel_rows(*, symbols=None, isins=None, lo: date, hi: date):
    """[date, isin, symbol, close] (the panel's split-safe adj_close as `close`) for the symbols / ISINs between lo and hi."""
    import pandas as pd
    key = (tuple(sorted(symbols or [])), tuple(sorted(isins or [])), lo, hi)
    if key in _PANEL:
        return _PANEL[key]
    filt = [("date", ">=", lo), ("date", "<=", hi)]
    if symbols:
        filt.append(("symbol", "in", list(symbols)))
    if isins:
        filt.append(("isin", "in", list(isins)))
    p = pd.read_parquet(SEL.DATA / "panel" / "prices.parquet", columns=["date", "isin", "symbol", "series", "adj_close", "turnover"], filters=filt)
    p = p[p["series"].isin(["EQ", "BE", "SM", "BZ"]) | p["series"].isna()].copy()
    p["date"] = pd.to_datetime(p["date"]).dt.date
    p = p.rename(columns={"adj_close": "close"})
    p = p[p["close"] > 0].sort_values(["isin", "date"])
    _PANEL[key] = p
    return p


def liquid_in_industry(industry: str, before: date, exclude=()) -> str:
    """The most liquid stored name (median traded value over the 250 sessions before `before`) of an industry of the stored sector map, as an ISIN: a stand-in picked by code."""
    import pandas as pd
    sm = pd.read_parquet(SEL.DATA / "index_membership" / "sector_map.parquet")
    isins = [i for i in sm[sm["industry"] == industry]["isin"].unique() if i not in set(exclude)]
    p = pd.read_parquet(SEL.DATA / "panel" / "prices.parquet", columns=["date", "isin", "turnover"], filters=[("isin", "in", isins), ("date", "<", before), ("date", ">=", before - timedelta(days=370))])
    return str(p.groupby("isin")["turnover"].median().sort_values(ascending=False).index[0])


def lay_real(base: Path, start: date, isin: str, real) -> dict:
    """Replace the closes of a profile name (before `start` in the store, from `start` on in the held-back file) by the real closes `real` (a Series date -> close), rescaled so the last close before
    `start` is the profile's own (the book's value is unchanged on the seed day; every later percentage is real). Missing real days repeat the last close."""
    import pandas as pd
    from pflab.pm import store
    con = store.connect(base / "pm" / "ledger.duckdb")
    rows = con.execute("SELECT date, close FROM prices WHERE isin=? ORDER BY date", [isin]).fetchall()
    held = pd.read_parquet(base / "held_prices.parquet")
    held["date"] = pd.to_datetime(held["date"]).dt.date
    hrows = held[held["isin"] == isin]
    days = [r[0] for r in rows] + list(hrows["date"])
    syn = {r[0]: float(r[1]) for r in rows}
    prev = max(d for d in syn if d < start)
    ser = pd.Series(real).sort_index()
    ser.index = pd.to_datetime(ser.index)
    al = ser.reindex(pd.to_datetime(sorted(set(days)))).ffill().bfill()
    al.index = [d.date() for d in al.index]
    k = syn[prev] / float(al.loc[prev])
    for d, c in syn.items():
        con.execute("UPDATE prices SET close=? WHERE isin=? AND date=?", [round(float(al.loc[d]) * k, 4), isin, d])
    m = (held["isin"] == isin)
    held.loc[m, "close"] = [round(float(al.loc[d]) * k, 4) for d in held.loc[m, "date"]]
    held.to_parquet(base / "held_prices.parquet")
    con.execute("CHECKPOINT")
    con.close()
    return {"isin": isin, "scale": round(k, 4), "days": len(days)}


def lay_all(base: Path, start: date, mapping: Dict[str, str], lo: date, hi: date) -> List[dict]:
    out = []
    syms = [v for v in mapping.values() if not str(v).startswith("IN")]
    isns = [v for v in mapping.values() if str(v).startswith("IN")]
    p = panel_rows(symbols=syms, lo=lo, hi=hi)
    pi = panel_rows(isins=isns, lo=lo, hi=hi) if isns else p.iloc[0:0]
    for isin, sym in mapping.items():
        g = pi[pi["isin"] == sym] if str(sym).startswith("IN") else p[p["symbol"] == sym]
        if len(g) < 100:
            out.append({"isin": isin, "symbol": sym, "skipped": f"only {len(g)} stored closes"})
            continue
        g = g.sort_values("turnover").drop_duplicates("date", keep="last") if "turnover" in g else g
        out.append({**lay_real(base, start, isin, g.set_index("date")["close"]), "real_symbol": sym})
    return out


def build_world(name: str, start: date, *, lay: Dict[str, str], extra: Optional[List[dict]] = None, lo: Optional[date] = None, hi: Optional[date] = None, events_after: bool = True):
    """Profile seeded on the session before `start`, real closes laid on `lay` (profile isin -> real symbol), real names added from `extra` ({"isin","symbol","name","sector","rows"}), the real
    index revealed by the clock. Returns (env, what was laid)."""
    base = R.WORK / f"base_{name}"
    orig_stocks = list(D.STOCKS)                  # the profile's holdings were bought in 2024-25: for a world in the past they are bought long before the start (a lot dated after the start would be a lot from the future)
    D.STOCKS[:] = [tuple(s[:-1]) + ((min(s[-1], start - timedelta(days=800)) if s[-1] else s[-1]),) for s in orig_stocks]
    try:
        D.build_base(base, start)
    finally:
        D.STOCKS[:] = orig_stocks
    laid = lay_all(base, start, lay, lo or start - timedelta(days=700), hi or start + timedelta(days=120))
    for e in extra or []:
        R.add_india_name(base, start, {k: e[k] for k in ("isin", "symbol", "name", "sector")}, e["rows"])
    prepare_real_dir()
    R.REVEAL["root"], R.REVEAL["india"], R.REVEAL["on"] = REAL_DIR, set(), True
    env = D.Env(name, R.WORK / "runs", base)
    R.REVEAL["env"], R.REVEAL["now"] = env, D.dt(start, 6)
    env.base_meta = SimpleNamespace(start=start, india=None)
    (env.data / "us").mkdir(parents=True, exist_ok=True)
    R.reveal(env, D.dt(start, 6))
    return env, laid


def patch_wide(members: List[tuple]):
    """The wide watch's universe in the world: the Nifty 500's membership data is not in a synthetic world, so the names this replay needs the watch to look at are its universe (the rest of the wide
    watch, `scan` and `commit`, is the real code). members = [(isin, symbol)]. Returns the undo."""
    import pandas as pd
    from pflab.think import wide
    orig = wide.universe

    def universe(con, day, market, root=None):
        if market != "IN" or not members:
            return pd.DataFrame(columns=["isin", "symbol", "weight"])
        return pd.DataFrame({"isin": [m[0] for m in members], "symbol": [m[1] for m in members], "weight": [1.0 / len(members)] * len(members)})
    wide.universe = universe
    return lambda: setattr(wide, "universe", orig)


def add_event(con, isin: str, kind: str, severity: str, ts: datetime, headline: str, key: str, rule: str = "dissemination time") -> None:
    if con.execute("SELECT 1 FROM kg2_event WHERE event_id=?", [key]).fetchone():
        return
    con.execute("INSERT INTO kg2_event (event_id, isin, source, ref, ts, event_date, kind, severity, headline, link_rule, link_proof, dedupe_key, ts_rule) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [key, isin, "bse_announcement", f"replay:{key}", ts, ts.date(), kind, severity, headline, "isin_in_filing", "the stored filing names the company", key, rule])
    try:
        con.execute("INSERT INTO kg2_event_class VALUES (?,?,?,?,?,?)", [key, kind, severity, "scripted", "replay", ts])
    except Exception:
        pass


def _ans(klass: str, option: str, symbol: str, *, happened: str, known: str, pending: str = "", pending_date: str = "", reason: str = "", worst="unlikely", likely="likely", best="unlikely",
         other: Optional[list] = None, sources=("the stored closes", "the stored headlines")) -> dict:
    return {"happened": happened, "sources": list(sources), "class": klass, "known": known, "pending": pending, "pending_date": pending_date, "other_names": other or [],
            "choices": [{"symbol": symbol, "option": option, "reason": reason or f"scripted: {option}"}], "likelihood": words(worst, likely, best)}


def _ordinary(case: dict) -> dict:
    sym = case.get("symbol") or "the name"
    return _ans("market_fear", "hold", sym, happened=f"{sym} moved with its market or sector on the day.", known="The move is in the stored closes.", reason="an ordinary move with its market: nothing to do")


# --- the run harness -------------------------------------------------------------------------------------------------------------------------------------------------------------

class Run:
    """One replay: world, scripted client, the day loop, and what to say afterwards."""

    def __init__(self, name: str, answers: Callable, env, check: str = "pass", cap: float = 300.0):
        self.name, self.env = name, env
        self.scen = Scenario(name, answers, check=check)
        R.install_cap(cap)
        self.client = ScriptedClient(self.scen.responder(env.cur()), {})
        R.arm(self.client)
        R.open_world(env, env.base_meta.start)
        self.timeline: List[dict] = []

    def run(self, first: date, last: date, hook: Optional[Callable] = None) -> List[dict]:
        tl = R.run_window(self.env, first, last, release=False, hook=hook)
        self.timeline += tl
        return tl

    @property
    def con(self):
        return self.env.cur()

    def close(self) -> None:
        R.disarm()
        self.env.close()


def case_rows(con, isin: Optional[str] = None, kind: Optional[str] = None) -> List[dict]:
    from pflab.think import cases
    out = cases._rows(con, "think_cases_s84", cases._CASE)
    return [c for c in out if (isin is None or c["isin"] == isin) and (kind is None or c["kind"] == kind)]


def decision_lines(con, case_id: int) -> List[str]:
    from pflab.think import cases
    out = []
    for d in cases.decisions(con, case_id):
        out.append(f"{d['decided_on']}: {d['symbol']}: model {d['model_option']}, rule {d['rule_option']}, acted {d['acted_option']}: {str(d['reason'])[:260]}")
    return out


def orders_lines(con, isin: str) -> List[str]:
    rows = con.execute("SELECT order_id, side, qty, amount, status, cast(placed_at as date), note FROM paper_orders WHERE isin=? ORDER BY order_id", [isin]).fetchall()
    return [f"order #{o}: {s} qty={q} amount={a} {st} placed {d}: {str(n)[:90]}" for o, s, q, a, st, d, n in rows]


def trade_lines(con, isin: str) -> List[str]:
    try:
        rows = con.execute("SELECT trade_id, date, side, qty, price FROM paper_trades WHERE isin=? ORDER BY trade_id", [isin]).fetchall()
    except Exception:
        return []
    return [f"fill #{t}: {s} {q:g} at Rs {p:,.2f} on {d}" for t, d, s, q, p in rows]


def cached(name: str) -> Optional[dict]:
    """S85_REPLAY_REUSE=1 re-evaluates the checks on the stored result of the last run (the world is not run again): for changing a check, never for a new claim."""
    p = OUT / f"{name}.json"
    if os.environ.get("S85_REPLAY_REUSE") and p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def finish(res: dict, name: str) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps({k: v for k, v in res.items() if k != "timeline"}, indent=1, default=str), encoding="utf-8")
    (OUT / f"{name}.txt").write_text(res.get("account", ""), encoding="utf-8")
    return res


def evidence_clean(r: Run, c) -> None:
    c.ok(not r.env.exceptions, f"no unhandled exception in the loops: {r.env.exceptions[:2]}", "think/wire.py")
    c.ok(not r.env.catcher.records, f"no error logged by pflab: {r.env.catcher.records[:2]}", "(the logger named)")


# --- (3) March 2020 --------------------------------------------------------------------------------------------------------------------------------------------------------------

def march_answers(case: dict, n: int) -> dict:
    """The market case: fear, buy the index fund in parts (what the model would say; the rule has its own guards). Every other case is an ordinary move with its market."""
    if case.get("kind") == "market":
        return _ans("market_fear", "buy_in_parts", "NIFTYBEES", happened="The Nifty 500 has fallen more than a tenth in twenty sessions; the stored closes show a fall across every sector with no company event behind it.",
                    known="The fall is in the stored index closes and in every held name's closes.", reason="a market-wide fall with no business damage to a holding: a small part of the reserve may go into the index fund in parts",
                    worst="unlikely", likely="even", best="likely", sources=("the stored index closes", "the stored closes of the held names"))
    return _ordinary(case)


def replay_march2020(*, last: date = date(2020, 4, 9)) -> dict:
    """The Covid fall as a market-wide case. World seeded 2 Mar 2020; real closes on the whole profile; the real Nifty 500 TRI revealed by the clock."""
    sel = SEL.select_march2020()
    start = date(2020, 3, 2)
    lay = {**STOCK_REAL, **ETF_REAL, "INE9S4A01011": liquid_in_industry("IT", start)}
    env, laid = build_world("march2020", start, lay=lay, lo=date(2019, 1, 1), hi=date(2020, 6, 30))
    r = Run("march2020", march_answers, env)
    probe: List[dict] = []

    def guard_probe(env_, t):
        """FINDING (think/rule.py `_decide_one`): for a HELD name (the index fund is in the book) a refused buy is reported as 'Hold: no sale beats holding', the timing guard that refused it is not in the
        reason. This hook asks the rule's own `_buy` what it says at each close (read only) so the account can show why a part waited."""
        if t.hour != 21 or not env_.cur():
            return
        from pflab import markets
        from pflab.think import cases as _c, odds, rule
        con_ = env_.cur()
        mk_ = [x for x in case_rows(con_) if x["kind"] == "market" and x["state"] in ("open", "acted")]
        if not mk_ or not markets.get("IN").is_session(t.date()):
            return
        case_ = _c.get_case(con_, mk_[0]["case_id"])
        isin_ = "INF9S1B01011"
        pos_ = odds.position(con_, "IN", isin_, "NIFTYBEES", t.date(), env_.data)
        kind_, move_, win_ = odds.case_kind_move(con_, case_)
        rates_ = odds.base_rates(con_, kind_, move=move_, isin=isin_, asof=t.date(), market="IN", symbol="NIFTYBEES", window=win_, root=env_.data)
        b = rule._buy(con_, case_, "market_fear", {"isin": isin_, "symbol": "NIFTYBEES", "option": "buy_in_parts"}, pos_, t.date(), "IN", rule.cfg(), rates_, None, env_.data, {"class": "market_fear"})
        probe.append({"day": str(t.date()), "option": b["option"], "refused": b.get("refused"), "guards": [g[:170] for g in b.get("guards", [])][:3], "basis": rates_.get("basis"), "history_n": rates_.get("history_n")})
    try:
        tl = r.run(start, last, hook=guard_probe)
        con = r.con
        from pflab.think import cases, reserve, score
        mk = [c for c in case_rows(con) if c["kind"] == "market"]
        etf = "INF9S1B01011"
        lines = []
        for c in mk[:1]:
            lines += decision_lines(con, c["case_id"])
        parts = [json.loads(s["payload_json"]) for c in mk[:1] for s in cases.steps(con, c["case_id"]) if s["step"] == "part"]
        waits = [s for c in mk[:1] for s in cases.steps(con, c["case_id"]) if s["step"] in ("looked", "failed")]
        extra = ["", "THE CASE", *[f"case #{c['case_id']} {c['title']} state={c['state']} class={c['klass']} opened {c['opened_on']}" for c in mk], *lines,
                 "", "WHAT THE RULE'S BUY BRANCH SAID AT EACH CLOSE (read-only probe; base rates: basis and count of past cases)", *[f"{x['day']}: {x['option']} refused={x['refused']} [{x['basis']}, n={x['history_n']}] {' | '.join(x['guards'])}" for x in probe],
                 "", "PARTS BOUGHT (reserve into the index fund)", *[f"part {p['n']} of {p['of']}: Rs {p['inr']:,.0f} on {p['day']}" for p in parts], *orders_lines(con, etf), *trade_lines(con, etf)]
        n_scored = score.score_due(con, last)
        extra += ["", f"SCORING on the stored closes at {last}: {n_scored} rows written", str(score.scorecard(con).get("text", ""))[:300]]
        res = {"replay": "march2020", "selection": sel, "laid": laid, "timeline": tl, "account": R.account(tl) + "\n" + "\n".join(extra), "model_answers": r.scen.log, "exceptions": r.env.exceptions[:5],
               "errors": r.env.catcher.records[:5], "market_cases": [(c["case_id"], str(c["opened_on"]), c["state"], c["klass"]) for c in mk], "parts": parts,
               "etf_orders": orders_lines(con, etf), "probe": probe, "reserve": reserve.reserve_status(con, "IN", last)}
        return finish(res, "march2020")
    finally:
        r.close()


def drill_march2020(c) -> None:
    res = cached("march2020") or replay_march2020()
    mk = res["market_cases"]
    c.note(f"selection: {res['selection']}")
    c.ok(bool(mk), f"the market case opened ({mk[:2]})", "think/watch.py _market_signal")
    if mk:
        first_cross = date.fromisoformat(res["selection"]["first_line_crossed"])
        opened = date.fromisoformat(mk[0][1])
        c.ok(first_cross <= opened <= first_cross + timedelta(days=4), f"it opened at the first close past the line, {first_cross}, not before and not days later (opened {opened})", "think/watch.py")
    parts = res["parts"]
    c.note(f"parts: {[(p['n'], p['day'], round(p['inr'])) for p in parts]}; etf orders: {res['etf_orders']}")
    c.ok(len(parts) <= 3, f"never more than three parts ({len(parts)})", "think/session.py")
    days = [date.fromisoformat(p["day"]) for p in parts]
    c.ok(all((b - a).days >= 5 for a, b in zip(days, days[1:])), f"parts are at least 5 days apart ({days})", "think/rule.py parts_gap_sessions")
    rs = res["reserve"]
    c.ok(sum(p["inr"] for p in parts) <= 0.5 * (rs["reserve_inr"] + sum(p["inr"] for p in parts)) + 1.0, "the parts together stay within half of the reserve (a market fall may use up to market_fall_reserve_share)", "think/rule.py")
    case_orders = [o for o in res["etf_orders"] if "case #" in o]
    c.ok(len(case_orders) == len(parts) and all(": buy " in o for o in case_orders), f"every part is one buy order that names its case ({len(case_orders)} orders, {len(parts)} parts)", "think/session.py")
    baseline_sells = [o for o in res["etf_orders"] if ": sell " in o and "baseline_v2" in o and o.split("placed ")[1][:10] > parts[0]["day"]] if parts else []
    c.note(f"FINDING: after the first part the core baseline sold the index fund again: {[o[:70] for o in baseline_sells]}")
    c.ok(any(p["guards"] for p in res["probe"]), f"the account says why parts waited: {[(p['day'], p['guards'][:1]) for p in res['probe'] if p['option'] != 'buy_in_parts'][:3]}", "think/rule.py")
    c.ok(any(p.get("basis") for p in res["probe"]), f"the base rates' basis is stated ({res['probe'][0]['basis'] if res['probe'] else None}, n={res['probe'][0]['history_n'] if res['probe'] else None})", "think/odds.py")
    c.ok(any(a["class"] == "market_fear" for a in res["model_answers"]), "the scripted model read it as market fear (no number in its answer)", "tools/replays_s85.py")
    c.ok(not res["exceptions"] and not res["errors"], f"no exception, no logged error ({res['exceptions'][:1]} {res['errors'][:1]})", "think/wire.py")


# --- (2) Indian governance -------------------------------------------------------------------------------------------------------------------------------------------------------

def gov_answers(case: dict, n: int) -> dict:
    sym = case.get("symbol") or "the name"
    if any(s.get("signal") == "thesis_event" for s in case.get("signals") or []):          # a case that carries the stored filing among its signals (the watch joins it to the case open on the name)
        return _ans("damage", "hold" if "SYNIT1" in sym else "nothing", sym, happened="The statutory auditors have resigned from the company, which is a governance warning; the shares fell hard on the days around the filing.",
                    known="The filing and the closes are stored; the reason for the resignation is not in the filing's text.", pending="the company's reply and the new auditor's appointment",
                    reason="a statutory auditor leaving is a governance break; the safe reading is damage, the rule decides what to do with it", worst="likely", likely="even", best="very unlikely",
                    sources=("the stored filing", "the stored closes"))
    return _ordinary(case)


def replay_governance(held: bool, *, last: Optional[date] = None) -> dict:
    """A real governance shock of 2018 from the stored red-flag events (chosen by code: tools/replays_s85_select.py). HELD: a stand-in holding carries the company's closes; NOT HELD: the system looked at it
    and passed earlier (a skip), the wide watch looks at it."""
    from pflab import markets
    sel = SEL.select_governance()
    ev = sel["event"]
    ev_day = date.fromisoformat(ev["usable_from"][:10])
    last = last or ev_day + timedelta(days=16)
    start = ev_day - timedelta(days=7)
    m = markets.get("IN")
    while not m.is_session(start):
        start -= timedelta(days=1)
    sym = SEL._panel([ev["isin"]], lo=str(ev_day - timedelta(days=30)), hi=str(ev_day))["symbol"].iloc[-1]
    real_ref = ev["isin"]                                    # the panel lists the name under changing symbols (a trade-to-trade segment sign): its closes are found by ISIN
    stand_in = "INE9S4A01011" if held else "INE9S7A01011"          # SYNIT1 (held) or SYNPICK1 (a name in the store the book does not hold)
    lay = {**{k: v for k, v in STOCK_REAL.items() if k != stand_in}, **ETF_REAL, stand_in: real_ref}
    if not held:
        lay["INE9S4A01011"] = liquid_in_industry("IT", start)
    env, laid = build_world("governance_held" if held else "governance_not_held", start, lay=lay, lo=start - timedelta(days=700), hi=last + timedelta(days=30))
    r = Run("governance", gov_answers, env)
    undo = None
    try:
        con = r.con
        ts = D.dt(m.next_session(ev_day), 9, 15)                  # A58: the stored time is the date only: used from the next trading day's open
        headline = ev["headline"]
        if not held:
            R.add_skip(con, "IN", stand_in, SYN[stand_in], "passed on before the filing: the picks sleeve preferred other names", start)
            undo = patch_wide([(stand_in, SYN[stand_in])])
        added = {"n": 0}

        def hook(env_, t):
            if ts <= t and not added["n"]:
                add_event(env_.cur(), stand_in, "auditor_resignation", "high", ts, headline, f"gov:{ev['isin']}:{ev_day}", "next_open_no_release_time")
                added["n"] = 1
        tl = r.run(start, last, hook=hook)
        con = r.con
        from pflab.think import cases
        cs = case_rows(con, stand_in)
        sells = con.execute("SELECT order_id, qty, status, cast(placed_at as date), note FROM paper_orders WHERE isin=? AND side IN ('sell','SELL') ORDER BY order_id", [stand_in]).fetchall()
        buys = con.execute("SELECT order_id FROM paper_orders WHERE isin=? AND side IN ('buy','BUY') AND cast(placed_at as date) >= ?", [stand_in, ts.date()]).fetchall()
        exits_ = con.execute("SELECT kind, reason FROM exit_events_s81 WHERE isin=? ORDER BY 1", [stand_in]).fetchall() if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='exit_events_s81'").fetchone()[0] else []
        fr = cases._rows(con, "think_freezes_s84", ("freeze_id", "isin", "since", "until", "until_event", "active"), "WHERE isin=?", [stand_in])
        pr = {str(d): float(c) for d, c in con.execute("SELECT date, close FROM prices WHERE isin=? ORDER BY date", [stand_in]).fetchall()}
        extra = ["", f"THE EVENT: {ev['company'].strip()} ({sym}), {ev['flag']}, stored dated {ev_day}, used from {ts:%a %d %b %H:%M} (A58: no release time). Headline: {headline[:160]}",
                 *[f"case #{c['case_id']} {c['title'][:100]} state={c['state']} class={c['klass']} opened {c['opened_on']}" for c in cs], *[l for c in cs for l in decision_lines(con, c["case_id"])],
                 *[f"exit event: {k}: {str(x)[:140]}" for k, x in exits_], *[f"sell order #{o}: qty {q} {st} placed {d}: {str(n)[:100]}" for o, q, st, d, n in sells],
                 *[f"freeze on the name: since {f['since']} until {f['until']} / {f['until_event']} active={f['active']}" for f in fr], *orders_lines(con, stand_in)[-3:], *trade_lines(con, stand_in)]
        res = {"replay": "governance_held" if held else "governance_not_held", "selection": sel, "laid": laid, "timeline": tl, "account": R.account(tl) + "\n" + "\n".join(extra), "model_answers": r.scen.log,
               "exceptions": r.env.exceptions[:5], "errors": r.env.catcher.records[:5], "event_ts": str(ts), "cases": [(c["case_id"], str(c["opened_on"]), c["state"], c["klass"], c["kind"]) for c in cs],
               "sells": [(o, q, st, str(d)) for o, q, st, d, n in sells], "buys_after_event": len(buys), "exit_events": [(k, str(x)[:100]) for k, x in exits_], "freezes": [(str(f["since"]), f["active"]) for f in fr],
               "closes": pr}
        return finish(res, "governance_held" if held else "governance_not_held")
    finally:
        if undo:
            undo()
        r.close()


def drill_governance(c) -> None:
    res = cached("governance_held") or replay_governance(True)
    c.note(f"selection: {res['selection']['event']['company'].strip()} {res['selection']['event']['flag']} {res['selection']['event']['usable_from']}: {res['selection']['why']}")
    ts = datetime.fromisoformat(res["event_ts"])
    day_s = f"{ts:%d %b %Y}"
    thesis = [e for e in res["exit_events"] if e[0] == "thesis"]
    case_sale = [e for e in res["exit_events"] if e[0] == "case"]
    sold_on_day = [x for x in res["sells"] if str(x[3]) >= ts.date().isoformat()]
    # S85: since the case is re-looked at once when a new thesis-break event joins it (fix3), the thinking loop's damage sale can reach the book on the day the event becomes usable, before the exit manager's own close-time check: either road is the sale this check wants
    c.ok((bool(thesis) and all(day_s in e[1] for e in thesis)) or (bool(case_sale) and bool(sold_on_day)),
         f"HELD: the thesis break (the exit manager's, or the thinking loop's damage sale) acts on the day the event became usable ({day_s}): thesis {thesis[:1]}, case sale {case_sale[:1]}, sold on or after the day {sold_on_day[:1]}", "core/exits.py check_thesis, think/session.py follow_up")
    sold = [s for s in res["sells"] if date.fromisoformat(s[3]) >= ts.date()]
    c.ok(bool(sold) and date.fromisoformat(sold[0][3]) <= ts.date() + timedelta(days=4), f"HELD: the stand-in holding was sold on the day the event became usable or within a few sessions, never before it (sells {res['sells']}, event usable {ts})", "core/exits.py")
    c.ok(res["buys_after_event"] == 0, "HELD: no buy of the name after the event", "think/rule.py")
    c.ok(not res["exceptions"] and not res["errors"], f"HELD: no exception, no logged error ({res['exceptions'][:1]} {res['errors'][:1]})", "think/wire.py")
    nres = cached("governance_not_held") or replay_governance(False)
    ncs = nres["cases"]
    c.ok(bool(ncs), f"NOT HELD: the wide watch noticed it and a case opened ({ncs[:2]})", "think/wide.py")
    c.ok(not nres["sells"] and nres["buys_after_event"] == 0, f"NOT HELD: nothing sold, nothing bought (sells {nres['sells']}, buys {nres['buys_after_event']})", "think/rule.py")
    c.ok(bool(nres["freezes"]) or any(cs[2] in ("acted", "closed", "advisory", "open") for cs in ncs), f"NOT HELD: passed and watched (freezes {nres['freezes']}, cases {ncs[:2]})", "think/session.py act")
    c.ok(not nres["exceptions"] and not nres["errors"], f"NOT HELD: no exception, no logged error ({nres['exceptions'][:1]} {nres['errors'][:1]})", "think/wire.py")


# --- (1) India rotation ----------------------------------------------------------------------------------------------------------------------------------------------------------

def rot_answers(case: dict, n: int) -> dict:
    sym = case.get("symbol") or "the name"
    if case.get("kind") in ("missed_run", "move", "rel", "run") and not str(sym).startswith("SYN"):
        return _ans("temporary", "buy_in_parts", sym, happened=f"{sym} rose with its whole industry while the metals names fell: money moved between sectors with the index flat.",
                    known="The rise is in the stored closes of the industry's members and of the index.", reason="a sector rotation with no company event: a small part from the reserve, in parts, if the guards allow",
                    worst="unlikely", likely="even", best="likely", sources=("the stored closes of the industry", "the stored index closes"))
    return _ordinary(case)


def replay_rotation(*, tail: int = 8) -> dict:
    """A stored real rotation (chosen by code): a basket of metals names fell and an IT basket rose in ten sessions with the Nifty 500 flat. The profile's held names carry the metals closes; the IT
    names the wide watch looks at are real names added to the store with their real closes."""
    from pflab import markets
    sel = SEL.select_rotation()
    m = markets.get("IN")
    w0, w1 = date.fromisoformat(sel["window_start"]), date.fromisoformat(sel["window_end"])
    start = w0 - timedelta(days=10)
    while not m.is_session(start):
        start -= timedelta(days=1)
    last = w1 + timedelta(days=tail)
    falls = [x["symbol"] for x in sel["falling_names"]][:3]
    it_stand_in = liquid_in_industry("IT", start, exclude=[x["isin"] for x in sel["rising_names"]])
    rises = [x for x in sel["rising_names"] if x["isin"] != it_stand_in and x["rel_5d_pct"] > 0][:4]          # the rising basket's members that rose (one member of an industry label fell on its own news: not part of the rotation)
    lay = {"INE9S1A01011": falls[0], "INE9S2A01011": falls[1], "INE9S3A01011": falls[2], "INE9S4A01011": it_stand_in, "INE9S5A01011": "HDFCBANK", "INE9S6A01011": "MARUTI", "INE9S7A01011": "SUNPHARMA", "INE9S8A01011": "PIDILITIND",
           **ETF_REAL}
    pan = panel_rows(isins=[x["isin"] for x in rises], lo=start - timedelta(days=500), hi=last + timedelta(days=30))
    extra = []
    for x in rises:
        g = pan[pan["isin"] == x["isin"]].sort_values("turnover").drop_duplicates("date", keep="last")
        extra.append({"isin": x["isin"], "symbol": x["symbol"], "name": f"{x['symbol']} (real)", "sector": "IT", "rows": g[["date", "close"]].reset_index(drop=True)})
    env, laid = build_world("rotation", start, lay=lay, extra=extra, lo=start - timedelta(days=700), hi=last + timedelta(days=30))
    r = Run("rotation", rot_answers, env)
    undo = patch_wide([(x["isin"], x["symbol"]) for x in rises])
    try:
        tl = r.run(start, last)
        con = r.con
        from pflab.think import cases
        tgt = sel["wide_target"]
        cs_all = case_rows(con)
        sig = [s for s in cases.signals(con) if s["isin"] in {x["isin"] for x in rises}]
        cs = [c for c in cs_all if c["isin"] in {x["isin"] for x in rises}]
        held_cs = [c for c in cs_all if c["isin"].startswith("INE9S") and c["isin"] in ("INE9S1A01011", "INE9S2A01011", "INE9S3A01011")]
        extra_l = ["", f"THE WINDOW: {sel['window_start']} to {sel['window_end']}: {sel['falling_industry']} basket {sel['falling_pct']}% ({sel['falling_members']} members), {sel['rising_industry']} basket +{sel['rising_pct']}% "
                       f"({sel['rising_members']} members), Nifty 500 TRI {sel['nifty500_tri_10d_pct']}% in 10 sessions",
                   *[f"signal {s['symbol']} {s['signal']} value {s['value']:.3f} (line {s['threshold']:.3f}) on {str(s['day'])[:10] if 'day' in s else ''}" for s in sig[:8]],
                   *[f"case #{c['case_id']} {c['symbol']} kind={c['kind']} state={c['state']} class={c['klass']} opened {c['opened_on']}" for c in cs],
                   *[l for c in cs for l in decision_lines(con, c["case_id"])], "held metals stand-ins: " + (", ".join(f"{c['symbol']} case {c['state']}" for c in held_cs) or "no case opened (a fall of 5 to 10 points in a basket is under every line of the watch)")]
        tg = [d for c in cs if c["symbol"] == tgt["symbol"] for d in decision_lines(con, c["case_id"])]
        extra_l += ["", f"IN TWO LINES (the wide target {tgt['symbol']}, +{tgt['rel_5d_pct']} points against the index in 5 sessions at the window's end):",
                    f"  {tgt['symbol']} was noticed by the wide watch while the metals basket fell and the IT basket rose with the index flat; the scripted model said buy in parts.",
                    f"  Rule: {tg[0].split(': ', 2)[-1][:300] if tg else 'no decision yet'}"]
        rrows = con.execute("SELECT worst_pct_book, option FROM think_options_s84 WHERE track='rule' AND chosen AND option='buy_in_parts'").fetchall()
        res = {"replay": "rotation", "selection": sel, "laid": laid, "timeline": tl, "account": R.account(tl) + "\n" + "\n".join(extra_l), "model_answers": r.scen.log, "exceptions": r.env.exceptions[:5],
               "errors": r.env.catcher.records[:5], "signals": [(s["symbol"], s["signal"], round(s["value"], 3)) for s in sig], "cases": [(c["case_id"], c["symbol"], str(c["opened_on"]), c["state"], c["klass"], c["kind"]) for c in cs],
               "decisions": [d for c in cs for d in decision_lines(con, c["case_id"])], "wide_target": tgt, "window": (str(w0), str(w1)),
               "rule_buy_worst_pct": [abs(float(x[0])) for x in rrows], "orders": [orders_lines(con, x["isin"]) for x in rises]}
        return finish(res, "rotation")
    finally:
        undo()
        r.close()


def drill_rotation(c) -> None:
    res = replay_rotation()
    sel = res["selection"]
    c.note(f"window {sel['window_start']} to {sel['window_end']}: {sel['falling_industry']} {sel['falling_pct']}%, {sel['rising_industry']} +{sel['rising_pct']}%, index {sel['nifty500_tri_10d_pct']}%: {sel['why']}")
    c.ok(sel["falling_pct"] <= -5 and sel["rising_pct"] >= 5 and abs(sel["nifty500_tri_10d_pct"]) <= 1.5, "the window has a basket down 5+ points, another up 5+ points, the index flat", "tools/replays_s85_select.py")
    w1 = sel["window_end"]
    sig = [s for s in res["signals"] if s[0] != "VAKRANGEE"]
    c.ok(bool(sig), f"the wide watch noticed names of the rising basket ({sig[:3]})", "think/wide.py")
    c.ok(bool(res["cases"]), f"a case ran on one ({res['cases'][:2]})", "think/watch.py, think/session.py")
    c.ok(any(cs[2] <= w1 for cs in res["cases"]), f"a case on a rising name opened by the window's end {w1} ({[cs[:3] for cs in res['cases']][:4]})", "think/wide.py")
    c.ok(all(w <= 0.0101 for w in res["rule_buy_worst_pct"]), f"every part the rule bought keeps the bad case within 1% of the whole book ({[round(w, 4) for w in res['rule_buy_worst_pct']][:4]})", "think/rule.py")
    c.ok(bool(res["decisions"]), f"it ended in a decision of the rule with its reason ({res['decisions'][:1]})", "think/rule.py")
    c.ok(not res["exceptions"] and not res["errors"], f"no exception, no logged error ({res['exceptions'][:1]} {res['errors'][:1]})", "think/wire.py")


# --- the CLI ---------------------------------------------------------------------------------------------------------------------------------------------------------------------

DRILLS: Dict[str, Callable] = {"replay_rotation": drill_rotation, "replay_governance": drill_governance, "replay_march2020": drill_march2020}


def run_all(only: Optional[str] = None) -> dict:
    res = {}
    for name, fn in DRILLS.items():
        if only and name != only:
            continue
        c = D.Check(name)
        t0 = time.time()
        try:
            fn(c)
            res[name] = c.result(t0)
        except Exception:
            c.evidence.append("ERROR: " + " | ".join(l.strip() for l in traceback.format_exc().strip().splitlines()[-4:])[:900])
            res[name] = {"name": name, "status": "ERROR", "evidence": c.evidence, "findings": [], "seconds": round(time.time() - t0, 1)}
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"drill_{name}.json").write_text(json.dumps(res[name], indent=1, default=str), encoding="utf-8")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["select", "drills"])
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    if a.cmd == "select":
        return SEL.main()
    out = run_all(a.only or None)
    for k, v in out.items():
        print(k, v["status"], f"{v.get('seconds')}s")
        for e in v["evidence"]:
            print("   ", e[:400])
    return 0 if all(v["status"] == "PASS" for v in out.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
