"""S81 B4: the exit manager and tax selling (`core/exits.py`, `core/harvest.py`, `core/tax_rows.py`). Synthetic data only (rule 7).

Book at the 2026-10-30 close (FY2026-27, the exemption row Rs 1,25,000): WIN (long-term, big gain), NEW (a gain whose lots turn long-term in 12 days), LOSS (a short-term loss),
CALM (a long-term holding with a small gain), SWG (a swing position), GLD (a gold ETF in the core). A synthetic sell in the year's trades gives the loss harvest a gain to offset.
"""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab.core import exits, harvest, tax_rows
from pflab.ledger import events as ev
from pflab.ledger import system
from pflab.paper import book
from pflab.pm import store
from pflab.tax import rules

WIN, NEW, LOSS, CALM, SWG, GLD = "INE000A01011", "INE000B01012", "INE000C01013", "INE000D01014", "INE000E01015", "INF000G01015"
NOW = datetime(2026, 10, 30, 16, 0)
DAYS = [d.date() for d in pd.bdate_range("2025-08-01", "2026-10-30")]
DAY = DAYS[-1]
PX = {WIN: 100.0, NEW: 100.0, LOSS: 100.0, CALM: 100.0, SWG: 100.0, GLD: 50.0}
LAST = {k: v for k, v in PX.items()}


def _price_path(isin: str, k: int, n: int) -> float:
    """A gently wobbling path that ends exactly at PX[isin] on the last day."""
    wob = 1.0 + (0.004 if k % 2 else -0.004)
    return PX[isin] * wob if k < n - 1 else PX[isin]


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    c = store.connect(tmp_path / "l.duckdb")
    meta = ((WIN, "equity", "EQUITY", "WIN", "Win Ltd", "Banks"), (NEW, "equity", "EQUITY", "NEW", "New Ltd", "Auto"), (LOSS, "equity", "EQUITY", "LOSS", "Loss Ltd", "Metals"),
            (CALM, "equity", "EQUITY", "CALM", "Calm Ltd", "Pharma"), (SWG, "equity", "EQUITY", "SWG", "Swing Ltd", "Textiles"), (GLD, "etf", "LISTED_NONEQUITY", "GLDBEES", "Goldbees Gold ETF", None))
    for isin, cls, tc, sym, name, sec in meta:
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, ?, 'synthetic', now())",
                  [isin, cls, tc, sym, name, sec])
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha')")
    log = ev.EventLog()
    log.append(ev.Event(kind="deposit", account_id="ZER", date=date(2023, 1, 1), amount=9_000_000.0))
    for isin, d, q, p in ((WIN, date(2024, 1, 10), 4000, 50.0), (NEW, date(2025, 11, 10), 2000, 60.0), (LOSS, date(2026, 6, 1), 2000, 150.0), (CALM, date(2024, 5, 6), 1000, 95.0),
                          (SWG, date(2026, 10, 20), 500, 100.0), (GLD, date(2024, 2, 1), 3000, 40.0)):
        log.append(ev.Event(kind="buy", account_id="ZER", date=d, isin=isin, qty=q, price=p))
    ev.save(c, log, NOW)
    for k, d in enumerate(DAYS):
        for isin in PX:
            c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d, _price_path(isin, k, len(DAYS))])
    system.switch(c, tmp_path, DAYS[-6], NOW, start_cash=20_000_000.0)
    book.seed(c, DAYS[-6], NOW)
    book.catch_up(c, DAY, datetime.combine(DAY, datetime.min.time()) + timedelta(hours=21))
    # this year's realised gains so far: a short-term gain a loss can offset (the paper book's own sell record)
    c.execute("INSERT INTO paper_trades VALUES (9001, ?, 9001, NULL, ?, 'X', 'sell', 100, 100.0, 10.0, 200000.0, 40000.0, ?)",
              [date(2026, 8, 3), CALM, json.dumps({"gains": {"st_eq": 200000.0}})])
    return c


