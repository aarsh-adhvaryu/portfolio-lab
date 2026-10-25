"""S38 graph views and the stock-list workflow. SYNTHETIC data."""
from datetime import date, datetime

from pflab.kg import graph as g
from pflab.kg import viz
from pflab.plan import safety
from pflab.plan import stock_list as sl
from pflab.pm import store


def test_export_html_and_obsidian(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    g.node(con, "person:investor", "person", "The investor")
    g.node(con, "company:A", "company", "Alpha\x02 Ltd")
    g.node(con, "sector:Power", "sector", "Power")
    g.edge(con, "person:investor", "owns", "company:A", date(2026, 6, 1), "ledger")
    g.edge(con, "company:A", "in_sector", "sector:Power", date(2000, 1, 1), "instruments")
    d = g.doc(con, "filing", "k", datetime(2026, 10, 10), "Board meeting", source="BSE")
    g.edge(con, d, "about", "company:A", datetime(2026, 10, 10), "bse")
    old = g.doc(con, "filing", "k0", datetime(2025, 1, 10), "Old filing", source="BSE")
    g.edge(con, old, "about", "company:A", datetime(2025, 1, 10), "bse")
    data = viz.export(con, days=30, asof=date(2026, 10, 15))
    ids = {n["id"] for n in data["nodes"]}
    assert {"person:investor", "company:A", "sector:Power", d} <= ids and old not in ids      # old documents left out
    p = viz.html(data, tmp_path / "kg.html")
    assert "3d-force-graph@1.80.0" in p.read_text(encoding="utf-8")
    assert viz.obsidian(con, tmp_path / "vault", 30, date(2026, 10, 15)) == 3
    note = (tmp_path / "vault" / "Alpha  Ltd.md").read_text(encoding="utf-8")
    assert "[[Power]]" in note and "Board meeting" in note and "Old filing" not in note


def test_stock_list_write_keeps_header(tmp_path):
    p = tmp_path / "stock_list.toml"
    p.write_text('# my list\nstocks = [\n  { symbol = "AAA", isin = "INE000A01011", scrip = "1" },\n]\n', encoding="utf-8")
    sl._write(sl.load(p) + [{"symbol": "BBB", "isin": "INE000B01011", "scrip": None}], p)
    txt = p.read_text(encoding="utf-8")
    assert txt.startswith("# my list") and [s["symbol"] for s in sl.load(p)] == ["AAA", "BBB"]
    assert sl.remove("AAA", p) and [s["symbol"] for s in sl.load(p)] == ["BBB"] and not sl.remove("ZZZ", p)


def test_financials_skip_interest_cover():
    import pandas as pd
    q = pd.DataFrame({"quarter_end": pd.date_range("2024-09-30", periods=8, freq="QE").date,
                      "net_profit": [10.0] * 8, "pbt": [13.0] * 8, "finance_costs": [50.0] * 8})
    assert not safety.evaluate("X", "BANK", q, -0.1).ok
    assert safety.evaluate("X", "BANK", q, -0.1, financial=True).ok
    assert safety.is_financial("Financial Services") and not safety.is_financial("Power")
