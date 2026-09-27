# E1d — verdict on re-run: ADOPT (2026-09-27)

Computed by `classify.classify_e1d`, never typed. Written to
`experiments/E1d/sweeps/validation-ca5e784819af9c07/verdict.json`.
**Supersedes the INCONCLUSIVE of 2026-09-25** (`E1d-verdict.md`), which was
measured before the 2026-09-27 corrections. No parameter changed, and §3–§7
are unchanged since the 2026-09-24 lock (span hash verified this session).
Sealed period untouched.

Change-log entries that apply: E1d 2026-09-24 (§3 wording; S11 added);
E1 §15 **2026-09-21** measurement correction; E1 §15 **2026-09-27**
accounting corrections a–d with their declared choices; E1 §15
**2026-09-27** D1/D2 data repairs, including the declared transition-action
refinement.

- **Why re-run:** E1b's procedure. The base-row regression at `0926a5b`
  showed G1, G2 and G4 holding in both periods (`E1-gap-attribution.md`
  §3). Aarsh ran both periods from scratch at HEAD.
- Sweeps (commit `1a6ce55`): `development-59aec2a0e9879d54`,
  `validation-ca5e784819af9c07`. Their base rows reproduce the regression
  (8.14% / 54.45%, 26.19% / 42.96%).
- STACK: E1 base under the same code, from `experiments/_regress/E1-{dev,val}.json`.

| | development | validation |
|---|---|---|
| G1 (CAGR Δ, MaxDD Δ) | +1.71 pp, −4.56 pp ✓ | +4.54 pp, −5.80 pp ✓ |
| G2 | ✓ | ✓ |
| G3 rows holding | 11 / 12 (S6 fails) ✓ | 10 / 11 (S10 fails; S11 n/a) ✓ |
| G4 turnover | ✓ | ✓ |

**GATE: ADOPT.** C1–C4 (reported, E1d as a candidate base): INCONCLUSIVE.
**MANDATE §3 and §5: not met.** E1d base vs B5 is −5.59 pp in development
and +3.75 pp in validation.

**§7 travels with this verdict.** E1d's hypothesis came from E1c's S6 on
these same years, so this pass is weaker evidence than a pass on a fresh
hypothesis. Under GATE the change joins the stack. The stack becomes
**E1 + E1d**, but only once Aarsh confirms it (see STATE and HANDOFF).
