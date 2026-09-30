"""pflab.readers: the A1 scorer (plan §3) and L's prompt (no network)."""
from pathlib import Path

import pytest

from pflab.readers import llm, score as sc

LABELS = Path(__file__).resolve().parents[1] / "docs/data/flag_audit_labels.md"


def test_kappa_perfect_and_chance():
    assert sc.kappa([("A", "A"), ("B", "B")]) == pytest.approx(1.0)
    assert sc.kappa([("A", "A"), ("A", "A")]) is None          # pe == 1
    assert sc.kappa([("A", "A"), ("A", "B"), ("B", "A"), ("B", "B")]) == pytest.approx(0.0)


def test_block_counts_precision_and_unclear():
    pairs = [("AT_COMPANY", "AT_COMPANY"), ("NOT_EVENT", "AT_COMPANY"),
             ("UNCLEAR", "UNCLEAR"), ("RELATED_ENTITY", "NOT_EVENT")]
    b = sc.block(pairs, [0.95, 0.8, 0.5, None])
    assert b["n"] == 4 and b["agreement"] == pytest.approx(0.5)
    assert b["precision_reader"] == pytest.approx(2 / 3)       # 2 AT of 3 non-UNCLEAR
    assert b["precision_reference"] == pytest.approx(1 / 3)
    assert b["unclear_rate_reader"] == pytest.approx(0.25)
    assert b["confusion"]["NOT_EVENT"]["AT_COMPANY"] == 1
    assert b["by_confidence"]["0.9-1.0"] == {"n": 1, "agreement": 1.0}
    assert b["by_confidence"]["0.0-0.7"] == {"n": 1, "agreement": 1.0}


def test_failed_read_counts_as_unclear():
    ref = {1: {"flag": "FRAUD", "label": "TRUE", "subtype": "AT_COMPANY"},
           2: {"flag": "FRAUD", "label": "UNSURE", "subtype": "UNCLEAR"}}
    s = sc.score(ref, {1: {"subtype": "bogus"}})
    assert s["failed_reads"] == 2
    assert s["overall"]["agreement"] == pytest.approx(0.5)


def test_reference_parses_the_committed_labels():
    ref = sc.reference(LABELS)
    assert len(ref) == 251
    assert ref[171]["subtype"] == "RELATED_ENTITY" and ref[165]["subtype"] == "UNCLEAR"


def test_prompt_carries_criteria_but_no_reference_answers():
    s = llm.system_prompt(LABELS, "audit")
    assert "The only question" in s and "| RATING_DOWNGRADE |" in s
    assert "(88, 97" not in s and "182" not in s and "rating letters" not in s
    assert "(every TRUE row)" in s
    assert "NONE" in llm.system_prompt(LABELS, "recall")


def test_cache_key_changes_with_any_input():
    k = llm.Cache.key
    assert k("d", "s", "u") != k("d", "s", "u2") != k("d2", "s", "u")
    assert k("d", "s", "u") == k("d", "s", "u")


def test_at_call_precision_ignores_reference_unclear():
    pairs = [("AT_COMPANY", "AT_COMPANY"), ("NOT_EVENT", "AT_COMPANY"),
             ("UNCLEAR", "AT_COMPANY"), ("AT_COMPANY", "NOT_EVENT")]
    assert sc.block(pairs)["at_call_precision"] == pytest.approx(0.5)
    ref = {i: {"flag": "F", "label": "", "subtype": s}
           for i, s in enumerate(["AT_COMPANY", "AT_COMPANY", "NOT_EVENT", "UNCLEAR"])}
    # K asserts AT_COMPANY everywhere: its AT calls correct = reference precision
    o = sc.score(ref, sc.keyword_reader(ref))["overall"]
    assert o["at_call_precision"] == pytest.approx(2 / 3) == o["precision_reference"]
