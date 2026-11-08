"""The verification harness of the system's own book (S79b item 18E): are splits, bonuses, dividends, ISIN changes, demergers and mergers applied to its lots, and is a top-up
added as outside money and deployed under the new allocation?

`run_synthetic(workdir)`  builds a throwaway system account (its own store, a synthetic market-data folder in the form the collectors write: the NSE feed's JSON, the combined
                         factor table, the dividends file), injects a split, a bonus, a cash dividend, an ISIN change, a demerger (price-drop factor) and a ratio merger, runs
                         `book.catch_up` and checks quantities, cost basis, lot dates, cash, value continuity across each ex-date, idempotence on a re-run and a late-arriving action.
`run_topup(workdir)`     a top-up is cash in the bank, flagged as outside money (`paper_days.flows`; `cadence.level_path` excludes it), and the next look sees cash above its target
                         class weight and is told to deploy it (`allocation.deploy_reason`); the deploy path moves cash toward the target.
`scan_real(con, root)`   the REAL corporate actions of the workshop data for the names of a book: every split, bonus and dividend in the window that the book held must be in its
                         ledger. `run_real(workdir, root)` builds the rehearsal profile's names (tools/rehearse.py) on their RAW closes and runs `scan_real` over it.
Each run is logged in `verify_book_s79` (kind, ok, checks). Nothing here touches the investor's record or the app.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

SPL, BON, DIV, ALI, ALI2, DEM, MRG, MRG2, LFT = ("INE111A01011", "INE222A01012", "INE333A01013", "INE444A01014", "INE444A01022", "INE555A01015", "INE666A01016", "INE666A01024",
                                                 "INE777A01017")
NOW = datetime(2026, 10, 28, 12, 0)
DAYS = [date(2026, 10, 26) + timedelta(days=k) for k in range(0, 48) if (date(2026, 10, 26) + timedelta(days=k)).weekday() < 5]
SEED = DAYS[2]                                                                  # 2026-10-28
EX = {"split": date(2026, 11, 4), "bonus": date(2026, 11, 6), "dividend": date(2026, 11, 9), "alias": date(2026, 11, 11), "demerger": date(2026, 11, 13), "merger": date(2026, 11, 17)}
LATE = date(2026, 11, 10)
OLD_SPLIT = date(2026, 1, 12)                                                    # before the book's start: the opening lots already carry it


def _row(isin: str, symbol: str, ex: date, subject: str, series: str = "EQ", fv: str = "10") -> dict:
    return {"bcEndDate": "-", "bcStartDate": "-", "caBroadcastDate": None, "comp": f"{symbol} Limited", "exDate": ex.strftime("%d-%b-%Y"), "faceVal": fv, "ind": "-", "isin": isin,
            "ndEndDate": "-", "ndStartDate": "-", "recDate": ex.strftime("%d-%b-%Y"), "series": series, "subject": subject, "symbol": symbol}


def write_feed(root: Path) -> None:
    """The collectors' files in their real form: the NSE feed (JSON, PURPOSE text), the combined factor table (PREVCLOSE rows), the dividends file."""
    (root / "corporate_actions" / "raw").mkdir(parents=True, exist_ok=True)
    (root / "dividends").mkdir(parents=True, exist_ok=True)
    rows = [_row(SPL, "SPLCO", EX["split"], "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"),
            _row(SPL, "SPLCO", EX["split"], "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"),        # NSE lists a revised purpose twice
            _row(SPL, "SPLCO", OLD_SPLIT, "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 5/- Per Share"),         # before the start: not applied
            _row(BON, "BONCO", EX["bonus"], "Bonus 1:1", fv="5"),
            _row(DIV, "DIVCO", EX["dividend"], "Interim Dividend - Rs 12.5 Per Share"),
            _row(ALI, "ALICO", EX["alias"], "Amalgamation"),
            _row(DEM, "DEMCO", EX["demerger"], "Demerger"),
            _row(MRG, "MRGCO", EX["merger"], "Amalgamation"),
            _row(LFT, "LFTCO", date(2026, 11, 10), "Buy Back")]
    (root / "corporate_actions" / "raw" / "2026.json").write_text(json.dumps(rows), encoding="utf-8")
    pd.DataFrame([{"isin": DEM, "ex_date": EX["demerger"], "factor": 0.85, "source": "prevclose", "prior_close": 1000.0, "adj_prev_close": 850.0, "bonus_factor": float("nan")},
                  {"isin": SPL, "ex_date": EX["split"], "factor": 0.2, "source": "purpose", "prior_close": float("nan"), "adj_prev_close": float("nan"), "bonus_factor": 1.0}]
                 ).to_parquet(root / "corporate_actions" / "factors.parquet", index=False)
    pd.DataFrame([{"isin": DIV, "ex_date": EX["dividend"], "dividend_per_share": 12.5}]).to_parquet(root / "dividends" / "dividends.parquet", index=False)


