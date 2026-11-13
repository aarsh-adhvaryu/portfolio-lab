# S85 sec: US company filings from the SEC (8-K items 5.02, 4.01, 4.02) into the graph

Branch `s85/sec`. Written 2026-11-13.

## What is built
- `ingest/sec_8k.py` (collector). For the US names the system holds, picks, skips or watches (the thinking loop's own `think/watch.scope`, funds left out; `[think] sec_scope = "book"`, `"sp500"` adds the index
  members, default stays "book"): read `data.sec.gov/submissions/CIK##########.json` (`[sec] user_agent` from `pm/secrets` via `sec_edgar.user_agent()`, header only), keep 8-Ks (not 8-K/A) in the look-back
  (30 days, 90 on the first run) whose items include 5.02, 4.01 or 4.02, fetch each main document, turn it into text with lxml, cut it into its items, write the raw file `<data>/sec_8k/<accession>.json`, index it in
  `sec_8k_s85` (a filing is never fetched twice; a failed fetch is retried up to 4 tries). Politeness: at most 4 requests a second, back-off on 429/5xx/timeouts (Retry-After honoured), a 403 waits once then stops the run
  (`Blocked`), no contact stops at once; the contact is scrubbed from every message and never stored. A company is asked at most every 90 minutes (12 hours after three failures).
- `kg2/sec_8k.py` (events from the raw files, classification by code). One event per (filing, item): isin `ZZ`+10-digit CIK, source `SEC EDGAR 8-K item 5.02` (4.01, 4.02), ref = accession, `ts` = SEC acceptance time
  (UTC) + 5:30 = IST, `ts_rule` release_time; no acceptance time: next US trading open (A58), rule `next_open_no_release_time`, date on the row. `build.py` reads them as a third event source (nothing added when there is no
  `sec_8k/` folder), nodes origin `us_filing`.
- Rules: 4.02 -> `accounting_concern` high (new kind, no equivalent existed; added to `THESIS_BREAK_KINDS`, so also the local model's closed list, the audit's list and `material_events`). 4.01: auditor resigned ->
  `auditor_resignation` high; dismissed with a STATED disagreement or reportable event -> high; declined to stand for re-election -> medium; ordinary dismissal -> `routine` low (the "there were no disagreements" boilerplate
  and the line about the new auditor are read as negations). 5.02: CEO/CFO/chair/founder terminated, removed, on leave, named with an investigation, resigning over a stated disagreement, or resigning "effective
  immediately" with no personal/health/retirement reason in the departure's own sentence -> `leadership_crisis` high; other departures of those roles -> `management_change` medium; appointments -> `management_change` low;
  plans/pay only -> `routine`. Compensation-plan sentences ("if terminated", "upon", "entitled") never count as an event.
- Job `sec_8k` (`service/tasks_s79_sec8k.py`): every 2 hours; runs inside the SEC's filing hours (weekdays 06:00-22:00 New York) or after a gap of 6 hours (app start); disabled with a visible reason when no `[sec] user_agent`;
  bounded (400 requests, 15 minutes); a refusal or failure is a `problems` line, never a failed run. Due on app open via `ondemand.MAX_AGE_H["sec_8k"] = 3`.
- `sync_store`: after new filings, when the graph is on and its audit passed, the new events are inserted in `kg2_event`/`kg2_node` at once (same function and as-of as the nightly rebuild, so the same event ids); the
  thinking loop does not wait up to 6 hours for the nightly build. With the graph off or the audit failed nothing is added (as for every graph row).
- Reader: `kg/events.material_events` follows `instrument_alias` (either direction, any depth), so a US name held by a real ISIN or `US:SYMBOL` finds the events stored under its CIK key; events come back under the asked key.
  `think/watch._thesis_signals` needed no change (test shows it sees the events).
- Graph as-of for US filings (`kg2/sec_8k.known_by`): a filing is in the build for Indian close day D if accepted by the next Indian open (09:15 IST after D). Reason: a US evening filing lands in the small hours of the
  next Indian day, and a rule of "date <= D" would hide it for a full day. `audit.py` allows US rows up to that moment and checks a derived US time against the US calendar. Readers still hold a row back until its own `ts`.

