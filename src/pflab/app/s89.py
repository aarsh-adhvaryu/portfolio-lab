"""S89: the endpoints behind the redesigned screens. Thin readers over stored state plus three small writers (his US holdings entered by hand, his watchlist, the agents' settings).

* `mine_in_s89`: HIS real Indian holdings, the latest Kite snapshot only (no history, no statements, no banking), refreshed at most every 5 minutes, read-only.
* `mine_us_s89`: HIS real US holdings, entered by hand. Never `/api/us/trade`; never the system's paper ledger; never in a paper total or score.
* `watch_s89`: names he does not own that the alarm lane also checks (cap 25).
Nothing here computes a decision, places an order or calls a model.
"""
from __future__ import annotations

import json
import math
import re
import threading
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import Body, HTTPException

REFRESH_MIN = 5
WATCH_CAP = 25
ALERTS = ("moves 3%+", "news", "results", "near its 52-week low")
VIEWS = {"hold": "hold", "wait": "watch", "freeze": "watch", "nothing": "watch", "trim": "trim", "sell": "trim", "buy in parts": "add"}
DDL = [
    "CREATE TABLE IF NOT EXISTS mine_in_s89 (symbol VARCHAR PRIMARY KEY, isin VARCHAR, exchange VARCHAR, qty DOUBLE, avg_price DOUBLE, last_price DOUBLE, day_change_pct DOUBLE, snapshot_at TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS mine_us_s89 (ticker VARCHAR PRIMARY KEY, shares DOUBLE NOT NULL, avg_price DOUBLE NOT NULL, bought_on DATE, updated_at TIMESTAMP NOT NULL)",
    "CREATE TABLE IF NOT EXISTS watch_s89 (symbol VARCHAR PRIMARY KEY, market VARCHAR NOT NULL, why VARCHAR, alerts_json VARCHAR, added_at TIMESTAMP NOT NULL)",
    "CREATE TABLE IF NOT EXISTS mine_meta_s89 (key VARCHAR PRIMARY KEY, value VARCHAR, seen_at TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS agent_settings_s89 (agent VARCHAR PRIMARY KEY, model VARCHAR, thinking VARCHAR, switches_json VARCHAR, updated_at TIMESTAMP)",
]


def ensure(con) -> None:
    for d in DDL:
        con.execute(d)


def _meta(con, key: str) -> Optional[tuple]:
    r = con.execute("SELECT value, seen_at FROM mine_meta_s89 WHERE key=?", [key]).fetchone()
    return (r[0], r[1]) if r else None


def _set_meta(con, key: str, value: str, now: datetime) -> None:
    con.execute("DELETE FROM mine_meta_s89 WHERE key=?", [key])
    con.execute("INSERT INTO mine_meta_s89 VALUES (?,?,?)", [key, value, now])


# --- his Indian holdings: the Kite snapshot -----------------------------------------------------------------------------------------------------

_REFRESH_LOCK = threading.Lock()


def refresh_india(rt, con, now: datetime, force: bool = False, kite=None) -> dict:
    """Read Kite holdings (read-only) at most every REFRESH_MIN minutes and REPLACE the one snapshot. -> {"state": ok | expired | none | error, "snapshot_at"}."""
    ensure(con)
    last = _meta(con, "india_refresh")
    if not force and last and last[1] and now - last[1] < timedelta(minutes=REFRESH_MIN):
        return {"state": last[0], "snapshot_at": last[1], "cached": True}
    k = kite
    if k is None:
        try:
            from pflab.ingest import kite as km
            sec = getattr(rt, "secrets", None)
            if sec is None:
                from pflab.pm import secrets as sc
                sec = sc.load()
            k = km.client(sec, now=now)
        except Exception:
            k = None
    if k is None:
        _set_meta(con, "india_refresh", "expired", now)
        return {"state": "expired", "snapshot_at": _snap_at(con)}
    try:
        rows = k.holdings()
    except Exception as e:                                          # a failure keeps the old snapshot and says so
        _set_meta(con, "india_refresh", "error", now)
        return {"state": "error", "snapshot_at": _snap_at(con), "error": type(e).__name__}
    try:                                                            # S91: the WHOLE response is checked before the snapshot is touched
        new = []
        for r in rows or []:
            qty = float(r.get("quantity", 0) or 0) + float(r.get("t1_quantity", 0) or 0)
            if qty <= 0:
                continue
            row = [r.get("tradingsymbol"), r.get("isin"), r.get("exchange"), qty, float(r.get("average_price", 0) or 0), float(r.get("last_price", 0) or 0),
                   float(r.get("day_change_percentage", 0) or 0), now]
            if not row[0] or not row[1] or not all(math.isfinite(x) for x in row[3:7]):
                raise ValueError("a holdings row has no symbol, no ISIN or a number that is not finite")
            new.append(row)
    except (ValueError, TypeError, AttributeError) as e:
        _set_meta(con, "india_refresh", "error", now)               # the last complete snapshot stays; the screen says the refresh failed
        return {"state": "error", "snapshot_at": _snap_at(con), "error": f"{type(e).__name__}: {str(e)[:120]}"}
    with _REFRESH_LOCK:                                             # one replace at a time: an older response cannot overwrite a newer snapshot
        newest = _snap_at(con)
        if newest is not None and newest > now:
            return {"state": "ok", "snapshot_at": newest, "cached": True}
        con.execute("BEGIN")
        try:
            con.execute("DELETE FROM mine_in_s89")
            for row in new:
                con.execute("INSERT OR REPLACE INTO mine_in_s89 VALUES (?,?,?,?,?,?,?,?)", row)
            con.execute("DELETE FROM mine_meta_s89 WHERE key=?", ["india_refresh"])
            con.execute("INSERT INTO mine_meta_s89 VALUES (?,?,?)", ["india_refresh", "ok", now])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return {"state": "ok", "snapshot_at": now}


