"""The bounded experiment loop (S67 local): hypothesis -> registered protocol -> baseline -> candidate in the sandbox -> trusted score ->
record -> keep or reject -> the next candidate chosen from the recorded results. The pattern of karpathy/autoresearch, inside this
system's own learner: the same counter (`counter`), the same development and validation periods (`templates.DEV/VAL`; the spent 2022-2025
period is never loaded), the same protocol discipline as `claims.register/test`, the same sandbox (`agents/sandbox.py`).

What the model may touch: the CANDIDATE script only (`compute(data)` returning a `signal`). What it may not: the evaluator (this file,
hashed into the protocol; a change after registration stops the run), the data (cut by the sandbox runner, not by the candidate), the
periods, the thresholds, the counter. The candidate's own claim of success is never read; only the signals it returns are scored here.

The experiment asks one question of an index series: does a rule, deciding each month-end from the rows up to that date only, beat the
simplest comparator (always invested) net of a switching cost, in a development period AND a later validation period, by more than the
bar that rises with the number of variants already searched? Most candidates will fail; a recorded rejection is a result. A kept
candidate is SHADOW research: nothing is wired into the brain as a rule, and the 24-month forward evidence the repo requires is untouched.

Budgets (per run): `MAX_ATTEMPTS` evaluated candidates (the learner's own per-run default of three), `REPAIRS` repair tries per attempt for a
crash, `ATTEMPT_WALL_S` per sandbox trial, `TOTAL_WALL_S` for the run, `MAX_COST_INR` for a paid writer. Stops early when a candidate is kept,
when the data or the sandbox is missing (the experiment waits, nothing is invented), or when a budget is used up.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from pflab.learner import counter
from pflab.learner import templates as tp

MAX_ATTEMPTS = 3
REPAIRS = 1
ATTEMPT_WALL_S = 300
TOTAL_WALL_S = 900
MAX_COST_INR = 50.0
SWITCH_COST = 0.001                    # of the portfolio, each time the position changes
MIN_MONTHS = tp.MIN_MONTHS
COMPARATOR = "always invested"
DEFAULT_DATASET = "index:NIFTY50_TRI"
SPENT_FROM = date(2022, 1, 1)           # the period the repo declares spent: never loaded into an experiment

STATUSES = ("registered", "running", "kept", "rejected", "deferred", "waiting")


def evaluator_sha() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# --- the trusted evaluator ------------------------------------------------------------------------------------------------------------------

def _d(s) -> date:
    return date.fromisoformat(str(s)[:10])


def month_ends(df: pd.DataFrame, start: str, end: str) -> List[date]:
    """The last trading day of each calendar month with rows in [start, end]."""
    s, e = _d(start), _d(end)
    days = sorted(d for d in df["date"] if s <= d <= e)
    last: Dict[Tuple[int, int], date] = {}
    for d in days:
        last[(d.year, d.month)] = d
    return [last[k] for k in sorted(last)]


def walk_dates(df: pd.DataFrame) -> List[date]:
    """Every decision date the experiment scores: month-ends of the development and the validation period, nothing later."""
    return sorted(set(month_ends(df, *tp.DEV)) | set(month_ends(df, *tp.VAL)))


def returns_between(df: pd.DataFrame, dates: List[date]) -> List[Tuple[date, float]]:
    """(decision date, return to the next decision date) for consecutive dates in the list."""
    px = dict(zip(df["date"], df["close"].astype(float)))
    return [(a, px[b] / px[a] - 1.0) for a, b in zip(dates, dates[1:])]


def score_period(df: pd.DataFrame, signals: Dict[str, float], period: Tuple[str, str]) -> dict:
    """Candidate (invested when its signal is above zero, else out, less SWITCH_COST per change) against the comparator (always invested)
    over the period's month-ends. Paired monthly differences; a missing signal is an error, never a zero."""
    dates = month_ends(df, *period)
    rows = returns_between(df, dates)
    cand, base, pos_prev, held = [], [], 1, 0
    for d, r in rows:
        s = signals.get(d.isoformat())
        if s is None or not math.isfinite(s):
            raise ValueError(f"no signal for {d}")
        pos = 1 if s > 0 else 0
        cand.append(pos * r - SWITCH_COST * abs(pos - pos_prev))
        base.append(r)
        pos_prev, held = pos, held + pos
    n = len(rows)
    diff = pd.Series(cand) - pd.Series(base)
    sd = float(diff.std(ddof=1)) if n > 1 else 0.0
    t = float(diff.mean() / (sd / math.sqrt(n))) if n > 1 and sd > 0 else 0.0

    def dd(x):
        eq = (1 + pd.Series(x)).cumprod()
        return float((eq / eq.cummax() - 1).min()) if len(eq) else 0.0
    return {"n_months": n, "mean_excess": float(diff.mean()) if n else 0.0, "t": round(t, 3), "cand_mean": float(pd.Series(cand).mean()) if n else 0.0,
            "base_mean": float(pd.Series(base).mean()) if n else 0.0, "cand_max_drawdown": round(dd(cand), 4), "base_max_drawdown": round(dd(base), 4),
            "exposure": round(held / n, 3) if n else 0.0}


