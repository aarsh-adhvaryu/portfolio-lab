"""S81 B7: the rebuilt knowledge graph (kg2): three layers, linking rules, the closed list, the audit, determinism, the scope file, the position layer and the
news collector. Everything is synthetic (rule 7): no real name, holding or amount."""
import json
import threading
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from pflab.kg import events as kev
from pflab.kg2 import audit, build as kb, classify, job, news, position, scope as sc, switch
from pflab.pm import store

ASOF = date(2026, 6, 30)
A, B_NEW, B_OLD, D = "INE000A01011", "INE000B01029", "INE000B01011", "INE000D01019"
C, E = "INE000C01017", "INE000E01015"


def _w(root, rel, df):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p)


def _filing(scrip, head, dissem, company="X Ltd", cat="Company Update", sub="", news_dt=None):
    return {"scrip_code": scrip, "company": company, "headline": head, "category": cat, "subcategory": sub,
            "news_dt": news_dt or dissem, "dissem_dt": dissem, "attachment": f"{abs(hash((scrip, head, str(dissem)))) % 10**8}.pdf", "news_sub": ""}


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "data"
    names = [("Alpha Industries Limited", "ALPHA", A, "2026-06-01"), ("Beta Finance Limited", "BETA", B_NEW, "2026-06-01"),
             ("Tata Gamma Limited", "GAMMA", C, "2026-06-01"), ("Tata Delta Limited", "DELTA", D, "2026-06-01")]
    _w(r, "index_membership/name_map.parquet", pd.DataFrame(
        [{"norm_name": n.lower(), "name": n, "symbol": s, "isin": i, "source": "equity_master", "first_seen": date(2010, 1, 1), "last_seen": date.fromisoformat(ls)}
         for n, s, i, ls in names]))
    _w(r, "index_membership/sector_map.parquet", pd.DataFrame(
        [{"capture_date": "2026-05-01", "index": "NIFTY500", "isin": i, "issuer": i[:9], "industry": ind, "taxonomy": "A"}
         for i, ind in [(A, "STEEL"), (B_NEW, "FINANCE"), (C, "STEEL"), (D, "FINANCE")]]))
    _w(r, "index_membership/NIFTY500.parquet", pd.DataFrame(
        [{"index": "NIFTY500", "isin": i, "symbol": s, "from_date": "2020-01-01", "to_date": None, "from_source": "x", "to_source": None, "from_date_latest": "2020-01-01"}
         for _, s, i, _ in names]))
    _w(r, "panel/prices.parquet", pd.DataFrame(
        [{"date": d, "isin": i, "close": c, "volume": 100} for i in (A, B_NEW, C, D) for d, c in (("2026-06-26", 10.0), ("2026-06-29", 11.0), ("2026-07-02", 99.0))]))
    _w(r, "panel/listing_dates.parquet", pd.DataFrame({"first_trade": ["2010-01-01"] * 3}, index=pd.Index([A, B_NEW, C], name="isin")))
    far = pd.Timestamp("2999-12-31")
    _w(r, "bse_scrip_isin/map.parquet", pd.DataFrame([
        {"scrip_code": "500001", "isin": A, "valid_from": pd.Timestamp("1990-01-01"), "valid_to": far, "company": "Alpha Industries Ltd", "in_panel": True},
        {"scrip_code": "500002", "isin": B_OLD, "valid_from": pd.Timestamp("1990-01-01"), "valid_to": pd.Timestamp("2026-03-14"), "company": "Beta Finance Ltd", "in_panel": True},
        {"scrip_code": "500002", "isin": B_NEW, "valid_from": pd.Timestamp("2026-03-15"), "valid_to": far, "company": "Beta Finance Ltd", "in_panel": True},
        {"scrip_code": "500003", "isin": "", "valid_from": pd.Timestamp("1990-01-01"), "valid_to": far, "company": "Tata Gamma Ltd", "in_panel": True},
        {"scrip_code": "500004", "isin": D, "valid_from": pd.Timestamp("2026-05-01"), "valid_to": far, "company": "Tata Delta Ltd", "in_panel": True},
    ]).assign(status="Active", first_seen=pd.Timestamp("2020-01-01"), last_seen=pd.Timestamp("2026-06-01"), n_announcements=1, source="t", isin_role="current"))
    rows10 = [
        _filing("500001", "Outcome of Board Meeting: financial results for the quarter ended 31 March", pd.Timestamp("2026-06-10 10:00")),
        _filing("500001", "Resignation of Statutory Auditors of the Company", pd.Timestamp("2026-06-10 11:00")),
        _filing("500001", "Resignation of Statutory Auditors of the Company", pd.Timestamp("2026-06-10 11:00")),          # exact duplicate
        _filing("500001", "Some filing with no dissemination time", pd.NaT, news_dt=pd.Timestamp("2026-06-10 12:00")),
        _filing("500004", "Trading window closure", pd.Timestamp("2026-04-10 09:00")),                                    # before its ISIN's validity
    ]
    rows11 = [_filing("500002", "Intimation of dividend record date", pd.Timestamp("2026-06-11 10:00")),
              _filing("500002", "Cancellation of order worth crore by customer", pd.Timestamp("2026-03-10 10:00"))]
    rows10 += [_filing("500001", f"Routine intimation number {k} to the exchange", pd.Timestamp("2026-06-10 13:00") + pd.Timedelta(minutes=k)) for k in range(30)]
    rows_after = [_filing("500001", "Receives order worth crore", pd.Timestamp("2026-07-05 10:00"))]
    for d, rows in (("2026-06-10", rows10), ("2026-06-11", rows11), ("2026-07-05", rows_after)):
        _w(r, f"bse_announcements/2026/{d}.parquet", pd.DataFrame(rows))
    # results: quarter id 140 is Jun 2026?  (Jun-2000 = 26, +4 per year) -> 26 + 26*4 = 130 is Jun 2026; 129 = Mar 2026 (known from 29 May); 130 not yet known at ASOF
    _w(r, "bse_results/500001.parquet", pd.DataFrame(
        [{"scrip_code": "500001", "qtr": q, "fld_type": "1", "fld_desc": d, "Value": v, "Header": "2", "Fld_SequenceID": "0"}
         for q, v in ((129.0, "100.0"), (130.0, "999.0")) for d in ("Net Sales/Revenue From Operations",)]))
    # news
    nrows = [
        {"date": "2026-06-20", "url": "https://n.example/alpha-industries-wins-big", "source": "n.example", "isin": A, "org": "alpha industries", "tone": 1.0, "themes": "", "india": True, "numarts": 1},
        {"date": "2026-06-20", "url": "https://n.example/story-with-text", "source": "n.example", "isin": A, "org": "alpha industries", "tone": -1.0, "themes": "", "india": True, "numarts": 1},
        {"date": "2026-06-20", "url": "https://n.example/other-text", "source": "n.example", "isin": A, "org": "alpha industries", "tone": 0.0, "themes": "", "india": True, "numarts": 1},
        {"date": "2026-06-20", "url": "https://n.example/unrelated", "source": "n.example", "isin": A, "org": "alpha industries", "tone": 0.0, "themes": "", "india": True, "numarts": 1},
        {"date": "2026-06-20", "url": "https://n.example/mismatch", "source": "n.example", "isin": A, "org": "alpha holdings", "tone": 0.0, "themes": "", "india": True, "numarts": 1},
        {"date": "2026-06-30", "url": "https://n.example/alpha-industries-today", "source": "n.example", "isin": A, "org": "alpha industries", "tone": 0.0, "themes": "", "india": True, "numarts": 1},
    ]
    _w(r, "news_s81/gkg1/2026-06-20.parquet", pd.DataFrame(nrows[:5]))
    _w(r, "news_s81/gkg1/2026-06-30.parquet", pd.DataFrame(nrows[5:]))
    for url, title, text in (("https://n.example/story-with-text", "Fraud probe at Alpha Industries", "Alpha Industries said an investigation ... " * 10),
                             ("https://n.example/other-text", "Market wrap", "Stocks rose today. " * 30)):
        p = news.text_path(r, news.url_hash(url))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"url": url, "title": title, "text": text}), encoding="utf-8")
    scope = {"version": 1, "built": "2026-06-01", "extra_isins": [], "names": [
        {"isin": A, "symbol": "ALPHA", "name": "Alpha Industries Limited", "aliases": ["alpha industries"], "text": True, "origin": "stock_list"},
        {"isin": B_NEW, "symbol": "BETA", "name": "Beta Finance Limited", "aliases": ["beta finance"], "text": False, "origin": "nifty500"},
        {"isin": C, "symbol": "GAMMA", "name": "Tata Gamma Limited", "aliases": ["tata gamma"], "text": False, "origin": "nifty500"},
        {"isin": D, "symbol": "DELTA", "name": "Tata Delta Limited", "aliases": ["tata delta"], "text": False, "origin": "nifty500"}]}
    (r / "kg").mkdir(parents=True, exist_ok=True)
    (r / "kg" / "scope.json").write_text(json.dumps(scope), encoding="utf-8")
    return r


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


