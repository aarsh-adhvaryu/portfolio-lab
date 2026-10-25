"""Reusable calculations: parameters reach the sandbox, the same question re-runs its kept code, a reviewed calculation
answers a similar question with parameters read by the local model (checked against their types), and anything less
certain goes to the writers."""
import json
from datetime import date, datetime

import pandas as pd
import pytest

from pflab.agents import workshop as wk

CODE = '''
def compute(data, params):
    s = data["index:X"]
    s = s[s["date"] >= params["start"]]
    return {"largest_close": float(s["close"].max()), "start": str(params["start"])}
'''
TEST = {"data": {"index:X": [{"date": "2020-01-01", "close": 5.0}, {"date": "2021-01-01", "close": 7.0},
                             {"date": "2022-01-01", "close": 6.0}]},
        "expected": {"largest_close": 7.0}, "tol": 1e-9, "params": {"start": "2020-06-01"}}
PARAMS = {"start": {"type": "date", "default": "2020-01-01", "about": "first date counted"}}


def frames(names):
    return {"index:X": pd.DataFrame({"date": pd.to_datetime(["2019-01-01", "2020-03-01", "2023-01-01"]),
                                     "close": [100.0, 50.0, 80.0]})}


def spec():
    return wk.Spec(["index:X"], CODE, TEST, "", "the largest close from a start date", PARAMS)


def test_parameters_reach_the_sandbox():
    r = wk.run(spec(), frames(["index:X"]))
    assert r.ok and r.result == {"largest_close": 80.0, "start": "2020-01-01"}          # the default
    r = wk.run(spec(), frames(["index:X"]), values={"start": "2019-01-01"})
    assert r.ok and r.result["largest_close"] == 100.0


def keep(tmp_path, question, label="new calculation, not reviewed", confirmed=None):
    s = spec()
    out = wk.Outcome("checked", wk.run(s, frames(s.datasets)), s, "Opus", ["Opus try 1: ok"])
    out.confirm = {"status": confirmed} if confirmed else None
    d = wk.keep(tmp_path, question, out, datetime(2026, 10, 23, 18, 0, len(list(tmp_path.glob("**/meta.json")))))
    if label == "reviewed":
        wk.promote(tmp_path, d.name, "test")
    return d.name


def test_the_same_question_reruns_its_kept_code_without_a_writer(tmp_path):
    keep(tmp_path, "Largest close of X since 2020")               # S58b: only its own example checked: not reused
    assert wk.from_library(tmp_path, "largest close of X  since 2020", frames, llm=None) is None
    keep(tmp_path, "Largest close of X since 2020", confirmed="agrees")
    out = wk.from_library(tmp_path, "largest close of X  since 2020", frames, llm=None)
    assert out.status == "checked" and out.writer.startswith("library: the same question") and out.run.result["largest_close"] == 80.0


def test_a_reviewed_calculation_answers_a_similar_question_with_parameters_read_locally(tmp_path):
    cid = keep(tmp_path, "Largest close of X since 2020", "reviewed")
    out = wk.from_library(tmp_path, "Largest close of X since 2019", frames, llm=lambda p: '{"start": "2019-01-01"}')
    assert out.reused_from == cid and out.values == {"start": "2019-01-01"} and out.run.result["largest_close"] == 100.0
    assert wk.from_library(tmp_path, "Largest close of X since 2019", frames, llm=lambda p: '{"start": "soon"}') is None
    assert wk.from_library(tmp_path, "Average volume of Y last week", frames, llm=lambda p: "{}") is None   # not similar


def test_an_unreviewed_calculation_is_reused_only_for_the_same_question(tmp_path):
    keep(tmp_path, "Largest close of X since 2020")
    assert wk.from_library(tmp_path, "Largest close of X since 2019", frames, llm=lambda p: '{"start": "2019-01-01"}') is None


def test_a_text_value_must_come_from_the_question():
    p = {"index": {"type": "text", "default": "NIFTY50"}}
    assert wk.fill(p, "the worst fall of NIFTY500", lambda _: '{"index": "NIFTY500"}') == {"index": "NIFTY500"}
    assert wk.fill(p, "the worst fall of NIFTY500", lambda _: '{"index": "BANKNIFTY"}') is None


def test_promote_from_the_dashboard(tmp_path):
    from fastapi.testclient import TestClient

    from pflab.app import runtime, server
    from pflab.pm import store
    pm = tmp_path / "pm"
    cid = keep(pm, "Largest close of X since 2020")
    rt = runtime.Runtime(pm, tmp_path / "data", tmp_path, con=store.connect(tmp_path / "l.duckdb"),
                         clock=lambda: datetime(2026, 10, 23, 19, 0))
    c = TestClient(server.create_app(rt))
    assert c.get("/api/ai").json()["calcs"][0]["label"] == "new calculation, not reviewed"
    assert c.post(f"/api/workshop/{cid}/promote").json() == {"ok": True}
    assert c.get("/api/ai").json()["calcs"][0]["label"] == "reviewed"
    assert c.post("/api/workshop/..%2Fx/promote").status_code in (400, 404)