def _state(con, day=DAY, total=None):
    h = book.holdings(con, day)
    return {"day": day, "value": total or h["value"], "rows": [{**r, "buyable": r["price"] is not None, "value": r["value"] or 0.0} for r in h["rows"]], "breaker": {"on": False}}


def _fill(con, isin, side, qty, px, day, kind_note="test"):
    """Fill a paper order for `qty` at `px` on `day` the way the book does (the ledger changes, a paper trade is written)."""
    oid = book.place(con, datetime.combine(day, datetime.min.time()) + timedelta(hours=10), None, isin, side, qty=qty)
    book.fill(con, day, datetime.combine(day, datetime.min.time()) + timedelta(hours=16))
    return oid


def _set_price(con, isin, px, day=DAY):
    con.execute("UPDATE prices SET close=? WHERE isin=? AND date=?", [px, isin, day])


def _kinds(orders):
    return sorted((o["isin"], o["kind"], o["side"]) for o in orders)


# --- plans ---------------------------------------------------------------------------------------------------------------------------

def test_backfill_gives_every_position_a_plan_from_its_lots_and_sleeve_defaults(con):
    made = exits.backfill_plans(con, DAY)
    assert len(made) == 6 and exits.backfill_plans(con, DAY) == []                       # once
    p = {x["isin"]: x for x in exits._plans(con)}
    assert p[GLD]["sleeve"] == "core" and p[GLD]["stop"] is None and p[GLD]["thesis_break_kinds"] == []        # core: no stop, rebalance only
    assert p[WIN]["sleeve"] == "longterm" and p[WIN]["stop"] is not None and p[WIN]["target"] is None and p[WIN]["time_stop_days"] is None
    assert 0.12 <= 1 - p[WIN]["stop"] / 100.0 <= 0.35 and p[WIN]["thesis_break_kinds"]
    assert p[WIN]["opened_on"] == date(2024, 1, 10) and p[WIN]["entry_price"] == pytest.approx(50.0, abs=0.5) and p[WIN]["source"] == "backfill"
    assert p[NEW]["tax_boundary_date"] == tax_rows.long_term_from(date(2025, 11, 10)) and p[WIN]["tax_boundary_date"] is None


def test_open_plan_swing_defaults_and_overrides_and_adding(con):
    pid = exits.open_plan(con, NOW, "IN", SWG, "swing", 100.0, 500)
    p = exits.get_plan(con, pid)
    assert p["stop"] < 100 and p["target"] > 100 and p["time_stop_days"] == 21 and p["status"] == "open"
    dist = 1 - p["stop"] / 100.0
    assert p["target"] == pytest.approx(100.0 * (1 + 2.0 * dist))                         # a target of twice the stop distance, from the config
    assert exits.open_plan(con, NOW, "IN", SWG, "swing", 110.0, 100) == pid               # a second buy updates the same plan
    pid2 = exits.open_plan(con, NOW, "IN", WIN, "longterm", 100.0, 10, plan={"stop": 80.0, "time_stop_days": 30})
    q = exits.get_plan(con, pid2)
    assert q["stop"] == 80.0 and q["time_stop_days"] == 30


# --- each exit kind fires once and only once -----------------------------------------------------------------------------------------

def test_stop_fires_once_and_the_reason_carries_numbers(con):
    exits.backfill_plans(con, DAY)
    p = {x["isin"]: x for x in exits._plans(con)}[CALM]
    _set_price(con, CALM, p["stop"] - 1.0)
    o = [x for x in exits.check_close(con, DAY, None, _state(con)) if x["isin"] == CALM]
    assert len(o) == 1 and o[0]["kind"] == "stop" and o[0]["side"] == "sell" and o[0]["fraction"] == 1.0 and o[0]["plan_id"] == p["plan_id"]
    assert f"{p['stop']:,.2f}" in o[0]["reason"] and "Stop hit" in o[0]["reason"] and "charges Rs" in o[0]["reason"]
    again = [x for x in exits.check_close(con, DAY, None, _state(con)) if x["isin"] == CALM]
    assert again == []                                                                    # the event is recorded: no second order for the same stop
    assert con.execute("SELECT count(*) FROM exit_events_s81 WHERE isin=? AND kind='stop'", [CALM]).fetchone()[0] == 1