def decide(dev: dict, val: dict, bar_dev: float) -> Tuple[bool, str]:
    """The registered rule: enough months in both periods, the candidate ahead of the comparator in both, t >= the development bar (which
    rises with the variants searched) and >= tp.T_VAL in validation."""
    if dev["n_months"] < MIN_MONTHS or val["n_months"] < MIN_MONTHS:
        return False, f"too few months to say anything (development {dev['n_months']}, validation {val['n_months']}, need {MIN_MONTHS} each)"
    if dev["mean_excess"] <= 0:
        return False, f"behind {COMPARATOR} in development (mean {dev['mean_excess']:+.4f} a month, t {dev['t']})"
    if dev["t"] < max(bar_dev, tp.T_DEV):
        return False, f"ahead in development but not by enough: t {dev['t']} under the bar {bar_dev:.2f}"
    if val["mean_excess"] <= 0:
        return False, f"ahead in development, behind in validation ({val['mean_excess']:+.4f} a month, t {val['t']})"
    if val["t"] < tp.T_VAL:
        return False, f"validation t {val['t']} under {tp.T_VAL}"
    return True, f"ahead of {COMPARATOR} in both periods (t {dev['t']} development, {val['t']} validation) net of switching costs"


# --- registration ---------------------------------------------------------------------------------------------------------------------------

