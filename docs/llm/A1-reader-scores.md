# A1 reader contest — scores (numbers only)

Scored by `tools/a1_contest.py score`, 2026-09-30. Plan: `docs/notes/A1-reader-plan.md` §3 (fixed before any reader ran). Reference: `flag_audit_labels.md`, SHA-256 `00493cb537d093f0286ddc161950fb894eeb12cadd20adca1dec8f809dc07633`. **Nothing is decided here.**

## Readers

| reader | model digest | system prompt SHA-256 | rows | seconds |
|---|---|---|---|---|
| L qwen3.5-9b-16k | `c1b119d707b9` | `c08fb2d097f8cc9e…` | 251 | 706.6 |
| gemma4-12b-16k (reported) | `44c1a7b692c0` | `c08fb2d097f8cc9e…` | 251 | 698.8 |
| qwen3.5-9b-16k letters | `c1b119d707b9` | `c08fb2d097f8cc9e…` | 16 | 54.8 |
| gemma4-12b-16k letters | `44c1a7b692c0` | `c08fb2d097f8cc9e…` | 16 | 62.1 |

L settings: temperature 0, seed 20260930, Ollama `think` off, JSON schema, reason first. A row with no valid subtype counts as UNCLEAR. **Determinism:** 20 random audit rows re-asked with the cache bypassed gave byte-identical replies (20 of 20), 2026-09-30.

## 1. Headline only, 251 rows, current reference

The primary score (plan §3): subtype accuracy. Adoption rule (plan §5.3) compares a reader's AT_COMPANY calls correct with K's (= the reference precision).

| reader | n | agreement | κ | reader UNCLEAR | reference UNCLEAR | AT_COMPANY calls correct | share of reader's resolved calls that are AT_COMPANY | failed |
|---|---|---|---|---|---|---|---|---|
| K (keywords) | 251 | 75% | 0.00 | 0% | 12% | 85% | 100% | 0 |
| L qwen3.5-9b-16k | 251 | 66% | 0.29 | 17% | 12% | 94% | 79% | 0 |
| gemma4-12b-16k (reported) | 251 | 48% | 0.22 | 11% | 12% | 98% | 42% | 0 |

### Per flag (agreement / κ / reader UNCLEAR / AT_COMPANY calls correct). K's AT_COMPANY calls correct = the reference precision

| flag | n | ref precision | K (keywords) | L qwen3.5-9b-16k | gemma4-12b-16k (reported) |
|---|---|---|---|---|---|
| AUDITOR_RESIGNATION | 30 | 97% | 97% / 0.00 / 0% / 97% | 90% / -0.03 / 3% / 96% | 60% / 0.10 / 13% / 100% |
| DEFAULT | 30 | 100% | 80% / 0.00 / 0% / 100% | 80% / 0.00 / 0% / 100% | 90% / 0.71 / 10% / 100% |
| FORENSIC_AUDIT | 14 | 90% | 64% / 0.00 / 0% / 90% | 57% / 0.34 / 21% / 100% | 64% / 0.44 / 7% / 100% |
| FRAUD | 30 | 72% | 60% / 0.00 / 0% / 72% | 27% / 0.03 / 17% / 67% | 17% / 0.04 / 0% / 75% |
| INSOLVENCY | 30 | 76% | 73% / 0.00 / 0% / 76% | 73% / 0.44 / 10% / 89% | 53% / 0.32 / 13% / 91% |
| PROMOTER_ENCUMBRANCE | 30 | 100% | 100% / — / 0% / 100% | 93% / 0.00 / 7% / 100% | 0% / 0.00 / 0% / — |
| RATING_DOWNGRADE | 30 | 54% | 43% / 0.00 / 0% / 54% | 40% / 0.21 / 77% / 100% | 37% / 0.16 / 43% / 100% |
| REGULATORY_ACTION | 30 | 91% | 67% / 0.00 / 0% / 91% | 47% / 0.21 / 20% / 100% | 30% / 0.11 / 3% / 100% |
| RESULTS_DELAY | 27 | 88% | 85% / 0.00 / 0% / 88% | 81% / -0.05 / 0% / 88% | 93% / 0.72 / 4% / 100% |

### Confusion, L qwen3.5-9b-16k (rows: reference; columns: reader)

