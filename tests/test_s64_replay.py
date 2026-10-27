"""S64 Phase 5 item 8: the replay bench re-runs a journaled pass with its tools answered from the journal."""
import json

import pytest

from pflab.hq import brain, egress, replay
from pflab.hq import tools as tl
from tests.test_s60_brain import CFG, Fake, _desk, _note_msg, _prices, _tool_msg, _walk, AAA, con, quiet_input  # noqa: F401


def original(con, tmp_path, quiet_input, monkeypatch):
    monkeypatch.setattr(brain, "SHADOW", True)
    rt = _desk(con, tmp_path)
    _prices(con, AAA, _walk(900, 1))
    c = Fake([_tool_msg(("memory_recall", {"words": "anything"}), ("research_flags", {"days": 7})),
              _note_msg("AAA is 9.0% of the portfolio. Nothing new.")])
    return rt, brain.think(rt, "asked", [], c, egress.Gate(), cfg=CFG)


def test_replay_answers_tools_from_the_log_and_executes_nothing(con, tmp_path, quiet_input, monkeypatch):
    rt, pid = original(con, tmp_path, quiet_input, monkeypatch)
    recorded = {t["tool"]: t["result"] for t in brain.tool_calls(con, pid)}
    calls_before = con.execute("SELECT count(*) FROM hq_tool_calls").fetchone()[0]
    # the changed brain asks the same two tools, and one the original never called
    c2 = Fake([_tool_msg(("memory_recall", {"words": "anything"}), ("research_flags", {"days": 7}),
                         ("price_history", {"symbol": "AAA"})),
               _note_msg("AAA is 9.0% of the portfolio. Replayed.")])
    monkeypatch.setattr(tl, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("a real tool ran in a replay")))
    r = replay.replay(rt, c2, egress.Gate(), pid, cfg=CFG)
    assert r["served"] == 2 and r["not_in_replay"] == ["price_history"] and r["status"] == "done"
    assert "Replayed" in r["new_note"] and "Nothing new" in r["old_note"]
    sent = c2.messages.sent[1]["messages"][2]["content"]                     # the tool results the new brain was shown
    texts = [b["content"] for b in sent]
    assert recorded["memory_recall"][:50] in texts[0] and texts[2].startswith("not in replay")
    assert con.execute("SELECT count(*) FROM hq_tool_calls").fetchone()[0] == calls_before      # the replay logged no tool calls
    row = con.execute("SELECT trigger, role, shadow FROM hq_passes WHERE pass_id=?", [r["new_pass"]]).fetchone()
    assert row == ("replay of #%d: asked" % pid, "rival", True)
    out = replay.side_by_side(r)
    assert "OLD pass" in out and "NEW pass" in out and "not in replay: 1 (price_history)" in out


def test_a_replay_of_a_replay_or_of_a_pass_without_tools_is_refused(con, tmp_path, quiet_input, monkeypatch):
    rt, pid = original(con, tmp_path, quiet_input, monkeypatch)
    con.execute("UPDATE hq_passes SET trigger='replay of #1: asked' WHERE pass_id=?", [pid])
    with pytest.raises(ValueError, match="itself a replay"):
        replay.replay(rt, Fake(), egress.Gate(), pid, cfg=CFG)
    con.execute("UPDATE hq_passes SET trigger='asked' WHERE pass_id=?", [pid])
    con.execute("DELETE FROM hq_tool_calls")
    with pytest.raises(ValueError, match="no tool calls"):
        replay.replay(rt, Fake(), egress.Gate(), pid, cfg=CFG)
    with pytest.raises(LookupError):
        replay.replay(rt, Fake(), egress.Gate(), 999, cfg=CFG)


def test_logtools_gives_each_repeated_call_its_own_result_and_marks_the_old_cut():
    calls = [{"tool": "t", "args": {"a": 1}, "status": "ran", "result": "first"},
             {"tool": "t", "args": {"a": 1}, "status": "ran", "result": "second"},
             {"tool": "u", "args": {}, "status": "error", "result": "x" * 2000}]
    lt = replay.LogTools(calls)
    assert lt(None, "t", {"a": 1}) == ("first", False) and lt(None, "t", {"a": 1}) == ("second", False)
    assert lt(None, "t", {"a": 1}) == ("second", False)                         # the last one stays available
    text, err = lt(None, "u", {})
    assert err and text.endswith("the original result was longer)")
    assert lt(None, "t", {"a": 2}) == (replay.NOT_IN_REPLAY, True) and lt.missed == ["t"]
