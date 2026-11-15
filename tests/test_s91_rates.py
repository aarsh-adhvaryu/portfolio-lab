"""S91: the "Rates up 1%" study. The rule in code equals the protocol's JSON block; a planted relation passes and noise fails the two-part rule; too little data is "insufficient" (not evidence);
the study refuses to run if the protocol changed after registration; the Lab preset follows the recorded verdict and, when it passes, shifts only the first month. Synthetic data only."""
from __future__ import annotations

import json
import re
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from pflab.lab import rates_study as rs
from pflab.pm import store


def _series(seed=1, slope=0.0, n_months=120):
    rng = np.random.default_rng(seed)
    idx = pd.period_range("2011-12", periods=n_months, freq="M")
    y = pd.Series(7 + np.cumsum(rng.normal(0, 0.15, n_months)), index=idx)
    dy = y.diff().fillna(0)
    book = pd.Series(0.008 + slope * dy + rng.normal(0, 0.02, n_months), index=idx)
    return book.iloc[1:], y


def test_the_rule_in_code_equals_the_protocol_json():
    text = rs.PROTOCOL.read_text(encoding="utf-8")
    block = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1))
    assert block == rs.RULE
    assert "INDIRLTLT01STM" in text and "+100 basis points" in text and "2022-2025 is spent" in text


def test_a_planted_relation_passes_both_parts_and_noise_fails(monkeypatch):
    book, y = _series(slope=-0.12)
    ok = rs.analyse(book, y, 99, 95, 100)
    assert ok["verdict"] == "pass" and ok["dev_pass"] and ok["val_pass"] and ok["dev"]["b"] < 0 and ok["oos_r2"] > 0 and abs(ok["response_per_100bp_pct"] + 12) < 4
    noise = rs.analyse(*_series(seed=7, slope=0.0), 99, 95, 100)
    assert noise["verdict"] == "fail" and not (noise["dev_pass"] and noise["val_pass"]) and "against a bar" in noise["why"]
    flip = book.copy()
    flip.loc[flip.index >= pd.Period("2018-01", "M")] = (0.008 - (flip.loc[flip.index >= pd.Period("2018-01", "M")] - 0.008)).to_numpy()   # the relation changes sign in validation
    assert rs.analyse(flip, y, 99, 95, 100)["verdict"] == "fail"


def test_too_little_data_is_insufficient_not_a_verdict():
    book, y = _series(slope=-0.12)
    assert rs.analyse(book, y, 99, 20, 100)["verdict"] == "insufficient"
    assert rs.analyse(book.iloc[:30], y.iloc[:31], 99, 95, 100)["verdict"] == "insufficient"


def test_registration_is_idempotent_counts_once_and_a_changed_protocol_blocks_the_run(tmp_path, monkeypatch):
    con = store.connect(tmp_path / "r.duckdb")
    n0 = con.execute("SELECT count(*) FROM learn_tests").fetchone()[0]
    assert rs.register(con, datetime(2026, 11, 16)) == [rs.NOTE] and rs.register(con, datetime(2026, 11, 16)) == []
    assert con.execute("SELECT count(*) FROM learn_tests").fetchone()[0] == n0 + 1
    assert rs.protocol_ok(con)["unchanged"] is True
    fake = tmp_path / "p.md"
    fake.write_text(rs.PROTOCOL.read_text(encoding="utf-8") + "\nedited", encoding="utf-8")
    monkeypatch.setattr(rs, "PROTOCOL", fake)
    assert rs.protocol_ok(con)["unchanged"] is False
    with pytest.raises(RuntimeError, match="not allowed to run"):
        rs.run(con, tmp_path, datetime(2026, 11, 16), y=pd.Series(dtype=float), write=False)


def test_the_preset_follows_the_recorded_verdict(tmp_path):
    assert rs.verdict(tmp_path / "none.json") == {"enabled": False, "why": "not tested yet: the study has not run"}
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"verdict": "fail", "why": "tested: not supported (t 0.4 against 1.65)"}), encoding="utf-8")
    assert rs.verdict(f) == {"enabled": False, "why": "tested: not supported (t 0.4 against 1.65)"}
    f.write_text(json.dumps({"verdict": "pass", "why": "w", "dev": {"b": -0.04, "se_b": 0.01, "r2": 0.2}, "oos_r2": 0.1}), encoding="utf-8")
    v = rs.verdict(f)
    assert v["enabled"] and v["b"] == -0.04 and v["se_b"] == 0.01
