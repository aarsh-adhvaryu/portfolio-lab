# Point-in-time index membership: what NSE publishes, and what it costs

Survey 2026-09-17, revised 2026-09-18. Written for charter E1b §3/§4 before
any E1b run. Nothing here is a strategy result; it is a data finding.

## Why this matters

E1b replaces E1's "top 500 by traded value" with "constituents of the Nifty
200 as of M". That is only a different experiment if membership is
point-in-time. Running today's list over 2007–2021 would make E1b a backtest
of the companies that are in the index *now* — the survivorship error
principle 6 forbids, and one that reliably produces a flattering result. So
the question is never "can we get a Nifty 200 list" but "can we get the list
as it stood at each month-end".

---

## 1. The source that looks right and is not

NSE's F&O circular series **"Change in the Constituents of Indices"**
(`nseindia.com/api/circulars`, matched on subject, filed under the Futures &
Options department) is the obvious source. All 98 of them, 2006–2026, were
indexed and read. They contain:

| index | sections found | years |
|---|---|---|
| Nifty 200 | **0** | — |
| Nifty 500 | 3 | 2006–2007 only |
| Nifty 100 | 10 | 2006–2008 only |
| Nifty Midcap 100 | 3 | 2006–2007 only |

These circulars exist *because an index change moves the F&O contracts*, so
they cover only derivative-eligible indices — Nifty 50, Bank Nifty, Nifty
Midcap Select, Nifty Financial Services and so on. Nifty 200 and Nifty 500
have no derivatives and are therefore never in them.

The earlier version of this document proposed sanctioning a PDF reader to
parse those 68 PDF circulars. That was the right call for a different reason
than stated: the reader is needed, but not for these files.

## 2. The source that is right

**NSE Indices Limited publishes every index change as a press release.**

- Listing: `https://www.niftyindices.com/media` — plain HTML; links are
  `/Press_Release/ind_prs<DDMMYYYY>.pdf`.
- **1,486 releases, 1998–2026.** All downloaded and cached under
  `PFLAB_DATA_DIR/index_membership/raw/press_releases/`.
- They do carry the broad indices, continuously.

The file date is the **announcement** date. The date that matters is the
**effective** date stated inside the text, typically three to five weeks
later. Using the wrong one puts every change weeks early.

## 3. Reading them: seven ways to be silently wrong

Every one of these was found by a check failing, not by reading code. Each
produced a *clean parse of the wrong thing*, which is the only failure mode
that could actually reach the portfolio.

1. **Reading order.** `pypdf` returns some older releases with whole sections
   ahead of their own headings, so a company is attached to whichever heading
   happens to precede it. Detected by `validate` (a row before the first
   heading; a company repeated inside one index) and retried with
   `pdfplumber`, which is the only use CLAUDE.md 7 sanctions for it.
2. **Faux-bold doubling.** pdfplumber renders bold runs as doubled glyphs
   (`IInnddiiaabbuullllss`). De-doubling must be decided **per line, not per
   word**: with a per-word rule `"77,"` is odd-length once the comma is
   attached, survives undoubled, and `"December 77, 2011"` fails to parse as a
   date — so the change silently takes the announcement date, a week early.
3. **The noun changes.** "company/companies" (most), "security/securities"
   (~1,460 occurrences) and "scrip/scrips" (~112) are all in use, sometimes in
   the same year. Matching only the first returned **zero Nifty 200 changes
   for 2016**, a semi-annual review year inside E1b's development window.
4. **The verb changes.** "is being excluded", "are being excluded" and "will
   be excluded" are all in use. Missing the third cost most of 2008.
5. **The third column is not always the symbol.** Releases up to about 2009
   print `Sr. No. | Company Name | Industry`. Read as a symbol, Bank of Punjab
   resolves to "BANKS" and the industry stays glued to the company name, so
   the row keys to nothing. The header decides which column is which.
6. **Unrecognised headings must still close a section.** "4) CNX Realty
   Index" is not one of ours, but if it does not end the section above it its
   companies are read as part of that index.

And one that is not a parsing problem at all:

