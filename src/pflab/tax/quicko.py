"""The Quicko pack (S65, S64 Phase 7 item 10): Quicko files his return; this prepares its inputs and reconciles. It files nothing.

Per financial year (the label is the year the FY ends, as everywhere in `tax/`: FY2026 = April 2025 to March 2026):

    gains by schedule   short-term 111A, short-term at slab, long-term 112A (with the 31-Jan-2018 grandfathering of
                        `gains.classify`), long-term 112 (no exemption); totals, the year's set-off and exemption
    Schedule 112A CSV   the department's utility layout (`configs/forms/itr_112a_layout.toml`, primary source, read 2026-10-28):
                        one row per holding bought on or before 31 Jan 2018 (BE), one consolidated row for the rest (AE)
    income              dividends by credit, bank interest, fixed-deposit interest (certified or ESTIMATED, labelled)
    foreign rows        US trades, remittances and TCS of the year, year-end holdings for Schedule FA, the gains in rupees
                        (ESTIMATES from `configs/tax/foreign.toml`, every row `secondary` until the primary-source check)
    reconcile           a Console or Quicko tax P&L export against the ledger, per ISIN; a difference above Rs 1 that the
                        file's own charges do not explain goes to Needs from you

Nothing here is a filing or advice. Money is float rupees; every estimate is labelled.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from pflab import _toml
from pflab.tax import gains as gn

LAYOUT = Path(__file__).resolve().parents[3] / "configs" / "forms" / "itr_112a_layout.toml"
GRANDFATHER_DATE = date(2018, 1, 31)
SCHEDULES = (("ST_111A", "short-term, section 111A (listed equity, STT paid)"), ("ST_SLAB", "short-term taxed at slab rates"),
             ("LT_112A", "long-term, section 112A (listed equity, STT paid; yearly exemption)"), ("LT_112", "long-term, section 112 (no exemption)"))


def layout(path: Optional[Path] = None) -> dict:
    cfg = _toml.load(path or LAYOUT)
    return {"meta": cfg["meta"], "columns": cfg["column"]}


# --- the 31 January 2018 value (s.55(2)(ac)) --------------------------------------------------------------------------------

def fmv_2018_from_bhavcopy(root: Path) -> Callable[[str], Optional[float]]:
    """The highest price quoted on 31 January 2018 per ISIN (the day before, if it did not trade that day), from the NSE bhavcopy
    in the data folder; None for an ISIN with no price then. The law names the highest price on the exchange; NSE only."""
    from pflab.data import bhavcopy
    try:
        df = bhavcopy.load(date(2018, 1, 22), GRANDFATHER_DATE, root)
    except Exception:
        return lambda isin: None
    if df.empty:
        return lambda isin: None
    last = df.sort_values("date").groupby("isin").tail(1)
    table = dict(zip(last["isin"], last["high"].astype(float)))
    return lambda isin: table.get(isin)


# --- gains by schedule ---------------------------------------------------------------------------------------------------------

def _names(con) -> Dict[str, str]:
    return {r[0]: (r[1] or r[2] or r[0]) for r in con.execute("SELECT isin, name, symbol FROM instruments").fetchall()}


def schedules(rows: pd.DataFrame) -> dict:
    out = {}
    for b, label in SCHEDULES:
        sub = rows[rows["bucket"] == b] if len(rows) else rows
        out[b] = {"label": label, "lines": int(len(sub)), "proceeds": round(float(sub["proceeds"].sum()), 2) if len(sub) else 0.0,
                  "cost": round(float(sub["cost_used"].sum()), 2) if len(sub) else 0.0,
                  "gain": round(float(sub["gain"].sum()), 2) if len(sub) else 0.0}
    return out


def _clean_name(s: str) -> str:
    """The utility accepts letters and digits only (no , / - _ ( ) & @ \\ ' \" ; :)."""
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 ]", " ", str(s))).strip()[:60] or "UNKNOWN"