GROUPS = {"tata": ["tata"]}


def G(root, **kw):
    return kb.build(root, ASOF, groups=GROUPS, **kw)


# ------------------------------------------------------------------ the three layers

def test_three_layers_exist_and_every_row_has_isin_source_date(root):
    g = G(root)
    assert len(g["node"]) >= 4 and len(g["fact"]) and len(g["relation"]) and len(g["event"])
    assert audit._missing(g) == {}
    keys = set(g["fact"]["fkey"])
    assert {"industry", "index_member:NIFTY500", "last_close", "listing_date", "net_sales_as_filed"} <= keys
    assert (g["fact"]["source"].str.len() > 0).all() and g["fact"]["as_of"].notna().all()


def test_facts_are_point_in_time(root):
    g = G(root)
    f = g["fact"]
    close = f[(f["isin"] == A) & (f["fkey"] == "last_close")].iloc[0]
    assert close["value_num"] == 11.0 and close["as_of"] == date(2026, 6, 29)       # the 2026-07-02 price is after ASOF
    ns = f[(f["isin"] == A) & (f["fkey"] == "net_sales_as_filed")].iloc[0]
    assert ns["value_num"] == 100.0                                              # quarter 130 (Jun 2026) is not known by 30 June: the earlier one is
    assert (pd.to_datetime(f["known_from"]).dt.date <= ASOF).all()


