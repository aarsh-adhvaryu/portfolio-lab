# Change log

Newest last. Dated; reason stated.

## 2026-10-06 — Research closed; repo repurposed as the Portfolio Manager

- Research is closed (shelved 2026-10-01, tag `shelved/2026-10-01`). Nothing
  further is run, registered or classified.
- The repository is repurposed as the **Portfolio Manager**: tax-aware FIFO
  lots, corporate actions, BSE results/announcements, price and NAV panel,
  data loaders. Research code, charters and verdicts moved out of `master`
  into the branch **`research-archive`** (created at the tag; pushed).
- **The sealed 2022–2025 period is considered spent.** Live use loads those
  prices, so it can no longer serve as unseen data. Nothing in the archive's
  verdicts may be re-read as out-of-sample evidence for it.
- The engine (`pflab.backtest`) and its import closure stay because the engine
  tests must pass unchanged; it is now a library, not a research harness.

## 2026-10-06 — research-archive protection rule

`research-archive` is **never checked out into `master`, merged, cherry-picked
or rebased onto it** until the investor says so in writing. Enforced in
`.githooks/pre-merge-commit` and `.githooks/pre-rebase` (activate with
`git config core.hooksPath .githooks`). Hooks cannot see fast-forwards or
cherry-picks; those rest on this rule.

Remote protection of `research-archive` (no deletion, no force-push) was attempted
2026-10-06 and refused by GitHub (private repo needs Pro). Not in place.

## 2026-10-06 — Planning; archive copy-out and library policy

- `docs/PLAN.md` and `docs/SESSION_TEMPLATE.md` written (33 sessions, S0–S32).
- The investor: "migrate things from the old repo, as much of that can be used here
  instead of just redoing." CLAUDE.md rule 1 amended: **file copies** from
  `research-archive` are allowed per `docs/MIGRATED.md`; merge, cherry-pick and
  rebase remain forbidden and the hooks are unchanged.
- The investor: use libraries (LangChain, LangGraph, …) instead of writing from
  scratch; OKF + PyYAML for the knowledge layer. CLAUDE.md rule 5 rewritten.

## 2026-10-06 — S1 done; decisions recorded

- S1 (store and instruments): `pflab.pm` (`store`, `secrets`, `instruments`),
  `pflab pm init|instruments`, migration 1 (`instruments`, `amfi_schemes`,
  `accounts`). Master built from panel (4,380 keys) + AMFI NAVAll (14,356
  schemes). AMFI moved to `portal.amfiindia.com/spages/NAVAll.txt`.
- Decisions (PLAN §10): FastAPI dashboard; `openpyxl` yes; CAS manual; dormant
  demat read-only, flagged, in totals; `PFLAB_PM_DIR` = `D:\portfolio_lab\pm`;
  Python stack; news/GMP chosen in the session that needs them. Backup target
  still not supplied.

## 2026-10-06 — S2 done; amendment A1

- `configs/tax/*.toml` (25 sourced rows: 18 primary, 4 secondary, 3 unverified) and `pflab.tax.rules` (`lookup`, `exemption`,
  `sgb_redemption_exempt`, `surcharge_cap`, `cess_rate`, `basic_exemption`).
- SGB conflict resolved against Finance Act 2026 s.43 (see PLAN §6). New-Act
  section numbers 196/197/198 confirmed from the same Act.
- A1: coverage starts 2024-07-23, not 2018-04-01; slabs and 87A move to S13.
  Open items (secondary/unverified rows) listed in PLAN §6.

## 2026-10-06 — S9 built; amendment A2

- `pflab.service`: schedule slots, job engine (lock, record, cooldown, catch-up once per latest slot), jobs
  (collect, prices, nav, filings, outbox, backup), Telegram outbox, backup, health. `pflab service
  tick|run|plan|status|test-alert|backup`. `tools/register_tasks.ps1` is written for the investor to run; no
  Task Scheduler entry was registered. The backup job is disabled until a target is set.
- A2: Telegram over the Bot API via `requests`; `python-telegram-bot` not added (send-only).
