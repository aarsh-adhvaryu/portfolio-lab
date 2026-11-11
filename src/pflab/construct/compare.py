"""What is left of the S79b 18A comparison module (A60, 2026-11-11).

The registered comparison of `construct` (a shrunk-covariance optimiser) against the current sizing rules (`docs/protocols/s79_construct_protocol.md`) was inconclusive (p 0.41) and
`construct` was never adopted, so its advice tool (`hq/tools_s79/t_construct.py`), the optimiser (`optimiser.py`), the advice builder (`run.py`) and the study driver that lived here
(`run`, `simulate`, the book and the bootstrap) were DELETED. The study record stays: `docs/protocols/s79_construct_protocol.md`, the counter row (`construct.register`, `learner/s79.py`)
and the table `construct_runs_s85`.

Kept because something that passed reads it: `clean`, the data-break filter of `lab/runner.py:build_panel` (a daily move beyond `jump` is a bad print and is removed from the path). The
shrunk covariance (`risk.py`, read by `core/state.py` and `core/card.py`) and the charges and tax estimates (`costs.py`, read by `lab/runner.py`) stay in this package too.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def clean(px: pd.DataFrame, jump: float) -> pd.DataFrame:
    r = px.pct_change(fill_method=None)
    bad = r.abs() > jump
    cum = np.log1p(r.where(bad, 0.0).fillna(0.0)).cumsum()
    return px * np.exp(-cum)