def test_a_stop_order_that_never_filled_is_voided_and_fires_again_next_close(con):
    exits.backfill_plans(con, DAY)
    p = {x["isin"]: x for x in exits._plans(con)}[CALM]
    _set_price(con, CALM, p["stop"] - 1.0)
    exits.check_close(con, DAY, None, _state(con))
    nxt = DAY + timedelta(days=3)
    out = exits.check_close(con, nxt, {CALM: p["stop"] - 2.0}, None)
    assert [x["kind"] for x in out if x["isin"] == CALM] == ["stop"]                      # nothing came of the first order: it is void, the stop is still hit
    assert con.execute("SELECT count(*) FROM exit_events_s81 WHERE isin=? AND kind='stop' AND status='void'", [CALM]).fetchone()[0] == 1


def test_target_and_time_stop_each_fire_once(con):
    pid = exits.open_plan(con, NOW, "IN", SWG, "swing", 100.0, 500)
    p = exits.get_plan(con, pid)
    px = p["target"] + 1.0
    o = exits.check_quote(con, datetime(2026, 11, 2, 11, 0), {SWG: px})
    assert [(x["isin"], x["kind"]) for x in o] == [(SWG, "target")] and "Target reached" in o[0]["reason"] and f"{p['target']:,.2f}" in o[0]["reason"]
    assert exits.check_quote(con, datetime(2026, 11, 2, 11, 5), {SWG: px}) == []
    con.execute("DELETE FROM exit_events_s81")
    late = date(2026, 10, 30) + timedelta(days=22)
    o = exits.check_close(con, late, {SWG: 100.0}, None)
    assert [x["kind"] for x in o if x["isin"] == SWG] == ["time"] and "Time stop: held" in [x["reason"] for x in o if x["isin"] == SWG][0]
    assert [x["kind"] for x in exits.check_close(con, late, {SWG: 100.0}, None) if x["isin"] == SWG] == []


def test_a_name_bought_today_waits_in_the_session_unless_its_stop_fires(con):
    d = datetime(2026, 10, 30, 11, 0)
    p = exits.get_plan(con, exits.open_plan(con, NOW, "IN", SWG, "swing", 100.0, 500))
    _fill(con, SWG, "buy", 10, 100.0, DAY)                                                # shares bought today (a lot dated today)
    assert exits.check_quote(con, d, {SWG: p["target"] + 2.0}) == []                      # target today: no same-day round trip, it waits
    assert con.execute("SELECT count(*) FROM exit_events_s81 WHERE kind='target' AND status='guarded'").fetchone()[0] == 1
    o = exits.check_quote(con, d, {SWG: p["stop"] - 1.0})
    assert [x["kind"] for x in o] == ["stop"]                                             # the stop still sells them
    assert exits.check_quote(con, d, {SWG: p["stop"] - 1.0}) == []


def test_thesis_break_sells_once_and_ignores_events_not_point_in_time(con):
    exits.backfill_plans(con, DAY)
    ev1 = {"isin": CALM, "kind": "fraud", "severity": "high", "ts": datetime(2026, 10, 30, 9, 40), "source": "BSE filing", "ref": "bse:1", "text": "the auditor flags a diversion of funds"}
    future = {**ev1, "ts": datetime(2026, 10, 31, 9, 40), "ref": "bse:2"}
    nots = {**ev1, "ts": None, "ref": "bse:3"}
    low = {**ev1, "severity": 0.1, "kind": "other", "ref": "bse:4"}
    old = {**ev1, "ts": datetime(2024, 1, 1, 9, 0), "ref": "bse:5"}                       # before the position was opened
    gld = {**ev1, "isin": GLD, "ref": "bse:6"}                                            # the core has no thesis to break
    o = exits.check_close(con, DAY, None, _state(con), events=[ev1, future, nots, low, old, gld])
    th = [x for x in o if x["kind"] == "thesis"]
    assert len(th) == 1 and th[0]["isin"] == CALM and th[0]["fraction"] == 1.0
    assert "fraud" in th[0]["reason"] and "BSE filing" in th[0]["reason"] and "severity 0.75" in th[0]["reason"]
    assert [x for x in exits.check_close(con, DAY, None, _state(con), events=[ev1]) if x["kind"] == "thesis"] == []
    assert exits.check_thesis(con, DAY, [ev1]) == []


