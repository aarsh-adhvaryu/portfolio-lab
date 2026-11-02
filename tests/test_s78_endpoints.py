"""S78: the endpoints the redesigned screens read: watchlist, self-check, learner ideas, top-up (refused outside the system's own account) and the cost-known flag. Synthetic profile."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from tests.test_s68_ui import NOW, server  # noqa: F401  (the fixture)


def _get(port, path):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10).read())


def _post(port, path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def test_the_screens_endpoints_answer_on_an_empty_profile(server):
    rt, port = server
    assert _get(port, "/api/watchlist") == {"items": []}
    sc = _get(port, "/api/selfcheck")
    assert sc["run"] is None and sc["groups"] == [] and sc["counts"] == {"ok": 0, "warn": 0, "bad": 0}
    ideas = _get(port, "/api/learner/ideas")
    assert ideas["ideas"] == [] and "tests counted" in ideas["counter"]
    assert _get(port, "/api/paper")["started"] is False


def test_a_top_up_is_refused_outside_the_systems_own_account(server):
    rt, port = server
    try:
        _post(port, "/api/paper/topup", {"amount": 1000})
        assert False, "should have been refused"
    except urllib.error.HTTPError as e:
        assert e.code == 400 and "not the system's own" in json.loads(e.read())["detail"]


def test_the_self_check_button_runs_and_the_screen_reads_the_result(server):
    rt, port = server
    import time
    out = _post(port, "/api/selfcheck/run", {})
    assert out["started"] is True and out["running"] is True                          # it returns at once; the rows appear as the checks finish
    assert _post(port, "/api/selfcheck/run", {})["started"] is False                  # a second press while it runs starts nothing
    for _ in range(120):
        sc = _get(port, "/api/selfcheck")
        if not sc["running"]:
            break
        time.sleep(0.5)
    assert sc["running"] is False and sc["run"]["id"] == out["run_id"] and sc["total"] > 0 and sc["groups"]
    assert sc["counts"]["ok"] + sc["counts"]["warn"] + sc["counts"]["bad"] == sc["total"]
