# RUNNING — the job queue

Every job that takes more than about five minutes: queued, running or done,
with where its output lands. Aarsh runs these; Claude writes the commands
and reads the results off disk afterwards.

`tools\status.ps1` shows what is actually running right now. **This file is
the intent; `status.ps1` is the truth.** When they disagree, believe
`status.ps1` and fix this file.

**At most four sweeps at once** (CLAUDE.md, "Running jobs"): 2.81 GB
measured peak, ~3.5 GB budgeted, 31.4 GB total. Check the free-RAM line in
`status.ps1` first — four is the ceiling only when the machine is quiet.

---

## Running

_(none)_ — verified 2026-09-27 with `tools\status.ps1`.

## Queued

**16. DONE 2026-10-01 (Claude, 1.6 and 2.4 min): A0 IDENTICAL at `6a29dde` in both periods; A1 and A3 LOCKED (`lock/E5-A-A1`, `lock/E5-A-A3`). Logs `experiments\_identity\a0_6a29dde_*.log`.**

**17–18. A1 and A3 development (LOCKED 2026-10-01; side by side, ~30 min each; `-WhatIf` passes).**
```
cd D:\portfolio_lab; .\tools\run_locked.ps1 -Experiment E5-A-A1 -Period e5a_development -Config configs\e5a_a1.toml
cd D:\portfolio_lab; .\tools\run_locked.ps1 -Experiment E5-A-A3 -Period e5a_development -Config configs\e5a_a3.toml
```
Each prints `SWEEP DIR:`; output `experiments\E5-A\A1|A3\sweeps\e5a_development-<id>`.
Validation waits for the development reviews.

**19–22. Gap diagnosis (DIAGNOSTIC, NOT PROMOTABLE; `docs/reviews/gap-diagnosis.md`).**
From the repo with a clean tree; ~3 GB each. E1d ~10 min, A0 ~12–15 min
(A0 also runs the stack). Two alongside jobs 17–18 (four at most), then the other two.
```
cd D:\portfolio_lab; $env:PFLAB_EXPERIMENTS_DIR='D:\portfolio_lab\experiments'; .venv\Scripts\python.exe -u tools\gap_diagnosis.py --strategy E1d --period development
cd D:\portfolio_lab; $env:PFLAB_EXPERIMENTS_DIR='D:\portfolio_lab\experiments'; .venv\Scripts\python.exe -u tools\gap_diagnosis.py --strategy E1d --period validation
cd D:\portfolio_lab; $env:PFLAB_EXPERIMENTS_DIR='D:\portfolio_lab\experiments'; .venv\Scripts\python.exe -u tools\gap_diagnosis.py --strategy A0 --period e5a_development
cd D:\portfolio_lab; $env:PFLAB_EXPERIMENTS_DIR='D:\portfolio_lab\experiments'; .venv\Scripts\python.exe -u tools\gap_diagnosis.py --strategy A0 --period validation
```
Done when each prints `DONE -> ...\diagnostics\gapdiag-<period>-<id>`.

**23. BSE results pull for A5 (after Aarsh decides the dating rule,
`docs/data/bse_results_finding.md` §3).** Network only, ~0.3 GB; 5–7 h;
resumable (re-run the same line). Nothing after Dec 2021 is fetched.
```
cd D:\portfolio_lab; .venv\Scripts\python.exe -u tools\probe_bse_results.py pull
```
Done at `DONE: 1184 scrips in ...\data\bse_results`.

**15. A1 event reads (E5-A families readiness §2; 2026-09-30).** L =
`qwen3.5-9b-16k` over the 710 events of its flags (DEFAULT, FORENSIC_AUDIT,
REGULATORY_ACTION), 2010 → 2021-12-31. One window; Ollama running; GPU only,
~0.3 GB RAM, so it can share the machine with sweeps. **About 35–60 min**
(3–5 s an event; 10 already cached). Resumable: stop and re-run the same line.
```
cd D:\portfolio_lab; .venv\Scripts\python.exe -u tools\a1_read_events.py --config configs\e5a_a1.toml
```
Done when it prints a JSON block with `"events": 710` and writes
`data\a1_readers\events_qwen3.5-9b-16k.parquet`. Then Claude builds the A1
stores (`tools\build_e5a_family.py --family A1`, seconds each).

