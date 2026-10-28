"""Theme exposure and its proposed limit (S64 Phase 5 item 4; the investor 2026-10-25: the system measures and proposes
with evidence, applied after his yes; then it holds itself to them).

    exposure        the share of the portfolio in each theme (stocks, and funds through look-through)
    history         the theme's price history, free of survivorship and hindsight: its published sector index where one
                    exists, else the point-in-time industry group (the Nifty 500 members of each day with that sector label,
                    delisted names included). A named basket of today's names is never used: it is chosen with hindsight
    propose_limit   by code: the largest weight w with w x (the theme's worst fall from its trailing 12-month high) <= 10%
                    of the portfolio, capped at the equity targets; the evidence is stored with the proposal
    propose/resolve a proposal is a `limit_proposals` row and a Needs-from-you question; it applies only on his yes
    breaches        the applied limits against today's exposure
    drift           his holdings inside a basket against the basket's approved weights (more than 5 points apart)
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from pflab import _toml

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "themes.toml"
RISK_BUDGET = 0.10               # the theme's worst fall may cost at most this share of the portfolio
WINDOW = 252                     # sessions: "12 months"
MIN_SESSIONS = 250
DRIFT_POINTS = 0.05
REVISE_AT = 0.20                 # an approved limit is re-proposed when new history moves it by more than this (relative)
KINDS = ("theme_limit", "theme_basket", "theme_member", "dip_reserve", "pot_limit", "us_sleeve")
YES = ("yes", "y", "ok", "okay", "approve", "approved", "apply", "go ahead", "sure")
NO = ("no", "n", "decline", "declined", "reject", "not now", "don't", "dont")


def config(path: Optional[Path] = None, pm_dir: Optional[Path] = None) -> dict:
    """configs/themes.toml plus the basket symbols from the investor's own PFLAB_PM_DIR/theme_baskets.toml (out of git: his
    list overlaps the themes)."""
    cfg = _toml.load(path or CONFIG)
    if path is None:
        from pflab.pm import store
        extra = Path(pm_dir or store.pm_dir()) / "theme_baskets.toml"
        if extra.exists():
            for t, v in _toml.load(extra).get("theme", {}).items():
                if t in cfg.get("theme", {}):
                    cfg["theme"][t]["basket"] = v.get("basket", [])
    return cfg


def symbol_isins(root, symbols: Iterable[str], asof: date) -> Dict[str, str]:
    """NSE symbol -> ISIN in force on `asof` (the panel's symbol map); a symbol with none is left out."""
    m = pd.read_parquet(Path(root) / "panel" / "symbol_isin_map.parquet")
    m = m[(m["valid_from"] <= asof) & (m["valid_to"] >= asof) & m["symbol"].isin(list(symbols))]
    return dict(zip(m["symbol"], m["isin"]))


def basket_isins(con, root, theme: str, asof: date, include_proposed: bool = True) -> Dict[str, str]:
    """symbol -> ISIN of the theme's basket: the stored members (active, or proposed) else the configured list."""
    rows = con.execute("SELECT isin FROM theme_baskets WHERE theme=? AND status IN (" +
                       ("'active','proposed'" if include_proposed else "'active'") + ") AND (until IS NULL OR until > ?)",
                       [theme, asof]).fetchall()
    if rows:
        names = dict(con.execute("SELECT isin, symbol FROM instruments WHERE symbol IS NOT NULL").fetchall())
        return {names.get(i, i): i for (i,) in rows}
    return symbol_isins(root, config().get("theme", {}).get(theme, {}).get("basket", []), asof)


def theme_members(con, root, theme: str, asof: date, isins: Iterable[str]) -> set:
    """The ISINs among `isins` that belong to the theme: in its basket, or in one of its sector-map industries."""
    cfg = config()["theme"][theme]
    out = set(basket_isins(con, root, theme, asof).values()) & set(isins)
    inds = {x.lower() for x in cfg.get("industries", [])}
    if inds:
        from pflab.data import sector_map
        t = sector_map.sector_at(sector_map.load(Path(root)), list(isins), asof, allow_later=False)
        out |= set(t.loc[t["industry"].fillna("").str.lower().isin(inds), "isin"])
    return out


def portfolio_exposures(con, asof: date, lookthrough: Optional[pd.DataFrame] = None) -> dict:
    """The exposure frames (bucket, sector, stock, issuer) with fund look-through where portfolio files are loaded."""
    from pflab.calc import valuation as val
    from pflab.ledger import events as ev
    from pflab.ledger.book import Ledger
    from pflab.risk import exposure
    from pflab.risk.report import instruments_frame
    v = val.value_ledger(Ledger.replay(ev.load(con), upto=asof), val.store_price_fn(con), asof)
    inst = instruments_frame(con)
    if lookthrough is None:
        funds = [i for i in val.by_isin(v)["isin"] if i in set(inst.loc[inst["asset_class"].isin(["etf", "mutual_fund"]), "isin"])]
        from pflab.pm import lookthrough as lkt
        lookthrough = lkt.lookthrough(con, funds, asof)[0] if funds else None
    return {**exposure.exposures(v, inst, lookthrough), "total": v.total}


def exposure_of(con, root, asof: date, ex: Optional[dict] = None) -> dict:
    """{theme: {label, weight, value, holdings: [[symbol, weight]]}} (weights are shares of the whole portfolio)."""
    ex = ex or portfolio_exposures(con, asof)
    stock = ex["stock"]
    names = dict(con.execute("SELECT isin, symbol FROM instruments").fetchall())
    out = {}
    for theme, cfg in config()["theme"].items():
        mem = theme_members(con, root, theme, asof, list(stock["isin"]))
        rows = stock[stock["isin"].isin(mem)]
        out[theme] = {"label": cfg["label"], "weight": float(rows["weight"].sum()), "value": float(rows["value"].sum()),
                      "holdings": [[names.get(r.isin, r.isin), float(r.weight)] for r in rows.itertuples()]}
    return out


# --- history and the proposed limit ------------------------------------------------------------------------------

def pit_proxy_history(mem: pd.DataFrame, labels: pd.DataFrame, r: pd.DataFrame, keywords: List[str],
                      min_names: int = 5) -> pd.Series:
    """The history of an industry group WITHOUT survivorship or hindsight: each month-end the Nifty 500 members of that day
    whose own sector label of that day contains a keyword (names later delisted included: they were members then), held equal
    weight over the next month; the daily total return `r` (sessions x isin). Names that stop trading drop out of the average
    from that day. Fewer than `min_names` live names in a month leave it out (NaN), never filled."""
    sessions = r.index
    every = pd.Series(range(len(sessions)), index=sessions).groupby([sessions.year, sessions.month]).max().tolist()
    kw = [k.lower() for k in keywords]
    out = {}
    lab = labels.assign(hit=labels["industry"].fillna("").str.lower().map(lambda s: any(k in s for k in kw)))
    for k in range(len(every) - 1):
        t = sessions[every[k]]
        live = set(mem[(mem["from_date"] <= t) & (mem["to_date"] > t)]["isin"])
        l = lab[(lab["capture_date"] <= t)].sort_values("capture_date").drop_duplicates("isin", keep="last")
        pick = sorted(live & set(l.loc[l["hit"], "isin"]) & set(r.columns))
        if len(pick) < min_names:
            continue
        seg = r.iloc[every[k] + 1: every[k + 1] + 1][pick]
        out.update(seg.mean(axis=1, skipna=True).to_dict())
    s = pd.Series(out, dtype=float).sort_index()
    return (1 + s).cumprod()


def history(con, root, theme: str, asof: date) -> tuple:
    """(series, how) with no survivorship and no hindsight: the theme's published index where one exists; else the point-in-time
    industry group named in `proxy` (pit_proxy_history). A named basket is never the history: a list of today's names is chosen
    with hindsight (the winners are on it), so it understates the falls."""
    cfg = config()["theme"][theme]
    if cfg.get("index"):
        try:
            from pflab.data import indices
            d = indices.load(cfg["index"], root)
            s = pd.Series(d["close"].to_numpy(float), index=pd.to_datetime(d["date"])).sort_index()
            return s[s.index <= pd.Timestamp(asof)], f"index {cfg['index']} (published, constituents change with the index)"
        except Exception:
            pass
    kws = cfg.get("proxy", [])
    if not kws:
        return pd.Series(dtype=float), "no survivorship-free history for this theme"
    cache = Path(root) / "derived" / f"theme_history_{theme}.parquet"
    if cache.exists() and (datetime.now() - datetime.fromtimestamp(cache.stat().st_mtime)).days < 7:
        c = pd.read_parquet(cache)["v"]
        return c[c.index <= pd.Timestamp(asof)], f"point-in-time industry group {kws} (Nifty 500 members of each day, delisted included)"
    from pflab.data import sector_map
    from pflab.learner import templates as tp
    root = Path(root)
    mem = tp.members(root)
    w = tp.wide_panel(root, sorted(set(mem["isin"])), "2008-06-01", str(asof))
    labels = sector_map.load(root)[["capture_date", "isin", "industry"]]
    labels = labels.assign(capture_date=pd.to_datetime(labels["capture_date"]))
    s = pit_proxy_history(mem, labels, w["r"], kws)
    cache.parent.mkdir(parents=True, exist_ok=True)
    s.rename("v").to_frame().to_parquet(cache)
    return s, f"point-in-time industry group {kws} (Nifty 500 members of each day, delisted included)"


def worst_fall(s: pd.Series, window: int = WINDOW) -> dict:
    """The deepest fall of the close below its trailing `window`-session high, with its date."""
    s = s.dropna()
    if len(s) < MIN_SESSIONS:
        return {"error": f"{len(s)} sessions, {MIN_SESSIONS} needed"}
    dd = s / s.rolling(window, min_periods=60).max() - 1.0
    return {"worst_fall": float(dd.min()), "on": str(dd.idxmin().date()), "sessions": int(len(s)),
            "from": str(s.index[0].date())}


def propose_limit(con, root, theme: str, asof: date, equity_cap: float, risk_budget: float = RISK_BUDGET) -> dict:
    s, how = history(con, root, theme, asof)
    wf = worst_fall(s)
    if "error" in wf:
        return {"theme": theme, "error": wf["error"], "history": how}
    raw = risk_budget / abs(wf["worst_fall"])
    return {"theme": theme, "limit": min(raw, equity_cap), "uncapped": raw, "capped": raw > equity_cap, "history": how,
            "risk_budget": risk_budget, "equity_cap": equity_cap, **wf,
            "rule": f"largest weight w with w x worst 12-month fall <= {risk_budget:.0%} of the portfolio, at most the equity targets"}


def equity_cap(root_targets: Optional[Path] = None) -> float:
    """Equity-type target share (direct stocks plus equity funds): the theme sits inside it."""
    from pflab.plan import targets as tg
    t = tg.load(root_targets)
    return sum(t.buckets[b].target for b in ("equity", "equity_fund") if b in t.buckets)


# --- proposals: asked, answered, applied -------------------------------------------------------------------------

def propose(con, kind: str, key: str, value, evidence: dict, text: str, now: datetime, revise: bool = False) -> Optional[int]:
    """Store a proposal and open its question; None when one for (kind, key) is already pending or applied. With `revise`, an
    applied one does not block (a new value for a limit he approved); a pending one still does. The old value stays in force
    until he says yes to the new one."""
    from pflab.agents import questions
    from pflab.pm.store import next_id
    if kind not in KINDS:
        raise ValueError(f"kind is one of {KINDS}")
    if con.execute("SELECT 1 FROM limit_proposals WHERE kind=? AND key=? AND status IN " +
                   ("('pending')" if revise else "('pending','applied')"), [kind, key]).fetchone():
        return None
    pid = next_id(con, "limit_proposals", "prop_id")
    qid = questions.ask(con, "limits", f"limit:{kind}:{key}:{pid}", f"{text} Answer yes to apply it, no to decline.", now)
    con.execute("INSERT INTO limit_proposals (prop_id, kind, key, value, evidence_json, status, proposed_at, q_id) "
                "VALUES (?,?,?,?,?,?,?,?)", [pid, kind, key, None if value is None else str(value),
                                             json.dumps(evidence, default=str), "pending", now, qid])
    return pid


def _apply_side_effects(con, kind: str, key: str, evidence: dict, now: datetime, approved: bool) -> None:
    if kind == "theme_basket":
        con.execute("UPDATE theme_baskets SET status=? WHERE theme=? AND status='proposed'",
                    ["active" if approved else "rejected", key])
    elif kind == "theme_member":
        theme, isin = key.split(":", 1)
        con.execute("UPDATE theme_baskets SET status=? WHERE theme=? AND isin=? AND status='proposed'",
                    ["active" if approved else "rejected", theme, isin])


def resolve(con, now: datetime) -> dict:
    """Apply or decline each pending proposal whose question the investor has answered. An answer that is neither a clear
    yes nor a clear no leaves it pending."""
    out = {"applied": 0, "declined": 0}
    for pid, kind, key, ev, qid in con.execute(
            "SELECT p.prop_id, p.kind, p.key, p.evidence_json, p.q_id FROM limit_proposals p WHERE p.status='pending' "
            "AND p.q_id IS NOT NULL").fetchall():
        st, ans = con.execute("SELECT status, answer FROM questions WHERE q_id=?", [qid]).fetchone() or ("dropped", None)
        word = (ans or "").strip().lower().rstrip(".! ")
        first = re.split(r"[^a-z']+", word)[0] if word else ""
        share = start = None
        if kind == "us_sleeve" and st == "answered":         # S65: his answer carries the share and an optional start month
            from pflab.risk import sleeve
            share, start = sleeve.parse_answer(ans, now.date())
        said_no = first in NO or word in NO
        if st == "dropped" or (st == "answered" and said_no):
            new = "declined"
        elif st == "answered" and (first in YES or word in YES or (share is not None and not said_no)):
            new = "applied"
        else:
            continue
        if kind == "us_sleeve" and new == "applied":
            if share is None:                                # a yes without a share cannot be applied: ask once more
                from pflab.agents import questions
                nq = questions.ask(con, "limits", f"limit:us_sleeve:share:{pid}:{qid}",
                                   "You said yes to the US sleeve but gave no share. Reply with a number, for example '10' or "
                                   "'10 from February 2027'.", now)
                if nq:
                    con.execute("UPDATE limit_proposals SET q_id=? WHERE prop_id=?", [nq, pid])
                continue
            e = json.loads(ev or "{}")
            e["start"] = start.isoformat() if start else None
            con.execute("UPDATE limit_proposals SET value=?, evidence_json=? WHERE prop_id=?", [str(share), json.dumps(e), pid])
        _apply_side_effects(con, kind, key, json.loads(ev or "{}"), now, new == "applied")
        if new == "applied":                                 # a newer approved value replaces the older one
            con.execute("UPDATE limit_proposals SET status='superseded', decided_at=? WHERE kind=? AND key=? AND status='applied'",
                        [now, kind, key])
        con.execute("UPDATE limit_proposals SET status=?, decided_at=? WHERE prop_id=?", [new, now, pid])
        out[new] += 1
    return out


def applied(con, kind: str, key: str) -> Optional[float]:
    r = con.execute("SELECT value FROM limit_proposals WHERE kind=? AND key=? AND status='applied' ORDER BY prop_id DESC LIMIT 1",
                    [kind, key]).fetchone()
    try:
        return float(r[0]) if r and r[0] is not None else None
    except ValueError:
        return None


def seed_baskets(con, root, asof: date, now: datetime) -> int:
    """Each configured theme's basket as a proposal (members equal-weighted, status 'proposed'); one question per theme."""
    n = 0
    for theme, cfg in config()["theme"].items():
        if con.execute("SELECT 1 FROM theme_baskets WHERE theme=?", [theme]).fetchone():
            continue
        got = symbol_isins(root, cfg.get("basket", []), asof)
        if not got:
            continue
        w = round(1.0 / len(got), 6)
        for isin in got.values():
            con.execute("INSERT INTO theme_baskets VALUES (?,?,?,?,NULL,'proposed')", [theme, isin, w, asof])
        missing = [s for s in cfg.get("basket", []) if s not in got]
        propose(con, "theme_basket", theme, None, {"members": got, "weight_each": w, "not_found": missing},
                f"Basket '{cfg['label']}': {len(got)} names, equal weight ({', '.join(got)})"
                + (f"; not found in the symbol map: {', '.join(missing)}" if missing else "") + ".", now)
        n += 1
    return n


def propose_limits(con, root, asof: date, now: datetime, cap: Optional[float] = None) -> int:
    """A limit proposal for every theme that has none pending or applied and enough history."""
    cap = equity_cap() if cap is None else cap
    n = 0
    for theme, cfg in config()["theme"].items():
        p = propose_limit(con, root, theme, asof, cap)
        if "limit" not in p:
            continue
        old = applied(con, "theme_limit", theme)
        if old is not None and abs(p["limit"] - old) / old <= REVISE_AT:
            continue                                         # the approved limit still stands
        got = propose(con, "theme_limit", theme, round(p["limit"], 4), p,
                      f"Limit for '{cfg['label']}': at most {p['limit']:.1%} of the portfolio. Its worst fall from the 12-month "
                      f"high was {p['worst_fall']:.0%} ({p['on']}, {p['history']}); {RISK_BUDGET:.0%} / {abs(p['worst_fall']):.0%} = "
                      f"{p['uncapped']:.1%}" + (", cut to the equity targets" if p["capped"] else "") + ". A description of history, "
                      "not a forecast." + (f" This revises the {old:.1%} you approved, because the history has moved it." if old is not None else ""),
                      now, revise=old is not None)
        n += got is not None
    return n


def breaches(con, ex_theme: dict) -> List[str]:
    out = []
    for theme, e in ex_theme.items():
        lim = applied(con, "theme_limit", theme)
        if lim is not None and e["weight"] > lim:
            out.append(f"Theme over its limit: {e['label']} is {e['weight']:.1%} of the portfolio, limit {lim:.1%}.")
    return out


def drift(con, root, asof: date, ex: Optional[dict] = None) -> List[str]:
    """Lines for baskets he approved: his holdings inside the basket against its weights, members 5+ points apart."""
    ex = ex or portfolio_exposures(con, asof)
    stock = ex["stock"].set_index("isin")["value"]
    names = dict(con.execute("SELECT isin, symbol FROM instruments").fetchall())
    out = []
    for theme in {t for (t,) in con.execute("SELECT DISTINCT theme FROM theme_baskets WHERE status='active'").fetchall()}:
        rows = con.execute("SELECT isin, weight FROM theme_baskets WHERE theme=? AND status='active' AND until IS NULL", [theme]).fetchall()
        held = {i: float(stock.get(i, 0.0)) for i, _w in rows}
        tot = sum(held.values())
        if tot <= 0:
            continue
        far = [(names.get(i, i), held[i] / tot - w) for i, w in rows if abs(held[i] / tot - w) > DRIFT_POINTS]
        if far:
            far.sort(key=lambda x: -abs(x[1]))
            out.append(f"Basket '{config()['theme'][theme]['label']}' drift from the approved weights: " +
                       ", ".join(f"{n} {d * 100:+.0f} pts" for n, d in far[:5]))
    return out


def over_limit(con, root, asof: date, isins: List[str], ex: Optional[dict] = None) -> Dict[str, str]:
    """{isin: reason} for the given ISINs that belong to a theme already at or over its applied limit (the advisor skips them)."""
    out: Dict[str, str] = {}
    exposure = exposure_of(con, root, asof, ex)
    for theme, e in exposure.items():
        lim = applied(con, "theme_limit", theme)
        if lim is None or e["weight"] < lim:
            continue
        for i in theme_members(con, root, theme, asof, isins):
            out[i] = f"theme '{e['label']}' at {e['weight']:.1%}, limit {lim:.1%}"
    return out
