"""The lab's runner (S80 phase 2): the ONE script that runs a strategist's policies. It is copied into the job folder with `engine.py` and `toolkit.py` and run as
`python -I lab_runner.py <folder>` (inside the Docker sandbox: no network, read-only root, the folder read-only, the result written to $PFLAB_OUT). It imports nothing from pflab.

job.json: {"cfg": {...}, "window": [start, end], "policies": [{"id", "file"}], "n_shuffles", "n_mc", "seed", "grid": {id: [params...]}}
data: px.parquet, turnover.parquet (wide, date index), meta.json, index.parquet, bench.parquet (one column `v`, date index).
out.json: {"results": {id: engine.evaluate(...)}, "errors": {id: text}, "seconds": ...}; a policy that fails is reported, the others still run.
"""
import importlib.util
import json
import os
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pandas as pd  # noqa: E402

import engine  # noqa: E402
import toolkit  # noqa: E402

sys.modules["toolkit"] = toolkit


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _series(path: Path) -> pd.Series:
    df = pd.read_parquet(path)
    return df["v"] if "v" in df.columns else df.iloc[:, 0]


def main(folder: str) -> int:
    f = Path(folder)
    job = json.loads((f / "job.json").read_text(encoding="utf-8"))
    out = {"results": {}, "errors": {}}
    t0 = time.time()
    try:
        data = {"px": pd.read_parquet(f / "px.parquet"), "turnover": pd.read_parquet(f / "turnover.parquet"), "meta": json.loads((f / "meta.json").read_text(encoding="utf-8")),
                "index": _series(f / "index.parquet"), "bench": _series(f / "bench.parquet")}
        for k in ("px", "turnover"):
            data[k].index = pd.to_datetime(data[k].index)
        for k in ("index", "bench"):
            data[k].index = pd.to_datetime(data[k].index)
        data["storylines"] = job.get("storylines") or {}
        ohlc = {n: pd.read_parquet(f / f"{n}_ratio.parquet") for n in ("open", "high", "low") if (f / f"{n}_ratio.parquet").exists()}
        for df in ohlc.values():
            df.index = pd.to_datetime(df.index)
        if ohlc:
            data["ohlc"] = ohlc                                                # S81: the day's range as ratios to the close (the daily replay's stops and targets)
        if (f / "results.json").exists():
            data["results"] = json.loads((f / "results.json").read_text(encoding="utf-8"))   # {key: [dates the financial results became known]}
        if (f / "extra.json").exists():
            data.update(json.loads((f / "extra.json").read_text(encoding="utf-8")))          # {"index_key": ...}
        if job.get("mode") == "harvest":                                       # S81 claim B: each arm with and without harvesting
            import swing
            arms = {}
            for p in job["policies"]:
                arms[p["id"]] = _load(f / p["file"], "pol_" + p["id"].replace("-", "_").replace(".", "_")).decide
            if data.get("index_key"):
                arms["index"] = None
            start, end = job["window"]
            out["results"]["harvest"] = swing.harvest_experiment(arms, data, start, end, job.get("cfg"))
            raise StopIteration
        if job.get("mode") == "c4":                                            # S82: harvesting where it can help, and stops on long-term stocks (protocol s82_harvest_stops)
            import c4_replay
            start, end = job["window"]
            out["results"]["c4"] = c4_replay.run_all(data, start, end, job.get("cfg"))
            raise StopIteration
        if job.get("mode") == "now":                                       # shadow: today's target weights of each policy, from its own previous shadow weights
            for p in job["policies"]:
                try:
                    mod = _load(f / p["file"], "pol_" + p["id"].replace("-", "_").replace(".", "_"))
                    w = engine.decision_now(mod.decide, job["params"].get(p["id"]) or {}, data, job["day"], (job.get("prev") or {}).get(p["id"]), job.get("cfg"))
                    out["results"][p["id"]] = {"weights": {k: float(v) for k, v in w.items()}}
                except Exception as e:
                    out["errors"][p["id"]] = f"{type(e).__name__}: {e}"[:600] + "\n" + traceback.format_exc()[-900:]
            raise StopIteration
        start, end = job["window"]
        for p in job["policies"]:
            try:
                mod = _load(f / p["file"], "pol_" + p["id"].replace("-", "_").replace(".", "_"))
                grid = job.get("grid", {}).get(p["id"]) or [{}]
                out["results"][p["id"]] = engine.evaluate(mod.decide, grid, data, start, end, job.get("cfg"), int(job.get("n_shuffles", 20)), int(job.get("n_mc", 1000)), int(job.get("seed", 80)),
                                                          cadence=str(getattr(mod, "CADENCE", "monthly")))
            except Exception as e:                                           # one policy failing is a finding for the strategist, not the end of the run
                out["errors"][p["id"]] = f"{type(e).__name__}: {e}"[:600] + "\n" + traceback.format_exc()[-900:]
    except StopIteration:
        pass
    except Exception as e:
        out["fatal"] = f"{type(e).__name__}: {e}"[:600] + "\n" + traceback.format_exc()[-900:]
    out["seconds"] = round(time.time() - t0, 2)
    dest = Path(os.environ.get("PFLAB_OUT") or f)
    (dest / "out.json").write_text(json.dumps(out, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