def test_relations_only_by_named_rules(root):
    g = G(root)
    r = g["relation"]
    assert set(r["rule"]) <= set(kb.RELATION_RULES)
    same_ind = r[r["rule"] == "same_industry"]
    assert {(a, b) for a, b in zip(same_ind["src_isin"], same_ind["dst_isin"])} >= {tuple(sorted((A, C))), tuple(sorted((B_NEW, D)))}
    grp = r[r["rule"] == "same_group_prefix"]
    assert [(a, b, d) for a, b, d in zip(grp["src_isin"], grp["dst_isin"], grp["detail"])] == [(C, D, "tata")]
    assert (r["source"].str.len() > 0).all()


# ------------------------------------------------------------------ events: confident-rule linking and the unlinked remainder

def test_filing_without_dissemination_time_is_left_out_of_everything(root):
    g = G(root)
    assert g["stats"]["no_dissem_time"] == 1
    assert not g["event"]["headline"].str.contains("no dissemination time").any()
    assert not g["unlinked"]["ref"].astype(str).str.contains("no dissemination").any() and len(g["unlinked"]) >= 1


def test_filing_links_by_scrip_isin_on_the_dissemination_date(root):
    ev = G(root)["event"]
    f = ev[ev["source"] == "bse_announcement"]
    old = f[f["headline"].str.contains("Cancellation")].iloc[0]
    new = f[f["headline"].str.contains("dividend")].iloc[0]
    assert old["isin"] == B_OLD and new["isin"] == B_NEW                            # the ISIN valid on each date
    assert old["link_rule"] == "filing:scrip_isin_on_dissem_date" and "valid on 2026-03-10" in old["link_proof"]
    assert old["kind"] == "large_order_loss" and new["kind"] == "dividend"


def test_unlinked_remainder_has_reasons(root):
    un = G(root)["unlinked"]
    assert "outside_isin_validity" in set(un["reason"])                             # D's filing came before its ISIN's validity
    m = kb.scrip_map(root)
    f = pd.DataFrame({"scrip_code": ["500003", "999999", "500001"], "day": [date(2026, 6, 1)] * 3})
    lk = kb.link_scrips(f, m)
    assert list(lk["why"][:2]) == ["blank_isin", "no_scrip_map"] and lk["isin"].iloc[2] == A


def test_no_event_after_the_day_and_duplicates_removed(root):
    ev = G(root)["event"]
    assert (pd.to_datetime(ev["ts"]).dt.date <= ASOF).all()
    assert not ev["headline"].str.contains("Receives order").any()                  # filed 2026-07-05
    a = ev[(ev["isin"] == A) & (ev["source"] == "bse_announcement")]
    assert a["headline"].str.contains("Resignation").sum() == 1                      # the exact duplicate is one event
    assert a[a["headline"].str.contains("Resignation")].iloc[0]["kind"] == "auditor_resignation"


def test_news_links_only_when_tag_and_name_agree(root):
    g = G(root)
    ev = g["event"]
    nw = ev[ev["source"] == "gdelt_gkg1"]
    assert set(nw["ref"]) == {"https://n.example/alpha-industries-wins-big", "https://n.example/story-with-text"}
    rules = dict(zip(nw["ref"], nw["link_rule"]))
    assert rules["https://n.example/story-with-text"] == "news:org_exact+text_name" and rules["https://n.example/alpha-industries-wins-big"] == "news:org_exact+url_slug"
    assert nw[nw["ref"].str.contains("story-with-text")].iloc[0]["kind"] == "fraud_investigation"      # the text's title, by rule
    un = g["unlinked"]
    reasons = dict(zip(un[un["source"] == "gdelt_gkg1"]["ref"], un[un["source"] == "gdelt_gkg1"]["reason"]))
    assert reasons["https://n.example/other-text"] == "text_lacks_name" and reasons["https://n.example/unrelated"] == "text_pending"
    assert reasons["https://n.example/mismatch"] == "tag_org_disagree"
    assert not nw["ref"].str.contains("today").any()                                 # an article of the day itself is usable only from the next day


# ------------------------------------------------------------------ the closed list

def test_closed_list_rules_and_validator():
    assert classify.rule_kind("Intimation of downgrade of credit rating by agency")[0] == "rating_downgrade"
    assert classify.rule_kind("Pledge invoked by lender on promoter shares")[0] == "promoter_pledge_increase"
    assert classify.rule_kind("Show cause notice received from SEBI")[0] == "regulatory_action"
    assert classify.rule_kind("Reduction in guidance for FY27")[0] == "guidance_cut"
    assert classify.rule_kind("Zzz", "Board Meeting")[0] == "board_meeting" and classify.rule_kind("Zzz")[0] == "other"
    assert set(classify.THESIS_BREAK_KINDS) == {"results_miss", "guidance_cut", "auditor_resignation", "promoter_pledge_increase", "regulatory_action", "rating_downgrade",
                                                "fraud_investigation", "large_order_loss"}
    assert classify.validate({"kind": "made_up", "severity": "high"}) and classify.validate({"kind": "none", "severity": "huge"})
    assert classify.validate({"kind": "none", "severity": "low"}) is None


