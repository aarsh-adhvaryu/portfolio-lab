"""S33 fixed deposits: SBI interest convention, facts vs estimates, FY interest and TDS, ladder warnings,
certificate parser, storage, tax wiring. Every deposit and certificate below is SYNTHETIC."""
from datetime import date

import pytest

from pflab.ingest import sbi_interest_cert as cert
from pflab.ledger.events import EventLog
from pflab.pm import estimate as est
from pflab.pm import fd as F
from pflab.pm import store
from pflab.tax import proposed as pr


def dep(**kw):
    base = dict(fd_id="0001", principal=100_000.0, rate=0.08, term_start=date(2025, 1, 10),
                maturity=date(2026, 1, 10), maturity_amount=round(100_000 * 1.02 ** 4, 2))
    base.update(kw)
    return F.FD(**base)


# --- the bank's arithmetic ----------------------------------------------------------------------------------------

def test_full_quarters_compound_at_rate_over_four():
    d = dep()
    assert F.contract_value(d, date(2026, 1, 10)) == pytest.approx(100_000 * 1.02 ** 4)
    assert F.contract_value(d, date(2025, 4, 10)) == pytest.approx(102_000.0)
    assert F.check(d) == pytest.approx(108_243.216)


def test_running_quarter_accrues_pro_rata_over_its_own_days():
    d = dep()
    # 10 Apr -> 10 Jul is 91 days; 30 days in: rate/4 x 30/91 on the compounded balance
    assert F.contract_value(d, date(2025, 5, 10)) == pytest.approx(102_000 * (1 + 0.02 * 30 / 91))


def test_final_stub_shorter_than_a_quarter_is_simple_over_365():
    d = dep(maturity=date(2026, 2, 19), maturity_amount=round(100_000 * 1.02 ** 4 * (1 + 0.08 * 40 / 365), 2))
    assert F.check(d) == pytest.approx(100_000 * 1.02 ** 4 * (1 + 0.08 * 40 / 365))


def test_terms_that_do_not_reproduce_the_bank_are_refused():
    with pytest.raises(F.FDError, match="maturity amount"):
        F.check(dep(maturity_amount=109_000.0))
    with pytest.raises(F.FDError, match="cumulative"):
        dep(payout="quarterly")
    with pytest.raises(F.FDError, match="closed_on"):
        dep(status="closed")


# --- facts vs estimates ----------------------------------------------------------------------------------------------

def test_value_is_the_bank_figure_on_the_anchor_day_and_an_estimate_after():
    d = dep(anchor_date=date(2025, 5, 10), anchor_value=102_600.0)
    assert F.value(d, date(2025, 5, 10)) == 102_600.0
    v = F.value(d, date(2025, 7, 10))
    assert isinstance(v, est.Estimate)
    with pytest.raises(TypeError):
        float(v)
    k = 102_600.0 / F.contract_value(d, date(2025, 5, 10))
    assert v.value == pytest.approx(k * F.contract_value(d, date(2025, 7, 10)))      # no FY end in between
    with pytest.raises(F.FDError, match="before the bank's reading"):
        F.value(d, date(2025, 4, 20))


def test_tds_is_withdrawn_at_each_fy_end_so_the_payout_is_below_the_contract():
    d = dep(anchor_date=date(2025, 1, 10), anchor_value=100_000.0)
    k, steps = F._projection(d, d.maturity)
    (t, interest, tds), = steps
    assert t == date(2025, 3, 31) and tds == pytest.approx(0.10 * interest)
    assert interest == pytest.approx(F.contract_value(d, t) - 100_000)
    p = F.maturity_payout(d)
    assert p.value < d.maturity_amount and p.horizon == "2026-01-10"
    gross = k * F.contract_value(d, d.maturity)
    assert p.value == pytest.approx(gross - 0.10 * (gross - k * F.contract_value(d, date(2025, 4, 1))))


def test_a_closed_deposit_is_worth_nothing_after_closing():
    d = dep(status="closed", closed_on=date(2025, 6, 1), closing_amount=101_000.0)
    assert F.value(d, date(2025, 6, 1)) == 0.0


