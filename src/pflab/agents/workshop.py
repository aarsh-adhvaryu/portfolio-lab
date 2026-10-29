"""The calculation workshop (S53; the investor 2026-10-20: fixed maths cannot think, so the models may write maths).

A question no tool answers goes to a writer model, which returns Python (`def compute(data) -> dict`), a worked test
case and optionally a second method. The numbers then come from running that code HERE, never from a model's text:

    1. static check   imports from a short list only; no files, network, system, eval or private attributes
    2. sandbox        a separate isolated Python process (`workshop_runner.py`), its own folder, a time limit
    0. measures       (S58b) a question a reviewed measure answers (calc/measures.py) never reaches a writer: the local
                      model only picks the measure and reads its values, and the answer says what was computed
    3. checks         the writer's test case must give its stated answer; a second method, when given, must agree;
                      (S58b) then an independent second writing, which never sees the first code, must agree on the
                      real data, else the calculation is "disputed" (both shown, neither reused or promoted)
    4. kept           PFLAB_PM_DIR/workshop/<id>/: spec, code, result, labelled "new calculation, not reviewed" until
                      the investor or Claude promotes it (`pflab workshop promote`); a promoted calculation can be rerun on
                      new data as a tool
Writers (The investor 2026-10-22, after the local model misread a drawdown question): Opus first through the doorbell
(`analyst.write_calculation`, two tries, each failure fed back); the local model only when Opus cannot be rung (off,
over the cap, waiting for the investor's yes). A writer sees the question and the datasets' SCHEMA
with made-up sample rows; the real rows (holdings, deposits, prices) are loaded only into the sandbox on this PC.
"""
from __future__ import annotations

import ast
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pflab.agents import sandbox as sb

RUNNER = Path(__file__).with_name("workshop_runner.py")
TIME_LIMIT_S = 60
MAX_CODE = 20000
LOCAL_TRIES = 2
UNREVIEWED = "new calculation, not reviewed"

# --- datasets: what a calculation may read (schema shown to writers; rows loaded only into the sandbox) -------------

FIXED = {
    "holdings": ("what is held now, one row per holding (all accounts together)",
                 {"symbol": "str", "isin": "str", "bucket": "str: equity | gold | debt | review", "qty": "float units",
                  "cost": "float rupees paid", "price": "float rupees", "value": "float rupees", "unrealised": "float rupees"}),
    "fds": ("open fixed deposits", {"maturity": "date (pandas datetime)", "value": "float rupees now",
                                    "reserve": "bool (kept apart)"}),
    "prices": ("daily closes of the held listed instruments, the last five years",
               {"isin": "str", "date": "date (pandas datetime)", "close": "float rupees"}),
}
SERIES_COLS = {"date": "date (pandas datetime)", "close": "float"}
_FIRST_PERSON = [(r"\b(my|our)\b", "the"), (r"\b(I|we)\b", "the investor"), (r"\b(me|us)\b", "the investor"),
                 (r"\b(mine|ours)\b", "the investor's")]


def neutral(question: str) -> str:
    """First-person wording -> third person, for a writer outside this PC (the egress gate still checks the rest)."""
    q = question
    for pat, rep in _FIRST_PERSON:
        q = re.sub(pat, rep, q, flags=re.I)
    return q


def catalogue(root: Path) -> Dict[str, Tuple[str, Dict[str, str]]]:
    """Every dataset name a writer may ask for: the fixed three plus index:<NAME> and global:<NAME> series on disk."""
    cat = dict(FIXED)
    for sub, label in (("indices", "index"), ("global", "global")):
        for p in sorted((root / sub).glob("*.parquet")):
            cat[f"{label}:{p.stem}"] = (f"daily {p.stem} ({'NSE' if label == 'index' else 'world markets, Yahoo'})",
                                        SERIES_COLS)
    return cat


def schema_text(cat: Dict[str, Tuple[str, Dict[str, str]]]) -> str:
    fixed = [f"- {n}: {d}; columns {', '.join(f'{c} ({t})' for c, t in cols.items())}" for n, (d, cols) in cat.items()
             if ":" not in n]
    series = sorted(n for n in cat if ":" in n)
    return "\n".join(fixed + [f"- index:<NAME> / global:<NAME>: a daily series, columns date (date), close (float). "
                              f"Available: {', '.join(series)}"])


