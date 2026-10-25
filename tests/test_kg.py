"""S38 knowledge graph: time-aware edges, timeline, GKG parsing, robots-respecting text fetch, guard additions.
SYNTHETIC data throughout."""
import io
import zipfile
from datetime import date, datetime

import pandas as pd
import pytest

from pflab.data import gdelt_gkg as gk
from pflab.kg import build as kb
from pflab.kg import graph as g
from pflab.kg import text as kt
from pflab.llm import guard
from pflab.pm import store


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


def test_state_edges_close_instead_of_overwriting(con):
    g.edge(con, "company:A", "guard_status", "verdict:ok", datetime(2026, 9, 1), "test")
    g.edge(con, "company:A", "guard_status", "verdict:ok", datetime(2026, 9, 5), "test")      # same state: no-op
    g.edge(con, "company:A", "guard_status", "verdict:fail", datetime(2026, 10, 1), "test")
    assert g.as_of(con, "company:A", "guard_status", datetime(2026, 9, 15)) == ["verdict:ok"]
    assert g.as_of(con, "company:A", "guard_status", datetime(2026, 10, 2)) == ["verdict:fail"]
    assert con.execute("SELECT count(*) FROM kg_edges").fetchone()[0] == 2


def test_ownership_periods_and_timeline(con):
    g.edge(con, kb.ME, "owns", "company:A", date(2026, 6, 1), "ledger")
    g.edge(con, kb.ME, "owns", "company:B", date(2026, 6, 1), "ledger")
    g.close(con, kb.ME, "owns", "company:A", date(2026, 8, 1))
    assert g.as_of(con, kb.ME, "owns", datetime(2026, 7, 1)) == ["company:A", "company:B"]
    assert g.as_of(con, kb.ME, "owns", datetime(2026, 9, 1)) == ["company:B"]
    d1 = g.doc(con, "filing", "k1", datetime(2026, 10, 1, 10), "Board meeting", source="BSE")
    d2 = g.doc(con, "article", "https://x.in/a", datetime(2026, 10, 5, 9), "Plant news", "https://x.in/a", "x.in", -2.0)
    g.edge(con, d1, "about", "company:B", datetime(2026, 10, 1, 10), "bse")
    g.edge(con, d2, "mentions", "company:B", datetime(2026, 10, 5, 9), "gdelt")
    tl = g.timeline(con, "company:B", date(2026, 9, 1))
    assert list(tl["kind"]) == ["article", "filing"]
    assert g.timeline(con, "company:B", date(2026, 9, 1), until=datetime(2026, 10, 2)).shape[0] == 1   # point in time


def _gkg_zip(rows):
    lines = []
    for r in rows:
        cols = [""] * 27
        cols[1], cols[3], cols[4], cols[7], cols[9], cols[13], cols[15], cols[23] = r
        lines.append("\t".join(cols))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.gkg.csv", "\n".join(lines))
    return buf.getvalue()


def test_gkg_rows_are_kept_only_when_a_company_is_named():
    raw = _gkg_zip([
        ("20261014120000", "a.in", "https://a.in/1", "ECON_STOCKMARKET;ENV_SOLAR", "1#India#IN#IN#", "greenwatt energy;sebi", "-1.5,2,3", "Greenwatt Energy,10"),
        ("20261014120000", "b.com", "https://b.com/2", "SPORTS", "1#United States#US#US#", "some club", "3.0,1,1", "Some Club,5"),
        ("20261014120000", "c.in", "https://c.in/3", "ECON", "", "", "0.5,1,1", "Greenfield Adani Greenery,4")])
    rx = gk.compile_aliases({"INE999E01013": ["greenwatt energy"], "INE000X01011": []})
    df = gk.parse(raw, rx)
    assert list(df["url"]) == ["https://a.in/1"] and df["isins"].iloc[0] == "INE999E01013"
    assert df["tone"].iloc[0] == -1.5 and bool(df["india"].iloc[0]) and "ENV_SOLAR" in df["themes"].iloc[0]


def test_text_fetch_respects_robots_and_records_status(con, tmp_path):
    g.doc(con, "article", "https://ok.in/a", datetime(2026, 10, 5), "a", "https://ok.in/a", "ok.in")
    g.doc(con, "article", "https://no.in/b", datetime(2026, 10, 4), "b", "https://no.in/b", "no.in")
    robots = kt.Robots(lambda u: "User-agent: *\nDisallow: /" if "no.in" in u else "")

    class R:
        status_code = 200
        text = "<html><body><article><p>" + "Adani Green commissioned a solar plant in Gujarat. " * 20 + "</p></article></body></html>"
    st = kt.fetch_texts(con, tmp_path / "text", robots=robots, get=lambda u: R(), spacing=0)
    assert st == {"ok": 1, "robots_disallow": 1}
    path = con.execute("SELECT text_path FROM kg_docs WHERE text_status='ok'").fetchone()[0]
    assert "solar plant" in open(path, encoding="utf-8").read()


def test_guard_accepts_numbers_from_the_cited_source_only_when_allowed():
    src = {"S1": "2026-10-14 article (x.in): GQG sold Adani stake worth over Rs 21,000 crore"}
    txt = "GQG sold a stake worth Rs 21000 crore on October 14, 2026 [S1]."
    assert not guard.check_all(txt, {}, src).ok
    assert guard.check_all(txt, {}, src, allow_cited_source_numbers=True).ok
    other = "GQG sold a stake worth Rs 21000 crore [S1]. The plant cost Rs 500 crore [S1]."
    assert not guard.check_all(other, {}, src, allow_cited_source_numbers=True).ok   # 500 is not in S1


def test_a_date_must_be_a_real_date_not_scattered_numbers():
    facts = {"documents": 6, "year": 2026}
    assert not guard.check_all("It happened on October 6, 2026 [F:documents].", facts, {}).ok
    assert guard.check_all("It happened on October 6, 2026 [F:d].", {"d": date(2026, 10, 6)}, {}).ok


def test_context_results_are_point_in_time_and_bases_never_mix(con):
    cid = "company:INE000Q01011"
    g.node(con, cid, "company", "Qqq Limited", {"symbol": "QQQ"})
    for qe, pub, basis, np_ in (("2026-03-31", datetime(2026, 5, 10), "standalone", 10.0),
                                ("2026-03-31", datetime(2026, 5, 10), "consolidated", 30.0),
                                ("2026-06-30", datetime(2026, 8, 5), "standalone", 12.0)):
        d = g.doc(con, "result", f"{qe}|{basis}", pub, f"{'Consolidated results' if basis == 'consolidated' else 'Results'}"
                  f" for quarter ended {qe}: net profit {np_} mn", source="BSE",
                  attrs={"net_profit": np_, "basis": basis, "quarter_end": qe})
        g.edge(con, d, "about", cid, pub, "quarterly_results")
    facts, _ = kb.context(con, ["QQQ"], date(2026, 7, 1), stock_list=[])
    assert facts["QQQ.q1.quarter_end"] == date(2026, 3, 31) and "QQQ.q2.quarter_end" not in facts   # June: not yet filed
    assert facts["QQQ.q1.net_profit"] == (10.0, "million") and facts["QQQ.q1.net_profit_consolidated"] == (30.0, "million")
