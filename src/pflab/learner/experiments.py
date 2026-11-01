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

import re

import pandas as pd

from pflab.learner import contracts
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

STATUSES = ("registered", "running", "kept", "rejected", "deferred", "waiting", "unsupported")

import threading
_LIVE: set = set()                      # experiments THIS process is running: a wake must not reap them; a dead process owns none
_LIVE_LOCK = threading.Lock()


def reap(con, now: datetime) -> int:
    """An experiment left `running` by a process that died goes back to `registered`: every attempt already recorded stays (and counted), and
    the run carries on from the attempts left. One that this process is still running is left alone."""
    with _LIVE_LOCK:
        mine = set(_LIVE)
    rows = [r[0] for r in con.execute("SELECT exp_id FROM learn_experiments WHERE status='running'").fetchall() if r[0] not in mine]
    for eid in rows:
        con.execute("UPDATE learn_experiments SET status='registered', decision_why=? WHERE exp_id=?",
                    [f"interrupted when the system closed ({now:%Y-%m-%d %H:%M}); continues from its recorded attempts", eid])
    return len(rows)


def evaluator_sha() -> str:
    """The trusted evaluator: this file and the contracts it dispatches to (a change to either after registration stops the run)."""
    h = hashlib.sha256(Path(__file__).read_bytes())
    h.update(Path(contracts.__file__).read_bytes())
    return h.hexdigest()


def score(contract: str, df: pd.DataFrame, signals: Dict[str, float], period: Tuple[str, str]) -> dict:
    """A period scored by the experiment's own contract. A contract this code does not know is an error, never a default."""
    if contract == "index_timing":
        return score_period(df, signals, period)
    if contract == "deployment":
        return contracts.score_deployment(df, signals, period, month_ends)
    raise ValueError(f"no evaluator for contract {contract!r}")


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


def next_day(days: List[date], d: date) -> Optional[date]:
    """The first trading day after `d`: a decision made on d's close is executed at the next session's close, never d's own."""
    import bisect
    i = bisect.bisect_right(days, d)
    return days[i] if i < len(days) else None


def returns_between(df: pd.DataFrame, dates: List[date]) -> List[Tuple[date, float]]:
    """(decision date, return held from the session after it to the session after the next decision date). The signal for d sees rows up to d
    only (the information cutoff); it is traded one session later (audit 2026-10-30: scoring from d's own close credited a price no one could get).
    A pair whose later execution day is not in the data is left out."""
    px = dict(zip(df["date"], df["close"].astype(float)))
    days = sorted(px)
    out = []
    for a, b in zip(dates, dates[1:]):
        ea, eb = next_day(days, a), next_day(days, b)
        if ea is None or eb is None or ea > b:
            continue
        out.append((a, px[eb] / px[ea] - 1.0))
    return out


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

    def dd(x):                                             # from the starting capital (1.0): a first-month loss is a drawdown (audit F5, 2026-10-30)
        eq = pd.concat([pd.Series([1.0]), (1 + pd.Series(x, dtype=float)).cumprod()], ignore_index=True)
        return float((eq / eq.cummax() - 1).min())
    return {"n_months": n, "mean_excess": float(diff.mean()) if n else 0.0, "t": round(t, 3), "cand_mean": float(pd.Series(cand).mean()) if n else 0.0,
            "base_mean": float(pd.Series(base).mean()) if n else 0.0, "cand_max_drawdown": round(dd(cand), 4), "base_max_drawdown": round(dd(base), 4),
            "exposure": round(held / n, 3) if n else 0.0}


def decide(dev: dict, val: dict, bar_dev: float, comparator: str = COMPARATOR) -> Tuple[bool, str]:
    """The registered rule: enough months in both periods, the candidate ahead of the comparator in both, t >= the development bar (which
    rises with the variants searched) and >= tp.T_VAL in validation."""
    if dev["n_months"] < MIN_MONTHS or val["n_months"] < MIN_MONTHS:
        return False, f"too few months to say anything (development {dev['n_months']}, validation {val['n_months']}, need {MIN_MONTHS} each)"
    if dev["mean_excess"] <= 0:
        return False, f"behind {comparator} in development (mean {dev['mean_excess']:+.4f}, t {dev['t']})"
    if dev["t"] < max(bar_dev, tp.T_DEV):
        return False, f"ahead in development but not by enough: t {dev['t']} under the bar {bar_dev:.2f}"
    if val["mean_excess"] <= 0:
        return False, f"ahead in development, behind in validation ({val['mean_excess']:+.4f}, t {val['t']})"
    if val["t"] < tp.T_VAL:
        return False, f"validation t {val['t']} under {tp.T_VAL}"
    return True, f"ahead of {comparator} in both periods (t {dev['t']} development, {val['t']} validation) net of costs"


