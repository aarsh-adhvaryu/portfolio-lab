"""Build the graph from the raw files, deterministically (S81 B7).

`build(root, asof, ...)` reads only raw files under `<root>` (index membership, panel prices, BSE scrip map / announcements / results, the GKG rows and article
texts of `news_s81`, the scope, the classification cache) and returns the five tables. The same files give the same tables byte for byte: every table is
sorted by its key and written with fixed options (`write`, `hash_tables`).

Layer 1 FACTS by ISIN from structured sources only (instrument master, industry, index membership, prices, results from the filings' own tables). Each: source,
as-of date, and `known_from` (<= asof: point in time; a result is known from its quarter end + 60 days, the rule `fundamentals/pit.py` uses).
Layer 2 RELATIONS by a NAMED rule only: `same_industry`, `same_group_prefix` (the group list in configs/kg2_groups.toml). A supplier/customer relation exists only
where a filing states it and no parser for that exists yet, so there are none. No relation is written by a model.
Layer 3 EVENTS (filings, news), attached by a confident rule only; the rule and its proof are on the row:
  filing   its scrip code -> the ISIN valid on its dissemination DATE (`bse_scrip_isin`); a filing with a date but NO dissemination time is used from the NEXT TRADING DAY's
           open (09:15 IST; A58, `filing_time.py`), its time stored as DERIVED (`ts_rule`), its date on the row
  news     the article row's organisation token equals the company's alias (tag) AND the article's own text names the company (or, with no text, its URL slug does)
Everything else is `unlinked` (counted by reason, never shown).
"""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import pandas as pd

from pflab.kg2 import classify, filing_time as ft, news, scope as sc, you

NODE_COLS = ["isin", "name", "symbol", "origin", "source", "as_of"]
FACT_COLS = ["isin", "fkey", "fvalue", "value_num", "source", "as_of", "known_from"]
REL_COLS = ["src_isin", "dst_isin", "rule", "detail", "source", "as_of"]
EVENT_COLS = ["event_id", "isin", "source", "ref", "ts", "event_date", "kind", "severity", "headline", "link_rule", "link_proof", "dedupe_key", "ts_rule"]
UNLINKED_COLS = ["source", "ref", "ts", "reason", "scope_name"]
TABLES = {"node": NODE_COLS, "fact": FACT_COLS, "relation": REL_COLS, "event": EVENT_COLS, "unlinked": UNLINKED_COLS}
KEYS = {"node": ["isin"], "fact": ["isin", "fkey", "as_of"], "relation": ["src_isin", "dst_isin", "rule"], "event": ["event_id"],
        "unlinked": ["source", "ref", "reason", "scope_name"]}
RELATION_RULES = ("same_industry", "same_group_prefix", "supplier_customer_filing")
GROUPS_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "kg2_groups.toml"
RESULT_LAG_DAYS = 60
MAX_PEER_GROUP = 60                  # a bucket of more than this many names is not a peer set (no relation written)
_WS = re.compile(r"\s+")


def _d(x) -> Optional[date]:
    if x is None or (isinstance(x, float) and pd.isna(x)) or x is pd.NaT:
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return pd.Timestamp(x).date()
    except (ValueError, TypeError):
        return None


