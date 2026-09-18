from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from pflab.eval.periods import (SealedPeriodError, WindowError, check_window, load_periods,
                                open_period, reveals, truncate_end)

CFG = Path(__file__).resolve().parents[1] / "configs" / "evaluation_periods.toml"


def test_load_and_truncate():
    ps = load_periods(CFG)
    assert ps["sealed"].sealed and not ps["development"].sealed
    df = pd.DataFrame({"date": pd.to_datetime(["2016-12-30", "2017-01-02"]), "x": [1, 2]})
    out = truncate_end(df, ps["development"])
    assert list(out["x"]) == [1]


def test_window_check():
    ps = load_periods(CFG)
    check_window(ps["development"], date(2007, 1, 1), date(2016, 12, 31))
    with pytest.raises(WindowError):
        check_window(ps["development"], date(2007, 1, 1), date(2017, 1, 1))


def test_sealed_requires_reason_and_journals(tmp_path):
    ps = load_periods(CFG)
    j = tmp_path / "journal.jsonl"
    with pytest.raises(SealedPeriodError):
        open_period("sealed", ps, j)
    with pytest.raises(SealedPeriodError):
        open_period("sealed", ps, j, unseal_reason="short")
    open_period("sealed", ps, j, unseal_reason="development and validation reviewed; single reveal")
    assert reveals(j) == 1
    open_period("development", ps, j)
    assert reveals(j) == 1
