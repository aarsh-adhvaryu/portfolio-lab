"""S82 cut agent: the small fixes (C12) and the writer-less code that went (C11). Synthetic."""
from __future__ import annotations

from datetime import date

import pytest
import requests

from pflab.data import gdelt_s79b, index_membership
from pflab.paper import book
from pflab.tax import rules


class _Resp:
    status_code = 200
    content = b"PK-zip"


class _HangingSession:
    """A server that never answers: a call WITHOUT a (connect, read) timeout would wait for ever; with one it raises like requests does."""

    def __init__(self):
        self.timeouts = []

    def get(self, url, timeout=None, **kw):
        self.timeouts.append(timeout)
        if timeout is None:
            raise AssertionError("a request without a timeout would hang for ever")
        raise requests.ConnectTimeout("no answer")


def test_gdelt_requests_carry_the_module_timeout_and_a_hang_ends(monkeypatch):
    assert gdelt_s79b.TIMEOUT == (20, 60)
    monkeypatch.setattr(gdelt_s79b.time, "sleep", lambda s: None)
    s = _HangingSession()
    assert gdelt_s79b._get("http://x/1.zip", s, tries=3) is None                     # gives up, does not hang
    assert s.timeouts == [(20, 60)] * 3


def test_gdelt_a_good_answer_still_passes_through(monkeypatch):
    class Ok:
        def get(self, url, timeout=None, **kw):
            assert timeout == gdelt_s79b.TIMEOUT
            return _Resp()
    assert gdelt_s79b._get("http://x/1.zip", Ok()) == b"PK-zip"


def test_tax_of_reads_the_exemption_from_the_dated_row_not_a_literal(monkeypatch):
    g = {"lt_eq": 300_000.0}
    d = date(2026, 11, 2)
    assert book.tax_of(g, d) == pytest.approx(0.125 * (300_000 - rules.exemption(2027)))      # today's row (Rs 1.25 lakh)
    seen = []

    def other_row(fy, *a, **k):
        seen.append(fy)
        return 200_000.0
    monkeypatch.setattr(rules, "exemption", other_row)                                       # a different dated row
    assert book.tax_of(g, d) == pytest.approx(0.125 * 100_000)
    assert seen == [2027]                                                                    # the FY of the day (the year it ends)
    assert book.tax_of(g, date(2027, 2, 1)) == pytest.approx(0.125 * 100_000) and seen[-1] == 2027
    assert book.tax_of(g, date(2027, 4, 2)) == pytest.approx(0.125 * 100_000) and seen[-1] == 2028


def test_tax_of_before_the_first_row_is_a_labelled_estimate_not_a_crash():
    assert book.tax_of({"lt_eq": 300_000.0}, date(2012, 6, 1)) == pytest.approx(0.125 * (300_000 - book.LT_EXEMPT))


def test_the_dead_membership_session_is_gone():
    assert not hasattr(index_membership, "_session")


def test_the_deleted_writer_less_code_is_gone():
    from pflab.hq import board, cases, keeper, scorecard
    from pflab.paper import allocation, benchmark, cadence
    for mod, names in ((keeper, ("add_prediction", "score_due", "base_rate", "scorecard_text")), (scorecard, ("HORIZONS", "KIND")),
                       (cases, ("discover", "brief", "defer")), (board, ("run_parallel", "WORKERS")),
                       (allocation, ("dossier_text", "playbook_text")), (benchmark, ("dossier_text",)), (cadence, ("lessons_text", "acted_since"))):
        for n in names:
            assert not hasattr(mod, n), f"{mod.__name__}.{n} should have been deleted"
    assert hasattr(allocation, "propose_allocation")                                         # the lab's tool still uses it
