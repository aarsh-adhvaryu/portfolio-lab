"""Build the point-in-time index membership tables (charter E1b §3, §4).

    python tools/build_index_membership.py --download     # fetch the archive
    python tools/build_index_membership.py --parse        # PDFs -> changes
    python tools/build_index_membership.py --build        # changes -> tables
    python tools/build_index_membership.py --all

Each stage caches to `PFLAB_DATA_DIR/index_membership/`, so re-running is
cheap and only `--download` touches the network. The stages are separate
because parsing 1,486 PDFs takes about twenty minutes and is the part most
likely to need another pass when NSE's house style turns out to have changed
again.

What it writes
--------------
    raw/press_releases/*.pdf      the archive, as served
    raw/press_release_listing.txt what the listing page offered
    changes.parquet               every inclusion/exclusion, keyed and dated
    changes_report.json           readers used, releases missing, suspect ones
    name_map.parquet              company name -> symbol -> ISIN
    NIFTY*.parquet                the membership tables
    manifests.json                provenance, including the carry-back span
    docs/data/index_name_unresolved.md   names for the investor to verify by hand

The count check
---------------
Each of these indices holds a fixed number of names by construction, so a
correct reconstruction holds exactly that many on every date. The build
prints the drift per year; a non-zero drift means a change was missed or
misread, and is a reason to fix the parser rather than to proceed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from pflab.data import (data_dir, index_captures as cap,
                        index_changes as ic, index_membership as im,
                        name_map as nm, symbol_isin as si)

START = date(2005, 1, 1)
PARENTS = ("NIFTY500", "NIFTY100", "NIFTY_MIDCAP100", "NIFTY200")


def download(root: Path) -> None:
    listing = ic.press_release_index(root, refresh=True)
    print(f"listed {len(listing)} press releases")
    new = cached = failed = 0
    for i, r in enumerate(listing.itertuples(index=False), 1):
        p = root / "index_membership" / "raw" / "press_releases" / r.file
        if p.exists() and p.stat().st_size:
            cached += 1
            continue
        try:
            ic.fetch(r.file, root)
            new += 1
        except Exception as e:
            print(f"  FAIL {r.file}: {type(e).__name__}")
            failed += 1
        if i % 200 == 0:
            print(f"  {i}/{len(listing)}", flush=True)
    print(f"downloaded new={new} cached={cached} failed={failed}")


def parse(root: Path) -> None:
    listing = ic.press_release_index(root)
    rows, readers, errors, suspect = [], {}, [], []
    for i, r in enumerate(listing.itertuples(index=False), 1):
        res = ic.parse_release(r.file, root)
        if res["error"]:
            errors.append({"file": r.file, "date": str(r.date),
                           "error": res["error"]})
        else:
            readers[res["reader"]] = readers.get(res["reader"], 0) + 1
            if res["problems"]:
                suspect.append({"file": r.file, "date": str(r.date),
                                "problems": res["problems"][:4],
                                "yielded_changes": bool(res["changes"])})
            rows.extend(res["changes"])
        if i % 200 == 0:
            print(f"  {i}/{len(listing)} changes={len(rows)}", flush=True)

    df = pd.DataFrame(rows, columns=["index", "action", "company", "symbol",
                                     "effective", "announced", "source_file"])
    ic.write(df, root)
    report = {
        "releases_listed": int(len(listing)),
        "releases_read": int(len(listing) - len(errors)),
        "releases_unavailable": len(errors),
        "releases_suspect": len(suspect),
        "releases_suspect_with_changes": sum(1 for x in suspect
                                             if x["yielded_changes"]),
        "readers": readers,
        "changes": int(len(df)),
        "by_index": {k: int(v) for k, v in df.groupby("index").size().items()},
        "missing_symbol": int(df["symbol"].isna().sum()),
        "unavailable": errors,
        "suspect": suspect,
    }
    (root / "index_membership" / "changes_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("unavailable", "suspect")}, indent=2))


def collect_captures(root: Path) -> None:
    caps, report = cap.collect(root)
    cap.write(caps, root)
    (root / "index_membership" / "captures_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"captures listed={report['captures_listed']} "
          f"parsed={report['parsed']} failed={len(report['failed'])}")
    for k, v in sorted(report["by_index"].items()):
        print(f"  {k:16s} {v['captures']:3d} captures  {v['first']} .. {v['last']}")


def build(root: Path, asof: date) -> int:
    changes = ic.load(root)
    changes["effective"] = pd.to_datetime(changes["effective"],
                                          errors="coerce").dt.date
    changes = changes.dropna(subset=["effective"])

    names = nm.build(root=root)
    nm.write(names, root)
    smap = si.load(root)
    listing = im.listing_dates(root)
    print(f"{len(changes)} changes | name map {len(names)} | symbol map {len(smap)} "
          f"| listing dates {len(listing)}")

    try:
        captures = cap.load(root)
    except Exception:
        captures = {}
        print("WARNING: no captures on disk; run --captures first")
    print("captures: " + ", ".join(f"{k}={len(v)}"
                                   for k, v in sorted(captures.items())))

    month_ends = [d.date() for d in
                  pd.date_range("2006-01-31", asof, freq="ME")]
    recs = changes.to_dict("records")
    tables, manifests, unresolved = {}, {}, []

    def _summarise(t, index, man):
        man["count_check"] = {k: v for k, v in
                              im.count_check(t, index, month_ends).items()
                              if k not in ("counts", "off")}
        ex = cap.exact_list_check(t, index, captures)
        man["exact_list_check"] = {k: v for k, v in ex.items() if k != "per_date"}
        man["exact_list_check"]["per_date"] = {
            d: {kk: vv for kk, vv in v.items() if kk not in ("missing", "extra")}
            for d, v in ex["per_date"].items()}
        return ex

    for index in PARENTS:
        t, man, un = im.build_index(index, recs, START, asof, captures,
                                    smap, names, listing)
        tables[index], manifests[index] = t, man
        unresolved.extend(un)
        ex = _summarise(t, index, man)
        print(f"{index:16s} rows={len(t):5d} anchors={man['anchors']:2d} "
              f"| exact-list {ex['exact']:2d}/{ex['dates']:2d} worst={ex['worst']:4d} "
              f"| count exact={man['count_check']['exact']:3d}/248 "
              f"worst={man['count_check']['worst']}")

    n200, n200_man = im.build_nifty200(recs, symbol_isin=smap, name_map=names,
                                       start=START, asof=asof, listing=listing,
                                       captures=captures)
    ex = _summarise(n200, "NIFTY200", n200_man)
    print(f"NIFTY200 spliced rows={len(n200)} cutover={n200_man['cutover']} "
          f"| exact-list {ex['exact']}/{ex['dates']} worst={ex['worst']} "
          f"| count exact={n200_man['count_check']['exact']}/248 "
          f"worst={n200_man['count_check']['worst']}")

    n200_man["era_labels"] = im.era_labels(month_ends)
    n200_man["bounds"] = {k: v for k, v in
                          im.bounds_report(n200, "NIFTY200").items()
                          if k != "rows"}
    n200_man["bounds"]["per_name"] = im.bounds_report(n200, "NIFTY200")["rows"]
    el = n200_man["era_labels"]
    print(f"eras: {el['proxy']} proxy month-ends before {el['cutover']}, "
          f"{el['published']} published from it")
    b = n200_man["bounds"]
    print(f"guessed starts: {b['guessed']} of {b['names']} names "
          f"({b['with_an_interval']} with a non-zero interval), "
          f"median {b['median_days']}d, widest {b['max_days']}d")
    for src, v in sorted(b["by_source"].items()):
        print(f"    {src:15s} {v['rows']:4d} rows  median {v['median_days']:5d}d  "
              f"max {v['max_days']:5d}d")

    ui = cap.union_identity_check(captures)
    manifests["union_identity_check"] = ui
    print("Nifty 100 / Midcap 100 overlap on dates both were captured: "
          + ", ".join(f"{r['date']}={r['overlap']}" for r in ui["detail"]))
    if ui["last_seen_overlapping"]:
        print(f"  they still overlapped on {ui['last_seen_overlapping']} and "
              f"were disjoint by {ui['first_seen_disjoint']}, so the union is "
              f"NOT Nifty 200 before the 2016 restructure")

    xc = cap.cross_check_nifty100(captures)
    manifests["nifty100_cross_check"] = xc
    print(f"Nifty 100 == Nifty 50 + Next 50: "
          f"{xc['exact']}/{xc['comparisons']} exact")

    for index, t in tables.items():
        if index != "NIFTY200":
            im.write(t, manifests[index], root)
    im.write(n200, n200_man, root)
    manifests["NIFTY200_spliced"] = n200_man
    (root / "index_membership" / "manifests.json").write_text(
        json.dumps(manifests, indent=2, default=str), encoding="utf-8")
    _write_unresolved_doc(pd.DataFrame(unresolved), root)
    # The gate is the exact-list check, not the count: counting catches a
    # missing change, comparing sets catches a wrong one too.
    return ex["worst"] or 0


def _write_unresolved_doc(u: pd.DataFrame, root: Path) -> None:
    lines = [
        "# Constituent-change names that could not be keyed to a security",
        "",
        "Charter E1b §3 as amended 2026-09-17. These are company names printed",
        "in an NSE Indices press release that the name map could not resolve to",
        "a single security at that date. **Nothing here is guessed.** A wrong",
        "match is silent and puts the wrong company in the universe; an",
        "unresolved name is merely absent from that one change.",
        "",
        "Verify these the way `symbol_isin.VERIFIED_STITCHES` is verified: by",
        "hand, one at a time, and only where the evidence is unambiguous. Add",
        "confirmed pairs to the name map rather than loosening `normalise`.",
        "",
    ]
    if len(u):
        u = u.copy()
        u["year"] = u["effective"].astype(str).str[:4]
        lines += ["## By year", "", "| year | unresolved |", "|---|---|"]
        lines += [f"| {y} | {n} |" for y, n in u.groupby("year").size().items()]
        lines += ["", "## By reason", "", "| reason | count |", "|---|---|"]
        lines += [f"| {r} | {n} |" for r, n in
                  u.groupby("reason").size().sort_values(ascending=False).items()]
        lines += ["", "## The names", "",
                  "| effective | index | company | symbol | reason | source |",
                  "|---|---|---|---|---|---|"]
        for r in u.sort_values(["effective", "company"]).itertuples(index=False):
            lines.append(f"| {r.effective} | {r.index} | {r.company} | "
                         f"{r.symbol or '—'} | {r.reason} | {r.source_file} |")
    else:
        lines.append("None: every name in every change resolved to a single "
                     "security.")
    doc = Path("docs/data/index_name_unresolved.md")
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {doc} ({len(u)} names)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--captures", action="store_true",
                    help="fetch and parse Internet Archive captures")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--asof", default=str(date.today()))
    a = ap.parse_args(argv)
    if not (a.download or a.parse or a.captures or a.build or a.all):
        ap.error("pick a stage: --download, --parse, --captures, --build "
                 "or --all")

    root = data_dir()
    asof = date.fromisoformat(a.asof)
    if a.download or a.all:
        download(root)
    if a.parse or a.all:
        parse(root)
    if a.captures or a.all:
        collect_captures(root)
    if a.build or a.all:
        worst = build(root, asof)
        if worst:
            print(f"\nexact-list check FAILED: worst disagreement {worst} "
                  f"names against a captured list. A change was missed or "
                  f"misread; fix the sources, never the check.")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
