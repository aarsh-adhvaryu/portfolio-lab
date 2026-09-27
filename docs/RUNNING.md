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

**4. Regression + gap attribution under D1/D2 (commit after `c8ba002`).** Four
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
