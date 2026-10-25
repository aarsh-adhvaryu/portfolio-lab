"""S52 (docs/research/timesfm2_protocol.md, amendment 2): LoRA fine-tuning of TimesFM 2.5 for Q1 (by market fold) and
Q6 (by company fold). Runs in .venv-train (torch, peft 0.21.2, timesfm 3.0.2).

The training forward pass is the model's own prefill (patching, running RevIN, the 20 layers, the point and quantile
heads, the continuous-quantile combination) with gradients; `check` proves it equals the library's forecast before any
training. Flip augmentation (x -> -x, quantiles reversed) keeps training consistent with flip-invariant inference.
Loss: mean pinball over the nine deciles + squared error of the mean channel, in the series' own normalised units.

Per (task, fold): one run per rank r in {8, 16}, constant learning rate, adapters saved at 1000 and 3000 steps (the
same as separate 1000- and 3000-step runs; amendment 5 restored this after amendments 3-4 had cut it); the setting with the lowest inner-validation pinball is merged into the base
weights and written to ft/<task>_<fold>/model.safetensors with meta.json. Checkpoints every 250 steps; a stopped run
resumes.

    .venv-train\\Scripts\\python tools\\timesfm2_finetune.py check
    .venv-train\\Scripts\\python tools\\timesfm2_finetune.py probe                  # GPU memory, worst case
    .venv-train\\Scripts\\python tools\\timesfm2_finetune.py q1 [--folds A,B]
    .venv-train\\Scripts\\python tools\\timesfm2_finetune.py q6 [--folds A,B]       # both targets
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

SEED = 20261020
RANKS = (8, 16)          # amendment 5 (2026-10-21, before any fine-tuning): the registered grid restored
SAVE_AT = (1000, 3000)
if os.environ.get("PFLAB_FT_SMOKE"):      # a tiny real run (train, save, merge, reload) to test the path end to end
    RANKS, SAVE_AT = (8,), (2, 4)
LR, BATCH, DROPOUT = 1e-4, 64, 0.05
MIN_FINITE = 8           # a window with fewer known values is not trained on (as in forecasting)
CLIP = 10.0              # amendment 5: training targets clipped at +-10 sd of their own window (margins reach 2,332)
DECILES = np.round(np.arange(1, 10) / 10, 1)
TARGETS = ["qkv_proj", "out", "ff0", "ff1"]
Q1 = {"h": 10, "contexts": (512, 1024), "train_to": "2012-12-31", "inner": ("2013-01-01", "2014-12-31")}
Q6 = {"h": 1, "contexts": (64,), "train_to": "2015-12-31", "inner": ("2016-01-01", "2017-12-31")}
FOLD_A = ("US_SP500", "DE_DAX", "JP_NIKKEI225", "HK_HANGSENG", "AU_ASX200")
FOLD_B = ("UK_FTSE100", "KR_KOSPI", "TW_TAIEX", "CN_SHANGHAI", "BR_BOVESPA")


def folder() -> Path:
    return Path(os.environ.get("PFLAB_DATA_DIR", r"D:\portfolio_lab\data")) / "research" / "timesfm2"


# --- the model's own forward, with gradients ----------------------------------------------------------------------------

def forward_deciles(module, x, mask, h):
    """x (B, C) float32, mask (B, C) bool (True = padding), C a multiple of 32 -> (B, h, 10) in normalised units
    [mean, deciles], and the global (mu, sigma) to undo them. Mirrors TimesFM_2p5_200M_torch.compile's decode for
    horizons <= 128 without flip averaging (that is applied by the caller)."""
    import torch
    from timesfm.torch import util
    mu = torch.mean(x, dim=-1, keepdim=True)
    sigma = torch.std(x, dim=-1, keepdim=True)
    xn = util.revin(x, mu, sigma, reverse=False)
    b = xn.shape[0]
    p = module.p
    pi = xn.reshape(b, -1, p)
    pm = mask.reshape(b, -1, p)
    n = torch.zeros(b, device=x.device)
    m_ = torch.zeros(b, device=x.device)
    s_ = torch.zeros(b, device=x.device)
    pmu, psg = [], []
    for i in range(pi.shape[1]):
        (n, m_, s_), _ = util.update_running_stats(n, m_, s_, pi[:, i], pm[:, i])
        pmu.append(m_)
        psg.append(s_)
    cmu, csg = torch.stack(pmu, 1), torch.stack(psg, 1)
    normed = util.revin(pi, cmu, csg, reverse=False)
    normed = torch.where(pm, 0.0, normed)
    (_, _, out_ts, out_qs), _ = module(normed, pm)
    pf = util.revin(out_ts, cmu, csg, reverse=True).reshape(b, -1, module.o, module.q)[:, -1]
    qs = util.revin(out_qs, cmu, csg, reverse=True).reshape(b, -1, module.os, module.q)[:, -1]
    full = pf.clone()
    for qi in (1, 2, 3, 4, 6, 7, 8, 9):
        full[:, :, qi] = qs[:, :module.o, qi] - qs[:, :module.o, 5] + pf[:, :, 5]
    return full[:, :h], mu, sigma


def clean(w) -> np.ndarray:
    """The library's own input cleaning (TimesFM_2p5.forecast): leading NaNs dropped, inner NaNs interpolated, so a
    window is seen in training exactly as it is at inference."""
    from timesfm.timesfm_2p5.timesfm_2p5_base import linear_interpolation, strip_leading_nans
    return np.asarray(linear_interpolation(strip_leading_nans(np.asarray(w, np.float32))), np.float32)


def enough(w) -> bool:
    return int(np.isfinite(np.asarray(w, float)).sum()) >= MIN_FINITE


def pad(ctxs, c):
    """Clean each window as the library does, keep its last c values, front-pad the rest (masked), as forecast()."""
    x = np.zeros((len(ctxs), c), np.float32)
    m = np.ones((len(ctxs), c), bool)
    for i, w in enumerate(ctxs):
        w = clean(w)[-c:]
        x[i, c - len(w):] = w
        m[i, c - len(w):] = False
    return x, m


def flip(q):
    """Quantile order for -x: mean negated, deciles negated and reversed."""
    import torch
    return torch.cat([-q[..., :1], torch.flip(-q[..., 1:], dims=(-1,))], dim=-1)


def loss_fn(pred, y):
    import torch
    lv = torch.tensor(DECILES, device=pred.device, dtype=pred.dtype)
    u = y[..., None] - pred[..., 1:]
    pin = torch.maximum(lv * u, (lv - 1) * u).mean()
    return pin + ((pred[..., 0] - y) ** 2).mean()


# --- data ---------------------------------------------------------------------------------------------------------------

def q1_samples(fold: str, kind: str):
    """(series list, [(series, t)] train, [(series, t)] inner) for the fold's markets."""
    names = FOLD_A if fold == "A" else FOLD_B
    series, train, inner = [], [], []
    for m in names:
        d = np.load(folder() / "inputs" / f"q1_{m}.npz")
        x, dates = d[f"x_{kind}"], d["dates"]
        k = len(series)
        series.append(x)
        for t in range(64, len(x) - Q1["h"]):
            end = dates[t + Q1["h"]]
            if not (enough(x[max(0, t - 63):t + 1]) and np.isfinite(x[t + 1:t + 1 + Q1["h"]]).all()):
                continue
            if end <= Q1["train_to"]:
                train.append((k, t))
            elif Q1["inner"][0] <= dates[t] <= Q1["inner"][1]:
                inner.append((k, t))
    return series, train, inner


