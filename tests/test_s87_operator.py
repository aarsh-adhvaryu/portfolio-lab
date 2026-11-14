"""S87 O2/O4: the operator's permissions, workspace, chat session (scripted SDK) and the build flow on a scratch git repo (branch, card, Yes merges and tags, No changes nothing)."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from pflab.llm import claude_plan as cp
from pflab.oper import build, perms, session, workspace
from test_s87_claude_plan import FakeClient, assistant, result  # noqa: F401  (the scripted SDK)

NOW = datetime(2026, 11, 16, 10, 0)


@pytest.fixture
def con(tmp_path, monkeypatch):
    from pflab.pm import store
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "data"))
    DATA[0] = tmp_path / "data"
    FakeClient.seen, FakeClient.script, FakeClient.capture_tool = [], [], None
    monkeypatch.setattr(cp, "client_factory", FakeClient)
    monkeypatch.setattr(cp, "signin_fn", lambda: {"ok": True, "method": "claude.ai", "detail": ""})
    return store.connect(tmp_path / "t.duckdb")


# --- permissions: refused by the callback, not by words ---------------------------------------------------------------------------------------

def test_answer_session_cannot_write_src_or_push(tmp_path):
    root = workspace.ensure(str(tmp_path))
    d = lambda t, i: perms.decide("answer", t, i, root)[0]
    assert d("Write", {"file_path": str(root / "notes" / "a.md")})
    assert d("Write", {"file_path": "research/x.py"})
    assert not d("Write", {"file_path": str(Path(__file__).resolve().parents[1] / "src" / "pflab" / "x.py")})
    assert not d("Edit", {"file_path": str(root / "CLAUDE.md")})
    assert not d("Write", {"file_path": str(root / "notes" / ".." / "CLAUDE.md")})
    assert not d("Bash", {"command": "git push origin main"})
    assert not d("Bash", {"command": "pflab pm networth; rm -rf x"})
    assert not d("Bash", {"command": "pflab --live service run"})
    assert d("Bash", {"command": "pflab pm networth"})
    assert d("Bash", {"command": "python -I research/study.py"})
    assert not d("Bash", {"command": "python -I ../src/x.py"})
    assert not d("Read", {"file_path": "C:/Windows/win.ini"})
    assert not d("WebFetch", {"url": "https://x"})


def test_build_session_edits_src_and_tests_never_pushes(tmp_path):
    wt = tmp_path / "wt"
    d = lambda t, i, b="fix/x": perms.decide("build", t, i, wt, branch=b)[0]
    assert d("Edit", {"file_path": str(wt / "src" / "a.py")}) and d("Write", {"file_path": str(wt / "tests" / "t.py")})
    assert not d("Edit", {"file_path": str(wt / "configs" / "core.toml")})
    assert not d("Edit", {"file_path": str(wt / "src" / "a.py")}, "main")
    assert d("Bash", {"command": "git commit -m x"}) and d("Bash", {"command": "python -m pytest -q tests/test_x.py"})
    for bad in ("git push", "git push origin main", "git merge main", "git checkout main", "git reset --hard", "git branch -D x"):
        assert not d("Bash", {"command": bad}), bad


def test_workspace_files(tmp_path):
    root = workspace.ensure(str(tmp_path))
    assert "not a coding assistant" in (root / "CLAUDE.md").read_text(encoding="utf-8")
    sk = (root / ".claude" / "skills" / "case_review" / "SKILL.md").read_text(encoding="utf-8")
    assert sk.startswith("---") and "name: case_review" in sk
    assert (root / ".claude" / "agents" / "reviewer.md").exists() and (root / "notes").is_dir() and (root / "research").is_dir()
    (root / "CLAUDE.md").write_text(workspace.texts.TAG + "\nMY EDIT", encoding="utf-8")
    workspace.ensure(str(tmp_path))
    assert "MY EDIT" in (root / "CLAUDE.md").read_text(encoding="utf-8")        # a current-version file edited by hand is kept


# --- the chat session ----------------------------------------------------------------------------------------------------------------------

def _ctx():
    return SimpleNamespace(source="the book is Rs 100", decisions=[], problems=[], results={}, images=[], con=None)


def _route(role="read"):
    return {"role": role, "model_key": "sonnet", "thinking": "medium", "auto": True, "why": "test", "tools": "all"}


DATA = [Path(".")]


def _answer(con, cid, first="HIS MESSAGE:\nhi"):
    from pflab.hq import passes
    ctx = _ctx()
    pid = passes.record(con, NOW, "assistant", [], "m", "assistant", "running")
    return session.answer(SimpleNamespace(data_root=str(DATA[0])), con, NOW, ctx=ctx, pid=pid, first=first, r=_route(), model_id="claude-sonnet-5-5", cid=cid, aid=1, q="hi",
                          progress=lambda s: None)


def test_chat_resumes_the_session_and_new_chat_starts_fresh(con, monkeypatch, tmp_path):
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "data"))
    FakeClient.script = [assistant("It is Rs 100."), result("It is Rs 100.", sid="sess-A")]
    out = _answer(con, 7)
    assert out["status"] == "done" and "Rs 100" in out["text"] and out["meta_obj"]["price"] == "plan"
    assert FakeClient.seen[-1].resume is None and FakeClient.seen[-1].cwd.endswith("operator")
    assert "mcp__oper__*" in FakeClient.seen[-1].allowed_tools
    FakeClient.script = [result("Still Rs 100.", sid="sess-A")]
    _answer(con, 7, first="FILES HE SENT WITH THIS MESSAGE (x)\n\nHIS MESSAGE:\nagain")
    assert FakeClient.seen[-1].resume == "sess-A"                    # the same chat resumes (survives a restart: the id is in the store)
    FakeClient.script = [result("fresh", sid="sess-B")]
    _answer(con, 8)                                                   # New chat = a new chat id = a new session
    assert FakeClient.seen[-1].resume is None


def test_usage_limit_in_chat_says_paused_and_does_not_fail(con):
    FakeClient.script = [result("usage limit reached. resets at 3pm", is_error=True, status=429)]
    out = _answer(con, 9)
    assert out["status"] == "done" and "paused" in out["text"].lower() and "paper book keep running" in out["text"]


def test_unsourced_numbers_are_removed_from_the_reply(con):
    FakeClient.script = [result("The book is Rs 100. It will be Rs 987,654 soon.", sid="s")]
    out = _answer(con, 10)
    assert "987,654" not in out["text"]


# --- the build flow on a scratch repo ---------------------------------------------------------------------------------------------------------

def _g(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    _g(["init", "-q", "--bare", "-b", "main", str(origin)], tmp_path)
    _g(["clone", "-q", str(origin), str(work)], tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        _g(["config", k, v], work)
    (work / "src").mkdir()
    (work / "tests").mkdir()
    (work / "src" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (work / "tests" / "test_m.py").write_text("import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parents[1] / 'src'))\nimport m\n\n\ndef test_f():\n    assert m.f() == 1\n", encoding="utf-8")
    _g(["add", "-A"], work)
    _g(["commit", "-q", "-m", "init"], work)
    _g(["push", "-q", "origin", "HEAD:main"], work)
    return work, origin


def _fixer(wt_holder):
    def script(opts):
        wt = Path(opts.cwd)
        wt_holder.append(wt)
        (wt / "src" / "m.py").write_text("def f():\n    return 2\n", encoding="utf-8")
        (wt / "tests" / "test_m.py").write_text("import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parents[1] / 'src'))\nimport m\n\n\ndef test_f():\n    assert m.f() == 2\n", encoding="utf-8")
        return [result("", structured={"cause": "f returned the wrong constant", "change": ["f returns 2", "test updated"], "tests": "1 passed", "fixed": True})]
    return script


def test_build_makes_a_branch_card_and_yes_merges_and_tags_no_changes_nothing(con, repo, monkeypatch, tmp_path):
    from pflab.entrance import cards
    work, origin = repo
    seen = []
    FakeClient.script = _fixer(seen)
    assert "queued" in build.request(con, NOW, "f returns the wrong constant in m.py", "test")
    assert "already" in build.request(con, NOW, "f returns the wrong constant in m.py", "test")
    r = build.run_pending(con, NOW, repo=work, venv_python=Path(sys.executable))
    assert r["status"] == "card", r
    assert r["branch"].startswith("fix/2026-11-16-") and r["tests"].startswith("passed")
    assert "src/m.py" in _g(["diff", "--name-only", "main..." + r["branch"]], work)
    assert _g(["rev-parse", "main"], work) == _g(["rev-parse", "origin/main"], work)           # main untouched before his Yes
    ev = FakeClient.seen[-1]
    assert ev.tools == ["Read", "Write", "Edit", "Glob", "Grep", "Bash"] and ev.can_use_tool is not None
    card = con.execute("SELECT card_id FROM cards_s85 WHERE msg_id=?", [r["card"]]).fetchone() if False else None
    out = cards.answer_card(con, r["card"], "yes", "laptop")
    assert "released" in str(out).lower() or "merged" in str(out).lower(), out
    _g(["fetch", "-q", "--tags", "origin"], work)
    assert f"v{datetime.now():%Y.%m.%d}" in _g(["tag", "--list"], work)      # the card runs the handler on the real clock
    assert "return 2" in _g(["show", "origin/main:src/m.py"], work)


def test_no_leaves_main_alone(con, repo):
    from pflab.entrance import cards
    work, origin = repo
    FakeClient.script = _fixer([])
    build.request(con, NOW, "f returns the wrong constant in m.py", "test")
    r = build.run_pending(con, NOW, repo=work, venv_python=Path(sys.executable))
    cards.answer_card(con, r["card"], "no", "laptop")
    _g(["fetch", "-q", "origin"], work)
    assert "return 1" in _g(["show", "origin/main:src/m.py"], work)
    assert _g(["tag", "--list"], work).strip() == ""


def test_two_builds_a_day_and_waiting_on_the_plan_limit(con, repo, monkeypatch):
    work, _ = repo
    monkeypatch.setattr(cp, "settings", lambda: {**cp.DEFAULTS, "build_per_day": 1})
    FakeClient.script = [result("limit reached", is_error=True, status=429)]
    build.request(con, NOW, "first problem here in module", "t")
    assert build.run_pending(con, NOW, repo=work, venv_python=Path(sys.executable)) is None          # the plan's limit: the build waits, nothing is lost
    assert con.execute("SELECT status FROM operator_builds_s87").fetchone()[0] == "requested"
    con.execute("DELETE FROM engine_state_s85 WHERE key='plan_pause'")
    FakeClient.script = _fixer([])
    assert build.run_pending(con, NOW, repo=work, venv_python=Path(sys.executable))["status"] == "card"
    build.request(con, NOW, "second problem in another module", "t")
    assert build.run_pending(con, NOW, repo=work, venv_python=Path(sys.executable)) is None          # the day's quota is used


# --- O3 weekly introspection, jobs, the endpoint for the screens, the terminal opener -----------------------------------------------------------

def test_week_key_is_the_last_friday_close():
    from pflab.oper import introspect as it
    assert str(it.week_key(datetime(2026, 11, 14, 9, 0))) == "2026-11-13"            # Saturday
    assert str(it.week_key(datetime(2026, 11, 13, 14, 0))) == "2026-11-06"           # Friday before the close: last week's
    assert str(it.week_key(datetime(2026, 11, 13, 16, 0))) == "2026-11-13"


def test_weekly_introspection_writes_the_note_once_and_candidates_are_not_live(con):
    from pflab.oper import introspect as it
    when = datetime(2026, 11, 14, 9, 0)
    FakeClient.script = [result("", structured={"worked": ["thin evidence so far"], "not_worked": [], "calibration": "too few scored decisions to judge the words",
                                                "learned": "nothing yet; the sample is too small to change a rule", "test_next": [{"idea": "trim rule after tax", "why": "untested"}]})]
    assert it.due(con, when)
    r = it.run(con, when)
    assert r["candidates"] == 1 and r["note_id"]
    assert not it.due(con, when) and it.run(con, when).get("skipped")
    assert "Weekly introspection" in con.execute("SELECT text FROM core_notes_s80").fetchone()[0]
    assert FakeClient.seen[-1].tools == []                                           # it reads facts; it has no tool and changes nothing


def test_jobs_are_registered_and_only_when_the_plan_engine_is_in_use(con, monkeypatch):
    from pflab.service import jobs, tasks
    tasks._load_s79_jobs()
    import pflab.service.tasks_s79_operator87  # noqa: F401
    assert "operator_build" in jobs.REGISTRY and "operator_weekly" in jobs.REGISTRY
    ctx = SimpleNamespace(con=con, now=NOW)
    assert jobs.REGISTRY["operator_build"].enabled_fn(ctx)[0] is True
    monkeypatch.setattr(cp, "settings", lambda: {**cp.DEFAULTS, "enabled": False})
    assert jobs.REGISTRY["operator_build"].enabled_fn(ctx)[0] is False


def test_problems_become_build_requests_but_plan_limits_do_not(con):
    from pflab.service import problems
    build.ensure(con)
    t0 = datetime(2026, 11, 16, 9, 0)
    problems._upsert(con, "job_failed", "k1", "job x failed: KeyError 'a'", "job x", t0, t0, 1)
    problems._upsert(con, "model_engine", "k2", "claude_plan: limit", "gateway", t0, t0, 1)
    assert build.scan_problems(con, datetime(2026, 11, 16, 10, 0)) == 1
    assert con.execute("SELECT count(*) FROM operator_builds_s87").fetchone()[0] == 1


def test_operator_endpoint_and_terminal(tmp_path, monkeypatch):
    import pandas as pd
    from fastapi.testclient import TestClient
    from pflab.app import runtime, server
    from pflab.pm import store
    from pflab.oper import terminal
    pm, data = tmp_path / "pm", tmp_path / "data"
    (data / "indices").mkdir(parents=True)
    monkeypatch.setattr(cp, "signin_fn", lambda: {"ok": True, "method": "claude.ai", "detail": ""})
    rt = runtime.Runtime(pm, data, tmp_path, con=store.connect(tmp_path / "l.duckdb"), clock=lambda: NOW)
    c = TestClient(server.create_app(rt))
    j = c.get("/api/operator").json()
    assert j["signed_in"] is True and j["thinking"] == "running" and set(j["tokens_today"]) == {"desk", "cases", "chat", "build"} and "open_cards" in j and "builds" in j
    seen = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-planted")
    r = terminal.open_terminal(str(data), popen=lambda argv, **kw: seen.update(kw, argv=argv))
    assert r["ok"] and seen["cwd"].endswith("operator") and "ANTHROPIC_API_KEY" not in seen["env"]
    monkeypatch.setattr(cp, "signin_fn", lambda: {"ok": False, "method": "api_key", "detail": "x"})
    assert terminal.open_terminal(str(data), popen=lambda *a, **k: 1 / 0)["ok"] is False


def test_his_logged_decisions_are_scored_against_the_index_point_in_time(con, monkeypatch):
    import pandas as pd
    from pflab.core import pick_score
    from pflab.oper import learn
    monkeypatch.setattr("pflab.agents.tradecheck.isin_of", lambda c, s: "INE000A01010" if s == "AAA" else None)
    days = pd.bdate_range("2026-01-01", periods=80)
    idx = pd.Series([100.0 + i * 0.1 for i in range(80)], index=days)
    stock = pd.Series([50.0 + i * 0.5 for i in range(80)], index=days)
    monkeypatch.setattr(pick_score, "index_series", lambda m, root=None: idx)
    monkeypatch.setattr(learn, "_series", lambda c, isin, root, asof: stock)
    assert "not a name" in learn.log_decision(con, datetime(2026, 1, 5, 18, 0), "ZZZ", "buy")
    assert "Logged" in learn.log_decision(con, datetime(2026, 1, 5, 18, 0), "AAA", "buy", "test")
    assert learn.score_due(con, datetime(2026, 1, 9, 10, 0)) == 0                  # not even 5 sessions yet
    assert learn.score_due(con, datetime(2026, 2, 20, 10, 0)) == 2                 # 5 and 20 sessions have passed, 60 has not
    s = learn.summary(con)
    assert s["n_logged"] == 1 and set(s["decisions"][0]["scores"]) == {"5_sessions", "20_sessions"}
    assert s["decisions"][0]["scores"]["5_sessions"]["excess_vs_nifty500_pct"] > 0
    assert learn.score_due(con, datetime(2026, 2, 20, 10, 0)) == 0                 # once each