def register(con, proto_dir: Path, now: datetime, *, hypothesis: str, why_it_matters: str, disproof: str, source_kind: str, source_ref: str = "",
             dataset: str = DEFAULT_DATASET, max_attempts: int = MAX_ATTEMPTS) -> int:
    """Commit the question, the comparator, the periods, the metric, the minimum evidence, the stop conditions and the budget BEFORE any
    candidate is seen. Returns the experiment id; the same hypothesis on the same dataset is never registered twice."""
    if source_kind not in ("case", "claim", "data_issue", "process_failure", "investor"):
        raise ValueError("source_kind must be case, claim, data_issue, process_failure or investor")
    if not hypothesis.strip() or not disproof.strip() or not why_it_matters.strip():
        raise ValueError("a hypothesis needs its reason and what would disprove it")
    key = hashlib.sha256(f"{hypothesis.strip().lower()}|{dataset}".encode()).hexdigest()
    old = con.execute("SELECT exp_id FROM learn_experiments WHERE key=?", [key]).fetchone()
    if old:
        return int(old[0])
    from pflab.pm.store import next_id
    eid = next_id(con, "learn_experiments", "exp_id")
    proto = {"exp_id": eid, "registered_at": now.isoformat(timespec="seconds"), "hypothesis": hypothesis.strip(), "why_it_matters": why_it_matters.strip(),
             "would_disprove": disproof.strip(), "source": {"kind": source_kind, "ref": source_ref}, "dataset": dataset,
             "comparator": COMPARATOR, "metric": "paired monthly return difference net of switching cost; t-statistic",
             "periods": {"development": tp.DEV, "validation": tp.VAL, "spent_not_loaded_from": SPENT_FROM.isoformat()},
             "switch_cost": SWITCH_COST, "minimum_evidence": f"{MIN_MONTHS} months in each period",
             "rule": (f"ahead of the comparator in both periods; development t >= max(counter.t_needed(N), {tp.T_DEV}) with N = the tests run including this "
                      f"candidate; validation t >= {tp.T_VAL}"),
             "stop": {"first_kept": True, "max_attempts": max_attempts, "repairs_per_attempt": REPAIRS, "wait_if_data_or_sandbox_missing": True},
             "budget": {"attempt_wall_s": ATTEMPT_WALL_S, "total_wall_s": TOTAL_WALL_S, "max_cost_inr": MAX_COST_INR},
             "tests_run_at_registration": counter.n_tests(con), "evaluator": "src/pflab/learner/experiments.py", "evaluator_sha256": evaluator_sha(),
             "candidate_may_edit": "the candidate script only", "status_on_keep": "shadow research: nothing is wired as a rule"}
    proto_dir.mkdir(parents=True, exist_ok=True)
    p = proto_dir / f"experiment_{eid}.json"
    body = json.dumps(proto, indent=1, sort_keys=True)
    p.write_text(body, encoding="utf-8")
    con.execute("INSERT INTO learn_experiments (exp_id, key, registered_at, hypothesis, why_it_matters, disproof, source_kind, source_ref, dataset, "
                "max_attempts, protocol_path, protocol_sha, evaluator_sha, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'registered')",
                [eid, key, now, hypothesis.strip()[:600], why_it_matters.strip()[:600], disproof.strip()[:600], source_kind, source_ref[:200], dataset,
                 max_attempts, str(p), hashlib.sha256(body.encode()).hexdigest(), proto["evaluator_sha256"]])
    return eid


def _attempt(con, eid: int, n: int, now: datetime, kind: str, status: str, **kw) -> int:
    from pflab.pm.store import next_id
    aid = next_id(con, "learn_attempts", "attempt_id")
    con.execute("INSERT INTO learn_attempts (attempt_id, exp_id, n, made_at, kind, status, code, code_sha, note, error, result_json, seconds, contained, cost_inr) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [aid, eid, n, now, kind, status, kw.get("code"), hashlib.sha256((kw.get("code") or "").encode()).hexdigest() if kw.get("code") else None,
                 (kw.get("note") or "")[:500], (kw.get("error") or "")[:500], json.dumps(kw.get("result"), default=str) if kw.get("result") is not None else None,
                 kw.get("seconds"), kw.get("contained"), kw.get("cost", 0.0)])
    return aid


def attempts(con, eid: int) -> List[dict]:
    cols = ["attempt_id", "n", "kind", "status", "note", "error", "result", "seconds", "contained", "cost_inr", "code"]
    rows = con.execute("SELECT attempt_id, n, kind, status, note, error, result_json, seconds, contained, cost_inr, code FROM learn_attempts "
                       "WHERE exp_id=? ORDER BY attempt_id", [eid]).fetchall()
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        d["result"] = json.loads(d["result"]) if d["result"] else None
        out.append(d)
    return out


# --- the writer's prompt: the next trial is chosen from what was recorded --------------------------------------------------------------------

WRITER_SYSTEM = (
    "You write ONE small Python rule for a research experiment on a daily index series. Reply with JSON only: "
    '{"datasets": ["<the dataset name>"], "code": "...", "test": {"data": {"<dataset name>": [rows]}, "expected": {"signal": value}, "tol": 1e-6}, '
    '"explain": "one sentence: why this rule might work"}. '
    "Rules: code defines def compute(data) where data maps the dataset name to a pandas DataFrame with columns date and close, and returns "
    '{"signal": number}: above 0 means be invested for the next month, 0 or below means be out. compute is called once per month-end with ONLY the rows '
    "up to that date; use only those rows. Allowed imports: numpy, pandas, math. No files, no network. The test case is a tiny made-up series with the "
    "signal you expect on its last row. You are shown every earlier candidate and exactly how it scored: do not repeat one that failed; change one thing "
    "for a reason."
)


