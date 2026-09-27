# E1-P — verdict on re-run: INCONCLUSIVE (2026-09-27)

Computed by `classify.classify_e1p`, never typed. Written to
`experiments/E1-P/sweeps/validation-edb8b1ddc7a25dea/verdict.json`.
**Supersedes the REJECT of 2026-09-19** (`E1-P-verdict.md`). No parameter
changed, and §3–§7 are unchanged since the 2026-09-19 lock (span hash
verified). Sealed period untouched.

Change-log entries that apply: E1-P 2026-09-19 (§3 per-lot resolution);
E1 §15 **2026-09-21** measurement correction; E1 §15 **2026-09-27**
accounting corrections a–d; E1 §15 **2026-09-27** D1/D2 data repairs.

- **Why re-run:** E1b's procedure, after the base-row regression at `0926a5b`
  showed G1 and G2 holding in validation.
- Sweeps (commit `1a6ce55`): `development-d39563896315d68f`,
  `validation-edb8b1ddc7a25dea`. Base rows 6.92% / 59.75%, 22.18% / 47.99%.
  Stack: E1 regression base, same code. N1/N2 are excluded from G3.

| | development | validation |
|---|---|---|
| G1 | +0.49 pp, +0.73 pp ✗ (0.01 short) | +0.52 pp, −0.77 pp ✓ |
| G2 | ✓ | ✓ |
| G3 rows holding | 1 / 6 ✗ | 3 / 6 ✗ |

**GATE: INCONCLUSIVE.** Neither REJECT condition holds any longer, and G3
fails in both periods, so it cannot ADOPT. The margins are a hundredth of a
point either side of the bar, so the reading is "no effect shown", as
before. The label changes; the conclusion does not.
