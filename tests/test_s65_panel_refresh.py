"""S65: the adjusted price panel is kept current by the system: appended nightly, rebuilt whole when the adjustment would change."""
import json
from datetime import date, timedelta

import pandas as pd
import pytest

from pflab.data import panel

D0 = date(2026, 10, 1)


class Source:
    """A stand-in for panel.build: one row per isin per session from D0 to `until`, only from `start` on."""
    def __init__(self):
        self.until = date(2026, 10, 5)
        self.calls = []

    def __call__(self, root, start=None, end=None, factors=None, dividends=None, mapping=None, unmapped="synthetic", write=True):
        self.calls.append(start)
        days = [D0 + timedelta(days=k) for k in range((self.until - D0).days + 1) if not start or D0 + timedelta(days=k) >= start]
        p = pd.DataFrame([{"date": d, "isin": i, "close": 100.0 + k, "adj_close": 100.0 + k, "adj_factor": 1.0, "dividend": 0.0}
                          for k, d in enumerate(days) for i in ("INE1", "INE2")])
        return p, {"rows": len(p)}


@pytest.fixture
def root(tmp_path):
    (tmp_path / "corporate_actions").mkdir()
    (tmp_path / "dividends").mkdir()
    pd.DataFrame({"isin": ["INE1"], "ex_date": [date(2026, 1, 1)], "factor": [0.5]}).to_parquet(tmp_path / "corporate_actions" / "factors.parquet")
    pd.DataFrame({"isin": ["INE1"], "ex_date": [date(2026, 9, 1)], "dividend_per_share": [2.0]}).to_parquet(tmp_path / "dividends" / "dividends.parquet")
    return tmp_path


def read(root):
    p = pd.read_parquet(root / "panel" / "prices.parquet")
    p["date"] = pd.to_datetime(p["date"]).dt.date
    return p


def test_no_panel_means_a_full_build_and_a_record_of_what_it_was_built_from(root):
    src = Source()
    r = panel.refresh(root, today=date(2026, 10, 6), build_fn=src)
    assert r["mode"] == "full" and r["why"] == "no panel yet" and r["last"] == "2026-10-05"
    assert len(read(root)) == 10 and src.calls == [None]
    st = json.loads((root / "panel" / "build_state.json").read_text(encoding="utf-8"))
    assert st["built_on"] == "2026-10-06" and st["last_date"] == "2026-10-05"
    assert not list((root / "panel").glob("*.tmp"))                                      # replaced atomically


def test_new_sessions_are_appended_and_old_rows_are_not_touched(root):
    src = Source()
    panel.refresh(root, today=date(2026, 10, 6), build_fn=src)
    before = read(root)
    src.until = date(2026, 10, 8)
    r = panel.refresh(root, today=date(2026, 10, 9), build_fn=src)
    after = read(root)
    assert r["mode"] == "append" and r["last"] == "2026-10-08" and src.calls[-1] == date(2026, 10, 6)
    kept = after[after["date"] <= date(2026, 10, 5)].sort_values(["isin", "date"]).reset_index(drop=True)
    assert len(after) == 16 and kept.equals(before.sort_values(["isin", "date"]).reset_index(drop=True))     # the old rows are as they were
    assert panel.refresh(root, today=date(2026, 10, 9), build_fn=src)["mode"] == "current"          # nothing new


def test_a_new_corporate_action_rebuilds_the_whole_panel(root):
    src = Source()
    panel.refresh(root, today=date(2026, 10, 6), build_fn=src)
    pd.DataFrame({"isin": ["INE1", "INE2"], "ex_date": [date(2026, 1, 1), date(2026, 10, 3)], "factor": [0.5, 0.1]}).to_parquet(
        root / "corporate_actions" / "factors.parquet")
    src.until = date(2026, 10, 7)
    r = panel.refresh(root, today=date(2026, 10, 8), build_fn=src)
    assert r["mode"] == "full" and r["why"] == "corporate actions changed" and src.calls[-1] is None
    assert len(read(root)) == 14                                                         # every session rebuilt


def test_a_late_dividend_inside_the_range_rebuilds_but_a_future_one_does_not(root):
    src = Source()
    panel.refresh(root, today=date(2026, 10, 6), build_fn=src)
    both = pd.read_parquet(root / "dividends" / "dividends.parquet")
    future = pd.concat([both, pd.DataFrame({"isin": ["INE2"], "ex_date": [date(2026, 12, 1)], "dividend_per_share": [1.0]})], ignore_index=True)
    future.to_parquet(root / "dividends" / "dividends.parquet")
    src.until = date(2026, 10, 7)
    assert panel.refresh(root, today=date(2026, 10, 8), build_fn=src)["mode"] == "append"           # ex-date after the panel's last day
    late = pd.concat([future, pd.DataFrame({"isin": ["INE2"], "ex_date": [date(2026, 10, 2)], "dividend_per_share": [1.0]})], ignore_index=True)
    late.to_parquet(root / "dividends" / "dividends.parquet")
    r = panel.refresh(root, today=date(2026, 10, 8), build_fn=src)
    assert r["mode"] == "full" and "late" in r["why"]


def test_it_is_rebuilt_whole_once_a_month_anyway(root):
    src = Source()
    panel.refresh(root, today=date(2026, 10, 6), build_fn=src)
    r = panel.refresh(root, today=date(2026, 11, 20), build_fn=src, max_age_days=30)
    assert r["mode"] == "full" and "older than 30 days" in r["why"]
    assert panel.refresh(root, today=date(2026, 11, 21), build_fn=src)["mode"] == "current"
    st = json.loads((root / "panel" / "build_state.json").read_text(encoding="utf-8"))
    assert st["built_on"] == "2026-11-20"


def test_the_collector_has_a_panel_source_after_dividends():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("collect_daily_t", Path(__file__).resolve().parents[1] / "tools" / "collect_daily.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    names = list(m.SOURCES)
    assert names.index("panel") == names.index("dividends") + 1 and "panel" not in m.CRITICAL
