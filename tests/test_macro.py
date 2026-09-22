from datetime import date

import pandas as pd

from pflab.data import macro


class _Resp:
    text = "observation_date,DGS10\n2020-01-02,1.88\n2020-01-01,\n2019-12-31,1.92\n"

    def raise_for_status(self):
        pass


def test_fetch_parses_sorts_and_drops_holidays(monkeypatch):
    monkeypatch.setattr(macro.requests, "get", lambda *a, **k: _Resp())
    df = macro.fetch("DGS10")
    assert list(df["date"]) == [date(2019, 12, 31), date(2020, 1, 2)]
    assert list(df["value"]) == [1.92, 1.88]


def test_collect_writes_one_file_per_series(monkeypatch, tmp_path):
    monkeypatch.setattr(macro, "fetch", lambda sid: pd.DataFrame(
        {"date": [date(2020, 1, 2)], "value": [1.0]}))
    out = macro.collect(tmp_path)
    assert set(out) == set(macro.SERIES)
    for key in macro.SERIES:
        assert len(macro.load(key, tmp_path)) == 1
