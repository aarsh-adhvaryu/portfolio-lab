# S81 B7: the knowledge graph and the news collection (agent "kg") notes

## What is built (all new, `src/pflab/kg2/`; the old `kg/` is untouched except `kg/events.py`, new)
- `scope.py` the scope file `<data>/kg/scope.json` (built from the app's alias file, the 100 current Nifty 100 names, the rest of the Nifty 500 as tags-only, 11 core
  ETFs; text cap 150; `merge_held(root, isins, names)` is how the coordinator passes his held names; `find_names` = the code rule for names the system finds itself:
  among tags-only names, article count in the last 30 days z >= 2 against their own history (min 8 articles) or a tone shift >= 1.5, at most 40; `apply_found`).
- `news.py` the one-year collection (below). `build.py` facts, relations, events, deterministic, parquet writer, store loader. `classify.py` the closed list, rule
  kinds, the local model's pick (via `llm/structured.ask_json`), append-only cache `<data>/kg/classified.jsonl`. `audit.py` `run_audit(con, root, day, graph=None)`.
  `position.py` the position layer. `switch.py` (`configs/kg2.toml` `[kg] on`, default OFF; `PFLAB_KG2` env wins). `job.py` `run(con, root, day, classify_limit)`:
  build, audit, load the store only if audit passed AND switch on, else the kg2 tables are emptied. `study.py` measures the registered study.
- `kg/events.py` `material_events(con, isins, since)` reads `kg2_event` (thesis-break kinds at any severity, or severity high); returns [] when the tables are empty.
- Migrations 123-130 in `pm/mig_s79/m_kg.py` (kg2_node, fact, relation, event, unlinked, event_class, audit, build). Config: `configs/kg2.toml`, `configs/kg2_groups.toml`.
- Tools: `tools/news_s81_run.py` (collector), `tools/kg2_run.py` (build + audit, counts only, in-memory store unless `--store COPY`).
- Protocol `docs/protocols/s81_kg_study_protocol.md` (committed before any run), code `kg2/study.py`.
- Tests `tests/test_s81_kg.py` (34, synthetic).

## Decisions (2026-11-09, his asleep)
1. News route: the GDELT 1.0 GKG DAILY files (`https://data.gdeltproject.org/gkg/YYYYMMDD.gkg.csv.zip`, 20-34 MB, ~50,000 rows a day, one row per article with
   organisations, tone, themes, URL). Measured: DOC 2.0 API reaches back only ~3 months and is rate-limited per query; the 15-minute GKG 2.1 files are 3-4 MB x 96 x 365
   = ~105 GB for English alone; v1 daily = ~9 GB of downloads for the year, filtered on the fly to the scope's organisation names (exact token = alias), nothing else kept.
   Cost of v1: a DAY, not a time. An article is dated by its day and usable only from the next day (the build excludes articles dated on the build day).
2. Raw rows kept: `news_s81/gkg1/YYYY-MM-DD.parquet`; article text (names with `text`): `news_s81/text/xx/<hash>.json` (trafilatura 2.0.0), local only.
3. Politeness: robots.txt per domain obeyed (unreadable: retry later), 1 request per domain per 3 s, 16 threads across domains, refused pages (robots/4xx/5xx/timeout/not HTML/no text)
   skipped and counted in the manifest; total size capped at 20 GB (rows + text, checked every minute). Log = counts only.
4. Link rules. Filing: scrip -> the ISIN valid on the dissemination DATE (inclusive both ends). No dissemination time: left out of everything (counted). News: the row's
   organisation token must EQUAL an alias of the ISIN (tag) AND the article's text names the company (or, with no text, its URL slug does); else unlinked with a reason.
5. Why the S80 audit saw 84.5%: (a) filings with no dissemination time were counted as unlinked (16% of the file; they are now left out by decision), and (b) a timestamp compared
   to a midnight `valid_to` dropped every filing on an ISIN's last valid day. Joined by dissemination DATE, listed (NSE-panel) scrips over the last 120 days of filings link 99.94%.
6. Facts' point in time: a result is known from its quarter end + 60 days (the rule `fundamentals/pit.py` uses; `bse_results` carries no filing date). `bse_results` history ends
   at quarter 112 (Dec 2021) for most scrips, so result facts exist only for names whose file is newer; the rest have none (honest gap).
