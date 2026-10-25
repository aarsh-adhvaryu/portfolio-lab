"""S53 calculation workshop: static checks, the sandboxed run and its checks, writers with feedback, the Opus doorbell
for code, keeping, promoting and rerunning. Fake writers only; the sandbox is a real separate Python process."""
import json
from datetime import date, datetime

import pandas as pd
import pytest

from pflab.agents import analyst as an
from pflab.agents import workshop as wk
from pflab.pm import store

GOOD = '''
import numpy as np

def compute(data):
    s = data["index:X"].sort_values("date")["close"].to_numpy()
    peak = np.maximum.accumulate(s)
    return {"max_drawdown": float((s / peak - 1).min()), "last_year": int(data["index:X"]["date"].dt.year.max())}
'''
ALT = '''
def compute(data):
    s = list(data["index:X"].sort_values("date")["close"])
    peak, worst = s[0], 0.0
    for x in s:
        peak = max(peak, x)
        worst = min(worst, x / peak - 1)
    return {"max_drawdown": worst, "last_year": int(data["index:X"]["date"].max().year)}
'''
TEST = {"data": {"index:X": [{"date": "2026-01-01", "close": 100.0}, {"date": "2026-01-02", "close": 80.0},
                             {"date": "2026-01-03", "close": 120.0}]},
        "expected": {"max_drawdown": -0.2}, "tol": 1e-9}


def frames():
    d = pd.date_range("2020-01-01", periods=5).date
    return {"index:X": pd.DataFrame({"date": d, "close": [10.0, 12.0, 9.0, 6.0, 15.0]})}


def spec(code=GOOD, test=TEST, alt=""):
    return wk.Spec(["index:X"], code, test, alt, "running peak, worst fall from it")


# --- static check -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("code,why", [
    ("import os\ndef compute(data):\n    return {}", "import os"),
    ("def compute(data):\n    return {'x': len(open('f').read())}", "open"),
    ("def compute(data):\n    return {'x': eval('1')}", "eval"),
    ("import pandas as pd\ndef compute(data):\n    return {'x': len(pd.read_csv('a'))}", ".read_csv"),
    ("def compute(data):\n    data['a'].to_csv('x')\n    return {}", ".to_csv"),
    ("def compute(data):\n    return {'x': data.__class__}", "._"),
    ("from subprocess import run\ndef compute(data):\n    return {}", "from subprocess"),
    ("print('hi')\ndef compute(data):\n    return {}", "top level"),
    ("def other(data):\n    return {}", "no top-level function compute"),
    ("def compute(data):\n    return {'x': __import__('os')}", "__import__"),
    ("def compute(data):\n    return {'x': data['a'].query('x > 1')}", ".query"),
    ("import scipy.stats\ndef compute(data):\n    return {'x': len(scipy.io.loadmat('f'))}", ".io"),
    ("import numpy as np\ndef compute(data):\n    return {'x': np.lib.format.open_memmap('f')}", ".lib"),
    ("import numpy as np\ndef compute(data):\n    return {'x': np.load('f')}", ".load"),
    ("import scipy\ndef compute(data):\n    return {}", "import scipy is not allowed"),
])
def test_static_check_blocks_files_network_system_and_tricks(code, why):
    assert any(why in p for p in wk.static_check(code)), wk.static_check(code)


def test_static_check_accepts_plain_numeric_code():
    assert wk.static_check(GOOD) == [] and wk.static_check(ALT) == []


# --- sandbox run ------------------------------------------------------------------------------------------------------

def test_good_code_runs_on_the_real_rows_after_its_test_passes():
    r = wk.run(spec(), frames())
    assert r.ok and r.result == {"max_drawdown": pytest.approx(-0.5), "last_year": 2020.0} and not r.cross_checked


def test_a_second_method_that_agrees_marks_it_cross_checked():
    r = wk.run(spec(alt=ALT), frames())
    assert r.ok and r.cross_checked


def test_a_wrong_test_answer_or_a_disagreeing_method_fails():
    r = wk.run(spec(test={**TEST, "expected": {"max_drawdown": -0.25}}), frames())
    assert not r.ok and "wrong answer" in r.problems[0]
    r2 = wk.run(spec(alt=ALT.replace("x / peak - 1", "(x / peak - 1) * (0.5 if len(s) > 3 else 1)")), frames())
    assert not r2.ok and "disagree" in r2.problems[0]


