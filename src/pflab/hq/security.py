"""The security agent (S62, PLAN A21): it watches the system itself and reports; it never changes code or data.

    egress     every request that left the PC (each paid call's body as sent, each Telegram message) re-checked against
               the egress list: his account / depository / folio / deposit ids, his name, his address words, an
               individual's PAN (fourth letter P; companies' PANs in filings are not his). Any hit is raised at once:
               Telegram and Needs from you. Every HQ round, code only.
    flows      data flowing as it should: the jobs (the health check's failures), open reconciliation breaks, the
               ledger against the newest Kite snapshot. Daily.
    privacy    the repo's tracked files grepped for the same list plus the ledger's amounts (six figures and more,
               Indian and plain grouping) and his stock list's symbols in docs and tests. Daily.
    tests      the test suite run in a subprocess (about 3 minutes). Daily.
    review     new code since the last review read by the slider's `review` model for bugs and leaks; only after the
               privacy grep of that diff passes and the egress check. Weekly (Sunday), about Rs 10.
A finding never quotes the value it found (a kind and a place only). Reports go to Needs from you; a leak also to
Telegram at once.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

PERSON_PAN = re.compile(r"\b[A-Z]{3}P[A-Z]\d{4}[A-Z]\b")
REVIEW_DAY = 6                                    # Sunday
REVIEW_CHARS = 120_000
TEST_TIMEOUT_S = 1200
TEXT_SUFFIX = (".py", ".md", ".toml", ".ps1", ".sh", ".js", ".html", ".css", ".json", ".txt", ".sql", ".yml", ".yaml",
               ".cfg", ".ini")


def hits(text: str, gate, pan: bool = True, names: bool = True) -> List[str]:
    """The kinds of his data found in `text` (never the values)."""
    out = []
    low = text.lower()
    # an id counts with no digit right before or after it (a short deposit id inside a filing's long number is not his;
    # the gate before sending stays stricter and blocks any substring)
    if any(re.search(r"(?<!\d)" + re.escape(i) + r"(?!\d)", text) for i in gate.ids):
        out.append("an account, depository, folio or deposit id")
    if names and any(re.search(r"\b" + re.escape(n) + r"\b", low) for n in gate.names):
        out.append("his name")
    if names and any(re.search(r"\b" + re.escape(a) + r"\b", low) for a in gate.address):
        out.append("his address words")
    if pan and PERSON_PAN.search(text):
        out.append("an individual's PAN")
    return out


def _last(con, kind: str) -> Optional[str]:
    r = con.execute("SELECT upto FROM sec_runs WHERE kind=? AND upto IS NOT NULL ORDER BY run_id DESC LIMIT 1", [kind]).fetchone()
    return r[0] if r else None


def _run(con, kind: str, status: str, upto: Optional[str], detail: dict, now: datetime, cost: float = 0.0) -> int:
    from pflab.pm.store import next_id
    rid = next_id(con, "sec_runs", "run_id")
    con.execute("INSERT INTO sec_runs VALUES (?,?,?,?,?,?,?)", [rid, now, kind, status, upto, json.dumps(detail, default=str)[:8000], cost])
    return rid


def report(rt, kind: str, severity: str, text: str, ref: str, now: datetime, telegram: bool = False) -> Optional[int]:
    """One finding: kept, asked under Needs from you once per ref, and on Telegram at once when it is a leak."""
    from pflab.agents import questions as qs
    from pflab.hq import messenger
    from pflab.pm.store import next_id
    con = rt.cursor()
    if con.execute("SELECT 1 FROM sec_findings WHERE kind=? AND ref=?", [kind, ref]).fetchone():
        return None
    fid = next_id(con, "sec_findings", "find_id")
    q = qs.ask(con, "security", f"security:{kind}:{ref}", f"Security ({kind}, {severity}): {text} Answer 'seen' when "
                                                          "noted.", now)
    con.execute("INSERT INTO sec_findings VALUES (?,?,?,?,?,?,?,?)", [fid, now, kind, severity, text[:1000], ref, q, False])
    if telegram:
        messenger.send_now(rt, f"Security: {text}", "security", dedup_key=f"security:{kind}:{ref}")
        con.execute("UPDATE sec_findings SET sent=true WHERE find_id=?", [fid])
    return fid


# --- egress, every round -------------------------------------------------------------------------------------------------

def egress(rt, gate=None) -> dict:
    from pflab.hq import egress as eg
    con, now = rt.cursor(), rt.clock()
    gate = gate or eg.load(con)
    last = _last(con, "egress")
    a0, m0 = (int(x) for x in (last or "0:0").split(":"))
    found, old = 0, []                                   # old: the first run's look back over all history, one summary
    calls = con.execute("SELECT call_id, agent, topic, request_json FROM api_calls WHERE call_id > ? AND status <> 'over_limit' "
                        "ORDER BY call_id", [a0]).fetchall()
    for cid, agent, topic, body in calls:
        k = hits(body or "", gate)
        if k:
            found += 1
            if last is None:
                old.append((f"call #{cid} ({agent or topic or 'analyst'})", k))
                continue
            report(rt, "egress", "high", f"a request to Anthropic (call #{cid}, {agent or topic or 'analyst'}) carried "
                                         f"{', '.join(k)}. Check what sent it before the next run.", f"call:{cid}", now,
                   telegram=True)
    msgs = con.execute("SELECT msg_id, kind, text FROM outbox WHERE msg_id > ? ORDER BY msg_id", [m0]).fetchall()
    for mid, kind, text in msgs:
        k = hits(text or "", gate, names=False)                 # his messages may name him; ids and PAN never
        if k and kind != "security":
            found += 1
            if last is None:
                old.append((f"message #{mid} ({kind})", k))
                continue
            report(rt, "egress", "high", f"a Telegram message (#{mid}, {kind}) carried {', '.join(k)}.", f"msg:{mid}", now,
                   telegram=False)
    if old:
        kinds = sorted({x for _, k in old for x in k})
        report(rt, "egress", "medium", f"the first look back over everything sent before the security agent existed found "
                                       f"{len(old)} item(s) carrying {', '.join(kinds)}: "
                                       + ", ".join(w for w, _ in old[:15]) + (" and more" if len(old) > 15 else "")
                                       + ". From now on each new one is raised at once.", "baseline", now)
    a1 = calls[-1][0] if calls else a0
    m1 = msgs[-1][0] if msgs else m0
    if calls or msgs:
        _run(con, "egress", "fail" if found else "ok", f"{a1}:{m1}", {"calls": len(calls), "messages": len(msgs),
                                                                      "hits": found}, now)
    return {"calls": len(calls), "messages": len(msgs), "hits": found}


# --- flows, daily -------------------------------------------------------------------------------------------------------

def flows(rt) -> dict:
    from pflab.service import health, jobs
    con, now = rt.cursor(), rt.clock()
    out = {}
    ctx = jobs.Ctx(con, now, rt.pm_dir, rt.data_root, rt.repo, secrets=rt.secrets)
    bad = [i for i in health.check(ctx) if i.status == "FAIL"]
    for i in bad:
        report(rt, "flows", "medium", f"{i.name}: {i.detail}", f"health:{i.name}:{now:%Y-%m-%d}", now)
    out["health_fail"] = len(bad)
    open_b = con.execute("SELECT count(*) FROM recon_breaks WHERE coalesce(status, 'open') = 'open' AND created_at >= ?",
                         [now - timedelta(days=7)]).fetchone()[0]
    if open_b:
        report(rt, "flows", "medium", f"{open_b} reconciliation break(s) open from the last 7 days (recon_breaks): the "
                                      "ledger and a source disagree.", f"recon:{now:%Y-%m-%d}", now)
    out["recon_open"] = int(open_b)
    try:
        from pflab.pm import today
        td = today.build(con, now.date())["today"]
        d = td.get("diffs", [])
        snap = td.get("snapshot_at")
        snap = datetime.fromisoformat(str(snap)[:19]) if snap else None      # the view gives it as text
        if d and snap and (now - snap).days <= 2 and td.get("documents_to") and (now.date() - td["documents_to"]).days > 35:
            report(rt, "flows", "low", f"Kite and the statements differ on {len(d)} holding(s) and the statements end "
                                       f"{td['documents_to']}: new statements will close it.", f"kite:{now:%Y-%m}", now)
        out["kite_diffs"] = len(d)
    except Exception as e:                                   # no ledger or no snapshot yet: said, not hidden
        out["kite_diffs"] = f"not checked: {type(e).__name__}"
    _run(con, "flows", "warn" if bad or open_b else "ok", None, out, now)
    return out


# --- privacy grep, daily ------------------------------------------------------------------------------------------------

def tracked(repo: Path) -> List[Path]:
    r = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True, timeout=60)
    return [repo / p for p in r.stdout.splitlines() if p.lower().endswith(TEXT_SUFFIX)]


def indian(n: int) -> str:
    s = str(n)
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + parts + [tail])


def amounts(con) -> List[str]:
    """The ledger's distinctive rupee amounts (six figures or more, not round thousands), as written in text."""
    vals = set()
    for (v,) in con.execute("SELECT DISTINCT abs(round(amount)) FROM events WHERE abs(amount) >= 100000 UNION "
                            "SELECT DISTINCT abs(round(amount)) FROM cash_ledger WHERE abs(amount) >= 100000").fetchall():
        if v and int(v) % 1000:
            vals.add(int(v))
    for (v,) in con.execute("SELECT DISTINCT abs(round(principal)) FROM fds WHERE principal >= 100000").fetchall():
        if v and int(v) % 1000:
            vals.add(int(v))
    return sorted({f for v in vals for f in (indian(v), f"{v:,}", str(v))})