def _snap_at(con):
    r = con.execute("SELECT max(snapshot_at) FROM mine_in_s89").fetchone()
    return r[0] if r else None


# --- his US holdings: by hand ---------------------------------------------------------------------------------------------------------------------

TICKER = re.compile(r"^[A-Z][A-Z.\-]{0,5}$")


def validate_us(ticker: Any, shares: Any, avg: Any, bought_on: Any, today: date) -> Dict[str, Any]:
    t = str(ticker or "").strip().upper()
    if not TICKER.match(t):
        raise ValueError("The ticker is letters only, up to 6 (for example NVDA).")
    try:
        q, p = float(shares), float(avg)
    except (TypeError, ValueError):
        raise ValueError("Shares and average price must be numbers.")
    if not (0 < q <= 1_000_000) or not math.isfinite(q):
        raise ValueError("Shares must be more than 0.")
    if not (0 < p <= 10_000_000) or not math.isfinite(p):
        raise ValueError("The average price must be more than 0.")
    d = None
    if bought_on:
        try:
            d = date.fromisoformat(str(bought_on)[:10])
        except ValueError:
            raise ValueError("The date must look like 2026-11-15.")
        if d > today:
            raise ValueError("The purchase date cannot be in the future.")
    return {"ticker": t, "shares": q, "avg_price": p, "bought_on": d}


def us_change(con, now: datetime, action: str, ticker: str, shares=None, avg_price=None, bought_on=None) -> dict:
    ensure(con)
    if action == "remove":
        t = str(ticker or "").strip().upper()
        n = con.execute("SELECT count(*) FROM mine_us_s89 WHERE ticker=?", [t]).fetchone()[0]
        if not n:
            raise ValueError(f"{t} is not in your US holdings.")
        con.execute("DELETE FROM mine_us_s89 WHERE ticker=?", [t])
        return {"ok": True, "removed": t}
    cur = con.execute("SELECT shares, avg_price, bought_on FROM mine_us_s89 WHERE ticker=?", [str(ticker or "").strip().upper()]).fetchone()
    if action == "add" and cur:
        raise ValueError("You already hold it: change its shares instead.")
    if action == "set" and not cur:
        raise ValueError("It is not in your US holdings yet: add it first.")
    if action not in ("add", "set"):
        raise ValueError("action must be add, set or remove")
    v = validate_us(ticker, shares if shares is not None else (cur[0] if cur else None), avg_price if avg_price is not None else (cur[1] if cur else None),
                    bought_on if bought_on is not None else (cur[2] if cur else None), now.date())
    con.execute("INSERT OR REPLACE INTO mine_us_s89 VALUES (?,?,?,?,?)", [v["ticker"], v["shares"], v["avg_price"], v["bought_on"], now])
    return {"ok": True, **{k: (str(x) if isinstance(x, date) else x) for k, x in v.items()}}


# --- his watchlist -----------------------------------------------------------------------------------------------------------------------------------

def watch_list(con) -> List[dict]:
    ensure(con)
    return [{"symbol": s, "market": m, "why": w or "", "alerts": json.loads(a or "[]"), "added_at": str(t)[:16]} for s, m, w, a, t in
            con.execute("SELECT symbol, market, why, alerts_json, added_at FROM watch_s89 ORDER BY added_at").fetchall()]


def watch_add(con, now: datetime, symbol: str, market: str = "India", why: str = "", alerts: Optional[List[str]] = None) -> dict:
    ensure(con)
    s = str(symbol or "").strip().upper()
    if not re.match(r"^[A-Z0-9&.\-]{1,20}$", s):
        raise ValueError("Type a name or ticker first.")
    market = {"IN": "India", "US": "US"}.get(str(market).upper(), str(market))
    if market not in ("India", "US"):
        raise ValueError("Market is India or US.")
    al = [a for a in (alerts if alerts is not None else ["moves 3%+", "news"]) if a in ALERTS]
    if con.execute("SELECT count(*) FROM watch_s89 WHERE symbol=?", [s]).fetchone()[0]:
        con.execute("UPDATE watch_s89 SET why=?, alerts_json=?, market=? WHERE symbol=?", [why[:200], json.dumps(al), market, s])
        return {"ok": True, "updated": s}
    if con.execute("SELECT count(*) FROM watch_s89").fetchone()[0] >= WATCH_CAP:
        raise ValueError(f"The watchlist holds up to {WATCH_CAP} names. Stop watching one first.")
    con.execute("INSERT INTO watch_s89 VALUES (?,?,?,?,?)", [s, market, why[:200], json.dumps(al), now])
    return {"ok": True, "added": s, "count": con.execute("SELECT count(*) FROM watch_s89").fetchone()[0]}