def _price(isin: str, k: int, d: date) -> Optional[float]:
    g = 1.001 ** k
    if isin == SPL:
        return 1000.0 * g * (0.2 if d >= EX["split"] else 1.0)
    if isin == BON:
        return 500.0 * g * (0.5 if d >= EX["bonus"] else 1.0)
    if isin == DIV:
        return 800.0 * g - (12.5 if d >= EX["dividend"] else 0.0)
    if isin == ALI:
        return 300.0 * g if d < EX["alias"] else None
    if isin == ALI2:
        return 300.0 * g if d >= EX["alias"] else None
    if isin == DEM:
        return 1000.0 * g * (0.85 if d >= EX["demerger"] else 1.0)
    if isin == MRG:
        return 300.0 * g if d < EX["merger"] else None
    if isin == MRG2:
        return 200.0 * g if d >= EX["merger"] else None
    if isin == LFT:
        return 100.0 * g
    return None


def build(workdir: Path):
    """(con, data_root, pm_dir): a system account on the synthetic market. Sets PFLAB_PM_DIR for the process (the caller restores it)."""
    import os
    from pflab.ledger import events as ev, system
    from pflab.paper import book
    from pflab.pm import store
    pm, root = Path(workdir) / "pm", Path(workdir) / "data"
    pm.mkdir(parents=True, exist_ok=True)
    os.environ["PFLAB_PM_DIR"] = str(pm)
    write_feed(root)
    con = store.connect(pm / "ledger.duckdb")
    names = {SPL: "SPLCO", BON: "BONCO", DIV: "DIVCO", ALI: "ALICO", ALI2: "ALICO", DEM: "DEMCO", MRG: "MRGCO", MRG2: "MRGCO", LFT: "LFTCO"}
    for isin, sym in names.items():
        con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, 'synthetic', now())",
                    [isin, sym, f"{sym} Limited"])
    con.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha')")
    lots = [(SPL, date(2023, 5, 2), 60, 700.0), (SPL, date(2025, 1, 3), 40, 900.0), (BON, date(2024, 2, 1), 100, 400.0), (DIV, date(2024, 3, 1), 200, 700.0), (ALI, date(2022, 6, 6), 50, 300.0),
            (DEM, date(2024, 8, 1), 30, 600.0), (MRG, date(2023, 9, 4), 40, 250.0), (LFT, date(2025, 2, 3), 10, 90.0)]
    log = ev.EventLog()
    log.append(ev.Event(kind="deposit", account_id="ZER", date=date(2022, 1, 1), amount=5_000_000.0))
    for isin, d, q, px in lots:
        log.append(ev.Event(kind="buy", account_id="ZER", date=d, isin=isin, qty=float(q), price=px))
    ev.save(con, log, NOW)
    for k, d in enumerate(DAYS):
        for isin in names:
            p = _price(isin, k, d)
            if p:
                con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d, p])
    con.execute("INSERT INTO instrument_alias VALUES (?, ?, ?)", [ALI, ALI2, EX["alias"]])
    system.switch(con, pm, SEED, NOW)
    book.seed(con, SEED, NOW)
    return con, root, pm


def _lots(con, isin: str) -> List[tuple]:
    return con.execute("SELECT acq_date, qty, cost_per_unit FROM lots WHERE account_id='SYSBROKER' AND isin=? AND qty > 1e-9 ORDER BY acq_date, lot_id", [isin]).fetchall()


def _value(con, d: date) -> float:
    return float(con.execute("SELECT value FROM paper_days WHERE day=?", [d]).fetchone()[0])


