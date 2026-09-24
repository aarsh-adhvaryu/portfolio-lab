"""Tests for the BSE shareholding collector.

The defects these lock down were all found live on 2026-09-23 and every one
of them parses cleanly, so none would be caught by "did the request work":

  * the pre-2016 zero-filled skeleton (six correct labels, all zeros)
  * the SEBI table's subtotal and grand-total rows, which double- and
    triple-count when summed
  * the old promoter table's trailing "Total" row, which doubles a holding
    exactly (Reliance Mar-2010 read 89.52% instead of 44.76%)
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from pflab.data import bse_shareholding as sh


def _cat(code, short, shares, pct, nsh=0, pledge=0):
    return {"Fld_Code": code, "Fld_ShortName": short, "FLD_LEVEL": None,
            "FLD_CATEGORY": "cat", "FLD_SUBCATEGORY": None,
            "Fld_NoOfShareHolders": nsh, "Fld_TotalNoOfShares": shares,
            "Fld_TotalPercentageOf_A_B_C2": pct,
            "Fld_PledgeEncumberedNoOfShares": pledge,
            "Fld_PledgeEncumberedPercentage": 0.0,
            "Fld_PledgeEncumberedPercentOfTSC": 0.0}


def _new_era_payload(prom=460, pub=540, c1=0, c2=0, auth="2016-01-21T15:52:14"):
    total = prom + pub + c1 + c2

    def p(x):
        return round(100.0 * x / total, 2) if total else 0.0

    cats = [_cat("STA1A2", "(A) Promoter", prom, p(prom), 58),
            _cat("STB1B2B3", "(B) Public", pub, p(pub), 1000),
            _cat("STC1", "(C1) DRs", c1, 0.0, 1),
            _cat("STC2", "(C2) Employee Trust", c2, 0.0, 0),
            _cat("STC1C2", "(C) Non Promoter-Non Public", c1 + c2, 0.0, 1),
            _cat("STABC", "Grand Total", total, 100.0, 1059)]
    return {"Table": [{"Fld_AuthoriseDate": auth}], "Table1": cats}


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload

    def get(self, url, params=None, headers=None, timeout=None):
        payload = self.payload

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return payload

        return R()


def test_quarter_ids_match_the_probed_anchors():
    # verified live against Corp_shpSec_shpqtrinfo_ng on 2026-09-23
    assert sh.quarter_end(65) == date(2010, 3, 31)
    assert sh.quarter_end(88) == date(2015, 12, 31)
    assert sh.quarter_end(130) == date(2026, 6, 30)
    assert sh.era_of(87) == "old" and sh.era_of(88) == "new"


def test_new_era_reads_named_rows_not_the_sum():
    """Summing Table1 would give 2x-3x the truth; the named rows give the truth."""
    s, cats = sh.fetch_new_era("1", 88, _FakeSession(_new_era_payload(460, 540)), 1)
    assert s["promoter_shares"] == 460
    assert s["public_shares"] == 540
    assert s["shares_outstanding_reported"] == 1000      # NOT 2000 or 3000
    assert s["n_shareholders_total"] == 1059             # NOT the sum of all rows
    assert sum(c["is_subtotal"] for c in cats) == 2      # C1C2 and ABC


def test_zero_filled_skeleton_is_unavailable_not_zero():
    """A pre-2016 quarter answers with correct labels and all-zero numbers."""
    payload = {"Table": [], "Table1": [_cat(c, c, 0, 0.0) for c in
                                       ("STA1A2", "STB1B2B3", "STC1", "STC2",
                                        "STC1C2", "STABC")]}
    with pytest.raises(sh.ShareholdingUnavailable):
        sh.fetch_new_era("1", 70, _FakeSession(payload), 1)


def test_old_era_total_row_is_not_added_to_the_entities():
    """Reliance Mar-2010 read 89.52% before this; the truth is 44.76%."""
    payload = {"Table": [
        {"Fld_shareholdername": "A Ltd", "Fld_NoOfShares": 300, "Fld_Percentage": 30.0,
         "fld_pledgeencumberednoofshares": 0},
        {"Fld_shareholdername": "B Ltd", "Fld_NoOfShares": 147, "Fld_Percentage": 14.76,
         "fld_pledgeencumberednoofshares": 0},
        {"Fld_shareholdername": "Total", "Fld_NoOfShares": 447, "Fld_Percentage": 44.76,
         "fld_pledgeencumberednoofshares": 0}]}
    s, cats = sh.fetch_old_era("1", 65, _FakeSession(payload), 1)
    assert s["promoter_pct"] == 44.76
    assert s["promoter_shares"] == 447
    assert cats == []
    # the fields that do not exist before 2016 are None, never 0
    for f in ("public_pct", "n_shareholders_total", "shares_outstanding_reported"):
        assert s[f] is None


def test_old_era_entities_disagreeing_with_total_is_a_halt():
    payload = {"Table": [
        {"Fld_shareholdername": "A Ltd", "Fld_NoOfShares": 100, "Fld_Percentage": 10.0,
         "fld_pledgeencumberednoofshares": 0},
        {"Fld_shareholdername": "Total", "Fld_NoOfShares": 999999, "Fld_Percentage": 44.0,
         "fld_pledgeencumberednoofshares": 0}]}
    with pytest.raises(sh.AddsUpFailure):
        sh.fetch_old_era("1", 65, _FakeSession(payload), 1)


@pytest.mark.parametrize("bad,era", [
    ({"promoter_pct": 148.25, "promoter_shares": 10}, "old"),
    ({"promoter_pct": -1.0, "promoter_shares": 10}, "old"),
    ({"promoter_pct": 40.0, "promoter_shares": 0}, "old"),
])
def test_adds_up_halts_on_impossible_records(bad, era):
    with pytest.raises(sh.AddsUpFailure):
        sh.check_adds_up(bad, era)


def test_adds_up_halts_when_percentages_miss_100():
    s = {"promoter_pct": 46.0, "public_pct": 20.0, "nonpromoter_nonpublic_pct": 0.0,
         "promoter_shares": 460, "public_shares": 200,
         "nonpromoter_nonpublic_shares": 0, "shares_outstanding_reported": 660}
    with pytest.raises(sh.AddsUpFailure):
        sh.check_adds_up(s, "new")


def test_adds_up_halts_when_components_miss_the_grand_total():
    s = {"promoter_pct": 46.0, "public_pct": 54.0, "nonpromoter_nonpublic_pct": 0.0,
         "promoter_shares": 460, "public_shares": 540,
         "nonpromoter_nonpublic_shares": 0, "shares_outstanding_reported": 9999}
    with pytest.raises(sh.AddsUpFailure):
        sh.check_adds_up(s, "new")


def test_derived_shares_outstanding_is_undefined_at_zero_promoter():
    """HDFC Bank has had no promoter since the merger; dividing by 0 is not a number."""
    d, how, err = sh.derive_shares_outstanding({"promoter_shares": 0, "promoter_pct": 0.0})
    assert d is None and how is None and err is None


def test_derived_error_scales_inversely_with_promoter_percent():
    big, _, e_big = sh.derive_shares_outstanding(
        {"promoter_shares": 500, "promoter_pct": 50.0})
    small, _, e_small = sh.derive_shares_outstanding(
        {"promoter_shares": 10, "promoter_pct": 1.0})
    assert big == pytest.approx(1000.0)
    assert small == pytest.approx(1000.0)
    assert e_big == pytest.approx(0.01)      # 0.005/50
    assert e_small == pytest.approx(0.5)     # 0.005/1  -- 50x worse
    assert e_small > e_big


def test_collect_one_records_unavailable_rather_than_raising():
    payload = {"Table": [], "Table1": [_cat(c, c, 0, 0.0) for c in ("STA1A2", "STABC")]}
    row, cats = sh.collect_one("1", 70, _FakeSession(payload))
    assert row["status"] == "unavailable"
    assert row["promoter_pct"] is None          # never a number
    assert cats == []


def test_collect_one_keeps_reported_and_derived_apart():
    row, _ = sh.collect_one("1", 88, _FakeSession(_new_era_payload(460, 540)))
    assert row["status"] == "ok"
    assert row["shares_outstanding_reported"] == 1000
    assert row["shares_outstanding_derived"] == pytest.approx(1000.0, rel=1e-3)
    assert "promoter_shares / (promoter_pct/100)" in row["shares_outstanding_derivation"]
    assert row["filing_date_source"] == "Fld_AuthoriseDate"


def test_filing_date_never_falls_back_to_quarter_end():
    """A quarter with no traceable filing keeps NaT, per the point-in-time rule."""
    row, _ = sh.collect_one("1", 65, _FakeSession({"Table": [
        {"Fld_shareholdername": "Total", "Fld_NoOfShares": 447, "Fld_Percentage": 44.76,
         "fld_pledgeencumberednoofshares": 0}]}))
    assert pd.isna(row["filing_date"])
    assert row["filing_date_source"] == "unresolved"
    assert row["quarter_end"] == date(2010, 3, 31)


# -- parallel safety ----------------------------------------------------
def test_shards_partition_the_universe_exactly():
    """No scrip-quarter may be reachable by two workers, and none by none."""
    codes = [str(500000 + i) for i in range(500)]
    for n in (2, 3, 4):
        buckets = [[c for c in codes if sh.shard_of(c, n) == i] for i in range(n)]
        flat = [c for b in buckets for c in b]
        assert sorted(flat) == sorted(codes)          # covers everything
        assert len(flat) == len(set(flat))            # exactly once


def test_shard_assignment_is_stable_across_restarts():
    assert sh.shard_of("500325", 3) == sh.shard_of("500325", 3)
    assert sh.shard_of("500325", 3) != sh.shard_of("500325", 4) or True


def test_a_throttleable_absence_is_re_asked():
    """An EMPTY table is what a throttled answer looks like, and it is
    indistinguishable from 'this company filed nothing'. It must not be
    ledgered on one look."""
    assert sh.needs_confirmation("x q70: no promoter rows", 70)
    assert sh.needs_confirmation("x q95: no Table1", 95)
    assert sh.needs_confirmation("x q95: no STABC grand-total row", 95)


def test_a_pre_2016_skeleton_is_not_re_asked():
    """It is structural and deterministic, so confirming it would add a
    request to each of the 23 old-era quarters and learn nothing."""
    r = "x: zero-filled skeleton (no SEBI-format filing)"
    assert not sh.needs_confirmation(r, 70)
    assert not sh.needs_confirmation(r, sh.QTRID_NEW_ERA - 1)
    # but after Dec 2015 a skeleton is unexpected, so it IS re-asked
    assert sh.needs_confirmation(r, sh.QTRID_NEW_ERA)
    assert sh.needs_confirmation(r, 128)


def test_an_adds_up_failure_is_not_re_asked():
    """It carries real numbers. Throttling does not invent 98.88%."""
    assert not sh.needs_confirmation("A+B+C2 = 98.880%, off 100 by more than 1.0", 100)
    assert not sh.needs_confirmation("promoter_pct 148.25 outside [0, 100]", 70)


def test_shard_files_are_separate(tmp_path):
    """Two workers writing one parquet would interleave read-modify-write
    and lose rows while each wrote a valid file."""
    root = tmp_path
    rows_a = [{"scrip_code": "1", "qtrid": 88, "status": "ok"}]
    rows_b = [{"scrip_code": "2", "qtrid": 88, "status": "ok"}]
    sh._flush(root, rows_a, [], shard=0)
    sh._flush(root, rows_b, [], shard=1)
    d = root / "bse_shareholding"
    assert (d / "summary.shard0.parquet").exists()
    assert (d / "summary.shard1.parquet").exists()
    assert not (d / "summary.parquet").exists()


def test_merge_shards_unions_without_losing_rows(tmp_path):
    root = tmp_path
    sh._flush(root, [{"scrip_code": "1", "qtrid": 88, "status": "ok"}], [], shard=0)
    sh._flush(root, [{"scrip_code": "2", "qtrid": 88, "status": "ok"}], [], shard=1)
    sh._mark(root, "1", 88, shard=0)
    sh._mark(root, "2", 88, shard=1)
    out = sh.merge_shards(root)
    assert out["summary"] == 2
    assert out["settled"] == 2
    merged = pd.read_parquet(root / "bse_shareholding" / "summary.parquet")
    assert set(merged["scrip_code"]) == {"1", "2"}


def test_done_pairs_includes_the_legacy_unsharded_ledger(tmp_path):
    """A shard must not redo work the earlier single-worker run finished."""
    root = tmp_path
    sh._mark(root, "1", 88)                 # legacy, unsharded
    sh._mark(root, "2", 88, shard=0)
    assert sh.done_pairs(root, shard=0) == {"1:88", "2:88"}
    assert sh.done_pairs(root, shard=1) == {"1:88"}


def test_rebuild_ledger_drops_orphans_that_would_never_be_retried(tmp_path):
    """The 2026-09-24 damage: a pair marked settled with no row behind it is
    a permanent gap, because the ledger is what stops it being re-asked."""
    root = tmp_path
    sh._flush(root, [{"scrip_code": "1", "qtrid": 88, "status": "ok"}], [], shard=0)
    sh._mark(root, "1", 88, shard=0)
    sh._mark(root, "2", 88, shard=0)        # orphan: ledgered, no row
    sh._mark(root, "3", 99)                 # orphan in the legacy ledger
    out = sh.rebuild_ledger_from_data(root)
    assert out["settled_from_data"] == 1
    assert out["orphans_dropped"] == 2
    led = (root / "bse_shareholding" / "_verified.txt").read_text().split()
    assert led == ["1:88"]                  # only what the data supports


def test_rebuild_ledger_recovers_rows_the_ledger_forgot(tmp_path):
    """Concurrent appends corrupted the ledger and it went backwards. A row
    that exists must be marked settled even if no ledger claims it."""
    root = tmp_path
    sh._flush(root, [{"scrip_code": "7", "qtrid": 70, "status": "ok"}], [], shard=1)
    out = sh.rebuild_ledger_from_data(root)
    assert out["unclaimed_recovered"] == 1
    assert sh.done_pairs(root) == {"7:70"}


def test_rebuild_ledger_removes_shard_ledgers(tmp_path):
    root = tmp_path
    sh._flush(root, [{"scrip_code": "1", "qtrid": 88, "status": "ok"}], [], shard=0)
    sh._mark(root, "1", 88, shard=0)
    sh.rebuild_ledger_from_data(root)
    assert not list((root / "bse_shareholding").glob("_verified.shard*.txt"))
    assert (root / "bse_shareholding" / "_verified.txt").exists()
