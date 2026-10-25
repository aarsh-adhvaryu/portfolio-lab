"""tools/timesfm2_forecast.batched: a context with almost no data gets no forecast instead of crashing the run
(2026-10-21: a stock that did not trade for a whole window stopped Q5)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import timesfm2_forecast as tf2  # noqa: E402


class Fake:
    def __init__(self):
        self.calls = []

    def deciles(self, ctxs, h, po=None, pf=None):
        self.calls.append((len(ctxs), po, pf))
        assert all(np.isfinite(c).sum() >= tf2.MIN_FINITE for c in ctxs)
        return np.stack([np.full((h, 9), float(np.nanmean(c)), np.float32) for c in ctxs])


def test_empty_or_thin_contexts_get_nan_and_the_rest_keep_their_rows():
    ctxs = [np.arange(20, dtype=np.float32), np.full(20, np.nan, np.float32), np.r_[np.full(15, np.nan), np.ones(5)],
            np.full(30, 2.0, np.float32)]
    pf = [np.zeros((3, 25)) + i for i in range(4)]
    m = Fake()
    q = tf2.batched(m, ctxs, 5, pf=pf, size=1)
    assert q.shape == (4, 5, 9) and np.isnan(q[1]).all() and np.isnan(q[2]).all()
    assert q[0, 0, 0] == np.mean(np.arange(20)) and q[3, 0, 0] == 2.0
    assert [int(c[2][0][0, 0]) for c in m.calls] == [0, 3]          # covariates follow their own series


def test_nothing_forecastable_returns_all_nan_without_calling_the_model():
    m = Fake()
    q = tf2.batched(m, [np.full(10, np.nan, np.float32)], 3)
    assert np.isnan(q).all() and m.calls == []
