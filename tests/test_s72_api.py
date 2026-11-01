"""S72-S73: the API behind the screens for house rules, memory, the envelope and the scorecard."""
from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from pflab.app.server import create_app
from pflab.hq import rules
from tests.test_s68_autonomy import NOW, con, rt  # noqa: F401  (fixtures)


def test_rules_memory_envelope_and_scorecard_are_served(rt, con):
    c = TestClient(create_app(rt))
    a = rules.propose(con, NOW, "method", "Always include a 0.5% charge in cost tests", name="costs")
    b = rules.propose(con, NOW, "method", "Always include a 0.3% charge in cost tests", name="costs")
    d = c.get("/api/rules").json()
    assert [r["rule_id"] for r in d["active"]] == [b["rule_id"]] and d["waiting"] == [] and d["version"] > 0
    out = c.post(f"/api/rules/{b['rule_id']}/undo").json()
    assert out["undone"] is True and out["restored"] == a["rule_id"]
    assert [r["text"] for r in c.get("/api/rules").json()["active"]] == ["Always include a 0.5% charge in cost tests"]
    assert (rt.pm_dir / "house_rules.md").exists()
    assert c.get("/api/envelope").json()["active"] is False
    sc = c.get("/api/scorecard").json()
    assert sc["table"] == [] and sc["proposals"] == []
    rec = c.get("/api/recall", params={"about": "What is the weather?"}).json()
    assert rec["conclusions"] == [] and rec["brief"] == "" and "effects_last_30_days" in rec