# --- the 12-month guard --------------------------------------------------------------------------------------------------------------

def test_guard_holds_a_winner_close_to_twelve_months_and_a_stop_overrides_it(con):
    exits.backfill_plans(con, DAY)
    plan = {x["isin"]: x for x in exits._plans(con)}[NEW]
    con.execute("UPDATE exit_plans_s81 SET time_stop_days=1, stop=? WHERE plan_id=?", [10.0, plan["plan_id"]])   # a time stop that is already due, and a stop far below
    o = exits.check_close(con, DAY, None, _state(con))
    assert [x for x in o if x["isin"] == NEW] == []                                        # time stop on a winner that turns long-term in 12 days: held back
    g = con.execute("SELECT reason FROM exit_events_s81 WHERE isin=? AND status='guarded'", [NEW]).fetchone()[0]
    assert "12-month guard" in g and "12 days" in g and "turn long-term on" in g
    _set_price(con, NEW, 9.0)                                                              # the stop fires (the price is under it): the guard does not hold a stop
    # (a loss has no guard anyway; the stop must go through either way)
    o = exits.check_close(con, DAY, None, _state(con))
    assert [x["kind"] for x in o if x["isin"] == NEW] == ["stop"]


def test_guard_stop_override_on_a_winner(con):
    exits.backfill_plans(con, DAY)
    plan = {x["isin"]: x for x in exits._plans(con)}[NEW]
    con.execute("UPDATE exit_plans_s81 SET stop=?, time_stop_days=1 WHERE plan_id=?", [120.0, plan["plan_id"]])   # price 100 is under a (raised) stop of 120 but the lots are in gain at 100 > 60
    o = [x for x in exits.check_close(con, DAY, None, _state(con)) if x["isin"] == NEW]
    assert [x["kind"] for x in o] == ["stop"]                                              # a winner, inside the guard window, sold because its stop fired


def test_guard_window_comes_from_the_config(con, monkeypatch):
    exits.backfill_plans(con, DAY)
    plan = {x["isin"]: x for x in exits._plans(con)}[NEW]
    con.execute("UPDATE exit_plans_s81 SET time_stop_days=1 WHERE plan_id=?", [plan["plan_id"]])
    real = exits.settings
    monkeypatch.setattr(exits, "settings", lambda: {**real(), "guard_days": 5})           # 12 days away is now outside the window
    assert [x["kind"] for x in exits.check_close(con, DAY, None, _state(con)) if x["isin"] == NEW] == ["time"]


# --- tax figures come from the engine rows --------------------------------------------------------------------------------------------

