# S65 plan: Phases 6 to 9, the app and the workshop (written 2026-10-28 for the next session)

Written for a Claude Code session that starts with NO memory of this project and for the investor. Everything needed is here
or in the files it names. Read in this order: CLAUDE.md, this file, docs/HANDOFF.md "Start here", docs/S64_BUILD_PLAN.md
(Progress, and Phases 7-8 in full: their task lists still apply where this file does not change them), docs/COMPANION.md.

## 1. What the investor decided on 2026-10-28 (do not reopen)
- **Two installations.** The APP is what runs his money: installed from the GitHub repo at a release tag into its own folder,
  only the files needed to run, its own data and store; the desktop shortcut and the scheduled tick point at it. The WORKSHOP
  (this folder, `D:\portfolio_lab`) is the developer's beta: Claude Code works here; its data is a copy that may be stale;
  finished work is released into the app as an update. In his words: "an app on the Play Store that came from GitHub".
- **Claude Code's memory will be reset.** The next session knows only what the repo and its docs say. Anything a session must
  know goes into CLAUDE.md, this plan, or docs/BUILT.md (Phase 8), never only into chat or the memory folder.
- **The US sleeve stays in BETA.** No US buying before January or February 2027; no money sent, no US holdings yet; Zerodha
  has approved his US access. Collection and studies keep running.
- **Quicko files his taxes.** The system keeps Quicko's inputs ready and reconciles; it does not file. The primary-source
  check of the foreign-tax rows is deferred (it is slow and optional now): it becomes a Needs-from-you item before the first
  remittance.
- **Two bank accounts the system has never seen** (small balances) will be closed as soon as he can (perhaps by December,
  before the FDs mature). SBI (main) and HDFC savings stay open. Question #17 in his Needs from you holds the checklist.
- **The run continues until January or February** while it collects, calibrates and personalises; then the US work resumes.

## 2. Where things stand (2026-10-28, branch pm/s64-finish, last commit 1103b37; 1,897 tests pass)
- Phase 5 done (summaries, recency, hypotheses, limits, suggestion numbers, scenarios, F&O, replay bench, scanners, business
  page, nudges, valuation and plain words, the one picture, option-implied probabilities, IPO planner, gauges).
- Rule tests: 7 rules registered and run (1 passed: below the 200-day average, an avoid rule); PEG study failed. Counter: 33
  tests, next bar t >= 2.97. Results in docs/research/s64_rules_results.md, s64_peg_results.md.
- Phase 6 built (see the Progress line in S64_BUILD_PLAN.md): sourced tax rows (all `secondary`), schema v38, dollar ledger,
  US prices for the 13 funds, EDGAR code (blocked, see 4.1), NYSE calendar, sleeve study. The live store is at v38.
- The live store was last run on 2026-10-24: news is stale until the system runs again.

## 3. The target shape (Phases 8 and 9 build it)
| | APP (runs his money) | WORKSHOP (beta, development) |
|---|---|---|
| folder | `D:\PortfolioLab` (confirm with him) | `D:\portfolio_lab` (this repo) |
| code | a clone of `main` at a release tag `vYYYY.MM.DD`; only runtime files | the full repo, any branch |
| data | `D:\PortfolioLab\data` and `\pm`, its own | its own copy; may be stale; never the app's |
| channel | `stable` (beta features off unless he turns them on in Settings) | `beta` |
| sends | Telegram, paid API calls within his Rs 2,500 cap | nothing outward unless a command says `--live`; paid calls only with `--paid`, counted against a dev cap |
| runs | the shortcut, the scheduled tick, the overnight run | tests and the developer's commands |
| update | `pflab update` (Settings button too): back up the store, fetch, check out the newest tag, install, self-test, start; `pflab update --rollback` returns to the previous tag | merge to `main`, run the suite, tag |

Rules for the split:
- **Environment.** Today the user-level variable `PFLAB_DATA_DIR` = `D:\portfolio_lab\data` (the workshop) and `PFLAB_PM_DIR` is
  unset (code default `D:\portfolio_lab\pm`). The app must not depend on them: its launcher, tick and overnight script set both
  from the app folder's `release.toml`. The workshop keeps `.claude/settings.json`. Remove the user-level variable at the
  switch-over (Phase 9) so nothing points at the workshop by accident.
- **One cap.** The Rs 2,500 monthly cap belongs to the app. The workshop's paid calls count against a separate dev line in
  `api_budget.toml` (default 0, raised by him).
