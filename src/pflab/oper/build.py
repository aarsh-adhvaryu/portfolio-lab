"""S87 O4: self-fixing, with his Yes. A new failure on the Problems list (or "build:" / "fix" from him, or the operator's `request_build`) becomes a BUILD request. A build session works in its OWN git
worktree of the workshop on a new branch `fix/<date>-<slug>` (the workshop's own working tree is never touched): finds the root cause, writes a failing test, fixes, runs the affected tests and the privacy
grep, and ends in one Yes/No card (laptop and Telegram) with the cause, the change in three lines and the test result. Yes: merged into main in a throw-away worktree, tagged, pushed (the app takes the tag at
its next start). No: the branch stays, nothing changes. At most `build_per_day` sessions a day, inside the build token budget. Nothing here merges or pushes without his Yes."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from pflab.llm import claude_plan as cp
from pflab.llm import gateway as gw
from pflab.oper import perms, workspace

log = logging.getLogger("pflab.build")
DDL = """CREATE TABLE IF NOT EXISTS operator_builds_s87 (build_id INTEGER PRIMARY KEY, created_at TIMESTAMP NOT NULL, source VARCHAR, problem VARCHAR NOT NULL, status VARCHAR NOT NULL,
         branch VARCHAR, worktree VARCHAR, cause VARCHAR, change_text VARCHAR, tests VARCHAR, card_msg_id INTEGER, finished_at TIMESTAMP, tokens INTEGER, detail VARCHAR)"""
SCHEMA = {"type": "object", "properties": {"cause": {"type": "string"}, "change": {"type": "array", "items": {"type": "string"}, "maxItems": 3}, "tests": {"type": "string"},
                                          "fixed": {"type": "boolean"}}, "required": ["cause", "change", "tests", "fixed"]}
IGNORE_KINDS = ("model_engine", "plan_limit", "usage_limit")
BRANCH_FN = "pflab.oper.build:merge_and_tag"
SYSTEM = """You are fixing a bug in the portfolio-lab code, on a git branch of your own. Rules: find the ROOT cause (not the symptom); write a failing test first; make the smallest fix; run the tests that
touch the change and `python -m pflab.hq.security` (it must print "privacy grep: clean"); commit on this branch with a message of 10 lines or fewer. Engine tests (test_engine_*, test_lookahead,
test_negative_control, test_measurement_fixes, test_accounting_audit) are never edited. Money is float rupees, dates are datetime.date, tests are synthetic, no real data. You may edit only src/ and tests/.
No push, no merge, no other branch. End with the structured answer: cause (plain words), change (at most 3 lines), tests (what ran and the result), fixed (true only if the tests pass)."""


def ensure(con) -> None:
    con.execute(DDL)


def repo_root() -> Path:
    try:
        from pflab import _toml
        w = (_toml.load(cp.CONFIG).get("operator") or {}).get("workshop")
        if w:
            return Path(w)
    except Exception:
        pass
    return Path(__file__).resolve().parents[3]


def git(args: List[str], cwd: Path, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:32].strip("-") or "bug"


def _started_today(con, now: datetime) -> int:
    d0 = datetime(now.year, now.month, now.day)
    return int(con.execute("SELECT count(*) FROM operator_builds_s87 WHERE created_at >= ? AND status NOT IN ('requested','refused')", [d0]).fetchone()[0])


def request(con, now: datetime, problem: str, source: str = "operator") -> str:
    ensure(con)
    problem = problem.strip()
    if len(problem) < 8:
        return "Say what is wrong in a few words, then I can open a build."
    dup = con.execute("SELECT build_id, status FROM operator_builds_s87 WHERE problem = ? AND created_at >= ?", [problem, datetime(now.year, now.month, now.day)]).fetchone()
    if dup:
        return f"Build #{dup[0]} for this is already {dup[1]}."
    from pflab.pm.store import next_id
    bid = next_id(con, "operator_builds_s87", "build_id")
    con.execute("INSERT INTO operator_builds_s87 (build_id, created_at, source, problem, status) VALUES (?,?,?,?,?)", [bid, now, source, problem[:2000], "requested"])
    left = int(cp.settings()["build_per_day"]) - _started_today(con, now)
    return f"Build #{bid} is queued ({'it starts at once' if left > 0 else 'today the two builds are used: it starts tomorrow'}). You get a Yes/No card when a fix is ready; nothing changes before your Yes."


def scan_problems(con, now: datetime) -> int:
    """A Problems row that is new since the last scan (an exception, a failed job, a failed self-check) becomes a build request; an engine or plan-limit line never does."""
    ensure(con)
    last = gw._get_state(con, "build_scan")
    since = datetime.fromisoformat(last) if last else datetime(now.year, now.month, now.day)
    try:
        from pflab.service import problems
        rows = problems.listing(con, since)
    except Exception:
        return 0
    n = 0
    for r in rows:
        if r["first_seen"] < since or r["kind"] in IGNORE_KINDS or "claude_plan" in str(r["text"]) or "plan's limit" in str(r["text"]):
            continue
        request(con, now, f"[{r['kind']}] {r['text']} ({r['context'] or 'no context'})", source="problems")
        n += 1
    gw._set_state(con, "build_scan", now.isoformat(), now, "problems scanned for builds")
    return n


def _test_run(wt: Path, py: Path, files: List[str]) -> str:
    if not files:
        return "no test file changed"
    env = {**os.environ, "PYTHONPATH": str(wt / "src"), **cp.child_env()}
    try:
        p = subprocess.run([str(py), "-m", "pytest", "-q", "-x", *files], cwd=str(wt), capture_output=True, text=True, timeout=900, env=env)
        tail = (p.stdout or "").strip().splitlines()[-1:] or [""]
        return f"{'passed' if p.returncode == 0 else 'FAILED'}: {tail[0]}"
    except Exception as e:
        return f"could not run: {type(e).__name__}"


def run_pending(con, now: datetime, *, repo: Optional[Path] = None, venv_python: Optional[Path] = None) -> Optional[dict]:
    """The oldest queued build, if today's quota and token budget allow: one session, one card. Returns the build row or None."""
    ensure(con)
    if not cp.settings()["enabled"] or _started_today(con, now) >= int(cp.settings()["build_per_day"]):
        return None
    row = con.execute("SELECT build_id, problem FROM operator_builds_s87 WHERE status='requested' ORDER BY build_id LIMIT 1").fetchone()
    if not row:
        return None
    bid, problem = int(row[0]), str(row[1])
    repo = repo or repo_root()
    py = venv_python or (repo / ".venv" / "Scripts" / "python.exe")
    if not py.exists():
        py = Path(os.environ.get("PYTHON", "python"))
    branch = f"fix/{now:%Y-%m-%d}-{slug(problem)}-{bid}"
    wt = workspace.root() / "builds" / f"b{bid}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    g = git(["worktree", "add", "-b", branch, str(wt), "main"], repo)
    if g.returncode != 0:
        con.execute("UPDATE operator_builds_s87 SET status='failed', detail=?, finished_at=? WHERE build_id=?", [f"worktree: {g.stderr[:300]}", now, bid])
        return {"build_id": bid, "status": "failed", "detail": g.stderr[:300]}
    con.execute("UPDATE operator_builds_s87 SET status='running', branch=?, worktree=? WHERE build_id=?", [branch, str(wt), bid])

    async def can_use(name, inp, c):
        ok, why = perms.decide("build", name, inp, wt, branch=branch)
        return cp.allow_result() if ok else cp.deny_result(f"refused: {why}")
    model = gw.resolve("read", engine="claude_plan")["model"]
    try:
        res = cp.run(con, prompt=f"THE PROBLEM:\n{problem}\n\nYou are in {wt} on branch {branch}. The tests run with `python -m pytest` (the repo's venv is already on PATH of the shell).", system=SYSTEM, model=model,
                     effort="medium", klass="build", purpose="build", agent="build", now=now, cwd=str(wt), tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"], can_use_tool=can_use,
                     schema=SCHEMA, max_turns=int(cp.settings()["max_turns_build"]), setting_sources=[], timeout=1500, extra_env={"PYTHONPATH": str(wt / "src")})
    except (cp.PlanPaused, cp.PlanBudgetSpent, cp.PlanUnusable) as e:
        con.execute("UPDATE operator_builds_s87 SET status='requested', detail=? WHERE build_id=?", [f"waits: {str(e)[:200]}", bid])
        git(["worktree", "remove", "--force", str(wt)], repo)
        git(["branch", "-D", branch], repo)
        return None
    except Exception as e:
        con.execute("UPDATE operator_builds_s87 SET status='failed', detail=?, finished_at=? WHERE build_id=?", [f"{type(e).__name__}: {str(e)[:300]}", now, bid])
        return {"build_id": bid, "status": "failed"}
    out = res.structured if isinstance(res.structured, dict) else {}
    if git(["status", "--porcelain"], wt).stdout.strip():                      # the session left changes uncommitted: commit them on the branch
        git(["add", "-A", "src", "tests"], wt)
        git(["commit", "-q", "-m", f"fix: {problem[:70]}\n\nBuild #{bid} (S87 operator). Cause: {str(out.get('cause', ''))[:200]}\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"], wt)
    changed = [f for f in git(["diff", "--name-only", "main...HEAD"], wt).stdout.split() if f]
    tests_changed = [f for f in changed if f.startswith("tests/")]
    verdict = _test_run(wt, py, tests_changed)
    ok = bool(changed) and bool(out.get("fixed")) and verdict.startswith("passed")
    change = "\n".join(f"- {c}" for c in (out.get("change") or [])[:3]) or "- (no summary)"
    tokens = res.input_tokens + res.output_tokens
    if not ok:
        con.execute("UPDATE operator_builds_s87 SET status='no_fix', cause=?, change_text=?, tests=?, tokens=?, finished_at=? WHERE build_id=?", [str(out.get("cause", ""))[:600], change, verdict, tokens, now, bid])
        return {"build_id": bid, "status": "no_fix", "branch": branch, "tests": verdict}
    text = (f"A fix is ready for: {problem[:200]}\n\nCause: {str(out.get('cause', ''))[:400]}\nChange:\n{change}\nTests: {verdict}\nBranch: {branch} ({len(changed)} file(s)).\n\n"
            "Yes merges it and tags a release (the app takes it at its next start). No leaves the branch as it is and changes nothing.")
    from pflab.entrance import cards
    mid = cards.post_decision_card(con, now, "build_fix", {"build_id": bid, "branch": branch, "problem": problem[:200], "repo": str(repo)}, text, BRANCH_FN, expires_hours=72)
    con.execute("UPDATE operator_builds_s87 SET status='card', cause=?, change_text=?, tests=?, card_msg_id=?, tokens=?, finished_at=? WHERE build_id=?",
                [str(out.get("cause", ""))[:600], change, verdict, mid, tokens, now, bid])
    return {"build_id": bid, "status": "card", "branch": branch, "tests": verdict, "card": mid}


