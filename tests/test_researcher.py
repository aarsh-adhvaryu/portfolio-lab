"""S44 researcher on a SYNTHETIC knowledge graph: flags found once, measured by code, briefs kept current."""
from datetime import date, datetime, timedelta

from pflab.agents import researcher as rs
from pflab.kg import graph as g
from pflab.pm import store

AAA = "INE000A01011"
LIST = [{"symbol": "AAA", "isin": AAA, "scrip": "500001"}]
ASOF = date(2026, 10, 17)
NOW = datetime(2026, 10, 17, 23, 30)


def _store(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'AAA', 'Aaa Limited', 'synthetic', now())""", [AAA])
    g.node(con, f"company:{AAA}", "company", "Aaa Limited", {"symbol": "AAA"})
    return con


def filing(con, when, title, sub, cat="Company Update"):
    d = g.doc(con, "filing", f"500001|{when}|{title}", when, title, source="BSE", attrs={"category": cat, "subcategory": sub})
    g.edge(con, d, "about", f"company:{AAA}", when, "bse_announcements", d)


def result(con, qe: date, filed: datetime, revenue, profit, basis="announcement"):
    con.execute("INSERT INTO quarterly_results (scrip_code, quarter_end, revenue, net_profit, usable_from, date_source, "
                "source, fetched_at) VALUES ('500001', ?, ?, ?, ?, ?, 'synthetic', now())", [qe, revenue, profit, filed, basis])


def article(con, when, k):
    d = g.doc(con, "article", f"https://x.in/{k}", when, f"story {k}", f"https://x.in/{k}", "x.in", -1.0)
    g.edge(con, d, "mentions", f"company:{AAA}", when, "gdelt_gkg", d)


def test_material_and_red_flag_filings_are_flagged_routine_ones_are_not(tmp_path):
    con = _store(tmp_path)
    filing(con, datetime(2026, 10, 15, 10), "Outcome of Board Meeting", "Financial Results")
    filing(con, datetime(2026, 10, 15, 11), "Copy of newspaper advertisement", "Newspaper Publication")
    filing(con, datetime(2026, 10, 16, 9), "Disclosure of default in payment of interest on NCDs", "Default")
    filing(con, datetime(2026, 9, 1, 9), "Outcome of Board Meeting", "Financial Results")          # before the window
    rep = rs.run(con, ASOF, LIST, write_briefs=False, now=NOW)
    kinds = sorted(f.kind for f in rep.new_flags)
    assert kinds == ["material_filing", "red_flag:DEFAULT"]
    assert rs.run(con, ASOF, LIST, write_briefs=False, now=NOW).new_flags == []              # never twice
    assert "default" in rep.digest() and "AAA" in rep.digest()


def test_the_adopted_tagger_is_asked_only_about_unmapped_filings(tmp_path):
    con = _store(tmp_path)
    filing(con, datetime(2026, 10, 15, 10), "Outcome of Board Meeting", "Financial Results")
    filing(con, datetime(2026, 10, 15, 11), "Copy of newspaper advertisement published in two dailies", "Newspaper Publication")
    filing(con, datetime(2026, 10, 15, 12), "Company has entered into a binding agreement to sell its cement unit", "General")
    filing(con, datetime(2026, 10, 15, 13), "Update on the annual general meeting venue and timing", "")
    filing(con, datetime(2026, 10, 15, 14), "Intimation attached", "General")                          # too short to judge
    asked = []
    tag = lambda t: (asked.append(t), "material" if "agreement" in t else "routine")[1]
    rep = rs.run(con, ASOF, LIST, write_briefs=False, now=NOW, tagger=tag)
    assert len(asked) == 2 and not any("newspaper" in t.lower() or "Board" in t for t in asked)
    model = [f for f in rep.new_flags if "model-tagged" in f.detail]
    assert len(model) == 1 and "cement" in model[0].detail and model[0].kind == "material_filing"


def test_the_digest_names_each_brief_once(tmp_path):
    con = _store(tmp_path)
    for k in (1, 2):
        con.execute("INSERT INTO briefs VALUES (?,?,?,?,?,?,?,?)", [k, AAA, "AAA", ASOF, NOW + timedelta(minutes=k), "refresh",
                                                                    k == 2, f"brief {k}"])
    filing(con, datetime(2026, 10, 17, 10), "Outcome of Board Meeting", "Financial Results")
    rs.run(con, ASOF, LIST, write_briefs=False, now=NOW)
    d = rs.digest_since(con, NOW - timedelta(hours=1))
    assert "Briefs rewritten: AAA (pflab" in d                       # once, and the newest (checked) one


def test_results_are_measured_against_the_same_quarter_a_year_earlier(tmp_path):
    con = _store(tmp_path)
    result(con, date(2025, 6, 30), datetime(2025, 8, 10, 18), 1000.0, 100.0)
    result(con, date(2026, 6, 30), datetime(2026, 10, 14, 18), 1100.0, 80.0)
    f = [x for x in rs.run(con, ASOF, LIST, write_briefs=False, now=NOW).new_flags if x.kind == "results"]
    assert len(f) == 1
    assert f[0].detail == ("results for the quarter ended 30-Jun-2026: revenue 1,100.0 mn (+10% on a year earlier); "
                           "net profit 80.0 mn (-20% on a year earlier)")
    assert rs._change("net profit", -860.0, 340.0) == "net profit -860.0 mn (a year earlier 340.0 mn)"


def test_a_guard_verdict_change_and_a_news_spike(tmp_path):
    con = _store(tmp_path)
    g.node(con, "verdict:ok", "verdict", "ok")
    g.node(con, "verdict:fail", "verdict", "fail")
    g.edge(con, f"company:{AAA}", "guard_status", "verdict:ok", datetime(2026, 10, 1, 21), "guards")
    g.edge(con, f"company:{AAA}", "guard_status", "verdict:fail", datetime(2026, 10, 16, 21), "guards")
    article(con, datetime(2026, 7, 1, 12), "history")     # news collected for more than 13 weeks
    for k in range(12):                                   # 12 weeks of 1 article a week, then 6 in the last week
        article(con, datetime(2026, 10, 9, 12) - timedelta(days=7 * k), f"old{k}")
    for k in range(6):
        article(con, datetime(2026, 10, 12 + k % 5, 12), f"new{k}")
    kinds = {f.kind: f.detail for f in rs.run(con, ASOF, LIST, write_briefs=False, now=NOW).new_flags}
    assert kinds["guard_change"] == "safety verdict ok -> fail"
    assert kinds["news_spike"].startswith("6 news articles in 7 days against a weekly average of 1.0")


def test_old_quarters_first_seen_now_and_young_news_raise_no_flags(tmp_path):
    """Real run 2026-10-17: 51 results flags for old quarters dated by first sight, and news spikes against a
    baseline that did not exist yet."""
    con = _store(tmp_path)
    result(con, date(2024, 3, 31), datetime(2026, 10, 12, 9), 900.0, 90.0)          # old quarter, filed late
    result(con, date(2026, 6, 30), datetime(2026, 10, 15, 9), 1200.0, 95.0, "first_seen")   # dated by first sight
    for k in range(8):
        article(con, datetime(2026, 10, 12 + k % 5, 12), f"n{k}")                    # collection began last week
    assert rs.run(con, ASOF, LIST, write_briefs=False, now=NOW).new_flags == []


def test_ids_survive_a_sequence_left_behind_by_a_killed_run(tmp_path):
    con = _store(tmp_path)
    filing(con, datetime(2026, 10, 15, 10), "Outcome of Board Meeting", "Financial Results")
    con.execute("INSERT INTO research_flags VALUES (1, 'X', 'X', 'k', now(), now(), 'r', 'd')")   # sequence still at 1
    assert len(rs.run(con, ASOF, LIST, write_briefs=False, now=NOW).new_flags) == 1


def test_briefs_are_written_for_flagged_or_stale_companies_only(tmp_path):
    con = _store(tmp_path)
    filing(con, datetime(2026, 10, 15, 10), "Outcome of Board Meeting", "Financial Results")
    good = lambda prompt: "The company filed its board meeting outcome [S1]."
    rep = rs.run(con, ASOF, LIST, llm=good, now=NOW)
    assert rep.briefs == {"AAA": True}
    assert rs.run(con, ASOF + timedelta(days=1), LIST, llm=good, now=NOW).briefs == {}            # nothing new, fresh
    assert rs.run(con, ASOF + timedelta(days=31), LIST, llm=good, now=NOW).briefs == {"AAA": True}   # stale
    shown = rs.show(con, "AAA", ASOF)
    assert "material_filing: Financial Results: Outcome of Board Meeting" in shown and "(checked)" in shown