def _eid(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def norm_headline(h: str) -> str:
    return _WS.sub(" ", re.sub(r"[^a-z0-9 ]", " ", str(h or "").lower())).strip()


def _frame(rows: List[dict], cols: List[str], key: List[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=cols)
    return df.sort_values(key, kind="mergesort").reset_index(drop=True) if len(df) else df


# ------------------------------------------------------------------ the scrip -> ISIN map, by date

def scrip_map(root: Path) -> pd.DataFrame:
    m = pd.read_parquet(Path(root) / "bse_scrip_isin" / "map.parquet")
    m["scrip_code"] = m["scrip_code"].astype(str)
    m["vf"] = pd.to_datetime(m["valid_from"]).dt.date
    m["vt"] = pd.to_datetime(m["valid_to"]).dt.date
    return m


def link_scrips(filings: pd.DataFrame, m: pd.DataFrame) -> pd.DataFrame:
    """Add `isin` (the ISIN valid on the filing's dissemination DATE, inclusive both ends; the newest `valid_from` when two overlap) and `why` for the rest:
    no_scrip_map, blank_isin, outside_isin_validity, ambiguous. `filings` needs `scrip_code` (str) and `day` (date)."""
    f = filings.copy()
    f.index.name = "rid"
    good = m[m["isin"].fillna("") != ""][["scrip_code", "isin", "vf", "vt"]]
    j = f[["scrip_code", "day"]].reset_index().merge(good, on="scrip_code", how="left")
    inside = j[j["isin"].notna() & (j["day"] >= j["vf"]) & (j["day"] <= j["vt"])]
    top = inside[inside["vf"] == inside.groupby("rid")["vf"].transform("max")]
    amb = top.groupby("rid")["isin"].nunique()
    ambiguous = set(amb[amb > 1].index)
    pick = top.sort_values(["rid", "isin"], kind="mergesort").drop_duplicates("rid").set_index("rid")["isin"]
    f["isin"] = pick.reindex(f.index)
    f.loc[list(ambiguous), "isin"] = None
    have = set(m["scrip_code"])
    blank = set(m[m["isin"].fillna("") == ""]["scrip_code"]) - set(good["scrip_code"])
    f["why"] = None
    for i in f.index[f["isin"].isna()]:
        s_ = f.at[i, "scrip_code"]
        f.at[i, "why"] = "ambiguous" if i in ambiguous else "no_scrip_map" if s_ not in have else "blank_isin" if s_ in blank else "outside_isin_validity"
    return f


# ------------------------------------------------------------------ filings

def read_filings(root: Path, since: date, until: date) -> pd.DataFrame:
    """Raw announcements dated since..until (file days; a filing's own day is its dissemination date, below)."""
    base = Path(root) / "bse_announcements"
    frames = []
    for y in range(since.year, until.year + 1):
        for p in sorted((base / str(y)).glob("*.parquet")):
            if since.isoformat() <= p.stem <= (until + timedelta(days=1)).isoformat():
                frames.append(pd.read_parquet(p).assign(file_day=date.fromisoformat(p.stem)))
    if not frames:
        return pd.DataFrame(columns=["scrip_code", "company", "headline", "category", "subcategory", "news_dt", "dissem_dt", "attachment", "news_sub", "file_day"])
    df = pd.concat(frames, ignore_index=True)
    df["scrip_code"] = df["scrip_code"].astype(str)
    return df


def filing_events(root: Path, asof: date, since: date, scope_isins: set, cache: Dict[str, dict], names: Dict[str, str]) -> tuple:
    """(events, unlinked, stats) for the filings of the scope's scrips. A filing with no dissemination time is used from the next trading day's open (A58): its `ts` is that
    open, `ts_rule` says `next_open_no_release_time`, `event_date` is the filing's own date. Only filings dated on or before `asof` are read (a derived time may fall after `asof`:
    readers hold such a row back until its time, `kg.events.material_events(until=...)`)."""
    m = scrip_map(root)
    my = m[m["isin"].isin(scope_isins)]["scrip_code"].unique()
    df = read_filings(root, since, asof)
    stats = {"filings_read": int(len(df)), "no_dissem_time": 0, "derived_time_used": 0, "in_scope": 0}
    if df.empty:
        return [], [], stats
    df = df[df["scrip_code"].isin(set(my))].copy()
    stats["in_scope"] = int(len(df))
    stats["no_dissem_time"] = int(df["dissem_dt"].isna().sum())
    tr = [ft.filing_time(a, b, c) for a, b, c in zip(df["dissem_dt"], df["news_dt"], df["file_day"])]
    df["ts"] = [t[0] for t in tr]
    df["ts_rule"] = [t[1] for t in tr]
    df["day"] = [t[2] for t in tr]
    df = df[df["ts_rule"].notna()].copy()                                      # a row with no date at all cannot be placed in time
    df = df[df["day"] <= asof]
    derived = df["ts_rule"] == ft.RULE_DERIVED
    timed_keys = {(a, norm_headline(h), d) for a, h, d in zip(df.loc[~derived, "scrip_code"], df.loc[~derived, "headline"], df.loc[~derived, "day"])}
    twin = derived & pd.Series([(a, norm_headline(h), d) in timed_keys for a, h, d in zip(df["scrip_code"], df["headline"], df["day"])], index=df.index)
    stats["derived_dropped_twin_of_timed"] = int(twin.sum())
    df = df[~twin]
    df = df.drop_duplicates(["scrip_code", "headline", "ts"]).reset_index(drop=True)
    stats["derived_time_used"] = int((df["ts_rule"] == ft.RULE_DERIVED).sum())
    lk = link_scrips(df, m)
    events, unlinked = [], []
    seen = set()
    for r in lk.itertuples():
        ts = pd.Timestamp(r.ts).to_pydatetime()
        if pd.isna(r.isin) or r.isin is None:
            unlinked.append({"source": "bse_announcement", "ref": f"{r.scrip_code}|{ts.isoformat()}", "ts": ts, "reason": r.why, "scope_name": r.company})
            continue
        head = str(r.headline or "")
        key = (r.isin, norm_headline(head), ts)
        if key in seen:
            continue
        seen.add(key)
        eid = _eid("bse_announcement", r.scrip_code, ts.isoformat(), norm_headline(head))
        kind, sev = classify.rule_kind(head + " " + str(r.news_sub or ""), str(r.category or ""), str(r.subcategory or ""))
        c = cache.get(eid)
        if c and kind == "other":
            kind, sev = c["kind"], c["severity"]
        derived_row = r.ts_rule == ft.RULE_DERIVED
        events.append({"event_id": eid, "isin": r.isin, "source": "bse_announcement", "ref": str(r.attachment or f"{r.scrip_code}|{ts.isoformat()}"), "ts": ts,
                       "event_date": r.day, "kind": kind, "severity": sev, "headline": head[:500],
                       "link_rule": "filing:scrip_isin_on_filing_date_no_release_time" if derived_row else "filing:scrip_isin_on_dissem_date",
                       "link_proof": f"scrip {r.scrip_code} -> {r.isin} valid on {r.day.isoformat()}" + (f"; no release time: used from {ts:%Y-%m-%d %H:%M} (next trading open)" if derived_row else ""),
                       "dedupe_key": f"{r.isin}|{norm_headline(head)}|{ts.isoformat()}", "ts_rule": r.ts_rule})
    return events, unlinked, stats


# ------------------------------------------------------------------ news

def _slug_words(url: str) -> str:
    p = urlparse(url)
    return " " + _WS.sub(" ", re.sub(r"[^a-z0-9]+", " ", (p.path + " " + p.netloc).lower())).strip() + " "


def news_events(root: Path, asof: date, since: date, scope: dict, cache: Dict[str, dict]) -> tuple:
    """(events, unlinked, stats). An article of day D is usable from D+1: only rows dated before `asof` are read."""
    df = news.load_rows(root, since)
    stats = {"news_rows": int(len(df))}
    if df.empty:
        return [], [], stats
    df = df[pd.to_datetime(df["date"]).dt.date < asof]
    by_isin = {n["isin"]: n for n in scope.get("names", [])}
    firsts: Dict[str, int] = {}
    for n in scope.get("names", []):
        for a in n.get("aliases", []):
            w = a.split()[0]
            firsts[w] = firsts.get(w, 0) + 1
    events, unlinked, seen = [], [], set()
    for r in df.sort_values(["isin", "url", "org"], kind="mergesort").itertuples():
        n = by_isin.get(r.isin)
        if not n or r.org not in set(n.get("aliases", [])):
            unlinked.append({"source": "gdelt_gkg1", "ref": r.url, "ts": None, "reason": "tag_org_disagree", "scope_name": r.org})
            continue
        day = pd.Timestamp(r.date).date()
        h = news.url_hash(r.url)
        tp = news.text_path(root, h)
        title, proof, rule = "", "", ""
        if tp.exists():
            t = json.loads(tp.read_text(encoding="utf-8"))
            hay = " " + _WS.sub(" ", re.sub(r"[^a-z0-9&+ ]", " ", (t.get("title", "") + " " + t.get("text", "")[:4000]).lower())) + " "
            title = t.get("title", "")
            hit = next((a for a in n["aliases"] if f" {a} " in hay), None)
            if hit:
                rule, proof = "news:org_exact+text_name", f"org token '{r.org}' = alias of {r.isin}; '{hit}' is in the text {h}"
            else:
                unlinked.append({"source": "gdelt_gkg1", "ref": r.url, "ts": None, "reason": "text_lacks_name", "scope_name": r.org})
                continue
        else:
            slug = _slug_words(r.url)
            hit = next((a for a in n["aliases"] if f" {a} " in slug), None)
            if not hit:
                a0 = n["aliases"][0].split()[0] if n["aliases"] else ""
                if len(a0) >= 6 and firsts.get(a0, 0) == 1 and f" {a0} " in slug:
                    hit = a0
            if hit:
                rule, proof = "news:org_exact+url_slug", f"org token '{r.org}' = alias of {r.isin}; '{hit}' is in the URL"
            else:
                unlinked.append({"source": "gdelt_gkg1", "ref": r.url, "ts": None, "reason": "text_pending" if n.get("text") else "no_second_confirmation",
                                 "scope_name": r.org})
                continue
        ts = datetime(day.year, day.month, day.day, 23, 59, 59)
        head = title or " ".join(urlparse(r.url).path.strip("/").split("/")[-1].replace("-", " ").split())[:200]
        key = (r.isin, norm_headline(head), day)
        if key in seen:
            continue
        seen.add(key)
        eid = _eid("gdelt_gkg1", r.isin, r.url)
        kind, sev = classify.rule_kind(head)
        kind = "news" if kind == "other" else kind
        if kind == "leadership_crisis":
            kind, sev = "news", "low"        # S84: a governance keyword in a headline is a lead the local model must confirm (the cache's pick may make it leadership_crisis / high); never a sale by itself
        if kind in classify.THESIS_BREAK_KINDS:
            sev = "low"          # a keyword in an article is a lead, never a thesis break by itself (the model's validated pick may raise it)
        c = cache.get(eid)
        if c and kind == "news":
            kind, sev = c["kind"], c["severity"]
            if kind == "leadership_crisis":
                # S84: a sale-grade kind from an article needs the company named in the HEADLINE itself (real run 2026-11-12: of four model-confirmed leads, two were about another body,
                # a school-board chairman and "a Mumbai-based firm", linked only because the company was named in the article's text). Otherwise it stays a lead.
                hn = " " + _WS.sub(" ", re.sub(r"[^a-z0-9&+ ]", " ", head.lower())) + " "
                if not any(f" {a} " in hn for a in n["aliases"]):
                    kind, sev = "news", "low"
        events.append({"event_id": eid, "isin": r.isin, "source": "gdelt_gkg1", "ref": r.url, "ts": ts, "event_date": day, "kind": kind, "severity": sev,
                       "headline": head[:500], "link_rule": rule, "link_proof": proof, "dedupe_key": f"{r.isin}|{norm_headline(head)}|{day.isoformat()}",
                       "ts_rule": ft.RULE_NEWS})
    return events, unlinked, stats


# ------------------------------------------------------------------ facts, nodes, relations

def _read_prices(root: Path, isins: set, asof: date) -> pd.DataFrame:
    import pyarrow.dataset as ds
    d = ds.dataset(str(Path(root) / "panel" / "prices.parquet"))
    import pyarrow as pa
    lim = asof.isoformat() if pa.types.is_string(d.schema.field("date").type) or pa.types.is_large_string(d.schema.field("date").type) else asof
    f = ds.field("isin").isin(sorted(isins)) & (ds.field("date") <= lim)
    t = d.to_table(columns=["date", "isin", "close", "volume"], filter=f).to_pandas()
    return t


def quarter_end(qtr: float) -> date:
    k = int(round(qtr)) - 26
    y, mo = 2000 + (6 + 3 * k - 1) // 12, (6 + 3 * k - 1) % 12 + 1
    return (pd.Timestamp(y, mo, 1) + pd.offsets.MonthEnd(0)).date()


RESULT_FIELDS = {"Net Sales/Revenue From Operations": "net_sales_as_filed", "Net Profit": "net_profit_as_filed", "Basic EPS for continuing operation": "eps_basic_as_filed"}


def result_facts(root: Path, isin_scrips: Dict[str, str], asof: date) -> List[dict]:
    out = []
    for isin, scrip in sorted(isin_scrips.items()):
        p = Path(root) / "bse_results" / f"{scrip}.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        qs = sorted(q for q in d["qtr"].dropna().unique() if quarter_end(q) + timedelta(days=RESULT_LAG_DAYS) <= asof)
        if not qs:
            continue
        q = qs[-1]
        known = quarter_end(q) + timedelta(days=RESULT_LAG_DAYS)
        sub = d[d["qtr"] == q]
        for desc, key in RESULT_FIELDS.items():
            v = sub[sub["fld_desc"] == desc]["Value"]
            if len(v):
                try:
                    num = float(str(v.iloc[0]).replace(",", ""))
                except ValueError:
                    continue
                out.append({"isin": isin, "fkey": key, "fvalue": f"{num:g}", "value_num": num, "source": "bse_results:quarter_end+60d",
                            "as_of": quarter_end(q), "known_from": known})
    return out


def facts_and_nodes(root: Path, asof: date, scope: dict) -> tuple:
    root = Path(root)
    names = scope.get("names", [])
    isins = {n["isin"] for n in names}
    nm = pd.read_parquet(root / "index_membership" / "name_map.parquet")
    nm = nm[nm["isin"].isin(isins)].sort_values(["isin", "last_seen"])
    nm_last = nm.groupby("isin").tail(1).set_index("isin")
    nodes, facts = [], []
    for n in names:
        isin = n["isin"]
        row = nm_last.loc[isin] if isin in nm_last.index else None
        nm_as = _d(row["last_seen"]) if row is not None else None
        nodes.append({"isin": isin, "name": (row["name"] if row is not None else n.get("name")) or n.get("name") or "", "symbol": n.get("symbol") or (row["symbol"] if row is not None else ""),
                      "origin": n.get("origin", ""), "source": "instrument_master:name_map" if row is not None else "scope:" + n.get("origin", "scope"),
                      "as_of": nm_as or _d(scope.get("built")) or asof})
    # industry (latest capture on or before asof)
    sm = pd.read_parquet(root / "index_membership" / "sector_map.parquet")
    sm = sm[sm["isin"].isin(isins)].copy()
    sm["cd"] = pd.to_datetime(sm["capture_date"]).dt.date
    sm = sm[sm["cd"] <= asof].sort_values(["isin", "cd", "index"], kind="mergesort").groupby("isin").tail(1)
    for r in sm.itertuples():
        facts.append({"isin": r.isin, "fkey": "industry", "fvalue": str(r.industry), "value_num": None, "source": f"index_membership/sector_map:{r.index}",
                      "as_of": r.cd, "known_from": r.cd})
    # index membership
    for ix in ("NIFTY100", "NIFTY200", "NIFTY500", "NIFTY_MIDCAP100"):
        p = root / "index_membership" / f"{ix}.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        d = d[d["isin"].isin(isins)].copy()
        d["fd"] = pd.to_datetime(d["from_date"]).dt.date
        d["td"] = d["to_date"].map(_d)
        d = d[(d["fd"] <= asof) & d["td"].map(lambda x: x is None or x > asof)]
        for r in d.sort_values(["isin", "fd"], kind="mergesort").groupby("isin").tail(1).itertuples():
            facts.append({"isin": r.isin, "fkey": f"index_member:{ix}", "fvalue": "member", "value_num": 1.0, "source": f"index_membership/{ix}", "as_of": r.fd, "known_from": r.fd})
    # prices and listing date
    px = _read_prices(root, isins, asof)
    if len(px):
        px = px[px["close"] > 0].sort_values(["isin", "date"], kind="mergesort").groupby("isin").tail(1)
        for r in px.itertuples():
            dd = _d(r.date)
            facts.append({"isin": r.isin, "fkey": "last_close", "fvalue": f"{r.close:.2f}", "value_num": float(r.close), "source": "panel/prices", "as_of": dd, "known_from": dd})
    ld = pd.read_parquet(root / "panel" / "listing_dates.parquet")
    for isin, r in ld[ld.index.isin(isins)].iterrows():
        dd = _d(r["first_trade"])
        if dd and dd <= asof:
            facts.append({"isin": isin, "fkey": "listing_date", "fvalue": dd.isoformat(), "value_num": None, "source": "panel/listing_dates", "as_of": dd, "known_from": dd})
    # results from the filings' own tables, by the scrip valid at asof
    m = scrip_map(root)
    cur = m[(m["isin"].isin(isins)) & (m["vf"] <= asof) & (m["vt"] >= asof)].sort_values(["isin", "vf", "scrip_code"], kind="mergesort").groupby("isin").tail(1)
    facts += result_facts(root, dict(zip(cur["isin"], cur["scrip_code"])), asof)
    return nodes, facts


def groups_config(path: Optional[Path] = None) -> Dict[str, List[str]]:
    p = path or GROUPS_CONFIG
    if not p.exists():
        return {}
    return {k: [x.lower() for x in v] for k, v in tomllib.loads(p.read_text(encoding="utf-8")).get("groups", {}).items()}


def relations(nodes: List[dict], facts: List[dict], groups: Dict[str, List[str]]) -> List[dict]:
    out: List[dict] = []
    ind: Dict[str, List[tuple]] = {}
    for f in facts:
        if f["fkey"] == "industry":
            ind.setdefault(f["fvalue"], []).append((f["isin"], f["as_of"]))
    for industry, members in sorted(ind.items()):
        members = sorted(set(members))
        if not 2 <= len(members) <= MAX_PEER_GROUP:
            continue
        for i, (a, da) in enumerate(members):
            for b, db in members[i + 1:]:
                out.append({"src_isin": a, "dst_isin": b, "rule": "same_industry", "detail": industry, "source": "index_membership/sector_map", "as_of": max(da, db)})
    first = {n["isin"]: (sc.norm_name(n["name"]).split() or [""])[0] for n in nodes}
    asof_of = {n["isin"]: n["as_of"] for n in nodes}
    for g, prefixes in sorted(groups.items()):
        mem = sorted(i for i, w in first.items() if w in prefixes)
        for k, a in enumerate(mem):
            for b in mem[k + 1:]:
                out.append({"src_isin": a, "dst_isin": b, "rule": "same_group_prefix", "detail": g, "source": "configs/kg2_groups.toml+instrument_master",
                            "as_of": max(asof_of[a], asof_of[b])})
    return out


# ------------------------------------------------------------------ the build

def build(root: Path, asof: date, scope: Optional[dict] = None, since: Optional[date] = None, groups: Optional[Dict[str, List[str]]] = None,
          with_news: bool = True) -> dict:
    """The graph as five DataFrames plus `stats`. Deterministic: sorted by key, no clock inside."""
    root = Path(root)
    scope = scope if scope is not None else sc.load(root)
    since = since or (asof - timedelta(days=400))
    cache = classify.load_cache(root)
    names = {n["isin"]: n.get("name", "") for n in scope.get("names", [])}
    nodes, facts = facts_and_nodes(root, asof, scope)
    fl_ev, fl_un, fl_st = filing_events(root, asof, since, set(names), cache, names)
    nw_ev, nw_un, nw_st = news_events(root, asof, since, scope, cache) if with_news else ([], [], {"news_rows": 0})
    you_ev, _, you_st = you.events(root, asof, scope)      # S85: what he sent (source "you"), usable from the moment it was received
    known = {n["isin"] for n in nodes}
    m = scrip_map(root)
    for e in fl_ev + nw_ev + you_ev:                          # an event's ISIN that is not in scope (an older ISIN of a scope scrip) still needs its node
        if e["isin"] not in known:
            r = m[m["isin"] == e["isin"]].head(1)
            nodes.append({"isin": e["isin"], "name": (r["company"].iloc[0] if len(r) else "") or "", "symbol": "", "origin": "event_isin",
                          "source": "bse_scrip_isin", "as_of": (r["vf"].iloc[0] if len(r) else asof)})
            known.add(e["isin"])
    nodes_df = _frame(nodes, NODE_COLS, KEYS["node"])
    facts = [f for f in facts if f["known_from"] <= asof]
    out = {"node": nodes_df, "fact": _frame(facts, FACT_COLS, KEYS["fact"]),
           "relation": _frame(relations(nodes, facts, groups if groups is not None else groups_config()), REL_COLS, KEYS["relation"]),
           "event": _frame(fl_ev + nw_ev + you_ev, EVENT_COLS, KEYS["event"]), "unlinked": _frame(fl_un + nw_un, UNLINKED_COLS, KEYS["unlinked"])}
    out["stats"] = {**fl_st, **nw_st, **you_st, **{k: int(len(v)) for k, v in out.items() if k in TABLES}}
    return out


def canonical_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, float_format="%.10g", lineterminator="\n").encode("utf-8")


def hash_tables(g: dict) -> Dict[str, str]:
    return {k: hashlib.sha256(canonical_csv(g[k])).hexdigest() for k in TABLES}


def write(g: dict, out_dir: Path) -> Dict[str, str]:
    """Parquet files, deterministic (fixed options, sorted rows); returns the SHA-256 of each file's bytes."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    h = {}
    for k in TABLES:
        p = out_dir / f"{k}.parquet"
        g[k].to_parquet(p, index=False, compression="zstd", row_group_size=100000)
        h[k] = hashlib.sha256(p.read_bytes()).hexdigest()
    return h


def load_store(con, g: dict, asof: date, now: Optional[datetime] = None) -> dict:
    """Replace the store's kg2 tables with this build (one transaction)."""
    now = now or datetime.now()
    from pflab.pm import store
    with store.transaction(con):
        for t in ("kg2_node", "kg2_fact", "kg2_relation", "kg2_event", "kg2_unlinked"):
            con.execute(f"DELETE FROM {t}")
        for key, table in (("node", "kg2_node"), ("fact", "kg2_fact"), ("relation", "kg2_relation"), ("event", "kg2_event"), ("unlinked", "kg2_unlinked")):
            df = g[key]
            if len(df):
                con.register("_kg2_df", df)
                con.execute(f"INSERT INTO {table} ({', '.join(df.columns)}) SELECT {', '.join(df.columns)} FROM _kg2_df")
                con.unregister("_kg2_df")
        h = hash_tables(g)
        con.execute("DELETE FROM kg2_build WHERE built_on=? AND as_of_day=?", [now.date(), asof])
        con.execute("INSERT INTO kg2_build VALUES (?,?,?,?,?,?)", [now.date(), now, asof, None, json.dumps(h, sort_keys=True), json.dumps(g["stats"], sort_keys=True)])
    return h
