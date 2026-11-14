# S86b progress (IST). One line per finished or dropped item. If resumed: read this first, continue from the first unfinished item for the clock's phase.
12:25 setup: branch pm/s86b-closeout from main v2026.11.14.2; scratch C:\Users\dnaad\AppData\Local\Temp/s86b
12:29 W1 built+tested (week_check criteria 6-14, ARM_FROM 16 Nov, problems list, pflab problems, /api/problems, page_loads middleware); tag at release
12:30 C1(2): conftest autouse clears hq.board._LIVE (leaked live task ids made reap return 0 in reversed order); proof = reversed suite
12:30 C2(b) live hour started in D:/s86b_scratch/live (kept)
12:31 C2(c) built+tested (through_funds, funds_text); C2(b) fixtures test added
12:34 C2(d) GDELT OFF in config (alarm_sources), merge_held wired earlier (merge_scope); amendment A81 to write
12:34 C4.1 exam fixes (keyword test, invalid reasons, stops); C4.2 OpenAI exam rerun STARTED (est Rs 41; month spend read before)
12:36 cli fix (timedelta shadow broke every command; test added); OpenAI exam rerun RESTARTED 12:40
12:38 C5.3 diagnosed: his xlsx/pdf ARE readable by the S85 reader (6 and 14 facts, Rs 1.70/7.23); old inbox rows said 0 -> chat context cites old rows; fixed with why_unreadable; Tijori link = redirect to the same PDF; links in files resolved. C5.1 real PDFs next
12:40 C5.1 real PDFs (11p refused by privacy screen: account-like number; 37p read in 2 parts, 2 facts, Rs 25.98; quote matching made punctuation-tolerant); C5.2 links true->supported Rs1.49, false->contradicted Rs1.25
12:42 C3.1 built+tested (scripted model)
12:46 C3.5 real gap RUN (Rs 3.77): ghost model look freeze (class unclear), live rule sells at next open; code-only ghost would sell Mon close 178.58 (cost Rs 830). harness in tools/s86b_real_gap.py, data D:/s86b_scratch/gap1
12:49 C2(a) first run: model flagged 43/63 plain-news items HIGH (19 genuine, 23 commentary, 1 wrong); added commentary filter + 12h new-look spacing; rerun nv2 started
12:49 C4(5): score_shadow already wired in score_due (S85) and tested (test file listed)
12:49 C3(6): rerunning march2020 replay with current code (A79 gauge protection) in background; log D:/s86b_scratch/march.log
12:50 C3(3) after-tax ghost scoring + protocol A4 done
12:55 C6 real-bars replay done (tools/s86b_us_bars.py): Thu pre-market decision 19:30 -> fill 20:05 first regular quote 156.18 (open 151.01); buy same day held, fills Fri 20:05; found+fixed: open-order names not quoted; first fill must be after the open minute
12:56 C4.2 OpenAI exam rerun DONE (medium 4/6, 0 facts missed, form FAIL 4 broken lists base_rate_set; high 4/6, form FAIL 5; Rs 15.86 + 25.19); C4.3 Claude exam does not fit cap (est Rs ~50/level), estimate only; C2(e) 2h lane run started (D:/s86b_scratch/live2h)
