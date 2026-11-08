"""Merge a LoRA adapter into the bf16 base, convert to GGUF with llama.cpp, quantise (A41, S79). Development only.

    python tools/model_lab/merge_and_gguf.py --dry-run --llama-cpp D:\\tools\\llama.cpp      # prints the exact commands, runs nothing
    python tools/model_lab/merge_and_gguf.py --llama-cpp D:\\tools\\llama.cpp                # merge (needs [ml]), convert, quantise

llama.cpp: download a release build of the same era (it provides llama-quantize.exe) and take convert_hf_to_gguf.py from the same
tag's source; the converter needs the `gguf` and `sentencepiece` packages (in the [ml] extra). The merge happens on the CPU in bf16
(about 16 GB of RAM) so it never competes with Ollama for the 12 GB card; QLoRA adapters are merged into the UNquantised base, not
into the 4-bit one. Exit codes: 0 ok, 2 bad arguments, 3 the [ml] extra is missing.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_common as lab  # noqa: E402

QUANTS = ("Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "F16")


def commands(merged: Path, out_dir: Path, llama_cpp: Path, quant: str = "Q8_0", name: str = "model") -> List[List[str]]:
    """The exact commands after the merge: convert to an F16 GGUF, then quantise (skipped for F16)."""
    f16 = out_dir / f"{name}-f16.gguf"
    cmds = [[sys.executable, str(llama_cpp / "convert_hf_to_gguf.py"), str(merged), "--outfile", str(f16), "--outtype", "f16"]]
    if quant.upper() != "F16":
        cmds.append([str(llama_cpp / "llama-quantize"), str(f16), str(out_dir / f"{name}-{quant.lower()}.gguf"), quant])
    return cmds


def merge(base: str, adapter: Path, merged: Path) -> None:  # pragma: no cover  (needs [ml]; not run in S79)
    mods = lab.require("torch", "transformers", "peft")
    torch, tf, peft = mods["torch"], mods["transformers"], mods["peft"]
    model = tf.AutoModelForCausalLM.from_pretrained(base, torch_dtype=torch.bfloat16, device_map={"": "cpu"})
    model = peft.PeftModel.from_pretrained(model, str(adapter)).merge_and_unload()
    merged.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(merged), safe_serialization=True)
    tf.AutoTokenizer.from_pretrained(base).save_pretrained(str(merged))


def main(argv: Optional[List[str]] = None) -> int:
    cfg = lab.load_toml(lab.CONFIG)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--adapter", type=Path, default=lab.LAB / cfg["output"]["dir"])
    ap.add_argument("--base", default=cfg["model"]["base"])
    ap.add_argument("--llama-cpp", type=Path, default=Path("llama.cpp"), help="folder with convert_hf_to_gguf.py and llama-quantize")
    ap.add_argument("--quant", default=cfg["output"]["gguf_quant"], choices=QUANTS)
    ap.add_argument("--name", default="pflab-qwen3-8b-lab")
    ap.add_argument("--out", type=Path, default=None, help="default: <adapter>/gguf")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    out = a.out or a.adapter / "gguf"
    merged = a.adapter / "merged"
    cmds = commands(merged, out, a.llama_cpp, a.quant, a.name)
    print(f"1. merge   {a.adapter} (LoRA) into {a.base} (bf16, CPU) -> {merged}")
    for i, c in enumerate(cmds, 2):
        print(f"{i}. run     {' '.join(shlex.quote(x) for x in c)}")
    print(f"then       python tools/model_lab/make_modelfile.py --gguf {out / (a.name + '-' + a.quant.lower() + '.gguf')} --tag {a.name}")
    if a.dry_run:
        print("dry run: nothing was merged or converted")
        return 0
    if not (a.adapter / "adapter_config.json").exists():
        print(f"merge_and_gguf: no adapter at {a.adapter} (adapter_config.json missing); run train_qlora.py first", file=sys.stderr)
        return 2
    for tool in (a.llama_cpp / "convert_hf_to_gguf.py",):
        if not tool.exists():
            print(f"merge_and_gguf: {tool} not found; pass --llama-cpp", file=sys.stderr)
            return 2
    try:
        merge(a.base, a.adapter, merged)
    except lab.MissingExtra as e:
        return lab.fail_missing(e)
    out.mkdir(parents=True, exist_ok=True)
    for c in cmds:
        r = subprocess.run(c)
        if r.returncode:
            print(f"merge_and_gguf: command failed ({r.returncode}): {c[0]}", file=sys.stderr)
            return r.returncode
    (out / f"{a.name}.recipe.json").write_text(json.dumps({"base": a.base, "adapter": str(a.adapter.name), "quant": a.quant}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