def sample_rows(cols: Dict[str, str], n: int = 3, seed: int = 0) -> List[dict]:
    """Made-up rows in a dataset's shape (never real values): shown to writers and usable in their test case."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        r = {}
        for c, t in cols.items():
            if t.startswith("date"):
                r[c] = str(date(2026, 1, 1) + timedelta(days=i))
            elif t.startswith("bool"):
                r[c] = bool(i % 2)
            elif t.startswith("str"):
                r[c] = {"bucket": ["equity", "gold", "debt"][i % 3]}.get(c, f"{c.upper()}{i}")
            else:
                r[c] = float(np.round(rng.uniform(10, 1000), 2))
        out.append(r)
    return out


def load_dataset(name: str, con, root: Path, asof: date) -> pd.DataFrame:
    """The real rows, on this PC only. Account and deposit ids are never included."""
    if name == "holdings":
        from pflab.pm import today as nw
        pos = nw.build(con, asof)["positions"]
        cols = list(FIXED["holdings"][1])
        return pos.groupby(["symbol", "isin", "bucket"], as_index=False)[["qty", "cost", "value", "unrealised"]].sum() \
            .merge(pos.groupby("isin", as_index=False)["price"].first(), on="isin")[cols]
    if name == "fds":
        from pflab.pm import today as nw
        return nw.build(con, asof)["fds"][["maturity", "value", "reserve"]].reset_index(drop=True)
    if name == "prices":
        from pflab.pm import today as nw
        isins = sorted(set(nw.build(con, asof)["positions"]["isin"]))
        if not isins:
            return pd.DataFrame(columns=["isin", "date", "close"])
        q = ",".join("?" * len(isins))
        return con.execute(f"SELECT isin, date, close FROM prices WHERE isin IN ({q}) AND date BETWEEN ? AND ? "
                           "ORDER BY isin, date", isins + [asof - timedelta(days=5 * 366), asof]).df()
    kind, _, key = name.partition(":")
    sub = {"index": "indices", "global": "global"}.get(kind)
    p = root / sub / f"{key}.parquet" if sub and re.fullmatch(r"[A-Za-z0-9_ ]+", key) else None
    if p is None or not p.exists():
        raise KeyError(f"no dataset {name!r}")
    df = pd.read_parquet(p, columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[df["date"] <= asof].sort_values("date").reset_index(drop=True)


# --- 1. static check -------------------------------------------------------------------------------------------------

# The checks guard against a writer's MISTAKES (a stray file read, a network call, a runaway loop); the writers are our
# own models, not adversaries. The code runs in Docker (no network, read-only root; agents/sandbox.py) when Docker works;
# the local subprocess is the fallback and is marked `contained: False`.
ALLOWED_IMPORTS = {"math", "statistics", "datetime", "itertools", "collections", "functools", "numpy", "pandas",
                   "scipy.stats", "scipy.optimize", "statsmodels", "statsmodels.api", "statsmodels.tsa.api",
                   "statsmodels.tsa.stattools", "statsmodels.stats.api"}
BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr",
                "delattr", "input", "breakpoint", "help", "exit", "quit", "memoryview", "__builtins__"}
BANNED_ATTRS = {"eval", "query", "system", "popen", "pickle", "memmap", "fromfile", "tofile", "genfromtxt", "pipe",
                # module paths that reach files, the OS or the network (scipy.io, numpy.lib, pandas.io, ...)
                "io", "lib", "os", "sys", "ctypeslib", "ctypes", "f2py", "testing", "distutils", "compat", "subprocess",
                "shutil", "pathlib", "builtins", "importlib", "socket", "http", "urllib", "request", "requests"}
BANNED_PREFIXES = ("_", "read", "load", "save", "write", "open", "dump")
TO_OK = {"to_numpy", "to_list", "to_dict", "to_frame", "to_period", "to_timestamp", "to_datetime", "to_series",
         "to_pydatetime", "to_timedelta", "to_numeric"}         # to_numeric: pure conversion (Opus used it, 2026-10-22)


def static_check(code: str) -> List[str]:
    """Reasons the code may not run (empty when it may)."""
    if len(code) > MAX_CODE:
        return [f"code longer than {MAX_CODE} characters"]
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax error: {e}"]
    bad = []
    for node in tree.body:                                    # top level: imports, functions, constants only
        if not isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Assign, ast.AnnAssign)) and \
                not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            bad.append(f"line {node.lineno}: only imports, functions and constants at the top level")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "compute" for n in tree.body):
        bad.append("no top-level function compute(data)")
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            bad += [f"line {n.lineno}: import {a.name} is not allowed" for a in n.names if a.name not in ALLOWED_IMPORTS]
        elif isinstance(n, ast.ImportFrom):
            if (n.module or "") not in ALLOWED_IMPORTS or n.level:
                bad.append(f"line {n.lineno}: from {n.module} import is not allowed")
        elif isinstance(n, ast.Name) and n.id in BANNED_NAMES:
            bad.append(f"line {n.lineno}: {n.id} is not allowed")
        elif isinstance(n, ast.Attribute):
            a = n.attr
            if a.startswith(BANNED_PREFIXES) or a in BANNED_ATTRS or (a.startswith("to_") and a not in TO_OK):
                bad.append(f"line {n.lineno}: .{a} is not allowed")
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            bad.append(f"line {n.lineno}: global/nonlocal is not allowed")
    return sorted(set(bad))


# --- 2-3. sandbox run and checks ---------------------------------------------------------------------------------------

@dataclass
class Spec:
    datasets: List[str]
    code: str
    test: dict                                   # {"data": {name: [rows]}, "expected": {name: value}, "tol": float}
    alt_code: str = ""
    explain: str = ""
    params: dict = field(default_factory=dict)   # {name: {"type": "text|number|date", "default": v, "about": "..."}}


@dataclass
class Run:
    ok: bool
    problems: List[str]
    result: Dict[str, object] = field(default_factory=dict)
    cross_checked: bool = False
    seconds: float = 0.0
    contained: bool = False                      # ran in Docker (no network, read-only root), not the local subprocess


def parse_spec(text: str) -> Spec:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("the writer's reply holds no JSON object")
    d = json.loads(m.group(0))
    return Spec([str(x) for x in d.get("datasets", [])], str(d.get("code", "")), dict(d.get("test") or {}),
                str(d.get("alt_code") or ""), str(d.get("explain") or ""), dict(d.get("params") or {}))


def same_method(a: str, b: str) -> bool:
    """True when two pieces of code are the same steps (identical after dropping names, comments and layout): a copy
    is not a second method (2026-10-22: the local model returned its code twice and "two methods agree" was shown)."""
    def norm(src: str) -> str:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return src
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                n.id = "v"
            elif isinstance(n, ast.arg):
                n.arg = "v"
        return ast.dump(tree, annotate_fields=False)
    return norm(a) == norm(b)


def defaults(spec: Spec) -> dict:
    return {k: (v or {}).get("default") for k, v in (spec.params or {}).items()}


def run(spec: Spec, frames: Dict[str, pd.DataFrame], python: str = sys.executable,
        time_limit: int = TIME_LIMIT_S, values: Optional[dict] = None, sandbox=None) -> Run:
    """Static check, then the sandbox (Docker when it works, else the local subprocess): the test case first, then the
    real frames (with `values` for the parameters, else their defaults); a second method must agree."""
    if spec.alt_code and same_method(spec.code, spec.alt_code):
        from dataclasses import replace
        spec = replace(spec, alt_code="")          # a copy is no second method: dropped (optional), never a failed try
    problems = static_check(spec.code) + ([f"alt_code: {p}" for p in static_check(spec.alt_code)] if spec.alt_code else [])
    t = spec.test or {}
    if not t.get("data") or not t.get("expected"):
        problems.append("no test case (test.data and test.expected are both required)")
    if problems:
        return Run(False, problems)
    work = Path(tempfile.mkdtemp(prefix="pflab_wk_"))
    try:
        (work / "code.py").write_text(spec.code, encoding="utf-8")
        if spec.alt_code:
            (work / "alt_code.py").write_text(spec.alt_code, encoding="utf-8")
        for i, name in enumerate(spec.datasets):
            frames[name].to_parquet(work / f"{i}.parquet", index=False)
        (work / "job.json").write_text(json.dumps({"datasets": spec.datasets, "test": t,
                                                    "params": {**defaults(spec), **(values or {})}}, default=str),
                                        encoding="utf-8")
        box = sandbox or sb.pick(python)
        t0 = datetime.now()
        try:
            box.run(work, time_limit)
        except subprocess.TimeoutExpired:
            return Run(False, [f"stopped after {time_limit} s"], contained=box.contained)
        secs = (datetime.now() - t0).total_seconds()
        out = sb.read_result(work / "out.json")
        c = box.contained
        if "error" in out:
            return Run(False, [out.get("test_detail") or out["error"]], seconds=secs, contained=c)
        if not out.get("test_ok"):
            return Run(False, ["the run produced no result"], seconds=secs, contained=c)
        if out.get("disagree"):
            return Run(False, ["the two methods disagree: " + "; ".join(out["disagree"][:5])], out.get("result", {}),
                       seconds=secs, contained=c)
        return Run(True, [], out["result"], cross_checked="alt_result" in out, seconds=secs, contained=c)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --- writers ----------------------------------------------------------------------------------------------------------

WRITER_SYSTEM = (
    "You write one small Python calculation for a personal portfolio system in India. Reply with JSON only:\n"
    '{"datasets": [names], "code": "...", "test": {"data": {name: [rows]}, "expected": {result: value}, "tol": 1e-6}, '
    '"alt_code": "...", "explain": "one short paragraph"}\n'
    "Rules: code defines def compute(data) where data maps each dataset name to a pandas DataFrame with the listed "
    "columns, and returns a flat dict of result names to numbers, booleans or short text. Imports only math, "
    "statistics, datetime, itertools, collections, functools, numpy, pandas, scipy.stats, scipy.optimize, "
    "statsmodels (api, tsa.api, tsa.stattools, stats.api). No files, "
    "network, printing, eval, or names starting with an underscore. The test is a tiny made-up case you can work out "
    "by hand, with the exact expected results; work them out from the question, not from your code. Apply every "
    "condition in the question (its period, units, percent or points). alt_code is optional: the same calculation by a "
    "different algorithm (not the same steps), used as a cross-check. Never put real holdings or amounts in the test: "
    "invent them. Where the question names a value that could change (an index or a stock, a period or a date, a "
    "threshold, a horizon), make it a parameter so the same code answers the next such question: write "
    'def compute(data, params), list them in "params": {name: {"type": "text|number|date", "default": the question\'s '
    'value, "about": "what it is"}}, and give the test its own "params" if they differ from the defaults.')


def writer_prompt(question: str, schema: str, samples: str, feedback: str = "") -> str:
    p = f"QUESTION:\n{question}\n\nDATASETS:\n{schema}\n\nSAMPLE ROWS (made up, for shape only):\n{samples}"
    if feedback:
        p += f"\n\nYOUR LAST ATTEMPT FAILED:\n{feedback}\nFix it and reply with the full JSON again."
    return p


def local_writer(model: Optional[str] = None) -> Callable[[str], str]:
    from pflab.llm import client, registry
    m = model or registry.chosen("general") or "qwen3:8b-q8_0"
    return lambda prompt: client.chat(m, [{"role": "system", "content": WRITER_SYSTEM}, {"role": "user", "content": prompt}],
                                      num_predict=2500, num_ctx=8192).text


@dataclass
class Outcome:
    status: str                       # checked | failed | blocked
    run: Optional[Run]
    spec: Optional[Spec]
    writer: str
    attempts: List[str]
    folder: Optional[Path] = None
    values: Optional[dict] = None                     # the parameter values this run used
    reused_from: Optional[str] = None                 # the kept calculation it came from (the library)
    measure: Optional[str] = None                     # a reviewed measure answered it (calc/measures.py)
    confirm: Optional[dict] = None                    # the independent second writing: agrees | disagrees | not run
    inputs: Optional[dict] = None                     # S67: the frames the run read (name -> DataFrame), kept by cases.record_calc


def solve(question: str, frames_for: Callable[[List[str]], Dict[str, pd.DataFrame]], schema: str, samples: str,
          writers: List[Tuple[str, Callable[[str], str], int]]) -> Outcome:
    """Try each writer in turn (name, prompt -> reply, tries); every failure is fed back to the same writer."""
    log: List[str] = []
    last_spec, last_run = None, None
    for name, write, tries in writers:
        feedback = ""
        for k in range(1, tries + 1):
            try:
                spec = parse_spec(write(writer_prompt(question, schema, samples, feedback)))
                unknown = [d for d in spec.datasets if d not in schema_names(schema)]
                if unknown:
                    raise ValueError(f"unknown dataset(s): {unknown}")
                r = run(spec, frames_for(spec.datasets))
            except sb.SandboxUnavailable:
                raise                                 # S67: nothing ran; asking the writer again would change nothing
            except Exception as e:                    # a writer's malformed reply is a failed attempt, never a crash
                spec, r = None, Run(False, [f"{type(e).__name__}: {e}"])
            log.append(f"{name} try {k}: " + ("ok" if r.ok else "; ".join(r.problems)[:300]))
            last_spec, last_run = spec, r
            if r.ok:
                return Outcome("checked", r, spec, name, log)
            feedback = "\n".join(r.problems)
    return Outcome("failed", last_run, last_spec, writers[-1][0] if writers else "", log)


# --- an independent second writing (S58b) ------------------------------------------------------------------------------
# A writer's own worked example only shows the code does what the writer meant (2026-10-22: a "largest fall from a peak"
# was computed as the largest one-day fall, and the model's test agreed with it). So a new calculation is written a
# second time, in a fresh call that never sees the first code, told only the names of the results to return; the two
# must agree on the real data. A disagreement is "disputed": both results shown, nothing reused or promoted.

CONFIRM_RTOL = 1e-4


def _numbers(d: dict) -> Dict[str, float]:
    return {k: float(v) for k, v in d.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def confirm(question: str, first: Outcome, frames_for, schema: str, samples: str,
            writers: List[Tuple[str, Callable[[str], str], int]]) -> dict:
    want = _numbers(first.run.result)
    if not want:
        return {"status": "not run", "detail": "no numeric result to compare"}
    note = (f"\n\nWrite this calculation yourself, from the question alone. compute must return a dict with exactly these "
            f"keys: {', '.join(sorted(want))} (the same meaning as their names), plus nothing else.")
    tried = []
    for name, write, _tries in writers:
        try:
            spec = parse_spec(write(writer_prompt(question, schema, samples) + note))
            if [d for d in spec.datasets if d not in schema_names(schema)]:
                raise ValueError("unknown dataset")
            r = run(spec, frames_for(spec.datasets))
        except sb.SandboxUnavailable:
            raise
        except Exception as e:                      # a malformed second writing is not a verdict
            tried.append(f"{name}: {type(e).__name__}: {e}"[:200])
            continue
        if not r.ok:
            tried.append(f"{name}: " + "; ".join(r.problems)[:200])
            continue
        got = _numbers(r.result)
        off = [f"{k}: {want[k]:,.6g} vs {got.get(k, float('nan')):,.6g}" for k in sorted(want)
               if k not in got or not math.isclose(want[k], got[k], rel_tol=CONFIRM_RTOL, abs_tol=1e-9)]
        return {"status": "disagrees" if off else "agrees", "writer": name, "detail": "; ".join(off[:6]),
                "second_result": r.result, "second_explain": spec.explain}
    return {"status": "not run", "detail": " | ".join(tried) or "no second writer"}


# --- reviewed measures first (S58b) -------------------------------------------------------------------------------------

ROUTER = ("Pick the one reviewed measure that answers the question, or none. Reply with JSON only: "
          '{"measure": a name from MEASURES or "none", "series": a name from SERIES, "second": a name from SERIES or null, '
          '"values": {parameter: value}}. Dates as YYYY-MM-DD (a calendar year Y is Y-01-01 to Y-12-31). Leave out a '
          "parameter the question does not give. Answer none when the question asks for anything the measure does not "
          "compute.")


def _grams(text: str, n: int = 3) -> set:
    """The question's words and runs of up to `n` neighbouring words joined ("Nifty 50" -> NIFTY50, never NIFTY500)."""
    w = re.findall(r"[A-Z0-9]+", text.upper())
    return {"".join(w[i:i + k]) for k in range(1, n + 1) for i in range(len(w) - k + 1)}