def prompt(con, eid: int, dataset: str, history: List[dict]) -> str:
    h, why, dis = con.execute("SELECT hypothesis, why_it_matters, disproof FROM learn_experiments WHERE exp_id=?", [eid]).fetchone()
    lines = [f"HYPOTHESIS: {h}", f"WHY IT MATTERS: {why}", f"WHAT WOULD DISPROVE IT: {dis}", f"DATASET: {dataset}",
             f"COMPARATOR: {COMPARATOR}. A candidate is kept only if it beats it in a development period ({tp.DEV[0]} to {tp.DEV[1]}) and a later validation "
             f"period ({tp.VAL[0]} to {tp.VAL[1]}), net of {SWITCH_COST:.1%} per switch; the bar rises with every variant already tried."]
    if history:
        lines.append("EARLIER CANDIDATES (measured by the evaluator, not claimed):")
        for a in history:
            r = a.get("result") or {}
            lines.append(f"- attempt {a['n']} [{a['status']}] {a['note'] or ''} {a['error'] or ''} "
                         + (f"development {r.get('development')}; validation {r.get('validation')}; decision: {r.get('why')}" if r.get("development") else ""))
            if a.get("code"):
                lines.append("  code: " + a["code"][:600].replace("\n", " | "))
    return "\n".join(lines)


# --- the run --------------------------------------------------------------------------------------------------------------------------------

def _verify_protocol(con, eid: int) -> dict:
    r = con.execute("SELECT status, protocol_path, protocol_sha, evaluator_sha, dataset, max_attempts, hypothesis FROM learn_experiments WHERE exp_id=?", [eid]).fetchone()
    if r is None:
        raise LookupError(f"no experiment #{eid}")
    status, path, sha, esha, dataset, max_attempts, hyp = r
    if status not in ("registered", "deferred", "waiting"):
        raise ValueError(f"experiment #{eid} is {status}: it is not run again")
    if hashlib.sha256(Path(path).read_text(encoding="utf-8").encode()).hexdigest() != sha:
        raise RuntimeError(f"experiment #{eid}: its protocol file changed after registration: not run")
    if esha != evaluator_sha():
        raise RuntimeError(f"experiment #{eid}: the evaluator changed since registration: register the question again")
    return {"dataset": dataset, "max_attempts": int(max_attempts), "hypothesis": hyp}


def _set(con, eid: int, status: str, why: str, now: datetime, **kw) -> None:
    con.execute("UPDATE learn_experiments SET status=?, decision_why=?, decided_at=?, baseline_json=coalesce(?, baseline_json) WHERE exp_id=?",
                [status, why[:600], now if status in ("kept", "rejected", "deferred") else None, kw.get("baseline"), eid])


