"""Pre-trade nudges (S64; the investor pointed at Zerodha's Kite nudges: a warning in the order window before the trade).

Kite's nudges, and what each becomes here, from our own data and labelled when it is a different rule:
    trade-to-trade (T2T)        the stock trades in series BE or BZ today: delivery only, no intraday, tight price band
    exchange surveillance       on an ASM / GSM / LTASM / ESM list today (the stage and the exchange's own code)
    insolvency (IRP)            the surveillance list flags IBC, or a BSE filing of the last year names the insolvency process
    corporate action            a split or bonus with an ex-date in the last 5 or next 14 days: the price drop at the ex-date
                                is the action, not a loss
    illiquid                    Kite uses a market value under Rs 100 crore; we have no share count, so: average daily traded
                                value over 20 sessions under Rs 25 lakh (OUR rule, labelled), and an order that is more than 1%
                                of it
    rights entitlement          the series or the symbol says rights entitlement
    to be suspended             a BSE filing of the last 30 days names a suspension of trading
    tips from unregistered      cannot be checked (no source): said in `not_checked`, never silently passed
A nudge is a warning with its source, not a block and not a signal; the order stays the investor's.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

ILLIQUID_RS = 25 * 100_000.0                 # average daily traded value below this: thinly traded
ORDER_SHARE = 0.01                           # an order above this share of the average daily value moves the price
CA_BEFORE, CA_AFTER = 5, 14
IRP_DAYS, SUSPEND_DAYS = 365, 30
IRP_WORDS = re.compile(r"insolvency resolution process|corporate insolvency resolution|\bCIRP\b|\bNCLT\b.{0,60}insolvency", re.I)
SUSPEND_WORDS = re.compile(r"suspen", re.I)
NOT_CHECKED = ["tips from unregistered sources (no data source for it)"]


def _bhav(root, isin: str, asof: date, days: int = 40) -> pd.DataFrame:
    from pflab import _duck
    from pflab.data.bhavcopy import bhav_files
    files = bhav_files(Path(root), asof - timedelta(days=days), asof)
    if not files:
        return pd.DataFrame(columns=["date", "symbol", "series", "turnover", "close"])
    rel = f"read_parquet({files!r}, union_by_name=true)"
    return _duck.sql(f"SELECT date, symbol, series, turnover, close FROM {rel} WHERE isin = '{isin}' AND date <= DATE '{asof}' "
                     "ORDER BY date").df()


def _surveillance(root, isin: str, asof: date) -> pd.DataFrame:
    p = Path(root) / "surveillance"
    files = sorted(f for f in p.glob("*.parquet") if f.stem <= str(asof)) if p.exists() else []
    if not files:
        return pd.DataFrame()
    d = pd.read_parquet(files[-1])
    return d[d["isin"] == isin]


def _announcements(root, scrip: Optional[str], asof: date, days: int) -> pd.DataFrame:
    """The scrip's BSE announcement headlines of the last `days`."""
    if not scrip:
        return pd.DataFrame()
    out = []
    for y in {asof.year, (asof - timedelta(days=days)).year}:
        p = Path(root) / "bse_announcements" / str(y)
        for f in sorted(p.glob("*.parquet")) if p.exists() else []:
            try:
                d = pd.read_parquet(f)
            except Exception:
                continue
            if "scrip_code" in d.columns:
                out.append(d[d["scrip_code"].astype(str) == str(scrip)])
    if not out:
        return pd.DataFrame()
    d = pd.concat(out, ignore_index=True)
    col = "dissem_dt" if "dissem_dt" in d.columns else d.columns[0]
    d[col] = pd.to_datetime(d[col])
    return d[(d[col] >= pd.Timestamp(asof - timedelta(days=days))) & (d[col] <= pd.Timestamp(asof))]


def _text_cols(d: pd.DataFrame) -> pd.Series:
    cols = [c for c in ("headline", "subcategory", "category", "title") if c in d.columns]
    return d[cols].fillna("").astype(str).agg(" ".join, axis=1) if cols and len(d) else pd.Series(dtype=str)


