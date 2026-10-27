"""Daily collector job (Phase 1 task 1.7).

Idempotent: re-running for the same days re-uses whatever is already on disk
and makes no network call for it. Schedule once a day after 19:00 IST.

    python tools/collect_daily.py                 # last 3 days
    python tools/collect_daily.py --days 7
    python tools/collect_daily.py --sources bhavcopy,corporate_actions
    python tools/collect_daily.py --status        # what the last runs did

Sources are isolated: bhavcopy is on E1's critical path, while BSE and GDELT
are E2 and their endpoints are still unverified (tasks 1.5/1.6). A failure in
one never stops the others, and the exit code reflects only the critical ones,
so a Task Scheduler alert means something real.

Exit codes: 0 all critical sources fine; 1 a critical source failed;
2 another run holds the lock.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date, datetime, timedelta

from pflab._lock import FileLock, LockBusy
from pflab.data import data_dir

# name -> (callable(start, end, root), critical)
CRITICAL = {"bhavcopy", "corporate_actions"}


def _bhavcopy(start, end, root):
    from pflab.data import bhavcopy
    # Every day, not just weekdays: NSE trades some Saturdays and Sundays
    # (Budget days, Diwali Muhurat).
    return bhavcopy.collect(start, end, root)


def _corporate_actions(start, end, root):
    """Refresh the current year so new splits and bonuses reach the factors.

    Without this the panel silently misadjusts the moment a held name splits --
    the exact failure the section 15 change of 2026-09-16 was made to prevent.
    """
    from pflab.data import nse_corporate_actions as nca
    nca.collect(start.year, end.year, root, refresh=True)
    # Merged, never overwritten: the stored table also holds the PREVCLOSE
    # factors, which `factors()` does not produce (2026-09-28).
    f = nca.merge_purpose(nca.factors(root), root)
    nca.write(f, root)
    return {"factors": len(f), "years": sorted({start.year, end.year})}


def _bse_bhavcopy(start, end, root):
    # closes for BSE-only listings (e.g. NSE's own shares); not critical
    from pflab.data import bse_bhavcopy
    return bse_bhavcopy.collect(start, end, root)


def _gkg(start, end, root):
    # GDELT GKG rows naming list/held companies, for the knowledge graph (~1 GB downloaded a day); not critical
    from datetime import date as _date, timedelta as _td
    from pflab.data import gdelt_gkg
    from pflab.kg import build as kb
    from pflab.plan import guards as gd
    import json as _json
    import os as _os
    from pathlib import Path as _Path
    given = _os.environ.get("PFLAB_GKG_ALIASES")
    if given:                                          # S58: the job holds the ledger and hands the names over
        al = _json.loads(_Path(given).read_text(encoding="utf-8"))
    else:
        from pflab.pm import store
        con = store.connect(read_only=True)
        al = kb.aliases(kb.universe(con, gd.stock_list()))
        con.close()
    out = {}
    # S58 re-run: a day missed by a failed run fell outside the next run's window; every run now looks back 14 days
    # (a day on disk is skipped at once, a missing one downloaded)
    d = _date.today() - _td(days=14)
    while d < min(end, _date.today()):                 # whole days only (today is still being published)
        out[str(d)] = gdelt_gkg.collect_day(d, al, root)
        d += _td(days=1)
    return out


def _indices(start, end, root):
    # benchmark and momentum index series (incremental); not critical
    from pflab.data import indices
    return indices.update_daily(root=root)


def _vix(start, end, root):
    # India VIX (NSE): incremental top-up; was never wired in, so the series stopped at 2026-09-21; not critical
    from pflab.data import india_vix
    return india_vix.update(root=root)


def _surveillance(start, end, root):
    # NSE ASM/GSM/ESM lists: current-only, so a daily snapshot builds the history; not critical
    from pflab.data import nse_surveillance
    return nse_surveillance.collect(start, end, root)


def _dividends(start, end, root):
    from pflab.data import dividends as dv
    d = dv.from_feed(root)
    dv.write(d, root)
    return {"rows": len(d)}


def _bse(start, end, root):
    from pflab.data import bse_announcements
    return bse_announcements.collect(start, end, root)


def _my_isins(root):
    """Held and listed ISINs: the job's hand-over file (it holds the ledger), else the ledger read-only."""
    import json as _json
    import os as _os
    from pathlib import Path as _Path
    given = _os.environ.get("PFLAB_GKG_ALIASES")
    if given:
        return sorted(_json.loads(_Path(given).read_text(encoding="utf-8")))
    from pflab.kg import build as kb
    from pflab.plan import guards as gd
    from pflab.pm import store
    con = store.connect(read_only=True)
    try:
        return sorted(kb.aliases(kb.universe(con, gd.stock_list())))
    finally:
        con.close()


def _insider(start, end, root):
    # S63: NSE insider (PIT) disclosures, the running month refetched; BSE's side comes with the announcements; not critical
    from pflab.data import nse_insider
    return nse_insider.collect(date(start.year, start.month, 1), end, root)


