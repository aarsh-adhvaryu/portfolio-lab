"""Tax selling (S81 B4, A51): the planning of exemption harvesting, loss harvesting and the buy-backs. Pure planning: it reads the book and the tax engine's rows and returns
specs; `core/exits.py` turns them into events and orders. Every rate and the yearly exemption come from `core/tax_rows.py` (the engine's dated rows).

Exemption harvesting   book long-term equity gains up to the yearly exemption by selling lots held over 12 months and buying the same name back, which resets the cost
                       price (the next sale of those shares then starts from today's price). Mostly in the last quarter of the financial year; outside it at most
                       `harvest_off_quarter_share` of the exemption. Only first-in-first-out prefixes of long-term lots, whole shares, at most `harvest_margin` of the room (the fill is at
                       the next close).
Loss harvesting        sell the lots in loss when this year's realised gains are taxed and the loss would cut the tax (the engine's set-off: a short-term loss against any
                       equity gain, a long-term loss against long-term gains), and buy back.
Buy-back               never the same session as the sale: the sale fills at one close, the buy-back is placed at the next close and fills at the one after. The Indian rules
                       have no wash-sale rule, but a buy and a sell of the same shares on one day is speculative income (A54), so the two legs are always on different sessions.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Dict, List, Optional, Tuple

from pflab.core import tax_rows as tr
from pflab.tax import rules


def _lot_json(taken: List[dict]) -> List[dict]:
    return [{"acq": t["acq"].isoformat(), "take": round(t["take"], 6), "cpu": round(t["cpu"], 6), "tax_class": t["tax_class"]} for t in taken]


def _roundtrip(ac: Optional[str], qty: float, price: float) -> float:
    from pflab.paper import book
    return book._charges(ac, "sell", qty * price) + book._charges(ac, "buy", qty * price) + 2 * book.SLIPPAGE * qty * price


def exemption_room(con, day: date, cfg: dict, pending_gain: float = 0.0) -> Tuple[float, dict]:
    """(rupees of long-term gain that may still be booked this close, the working). Raises `rules.RuleGap` when no row covers the date."""
    ex = tr.exemption(day)
    g = tr.year_gains(con, day)
    used = tr.exemption_used(g) + max(0.0, pending_gain)
    in_q = day.month in [int(m) for m in cfg["harvest_quarter_months"]]
    cap = ex if in_q else ex * float(cfg["harvest_off_quarter_share"])
    room = max(0.0, cap - used) * float(cfg["harvest_margin"])
    return room, {"fy": tr.fy_label(day), "exemption": ex, "used": round(used, 2), "cap": round(cap, 2), "in_last_quarter": in_q, "room": round(room, 2),
                  "row": "exemption ltcg_112a (configs/tax/capital_gains.toml)"}


def exemption_specs(con, day: date, cfg: dict, cands: List[dict], total: float, pending_gain: float = 0.0, breaker: bool = False) -> Tuple[List[dict], List[str], dict]:
    """`cands`: [{plan, isin, symbol, asset_class, price}] (the positions that may be harvested: core and long-term, priced, buyable, nothing pending).
    -> (specs, notes on what was skipped and why, the working)."""
    from pflab.paper import book
    notes: List[str] = []
    try:
        room, work = exemption_room(con, day, cfg, pending_gain)
        rates = tr.rates(day)
    except rules.RuleGap as e:
        return [], [f"no exemption harvesting: the tax engine has no row for {day} ({e})"], {}
    if breaker and cfg.get("rebuy", True):
        return [], ["no exemption harvesting while the circuit breaker is on (the buy-back would be refused)"], work
    if room <= 0:
        return [], [f"no exemption room: Rs {work['used']:,.0f} of the Rs {work['cap']:,.0f} allowed this close is already booked"], work
    left, sold_value, cap_value = room, 0.0, float(cfg["harvest_max_book_share"]) * total
    ranked = []
    for c in cands:
        lots = tr.lots(con, c["isin"])
        gain_total = sum(l["qty"] * (c["price"] - l["cpu"]) for l in lots if tr.is_long_term(l["acq"], day))
        ranked.append((gain_total / max(1.0, sum(l["qty"] * c["price"] for l in lots)), c["symbol"] or "", c, lots))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    specs = []
    for _ratio, _sym, c, lots in ranked:
        if left <= 0 or sold_value >= cap_value:
            break
        price, ac = c["price"], c["asset_class"]
        qty, cum, take_lots = 0.0, 0.0, []
        for l in lots:
            if book._bucket(l["tax_class"], ac, l["acq"], day) != "lt_eq" or not tr.is_long_term(l["acq"], day):
                break                                                     # FIFO: the first lot that is not a long-term equity lot ends the prefix
            per = price - l["cpu"]
            if per <= 0:                                                  # a long-term loss lot at the front is sold with it: it lowers what is booked
                take = l["qty"]
            elif cum + l["qty"] * per <= left:
                take = l["qty"]
            else:
                take = float(math.floor(max(0.0, left - cum) / per))
            if take <= 0:
                break
            take_lots.append({**l, "take": take})
            qty += take
            cum += take * per
            if take < l["qty"]:
                break
        if qty < 1 or cum <= 0:
            continue
        fee = book._charges(ac, "sell", qty * price)
        gains = tr.sale_gains(take_lots, price, fee, ac, day)
        gain = gains.get("lt_eq", 0.0)
        if gain < float(cfg["harvest_min_gain"]):
            notes.append(f"{c['symbol']}: a harvest would book Rs {gain:,.0f}, under the Rs {float(cfg['harvest_min_gain']):,.0f} minimum")
            continue
        value = qty * price
        saving = rates["lt_eq"] * gain
        cost = _roundtrip(ac, qty, price)
        if saving < float(cfg["harvest_cost_multiple"]) * cost:
            notes.append(f"{c['symbol']}: the tax saved later (Rs {saving:,.0f}) is under {float(cfg['harvest_cost_multiple']):.0f} times the round-trip charges (Rs {cost:,.0f})")
            continue
        if sold_value + value > cap_value and sold_value > 0:
            notes.append(f"{c['symbol']}: left for a later close (a harvest sells at most {float(cfg['harvest_max_book_share']):.0%} of the book at one close)")
            continue
        extra = tr.tax_of(tr.add(tr.year_gains(con, day), gains), day) - tr.tax_of(tr.year_gains(con, day), day)
        left -= gain
        sold_value += value
        specs.append({"plan": c["plan"], "isin": c["isin"], "symbol": c["symbol"], "qty": qty, "price": price, "value": value, "gain": gain, "gains": gains,
                      "tax_saved_later": saving, "extra_tax_now": extra, "charges": fee, "roundtrip": cost, "lots": _lot_json(take_lots), "room_after": left, "work": work,
                      "sub": "exemption"})
    return specs, notes, work


def loss_specs(con, day: date, cfg: dict, cands: List[dict], base_gains: Dict[str, float]) -> Tuple[List[dict], List[str]]:
    """Loss harvesting. `base_gains`: this year's gains by bucket so far, with the exemption harvests chosen at this close already added."""
    from pflab.paper import book
    notes: List[str] = []
    if not cfg.get("loss_harvest", True):
        return [], []
    try:
        tr.rates(day)
    except rules.RuleGap as e:
        return [], [f"no loss harvesting: the tax engine has no row for {day} ({e})"]
    g = dict(base_gains)
    specs, left = [], list(cands)
    while left:
        t0 = tr.tax_of(g, day)
        if t0 <= 0:
            notes.append("no loss harvesting: this year's realised gains carry no tax a loss could offset" if not specs else "")
            break
        best = None
        for c in left:
            price, ac = c["price"], c["asset_class"]
            lots = tr.lots(con, c["isin"])
            cum = 0.0
            for k, l in enumerate(lots):
                cum += l["qty"]
                taken = tr.consume(lots, cum)
                fee = book._charges(ac, "sell", cum * price)
                gains = tr.sale_gains(taken, price, fee, ac, day)
                if any(b in ("lt_other", "slab") for b in gains):         # only equity-taxed lots (the equity set-off rules); other buckets are left to the stop and rebalance paths
                    break
                if sum(gains.values()) >= 0:
                    continue
                saving = t0 - tr.tax_of(tr.add(g, gains), day)
                cost = _roundtrip(ac, cum, price)
                if saving >= float(cfg["loss_min_saving"]) and saving >= float(cfg["harvest_cost_multiple"]) * cost and cum * price >= float(cfg.get("min_trim_rupees", 2000.0)):
                    if best is None or saving > best["saving"]:
                        best = {"plan": c["plan"], "isin": c["isin"], "symbol": c["symbol"], "qty": cum, "price": price, "value": cum * price, "gain": sum(gains.values()),
                                "gains": gains, "saving": saving, "charges": fee, "roundtrip": cost, "lots": _lot_json(taken), "cand": c, "tax_before": t0,
                                "tax_after": t0 - saving, "sub": "loss"}
        if best is None:
            break
        left = [c for c in left if c["isin"] != best["cand"]["isin"]]
        g = tr.add(g, best["gains"])
        best.pop("cand")
        specs.append(best)
    return specs, [n for n in notes if n]


def rebuy_specs(con, day: date, cfg: dict, breaker: bool) -> Tuple[List[dict], List[str]]:
    """Filled harvest sales with no buy-back yet: the shares to buy back now (placed at this close, so they fill at the next session, never the sale's own)."""
    out, notes = [], []
    if not cfg.get("rebuy", True):
        return out, notes
    rows = con.execute("SELECT s.event_id, s.plan_id, s.market, s.isin, s.qty, s.filled_on, s.kind FROM exit_events_s81 s WHERE s.side='sell' AND s.kind='harvest' AND s.status='filled' "
                       "AND NOT EXISTS (SELECT 1 FROM exit_events_s81 b WHERE b.link_event_id = s.event_id AND b.status IN ('emitted','filled')) ORDER BY s.event_id").fetchall()
    for eid, pid, market, isin, qty, filled_on, _k in rows:
        if filled_on is None or filled_on > day:
            continue
        if breaker:
            notes.append(f"buy-back of {isin} waits: the circuit breaker is on")
            continue
        out.append({"sale_event": eid, "plan_id": pid, "market": market, "isin": isin, "qty": float(qty), "sold_on": filled_on})
    return out, notes