# --- registration ---------------------------------------------------------------------------------------------------------------------------

def register(con, proto_dir: Path, now: datetime, *, hypothesis: str, why_it_matters: str, disproof: str, source_kind: str, source_ref: str = "",
             dataset: str = DEFAULT_DATASET, max_attempts: int = MAX_ATTEMPTS, contract: Optional[str] = None) -> int:
    """Commit the question, the comparator, the periods, the metric, the minimum evidence, the stop conditions and the budget BEFORE any
    candidate is seen. Returns the experiment id; the same hypothesis on the same dataset is never registered twice. `contract` names the
    evaluation (`learner/contracts.py`); a hypothesis no contract fits is recorded with status `unsupported` and the reason, and is never run
    through another contract's template."""
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
    try:
        cname = contracts.resolve(hypothesis, contract)
    except contracts.Unsupported as e:
        con.execute("INSERT INTO learn_experiments (exp_id, key, registered_at, hypothesis, why_it_matters, disproof, source_kind, source_ref, dataset, "
                    "max_attempts, protocol_path, protocol_sha, evaluator_sha, status, decision_why, decided_at, contract) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'unsupported', ?, ?, NULL)",
                    [eid, key, now, hypothesis.strip()[:600], why_it_matters.strip()[:600], disproof.strip()[:600], source_kind, source_ref[:200], dataset,
                     0, "", "", evaluator_sha(), str(e)[:600], now])
        return eid
    c = contracts.CONTRACTS[cname]
    proto = {"exp_id": eid, "registered_at": now.isoformat(timespec="seconds"), "hypothesis": hypothesis.strip(), "why_it_matters": why_it_matters.strip(),
             "would_disprove": disproof.strip(), "source": {"kind": source_kind, "ref": source_ref}, "dataset": dataset,
             "contract": cname, "comparator": c.comparator, "metric": c.metric,
             "assumptions": ({"cash_rate_pa": contracts.CASH_RATE_PA, "cost_bps": contracts.COST_BPS, "horizon_months": contracts.HORIZON} if cname == "deployment" else {}),
             "periods": {"development": tp.DEV, "validation": tp.VAL, "spent_not_loaded_from": SPENT_FROM.isoformat()},
             "switch_cost": SWITCH_COST, "minimum_evidence": f"{MIN_MONTHS} {c.min_text}",
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
                "max_attempts, protocol_path, protocol_sha, evaluator_sha, status, contract) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'registered', ?)",
                [eid, key, now, hypothesis.strip()[:600], why_it_matters.strip()[:600], disproof.strip()[:600], source_kind, source_ref[:200], dataset,
                 max_attempts, str(p), hashlib.sha256(body.encode()).hexdigest(), proto["evaluator_sha256"], cname])
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
    "You write ONE small Python rule for a research experiment on a daily index series. Reply in exactly this form and nothing else:\n"
    "WHY: one sentence on why this rule might work\n"
    "```python\n<the code>\n```\n"
    "The code defines def compute(data) where data maps the dataset name to a pandas DataFrame with columns date and close, and returns "
    '{"signal": number}: above 0 means be invested for the next month, 0 or below means be out. compute is called once per month-end with ONLY the rows '
    "up to that date; use only those rows, never assume a length (check len first). Do not modify the input frame. Allowed imports: numpy, pandas, math. "
    "The frame holds DAILY rows (a month is about 21 rows, a year about 252). "
    "No files, no network. You are shown every earlier candidate and exactly how it scored: do not repeat one that failed; change one thing for a reason."
)

FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S)