def test_model_only_picks_from_the_list_and_code_validates():
    class R:
        def __init__(self, text):
            self.text = text
    calls = []

    def chat(model, msgs, **kw):
        calls.append(1)
        return R(json.dumps({"kind": "bribery", "severity": "high"}) if len(calls) == 1 else json.dumps({"kind": "fraud_investigation", "severity": "high"}))
    got = classify.model_classify("Raid at company premises", chat=chat)
    assert got == {"kind": "fraud_investigation", "severity": "high"} and len(calls) == 2         # the first answer was off-list: one retry
    assert classify.model_classify("x", chat=lambda *a, **k: R("not json")) is None                # no valid answer: the rule's answer stays
    assert classify.final_kind(("other", "low"), {"kind": "none", "severity": "high"}) == ("other", "low", "model")
    assert classify.final_kind(("rating_downgrade", "high"), {"kind": "none", "severity": "low"}) == ("rating_downgrade", "high", "rule")


def test_classify_pending_caches_and_the_build_reads_the_cache(root):
    class R:
        def __init__(self, text):
            self.text = text
    g = G(root)
    target = g["event"][g["event"]["kind"] == "news"]
    assert len(target) == 1                                                       # the slug-linked article has no rule kind
    out = job.classify_pending(root, g, limit=5, chat=lambda *a, **k: R(json.dumps({"kind": "regulatory_action", "severity": "medium"})))
    assert out["classified"] >= 1
    g2 = G(root)
    assert "regulatory_action" in set(g2["event"]["kind"])
    cache = classify.load_cache(root)
    assert all(v["kind"] in classify.KINDS and v["severity"] in classify.SEVERITIES for v in cache.values())


# ------------------------------------------------------------------ determinism

def test_rebuild_is_identical_byte_for_byte(root, tmp_path):
    h1, h2 = kb.hash_tables(G(root)), kb.hash_tables(G(root))
    assert h1 == h2
    f1 = kb.write(G(root), tmp_path / "o1")
    f2 = kb.write(G(root), tmp_path / "o2")
    assert f1 == f2 and all(len(v) == 64 for v in f1.values())


# ------------------------------------------------------------------ the audit

def _audit(con, root, g=None, **kw):
    return audit.run_audit(con, root, ASOF, graph=g if g is not None else G(root), **kw)


def _by(res):
    return {c["name"]: c for c in res["checks"]}


def test_audit_passes_on_a_good_graph_and_writes_the_sample(root, con):
    res = _audit(con, root)
    c = _by(res)
    assert res["passed"], [x for x in res["checks"] if x["gating"] and not x["passed"]]
    assert c["filing_link_rate"]["value"] >= 0.95 and c["duplicates"]["value"] < 0.01 and c["rebuild_identical"]["value"] is True
    sample = pd.read_csv(root / "kg" / "audit_sample.csv")
    assert 0 < len(sample) <= 50 and {"link_rule", "link_proof", "headline"} <= set(sample.columns)
    assert con.execute("SELECT passed FROM kg2_audit WHERE day=?", [ASOF]).fetchone()[0] is True


def test_audit_fails_on_a_missing_source(root, con):
    g = G(root)
    g["fact"].loc[0, "source"] = None
    res = _audit(con, root, g)
    assert not res["passed"] and not _by(res)["every_row_has_isin_source_date"]["passed"]


def test_audit_fails_on_a_point_in_time_violation(root, con):
    g = G(root)
    g["event"].loc[0, "ts"] = datetime(2026, 7, 5, 10, 0)
    g["event"].loc[0, "event_date"] = date(2026, 7, 5)
    res = _audit(con, root, g)
    assert not _by(res)["point_in_time"]["passed"] and not res["passed"]


def test_audit_fails_when_filings_do_not_link(root, con):
    far = pd.Timestamp("2999-12-31")
    m = pd.read_parquet(root / "bse_scrip_isin" / "map.parquet")
    m.loc[m["scrip_code"] == "500001", "valid_from"] = pd.Timestamp("2030-01-01")        # nothing of A links on its date any more
    m.to_parquet(root / "bse_scrip_isin" / "map.parquet")
    res = _audit(con, root, G(root))
    c = _by(res)["filing_link_rate"]
    assert not c["passed"] and c["value"] < 0.95 and not res["passed"]


def test_audit_fails_on_duplicates(root, con):
    g = G(root)
    dup = pd.concat([g["event"]] + [g["event"].iloc[[0]]] * 3, ignore_index=True)
    g["event"] = dup
    res = _audit(con, root, g)
    assert not _by(res)["duplicates"]["passed"] and _by(res)["duplicates"]["value"] >= 0.01