## Decisions (2026-11-13, own)
1. 8-K/A is not read (the original carries the news). 2. Non-crisis CEO/CFO/chair departures are `management_change` medium (informational; not a thesis-break kind, so the watch ignores them). 3. `accounting_concern` added to
the kind list as briefed (no equivalent); not added to `core.toml [exits] thesis_kinds` (exits are India only). 4. Raw files, not store rows, are the source of graph events (the graph is rebuilt nightly and must be byte-identical).
5. A same-sentence rule for terminated/removed (and investigations): found on real filings that a "CEO onboarding" phrase next to another person's termination date made a false crisis.

## Real path (2026-11-13, real SEC, scratch folder `D:\s85_scratch\sec\data`, nothing in the app)
Five large names, 365-day look-back: 15 filings with a wanted item (all 5.02), 20 requests, 15 events: 13 `management_change` low, 1 medium, 1 `leadership_crisis` high (a CEO resignation "effective immediately" filed
2026-11-12; the first version missed it because the word "family" in a later biography blocked it: fixed, tested). A second look the same day: 5 requests, 0 stored (idempotent). A wider check on two more names over 1500 days
(for 4.01): 34 filings (31 x 5.02, 3 x 4.01), 36 requests; real auditor resignation -> high, planned auditor change -> routine, after tuning the 49 events give 2 `leadership_crisis` and 1 `auditor_resignation`. No 4.02 occurred in
the names tried (4.02 is covered by the fixture test only). Fallbacks (item heading not found) after the fixes: 0 of 49 (an early version missed "Item&#8201;5.02" with a thin space and an XML-declared document).
Symbols are in the scratch folder only.

## Tests
`tests/test_s85_sec.py` (56): index parsing and item filtering, text and item cutting, 22 classification cases (several from real filings), headline, collect + idempotence + retry, pacing (<=4/s on a fake clock), 429
back-off with Retry-After, 403 stops the run, no contact -> no request, no header in any log/row/file/result, graph events and time rules (IST, A58, point in time), byte-identical rebuild and the audit passing, store sync,
alias reading, the watch's thesis signal, scope (picks, skips, funds left out, sp500 switch), job body and registration, migration. Also green: test_s81_kg (updated: the pinned kind set now includes `accounting_concern`),
test_s82_kg, test_s84_kgkind, test_s81_exits, test_s81_ondemand, test_s79_open, test_s84_watch, test_s84_wire, test_s83_score, test_s79_implied, test_s80_advisors (238 passed before the one pinned-set edit).

## Shared files touched (each a small hunk)
`kg2/build.py` (3 hunks), `kg2/audit.py` (two checks aware of US rows), `kg2/classify.py` (kind + one prompt sentence), `kg/events.py` (alias reading), `service/ondemand.py` (one dict entry), `app/world.py` (one job name in
the "filings" group), `configs/core.toml` (`[think] sec_scope = "book"`), `tests/test_s81_kg.py` (pinned kind set). Migration `pm/mig_s79/m_sec85.py` (275, 276; 277-279 spare).

## OFF / not done
Nothing is OFF by switch: the job runs when `[sec] user_agent` exists. `sec_scope = "sp500"` is the later switch (code and test exist, default "book"; 500 names would take about 5 minutes of requests per full pass).
Not built: 8-K/A, other items (e.g. 2.06 impairments, 8.01), a model reading of a filing (code rules only), the graph's local-model path for these events.

## Exposed for screens
`ingest.sec_8k.run_job(...)` returns JSON-able counts (`stored`, `by_item`, `problems`, `graph`); tables `sec_8k_s85` (per filing status) and `sec_8k_cik_s85` (per company: last asked, status); events appear in
`kg2_event` with source "SEC EDGAR 8-K item N" and in `material_events`.

## Lines for the coordinator
BUILT.md: job `sec_8k` (every 2 h, SEC filing hours; code, free), tables `sec_8k_s85`/`sec_8k_cik_s85`, raw `<data>/sec_8k/`, source "SEC EDGAR 8-K item 5.02/4.01/4.02", kind `accounting_concern`, config `[think] sec_scope`.
Note: US events appear in the graph only while `kg2.switch` is on and its audit passes (same as every graph row).
