"""Probe BSE's historical financial-results endpoint for A5 (E5-A §14
2026-10-01). Collects nothing large: a stratified sample, written to
PFLAB_DATA_DIR/_probe/bse_results_sample.parquet.

    python tools/probe_bse_results.py coverage --per-year 30
    python tools/probe_bse_results.py fetch --scrip 500325 --qtr 66
    python tools/probe_bse_results.py spotcheck --n 20
    python tools/probe_bse_results.py pull --dry-run     # size of the full pull
    python tools/probe_bse_results.py pull               # Aarsh's: hours, resumable

Endpoint (found 2026-10-01 in bseindia.com's results page bundle):
  Corp_detailedResult_Transpose_ng/w?Scrip_cd=<scrip>&Qtr=<qtr id>
standalone results, one row per line item, values as filed in the BSE
template (no filing timestamp). Quarter ids: Jun-2000 = 26, +1 a quarter,
annual = Mar quarter + 0.5. CorprateResultbeta/w?scripcode= lists every
quarter a company has. The filing time comes from the results announcement
in the BSE announcements feed (dissem_dt, else news_dt before 2015-08).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import random
import re
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pflab.data import data_dir, bse_scrip_isin  # noqa: E402
from pflab.data.bse_announcements import HEADERS  # noqa: E402

API = "https://api.bseindia.com/BseIndiaAPI/api/Corp_detailedResult_Transpose_ng/w"
SEED = 20261001
FIELDS = {"revenue": ("net sales/revenue from operations", "net sales / income from operations",
                      "revenue from operations", "net sales", "income from operations",
                      "interest earned"),
          "net_profit": ("net profit",),
          "eps": ("basic eps", "basic for", "basic", "eps")}


def qtr_id(q_end: date) -> float:
    """BSE's quarter id: Jun-2000 = 26."""
    k = (q_end.year - 2000) * 4 + (q_end.month - 6) // 3
    return 26.0 + k


def fetch(session, scrip: str, qtr: float) -> list:
    for attempt in range(3):
        try:
            r = session.get(API, params={"Scrip_cd": scrip, "Qtr": f"{qtr:.2f}"},
                            headers=HEADERS, timeout=30)
            if r.status_code == 200 and r.text.strip().startswith("{"):
                return r.json().get("table1") or []
        except Exception:
            pass
        time.sleep(1 + attempt)
    return None


def pick(rows: list, keys) -> float | None:
    for k in keys:
        for x in rows:
            d = x.get("fld_desc", "").strip().lower()
            if d.startswith(k):
                try:
                    return float(str(x.get("Value", "")).replace(",", ""))
                except ValueError:
                    continue
    return None


def parse(rows: list) -> dict:
    if rows is None:
        return {"status": "error"}
    out = {"status": "ok" if len(rows) > 3 else "empty", "n_lines": len(rows)}
    for f, keys in FIELDS.items():
        out[f] = pick(rows, keys)
    hdr = {x["fld_desc"]: x["Value"] for x in rows if x.get("Header") == "2"}
    out["type"] = hdr.get("Type")
    out["date_end"] = hdr.get("Date End")
    return out


def universe_sample(per_year: int) -> pd.DataFrame:
    """per_year ISINs drawn from E1's universe (A0 stores' U(M)) at each
    September month-end 2007-2021, with the BSE scrip carrying each then."""
    from pflab.ranker import store
    rng = random.Random(SEED)
    rows = []
    smap = bse_scrip_isin.load()
    smap = smap[smap["isin"] != ""]
    for per in ("e5a_development", "validation"):
        f = pd.read_parquet(store.store_dir(per) / "features_a0.parquet",
                            columns=["isin", "month_end", "feature"])
        f = f[f["feature"] == "mom_1m"]
        f["month_end"] = pd.to_datetime(f["month_end"]).dt.date
        for y in range(2007, 2022):
            ms = sorted(m for m in f["month_end"].unique() if m.year == y and m.month == 9)
            if not ms:
                continue
            m = ms[-1]
            isins = sorted(f.loc[f["month_end"] == m, "isin"].unique())
            t = pd.Timestamp(m)
            ok = smap[(smap["valid_from"] <= t) & (smap["valid_to"] >= t)]
            sc = ok.drop_duplicates("isin").set_index("isin")["scrip_code"].astype(str)
            pool = [i for i in isins if i in sc.index]
            for i in rng.sample(pool, min(per_year, len(pool))):
                rows.append({"year": y, "month_end": m, "isin": i, "scrip_code": sc[i],
                             "universe": len(isins), "with_scrip": len(pool)})
    return pd.DataFrame(rows).drop_duplicates(["year", "isin"])


