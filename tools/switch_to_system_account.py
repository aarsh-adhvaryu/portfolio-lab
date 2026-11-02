"""Switch the installed app to the system's own account (S77, A36). Run with the dashboard CLOSED (only one process may hold the store).

    .venv\\Scripts\\python tools\\switch_to_system_account.py --pm D:\\PortfolioLabApp\\pm --app-root D:\\PortfolioLabApp --repo D:\\PortfolioLabApp\\app            (dry run: counts only)
    ... --apply                                                                                                                                  (does it)

It prints counts and kinds, never the values of his record. A safety copy of the store is made first and removed only after the new account verifies.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pm", required=True)
    ap.add_argument("--app-root", default=None)
    ap.add_argument("--repo", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--start-cash", type=float, default=500_000.0)
    a = ap.parse_args(argv)
    os.environ["PFLAB_PM_DIR"] = str(a.pm)
    from pflab.ledger import system
    from pflab.pm import store
    con = store.connect()
    repo = Path(a.repo) if a.repo else None
    template = (repo / "configs" / "targets.toml") if repo else None
    out = system.run_switch(con, Path(a.pm), Path(a.app_root) if a.app_root else None, repo, datetime.now(), apply=a.apply, start_cash=a.start_cash, template_targets=template)
    print(json.dumps(out, indent=1, default=str))
    return 0 if (not a.apply or out.get("verify", {}).get("ok")) else 1


if __name__ == "__main__":
    sys.exit(main())
