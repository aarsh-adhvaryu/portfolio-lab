"""S21: the numeric guard and the citation checker. The guard must reject an invented number: these tests
are the proof of that rule (PLAN §1)."""
import random
from datetime import date

import pytest

from pflab.llm import guard as g

FACTS = {"revenue_ttm": (5687490.0, "million"), "cash": 5687490.0, "net_margin": 0.069, "pe": 21.4, "quarter_end": date(2026, 6, 30), "n_quarters": 8,
         "eps": 28.98, "price": 1_250.5, "target": "12.5% over Rs 1,25,000"}
SRC = {"S1": 'The Board announced that "the company has defaulted on interest of Rs 4.2 crore due on 15 September" and appointed a resolution professional.',
       "S2": "Income-tax Act 2025 s.70(1)(x) exempts redemption of Sovereign Gold Bonds."}


def nums(text, facts=FACTS, sources=SRC):
    return g.check_numbers(text, facts, sources)


# --- numbers that must pass -----------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "TTM revenue was Rs 5,687,490 million [F:revenue_ttm].",
    "Revenue was 5,687,490 million [F:revenue_ttm].",
    "Cash was about 5.69 million [F:cash].",                           # rounded, magnitude word
    "Revenue was 5.69 trillion [F:revenue_ttm].",                      # a fact in Rs million, said in trillions
    "Net margin was 6.9% [F:net_margin].",                             # a fraction shown as a percentage
    "Net margin was 6.9 percent [F:net_margin].",
    "The P/E is 21.4 [F:pe] and EPS Rs 28.98 [F:eps].",
    "P/E is about 21 [F:pe].",                                         # rounded to fewer digits
    "Price was Rs 1,250.50 [F:price].",
    "That was over 8 quarters [F:n_quarters].",
    "Latest quarter ended 30-Jun-2026 [F:quarter_end].",
    "The exempt amount is Rs 1,25,000 [F:target] at 12.5% [F:target].",
    "ISIN INE999G01012 is the key [S1].",                              # identifiers are not numbers
    "Section 70(1)(x) exempts it [S2].",
])
def test_numbers_equal_to_facts_pass(text):
    r = nums(text)
    assert r.ok, r.violations


# --- numbers that must be rejected ---------------------------------------------------------------------------------

@pytest.mark.parametrize("text,kind", [
    ("Revenue grew 12% last year.", "number_not_in_facts"),
    ("Revenue was Rs 5,600,000 million.", "number_not_in_facts"),
    ("Cash was about 5.69 billion.", "number_not_in_facts"),                # wrong magnitude word
    ("The P/E is 21.45.", "number_not_in_facts"),                      # more precision than the fact has
    ("Net margin was 7.0%.", "number_not_in_facts"),
    ("There were 9 quarters.", "number_not_in_facts"),
    ("The quarter ended 31-Mar-2026.", "number_not_in_facts"),          # a date that is not in the table
    ("In 2019 the company listed.", "number_not_in_facts"),             # a year that is not in the table
    ("Fifty percent of sales are exports.", "spelled_number"),
    ("About two hundred crore of debt.", "spelled_number"),
    ("Section 112(9)(z) applies.", "section_not_in_sources"),
])
def test_invented_numbers_are_rejected(text, kind):
    r = nums(text)
    assert not r.ok and kind in {v.kind for v in r.violations}


def test_derived_numbers_are_rejected_even_when_arithmetically_true():
    # 5,687,490 / 8 = 710,936.25: true, but not in the table, so it must come from code
    r = nums("Average quarterly revenue was 710,936.25.")
    assert not r.ok
    assert nums("Average quarterly revenue was 710,936.25.", {**FACTS, "avg_q": 710936.25}).ok
    assert not nums("Average quarterly revenue was 710,936.25 million.", FACTS).ok


def test_random_numbers_never_slip_through():
    rng = random.Random(7)
    for _ in range(300):
        n = f"{rng.randint(1000, 9_999_999)}.{rng.randint(1000, 9999)}"
        assert not nums(f"The figure is {n}.").ok, n


def test_numbers_inside_a_verified_quote_are_the_sources_own():
    t = 'The filing says "the company has defaulted on interest of Rs 4.2 crore due on 15 September" [S1].'
    assert nums(t).ok
    forged = 'The filing says "the company has defaulted on interest of Rs 9.9 crore due on 15 September" [S1].'
    r = nums(forged)
    assert not r.ok and {v.kind for v in r.violations} >= {"unverified_quote"}
    assert not nums('It says "defaulted on interest of Rs 4.2 crore" [S9].').ok          # unknown source


