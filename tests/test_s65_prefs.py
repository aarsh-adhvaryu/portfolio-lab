"""S65: the AI changes his preferences when HE asks: one exact edit put to him, applied on his yes after a backup, undone if invalid."""
import json
from datetime import datetime

import pytest

from pflab import _toml
from pflab.agents import questions
from pflab.plan import prefs, stock_list as sl, targets as tg
from pflab.pm import store
from pflab.risk import themes

NOW = datetime(2026, 10, 29, 10, 0)
TARGETS = """# his file, with a comment that must survive
[meta]
set_by = "him"

[bucket.equity]
target = 0.6
soft_band = 0.05

[bucket.debt]
target = 0.4
soft_band = 0.05
"""


@pytest.fixture
def pm(tmp_path, monkeypatch):
    p = tmp_path / "pm"
    p.mkdir()
    monkeypatch.setenv("PFLAB_PM_DIR", str(p))
    (p / "targets.toml").write_text(TARGETS, encoding="utf-8")
    (p / "api_budget.toml").write_text("[api]\nmonthly_cap_rupees = 2500\nadopted = true\n", encoding="utf-8")
    monkeypatch.setattr(tg, "default_path", lambda: p / "targets.toml")

    def load(path=None):
        d = _toml.load(path or p / "targets.toml")
        if abs(sum(b["target"] for b in d["bucket"].values()) - 1.0) > 1e-9:
            raise ValueError("weights do not sum to 1")
    monkeypatch.setattr(tg, "load", load)
    return p


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


def say(con, text):
    q = con.execute("SELECT q_id FROM limit_proposals ORDER BY prop_id DESC").fetchone()[0]
    questions.answer(con, q, text, NOW)
    return themes.resolve(con, NOW)


def test_a_target_change_is_proposed_then_applied_on_his_yes_with_a_backup(pm, con):
    assert prefs.propose(con, "targets", "weights", {"equity": 0.55, "debt": 0.45}, "he said: less in stocks", NOW)
    assert "0.6" in (pm / "targets.toml").read_text(encoding="utf-8")                          # nothing changes before his yes
    assert say(con, "yes")["applied"] == 1
    text = (pm / "targets.toml").read_text(encoding="utf-8")
    assert "target = 0.55" in text and "target = 0.45" in text and "# his file, with a comment that must survive" in text
    assert list((pm / "backups").glob("targets.toml.*.bak"))


def test_a_change_that_would_not_validate_is_undone_and_declined(pm, con):
    prefs.propose(con, "targets", "weights", {"equity": 0.7}, "he asked for more stocks", NOW)
    out = say(con, "yes")
    assert out == {"applied": 0, "declined": 1}
    assert (pm / "targets.toml").read_text(encoding="utf-8") == TARGETS                         # restored exactly
    ev = json.loads(con.execute("SELECT evidence_json FROM limit_proposals").fetchone()[0])
    assert "not made" in ev["result"] and "validate" in ev["result"]


def test_the_api_cap_and_the_stock_list_change_the_same_way(pm, con, monkeypatch):
    prefs.propose(con, "api_cap", "monthly", 3000, "he raised it", NOW)
    say(con, "yes")
    assert "monthly_cap_rupees = 3000" in (pm / "api_budget.toml").read_text(encoding="utf-8")
    seen = []
    monkeypatch.setattr(sl, "path", lambda: pm / "stock_list.toml")
    monkeypatch.setattr(sl, "add", lambda con, s, asof=None, p=None, run_agents=True: seen.append(("add", s)) or {})
    prefs.propose(con, "stock_list", "add", "abc", "he wants it watched", NOW)
    say(con, "yes")
    assert seen == [("add", "ABC")]


def test_a_no_changes_nothing_and_bad_requests_are_refused(pm, con):
    prefs.propose(con, "api_cap", "monthly", 4000, "x", NOW)
    assert say(con, "no")["declined"] == 1 and "2500" in (pm / "api_budget.toml").read_text(encoding="utf-8")
    for kind, key, value in (("targets", "weights", {"equity": 1.5}), ("stock_list", "buy", "ABC"), ("api_cap", "monthly", 10 ** 7),
                             ("risk_limit", "x", 1)):
        with pytest.raises(prefs.PrefError):
            prefs.check(kind, key, value)


def test_the_brain_tool_only_proposes(pm, con, tmp_path):
    from pflab.hq import egress, governor as gv, tools as tl
    from pflab.hq.desk import Desk
    rt = Desk(con, pm, tmp_path / "data", tmp_path, None, {"brain": "economy"}, clock=lambda: NOW)
    ctx = tl.Ctx(rt, 1, gv.OPUS, False, {}, egress.Gate(), NOW, source="")
    text, err = tl.run(ctx, "change_preference", {"kind": "api_cap", "key": "monthly", "value": "3500", "why": "he asked: raise my cap to 3500"})
    assert not err and "waiting for his yes" in text
    assert "2500" in (pm / "api_budget.toml").read_text(encoding="utf-8")
    assert con.execute("SELECT kind, key, value, status FROM limit_proposals").fetchall() == [("preference", "api_cap:monthly", "3500", "pending")]
