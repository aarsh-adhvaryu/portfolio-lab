"""pflab command line."""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta


def _d(s: str) -> date:
    return date.fromisoformat(s)


def main(argv=None):
    p = argparse.ArgumentParser(prog="pflab")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="run a data collector")
    c.add_argument("source", choices=["bhavcopy", "bse", "gdelt"])
    c.add_argument("--from", dest="start", type=_d, default=date.today() - timedelta(days=3))
    c.add_argument("--to", dest="end", type=_d, default=date.today())

    b = sub.add_parser("backtest", help="run one config (Phase 2)")
    b.add_argument("config")
    b.add_argument("--period", default=None, help="overrides [evaluation].period")
    b.add_argument("--unseal", default=None, help="written reason; required for the sealed period")

    s = sub.add_parser("sweep", help="run the pre-registered sweep (Phase 2)")
    s.add_argument("config")
    s.add_argument("--period", default=None)
    s.add_argument("--unseal", default=None)

    k = sub.add_parser("classify", help="verdict from two sweeps (Phase 2)")
    k.add_argument("development")
    k.add_argument("validation")

    a = p.parse_args(argv)
    if a.cmd == "collect":
        if a.source == "bhavcopy":
            from pflab.data import bhavcopy as m
        elif a.source == "bse":
            from pflab.data import bse_announcements as m
        else:
            from pflab.data import gdelt as m
        print(m.collect(a.start, a.end))
        return 0
    if a.cmd in ("backtest", "sweep"):
        from pflab.backtest import runner
        print(runner.main(a.config, getattr(a, "period", None), a.unseal,
                          sweep=(a.cmd == "sweep")))
    if a.cmd == "classify":
        from pflab.eval import classify
        import json
        print(json.dumps(classify.classify(a.development, a.validation),
                         indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
