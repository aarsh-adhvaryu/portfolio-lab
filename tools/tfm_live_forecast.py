"""S52 live forecasts (quant/tfm2_live.py): TimesFM on tonight's inputs, with the study's own model wrappers and options
(tools/timesfm2_forecast.py), on the CPU by default (a few dozen series; the laptop GPU stays free). Runs in .venv-train,
offline (HF_HUB_OFFLINE=1: the weights are in the Hugging Face cache).

    .venv-train\\Scripts\\python tools\\tfm_live_forecast.py <inputs.json> <deciles.json> [--gpu]

    turnover  T30C: TimesFM 3.0, past-and-future calendar covariates, 5 sessions      -> (5, 9) per stock
    revenue   F25: TimesFM 2.5 with the weights fine-tuned on the company's OTHER fold -> (9,) per company
    margin    T25: TimesFM 2.5 zero-shot                                               -> (9,) per company
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import timesfm2_forecast as tff  # noqa: E402


def _short_sha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:12]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    gpu = "--gpu" in argv
    fin, fout = [a for a in argv if not a.startswith("--")][:2]
    device = None if gpu else "cpu"
    if not gpu:
        import torch                                        # as the smoke test: never touch the GPU on the CPU path
        torch.cuda.is_available = lambda: False
    d = json.loads(Path(fin).read_text(encoding="utf-8"))
    out: dict = {"asof": d["asof"], "models": {}, "turnover": {}, "revenue": {}, "margin": {}}

    if d.get("turnover"):
        m = tff.load_model("T30C", 512, 128, device)
        ctxs = [np.asarray(c["ctx"], np.float32) for c in d["turnover"]]
        pf = [np.asarray(c["pf"], np.float32) for c in d["turnover"]]
        q = tff.batched(m, ctxs, tff.H5, None, pf)
        out["turnover"] = {c["key"]: q[i].tolist() for i, c in enumerate(d["turnover"]) if np.isfinite(q[i]).all()}
        out["models"]["turnover"] = "T30C google/timesfm-3.0-pytorch"
        del m

    if d.get("revenue"):
        shas = []
        for fold in ("A", "B"):
            sel = [c for c in d["revenue"] if c["fold"] == fold]
            if not sel:
                continue
            try:
                w = tff.ft_weights("q6_ln_revenue", fold)           # the model trained on the other fold
            except FileNotFoundError:                               # S63: a fresh install has none: revenue alone
                shas.append(f"fold {fold} weights missing")         # falls back (the baseline serves), the rest runs
                continue
            shas.append(f"{Path(w).parent.name}:{_short_sha(w)}")
            m = tff.load_model("F25", 64, 128, device, w)
            q = tff.batched(m, [np.asarray(c["ctx"], np.float32) for c in sel], 1)
            out["revenue"].update({c["key"]: q[i, 0].tolist() for i, c in enumerate(sel) if np.isfinite(q[i]).all()})
            del m
        out["models"]["revenue"] = "F25 " + ",".join(shas)

    if d.get("margin"):
        m = tff.load_model("T25", 64, 128, device)
        q = tff.batched(m, [np.asarray(c["ctx"], np.float32) for c in d["margin"]], 1)
        out["margin"] = {c["key"]: q[i, 0].tolist() for i, c in enumerate(d["margin"]) if np.isfinite(q[i]).all()}
        out["models"]["margin"] = "T25 google/timesfm-2.5-200m-pytorch"
        del m

    tmp = Path(fout).with_suffix(".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    tmp.replace(fout)
    print(f"LIVE FORECASTS {d['asof']}: turnover {len(out['turnover'])}, revenue {len(out['revenue'])}, "
          f"margin {len(out['margin'])}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
