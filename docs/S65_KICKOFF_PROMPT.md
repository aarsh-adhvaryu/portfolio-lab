You are starting S65 for Portfolio Lab, the investor's personal portfolio system (real money, India; a small US sleeve in beta).
You have no memory of earlier sessions: everything you need is in the repo. Read, in this order, before anything else:
CLAUDE.md, docs/S65_PLAN.md (this session's plan and his decisions of 2026-10-28), docs/HANDOFF.md "Start here",
docs/S64_BUILD_PLAN.md (the Progress section, and Phases 7 and 8 in full), docs/COMPANION.md (his intent in his own words).

The session builds Phases 6 to 9 of docs/S65_PLAN.md: finish the US sleeve as a beta feature, the system's own onboarding and the
Quicko pack, the clean and the split into the APP (installed from a GitHub tag, runs his money) and the WORKSHOP (this folder,
development), and the switch-over that keeps his running record. Start by asking him, in one message, the four things in
section 8 of the plan. Do not ask him to re-explain anything written in the plan.

House rules (CLAUDE.md): reports to him in 15 lines or fewer; long runs are his, with the exact command, duration and how to tell
it finished; run the real path yourself before handing him a command; no shell heredocs for code (write files with the file
tools; after any scripted edit, check for control characters); privacy grep (`.venv\Scripts\python -m pflab.hq.security`)
before any push; pytest needs `--basetemp` under the scratchpad on this PC; at each stop update STATE, HANDOFF and the plan's
progress, and commit.