def symbols(con=None) -> List[str]:
    """His stock list as the repo must never show it: symbols (4+ letters), ISINs and, with the ledger, the companies'
    names without their legal endings (S63: the first clean found names and ISINs the symbols missed)."""
    from pflab.plan import guards as gd
    lst = gd.stock_list()
    out = {s["symbol"] for s in lst if len(s["symbol"]) >= 4} | {s["isin"] for s in lst if s.get("isin")}
    if con is not None and lst:
        isins = [s["isin"] for s in lst if s.get("isin")]
        for (n,) in con.execute(f"SELECT name FROM instruments WHERE isin IN ({','.join('?' * len(isins))})", isins).fetchall():
            core = re.sub(r"\b(limited|ltd\.?|industries|india|the|company|corporation|of)\b", "", n or "", flags=re.I).strip(" .,")
            if len(core) >= 5:
                out.add(core)
    return sorted(out)


def grep(files: Iterable[Path], gate, money: List[str], syms: List[str], repo: Path) -> List[Tuple[str, str]]:
    """(place, kind) for each file line carrying his data (S63: list names count in every file, code too)."""
    out = []
    num = [re.compile(r"(?<![\d,])" + re.escape(m) + r"(?![\d,])") for m in money]
    sym = [re.compile(r"\b" + re.escape(s) + r"\b", re.I if " " in s or s[:1].islower() else 0) for s in syms]
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = p.relative_to(repo).as_posix()
        for i, line in enumerate(text.splitlines(), 1):
            k = hits(line, gate)
            if any(rx.search(line) for rx in num):
                k.append("a ledger amount")
            if any(rx.search(line) for rx in sym):
                k.append("a stock-list name")
            for x in k:
                out.append((f"{rel}:{i}", x))
    return out