def parse_reply(text: str) -> Tuple[str, str]:
    """(code, why) from the writer's reply: the first fenced block, else the whole reply if it already is a module. A model's thinking, if
    any, is dropped first. Raises ValueError when there is no code."""
    t = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    m = FENCE.search(t)
    code = (m.group(1) if m else t if "def compute" in t else "").strip("\n")
    if "def compute" not in code:
        raise ValueError("the reply holds no code with def compute(data)")
    w = re.search(r"WHY:\s*(.+)", t)
    return code + "\n", (w.group(1).strip() if w else "")[:300]


def contract_of(con, eid: int) -> str:
    r = con.execute("SELECT contract FROM learn_experiments WHERE exp_id=?", [eid]).fetchone()
    return (r[0] if r and r[0] else contracts.DEFAULT)               # experiments registered before S68 are index timing


def prompt(con, eid: int, dataset: str, history: List[dict]) -> str:
    h, why, dis = con.execute("SELECT hypothesis, why_it_matters, disproof FROM learn_experiments WHERE exp_id=?", [eid]).fetchone()
    cname = contract_of(con, eid)
    c = contracts.CONTRACTS[cname]
    costs = f"net of {SWITCH_COST:.1%} per switch" if cname == "index_timing" else f"net of {contracts.COST_BPS:.0f} basis points per rupee invested"
    lines = [f"CONTRACT: {cname}", f"HYPOTHESIS: {h}", f"WHY IT MATTERS: {why}", f"WHAT WOULD DISPROVE IT: {dis}", f"DATASET: {dataset}",
             f"COMPARATOR: {c.comparator}. A candidate is kept only if it beats it in a development period ({tp.DEV[0]} to {tp.DEV[1]}) and a later validation "
             f"period ({tp.VAL[0]} to {tp.VAL[1]}), {costs}; the bar rises with every variant already tried."]
    if history:
        lines.append("EARLIER CANDIDATES (measured by the evaluator, not claimed):")
        for a in history:
            r = a.get("result") or {}
            # (audit F5) only the development result goes back to the writer: a validation result fed into the next try would make the
            # validation period part of the search, no longer unseen. The decision says only whether it passed, not by how much.
            lines.append(f"- attempt {a['n']} [{a['status']}] {a['note'] or ''} {a['error'] or ''} "
                         + (f"development {r.get('development')}; decision: {'kept' if a['status'] == 'kept' else 'not kept'}" if r.get("development") else ""))
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
    with _LIVE_LOCK:
        _LIVE.add(eid)
    try:
        return _run(con, eid, root, now, writer, sandbox, frame, clock, dataset, max_attempts)
    finally:
        with _LIVE_LOCK:
            _LIVE.discard(eid)