7. **The index was renamed mid-history.** NSE's 2016-02-22 restructure
   release states it outright: *"rebranding of existing Nifty Midcap 100 and
   Nifty Smallcap 100 indices … published under the new names Nifty Free
   Float Midcap 100 and Nifty Free Float Smallcap 100."* Without that alias,
   Nifty Midcap 100 had **zero changes in both 2016 and 2017**. A distinct
   **Nifty *Full* Midcap 100** was launched in the same restructure and must
   not be matched.

## 4. Coverage: when each index's history begins

Counted by effective date, from the parsed archive.

| index | history begins | continuous from |
|---|---|---|
| Nifty 500 | 2003-01-21 | 2003 |
| Nifty Midcap 100 | 2005-12-08 | 2005 |
| Nifty 100 | 2006-06-26 | 2006 |
| **Nifty 200** | **2011-11-22** | 2011 |

**Nifty 200 did not exist before 2011.** No source can say who was in it in
2007, because nobody was.

## 5. Why the window is still 2007

NSE's methodology document defines Nifty 200 exactly:

> **Nifty 200** — Constituents forming part of Nifty 100 and Nifty Midcap 100

with no further selection criterion and a blank "maximum replacements per
review". It is a union, not a selection from a union. Both parents' histories
begin **before** E1b's development start of 2007-01-01, so the pre-2011 years
are *derived from the index's own definition* rather than carried back from a
modern list.

`index_membership.build_nifty200` therefore builds both eras and splices
them, recording in the manifest which years are reconstructed and which are
published — they are not equally strong evidence and the verdict must be able
to say so.

**Carry-back for E1b's window is zero.** Nifty 100's history starts
2006-06-26 and Nifty Midcap 100's 2005-12-08, both before 2007-01-01.
`allow_long_carry_back` stays off for the window E1b actually runs.
(Measured against an arbitrary 2005-01-01 start the spans are 541 and 341
days respectively; against 2007-01-01 both are negative.)

So **E1b's window stays 2007–2016 development / 2017–2021 validation**, and
E1b §4 did not need amending. This was recorded in E1b §10 on 2026-09-17.

## 6. Keying a name to a security

From 2011 the releases carry a **Symbol** column, so §3's original
"mapped to ISIN by symbol at that date" works directly. Before that they
print the company name only, which is why §3 was amended.

`data/index_membership/name_map.parquet` — 4,063 rows — is built from:

1. the **corporate-actions feed** (name + symbol + ISIN + date on one row,
   42k rows from 2004) — the only source that ties all three together at a
   point in time, so it wins;
2. the **equity master** `EQUITY_L.csv` (name, symbol, ISIN) — authoritative
   but present-tense, so it never overrides (1);
3. the **current index lists** (name, ISIN).

Resolution is **name → symbol → ISIN-at-date**, not name → ISIN. That order
matters: 579 of 3,324 normalised names carry more than one ISIN, but only 114
carry more than one symbol, because a split issues the same company a new
ISIN. Going through the symbol first collapses four fifths of the ambiguity
and hands the date to the existing date-ranged map, which is CLAUDE.md 8 done
properly.

Ambiguity is never broken by a coin flip. Anything that does not resolve to
exactly one security is written to `docs/data/index_name_unresolved.md` for
The investor to verify by hand, the way `symbol_isin.VERIFIED_STITCHES` is verified.
Per §3 as amended, **a year with more than 2% of its changes unresolved halts
the build.**

## 7. The check that decides whether any of this is usable

Each of these indices holds a **fixed number of names by construction**. A
correct reconstruction therefore holds exactly that many on *every* date, and
`index_membership.count_check` reports where it does not. This needs no
external answer key and it is the real test of the parse.

Two walk-back bugs were found by it and fixed:

- **Keying on symbol.** A name renamed between the change and today never
  matched its own entry, so the walk emitted a second window instead of
  closing the first. The key is now a company id stable across renames and
  splits.
- **Phantom open windows.** An inclusion for a name the walk had no record of
  was emitted with `to_date=None` — a name that joins and never leaves,
  inflating every later date by one, invisibly. Those are now *recorded* as
  unmatched, and the count of them is the honest measure of how much of the
  history is still missing.

