"""Build an E5-A family's feature store for one period (E5-A §6(b)-(d)).

    python tools\\build_e5a_family.py --family A1 --config configs\\e5a_a1.toml --period e5a_development
    python tools\\build_e5a_family.py --family A3 --config configs\\e5a_a3.toml --period validation

Built over A0's store for the same period (U(M) and month-ends read from its
verified files), so a family never adds a name and never reaches past the
period's end. A1 needs L's readings (`tools/a1_read_events.py`) for every
event of L's flags up to the period's end, and refuses without them. A2 and
A3 (and A5) read the truncated panel (A2: its corporate actions, for the split/bonus
restatement) through `runner.prepare`, as the A0 build does.
Writes PFLAB_DATA_DIR/e5a/<period>/features_<fam>.parquet and meta_<fam>.json.
A data build, not a sweep.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from pflab.backtest import runner  # noqa: E402
from pflab.eval import artifacts, periods  # noqa: E402
from pflab.ranker import events as ev_mod, exposure as ex_mod, family, store  # noqa: E402
from pflab.ranker import holdings as ho_mod  # noqa: E402
from pflab.ranker import features as ft  # noqa: E402


def _say(msg):
    print(msg, file=sys.stderr, flush=True)


def _sha_df(df: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=False).values.tobytes()).hexdigest()


def _period(cfg, name):
    ev = cfg.get("evaluation", {})
    return periods.load_periods(ROOT / ev.get("periods_path", "configs/evaluation_periods.toml"))[name]


def build(fam: str, config_path: str, period_name: str) -> dict:
    t0 = time.time()
    cfg = runner.load_config(config_path)
    if family.family_of(cfg) != fam:
        raise SystemExit(f"{config_path} is family {family.family_of(cfg)}, not {fam}")
    period = _period(cfg, period_name)
    if period.sealed:
        raise SystemExit("refusing: the sealed period is never built")
    d = store.store_dir(period.name)
    a0, _labels, a0_meta = store.load(d)
    universe = {m: list(g["isin"].unique()) for m, g in a0.groupby("month_end", sort=True)}
    del a0, _labels
    extra = {}
    if fam == "A1":
        from pflab.data import bse_scrip_isin, red_flag_events
        rd = importlib.util.spec_from_file_location("rd", ROOT / "tools/a1_read_events.py")
        rdm = importlib.util.module_from_spec(rd)
        rd.loader.exec_module(rdm)
        blk = cfg["e5a"]["a1"]
        reads = rdm.load_reads(blk["l_model"])
        raw = red_flag_events.load()
        evs = ev_mod.subtyped(raw, blk["reader"], reads, period.end)
        smap = bse_scrip_isin.load()
        smap = smap[smap["isin"] != ""]
        mes = sorted(universe)
        feats = ev_mod.a1_features(evs, universe, mes, smap, blk["reader"])
        rp = rdm.out_path(blk["l_model"])
        from pflab.data import data_dir
        extra = {"events_file": artifacts.file_sha(data_dir() / "red_flag_events" / "events.parquet"),
                 "reads_file": artifacts.file_sha(rp) if rp.exists() else None,
                 "l_model": blk["l_model"],
                 "events_counted": {f"{f}/{s}": int(n) for (f, s), n in
                                    evs.groupby(["flag", "subtype"]).size().items()},
                 "scrip_map": _sha_df(smap[["scrip_code", "isin", "valid_from", "valid_to"]])}
    elif fam == "A5":
        from pflab.data import bse_scrip_isin, data_dir, positioning as pos
        from pflab.ranker import valuation as va
        import duckdb
        _p, panel, *_rest = runner.prepare(family.base_config(cfg), period_name)
        panel = ft.dated(panel)
        if artifacts.data_fingerprint(panel) != a0_meta["panel_fingerprint"]:
            raise SystemExit("the panel differs from the one A0's store was built on")
        blk = cfg["e5a"].get("a5") or {}
        if list(blk.get("columns", [])) != va.COLUMNS or                 (blk.get("hist_months"), blk.get("hist_min")) != (va.HIST, va.HIST_MIN):
            raise SystemExit(f"[e5a.a5] {blk} disagrees with valuation.py")
        rdir = data_dir() / "bse_results"
        raw = duckdb.connect().sql(f"""
            select scrip_code, qtr, fld_desc, "Value"
            from read_parquet('{rdir.as_posix()}/*.parquet', filename=true, file_row_number=true)
            order by filename, file_row_number""").df()   # the API's order: `pick` reads it first to last
        rq = va.results_quarters(raw)
        rq = rq[rq["quarter_end"] <= period.end]
        src = (data_dir() / "bse_announcements").as_posix() + "/*/*.parquet"
        ann = duckdb.connect().sql(f"""
            select scrip_code, coalesce(dissem_dt, news_dt) as t, category, subcategory, headline
            from read_parquet('{src}', union_by_name=true)
            where coalesce(dissem_dt, news_dt) <= TIMESTAMP '{period.end} 23:59:59'
              and (headline ilike '%result%' or category = 'Result')""").df()
        dq = va.dated_quarters(rq, va.matched_announcements(ann, rq))
        spath = data_dir() / "bse_shareholding" / "summary.parquet"
        sann = duckdb.connect().sql(f"""
            select scrip_code, coalesce(dissem_dt, news_dt) as t, headline
            from read_parquet('{src}', union_by_name=true)
            where (subcategory = 'Shareholding' or headline ilike '%shareholding pattern%')
              and coalesce(dissem_dt, news_dt) <= TIMESTAMP '{period.end} 23:59:59'""").df()
        shares = ho_mod.quarters(pd.read_parquet(spath), ho_mod.announcement_dates(sann))
        dpath = data_dir() / "dividends" / "dividends.parquet"
        div = pd.read_parquet(dpath)
        div = div[pd.to_datetime(div["ex_date"]).dt.date <= period.end]
        resolver = pos.ScripResolver(bse_scrip_isin.load())
        feats = va.a5_features(dq, div, shares, panel, universe, resolver)
        del panel
        extra = {"results_rows": _sha_df(raw.astype(str)),
                 "summary_file": artifacts.file_sha(spath),
                 "dividends_file": artifacts.file_sha(dpath),
                 "quarters": int(len(dq)),
                 "date_source": dq["date_source"].value_counts().to_dict(),
                 "date_source_by_year": {str(y): g.value_counts().to_dict() for y, g in
                                         dq.groupby([q.year for q in dq["quarter_end"]])["date_source"]},
                 "build_readings": ("TTM from the latest usable quarter and the three before, "
                                    "never substituted; EPS and dividends x k(then)/k(M), "
                                    "shares x k(M)/k(then); yoy over |earlier TTM|; no dividend = 0")}
    elif fam == "A2":
        from pflab.data import bse_scrip_isin, data_dir, positioning as pos
        _p, panel, _ix, actions, *_rest = runner.prepare(family.base_config(cfg), period_name)
        if artifacts.data_fingerprint(ft.dated(panel)) != a0_meta["panel_fingerprint"]:
            raise SystemExit("the panel differs from the one A0's store was built on")
        del panel
        if list((cfg["e5a"].get("a2") or {}).get("quarters", [])) != list(ho_mod.QUARTERS):
            raise SystemExit(f"[e5a.a2] quarters disagree with holdings.py's {ho_mod.QUARTERS}")
        spath = data_dir() / "bse_shareholding" / "summary.parquet"
        summary = pd.read_parquet(spath)
        resolver = pos.ScripResolver(bse_scrip_isin.load())
        import duckdb
        src = (data_dir() / "bse_announcements").as_posix() + "/*/*.parquet"
        ann = duckdb.connect().sql(f"""
            select scrip_code, coalesce(dissem_dt, news_dt) as t, headline
            from read_parquet('{src}', union_by_name=true)
            where (subcategory = 'Shareholding' or headline ilike '%shareholding pattern%')
              and coalesce(dissem_dt, news_dt) <= TIMESTAMP '{period.end} 23:59:59'""").df()
        announced = ho_mod.announcement_dates(ann)
        pq = ho_mod.quarters(summary, announced)
        pr = ho_mod.pairs(pq, actions, resolver.all_isins())
        feats = ho_mod.a2_features(pr, universe, resolver)
        extra = {"summary_file": artifacts.file_sha(spath),
                 "actions": _sha_df(actions.reset_index(drop=True)) if actions is not None else None,
                 "pledge_invocations": "dropped, declared (no source; E5-A §14 2026-10-01)",
                 "announcements": _sha_df(announced.astype(str)),
                 "date_source": pq["date_source"].value_counts().to_dict()}
    else:
        _p, panel, *_rest = runner.prepare(family.base_config(cfg), period_name)
        panel = ft.dated(panel)
        if artifacts.data_fingerprint(panel) != a0_meta["panel_fingerprint"]:
            raise SystemExit("the panel differs from the one A0's store was built on")
        names = sorted(set().union(*map(set, universe.values())))
        sub = panel.loc[panel["isin"].isin(names), ["date", "isin", "adj_close"]]
        cw = sub.pivot_table(index="date", columns="isin", values="adj_close", aggfunc="last")
        mes = ft.month_ends(panel)
        blk = cfg["e5a"].get("a3") or {}
        if (blk.get("window_months"), blk.get("min_obs")) != (ex_mod.WINDOW, ex_mod.MIN_OBS):
            raise SystemExit(f"[e5a.a3] {blk} disagrees with exposure.py's 36 / 24")
        series = ex_mod.load_series()
        feats = ex_mod.a3_features(cw, series, universe, mes, period.end)
        extra = {"series": {k: _sha_df(ex_mod.usable(s, ex_mod.FACTORS.get(k, (None, 0))[1],
                                                    period.end).reset_index())
                            for k, s in series.items()}}
    _say(f"{fam}: {len(feats):,} rows ({time.time() - t0:.0f}s)")
    avail = feats.groupby("feature")["available"].mean().round(4).to_dict()
    cov = (feats.groupby(["month_end", "isin"])["available"].any()
           .groupby(level=0).mean())
    meta = {"family": fam, "period": period.name, "period_start": str(period.start),
            "period_end": str(period.end), "config": config_path,
            "identity": family.identity(cfg), "builder_sha": family.builder_sha(fam),
            "a0_files": a0_meta["files"], "code": artifacts.code_commit(),
            "built_at": datetime.now(timezone.utc).isoformat(),
            "availability": avail,
            "coverage_by_year": {str(y): round(float(v), 4) for y, v in
                                 cov.groupby([m.year for m in cov.index]).mean().items()},
            "first_month_covered_50pct": next((str(m) for m, v in cov.items() if v >= 0.5), None),
            **extra}
    before = family.file_sha(d, fam)
    shas = family.write(d, fam, feats, meta)
    meta["seconds"] = round(time.time() - t0, 1)
    _say(f"wrote {d} ({meta['seconds']}s)" +
         ("" if before is None else f"; identical to the previous build: {before == shas[family.features_file(fam)]}"))
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--family", required=True, choices=family.FAMILIES)
    ap.add_argument("--config", required=True)
    ap.add_argument("--period", required=True)
    a = ap.parse_args(argv)
    meta = build(a.family, a.config, a.period)
    print(json.dumps({k: meta.get(k) for k in ("family", "period", "coverage_by_year",
                                               "first_month_covered_50pct", "events_counted",
                                               "seconds")}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