def run_synthetic(workdir: Path, log: bool = True) -> dict:
    import os
    from pflab.ledger import corporate_actions as ca, system
    from pflab.paper import book, corp
    from pflab.pm import store
    old_env = {k: os.environ.get(k) for k in ("PFLAB_PM_DIR", "PFLAB_DATA_DIR")}
    try:
        con, root, pm = build(Path(workdir))
        os.environ["PFLAB_DATA_DIR"] = str(root)
        before = {i: _lots(con, i) for i in (SPL, BON, DIV, ALI, DEM, MRG)}
        cash0 = book.cash(con, SEED)
        # a human-entered merger with a ratio (the feed carries none: 1.5 new units of MRG2 per old unit), entered on its day like any event
        import dataclasses
        mrg = dataclasses.replace(ca.merger(MRG, EX["merger"], MRG2, 1.5), ref=corp.ref("merger", MRG, EX["merger"]))
        day_before = max(d for d in DAYS if d < EX["merger"])
        out = book.catch_up(con, day_before, datetime.combine(day_before, datetime.min.time()) + timedelta(hours=21))
        system.append(con, [mrg], NOW)
        out2 = book.catch_up(con, DAYS[-1], datetime(2026, 12, 31, 21, 0))
        out = {"corporate_actions": out["corporate_actions"] + out2["corporate_actions"]}
        kinds = [(a["kind"], a["isin"]) for a in out["corporate_actions"] if a["kind"] != "error"]
        errors = [a for a in out["corporate_actions"] if a["kind"] == "error"]
        c: Dict[str, object] = {}
        # split
        spl = _lots(con, SPL)
        c["split: quantity x5, lot dates kept"] = [(l[0], round(l[1], 6)) for l in spl] == [(date(2023, 5, 2), 300.0), (date(2025, 1, 3), 200.0)]
        c["split: total cost unchanged"] = abs(sum(l[1] * l[2] for l in spl) - sum(l[1] * l[2] for l in before[SPL])) < 0.01
        c["split: applied once (feed listed it twice)"] = kinds.count(("split", SPL)) == 1
        c["split: the pre-start action was not applied"] = con.execute("SELECT count(*) FROM events WHERE ref=?", [corp.ref("split", SPL, OLD_SPLIT)]).fetchone()[0] == 0
        # bonus
        bon = _lots(con, BON)
        c["bonus: old lot untouched, new nil-cost lot at the ex-date"] = (len(bon) == 2 and bon[0][:2] == (date(2024, 2, 1), 100.0) and bon[1][0] == EX["bonus"] and bon[1][1] == 100.0 and bon[1][2] == 0.0)
        # dividend
        got = con.execute("SELECT coalesce(sum(amount),0) FROM cash_ledger WHERE account_id='SYSBROKER' AND kind='dividend' AND ref=?", [DIV]).fetchone()[0]
        c["dividend: Rs 12.5 x 200 credited to cash and logged"] = abs(got - 2500.0) < 0.01 and con.execute("SELECT count(*) FROM income WHERE isin=? AND kind='dividend'", [DIV]).fetchone()[0] == 1
        # isin change through instrument_alias
        ali = _lots(con, ALI2)
        c["isin change: lots re-keyed through instrument_alias, date and cost kept"] = (len(_lots(con, ALI)) == 0 and [(l[0], l[1], round(l[2], 6)) for l in ali] == [(date(2022, 6, 6), 50.0, 300.0)])
        # demerger as a price-drop credit
        dem = _lots(con, DEM)
        credit = con.execute("SELECT coalesce(sum(amount),0) FROM cash_ledger WHERE account_id='SYSBROKER' AND kind='corp_action' AND ref=?", [DEM]).fetchone()[0]
        c["demerger: cash for the price drop, cost scaled by the factor, date kept"] = (abs(credit - 30 * 150.0) < 0.01 and dem[0][0] == date(2024, 8, 1) and abs(dem[0][2] - 600.0 * 0.85) < 1e-6)
        # merger with a ratio
        m2 = _lots(con, MRG2)
        c["merger: units x1.5, cost and date carried to the new ISIN"] = (len(_lots(con, MRG)) == 0 and [(l[0], round(l[1], 6), round(l[2] * l[1], 4)) for l in m2] == [(date(2023, 9, 4), 60.0, 10000.0)])
        # buy-back / rights are left alone and said
        c["buy-back: left alone and reported"] = any(x["isin"] == LFT for x in corp.apply_due(con, DAYS[-1], NOW)["left"]) and len(_lots(con, LFT)) == 1
        # value continuity at each ex-date (an unapplied split would cut the book by ~10%)
        worst = 0.0
        for name, ex in EX.items():
            prev = max(d for d in DAYS if d < ex)
            worst = max(worst, abs(_value(con, ex) / _value(con, prev) - 1.0))
        c["the book's value does not jump at any ex-date (largest one-day move)"] = worst < 0.02
        # idempotence
        n_ev, n_lots, cash_end = con.execute("SELECT count(*) FROM events").fetchone()[0], con.execute("SELECT count(*), sum(qty) FROM lots").fetchone(), book.cash(con)
        again = corp.apply_due(con, DAYS[-1], NOW)
        book.catch_up(con, DAYS[-1], datetime(2027, 1, 2, 21, 0))
        c["idempotent: a second run adds no event, lot or cash"] = (again["applied"] == [] and con.execute("SELECT count(*) FROM events").fetchone()[0] == n_ev
                                                                    and tuple(con.execute("SELECT count(*), sum(qty) FROM lots").fetchone()) == tuple(n_lots) and abs(book.cash(con) - cash_end) < 1e-9)
        c["the account still replays (no overdraft, no lot error)"] = system.verify(con)["checks"]["no other lot owner"] is True
        c["no error raised by the hook"] = not errors
        # a late-arriving action (the feed learns of it after the days were marked)
        late = _late(con, root)
        c["late action: applied, the marked days re-marked, value continuous"] = late
        ok = all(bool(v) for v in c.values())
        res = {"kind": "synthetic", "ok": ok, "checks": {k: bool(v) for k, v in c.items()}, "applied": sorted(set(k for k, _ in kinds)), "worst_one_day_move": round(worst, 4), "errors": errors}
        if log:
            _log(con, "synthetic", ok, res)
        return res
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _late(con, root: Path) -> bool:
    """Teach the feed a 1:2 bonus on BON a week after the fact (ex-date inside the marked days) and apply it."""
    from pflab.paper import corp
    rows = json.loads((root / "corporate_actions" / "raw" / "2026.json").read_text(encoding="utf-8"))
    rows.append(_row(DIV, "DIVCO", LATE, "Bonus 1:4", fv="10"))
    (root / "corporate_actions" / "raw" / "2026.json").write_text(json.dumps(rows), encoding="utf-8")
    day = LATE
    q0 = sum(l[1] for l in _lots(con, DIV))
    v_before = _value(con, day)
    res = corp.apply_due(con, DAYS[-1], NOW, root=root)
    q1 = sum(l[1] for l in _lots(con, DIV))
    return bool(res.get("remarked")) and abs(q1 - q0 * 1.25) < 1e-6 and abs(_value(con, day) - v_before) > 0 and json.loads(
        con.execute("SELECT holdings_json FROM paper_days WHERE day=?", [DAYS[-1]]).fetchone()[0]).get(DIV) == q1