`unmatched_includes` and `unmatched_excludes` in each manifest are the number
of changes whose counterpart was never seen. They are the quantity to drive
to zero.

## 8. Status

See §9 for the current numbers. The tables are built and the pipeline is
reproducible:

    python tools/build_index_membership.py --download   # network
    python tools/build_index_membership.py --parse      # PDFs -> changes
    python tools/build_index_membership.py --build      # changes -> tables

`--build` exits non-zero while the count check fails.

### Known gaps that are not parser bugs

**Ten press releases are listed but not served.** The server returns its 404
page with HTTP **200**, so the bytes must be checked for `%PDF` rather than
the status code. Several fall in February, March or September — semi-annual
review months:

    2011-09-06  2012-03-02  2016-06-02  2017-02-02  2017-03-02
    2018-06-05  2019-07-16  2023-03-14  2026-03-24  2026-05-29

These are genuinely absent upstream; re-fetching with a fresh session returns
the same error page. Each one is some number of unmatched changes that no
amount of parser work will recover from this source.

## 9. Current numbers (run of 2026-09-18, after the listing cap and the captures)

### Two changes since the last revision

**Step 1 — every window is floored at the name's first traded session.** A
name cannot be an index member before it traded, and the walk back has no way
to know that on its own: a name whose inclusion was never published falls
through to the carry-back and is recorded as a member from the start of time,
which is how NYKAA and 360ONE ended up in the 2005 Nifty Midcap 100.

The floor needs **two keys**. On ISIN alone a split looks like a new listing —
Bombay Burmah's post-split ISIN first trades in 2012 while the symbol BBTC
goes back to the start of the panel — and 197 of Nifty 500's 1,292 windows are
in that position. The floor is the earlier of the ISIN's and the symbol's
first session, which neither a split nor a rename can move.

**Step 2 — the walk back is anchored on every archived list, not just on the
present.** 72 captures were found on the Internet Archive and 69 parsed; all
of them carry Symbol and ISIN, including the 2006 ones.

| index | captures | span |
|---|---|---|
| Nifty 100 | 21 | 2006-11-06 .. 2026-08-27 |
| Nifty 500 | 14 | 2006-11-08 .. 2026-08-27 |
| Nifty Midcap 100 | 10 | 2006-11-08 .. 2026-09-04 |
| Nifty 200 | 4 | 2017-11-13 .. 2023-08-11 |
| Nifty 50 / Next 50 (cross-check only) | 11 / 9 | 2016-03-10 .. 2026-08-27 |

Three captures could not be fetched. The replay host returns a transient 502
often enough to lose half of them on a single attempt, so the fetch retries.

With one anchor at the present, a change missed in 2013 is wrong for every
date before 2013 and the error compounds over twenty years. Anchored every
couple of years, the same missed change is wrong only inside its own segment.

### The check is now the captured list, not the count

Comparing counts catches a missing change. Comparing the reconstructed set to
the captured set on the same date catches a **wrong** one too, which counting
never can. The build gates on this and exits non-zero while it fails.

| index | exact-list | worst disagreement |
|---|---|---|
| **Nifty 200 (spliced)** | **4/4** | **0** |
| Nifty 100 | 21/21 | 0 |
| Nifty Midcap 100 | 10/10 | 0 |
| Nifty 500 | 13/14 | 1 name |

**The build exits zero.** Nifty 100 is also exactly Nifty 50 + Nifty Next 50
on the one date all three were captured together.

### Drift by year, after step 1 and step 2

Median month-end count minus the index's nominal size:

| year | Nifty 100 | Midcap 100 | Nifty 200 | Nifty 500 |
|---|---|---|---|---|
| 2006 | −2 | 0 | −31 | −5 |
| 2007 | −6 | −4 | −36 | −27 |
| 2008 | 0 | 0 | −27 | −3 |
| 2009 | 0 | 0 | −27 | −2 |
| 2010 | −2 | −1 | −32 | −15 |
| 2011 | 0 | 0 | −30 | −7 |
| 2012 | 0 | 0 | **0** | −6 |
| 2013 | 0 | 0 | **0** | −2 |
| 2014 | 0 | 0 | **0** | 0 |
| 2015 | 0 | 2 | **0** | −3 |
| 2016 | 1 | 2 | +1 | 1 |
| 2017 | 1 | 1 | +1 | 1 |
| 2018 | 1 | −1 | +1 | 1 |
| 2019 | 0 | 0 | −2 | 0 |
| 2020 | −1 | −3 | −2 | −11 |
| 2021 | −1 | −2 | −1 | −12 |
| 2022 | −1 | −2 | −1 | −5 |
| 2023 | 0 | −2 | −1 | 1 |
| 2024 | −3 | −3 | −7 | −15 |
| 2025 | 0 | 1 | +1 | 0 |
| 2026 | 0 | 0 | 0 | 0 |