def run(con, eid: int, root: Path, now: datetime, writer: Callable[[str], str], *, sandbox=None, frame: Optional[pd.DataFrame] = None,
        clock: Callable[[], float] = time.monotonic) -> dict:
    """Run one registered experiment inside its budget. `writer(prompt) -> reply text` is the candidate source (the local model, or the API
    analyst behind its own gate and cap); `frame` is for tests (the dataset's rows). Returns {status, why, attempts}."""
    from pflab.agents import sandbox as sb
    from pflab.agents import workshop as wk
    meta = _verify_protocol(con, eid)
    dataset, max_attempts = meta["dataset"], meta["max_attempts"]
    t_start = clock()
    try:
        box = sandbox or sb.pick()
    except sb.SandboxUnavailable as e:
        _set(con, eid, "waiting", f"waiting for the sandbox: {e}", now)
        return {"status": "waiting", "why": str(e), "attempts": 0}
    try:
        df = frame if frame is not None else wk.load_dataset(dataset, con, root, SPENT_FROM)
    except Exception as e:                                       # the data is missing: wait, invent nothing
        _set(con, eid, "waiting", f"waiting for the data: {type(e).__name__}: {str(e)[:120]}", now)
        return {"status": "waiting", "why": f"no data: {e}", "attempts": 0}
    df = df[df["date"] < SPENT_FROM].sort_values("date").reset_index(drop=True)          # the spent period is never given to a candidate
    dates = walk_dates(df)
    if len(month_ends(df, *tp.DEV)) < MIN_MONTHS + 1 or len(month_ends(df, *tp.VAL)) < MIN_MONTHS + 1:
        _set(con, eid, "waiting", "waiting for history: fewer than the months the protocol needs", now)
        return {"status": "waiting", "why": "not enough history", "attempts": 0}
    con.execute("UPDATE learn_experiments SET status='running' WHERE exp_id=?", [eid])
    # the comparator, scored by trusted code and recorded as attempt 0
    always = {d.isoformat(): 1.0 for d in dates}
    base = {"development": score_period(df, always, tp.DEV), "validation": score_period(df, always, tp.VAL)}
    if not any(a["kind"] == "baseline" for a in attempts(con, eid)):
        _attempt(con, eid, 0, now, "baseline", "ok", note=COMPARATOR, result=base)
    kept, spent_s, cost = None, 0.0, 0.0
    done = sum(1 for a in attempts(con, eid) if a["kind"] == "candidate" and a["status"] in ("kept", "rejected"))
    crashes = 0
    tried = done
    while tried < max_attempts and kept is None:
        if clock() - t_start > TOTAL_WALL_S:
            break
        if cost > MAX_COST_INR:
            break
        history = [a for a in attempts(con, eid) if a["kind"] != "baseline"]
        feedback, outcome = "", None
        for rep in range(REPAIRS + 1):
            reply = writer(prompt(con, eid, dataset, history) + (f"\nYOUR LAST TRY FAILED TO RUN: {feedback}\nFix only that." if feedback else ""))
            cost += float(getattr(writer, "last_cost", 0.0) or 0.0)
            try:
                spec = wk.parse_spec(reply)
                spec = wk.Spec([dataset], spec.code, spec.test, "", spec.explain, spec.params)
                if dataset not in (spec.test.get("data") or {}):
                    raise ValueError(f"the test case needs data for {dataset!r}")
                r = wk.run(spec, {dataset: df}, time_limit=ATTEMPT_WALL_S, sandbox=box, walk=[d.isoformat() for d in dates])
            except sb.SandboxUnavailable as e:
                _set(con, eid, "waiting", f"waiting for the sandbox: {e}", now)
                return {"status": "waiting", "why": str(e), "attempts": tried}
            except Exception as e:
                r, spec = wk.Run(False, [f"{type(e).__name__}: {str(e)[:200]}"]), None
            if r.ok and r.walk:
                outcome = (spec, r)
                break
            feedback = "; ".join(r.problems)[:400] or "no signals were returned"
            _attempt(con, eid, tried + 1, now, "repair" if rep else "candidate", "crash", code=getattr(spec, "code", None), error=feedback,
                     seconds=r.seconds, contained=r.contained)
        if outcome is None:                                       # crashed through its repairs: counts toward the attempts, not the tests
            crashes += 1
            tried += 1
            continue
        spec, r = outcome
        try:
            dev, val = score_period(df, r.walk, tp.DEV), score_period(df, r.walk, tp.VAL)
        except ValueError as e:
            _attempt(con, eid, tried + 1, now, "candidate", "crash", code=spec.code, error=f"the signals were incomplete: {e}", seconds=r.seconds, contained=r.contained)
            crashes += 1
            tried += 1
            continue
        n_tests = counter.n_tests(con) + 1                         # this candidate counts, kept or not
        bar = counter.t_needed(n_tests)
        ok, why = decide(dev, val, bar)
        counter.record(con, now, "learner", "experiment:switch_rule", {"exp_id": eid, "attempt": tried + 1, "code_sha": hashlib.sha256(spec.code.encode()).hexdigest()[:16]},
                       n_dev=dev["n_months"], t_dev=dev["t"], t_val=val["t"], threshold_dev=bar, passed=ok, note=f"experiment:{eid}")
        res = {"development": dev, "validation": val, "dev_bar": round(bar, 3), "tests_in_family": n_tests, "why": why, "baseline": base}
        _attempt(con, eid, tried + 1, now, "candidate", "kept" if ok else "rejected", code=spec.code, note=spec.explain, result=res,
                 seconds=r.seconds, contained=r.contained, cost=0.0)
        tried += 1
        spent_s += r.seconds or 0.0
        if ok:
            kept = res
    bj = json.dumps(base)
    if kept is not None:
        _set(con, eid, "kept", f"a candidate beat {COMPARATOR} in both periods: {kept['why']}. Shadow research only; nothing is wired as a rule", now, baseline=bj)
        status = "kept"
    elif tried >= max_attempts and crashes == tried:
        _set(con, eid, "deferred", f"every candidate failed to run ({crashes} of {tried}); try again with a different writer", now, baseline=bj)
        status = "deferred"
    elif tried >= max_attempts:
        _set(con, eid, "rejected", f"{tried} candidate(s) tried, none beat {COMPARATOR} by the registered rule", now, baseline=bj)
        status = "rejected"
    else:
        _set(con, eid, "deferred", "stopped on the time or cost budget before the attempts were used", now, baseline=bj)
        status = "deferred"
    why = con.execute("SELECT decision_why FROM learn_experiments WHERE exp_id=?", [eid]).fetchone()[0]
    lesson(con, eid, status, why, now)
    return {"status": status, "why": why, "attempts": tried, "crashes": crashes}