def test_audit_fails_on_an_off_list_kind_or_rule(root, con):
    g = G(root)
    g["event"].loc[0, "kind"] = "model_made_this_up"
    assert not _by(_audit(con, root, g))["closed_lists"]["passed"]
    g = G(root)
    g["relation"].loc[0, "rule"] = "model_said_so"
    assert not _by(_audit(con, root, g))["closed_lists"]["passed"]


def test_audit_fails_when_the_rebuild_differs(root, con, monkeypatch):
    real, n = kb.build, [0]

    def drifting(*a, **k):
        g = real(*a, **k)
        n[0] += 1
        if n[0] > 1:
            g["event"] = g["event"].iloc[:-1]
        return g
    g = G(root)
    monkeypatch.setattr(kb, "build", drifting)
    res = _audit(con, root, g)
    assert not _by(res)["rebuild_identical"]["passed"] and not res["passed"]


def test_audit_fails_on_news_tag_disagreement(root, con):
    g = G(root)
    assert _by(_audit(con, root, g))["news_tag_agreement"]["passed"]
    i = g["event"].index[g["event"]["source"] == "gdelt_gkg1"][0]
    g["event"].loc[i, "link_proof"] = "org token 'somebody else' = alias of x; 'x' is in the text"         # a linked article whose tag and name disagree
    assert not _by(_audit(con, root, g))["news_tag_agreement"]["passed"]


# ------------------------------------------------------------------ store, switch, material events

def test_job_loads_the_store_only_when_audit_passes_and_switch_on(root, con, monkeypatch):
    monkeypatch.setenv("PFLAB_KG2", "off")
    out = job.run(con, root, ASOF)
    assert out["passed"] and not out["loaded"] and con.execute("SELECT count(*) FROM kg2_event").fetchone()[0] == 0
    monkeypatch.setenv("PFLAB_KG2", "on")
    out = job.run(con, root, ASOF)
    assert out["loaded"] and con.execute("SELECT count(*) FROM kg2_event").fetchone()[0] > 0
    assert switch.active(con, ASOF)
    assert con.execute("SELECT count(*) FROM kg2_build").fetchone()[0] == 1
    # a failing audit empties the tables again
    m = pd.read_parquet(root / "bse_scrip_isin" / "map.parquet")
    m.loc[m["scrip_code"] == "500001", "valid_from"] = pd.Timestamp("2030-01-01")
    m.to_parquet(root / "bse_scrip_isin" / "map.parquet")
    out = job.run(con, root, ASOF)
    assert not out["passed"] and "filing_link_rate" in out["failed_checks"] and con.execute("SELECT count(*) FROM kg2_event").fetchone()[0] == 0


def test_default_switch_is_off():
    assert switch.CONFIG.exists() and "on = false" in switch.CONFIG.read_text(encoding="utf-8")


def test_material_events_reads_thesis_breaks(root, con, monkeypatch):
    monkeypatch.setenv("PFLAB_KG2", "on")
    job.run(con, root, ASOF)
    ev = kev.material_events(con, [A, B_NEW, B_OLD], date(2026, 6, 1))
    kinds = {e["kind"] for e in ev}
    assert "auditor_resignation" in kinds and "dividend" not in kinds and "results" not in kinds
    e = ev[0]
    assert set(e) == {"isin", "kind", "severity", "ts", "source", "ref", "text"} and isinstance(e["ts"], datetime)
    assert kev.material_events(con, [A], date(2026, 6, 11)) == [e2 for e2 in ev if e2["isin"] == A and e2["ts"] >= datetime(2026, 6, 11)]
    assert kev.material_events(con, [], date(2026, 1, 1)) == []
    assert not [e for e in ev if e["source"] == "gdelt_gkg1"]                           # a news keyword is a lead (severity low), never a thesis break by itself


# ------------------------------------------------------------------ the scope file

def test_scope_build_merge_found_and_aliases(root, tmp_path):
    (root / "_daily").mkdir()
    (root / "_daily" / "gkg_aliases.json").write_text(json.dumps({A: ["alpha industries", "alpha inds"]}), encoding="utf-8")
    pd.DataFrame([{"index": "NIFTY100", "isin": B_NEW, "symbol": "BETA", "from_date": "2020-01-01", "to_date": None, "from_source": "x", "to_source": None,
                   "from_date_latest": "2020-01-01"}]).to_parquet(root / "index_membership" / "NIFTY100.parquet")
    _w(root, "panel/symbol_isin_map.parquet", pd.DataFrame([{"symbol": "GOLDBEES", "isin": "INF000000001", "valid_from": "1990-01-01", "valid_to": "2999-12-31"}]))
    s = sc.build_scope(root, today=ASOF)
    by = {n["isin"]: n for n in s["names"]}
    assert by[A]["origin"] == "stock_list" and by[A]["text"] and "alpha inds" in by[A]["aliases"]
    assert by[B_NEW]["origin"] == "nifty100" and by[B_NEW]["text"]
    assert by["INF000000001"]["origin"] == "etf" and by[C]["origin"] == "nifty500" and not by[C]["text"]
    assert sc.load(root)["built"] == ASOF.isoformat() and sc.alias_index(s)["beta finance"] == B_NEW
    # an alias two ISINs share is dropped for both
    amb = sc.dedupe_aliases([{"isin": "I1", "aliases": ["same name", "one"]}, {"isin": "I2", "aliases": ["same name"]}])
    assert amb[0]["aliases"] == ["one"] and amb[1]["aliases"] == []
    assert sc.aliases_for("ABC") == []                                               # shorter than six characters: no alias
    # the coordinator adds held names; they get text collection
    s2 = sc.merge_held(root, [C, "INE999Z01010"], {"INE999Z01010": ["held company"]})
    by2 = {n["isin"]: n for n in s2["names"]}
    assert by2[C]["text"] and by2["INE999Z01010"]["origin"] == "held" and sc.text_isins(s2) >= {C, "INE999Z01010"}


