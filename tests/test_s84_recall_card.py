"""S84 recall: the company card's "what we already know" section (`lab/screen.py`). The store and bars are the S83 screen test's synthetic ones."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace as NS

import pytest
from test_s83_tools import NOW, con, isin, root                      # noqa: F401  (fixtures)

from pflab.agents import analyst as an
from pflab.lab import screen
from pflab.think import recall

CFG = {"model": an.MODEL, "cap": 1500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True}


def _note(con, topic: str, isins, text: str, when: datetime) -> str:
    req = an.Request("How did revenue change and why?", topic, [], list(isins), True)
    cid = an._log(con, req, "live", an.MODEL, "sending", when, {})
    an.keep(con, cid, req, text, NS(input_tokens=8000, output_tokens=900), False, CFG, when)
    return con.execute("SELECT note_doc FROM api_calls WHERE call_id=?", [cid]).fetchone()[0]


def test_a_seeded_analyst_note_on_a_name_is_in_its_company_card_and_counted_as_used_and_another_names_is_not(con, root):
    mine = _note(con, "UPCO", [isin("UPCO")], "Up Co's order book is full for two quarters.", datetime(2026, 11, 3, 21, 0))
    other = _note(con, "DOWNCO", [isin("DOWNCO")], "Down Co is losing share to imports.", datetime(2026, 11, 4, 21, 0))
    later = _note(con, "UPCO", [isin("UPCO")], "A note written after the card's day.", datetime(2026, 11, 11, 21, 0))
    c = screen.company_card(con, NOW, "IN", "UPCO", root=root)
    know = c["what_we_already_know"]
    assert c["ok"] and know["n"] >= 1 and "order book is full" in know["text"] and f"analyst_note {mine}" in know["ids"]
    assert "losing share" not in know["text"] and other not in " ".join(know["ids"]) and later not in " ".join(know["ids"])
    row = con.execute("SELECT used_by_kind, used_by_ref, day FROM knowledge_use_s84 WHERE item_id=?", [mine]).fetchone()
    assert row[0] == "card" and row[1] == "IN:UPCO" and str(row[2]) == "2026-11-10"
    assert con.execute("SELECT count(*) FROM knowledge_use_s84 WHERE item_id IN (?, ?)", [other, later]).fetchone()[0] == 0
    assert recall.knowledge_line(con, NOW.date())["read_by_a_decision"] == 1
    assert screen.company_card(con, NOW, "IN", "NOSUCHSYM", root=root).get("what_we_already_know") is None           # a name the store does not know has no section


def test_a_card_with_nothing_stored_says_so(con, root):
    c = screen.company_card(con, NOW, "IN", "DOWNCO", root=root)
    assert c["what_we_already_know"]["n"] == 0 and "nothing stored" in c["what_we_already_know"]["text"]