def rows_112a(rows: pd.DataFrame, names: Dict[str, str], fmv_2018: Optional[Callable[[str], Optional[float]]] = None) -> List[dict]:
    """Schedule 112A rows keyed by the layout's column keys. BE: one per holding bought on or before 31 Jan 2018, with the
    grandfathered cost (column 9 = the lower of 11 and 6, column 7 = the higher of 8 and 9); AE: everything later in one
    consolidated row. Sale proceeds are net of selling charges, so column 12 is 0 and column 6 is the net value: column 14 is the
    same either way."""
    sub = rows[rows["bucket"] == "LT_112A"] if len(rows) else rows
    out: List[dict] = []
    be = sub[sub["acq_date"] <= GRANDFATHER_DATE] if len(sub) else sub
    for isin, g in (be.groupby("isin") if len(be) else []):
        fmv = fmv_2018(isin) if fmv_2018 else None
        if fmv is None:
            raise gn.GainsError(f"{isin} is a 112A holding bought before 1 Feb 2018 and needs its 31 January 2018 value")
        qty, proceeds, cost = float(g["qty"].sum()), float(g["proceeds"].sum()), float(g["cost"].sum())
        price = round(proceeds / qty, 4)
        full = round(qty * price)
        fmv_total = round(qty * round(fmv, 4))
        col9 = min(fmv_total, full)
        col7 = max(round(cost, 4), col9)
        out.append({"acquired": "BE", "isin": isin, "name": _clean_name(names.get(isin, isin)), "qty": round(qty, 4), "price": price,
                    "full_value": full, "cost_without_indexation": col7, "cost": round(cost, 4), "lower_of_11_and_6": col9,
                    "fmv_per_unit": round(fmv, 4), "fmv_total": fmv_total, "expenditure": 0.0,
                    "deductions": round(col7), "balance": full - round(col7)})
    ae = sub[sub["acq_date"] > GRANDFATHER_DATE] if len(sub) else sub
    if len(ae):
        full, cost = round(float(ae["proceeds"].sum())), float(ae["cost"].sum())
        out.append({"acquired": "AE", "isin": "INNOTREQUIRD", "name": "CONSOLIDATED", "qty": "", "price": "", "full_value": full,
                    "cost_without_indexation": round(cost, 4), "cost": round(cost, 4), "lower_of_11_and_6": "", "fmv_per_unit": "",
                    "fmv_total": "", "expenditure": 0.0, "deductions": round(cost), "balance": full - round(cost)})
    return out


