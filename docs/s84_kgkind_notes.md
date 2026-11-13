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
5. "Resigns with immediate effect" of a chief executive, managing director or chair IS a leadership_crisis (his list), but not when the filing gives a personal / health / family reason,
   keeps the person on the board, or concerns an independent, non-executive or vice chair. Plain resignations with "immediate effect" remain about half the real hits; if the coordinator
   finds a sale on those too hasty, drop `_QUIT_AT_ONCE` from `classify._LEADERSHIP` (one line) and the thinking loop alone judges them.
6. A model-confirmed `leadership_crisis` on an ARTICLE counts only when the company's name is in the headline (see the real run below); a BSE filing needs no such check.
7. A class action about a settlement, a dismissal or a ruling in the company's favour is not medium bad news (falls through to the later rules).

## Tests (`tests/test_s84_kgkind.py`, 49 cases)
closed lists; eight governance headlines (Nvidia week: board opens investigation into CEO, board prepares to oust CEO, CEO and espionage link; a promoter arrested; chief executive on leave
/ leaving with immediate effect / chairman removed); two class actions = regulatory_action medium; eight ordinary headlines = no thesis-break kind; the old rules unchanged; the scripted
local model (off-list answer, one retry, valid pick); a BSE filing -> `leadership_crisis` high from the next open and a byte-identical rebuild and a passing point-in-time audit; a news
lead confirmed by the model becomes a thesis break seen by `material_events`; a model "none" leaves it `other`; the exit manager: Friday nothing, Monday sells once; an old plan reads the
new kind; ordinary news and a core plan never sell. Also run and green: test_s81_kg, test_s82_kg, test_s81_exits, test_kg, test_kg_clean, test_kg_switch (107) and test_s81_loop_exits,
test_s81_drills_fixes, test_s81_drills_harness, test_s83_picks, test_s81_session, test_s81_swing, test_s81_autonomy (94). Later additions: twelve "looked like a shock on real filings, is
not" headlines, eight "real filing shapes that are a shock", a headline-name guard test.

## Shared files touched
`core/exits.py` (the default kind list and one line in `check_thesis`), `configs/core.toml` (`[exits] thesis_kinds`), `kg2/build.py` (about 10 lines in the news path), `kg2/job.py` (priority order), `tests/test_s81_kg.py` (one pinned set). Of the shared files in the brief's list none was touched.
Not touched: loop, session, PLAN, BUILT, CLAUDE.

## Exposed for screens
Nothing new to draw. `classify.rule_kind(headline) -> (kind, severity)` and `kg.events.material_events(con, isins, since)` carry the kind as plain strings; Today / reports get the kind's
name inside the existing thesis-break text ("Thesis break: leadership_crisis event ...").

## Checked on the real filings (read only; 2026-11-12)
All 2.9 million distinct BSE announcement headlines of 2010-2026 (6,160 daily files) were run through the rules. A first version fooled itself on real text, so the rules were
tightened until the hit list read clean (final numbers):
- `leadership_crisis` fires on 78 headlines in 16 years (about 3 in 100,000), about half of them arrests, custody, investigations and removals of a chief executive, chair or promoter,
  the rest chief executive / managing director / chair resigning "with immediate effect" without a stated personal reason (decision 5 below).
- Found and fixed: "sanction" in loan / scheme papers (a director "sanctioning"), the exchange's template titles ("in case of Frauds/defaults/arrest by promoter or KMP", the generic
  "Appointment and Removal / Cessation of CEO"), replies to rumours, "cardiac arrest" (a promoter's death), resignations that give a personal or health reason or keep the person on the
  board, independent / non-executive / vice chairs, promoter re-classification notices ("removal of name from the promoter group").
- 12 class-action filings are `regulatory_action` / medium (a filing about a settlement, a dismissal or a ruling in the company's favour is not).
- Still missed (known, not worth a looser rule): arrests where the person is named only by a long description ("Whole Time Director / Promoter Group ... arrested" is now caught; a
  few unusual phrasings are not).

## The local model on the new kind, and the cache
- `classify_pending` with the REAL local model (Ollama qwen3:8b, no paid call): 40 events in 196 seconds (about 5 s each). Four news leads were confirmed `leadership_crisis` / high.
  All four were WRONG LINKS: a school-board chairman and "a Mumbai-based firm" were tied to a bank / a state agency only because the article's text named it; "Fino Payments Bank CEO" to a
  large IT company; "Schaeffler India CEO in custody" to a car maker. So the build now keeps such a pick as `news` / low unless the company is named in the HEADLINE (alias match,
  code; test). On the real graph that leaves ONE `leadership_crisis` event (a real arrest of a non-executive chairman, a BSE filing of 13 Nov 2025) and no wrong sale.
- The cache cannot be rebuilt for the whole scope in 20 minutes: about 90,000 events are `other` / `news`, at about 5 s each that is about 125 hours. It does not need to be: the rules
  are code and apply at every build; the model only breaks ties on `other` / `news`. The nightly job asks about 40 events a night, governance headlines FIRST (a new order in
  `kg2/job.py`), so the first nights cover every lead. The scratch cache now holds 400 rows (360 real + 40 new); the app's own `classified.jsonl` was NOT touched.
- How: scratch root `D:\s84_scratch\kgkind\root` (junctions to the real data folders, a copy of `kg/classified.jsonl` and `scope.json`; nothing written to the app).

## Nightly audit on the scratch copy (day 2026-11-12, final code; graph 139,836 events)
passed. every_row_has_isin_source_date 0; point_in_time 0 events after the day, 0 facts known later, 0 without a time; derived_time_rule 0 wrong; filing_link_rate 0.9994 (203,844 of
203,972 earlier measure; threshold 0.95); news_tag_agreement 0; duplicates 0.0 (threshold 0.01); closed_lists kinds_ok and relation_rules_ok; rebuild_identical True (two builds from the
raw files, SHA-256 per table, same); sample_written 50; 907 filings carry a derived time (A58); news link share 0.4222. A build takes about 1.5 minutes warm (5 to 13 minutes cold or
while the PC is busy). The first audit (before the headline guard, same checks) also passed. Raw outputs: `D:\s84_scratch\kgkind\final_audit.out`, `rebuild_audit.out`, `scan_raw4.out`.

## OFF / not done
Nothing is switched off: the kind is live in the graph, the model prompt, the rules and the exit manager. The nightly job's graph switch (`kg2.switch`) is unchanged (it switches ON
only when its audit passes; this change keeps the audit green). US filings and exposure through funds are S85 (not touched).