def watch_remove(con, symbol: str) -> dict:
    ensure(con)
    s = str(symbol or "").strip().upper()
    con.execute("DELETE FROM watch_s89 WHERE symbol=?", [s])
    return {"ok": True, "removed": s}


# --- reading the holdings ---------------------------------------------------------------------------------------------------------------------------

def _usd_inr() -> float:
    try:
        from pflab.agents import analyst as an
        return float(an.config()["usd_inr"])
    except Exception:
        return 0.0


def _spark_in(con, root, isin, asof: date, n: int = 60) -> List[float]:
    try:
        from pflab.hq import stocks
        c = stocks.closes(con, root, isin, asof).iloc[-n:]
        return [round(float(x), 2) for x in c.values]
    except Exception:
        return []


def _us_prices(root, ticker: str) -> Optional[dict]:
    try:
        from pflab.us import data as ud
        b = ud.bars(ticker, root)
        if b is None or len(b) < 1:
            return None
        last = float(b["close"].iloc[-1])
        prev = float(b["close"].iloc[-2]) if len(b) > 1 else last
        return {"price": last, "day_pct": (last / prev - 1) * 100 if prev else 0.0, "spark": [round(float(x), 2) for x in b["close"].iloc[-60:].values], "as_of": str(b["date"].iloc[-1])}
    except Exception:
        return None


def _view_for(con, isin: Optional[str], now: datetime) -> Optional[dict]:
    """Claude's view of a name he holds, from the thinking loop's latest decision on it (a closed list); None when it has not looked: shown as 'not yet'."""
    if not isin:
        return None
    try:
        r = con.execute("SELECT acted_option, decided_on, reason FROM think_decisions_s84 WHERE isin=? ORDER BY decided_on DESC, decision_id DESC LIMIT 1", [isin]).fetchone()
    except Exception:
        return None
    if not r or not r[0] or (now.date() - r[1]).days > 30:
        return None
    return {"label": VIEWS.get(str(r[0]), "watch"), "option": r[0], "since": str(r[1]), "why": str(r[2] or "")[:260]}


def mine(rt, con, now: datetime, tab: str = "all") -> dict:
    ensure(con)
    root = rt.data_root
    rows: List[dict] = []
    fx = _usd_inr()
    snap = _snap_at(con)
    if tab in ("all", "in"):
        for sym, isin, qty, avg, last, dchg in con.execute("SELECT symbol, isin, qty, avg_price, last_price, day_change_pct FROM mine_in_s89 ORDER BY symbol").fetchall():
            val = qty * last
            rows.append({"id": sym, "market": "in", "symbol": sym, "name": sym, "qty": qty, "avg": avg, "price": last, "value_inr": val, "day_pct": dchg,
                         "since_buy_pct": (last / avg - 1) * 100 if avg else None, "spark": _spark_in(con, root, isin, now.date()), "view": _view_for(con, isin, now), "isin": isin})
    if tab in ("all", "us"):
        for t, q, p, d in con.execute("SELECT ticker, shares, avg_price, bought_on FROM mine_us_s89 ORDER BY ticker").fetchall():
            px = _us_prices(root, t)
            val = (px["price"] * q * fx) if (px and fx) else None
            rows.append({"id": t, "market": "us", "symbol": t, "name": t, "qty": q, "avg": p, "price": px["price"] if px else None, "value_inr": val, "day_pct": px["day_pct"] if px else None,
                         "since_buy_pct": (px["price"] / p - 1) * 100 if px and p else None, "spark": px["spark"] if px else [], "view": None, "bought_on": str(d) if d else None,
                         "price_as_of": px["as_of"] if px else None})
    total = sum(r["value_inr"] for r in rows if r["value_inr"])
    for r in rows:
        r["weight"] = (r["value_inr"] / total * 100) if (total and r["value_inr"]) else None
    rows.sort(key=lambda r: -(r["value_inr"] or 0))
    in_v = sum(r["value_inr"] for r in rows if r["market"] == "in" and r["value_inr"])
    us_v = sum(r["value_inr"] for r in rows if r["market"] == "us" and r["value_inr"])
    today = sum((r["value_inr"] * r["day_pct"] / (100 + r["day_pct"])) for r in rows if r["value_inr"] and r["day_pct"] is not None)
    state = _meta(con, "india_refresh")
    alarms = []
    try:
        syms = [r["symbol"] for r in rows]
        if syms:
            q = ",".join("?" for _ in syms)
            alarms = [{"symbol": s, "headline": h, "at": str(a)[:16]} for s, h, a in con.execute(
                f"SELECT symbol, headline, first_seen_at FROM alarm_s86 WHERE symbol IN ({q}) ORDER BY alarm_id DESC LIMIT 8", syms).fetchall()]
    except Exception:
        pass
    n_in = con.execute("SELECT count(*) FROM mine_in_s89").fetchone()[0]
    return {"tab": tab, "rows": rows, "summary": {"value_inr": total or None, "india_inr": in_v or None, "us_inr": us_v or None, "today_inr": today if rows else None,
                                                    "today_pct": (today / (total - today) * 100) if total and total != today else None, "fx": fx or None},
            "mix": [{"name": "India", "w": in_v / total} for _ in [0] if total and in_v] + [{"name": "US", "w": us_v / total} for _ in [0] if total and us_v],
            "state": {"kite": state[0] if state else "never", "snapshot_at": str(snap)[:16] if snap else None, "india_names": n_in},
            "alarms": alarms,
            "empty": None if rows else ("No holdings yet. India comes from your Kite login; add US holdings by hand under Add and watch." if True else "")}


