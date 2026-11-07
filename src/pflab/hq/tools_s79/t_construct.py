"""S79b item 18A: the `construct` tool (read). Sizing, never direction: target weights for the paper book from the ensemble forecasts, a shrunk-covariance risk model, the rails,
charges and tax, and the system's own allocation target. Works with {} (the whole book); a harmless dict when there is no book or the switch is off.

Result keys (stable; the situation adapters read them):
  off                        True when `[construct] on = false` (nothing else is returned)
  ok                         False when the optimiser or the inputs failed: `fallback` says the current sizing rules decide
  status / adopted           "NOT ADOPTED: advice only ..." or "ADOPTED"; `comparison` = {verdict, reason, run_at} of the registered backtest comparison (or None)
  as_of, book_value          the date and the paper book's value (rupees)
  target_weights             [{symbol, isin, current_pct, target_pct, change_pct, expected_excess_pct, expected_source}] (percent of the book)
  cash_target_pct, cash_now_pct
  trades                     [{symbol, isin, side, qty, price, rupees, weight_before_pct, weight_after_pct, est_charges, est_tax}] (estimates)
  est_charges_total, est_tax_total, binding (tight constraints, words), gap_to_current_rules [{symbol, construct_pct, current_rule_pct, difference_pct}]
  utility_gain_vs_doing_nothing, parts, inputs {shrinkage, returns_days, names_with_history, names_with_forecast, no_forecast_rule, ...}, notes
Optional input `symbols` ("RELIANCE,ITC"): size only buys of these names (a BUY decision list), keeping every other holding where it is.
"""
from __future__ import annotations

from pflab.hq.tools import Ctx, Tool, _s


def construct(ctx: Ctx, a: dict) -> dict:
    try:
        from pflab import construct as C
        if not C.is_on():
            return {"off": True}
        try:
            C.register(ctx.con, ctx.now)                                   # counts the registered comparison in the learner once (idempotent)
        except Exception:
            pass
        from pflab.construct import run as R
        decisions = None
        syms = [s.strip().upper() for s in str(a.get("symbols") or "").replace(";", ",").split(",") if s.strip()]
        if syms:
            from pflab.paper import book
            decisions = [{"action": "BUY", "symbol": s, "isin": book.isin_of(ctx.con, s), "id": s} for s in syms]
            decisions = [d for d in decisions if d["isin"]]
            decisions += _held_as_hold(ctx.con, ctx.now, {d["isin"] for d in decisions})
        out = R.advise(ctx.con, ctx.now, getattr(ctx.rt, "data_root", None), None, decisions or None, log=False)
        if ctx.call_ref:
            out["call_id"] = ctx.call_ref
        return out
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}", "fallback": "the current sizing rules decide", "note": "construct could not be read"}


def _held_as_hold(con, now, skip) -> list:
    try:
        from pflab.paper import book
        return [{"action": "HOLD", "isin": i, "id": i} for i in book.positions(con) if i not in skip]
    except Exception:
        return []


TOOLS = [
    Tool("construct", "read", "Portfolio construction for the paper book (sizing only; direction stays the team's): target weights from the ensemble forecasts (expected return and "
         "dispersion), a Ledoit-Wolf shrunk covariance risk model, and a constrained optimiser. The rails are hard constraints (company 10%, sector 25%, one ETF 35%, circuit breaker "
         "= no new buying, cash >= 0, long only), Zerodha charges and the estimated FIFO tax are in the objective, and the book is pulled toward the system's own allocation target. "
         "Returns the target weights, the trades they imply (quantity, rupees, estimated charges and tax), the binding constraints and the gap to the current sizing rules. Labelled "
         "NOT ADOPTED until the registered comparison (docs/protocols/s79_construct_protocol.md) passes; then the paper manager sizes with it. A name without a forecast has zero "
         "expected excess. Works with no input.",
         {"symbols": _s("optional: comma-separated symbols of a BUY list to size (other holdings are kept)", 200)}, (), construct),
]