def q6_samples(fold: str, target: str):
    d = np.load(folder() / "inputs" / "q6.npz")
    x, qe, fc, rs, fo = d[target], d["quarter_end"], d["forecastable"], d["run_start"], d["fold"]
    train, inner = [], []
    for i in np.flatnonzero(fc & (fo == fold) & np.isfinite(x)):
        if not enough(x[rs[i]:i]):
            continue
        item = (int(rs[i]), int(i))
        if qe[i] <= Q6["train_to"]:
            train.append(item)
        elif Q6["inner"][0] <= qe[i] <= Q6["inner"][1]:
            inner.append(item)
    return x, train, inner


def batch_q1(series, items, h, rng, ctx=None):
    cs, ys = [], []
    c = ctx or int(rng.choice(Q1["contexts"]))
    for k, t in items:
        x = series[k]
        cs.append(x[max(0, t + 1 - c):t + 1])
        ys.append(x[t + 1:t + 1 + h])
    xb, mb = pad(cs, c)
    return xb, mb, np.asarray(ys, np.float32)


def batch_q6(x, items):
    cs = [x[s:i] for s, i in items]
    ys = [[x[i]] for _s, i in items]
    xb, mb = pad(cs, Q6["contexts"][0])
    return xb, mb, np.asarray(ys, np.float32)


