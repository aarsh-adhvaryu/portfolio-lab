# A1 — plan: three readers of company announcements (2026-09-29)

**Plan only.** Nothing is built, fetched or run. It waits for Aarsh's review of
`docs/data/flag_audit_labels.md`; his reviewed labels are the reference every
reader is scored against. **Change-log entries that apply:** E5-A §14 —
2026-09-27 (A1's precondition: a sampled precision check of each subtype),
2026-09-28 readiness decisions, 2026-09-29 A0 lock. E5-A §13: no LLM decides
anything; an LLM output enters only as a timestamped record with its source
and cutoff.

## 1. Rows and readers

**Rows**: the 251 masked rows of `docs/data/flag_audit.md` (seed 20260925,
2017–2021, E1's eligible names). Every reader reads the same masked text and
sees no other reader's labels.

| reader | what it is | on these rows |
|---|---|---|
| **K**, frozen keyword rules | `pflab/data/red_flags`, as E2-A ran them | TRUE on all 251 **by construction**: the sample was drawn from flagged events. K's score is the reference precision per flag. It cannot say UNSURE |
| **J**, Jev | **not defined anywhere in the repo.** Planned as a second human reader, given the masked file and the written criteria, blind to Aarsh's and Claude's labels | one pass, submitted before any discussion |
| **L**, local LLM | Ollama is installed, with `qwen3.5-9b-16k` and `gemma4-12b-16k`, on an RTX 5070 Ti with 12 GB. Called through `requests`, so no new dependency | temperature 0, fixed seed; the prompt is the criteria table of `flag_audit_labels.md`, verbatim; output is JSON `{label, reason}`. The model digest and the prompt's SHA-256 are recorded |

## 2. Credit-rating revisions need the attached PDF

- **Audit**: of 30 RATING_DOWNGRADE rows, the draft marks 22 UNSURE. **21
  headlines say "revision" and give no direction, and all 21 have a BSE
  attachment** (27 of the 30 rating rows do).
- **Full history**, if A1 uses rating direction: 1,101 RATING_DOWNGRADE
  events 2010–2026, 924 of them worded as a revision. Across all
  announcements, 995 say "revision in credit rating" and 940 of those carry an
  attachment.
- **Fetching**: from BSE's corporate-filing attachment path by the stored
  `attachment` name, at the collectors' pace (0.8 s pause plus the download,
  about 2 s each). **The audit's 21 take about 1 minute; the history's ~924
  take about 30 minutes**, which makes that Aarsh's job. Files are 0.1–0.5 MB,
  so under 0.5 GB in `data/bse_attachments/`. These are estimates; the first
  20 fetches measure the real rate.
- **Text**: extracted with `pypdf`. A scanned PDF yields no text and its row
  stays UNSURE. It is counted, not OCR'd, because OCR is not in CLAUDE.md 7.
- **Masking**: the letters name the company and carry dates, so
  `flag_audit_sample.mask_text` runs on the PDF text before any reader sees
  it. The old and new ratings survive the masking.
- **Scored twice**: headline only, then headline plus attachment. Aarsh labels
  the 21 again with the attachment, and that becomes the reference for those
  rows. The two scores are reported separately.
- **Point in time**: the attachment is disseminated with the announcement
  (same `dissem_dt`), so a feature built from it keeps the headline's
  `usable_from`.

## 3. Scoring, fixed before any reader runs

- Per flag and overall: a 3×3 confusion matrix against the reference;
  agreement; Cohen's κ; each reader's precision T/(T+F); the UNSURE rate.
- **Power**: with 30 rows a flag, a precision has a 95% Wilson interval of
  about ±15 pp. Readers that differ by less than about 20 pp on one flag
  cannot be told apart. Overall (251 rows) the interval is about ±5 pp.
- **Recall is invisible here**: every row was flagged by K, so an event K
  missed cannot appear. That matters only if L might replace K.
- **Hindsight**: L's training data postdates 2017–2021, so it may recognise a
  masked event. That does not bias a label-quality score. It does limit using
  L to build A1 features, and E5-A §13's record must carry the model's
  cutoff.

## 4. Cost and time

| reader | money | 251 rows | + 21 attachments | build |
|---|---|---|---|---|
| K | 0 | seconds (already applied) | cannot read them | none |
| J | Jev's time | ~1.5–2 h at 20–30 s a row | ~20 min | a blank copy of the masked file |
| L | 0 (local) | ~5–10 min at 1–2 s a row (~500-token prompt) | ~2 min (1–3k tokens each) | ~½ day: fetcher, reader, scorer, tests; re-run once to check the output is identical |
| Aarsh (reference) | his time | review already drafted | ~20 min | — |

L over the red-flag table's 16,054 events (for A1 itself, not the audit)
would take about 4.5–9 h, an overnight job for Aarsh.

## 5. Decisions for Aarsh

1. **Who or what is Jev?** If Jev is a tool rather than a person, only J's
   row in §1 and §4 changes.
2. **Which LLM.** Recommended: `qwen3.5-9b-16k` as L, with `gemma4-12b-16k`
   run and reported but never chosen after seeing its score.
3. **Adoption rule per flag.** Proposed: J or L replaces K's reading of a
   flag only if its precision is at least K's and its UNSURE rate is no
   higher than the reference's. Otherwise K stays.
4. **Recall sample.** Draw 250 unflagged announcements from the same window
   and universe for J and L, needed only if L could replace K.
5. **The ~924-PDF history fetch** is needed only if A1 uses rating direction.

## 6. Order

1. Aarsh finalises the labels. The file is committed and its SHA-256
   recorded; it is the reference.
2. Fetch, extract and mask the 21 attachments; Aarsh labels those rows with
   the attachment.
3. J and L read, blind.
4. Score and write the result up. Nothing in A1 changes before that.
