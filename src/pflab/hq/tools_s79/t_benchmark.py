"""S79b item 18B/18E tool: `benchmark` reads the system's book against the benchmark that matches its own allocation, the monthly attribution, and the latest verification runs
of the book's corporate actions and top-ups. Read only; works with {} args."""
from __future__ import annotations

from pflab.hq.tools import Ctx, Tool, _s


def benchmark(ctx: Ctx, a: dict) -> dict:
    """Read: {market, started, since, as_of, sessions, book:{return, level}, benchmark:{return, level, weights_start_of_day, weights_now, source, target_id, labels}, excess,
    monthly:[{month, period_start, period_end, sessions, book_return, bench_return, excess, allocation, selection, timing, costs, tax, residual, partial, by_class}], latest_month,
    stale_classes, worst_fall_book, notes, verification:{runs:[{kind, at, ok, failed}]}}. Returns are fractions (0.012 = 1.2%)."""
    try:
        from pflab.paper import benchmark as bm, verify_book
        if not bm.on():
            return {"off": True}
        market = str(a.get("market") or "IN").upper()
        out = bm.status(ctx.con, market, ctx.now.date())
        if out.get("off"):
            return out
        out["verification"] = verify_book.status(ctx.con)
        out["about"] = ("parts add up exactly: allocation + selection + timing + costs + tax + residual = excess (book minus benchmark), each in points of the month's opening value; "
                        "costs and tax are negative effects; tax is an estimate; the benchmark is the active allocation target's weights on the class indices (labels says which), the Kite-seed "
                        "weights before any target")
        return out
    except Exception as e:                                     # a probe, or a store before the migration, must get a harmless answer
        return {"started": False, "note": f"the benchmark is not readable now ({type(e).__name__})"}


TOOLS = [
    Tool("benchmark", "read", "The system's book against its OWN benchmark (its allocation target's weights on a Nifty 500 total-return, gold in rupees, US index in rupees and cash-rate blend, "
         "re-weighted when the target changes): the result since the start, the weights in force, the monthly attribution of the excess into allocation, selection, timing, costs and tax "
         "(plus an explicit residual), and the latest checks that corporate actions and top-ups reach the book. Returns are fractions.",
         {"market": _s("IN or US", 4)}, (), benchmark),
]
