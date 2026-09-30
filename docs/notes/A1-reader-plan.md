# A1 — plan: readers of company announcements (2026-09-29, decided 2026-09-30)

**Plan; no reader built or run.** **Change-log entries that apply:** E5-A §14 —
2026-09-27 (A1's precondition: a sampled precision check of each subtype),
2026-09-28 readiness decisions, 2026-09-29 A0 lock, **2026-09-30 A1 plan
decisions**, **2026-09-30 §6(b) amendment** (features per flag and subtype,
NOT_EVENT excluded; contest scores subtype accuracy; confidence recorded, not a
feature). E5-A §13: no LLM decides anything; an LLM output enters only as a
timestamped record with its source and cutoff.

**Reference:** `docs/data/flag_audit_labels.md`, reviewed and confirmed by
Aarsh, committed at `a15c775`, **SHA-256
`f1fc74d719d8e2e1f84d8723daa59afb2ac9caaadc3ff5eee9bb2a25f953471c`** (the
committed blob; a CRLF checkout hashes differently). Subtypes: AT_COMPANY 182,
AGAINST_COMPANY 5, RELATED_ENTITY 7, NOT_EVENT 10, UNCLEAR 47 (251).

## 1. Rows and readers

**Rows**: the 251 masked rows of `docs/data/flag_audit.md` (seed 20260925,
2017–2021, E1's eligible names). Every reader reads the same masked text and
sees no other reader's labels.

| reader | what it is | on these rows |
|---|---|---|
| **K**, frozen keyword rules | `pflab/data/red_flags`, as E2-A ran them | TRUE on all 251 **by construction**: the sample was drawn from flagged events. K's score is the reference precision per flag. It cannot say UNSURE |
| ~~**J**, Jev~~ | **Dropped 2026-09-30.** Jev is TypeSafe's hosted classification model (an API needing `TYPESAFE_API_KEY`), not a person. Aarsh has no key. Can be added later as a third reader under the same scoring | — |
| **L**, local LLM | Ollama, **`qwen3.5-9b-16k`** (decided). `gemma4-12b-16k` is run and reported, **never chosen after its score is seen**. RTX 5070 Ti, 12 GB; called through `requests`, no new dependency | temperature 0, fixed seed; the prompt is the criteria and subtype tables of `flag_audit_labels.md`, verbatim; output is JSON `{label, subtype, confidence, reason}`. The model digest and the prompt's SHA-256 are recorded |

**The contest is K against L.** K has no subtype of its own: it asserts
AT_COMPANY on every row it flags, which is exactly what its precision measures.

## 2. Credit-rating revisions need the attached PDF

- **Audit**: of 30 RATING_DOWNGRADE rows, the draft marks 22 UNSURE. **21
  headlines say "revision" and give no direction, and all 21 have a BSE
  attachment** (27 of the 30 rating rows do).
- **Full history**: 1,101 RATING_DOWNGRADE events 2010–2026; 935 worded as
  a revision carry 913 distinct attachments. **Queued as Aarsh's job
  (RUNNING.md 13, ~35 min).** Across all
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
- **Done for the audit's 21 (2026-09-30, `tools/rating_pdfs.py --audit`,
  47 s):** 16 with text, **4 scanned** (165–168), **1 not at BSE** (172). Masked
  extracts are in `docs/data/rating_pdf_labels.md` for Aarsh to mark UP / DOWN /
  NO CHANGE. `mask_text` alone let through ISINs, a subsidiary, a group name
  and addresses; the tool adds CIN/ISIN/web/code/phone masks, drops letterhead
  lines, and masks named entities found on review (per row, in the gitignored
  `data/bse_attachments/audit_rows.json`).
- **Finding: today's sampler no longer reproduces `flag_audit.md`.** The
  2026-09-27 D1/D2 repairs widened E1's eligible set, so it draws 254 rows,
  149 different. The drawing commit's eligible set (`041ec33`, 894 names) on
  today's data reproduces all 251 rows exactly; it is saved as
  `data/flag_audit/eligible_041ec33.json` and is the audit's universe from now
  on (recall sample included).
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

- **Primary (E5-A §14, 2026-09-30): subtype accuracy.** Per flag and
  overall, a 5×5 confusion matrix of the reader's subtype against the
  reference's; agreement; Cohen's κ; the UNCLEAR rate.
- Secondary, for continuity with the audit: precision T/(T+F), where TRUE is
  AT_COMPANY.
- **Confidence** (L only): recorded per row and reported (accuracy by
  confidence band). It is not an A1 feature.
- **Power**: with 30 rows a flag, a precision has a 95% Wilson interval of
  about ±15 pp. Readers that differ by less than about 20 pp on one flag
  cannot be told apart. Overall (251 rows) the interval is about ±5 pp.
- **Recall is invisible here**: every row was flagged by K, so an event K
  missed cannot appear. **Recall sample drawn 2026-09-30:**
  `docs/data/flag_recall_sample.md`, 250 of 342,168 unflagged announcements
  on the audit's names, 2017–2021, seed 20260930, masked with `mask_strict`
  (symbols, short name tokens, ISINs, links, SAST acquirers). Aarsh labels it
  (flag or NONE, subtype); L reads it.
- **Hindsight**: L's training data postdates 2017–2021, so it may recognise a
  masked event. That does not bias a label-quality score. It does limit using
  L to build A1 features, and E5-A §13's record must carry the model's
  cutoff.

## 4. Cost and time

| reader | money | 251 rows | + 21 attachments | build |
|---|---|---|---|---|
| K | 0 | seconds (already applied) | cannot read them | none |
| L | 0 (local) | ~5–10 min at 1–2 s a row (~500-token prompt) | ~2 min (1–3k tokens each) | ~½ day: fetcher, reader, scorer, tests; re-run once to check the output is identical |
| Aarsh (reference) | his time | review already drafted | ~20 min | — |

L over the red-flag table's 16,054 events (for A1 itself, not the audit)
would take about 4.5–9 h, an overnight job for Aarsh.

## 5. Decisions (Aarsh, 2026-09-30; E5-A §14)

1. **Jev** is TypeSafe's hosted model, not a person; no key, so J is dropped.
2. **L = `qwen3.5-9b-16k`**; `gemma4-12b-16k` reported, never chosen.
3. **Adoption rule per flag, as proposed:** L replaces K's reading of a flag
   only if its precision is at least K's and its UNSURE rate is no higher
   than the reference's. Otherwise K stays. Subtype accuracy is reported
   beside it (E5-A §14 2026-09-30).
4. **Recall sample:** drawn (§3).
5. **History fetch:** queued, RUNNING.md job 13.
6. **Open, for Aarsh before A1 locks:** how a reader's UNCLEAR enters the
   per-subtype counts.

## 6. Order

1. ~~Aarsh finalises the labels~~ — done, `a15c775`, SHA-256 above.
2. ~~Fetch, extract and mask the 21 attachments~~ — done; **Aarsh marks
   `rating_pdf_labels.md`** and labels the recall sample.
3. L reads, blind (both models; the 251, the 21 with attachment, the 250).
4. Score and write the result up. Nothing in A1 changes before that.
