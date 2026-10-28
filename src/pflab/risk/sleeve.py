"""The US sleeve decision (S64 Phase 6 item 6): what putting 0, 10, 15 or 20% of the portfolio in US shares would have done, in rupees.

The sleeve is the S&P 500 total return (SPY, dividends in) times the rupee price of the dollar (FRED's noon New York USDINR),
so the rupee's own moves are inside. It joins the simulator's assets (Nifty 500 and Momentum 50 funds, his stocks, gold, debt,
cash) on the dates every series exists, and the same circular block bootstrap as `risk/montecarlo` draws five-year paths: the
stock market, the dollar and the rest move together in the draws as they did. For each share it reports the rupee growth, the
spread, the worst fall in any session of the history, the chance of a fall beyond the investor's 35% limit, and what it costs to
set up (TCS above Rs 10 lakh, brokerage, the bank's currency markup).

WHAT IT CANNOT SAY. History is about twenty years: one US boom and one rupee that kept falling against the dollar (about 3% a
year) are in it; neither is a promise. The base mix is the investor's TARGET mix. The result goes to Needs from you as a table
and a proposal; the share is his yes, and `targets.toml` is his to edit (the system never changes a target).
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from pflab.risk import montecarlo as mc

SHARES = (0.0, 0.10, 0.15, 0.20)
ASSETS = mc.ASSETS + ("us",)
BROKERAGE = 0.0010                      # per side, Zerodha GIFT City guide (configs/tax/foreign.toml: gift_city_charges)
MARKUP = (0.004, 0.014)                 # bank currency conversion above the RBI reference rate, same row
CAVEAT = ("about twenty years of history, one US boom and a rupee that fell against the dollar throughout; none is a promise. "
          "The S&P 500 total return is SPY (its small fund fee is inside).")


def us_levels(root: Path) -> Dict[str, pd.Series]:
    """Daily levels: the S&P 500 total return in dollars (SPY adjusted close), the dollar's price in rupees, and their product."""
    from pflab.data import macro
    spy = pd.read_parquet(Path(root) / "us" / "raw" / "SPY.parquet")
    usd = pd.Series(spy["adj_close"].to_numpy(float), index=pd.to_datetime(spy["date"])).sort_index()
    fx = macro.load("USDINR", root)
    fx = pd.Series(fx["value"].to_numpy(float), index=pd.to_datetime(fx["date"])).dropna().sort_index()
    both = pd.concat([usd.rename("usd"), fx.rename("fx")], axis=1).sort_index().ffill().dropna()
    both["inr"] = both["usd"] * both["fx"]
    return {"usd": both["usd"], "fx": both["fx"], "inr": both["inr"]}


def joint(root: Path):
    """(monthly, daily) simple returns for the simulator's assets plus `us`, on the dates every series exists."""
    lv = us_levels(root)
    R, Rd = mc.history(root), mc.history_daily(root)
    m = lv["inr"].resample("ME").last().pct_change()
    R = R.assign(us=m.reindex(R.index)).dropna()
    d = lv["inr"].reindex(Rd.index, method="ffill").pct_change()
    Rd = Rd.assign(us=d).dropna()
    return R[list(ASSETS)], Rd[list(ASSETS)], lv


def base_mix(con, asof: date) -> Dict[str, float]:
    """His target mix over the simulator's assets (stocks as `stocks`), else today's holdings."""
    from pflab.app import sims
    m = sims.target_mix(con)
    src = "target"
    if m is None:
        m, src = sims.current_mix(con, asof), "current"
    out = {a: 0.0 for a in mc.ASSETS}
    out["stocks"] = m.get("stocks", 0.0) + m.get("mine", 0.0)
    for a in ("n500", "mom50", "gold", "debt", "cash"):
        out[a] = m.get(a, 0.0)
    s = sum(out.values())
    out = {a: v / s for a, v in out.items()}
    out["_source"] = src            # type: ignore[assignment]
    return out


def weights(base: Dict[str, float], share: float) -> np.ndarray:
    w = np.array([base[a] * (1 - share) for a in mc.ASSETS] + [share])
    assert abs(w.sum() - 1) < 1e-9
    return w


def setup_cost(amount_inr: float, remitted_before: float = 0.0) -> dict:
    """What it costs to put `amount_inr` into the sleeve: TCS (a credit, a cash cost until he files), brokerage on the buy, the
    bank's currency markup (a range). ESTIMATES from configs/tax/foreign.toml and Zerodha's guide."""
    from pflab.tax import foreign as tf
    t = tf.tcs(remitted_before, amount_inr)
    th = t["threshold_rs"]
    two = tf.tcs(0.0, amount_inr / 2)["tcs_rs"] * 2                 # half in each of two financial years: each has its own threshold
    return {"amount_inr": round(amount_inr), "tcs_inr": t["tcs_rs"], "tcs_if_split_over_two_financial_years_inr": round(two, 2),
            "tcs_note": f"TCS counts per financial year above Rs {th:,.0f}; a credit against his tax when he files",
            "brokerage_inr": round(amount_inr * BROKERAGE), "currency_markup_inr": [round(amount_inr * MARKUP[0]), round(amount_inr * MARKUP[1])],
            "label": t["label"] + "; brokerage and markup: gift_city_charges (Zerodha)"}