# --- the Home screen ----------------------------------------------------------------------------------------------------------------------------------

def status_rows(con, now: datetime, token_ok: bool, plan: dict) -> dict:
    """S91: what the morning needs to show at a glance: the running release, the last complete Kite snapshot, the latest closed five-minute candle, the day's saved study, and the next action
    or the specific reason something waits. Each row {name, text, state: ok | wait | bad}."""
    rows: List[dict] = []
    try:
        from pflab import release
        r = (release.load() or {}).get("app") or {}
        rows.append({"name": "Running release", "text": r.get("tag") or "workshop copy", "state": "ok"})
    except Exception:
        pass
    snap = _snap_at(con)
    m = _meta(con, "india_refresh")
    if snap is None:
        rows.append({"name": "Your holdings (Kite)", "text": "no snapshot yet" + ("" if token_ok else ": log in to Kite"), "state": "wait"})
    else:
        age = (now - snap).total_seconds() / 60
        bad = bool(m and m[0] == "error")
        rows.append({"name": "Your holdings (Kite)", "text": f"complete snapshot {str(snap)[11:16]} ({'today' if snap.date() == now.date() else str(snap)[:10]})" + (" · the last refresh failed, this one is kept" if bad else ""),
                     "state": "bad" if bad else ("ok" if age < 15 or snap.date() != now.date() else "wait")})
    try:
        from pflab.ingest import intraday5
        lc = intraday5.latest_closed_any(con)
        last = con.execute("SELECT started_at, status, detail FROM job_runs WHERE job='candles_5m' ORDER BY run_id DESC LIMIT 1").fetchone()
        if lc:
            rows.append({"name": "Latest closed 5-minute candle", "text": lc[5:] if lc[:4] == str(now.year) else lc, "state": "ok"})
        else:
            why = "waiting for the Kite login" if not token_ok else ("starts in market hours; the first session candles arrive within 5 minutes of 09:20" if last is None else "none stored yet")
            rows.append({"name": "Latest closed 5-minute candle", "text": why, "state": "wait"})
    except Exception:
        pass
    try:
        from pflab.app import investigation
        inv = investigation.get(con, now.date())
        if inv and inv["status"] == "done":
            rows.append({"name": "Saved study today", "text": f"{inv['subject']}: {inv['result'].get('verdict')} (p {inv['result'].get('p_value')}), {inv['period_from']} to {inv['period_to']}", "state": "ok"})
        else:
            why = (inv or {}).get("detail") or investigation.waiting_reason(con, now) or "runs within 15 minutes"
            rows.append({"name": "Saved study today", "text": why, "state": "wait"})
    except Exception:
        pass
    nxt = ("Log in to Kite: nothing live starts until you do" if not token_ok else "Paused: the plan limit; code-only work goes on" if plan.get("thinking") == "paused"
           else "Not signed in on your Claude plan" if not plan.get("signed_in") else "Nothing needs you: it is working through the day's agenda")
    return {"rows": rows, "next": nxt}


def _eyes(con, now: datetime) -> List[dict]:
    try:
        from pflab.think import alarm
        rows = alarm.eyes(con, now)
    except Exception:
        rows = []
    out = []
    for e in rows:
        age = e.get("age_min")
        state = "down" if e.get("blind_since") else ("ok" if age is not None and age < 180 else ("late" if age is not None else "never"))
        out.append({"name": e.get("label") or e.get("source"), "state": state, "age_min": None if age is None else round(age), "error": e.get("error")})
    return out


