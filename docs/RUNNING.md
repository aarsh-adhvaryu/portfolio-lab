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

_(none)_

## Queued

| # | job | command (from `D:\portfolio_lab`) | output | expect | can share the machine? |
|---|---|---|---|---|---|
| 1 | **Infrastructure end-to-end test** — reproduce E1 base development through the locked-run path | see "The end-to-end test" below | `experiments\_infratest\` | ~15 min | yes |

## Done

| job | finished | output | result |
|---|---|---|---|
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
