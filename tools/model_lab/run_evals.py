"""Run the app's own evaluation sets on an Ollama tag and write the results JSON in the app's shape (A41, S79). Development only.

    python tools/model_lab/run_evals.py --tag qwen3:8b-q8_0 --limit 3          # a smoke pass: 3 items per task, not evidence
    python tools/model_lab/run_evals.py --tag pflab-qwen3-8b-lab --round 3     # a full registered run

It calls `pflab.llm.eval12.evaluate`, the same harness `pflab llm eval12` uses (routing, guarded answers, extraction, materiality, the
same sets, seeds, prompts and thresholds), so a tuned tag and the base tag are scored identically. The result file has the app's keys:
{"model", "scores", "passes", "detail", "run_at"} plus a "harness" block (round, tasks, limit, smoke).
Rule 10: a full run needs a pick registered in configs/llm_models.toml BEFORE the run (llm.registry.require_registered); a --limit run is a
smoke test of the plumbing and is exempt, is flagged smoke, and is never to be read as a score. Needs Ollama running; no torch.
The sets live under PFLAB_DATA_DIR/llm_eval (the workshop's data folder; the app's folder is never touched).
Exit codes: 0 ok, 2 bad arguments or not registered, 4 Ollama unreachable or the tag not installed.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_common as lab  # noqa: E402

ALL_TASKS = ("routing", "answers", "extraction", "materiality")
ROLES = {1: "eval12", 2: "eval12-r2", 3: "eval12-r3"}


def data_root() -> Path:
    """PFLAB_DATA_DIR, else the checkout's data folder (the relative default of pflab would depend on the working directory)."""
    env = os.environ.get("PFLAB_DATA_DIR")
    return Path(env).expanduser() if env else lab.ROOT / "data"


@contextlib.contextmanager
def limited(n: Optional[int]) -> Iterator[None]:
    """Cut every task of the harness to its first `n` items, through the harness's own functions (so the code path is the real one)."""
    from pflab.llm import eval12
    if not n:
        yield
        return
    orig = (eval12.routing_set, eval12.run_answers, eval12.run_extraction, eval12.run_materiality)
    eval12.routing_set = lambda path=eval12.ROUTING: orig[0](path)[:n]
    eval12.run_answers = lambda model, chat, n_=50, **k: orig[1](model, chat, n=n, **{x: v for x, v in k.items() if x != "n"})
    eval12.run_extraction = lambda model, chat, items: orig[2](model, chat, items[:n])
    eval12.run_materiality = lambda model, chat, items: orig[3](model, chat, items[:n])
    try:
        yield
    finally:
        eval12.routing_set, eval12.run_answers, eval12.run_extraction, eval12.run_materiality = orig


def check_registered(tag: str, round_: int, role: Optional[str], smoke: bool) -> Optional[dict]:
    """Rule 10: a full run needs an earlier registration. A smoke run is exempt."""
    from pflab.llm import registry
    if smoke:
        return None
    return registry.require_registered(role or ROLES[round_], tag, datetime.now())


def run(tag: str, round_: int = 1, tasks=ALL_TASKS, limit: Optional[int] = None, chat: Optional[Callable] = None,
        root: Optional[Path] = None) -> dict:
    """Evaluate `tag` and return the result dict in the app's shape."""
    from pflab.llm import client, eval12
    root = root or data_root()
    with limited(limit):
        rep = eval12.evaluate(tag, chat or client.chat, root, list(tasks), round_=round_)
    return {"model": tag, "scores": rep.scores, "passes": rep.passes(), "detail": rep.detail, "run_at": datetime.now().isoformat(),
            "harness": {"round": round_, "tasks": list(tasks), "limit": limit, "smoke": bool(limit), "source": "tools/model_lab/run_evals.py"}}


def out_path(out_dir: Path, tag: str, limit: Optional[int]) -> Path:
    return out_dir / (tag.replace(":", "_").replace("/", "_") + (".smoke" if limit else "") + ".json")


def baseline_scores(root: Path, round_: int, tag: str) -> Optional[Dict[str, float]]:
    """The app's stored result for the base tag in the same round, for a side-by-side line (None if absent or the same tag)."""
    from pflab.llm import eval12
    base = "qwen3:8b-q8_0"
    p = root / "llm_eval" / eval12.ROUNDS[round_]["results"] / (base.replace(":", "_") + ".json")
    if tag == base or not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8")).get("scores")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True, help="Ollama tag, e.g. qwen3:8b-q8_0 or a tag made with `ollama create`")
    ap.add_argument("--round", type=int, choices=sorted(ROLES), default=1)
    ap.add_argument("--tasks", nargs="+", choices=ALL_TASKS, default=list(ALL_TASKS))
    ap.add_argument("--limit", type=int, default=None, help="first N items of every task: a smoke test, not a score")
    ap.add_argument("--role", default=None, help="registered role (default eval12 / eval12-r2 / eval12-r3 by round)")
    ap.add_argument("--out", type=Path, default=lab.OUTPUTS / "evals")
    a = ap.parse_args(argv)
    if a.limit is not None and a.limit < 1:
        print("run_evals: --limit must be at least 1", file=sys.stderr)
        return 2
    from pflab.llm import client, registry
    try:
        check_registered(a.tag, a.round, a.role, bool(a.limit))
    except registry.NotRegistered as e:
        print(f"run_evals: {e}", file=sys.stderr)
        return 2
    try:
        have = client.installed()
        if client.resolve(a.tag, have) is None:
            print(f"run_evals: {a.tag} is not installed in Ollama; installed: {sorted(have)}", file=sys.stderr)
            return 4
    except client.OllamaError as e:
        print(f"run_evals: {e}", file=sys.stderr)
        return 4
    res = run(a.tag, a.round, a.tasks, a.limit)
    a.out.mkdir(parents=True, exist_ok=True)
    p = out_path(a.out, a.tag, a.limit)
    p.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(a.tag, {k: round(v, 3) for k, v in res["scores"].items()})
    if a.limit:
        print(f"smoke run on {a.limit} item(s) per task: it proves the plumbing, it is NOT a score")
    else:
        print("passes", res["passes"])
        base = baseline_scores(data_root(), a.round, a.tag)
        if base:
            print("base qwen3:8b-q8_0 (stored)", {k: round(v, 3) for k, v in base.items()})
    print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
