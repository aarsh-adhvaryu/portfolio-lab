"""Activation steering skeleton (A41, S79). Development only.

A steering direction is the mean hidden state of the positive prompts minus the mean of the negative prompts at one layer (contrastive
pairs: same facts, different behaviour). At inference a forward hook adds alpha * direction to that layer's output. No weights change,
so the result is an experiment on the base model, not a new GGUF; to reach the app it must be baked into weights (e.g. a LoRA trained
to reproduce it) and then pass run_evals.py through a registered comparison (rule 10). Prompts: public or invented text only.

    python tools/model_lab/steer.py --dry-run                       # validate prompts, print the plan; no torch needed
    python tools/model_lab/steer.py compute                         # direction -> outputs/steer_<name>.npy  (needs [ml] + GPU)
    python tools/model_lab/steer.py generate --prompt "..."         # steered vs plain generation side by side

Exit codes: 0 ok, 2 bad config, 3 the [ml] extra is missing. NOT YET RUN on a real model in S79; the numpy maths is tested.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_common as lab  # noqa: E402

ML_MODULES = ("torch", "transformers")


class SteerConfigError(ValueError):
    pass


def validate(cfg: dict) -> None:
    p, s = cfg.get("prompts", {}), cfg.get("steer", {})
    pos, neg = p.get("positive", []), p.get("negative", [])
    if not pos or len(pos) != len(neg):
        raise SteerConfigError(f"positive and negative must be non-empty lists of equal length (got {len(pos)} and {len(neg)})")
    if any(not str(x).strip() for x in list(pos) + list(neg)):
        raise SteerConfigError("an empty prompt")
    if s.get("token", "last") != "last":
        raise SteerConfigError("only token = 'last' is implemented")
    if not isinstance(s.get("layer"), int) or s["layer"] < 0 or not isinstance(s.get("alpha"), (int, float)):
        raise SteerConfigError("[steer] layer (int >= 0) and alpha (number) are required")


def direction(pos: Sequence[Sequence[float]], neg: Sequence[Sequence[float]]) -> Tuple[np.ndarray, float]:
    """(unit direction, raw norm) of mean(pos) - mean(neg). Rows are hidden states, one per prompt. Zero if the means coincide."""
    p, n = np.asarray(pos, dtype=np.float64), np.asarray(neg, dtype=np.float64)
    if p.ndim != 2 or p.shape != n.shape or len(p) == 0:
        raise SteerConfigError(f"pos and neg must be equal 2-D arrays, got {p.shape} and {n.shape}")
    d = p.mean(axis=0) - n.mean(axis=0)
    norm = float(np.linalg.norm(d))
    return (d / norm if norm > 0 else d), norm


def steered(hidden: np.ndarray, unit: np.ndarray, alpha: float) -> np.ndarray:
    """What the hook does to one layer's output: add alpha * unit direction to every position."""
    return np.asarray(hidden) + alpha * np.asarray(unit)


def plan(cfg: dict) -> List[str]:
    s, p = cfg["steer"], cfg["prompts"]
    gone = lab.missing(ML_MODULES)
    return [f"model       {cfg['model']['base']} ({cfg['model'].get('dtype', 'bfloat16')})",
            f"direction   '{s['name']}' from {len(p['positive'])} contrastive pairs, layer {s['layer']}, last-token hidden state",
            f"apply       forward hook on model.model.layers[{s['layer']}] adds {s['alpha']} * unit direction at inference",
            f"test        {len(p.get('test', []))} held-out prompt(s) for a side-by-side read",
            "extra       " + ("[ml] installed" if not gone else f"[ml] NOT installed (missing: {', '.join(gone)}); dry run does not need it")]


def _load(cfg: dict):  # pragma: no cover  (needs the extra and a GPU)
    mods = lab.require(*ML_MODULES)
    torch, tf = mods["torch"], mods["transformers"]
    tok = tf.AutoTokenizer.from_pretrained(cfg["model"]["base"])
    model = tf.AutoModelForCausalLM.from_pretrained(cfg["model"]["base"], torch_dtype=getattr(torch, cfg["model"].get("dtype", "bfloat16")),
                                                    device_map={"": 0})
    model.eval()
    return torch, tok, model


def compute_direction(cfg: dict) -> np.ndarray:  # pragma: no cover
    torch, tok, model = _load(cfg)
    layer = cfg["steer"]["layer"]

    def last_hidden(text: str) -> np.ndarray:
        ids = tok(text, return_tensors="pt").to(model.device)
        with torch.no_grad():
            hs = model(**ids, output_hidden_states=True).hidden_states[layer + 1]      # hidden_states[0] is the embedding output
        return hs[0, -1].float().cpu().numpy()

    pos = [last_hidden(t) for t in cfg["prompts"]["positive"]]
    neg = [last_hidden(t) for t in cfg["prompts"]["negative"]]
    unit, norm = direction(pos, neg)
    print(f"direction norm before scaling: {norm:.3f}")
    return unit


def generate(cfg: dict, unit: np.ndarray, prompt: str) -> Tuple[str, str]:  # pragma: no cover
    torch, tok, model = _load(cfg)
    s = cfg["steer"]
    vec = torch.tensor(unit, dtype=next(model.parameters()).dtype, device=model.device)

    def hook(_module, _inp, out):
        h = out[0] if isinstance(out, tuple) else out
        h = h + s["alpha"] * vec
        return (h,) + tuple(out[1:]) if isinstance(out, tuple) else h

    def run() -> str:
        ids = tok(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            o = model.generate(**ids, max_new_tokens=200, do_sample=False)
        return tok.decode(o[0, ids["input_ids"].shape[1]:], skip_special_tokens=True)

    plain = run()
    handle = model.model.layers[s["layer"]].register_forward_hook(hook)
    try:
        return plain, run()
    finally:
        handle.remove()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("action", nargs="?", choices=["compute", "generate"], default=None)
    ap.add_argument("--config", type=Path, default=lab.STEER_CONFIG)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--direction", type=Path, default=None, help=".npy written by compute (default outputs/steer_<name>.npy)")
    a = ap.parse_args(argv)
    try:
        cfg = lab.load_toml(a.config)
        validate(cfg)
    except (SteerConfigError, KeyError, OSError) as e:
        print(f"steer: {e}", file=sys.stderr)
        return 2
    for line in plan(cfg):
        print(line)
    if a.dry_run or a.action is None:
        print("dry run: nothing was computed")
        return 0
    path = a.direction or lab.OUTPUTS / f"steer_{cfg['steer']['name']}.npy"
    try:
        if a.action == "compute":
            unit = compute_direction(cfg)
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, unit)
            print(f"saved {path}")
        else:
            prompt = a.prompt or (cfg["prompts"].get("test") or [""])[0]
            plain, steer = generate(cfg, np.load(path), prompt)
            print(f"--- plain\n{plain}\n--- steered (alpha {cfg['steer']['alpha']})\n{steer}")
    except lab.MissingExtra as e:
        return lab.fail_missing(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