# --- training -------------------------------------------------------------------------------------------------------------

def base_module(device):
    import timesfm
    w = timesfm.TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch", torch_compile=False)
    mod = w.model.to(device)
    return w, mod


def run_rank(task, fold, r, make_batch, inner_eval, out: Path, device) -> dict:
    """Train one LoRA rank; returns {steps: inner pinball} for the saved checkpoints."""
    import torch
    from peft import LoraConfig, get_peft_model, set_peft_model_state_dict, get_peft_model_state_dict
    torch.manual_seed(SEED + r)
    rng = np.random.default_rng(SEED + r)
    _, mod = base_module(device)
    for p in mod.parameters():
        p.requires_grad_(False)
    pm = get_peft_model(mod, LoraConfig(r=r, lora_alpha=2 * r, lora_dropout=DROPOUT, target_modules=TARGETS))
    opt = torch.optim.AdamW([p for p in pm.parameters() if p.requires_grad], lr=LR)
    ck = out / f"r{r}_ckpt.pt"
    step, scores = 0, {}
    if ck.exists():
        st = torch.load(ck, map_location=device)
        set_peft_model_state_dict(pm, st["lora"])
        opt.load_state_dict(st["opt"])
        step, scores = st["step"], st["scores"]
        rng = np.random.default_rng(SEED + r + step)
        print(f"  resumed {task} {fold} r{r} at step {step}", flush=True)
    pm.train()
    t0 = time.time()
    while step < max(SAVE_AT):
        xb, mb, yb = make_batch(rng)
        x = torch.from_numpy(xb).to(device)
        m = torch.from_numpy(mb).to(device)
        y = torch.from_numpy(yb).to(device)
        if rng.random() < 0.5:                               # flip augmentation
            x, y, flipped = -x, -y, True
        else:
            flipped = False
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device != "cpu"):
            pred, mu, sg = forward_deciles(pm.base_model.model, x, m, y.shape[1])
        yn = ((y - mu) / torch.where(sg < 1e-6, 1.0, sg)).clamp(-CLIP, CLIP)
        loss = loss_fn(pred.float(), yn)
        opt.zero_grad(set_to_none=True)
        if torch.isfinite(loss):
            loss.backward()
            opt.step()
        else:                                                # never let one bad batch poison the adapter
            print(f"  {task} {fold} r{r} step {step + 1}: non-finite loss, batch skipped", flush=True)
        step += 1
        if step % 50 == 0:
            print(f"  {task} {fold} r{r} step {step} loss {loss.item():.4f} ({(time.time() - t0) / 60:.1f} min)", flush=True)
        if step in SAVE_AT:
            pm.eval()
            scores[step] = inner_eval(pm.base_model.model)
            torch.save(get_peft_model_state_dict(pm), out / f"r{r}_s{step}.pt")
            print(f"  {task} {fold} r{r} step {step}: inner pinball {scores[step]:.5f}", flush=True)
            pm.train()
        if step % 250 == 0 or step in SAVE_AT:
            torch.save({"lora": get_peft_model_state_dict(pm), "opt": opt.state_dict(), "step": step, "scores": scores}, ck)
    return scores