def _deals(start, end, root):
    # S63: NSE bulk and block deals, day by day (the running month refetched); not critical
    from pflab.data import nse_deals
    return nse_deals.collect(start, end, root=root, log=lambda s: None)


def _fpi(start, end, root):
    # S63: FII / FPI daily net investment (NSDL), the last two months merged into the history; not critical
    from pflab.data import fpi_flows
    m0 = date(end.year - (end.month == 1), (end.month - 2) % 12 + 1, 1)
    r = fpi_flows.collect(m0, end, root, merge=True)
    return {k: r[k] for k in ("rows", "last", "failed")}


def _macro(start, end, root):
    # S63: Brent, USDINR, US 10-year (FRED, no key): small series, fetched whole; not critical
    from pflab.data import macro
    return {k: v["last"] for k, v in macro.collect(root).items()}


def _holders(start, end, root):
    # S63: shareholding pattern (promoters, pledges) and institutional holding of held and listed names, the two
    # newest quarters (a quarter on disk is skipped); not critical
    import duckdb as _duck
    from pflab.data import bse_institutions as bi, bse_shareholding as bs
    isins = _my_isins(root)
    mp = _duck.sql(f"select scrip_code, isin from '{root / 'bse_scrip_isin' / 'map.parquet'}'").df()
    scrips = sorted(set(mp[mp["isin"].isin(set(isins))]["scrip_code"].astype(str)))
    q = bs.latest_qtrid(end)
    a = bs.collect(scrips, q - 1, q, root=root)
    b = bi.collect(scrips, [q - 1, q], root=root, log=lambda s: None)
    return {"scrips": len(scrips), "quarters": [q - 1, q], "shareholding": str(a)[:120], "institutions": str(b)[:120]}


def _fo(start, end, root):
    # S64: F&O daily (futures and options rows, participant-wise open interest) and its derived tables: Nifty ATM IV, PCR,
    # futures premium, max pain, stock build-up classes; not critical. A session not yet published is tried again next run.
    from pflab.data import fo_daily
    from pflab.quant import options
    got = fo_daily.collect(max(start, end - timedelta(days=10)), end, root)
    got["derived"] = options.derive_missing(root)
    got["missing"] = got["missing"][-3:]
    return got


def _gdelt(start, end, root):
    from pflab.data import gdelt
    # GDELT publishes in arrears, so ask for yesterday and back.
    return gdelt.collect(start - timedelta(days=1), end - timedelta(days=1), root)


SOURCES = {
    "bhavcopy": _bhavcopy,
    "corporate_actions": _corporate_actions,
    "bse_bhavcopy": _bse_bhavcopy,
    "surveillance": _surveillance,
    "indices": _indices,
    "vix": _vix,
    "gkg": _gkg,
    "dividends": _dividends,
    "bse": _bse,
    "gdelt": _gdelt,
    "insider": _insider,
    "deals": _deals,
    "fpi": _fpi,
    "macro": _macro,
    "holders": _holders,
    "fo": _fo,
}


def _log(root, rec: dict) -> None:
    p = root / "_daily" / "collect_log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def status(root, limit: int = 20) -> None:
    p = root / "_daily" / "collect_log.jsonl"
    if not p.exists():
        print("no daily runs recorded yet")
        return
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows[-limit:]:
        mark = "ok " if r.get("ok") else "FAIL"
        print(f"  {r['ts'][:19]}  {mark} {r['source']:18s} {r.get('result') or r.get('error','')}")
    bad = [r for r in rows if not r.get("ok")]
    print(f"\n{len(rows)} entries, {len(bad)} failures")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--sources", default=",".join(SOURCES))
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)

    root = data_dir()
    if a.status:
        status(root)
        return 0

    names = [s.strip() for s in a.sources.split(",") if s.strip()]
    unknown = set(names) - set(SOURCES)
    if unknown:
        print(f"unknown source(s): {sorted(unknown)}; known: {sorted(SOURCES)}")
        return 1

    end = date.today()
    start = end - timedelta(days=a.days)
    print(f"data dir: {root.resolve()}")
    print(f"window:   {start} .. {end}")

    failed_critical = []
    try:
        with FileLock(root / "_daily" / "collect.lock", "daily collector"):
            for name in names:
                t0 = datetime.now()
                try:
                    res = SOURCES[name](start, end, root)
                    ok, err = True, None
                    print(f"  {name:18s} ok   {res}", flush=True)
                except Exception as e:
                    ok, err, res = False, f"{type(e).__name__}: {e}", None
                    print(f"  {name:18s} FAIL {err}", flush=True)
                    if name in CRITICAL:
                        failed_critical.append(name)
                        traceback.print_exc()
                _log(root, {"ts": t0.isoformat(), "source": name, "ok": ok,
                            "window": [start, end], "result": res, "error": err,
                            "seconds": round((datetime.now() - t0).total_seconds(), 1)})
    except LockBusy as e:
        print(f"skipped: {e}")
        return 2

    if failed_critical:
        print(f"\nCRITICAL source(s) failed: {failed_critical}")
        return 1
    print("\nall requested sources completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
