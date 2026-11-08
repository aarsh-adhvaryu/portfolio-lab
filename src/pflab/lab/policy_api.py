"""The policy interface (S80 phase 2): one Python function in its own versioned folder,

    decide(state, forecasts, sims, storylines, params) -> {key: target weight}

It may call the toolkit (`from toolkit import ...`) and the standard maths modules, must finish in seconds, and has no network, no files, no clock. It cannot reach the rails, the
data, the scoring or its own promotion: they are code outside it. A policy file may also declare a parameter grid, `PARAMS = {"lookback": [126, 252], "n": [10, 20]}`, so one file
stands for every combination (the lab runs each and counts every one as a trial).

`state` (a dict, the same layout in the replay and in the live loop):
    day         the decision day (datetime.date)
    prices      DataFrame of adjusted closes up to and including `day` (columns = security keys)
    turnover    DataFrame of daily traded value on the same grid (liquidity)
    weights     {key: current weight in the book}; cash = 1 - sum
    value       the book's value in rupees
    meta        {key: {"symbol", "etf": bool, "sector": str|None}}
    universe    the keys the policy may hold (liquid, with enough history)
    index       Series: the market index (adjusted closes) up to `day`
    target      {"equity": %, ...} the system's allocation target, or None
    caps        {key: the hard cap the rails will apply}
`forecasts`, `sims`, `storylines` are dicts (empty until those layers feed them; phase 3 fills `storylines`).
"""
from __future__ import annotations

import ast
import types
from typing import Callable, Dict, List, Optional, Tuple

ALLOWED_IMPORTS = {"math", "statistics", "itertools", "functools", "collections", "dataclasses", "typing", "numpy", "pandas", "toolkit", "__future__"}
FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "input", "globals", "locals", "vars", "getattr", "setattr", "delattr", "breakpoint", "exit", "quit", "memoryview"}
FORBIDDEN_ATTRS = {"__class__", "__bases__", "__subclasses__", "__globals__", "__builtins__", "__dict__", "__code__", "__mro__", "read_csv", "read_parquet", "read_pickle", "to_csv",
                   "to_parquet", "to_pickle", "read_json", "read_html", "read_sql", "system", "popen", "environ", "urlopen"}
MAX_GRID = 24                                                # combinations in one file (about a minute each on the real history); more must be cut by the author


def validate(code: str) -> List[str]:
    """Problems with a policy's source (empty = acceptable). A static allow-list: the sandbox is the real boundary, this keeps the in-process champion honest too."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax error: {e.msg} (line {e.lineno})"]
    problems: List[str] = []
    has_decide = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"import {a.name} is not allowed (allowed: {', '.join(sorted(ALLOWED_IMPORTS - {'__future__'}))})")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS or node.level:
                problems.append(f"from {'.' * node.level}{node.module} import ... is not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(f"the name {node.id} is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            problems.append(f"the attribute .{node.attr} is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            problems.append("global and nonlocal are not allowed")
        elif isinstance(node, ast.FunctionDef) and node.name == "decide":
            has_decide = True
            n = len(node.args.args)
            if n < 4 or n > 5:
                problems.append("decide must take (state, forecasts, sims, storylines) and optionally params")
    if not has_decide:
        problems.append("there is no function decide(state, forecasts, sims, storylines, params=None)")
    return list(dict.fromkeys(problems))


def toolkit_module() -> types.ModuleType:
    from pflab.lab import toolkit
    return toolkit


def load(code: str, toolkit=None) -> Tuple[Callable, Dict[str, list]]:
    """Compile a validated policy and return (decide, grid). `toolkit` is registered as the module `toolkit` for the policy's own import."""
    import sys
    bad = validate(code)
    if bad:
        raise ValueError("; ".join(bad))
    tk = toolkit or toolkit_module()
    prev = sys.modules.get("toolkit")
    sys.modules["toolkit"] = tk
    try:
        mod = types.ModuleType("policy_under_test")
        exec(compile(code, "<policy>", "exec"), mod.__dict__)
    finally:
        if prev is not None:
            sys.modules["toolkit"] = prev
        else:
            sys.modules.pop("toolkit", None)
    fn = mod.__dict__.get("decide")
    if not callable(fn):
        raise ValueError("decide is not a function")
    grid = dict(mod.__dict__.get("PARAMS") or {})
    return fn, grid


def expand_grid(grid: Dict[str, list]) -> List[dict]:
    """Every combination of a PARAMS grid (one empty dict when there is none); refuses a grid over MAX_GRID combinations."""
    import itertools
    if not grid:
        return [{}]
    keys = sorted(grid)
    for k in keys:
        if not isinstance(grid[k], (list, tuple)) or not grid[k]:
            raise ValueError(f"PARAMS[{k!r}] must be a non-empty list")
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*(grid[k] for k in keys))]
    if len(combos) > MAX_GRID:
        raise ValueError(f"the grid has {len(combos)} combinations; the limit is {MAX_GRID}")
    return combos


def call(fn: Callable, state: dict, forecasts: Optional[dict], sims: Optional[dict], storylines: Optional[dict], params: Optional[dict]) -> Dict[str, float]:
    """Run decide and clean its answer: finite, non-negative weights on known keys only (anything else is dropped, so a policy cannot invent a security)."""
    import math
    w = fn(state, forecasts or {}, sims or {}, storylines or {}, dict(params or {}))
    if not isinstance(w, dict):
        raise ValueError("decide must return a dict {key: weight}")
    known = set(state["universe"]) | set(state["weights"])
    out = {}
    for k, v in w.items():
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if k in known and math.isfinite(x) and x > 0:
            out[k] = x
    return out