def inner_pinball(module, batches, device) -> float:
    """Mean pinball over the deciles on the inner validation, flip-averaged as at inference, in normalised units."""
    import torch
    tot, n = 0.0, 0
    with torch.no_grad():
        for xb, mb, yb in batches:
            x, m, y = (torch.from_numpy(a).to(device) for a in (xb, mb, yb))
            p1, mu, sg = forward_deciles(module, x, m, y.shape[1])
            p2, _, _ = forward_deciles(module, -x, m, y.shape[1])
            pred = (p1 + flip(p2)) / 2
            yn = ((y - mu) / torch.where(sg < 1e-6, 1.0, sg)).clamp(-CLIP, CLIP)
            lv = torch.tensor(DECILES, device=device)
            u = yn[..., None] - pred[..., 1:]
            tot += float(torch.maximum(lv * u, (lv - 1) * u).mean()) * len(xb)
            n += len(xb)
    return tot / max(n, 1)


def finish(task, fold, out: Path, scores_by_rank: dict, device) -> None:
    """Merge the best (rank, steps) into the base weights; write model.safetensors and meta.json."""
    import torch
    from peft import LoraConfig, get_peft_model, set_peft_model_state_dict
    from safetensors.torch import save_file
    best = min(((r, s, v) for r, sc in scores_by_rank.items() for s, v in sc.items()), key=lambda z: z[2])
    r, s, v = best
    _, mod = base_module(device)
    pm = get_peft_model(mod, LoraConfig(r=r, lora_alpha=2 * r, lora_dropout=DROPOUT, target_modules=TARGETS))
    set_peft_model_state_dict(pm, torch.load(out / f"r{r}_s{s}.pt", map_location=device))
    merged = pm.merge_and_unload()
    save_file({k: t.contiguous().cpu() for k, t in merged.state_dict().items()}, str(out / "model.safetensors"))
    (out / "meta.json").write_text(json.dumps({"task": task, "fold": fold, "rank": r, "steps": s, "inner_pinball": v,
                                               "all": {str(k): {str(a): b for a, b in sc.items()}
                                                       for k, sc in scores_by_rank.items()}}, indent=1))
    print(f"  {task} {fold}: chose r{r} at {s} steps (inner pinball {v:.5f}) -> {out / 'model.safetensors'}", flush=True)


def train_task(task: str, fold: str, device: str) -> None:
    out = folder() / ("ft_smoke" if os.environ.get("PFLAB_FT_SMOKE") else "ft") / f"{task}_{fold}"
    if (out / "model.safetensors").exists():
        print(f"{task} {fold}: done already", flush=True)
        return
    out.mkdir(parents=True, exist_ok=True)
    rng_inner = np.random.default_rng(SEED)
    if task == "q1":
        kind = json.loads((folder() / "choices.json").read_text())["F25_input"]
        series, train, inner = q1_samples(fold, kind)
        pick = rng_inner.choice(len(inner), size=min(2048, len(inner)), replace=False)
        inner_b = [batch_q1(series, [inner[i] for i in pick[j:j + BATCH]], Q1["h"], rng_inner, ctx=1024)
                   for j in range(0, len(pick), BATCH)]

        def make(rng):
            return batch_q1(series, [train[i] for i in rng.integers(0, len(train), BATCH)], Q1["h"], rng)
    else:
        target = task.replace("q6_", "")
        x, train, inner = q6_samples(fold, target)
        inner_b = [batch_q6(x, inner[j:j + BATCH]) for j in range(0, len(inner), BATCH)]

        def make(rng):
            return batch_q6(x, [train[i] for i in rng.integers(0, len(train), BATCH)])
    print(f"{task} {fold}: {len(train)} training samples, {len(inner)} inner validation", flush=True)
    scores = {r: run_rank(task, fold, r, make, lambda mod: inner_pinball(mod, inner_b, device), out, device)
              for r in RANKS}
    finish(task, fold, out, scores, device)


# --- checks -----------------------------------------------------------------------------------------------------------------