def test_find_names_flags_unusual_volume_only_among_tag_only_names(root):
    rows = []
    for k in range(60):                                                            # a quiet history for B, then a burst in the last 30 days
        rows.append({"date": (ASOF - timedelta(days=100 - k)).isoformat(), "url": f"https://x/{k}", "source": "x", "isin": B_NEW, "org": "beta finance", "tone": 0.0,
                     "themes": "", "india": True, "numarts": 1})
    for k in range(90):
        rows.append({"date": (ASOF - timedelta(days=k % 10)).isoformat(), "url": f"https://x/burst{k}", "source": "x", "isin": B_NEW, "org": "beta finance", "tone": -3.0,
                     "themes": "", "india": True, "numarts": 1})
    _w(root, "news_s81/gkg1/2026-05-01.parquet", pd.DataFrame(rows))
    out = sc.find_names(root, today=ASOF)
    assert [o["isin"] for o in out] == [B_NEW] and out[0]["z_volume"] >= 2 and len(out) <= sc.FOUND_CAP
    assert sc.apply_found(root, out) == 1 and sc.load(root)["names"][1]["origin"] == "found"


# ------------------------------------------------------------------ the position layer

def test_position_layer_reads_the_book(con):
    day = date(2026, 6, 30)
    con.execute("INSERT INTO paper_lots VALUES (1, ?, 'ALPHA', ?, 10, 100.0, 'EQUITY', 'test')", [A, date(2025, 7, 10)])
    con.execute("INSERT INTO paper_lots VALUES (2, ?, 'ALPHA', ?, 5, 80.0, 'EQUITY', 'test')", [A, date(2024, 1, 5)])
    con.execute("INSERT INTO prices VALUES (?, ?, 120.0, 'EQ', 't', ?)", [A, date(2026, 6, 29), datetime(2026, 6, 29)])
    con.execute("INSERT INTO paper_trades (trade_id, day, isin, side, qty, price, charges, realised, detail_json) VALUES (1, ?, ?, 'sell', 1, 1, 0, 50000, ?)",
                [date(2026, 5, 4), "INE000X01011", json.dumps({"gains": {"lt_eq": 50000.0}})])
    con.execute("INSERT INTO storylines_s80 (storyline_id, market, claim, kind, direction, subject, opened_on, status, prior) VALUES (1,'IN','Alpha benefits from a falling input cost over the quarter','market',1,'NIFTY500_TRI',?, 'open', 0.5)", [date(2026, 6, 1)])
    con.execute("INSERT INTO storyline_exposure_s80 VALUES (1, ?, 0.6, 'test', ?)", [A, date(2026, 6, 1)])
    p = position.positions(con, day)
    h = p["holdings"][0]
    assert h["qty"] == 15 and h["cost"] == pytest.approx(1400.0) and h["value"] == pytest.approx(1800.0) and h["unrealised"] == pytest.approx(400.0)
    young = [l for l in h["lots"] if l["lot_id"] == 1][0]
    assert not young["long_term"] and young["days_to_long_term"] == (date(2026, 7, 11) - day).days and h["days_to_next_long_term"] == young["days_to_long_term"]
    old = [l for l in h["lots"] if l["lot_id"] == 2][0]
    assert old["long_term"] and old["days_to_long_term"] == 0 and h["unrealised_long_term"] == pytest.approx(200.0) and h["unrealised_short_term"] == pytest.approx(200.0)
    ex = p["exemption"]
    assert ex["fy"] == 2027 and ex["used"] == 50000.0 and ex["left"] == ex["limit"] - 50000.0 and ex["limit"] > 0
    assert h["exit_plan"] is None and h["storylines"][0]["storyline_id"] == 1 and h["events"] == []


def test_position_layer_shows_the_exit_plan_and_events_when_they_exist(con):
    day = date(2026, 6, 30)
    con.execute("INSERT INTO paper_lots VALUES (1, ?, 'ALPHA', ?, 10, 100.0, 'EQUITY', 'test')", [A, date(2025, 1, 10)])
    con.execute("CREATE TABLE exit_plans_s81 (plan_id INTEGER, isin VARCHAR, status VARCHAR, stop DOUBLE, opened DATE)")
    con.execute("INSERT INTO exit_plans_s81 VALUES (1, ?, 'open', 90.0, ?)", [A, date(2025, 1, 10)])
    con.execute("INSERT INTO kg2_event VALUES ('e1', ?, 'bse_announcement', 'r', ?, ?, 'regulatory_action', 'high', 'Show cause notice', 'filing:scrip_isin_on_dissem_date', 'p', 'k')",
                [A, datetime(2026, 6, 20, 10), date(2026, 6, 20)])
    h = position.positions(con, day)["holdings"][0]
    assert h["exit_plan"]["stop"] == 90.0 and h["events"][0]["kind"] == "regulatory_action"
    assert position.positions(con, date(2024, 1, 1))["holdings"] == []                # nothing was held yet