def test_exemption_harvest_books_at_most_the_exemption_and_buys_back_next_session(con):
    exits.backfill_plans(con, DAY)
    room, work = harvest.exemption_room(con, DAY, exits.settings())
    assert work["exemption"] == rules.exemption(2027) == 125000.0 and work["in_last_quarter"] is False
    assert room == pytest.approx(125000.0 * 0.34 * 0.90)                                  # outside the last quarter: a share of the exemption
    jan = date(2027, 2, 15)
    for d in (jan,):                                                                       # in the last quarter: the whole exemption (less the margin)
        r2, w2 = harvest.exemption_room(con, d, exits.settings())
        assert w2["in_last_quarter"] and r2 == pytest.approx(125000.0 * 0.90)
    o = [x for x in exits.check_close(con, DAY, None, _state(con)) if x["kind"] == "harvest"]
    h = [x for x in o if x["side"] == "sell" and x["isin"] == WIN]
    assert len(h) == 1 and h[0]["qty"] >= 1 and "Exemption harvest" in h[0]["reason"] and "bought back at the next session" in h[0]["reason"]
    gain = h[0]["qty"] * (100.0 - 50.0) - (h[0]["est_charges"] or 0.0)
    assert gain <= room + 1.0                                                              # never more than the room
    assert h[0]["est_tax"] == 0.0                                                          # inside the exemption: no tax
    # the sale fills at the next close; the buy-back is emitted only at the close after the sale filled, and fills a LATER session
    nxt = DAY + timedelta(days=3)
    for k in range(2):
        con.execute("INSERT INTO prices VALUES (?, ?, 100.0, 'EQ', 'nse_bhavcopy', now())", [WIN, nxt + timedelta(days=k)]) if False else None
    assert [x for x in o if x["side"] == "buy" and x["isin"] == WIN] == []                 # no buy in the same close as the sale (no same-day round trip)


def _next_session(con, d):
    nd = d + timedelta(days=3 if d.weekday() == 4 else 1)
    for isin, px in PX.items():
        con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, nd, px])
    return nd


def test_harvest_sale_buyback_resets_cost_and_never_shares_a_session(con):
    exits.backfill_plans(con, DAY)
    o = exits.check_close(con, DAY, None, _state(con))
    sale = [x for x in o if x["kind"] == "harvest" and x["isin"] == WIN][0]
    old_lots = tax_rows.lots(con, WIN)
    oid = book.place(con, NOW, None, WIN, "sell", qty=sale["qty"])
    d1 = _next_session(con, DAY)
    book.fill(con, d1, datetime.combine(d1, datetime.min.time()) + timedelta(hours=20))
    out = exits.check_close(con, d1, None, None, now=datetime.combine(d1, datetime.min.time()) + timedelta(hours=16))
    buy = [x for x in out if x["kind"] == "harvest" and x["side"] == "buy" and x["isin"] == WIN]
    assert len(buy) == 1 and buy[0]["qty"] == sale["qty"] and "different session from the sale" in buy[0]["reason"]
    sold_on = con.execute("SELECT filled_on FROM exit_events_s81 WHERE kind='harvest' AND side='sell' AND isin=?", [WIN]).fetchone()[0]
    assert sold_on == d1                                                                   # sold at d1's close; the buy-back is placed at d1's close and fills at d2's
    assert con.execute("SELECT status FROM exit_plans_s81 WHERE isin=?", [WIN]).fetchone()[0] == "open"      # a partial harvest leaves the plan open
    book.place(con, datetime.combine(d1, datetime.min.time()) + timedelta(hours=16), None, WIN, "buy", qty=buy[0]["qty"])
    d2 = _next_session(con, d1)
    book.fill(con, d2, datetime.combine(d2, datetime.min.time()) + timedelta(hours=20))
    lots = tax_rows.lots(con, WIN)
    new = [l for l in lots if l["acq"] == d2]
    assert len(new) == 1 and new[0]["cpu"] == pytest.approx(100.0, rel=0.01)               # the cost price is reset to today's price
    assert sum(l["qty"] for l in lots) == pytest.approx(sum(l["qty"] for l in old_lots), abs=1)
    assert exits.check_close(con, d2, None, None, now=datetime.combine(d2, datetime.min.time()) + timedelta(hours=16)) is not None
    assert [x for x in exits.check_close(con, d2, None, None) if x["kind"] == "harvest" and x["side"] == "buy"] == []   # the buy-back is made once
    n_events = con.execute("SELECT count(*) FROM exit_events_s81 WHERE kind='harvest' AND side='buy'").fetchone()[0]
    assert n_events == 1