def _log(con, kind: str, ok: bool, res: dict) -> None:
    from pflab.pm.store import next_id
    con.execute("INSERT INTO verify_book_s79 VALUES (?,?,?,?,?,?,?)", [next_id(con, "verify_book_s79", "run_id"), "IN", datetime.now(), kind, bool(ok), json.dumps(res, default=str)[:20000], None])


# --- the top-up ---------------------------------------------------------------------------------------------------------------------------

def run_topup(workdir: Path, log: bool = True) -> dict:
    import os
    from pflab.hq import missions
    from pflab.paper import allocation, book, cadence, funds
    old_env = {k: os.environ.get(k) for k in ("PFLAB_PM_DIR", "PFLAB_DATA_DIR")}
    try:
        con, root, pm = build(Path(workdir))
        os.environ["PFLAB_DATA_DIR"] = str(root)
        (pm / "app").mkdir(exist_ok=True)
        t = allocation.propose_allocation(con, {"equity": 70, "gold": 10, "international": 5, "cash": 15}, "x" * 60, datetime(2026, 10, 29, 9, 0))
        allocation.review_target(con, t["target_id"], "approve", "ok", datetime(2026, 10, 29, 9, 5))
        missions.create(con, datetime(2026, 10, 29, 10, 0), "Paper portfolio: review", pm_dir=pm, origin="paper")
        day = DAYS[8]
        book.catch_up(con, DAYS[7], datetime.combine(DAYS[7], datetime.min.time()) + timedelta(hours=21))
        c: Dict[str, object] = {}
        v_before = _value(con, DAYS[7])
        bank0 = funds.bank_cash(con)
        r = funds.topup(con, 40_000, "the investor", day, datetime.combine(day, datetime.min.time()) + timedelta(hours=9))
        c["top-up is cash in the bank"] = r["added"] == 40_000 and abs(funds.bank_cash(con) - bank0 - 40_000) < 1e-6
        book.catch_up(con, day, datetime.combine(day, datetime.min.time()) + timedelta(hours=21))
        flows = con.execute("SELECT flows FROM paper_days WHERE day=?", [day]).fetchone()[0]
        c["flagged as outside money in paper_days.flows"] = abs(flows - 40_000) < 1e-6
        lv = dict(cadence.level_path(con))
        c["the return maths excludes it (level path moves by the market only)"] = abs(lv[day] / lv[DAYS[7]] - 1.0) < 0.01 and _value(con, day) - v_before > 39_000
        now = datetime.combine(day, datetime.min.time()) + timedelta(hours=21)
        why = allocation.reasons(con, now)
        c["the next look is told to deploy it (cash above its target class weight)"] = any("top-up" in w and "deploy" in w for w in why)
        d = allocation.drift(book.holdings(con, day), allocation.active_target(con))
        cash_line = next(x for x in d["classes"] if x["name"] == "cash")
        c["cash is above its target weight before deploying"] = cash_line["gap_pct"] < -allocation.BAND_PCT
        missions.create(con, now + timedelta(minutes=5), "Paper portfolio: deploy the top-up", pm_dir=pm, origin="paper")
        c["once the team has looked, the reason is spent"] = not any("top-up" in w for w in allocation.reasons(con, now + timedelta(hours=1)))
        # the deploy path: orders sized from the gap (as the manager's sizing does under the rails) move cash to the band
        gap = [x for x in allocation.trade_toward(book.holdings(con, day), allocation.active_target(con))["add"] if x["name"] == "equity"]
        if gap:                                                                    # the names with room under the 10% company rail (the manager's sizing would cut the rest)
            for isin in (BON, DEM, LFT):
                book.place(con, datetime.combine(DAYS[9], datetime.min.time()) + timedelta(hours=10), None, isin, "buy", amount=min(gap[0]["gap_rupees"], 0.095 * _value(con, day)))
        book.catch_up(con, DAYS[10], datetime.combine(DAYS[10], datetime.min.time()) + timedelta(hours=21))
        d2 = allocation.drift(book.holdings(con, DAYS[10]), allocation.active_target(con))
        c2 = next(x for x in d2["classes"] if x["name"] == "cash")
        c["deploying moves cash toward its target"] = c2["actual_pct"] < cash_line["actual_pct"] - 5.0
        c["the deployed buys are not outside money"] = con.execute("SELECT coalesce(sum(flows),0) FROM paper_days WHERE day > ?", [day]).fetchone()[0] == 0
        ok = all(bool(v) for v in c.values())
        res = {"kind": "topup", "ok": ok, "checks": {k: bool(v) for k, v in c.items()}, "cash_pct_before": cash_line["actual_pct"], "cash_pct_after": c2["actual_pct"], "reasons": why}
        if log:
            _log(con, "topup", ok, res)
        return res
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# --- the real corporate actions ---------------------------------------------------------------------------------------------------------

