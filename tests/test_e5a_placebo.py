"""tools/e5a_placebo.py: the shuffle permutes returns only within (M, h)."""
import importlib.util
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

_spec = importlib.util.spec_from_file_location(
    "e5a_placebo", Path(__file__).resolve().parents[1] / "tools" / "e5a_placebo.py")
placebo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(placebo)


def _labels():
    rows = []
    for m in (date(2011, 1, 31), date(2011, 2, 28)):
        for h in (1, 3):
            for i in range(6):
                rows.append({"isin": f"X{i}", "month_end": m, "h": h, "kind": "open",
                             "ret": float(i) + 10 * h + (100 if m.month == 2 else 0)})
    rows.append({"isin": "X9", "month_end": date(2011, 1, 31), "h": 1,
                 "kind": "pending", "ret": np.nan})
    return pd.DataFrame(rows)


def test_shuffle_keeps_each_cross_section_multiset_and_rows():
    L = _labels()
    S = placebo.shuffle_within(L, seed=1)
    assert (S[["isin", "month_end", "h", "kind"]] == L[["isin", "month_end", "h", "kind"]]).all().all()
    for key, g in L.groupby(["month_end", "h"]):
        s = S.loc[g.index, "ret"]
        assert sorted(s.dropna()) == sorted(g["ret"].dropna())
    assert S["ret"].isna().sum() == 1
    assert not np.array_equal(S["ret"].fillna(-1), L["ret"].fillna(-1))


def test_shuffle_is_deterministic():
    L = _labels()
    assert placebo.shuffle_within(L, 7)["ret"].equals(placebo.shuffle_within(L, 7)["ret"])
