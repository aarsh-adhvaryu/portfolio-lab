# Recall sample — rows for Aarsh to label

From `flag_recall_sample.md` (250 unflagged announcements). **3** rows that L (`qwen3.5-9b-16k`, digest `c1b119d707b9`) flags, plus **30** of the other 247 at random (seed 20260930), in row order, 33 in all. L's reading is **not shown**, so the label is blind; it is in `data/a1_readers/` and is joined after labelling.

**Labelled by Aarsh, 2026-09-30.** Every row not named below is NONE / NOT_EVENT. R63, R224: RATING_DOWNGRADE / UNCLEAR (a revision, direction not given). R189: INSOLVENCY / AT_COMPANY — a Committee of Creditors exists only in CIRP. L's reading was joined after labelling.

Mark each row with the flag whose event it is, or **NONE**, and a subtype from `flag_audit_labels.md` (AT_COMPANY, AGAINST_COMPANY, RELATED_ENTITY, NOT_EVENT, UNCLEAR).

| row | headline (masked) | category | subcategory | flag or NONE | subtype | L flag | L subtype |
|---|---|---|---|---|---|---|---|
| R6 | Pursuant to Regulation 30 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] (as amended), we wish to inform you that the Company has commenced commercial production .... | Company Update | General | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R7 | Pursuant to Regulation 29 and other applicable provisions of the SEBI (Listing Obligations and Disclosure Requirements) Regulations [DATE] (Listing Regulations), we wish to inform that the .... | Board Meeting | Board Meeting | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R11 | Pursuant to Regulation 30, 42, 44 and other applicable Regulations of the Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, [DATE], please .... | Corp. Action | Record Date | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R13 |  | Company Update | Reg. 13(3) - Statement of Investor Complaints | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R22 | Sub: Overseas expansion<BR> <BR> This is to inform you that the Central [CO] of UAE has given approval to open a representative office of the [CO] [CO] [CO] in Dubai, UAE.<BR> .... | Company Update | General | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R57 | Schedule of Investor Meet made by the [CO] | Company Update | General | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R63 | This is with reference to revised rating of Brickwork for Fund Based Long Term, Non Fund Based Short Term and Non-Convertible Debentures. | Company Update | Credit Rating | RATING_DOWNGRADE | UNCLEAR | RATING_DOWNGRADE | UNCLEAR |
| R68 | In terms of SEBI (Listing Obligations & Disclosure Requirements) Regulations, [DATE], we are to inform that, due to professional pre-occupation, Mr. Rajendra Naniwadekar has resigned as an .... | Company Update | Resignation of Director | NONE | NOT_EVENT | AUDITOR_RESIGNATION | AT_COMPANY |
| R73 | We enclose the Statement of deviation or variation in public issue, rights issue, preferential issue etc. for the quarter ended [DATE]. | Company Update | Reg. 32 (1), (3) - Statement of Deviation & Variation | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R81 | Unaudited Financial Results for the quarter and nine months ended [DATE]. | Result | Financial Results | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R106 | Pursuant to Regulation 30 and 47 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], please find attached herewith the copy of newspaper clippings dated [DATE].... | Company Update | Newspaper Publication | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R110 | Loss of Share Certificate | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R113 | We wish to inform that [CO] has bagged further orders for Metro Coaches from M/s Delhi Metro Rail Corporation Limited (DMRC) for MMRDA Mumbai line 2&7 for additional 21 trainsets (126 Nos.) .... | Company Update | Award of Order / Receipt of Order | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R121 | Pursuant to the Company's Code of Conduct to Regulate, Monitor and Report Trading by Insiders and Designated Persons and the SEBI (Prohibition of Insider Trading) Regulations, [DATE], we .... | Insider Trading / SAST | Closure of Trading Window | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R122 | Consolidated Report of Scrutinizer for the Annual General meeting held on Thursday [DATE] | AGM/EGM | AGM | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R130 | The Exchange has received the disclosure under Regulation 29(2) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, [DATE] for [ACQUIRER] | Insider Trading / SAST | Disclosures under Reg. 29(2) of SEBI (SAST) Regulations, 2011 | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R131 | Intimation under Regulation 30 of SEBI(LODR)Regulations, [DATE] w.r.t. Investor Conference to be held in Mumbai dated [DATE] | Company Update | Analyst / Investor Meet | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R148 | [CO] Signs Pacts with Rosoboronexport, Coast Guard, IIT Kanpur and TAPL | Company Update | Press Release / Media Release | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R152 | Pursuant to Regulation 29 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], and all other applicable provisions, if any, this is to inform you that the Board .... | Insider Trading / SAST | Closure of Trading Window | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R164 | This is to inform you that due to the global outbreak of Coronavirus disease [DATE] (COVID-19) and in compliance with the directives of the Government of India / State Governments, the [CO] .... | Company Update | General | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R166 | Disclosure under SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] (Listing Regulations)<BR> <BR> Pursuant to Regulation 30 of Listing Regulations, please find below .... | Company Update | Analyst / Investor Meet | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R167 | Pursuant to Regulations 30 and 33 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], please find enclosed herewith Press Release with respect to Audited Financial .... | Company Update | Press Release / Media Release | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R175 | We would like to inform you that the 47th Annual General Meeting (AGM) of the Shareholders of the Company will be held on Friday, the [DATE] at 11.30 a.m. through Video Conference .... | AGM/EGM | AGM | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R184 | Allotment of 214,613 equity shares under ESOS on [DATE] | Company Update | Allotment of ESOP / ESPS | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R185 | <table border=''1''><tr bgcolor=''#d6d6d6''><th class=''TTRow_left''> No.of Investor complaints pending at the beginning of the quarter </th><th class=''TTRow''> No.of Investor complaints received during the quarter</th><th class=''TTRow''> No.of Investor complaints disposed of during the quarter </ | Company Update | Reg. 13(3) - Statement of Investor Complaints | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R187 | Unaudited Standalone and Consolidated Financial Results of the [CO] for the Quarter and Half year ended [DATE] <BR> | Result | Financial Results | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R189 | In pursuance of Regulation 30 read with sub-clause 16(g) of Clause A of Part A of Schedule III of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] ("Listing .... | Company Update | Outcome of meeting of Committee of Creditors | INSOLVENCY | AT_COMPANY | NONE | NOT_EVENT |
| R195 | Pursuant to the Regulation 23(9) of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] we enclose herewith the half-yearly disclosure of Related Party Transactions .... | Result | Financial Results | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R196 | Pursuant to Regulation 23(9) of the Listing Regulations, please find enclosed the disclosure on Related Party Transactions on a consolidated basis for the half year ended [DATE].... | Company Update | General | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R211 | Pursuant to Regulation 30 of the Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, [DATE], please find enclosed herewith a copy of letter .... | Company Update | General | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R213 | we hereby confirm that activities in relation to both physical and electronic share transfer facility are maintained by the Company''s Registrar and Share Transfer Agent, viz., Link Intime .... | Company Update | Reg. 7(3) – Compliance Certificate (RTA & Compliance Officer) | NONE | NOT_EVENT | NONE | NOT_EVENT |
| R224 | Intimation pursuant to Regulation 30(6) of Listing Regulations, [DATE] | Company Update | Credit Rating | RATING_DOWNGRADE | UNCLEAR | RATING_DOWNGRADE | UNCLEAR |
| R226 | Intimation of loss of share certificates dated [DATE] | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate | NONE | NOT_EVENT | NONE | NOT_EVENT |

