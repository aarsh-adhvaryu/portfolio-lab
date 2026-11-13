"""S85 `weekrun`: regressions found by the accelerated_week drill (a week of the whole system, scripted). Synthetic data only."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pytest

from pflab.agents import analyst as an
from pflab.pm import store
from pflab.think import recall, score

NOW = datetime(2026, 10, 21, 21, 0)


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "t.duckdb")
    yield c
    c.close()


def test_a_recalled_notes_hash_id_never_looks_like_a_phone_or_account_number_to_the_egress_gate():
    """A note's id is a hash; one with ten digits in a row (`...8629119755`) made the gate refuse the whole case message (found by the week drill, 2026-10-21 desk)."""
    it = {"day": "2026-10-21", "kind": "note", "id": "doc:analyst_note:4d675f8629119755", "source": "case", "title": "Case #6", "text": ""}
    line = recall._line(it)
    assert "analyst_note" in line and "4d67" in line
    for name, rx in an._IDS.items():
        assert not rx.search(line), (name, line)
    # ids that are only digits, and ordinary ones, keep their meaning (display only)
    assert recall._shown_id("case:6") == "case:6" and recall._shown_id("doc:x:1234") == "doc:x:1234"
    assert not re.search(r"\d{9,}", recall._shown_id("12345678901234567890"))


def _seed_decisions(con):
    """Two cases, one read on claude and decided on day D, one read on openai and decided on D+1; both scored at 20 sessions on the track `model` and `rule`."""
    from pflab.think import cases
    d0 = date(2026, 10, 15)
    ids = {}
    for sym, eng, day, did, vs in (("AAA", "claude", d0, 1, 100.0), ("BBB", "openai", d0 + timedelta(days=1), 2, -40.0)):
        cid = cases.open_case(con, datetime(day.year, day.month, day.day, 9), market="IN", kind="move", isin=f"INE9S0{did}A01011", symbol=sym, title=sym, opened_by="test")
        cases.add_step(con, cid, datetime(day.year, day.month, day.day, 10), "answer", engine=eng, model="m-" + eng, thinking="high")
        con.execute("INSERT INTO think_decisions_s84 (decision_id, case_id, decided_on, isin, symbol, rule_option, model_option, acted_option, differs, order_refs_json, reason, advisory) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [did, cid, day, f"INE9S0{did}A01011", sym, "hold", "hold", "hold", False, "[]", "t", False])
        cols = [r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name='think_scores_s84' ORDER BY ordinal_position").fetchall()]
        for track in ("model", "rule"):
            row = {"score_id": did * 10 + (track == "rule"), "decision_id": did, "track": track, "horizon_sessions": 20, "option": "hold", "result_inr": vs, "vs_nothing_inr": vs}
            vals = [row.get(k) for k in cols]
            con.execute(f"INSERT INTO think_scores_s84 ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", vals)
        ids[eng] = did
    return ids


def test_a_switch_of_engine_keeps_each_engines_own_record_in_the_scorecard(con):
    ids = _seed_decisions(con)
    made = score.engine_of_decisions(con)
    assert made == {ids["claude"]: "claude", ids["openai"]: "openai"}
    from pflab.llm import gateway
    gateway.grant(con, "openai", "use", now=NOW, wording="test")
    gateway.record_exam(con, "openai", form_pass=True, grade="test", now=NOW)
    gateway.key_set, real = (lambda st, name: True), gateway.key_set
    try:
        assert gateway.use(con, "openai", yes=True, now=NOW)["ok"]
    finally:
        gateway.key_set = real
    be = score.by_engine(con)
    assert set(be) == {"claude", "openai"} and be["openai"]["in_use"] and not be["claude"]["in_use"]
    assert be["claude"]["model_track"]["n"] == 1 and be["claude"]["model_track"]["vs_nothing_inr"] == 100.0
    assert be["openai"]["model_track"]["n"] == 1 and be["openai"]["model_track"]["vs_nothing_inr"] == -40.0


def test_with_one_engine_only_the_scorecard_is_what_it_always_was(con):
    _seed_decisions(con)
    con.execute("UPDATE think_steps_s84 SET engine='claude'")
    be = score.by_engine(con)
    assert set(be) == {"claude"} and be["claude"]["model_track"]["n"] == 2
