"""S52 (docs/research/timesfm2_protocol.md): TimesFM 2.5 and 3.0 forecasts for Q1-Q6. Runs in .venv-train.

Reads the inputs `tools/timesfm2_study.py prepare` wrote (PFLAB_DATA_DIR/research/timesfm2/inputs) and writes deciles:
    forecasts/q1/<cand>/<input>_<ctx>/<market>.npz   q (n, 10, 9)  deciles of the log-variance input, t+1..t+10
    forecasts/q3/<cand>/<market>.npz                 q (n, 3, 9)   deciles of ln C(t+h) - ln C(t), h = 63, 126, 252
    forecasts/q5/<cand>/<isin>.npz                   q (n, 5, 9)   deciles of daily ln turnover, t+1..t+5
    forecasts/q6/<cand>/<target>.npz                 q (n, 9)      deciles of next quarter's ln revenue or margin
Candidates: T25 / T30 zero-shot, T30X (3.0 + ln US VIX, past only), T30C (3.0 + calendar, past and future), F25 (2.5
fine-tuned by tools/timesfm2_finetune.py, the other fold's weights). Each file is written once (temp file, then rename):
a stopped run resumes where it stopped.

    .venv-train\\Scripts\\python tools\\timesfm2_forecast.py smoke          # CPU, a few series, nothing saved
    .venv-train\\Scripts\\python tools\\timesfm2_forecast.py probe          # GPU memory at the worst case
    .venv-train\\Scripts\\python tools\\timesfm2_forecast.py run [--tasks q1,q3,q5,q6] [--cands T25,T30,T30X,T30C,F25]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

H1, H5 = 10, 5
RANGE_H = (63, 126, 252)
INPUTS = ("log", "log5")
CONTEXTS = (512, 1024)
BATCH = 128         # a steady full load (amendment 4: the stop-start temperature guard and batch 32 were removed)


def folder() -> Path:
    return Path(os.environ.get("PFLAB_DATA_DIR", r"D:\portfolio_lab\data")) / "research" / "timesfm2"


def save(path: Path, **arrays) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.npz")
    np.savez(tmp, **arrays)
    os.replace(tmp, path)


def windows(x: np.ndarray, idx: np.ndarray, ctx: int, cov: np.ndarray | None = None):
    """Context for a forecast at t: x[t-ctx+1 .. t] (data up to t only), leading NaNs dropped. With `cov` (k, n), the
    covariate rows over exactly the same positions are returned too (k, len)."""
    xs, cs = [], []
    for t in idx:
        s = max(0, t + 1 - ctx)
        w = x[s:t + 1].astype(np.float32)
        ok = np.flatnonzero(np.isfinite(w))
        a = ok[0] if len(ok) else 0
        xs.append(w[a:])
        if cov is not None:
            cs.append(np.atleast_2d(cov)[:, s + a:t + 1].astype(np.float32))
    return xs if cov is None else (xs, cs)


# --- models --------------------------------------------------------------------------------------------------------------

class V25:
    """TimesFM 2.5: continuous quantile head, flip invariance, quantile crossing fixed, no positivity (log inputs)."""

    def __init__(self, max_context: int, max_horizon: int, weights: str | None = None, device: str | None = None):
        import timesfm                                       # CPU-only runs switch CUDA off in main(), before this
        self.m = timesfm.TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch", torch_compile=False)
        if weights:
            self.m.model.load_checkpoint(weights)
        self.m.compile(timesfm.ForecastConfig(max_context=max_context, max_horizon=max_horizon, normalize_inputs=True,
                                              per_core_batch_size=BATCH, use_continuous_quantile_head=True,
                                              force_flip_invariance=True, infer_is_positive=False,
                                              fix_quantile_crossing=True))

    def deciles(self, ctxs: list, h: int, po=None, pf=None) -> np.ndarray:
        if po is not None or pf is not None:
            raise ValueError("2.5 runs without covariates here (amendment 1)")
        _, full = self.m.forecast(horizon=h, inputs=list(ctxs))
        return np.asarray(full, np.float32)[:, :h, 1:10]          # channel 0 is the mean; 1..9 the deciles


class V30:
    """TimesFM 3.0: quantiles returned and sorted, symmetric averaging, no positivity; covariates native, per series."""

    def __init__(self, device: str | None = None):
        import timesfm
        self.m = timesfm.TimesFM3Forecaster.from_pretrained("google/timesfm-3.0-pytorch", device=device or "cuda",
                                                           per_core_batch_size=BATCH)
        assert list(self.m.config.quantiles) == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9], self.m.config.quantiles

    def deciles(self, ctxs: list, h: int, po=None, pf=None) -> np.ndarray:
        outs = self.m.predict_batch(list(ctxs), horizon=h, past_only_covariates=po, past_future_covariates=pf,
                                    return_quantiles=True, use_symmetric_averaging=True, make_positive=False,
                                    sort_quantiles=True)
        return np.stack([np.asarray(o.quantiles, np.float32)[:h, :9] for o in outs])


MIN_FINITE = 8      # a context with fewer known values (a stock that did not trade, a margin never reported) gets no
                    # forecast (NaN): TimesFM's own input cleaning fails on an empty series (2026-10-21, Q5)


def batched(model, ctxs, h, po=None, pf=None, size=BATCH) -> np.ndarray:
    res = np.full((len(ctxs), h, 9), np.nan, np.float32)
    keep = [i for i, c in enumerate(ctxs) if np.isfinite(c).sum() >= MIN_FINITE]
    for j in range(0, len(keep), size):
        ix = keep[j:j + size]
        res[ix] = model.deciles([ctxs[i] for i in ix], h, None if po is None else [po[i] for i in ix],
                                None if pf is None else [pf[i] for i in ix])
    return res


def load_model(cand: str, max_context: int, max_horizon: int, device=None, weights=None):
    if cand in ("T25", "F25"):
        return V25(max_context, max_horizon, weights, device)
    return V30(device)


# --- tasks ---------------------------------------------------------------------------------------------------------------

def inputs(name: str) -> dict:
    d = np.load(folder() / "inputs" / name, allow_pickle=False)
    return {k: d[k] for k in d.files}


def q1_files():
    return sorted(p.name for p in (folder() / "inputs").glob("q1_*.npz"))


def ft_weights(task: str, fold: str) -> str:
    """F25 for a market of fold A uses the model fine-tuned on fold B, and the other way round."""
    other = {"A": "B", "B": "A"}[fold]
    p = folder() / "ft" / f"{task}_{other}" / "model.safetensors"
    if not p.exists():
        raise FileNotFoundError(f"{p}: run tools/timesfm2_finetune.py {task} first")
    return str(p)


def task_q1(cands, smoke=False, device=None) -> None:
    choice = json.loads((folder() / "choices.json").read_text()) if (folder() / "choices.json").exists() else {}
    for cand in cands:
        if cand == "T30C":
            continue
        kinds = [choice["F25_input"]] if cand == "F25" else list(INPUTS)
        folds = ("A", "B", "-") if cand == "F25" else ("all",)
        for fold in folds:
            files = [f for f in q1_files() if cand != "F25" or inputs(f)["fold"].item() == fold]
            if cand == "F25" and (not files or fold == "-"):
                continue                                   # the Nifty is described with the zero-shot models only
            model = load_model(cand, max(CONTEXTS), 128, device, ft_weights("q1", fold) if cand == "F25" else None)
            for kind in kinds:
                for ctx in CONTEXTS:
                    for f in files[:1] if smoke else files:
                        out = folder() / "forecasts" / "q1" / cand / f"{kind}_{ctx}" / f.replace("q1_", "")
                        if out.exists() and not smoke:
                            continue
                        d = inputs(f)
                        idx = d["idx"][:3] if smoke else d["idx"]
                        x = d[f"x_{kind}"]
                        po = None
                        if cand == "T30X":
                            if not np.isfinite(d["lnvix"]).any():
                                continue
                            cw, po = windows(x, idx, ctx, d["lnvix"])
                        else:
                            cw = windows(x, idx, ctx)
                        t0 = time.time()
                        q = batched(model, cw, H1, po)
                        if smoke:
                            print(f"  smoke q1 {cand} {kind} {ctx} {f}: {q.shape} sorted={bool((np.diff(q, axis=-1) >= -1e-5).all())}"
                                  f" finite={bool(np.isfinite(q).all())}", flush=True)
                            continue
                        save(out, dates=d["dates"][idx], q=q)
                        print(f"  q1 {cand} {kind}_{ctx} {f}: {len(idx)} in {time.time() - t0:.0f} s", flush=True)
            del model


def task_q3(cands, smoke=False, device=None) -> None:
    for cand in [c for c in cands if c in ("T25", "T30")]:
        model = load_model(cand, 1024, 256, device)
        for f in sorted(p.name for p in (folder() / "inputs").glob("q3_*.npz"))[:1 if smoke else None]:
            out = folder() / "forecasts" / "q3" / cand / f.replace("q3_", "")
            if out.exists() and not smoke:
                continue
            d = inputs(f)
            idx = d["idx"][:2] if smoke else d["idx"]
            lnc = d["lnc"]
            q = batched(model, windows(lnc, idx, 1024), max(RANGE_H))
            cum = np.stack([q[:, h - 1, :] - lnc[idx][:, None] for h in RANGE_H], axis=1)
            if smoke:
                print(f"  smoke q3 {cand} {f}: {cum.shape} median h252 {np.round(cum[:, 2, 4], 3)}", flush=True)
                continue
            save(out, dates=d["dates"][idx], q=cum.astype(np.float32))
            print(f"  q3 {cand} {f}: {len(idx)}", flush=True)
        del model


def task_q5(cands, smoke=False, device=None) -> None:
    files = sorted(p.name for p in (folder() / "inputs").glob("q5_*.npz"))
    for cand in [c for c in cands if c in ("T25", "T30", "T30C")]:
        model = load_model(cand, 512, 128, device)
        for f in files[:1] if smoke else files:
            out = folder() / "forecasts" / "q5" / cand / f.replace("q5_", "")
            if out.exists() and not smoke:
                continue
            d = inputs(f)
            idx = d["idx"][:3] if smoke else d["idx"]
            cw = windows(d["lt"], idx, 512)
            pf = None
            if cand == "T30C":                           # the calendar over the context AND the next 5 sessions
                pf = [d["cov"][:, t + 1 - len(c):t + 1 + H5].astype(np.float32) for t, c in zip(idx, cw)]
            q = batched(model, cw, H5, None, pf)
            if smoke:
                print(f"  smoke q5 {cand} {f}: {q.shape} finite={bool(np.isfinite(q).all())}", flush=True)
                continue
            save(out, dates=d["dates"][idx], q=q)
        print(f"  q5 {cand}: {len(files)} stocks", flush=True)
        del model


def task_q6(cands, smoke=False, device=None) -> None:
    d = inputs("q6.npz")
    for cand in [c for c in cands if c in ("T25", "T30", "F25")]:
        for target in ("ln_revenue", "margin"):
            out = folder() / "forecasts" / "q6" / cand / f"{target}.npz"
            if out.exists() and not smoke:
                continue
            rows = np.flatnonzero(d["forecastable"])[:5 if smoke else None]
            x = d[target]
            ctxs = [x[d["run_start"][i]:i].astype(np.float32) for i in rows]   # quarters up to i-1 only
            if cand == "F25":
                q = np.full((len(rows), 1, 9), np.nan, np.float32)
                for fold in ("A", "B"):
                    sel = np.flatnonzero(d["fold"][rows] == fold)
                    if not len(sel):
                        continue
                    model = load_model(cand, 64, 128, device, ft_weights(f"q6_{target}", fold))
                    q[sel] = batched(model, [ctxs[i] for i in sel], 1)
                    del model
            else:
                model = load_model(cand, 64, 128, device)
                q = batched(model, ctxs, 1)
                del model
            if smoke:
                print(f"  smoke q6 {cand} {target}: {q.shape} {np.round(q[:, 0, 4], 3)} vs {np.round(x[rows], 3)}",
                      flush=True)
                continue
            save(out, rows=rows, q=q[:, 0, :])
            print(f"  q6 {cand} {target}: {len(rows)}", flush=True)


TASKS = {"q1": task_q1, "q3": task_q3, "q5": task_q5, "q6": task_q6}


def probe() -> int:
    """Worst case for memory: 2.5 and 3.0 at context 1024, a full batch, the longest horizon."""
    import torch
    x = [np.random.default_rng(0).normal(size=1024).astype(np.float32) for _ in range(BATCH)]
    for name, mk in (("2.5", lambda: V25(1024, 256)), ("3.0", lambda: V30())):
        torch.cuda.reset_peak_memory_stats()
        m = mk()
        q = m.deciles(x, 252)
        print(f"probe {name}: {q.shape}, peak GPU {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB", flush=True)
        del m
        torch.cuda.empty_cache()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=["smoke", "probe", "run"])
    ap.add_argument("--tasks", default="q1,q3,q5,q6")
    ap.add_argument("--cands", default="T25,T30,T30X,T30C")
    a = ap.parse_args(argv)
    if a.step == "probe":
        return probe()
    smoke = a.step == "smoke"
    device = "cpu" if smoke else None
    if smoke:                                               # never touch the GPU from a smoke test (S47 may hold it)
        import torch                                        # CUDA_VISIBLE_DEVICES="" is not enough on Windows
        torch.cuda.is_available = lambda: False
    cands = [c.strip() for c in a.cands.split(",")]
    for t in a.tasks.split(","):
        print(f"{t} ...", flush=True)
        TASKS[t.strip()](cands, smoke=smoke, device=device)
    print("SMOKE OK" if smoke else "FORECASTS DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