def next_tag(repo: Path, now: datetime) -> str:
    base = f"v{now:%Y.%m.%d}"
    have = set(git(["tag", "--list", base + "*"], repo).stdout.split())
    if base not in have:
        return base
    n = 1
    while f"{base}.{n}" in have:
        n += 1
    return f"{base}.{n}"


def merge_and_tag(con, now: datetime, payload: dict) -> str:
    """Runs ONLY after his Yes (the card framework calls it): merge the fix branch onto origin/main in a throw-away worktree, tag, push. Returns a line for the chat."""
    repo = Path(payload.get("repo") or repo_root())
    branch = str(payload.get("branch") or "")
    if not branch.startswith("fix/"):
        return "Nothing merged: the branch name is not a fix branch."
    git(["fetch", "-q", "origin"], repo)
    base = "origin/main" if git(["rev-parse", "--verify", "-q", "origin/main"], repo).returncode == 0 else "main"
    tmp = workspace.root() / "builds" / f"merge_{payload.get('build_id')}"
    g = git(["worktree", "add", "--detach", str(tmp), base], repo)
    if g.returncode != 0:
        return f"Nothing merged: {g.stderr[:200]}"
    try:
        m = git(["merge", "--no-ff", "-q", "-m", f"Merge {branch}: {str(payload.get('problem', ''))[:60]} (his Yes)", branch], tmp)
        if m.returncode != 0:
            git(["merge", "--abort"], tmp)
            return f"Nothing merged: the branch does not merge cleanly ({m.stderr[:150]}). The branch stays."
        tag = next_tag(repo, now)
        git(["tag", tag], tmp)
        p = git(["push", "origin", "HEAD:refs/heads/main", tag], tmp, timeout=240)
        if p.returncode != 0:
            git(["tag", "-d", tag], tmp)
            return f"Merged locally but the push failed ({p.stderr[:150]}). Nothing was released."
        con.execute("UPDATE operator_builds_s87 SET status='merged', detail=? WHERE build_id=?", [tag, int(payload.get("build_id") or 0)])
        return f"Merged and released as {tag}. The app takes it at its next start."
    finally:
        git(["worktree", "remove", "--force", str(tmp)], repo)