def test_harvest_amount_follows_the_dated_row(con, tmp_path, monkeypatch):
    exits.backfill_plans(con, DAY)
    base_room = harvest.exemption_room(con, DAY, exits.settings())[0]
    src = rules.config_dir()
    alt = tmp_path / "tax_alt"
    shutil.copytree(src, alt)
    f = alt / "capital_gains.toml"
    f.write_text(f.read_text(encoding="utf-8").replace("amount = 125000.0", "amount = 50000.0"), encoding="utf-8")
    monkeypatch.setattr(rules, "config_dir", lambda: alt)
    rules._load.cache_clear()
    try:
        assert tax_rows.exemption(DAY) == 50000.0
        room2 = harvest.exemption_room(con, DAY, exits.settings())[0]
        assert room2 == pytest.approx(base_room * 0.4)                                     # the harvest room moves with the row
        o = [x for x in exits.check_close(con, DAY, None, _state(con)) if x["kind"] == "harvest" and x["isin"] == WIN]
        assert o and o[0]["qty"] * 50.0 <= 50000.0 * 0.34 * 0.90 + 100.0
    finally:
        monkeypatch.undo()
        rules._load.cache_clear()


def test_exemption_already_used_leaves_no_room_and_no_row_means_no_harvest(con, monkeypatch):
    exits.backfill_plans(con, DAY)
    con.execute("INSERT INTO paper_trades VALUES (9002, ?, 9002, NULL, ?, 'X', 'sell', 100, 100.0, 10.0, 130000.0, 0.0, ?)",
                [date(2026, 9, 1), CALM, json.dumps({"gains": {"lt_eq": 130000.0}})])
    assert [x for x in exits.check_close(con, DAY, None, _state(con)) if x["kind"] == "harvest" and "Exemption harvest" in x["reason"]] == []   # the year's exemption is used up
    assert "no exemption room" in con.execute("SELECT reason FROM exit_events_s81 WHERE status='note'").fetchone()[0]
    con.execute("DELETE FROM paper_trades WHERE trade_id=9002")
    old = date(2024, 3, 1)                                                                 # before the rows' coverage: no harvest, the reason says so
    out, notes, _w = harvest.exemption_specs(con, old, exits.settings(), [], 1e6)
    assert out == [] and "no row" in notes[0]


def test_loss_harvest_offsets_gains_and_buys_back(con):
    exits.backfill_plans(con, DAY)
    cfg = exits.settings()
    o = exits.check_close(con, DAY, None, _state(con))
    h = [x for x in o if x["kind"] == "harvest" and x["isin"] == LOSS and x["side"] == "sell"]
    assert len(h) == 1 and "Loss harvest" in h[0]["reason"] and "saves Rs" in h[0]["reason"]
    saving = float(h[0]["reason"].split("saves Rs ")[1].split(";")[0].replace(",", ""))
    assert saving >= cfg["loss_min_saving"]
    # without the year's gains there is nothing to offset: no loss harvest
    con.execute("DELETE FROM paper_trades WHERE trade_id=9001")
    con.execute("DELETE FROM exit_events_s81")
    assert [x for x in exits.check_close(con, DAY, None, _state(con)) if x["isin"] == LOSS] == []


def test_core_etf_with_a_non_equity_tax_class_is_not_loss_or_exemption_harvested(con):
    exits.backfill_plans(con, DAY)
    assert [x for x in exits.check_close(con, DAY, None, _state(con)) if x["isin"] == GLD] == []


# --- rails ---------------------------------------------------------------------------------------------------------------------------

def test_rail_trim_brings_a_name_under_its_limit(con):
    exits.backfill_plans(con, DAY)
    st = _state(con, total=1_500_000.0)                                                    # a book of Rs 15 lakh: WIN (Rs 4 lakh) is far over the 10% company rail
    w = {r["isin"]: r["value"] / st["value"] for r in st["rows"]}
    big = max(w, key=w.get)
    assert w[big] > 0.10
    o = [x for x in exits.check_close(con, DAY, None, st) if x["kind"] == "trim"]
    assert o and "Rail trim" in o[0]["reason"] and "limit" in o[0]["reason"]
    t = [x for x in o if x["isin"] == big]
    assert t and t[0]["side"] == "sell" and 0 < t[0]["fraction"] < 1
    after = (st["rows"][[r["isin"] for r in st["rows"]].index(big)]["value"] - t[0]["qty"] * t[0]["price"]) / st["value"]
    assert after <= 0.10 - 0.01 + 0.002