def check(root, isin: str, asof: date, symbol: Optional[str] = None, order_rupees: Optional[float] = None,
          scrip: Optional[str] = None) -> List[dict]:
    """The nudges that apply to this stock today: [{kind, text, source}]. Empty means none apply, not that nothing was checked
    (see NOT_CHECKED)."""
    root = Path(root)
    out: List[dict] = []

    def add(kind, text, source):
        out.append({"kind": kind, "text": text, "source": source})
    b = _bhav(root, isin, asof)
    if len(b):
        last = b.iloc[-1]
        sym = symbol or last["symbol"]
        if str(last["series"]) in ("BE", "BZ"):
            add("t2t", f"{sym} trades in the trade-to-trade series ({last['series']}): every buy must be taken in delivery, no "
                       "intraday, and the exchange keeps its price band narrow.", f"NSE bhavcopy {last['date']:%Y-%m-%d}")
        if str(last["series"]) in ("RE", "RR") or str(sym).upper().endswith("-RE"):
            add("rights_entitlement", f"{sym} is a rights entitlement: it lapses if not applied for, and the whole amount can be "
                                      "lost.", f"NSE bhavcopy {last['date']:%Y-%m-%d}")
        tail = b.tail(20)
        adv = float(tail["turnover"].mean()) if len(tail) >= 10 and tail["turnover"].notna().any() else None
        if adv is not None and adv < ILLIQUID_RS:
            add("illiquid", f"{sym} is thinly traded: about Rs {adv / 1e5:,.1f} lakh a day over {len(tail)} sessions (our limit "
                            f"Rs {ILLIQUID_RS / 1e5:,.0f} lakh; Kite's own test is a market value under Rs 100 crore). Thin stocks "
                            "swing on small orders and are where pump-and-dump schemes live.", "NSE bhavcopy turnover")
        elif adv and order_rupees and order_rupees > ORDER_SHARE * adv:
            add("illiquid", f"This order is {order_rupees / adv:.1%} of {sym}'s average daily traded value (Rs {adv / 1e5:,.1f} lakh): "
                            "it will move the price; split it or use a limit.", "NSE bhavcopy turnover")
    s = _surveillance(root, isin, asof)
    for r in s.itertuples():
        add("surveillance", f"On the exchange's {r.list} list: {r.code} ({r.desc[:80]}). Verdict: {r.verdict}.",
            f"NSE surveillance {r.date}")
    if len(s) and bool(s["ibc"].any()):
        add("irp", "Flagged under the insolvency code (IBC): the whole investment can be lost if the shares are extinguished in a "
                   "resolution.", "NSE surveillance")
    try:
        from pflab.data import nse_corporate_actions as nca
        ev = nca.events(root)
        ev = ev[(ev["isin"] == isin) & (ev["kind"].isin(["split", "bonus"]))]
        ev = ev[(pd.to_datetime(ev["ex_date"]) >= pd.Timestamp(asof - timedelta(days=CA_BEFORE)))
                & (pd.to_datetime(ev["ex_date"]) <= pd.Timestamp(asof + timedelta(days=CA_AFTER)))]
        for r in ev.itertuples():
            add("corporate_action", f"A {r.kind} goes ex on {pd.Timestamp(r.ex_date):%d %b %Y}: the price falls by the action at the "
                                    "ex-date. It is not a loss, and a price comparison across it is not like for like.",
                "NSE corporate actions")
    except Exception:
        pass
    if scrip:
        try:
            a = _announcements(root, scrip, asof, IRP_DAYS)
            t = _text_cols(a)
            if len(t) and t.str.contains(IRP_WORDS).any() and not any(n["kind"] == "irp" for n in out):
                hit = t[t.str.contains(IRP_WORDS)].iloc[0][:110]
                add("irp", f"A filing of the last year names the insolvency resolution process ('{hit}'): it may concern the "
                           "company itself or a debtor or subsidiary, so read it; if it is the company's, the shares can be "
                           "extinguished in a resolution.", "BSE announcements")
            recent = _announcements(root, scrip, asof, SUSPEND_DAYS)
            tr = _text_cols(recent)
            if len(tr) and tr.str.contains(SUSPEND_WORDS).any():
                add("suspension", "A filing of the last 30 days mentions a suspension of trading; check it before buying.",
                    "BSE announcements")
        except Exception:
            pass
    return out


def lines(nudges: List[dict]) -> List[str]:
    return [f"NUDGE ({n['kind']}): {n['text']}" for n in nudges]


def fn(con, root, asof: date) -> Callable[[str, float], List[str]]:
    """A ticket helper: (isin, order rupees) -> nudge lines. Looks up the BSE scrip itself."""
    from pflab.quant import forecast as fc

    def nudge_lines(isin: str, order_rupees: float = 0.0) -> List[str]:
        try:
            return lines(check(root, isin, asof, order_rupees=order_rupees or None, scrip=fc.scrip_of(Path(root), isin, asof)))
        except Exception:
            return []
    return nudge_lines
