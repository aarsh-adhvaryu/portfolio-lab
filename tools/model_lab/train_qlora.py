"""QLoRA fine-tune of qwen3 8B on the system's own guarded writing (A41, S79). Development only.

    python tools/model_lab/train_qlora.py --dry-run            # validates config + dataset, prints the plan; needs no torch; exit 0
    python tools/model_lab/train_qlora.py                      # the real run (needs the [ml] extra and a free GPU)

Exit codes: 0 ok, 2 bad config or dataset, 3 the [ml] extra is missing (a clear message, never a traceback).
A real run is a registered run (rule 10): the recipe in config/qlora_qwen3_8b.toml and the dataset SHA-256 are written to the
output folder beside the adapter, and the adapter is judged only by run_evals.py on the same sets as the base tag.
Before a long run, from an Administrator PowerShell:  nvidia-smi -lgc 210,2100   and   nvidia-smi -lmc 405,9001
(the laptop GPU drops off the bus at top boost). After a loss of the GPU use Restart, not Shut down.
NOT YET RUN: no training happened in S79; the trainer section below is written against trl 0.23 / peft 0.17 and is untested.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_common as lab  # noqa: E402

ML_MODULES = ("torch", "transformers", "peft", "trl", "bitsandbytes", "datasets", "accelerate")
REQUIRED = {"model": ("base", "ollama_base"), "quant": ("load_in_4bit", "bnb_4bit_quant_type", "compute_dtype"),
            "lora": ("r", "alpha", "dropout", "target_modules"),
            "train": ("seed", "learning_rate", "epochs", "max_len", "per_device_batch", "grad_accum"),
            "data": ("train", "valid", "min_examples"), "output": ("dir", "gguf_quant")}
ROLES = ("system", "user", "assistant")


class ConfigError(ValueError):
    pass


def load_config(path: Path) -> dict:
    cfg = lab.load_toml(path)
    problems = []
    for sec, keys in REQUIRED.items():
        for k in keys:
            if k not in cfg.get(sec, {}):
                problems.append(f"[{sec}] {k} is missing")
    if problems:
        raise ConfigError("; ".join(problems))
    t, l = cfg["train"], cfg["lora"]
    if not (0 < t["learning_rate"] < 1e-2):
        problems.append("learning_rate outside (0, 0.01)")
    if t["epochs"] < 1 or t["max_len"] < 128 or t["per_device_batch"] < 1 or t["grad_accum"] < 1:
        problems.append("epochs, max_len, per_device_batch, grad_accum out of range")
    if l["r"] < 1 or l["alpha"] < 1 or not (0 <= l["dropout"] < 1) or not l["target_modules"]:
        problems.append("lora r/alpha/dropout/target_modules out of range")
    if cfg["quant"]["compute_dtype"] not in ("bfloat16", "float16"):
        problems.append("compute_dtype must be bfloat16 or float16")
    if problems:
        raise ConfigError("; ".join(problems))
    return cfg


def validate_dataset(path: Path, min_examples: int) -> Dict[str, object]:
    """Every line {"messages": [system?, user, assistant]} with non-empty text and the assistant last."""
    if not path.exists():
        raise ConfigError(f"dataset {path} not found: run build_dataset.py on a ledger copy first")
    rows = lab.read_jsonl(path)
    chars = 0
    for i, r in enumerate(rows, 1):
        m = r.get("messages")
        if not isinstance(m, list) or len(m) < 2 or m[-1].get("role") != "assistant":
            raise ConfigError(f"{path.name} line {i}: messages must end with an assistant turn")
        for turn in m:
            if turn.get("role") not in ROLES or not str(turn.get("content", "")).strip():
                raise ConfigError(f"{path.name} line {i}: bad or empty turn {turn.get('role')!r}")
            chars += len(turn["content"])
    if len(rows) < min_examples:
        raise ConfigError(f"{path.name} has {len(rows)} examples, fewer than min_examples={min_examples}")
    return {"n": len(rows), "chars": chars, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def plan(cfg: dict, train: dict, valid: Optional[dict]) -> List[str]:
    t, l, q = cfg["train"], cfg["lora"], cfg["quant"]
    eff = t["per_device_batch"] * t["grad_accum"]
    steps = math.ceil(train["n"] / eff) * t["epochs"]
    tokens = int(train["chars"] / 3.5)
    gone = lab.missing(ML_MODULES)
    return [
        f"base            {cfg['model']['base']} (4-bit {q['bnb_4bit_quant_type']}, compute {q['compute_dtype']}); baseline tag {cfg['model']['ollama_base']}",
        f"lora            r={l['r']} alpha={l['alpha']} dropout={l['dropout']} targets={','.join(l['target_modules'])}",
        f"train           lr={t['learning_rate']} epochs={t['epochs']} max_len={t['max_len']} batch={t['per_device_batch']}x{t['grad_accum']}={eff} seed={t['seed']}"
        f" grad_ckpt={t.get('gradient_checkpointing', True)}",
        f"data            train {train['n']} examples (~{tokens:,} tokens/epoch), valid {valid['n'] if valid else 'none'}; sha256 {train['sha256'][:16]}...",
        f"steps           ~{steps} optimiser steps",
        f"output          {cfg['output']['dir']} (adapter), then merge_and_gguf.py -> {cfg['output']['gguf_quant']} GGUF",
        f"hardware        RTX 5070 Ti Laptop 12 GB: cap the clocks first: {' ; '.join(cfg.get('hardware', {}).get('clock_caps', []))}",
        "extra           " + ("[ml] installed" if not gone else f"[ml] NOT installed (missing: {', '.join(gone)}); a real run would stop here, a dry run does not need it"),
    ]


def train(cfg: dict, root: Path) -> int:  # pragma: no cover  (needs the [ml] extra and a GPU; not run in S79)
    mods = lab.require(*ML_MODULES)
    torch, transformers, peft, trl, datasets = (mods[k] for k in ("torch", "transformers", "peft", "trl", "datasets"))
    if not torch.cuda.is_available():
        print("train_qlora: no CUDA GPU visible to torch (install the cu128 wheel; check nvidia-smi)", file=sys.stderr)
        return 3
    free_gb = torch.cuda.mem_get_info()[0] / 2**30
    need = cfg.get("hardware", {}).get("min_vram_gb", 11.0)
    if free_gb < need:
        print(f"train_qlora: only {free_gb:.1f} GB of GPU memory free, need {need}; close Ollama models (ollama stop) and the app", file=sys.stderr)
        return 3
    t, l, q, out = cfg["train"], cfg["lora"], cfg["quant"], root / cfg["output"]["dir"]
    out.mkdir(parents=True, exist_ok=True)
    dtype = getattr(torch, q["compute_dtype"])
    bnb = transformers.BitsAndBytesConfig(load_in_4bit=q["load_in_4bit"], bnb_4bit_quant_type=q["bnb_4bit_quant_type"],
                                          bnb_4bit_use_double_quant=q.get("bnb_4bit_use_double_quant", True), bnb_4bit_compute_dtype=dtype)
    tok = transformers.AutoTokenizer.from_pretrained(cfg["model"]["base"])
    model = transformers.AutoModelForCausalLM.from_pretrained(cfg["model"]["base"], quantization_config=bnb, torch_dtype=dtype, device_map={"": 0})
    lora = peft.LoraConfig(r=l["r"], lora_alpha=l["alpha"], lora_dropout=l["dropout"], bias=l.get("bias", "none"),
                           target_modules=l["target_modules"], task_type=l.get("task_type", "CAUSAL_LM"))

    def split(ex):                                             # prompt/completion: loss on the assistant turn only
        return {"prompt": ex["messages"][:-1], "completion": [ex["messages"][-1]]}

    ds = {k: datasets.load_dataset("json", data_files=str(root / cfg["data"][k]), split="train").map(split, remove_columns=["messages", "meta"])
          for k in ("train", "valid") if (root / cfg["data"][k]).exists()}
    args = trl.SFTConfig(output_dir=str(out), seed=t["seed"], learning_rate=t["learning_rate"], lr_scheduler_type=t["lr_scheduler"],
                         warmup_ratio=t["warmup_ratio"], num_train_epochs=t["epochs"], max_length=t["max_len"],
                         per_device_train_batch_size=t["per_device_batch"], gradient_accumulation_steps=t["grad_accum"],
                         gradient_checkpointing=t["gradient_checkpointing"], optim=t["optim"], weight_decay=t["weight_decay"],
                         max_grad_norm=t["max_grad_norm"], bf16=t["bf16"], logging_steps=t["logging_steps"], save_steps=t["save_steps"],
                         eval_strategy="epoch" if "valid" in ds else "no", report_to=[])
    trainer = trl.SFTTrainer(model=model, args=args, train_dataset=ds["train"], eval_dataset=ds.get("valid"), processing_class=tok, peft_config=lora)
    trainer.train()
    trainer.save_model(str(out))
    (out / "recipe.json").write_text(json.dumps({"config": cfg, "train_sha256": hashlib.sha256((root / cfg["data"]["train"]).read_bytes()).hexdigest()},
                                                indent=1), encoding="utf-8")
    print(f"adapter saved to {out}; next: merge_and_gguf.py")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", type=Path, default=lab.CONFIG)
    ap.add_argument("--dry-run", action="store_true", help="validate config and dataset, print the plan, run nothing")
    ap.add_argument("--min-examples", type=int, default=None, help="override [data] min_examples (a dry run on a small sample)")
    ap.add_argument("--root", type=Path, default=lab.LAB, help="folder the config's relative paths resolve against")
    a = ap.parse_args(argv)
    try:
        cfg = load_config(a.config)
        if a.min_examples is not None:
            cfg["data"]["min_examples"] = a.min_examples
        mn = cfg["data"]["min_examples"]
        train_info = validate_dataset(a.root / cfg["data"]["train"], mn)
        vp = a.root / cfg["data"]["valid"]
        valid_info = validate_dataset(vp, 0) if vp.exists() else None
    except (ConfigError, ValueError, OSError) as e:
        print(f"train_qlora: {e}", file=sys.stderr)
        return 2
    for line in plan(cfg, train_info, valid_info):
        print(line)
    if a.dry_run:
        print("dry run: nothing was trained")
        return 0
    try:
        return train(cfg, a.root)
    except lab.MissingExtra as e:
        return lab.fail_missing(e)


if __name__ == "__main__":
    sys.exit(main())