# --- interest per FY ---------------------------------------------------------------------------------------------------

def test_certificate_rows_are_facts_and_win():
    d = dep(anchor_date=date(2025, 5, 10), anchor_value=102_600.0)
    facts = {("0001", 2026): {"paid": 700.0, "accrued": 6_300.0, "tds": 700.0}}
    r = F.fy_interest(d, 2026, facts)
    assert r.source == "certificate" and r.interest == 7_000.0 and r.tds == 700.0


def test_estimate_for_the_anchor_year_and_refusal_before_it():
    d = dep(term_start=date(2025, 1, 10), anchor_date=date(2025, 5, 10), anchor_value=102_600.0)
    r = F.fy_interest(d, 2026, {})
    k = 102_600.0 / F.contract_value(d, date(2025, 5, 10))
    want = k * (F.contract_value(d, date(2026, 1, 10)) - F.contract_value(d, date(2025, 4, 1)))
    assert r.source == "estimate" and r.interest.value == pytest.approx(want) and r.tds.value == pytest.approx(0.1 * want)
    with pytest.raises(F.FDError, match="no certificate row"):
        F.fy_interest(d, 2025, {})
    assert F.fy_interest(d, 2027, {}) is None                       # matured before FY2026-27


def test_a_renewal_inside_the_fy_counts_the_previous_term_too():
    renewed = dep(term_start=date(2025, 7, 1), maturity=date(2026, 7, 1), principal=110_000.0,
                  maturity_amount=round(110_000 * 1.02 ** 4, 2), opened=date(2024, 7, 1),
                  anchor_date=date(2025, 7, 1), anchor_value=110_000.0, prev_rate=0.08)
    r = F.fy_interest(renewed, 2026, {})
    g = 1.02 ** ((date(2025, 7, 1) - date(2025, 4, 1)).days / (365 / 4))
    v0 = 110_000 / (g - 0.10 * (g - 1))
    new_term = F.contract_value(renewed, date(2026, 3, 31)) - 110_000
    assert r.interest.value == pytest.approx(v0 * (g - 1) + new_term)
    fresh = dep(term_start=date(2025, 7, 1), maturity=date(2026, 7, 1), maturity_amount=round(100_000 * 1.02 ** 4, 2),
                anchor_date=date(2025, 7, 1), anchor_value=100_000.0)
    assert F.fy_interest(fresh, 2026, {}).interest.value == pytest.approx(F.contract_value(fresh, date(2026, 3, 31)) - 100_000)


def test_year_totals_keep_certified_rows_of_deposits_closed_before_the_file():
    d = dep(anchor_date=date(2025, 5, 10), anchor_value=102_600.0)
    facts = {("0001", 2026): {"paid": 0.0, "accrued": 7_000.0, "tds": 700.0},
             ("0999", 2026): {"paid": 4_000.0, "accrued": 0.0, "tds": 400.0}}
    t = F.year_totals([d], 2026, facts)
    assert t["certified_interest"] == 11_000.0 and t["certified_tds"] == 1_100.0 and not t["is_estimate"]


# --- ladder and warnings -------------------------------------------------------------------------------------------------

def test_warnings_flag_renewal_instructions_and_near_maturities():
    a = dep(fd_id="A", anchor_date=date(2025, 11, 1), anchor_value=106_000.0, instruction="Credit to Account")
    b = dep(fd_id="B", anchor_date=date(2025, 11, 1), anchor_value=106_000.0, instruction="Auto Renewal",
            maturity=date(2026, 1, 10), bank="HDFC")
    w = F.warnings([a, b], date(2025, 12, 1))
    assert any("HDFC FD of Rs 100,000" in x and "renew" in x for x in w)
    assert not any("FD A" in x or "FD B" in x for x in w)          # never the deposit's number (S62)
    assert sum("matures in 40 days" in x for x in w) == 2
    assert not any("renew" in x for x in F.warnings([a], date(2025, 12, 1)))
    assert [r["fd_id"] for r in F.ladder([b, a], date(2025, 12, 1))] == ["A", "B"]


