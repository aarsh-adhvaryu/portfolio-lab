# S85 readers (C2): the local screen, the readers, the graph door (a)

Branch `s85/readers`. Tests: `tests/test_s85_readers.py` (31, green); related suites run green: test_s62_security, test_s78_chart, test_s81_kg, test_s82_kg, test_s84_kgkind, test_s84_recall, test_s84_gate, test_kg_switch, test_s84_watch (203 passed).

## What is built
- `entrance/screen.py` (A71): `check_text(text, con=None)` -> {ok, text (masked), masked (kinds, never values), flagged, refused}; `check_file(path, name, mime, con=None)` -> {ok, kind, refused, reason, score, mask_needed, pages, scanned}.
  Terms from `privacy_terms.json` (through `security.load_terms`) plus the ledger ids when a connection is given; patterns for PAN, Aadhaar, account (labelled and bare 9-18 digit runs, also at a sentence end), IFSC, UPI, card (Luhn), phone, e-mail (hq/redact does most of the masking).
  Personal-record detector: `ingest.sniff` kinds plus a score (header marker 3, ids 3, person PAN/Aadhaar 3, IFSC beside an account 2, 5+ dated amount rows 2; a public-document word takes 3 off); refused at 3. A locked file, a scan with no OCR on this PC, an image with no OCR: refused (fails closed).
- `entrance/readers.py` (E3, A72): `read_attachment`, `check_link`, `only_sourced_in`, `source_type`, `fetch`, `sheet_summary`. PDF as document blocks in parts of 30 pages (max 6 parts; the page of a fact is found by code from its quote); sheet/CSV summarised by code; image by vision with the numbers checked against Windows OCR; text direct and masked. A PDF whose text names his name/address words is not sent: masked text is.
  A claim is kept only if its quote is in the source and every number is in the source; otherwise dropped with a visible note. Same bytes twice: stored answer, cost 0.
- Door (a) `kg2/you.py`: events with source "you", `ts` = received time, `ts_rule` = `received_time`, linked by `you:isin_in_text` or `you:alias_exact_in_text` (alias named twice or in the title area; never a model). Raw file `<data>/kg/you_events.jsonl` (append-only) is a raw input of `kg2.build`, so the nightly rebuild keeps them and two rebuilds stay identical. When the graph is ON and audited, the rows also go into `kg2_event` at once. A keyword (fraud, resignation) in something he sent gives kind `news`, severity low (a lead, never a thesis break).
  Facts are also a dated note via `recall.write_back(source="you")`. A supported link check is an event; a contradicted or unverifiable claim is a note only.
- Migrations 320 (`received_docs_s85`) and 321 (`link_checks_s85`) in `pm/mig_s79/m_readers85.py`.

## Decisions (2026-11-13)
- The event goes to a raw file, not straight into `kg2_event` only, because the nightly job deletes and rebuilds those tables from raw files.
- Documents/images are passed to the gateway as `documents=[{"name","media_type","data"(base64),"title"}]` / `images=[{"media_type","data"}]` when `gateway.call` accepts those arguments, else as Anthropic content blocks inside the message (works with today's gateway). `engines` should accept this shape or tell me another.
- Agent name: "reading" when `gateway.AGENTS` has it, else "desk". Today it ran as "desk" (so it counts in the thinking layer's limits): `engines` must add "reading" to `AGENTS` and `hq/governor.LIMITS`.
- The prompt for a link check holds no URL (its digits, a CIK or accession number, trip the egress "account-like number" rule); the answer lists the URLs itself.
- Digit runs of 9+ in a message are masked as account numbers, so a long plain number he types is masked (rupee amounts with commas are untouched).
- Web fallback (`analyst.web_search`) only when the page cannot be fetched here; a news link is checked at an official page it links to (exchange, SEC, regulator, company IR), else the answer says no original source was found.
- Same-subject effect to watch (loopchat): a note "from you" is a note on the name, so `recall.same_subject_fresh` may treat his document as a fresh answer and skip a paid read.

## Real path (2026-11-13, on a copy of the store, scratch folders)
One real Sonnet read of a 4-page public SEC compliance guide (14 facts, pages kept, Rs 3.49) and one real link check of the public SEC Form 8-K PDF (claim about Item 5.02: supported at the original source, quote found, Rs 1.18). Total Rs 4.67, claude-sonnet-5-5 / role read / thinking medium.

## OFF / not verified
- Nothing is switched off. Not verified: Telegram path, the chat store `attach` call (wrapped in try; `entrance.store` was not merged), a scanned PDF through real OCR (tested with OCR faked), a news link on the real web, the `reading` agent in the governor.

## Shared files touched
`kg2/build.py` (3 small hunks), `kg2/audit.py` (one check `you_events_point_in_time`), `kg2/filing_time.py` (RULE_RECEIVED), `hq/llm.py` (`_strip_images` also strips base64 `document` blocks from the request log). No `entrance/__init__.py` was created (the chat agent owns it; the package works as a namespace until then).

## Lines for the coordinator
BUILT.md: `entrance/screen.py`, `entrance/readers.py`, `kg2/you.py`, tables `received_docs_s85`, `link_checks_s85`, graph source "you" with `ts_rule` received_time, audit check `you_events_point_in_time`.

## Exposed for screens
`readers.read_attachment(...)` and `readers.check_link(...)` return JSON-able dicts (`summary_text`, `facts`, `isins`, `graph_nodes`/`node` with `/api/graph/node?id=company:<ISIN>`); `received_docs_s85` and `link_checks_s85` rows; `screen.check_text/check_file`.