Nifty 100 and Nifty Midcap 100 went from +5/+44 to within a couple of names
across the whole history. The **+1 in 2016–2018 is not an error**: NSE's own
captured Nifty 200 list has 201 rows on 2017-11-13, 2018-03-15 and
2019-02-02, so the nominal 200 is what is wrong there, not the reconstruction.

## 10. The union identity is false before 2016

This is the finding that decides E1b's window, and it comes from the captures
rather than from a document.

NSE's methodology (September 2026 edition) defines Nifty 200 as "Constituents
forming part of Nifty 100 and Nifty Midcap 100". §5 of this document took that
at face value. The captures show it is written in the present tense. On the
three dates both parents were captured:

| date | Nifty 100 | Midcap 100 | **overlap** | union |
|---|---|---|---|---|
| 2010-01-02 | 100 | 100 | **27** | 173 |
| 2014-01-22 | 100 | 100 | **32** | 168 |
| 2026-08-27 | 100 | 100 | **0** | 200 |

Before the 2016 restructure the old CNX Midcap was an independently selected
index that shared names with CNX 100; only the restructure — effective
2016-04-01, redefining the mid-cap segment as ranks 101–250 of Nifty 500 —
made the two a partition. The transition is bracketed by the captures rather
than pinned: they still overlapped on 2014-01-22 and were disjoint by
2026-08-27, and the restructure release explains why.

So the union derivation is valid from 2016 and is **not evidence about 2007**.
The −27 to −36 drift in the Nifty 200 rows for 2006–2011 above is that
overlap, not a parsing gap.

## 11. Proposed window (not applied)

Per the instruction of 2026-09-18, this is a proposal only; nothing has been
changed in E1b §4 and no run has been made.

Nifty 200 membership is trustworthy from **2012**:

| years | state |
|---|---|
| 2006–2011 | union of two indices that overlapped — **not Nifty 200** |
| 2012–2015 | **exactly 200 on every month-end** |
| 2016–2018 | 201, which is what NSE's own captured list holds |
| 2019–2026 | within a few names; exact on all four capture dates |

**The proposal is that E1b's development window start in 2012** rather than
2007 — development 2012–2016, validation 2017–2021 — which keeps the
validation window as chartered and costs five years of development history.

The alternative, running from 2007 on the union, would put a universe that is
27–36 names short of the real Nifty 200 into the years that decide the
verdict. That is not a smaller version of the experiment; it is a different
one.

## 12. Residual: names whose window rests on a guess

An end of a window is evidence when a published change gives it, when an
archived list on the far side pins it, or when the security's first traded
session bounds it. It is a guess when a name appears in one capture and not
the previous one with no change notice to explain it: it joined somewhere
inside that segment and the build places it at the start.

| index | names | with a guessed end | share |
|---|---|---|---|
| Nifty 200 | 555 | 315 | 57% |
| Nifty 100 | 272 | 176 | 65% |
| Nifty Midcap 100 | 403 | 225 | 56% |
| Nifty 500 | 1,369 | 770 | 56% |

These are listed in the manifest with their bounded windows. **Sweep row S12
drops them**, so the sweep shows what the guesses were worth instead of
leaving it to be argued. If the base row and S12 agree, the residual gaps did
not decide anything. S12 was added to E1b §6 as a draft on 2026-09-18.

The share is high because most windows sit between two captures rather than
between two change notices. It is not the same quantity as the drift above:
a guessed start inside a segment is bounded by that segment, which is why the
exact-list check still passes.