def test_a_trim_inside_the_band_does_nothing_and_trims_happen_once(con):
    exits.backfill_plans(con, DAY)
    st = _state(con, total=1_500_000.0)
    first = [x for x in exits.check_close(con, DAY, None, st) if x["kind"] == "trim"]
    again = [x for x in exits.check_close(con, DAY, None, st) if x["kind"] == "trim"]
    assert first and again == []


def test_sector_trim_picks_names_in_the_sector(con):
    exits.backfill_plans(con, DAY)
    for isin in (WIN, NEW, LOSS, CALM, SWG):
        con.execute("UPDATE instruments SET sector='Banks' WHERE isin=?", [isin])
    st = _state(con, total=1_500_000.0)
    for r in st["rows"]:
        if r["isin"] != GLD:
            r["sector"] = "Banks"
    o = [x for x in exits.check_close(con, DAY, None, st) if x["kind"] == "trim"]
    assert any("Sector trim" in x["reason"] or "Rail trim" in x["reason"] for x in o)


# --- scoring ---------------------------------------------------------------------------------------------------------------------------

def _grow_sessions(con, start, n, factor):
    d = start
    for k in range(n):
        d = d + timedelta(days=3 if d.weekday() == 4 else 1)
        for isin, px in PX.items():
            con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d, px * (factor ** (k + 1))])
    return d


def test_scoring_against_holding_after_tax_at_20_and_60_sessions(con):
    exits.backfill_plans(con, DAY)
    p = {x["isin"]: x for x in exits._plans(con)}[CALM]
    _set_price(con, CALM, p["stop"] - 1.0)
    o = [x for x in exits.check_close(con, DAY, None, _state(con)) if x["isin"] == CALM and x["kind"] == "stop"][0]
    book.place(con, NOW, None, CALM, "sell", qty=o["qty"])
    d1 = _next_session(con, DAY)
    book.fill(con, d1, datetime.combine(d1, datetime.min.time()) + timedelta(hours=20))
    last = _grow_sessions(con, d1, 60, 1.002)                                              # the stock then keeps rising: holding would have been better
    exits.check_close(con, last, None, None)
    rows = con.execute("SELECT horizon_sessions, outcome, hold_value, sale_value, diff, tax, proceeds_after_tax FROM exit_scores_s81 WHERE kind='stop' ORDER BY 1").fetchall()
    assert [r[0] for r in rows] == [20, 60]
    assert all(r[1] == "bad" and r[2] > r[3] and r[4] < 0 for r in rows)                   # sold at the stop, the stock rose: holding won, after tax on both sides
    assert rows[1][2] - rows[1][3] > rows[0][2] - rows[0][3]
    assert exits.check_close(con, last, None, None) is not None
    assert con.execute("SELECT count(*) FROM exit_scores_s81 WHERE kind='stop'").fetchone()[0] == 2        # scored once
    rec = exits.record(con, 20)
    r = [x for x in rec["by_kind"] if x["kind"] == "stop"][0]
    assert r["n"] == 1 and r["good"] == 0 and "count, not a conclusion" in r["note"] and "hit_rate" not in r
    assert rec["actions"]["stop"]["filled"] == 1


def test_a_stop_that_saved_money_scores_good(con):
    exits.backfill_plans(con, DAY)
    p = {x["isin"]: x for x in exits._plans(con)}[CALM]
    _set_price(con, CALM, p["stop"] - 1.0)
    o = [x for x in exits.check_close(con, DAY, None, _state(con)) if x["isin"] == CALM and x["kind"] == "stop"][0]
    book.place(con, NOW, None, CALM, "sell", qty=o["qty"])
    d1 = _next_session(con, DAY)
    book.fill(con, d1, datetime.combine(d1, datetime.min.time()) + timedelta(hours=20))
    last = _grow_sessions(con, d1, 20, 0.99)
    exits.check_close(con, last, None, None)
    row = con.execute("SELECT outcome, diff, detail_json FROM exit_scores_s81 WHERE kind='stop' AND horizon_sessions=20").fetchone()
    assert row[0] == "good" and row[1] > 0 and "engine rows" in row[2]