def privacy(rt, gate=None) -> dict:
    from pflab.hq import egress as eg
    con, now = rt.cursor(), rt.clock()
    gate = gate or eg.load(con)
    found = grep(tracked(Path(rt.repo)), gate, amounts(con), symbols(con), Path(rt.repo))
    kinds = sorted({k for _, k in found})
    serious = [(p, k) for p, k in found if k != "his name"]   # the docs address him by name: S63 decides; low until then
    if found:
        show = serious or found
        places = ", ".join(sorted({p for p, _ in show})[:12])
        report(rt, "privacy", "high" if serious else "low",
               f"{len(found)} line(s) in the repo carry {', '.join(kinds)}"
               + (f" ({len(serious)} beyond his name)" if serious and len(serious) < len(found) else "") + f": {places}"
               + (" and more" if len({p for p, _ in show}) > 12 else "") + ". Nothing is pushed until they go.",
               f"privacy:{now:%Y-%m-%d}", now, telegram=bool(serious))
    _run(con, "privacy", "fail" if found else "ok", None, {"lines": len(found), "kinds": kinds}, now)
    return {"lines": len(found), "kinds": kinds}


# --- tests, daily -------------------------------------------------------------------------------------------------------

def python_of(repo: Path) -> str:
    v = Path(repo) / ".venv" / "Scripts" / "python.exe"
    return str(v) if v.exists() else sys.executable