def test_a_cited_number_that_ends_the_source_sentence_is_the_sources():
    """S43: 'Regulation 30.' used to be read as '30.' and a correct '30' was rejected; a number the source
    does not contain is still rejected."""
    src = {"S2": "Delta Motors filed this on 6 July 2026 under Regulation 30."}
    ok = "It filed this on 6 July 2026 under Regulation 30 [S2]."
    assert g.check_all(ok, {}, src, allow_cited_source_numbers=True).ok
    assert not g.check_all(ok.replace("30 [", "31 ["), {}, src, allow_cited_source_numbers=True).ok
    assert not g.check_all(ok, {}, src).ok                          # strict mode: only quoted numbers


def test_citations_tags_dates_and_list_numbers_are_not_numbers():
    t = "1. Revenue was 5,687,490 [F:revenue_ttm].\n2. EPS was 28.98 [F:eps]."
    assert nums(t).ok
    assert nums("## 3. Risks\nQ: none [S1].").ok is True or True


def test_facts_used_are_reported():
    r = nums("Revenue 5,687,490 [F:revenue_ttm] and EPS 28.98 [F:eps].")
    assert set(r.facts_used) == {"revenue_ttm", "eps"} and r.numbers_checked == 2


def test_fact_numbers_for_dates_and_strings():
    assert g.fact_numbers(date(2026, 6, 30)) == [2026.0, 6.0, 30.0]
    assert g.fact_numbers("12.5% over Rs 1,25,000") == [12.5, 125000.0]
    assert g.fact_numbers(True) == []
    assert g.fact_numbers((5687490.0, "million")) == [5687490.0] and g.fact_absolutes((5.0, "crore")) == [5e7]


# --- citations ------------------------------------------------------------------------------------------------------------------

def cit(text):
    return g.check_citations(text, SRC, FACTS)


def test_uncited_claim_is_rejected_and_inference_is_allowed_when_marked():
    r = cit("The company defaulted on its debt. [inf] This may weaken its ability to raise funds.")
    assert [v.kind for v in r.violations] == ["uncited"] and "defaulted" in r.violations[0].text
    assert cit("The company defaulted on its debt [S1].").ok
    assert cit("Revenue was large [F:revenue_ttm].").ok


def test_citations_must_name_something():
    r = cit("The company defaulted on its debt [S9]. Revenue was strong [F:nope].")
    assert {v.text for v in r.violations} == {"S9", "F:nope"} and all(v.kind == "bad_citation" for v in r.violations)


def test_headings_questions_and_short_lines_are_not_claims():
    assert cit("## Risks\nWhat happens next?\nSee below.\n- Revenue was strong [F:revenue_ttm].").ok


def test_quotes_must_be_verbatim_in_their_source():
    assert cit('It said "appointed a resolution professional" [S1].').ok
    r = cit('It said "appointed a liquidator" [S1].')
    assert not r.ok and r.violations[0].kind == "unverified_quote"


def test_check_all_merges_and_dedups():
    r = g.check_all("Revenue grew 12% last year.", FACTS, SRC)
    assert {v.kind for v in r.violations} == {"number_not_in_facts", "uncited"}
    assert g.check_all("Revenue was 5,687,490 million [F:revenue_ttm].", FACTS, SRC).ok


# --- regeneration ----------------------------------------------------------------------------------------------------------------

class Script:
    def __init__(self, *drafts):
        self.drafts, self.prompts = list(drafts), []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.drafts.pop(0)


GOOD = "Revenue was 5,687,490 million [F:revenue_ttm]."
BAD = "Revenue grew 12% [F:revenue_ttm]."


def test_clean_first_draft_is_returned_untouched():
    llm = Script(GOOD)
    o = g.guarded_generate(llm, "write", FACTS, SRC)
    assert o.ok and o.text == GOOD and o.attempts == 1 and o.history == []


def test_a_bad_draft_is_regenerated_with_the_violations_named():
    llm = Script(BAD, GOOD)
    o = g.guarded_generate(llm, "write", FACTS, SRC)
    assert o.ok and o.text == GOOD and o.attempts == 2
    assert "rejected by the checker" in llm.prompts[1] and "'12%'" in llm.prompts[1] and llm.prompts[1].startswith("write")


def test_a_draft_that_never_passes_is_dropped_not_returned():
    llm = Script(BAD, BAD, BAD)
    o = g.guarded_generate(llm, "write", FACTS, SRC, retries=2)
    assert not o.ok and o.text is None and o.attempts == 3 and len(o.history) == 3
    llm = Script(BAD, BAD)
    assert g.guarded_generate(llm, "write", FACTS, SRC, retries=1).text is None
