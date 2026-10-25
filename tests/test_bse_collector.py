"""BSE collector integrity (2026-09-22). No network: a fake session."""
from datetime import date

import pandas as pd
import pytest

from pflab.data import bse_announcements as B


class _Resp:
    def __init__(self, j): self._j = j
    def raise_for_status(self): pass
    def json(self): return self._j


class _Session:
    """Serves page p of a day from a list of per-page answers."""
    def __init__(self, pages): self.pages = pages
    def get(self, url, params=None, headers=None, timeout=None):
        return _Resp(self.pages[params["pageno"] - 1])


def _rows(n, start=0):
    return [{"NEWSID": f"id{i}", "SCRIP_CD": 500000 + i, "HEADLINE": f"h{i}"}
            for i in range(start, start + n)]


def _page(rows, total):
    return {"Table": rows, "Table1": [{"ROWCNT": total}]}


def test_a_full_multi_page_day_is_kept():
    s = _Session([_page(_rows(50), 120), _page(_rows(50, 50), 120), _page(_rows(20, 100), 120)])
    assert len(B.fetch_day(date(2025, 7, 15), s, page_sleep=0)) == 120


def test_a_throttled_blank_row_is_refused_not_written():
    """The 2026-09-22 failure: one all-null row where the day should be."""
    s = _Session([{"Table": [{"NEWSID": None, "SCRIP_CD": None}], "Table1": [{"ROWCNT": 1239}]}])
    with pytest.raises(B.IncompleteDay, match="no NEWSID"):
        B.fetch_day(date(2025, 7, 15), s, page_sleep=0)


def test_a_day_that_stops_paging_early_is_refused():
    """An empty page mid-day would otherwise have saved a short day silently."""
    s = _Session([_page(_rows(50), 120), _page([], 120)])
    with pytest.raises(B.IncompleteDay, match="collected 50 of 120"):
        B.fetch_day(date(2025, 7, 15), s, page_sleep=0)


def test_a_genuinely_empty_day_is_empty_and_a_countless_answer_is_not_trusted():
    assert B.fetch_day(date(2010, 1, 3), _Session([_page([], 0)]), page_sleep=0) == []
    with pytest.raises(B.IncompleteDay, match="ROWCNT"):
        B.fetch_day(date(2010, 1, 3), _Session([{"Table": []}]), page_sleep=0)


def test_verify_file_catches_a_blank_or_short_saved_day(tmp_path):
    good, blank = tmp_path / "g.parquet", tmp_path / "b.parquet"
    B.normalize(_rows(3)).to_parquet(good, index=False)
    B.normalize([{"SCRIP_CD": None}]).to_parquet(blank, index=False)
    s = _Session([_page(_rows(3), 3)])
    assert B.verify_file(date(2025, 1, 2), good, s) is True
    assert B.verify_file(date(2025, 1, 2), blank, s) is False
    assert B.verify_file(date(2025, 1, 2), good, _Session([_page(_rows(3), 5)])) is False


def test_a_throttled_check_leaves_the_day_unverified_and_retries_it(tmp_path, monkeypatch):
    """A throttled answer to the CHECK must neither delete a good file nor
    mark it verified; the next pass checks it again."""
    d = date(2025, 1, 2)
    f = tmp_path / "bse_announcements" / "2025" / "2025-01-02.parquet"
    f.parent.mkdir(parents=True)
    B.normalize(_rows(3)).to_parquet(f, index=False)
    monkeypatch.setattr(B.requests, "Session", lambda: _Session([{"Table": []}]))
    st = B.collect(d, d, root=tmp_path, sleep=0, verify=True)
    assert st["unverified"] == 1 and f.exists()
    assert d.isoformat() not in B.verified_days(tmp_path)
    monkeypatch.setattr(B.requests, "Session", lambda: _Session([_page(_rows(3), 3)]))
    st = B.collect(d, d, root=tmp_path, sleep=0, verify=True)
    assert st["verified"] == 1 and d.isoformat() in B.verified_days(tmp_path)
    st = B.collect(d, d, root=tmp_path, sleep=0, verify=True)   # ledger: no request
    assert st["verified"] == 0 and st["unverified"] == 0


def test_a_newly_written_day_goes_straight_into_the_ledger(tmp_path, monkeypatch):
    d = date(2025, 1, 3)
    monkeypatch.setattr(B.requests, "Session", lambda: _Session([_page(_rows(2), 2)]))
    B.collect(d, d, root=tmp_path, sleep=0)
    assert d.isoformat() in B.verified_days(tmp_path)


def test_a_re_disseminated_announcement_counts_twice():
    """2015-08-29 (found 2026-09-23): BSE's ROWCNT counts a second, later
    dissemination of the same NEWSID. Keying on NEWSID alone left the day
    one short of its own count on every pass, for ever."""
    rows = _rows(49) + [{"NEWSID": "dup", "SCRIP_CD": 532141, "HEADLINE": "results",
                         "DissemDT": "2015-08-29T14:58:51.1"},
                        {"NEWSID": "dup", "SCRIP_CD": 532141, "HEADLINE": "results",
                         "DissemDT": "2015-08-29T15:10:13.483"}]
    s = _Session([_page(rows, 51)])
    assert len(B.fetch_day(date(2015, 8, 29), s, page_sleep=0)) == 51


def test_an_identical_repeat_of_a_row_is_still_deduplicated():
    """Paging overlap must not inflate a day: same NEWSID and same DissemDT."""
    r = {"NEWSID": "x", "SCRIP_CD": 1, "HEADLINE": "h", "DissemDT": "2015-08-29T10:00:00"}
    s = _Session([_page([r, dict(r)], 1)])
    assert len(B.fetch_day(date(2015, 8, 29), s, page_sleep=0)) == 1