def check(device: str) -> int:
    """The training forward (flip-averaged) must equal the library's forecast, deciles and mean, on real inputs."""
    import timesfm
    import torch
    rng = np.random.default_rng(1)
    d = np.load(folder() / "inputs" / "q1_US_SP500.npz")
    x = d["x_log"]
    ts = d["idx"][rng.choice(len(d["idx"]), 4, replace=False)]
    ctxs = [x[t - 511:t + 1] for t in ts]
    w, mod = base_module(device)
    w.compile(timesfm.ForecastConfig(max_context=512, max_horizon=128, normalize_inputs=True, per_core_batch_size=4,
                                     use_continuous_quantile_head=True, force_flip_invariance=True,
                                     infer_is_positive=False, fix_quantile_crossing=False))
    _, lib = w.forecast(horizon=10, inputs=[c.astype(np.float32) for c in ctxs])
    xb, mb = pad(ctxs, 512)
    with torch.no_grad():
        xt, mt = torch.from_numpy(xb).to(device), torch.from_numpy(mb).to(device)
        p1, mu, sg = forward_deciles(mod, xt, mt, 10)
        p2, _, _ = forward_deciles(mod, -xt, mt, 10)
        mine = ((p1 + flip(p2)) / 2 * sg[..., None] + mu[..., None]).cpu().numpy()
    err = float(np.abs(mine - lib).max())
    print(f"check: max |training forward - library forecast| = {err:.2e} over {mine.shape}", flush=True)
    if err > 1e-3:
        print("CHECK FAILED", flush=True)
        return 1
    print("CHECK OK", flush=True)
    return 0


def probe(device: str) -> int:
    """Peak GPU memory for one training step at the worst case (context 1024, batch 64, rank 16)."""
    import torch
    from peft import LoraConfig, get_peft_model
    _, mod = base_module(device)
    for p in mod.parameters():
        p.requires_grad_(False)
    pm = get_peft_model(mod, LoraConfig(r=16, lora_alpha=32, lora_dropout=DROPOUT, target_modules=TARGETS))
    opt = torch.optim.AdamW([p for p in pm.parameters() if p.requires_grad], lr=LR)
    torch.cuda.reset_peak_memory_stats()
    timing = {}
    for c, h, n in ((1024, 10, 12), (512, 10, 12), (64, 1, 12)):    # Q1's two contexts, then Q6's
        x = torch.randn(BATCH, c, device=device)
        m = torch.zeros(BATCH, c, dtype=torch.bool, device=device)
        y = torch.randn(BATCH, h, device=device)
        for k in range(n + 2):                                    # two warm-up steps, then timed
            if k == 2:
                torch.cuda.synchronize()
                t0 = time.time()
            with torch.autocast("cuda", dtype=torch.bfloat16):
                pred, mu, sg = forward_deciles(pm.base_model.model, x, m, h)
            loss = loss_fn(pred.float(), (y - mu) / sg)
            opt.zero_grad()
            loss.backward()
            opt.step()
        torch.cuda.synchronize()
        timing[c] = (time.time() - t0) / n
    print(f"probe: peak {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB, "
          + ", ".join(f"context {c}: {s:.2f} s/step" for c, s in timing.items()), flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=["check", "probe", "q1", "q6"])
    ap.add_argument("--folds", default="A,B")
    ap.add_argument("--cpu", action="store_true", help="hide the GPU (check only; training needs the GPU)")
    a = ap.parse_args(argv)
    import torch
    if a.cpu:                       # CUDA_VISIBLE_DEVICES="" leaves torch half-seeing the GPU on Windows: say no outright
        torch.cuda.is_available = lambda: False
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if a.step == "check":
        return check(device)
    if a.step == "probe":
        return probe(device)
    if device == "cpu":
        print("training needs the GPU", flush=True)
        return 2
    tasks = ["q1"] if a.step == "q1" else ["q6_ln_revenue", "q6_margin"]
    for task in tasks:
        for fold in a.folds.split(","):
            train_task(task, fold.strip(), device)
    print("FINETUNE DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
