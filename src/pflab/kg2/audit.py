"""The nightly audit of the graph, as code (S81 B7). `run_audit(con, root, day) -> {"passed": bool, "checks": [...]}`.

The graph's switch turns ON only when every gating check passes. The checks, in the order of KG_AUDIT_S80.md:
  every_row_has_isin_source_date   no node, fact, relation or event row lacks an ISIN, a source or a date
  point_in_time                    no event dated after `day` (an event's own date; a filing's usable-from time `ts` may be the next trading open, never later than that),
                                   no fact known after `day`, no event without a time
  derived_time_rule                every event has a `ts_rule`; every filing whose time is DERIVED (no release time, A58) has `ts` = 09:15 IST of the first trading day after
                                   its own date (checked against the market calendar), and is never earlier than its date
  filing_link_rate                 >= 95% of the filings of LISTED names (those with a dissemination time, and, since A58, those with only a date) link to an ISIN on
                                   their date, measured on the raw files, independently of the graph; the S80 figure (84.5%) is reported beside it
  news_tag_agreement               every kept news row's ISIN tag and organisation name agree (no `tag_org_disagree`)
  duplicates                       events duplicated under (isin, headline, time) < 1%
  closed_lists                     every kind/severity is on the closed list; every relation rule is a named rule
  rebuild_identical                two rebuilds from the raw files are byte-for-byte the same tables
  sample_written                   `<data>/kg/audit_sample.csv`: 50 random links with their proof, for hand-checking
Informational (never gating): the news link share, the filings used with a derived time (A58), the unlinked reasons.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from pflab.kg2 import build as kb, classify, filing_time as ft, scope as sc, sec_8k

FILING_LINK_MIN = 0.95
DUP_MAX = 0.01
SAMPLE_N = 50
S80_MEASURED = 0.845


def _chk(name: str, passed: bool, value=None, threshold=None, note: str = "", gating: bool = True) -> dict:
    return {"name": name, "passed": bool(passed), "value": value, "threshold": threshold, "note": note, "gating": gating}


def graph_from_store(con) -> dict:
    g = {}
    for key, table in (("node", "kg2_node"), ("fact", "kg2_fact"), ("relation", "kg2_relation"), ("event", "kg2_event"), ("unlinked", "kg2_unlinked")):
        cols = kb.TABLES[key]
        g[key] = con.execute(f"SELECT {', '.join(cols)} FROM {table}").df()[cols]
    g["stats"] = {}
    return g


def raw_filing_link_rate(root: Path, day: date, days: int = 365, m: Optional[pd.DataFrame] = None) -> dict:
    """On the raw announcement files: of the filings of listed (in the NSE panel) scrips, how many link to an ISIN on their date. A filing with a dissemination time is dated by it;
    one with only a date (A58) by that date (`filing_time.filing_time`); `rate_timed_only` is the S81 figure (filings with a release time), `rate` the figure over every dated filing."""
    m = m if m is not None else kb.scrip_map(root)
    df = kb.read_filings(root, day - timedelta(days=days), day)
    if df.empty:
        return {"filings": 0, "no_dissem": 0, "with_dissem": 0, "linked": 0, "rate": None, "rate_timed_only": None, "rate_derived_only": None,
                "rate_if_no_dissem_counted": None, "reasons": {}}
    listed = set(m[m["in_panel"]]["scrip_code"])
    df = df[df["scrip_code"].isin(listed)].drop_duplicates(["scrip_code", "headline", "news_dt", "dissem_dt", "file_day"]).copy()
    n_all, no_d = int(len(df)), int(df["dissem_dt"].isna().sum())
    tr = [ft.filing_time(a, b, c) for a, b, c in zip(df["dissem_dt"], df["news_dt"], df["file_day"])]
    df["day"] = [t[2] for t in tr]
    df["derived"] = [t[1] == ft.RULE_DERIVED for t in tr]
    df = df[df["day"].notna()]
    df = df[df["day"] <= day].reset_index(drop=True)
    lk = kb.link_scrips(df, m) if len(df) else df.assign(isin=None, why=None)
    linked = int(lk["isin"].notna().sum()) if len(lk) else 0
    timed = lk[~lk["derived"]] if len(lk) else lk
    n_der = int(lk["derived"].sum()) if len(lk) else 0
    linked_timed = int(timed["isin"].notna().sum()) if len(lk) else 0
    return {"filings": n_all, "no_dissem": no_d, "with_dissem": int(len(df)), "linked": linked,
            "rate": (linked / len(df)) if len(df) else None,
            "rate_timed_only": (linked_timed / len(timed)) if len(lk) and len(timed) else None,
            "rate_derived_only": ((linked - linked_timed) / n_der) if n_der else None,
            "rate_if_no_dissem_counted": (linked / n_all) if n_all else None,
            "reasons": {k: int(v) for k, v in lk["why"].value_counts().items()} if len(lk) else {}}


def _r4(x):
    return None if x is None else round(x, 4)


def _missing(g: dict) -> Dict[str, int]:
    need = {"node": ["isin", "source", "as_of"], "fact": ["isin", "source", "as_of", "known_from"], "relation": ["src_isin", "dst_isin", "source", "as_of"],
            "event": ["isin", "source", "ts", "event_date", "link_rule", "link_proof", "ts_rule"]}
    out = {}
    for t, cols in need.items():
        df = g[t]
        for c in cols:
            bad = int((df[c].isna() | (df[c].astype(str).str.strip() == "")).sum()) if len(df) else 0
            if bad:
                out[f"{t}.{c}"] = bad
    return out


def _sample(g: dict, root: Path, day: date) -> int:
    ev = g["event"]
    n = min(SAMPLE_N, len(ev))
    out = Path(root) / "kg" / "audit_sample.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    s = ev.sample(n=n, random_state=int(day.strftime("%Y%m%d"))) if n else ev
    names = dict(zip(g["node"]["isin"], g["node"]["name"]))
    s = s.assign(name=s["isin"].map(names))[["event_id", "isin", "name", "source", "ts", "kind", "headline", "link_rule", "link_proof", "ref"]]
    s.sort_values("event_id").to_csv(out, index=False, encoding="utf-8")
    return int(len(s))


def run_audit(con, root: Path, day: date, graph: Optional[dict] = None, store: bool = True) -> dict:
    """The audit of the graph in the store (or `graph`, a build not yet loaded). Writes the sample file and, with `store`, the verdict row."""
    root = Path(root)
    g = graph if graph is not None else graph_from_store(con)
    checks: List[dict] = []
    miss = _missing(g)
    checks.append(_chk("every_row_has_isin_source_date", not miss, value=miss or 0, threshold=0, note="rows missing an ISIN, a source or a date, by column"))
    ev, fa = g["event"], g["fact"]
    derived = (ev["ts_rule"] == ft.RULE_DERIVED) if len(ev) else pd.Series([], dtype=bool)
    # a derived time is the next open after the event's own date, so it may sit after `day` (the day's own filings): the event's DATE is what may not
    is_sec = ev["source"].map(sec_8k.is_sec_source) if len(ev) else pd.Series([], dtype=bool)       # S85: a US filing may sit up to the next Indian open (`sec_8k.known_by`), no later
    limit = sec_8k.known_by(day)
    late_e = int((pd.to_datetime(ev["ts"]).dt.date[~derived & ~is_sec] > day).sum() + (pd.to_datetime(ev["ts"])[is_sec] > pd.Timestamp(limit)).sum()) if len(ev) else 0
    late_e2 = int((pd.to_datetime(ev["event_date"]).dt.date[~is_sec] > day).sum() + (pd.to_datetime(ev["event_date"]).dt.date[is_sec] > limit.date()).sum()) if len(ev) else 0
    late_f = int((pd.to_datetime(fa["known_from"]).dt.date > day).sum()) if len(fa) else 0
    no_ts = int(ev["ts"].isna().sum()) if len(ev) else 0
    checks.append(_chk("point_in_time", late_e + late_e2 + late_f + no_ts == 0, value={"events_after_day": late_e + late_e2, "facts_known_after_day": late_f, "events_without_timestamp": no_ts},
                       threshold=0, note=f"day {day.isoformat()}; {int(derived.sum())} filing(s) carry a derived time (readers hold them back until it)"))
    bad_rule = 0
    if len(ev):
        for r in ev[derived].itertuples():
            ts, ed = pd.Timestamp(r.ts).to_pydatetime(), pd.Timestamp(r.event_date).date()
            if ts != ft.next_open(ed, sec_8k.FILING_MARKET if sec_8k.is_sec_source(r.source) else "IN"):      # a US filing's derived time is the US calendar's next open (S85)
                bad_rule += 1
        bad_rule += int((~ev["ts_rule"].isin(ft.RULES)).sum())
    checks.append(_chk("derived_time_rule", bad_rule == 0, value=bad_rule, threshold=0,
                       note="every event names its time rule; a filing with no release time is used from the first trading open after its own date (09:15 IST, market calendar)"))
    fl = raw_filing_link_rate(root, day)
    rate = fl["rate"]
    checks.append(_chk("filing_link_rate", rate is not None and rate >= FILING_LINK_MIN, value=None if rate is None else round(rate, 4), threshold=FILING_LINK_MIN,
                       note=f"{fl['linked']} of {fl['with_dissem']} filings of listed scrips link on their date (A58: the {fl['no_dissem']} with no release time are dated by their "
                            f"file day and counted); with a release time only: {_r4(fl['rate_timed_only'])}; with a date only: {_r4(fl['rate_derived_only'])}; "
                            f"S80 measured {S80_MEASURED:.1%}; unlinked reasons {fl['reasons']}"))
    un = g["unlinked"]
    reasons = {k: int(v) for k, v in un["reason"].value_counts().items()} if len(un) else {}
    aliases = {n["isin"]: set(n.get("aliases", [])) for n in sc.load(root).get("names", [])}
    bad_tag = 0
    for r in ev[ev["source"] == "gdelt_gkg1"].itertuples() if len(ev) else []:
        mt = re.search(r"org token '([^']+)'", str(r.link_proof))
        if not mt or mt.group(1) not in aliases.get(r.isin, set()):
            bad_tag += 1
    checks.append(_chk("news_tag_agreement", bad_tag == 0, value=bad_tag, threshold=0,
                       note="every linked article's organisation token must equal an alias of its ISIN (rows whose alias was later dropped are unlinked: "
                            f"{reasons.get('tag_org_disagree', 0)})"))
    if len(ev):
        dup = 1.0 - ev["dedupe_key"].nunique() / len(ev)
    else:
        dup = 0.0
    checks.append(_chk("duplicates", dup < DUP_MAX, value=round(dup, 5), threshold=DUP_MAX, note="events sharing (isin, headline, time)"))
    kinds_ok = bool(ev["kind"].isin(classify.KINDS).all() and ev["severity"].isin(classify.SEVERITIES).all()) if len(ev) else True
    rel = g["relation"]
    rules_ok = bool(rel["rule"].isin(kb.RELATION_RULES).all()) if len(rel) else True
    checks.append(_chk("closed_lists", kinds_ok and rules_ok, value={"kinds_ok": kinds_ok, "relation_rules_ok": rules_ok}, threshold=True))
    ident, note = None, ""
    try:
        a, b = kb.build(root, day), kb.build(root, day)
        ha, hb = kb.hash_tables(a), kb.hash_tables(b)
        ident = ha == hb
        note = "two rebuilds from the raw files compared table by table (SHA-256 of the canonical rows)"
        if graph is not None or len(g["node"]):
            stored = kb.hash_tables({**g, "stats": {}}) if len(g["node"]) else None
            note += f"; matches the graph audited: {stored == ha if stored else 'n/a'}"
    except Exception as e:                                         # a build that cannot run is a failed check, said plainly
        note = f"rebuild failed: {type(e).__name__}: {str(e)[:160]}"
    checks.append(_chk("rebuild_identical", bool(ident), value=ident, threshold=True, note=note))
    n_s = _sample(g, root, day)
    checks.append(_chk("sample_written", n_s == min(SAMPLE_N, len(ev)), value=n_s, threshold=min(SAMPLE_N, len(ev)), note=str(root / "kg" / "audit_sample.csv")))
    n_der = int(derived.sum()) if len(ev) else 0
    checks.append(_chk("info_filings_with_derived_time", True, value=n_der, note=f"filings with a date but no release time, used from the next trading open (A58); "
                       f"{fl['no_dissem']} such rows in the raw 365-day file of listed scrips", gating=False))
    checks.append(_chk("info_unlinked_reasons", True, value=reasons, note="events no confident rule could attach (kept as counts, never shown)", gating=False))
    n_news = int((ev["source"] == "gdelt_gkg1").sum()) if len(ev) else 0
    n_news_un = int(sum(v for k, v in reasons.items() if k not in ("outside_isin_validity", "no_scrip_map", "blank_isin", "ambiguous")))
    checks.append(_chk("info_news_link_share", True, value=None if not (n_news + n_news_un) else round(n_news / (n_news + n_news_un), 4),
                       note=f"{n_news} linked, {n_news_un} unlinked (second confirmation missing); a peripheral mention is not shown by design", gating=False))
    passed = all(c["passed"] for c in checks if c["gating"])
    res = {"passed": passed, "checks": checks, "day": day.isoformat()}
    if store:
        con.execute("DELETE FROM kg2_audit WHERE day=?", [day])
        con.execute("INSERT INTO kg2_audit VALUES (?,?,?,?)", [day, passed, json.dumps(checks, sort_keys=True, default=str), datetime.now()])
    return res


def last_passed(con, day: date, max_age_days: int = 3) -> bool:
    r = con.execute("SELECT passed, day FROM kg2_audit WHERE day <= ? ORDER BY day DESC LIMIT 1", [day]).fetchone()
    return bool(r and r[0] and (day - r[1]).days <= max_age_days)
