"""Zerodha Console tradebook (CSV or .xlsx) -> ledger events (PLAN S4).

The Console tradebook has one row per execution: symbol, isin, trade_date, exchange, segment, series,
trade_type, auction, quantity, price, trade_id, order_id, order_execution_time. It carries NO charges
(contract notes are the truth for those) and NO deposits, so the import builds buy and sell events
only and reports what is missing; opening balances and charges are reconciled in S7. Import is
idempotent: an execution whose trade_id is already in the log (as an event `ref`) is skipped.
"""
from __future__ import annotations

import io
import itertools
import re
import zipfile
from pathlib import Path
from typing import Callable, List, Optional, Set, Tuple, Union

import pandas as pd

from pflab.ledger.events import Event

REQUIRED = ["symbol", "isin", "trade_date", "trade_type", "quantity", "price", "trade_id"]


class TradebookError(ValueError):
    pass


def _cell(v) -> Optional[str]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def name_sheets(raw: bytes) -> bytes:
    """An .xlsx whose `xl/workbook.xml` names no sheet (some Console exports), with the names filled in, in memory; any other bytes unchanged."""
    if raw[:2] != b"PK":
        return raw
    zin = zipfile.ZipFile(io.BytesIO(raw))
    wb_xml = zin.read("xl/workbook.xml").decode("utf-8")
    n = itertools.count(1)
    fixed = re.sub(r"<sheet (?![^>]*\bname=)", lambda m: f'<sheet name="Sheet{next(n)}" ', wb_xml)
    if fixed == wb_xml:
        return raw
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item, fixed if item.filename == "xl/workbook.xml" else zin.read(item.filename))
    return buf.getvalue()


def _xlsx_frame(path: Path) -> pd.DataFrame:
    """Console .xlsx -> raw frame. The sheet has a preamble (Client ID, report title) above the header row,
    found by its Symbol and Trade ID cells. Some Console exports name no sheet in `xl/workbook.xml`, which
    openpyxl refuses; the missing name is filled in memory and the file on disk is untouched."""
    import openpyxl
    raw = name_sheets(path.read_bytes())
    ws = openpyxl.load_workbook(io.BytesIO(raw), data_only=True).worksheets[0]
    rows = [[_cell(c) for c in r] for r in ws.iter_rows(values_only=True)]
    head = next((i for i, r in enumerate(rows)
                 if {"symbol", "trade id"} <= {(c or "").strip().lower() for c in r}), None)
    if head is None:
        raise TradebookError(f"no header row with Symbol and Trade ID in {path.name}")
    cols = [(c or "").strip() for c in rows[head]]
    body = [r for r in rows[head + 1:] if any(r)]
    return pd.DataFrame(body, columns=cols).loc[:, [c for c in cols if c]]


def parse(source: Union[str, Path]) -> pd.DataFrame:
    """CSV text, CSV path or Console .xlsx path -> normalised frame: isin, symbol, date, side, qty, price,
    trade_id, order_id, exchange, series."""
    s = str(source)
    if "\n" not in s and s.lower().endswith(".xlsx"):
        df = _xlsx_frame(Path(source))
    else:
        text = s if "\n" in s else Path(source).read_text(encoding="utf-8-sig")
        df = pd.read_csv(io.StringIO(text), dtype=str)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise TradebookError(f"tradebook is missing columns {missing}; found {list(df.columns)}")
    df = df.dropna(subset=["trade_id"])
    out = pd.DataFrame({
        "isin": df["isin"].str.strip().str.upper(),
        "symbol": df["symbol"].str.strip(),
        "date": pd.to_datetime(df["trade_date"].str.strip()).dt.date,
        "side": df["trade_type"].str.strip().str.lower(),
        "qty": pd.to_numeric(df["quantity"]),
        "price": pd.to_numeric(df["price"]),
        "trade_id": df["trade_id"].str.strip(),
        "order_id": df["order_id"].str.strip() if "order_id" in df.columns else "",
        "exchange": df["exchange"].str.strip() if "exchange" in df.columns else "",
        "series": df["series"].str.strip() if "series" in df.columns else "",
    })
    # Console lists IPO allotments as buys with trade_id "IPO" and no ISIN. They are not exchange trades:
    # they are set aside (`attrs["ipo_allotments"]`) to be recorded as ipo_* events with the bank block (S19).
    is_ipo = out["trade_id"].str.upper().eq("IPO")
    ipo, out = out[is_ipo], out[~is_ipo]
    bad = out[~out["side"].isin(["buy", "sell"])]
    if len(bad):
        raise TradebookError(f"unknown trade_type {sorted(set(bad['side']))} on trade_id {list(bad['trade_id'][:3])}")
    if (out["qty"] <= 0).any() or (out["price"] < 0).any():
        raise TradebookError("non-positive quantity or negative price in the tradebook")
    if out["isin"].isna().any() or (out["isin"] == "").any():
        raise TradebookError("a row has no ISIN: ISIN is the security key, no symbol-only imports")
    if out["trade_id"].duplicated().any():
        raise TradebookError(f"duplicate trade_id inside the file: {list(out[out['trade_id'].duplicated()]['trade_id'][:3])}")
    out = out.sort_values(["date", "trade_id"], kind="mergesort").reset_index(drop=True)
    out.attrs["ipo_allotments"] = ipo[["symbol", "date", "qty", "price", "exchange"]].to_dict("records")
    return out


def to_events(df: pd.DataFrame, account: str, existing_refs: Optional[Set[str]] = None,
              tax_class_of: Optional[Callable[[str], Optional[str]]] = None,
              source_doc_sha: str = "") -> Tuple[List[Event], dict]:
    existing_refs = existing_refs or set()
    events, skipped = [], 0
    for r in df.itertuples(index=False):
        if r.trade_id in existing_refs:
            skipped += 1
            continue
        events.append(Event(r.side, account, r.date, isin=r.isin, qty=float(r.qty), price=float(r.price),
                            ref=r.trade_id, source_doc_sha=source_doc_sha,
                            tax_class=tax_class_of(r.isin) if tax_class_of else None))
    new = df[~df["trade_id"].isin(existing_refs)]
    b, s = new[new["side"] == "buy"], new[new["side"] == "sell"]
    report = {"events": len(events), "skipped_existing": skipped,
              "buy_value": float((b["qty"] * b["price"]).sum()), "sell_value": float((s["qty"] * s["price"]).sum()),
              "first_date": min(new["date"]) if len(new) else None, "last_date": max(new["date"]) if len(new) else None,
              "missing": ["charges (contract notes are the truth; not in the tradebook)",
                          "deposits / opening cash (add them; the ledger refuses purchases without funds)"]}
    ipo = df.attrs.get("ipo_allotments", [])
    if ipo:
        report["ipo_allotments"] = ipo
        report["missing"].append(f"{len(ipo)} IPO allotment(s) not imported: record them as ipo_* events with "
                                 "the ISIN and the bank block (ledger.ipo)")
    return events, report