def scan_real(con, root: Optional[Path] = None, start: Optional[date] = None, upto: Optional[date] = None) -> dict:
    """Every split, bonus, price-drop factor and dividend of the REAL feed (the workshop's data) on the names the book held, in (start, upto]: is it in the ledger?"""
    import dataclasses
    from pflab.paper import book, corp
    start = start or book.started(con)
    upto = upto or date.max
    held = corp.held_isins(con)
    src = corp.restated(con, corp.sources(root), held)
    raw, fac, dv = src["raw"], src["factors"], src["dividends"]
    out: Dict[str, object] = {"window": [str(start), str(upto) if upto != date.max else "latest"], "names": len(held), "stale_feed_isins_mapped": src["isin_map"]}
    from pflab.ledger import corporate_actions as ca
    sel = raw[raw["isin"].isin(held) & (raw["ex_date"] > start) & (raw["ex_date"] <= upto)]
    want_share = [e for e in ca.from_nse_feed(sel, held, since=start + timedelta(days=1))]
    out["feed_split_bonus"] = len(want_share)
    in_ledger = {r[0] for r in con.execute("SELECT ref FROM events WHERE ref LIKE 'corp:%'").fetchall()}
    miss = [e for e in want_share if dataclasses.replace(e, ref=corp.ref(e.params["action"], e.isin, e.date)).ref not in in_ledger]
    out["split_bonus_missing"] = [{"isin": e.isin, "ex": str(e.date), "kind": e.params["action"]} for e in miss]
    d = dv[dv["isin"].isin(held) & (dv["ex_date"] > start) & (dv["ex_date"] <= upto)]
    pre = fac[(fac["source"].fillna("purpose") == "prevclose") & fac["isin"].isin(held) & (fac["ex_date"] > start) & (fac["ex_date"] <= upto)]
    pre_keys = {(r.isin, r.ex_date) for r in pre.itertuples(index=False)}
    out["feed_dividends"] = int(len(d))
    holders = 0
    dmiss = []
    for r in d.itertuples(index=False):
        if (r.isin, r.ex_date) in pre_keys:
            continue                                                # the price-drop factor carries it (the collector's rule: one per date)
        if corp.ref("dividend", r.isin, r.ex_date) in in_ledger:
            holders += 1
        else:
            qty = corp._qty_before(__import__("pflab.ledger.events", fromlist=["x"]).load(con), r.isin, r.ex_date, with_actions=True)
            if qty > 1e-9:
                dmiss.append({"isin": r.isin, "ex": str(r.ex_date), "dps": float(r.dividend_per_share), "qty": qty})
    out["dividends_credited"] = holders
    out["dividends_missing"] = dmiss
    out["feed_price_drop_factors"] = int(len(pre))
    out["price_drop_applied"] = sum(1 for r in pre.itertuples(index=False) if corp.ref("cash_credit", r.isin, r.ex_date) in in_ledger or corp.ref("split", r.isin, r.ex_date) in in_ledger)
    out["events_in_ledger"] = {k: sum(1 for x in in_ledger if x.startswith(f"corp:{k}:")) for k in ("split", "bonus", "dividend", "cash_credit", "cash_in_lieu", "isin_change")}
    unr = []
    for r in sel.itertuples(index=False):
        if corp._UNRATIOED.search(str(r.subject)) and (r.isin, r.ex_date) not in pre_keys and corp.ref("isin_change", r.isin, r.ex_date) not in in_ledger:
            unr.append({"symbol": r.symbol, "ex": str(r.ex_date), "subject": str(r.subject)})
    out["demergers_or_mergers_without_a_ratio"] = unr          # the feed gives no ratio and NSE's PREVCLOSE is not adjusted for them: the book cannot value what the holder received
    out["ok"] = not miss and not dmiss
    return out


