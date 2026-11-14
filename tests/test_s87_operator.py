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