def csv_112a(rows: List[dict], path: Optional[Path] = None) -> str:
    """The rows as the utility's CSV: the layout's headings, in its order, no forbidden characters, CRLF line ends."""
    cols = layout(path)["columns"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([c["heading"] for c in cols])
    for r in rows:
        w.writerow([r.get(c["key"], "") for c in cols])
    return buf.getvalue()


# --- income and the foreign rows -------------------------------------------------------------------------------------------------

def income_block(t: dict, names: Dict[str, str], fy: int) -> dict:
    from pflab.tax.india_lots import fy_of
    led = t["ledger"]
    div = [i for i in led.income if i.kind == "dividend" and fy_of(i.date) == fy]
    intr = [i for i in led.income if i.kind == "interest" and fy_of(i.date) == fy]
    fd = t.get("fd") or {"rows": [], "interest": 0.0, "tds": 0.0, "is_estimate": False}
    num = lambda x: float(getattr(x, "value", x))             # noqa: E731
    return {"dividends": {"rows": [{"date": str(i.date), "isin": i.isin, "name": names.get(i.isin or "", i.isin or ""), "gross": round(i.gross, 2),
                                    "tds": round(i.tds, 2)} for i in sorted(div, key=lambda x: x.date)],
                          "gross": round(sum(i.gross for i in div), 2), "tds": round(sum(i.tds for i in div), 2)},
            "bank_interest": {"gross": round(sum(i.gross for i in intr), 2), "tds": round(sum(i.tds for i in intr), 2), "lines": len(intr)},
            "fd_interest": {"interest": round(num(fd["interest"]), 2), "tds": round(num(fd["tds"]), 2),
                            "is_estimate": bool(fd.get("is_estimate")),
                            "rows": [{"fd": r.fd_id, "interest": round(num(r.interest), 2), "tds": round(num(r.tds), 2), "source": r.source}
                                     for r in fd["rows"]],
                            "label": "ESTIMATE until the bank's certificate" if fd.get("is_estimate") else "from the bank's certificates"}}


def foreign_block(con, fy: int, slab: float = 0.30) -> dict:
    """US rows for the FY (Apr to Mar) and the calendar year Schedule FA asks about. ESTIMATES, labelled; nothing recorded is invented:
    US tax withheld and peak values are not on record until a statement parser exists."""
    from pflab.ledger import foreign as lf
    lo, hi = date(fy - 1, 4, 1), date(fy, 3, 31)
    trades = [{"date": str(r[0]), "symbol": r[1], "side": r[2], "qty": r[3], "price_usd": r[4], "charges_usd": r[5] or 0.0}
              for r in con.execute("SELECT trade_date, symbol, side, qty, price_usd, charges_usd FROM us_trades WHERE trade_date BETWEEN ? AND ? "
                                   "ORDER BY trade_date, trade_id", [lo, hi]).fetchall()]
    rem = [{"date": str(r[0]), "usd": r[1], "inr": r[2], "tcs_inr": r[3] or 0.0}
           for r in con.execute("SELECT remit_date, usd, inr, tcs_inr FROM us_remittances WHERE remit_date BETWEEN ? AND ? ORDER BY remit_date",
                                [lo, hi]).fetchall()]
    cal_end = date(fy - 1, 12, 31)                              # Schedule FA: the calendar year that ends inside the FY
    out = {"trades": trades, "remittances": rem, "tcs_total_inr": round(sum(r["tcs_inr"] for r in rem), 2),
           "schedule_fa_holdings_on": str(cal_end), "schedule_fa_holdings": lf.positions(con, cal_end),
           "us_tax_withheld": "not on record: needs the GIFT City statements (a parser comes with the first statement)",
           "form_67": "needs the US tax paid abroad (not on record)", "peak_value_in_year": "not on record (Schedule FA asks for it)"}
    if trades or out["schedule_fa_holdings"]:
        out["gains"] = lf.gains(con, fy - 1, slab)
    return out


def build(con, fy: int, root: Optional[Path] = None, fmv_2018: Optional[Callable] = None) -> dict:
    """Everything above for one FY. A holding that needs its 2018 value and has none is listed under `problems`, not guessed."""
    from datetime import date as _date

    from pflab.ledger import events as ev
    from pflab.ledger.book import Ledger
    from pflab.pm import fd as fdm
    from pflab.tax import report
    fmv = fmv_2018 or (fmv_2018_from_bhavcopy(root) if root else None)
    problems: List[str] = []
    try:                    # the gains and income only: the regime tax needs slab tables the pack does not use
        led = Ledger.replay(ev.load(con), upto=_date(fy, 3, 31))
        every = gn.detail(led.realised, report.tax_class_lookup(con), fmv_2018=fmv)
        first = min([fy] + (list(every["fy"]) if len(every) else []))
        g = next((x for x in gn.settle_all(every, first_fy=first, last_fy=fy) if x.fy == fy), None)
    except gn.GainsError as e:
        raise RuntimeError(f"the year's gains cannot be computed yet: {e}") from None
    rows = every[every["fy"] == fy] if len(every) else every
    t = {"ledger": led, "fd": fdm.year_totals(fdm.load(con), fy, fdm.interest_facts(con))}
    names = _names(con)
    r112 = rows_112a(rows, names, fmv)
    return {"fy": fy, "label": f"FY{fy - 1}-{str(fy)[2:]}", "schedules": schedules(rows),
            "year": None if g is None else {"realised": g.realised, "after_current_year_set_off": g.after_current, "taxable": g.taxable,
                                           "exemption_used": g.exemption_used, "exemption_available": g.exemption_available,
                                           "carried_out": [(l.origin_fy, "LT" if l.long_term else "ST", round(l.amount, 2)) for l in g.carried_out]},
            "sales": [{"isin": r.isin, "name": names.get(r.isin, r.isin), "bucket": r.bucket, "bought": str(r.acq_date), "sold": str(r.sell_date),
                       "qty": r.qty, "proceeds": round(r.proceeds, 2), "cost": round(r.cost_used, 2), "gain": round(r.gain, 2),
                       "grandfathered": bool(r.grandfathered)} for r in rows.itertuples()] if len(rows) else [],
            "schedule_112a": r112, "schedule_112a_csv": csv_112a(r112), "income": income_block(t, names, fy), "foreign": foreign_block(con, fy),
            "problems": problems, "notes": [
                "Proceeds are net of selling charges and cost includes buying charges, so 'Expenditure on transfer' (column 12) is 0 and column 6 is the net value; the Balance equals the gain either way.",
                "FMV on 31 Jan 2018 is the NSE bhavcopy high of that day (or the last session before): the law names the highest price on the exchange.",
                "Quicko files the return. Check this against its own capital-gains summary before filing; differences go through `reconcile`."]}


def write_pack(pack: dict, out_dir: Path) -> List[Path]:
    """Files for the year: the 112A CSV, the sales and income as CSV, and a summary text. Returns the paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fy = pack["fy"]
    paths = []
    p = out_dir / f"schedule_112A_FY{fy}.csv"
    p.write_text(pack["schedule_112a_csv"], encoding="utf-8", newline="")
    paths.append(p)
    s = out_dir / f"sales_FY{fy}.csv"
    pd.DataFrame(pack["sales"]).to_csv(s, index=False)
    paths.append(s)
    d = out_dir / f"dividends_FY{fy}.csv"
    pd.DataFrame(pack["income"]["dividends"]["rows"]).to_csv(d, index=False)
    paths.append(d)
    lines = [f"Quicko pack {pack['label']} (prepared {datetime.now():%Y-%m-%d}; nothing is filed from this)"]
    for b, label in SCHEDULES:
        x = pack["schedules"][b]
        lines.append(f"  {b:8} {label}: {x['lines']} line(s), proceeds {x['proceeds']:,.0f}, cost {x['cost']:,.0f}, gain {x['gain']:,.0f}")
    inc = pack["income"]
    lines.append(f"  dividends {inc['dividends']['gross']:,.0f} (TDS {inc['dividends']['tds']:,.0f}); bank interest {inc['bank_interest']['gross']:,.0f}; "
                 f"FD interest {inc['fd_interest']['interest']:,.0f} (TDS {inc['fd_interest']['tds']:,.0f}, {inc['fd_interest']['label']})")
    f = pack["foreign"]
    lines.append(f"  foreign: {len(f['trades'])} trade(s), {len(f['remittances'])} remittance(s), TCS {f['tcs_total_inr']:,.0f}, "
                 f"{len(f['schedule_fa_holdings'])} holding(s) on {f['schedule_fa_holdings_on']}; ESTIMATES (foreign-tax rows are secondary-sourced)")
    lines += ["  note: " + n for n in pack["notes"]]
    t = out_dir / f"summary_FY{fy}.txt"
    t.write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths.append(t)
    return paths


# --- reconcile a Console or Quicko tax P&L export ------------------------------------------------------------------------------

PROFIT_NAMES = ("taxable profit", "realised profit", "realized profit", "profit", "capital gain", "gain", "p&l", "pnl")
CHARGE_NAMES = ("brokerage", "charges", "total charges")


def _table(data: bytes, name: str, passwords=()) -> pd.DataFrame:
    """The export's table: the first row that names an ISIN column and a profit column is the header."""
    from pflab.ingest import bank
    if Path(name).suffix.lower() == ".csv":
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
    else:
        rows = bank._sheet_rows(data, (list(passwords) or [None])[0])
    for i, r in enumerate(rows[:80]):
        low = [str(c).strip().lower() for c in r]
        if "isin" in low and any(any(p == c for p in PROFIT_NAMES) for c in low):
            head = [str(c).strip() for c in r]
            return pd.DataFrame([list(x) + [None] * (len(head) - len(x)) for x in rows[i + 1:]], columns=[h or f"c{j}" for j, h in enumerate(head)])
    raise ValueError("no table with an ISIN column and a profit column (Console 'Tax P&L' or a Quicko capital-gains export)")


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return float("nan")


def reconcile(pack: dict, data: bytes, name: str, tol: float = 1.0) -> dict:
    """Per ISIN: the ledger's gain for the year against the export's profit (and the export's own charges, which its profit leaves out).
    A difference above `tol` rupees that charges do not explain is reported."""
    df = _table(data, name)
    low = {c.lower(): c for c in df.columns}
    isin_c = low["isin"]
    profit_c = next(low[p] for p in PROFIT_NAMES if p in low)
    charge_cs = [low[c] for c in CHARGE_NAMES if c in low][:1]
    exit_c = next((low[c] for c in ("exit date", "sell date", "sale date", "date of sale") if c in low), None)
    if exit_c:
        text = df[exit_c].astype(str).str.strip().str[:10]
        d = pd.to_datetime(text, errors="coerce", format="%Y-%m-%d")                      # ISO first: dayfirst would misread 2025-10-01
        d = d.fillna(pd.to_datetime(text, errors="coerce", dayfirst=True, format="mixed"))
        df = df[(d >= pd.Timestamp(date(pack["fy"] - 1, 4, 1))) & (d <= pd.Timestamp(date(pack["fy"], 3, 31)))]
    df = df[df[isin_c].astype(str).str.match(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$", na=False)]
    theirs = df.assign(_p=df[profit_c].map(_num)).groupby(isin_c)["_p"].sum()
    charges = df.assign(_c=df[charge_cs[0]].map(_num)).groupby(isin_c)["_c"].sum() if charge_cs else pd.Series(dtype=float)
    ours: Dict[str, float] = {}
    for s in pack["sales"]:
        ours[s["isin"]] = ours.get(s["isin"], 0.0) + s["gain"]
    rows = []
    for isin in sorted(set(ours) | set(theirs.index)):
        a, b = round(ours.get(isin, 0.0), 2), round(float(theirs.get(isin, 0.0)), 2)
        ch = round(float(charges.get(isin, 0.0)), 2) if len(charges) else 0.0
        resid = round(a - (b - ch), 2)                         # the export's profit is before charges: remove them from its side
        rows.append({"isin": isin, "name": next((s["name"] for s in pack["sales"] if s["isin"] == isin), isin), "ledger": a, "export": b,
                     "export_charges": ch, "difference": round(a - b, 2), "unexplained": resid,
                     "ok": abs(resid) <= tol or (not ch and abs(a - b) <= tol)})
    return {"fy": pack["fy"], "rows": rows, "matched": sum(r["ok"] for r in rows), "differences": [r for r in rows if not r["ok"]], "tolerance": tol}


def ask_differences(con, rec: dict, now: Optional[datetime] = None) -> int:
    """One Needs-from-you item per ISIN whose difference above Rs 1 stays unexplained. Returns how many were new."""
    from pflab.agents import questions
    n = 0
    for r in rec["differences"]:
        text = (f"The tax P&L export and my ledger disagree for {r['name']} ({r['isin']}) in FY{rec['fy'] - 1}-{str(rec['fy'])[2:]}: "
                f"mine {r['ledger']:,.2f}, the file {r['export']:,.2f} (its own charges {r['export_charges']:,.2f}), Rs {abs(r['unexplained']):,.2f} "
                "unexplained. A missing or extra trade, a different cost basis, or the 31 January 2018 value are the usual causes. "
                "Tell me which side is right, or drop the missing statement into Inbox and files.")
        if questions.ask(con, "quicko", f"quicko:recon:{rec['fy']}:{r['isin']}", text, now or datetime.now()):
            n += 1
    return n