def announcements_for(sample: pd.DataFrame) -> pd.DataFrame:
    """The first results announcement for the September quarter, per row:
    from 2015-08 BSE's own category (Result / Financial Results, whose
    headline rarely names the quarter); before it, a headline naming results
    and September. Window: 1 October to 15 January."""
    import duckdb
    src = (data_dir() / "bse_announcements").as_posix() + "/*/*.parquet"
    con = duckdb.connect()
    con.register("s", sample[["year", "scrip_code"]])
    q = f"""
      select s.year, s.scrip_code, min(coalesce(a.dissem_dt, a.news_dt)) as filed,
             arg_min(a.attachment, coalesce(a.dissem_dt, a.news_dt)) as attachment
      from s join read_parquet('{src}', union_by_name=true) a
        on a.scrip_code = s.scrip_code
       and coalesce(a.dissem_dt, a.news_dt) between make_date(s.year, 10, 1)
                                               and make_date(s.year + 1, 1, 15)
       and ((a.category = 'Result' and a.subcategory = 'Financial Results')
            or (a.headline ilike '%result%' and a.headline ilike '%september%'))
      group by 1, 2"""
    return con.sql(q).df()


def coverage(per_year: int) -> None:
    sample = universe_sample(per_year)
    s = requests.Session()
    sample["qtr"] = [qtr_id(date(y, 9, 30)) for y in sample["year"]]

    def job(r):
        return parse(fetch(s, r.scrip_code, r.qtr))
    with cf.ThreadPoolExecutor(4) as ex:
        res = list(ex.map(job, sample.itertuples(index=False)))
    out = pd.concat([sample.reset_index(drop=True), pd.DataFrame(res)], axis=1)
    ann = announcements_for(out)
    out = out.merge(ann, on=["year", "scrip_code"], how="left")
    p = data_dir() / "_probe"
    p.mkdir(exist_ok=True)
    out.to_parquet(p / "bse_results_sample.parquet", index=False)
    g = out.groupby("year").agg(
        n=("isin", "size"), ok=("status", lambda x: (x == "ok").mean()),
        revenue=("revenue", lambda x: x.notna().mean()),
        net_profit=("net_profit", lambda x: x.notna().mean()),
        eps=("eps", lambda x: x.notna().mean()),
        dated=("filed", lambda x: x.notna().mean()),
        universe_with_scrip=("with_scrip", "first"), universe=("universe", "first"))
    print(g.round(2).to_string())
    print(json.dumps({"rows": len(out), "errors": int((out["status"] == "error").sum())}))


NUM = re.compile(r"\(?-?\d[\d,]*\.?\d*\)?")
SCALES = {"as stored": 1.0, "lakh": 10.0, "crore": 0.1, "thousand": 1000.0,
          "rupees": 1e6, "million x100": 100.0}


def in_filing(value: float, numbers: list) -> str | None:
    """The unit in which `value` appears among the filing's numbers (within
    0.5%, or 1 unit of the last digit for small values), else None."""
    if value is None or value == 0:
        return None
    for unit, k in SCALES.items():
        v = abs(value * k)
        if any(abs(abs(n) - v) <= max(0.005 * v, 0.51) for n in numbers):
            return unit
    return None


def spotcheck(n: int) -> None:
    """n seeded rows from the coverage sample, 2011-2016, checked against the
    PDF attached to the results announcement that dates them."""
    sys.path.insert(0, str(ROOT / "tools"))
    import rating_pdfs as rp
    o = pd.read_parquet(data_dir() / "_probe" / "bse_results_sample.parquet")
    o = o[o["year"].between(2011, 2016) & (o["status"] == "ok") &
          o["attachment"].fillna("").ne("")]
    o = o.sample(n=n, random_state=SEED).sort_values(["year", "scrip_code"])
    s, root, rows = requests.Session(), rp._root(), []
    for r in o.itertuples(index=False):
        pdf = rp.fetch(r.attachment, s, root)
        rec = {"year": r.year, "scrip_code": r.scrip_code, "isin": r.isin,
               "attachment": r.attachment, "revenue": r.revenue,
               "net_profit": r.net_profit, "eps": r.eps}
        if pdf is None:
            rec["result"] = "no PDF at BSE"
        else:
            text, _ = rp.extract(pdf)
            nums = []
            for t in NUM.findall(text):
                t2 = t.replace(",", "").strip("()")
                try:
                    nums.append(float(t2))
                except ValueError:
                    pass
            if len(nums) < 20:
                rec["result"] = "scanned (no text)"
            else:
                u = {f: in_filing(getattr(r, f), nums) for f in ("revenue", "net_profit", "eps")}
                rec.update({f"{f}_unit": v for f, v in u.items()})
                hit = [f for f, v in u.items() if v]
                rec["result"] = ("all three match" if len(hit) == 3 else
                                 f"match: {', '.join(hit) or 'none'}")
        rows.append(rec)
        print(f"{r.year} {r.scrip_code} {rec['result']}", flush=True)
    out = pd.DataFrame(rows)
    out.to_parquet(data_dir() / "_probe" / "bse_results_spotcheck.parquet", index=False)
    print(out["result"].value_counts().to_string())


