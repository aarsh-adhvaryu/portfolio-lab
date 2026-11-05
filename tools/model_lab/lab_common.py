"""Shared helpers of the model lab (A41, S79). Development only; the app never imports this folder.

Everything here runs WITHOUT the `[ml]` extra: torch, transformers, peft, trl and bitsandbytes are imported lazily by the scripts
that need them, through `require`, which fails with one clear message when the extra is missing.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Dict, Iterable, List

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:                      # run from a checkout, no install needed
    sys.path.insert(0, str(SRC))

CONFIG = LAB / "config" / "qlora_qwen3_8b.toml"
STEER_CONFIG = LAB / "config" / "steer_cites.toml"
OUTPUTS = LAB / "outputs"                        # gitignored: weights, adapters, GGUFs, eval JSON
DATASETS = LAB / "datasets"                      # gitignored: JSONL built from the system's own journal

EXIT_MISSING_EXTRA = 3

INSTALL_HINT = (
    "The model lab's ML extra is not installed ({missing}). It is for development only and is not part of the app.\n"
    "  1. python -m venv .venv-train  (a separate venv; never the app's)\n"
    "  2. .venv-train\\Scripts\\pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu128\n"
    "  3. .venv-train\\Scripts\\pip install -e \".[ml]\"\n"
    "A --dry-run needs none of this."
)


class MissingExtra(RuntimeError):
    """The `[ml]` optional extra (torch and friends) is not installed."""


def have(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def missing(modules: Iterable[str]) -> List[str]:
    return [m for m in modules if not have(m)]


def require(*modules: str) -> Dict[str, object]:
    """Import and return the named modules, or raise MissingExtra with the install steps (never a bare ImportError)."""
    gone = missing(modules)
    if gone:
        raise MissingExtra(INSTALL_HINT.format(missing=", ".join(gone)))
    return {m: importlib.import_module(m) for m in modules}


def fail_missing(e: MissingExtra) -> int:
    print(f"model_lab: {e}", file=sys.stderr)
    return EXIT_MISSING_EXTRA


def load_toml(path: Path) -> dict:
    from pflab import _toml
    return _toml.load(path)


def read_jsonl(path: Path) -> List[dict]:
    import json
    out = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError as e:
                raise ValueError(f"{path}:{i}: not JSON ({e})") from e
    return out
