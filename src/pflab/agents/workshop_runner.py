"""The workshop's sandbox runner (S53). Run as its own isolated process (`python -I workshop_runner.py <folder>`) by
`agents.workshop.run`; never imported by the system. It reads `job.json` and the dataset parquet files in <folder>,
loads the model-written module from <folder>/code.py (and alt_code.py), runs the test case first, then the real data,
and writes `out.json`. Results must be a flat dict of names to finite numbers, booleans or short text.
"""
import importlib.util
import json
import math
import os
import sys
import traceback
from pathlib import Path

import pandas as pd


def _call(fn, frames: dict, params: dict):
    """compute(data) or, for a calculation with parameters, compute(data, params)."""
    import inspect
    return fn(frames, dict(params)) if len(inspect.signature(fn).parameters) >= 2 else fn(frames)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.compute


def _clean(res) -> dict:
    if not isinstance(res, dict) or not res or len(res) > 50:
        raise ValueError("compute must return a dict of 1 to 50 named results")
    out = {}
    for k, v in res.items():
        if not isinstance(k, str) or len(k) > 80:
            raise ValueError("result names must be short strings")
        if hasattr(v, "item"):                       # numpy scalars
            v = v.item()
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            if not math.isfinite(float(v)):
                raise ValueError(f"result {k!r} is not a finite number")
            out[k] = float(v)
        elif isinstance(v, str) and len(v) <= 200:
            out[k] = v
        else:
            raise ValueError(f"result {k!r} must be a number, a boolean or a short text, not {type(v).__name__}")
    return out


DATE_COLS = ("date", "maturity")


def _dates(df: pd.DataFrame) -> pd.DataFrame:
    """Date columns as pandas datetimes, the same in the test case and the real data."""
    for c in DATE_COLS:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c])
    return df


def _frames(spec: dict, folder: Path) -> dict:
    return {name: _dates(pd.read_parquet(folder / f"{i}.parquet")) for i, name in enumerate(spec)}


def _agree(a: dict, b: dict, tol: float, only=None) -> list:
    bad = []
    for k in sorted(only if only is not None else set(a) | set(b)):
        x, y = a.get(k), b.get(k)
        if isinstance(x, float) and isinstance(y, float):
            if abs(x - y) > tol * max(1.0, abs(x), abs(y)):
                bad.append(f"{k}: {x} vs {y}")
        elif x != y:
            bad.append(f"{k}: {x!r} vs {y!r}")
    return bad


MAX_WALK = 400


def _walk(fn, real: dict, walk: dict, params: dict) -> dict:
    """Walk-forward: for each date, compute() sees ONLY the rows dated up to and including it (cut here, by this runner, not by the model's
    code) and must return a `signal`. Point-in-time by construction: a candidate cannot read a row after the date it is asked about."""
    dates = [str(d) for d in walk.get("dates", [])]
    if not dates or len(dates) > MAX_WALK:
        raise ValueError(f"walk needs 1 to {MAX_WALK} dates")
    out = {}
    for d in dates:
        cut = pd.Timestamp(d)
        sub = {n: f[pd.to_datetime(f["date"]) <= cut].copy() for n, f in real.items()}
        r = _clean(_call(fn, sub, params))
        s = r.get("signal")
        if isinstance(s, bool) or not isinstance(s, (int, float)):
            raise ValueError("compute must return a numeric 'signal'")
        out[d] = float(s)
    return out


def main(folder: str) -> int:
    f = Path(folder)
    job = json.loads((f / "job.json").read_text(encoding="utf-8"))
    out = {"test_ok": False}
    try:
        fns = {"compute": _load(f / "code.py", "wk_code")}
        if (f / "alt_code.py").exists():
            fns["alt"] = _load(f / "alt_code.py", "wk_alt")
        test = {n: _dates(pd.DataFrame(rows)) for n, rows in job["test"]["data"].items()}
        for k, fn in fns.items():
            got = _clean(_call(fn, {n: d.copy() for n, d in test.items()}, {**job.get("params", {}),
                                                                                **job["test"].get("params", {})}))
            exp = {kk: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
                   for kk, v in job["test"]["expected"].items()}
            if not exp:
                raise AssertionError("the test case states no expected result")
            bad = _agree(got, exp, float(job["test"].get("tol", 1e-6)), only=set(exp))
            if bad:
                out["test_detail"] = f"{k} gives the wrong answer on the test case: " + "; ".join(bad[:5])
                raise AssertionError(out["test_detail"])
        out["test_ok"] = True
        real = _frames(job["datasets"], f)
        if job.get("walk"):
            out["walk"] = _walk(fns["compute"], real, job["walk"], job.get("params", {}))
            out["result"] = {"walk_dates": float(len(out["walk"]))}
        else:
            out["result"] = _clean(_call(fns["compute"], {n: d.copy() for n, d in real.items()}, job.get("params", {})))
        if "alt" in fns and not job.get("walk"):
            out["alt_result"] = _clean(_call(fns["alt"], {n: d.copy() for n, d in real.items()}, job.get("params", {})))
            out["disagree"] = _agree(out["result"], out["alt_result"], 1e-4)
    except Exception as e:                            # the model's code failing is a finding, reported back to it
        out["error"] = f"{type(e).__name__}: {e}"
        out["trace"] = traceback.format_exc()[-1500:]
    dest = Path(os.environ.get("PFLAB_OUT") or f)         # in the sandbox the job folder is read-only; the one place to write is /out
    (dest / "out.json").write_text(json.dumps(out, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
