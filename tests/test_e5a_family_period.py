"""tools/e5a_family_period.py: divergence from A0 and the drawdown window."""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import e5a_family_period as efp  # noqa: E402


def _decisions(root: Path, row: str, held: list) -> None:
    d = root / row
    d.mkdir(parents=True)
    rows = [{"month_end": f"2015-0{i + 1}-28", "held": h} for i, h in enumerate(held)]
    (d / "decisions.json").write_text(json.dumps(rows), encoding="utf-8")


def test_first_divergence(tmp_path):
    _decisions(tmp_path / "a0", "base", [["X"], ["X", "Y"], ["Y"]])
    _decisions(tmp_path / "c", "base", [["X"], ["Y", "X"], ["Z"]])
    out = efp.first_divergence(tmp_path / "c", tmp_path / "a0")
    assert out["base"] == {"first": "2015-03-28", "month_ends_differing": 1, "month_ends": 3}


def test_drawdown_window(tmp_path):
    d = tmp_path / "rows" / "base"
    d.mkdir(parents=True)
    dates = pd.date_range("2015-01-01", periods=5).date
    pd.DataFrame({"date": dates, "nav_liq": [100.0, 120.0, 90.0, 110.0, 95.0]}).to_parquet(d / "equity.parquet")
    (tmp_path / "criteria.json").write_text(json.dumps({"rows": {"base": {"max_drawdown": -0.25}}}))
    w = efp.drawdown_window(tmp_path)
    assert (w["peak"], w["trough"], w["matches_criteria"]) == ("2015-01-02", "2015-01-03", True)
