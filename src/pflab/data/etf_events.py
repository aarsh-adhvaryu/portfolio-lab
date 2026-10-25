"""Declared ETF unit splits and ISIN successions the panel does not carry.

Found 2026-09-27 (`docs/notes/E3-readiness.md` §2). On 2019-12-19 NIFTYBEES
split its units 1:10 and GOLDBEES 1:100, and on 2019-12-20 both moved to
new ISINs (the AMC's scheme transfer to a new sponsor). The panel's adjustment
factors come from NSE's *equity* corporate-actions feed, which carries
neither, so the adjusted series fell 89.9% and 99.0% in a day and the old
ISINs then stopped trading -- which the engine reads as a delisting.

`apply` repairs both, **for ETF rows only and only when a config asks**, on
the path after `periods.truncate_end`:

* rows under the old ISIN are re-keyed to the successor, so the book holds
  one security across the switch (CLAUDE.md rule 8: the ISIN change is a
  dated fact, recorded here with its date);
* rows before the ex-date have their adjustment factor multiplied by the
  split factor, so `adj_close` is continuous;
* a share-count action is added at the ex-date, so a holder's units
  multiply exactly as a stock split's do (`engine._apply_ex_date_events`).

Stock rows are never touched, so no E1-family result can move; the configs
that do not set `data.etf_events` see the panel byte-for-byte as before.
Every factor below was checked against the closes either side of the event.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional, Tuple

import pandas as pd

# symbol, old ISIN, new ISIN, first session under the new ISIN, split ex-date,
# price factor (multiplies prices strictly before the ex-date)
DECLARED: List[dict] = [
    {"symbol": "NIFTYBEES", "old_isin": "INF732E01011", "new_isin": "INF204KB14I2",
     "new_isin_from": date(2019, 12, 20), "ex_date": date(2019, 12, 19),
     "factor": 0.1,
     "evidence": "close 1,292.54 on 2019-12-18, 130.20 on 2019-12-19 (ratio 0.1007)"},
    {"symbol": "GOLDBEES", "old_isin": "INF732E01102", "new_isin": "INF204KB17I5",
     "new_isin_from": date(2019, 12, 20), "ex_date": date(2019, 12, 19),
     "factor": 0.01,
     "evidence": "close 3,359.60 on 2019-12-18, 33.55 on 2019-12-19 (ratio 0.00999)"},
]


class ETFEventError(RuntimeError):
    pass


def apply(panel: pd.DataFrame, actions: Optional[pd.DataFrame],
          events: List[dict] = DECLARED) -> Tuple[pd.DataFrame, Optional[pd.DataFrame], list]:
    """(panel, actions, report). Panel dates may be `date` or Timestamp."""
    p = panel.copy()
    d = pd.to_datetime(p["date"]).dt.date
    report, new_actions = [], []
    for ev in events:
        old, new = ev["old_isin"], ev["new_isin"]
        is_old, is_new = p["isin"] == old, p["isin"] == new
        if not (is_old.any() or is_new.any()):
            continue
        if "instrument_type" in p.columns:
            bad = p.loc[is_old | is_new, "instrument_type"].unique()
            if set(bad) - {"ETF"}:
                raise ETFEventError(f"{ev['symbol']}: rows typed {set(bad)}, not ETF")
        if (d[is_old] >= ev["new_isin_from"]).any() or (d[is_new] < ev["new_isin_from"]).any():
            raise ETFEventError(f"{ev['symbol']}: ISIN dates overlap the switch")
        p.loc[is_old, "isin"] = new
        before = (p["isin"] == new) & (d < ev["ex_date"])
        f = float(ev["factor"])
        p.loc[before, "adj_factor"] = p.loc[before, "adj_factor"] * f
        p.loc[before, "adj_close"] = p.loc[before, "close"] * p.loc[before, "adj_factor"]
        if "adj_open" in p.columns:
            p.loc[before, "adj_open"] = p.loc[before, "open"] * p.loc[before, "adj_factor"]
        if (d[p["isin"] == new] >= ev["ex_date"]).any():
            new_actions.append({"isin": new, "ex_date": ev["ex_date"], "factor": f,
                                "source": "purpose", "prior_close": float("nan"),
                                "adj_prev_close": float("nan")})
        report.append({"symbol": ev["symbol"], "old_isin": old, "new_isin": new,
                       "rows_rekeyed": int(is_old.sum()),
                       "rows_adjusted": int(before.sum()),
                       "ex_date": str(ev["ex_date"]), "factor": f})
    if p.duplicated(["date", "isin"]).any():
        raise ETFEventError("re-keying produced duplicate (date, isin) rows")
    if new_actions:
        add = pd.DataFrame(new_actions)
        actions = add if actions is None else pd.concat([actions, add],
                                                        ignore_index=True)
    return p, actions, report