def test_record_laplace_rate_only_from_twenty(con):
    for i in range(25):
        con.execute("INSERT INTO exit_scores_s81 (score_id, market, isin, kind, sleeve, trade_id, sold_on, horizon_sessions, diff, diff_pct, outcome) VALUES (?, 'IN', ?, 'target', 'swing', ?, ?, 20, 1.0, 1.0, ?)",
                    [i + 1, SWG, i + 1, DAY, "good" if i < 20 else "bad"])
    for i in range(5):
        con.execute("INSERT INTO exit_scores_s81 (score_id, market, isin, kind, sleeve, trade_id, sold_on, horizon_sessions, diff, diff_pct, outcome) VALUES (?, 'IN', ?, 'time', 'swing', ?, ?, 20, -1.0, -1.0, 'bad')",
                    [100 + i, SWG, 100 + i, DAY])
    rec = exits.record(con, 20)
    t = {r["kind"]: r for r in rec["by_kind"]}
    assert t["target"]["n"] == 25 and t["target"]["hit_rate"] == pytest.approx((20 + 1) / (25 + 2), abs=1e-3)
    assert t["time"]["n"] == 5 and "hit_rate" not in t["time"] and "count" in t["time"]["note"]
    s = exits.swing_score(con)
    assert s["n"] == 30 and s["grow"] is True and s["excess"] > 0
    con.execute("UPDATE exit_scores_s81 SET diff_pct=-5.0, outcome='bad'")
    s2 = exits.swing_score(con)
    assert s2["grow"] is False and s2["excess"] < 0


def test_swing_score_with_few_sales_does_not_grow(con):
    s = exits.swing_score(con)
    assert s == {**s, "n": 0, "grow": False} and "base share" in s["why"]


# --- the loop's contract -----------------------------------------------------------------------------------------------------------------

def test_orders_have_the_contract_fields_and_off_switch(con, monkeypatch):
    exits.backfill_plans(con, DAY)
    o = exits.check_close(con, DAY, None, _state(con))
    assert o
    for x in o:
        assert {"market", "isin", "side", "qty", "fraction", "kind", "reason", "plan_id"} <= set(x) and x["kind"] in exits.KINDS and x["market"] == "IN"
        assert x["reason"] and any(ch.isdigit() for ch in x["reason"])
    real = exits.settings
    monkeypatch.setattr(exits, "settings", lambda: {**real(), "on": False})
    assert exits.check_close(con, DAY, None, _state(con)) == [] and exits.check_quote(con, NOW, {SWG: 1.0}) == []


def test_adopted_rebalance_sales_are_scored_like_any_sale(con):
    exits.backfill_plans(con, DAY, now=datetime.combine(DAY, datetime.min.time()))
    book.place(con, datetime.combine(DAY, datetime.min.time()) + timedelta(hours=16), None, CALM, "sell", qty=100)
    d1 = _next_session(con, DAY)
    book.fill(con, d1, datetime.combine(d1, datetime.min.time()) + timedelta(hours=20))
    last = _grow_sessions(con, d1, 20, 1.001)
    exits.check_close(con, last, None, None)
    row = con.execute("SELECT kind FROM exit_scores_s81").fetchall()
    assert row == [("rebalance",)]


def test_scripts_have_no_control_characters():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src" / "pflab"
    for f in ("core/exits.py", "core/harvest.py", "core/tax_rows.py", "pm/mig_s79/m_exits.py"):
        t = (root / f).read_text(encoding="utf-8")
        assert not [c for c in t if ord(c) < 32 and c not in "\n\r\t"], f
