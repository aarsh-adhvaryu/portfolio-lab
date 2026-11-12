# S84 kgkind: T2a, the `leadership_crisis` event kind (A68)

Branch `s84/kgkind`. Written 2026-11-12.

## What is built
- `kg2/classify.py`: `leadership_crisis` is the ninth thesis-break kind (`THESIS_BREAK_KINDS`, so also in `KINDS`, the local model's closed list `MODEL_PICKS`, its JSON schema enum, the
  audit's closed-list check, and `kg/events.material_events`, which reads `THESIS_BREAK_KINDS`; `think/watch` sees it as a thesis-break-kind event with no further change).
- Rules (code first, the model only where code has no answer): severity HIGH for a board or regulator investigation of the chief executive, chair, founder, managing director or a
  promoter (either word order); the chief executive, chair or founder ousted, removed, fired, put on leave, or resigning / leaving "with immediate effect"; "board prepares to oust";
  a promoter or chief executive arrested, detained or indicted; an executive, officer or director linked to espionage, sanctions or a criminal case.
  A securities class action (class action, securities suit / lawsuit, shareholder lawsuit) is `regulatory_action` MEDIUM, checked first so the word "fraud" inside it does not make it a
  fraud investigation. Ordinary appointments, retirements, company-secretary or independent-director exits, "CEO to present at a conference" stay as before (tests).
- The local model's prompt (`classify.SYSTEM`) now defines `leadership_crisis` and the class-action rule, still a closed list, no numbers.
- `kg2/build.py` (news path): a governance keyword in a news HEADLINE is a lead, not a sale: the event is stored as `news` / low until the local model's validated pick (cached,
  append-only) makes it `leadership_crisis` / high; the rule's answer for a BSE filing stands as before (a filing is the company's own disclosure). Same rule as the other thesis kinds
  (a keyword in an article is a lead), but those never reached the model; this one does.
- `kg2/job.py` `classify_pending`: headlines with a governance keyword are asked about first, then newest first (the nightly limit of 40 cannot starve them).
- `core/exits.py` and `configs/core.toml [exits] thesis_kinds`: `leadership_crisis` added. `check_thesis` also reads today's configured kinds for plans opened before this release
  (a plan stores its kinds when opened), so an old plan breaks on the new kind too. A high event breaks the thesis on severity alone (0.75) as before; A58 timing unchanged (a filing
  with no release time is used from the next trading open; the test shows Friday nothing, Monday one sale, never twice). The core plan (no thesis break) ignores events.

## Decisions (2026-11-12, own, no one awake)
1. Class action = `regulatory_action` / medium, exactly as briefed. Consequence to know: the exit manager's rule "a kind hit at severity >= 0.5 breaks the thesis" means a held longterm
   name with a class-action filing IS sold (same as every other medium thesis kind such as guidance_cut). The thinking loop (T5) is the better judge of a class action; the coordinator
   may want `check_thesis` to leave medium `regulatory_action` to the loop. Left as is: changing the exit manager's meaning is outside this item.
2. A news headline never makes a sale by itself (see above); the model must confirm.
3. `promoter` is in the "top person" list for investigation and arrest, not for "removed" (to avoid "removal of promoter from the promoter group" reclassification notices).
4. `test_s81_kg.py::test_closed_list_rules_and_validator` pinned the set of thesis-break kinds: updated to include the new kind (behaviour that changed on purpose).

## Tests (`tests/test_s84_kgkind.py`, 28 cases)
closed lists; eight governance headlines (Nvidia week: board opens investigation into CEO, board prepares to oust CEO, CEO and espionage link; a promoter arrested; chief executive on leave
/ leaving with immediate effect / chairman removed); two class actions = regulatory_action medium; eight ordinary headlines = no thesis-break kind; the old rules unchanged; the scripted
local model (off-list answer, one retry, valid pick); a BSE filing -> `leadership_crisis` high from the next open and a byte-identical rebuild and a passing point-in-time audit; a news
lead confirmed by the model becomes a thesis break seen by `material_events`; a model "none" leaves it `other`; the exit manager: Friday nothing, Monday sells once; an old plan reads the
new kind; ordinary news and a core plan never sell. Also run and green: test_s81_kg, test_s82_kg, test_s81_exits, test_kg, test_kg_clean, test_kg_switch (107) and test_s81_loop_exits,
test_s81_drills_fixes, test_s81_drills_harness, test_s83_picks, test_s81_session, test_s81_swing, test_s81_autonomy (94).

## Shared files touched
`core/exits.py` (the default kind list and one line in `check_thesis`), `configs/core.toml` (`[exits] thesis_kinds`), `kg2/build.py` (3 lines), `kg2/job.py` (priority order).
Not touched: loop, session, PLAN, BUILT, CLAUDE.

## Exposed for screens
Nothing new to draw. `classify.rule_kind(headline) -> (kind, severity)` and `kg.events.material_events(con, isins, since)` carry the kind as plain strings; Today / reports get the kind's
name inside the existing thesis-break text ("Thesis break: leadership_crisis event ...").

## Cache rebuild and the nightly audit on a scratch copy
(see the end of this file)
