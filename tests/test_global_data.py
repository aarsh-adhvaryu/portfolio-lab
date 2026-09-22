import importlib.util
from datetime import date
from pathlib import Path

import pytest

from pflab.data import global_markets as g

_spec = importlib.util.spec_from_file_location(
    "ingest_gdelt_world", Path(__file__).resolve().parents[1] / "tools" / "ingest_gdelt_world.py")
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)


class _Resp:
    def __init__(self, j):
        self._j = j

    def json(self):
        return self._j


def test_fetch_uses_exchange_local_date(monkeypatch):
    # Sydney opens 10:00 AEST = 00:00 UTC; in AEDT (+11) that is 23:00 UTC the
    # PREVIOUS day. The UTC date would be wrong; the local date is right.
    ts = int(pd_ts("2020-01-01T23:00:00Z"))
    j = {"chart": {"result": [{"meta": {"gmtoffset": 39600}, "timestamp": [ts, ts + 86400],
                               "indicators": {"quote": [{"open": [1, 2], "high": [1, 2], "low": [1, 2],
                                                         "close": [1.0, None], "volume": [0, 0]}]}}]}}
    monkeypatch.setattr(g.requests, "get", lambda *a, **k: _Resp(j))
    df = g.fetch("^AXJO")
    assert list(df["date"]) == [date(2020, 1, 2)]           # null close dropped
    assert df["adj_close"].iloc[0] == 1.0                   # no adjclose -> close


def pd_ts(s):
    import pandas as pd
    return pd.Timestamp(s).timestamp()


def test_world_ingest_checks_duplicates(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    head = "day,country,n_events,n_articles,mean_tone,mean_goldstein,q1,q2,q3,q4\n"
    (src / "a.csv").write_text(head + "20150218,US,10,50,-1.0,0.5,5,2,2,1\n20150218,NA,3,9,-2.0,0.1,1,1,1,0\n")
    r = W.ingest(src, tmp_path / "out")
    assert r["rows"] == 2 and r["countries"] == 2           # 'NA' (Namibia) is not a null
    (src / "b.csv").write_text(head + "20150218,US,10,50,-1.0,0.5,5,2,2,1\n")
    with pytest.raises(ValueError, match="appears twice"):
        W.ingest(src, tmp_path / "out")