def series_fits(question: str, name: str) -> bool:
    """An NSE index series named in the question: every part of its name (SECTOR aside) is a word or a run of joined
    words there (Nifty 50 is not Nifty 500; IT is not inside "within"), and total return (TRI) only when the question
    says so. Other series (world markets) are not checked here; the answer names the series either way."""
    kind, _, key = name.partition(":")
    if kind != "index":
        return True
    q = _grams(question)
    parts = key.split("_")
    suffix = parts[-1] if parts[-1] in ("PRICE", "TRI", "VALUATION") else ""
    main = [p for p in (parts[:-1] if suffix else parts) if p != "SECTOR"]
    if not all(p in q for p in main):
        return False
    tri = "TRI" in re.findall(r"[A-Z]+", question.upper()) or "TOTAL RETURN" in question.upper()
    if suffix == "VALUATION":
        return bool(re.search(r"\b(P/?E|P/?B|VALUATION|DIVIDEND YIELD)\b", question.upper()))
    return suffix == ("TRI" if tri else "PRICE") or not suffix


TAX_PLAN = ("- tax_plan: tax if holdings are sold today (lot by lot), when lots turn long-term and what waiting saves, "
            "the long-term gains exemption left this year, losses that lower this year's tax; no series (null)")


def from_measures(question: str, cat, frames_for, llm: Optional[Callable[[str], str]], con=None,
                  asof: Optional[date] = None) -> Optional[Outcome]:
    """A question a reviewed measure answers: the local model picks it and reads its values; the code is ours."""
    from pflab.calc import measures as ms
    if llm is None:
        return None
    series = sorted(n for n in cat if ":" in n)
    reply = llm(f"{ROUTER}\n\nMEASURES:\n{ms.catalogue_text()}\n{TAX_PLAN if con is not None else ''}\n\n"
                f"SERIES: {', '.join(series)}\n\nQUESTION: {question}")
    try:
        got = json.loads(re.search(r"\{.*\}", reply or "", re.S).group(0))
    except (AttributeError, ValueError):
        return None
    name, s1, s2 = got.get("measure"), got.get("series"), got.get("second")
    if name == "tax_plan" and con is not None:          # S58b: tax planning is the tax engine's, never written code
        from pflab.agents import tools
        facts = tools.taxplan(con, asof or date.today())
        named = {k.split(".")[1] for k in facts if k.count(".") >= 2 and re.search(
            r"\b" + re.escape(k.split(".")[1]) + r"\b", question, re.I)}
        res = {k: v for k, v in facts.items() if not named or k.count(".") < 2 or k.split(".")[1] in named
               or k.startswith("taxplan.harvest.")}
        spec = Spec([], "", {}, explain="Reviewed: the tax engine (tax/plan.py: each sale replayed on a copy of the "
                                        "ledger under the dated tax rules), at today's prices, before fees.")
        out = Outcome("checked", Run(True, [], res), spec, "reviewed measure (tax_plan)", ["reviewed measure: tax_plan"])
        out.values, out.measure = {}, "tax_plan"
        return out
    m = ms.MEASURES.get(name)
    if m is None or s1 not in series or (m.second and s2 not in series):
        return None
    note = []
    # a misread series (2026-10-24: Nifty 500 TRI read as Nifty 50; S59 test: a Nifty 50 question answered on the S&P
    # 500): when the question names an NSE index, the series must be that index
    fit = [n for n in series if n.startswith("index:") and series_fits(question, n)]
    if not series_fits(question, s1) or (fit and s1 not in fit):
        if len(fit) != 1 or m.second:
            return None
        note, s1 = [f"series corrected from {s1} to {fit[0]} (the name in the question)"], fit[0]
    if m.second and not series_fits(question, s2):
        return None
    values = {}
    for k, v in (got.get("values") or {}).items():
        p = m.params.get(k)
        if p is None or v in (None, ""):
            continue
        try:
            values[k] = pd.Timestamp(str(v)).date().isoformat() if p["type"] == "date" else float(v)
        except (TypeError, ValueError):
            return None
    names = [s1] + ([s2] if m.second else [])
    frames = frames_for(names)
    res = ms.run(name, frames[s1], values, frames.get(s2) if m.second else None)
    what = ms.describe(name, s1, values, s2 if m.second else None)
    spec = Spec(names, "", {}, explain=f"Reviewed measure: {what}. Definition: {res.get('definition', '')}."
                + "".join(f" ({n})" for n in note))
    out = Outcome("checked", Run(True, [], res), spec, f"reviewed measure ({name})", [f"reviewed measure: {what}", *note])
    out.values, out.measure = values, name
    return out


