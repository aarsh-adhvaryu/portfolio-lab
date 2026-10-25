"""S46: quant researcher routing, drift rules, event-study arithmetic, event confirmation, thesis tracker. SYNTHETIC."""
import json
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from pflab.agents import event, quant, questions, thesis
from pflab.kg import graph as g
from pflab.ledger.events import Event, EventLog, save
from pflab.pm import store
from pflab.quant import drift, event_study as es


def test_ideas_map_to_templates():
    assert quant.route("how do stocks move after credit rating downgrades")[0] == "event_study"
    assert quant.route("how do stocks move after credit rating downgrades")[1]["label"] == "rating downgrade"
    assert quant.route("what happens after dividend announcements")[1]["subcategories"] == ["Dividend"]
    assert quant.route("is the dip rule still working?")[0] == "drift"
    assert quant.route("will gold go up")[0] == "none"


def test_drift_flags_a_rule_that_stopped_warning():
    idx = pd.bdate_range("2015-01-01", periods=2600)
    r = pd.Series(0.001, index=idx)
    k = np.arange(len(idx))
    r[(k % 40 == 0) | (k % 40 == 3)] = -0.03                       # falls in pairs: follow-on falls every 40 sessions
    # one fall lifts the chance to about 0.34 here; a threshold of 0.30 warns before the follow-on fall 3 sessions later
    c = {"mu": 0.0125, "alpha": 0.75, "beta": 0.05, "threshold": -0.02, "horizon": 10, "t1": 0.30}
    calm = drift.market_state(r, c, since="2020-01-01")
    assert calm["follow_on"] > 10 and calm["recall"] > 0.8
    never = drift.market_state(r, {**c, "t1": 0.999}, since="2020-01-01")    # a threshold that never warns
    assert never["recall"] == 0.0 and never["drift"]
    # four 5% falls: from the first close, -9.75% after three, -14.3% after four: one trigger
    d = drift.dip_rule(pd.Series([-0.05] * 4 + [0.0] * 300, index=pd.bdate_range("2022-01-03", periods=304)))
    assert d["triggers"] == 1 and not d["drift"]


def test_event_study_cars_by_hand():
    days = pd.bdate_range("2020-01-01", periods=30)
    rets = pd.DataFrame({"A": 0.01}, index=days)
    mkt = pd.Series(0.004, index=days)
    ev = pd.DataFrame({"isin": ["A", "A"], "t": [pd.Timestamp("2020-01-02 10:00"), pd.Timestamp("2020-01-02 16:00")],
                       "headline": ["h1", "h2"]})
    c = es.cars(ev, rets, mkt, windows=(1, 5))
    assert c["car_1"].tolist() == pytest.approx([0.012, 0.012]) and c["car_5"].iloc[0] == pytest.approx(0.036)
    assert list(c["t"]) == list(ev["t"])                            # after 15:30 the event session is the next day
    s = es.summary(c, (1, 5))
    assert s["CAR[0,5]"]["n"] == 2 and s["CAR[0,5]"]["mean"] == pytest.approx(0.036)


def _store(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at)
                   VALUES ('INE000A01011', 'isin', 'equity', 'listed_equity', TRUE, 'AAA', 'Aaa Pharma Limited',
                   'Pharmaceuticals', 'synthetic', now())""")
    g.node(con, "company:INE000A01011", "company", "Aaa Pharma Limited", {"symbol": "AAA"})
    return con


def test_news_is_confirmed_only_by_a_matching_recent_filing(tmp_path):
    con = _store(tmp_path)
    d = g.doc(con, "filing", "k1", datetime(2026, 10, 15, 11), "Licensing agreement for oncology drug with Beta Corp",
              source="BSE", attrs={"subcategory": "Agreement"})
    g.edge(con, d, "about", "company:INE000A01011", datetime(2026, 10, 15, 11), "bse")
    hit = event.confirm(con, "INE000A01011", "Aaa Pharma signs an oncology drug licensing deal", date(2026, 10, 17))
    assert hit and hit["subcategory"] == "Agreement"
    assert event.confirm(con, "INE000A01011", "Aaa Pharma opens a new plant in Gujarat", date(2026, 10, 17)) is None
    assert event.confirm(con, "INE000A01011", "Aaa Pharma oncology drug licensing", date(2026, 11, 30)) is None   # too old


def test_thesis_tracks_evidence_exposure_and_asks_at_expiry(tmp_path):
    con = _store(tmp_path)
    con.execute("INSERT INTO accounts (account_id, kind) VALUES ('ZER', 'demat')")
    save(con, EventLog([Event("deposit", "ZER", date(2026, 9, 1), amount=50_000.0),
                        Event("buy", "ZER", date(2026, 9, 2), isin="INE000A01011", qty=10, price=1000.0, ref="T1")]))
    con.execute("INSERT INTO prices VALUES ('INE000A01011', '2026-10-16', 1100.0, 'EQ', 'nse', now())")
    a = g.doc(con, "article", "u1", datetime(2026, 10, 10), "Pharma pricing pressure in US generics", "u1", "x.in")
    tid = thesis.add(con, "Generic drug prices will fall", ["generic", "pricing pressure"], ["Pharmaceuticals"],
                     months=1, now=datetime(2026, 10, 1))
    rows = thesis.update(con, date(2026, 10, 17), with_cost=False)
    assert rows[0]["evidence"]["documents"] == 1 and rows[0]["exposure"]["rupees"] == pytest.approx(11_000.0)
    assert "Generic drug prices" in thesis.render(rows) and questions.open_questions(con) == []
    thesis.update(con, date(2026, 11, 1), with_cost=False)                             # expired on 2026-11-01
    assert "reached its expiry" in questions.open_questions(con)[0][2]
    with pytest.raises(ValueError):
        thesis.add(con, "no words", [], [])
