"""Command line of the S84 replays (see tools/replays_s84.py for what each one is).

    python tools/replays_s84_cli.py data
    python tools/replays_s84_cli.py replay [nvda_held|nvda_not_held|ather] [--no-morning]
    python tools/replays_s84_cli.py drills [name]
    python tools/replays_s84_cli.py real            # the ONE real path: a real Sonnet read and a real Opus decision (needs PFLAB secrets file and a paid-call go: it sets PFLAB_PAID itself)
    python tools/replays_s84_cli.py all
Reports go to S84_REPLAY_OUT (default D:\\s84_scratch\\replay\\out) as <name>.json and <name>.txt.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import replays_s84 as R  # noqa: E402


def _save(res: dict, name: str) -> Path:
    R.OUT.mkdir(parents=True, exist_ok=True)
    p = R.OUT / f"{name}.json"
    p.write_text(json.dumps({k: v for k, v in res.items() if k != "timeline"}, indent=1, default=str), encoding="utf-8")
    (R.OUT / f"{name}.txt").write_text(res.get("account", ""), encoding="utf-8")
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["data", "replay", "drills", "real", "all"])
    ap.add_argument("which", nargs="?", default="")
    ap.add_argument("--no-morning", action="store_true", help="the loop as the wire ships it (no extra morning watch)")
    a = ap.parse_args(argv)
    if a.cmd == "data":
        print(json.dumps(R.build_real_data(), indent=1, default=str))
        return 0
    if a.cmd in ("replay", "all"):
        for w in ([a.which] if a.which else ["nvda_held", "nvda_not_held", "ather"]):
            res = R.replay_ather() if w == "ather" else R.replay_nvda(w == "nvda_held", morning=not a.no_morning)
            print(w, "->", _save(res, w))
    if a.cmd == "real":
        res = R.replay_nvda(True, real=True, morning=False)
        print("real ->", _save(res, "real_nvda_held"))
    if a.cmd in ("drills", "all"):
        import replays_s84_drills as DR
        print(json.dumps(DR.run_all(a.which or None, R.OUT), indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