**14. DONE 2026-09-30** (scored: `docs/notes/A1-reader-scores.md`).
**14. (done, kept for the record) A1 reader contest (A1 plan §3–§6; 2026-09-30).** L = `qwen3.5-9b-16k` on the 251
audit rows and 16 rating letters, then `gemma4-12b-16k` on the same (reported only),
then L on the 250-row recall sample. One window, sequential (one GPU). About 45 min
(3.1 s a row measured on 5 rows each). Ollama must be running; the sweeps are
unaffected (GPU, ~0.3 GB RAM). Resumable: reads are cached in `data\a1_readers\`.
```
cd D:\portfolio_lab; .venv\Scripts\python.exe -u tools\a1_contest.py read; .venv\Scripts\python.exe -u tools\a1_contest.py read --model gemma4-12b-16k; .venv\Scripts\python.exe -u tools\a1_contest.py recall
```
Done when the last line reads `qwen3.5-9b-16k recall: 250 rows, …`. Then Claude
runs `score` and `recall-sheet` (seconds each).

**Done 2026-09-30:** A0 validation `E5-A\sweeps\validation-c6564e07b9148590` 7.51% / 26.69%
(INCONCLUSIVE); E3-R validation `E3-R\sweeps\validation-d1e612b69131648d` 19.62% / 48.08%
(REJECT).

**8–10. E5-A A0, locked 2026-09-29 (`lock/E5-A` → `530a3d8`).** Three windows
from the places shown, all at once (~3 GB each; nothing else running). Stores
already rebuilt at the tag.

| # | job | command | output | expect |
|---|---|---|---|---|
| 8 | A0 development | `cd D:\portfolio_lab; .\tools\run_locked.ps1 -Experiment E5-A -Period e5a_development -Config configs\e5a_a0.toml` | `experiments\E5-A\sweeps\e5a_development-<id>`; prints `SWEEP DIR:` | ~30 min |
| 9 | A0 exploratory (never counted) | same, `-Period e5a_exploratory` | `experiments\E5-A\sweeps\e5a_exploratory-<id>` | ~20 min |
| 10 | validation STACK at the tag (E5-A §8) | `cd D:\pl_runs\E5-A; $env:PYTHONPATH='D:\pl_runs\E5-A\src'; $env:PFLAB_EXPERIMENTS_DIR='D:\portfolio_lab\experiments'; D:\portfolio_lab\.venv\Scripts\python.exe -u tools\regress_bases.py E1d-e5a-val` | `experiments\E1d\regression\validation-<id>`; marker `experiments\_regress\E1d-e5a-val.json` | ~10 min |

A0's validation sweep waits for its development verdict.

_Status 2026-09-30 15:46: **8–11 and 13 DONE** (base CAGR / MaxDD, liquidation):
8 `E5-A\sweeps\e5a_development-cedd1b289d7bb7aa` 12.59% / 14.46%;
9 `e5a_exploratory-d5b68a41eeb004e4` 14.32% / 20.75% (never counted);
10 `E1d\regression\validation-a6256fbb0ba71a8f` 26.21% / 42.96%;
11 `E3-R\sweeps\development-7abfb3d39c34e018` 6.82% / 54.16%;
13 883 of 913 PDFs cached, 30 not at BSE. **12 re-run 15:52 with logs: both IDENTICAL** (`experiments\_identity\e1d_e3r_*.log`); E3-R's STACK = the c6ef67e E1d sweeps._

**12. E3-R STACK check (E3-R §11, 2026-09-30) — before job 11 is classified.**
E1d base at `lock/E3-R` against E1d's full sweeps at `c6ef67e`. Two windows,
side by side, ~5–10 min each (~3 GB each). The live repo's tool is run on the
worktree's code; its first line must say `pflab imported from
D:\pl_runs\E3-R\src\...`, or the check is void.
```
cd D:\pl_runs\E3-R; $env:PYTHONPATH='D:\pl_runs\E3-R\src'; $env:PFLAB_EXPERIMENTS_DIR='D:\portfolio_lab\experiments'; D:\portfolio_lab\.venv\Scripts\python.exe -u D:\portfolio_lab\tools\e1_identity.py development --config configs/e1d.toml --ref D:\portfolio_lab\experiments\E1d\sweeps\development-924cec1bb3dd9ff9\rows\base
cd D:\pl_runs\E3-R; $env:PYTHONPATH='D:\pl_runs\E3-R\src'; $env:PFLAB_EXPERIMENTS_DIR='D:\portfolio_lab\experiments'; D:\portfolio_lab\.venv\Scripts\python.exe -u D:\portfolio_lab\tools\e1_identity.py validation --config configs/e1d.toml --ref D:\portfolio_lab\experiments\E1d\sweeps\validation-a0e0f5aa78dc160f\rows\base
```
Pass: both print `IDENTICAL` and exit 0 (a key-order-only note is a pass) →
the c6ef67e sweeps are E3-R's STACK. Either `DIFFERENT` → re-run E1d full at
the tag (Claude writes that command).

**13. Rating-revision PDF history (A1 plan §2; decided 2026-09-30).** Every
RATING_DOWNGRADE event 2010–2026 worded as a revision (935 events, 913 attachments), fetched from BSE
and cached in `data\bse_attachments\`. One window, ~35 min (2.2 s a file
measured on the audit's 21), < 0.5 GB, network only (~0.3 GB RAM), can run
alongside anything. Resumable: re-running skips cached files.
`cd D:\portfolio_lab; .venv\Scripts\python.exe -u tools\rating_pdfs.py --history`
Done when it prints `DONE ->` and `data\bse_attachments\_history.json` exists
(counts of cached and not found).

**11. E3-R development, locked 2026-09-29 (`lock/E3-R` → `c06c6af`), against
E1 + E1d.** With 8–10 running this is the fourth sweep: check `tools\status.ps1`
shows ~14 GB free first. `cd D:\portfolio_lab; .\tools\run_locked.ps1
-Experiment E3-R -Period development` → `experiments\E3-R\sweeps\development-<id>`,
~30–40 min (base + S1–S10); prints `SWEEP DIR:`. Validation after the
development review.

**7. DONE 2026-09-29 20:26 at `19ac284` (4.4 min) → `experiments\E1d\regression\e5a_development-977f12d2dd395573`.** E5-A A0's STACK on `e5a_development` (2026-09-29).** E1 + E1d base row and
B1–B5 on 2011–2016, base only; A0's development verdict compares against it
(E5-A §8). One PowerShell window from `D:\portfolio_lab`, ~10 min, ~3 GB; can
run alongside anything (it is one sweep):
`$env:PFLAB_EXPERIMENTS_DIR='D:\portfolio_lab\experiments'; .venv\Scripts\python.exe -u tools\regress_bases.py E1d-e5a-dev`
Lands in `experiments\E1d\regression\e5a_development-<run_id>`. Done when
`experiments\_regress\E1d-e5a-dev.json` exists and the window printed `DONE ->`.
The A0 sweeps themselves wait for the lock (`tools\run_locked.ps1`).

**6. DONE 2026-09-29 at `c6ef67e`, 14/14 (verdicts: `docs/reviews/regression-2026-09-28-verdicts.md`) — final regression, all six experiments, both periods,
full sweeps** (E1 §15 2026-09-28 fixes). Four PowerShell windows from
`D:\portfolio_lab`, one lane each, all at once (~3 GB each):
`$env:PFLAB_EXPERIMENTS_DIR='D:\portfolio_lab\experiments'; .venv\Scripts\python.exe -u tools\regress_bases.py --full --lane A`
(then `B`, `C`, `D`). Lanes A/B: E1, E1b, E1-P full + E1 on E2-A's window
(base only); C/D: E1c, E1d, E2-A full. ~45–70 min a lane. Done when all 14
markers in `experiments\_regress\` carry the new commit and `"full"`, and each
window printed `DONE ->` for every job. Then `tools\regress_bases.py --report`.

**5. DONE 2026-09-27 at `1a6ce55`** (E1-P dev/val, E1d dev/val; E1d ADOPT, E1-P INCONCLUSIVE). Full re-runs after the D1/D2 base-row flips (E1b's procedure; Aarsh's decision).**
Four windows at once, ~15-20 min each, at HEAD (not `run_locked`: the fix is the
code change). Each prints its output dir when done:
`$env:PFLAB_EXPERIMENTS_DIR='D:\portfolio_lab\experiments'; .venv\Scripts\python.exe -u -m pflab.cli sweep configs\e1p.toml --period development`
(and `--period validation`; and the same two for `configs\e1d.toml`).

**4. DONE 2026-09-27 at `0926a5b`.** Regression + gap attribution under D1/D2 (commit after `c8ba002`).** Four
lanes in four terminals, then the gap job; commands in HANDOFF / chat of
2026-09-27. Old marker files are overwritten; old result dirs stay.

| # | job | command (from `D:\portfolio_lab`) | output | expect | can share the machine? |
|---|---|---|---|---|---|
| 1 | **Infrastructure end-to-end test** — reproduce E1 base development through the locked-run path | see "The end-to-end test" below | `experiments\_infratest\` | ~15 min | yes |
| 3 | ~~E1 gap attribution~~ **DONE 2026-09-27** (`gap-development-ce4403d3ad65303b`; re-run after D1/D2) — **E1 gap attribution, development** (audit Deliverable 2; diagnostic, not promotable) — 12 one-change controls + 3 combined rows + B2/B5 twice | `$env:PFLAB_EXPERIMENTS_DIR='D:\portfolio_lab\experiments'; .venv\Scripts\python.exe tools\gap_attribution.py` | `experiments\E1\diagnostics\gap-development-<id>\summary.md`; prints `DONE ->` | ~15 min (0.9 min a row) | yes (one panel, ~3 GB) |
| 2 | ~~Regression under the 2026-09-27 corrections~~ **DONE 2026-09-27**, 14/14 markers, commit 19f1ea2 | `tools/regress_bases.py --report` | `experiments\_regress\` | — | — |

**2026-09-27, accounting corrections (E1 §15):** job 1 and `tools/e1_identity.py`
compare against pre-correction results and will now differ by design. Re-run
the E1 regression under the corrections first (job 2 below).

**Reading the E1 identity check** (done 2026-09-27, both PASS). Exit code 0 and `IDENTICAL` is the pass. If either
says `DIFFERENT`, do not start any E3-R, E2-D1 or E2-D2 run: re-run the
same tool from a worktree at commit `c33feb3` (before this session's engine
changes) to tell whether the difference is this session's or older.

**After the locks, not before** (each needs Aarsh's lock first): E2-D1's
STACK run and sweeps (`docs/notes/E2D1-readiness.md` §5), E3-R's sweeps
(`.\tools\run_locked.ps1 -Experiment E3-R -Period development`, then
`validation`), E2-D2's sweeps (`docs/notes/E2D2-readiness.md` §4).

## Done

| job | finished | output | result |
|---|---|---|---|
| E1 identity, development (`tools/e1_identity.py`) | 2026-09-27 | `experiments\_identity\development.log` | **PASS** — equity and trades identical; decisions identical in content; `reference_close` key order differs (set iteration, varies per process, predates this session) |
| E1 identity, validation | 2026-09-27 | `experiments\_identity\validation.log` | **PASS** — same |
| shareholding backfill 2010–2026 | 2026-09-25 | `data\bse_shareholding\` | 194,035 / 194,040 (100.0%), 2,940 scrips, `unstable` 0 |
| red-flag table 2010–2026 | 2026-09-25 | `data\red_flag_events\events.parquet` | 16,054 events, 15,962 with ISIN |
| E1d development sweep | 2026-09-24 | `experiments\E1d\sweeps\development-a8d5d7cda901a63f` | 11.55% / 49.54% |
| E1d validation sweep | 2026-09-25 | `experiments\E1d\sweeps\validation-7d350769a6907044` | 24.27% / 36.72% — verdict INCONCLUSIVE |
| E2-A development sweep | 2026-09-25 | `experiments\E2-A\sweeps\e2a_development-9098271bff563780` | 11.85% / 33.18% |
| E2-A validation sweep | 2026-09-25 | `experiments\E2-A\sweeps\e2a_validation-da6040804aa08fa8` | 41.84% / 8.41% — verdict REJECT |
| E2-A §8a event studies | 2026-09-25 | `experiments\E2-A\event_study_*.json` | −7.73% (t −3.14) then +12.16% (t +3.48) |

---

## The end-to-end test

Proves the locked-run path reproduces a known number before any real
experiment depends on it. E1 base development must come back at
**8.97% / 55.40%**.

```powershell
cd D:\portfolio_lab

