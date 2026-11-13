"""S84 recall: a pick on a name with an earlier note or case must say what it takes from it (`core/picks.propose`, field `takes_from`, 20+ characters)."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace as NS

import pytest
from test_s83_picks import CCC, DDD, NOW, con, item                    # noqa: F401  (fixtures and helpers)

from pflab.agents import analyst as an
from pflab.core import picks
from pflab.lab import tools
from pflab.think import cases, recall

CFG = {"model": an.MODEL, "cap": 1500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True}


def _note(con, topic, isins, text, when):
    req = an.Request("How did revenue change and why?", topic, [], list(isins), True)
    cid = an._log(con, req, "live", an.MODEL, "sending", when, {})
    an.keep(con, cid, req, text, NS(input_tokens=8000, output_tokens=900), False, CFG, when)
    return con.execute("SELECT note_doc FROM api_calls WHERE call_id=?", [cid]).fetchone()[0]


def test_a_pick_on_a_name_with_an_earlier_note_must_say_what_it_takes_from_it(con):
    doc = _note(con, "CCC", [CCC], "CCC's margins are widening as input costs fall.", NOW - timedelta(days=3))
    out = picks.propose(con, NOW, "IN", [item("CCC"), item("DDD")], session_ref="s1")
    assert [a["symbol"] for a in out["accepted"]] == ["DDD"]                                       # DDD has no earlier note: no demand
    why = out["refused"][0]["reason"]
    assert out["refused"][0]["symbol"] == "CCC" and "takes_from" in why and doc in why and "20" in why
    short = picks.propose(con, NOW, "IN", [item("CCC", takes_from="the note")], session_ref="s1")
    assert short["accepted"] == [] and "takes_from" in short["refused"][0]["reason"]
    ok = picks.propose(con, NOW, "IN", [item("CCC", takes_from="takes the margin trend from the analyst note of three days ago")], session_ref="s1")
    assert [a["symbol"] for a in ok["accepted"]] == ["CCC"]
    pid = ok["accepted"][0]["pick_id"]
    assert con.execute("SELECT takes_from FROM picks_s83 WHERE pick_id=?", [pid]).fetchone()[0].startswith("takes the margin trend")
    row = con.execute("SELECT used_by_kind, used_by_ref FROM knowledge_use_s84 WHERE item_id=?", [doc]).fetchone()
    assert row == ("pick", f"pick:{pid}")                                                          # the note was read by the pick


def test_an_earlier_case_also_needs_a_sentence_and_a_name_with_neither_does_not(con):
    c = cases.open_case(con, NOW - timedelta(days=2), market="IN", kind="move", isin=DDD, symbol="DDD", title="DDD fell 9%")
    cases.set_case(con, c, klass="temporary", summary="a fall with the market")
    out = picks.propose(con, NOW, "IN", [item("DDD")], session_ref="s1")
    assert out["accepted"] == [] and "takes_from" in out["refused"][0]["reason"] and f"case:{c}" in out["refused"][0]["reason"]
    assert picks.propose(con, NOW, "IN", [item("DDD", takes_from="a fall on market fear that the case judged temporary")], session_ref="s1")["accepted"]


def test_the_picks_tool_carries_the_field(con):
    props = tools.ITEM["properties"]
    assert "takes_from" in props and "takes_from" not in tools.ITEM["required"]