- **Data copy.** The app is seeded once from the workshop's data, leaving out what it does not run on: `data\llm_eval` (33 GB),
  `data\models` (16 GB), `data\backups`, and anything Phase 8's inventory marks unused. About 5 GB remains; check free space
  first. The store `pm\` (638 MB) is copied whole (his record: ledger, learner counter, suggestions, journal, questions).
- **Beta features** are listed in `configs/features.toml` (start: `us_sleeve`). In the app they are hidden or labelled BETA
  unless Settings says otherwise; data collection for them still runs so history builds up.

## 4. Phase 6 (US sleeve, finish as beta)
1. **SEC contact.** SEC answered 403 to the default User-Agent (2026-10-27; its fair-access policy wants a real contact). Do NOT
   try other User-Agent strings. When he gives one, it goes into `%USERPROFILE%\.pflab\secrets.toml` as `[sec] user_agent =
   "Name email"`; then run `us_prices.cik_map()` and one `sec_edgar.submissions` for a fund-free test, rebuild the US panel with
   CIK keys, and add aliases for any `US:` keys already used.
2. **Beta flag.** `configs/features.toml`, a Settings switch, and checks in the dashboard US panel, the brain's rule 6e, the
   picture's `us_sleeve`, and the `us_open` pass (only when the flag is on AND he holds US shares).
3. **Sleeve question.** The `companion` job asks once (limit_proposals kind `us_sleeve`). His answer: a share and a start month;
   the system then shows how to split funding across financial years to keep TCS low. `targets.toml` stays his to edit.
4. **Deferred items as dated Needs-from-you entries (not code):** the primary-source check of `configs/tax/foreign.toml`
   (opens 2027-01-01 or at the first remittance, whichever first); the GIFT City statement parser (opens when his first
   statement lands in the inbox).
5. **S&P 500 stock data** stays in the workshop until the SEC contact exists; the app collects the 13 funds and his US list.

## 5. Phase 7 (the system onboards him; the Quicko pack)
Keep items 1-9 of S64_BUILD_PLAN.md Phase 7 (secrets setup, setup page, classification by content, bank labels by the system,
IPO and opening-cost forms, the "investing 50k" path, `pflab pm reset` but see 6.3, tests). Changes:
- **Closing accounts.** The own-transfer matcher (item 4) must recognise the closing balance of an account it has never seen as
  his own money when he says so (question #17), and record the closed accounts by bank name with no numbers.
- **Item 10 becomes the Quicko pack**, not a tax engine for filing: per financial year, an export of realised gains by schedule
  (111A, 112A with the 31-Jan-2018 rule, slab items), dividends, FD interest, and the foreign rows (trades, remittances, TCS,
  US tax withheld, year-end holdings for Schedule FA); Schedule 112A as a CSV in the official ITR utility's layout (fetch the
  template, record URL and version, test against it); and the reconciliation of a Quicko or Console tax P&L export per ISIN
  (differences above Rs 1 to Needs from you). Advance-tax reminders and harvesting suggestions are optional; do them only if
  time remains.

## 6. Phase 8 (the clean and the split)
1. **Prune and docs:** S64_BUILD_PLAN.md Phase 8 items 1-3 in full (inventory, delete unreachable modules, BUILT.md,
   STUDIES.md, PLAN.md, README.md as the first-run guide, CLAUDE.md under 90 lines, the authorised git and archive deletions).
2. **Fold the memory rules into CLAUDE.md** (the memory folder will be gone): long runs are his (give the exact command, the
   duration, how to tell it finished); run the real path yourself before handing him a command; decide technical choices with a
   safe fallback, his money and limits stay his; act at once when data arrives; local first, paid only where it beats local,
   inside his cap; delete personal inputs after calibration; one brain with tools; the system works on its own and asks only
   what only he can answer.
3. **The app machinery:** `release.toml` (folder, channel), the launcher, tick and overnight script reading it, `pflab update`
   and `--rollback`, `tools/install_app.ps1` (clone at a tag, create .venv, install, build the Docker sandbox image, create the
   shortcut, register the tick), `tools/seed_app.ps1` (the one-time data copy of 3), `configs/features.toml`, the workshop's
   outward guard (`PFLAB_CHANNEL=beta`: no Telegram, no paid calls without `--paid`, no tick registration).
4. **Tests:** release.toml overrides the environment; the beta guard blocks Telegram and paid calls; update and rollback on a
   temporary git repo; the seed copy leaves out the listed folders; feature flags hide and show.

## 7. Phase 9 (switch over to the app; his record is kept)
The S64 plan's "restart" wiped and rebuilt the store. That is changed: the running store is his record (learner counter,
suggestions, journal, answers) and is copied, never wiped. A clean-room install is tested separately.
1. Merge `pm/s64-finish` to `main` (privacy grep clean), tag the first release.
2. **Clean-room test:** install the tag into a temporary folder with NO data: the first-run guide must work from README alone
   (his reinstall requirement); then delete that folder.
3. **Install the app** into `D:\PortfolioLab` from the tag, seed its data from the workshop (3), point the shortcut and the tick at
   it, remove the user-level `PFLAB_DATA_DIR`, stop every workshop scheduled task.
4. **Real-path checks in the app:** self-test, migrations, `overnight.ps1 -DryRun` and `-Phases selftest`, one real brain pass on
   the picture (about Rs 10), the two Telegram summaries with sending on (he receives two messages), the `companion` job once
   (his Needs from you fills with the basket, limit, reserve, pot and sleeve questions).
5. Hand him: what runs when, what it will ask, and the date of the next session (a sync check in January or February).

## 8. What only he can give (ask once, in one message, at the start)
1. The SEC contact (a name and an email he is happy to send to SEC with each request), or "not yet".
2. The app folder (default `D:\PortfolioLab`) and free disk space for about 5 GB.
3. A yes to removing the user-level `PFLAB_DATA_DIR` at the switch-over.
4. Answers to Needs from you as they come (question #17 first: the closing accounts and the FD payout check).

## 9. Risks to watch
- Two copies of the same secrets: the workshop must never run the bot, the tick or the outbox (Telegram would answer twice).
- A migration in an update runs on his real store: back up first, every time (`pflab update` does it).
- Stale workshop data is expected; never copy workshop data over the app's after the switch-over.
- 54 GB in the workshop's data folder: do not seed it whole.