| reference \ reader | AT_COMPANY | AGAINST_COMPANY | RELATED_ENTITY | NOT_EVENT | UNCLEAR |
|---|---|---|---|---|---|
| AT_COMPANY | 145 | 1 | 7 | 12 | 23 |
| AGAINST_COMPANY | 3 | 0 | 0 | 1 | 1 |
| RELATED_ENTITY | 2 | 0 | 5 | 0 | 1 |
| NOT_EVENT | 4 | 0 | 0 | 6 | 9 |
| UNCLEAR | 10 | 0 | 5 | 7 | 9 |

Agreement by stated confidence: 0.0-0.7: — (n 0); 0.7-0.9: 0% (n 1); 0.9-1.0: 66% (n 250)

### Confusion, gemma4-12b-16k (reported) (rows: reference; columns: reader)

| reference \ reader | AT_COMPANY | AGAINST_COMPANY | RELATED_ENTITY | NOT_EVENT | UNCLEAR |
|---|---|---|---|---|---|
| AT_COMPANY | 92 | 1 | 6 | 75 | 14 |
| AGAINST_COMPANY | 1 | 0 | 0 | 4 | 0 |
| RELATED_ENTITY | 1 | 0 | 6 | 1 | 0 |
| NOT_EVENT | 0 | 0 | 0 | 14 | 5 |
| UNCLEAR | 1 | 0 | 4 | 18 | 8 |

Agreement by stated confidence: 0.0-0.7: — (n 0); 0.7-0.9: 0% (n 13); 0.9-1.0: 50% (n 238)

## 2. Headline only, 251 rows, reference before the rating directions (a15c775)

For continuity: the 21 revision rows were UNCLEAR in this reference.

| reader | n | agreement | κ | reader UNCLEAR | reference UNCLEAR | AT_COMPANY calls correct | share of reader's resolved calls that are AT_COMPANY | failed |
|---|---|---|---|---|---|---|---|---|
| K (keywords) | 251 | 73% | 0.00 | 0% | 19% | 89% | 100% | 0 |
| L qwen3.5-9b-16k | 251 | 72% | 0.43 | 17% | 19% | 94% | 79% | 0 |
| gemma4-12b-16k (reported) | 251 | 50% | 0.27 | 11% | 19% | 98% | 42% | 0 |

## 3. The 16 readable rating letters, current reference

| reader | input | n | agreement | κ | reader UNCLEAR |
|---|---|---|---|---|---|
| K (keywords) | headline | 16 | 38% | 0.00 | 0% |
| L qwen3.5-9b-16k | headline | 16 | 0% | 0.00 | 100% |
| gemma4-12b-16k (reported) | headline | 16 | 25% | 0.01 | 56% |
| qwen3.5-9b-16k | headline + letter | 16 | 50% | 0.27 | 31% |
| gemma4-12b-16k | headline + letter | 16 | 81% | 0.66 | 6% |

| row | reference | qwen3.5-9b-16k + letter | gemma4-12b-16k + letter |
|---|---|---|---|
| 169 | NOT_EVENT | NOT_EVENT | NOT_EVENT |
| 170 | NOT_EVENT | NOT_EVENT | NOT_EVENT |
| 171 | RELATED_ENTITY | AT_COMPANY | RELATED_ENTITY |
| 174 | NOT_EVENT | UNCLEAR | NOT_EVENT |
| 175 | AT_COMPANY | UNCLEAR | AT_COMPANY |
| 179 | AT_COMPANY | UNCLEAR | AT_COMPANY |
| 182 | AT_COMPANY | AT_COMPANY | NOT_EVENT |
| 183 | AT_COMPANY | UNCLEAR | AT_COMPANY |
| 185 | NOT_EVENT | AT_COMPANY | NOT_EVENT |
| 186 | NOT_EVENT | NOT_EVENT | NOT_EVENT |
| 187 | AT_COMPANY | AT_COMPANY | AT_COMPANY |
| 188 | AT_COMPANY | AT_COMPANY | NOT_EVENT |
| 190 | NOT_EVENT | UNCLEAR | NOT_EVENT |
| 191 | NOT_EVENT | AT_COMPANY | UNCLEAR |
| 192 | NOT_EVENT | NOT_EVENT | NOT_EVENT |
| 193 | NOT_EVENT | NOT_EVENT | NOT_EVENT |

## 4. Recall sample, qwen3.5-9b-16k: flags raised on 250 unflagged rows

NONE 247, RATING_DOWNGRADE 2, AUDITOR_RESIGNATION 1
(726.7 s). No reference yet: The investor labels `docs/data/recall_labels.md`.