def tests(rt, run=subprocess.run) -> dict:
    con, now = rt.cursor(), rt.clock()
    out = ""
    try:
        r = run([python_of(Path(rt.repo)), "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=rt.repo, capture_output=True,
                text=True, timeout=TEST_TIMEOUT_S)
        out = r.stdout or ""
        ok = r.returncode == 0
        line = ([x for x in out.splitlines() if x.strip()][-1:] or ["(no output)"])[0][:300]
    except subprocess.TimeoutExpired:
        ok, line = False, f"timed out after {TEST_TIMEOUT_S} s"
    if not ok:
        failed = [x[7:90] for x in out.splitlines() if x.startswith("FAILED")][:8]
        report(rt, "tests", "high", f"the test suite failed: {line}" + (f" ({'; '.join(failed)})" if failed else ""),
               f"tests:{now:%Y-%m-%d}", now)
    _run(con, "tests", "ok" if ok else "fail", None, {"summary": line}, now)
    return {"ok": ok, "summary": line}


# --- code review, weekly ------------------------------------------------------------------------------------------------

REVIEW_SYSTEM = (
    "You review new code of a private investor's portfolio system (Python; it reads his ledger and sends some text to "
    "an API). Find real problems only: bugs that give wrong numbers or crash, data that could leak (account ids, names, "
    "statements sent out, secrets printed or logged), a money path that could act without the investor, point-in-time "
    "errors (using data dated after the decision). Skip style. Reply with JSON only; an empty list when nothing is wrong.")
REVIEW_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["findings"],
                 "properties": {"findings": {"type": "array", "items": {
                     "type": "object", "additionalProperties": False, "required": ["file", "severity", "problem"],
                     "properties": {"file": {"type": "string"}, "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                                    "problem": {"type": "string"}}}}}}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=120).stdout.strip()


def review_due(con, now: datetime) -> bool:
    if now.weekday() != REVIEW_DAY:
        return False
    r = con.execute("SELECT max(run_at) FROM sec_runs WHERE kind='review'").fetchone()[0]
    return r is None or r.date() < now.date()


def review(rt, client=None, gate=None, draft=None) -> dict:
    """The diff since the last reviewed commit (code folders only), read by the review model."""
    from pflab.hq import egress as eg, governor as gv, llm, models
    con, now, repo = rt.cursor(), rt.clock(), Path(rt.repo)
    gate = gate or eg.load(con)
    head = _git(repo, "rev-parse", "HEAD")
    base = _last(con, "review") or (_git(repo, "log", "--since=7.days", "--format=%H").splitlines() or [head])[-1]
    if base == head:
        _run(con, "review", "ok", head, {"why": "no new commits"}, now)
        return {"reviewed": 0}
    diff = _git(repo, "diff", f"{base}..{head}", "--", "src", "tools", "tests", "configs")
    if not diff:
        _run(con, "review", "ok", head, {"why": "no code changed"}, now)
        return {"reviewed": 0}
    from pflab.hq import brain
    diff = PERSON_PAN.sub("[PAN]", brain.unnamed(diff, gate.names))   # the code's docstrings name him; tests hold PANs
    bad = [k for line in diff.splitlines() for k in hits(line, gate)]
    money = amounts(con)
    if bad or any(m in diff for m in money):                  # a real id, his address or a ledger amount in code
        report(rt, "review", "high", "the new code carries his data (the privacy grep found it in the diff): not sent "
                                     "for review until it is removed.", f"review-blocked:{head[:12]}", now, telegram=True)
        _run(con, "review", "blocked", None, {"kinds": sorted(set(bad))}, now)
        return {"reviewed": 0, "blocked": True}
    text = diff[:REVIEW_CHARS]
    if draft is None:
        from pflab.hq import service
        client = client or service.client(rt)
        model = models.model_id("review", rt.settings)

        def draft(system, prompt, schema):
            p = {"model": model, "max_tokens": 4000, "system": system,
                 "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
                 "messages": [{"role": "user", "content": prompt}]}
            # code, not his data: his list was checked above line by line (the generic patterns would read the
            # egress module's own examples as account numbers)
            s = llm.call(con, "worker", p, client, now=now, mode=rt.settings.get("brain", "economy"), private_text="",
                         gate=gate, doc_kinds=(), topic="security review", question=f"review {base[:8]}..{head[:8]}")
            draft.cost = s.cost_inr
            return s.json()
        draft.cost = 0.0
    out = draft(REVIEW_SYSTEM, f"DIFF {base[:10]}..{head[:10]}" + (" (cut)" if len(diff) > REVIEW_CHARS else "") + f":\n{text}",
                REVIEW_SCHEMA)
    fs = [f for f in (out.get("findings") or []) if f.get("severity") in ("high", "medium")][:6]
    if fs:
        report(rt, "review", max((f["severity"] for f in fs), key=["low", "medium", "high"].index),
               "the weekly code review found: " + " | ".join(f"{f['file'][:60]}: {f['problem'][:200]}" for f in fs),
               f"review:{head[:12]}", now)
    _run(con, "review", "warn" if fs else "ok", head, {"findings": out.get("findings", [])[:20], "base": base}, now,
         float(getattr(draft, "cost", 0.0)))
    return {"reviewed": 1, "findings": len(fs), "cost": float(getattr(draft, "cost", 0.0)), "model": gv.SONNET}


def uncontained(rt) -> dict:
    """S64: workshop calculations that ran outside Docker (the local subprocess is no security boundary): a count, and
    whether Docker answers now. Reported, never an alert by itself."""
    import json as _json
    from pflab.agents import sandbox, workshop
    n = total = 0
    for p in workshop.folder(rt.pm_dir).glob("*/meta.json"):
        try:
            m = _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        total += 1
        n += int(m.get("contained") is False and m.get("status") in ("checked", "disputed"))
    return {"uncontained_runs": n, "of": total, "docker_now": sandbox.available(force=True)}


def job(ctx) -> dict:
    """The `security` job (daily): flows, privacy grep, the tests; the code review on Sundays."""
    from pflab.hq import desk, service
    rt = desk.from_ctx(ctx)
    out = {}
    parts = [("egress", lambda: egress(rt)), ("flows", lambda: flows(rt)), ("privacy", lambda: privacy(rt)),
             ("sandbox", lambda: uncontained(rt)), ("tests", lambda: tests(rt))]
    if review_due(rt.cursor(), rt.clock()) and service.paid_allowed(rt):
        parts.append(("review", lambda: review(rt)))
    for name, fn in parts:
        try:
            out[name] = fn()
        except Exception as e:                               # one part failing is itself reported
            out[name] = f"failed: {type(e).__name__}: {str(e)[:200]}"
    return {k: (v if isinstance(v, (int, float, str)) else str(v)[:300]) for k, v in out.items()}


def status(con, limit: int = 10) -> str:
    runs = con.execute("SELECT kind, max(run_at), arg_max(status, run_at) FROM sec_runs GROUP BY kind ORDER BY kind").fetchall()
    lines = ["Last checks: " + ("; ".join(f"{k} {str(a)[:16]} {s}" for k, a, s in runs) or "none yet")]
    for at, kind, sev, text in con.execute("SELECT found_at, kind, severity, text FROM sec_findings ORDER BY find_id DESC "
                                           "LIMIT ?", [limit]).fetchall():
        lines.append(f"{str(at)[:16]} [{kind}, {sev}] {text[:200]}")
    return "\n".join(lines)


def push_check(repo: Path) -> int:
    """S63: the pre-push hook (`.githooks/pre-push`): the privacy grep over the tracked files; 1 blocks the push.
    The ledger is read read-only; when it cannot be read (the dashboard holds it) the push is blocked too."""
    import duckdb
    from pflab.hq import egress as eg
    from pflab.pm import store
    try:
        con = duckdb.connect(str(store.db_path()), read_only=True)
    except Exception as e:
        print(f"push blocked: the ledger could not be read for the privacy grep ({type(e).__name__}); close the "
              "dashboard and push again")
        return 1
    try:
        found = grep(tracked(repo), eg.load(con), amounts(con), symbols(con), repo)
    finally:
        con.close()
    for p, k in found[:40]:
        print(f"  {p}: {k}")
    if found:
        print(f"push blocked: {len(found)} line(s) carry the investor's data (kinds above, never the values)")
        return 1
    print("privacy grep: clean")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(push_check(Path(__file__).resolve().parents[3]))