def home(rt, con, now: datetime) -> dict:
    ensure(con)
    needs: List[dict] = []
    kite = _meta(con, "india_refresh")
    try:                                                              # S90: the day's Kite token decides, not a snapshot note that may be minutes old
        from pflab.ingest import kite as _k
        token_ok = _k.TokenStore().load(now) is not None
    except Exception:
        token_ok = False
    if token_ok and (not kite or kite[0] in ("expired", "none", "never")):
        try:
            refresh_india(rt, con, now, force=True)
            kite = _meta(con, "india_refresh")
        except Exception:
            pass
    kite_bad = not token_ok
    try:
        from pflab.oper import build
        build.ensure(con)
        for mid, state, text in con.execute("SELECT m.msg_id, c.state, substr(m.text,1,320) FROM cards_s85 c JOIN chat_messages m ON m.msg_id = c.msg_id WHERE c.state='open' ORDER BY m.msg_id DESC LIMIT 12").fetchall():
            needs.append({"kind": "fix ready" if text.startswith("A fix is ready") else "question", "id": f"card:{mid}", "msg_id": mid, "text": text.split("\n")[0][:160], "detail": text[:320], "yes_no": True})
    except Exception:
        pass
    try:
        from pflab.agents import questions
        for qid, agent, text in questions.open_questions(con)[:8]:
            needs.append({"kind": "question", "id": f"q:{qid}", "qid": qid, "text": str(text)[:160], "detail": str(text)[:320], "yes_no": True})
    except Exception:
        pass
    try:
        for aid, sym, head, at in con.execute("SELECT alarm_id, symbol, headline, first_seen_at FROM alarm_s86 WHERE day=? AND decided_at IS NULL AND coalesce(mode,'live')='live' ORDER BY alarm_id DESC LIMIT 5", [now.date()]).fetchall():
            needs.append({"kind": "alarm", "id": f"alarm:{aid}", "text": f"{sym}: {head}"[:160], "detail": "A case is open; the decision is told here and on Telegram.", "when": str(at)[:16], "link": "#/graph"})
    except Exception:
        pass
    try:
        from pflab.oper import plans as _pl
        for pl in _pl.listing(con, 6):
            if pl["status"] == "proposed":
                needs.insert(0, {"kind": "plan", "id": f"plan:{pl['plan_id']}", "plan_id": pl["plan_id"], "text": pl["title"], "detail": f"{len(pl['steps'])} steps, about {pl['est_tokens']:,} tokens of your plan",
                                 "steps": [{"n": s["n"], "text": s["text"], "uses": s["uses"]} for s in pl["steps"]], "plan_card": True})
    except Exception:
        pass
    if kite_bad:
        needs.insert(0, {"kind": "do this", "id": "kite", "text": "Log in to Kite", "detail": "Takes 20 seconds. Until then your money shows the last snapshot.", "link": "#/kite"})
    heard = []
    try:
        for sym, head, at, mode, dec in con.execute("SELECT symbol, headline, first_seen_at, coalesce(mode,'live'), decided_at FROM alarm_s86 ORDER BY alarm_id DESC LIMIT 8").fetchall():
            heard.append({"kind": "alarm" if dec is not None or mode == "live" else "noted", "symbol": sym, "text": str(head)[:140], "at": str(at)[:16]})
    except Exception:
        pass
    eyes = _eyes(con, now)
    from pflab.llm import claude_plan as cp
    plan = cp.state(con, now)
    banner = None
    if kite_bad:
        banner = {"kind": "kite", "title": "Kite login expired", "text": "Your Indian prices are the last snapshot. Claude's India book will not trade until you log in; stops are still checked on the last prices.", "cta": "Log in to Kite", "href": "#/kite"}
    elif plan["thinking"] == "paused":
        banner = {"kind": "plan", "title": f"Plan limit reached · thinking paused until {plan['paused_until']}", "text": "No model calls until then. The paper book's rails, stops, alarm keywords and Telegram alerts keep running without the model. Chat answers wait too.", "cta": "See usage", "href": "#/usage"}
    elif not plan["signed_in"]:
        banner = {"kind": "plan", "title": "Not signed in on your Claude plan", "text": plan["detail"], "cta": "Settings", "href": "#/settings"}
    else:
        down = [e for e in eyes if e["state"] == "down"]
        if down:
            banner = {"kind": "down", "title": f"{down[0]['name']} not answering", "text": "Alarms keep running on the sources that answer. It retries every 15 minutes and tells you on Telegram when it is back.", "cta": "See its eyes", "href": "#/agents"}
    story = None
    try:                                                              # the most likely open storyline (the graph's own table)
        cur = con.execute("SELECT * FROM storylines_s80 WHERE status='open' ORDER BY probability DESC NULLS LAST LIMIT 1")
        cols = [d[0] for d in cur.description]
        r = cur.fetchone()
        if r:
            row = dict(zip(cols, r))
            n_open = con.execute("SELECT count(*) FROM storylines_s80 WHERE status='open'").fetchone()[0]
            story = {"claim": row.get("claim"), "probability": row.get("probability"), "direction": row.get("direction"), "more": max(0, int(n_open) - 1)}
    except Exception:
        story = None
    day0 = datetime(now.year, now.month, now.day)

    def n_(sql, args=()):
        try:
            return int(con.execute(sql, list(args)).fetchone()[0] or 0)
        except Exception:
            return None
    counts = {"checks": n_("SELECT count(*) FROM job_runs WHERE started_at >= ? AND status='ok'", [day0]),
              "forecasts": n_("SELECT count(*) FROM forecasts_s79 WHERE made_at >= ? AND source='live'", [day0]),
              "filings": n_("SELECT count(*) FROM kg_docs WHERE kind='filing' AND published_at >= ?", [day0])}
    last_job = None
    try:
        r = con.execute("SELECT job, started_at, finished_at, status FROM job_runs ORDER BY run_id DESC LIMIT 1").fetchone()
        last_job = {"job": r[0], "started_at": str(r[1])[:16], "finished_at": str(r[2])[:16] if r[2] else None, "status": r[3]} if r else None
    except Exception:
        last_job = None
    recent = []
    try:                                                              # S90: what it actually did, newest first, for "What it is doing now"
        for job, st_at, status in con.execute("SELECT job, started_at, status FROM job_runs WHERE status <> 'skipped' ORDER BY run_id DESC LIMIT 7").fetchall():
            recent.append({"job": job, "at": str(st_at)[:16], "status": status})
    except Exception:
        recent = []
    paper = None
    try:
        from pflab.paper import manager
        p = manager.status(con, rt.data_root)
        if p.get("started"):
            days = p.get("days") or []
            paper = {"value": p.get("value"), "days": [[str(d.get("date") or d.get("day")), d.get("value")] for d in days[-120:]], "nifty": [[str(d.get("date") or d.get("day")), d.get("value")] for d in (p.get("nifty") or [])[-120:]]}
    except Exception:
        paper = None
    m = mine(rt, con, now, "all")
    return {"now": str(now)[:16], "banner": banner, "needs": needs, "heard": heard, "eyes": eyes, "plan": plan, "paper": paper, "mine": {"value_inr": m["summary"]["value_inr"], "today_pct": m["summary"]["today_pct"],
            "snapshot_at": m["state"]["snapshot_at"]}, "fall_chance": _fall(con), "plans": _plans_now(con), "storyline": story, "counts": counts, "last_job": last_job, "recent": recent, "kite_ok": token_ok, "status": status_rows(con, now, token_ok, plan), "kite_login": getattr(rt, "kite_state", None),
            "doing": {"mode": (con.execute("SELECT mode FROM desk_sessions_s84 ORDER BY session_id DESC LIMIT 1").fetchone() or [None])[0] if _has(con, "desk_sessions_s84") else None}}


