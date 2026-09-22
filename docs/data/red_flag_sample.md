# Red-flag keyword sample — for review

Corpus: **41,128 BSE announcements** over 40 days, 2026-05-19 to 2026-09-16.
Flagged: **270** (0.66%).

Rules live in `pflab/data/red_flags.py`. They are a first draft and are **not** tuned against this sample — that is the point of the review. Nothing here feeds E1; this is E2-A groundwork.

## Hits per rule

| flag | hits | share of corpus |
|---|---|---|
| PROMOTER_ENCUMBRANCE | 73 | 0.177% |
| INSOLVENCY | 67 | 0.163% |
| AUDITOR_RESIGNATION | 66 | 0.160% |
| RESULTS_DELAY | 34 | 0.083% |
| RATING_DOWNGRADE | 13 | 0.032% |
| REGULATORY_ACTION | 12 | 0.029% |
| FRAUD | 3 | 0.007% |
| FORENSIC_AUDIT | 2 | 0.005% |
| DEFAULT | 2 | 0.005% |

## The 50 most common flagged headlines

Digits are replaced with `#` so near-identical headlines group.

| n | flags | headline (normalised) |
|---|---|---|
| 69 | PROMOTER_ENCUMBRANCE | the exchange has received the disclosures of reasons for encumbrance by promoter of listed companies under reg |
| 6 | INSOLVENCY | outcome of board meeting held on june #, # inter alia for consideration and approval of audited financial stat |
| 4 | PROMOTER_ENCUMBRANCE | the exchange has received the revised disclosures of reasons for encumbrance by promoter of listed companies u |
| 3 | AUDITOR_RESIGNATION | resignation of statutory auditor |
| 3 | INSOLVENCY | we hereby submitting newspaper clippings of unaudited standalone financial results of the arshiya limited (cir |
| 2 | INSOLVENCY | skil infrastructure limited has informed the exchange regarding un-audited standalone and consolidated financi |
| 2 | RESULTS_DELAY | delay in financial results |
| 2 | AUDITOR_RESIGNATION | resignation of statutory auditor of the company |
| 2 | RATING_DOWNGRADE | intimation of revision in credit rating |
| 2 | INSOLVENCY | corporate insolvency resolution process (cirp) - admission of application by tribunal |
| 2 | AUDITOR_RESIGNATION | as attached |
| 2 | AUDITOR_RESIGNATION | enclosed herewith resignation of statutory auditor w.e.f. #/#/# |
| 2 | AUDITOR_RESIGNATION | flexituff ventures international limited hereby submits resignation of statutory auditor of the company |
| 2 | AUDITOR_RESIGNATION | intimation for resignation of statutory auditors of the company. |
| 1 | REGULATORY_ACTION | pursuant to regulation # of sebi (lodr), #, intimation regarding show cause notice issued by excise & taxation |
| 1 | AUDITOR_RESIGNATION | disclosure for resignation of statutory auditors. |
| 1 | AUDITOR_RESIGNATION | the stock exchange and stakeholders are required to take note of the resignation of statutory auditor of the c |
| 1 | AUDITOR_RESIGNATION | resignation of internal auditor |
| 1 | FORENSIC_AUDIT | announcement under reg # (lodr) - appointment of forensic auditor |
| 1 | INSOLVENCY | hearing fixed on #.#.# could not be taken up. now the matter is listed for hearing on #.#.# |
| 1 | RESULTS_DELAY | delay in submission of financial results for the financial year ended march #,# |
| 1 | AUDITOR_RESIGNATION | intimation regarding appointment of secretarial auditors of the company due to casual vacancy caused by resign |
| 1 | AUDITOR_RESIGNATION | appointment of statuory auditor and resignation of statuory auditor |
| 1 | INSOLVENCY | we hereby submitting newspaper clippings of audited standalone financial results of the arshiya limited (cirp) |
| 1 | INSOLVENCY | the disclosure in enclosed herewith. |
| 1 | AUDITOR_RESIGNATION | change in management - appointment of dr. swetha as additional director, appointment of internal auditor and r |
| 1 | AUDITOR_RESIGNATION | pursuant to regulation # of the sebi (lodr) regulations, # read with schedule iii therto, we wish to inform yo |
| 1 | REGULATORY_ACTION | pursuant to reg # of sebi(lodr), #, the show cause notice of directorate general of gst intellligence (dggi) i |
| 1 | INSOLVENCY | resolution plans received by the resolution professional |
| 1 | INSOLVENCY | pursuant to the provisions of regulation # (#) (a) of sebi ( lodr) regulations, #, as amended, it is hereby in |
| 1 | AUDITOR_RESIGNATION | approval of the audited standalone and consolidated results for the financial year and quarter ended march #,  |
| 1 | RESULTS_DELAY | delay in financial results for the year ended #st march, # |
| 1 | INSOLVENCY | submission of financials for the year ended march #, # for shree hanuman sugar & industries limited (under cir |
| 1 | FORENSIC_AUDIT | forensic audit report intimation |
| 1 | AUDITOR_RESIGNATION | intimation pursuant to regulation # of the sebi (lodr) regulations, # pertaining to the resignation of secreta |
| 1 | RESULTS_DELAY | intimation regarding expected delay in submission of audited results of the company for year ended on #.#.# du |
| 1 | RESULTS_DELAY | intimation of delay related to submission of audited financial results for the year ended #.#.# |
| 1 | AUDITOR_RESIGNATION | submission of information pursuant to earlier disclosure dated november #, # regarding resignation of statutor |
| 1 | AUDITOR_RESIGNATION | enclosed herewith resignation of secretarial auditor announcement under sebi lodr # |
| 1 | AUDITOR_RESIGNATION | announcement under regulation # for resignation and appointment of secretarial auditor |
| 1 | AUDITOR_RESIGNATION | submission pursuant to resignation of statutory auditor. |
| 1 | REGULATORY_ACTION | further to our letter dated #b/cmrl/#/# dated may #,#,we would like to inform you that the enforcement directo |
| 1 | AUDITOR_RESIGNATION | pursuant to reg. # of sebi lodr please find attached resignation of statutory auditor w.e.f. #.#.# |
| 1 | AUDITOR_RESIGNATION | resignation of statutory auditor of the company w.e.f from closing of business hours #.#.# |
| 1 | INSOLVENCY | issuance of corporate gurantee to nrb-ibc bearings private limited and nibl-korta engineering private limited, |
| 1 | INSOLVENCY | prior-intimation of #th coc meeting of jatalia global ventures limited (under cirp) to be held on friday, #th  |
| 1 | AUDITOR_RESIGNATION | intimation of resignation of m/s. k s rao & associates, statutory auditors of the company. |
| 1 | RATING_DOWNGRADE | intimation for revision in the credit rating of ideaforge technology limited |
| 1 | AUDITOR_RESIGNATION | intimation under regulation # of sebi (lodr) regulations, #- resignation of statutory ayditor |
| 1 | INSOLVENCY | shirpur gold refinery limited has informed the exchange about non-submission of audited financial results (sta |

## What to look for

1. **False positives.** `PROMOTER_PLEDGE` matches the bare word `pledge`, so routine SAST 31(1) disclosures score the same as a distressed pledge invocation. Decide whether that is wanted.
2. **Over-broad abbreviations.** `REGULATORY_ACTION` includes `\bed\b` and `\bsat\b`, which are also ordinary English words.
3. **Missing rules.** The table below is the highest-volume *unflagged* headline shapes; anything in it that should be a red flag means a rule is absent.

## 25 most common unflagged headlines (for comparison)

| n | headline (normalised) |
|---|---|
| 1143 | the exchange has received the disclosure under regulation #(#) of sebi (substantial acquisition of shares & ta |
| 290 | outcome of board meeting |
| 192 | newspaper publication |
| 159 | closure of trading window |
| 139 | as attached |
| 134 | press release |
| 131 | as per attachment |
| 130 | enclosed |
| 115 | the exchange has received disclosure under regulation #(#) and #(#) of sebi (substantial acquisition of shares |
| 111 | annual secretarial compliance report |
| 110 | intimation of closure of trading window |
| 109 | investor presentation |
| 97 | annual secretarial compliance report for the financial year ended march #, # |
| 87 | attached |
| 73 | as enclosed |
| 72 | annual secretarial compliance report for the year ended march #, # |
| 61 | pfa |
| 59 | <b>format of initial disclosure to be made by an entity identified as a large corporate.</b><br/><br/> <table  |
| 52 | outcome of board meeting held on may #, # |
| 52 | pursuant to regulation # of the securities and exchange board of india (listing obligations and disclosure req |
| 51 | the exchange has received the disclosure under regulation #(#) in respect of acquisition under regulation #(#) |
| 50 | annual secretarial compliance report for the year ended march #, #. |
| 49 | copy of newspaper publication |
| 49 | annual secretarial compliance report for the financial year ended march #, #. |
| 47 | please refer the enclosed file. |

## Caveat on the window

This is 40 days, not the 2010 backfill the task list describes; `docs/PHASE1_SPRINT.md` defers that until after the first development run. It is enough to judge the *shape* of what the rules catch, not their long-run base rates.