def study(root: Path, base: Dict[str, float], shares: Sequence[float] = SHARES, years: int = 5, n: int = 10_000,
          seed: int = 20261027, investable: Optional[float] = None, R: Optional[pd.DataFrame] = None,
          Rd: Optional[pd.DataFrame] = None) -> dict:
    if R is None or Rd is None:
        R, Rd, _lv = joint(root)
    months = 12 * years
    rng = np.random.default_rng(seed)
    X, Xd = R.values, Rd.values
    paths = mc.block_paths(X, months, n, rng)
    rows = []
    for s in shares:
        w = weights(base, s)
        v = mc.mix_values(paths, w)
        port = X @ w
        dv = np.concatenate([[1.0], np.cumprod(1 + Xd @ w)])
        r = mc.summary(v, months)
        row = {"share": s, "median_cagr": round(r["median_cagr"], 4), "p5_end": round(r[f"y{years}"]["p5"], 3), "p50_end": round(r[f"y{years}"]["p50"], 3),
               "p95_end": round(r[f"y{years}"]["p95"], 3), "p_loss_at_end": round(r["p_loss_at_end"], 3),
               "p_fall_beyond_35pct_any_day": round(mc.fall_any_day_block(Xd, w, months, n, np.random.default_rng(seed + 1)), 4),
               "history_return_a_year": round(float(np.prod(1 + port) ** (12 / len(port)) - 1), 4),
               "history_vol_a_year": round(float(port.std(ddof=1) * np.sqrt(12)), 4),
               "history_worst_fall_any_day": round(float((dv / np.maximum.accumulate(dv) - 1).min()), 4)}
        if investable:
            row["amount_inr"] = round(investable * s)
            row["setup"] = setup_cost(investable * s)
        rows.append(row)
    us = X[:, -1]
    n500 = X[:, mc.ASSETS.index("n500")]
    out = {"asof_history": f"{R.index[0]:%Y-%m} to {R.index[-1]:%Y-%m} ({len(R)} months)", "base_mix_source": base.get("_source"),
           "base_mix": {a: round(base[a], 3) for a in mc.ASSETS}, "rows": rows, "years": years, "paths": n,
           "us_alone": {"rupee_return_a_year": round(float(np.prod(1 + us) ** (12 / len(us)) - 1), 4),
                        "nifty500_return_a_year": round(float(np.prod(1 + n500) ** (12 / len(n500)) - 1), 4),
                        "correlation_with_nifty500": round(float(np.corrcoef(us, n500)[0, 1]), 3),
                        "monthly_vol_a_year": round(float(us.std(ddof=1) * np.sqrt(12)), 4)},
           "caveat": CAVEAT}
    return out