def schema_names(schema: str) -> set:
    names = set(re.findall(r"^- (\w+):", schema, re.M))
    m = re.search(r"Available: (.*)$", schema, re.M)
    if m:
        names |= {x.strip() for x in m.group(1).split(",") if x.strip()}
    return names


# --- 4. kept -----------------------------------------------------------------------------------------------------------

def folder(pm_dir: Path) -> Path:
    return pm_dir / "workshop"


def keep(pm_dir: Path, question: str, out: Outcome, now: datetime) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:40] or "calc"
    d = folder(pm_dir) / f"{now:%Y%m%d-%H%M%S}-{slug}"
    d.mkdir(parents=True, exist_ok=True)
    label = ("reviewed measure" if out.measure else UNREVIEWED if out.status == "checked" else
             "disputed: two independent writings disagree" if out.status == "disputed" else "failed")
    meta = {"question": question, "status": out.status, "label": label, "measure": out.measure,
            "confirmed": (out.confirm or {}).get("status"), "confirm": out.confirm,
            "writer": out.writer, "attempts": out.attempts, "created": now.isoformat(timespec="seconds"),
            "datasets": out.spec.datasets if out.spec else [], "explain": out.spec.explain if out.spec else "",
            "test": out.spec.test if out.spec else {}, "result": out.run.result if out.run else {},
            "cross_checked": bool(out.run and out.run.cross_checked),
            "contained": bool(out.run and out.run.contained),
            "params": out.spec.params if out.spec else {}, "values": getattr(out, "values", None) or
            (defaults(out.spec) if out.spec else {}), "reused_from": getattr(out, "reused_from", None)}
    (d / "meta.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    if out.spec and out.spec.code:
        (d / "code.py").write_text(out.spec.code, encoding="utf-8")
        if out.spec.alt_code:
            (d / "alt_code.py").write_text(out.spec.alt_code, encoding="utf-8")
    out.folder = d
    return d


def promote(pm_dir: Path, calc_id: str, by: str, now: Optional[datetime] = None) -> dict:
    d = folder(pm_dir) / calc_id
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    if meta["status"] != "checked":
        raise ValueError("only a checked calculation can be promoted (a disputed one never)")
    if meta.get("measure"):
        raise ValueError("a reviewed measure is already reviewed (calc/measures.py)")
    meta.update(label="reviewed", reviewed_by=by, reviewed=(now or datetime.now()).isoformat(timespec="seconds"))
    (d / "meta.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    return meta


def load_spec(pm_dir: Path, calc_id: str) -> Tuple[Spec, dict]:
    d = folder(pm_dir) / calc_id
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    alt = (d / "alt_code.py").read_text(encoding="utf-8") if (d / "alt_code.py").exists() else ""
    return Spec(meta["datasets"], (d / "code.py").read_text(encoding="utf-8"), meta["test"], alt, meta.get("explain", ""),
                meta.get("params") or {}), meta


def rerun(pm_dir: Path, calc_id: str, frames_for: Callable[[List[str]], Dict[str, pd.DataFrame]],
          values: Optional[dict] = None) -> Run:
    """A kept calculation on today's data (a promoted one is a tool), with its kept parameter values unless given."""
    spec, meta = load_spec(pm_dir, calc_id)
    return run(spec, frames_for(spec.datasets), values=values if values is not None else (meta.get("values") or {}))


# --- the library (reusable calculations) -------------------------------------------------------------------------------
# Before a writer is paid, the kept calculations are searched: the same question asked before is run again on today's
# data; a similar question with a calculation the investor reviewed (promoted) and parameters is answered by it, the local
# model only filling in the parameters (checked against their types). Nothing new is written; the run is the same
# sandbox with its worked example first.

STOP = set("the a an of in on to for and or is are was were be what how much many by from with at as it its this that "
           "which when did does do since over between than per each".split())
SIMILAR = 0.4


def words(q: str) -> set:
    return {w for w in re.findall(r"[a-z]+", q.lower()) if w not in STOP and len(w) > 1}


def find(pm_dir: Path, question: str) -> Optional[Tuple[str, dict, str]]:
    """(calc id, meta, how): "same" for the same question (a calculation reviewed or confirmed by an independent second
    writing; S58b: one only checked against its own writer's example is not reused), "similar" for a reviewed one with
    parameters whose question shares at least SIMILAR of its words; the newest wins. Measures are not kept code."""
    q, best = " ".join(question.lower().split()), None
    for d in sorted(folder(pm_dir).glob("*/meta.json"), reverse=True):
        m = json.loads(d.read_text(encoding="utf-8"))
        if m.get("status") != "checked" or m.get("measure"):
            continue
        if " ".join(m["question"].lower().split()) == q and (m.get("label") == "reviewed" or m.get("confirmed") == "agrees"):
            return d.parent.name, m, "same"
        if m.get("label") == "reviewed" and m.get("params") and best is None:
            a, b = words(question), words(m["question"])
            if a and b and len(a & b) / len(a | b) >= SIMILAR:
                best = (d.parent.name, m, "similar")
    return best


def fill(params: dict, question: str, llm: Callable[[str], str]) -> Optional[dict]:
    """The local model reads the parameter values out of the new question; each is checked against its type, and a
    text value must appear in the question. None when any value fails (the writers take over)."""
    lines = "\n".join(f'- {k} ({v.get("type", "text")}): {v.get("about", "")} (example: {v.get("default")})'
                       for k, v in params.items())
    reply = llm(f"Read the values of these parameters from the question. Reply with JSON only, one key per parameter.\n"
                f"PARAMETERS:\n{lines}\n\nQUESTION: {question}")
    try:
        got = json.loads(re.search(r"\{.*\}", reply or "", re.S).group(0))
    except (AttributeError, ValueError):
        return None
    out = {}
    for k, v in params.items():
        x, t = got.get(k), (v or {}).get("type", "text")
        try:
            if t == "number":
                out[k] = float(x)
            elif t == "date":
                out[k] = pd.Timestamp(str(x)).date().isoformat()
            else:
                if not isinstance(x, str) or not x.strip() or x.strip().lower() not in question.lower():
                    return None
                out[k] = x.strip()
        except (TypeError, ValueError):
            return None
    return out


def from_library(pm_dir: Path, question: str, frames_for, llm: Optional[Callable[[str], str]]) -> Optional[Outcome]:
    hit = find(pm_dir, question)
    if not hit:
        return None
    cid, meta, how = hit
    spec, _ = load_spec(pm_dir, cid)
    if how == "same":
        values = meta.get("values") or defaults(spec)
        who = f"library: the same question, kept {cid}" + (" (reviewed)" if meta.get("label") == "reviewed" else "")
    else:
        if llm is None:
            return None
        values = fill(spec.params, question, llm)
        if values is None:
            return None
        who = f"library: reviewed calculation {cid}, parameters read locally"
    r = run(spec, frames_for(spec.datasets), values=values)
    if not r.ok:
        return None
    out = Outcome("checked", r, spec, who, [f"{who}: ok"])
    out.values, out.reused_from = values, cid
    return out


def listing(pm_dir: Path) -> List[dict]:
    out = []
    for d in sorted(folder(pm_dir).glob("*/meta.json")):
        m = json.loads(d.read_text(encoding="utf-8"))
        out.append({"id": d.parent.name, "status": m["status"], "label": m["label"], "question": m["question"]})
    return out


def ask(con, question: str, pm_dir: Path, root: Path, asof: date, *, writer: str = "auto", secrets=None,
        approved: bool = False, now: Optional[datetime] = None, local: Optional[Callable[[str], str]] = None,
        opus_client=None, library: bool = True) -> Outcome:
    """The whole loop for one question: writers in turn, sandboxed checks, kept with its code, noted in memory."""
    from pflab.agents import analyst as an
    from pflab.agents import memory as mem
    now = now or datetime.now()
    why = sb.blocked_by_probe(con)
    if why:
        raise sb.SandboxUnavailable(why)                     # S67: a failed containment probe stops generated code until it passes again
    cat = catalogue(root)
    schema = schema_text(cat)
    shown = {n: sample_rows(cols) for n, (_d, cols) in cat.items() if ":" not in n}
    shown["index:<NAME>"] = sample_rows(SERIES_COLS)
    samples = json.dumps(shown, indent=0, default=str)
    writers: List[Tuple[str, Callable[[str], str], int]] = []
    if writer in ("auto", "opus") and an.config()["adopted"]:
        client = opus_client or an.make_client(secrets)
        first_m = an.slider("workshop")                     # S61: Sonnet passed the acceptance test as the writer
        second_m = an.MODEL if first_m == an.SONNET else an.SONNET     # the check is always the other model
        name = {an.MODEL: "Opus 5.5", an.SONNET: "Sonnet 5.5"}

        def opus(prompt: str) -> str:
            sent = prompt.replace(question, neutral(question), 1)
            return an.write_calculation(con, sent, WRITER_SYSTEM, client, now=now, approved=approved,
                                        cfg={**an.config(), "model": first_m},
                                        gate_text=sent.replace(schema, "").replace(samples, ""))
        writers.append((f"{name.get(first_m, first_m)} (analyst)", opus, 2))

        def sonnet(prompt: str) -> str:                     # S59: a different model makes the better second writing
            sent = prompt.replace(question, neutral(question), 1)
            return an.write_calculation(con, sent, WRITER_SYSTEM, client, now=now, approved=approved,
                                        cfg={**an.config(), "model": second_m},
                                        gate_text=sent.replace(schema, "").replace(samples, ""))
        second = [(f"{name.get(second_m, second_m)} (independent)", sonnet, 1)]
    else:
        second = []
    if writer == "local" or (writer == "auto" and not writers):
        writers.append(("local model", local or local_writer(), LOCAL_TRIES))
    elif writer == "auto":                                   # Opus refused or failed its checks: the local model, labelled
        writers.append(("local model (fallback after Opus)", local or local_writer(), LOCAL_TRIES))
    captured: dict = {}

    def frames_for(names):                                  # S67: what each run read is remembered, so the number can be reproduced from it
        got = {n: load_dataset(n, con, root, asof) for n in names}
        captured.update(got)
        return got
    out = None
    if library:                                            # reviewed measures, then the library, before paying a writer
        filler = local or _filler()
        for step in (lambda: from_measures(question, cat, frames_for, filler, con, asof),
                     lambda: from_library(pm_dir, question, frames_for, filler)):
            try:
                out = step()
            except Exception:                              # a miss is never an error: the next step takes over
                out = None
            if out is not None:
                break
    if out is None:
        out = solve(question, frames_for, schema, samples, writers)
        if out.status == "checked":                        # S58b: never accepted on its own writer's example alone
            out.confirm = confirm(question, out, frames_for, schema, samples, second + writers)
            if out.confirm["status"] == "disagrees":
                out.status = "disputed"
    if out.spec is not None:
        out.inputs = {n: captured[n] for n in out.spec.datasets if n in captured}
    d = keep(pm_dir, question, out, now)
    if out.run is not None and not out.run.contained:       # only the explicit workshop setting runs uncontained; say so once a day
        from pflab.agents import questions as qs
        qs.ask(con, "workshop", f"workshop:uncontained:{now:%Y-%m-%d}",
               "This calculation ran in the uncontained developer subprocess (PFLAB_SANDBOX=local), not in Docker. It is a workshop setting, "
               "not for the app. Answer 'seen' when noted.", now)
    if out.status == "checked":
        summary = "; ".join(f"{k} {v}" for k, v in list(out.run.result.items())[:10])
        how = "reviewed measure" if out.measure else f"{UNREVIEWED}; second writing {(out.confirm or {}).get('status', 'n/a')}"
        mem.remember(con, "note", f"Workshop calculation ({how}) for: {question} -> {summary}",
                     subject="workshop", source=f"workshop {d.name}", now=now)
    return out


def _filler() -> Optional[Callable[[str], str]]:
    """The local model for reading parameter values (short JSON), if one is chosen."""
    from pflab.llm import client, registry
    m = registry.chosen("general")
    if not m:
        return None
    return lambda prompt: client.chat(m, [{"role": "user", "content": prompt}], num_predict=300, num_ctx=4096).text


def _values(res: dict) -> List[str]:
    return [f"  {k}: {v:,.4f}" if isinstance(v, float) else f"  {k}: {v}" for k, v in res.items()]


def render(out: Outcome) -> str:
    if out.status == "disputed":
        c = out.confirm or {}
        return "\n".join(["Two independent writings DISAGREE, so neither answer is used (" + c.get("detail", "") + ").",
                          f"First ({out.writer}): " + (out.spec.explain[:400] if out.spec else ""), *_values(out.run.result),
                          f"Second ({c.get('writer')}): " + (c.get("second_explain") or "")[:400],
                          *_values(c.get("second_result") or {}),
                          "Read both methods; ask again with the definition spelled out, or ask for a reviewed measure."])
    if out.status != "checked":
        return ("No checked calculation: " + (out.attempts[-1] if out.attempts else "no writer available") +
                ("\nTried: " + " | ".join(out.attempts) if len(out.attempts) > 1 else ""))
    r = out.run
    if out.measure:
        return "\n".join([f"{out.spec.explain}", "Code: pflab/calc/measures.py (reviewed, tested against worked answers "
                          "and a second implementation); the local model only chose the measure and read its values.",
                          *_values(r.result)])
    c = out.confirm or {}
    second = {"agrees": f"an independent second writing ({c.get('writer')}) agrees",
              "disagrees": "the second writing disagrees"}.get(c.get("status"), f"NOT confirmed ({c.get('detail', 'no second writing')})")
    lines = [f"Calculation ({UNREVIEWED}; written by {out.writer}; it passed the writer's own worked example"
             + (" and a second method agrees" if r.cross_checked else "") + f"; {second}; run {r.seconds:.1f} s):"]
    lines += _values(r.result)
    if out.spec and out.spec.explain:
        lines.append(f"Method: {out.spec.explain[:600]}")
    if out.folder:
        lines.append(f"Kept in {out.folder} (code beside the result).")
    lines.append("The checks show the code does what its writer meant; read the method to see it answers your question "
                 "before promoting it.")
    return "\n".join(lines)