LIST_API = "https://api.bseindia.com/BseIndiaAPI/api/CorprateResultbeta/w"
FIRST_Q, LAST_Q = date(2006, 12, 31), date(2021, 12, 31)   # 2007 TTM .. validation end


def universe_scrips() -> list:
    """Every BSE scrip that carried an ISIN of E1's U(M), 2007-2021."""
    from pflab.ranker import store
    isins = set()
    for per in ("e5a_development", "validation"):
        f = pd.read_parquet(store.store_dir(per) / "features_a0.parquet",
                            columns=["isin", "month_end", "feature"])
        f = f[(f["feature"] == "mom_1m") &
              (pd.to_datetime(f["month_end"]).dt.year.between(2007, 2021))]
        isins |= set(f["isin"])
    smap = bse_scrip_isin.load()
    return sorted(set(smap.loc[smap["isin"].isin(isins), "scrip_code"].astype(str)))


def pull(dry_run: bool) -> None:
    """Every quarter FIRST_Q..LAST_Q of every universe scrip, raw line items,
    one parquet per scrip under PFLAB_DATA_DIR/bse_results/. Resumable: a
    scrip whose file exists is skipped. Nothing past 2021-12-31 is fetched
    (the sealed period is never collected for a backtest input)."""
    scrips = universe_scrips()
    out = data_dir() / "bse_results"
    todo = [sc for sc in scrips if not (out / f"{sc}.parquet").exists()]
    lo, hi = qtr_id(FIRST_Q), qtr_id(LAST_Q)
    n_q = int(hi - lo + 1)
    print(f"{len(scrips)} scrips, {len(todo)} to fetch; up to {n_q} quarters each "
          f"(+1 list call); ~{len(todo) * (n_q + 1) / 2.9 / 3600:.1f} h at the probe's 2.9 req/s")
    if dry_run:
        return
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()

    def one(sc):
        try:
            r = s.get(LIST_API, params={"scripcode": sc}, headers=HEADERS, timeout=30)
            # Table: one row per financial year, Q1..Q4 = "Jun-10;JQ2010-2011;66.00;<url>"
            have = {float(v.split(";")[2]) for x in (r.json().get("Table") or [])
                    for c in ("Q1", "Q2", "Q3", "Q4") if (v := x.get(c))}
        except Exception:
            have = None                      # list failed: try every quarter
        rows = []
        for k in range(n_q):
            q = lo + k
            if have is not None and q not in have:
                continue
            t = fetch(s, sc, q)
            for x in t or []:
                rows.append({"scrip_code": sc, "qtr": q, **{c: str(x.get(c)) for c in
                             ("fld_type", "fld_desc", "Value", "Header", "Fld_SequenceID")}})
            if t is None:
                rows.append({"scrip_code": sc, "qtr": q, "fld_desc": "__ERROR__"})
        pd.DataFrame(rows, columns=["scrip_code", "qtr", "fld_type", "fld_desc", "Value",
                                    "Header", "Fld_SequenceID"]).to_parquet(
            out / f"{sc}.parquet", index=False)
        return sc, len(rows)
    t0 = time.time()
    with cf.ThreadPoolExecutor(4) as ex:
        for i, (sc, n) in enumerate(ex.map(one, todo), 1):
            if i % 25 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} scrips, {(time.time() - t0) / 60:.0f} min", flush=True)
    print(f"DONE: {len(scrips)} scrips in {out}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("redate", help="re-date the saved sample (no network)")
    pl = sub.add_parser("pull")
    pl.add_argument("--dry-run", action="store_true")
    sp = sub.add_parser("spotcheck")
    sp.add_argument("--n", type=int, default=20)
    c = sub.add_parser("coverage")
    c.add_argument("--per-year", type=int, default=30)
    f = sub.add_parser("fetch")
    f.add_argument("--scrip", required=True)
    f.add_argument("--qtr", type=float, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "coverage":
        coverage(a.per_year)
    elif a.cmd == "pull":
        pull(a.dry_run)
    elif a.cmd == "spotcheck":
        spotcheck(a.n)
    elif a.cmd == "redate":
        p = data_dir() / "_probe" / "bse_results_sample.parquet"
        out = pd.read_parquet(p).drop(columns=["filed", "attachment"])
        out = out.merge(announcements_for(out), on=["year", "scrip_code"], how="left")
        out.to_parquet(p, index=False)
        lag = (pd.to_datetime(out["filed"]) - pd.to_datetime(out["year"].astype(str) + "-09-30")).dt.days
        print(out.assign(lag=lag).groupby("year").agg(
            ok=("status", lambda x: (x == "ok").mean()),
            dated=("filed", lambda x: x.notna().mean()),
            lag_median=("lag", "median"), lag_max=("lag", "max")).round(2).to_string())
    else:
        rows = fetch(requests.Session(), a.scrip, a.qtr)
        print(json.dumps(parse(rows), indent=1, default=str))
        for x in rows or []:
            print(f"  {x.get('fld_desc')}: {x.get('Value')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