# ------------------------------------------------------------------ the news collector

def _gkg1_zip(path: Path, rows):
    cols = ["DATE", "NUMARTS", "COUNTS", "THEMES", "LOCATIONS", "PERSONS", "ORGANIZATIONS", "TONE", "CAMEOEVENTIDS", "SOURCES", "SOURCEURLS"]
    df = pd.DataFrame([{**{c: "" for c in cols}, **r} for r in rows], columns=cols)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("x.gkg.csv", df.to_csv(sep="\t", index=False, quoting=3, escapechar="\\"))


def test_parse_keeps_only_exact_organisation_tokens(tmp_path):
    z = tmp_path / "d.zip"
    _gkg1_zip(z, [{"ORGANIZATIONS": "alpha industries;someone else", "SOURCES": "n.example", "SOURCEURLS": "https://n.example/a<UDIV>https://n.example/b", "TONE": "-2.5,1,3", "LOCATIONS": "1#India#IN#IN#1#1#IN", "NUMARTS": "2"},
                  {"ORGANIZATIONS": "alpha industries foundation", "SOURCES": "n.example", "SOURCEURLS": "https://n.example/c", "TONE": "0", "NUMARTS": "1"},
                  {"ORGANIZATIONS": "", "SOURCEURLS": "https://n.example/d", "NUMARTS": "1"}])
    df = news.parse_gkg1(z, date(2026, 6, 1), {"alpha industries": A})
    assert list(df["url"]) == ["https://n.example/a", "https://n.example/b"] and set(df["isin"]) == {A} and df["india"].all() and df["tone"].iloc[0] == -2.5


def test_collector_is_resumable_polite_and_stops_cleanly(root, tmp_path):
    import shutil
    shutil.rmtree(root / "news_s81")
    n_dl = []

    def dl(session, day, tmp):
        n_dl.append(day)
        z = Path(tmp) / f"{day.isoformat()}.zip.part"
        Path(tmp).mkdir(parents=True, exist_ok=True)
        _gkg1_zip(z, [{"ORGANIZATIONS": "alpha industries", "SOURCES": "n.example", "SOURCEURLS": f"https://n.example/alpha-industries-{day.day}", "TONE": "1", "NUMARTS": "1"}])
        return z

    fetched = []

    def fetch(r, session, pol, h, url):
        fetched.append(url)
        return "ok", 10
    out = news.run(root, days_back=3, today=date(2026, 7, 10), dl=dl, fetch=fetch, text_threads=2, day_workers=1)
    assert out["results"]["done"] == 3 and len(n_dl) == 3 and sorted(fetched) == sorted(f"https://n.example/alpha-industries-{d}" for d in (9, 8, 7))
    assert (root / "news_s81" / "gkg1" / "2026-07-09.parquet").exists() and not list((root / "news_s81" / "gkg1").glob("*.tmp"))
    n_dl.clear()
    out2 = news.run(root, days_back=3, today=date(2026, 7, 10), dl=dl, fetch=fetch, text_threads=2, day_workers=1)
    assert n_dl == [] and out2["manifest"]["urls"].get("ok") == 3                          # nothing is downloaded or fetched twice
    (root / "news_s81" / "STOP").write_text("x")
    out3 = news.run(root, days_back=10, today=date(2026, 7, 10), dl=dl, fetch=fetch, text_threads=2, day_workers=1)
    assert n_dl == [] and out3["results"]["done"] == 0                                    # a STOP file ends the run before the next day
    log = (root / "news_s81" / "collect.log").read_text(encoding="utf-8")
    assert "stop:" in log and "n.example" not in log                                     # counts only


def test_a_refusing_page_is_skipped_and_counted_and_robots_are_obeyed(root):
    man = news.Manifest(root)

    class Resp:
        def __init__(self, status, text=""):
            self.status_code, self.text, self.headers, self.encoding = status, text, {"Content-Type": "text/html"}, "utf-8"
    calls = []

    class Sess:
        def get(self, url, **kw):
            calls.append(url)
            if url.endswith("/robots.txt"):
                return Resp(200, "User-agent: *\nDisallow: /private/\n")
            return Resp(403)
    pol = news.Politeness(Sess(), delay=0)
    assert news.fetch_one(root, Sess(), pol, "h1", "https://s.example/private/a") == ("robots", 0)           # robots.txt says no: the page is never requested
    assert not any("/private/a" in c for c in calls)
    assert news.fetch_one(root, Sess(), pol, "h2", "https://s.example/open/a") == ("http", 0)                # refused: skipped, counted
    assert sum(1 for c in calls if c.endswith("robots.txt")) == 1                                       # robots.txt is read once per domain
    man.many("INSERT INTO urls(h,url,domain,day,isin,status) VALUES(?,?,?,?,?,?)", [("a", "u1", "d", "2026-01-01", A, "robots"), ("b", "u2", "d", "2026-01-01", A, "ok")])
    assert man.counts()["urls"] == {"robots": 1, "ok": 1}


