"""S81 B6: a policy on probation trades its slice of the book inside the close loop, and a failing slice leaves its share to the champion. Synthetic (the S80 core fixture)."""
from __future__ import annotations

from pflab.core import loop
from pflab.lab import live, probation, service
from tests.test_s80_core import AAA, BBB, DAYS, NOW, calm_index, con  # noqa: F401  (the fixture and helpers)


def _slice(monkeypatch, weights=None, fail=False):
    monkeypatch.setattr(probation, "slices", lambda con, day: [{"policy_id": "lab_x", "share": 0.05, "since": str(day)}])
    monkeypatch.setattr(service, "get", lambda con, pid: {"policy_id": pid, "code": "x", "params": {}})
    if fail:
        monkeypatch.setattr(live, "decide", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("slice policy broke")))
    else:
        monkeypatch.setattr(live, "decide", lambda *a, **k: weights)


def test_a_slice_policy_is_blended_into_the_targets_and_named_in_the_note(con, monkeypatch):
    _slice(monkeypatch, {BBB: 0.08})
    r = loop.run(con, NOW, None, calm_index())
    assert r.get("status") in ("traded", "held"), r
    note = con.execute("SELECT note FROM core_runs_s80 WHERE day=?", [DAYS[-1]]).fetchone()[0]
    assert "probation slice(s) trade their share: lab_x 5%" in note


def test_a_failing_slice_policy_leaves_its_share_to_the_champion_and_says_so(con, monkeypatch):
    _slice(monkeypatch, fail=True)
    r = loop.run(con, NOW, None, calm_index())
    assert r.get("status") in ("traded", "held"), r
    assert con.execute("SELECT count(*) FROM paper_acts WHERE loop='core_loop' AND useful=FALSE AND what LIKE '%probation policy lab_x failed%'").fetchone()[0] == 1
    note = con.execute("SELECT note FROM core_runs_s80 WHERE day=?", [DAYS[-1]]).fetchone()[0]
    assert "probation slice" not in note