def lesson(con, eid: int, status: str, why: str, now: datetime) -> None:
    """What the brain may know afterwards: the outcome, with its limit stated. Never a rule; a rejection is as useful as a keep."""
    from pflab.learner import live
    h = con.execute("SELECT hypothesis FROM learn_experiments WHERE exp_id=?", [eid]).fetchone()[0]
    n = counter.n_tests(con)
    limit = ("This is SHADOW research on index history to 2021: not a forecast, not a rule, and the forward evidence is still required."
             if status == "kept" else "A rejection on this period says this rule did not help here; it does not prove no rule can.")
    live.put(con, "experiment", f"experiment:{eid}", f"Experiment #{eid} {status}: '{h[:160]}'. {why[:240]} {limit} ({n} variants searched so far.)",
             status, f"experiment #{eid}", now)


def local_writer(model: Optional[str] = None) -> Callable[[str], str]:
    """The candidate writer on this PC (the local model, no cost, nothing leaves): the experiment's own system prompt."""
    from pflab.llm import client, registry
    m = model or registry.chosen("general") or "qwen3:8b-q8_0"
    return lambda prompt: client.chat(m, [{"role": "system", "content": WRITER_SYSTEM}, {"role": "user", "content": prompt}],
                                      num_predict=2500, num_ctx=8192).text


def select(con) -> Optional[int]:
    """The next experiment to run: the oldest registered one, then a waiting one whose wait may be over. None when there is nothing."""
    r = con.execute("SELECT exp_id FROM learn_experiments WHERE status IN ('registered', 'waiting') ORDER BY (status='registered') DESC, exp_id LIMIT 1").fetchone()
    return int(r[0]) if r else None


def step(rt, writer: Callable[[str], str], *, sandbox=None) -> dict:
    """One bounded step for the learner's cycle: run the next experiment, if there is one. Nothing is created to look busy."""
    con, now = rt.cursor(), rt.clock()
    eid = select(con)
    if eid is None:
        return {"idle": "no experiment is registered"}
    try:
        return {"experiment": eid, **run(con, eid, rt.data_root, now, writer, sandbox=sandbox)}
    except Exception as e:
        return {"experiment": eid, "status": "not run", "why": f"{type(e).__name__}: {str(e)[:160]}"}


def report(con) -> List[dict]:
    """For the screen and the chat: every experiment, its status and the evidence."""
    out = []
    for eid, h, st, why, src in con.execute("SELECT exp_id, hypothesis, status, decision_why, source_kind FROM learn_experiments ORDER BY exp_id").fetchall():
        a = attempts(con, eid)
        out.append({"id": eid, "hypothesis": h, "status": st, "why": why, "source": src, "candidates": sum(1 for x in a if x["kind"] != "baseline"),
                    "crashes": sum(1 for x in a if x["status"] == "crash"), "kept": sum(1 for x in a if x["status"] == "kept")})
    return out
