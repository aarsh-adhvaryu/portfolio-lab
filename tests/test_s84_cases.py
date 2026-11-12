"""S84: the case store of the thinking loop (`think/cases.py`). Synthetic data only (rule 7)."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from pflab import think
from pflab.pm import store
from pflab.think import cases

NOW = datetime(2026, 11, 12, 16, 0)
ISIN = "ZZ0001045810"


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "t.duckdb")


def _case(con, **kw):
    sid = cases.record_signal(con, NOW, market="US", isin=ISIN, symbol="NVDA", signal="move", value=-0.095, threshold=0.05, surprise=3.1, exposure_inr=80000, score=2.4)
    return cases.open_case(con, NOW, market="US", kind="move", isin=ISIN, symbol="NVDA", title="NVDA down 9.5%", exposure_inr=80000, exposure_pct=0.07, score=2.4, signal_ids=[sid], **kw), sid


def test_the_settings_are_read_and_the_closed_lists_are_what_the_brief_says():
    s = think.settings()
    assert s["max_cases_per_day"] == 3 and s["bet_worst_pct_book"] == 0.01 and s["parts"] == 3 and s["parts_gap_sessions"] == 5
    assert think.OPTIONS == ("sell", "trim", "hold", "freeze", "wait", "buy_in_parts", "nothing")
    assert think.CLASSES == ("market_fear", "temporary", "damage", "unclear") and think.WORDS[2] == "even"


def test_a_case_keeps_its_signals_steps_options_and_decision(con):
    cid, sid = _case(con)
    cases.set_case(con, cid, klass="damage", pending="the board's decision", next_look_on=date(2026, 11, 13))
    cases.add_step(con, cid, NOW, "understand", engine="anthropic", model="sonnet", thinking="medium", cost_rupees=1.2, cached_tokens=900, payload={"x": 1})
    cases.add_option(con, cid, NOW, track="rule", isin=ISIN, symbol="NVDA", option="sell", worst_inr=-1000, likely_inr=5000, best_inr=9000, expected_inr=4000, worst_pct_book=-0.001, chosen=True)
    cases.record_decision(con, cid, NOW.date(), isin=ISIN, symbol="NVDA", rule_option="sell", model_option="trim", acted_option="sell", reason="a thesis break")
    c = cases.get_case(con, cid)
    assert c["klass"] == "damage" and c["signals"][0]["case_id"] == cid and c["steps"][0]["model"] == "sonnet" and c["steps"][0]["cached_tokens"] == 900
    assert c["options"][0]["chosen"] and c["decisions"][0]["differs"] is True and c["decisions"][0]["acted_option"] == "sell"


def test_a_name_with_an_open_case_joins_it_and_the_look_and_the_day_count_work(con):
    cid, _ = _case(con)
    assert cases.case_for(con, ISIN)["case_id"] == cid and cases.case_for(con, "ZZ0000000000") is None
    assert cases.cases_opened_on(con, NOW.date()) == 1
    cases.set_case(con, cid, next_look_on=date(2026, 11, 13))
    assert cases.looks_due(con, date(2026, 11, 12)) == [] and [c["case_id"] for c in cases.looks_due(con, date(2026, 11, 13))] == [cid]
    cases.close_case(con, cid, date(2026, 11, 14), "the pending question was answered")
    assert cases.open_cases(con) == [] and cases.get_case(con, cid)["closed_reason"].startswith("the pending")


def test_a_noticed_case_is_not_an_open_case_and_is_not_counted_as_thought_through(con):
    cases.open_case(con, NOW, market="IN", kind="move", isin="INE000A01011", symbol="AAA", title="noticed only", state="noticed")
    assert cases.open_cases(con) == [] and cases.cases_opened_on(con, NOW.date()) == 0
    assert cases.thinking_block(con, NOW.date())["noticed_not_examined_today"] == 1


def test_a_freeze_holds_until_its_date_or_is_released(con):
    cid, _ = _case(con)
    fid = cases.add_freeze(con, NOW, isin=ISIN, symbol="NVDA", market="US", case_id=cid, until=date(2026, 11, 20), reason="the board has not decided")
    assert cases.is_frozen(con, ISIN, date(2026, 11, 13))["freeze_id"] == fid and cases.is_frozen(con, ISIN, date(2026, 11, 21)) is None
    cases.release_freeze(con, fid)
    assert cases.is_frozen(con, ISIN, date(2026, 11, 13)) is None


def test_the_word_table_starts_at_the_brief_and_a_stored_row_overrides_it(con):
    assert cases.probabilities(con) == think.WORD_P and think.WORD_P["likely"] == 0.75
    assert cases.seed_calibration(con, NOW.date()) == 5 and cases.seed_calibration(con, NOW.date()) == 0
    con.execute("UPDATE think_calibration_s84 SET probability=0.6 WHERE word='likely'")
    assert cases.probabilities(con)["likely"] == 0.6


def test_the_thinking_block_is_plain_words(con):
    cid, _ = _case(con)
    cases.set_case(con, cid, klass="unclear", pending="a board meeting", next_look_cond="a filing")
    t = cases.thinking_block(con, NOW.date())
    assert "NVDA (unclear)" in t["text"] and "waiting for: a board meeting" in t["text"] and "looks again on: a filing" in t["text"]
    assert cases.thinking_block(store.connect(":memory:"), NOW.date())["text"] == "Thinking about: nothing open."
