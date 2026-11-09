"""S81: minute bars for the core ETFs (index, gold, international) from Kite, read only, into `PFLAB_DATA_DIR\\bars_1m` (the same layout as every other name).

    .venv\\Scripts\\python tools\\backfill_etf_bars_s81.py [--since 2024-01-01] [--symbols A,B,...] [--until HH:MM] [--status]

It runs ONE extra tier ("etf") through the same `ingest/kite_backfill.run` as `tools/backfill_bars_1m.py`. Symbols that Kite does not list are skipped and counted; a symbol that is
already covered is only topped up. Never writes a token or a holding; the log carries counts and the symbols of PUBLIC ETFs only.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from pflab.ingest import kite_backfill as kb

# Candidate India-listed core ETFs (public instruments): Nifty 50 / Next 50 / Nifty 500 index, gold and silver, international (Nasdaq 100, S&P 500, FANG, Hang Seng).
CANDIDATES = ["NIFTYBEES", "JUNIORBEES", "BANKBEES", "SETFNIF50", "NIFTYIETF", "MONIFTY500", "NIF100BEES", "GOLDBEES", "GOLDIETF", "AXISGOLD", "SILVERBEES",
              "MON100", "MAFANG", "MASPTOP50", "HNGSNGBEES", "MOM100", "N100", "LIQUIDBEES"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(CANDIDATES))
    ap.add_argument("--since", default="2023-01-01")
    ap.add_argument("--until")
    ap.add_argument("--root")
    ap.add_argument("--log", default=r"D:\s81_scratch\kite\etf_backfill.log")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else kb.default_root()
    if a.status:
        have = sorted(p.stem for p in (root / "IN").glob("*.parquet"))
        print({"etfs_present": [s for s in a.symbols.split(",") if s in have], "root": str(root)})
        return 0
    log_path = Path(a.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log_path, "a", encoding="utf-8", buffering=1)

    def log(s: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {s}" if not s[:2].isdigit() else s
        fh.write(line + "\n")
        print(line, flush=True)

    from pflab.ingest import kite as km
    from pflab.pm import secrets
    kc = km.client(secrets.load())
    if kc is None:
        log("kite logged out: no valid token (open the Portfolio Lab app and press Log in to Kite, or run tools\\kite_login.py)")
        return 2
    eq, _ix = kb.instrument_tokens(kc)
    want = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    items = [(s, eq[s]) for s in want if s in eq]
    log(f"etf tier: {len(items)} of {len(want)} symbols are listed: {', '.join(s for s, _ in items)}; missing: {', '.join(s for s in want if s not in eq) or 'none'}")
    deadline = None
    if a.until:
        h, m = (int(x) for x in a.until.split(":"))
        deadline = datetime.combine(date.today(), time(h, m))
        if deadline <= datetime.now():
            deadline += timedelta(days=1)
    cfg = kb.RunConfig(root=root, market="IN", workers=3, tiers=("etf",), since_by_tier={"etf": date.fromisoformat(a.since)})
    res = kb.run(kc, cfg, deadline=deadline, stop_file=log_path.parent / "STOP", log=log, tiers_plan=[dict(tier="etf", since=date.fromisoformat(a.since), items=items)])
    log(f"etf backfill end: {res}")
    return 0 if not res.get("stopped") or res["stopped"] in ("StopRun",) else 1


if __name__ == "__main__":
    sys.exit(main())
