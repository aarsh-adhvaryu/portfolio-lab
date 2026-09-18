"""Red-flag rules, revised 2026-09-16 against the 41,128-announcement sample.

Every headline below is either verbatim from that corpus or the shape the
review named. The negative cases are the point: the first draft fired on all
of them.
"""
from pflab.data.red_flags import RULES, classify


# -- INSOLVENCY ---------------------------------------------------------
def test_insolvency_needs_an_insolvency_process():
    assert "INSOLVENCY" in classify("Intimation of NCLT order admitting CIRP")
    assert "INSOLVENCY" in classify("Appointment of Resolution Professional")
    assert "INSOLVENCY" in classify("Admission of application under IBC")
    assert "INSOLVENCY" in classify("Commencement of liquidation")


def test_bare_nclt_scheme_is_not_insolvency():
    """JSW Energy and GE Power appear under NCLT in the sample; neither is
    insolvent. A scheme of arrangement goes through the NCLT as a matter of
    course."""
    assert classify("NCLT convened meeting for Scheme of Arrangement") == []
    assert classify("NCLT approves Scheme of Amalgamation") == []
    assert classify("Order of NCLT on the Demerger") == []


# -- REGULATORY_ACTION --------------------------------------------------
def test_regulatory_action_needs_sebi_or_sat_as_the_actor():
    assert "REGULATORY_ACTION" in classify("SEBI has passed an order imposing penalty")
    assert "REGULATORY_ACTION" in classify("Adjudication order received from SEBI")
    assert "REGULATORY_ACTION" in classify("Show cause notice issued by SEBI")
    assert "REGULATORY_ACTION" in classify("Search by the Enforcement Directorate")


def test_business_orders_are_not_regulatory_action():
    """Verbatim from the sample: a purchase order matched the first draft."""
    assert classify('Intimation with regards to "Siyaram Recycling" secured '
                    "order amounting to Rs. 1,00,00,000") == []
    assert classify("Bagging of work order from NTPC") == []
    assert classify("Receipt of order / Letter of Intent") == []


def test_lodr_boilerplate_is_not_regulatory_action():
    """The commonest false positive: standard LODR filing language."""
    assert classify("Pursuant to the provisions of Regulation 30 of SEBI "
                    "(Listing Obligations and Disclosure Requirements) "
                    "Regulations, 2015") == []


def test_bare_ed_and_sat_are_gone():
    assert classify("Board meeting held and concluded") == []
    assert classify("Sat down with analysts for a call") == []


# -- PROMOTER_ENCUMBRANCE ----------------------------------------------
def test_reasons_for_encumbrance_is_the_distress_signal():
    """SEBI requires this disclosure only when pledging crosses 50% of promoter
    holding or 20% of share capital, so it is kept as its own flag."""
    assert "PROMOTER_ENCUMBRANCE" in classify(
        "The Exchange has received the disclosures of reasons for encumbrance "
        "by promoter of listed companies")


def test_ordinary_pledge_creation_and_release_is_not_flagged():
    """1,143 rows in the sample; routine SAST 31(1) traffic, left to E2-A."""
    assert classify("Disclosure under Regulation 31(1) of SEBI SAST "
                    "Regulations - creation of pledge") == []
    assert classify("Release of pledge of shares by promoter") == []


# -- DEFAULT and RATING_DOWNGRADE --------------------------------------
def test_default_catches_delayed_interest_and_principal():
    assert "DEFAULT" in classify("Default in repayment of term loan")
    assert "DEFAULT" in classify("Delay in payment of interest on NCDs")
    assert "DEFAULT" in classify("Disclosure of default on debt securities")


def test_nil_default_is_not_a_default():
    assert classify("Disclosure of default: NIL default as on date") == []


def test_rating_downgrade():
    assert "RATING_DOWNGRADE" in classify("Downgrade in credit rating by CRISIL")
    assert "RATING_DOWNGRADE" in classify("Revision in credit rating")
    assert classify("Upgrade in credit rating by ICRA") == []


# -- the rest -----------------------------------------------------------
def test_auditor_resignation_and_forensic_audit():
    assert "AUDITOR_RESIGNATION" in classify("Resignation of Statutory Auditor")
    assert "AUDITOR_RESIGNATION" in classify("Statutory auditor has resigned")
    assert "FORENSIC_AUDIT" in classify("Initiation of forensic audit")


def test_results_delay_and_fraud():
    assert "RESULTS_DELAY" in classify("Delay in submission of financial results")
    assert "FRAUD" in classify("Whistleblower complaint alleging fraud")
    assert classify("Fraud prevention policy adopted by the Board") == []


def test_category_and_subcategory_participate_in_matching():
    """BSE headlines are often "as attached"; the category fields carry the
    signal, which is why they are matched too."""
    assert "AUDITOR_RESIGNATION" in classify(
        "as attached", category="Company Update",
        subcategory="Resignation of Statutory Auditor")


def test_plain_announcements_stay_clean():
    for h in ["Board Meeting Intimation", "Trading Window Closure",
              "Newspaper Publication", "Analyst Meet Intimation",
              "Outcome of Board Meeting - audited financial statements"]:
        assert classify(h) == [], h


def test_rule_set_is_the_frozen_one():
    assert set(RULES) == {
        "INSOLVENCY", "REGULATORY_ACTION", "FORENSIC_AUDIT",
        "AUDITOR_RESIGNATION", "DEFAULT", "RATING_DOWNGRADE",
        "PROMOTER_ENCUMBRANCE", "RESULTS_DELAY", "FRAUD"}
