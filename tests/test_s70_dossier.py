"""S70: a failed calculation says why in the dossier every worker and the reviewer read (the live check's reviewer saw only an empty result)."""
from __future__ import annotations

import json

from pflab.hq import cases, missions, workers
from tests.test_s68_autonomy import NOW, con, rt  # noqa: F401  (fixtures)


def _calc(con, cid, status, check):
    k = cases._id(con, "hq_calcs", "calc_id")
    con.execute("INSERT INTO hq_calcs (calc_id, case_id, created_at, question, code, code_sha, datasets_json, params_json, result_json, status, contained, attempts, check_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [k, cid, NOW, "worst fall under a stated shock", "x = 1", "sha", "[]", "{}", "{}", status, True, 4, json.dumps(check)])
    return k


def test_a_failed_calculation_shows_its_reason_to_every_role(rt, con):
    cid = missions.create(con, NOW, "Compare phased buying with holding cash", pm_dir=rt.pm_dir)["case_id"]
    bad = _calc(con, cid, "failed", {"problems": ["KeyError: 'nifty_fall_percentages'", "second problem"]})
    mute = _calc(con, cid, "failed", {})
    ok = _calc(con, cid, "checked", {"problems": []})
    for role in ("research", "quant", "coordinator", "review"):
        text = workers._dossier(con, cid, {"body": {}, "id": 1}, NOW, role)
        assert f"CALC #{bad} [failed]" in text and "FAILED because: KeyError: 'nifty_fall_percentages'" in text and "second problem" not in text
        assert f"CALC #{mute} [failed]" in text and "FAILED (no reason was recorded)" in text
        assert f"CALC #{ok} [checked]" in text and text.count("FAILED") == 2                       # a calculation that worked carries no failure note