def _fall(con) -> Optional[dict]:
    """The stored chance of a fall (the forecaster's own table), or None while none has been made."""
    try:
        r = con.execute("SELECT p, horizon_sessions, as_of, threshold, ref_high FROM fall_risk_s79 WHERE market='IN' AND source='live' AND p IS NOT NULL ORDER BY as_of DESC LIMIT 1").fetchone()
    except Exception:
        return None
    if not r:
        return None
    drop = (1 - float(r[3]) / float(r[4])) * 100 if r[3] and r[4] else None
    return {"p": float(r[0]), "horizon": int(r[1]), "as_of": str(r[2]), "drop_pct": drop}


def _plans_now(con) -> list:
    try:
        from pflab.oper import plans as _pl
        return [p for p in _pl.listing(con, 6) if p["status"] in ("running", "paused")]
    except Exception:
        return []


def _has(con, table: str) -> bool:
    try:
        con.execute(f"SELECT 1 FROM {table} LIMIT 1")
        return True
    except Exception:
        return False


# --- the Lab: a pair ------------------------------------------------------------------------------------------------------------------------------------

def pair(con, root, asof: date, a: str, b: str, years: int = 3) -> dict:
    """Both normalised series, the gap's z-score, the cointegration p-value, the hedge ratio, the half-life and the correlation, with a coded verdict. Worked out here, 0 tokens."""
    import numpy as np
    import pandas as pd
    from pflab.agents.tradecheck import isin_of
    from pflab.hq import stocks
    cs = []
    for sym in (a, b):
        s = str(sym or "").upper().strip()
        if not s:
            raise ValueError("Give two names.")
        isin = isin_of(con, s)
        if not isin:
            raise ValueError(f"{s or 'a name'} is not a name the record knows.")
        cs.append(stocks.closes(con, root, isin, asof).iloc[-252 * years:].rename(s))
    df = pd.concat(cs, axis=1).dropna()
    if len(df) < 120:
        raise ValueError(f"Too little shared history ({len(df)} days) for a pair study.")
    na, nb = df.columns
    la, lb = np.log(df[na]), np.log(df[nb])
    beta = float(np.polyfit(lb, la, 1)[0])
    spread = la - beta * lb
    z = float((spread.iloc[-1] - spread.mean()) / spread.std()) if spread.std() else 0.0
    from statsmodels.tsa.stattools import coint
    p = float(coint(la, lb)[1])
    ds, lag = spread.diff().dropna(), spread.shift(1).dropna()
    k = float(np.polyfit(lag.loc[ds.index], ds, 1)[0])
    half = float(-math.log(2) / k) if k < 0 else None
    r = np.log(df).diff().dropna()
    corr = float(r[na].corr(r[nb]))
    verdict = "tied" if (p < 0.05 and half is not None and half < 60) else ("loose" if p < 0.15 else "not tied")
    norm = lambda s: [round(float(x), 2) for x in (s / s.iloc[0] * 100).values]
    return {"a": na, "b": nb, "days": int(len(df)), "dates": [str(d)[:10] for d in df.index], "series_a": norm(df[na]), "series_b": norm(df[nb]), "gap_z": round(z, 2), "p_value": round(p, 3),
            "hedge_ratio": round(beta, 2), "half_life_days": None if half is None else round(half, 1), "correlation": round(corr, 2), "verdict": verdict,
            "label": "worked out by the Lab tools, 0 tokens", "note": "a description of the past, not a forecast"}


# --- agents ------------------------------------------------------------------------------------------------------------------------------------------------

AGENTS = [("quick", "Quick answers", "chat_light"), ("full", "Full operator", "chat"), ("desk", "Daily desk", "desk"), ("case", "Case worker", "cases"), ("alarm", "Alarm reader", "cases"),
          ("fixer", "Fixer", "build"), ("weekly", "Weekly look", "desk")]
MODELS = ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5")
LEVELS = ("low", "medium", "high", "max")


