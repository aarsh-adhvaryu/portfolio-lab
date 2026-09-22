"""Content-addressed run artifacts — Phase 2 task 2.3.

A run's identity is the hash of its config, its data and its code
(principle 9). Re-running with identical inputs verifies the existing
artifacts and refuses to overwrite; a changed input lands in a different
directory, so nothing is ever silently replaced.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_id(config_text: str, data_fingerprint: str, code_commit: str,
           period_name: str) -> str:
    """16 hex chars over the four things that can change a result."""
    return _sha("\n".join([config_text, data_fingerprint, code_commit,
                           period_name]))[:16]


def data_fingerprint(panel: pd.DataFrame, extra: Optional[dict] = None) -> str:
    """Identity of the data a run actually saw: a content hash of every row.

    It must be content, not shape, or two different datasets of the same shape
    would share a run id (principle 9). Seal identity (task 2.4b) still holds
    because the panel handed in here is already truncated -- rows after the
    period end were removed by truncate_end, so appending them upstream cannot
    reach this hash.
    """
    df = panel.sort_values(["isin", "date"]).reset_index(drop=True)
    row_hash = pd.util.hash_pandas_object(df, index=False).values
    digest = hashlib.sha256(row_hash.tobytes()).hexdigest()
    parts = {
        "rows": int(len(df)),
        "securities": int(df["isin"].nunique()),
        "first": str(pd.to_datetime(df["date"]).min().date()),
        "last": str(pd.to_datetime(df["date"]).max().date()),
        "columns": sorted(map(str, df.columns)),
        "content": digest,
    }
    if extra:
        parts.update(extra)
    return _sha(json.dumps(parts, sort_keys=True, default=str))


def source_fingerprint() -> str:
    """A content hash of the code the engine is actually running.

    `git rev-parse HEAD` pins the code only when the tree is clean. While it
    is dirty -- which is every session in progress -- two materially
    different versions of the engine share a commit hash, so a run id built
    on the commit alone cannot tell them apart. They then land in the same
    content-addressed directory, and principle 5's "identical inputs verify"
    becomes "different inputs overwrite". This closes that: the hash covers
    every source file a run's behaviour can depend on.
    """
    root = Path(__file__).resolve().parents[3]
    h = hashlib.sha256()
    for sub in ("src/pflab", "tools"):
        d = root / sub
        if not d.exists():
            continue
        for f in sorted(d.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            h.update(str(f.relative_to(root)).replace("\\", "/").encode("utf-8"))
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def code_commit() -> dict:
    try:
        h = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                    stderr=subprocess.DEVNULL).decode().strip()
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain"], stderr=subprocess.DEVNULL).decode().strip())
    except Exception:
        h, dirty = "unknown", True
    return {"commit": h, "dirty": dirty, "source_sha": source_fingerprint()}


def code_identity(commit: dict) -> str:
    """What `run_id` should hash for "the code". A clean tree is pinned by
    its commit; a dirty one needs the source hash as well, or two different
    working trees produce the same run id."""
    if not commit.get("dirty"):
        return commit.get("commit", "unknown")
    return f"{commit.get('commit', 'unknown')}+{commit.get('source_sha', '?')}"


class ArtifactConflict(RuntimeError):
    pass


def write_run(run_dir, result, manifest: dict, benchmarks: Optional[dict] = None,
              overwrite: bool = False) -> Path:
    """Write the run. If the directory already holds a manifest, verify it
    matches and leave the artifacts alone (principle 9)."""
    run_dir = Path(run_dir)
    mpath = run_dir / "manifest.json"
    if mpath.exists() and not overwrite:
        old = json.loads(mpath.read_text(encoding="utf-8"))
        if old.get("run_id") != manifest.get("run_id"):
            raise ArtifactConflict(
                f"{run_dir} holds run {old.get('run_id')}, not {manifest.get('run_id')}")
        return run_dir      # identical inputs: verified, not rewritten

    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = dict(manifest)
    manifest["warnings"] = _warning_summary(result.warnings)
    manifest["hooks_active"] = result.hooks_active
    manifest["adv_skips"] = adv_skip_report(result)
    manifest["extras"] = extras_report(result)
    mpath.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    (run_dir / "metrics.json").write_text(
        json.dumps(metrics_of(result, benchmarks), indent=2, default=str),
        encoding="utf-8")
    (run_dir / "decisions.json").write_text(
        json.dumps(result.decisions, indent=2, default=str), encoding="utf-8")
    result.equity.to_csv(run_dir / "equity.csv", index=False)
    getattr(result, "adv_skips", pd.DataFrame()).to_csv(
        run_dir / "adv_skips.csv", index=False)
    (run_dir / "adv_skip_report.json").write_text(
        json.dumps(adv_skip_report(result), indent=2, default=str), encoding="utf-8")
    (run_dir / "extras.json").write_text(
        json.dumps(extras_report(result), indent=2, default=str), encoding="utf-8")
    result.trades.to_csv(run_dir / "trades.csv", index=False)
    result.taxes.to_csv(run_dir / "taxes.csv", index=False)
    with open(run_dir / "provenance.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                            **code_commit(), "python": platform.python_version()}) + "\n")
    return run_dir


def adv_skip_report(result) -> dict:
    """§7 as amended 2026-09-17: skips are recorded, not silent.

    Reports the per-year count, the share of attempted buys that were skipped,
    and any month where EVERY planned buy was skipped -- that last one matters
    because it means the SIP went to cash for a liquidity reason, not because
    the strategy chose to hold cash.
    """
    skips = getattr(result, "adv_skips", None)
    executed = 0
    if len(result.trades):
        executed = int((result.trades["side"] == "BUY").sum())
    if skips is None or len(skips) == 0:
        return {"skips": 0, "attempted_buys": executed, "share_skipped": 0.0,
                "by_year": {}, "months_fully_skipped": [], "worst": []}
    s = skips.copy()
    s["date"] = pd.to_datetime(s["date"])
    attempted = executed + len(s)
    by_year = {int(y): int(n) for y, n in s.groupby(s["date"].dt.year).size().items()}

    # a month is "fully skipped" when the number of skips equals the number of
    # buys the engine planned that session and none was executed
    fully = []
    for d, g in s.groupby(s["date"]):
        planned = int(g["planned"].max())
        done = 0
        if len(result.trades):
            done = int(((result.trades["side"] == "BUY") &
                        (pd.to_datetime(result.trades["date"]) == d)).sum())
        if done == 0 and len(g) >= planned > 0:
            fully.append({"date": str(d.date()), "planned": planned,
                          "skipped": int(len(g))})
    worst = (s.nlargest(10, "ratio")[["date", "isin", "buy_value", "adv", "ratio"]]
              .assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d"))
              .to_dict("records"))
    return {"skips": int(len(s)), "attempted_buys": attempted,
            "share_skipped": round(len(s) / attempted, 4) if attempted else 0.0,
            "by_year": by_year, "months_fully_skipped": fully, "worst": worst}


def extras_report(result, config=None, membership=None,
                  overlap_index="NIFTY200_MOMENTUM30") -> dict:
    """The four extras requested in docs/reviews/E1-development.md.

    Reporting only: every number here is read off a completed run. No decision
    is recomputed and nothing feeds back into the strategy.
    """
    from pflab.eval import metrics as M
    eq = result.equity

    def _cagr(col):
        if col not in eq.columns:
            return None
        nav = pd.Series(eq[col].values, index=pd.to_datetime(eq["date"])).dropna()
        return M.cagr(nav) if len(nav) > 1 else None

    # 1 -- pre-tax CAGR and tax paid -------------------------------------
    pre, post = _cagr("nav_liq_pre"), _cagr("nav_liq")
    running = float(eq["tax_paid_cum"].iloc[-1]) if "tax_paid_cum" in eq else 0.0
    liq = float(eq["liquidation_tax"].iloc[-1]) if "liquidation_tax" in eq else 0.0
    tax = {
        "cagr_pre_tax_liq": pre,
        "cagr_after_tax_liq": post,
        "tax_drag_pp": (100 * (pre - post)) if (pre is not None and post is not None) else None,
        "tax_paid_running": running,
        "tax_paid_liquidation": liq,
        "tax_paid_total": running + liq,
        "short_term_share_of_realised_gains_pct": _short_term_share(result),
    }

    # 2 -- suspended / delisted holdings ---------------------------------
    tr = result.trades
    exits = tr[tr["side"] == "SELL_DELIST"] if len(tr) else tr
    wo = [w for w in (result.warnings or ()) if w.get("kind") == "write_off"]
    names = set(exits["isin"]) | {w["isin"] for w in wo}
    keys = {(r.isin, pd.Timestamp(r.date).date()) for r in exits.itertuples(index=False)}
    keys |= {(w["isin"], w["date"]) for w in wo}
    gain = sum(r.gain for r in (result.realised or ()) if (r.isin, r.sell_date) in keys)
    invested = float(eq["flow"].sum()) if len(eq) else 0.0
    final = float((eq["equity_value"] + eq["cash"]).iloc[-1]) if len(eq) else 0.0
    delisting = {
        "names": len(names),
        "exits_at_last_close": int(len(exits)),
        "written_off": len(wo),
        "realised_pnl": float(gain),
        "pnl_pct_of_contributions": (100 * gain / invested) if invested else None,
        "pnl_pct_of_final_value": (100 * gain / final) if final else None,
    }

    # 3 -- RISK_OFF months and cash share by year ------------------------
    e = eq.copy()
    e["date"] = pd.to_datetime(e["date"])
    e["year"] = e["date"].dt.year
    e["total"] = e["equity_value"] + e["cash"]
    e["cash_share"] = (e["cash"] / e["total"]).where(e["total"] > 0)
    has_ro = "risk_off" in e.columns
    by_year = {}
    for y, g in e.groupby("year"):
        # Years before the period start carry no capital, so the share is
        # undefined there; reporting NaN as 0% would understate the cash held.
        share = g["cash_share"].dropna()
        if share.empty:
            continue
        ro = int(g.loc[g["risk_off"], "date"].dt.to_period("M").nunique()) if has_ro else 0
        by_year[int(y)] = {
            "risk_off_months": ro,
            "mean_cash_share_pct": round(100 * float(share.mean()), 2),
            "max_cash_share_pct": round(100 * float(share.max()), 2),
        }
    regime = {
        "risk_off_months_total": (int(e.loc[e["risk_off"], "date"].dt.to_period("M").nunique())
                                  if has_ro else 0),
        "months_total": int(e["date"].dt.to_period("M").nunique()),
        "mean_cash_share_pct": round(100 * float(e["cash_share"].dropna().mean()), 2),
        "by_year": by_year,
    }

    return {
        "tax": tax,
        "delisting": delisting,
        "regime": regime,
        "equity_sleeve": equity_sleeve_return(result),
        "most_traded": most_traded(result),
        "holdings_turnover_rank": _turnover_rank_by_year(result),
        "index_overlap": _index_overlap_by_year(result, membership, overlap_index),
        "market_cap_proxy": ("unavailable: charter section 2 ranks by traded value "
                             "precisely to avoid needing point-in-time shares "
                             "outstanding, which the panel does not carry"),
    }


def equity_sleeve_return(result) -> dict:
    """What the INVESTED rupee earned, with the cash sleeve taken out.

    Requested in docs/reviews/E1b-development.md. The base row held a mean
    22.4% in cash at 6% while the momentum index compounded at 13.5%, so the
    headline CAGR mixes two different things: what the signal picked and what
    the seat belt cost. This separates them.

    The equity sleeve is unitised on its own:

      value  = equity_value + cumulative dividends received
               (a dividend is a return ON the holding that leaves
               `equity_value` for cash on the ex-date, so adding it back is
               what makes this a total return rather than a price return)
      flow   = cash actually moved across the boundary by trading --
               a buy at its FULL outlay including costs, a sell at its NET
               proceeds after costs, a §9 cash credit as a withdrawal

    Charging the sleeve its own transaction costs is deliberate: the question
    is what the invested rupee earned net of the cost of investing it, not
    what a frictionless version of it would have earned.

    This is reporting only. It changes no decision and is not a criterion.
    """
    from pflab.eval import metrics as M
    eq = result.equity
    if not len(eq):
        return {"available": False, "reason": "no equity curve"}

    idx = pd.to_datetime(eq["date"])
    value = pd.Series(eq["equity_value"].astype(float).values, index=idx)
    if "dividends" in eq.columns:
        value = value + pd.Series(eq["dividends"].astype(float).values,
                                  index=idx).cumsum()
        div_total = float(eq["dividends"].sum())
    else:
        div_total = None        # older run: price return only, say so

    tr = result.trades
    flows = pd.Series(0.0, index=idx)
    if len(tr):
        t = tr.copy()
        t["date"] = pd.to_datetime(t["date"])
        t["qty"] = t["qty"].astype(float)
        t["fill_price"] = t["fill_price"].astype(float)
        t["costs"] = t["costs"].fillna(0.0).astype(float)
        notional = t["qty"] * t["fill_price"]
        signed = pd.Series(0.0, index=t.index)
        buys = t["side"] == "BUY"
        sells = t["side"].str.startswith("SELL")
        credits = t["side"] == "CASH_CREDIT"
        signed[buys] = notional[buys] + t["costs"][buys]
        signed[sells] = -(notional[sells] - t["costs"][sells])
        signed[credits] = -notional[credits]
        byday = signed.groupby(t["date"]).sum()
        flows = flows.add(byday.reindex(idx).fillna(0.0), fill_value=0.0)

    # Two readings, and the first is the one to quote.
    #
    # CONTRIBUTION (capital-weighted). Each day's equity P&L is expressed as a
    # share of the whole portfolio and chained. Equity and cash contributions
    # then ADD UP to the portfolio's own return, which is what "separate cash
    # carry from signal" actually asks for.
    #
    # SLEEVE (time-weighted) is reported too, and is NOT the headline. A
    # time-weighted return gives every day equal weight regardless of how much
    # capital is at risk, and §6 spends long stretches almost entirely in cash
    # -- 162 sessions below 25% equity weight on E1b's base row, 115 below
    # 10%. On 2009-02-02 the leftover stub fell 21% on a base of Rs 4,239 and
    # that day counts as much as a fully invested one. It answers "what would
    # you earn holding whatever stub the strategy happened to keep", which is
    # not the question.
    flows = flows.reindex(value.index).fillna(0.0)
    alive = value.ne(0) | flows.ne(0)
    if not alive.any():
        return {"available": False, "reason": "the sleeve never held capital"}
    start = alive.idxmax()
    value, flows = value.loc[start:], flows.loc[start:]

    eqdf = result.equity
    eidx = pd.to_datetime(eqdf["date"])
    cash = pd.Series(eqdf["cash"].astype(float).values, index=eidx).loc[value.index]
    sip = pd.Series(eqdf["flow"].astype(float).values, index=eidx).loc[value.index]

    v, f = value.values, flows.values
    c, sp = cash.values, sip.values
    total = v + c
    n = len(v)
    if n < 2:
        return {"available": False, "reason": "fewer than two sessions"}

    r_eq = np.zeros(n)
    r_cash = np.zeros(n)
    r_tw = np.zeros(n)
    invested = np.zeros(n, dtype=bool)
    for i in range(1, n):
        denom = total[i - 1] + sp[i]
        if denom > 1e-9:
            r_eq[i] = (v[i] - (v[i - 1] + f[i])) / denom
            r_cash[i] = (c[i] - (c[i - 1] + sp[i] - f[i])) / denom
        base = v[i - 1] + f[i]
        if base > 1e-9:
            r_tw[i] = v[i] / base - 1.0
            invested[i] = True

    years = (value.index[-1] - value.index[0]).days / 365.25
    if years <= 0:
        return {"available": False, "reason": "zero-length window"}

    def _ann(series):
        g = float(np.prod(1.0 + series))
        return (g ** (1 / years) - 1) if g > 0 else None

    eq_c, cash_c = _ann(r_eq), _ann(r_cash)
    tw = _ann(r_tw)
    total_pre = _cagr_of(result, "nav_liq_pre") or _cagr_of(result, "nav_liq")

    return {
        "available": True,
        # headline: the decomposition, which adds up
        "contribution_equity_pp": (100 * eq_c) if eq_c is not None else None,
        "contribution_cash_pp": (100 * cash_c) if cash_c is not None else None,
        "contribution_sum_pp": ((100 * (eq_c + cash_c))
                                if None not in (eq_c, cash_c) else None),
        "cagr_pre_tax_for_reconciliation": total_pre,
        "mean_equity_weight": float(np.nanmean(np.divide(
            v, total, out=np.zeros_like(v), where=total > 0))),
        # secondary, and explicitly not the headline
        "time_weighted_sleeve_cagr": tw,
        "time_weighted_caveat": (
            "equal weight per day regardless of capital at risk; distorted "
            "whenever the strategy is mostly in cash"),
        "sessions_below_25pct_equity": int((np.divide(
            v, total, out=np.zeros_like(v), where=total > 0) < 0.25).sum()),
        "share_of_days_invested": round(float(invested.mean()), 4),
        "dividends_received": div_total,
        "basis": ("equity contribution and cash contribution are each day's "
                  "P&L over the whole portfolio, chained, so they add to the "
                  "portfolio's pre-tax return. Dividends are added back to "
                  "equity; transaction costs are charged to it."),
    }


def most_traded(result, n: int = 10) -> list:
    """The names a row put the most money through. Reporting only.

    Asked for as a data check on E1b's S10, where a 3.91% CAGR on the Nifty
    500 membership universe is not credible without seeing what it bought.
    """
    tr = result.trades
    if not len(tr):
        return []
    t = tr.copy()
    t["notional"] = t["qty"].astype(float) * t["fill_price"].astype(float)
    g = t.groupby("isin").agg(trades=("side", "size"),
                              notional=("notional", "sum"),
                              buys=("side", lambda x: int((x == "BUY").sum())))
    g = g.sort_values("notional", ascending=False).head(n)
    return [{"isin": i, "trades": int(r.trades), "buys": int(r.buys),
             "notional": float(r.notional)} for i, r in g.iterrows()]


def _cagr_of(result, col):
    from pflab.eval import metrics as M
    eq = result.equity
    if col not in eq.columns:
        return None
    nav = pd.Series(eq[col].values, index=pd.to_datetime(eq["date"])).dropna()
    return M.cagr(nav) if len(nav) > 1 else None


def _short_term_share(result):
    """Share of realised GAINS taxed at the short-term rate (section 8)."""
    gains = [r for r in (result.realised or ()) if r.gain > 0]
    total = sum(r.gain for r in gains)
    if not total:
        return None
    st = sum(r.gain for r in gains if not r.long_term)
    return round(100 * st / total, 2)


def _turnover_rank_by_year(result):
    """Median rank, by trailing traded value, of the names held at each
    month-end. Rank 1 is the most traded name in the eligible universe, so a
    rising median means the portfolio drifted into thinner names."""
    pre = getattr(result, "universe_pre", None)
    if not pre or not result.decisions:
        return {}
    turn = pre["turnover"]
    rows = []
    for d in result.decisions:
        m, held = d["month_end"], d.get("held") or []
        if not held or m not in turn.index:
            continue
        ranks = turn.loc[m].dropna().rank(ascending=False, method="first")
        vals = [float(ranks[h]) for h in held if h in ranks.index]
        if vals:
            rows.append({"year": m.year, "median_rank": float(pd.Series(vals).median()),
                         "n_held": len(vals)})
    if not rows:
        return {}
    df = pd.DataFrame(rows)
    return {int(y): {"median_turnover_rank": round(float(g["median_rank"].median()), 1),
                     "mean_names_held": round(float(g["n_held"].mean()), 1)}
            for y, g in df.groupby("year")}


def _index_overlap_by_year(result, membership, index):
    """E1b §8: share of month-end holdings that were constituents of `index`.

    Reporting only. Returns a sentence, not a number, when no point-in-time
    table for the index is available -- overlap measured against TODAY's
    constituent list would be a survivorship artefact (principle 6) and would
    read as a real number in the summary, which is worse than a blank.
    """
    if membership is None or len(membership) == 0:
        return (f"unavailable: no point-in-time constituent table for {index}. "
                f"Measuring overlap against today's list would be a "
                f"survivorship artefact, so no number is reported.")
    from pflab.data import index_membership as im
    rows = []
    for d in (result.decisions or ()):
        m, held = d["month_end"], d.get("held") or []
        if not held:
            continue
        members = im.members_at(membership, index, m)
        rows.append({"year": m.year, "n_held": len(held),
                     "n_in": sum(1 for h in held if h in members)})
    if not rows:
        return {}
    df = pd.DataFrame(rows)
    by_year = {}
    for y, g in df.groupby("year"):
        held, inside = float(g["n_held"].sum()), float(g["n_in"].sum())
        by_year[int(y)] = {"overlap_pct": round(100 * inside / held, 1) if held else None,
                           "mean_names_held": round(float(g["n_held"].mean()), 1),
                           "mean_in_index": round(float(g["n_in"].mean()), 1)}
    total_held, total_in = float(df["n_held"].sum()), float(df["n_in"].sum())
    return {"index": index,
            "overall_pct": round(100 * total_in / total_held, 1) if total_held else None,
            "by_year": by_year}


def _warning_summary(warnings) -> dict:
    out: dict = {}
    for w in warnings or ():
        out[w.get("kind", "?")] = out.get(w.get("kind", "?"), 0) + 1
    return out


def metrics_of(result, benchmarks: Optional[dict] = None) -> dict:
    """CAGR / MaxDD / Sharpe / turnover / cost and tax drag for the three NAV
    paths, plus each benchmark on the same basis."""
    from pflab.eval import metrics as M
    eq = result.equity
    out = {"paths": {}}
    for path in ("nav_pre", "nav_post", "nav_liq"):
        if path not in eq.columns:
            continue
        nav = pd.Series(eq[path].values, index=pd.to_datetime(eq["date"])).dropna()
        if nav.empty:
            continue
        out["paths"][path] = {"cagr": M.cagr(nav), "max_drawdown": M.max_drawdown(nav),
                              "sharpe": M.sharpe(nav)}
    tr = result.trades
    buys = tr[tr["side"] == "BUY"] if len(tr) else tr
    sells = tr[tr["side"].str.startswith("SELL")] if len(tr) else tr
    total_costs = float(tr["costs"].sum()) if len(tr) else 0.0
    invested = float(eq["flow"].sum()) if len(eq) else 0.0
    out["trades"] = {"n": int(len(tr)), "buys": int(len(buys)), "sells": int(len(sells)),
                     "costs": total_costs,
                     "cost_drag_pct_of_flow": (100 * total_costs / invested) if invested else 0.0}
    tax_total = float(result.taxes["tax"].sum()) if len(result.taxes) else 0.0
    liq = float(eq["liquidation_tax"].iloc[-1]) if "liquidation_tax" in eq.columns and len(eq) else 0.0
    out["tax"] = {"paid": tax_total, "liquidation": liq,
                  "tax_drag_pct_of_flow": (100 * (tax_total + liq) / invested) if invested else 0.0}
    sell_notional = float((sells["qty"] * sells["fill_price"]).sum()) if len(sells) else 0.0
    avg_equity = float(eq["equity_value"].mean()) if len(eq) else 0.0
    years = max((pd.to_datetime(eq["date"]).max() - pd.to_datetime(eq["date"]).min()).days / 365.25, 1e-9)
    out["turnover_annual"] = (sell_notional / avg_equity / years) if avg_equity else 0.0
    if benchmarks:
        out["benchmarks"] = {}
        for name, res in benchmarks.items():
            beq = res.equity
            nav = pd.Series(beq["nav_liq"].values, index=pd.to_datetime(beq["date"])).dropna()
            if nav.empty:
                continue
            out["benchmarks"][name] = {"cagr": M.cagr(nav),
                                       "max_drawdown": M.max_drawdown(nav)}
    return out


# -- E1-P §7 ------------------------------------------------------------
def _forward_returns(close_w, when, isins, sessions_ahead):
    """Forward return of each name from `when`, over `sessions_ahead`.

    A name that stops trading inside the window is DROPPED, never imputed:
    its last price is not a price it could have been sold at.
    """
    out = []
    if close_w is None or when not in close_w.index:
        return out
    i = close_w.index.get_loc(when)
    j = min(i + sessions_ahead, len(close_w.index) - 1)
    if j <= i:
        return out
    for isin in isins:
        if isin not in close_w.columns:
            continue
        a = close_w.iat[i, close_w.columns.get_loc(isin)]
        b = close_w.iat[j, close_w.columns.get_loc(isin)]
        if pd.isna(a) or pd.isna(b) or a <= 0:
            continue
        out.append(float(b / a - 1.0))
    return out


def deferred_lot_outcomes(result, close_w=None, months: int = 3) -> dict:
    """E1-P §7: "the forward 3-month return of deferred lots vs the lots E1
    would have sold".

    The comparator is the names the SAME month-end band-exited, because a
    deferred name is exactly a name E1 would have band-exited. If patience is
    free the two are alike and the tax saving is the whole gain; if the
    deferred names fall further, the saving was paid for out of return.

    Reporting only. Read off a completed run; no decision is recomputed.
    """
    decisions = result.decisions or []
    if not decisions:
        return {"available": False, "reason": "no decisions"}
    n_def = sum(len(d.get("deferred") or []) for d in decisions)
    if not n_def:
        return {"available": True, "deferrals": 0,
                "note": "nothing was deferred (E1 base, or the rule never fired)"}
    if close_w is None:
        return {"available": False,
                "reason": "needs the close panel to measure forward returns"}

    sessions_ahead = int(round(months * 21))
    deferred, sold, by_month = [], [], []
    for d in decisions:
        m = d["month_end"]
        dl = _forward_returns(close_w, m, d.get("deferred") or [], sessions_ahead)
        sl = _forward_returns(close_w, m,
                              [e["isin"] for e in (d.get("exits") or [])
                               if e.get("reason") == "band"], sessions_ahead)
        deferred += dl
        sold += sl
        if dl or sl:
            by_month.append({
                "month_end": str(m), "deferred": len(dl), "band_sold": len(sl),
                "deferred_fwd_pct": (100 * float(np.mean(dl))) if dl else None,
                "band_sold_fwd_pct": (100 * float(np.mean(sl))) if sl else None})

    return {
        "available": True,
        "months": months,
        "deferrals": n_def,
        "month_ends_with_a_deferral": sum(1 for d in decisions if d.get("deferred")),
        "deferred_forward_mean_pct": (100 * float(np.mean(deferred))) if deferred else None,
        "deferred_forward_median_pct": (100 * float(np.median(deferred))) if deferred else None,
        "band_sold_forward_mean_pct": (100 * float(np.mean(sold))) if sold else None,
        "band_sold_forward_median_pct": (100 * float(np.median(sold))) if sold else None,
        "gap_pp": ((100 * (float(np.mean(deferred)) - float(np.mean(sold))))
                   if deferred and sold else None),
        "measured_on": {"deferred": len(deferred), "band_sold": len(sold)},
        "by_month": by_month,
        "basis": (f"forward return from the month-end close over "
                  f"{sessions_ahead} sessions (~{months} months). A NEGATIVE "
                  f"gap_pp means the deferred names did worse than the ones "
                  f"sold, i.e. the tax saving was paid for out of return."),
    }


def control_sell_outcomes(result, close_w=None, months: int = 6) -> dict:
    """E1-P §7 for N1/N2: how many sells the control fired and what those
    names did over the following six months.

    A stop-loss that fires on names which then recover has cost money; one
    that fires on names which keep falling has saved it. This says which. It
    does not say whether the control is adoptable -- §4 says it is not.
    """
    tr = result.trades
    if tr is None or not len(tr):
        return {"available": True, "sells": 0}
    sells = tr[tr["side"] == "SELL_INTRA"]
    if not len(sells):
        return {"available": True, "sells": 0,
                "note": "no intra-month exits (E1 base, or no control ran)"}
    if close_w is None:
        return {"available": False,
                "reason": "needs the close panel to measure forward returns"}

    sessions_ahead = int(round(months * 21))
    fwd = []
    for r in sells.itertuples(index=False):
        d = r.date.date() if hasattr(r.date, "date") else r.date
        fwd += _forward_returns(close_w, d, [r.isin], sessions_ahead)

    s = sells.copy()
    s["date"] = pd.to_datetime(s["date"])
    return {
        "available": True,
        "sells": int(len(sells)),
        "names": int(sells["isin"].nunique()),
        "by_year": {int(y): int(n) for y, n in s.groupby(s["date"].dt.year).size().items()},
        "months": months,
        "forward_mean_pct": (100 * float(np.mean(fwd))) if fwd else None,
        "forward_median_pct": (100 * float(np.median(fwd))) if fwd else None,
        "measured_on": len(fwd),
        "basis": (f"forward return from the sell fill over {sessions_ahead} "
                  f"sessions (~{months} months). A POSITIVE mean means the "
                  f"control sold names that then ROSE -- impatience cost "
                  f"return, which is what §4 exists to measure."),
    }