# --- file, store, tax ------------------------------------------------------------------------------------------------------

TOML = """as_of = 2025-05-10
[[fd]]
id = "0001"
principal = 100000.0
rate_pct = 8.0
start = 2025-01-10
maturity = 2026-01-10
maturity_amount = 108243.22
current_value = 102600.0
maturity_instruction = "Default"
[[fd]]
id = "0002"
status = "closed"
principal = 100000.0
rate_pct = 8.0
start = 2025-01-10
maturity = 2026-01-10
maturity_amount = 108243.22
closed_on = 2025-03-01
closing_amount = 101000.0
"""


def test_file_store_round_trip_and_duplicate_ids(tmp_path):
    p = tmp_path / "fd.toml"
    p.write_text(TOML)
    fds = F.from_toml(p)
    assert [f.fd_id for f in fds] == ["0001", "0002"] and fds[0].anchor_value == 102_600.0 and fds[1].anchor_date is None
    con = store.connect(tmp_path / "pm.duckdb")
    assert F.save(con, fds, "test") == 2 and F.load(con) == sorted(fds, key=lambda f: (f.maturity, f.fd_id))
    F.save_interest(con, 2025, [{"fd_id": "0001", "paid": 0.0, "accrued": 1_000.0, "tds": 100.0}], "cert")
    assert F.interest_facts(con) == {("0001", 2025): {"paid": 0.0, "accrued": 1_000.0, "tds": 100.0}}
    p.write_text(TOML.replace('id = "0002"', 'id = "0001"'))
    with pytest.raises(F.FDError, match="twice"):
        F.from_toml(p)


def test_fd_interest_and_tds_enter_the_year_tax():
    base = pr.year_tax(EventLog([]), 2027, lambda i, h: "EQUITY")
    with_fd = pr.year_tax(EventLog([]), 2027, lambda i, h: "EQUITY", extra_interest=900_000.0, extra_tds=90_000.0)
    assert with_fd["inputs"].interest_gross == base["inputs"].interest_gross + 900_000.0
    assert with_fd["inputs"].tds_credit == 90_000.0
    assert with_fd["regimes"]["new"].slab_income == pytest.approx(900_000.0)


# --- certificate ------------------------------------------------------------------------------------------------------------

CERT = """This is to certify that undernoted amount of interest has been paid by us on the TDR/STDR/SB/FCNR/Recurring A/CS
in the name of Mr. SYNTHETIC (CUSTOMER NO :00000000000) for the financial year ended 31st March 2026.
000000000001111 13036 SB 2,00,000.00 5,000.00 100.00 0.00 0.00 INR
000000000002222 13036 FD 10,00,000.00 7,000.00 63,000.00 7,000.00 0.00 INR
000000000003333 13036 FD 0.00 40,000.00 0.00 4,000.00 0.00 INR
TOTAL 52,000.00 63,100.00 11,000.00 0.00
"""


def test_certificate_rows_add_up_and_sb_is_left_to_the_bank_statement():
    fy, rows = cert.parse_text(CERT)
    assert fy == 2026 and [r.kind for r in rows] == ["SB", "FD", "FD"]
    assert cert.fd_rows(rows) == [{"fd_id": "2222", "paid": 7_000.0, "accrued": 63_000.0, "tds": 7_000.0},
                                  {"fd_id": "3333", "paid": 40_000.0, "accrued": 0.0, "tds": 4_000.0}]


@pytest.mark.parametrize("mutate,msg", [
    (lambda s: s.replace("TOTAL 52,000.00", "TOTAL 53,000.00"), "interest paid"),
    (lambda s: s.replace("financial year ended 31st March 2026", "period"), "not an SBI interest certificate"),
    (lambda s: s.replace("000000000003333", "000000000012222"), "collide"),
    (lambda s: "\n".join(l for l in s.splitlines() if not l.startswith("TOTAL")), "no TOTAL"),
])
def test_a_certificate_that_does_not_add_up_is_refused(mutate, msg):
    with pytest.raises(cert.CertificateError, match=msg):
        cert.parse_text(mutate(CERT))