def agents(con, now: datetime) -> dict:
    ensure(con)
    from pflab.llm import claude_plan as cp
    from pflab.llm import gateway as gw
    st = cp.state(con, now)
    sets = {a: (m, t, json.loads(sw or "{}")) for a, m, t, sw in con.execute("SELECT agent, model, thinking, switches_json FROM agent_settings_s89").fetchall()}
    defaults = {"quick": ("read", "low"), "full": ("read", "medium"), "desk": ("read", "medium"), "case": ("decide", "high"), "alarm": ("quick", "low"), "fixer": ("read", "medium"), "weekly": ("read", "medium")}
    out = []
    for key, label, klass in AGENTS:
        role, lvl = defaults[key]
        try:
            spec = gw.resolve(role, engine="claude_plan")
            dm, dl = spec["model"], lvl
        except Exception:
            dm, dl = None, lvl
        m, t, sw = sets.get(key, (None, None, {}))
        last = None
        try:
            r = con.execute("SELECT max(created_at) FROM api_calls WHERE mode='plan' AND topic LIKE ?", [f"plan:{klass}:%"]).fetchone()
            last = str(r[0])[:16] if r and r[0] else None
        except Exception:
            pass
        out.append({"key": key, "label": label, "model": m or dm, "thinking": t or dl, "default_model": dm, "default_thinking": dl, "changed": bool(m or t), "last_run": last,
                    "tokens_today": st["tokens_today"].get(klass, {}).get("used", 0), "budget": st["tokens_today"].get(klass, {}).get("budget"),
                    "tools": {"quick": "5 small tools", "full": "the system's tools (30 by default, the rest by name)", "desk": "none (reads facts)", "case": "the case tools", "alarm": "none",
                              "fixer": "files in src and tests, git on a fix branch, tests", "weekly": "none (reads facts)"}[key],
                    "applies": ("this reader uses the local model, not a plan model" if key == "alarm" else "from the next run")})
    sw = sets.get("_switches", (None, None, {}))[2]
    skills = []
    try:
        from pflab.oper import texts
        for name, body in texts.SKILLS.items():
            m = re.search(r"^description:\s*(.+)$", body, re.M)
            skills.append({"name": name, "description": (m.group(1) if m else "").strip()})
    except Exception:
        skills = []
    return {"agents": out, "models": list(MODELS), "levels": list(LEVELS), "switches": {k: bool(sw.get(k, False)) for k in ("kite", "nse", "tijori", "connectors")},
            "switch_note": "These load for full answers only and are off by default.", "signed_in": st["signed_in"], "skills": skills}


def agents_set(con, now: datetime, body: dict) -> dict:
    ensure(con)
    if "switch" in body:
        k = str(body["switch"])
        if k not in ("kite", "nse", "tijori", "connectors"):
            raise ValueError("unknown switch")
        cur = con.execute("SELECT switches_json FROM agent_settings_s89 WHERE agent='_switches'").fetchone()
        sw = json.loads(cur[0]) if cur and cur[0] else {}
        sw[k] = bool(body.get("on"))
        con.execute("DELETE FROM agent_settings_s89 WHERE agent='_switches'")
        con.execute("INSERT INTO agent_settings_s89 VALUES ('_switches', NULL, NULL, ?, ?)", [json.dumps(sw), now])
        return {"ok": True, "switch": k, "on": sw[k]}
    key, model, thinking = str(body.get("agent") or ""), body.get("model"), body.get("thinking")
    if key not in {a[0] for a in AGENTS}:
        raise ValueError("unknown agent")
    if model is not None and model not in MODELS:
        raise ValueError("model must be one of " + ", ".join(MODELS))
    if thinking is not None and thinking not in LEVELS:
        raise ValueError("thinking must be one of " + ", ".join(LEVELS))
    cur = con.execute("SELECT model, thinking, switches_json FROM agent_settings_s89 WHERE agent=?", [key]).fetchone()
    m, t = (model if model is not None else (cur[0] if cur else None)), (thinking if thinking is not None else (cur[1] if cur else None))
    con.execute("DELETE FROM agent_settings_s89 WHERE agent=?", [key])
    con.execute("INSERT INTO agent_settings_s89 VALUES (?,?,?,?,?)", [key, m, t, "{}", now])
    return {"ok": True, "agent": key, "model": m, "thinking": t, "applies": "from the next run"}


def agent_override(con, key: str) -> Optional[tuple]:
    """(model, thinking) he set for an agent (None, None when he has not): read by the chat roads at the start of a run."""
    try:
        r = con.execute("SELECT model, thinking FROM agent_settings_s89 WHERE agent=?", [key]).fetchone()
    except Exception:
        return None
    return (r[0], r[1]) if r else None


# --- registration ----------------------------------------------------------------------------------------------------------------------------------------