REHEARSAL = {"HINDUNILVR": "INE030A01027", "ITC": "INE154A01025", "LT": "INE018A01030", "MARUTI": "INE585B01010", "ASIANPAINT": "INE021A01026", "NESTLEIND": "INE239A01024",
             "GOLDBEES": "INF204KB17I5", "NIFTYBEES": "INF204KB14I2"}
QTY = {"HINDUNILVR": 120, "ITC": 600, "LT": 60, "MARUTI": 15, "ASIANPAINT": 40, "NESTLEIND": 10}


def run_real(workdir: Path, root: Optional[Path] = None, start: date = date(2024, 2, 1), upto: Optional[date] = None, log: bool = True) -> dict:
    """The rehearsal profile's names on their RAW closes (not the adjusted panel) from `start` to the data's last session; the system book catches up through every real action."""
    import os
    from pflab import _duck
    from pflab.data import bhavcopy, data_dir
    from pflab.ledger import events as ev, system
    from pflab.paper import book
    from pflab.pm import store
    root = Path(root or data_dir())
    old_env = {k: os.environ.get(k) for k in ("PFLAB_PM_DIR", "PFLAB_DATA_DIR")}
    try:
        pm = Path(workdir) / "pm"
        pm.mkdir(parents=True, exist_ok=True)
        os.environ["PFLAB_PM_DIR"], os.environ["PFLAB_DATA_DIR"] = str(pm), str(root)
        con = store.connect(pm / "ledger.duckdb")
        last = upto or max(date.fromisoformat(p.stem) for p in (root / "bhavcopy" / str(date.today().year)).glob("*.parquet"))
        files = bhavcopy.bhav_files(root, start, last)
        isins = list(REHEARSAL.values())
        px = _duck.sql("select date, isin, close from read_parquet([" + ",".join(repr(f) for f in files) + "], union_by_name=true) where isin in (" + ",".join(repr(i) for i in isins)
                       + f") and series='EQ' and close > 0 and date >= DATE '{start.isoformat()}' and date <= DATE '{last.isoformat()}'").to_df()
        px["date"] = pd.to_datetime(px["date"]).dt.date
        for sym, isin in REHEARSAL.items():
            con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, 'synthetic rehearsal', now())",
                        [isin, "etf" if "BEES" in sym else "equity", "LISTED_NONEQUITY" if "BEES" in sym else "EQUITY", sym, sym])
        for r in px.itertuples(index=False):
            con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [r.isin, r.date, float(r.close)])
        con.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha')")
        first = px.groupby("isin")["date"].min()
        log_ = ev.EventLog()
        log_.append(ev.Event(kind="deposit", account_id="ZER", date=start - timedelta(days=30), amount=50_000_000.0))
        for sym, q in QTY.items():
            isin = REHEARSAL[sym]
            d0 = first[isin]
            p0 = float(px[(px["isin"] == isin) & (px["date"] == d0)]["close"].iloc[0])
            log_.append(ev.Event(kind="buy", account_id="ZER", date=start - timedelta(days=1), isin=isin, qty=float(q), price=p0, ref="SYNTH-" + sym))
        ev.save(con, log_, datetime.now())
        seed_day = px["date"].min()
        system.switch(con, pm, seed_day, datetime.now())
        book.seed(con, seed_day, datetime.now())
        t0 = datetime.now()
        res = book.catch_up(con, last, datetime.combine(last, datetime.min.time()) + timedelta(hours=21))
        scan = scan_real(con, root, seed_day, last)
        applied = [a for a in res["corporate_actions"] if a["kind"] != "error"]
        errors = [a for a in res["corporate_actions"] if a["kind"] == "error"]
        # the largest one-day move of the book across the window: an unapplied action shows up here
        vals = [r[0] for r in con.execute("SELECT value FROM paper_days ORDER BY day").fetchall()]
        worst = max((abs(b / a - 1.0) for a, b in zip(vals, vals[1:]) if a > 0), default=0.0)
        out = {"kind": "real", "ok": bool(scan["ok"] and not errors), "sessions": len(res["days"]), "seconds": round((datetime.now() - t0).total_seconds(), 1), "applied": len(applied),
               "by_kind": {k: sum(1 for a in applied if a["kind"] == k) for k in sorted({a["kind"] for a in applied})}, "scan": scan, "errors": errors[:3],
               "largest_one_day_move_of_the_book": round(worst, 4), "dividends_rupees": round(sum(a.get("rupees", 0.0) for a in applied if a["kind"] == "dividend"), 2)}
        if log:
            _log(con, "real", out["ok"], out)
        return out
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def status(con) -> dict:
    """The latest verification runs (what the tool shows): kind, when, ok and which checks failed."""
    try:
        rows = con.execute("SELECT kind, ran_at, ok, checks_json FROM verify_book_s79 ORDER BY run_id DESC LIMIT 6").fetchall()
    except Exception:
        return {"runs": []}
    out = []
    for k, at, ok, cj in rows:
        j = json.loads(cj or "{}")
        out.append({"kind": k, "at": str(at)[:16], "ok": bool(ok), "failed": [n for n, v in (j.get("checks") or {}).items() if not v]})
    return {"runs": out}


if __name__ == "__main__":
    import argparse
    import tempfile
    ap = argparse.ArgumentParser(description="verify the system's own book against corporate actions and top-ups")
    ap.add_argument("what", choices=("synthetic", "topup", "real"))
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--data", default=None)
    ap.add_argument("--start", default="2024-02-01")
    a = ap.parse_args()
    wd = Path(a.workdir or tempfile.mkdtemp(prefix="verify_book_"))
    if a.what == "synthetic":
        r = run_synthetic(wd)
    elif a.what == "topup":
        r = run_topup(wd)
    else:
        r = run_real(wd, Path(a.data) if a.data else None, date.fromisoformat(a.start))
    print(json.dumps(r, indent=1, default=str))