## Recall (2026-09-30)

Two strata of the 250: the 3 rows L flags (all labelled) and 30 of the
other 247 (weight 247/30). Events are counted per announcement; NOT_EVENT
is not an event.

| | L-flagged (3) | other 247 (30 read) | estimated events in the 250 |
|---|---|---|---|
| any subtype | 2 (R63, R224) | 1 (R189) | 2 + 247/30 = **10.2** |
| AT_COMPANY | 0 | 1 (R189) | **8.2** |

- **K** finds none of these by construction. Scaled to the pool (342,168
  unflagged; K's flagged 2,094 hold ≈ 1,971 events, 1,683 AT_COMPANY, by
  the audit's per-flag subtype shares): **K recall ≈ 12%** (any subtype),
  **13%** (AT_COMPANY). The whole missed estimate rests on one row: with
  1 of 30's 95% Wilson interval (0.6%–16.7%) the range is **3%–29%** and
  3%–46%.
- **L** on the unflagged pool finds **2 of 10.2 ≈ 20%** (both rating
  revisions of unknown direction) and **0 of 8.2 AT_COMPANY**; it missed
  R189. L's flags there are 2 of 3 right (R68 is a director's resignation,
  not an auditor's).
- Reading: K's misses include repeat filings of a running event (R189 is a
  CoC outcome of an admitted CIRP), so announcement recall understates
  event-level recall; an event-level measure needs the first filing per
  event, which this sample cannot give. Nothing is changed because of it.