# 1. a throwaway tag and worktree at HEAD
git tag lock/_infratest
git worktree add --detach D:\pl_runs\_infratest lock/_infratest

# 2. run through the locked path (~15 min)
.\tools\run_locked.ps1 -Experiment _infratest -Period development -Config configs\e1.toml

# 3. check the number, then clean up
git worktree remove D:\pl_runs\_infratest --force
git tag -d lock/_infratest
```

**What to watch as it starts.** The script prints `pflab.__file__` before it
runs anything. It must be under `D:\pl_runs\_infratest\src`. If it is under
`D:\portfolio_lab\src` the script aborts — that is the editable install
shadowing `PYTHONPATH`, and it is the whole reason the check exists.

**Expect one refusal first.** `_infratest` has no entry in
`check_lock.REGISTRY`, so the script will refuse with *"an experiment nobody
recorded a hash for is an experiment nobody locked"*. That refusal is the
tool working. To run the test anyway, pass `-Config configs\e1.toml` and add
a temporary `"_infratest"` entry to the registry pointing at E1's span, or
run the E1 lock instead:

```powershell
git tag lock/E1 && git worktree add --detach D:\pl_runs\E1 lock/E1
.\tools\run_locked.ps1 -Experiment E1 -Period development
```

`E1` is already in the registry and its span verifies, so this is the
cleaner test — and it leaves a real `lock/E1` tag, which the adopted stack
should arguably have anyway.

**Dry run first, which costs nothing:**

```powershell
.\tools\run_locked.ps1 -Experiment E1 -Period development -WhatIf
```

That performs every check, prints the tag, the code path, the expected
duration and where results will go, and stops before running.


## The regression (job 2, 2026-09-27)

Commit first: the tool refuses a dirty tree. Four PowerShell windows, one
lane each, all from `D:\portfolio_lab`. Check `tools\status.ps1` shows about
14 GB free first.

```powershell
$env:PFLAB_EXPERIMENTS_DIR='D:\portfolio_lab\experiments'
.\.venv\Scripts\python.exe tools
egress_bases.py --lane A   # window 1: E1, E1b, E1-P dev; E1 on E2-A dev window
.\.venv\Scripts\python.exe tools
egress_bases.py --lane B   # window 2: the same, validation
.\.venv\Scripts\python.exe tools
egress_bases.py --lane C   # window 3: E1c, E1d, E2-A development
.\.venv\Scripts\python.exe tools
egress_bases.py --lane D   # window 4: E1c, E1d, E2-A validation
```

Each job prints `== <job> DONE -> <dir>` and writes
`experiments\_regress\<job>.json`. **Finished = 14 markers.** Then run
`.\.venv\Scripts\python.exe tools
egress_bases.py --report` (old vs new
base rows). The lanes are independent, so a failed job stops only its own
lane: re-run that lane's remaining jobs by name.