def _run(con, eid: int, root: Path, now: datetime, writer, sandbox, frame, clock, dataset: str, max_attempts: int) -> dict:
    from pflab.agents import sandbox as sb
    from pflab.agents import workshop as wk
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
    cname = contract_of(con, eid)
    comparator = contracts.CONTRACTS[cname].comparator
    always = contracts.baseline_signals(cname, dates)
    base = {"development": score(cname, df, always, tp.DEV), "validation": score(cname, df, always, tp.VAL)}
    if not any(a["kind"] == "baseline" for a in attempts(con, eid)):
        _attempt(con, eid, 0, now, "baseline", "ok", note=comparator, result=base)
    # (audit) the budget survives a restart: every attempt number used (kept, rejected, crashed or duplicate), the money and the seconds already
    # spent are read back from the record, so an interrupted run resumes inside the SAME budget instead of a fresh one
    prior = [a for a in attempts(con, eid) if a["kind"] != "baseline"]
    tried = max((int(a["n"]) for a in prior), default=0)
    cost = sum(float(a.get("cost_inr") or 0.0) for a in prior)
    used_s = sum(float(a.get("seconds") or 0.0) for a in prior)
    kept, spent_s = None, 0.0
    crashes = 0
    while tried < max_attempts and kept is None:
        if clock() - t_start + used_s > TOTAL_WALL_S:
            break
        if cost > MAX_COST_INR:
            break
        history = [a for a in attempts(con, eid) if a["kind"] != "baseline"]
        feedback, outcome = "", None
        for rep in range(REPAIRS + 1):
            reply = writer(prompt(con, eid, dataset, history) + (f"\nYOUR LAST TRY FAILED TO RUN: {feedback}\nFix only that." if feedback else ""))
            step_cost = float(getattr(writer, "last_cost", 0.0) or 0.0)
            cost += step_cost
            try:
                code, why_w = parse_reply(reply)
                smoke = [{"date": d.isoformat(), "close": float(c)} for d, c in zip(df["date"][:60], df["close"][:60])]      # trusted rows, not the model's
                spec = wk.Spec([dataset], code, {"data": {dataset: smoke}, "expected": {}}, "", why_w)
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
                     seconds=r.seconds, contained=r.contained, cost=step_cost)
        if outcome is None:                                       # crashed through its repairs: counts toward the attempts, not the tests
            crashes += 1
            tried += 1
            continue
        spec, r = outcome
        sha = hashlib.sha256(spec.code.encode()).hexdigest()
        if any(a.get("code") and hashlib.sha256(a["code"].encode()).hexdigest() == sha for a in attempts(con, eid) if a["kind"] != "baseline"):
            # the same code again is not a new variant: it is not scored again and does not count as a test; it uses an attempt
            _attempt(con, eid, tried + 1, now, "candidate", "duplicate", code=spec.code, error="identical to an earlier candidate: not scored again",
                     seconds=r.seconds, contained=r.contained)
            tried += 1
            continue
        try:
            dev, val = score(cname, df, r.walk, tp.DEV), score(cname, df, r.walk, tp.VAL)
        except ValueError as e:
            _attempt(con, eid, tried + 1, now, "candidate", "crash", code=spec.code, error=f"the signals were incomplete: {e}", seconds=r.seconds, contained=r.contained)
            crashes += 1
            tried += 1
            continue
        n_tests = counter.n_tests(con) + 1                         # this candidate counts, kept or not
        bar = counter.t_needed(n_tests)
        ok, why = decide(dev, val, bar, comparator)
        counter.record(con, now, "learner", "experiment:switch_rule" if cname == "index_timing" else f"experiment:{cname}", {"exp_id": eid, "attempt": tried + 1, "code_sha": hashlib.sha256(spec.code.encode()).hexdigest()[:16]},
                       n_dev=dev["n_months"], t_dev=dev["t"], t_val=val["t"], threshold_dev=bar, passed=ok, note=f"experiment:{eid}")
        res = {"development": dev, "validation": val, "dev_bar": round(bar, 3), "tests_in_family": n_tests, "why": why, "baseline": base}
        _attempt(con, eid, tried + 1, now, "candidate", "kept" if ok else "rejected", code=spec.code, note=spec.explain, result=res,
                 seconds=r.seconds, contained=r.contained, cost=step_cost)
        tried += 1
        spent_s += r.seconds or 0.0
        if ok:
            kept = res
    bj = json.dumps(base)
    if kept is not None:
        _set(con, eid, "kept", f"a candidate beat {comparator} in both periods: {kept['why']}. Shadow research only; nothing is wired as a rule", now, baseline=bj)
        status = "kept"
    elif tried >= max_attempts and crashes == tried:
        _set(con, eid, "deferred", f"every candidate failed to run ({crashes} of {tried}); try again with a different writer", now, baseline=bj)
        status = "deferred"
    elif tried >= max_attempts:
        _set(con, eid, "rejected", f"{tried} candidate(s) tried, none beat {comparator} by the registered rule", now, baseline=bj)
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
    def write(prompt: str) -> str:
        c = re.match(r"CONTRACT: (\w+)", prompt)
        system = contracts.CONTRACTS[c.group(1)].writer_system if c and c.group(1) in contracts.CONTRACTS else WRITER_SYSTEM
        return client.chat(m, [{"role": "system", "content": system}, {"role": "user", "content": prompt}], num_predict=2500, num_ctx=8192, purpose="experiment_code").text
    return write


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
    except RuntimeError as e:
        if "evaluator changed" not in str(e):
            return {"experiment": eid, "status": "not run", "why": f"{type(e).__name__}: {str(e)[:160]}"}
        _set(con, eid, "deferred", "the evaluator changed after it was registered (2026-10-30: trades at the next session's price): "
             "its result would not mean what was registered; ask the question again to run it under the new rule", now)
        return {"experiment": eid, "status": "deferred", "why": "the evaluator changed since registration"}
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