def test_no_test_case_no_run_and_bad_results_are_refused():
    assert "no test case" in wk.run(spec(test={}), frames()).problems[0]
    nan = "def compute(data):\n    return {'x': float('nan')}"
    assert "not a finite number" in wk.run(spec(nan, {"data": TEST["data"], "expected": {"x": 1.0}}), frames()).problems[0]


def test_a_runaway_calculation_is_stopped():
    loop = "def compute(data):\n    while True:\n        pass"
    r = wk.run(spec(loop), frames(), time_limit=3)
    assert not r.ok and "stopped after 3 s" in r.problems[0]


# --- writers ------------------------------------------------------------------------------------------------------------

def reply(code=GOOD, test=TEST, datasets=("index:X",)):
    return "Here you go:\n" + json.dumps({"datasets": list(datasets), "code": code, "test": test, "explain": "peak"})


SCHEMA = "- holdings: x; columns a (str)\n- index:<NAME> / global:<NAME>: a daily series. Available: index:X"


def test_a_failure_is_fed_back_and_the_second_try_can_pass():
    prompts = []
    answers = iter([reply("import os\ndef compute(data):\n    return {}"), reply()])

    def w(p):
        prompts.append(p)
        return next(answers)
    out = wk.solve("worst fall of X?", lambda n: frames(), SCHEMA, "{}", [("local", w, 2)])
    assert out.status == "checked" and len(out.attempts) == 2 and "import os is not allowed" in prompts[1]
    assert "YOUR LAST ATTEMPT FAILED" in prompts[1] and "YOUR LAST" not in prompts[0]


def test_writers_hand_over_and_garbage_or_unknown_datasets_are_failed_attempts():
    bad = iter(["no json here", reply(datasets=("global:NOPE",))])
    out = wk.solve("q", lambda n: frames(), SCHEMA, "{}", [("local", lambda p: next(bad), 2), ("opus", lambda p: reply(), 1)])
    assert out.status == "checked" and out.writer == "opus" and "unknown dataset" in out.attempts[1]
    none = wk.solve("q", lambda n: frames(), SCHEMA, "{}", [("local", lambda p: "nothing", 1)])
    assert none.status == "failed" and "No checked calculation" in wk.render(none)


def test_questions_lose_first_person_wording_before_leaving():
    assert wk.neutral("What is my portfolio's drawdown if I add gold?") == \
        "What is the portfolio's drawdown if the investor add gold?"


def test_sample_rows_are_made_up_and_shaped_like_the_schema():
    rows = wk.sample_rows(wk.FIXED["holdings"][1])
    assert len(rows) == 3 and set(rows[0]) == set(wk.FIXED["holdings"][1]) and rows[1]["bucket"] == "gold"


# --- the Opus doorbell for code -------------------------------------------------------------------------------------------

class FakeClient:
    def __init__(self, text):
        self.sent = None
        outer = self

        class M:
            def count_tokens(_, **k):
                return type("T", (), {"input_tokens": 2000})()
        self.messages = M()

        class B:
            class messages:
                @staticmethod
                def create(**k):
                    outer.sent = k
                    return type("Msg", (), {"content": [type("Blk", (), {"type": "text", "text": text})()],
                                            "usage": type("U", (), {"input_tokens": 2000, "output_tokens": 800})()})()
        self.beta = B()


CFG = {"model": "m", "cap": 1500.0, "ask_above": 500.0, "usd_inr": 90.0, "adopted": True}