def test_requeue_gives_new_text_scope_names_their_back_years(root):
    man = news.Manifest(root)
    s = sc.load(root)
    assert news.requeue_text(root, man, s) == 6                                           # the six articles collected for A (text scope)
    for n in s["names"]:
        n["text"] = True
    assert news.requeue_text(root, man, s) == 0                                           # B, C, D have no rows: nothing to add; and no duplicates
    assert man.counts()["urls"] == {"pending": 6}


# ------------------------------------------------------------------ the "graph earns its place" study (measurement only)

def _story(con, sid, kind="market"):
    con.execute("INSERT INTO storylines_s80 (storyline_id, market, claim, kind, direction, subject, opened_on, status, prior) VALUES (?,'IN','x'||?,?,1,'NIFTY500_TRI',?, 'open', 0.5)",
                [sid, str(sid), kind, date(2027, 1, 1)])


def _pred(con, pid, sid, outcome, made=date(2027, 2, 1), due=date(2027, 3, 1)):
    con.execute("INSERT INTO storyline_predictions_s80 (pred_id, storyline_id, made_on, horizon_sessions, subject, expected_sign, due_on, outcome) VALUES (?,?,?,?,?,?,?,?)",
                [pid, sid, made, pid, "NIFTY500_TRI", 1, due, outcome])


def _graph_evidence(con, sid, ref="e1"):
    con.execute("INSERT INTO storyline_evidence_s80 (evidence_id, storyline_id, evidence_date, stance, text, source_kind, source_ref, strength) VALUES (?,?,?,?,?,?,?,1.0)",
                [sid * 100, sid, date(2027, 1, 15), "for", "t", "kg2_event", ref])


def test_study_is_pending_until_enough_scored_predictions_and_date(con):
    from pflab.kg2 import study
    r = study.prediction_comparison(con, date(2027, 6, 1))
    assert r["verdict"] == "pending" and r["graph"]["n"] == 0
    _story(con, 1)
    _graph_evidence(con, 1)
    for i in range(40):
        _pred(con, i + 1, 1, "good" if i % 4 else "bad")
    assert study.prediction_comparison(con, date(2027, 6, 1))["verdict"] == "pending"              # no plain arm yet
    assert study.prediction_comparison(con, date(2027, 4, 1))["verdict"] == "pending"              # not before the date even with data


def test_study_pass_and_fail_by_the_registered_rule(con):
    from pflab.kg2 import study
    _story(con, 1)
    _story(con, 2)
    _graph_evidence(con, 1)
    for i in range(40):                                                                           # graph arm: 75% hit; plain arm: 50%
        _pred(con, i + 1, 1, "good" if i % 4 else "bad")
        _pred(con, 100 + i, 2, "good" if i % 2 else "bad")
    r = study.prediction_comparison(con, date(2027, 6, 1))
    assert r["verdict"] == "pass" and r["diff"] == pytest.approx(0.25) and r["z"] >= 1.96
    con.execute("DELETE FROM storyline_predictions_s80")
    for i in range(40):                                                                           # same hit rate in both arms: fail, not pending
        _pred(con, i + 1, 1, "good" if i % 2 else "bad")
        _pred(con, 100 + i, 2, "good" if i % 2 else "bad")
    assert study.prediction_comparison(con, date(2027, 6, 1))["verdict"] == "fail"
    # evidence dated after the prediction does not put a storyline in the graph arm
    con.execute("DELETE FROM storyline_evidence_s80")
    con.execute("INSERT INTO storyline_evidence_s80 (evidence_id, storyline_id, evidence_date, stance, text, source_kind, source_ref, strength) VALUES (1,1,?, 'for','t','kg2_event','e',1.0)", [date(2027, 2, 20)])
    assert study.prediction_comparison(con, date(2027, 6, 1))["graph"]["n"] == 0


def test_study_attachment_check_rederives_the_proof(root, con):
    from pflab.kg2 import study
    res = audit.run_audit(con, root, ASOF, graph=G(root))
    assert res["passed"]
    out = study.attachment_check(con, root, ASOF)
    assert out["sample_n"] > 0 and out["sample_correct"] == out["sample_n"] and out["verdict"] == "pending"      # too few rows to conclude
    s = pd.read_csv(root / "kg" / "audit_sample.csv", dtype=str)
    s.loc[0, "link_proof"] = "scrip 500001 -> INE999999999 valid on 2026-06-10" if s.loc[0, "link_rule"].startswith("filing:") else "org token 'zzz' = alias"
    s.to_csv(root / "kg" / "audit_sample.csv", index=False)
    assert study.attachment_check(con, root, ASOF)["sample_correct"] == out["sample_n"] - 1                         # a corrupted proof is caught