def register(app, rt) -> None:
    def err(e: Exception):
        raise HTTPException(400, str(e))

    @app.get("/api/mine")
    def mine_view(tab: str = "all", refresh: bool = False):
        con = rt.cursor()
        now = rt.clock()
        ensure(con)
        try:
            r = refresh_india(rt, con, now, force=refresh)
        except Exception:
            r = {"state": "error"}
        return json.loads(json.dumps(mine(rt, con, now, tab if tab in ("all", "in", "us") else "all"), default=str))

    @app.post("/api/mine/us")
    def mine_us(body: dict = Body(...)):
        con = rt.cursor()
        try:
            out = us_change(con, rt.clock(), str(body.get("action") or "add"), body.get("ticker"), body.get("shares"), body.get("avg_price"), body.get("bought_on"))
        except ValueError as e:
            err(e)
        rt.bump("portfolio")
        return out

    @app.get("/api/mine/watch")
    def mine_watch():
        con = rt.cursor()
        rows = watch_list(con)
        for r in rows:
            r["note"] = None
            try:
                h = con.execute("SELECT headline FROM alarm_s86 WHERE symbol=? ORDER BY alarm_id DESC LIMIT 1", [r["symbol"]]).fetchone()
                r["note"] = h[0] if h else None
            except Exception:
                pass
        return {"rows": rows, "count": len(rows), "cap": WATCH_CAP, "alerts": list(ALERTS)}

    @app.post("/api/mine/watch")
    def mine_watch_post(body: dict = Body(...)):
        con = rt.cursor()
        try:
            if str(body.get("action") or "add") == "remove":
                return watch_remove(con, body.get("symbol"))
            return watch_add(con, rt.clock(), body.get("symbol"), body.get("market") or "India", str(body.get("why") or ""), body.get("alerts"))
        except ValueError as e:
            err(e)

    @app.get("/api/home")
    def home_view():
        con = rt.cursor()
        now = rt.clock()
        try:
            refresh_india(rt, con, now)
        except Exception:
            pass
        return json.loads(json.dumps(home(rt, con, now), default=str))

    @app.post("/api/lab/pair")
    def lab_pair(body: dict = Body(...)):
        try:
            return json.loads(json.dumps(pair(rt.cursor(), rt.data_root, rt.clock().date(), str(body.get("a") or ""), str(body.get("b") or "")), default=str))
        except ValueError as e:
            err(e)

    from pflab.app import s89b

    @app.get("/api/lab/presets")
    def lab_presets():
        return {"scenarios": s89b.presets(rt.cursor(), rt.clock()), "horizons": list(s89b.HORIZONS), "bases": ["mine", "paper"]}

    @app.post("/api/lab/simulate")
    def lab_simulate(body: dict = Body(...)):
        try:
            return json.loads(json.dumps(s89b.simulate(rt, rt.cursor(), rt.clock(), str(body.get("scenario") or "normal"), int(body.get("horizon") or 60), str(body.get("basis") or "paper")), default=str))
        except (ValueError, TypeError) as e:
            err(e)

    @app.get("/api/lab/forecast")
    def lab_forecast(market: str = "IN", subject: str = ""):
        return json.loads(json.dumps(s89b.forecast(rt.cursor(), market, subject or None, rt.data_root), default=str))

    @app.get("/api/lab/pairs")
    def lab_pairs():
        return json.loads(json.dumps({"pairs": s89b.pairs_of_book(rt, rt.cursor(), rt.clock())}, default=str))

    @app.get("/api/book")
    def book_view(market: str = "IN"):
        return json.loads(json.dumps(s89b.book(rt, rt.cursor(), rt.clock(), market), default=str))

    @app.get("/api/graph/ego")
    def graph_ego_view(symbol: str = ""):
        return json.loads(json.dumps(s89b.graph_ego(rt, rt.cursor(), rt.clock(), symbol or None), default=str))

    @app.get("/api/kite/status")
    def kite_status():
        """Settings' Kite line: the login in progress (idle / waiting / done / failed: why) and the day's token (ok or not)."""
        from pflab.ingest import kite as k
        try:
            tok = k.TokenStore().load(rt.clock()) is not None
        except Exception:
            tok = False
        con = rt.cursor()
        ensure(con)
        m = _meta(con, "india_refresh")
        return {"login": getattr(rt, "kite_state", "idle"), "token_today": tok, "refresh": m[0] if m else None, "refresh_at": str(m[1])[:16] if m else None}

    @app.get("/api/week")
    def week_view():
        return json.loads(json.dumps(s89b.week_status(rt.cursor(), rt.clock()), default=str))

    @app.get("/api/usage/plan")
    def usage_plan_view():
        return json.loads(json.dumps(s89b.usage_plan(rt.cursor(), rt.clock()), default=str))

    @app.get("/api/book/reliability")
    def book_reliability():
        return json.loads(json.dumps(s89b.reliability(rt.cursor(), rt.clock()), default=str))

    @app.get("/api/stock/{symbol}")
    def stock_view(symbol: str, tf: str = "day"):
        try:
            return json.loads(json.dumps(s89b.stock(rt, rt.cursor(), rt.clock(), symbol, tf if tf in ("week", "5min") else "day"), default=str))
        except ValueError as e:
            err(e)

    from pflab.oper import plans as _plans
    _plans.bind(rt)
    from pflab.service import tasks_s91_investigation as _inv
    _inv.bind(rt)

    @app.get("/api/plans")
    def plans_view():
        return json.loads(json.dumps({"plans": _plans.listing(rt.cursor())}, default=str))

    @app.post("/api/plans/{plan_id}/{action}")
    def plans_act(plan_id: int, action: str):
        con = rt.cursor()
        if action == "start":
            _plans.start(con, rt.clock(), plan_id)
        elif action == "cancel":
            _plans.cancel(con, plan_id)
        else:
            raise HTTPException(400, "action is start or cancel")
        rt.bump("plans", "chat")
        return _plans.get(con, plan_id) or {}

    @app.get("/api/agents")
    def agents_view():
        return json.loads(json.dumps(agents(rt.cursor(), rt.clock()), default=str))

    @app.post("/api/agents")
    def agents_post(body: dict = Body(...)):
        try:
            return agents_set(rt.cursor(), rt.clock(), body)
        except ValueError as e:
            err(e)