def fx_split(root: Path) -> dict:
    """How much of the US sleeve's rupee growth was the stock market and how much the rupee, over the same history."""
    lv = us_levels(root)
    yrs = (lv["inr"].index[-1] - lv["inr"].index[0]).days / 365.25
    cagr = lambda s: float((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1)         # noqa: E731
    return {"years": round(yrs, 1), "in_dollars": round(cagr(lv["usd"]), 4), "dollar_in_rupees": round(cagr(lv["fx"]), 4), "in_rupees": round(cagr(lv["inr"]), 4)}


def propose(con, root: Path, asof: date, now, investable: float, years: int = 5, n: int = 10_000) -> Optional[int]:
    """Run the study and put it to Needs from you. The yes records a share; targets.toml stays his to edit."""
    from pflab.risk import themes
    res = study(root, base_mix(con, asof), years=years, n=n, investable=investable)
    res["fx_split"] = fx_split(root)
    lines = ["US sleeve (S&P 500 in rupees) as a share of the whole portfolio, over " + res["asof_history"] + ":"]
    for r in res["rows"]:
        lines.append(f"  {r['share']:.0%}: median growth {r['median_cagr']:.1%} a year, {res['years']}-year p5 {r['p5_end']:.2f}x p95 {r['p95_end']:.2f}x, "
                     f"chance of a 35% fall {r['p_fall_beyond_35pct_any_day']:.1%}, worst fall in the history {r['history_worst_fall_any_day']:.0%}"
                     + (f"; TCS Rs {r['setup']['tcs_inr']:,.0f} in one year, Rs {r['setup']['tcs_if_split_over_two_financial_years_inr']:,.0f} "
                        "if funded over two financial years" if r.get("setup") else ""))
    lines.append(f"The US alone: {res['us_alone']['rupee_return_a_year']:.1%} a year in rupees against {res['us_alone']['nifty500_return_a_year']:.1%} "
                 f"for the Nifty 500; correlation {res['us_alone']['correlation_with_nifty500']}. {CAVEAT} Which share, if any, and from "
                 "which month: 'yes 10 from February 2027' (the month is optional). I then show how to spread the money over financial "
                 "years to keep TCS low; you add [bucket.intl_equity] to targets.toml yourself.")
    return themes.propose(con, "us_sleeve", "share", None, res, "\n".join(lines), now)


# --- his answer: a share and a start month; then the funding split --------------------------------------------------------

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
_MONTH_RE = re.compile(r"\b(" + "|".join(m + "|" + m[:3] for m in _MONTHS) + r")\b\.?(?:\s+(20\d\d))?")
_ISO_RE = re.compile(r"\b(20\d\d)-(0[1-9]|1[0-2])\b")
MAX_SHARE = 0.5                          # a share above half the portfolio is read as a mistake, not an instruction


def parse_answer(text: Optional[str], today: date) -> tuple:
    """(share as a fraction or None, first day of the start month or None) from 'yes 10', '10% from feb 2027', 'yes 12 2027-03'.
    A number is a percent. Without a year the next such month is meant."""
    t = (text or "").lower()
    start = None
    m = _ISO_RE.search(t)
    if m:
        start, t = date(int(m[1]), int(m[2]), 1), t[:m.start()] + " " + t[m.end():]
    else:
        m = _MONTH_RE.search(t)
        if m:
            mon = next(i for i, name in enumerate(_MONTHS, 1) if m[1] in (name, name[:3]))
            year = int(m[2]) if m[2] else (today.year if mon >= today.month else today.year + 1)
            start, t = date(year, mon, 1), t[:m.start()] + " " + t[m.end():]
    n = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)", re.sub(r"\b20\d\d\b", " ", t))
    share = float(n[1]) / 100 if n else None
    return (share if share is not None and 0 < share <= MAX_SHARE else None), start


def funding_plan(amount_inr: float, start: date, remitted_before_inr: float = 0.0, max_years: int = 6) -> dict:
    """Spread `amount_inr` over financial years so that no year's remittances pass the TCS threshold, starting with what is left
    of the start year's room. ESTIMATE from configs/tax/foreign.toml; TCS is a credit when he files, so a lump costs cash for a
    while, not a loss."""
    from pflab.ledger import foreign as lf
    from pflab.tax import foreign as tf
    th = tf.tcs(0.0, 0.0)["threshold_rs"]
    fy, left, rows, room = lf.fy_of(start), float(amount_inr), [], max(0.0, th - remitted_before_inr)
    for _ in range(max_years):
        take = min(left, room)
        if take > 0:
            rows.append({"fy": f"{fy}-{fy + 1}", "amount_inr": round(take)})
            left -= take
        if left <= 0:
            break
        fy, room = fy + 1, th
    lumped = tf.tcs(remitted_before_inr, amount_inr)
    return {"amount_inr": round(amount_inr), "start": start.isoformat(), "by_financial_year": rows, "unplaced_inr": round(max(left, 0.0)),
            "tcs_if_split_inr": 0.0, "tcs_if_one_lump_inr": lumped["tcs_rs"], "label": lumped["label"],
            "note": "each year's room is the TCS threshold less what already went abroad that year; also inside the LRS limit"}


def current_plan(con, asof: date, investable: float) -> Optional[dict]:
    """The approved share and start month with today's funding split, or None while no share is approved."""
    from pflab.ledger import foreign as lf
    from pflab.risk import themes
    share = themes.applied(con, "us_sleeve", "share")
    if share is None:
        return None
    row = con.execute("SELECT evidence_json FROM limit_proposals WHERE kind='us_sleeve' AND key='share' AND status='applied' "
                      "ORDER BY prop_id DESC LIMIT 1").fetchone()
    s = (json.loads(row[0] or "{}").get("start") if row else None)
    start = date.fromisoformat(s) if s else asof
    start = max(start, date(asof.year, asof.month, 1))
    before = lf.remitted_in_fy(con, start)["inr"]
    return {"share": share, **funding_plan(share * investable, start, before)}


def plan_now(con, asof: date) -> Optional[dict]:
    """current_plan with today's investable amount; None (and no work) while no share is approved."""
    from pflab.plan import companion
    from pflab.risk import themes
    if themes.applied(con, "us_sleeve", "share") is None:
        return None
    return current_plan(con, asof, companion.positions(con, asof)["investable"])