7. Relations: `same_industry` (buckets of 2-60 names), `same_group_prefix` (`configs/kg2_groups.toml`, printed list). Supplier/customer: no parser exists, so none written.
8. Position layer reads `paper_lots` (system's own book; `book="ledger"` reads `lots`). The exemption limit from `tax.rules.exemption` (FY label = year it ends), used from
   `paper.book.year_gains` (that module labels a FY by the year it STARTS: the code converts). The exit plan is read from `exit_plans_s81` defensively (None when absent).
9. Names found by the system: the app's GDELT aggregates are India-wide only (no per-name series), so the rule runs on the collected rows of the Nifty 500 tags-only names.
10. Core ETF names rarely appear as organisations in news; they are in scope for completeness and will produce few rows.

## Collector: run, stop, log
- Started 2026-11-09 23:07 IST from a standalone copy (`D:\s81_scratch\kg_run\`, so it survives removal of the worktree), until 05:10 IST.
- Command (from `D:\s81_scratch\kg_run`): `D:\portfolio_lab\.venv\Scripts\python.exe run.py --root D:\PortfolioLabApp\data --until 05:10` (resumable; re-run after a stop; add `--find`
  to add the names found by the rule, `--build-scope` to rebuild the scope; `--until none` for no time limit).
- Log: `D:\PortfolioLabApp\data\news_s81\collect.log` (counts only); stdout `D:\s81_scratch\kg_run\stdout.log`. Manifest `news_s81\manifest.sqlite` (days, urls).
- Stop: create the file `D:\PortfolioLabApp\data\news_s81\STOP` (clean stop after the pages in hand); it is deleted at the next start. Only one runs at a time (`run.pid`).
- The live app reads `data\`; it must not be open while the collector runs a LOT of text threads (CPU-heavy: ~3 cores). Nothing outside `news_s81\` and `kg\` is written.

## What is OFF and how to switch on
The graph is OFF (`configs/kg2.toml` `on = false`). To turn on: run `tools/kg2_run.py` (or `kg2.job.run` from the nightly job); read `data\kg\audit_last.json`; if every gating
check passes, set `[kg] on = true`; `job.run` then loads the tables. Wiring (coordinator): call `kg2.job.run(con, root, day)` nightly after the filings/news collectors; feed
`kg.events.material_events` to `exits.check_thesis`; add a story adapter that adds `kg2_event` rows as evidence (`source_kind="kg2_event"`, `source_ref=event_id`) so the study can count.

## Shared files touched
None (only new files; `src/pflab/kg/events.py` is new inside the old package).

## What is left
Model classification of events runs only on request (`classify_limit`); a result-miss detector (needs consensus) does not exist (kind `results_miss` only by the model);
a scheduler hook for the collector's daily top-up (the collector backfills one year; a daily run of `run.py --days 3` keeps it current).

## Real path (2026-11-09 ~23:50, scope of 514 names, as-of 2026-11-09, collector paused for the audit and restarted after)
Collection: 365 days in ~32 min, 184,799 article rows (19 MB of rows), no failed day. Text pass was still running (about 9k pages kept, 40% of attempts refused/blocked).
Graph: 521 nodes, 3,363 facts, 4,320 relations (4,183 same_industry, 137 same_group_prefix), 91,294 events, 153,803 unlinked (counts below). Audit: PASSED, every gating check:
every row has isin/source/date (0 missing); point in time (0 after the day); filing link rate 99.94% on listed scrips (S80: 84.5%: cause in decision 5); news tag agreement 0 bad;
duplicates 0.0%; closed lists ok; rebuild byte-identical (needs the collector paused: two builds of a moving input differ, by design); sample of 50 written.
Informational: 3,444 filings in the 365-day file without a dissemination time were left out; the news link share is 14% because 114k rows are `text_pending` (text still being
fetched) and 36k tags-only rows have no second confirmation (peripheral mentions are not shown, by design). The local model classified 120 events (0 failed, ~5 s each).
The graph was NOT loaded into any store (switch OFF; throw-away in-memory store used). `data\kg\audit_last.json`, `audit_sample.csv`, `graph\*.parquet` hold the result.
For a rebuild that stays identical while the collector runs, pause it first: create `news_s81\STOP`, wait for exit, run `tools\kg2_run.py`, restart `run.py`.
Second collector run started 23:52 (log `D:\s81_scratch\kg_run\stdout2.log`; same command as above).
