"""Exposure by asset bucket, sector, stock and issuer (PLAN S15).

Weights are shares of TOTAL portfolio value (invested plus cash) unless stated, so cash is
an exposure like any other. Unpriced positions are not in any weight: they are reported in
`unpriced` and the weights say what share of the priced total they are. Fund holdings carry
no sector until S16's look-through is supplied: they appear under a `fund:<category>` label,
never spread by guess.
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from pflab.calc.valuation import Valuation, by_isin

BUCKETS = ("equity", "equity_fund", "debt", "gold", "reit_invit", "cash", "intl_equity", "unclassified")      # S64: intl_equity = the US sleeve


def bucket(asset_class: Optional[str], tax_class: Optional[str], category: Optional[str] = None,
           name: Optional[str] = None, market: Optional[str] = None) -> str:
    """Risk bucket for one instrument, from labels the instrument master already holds. An instrument that trades outside
    NSE and BSE (S64: a US stock or ETF) is `intl_equity`."""
    if isinstance(market, str) and market and market not in ("NSE", "BSE"):
        return "intl_equity"
    ac, tc = (asset_class or ""), (tax_class or "")
    text = f"{category or ''} {name or ''}".lower()
    if ac in ("sgb", "gold_physical") or tc in ("SGB", "PHYSICAL_GOLD"):
        return "gold"
    if "gold" in text or "silver" in text:
        return "gold" if ac in ("etf", "mutual_fund") else "unclassified"
    if ac == "equity":
        return "equity"
    if ac in ("reit", "invit") or tc == "BUSINESS_TRUST":
        return "reit_invit"
    if ac == "bond" or tc in ("DEBT_MF", "UNLISTED_DEBT"):
        return "debt"
    if tc == "LISTED_NONEQUITY":
        return "debt" if ac == "bond" else "unclassified"
    if ac in ("etf", "mutual_fund") and tc == "EQUITY":
        return "equity_fund"
    return "unclassified"


def exposures(v: Valuation, instruments: pd.DataFrame,
              lookthrough: Optional[pd.DataFrame] = None) -> Dict[str, pd.DataFrame]:
    """Weights by bucket, sector, stock and issuer.

    `instruments`: columns isin, asset_class, tax_class, sector, issuer, name, category.
    `lookthrough`: optional (fund_isin, isin, sector, issuer, weight) rows from S16, weights per
    fund summing to <= 1; a fund's value is then spread over its holdings for sector, stock and
    issuer, and any remainder stays under the fund's own label."""
    g = by_isin(v)
    inst = instruments.set_index("isin") if "isin" in instruments.columns else instruments
    total = v.total
    rows = []
    for r in g.itertuples():
        if r.value != r.value:           # NaN: unpriced
            continue
        i = inst.loc[r.isin] if r.isin in inst.index else None
        rows.append(dict(isin=r.isin, value=r.value,
                         bucket=bucket(*(None if i is None else (i["asset_class"], i["tax_class"],
                                                                 i.get("category"), i.get("name"), i.get("market"))))
                         if i is not None else bucket(None, None),
                         sector=None if i is None else i.get("sector"),
                         issuer=None if i is None else i.get("issuer"),
                         name=None if i is None else i.get("name"),
                         category=None if i is None else i.get("category")))
    h = pd.DataFrame(rows, columns=["isin", "value", "bucket", "sector", "issuer", "name", "category"])
    for c in ("sector", "issuer", "name", "category"):        # pandas NaN is truthy: make absence None
        h[c] = h[c].astype(object).where(h[c].notna(), None)
    cash = pd.DataFrame([{"bucket": "cash", "value": v.cash_total}]) if v.cash_total else pd.DataFrame(columns=["bucket", "value"])
    allb = pd.concat([h[["bucket", "value"]], cash], ignore_index=True)
    by_bucket = _weights(allb.groupby("bucket", as_index=False)["value"].sum(), total, "bucket")

    # sector / stock / issuer: look through funds where S16 supplied it
    parts = []
    lt = lookthrough if lookthrough is not None else pd.DataFrame(columns=["fund_isin", "isin", "sector", "issuer", "weight"])
    funds = set(lt["fund_isin"]) if len(lt) else set()
    for r in h.itertuples():
        if r.isin in funds:
            sub = lt[lt["fund_isin"] == r.isin]
            for s in sub.itertuples():
                parts.append(dict(isin=s.isin, sector=s.sector, issuer=s.issuer, value=r.value * s.weight,
                                  via=r.isin))
            rest = 1.0 - float(sub["weight"].sum())
            if rest > 1e-9:
                parts.append(dict(isin=r.isin, sector=f"fund:{r.category or 'unknown'} (unlooked remainder)",
                                  issuer=None, value=r.value * rest, via=r.isin))
        elif r.bucket in ("equity",):
            parts.append(dict(isin=r.isin, sector=r.sector or "Unclassified", issuer=r.issuer, value=r.value, via=None))
        elif r.bucket in ("equity_fund", "unclassified", "reit_invit") and r.isin not in funds:
            parts.append(dict(isin=r.isin, sector=f"fund:{r.category or r.bucket}", issuer=None, value=r.value, via=None))
    p = pd.DataFrame(parts, columns=["isin", "sector", "issuer", "value", "via"])
    by_sector = _weights(p.groupby("sector", as_index=False)["value"].sum(), total, "sector") if len(p) else _empty("sector")
    by_stock = _weights(p.groupby("isin", as_index=False)["value"].sum(), total, "isin") if len(p) else _empty("isin")
    by_issuer = _weights(p.dropna(subset=["issuer"]).groupby("issuer", as_index=False)["value"].sum(),
                         total, "issuer") if len(p) and p["issuer"].notna().any() else _empty("issuer")
    return {"bucket": by_bucket, "sector": by_sector, "stock": by_stock, "issuer": by_issuer,
            "unpriced": pd.DataFrame(v.unpriced, columns=["account", "isin", "qty", "cost"])}


def _weights(df: pd.DataFrame, total: float, key: str) -> pd.DataFrame:
    out = df.copy()
    out["weight"] = out["value"] / total if total > 0 else float("nan")
    return out.sort_values("value", ascending=False).reset_index(drop=True)


def _empty(key: str) -> pd.DataFrame:
    return pd.DataFrame(columns=[key, "value", "weight"])