def test_opus_writes_code_through_the_gate_and_the_budget(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    c = FakeClient(reply())
    text = an.write_calculation(con, "QUESTION:\nworst fall of the index?", wk.WRITER_SYSTEM, c, cfg=CFG,
                                pv=an.Private(), now=datetime(2026, 10, 20, 15))
    assert wk.parse_spec(text).datasets == ["index:X"] and c.sent["system"] == wk.WRITER_SYSTEM
    assert con.execute("SELECT status, topic FROM api_calls").fetchone() == ("done", "workshop")
    with pytest.raises(an.EgressBlocked):                    # a ledger amount in the question never leaves
        an.write_calculation(con, "if the portfolio adds 123456 rupees", "s", FakeClient("{}"), cfg=CFG,
                             pv=an.Private(amounts={123456.0}))
    with pytest.raises(an.NotAdopted):
        an.write_calculation(con, "q", "s", FakeClient("{}"), cfg={**CFG, "adopted": False}, pv=an.Private())


# --- the whole loop, kept, promoted, rerun ------------------------------------------------------------------------------

def test_ask_keeps_the_code_beside_the_result_then_promote_and_rerun(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "indices").mkdir(parents=True)
    pd.DataFrame({"date": pd.date_range("2020-01-01", periods=5).date, "close": [10.0, 12.0, 9.0, 6.0, 15.0]}) \
        .to_parquet(root / "indices" / "X.parquet")
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(an, "config", lambda: {**CFG, "adopted": False})
    out = wk.ask(con, "What was the worst fall of X?", tmp_path / "pm", root, date(2026, 10, 20),
                 local=lambda p: reply(), now=datetime(2026, 10, 20, 15, 0))
    assert out.status == "checked" and out.run.result["max_drawdown"] == pytest.approx(-0.5)
    meta = json.loads((out.folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["label"] == wk.UNREVIEWED and (out.folder / "code.py").exists()
    assert "not reviewed" in wk.render(out)
    mem = con.execute("SELECT text FROM memory WHERE source LIKE 'workshop %'").fetchone()[0]
    assert "max_drawdown -0.5" in mem
    cid = out.folder.name
    assert wk.listing(tmp_path / "pm")[0]["id"] == cid
    assert wk.promote(tmp_path / "pm", cid, by="investor")["label"] == "reviewed"
    again = wk.rerun(tmp_path / "pm", cid, lambda n: {k: wk.load_dataset(k, con, root, date(2020, 1, 4)) for k in n})
    assert again.ok and again.result["max_drawdown"] == pytest.approx(-0.5)          # data up to the as-of date only


def test_datasets_never_carry_account_or_deposit_ids(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    h = wk.load_dataset("holdings", con, tmp_path, date(2026, 10, 20))
    f = wk.load_dataset("fds", con, tmp_path, date(2026, 10, 20))
    assert list(h.columns) == list(wk.FIXED["holdings"][1]) and "account" not in h.columns
    assert list(f.columns) == ["maturity", "value", "reserve"]
    with pytest.raises(KeyError):
        wk.load_dataset("index:../secrets", con, tmp_path, date(2026, 10, 20))


def test_a_copy_of_the_code_is_not_a_second_method():
    renamed = GOOD.replace("data", "frames")                       # same steps, other names: still a copy
    for alt in (GOOD, "\n# the same, again\n" + GOOD, renamed):
        r = wk.run(spec(alt=alt), frames())
        assert r.ok and not r.cross_checked                          # dropped, not a failed try
    assert not wk.same_method(GOOD, ALT) and wk.run(spec(alt=ALT), frames()).cross_checked


def test_auto_asks_opus_first_and_falls_back_to_the_local_model(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "indices").mkdir(parents=True)
    pd.DataFrame({"date": pd.date_range("2020-01-01", periods=5).date, "close": [10.0, 12.0, 9.0, 6.0, 15.0]}) \
        .to_parquet(root / "indices" / "X.parquet")
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(an, "config", lambda: CFG)
    monkeypatch.setattr(an, "private_values", lambda con: an.Private())
    local_calls = []
    out = wk.ask(con, "What was the worst fall of X?", tmp_path / "pm", root, date(2026, 10, 20),
                 local=lambda p: local_calls.append(p) or reply(), opus_client=FakeClient(reply()),
                 now=datetime(2026, 10, 20, 15, 0))
    # the local model may pick a reviewed measure (none fits here) but never writes the code when Opus can
    assert out.status == "checked" and out.writer.endswith("(analyst)") and not [p for p in local_calls if p.startswith("QUESTION:")]
    assert out.confirm["status"] == "agrees"                    # an independent second writing on the real data
    out = wk.ask(con, "What was the worst fall of X?", tmp_path / "pm", root, date(2026, 10, 20),
                 local=lambda p: reply(), opus_client=FakeClient("no json"), now=datetime(2026, 10, 20, 15, 1),
                 library=False)                          # the writers' order (the library would answer a repeat)
    assert out.writer == "local model (fallback after Opus)" and len(out.attempts) == 3
    out = wk.ask(con, "What was the worst fall of X?", tmp_path / "pm", root, date(2026, 10, 20),
                 local=lambda p: reply(), opus_client=FakeClient("no json"), now=datetime(2026, 10, 20, 15, 2))
    assert out.writer.startswith("library: the same question") and out.reused_from   # no writer paid for a repeat
