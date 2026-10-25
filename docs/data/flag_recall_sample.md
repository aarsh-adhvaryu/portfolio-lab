# Red-flag recall sample — unflagged announcements

Drawn 2026-09-30 by `tools/flag_audit_sample.py --recall`.
Seed **20260930**, fixed and recorded. 250 of 342,168 announcements dated
2017-01-01 .. 2021-12-31 on the audit's names that **no keyword rule
flags**. Universe: the audit's 894 names (E1's eligible set as drawn at 041ec33; ISIN list SHA-256 `51d2e612d79b356a…`).

A1 plan §5.4: K cannot see an event it missed, so this sample is the
only place recall shows. Masked as `flag_audit.md` is; **no returns and
no company names** (`mask_strict`: `mask_text` plus symbols, short name
tokens, ISINs, links and codes). Readers mark each row with the flag whose event it
is (or NONE) and a subtype from `flag_audit_labels.md`.

| row | headline (masked) | category | subcategory | flag or NONE | subtype |
|---|---|---|---|---|---|
| R1 | [CO] [CO] [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R2 | [CO] [CO] Ltd has informed BSE regarding notice of the National Company Law Tribunal (NCLT) convened meeting of the Equity Shareholders of the Company on [DATE]. | AGM/EGM | Court Convened Meeting |  |  |
| R3 | [CO] Ltd has informed BSE regarding "Details of Analyst / Institutional Investors Meet". | Company Update | General |  |  |
| R4 | Pursuant to Regulation 57(1) of Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, [DATE] ('Listing Regulations'), we hereby certify that .... | Company Update | General |  |  |
| R5 | Notice of Postal Ballot dated [DATE] | AGM/EGM | Postal Ballot |  |  |
| R6 | Pursuant to Regulation 30 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] (as amended), we wish to inform you that the Company has commenced commercial production .... | Company Update | General |  |  |
| R7 | Pursuant to Regulation 29 and other applicable provisions of the SEBI (Listing Obligations and Disclosure Requirements) Regulations [DATE] (Listing Regulations), we wish to inform that the .... | Board Meeting | Board Meeting |  |  |
| R8 | Please find enclosed Compliance Certificate Pursuant to Regulation 7(3) of the SEBI (Listing Obligations & Disclosure Requirements) Regulations, [DATE] for the half year ended [DATE] | Company Update | Reg. 7(3) – Compliance Certificate (RTA & Compliance Officer) |  |  |
| R9 | submission of audited Results for the year ended [DATE] | Result | Financial Results |  |  |
| R10 | SUB.: OUTCOME OF BOARD MEETING HELD ON [DATE].<BR> <BR> Dear Sir,<BR> <BR> This is in continuation to our letter dated [DATE]. This is to inform you that the Meeting of the .... | Result | Financial Results |  |  |
| R11 | Pursuant to Regulation 30, 42, 44 and other applicable Regulations of the Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, [DATE], please .... | Corp. Action | Record Date |  |  |
| R12 | [CO] [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R13 |  | Company Update | Reg. 13(3) - Statement of Investor Complaints |  |  |
| R14 | Revised Audited Financial Result for the quarter/year ended on [DATE] under the format prescribed in Schedule III to the Companies Act, [DATE] along with Auditor Report<BR> <BR> This .... | Result | Financial Results |  |  |
| R15 | Summary of the proceedings of the sixty eighth Annual General Meeting of the Company held on [DATE] | AGM/EGM | AGM |  |  |
| R16 | Pursuant to Regulation 33 of the SEBI Listing Regulations, the Board of Directors of the Company, at their meeting held today i.e. [DATE], have approved the Unaudited Standalone .... | Result | Financial Results |  |  |
| R17 | [CO] [CO] Ltd has informed BSE that the Board of Directors of the Company at its meeting held on [DATE], inter alia, has considered and approved the following:<BR><BR>- .... | AGM/EGM | AGM |  |  |
| R18 | Pursuant to Regulation 30 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], given below is the schedule of meetings with the Analyst / Institutional Investor .... | Company Update | Analyst / Investor Meet |  |  |
| R19 | Regulation 30(6) of SEBI (LODR) Regulations [DATE]- Update on Institutional Investors Meets - [CO].<BR> <BR> <BR> With reference to the subject cited above, we hereby forward the details .... | Company Update | Analyst / Investor Meet |  |  |
| R20 | This is to inform that the Interest Rates on Savings [CO] Deposits of the [CO] have been revised with effect from [DATE] and the interest rates will be as per the attached file. | Company Update | General |  |  |
| R21 | [CO] [CO] [CO] [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R22 | Sub: Overseas expansion<BR> <BR> This is to inform you that the Central [CO] of UAE has given approval to open a representative office of the [CO] [CO] [CO] in Dubai, UAE.<BR> .... | Company Update | General |  |  |
| R23 | The Exchange has received the disclosure under Regulation 29(2) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, [DATE] for [ACQUIRER] | Insider Trading / SAST | Disclosures under Reg. 29(2) of SEBI (SAST) Regulations, 2011 |  |  |
| R24 | Pursuant to Regulation 30 of the Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, [DATE], please note that the Company, as part of its .... | Company Update | Analyst / Investor Meet |  |  |
| R25 | Unaudited Financial Results in consonance with the new Accounting Standards for the quarter and half year ended [DATE] alongwith the Limited Review Report of the Auditors on .... | Result | Financial Results |  |  |
| R26 | This is to inform you that the month of [DATE] following Equity Shares of the Company (ISIN [ISIN]) have been dematerialized/ rematerialized. In this connection we send herewith .... | Company Update | General |  |  |
| R27 | Intimation of Participation in Conference Conducted by karvy Stock Broking Limited . | Company Update | Analyst / Investor Meet |  |  |
| R28 | [CO] [CO] [CO] Ltd has informed BSE that the Board of Directors of the Company, at their Meeting held on [DATE] declared a second interim dividend of Rs. 4/- (Rupees .... | Corp. Action | Dividend |  |  |
| R29 | This is to inform you that in terms of Company's Code of Conduct for Regulating, Monitoring and Reporting of Trading by Insiders, the trading window will remain closed from [DATE].... | Insider Trading / SAST | Closure of Trading Window |  |  |
| R30 | Proceeding of EGM | AGM/EGM | EGM |  |  |
| R31 | [CO] [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R32 | [CO] [CO] [CO] secures Product Patents in Aripo and South Korea | Company Update | Press Release / Media Release |  |  |
| R33 | Board meeting intimation pursuant to Regulation 29 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] to be held on Wednesday, [DATE] | Board Meeting | Board Meeting |  |  |
| R34 | Unaudited Financial Results of the [CO] for the third quarter and nine months ended [DATE] | Result | Financial Results |  |  |
| R35 | The Exchange has received the disclosure under Regulation 29(2) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, [DATE] for [ACQUIRER] | Insider Trading / SAST | Disclosures under Reg. 29(2) of SEBI (SAST) Regulations, 2011 |  |  |
| R36 | Please find enclosed herewith a copy of Investor Presentation with respect to Unaudited Standalone Financial Results for the quarter and nine months ended [DATE]. | Company Update | Investor Presentation |  |  |
| R37 | Disclosure under Regulation 30 of the SEBI (LODR) Regulations [DATE] | Company Update | General |  |  |
| R38 | Please find attached herewith investor Presentation and kindly take the same on your record. | Company Update | Investor Presentation |  |  |
| R39 | DISCLOSURE ON THE INVESTMENT THROUGH ACQUISITION OF 16, 00,000 EQUITY SHARES OF PAYPERMINT PRIVATE LIMITED, THE SUBSIDIARY COMPANY IN INDIA, BY WAY OF ITS RIGHTS ISSUE. | Company Update | General |  |  |
| R40 | [CO] [CO] Community Development Trust launches Mother and Child Health Initiative in Mumbai , Maharashtra | Company Update | Press Release / Media Release |  |  |
| R41 | [CO] Ltd has informed BSE regarding the details of Voting results of Postal Ballot, under Regulation 44(3) of SEBI (LODR) Regulations, [DATE]. Kindly .... | AGM/EGM | Postal Ballot |  |  |
| R42 | Board Meeting of [CO] [CO] Limited will be held on Tuesday, [DATE] at Mumbai, to discuss and approve, inter alia, the following:<BR> <BR> a.Audited Annual Financial Statements (Standalone .... | Insider Trading / SAST | Closure of Trading Window |  |  |
| R43 | Compliance Certificate for the half year ended [DATE]. | Company Update | Reg. 7(3) – Compliance Certificate (RTA & Compliance Officer) |  |  |
| R44 | Press Release | Company Update | Press Release / Media Release |  |  |
| R45 | [CO] [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R46 | [CO] [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R47 | Compliance Certificate under regulation 7(3) of the SEBI (LODR) Regulations, [DATE] | Company Update | Reg. 7(3) – Compliance Certificate (RTA & Compliance Officer) |  |  |
| R48 | [CO] Ltd has informed BSE that a meeting of the Board of Directors of the Company is scheduled to be held on [DATE] for considering and approving among others the Audited Financial .... | Corp. Action | Dividend |  |  |
| R49 | Intimation of Schedule of Investor Meeting on [DATE] and [DATE].<BR> | Company Update | Analyst / Investor Meet |  |  |
| R50 | Sub: Change in Board of Directors <BR> <BR> Pursuant to Regulation 30 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], please take note that the Board of .... | Company Update | Change in Directorate |  |  |
| R51 | The Exchange has received the disclosure under Regulation 31(1) and 31(2) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, [DATE] for [ACQUIRER] | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |  |
| R52 | <table border=''1''><tr bgcolor=''#d6d6d6''><th class=''TTRow_left''> No.of Investor complaints pending at the beginning of the quarter </th><th class=''TTRow''> No.of Investor complaints received during the quarter</th><th class=''TTRow''> No.of Investor complaints disposed of during the quarter </ | Company Update | Reg. 13(3) - Statement of Investor Complaints |  |  |
| R53 | <table border=''1''><tr bgcolor=''#d6d6d6''><th class=''TTRow_left''> No.of Investor complaints pending at the beginning of the quarter </th><th class=''TTRow''> No.of Investor complaints received during the quarter</th><th class=''TTRow''> No.of Investor complaints disposed of during the quarter </ | Company Update | Reg. 13(3) - Statement of Investor Complaints |  |  |
| R54 | [CO] [CO] [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R55 | The Exchange has received the disclosure under Regulation 29(1) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, [DATE] for [ACQUIRER] | Insider Trading / SAST | Disclosures under Reg. 29(1) of SEBI (SAST) Regulations, 2011 |  |  |
| R56 | We wish to inform you that the Company has allotted 3,13,439 Equity shares of Rs. 10/- each bearing distinctive numbers 690,051,042 to 690,364,480 on [DATE], under Employee .... | Company Update | Allotment of ESOP / ESPS |  |  |
| R57 | Schedule of Investor Meet made by the [CO] | Company Update | General |  |  |
| R58 | Please find attached details of Voting Results at the 35th Annual General Meeting (AGM) of the Company held on [DATE], under Regulation 44(3) of SEBI (LODR) Regulations, [DATE] .... | AGM/EGM | AGM |  |  |
| R59 | Copy of Notice published regarding loss of Share Certificates | Company Update | Newspaper Publication |  |  |
| R60 | [CO] [CO] [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R61 | [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R62 | The Exchange has received the disclosure under Regulation 10(6) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, [DATE] for [ACQUIRER] | Insider Trading / SAST | Disclosures under Reg. 10(6) of SEBI (SAST) Regulations, 2011 |  |  |
| R63 | This is with reference to revised rating of Brickwork for Fund Based Long Term, Non Fund Based Short Term and Non-Convertible Debentures. | Company Update | Credit Rating |  |  |
| R64 | [CO] [CO] [CO] Limited has informed the Exchange regarding Change in Director(s) of the Company. | Company Update | Change in Directorate |  |  |
| R65 | We send herewith the compliance certificate duly signed by the Compliance Officer of the Company and authorized representative of Karvy Computershare Private Limited, Registrar and Share .... | Company Update | Reg. 7(3) – Compliance Certificate (RTA & Compliance Officer) |  |  |
| R66 | We are enclosing herewith a press release titled '[CO] Africa announces the appointment of Board of Directors' issued by [CO] Africa Limited, a subsidiary company.<BR> <BR> Kindly take .... | Company Update | Press Release / Media Release (Revised) |  |  |
| R67 | We wish to inform you that at the meeting of Board of directors held on [DATE]. [DATE], the board has approved & adopted unaudited financial result for half year & second quarter ended [DATE] | Result | Financial Results |  |  |
| R68 | In terms of SEBI (Listing Obligations & Disclosure Requirements) Regulations, [DATE], we are to inform that, due to professional pre-occupation, Mr. Rajendra Naniwadekar has resigned as an .... | Company Update | Resignation of Director |  |  |
| R69 | The Company has allotted 208,250 equity shares under the [DATE] Stock Incentive Compensation Plan on [DATE] to eligible employees. | Company Update | Allotment of ESOP / ESPS |  |  |
| R70 | Analyst/Investor meet | Company Update | Analyst / Investor Meet |  |  |
| R71 | [CO] Ltd has informed BSE regarding Loss of Share Certificate / Issue of Duplicate Share Certificate. | Company Update | General |  |  |
| R72 | Please find enclosed herewith Intimation w.r.t. Appointment of Registrar and Share Transfer Agent of the Company for public issue of secured NCD. | Company Update | General |  |  |
| R73 | We enclose the Statement of deviation or variation in public issue, rights issue, preferential issue etc. for the quarter ended [DATE]. | Company Update | Reg. 32 (1), (3) - Statement of Deviation & Variation |  |  |
| R74 | Loss of Share Certificate / Issue of Duplicate Share Certificate | Company Update | General |  |  |
| R75 | The Company is planning to shut down one of the Crude Distillation units and Coker Unit of its DTA refinery at Jamnagar for routine maintenance and inspection activities for about 4 weeks .... | Company Update | General |  |  |
| R76 | Intimation of Closure of Trading Window. | Insider Trading / SAST | Closure of Trading Window |  |  |
| R77 | As required under the Listing Agreement entered into by us with your Stock Exchange and as per Regulation 33 of SEBI (Listing Obligation and Disclosure Requirements) Regulations [DATE], we .... | Result | Financial Results |  |  |
| R78 | [CO] [CO] & [CO] [CO] Ltd has informed BSE regarding Loss of Share Certificate / Issue of Duplicate Share Certificate. | Company Update | General |  |  |
| R79 | Un-audited Financial Results (Standalone) of the Company for the third quarter / nine months ended [DATE], along with the Limited Review Report thereon furnished by the Joint .... | Result | Financial Results |  |  |
| R80 | Outcome of Board Meeting of [CO] [CO] Limited held on [DATE].<BR> <BR> The meeting commenced at 4.00 p.m. and concluded at 4.30 p.m. | Result | Financial Results |  |  |
| R81 | Unaudited Financial Results for the quarter and nine months ended [DATE]. | Result | Financial Results |  |  |
| R82 | [CO] Ltd has informed BSE regarding Loss of Share Certificate / Issue of Duplicate Share Certificate. | Company Update | General |  |  |
| R83 | The Exchange has received the disclosure under Regulation 31(1) and 31(2) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, [DATE] for [ACQUIRER] | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |  |
| R84 | The Exchange has received the disclosure under Regulation 29(2) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, [DATE] for [ACQUIRER] | Insider Trading / SAST | Disclosures under Reg. 29(2) of SEBI (SAST) Regulations, 2011 |  |  |
| R85 | Intimation regarding loss of share certificate and issue of duplicate Share certificate of [CO] [CO] Limited pursuant to Regulation 39(3) of the SEBI (Listing Obligations and Disclosure .... | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R86 | Loss of Shares Certificates | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R87 | Please find enclosed herewith One on One Investor Meeting scheduled on [DATE]. | Company Update | Analyst / Investor Meet |  |  |
| R88 | Pursuant to Regulation 39(3) of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], please find enclosed the intimation received from our Registrar and Share Transfer .... | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R89 | The Exchange has received the disclosure under Regulation 10(5) in respect of acquisition under Regulation 10(1)(a) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, .... | Insider Trading / SAST | Disclosures under Reg. 10(5) in respect of acquisition under Reg. 10(1)(a) of SEBI (SAST) Reg. 2011 |  |  |
| R90 | Dear Sirs,<BR> <BR> We write to inform you that our Registrar & Transfer Agent (RTA) M/s Maheshwari Datamatics Private Ltd. has received request and required formalities from following .... | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R91 | [CO] [CO] [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R92 | Filing of Compliance Certificate under Regulation 7(3) for the quarter ended [DATE] | Company Update | Reg. 7(3) – Compliance Certificate (RTA & Compliance Officer) |  |  |
| R93 | Please find enclosed a copy of the press release titled 'Baring Private Equity Asia to acquire 30% stake in [CO] Technologies Limited from [CO] Limited and other promoter entities and make .... | Company Update | Press Release / Media Release |  |  |
| R94 | Please find attached herewith Announcement in respect of Award of Contract. | Company Update | Award of Order / Receipt of Order |  |  |
| R95 | We hereby confirm that during the half year ended on [DATE], all the activities in relation to the facility of transferring the Equity Shares of the Company, both in physical and .... | Company Update | Reg. 7(3) – Compliance Certificate (RTA & Compliance Officer) |  |  |
| R96 | [CO] receives approval from Russian Ministry of Healthcare to market Momate Rhino metered nasal spray as an Over-the-Counter (OTC) product | Company Update | Press Release / Media Release |  |  |
| R97 | Recommendation of final dividend subject to approval of members @ 1600% viz., INR 32 per equity share of INR 2/- each for the financial year [DATE]-19. The dividend, if declared at the ensuing .... | Corp. Action | Dividend |  |  |
| R98 | [CO] [CO] [CO] LTD.has informed BSE that the meeting of the Board of Directors of the Company is scheduled on [DATE] ,inter alia, to consider and approve Dear Sir,<BR> Pursuant .... | Board Meeting | Board Meeting |  |  |
| R99 | [CO] [CO] [CO] OF [CO] LTD.has informed BSE that the meeting of the Board of Directors of the Company is scheduled on [DATE] ,inter alia, to consider and approve Pursuant .... | Board Meeting | Board Meeting |  |  |
| R100 | [CO] receives final approval from the USFDA for Esomeprazole Magnesium Delayed-Release Capsules USP | Company Update | Press Release / Media Release |  |  |
| R101 | [CO] Ltd has informed BSE that the Register of Members & Share Transfer Books of the Company will remain closed from [DATE] to [DATE] (both days inclusive) for the purpose .... | AGM/EGM | Book Closure / AGM |  |  |
| R102 | With reference to Reg.30 of SEBI (Listing obligation and Disclosure Requirements) Regulations, [DATE], and Outcome of previous board meeting dated [DATE], we would like to disclose .... | Company Update | General |  |  |
| R103 | Pursuant to Regulation 23(9) of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] and all other applicable regulations, if any, the disclosures of related party .... | Result | Financial Results |  |  |
| R104 | Duplicate Issue of Share Certificate | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R105 | Pursuant to the relevant provisions of SEBI (Listing Obligations and Disclosure Requirements), Regulations [DATE], we would like to inform you that the officials of the Company will be participating .... | Company Update | Analyst / Investor Meet |  |  |
| R106 | Pursuant to Regulation 30 and 47 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], please find attached herewith the copy of newspaper clippings dated [DATE].... | Company Update | Newspaper Publication |  |  |
| R107 | Board of Directors have in their meeting held on [DATE] approved following :<BR> a) Reappointment of Ms Pooja Haldea as Independent Director, for the second consecutive term of five .... | Company Update | Change in Directorate |  |  |
| R108 | Information under Regulation 39(3) of the SEBI (Listing Obligations & Disclosure Requirements) Regulations, [DATE]. | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R109 | Dear Sir/ Madam,<BR> <BR> This is to inform you that the 12th AGM of the Company will be held on Wednesday, [DATE] at Swatantryaveer Savarkar Rashtriya Smarak, 252, Veer Savarkar .... | Company Update | General |  |  |
| R110 | Loss of Share Certificate | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R111 | Scrutinizer''s Report | AGM/EGM | AGM |  |  |
| R112 | Intimation under Regulation 30 of Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, [DATE] | Company Update | General |  |  |
| R113 | We wish to inform that [CO] has bagged further orders for Metro Coaches from M/s Delhi Metro Rail Corporation Limited (DMRC) for MMRDA Mumbai line 2&7 for additional 21 trainsets (126 Nos.) .... | Company Update | Award of Order / Receipt of Order |  |  |
| R114 | Intimation of Schedule of Analyst/Institutional Investor Meeting. | Company Update | Analyst / Investor Meet |  |  |
| R115 | Pursuant to Regulation 30(6) read with Schedule III of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] ("the Regulation").<BR> <BR> A copy of the Press Release .... | Company Update | Credit Rating |  |  |
| R116 | With reference to news appeared in [WEB] dated [DATE] quoting "[CO] [CO] gains 4% on debt reduction plan", [CO] [CO] & Power Ltd has submitted .... | Company Update | Clarification |  |  |
| R117 | Approval of Un-Audited Financial Results of the Company for the First Quarter ended on [DATE] and Outcome of the Board Meeting held on [DATE] | Result | Financial Results |  |  |
| R118 | We send herewith a copy of the Investor Brief: Sixth Edition, through which we intend to keep our shareholders abreast with the operational performance, the organic project pipeline, internal .... | Company Update | General |  |  |
| R119 | Intimation of Schedule of Analyst / Institutional Investor meeting | Company Update | Analyst / Investor Meet |  |  |
| R120 | Please find enclosed schedule of the Non deal roadshow held in Hong Kong on [DATE]. At this roadshow, the management of the Company met investors and a presentation was made to them. .... | Company Update | Analyst / Investor Meet |  |  |
| R121 | Pursuant to the Company's Code of Conduct to Regulate, Monitor and Report Trading by Insiders and Designated Persons and the SEBI (Prohibition of Insider Trading) Regulations, [DATE], we .... | Insider Trading / SAST | Closure of Trading Window |  |  |
| R122 | Consolidated Report of Scrutinizer for the Annual General meeting held on Thursday [DATE] | AGM/EGM | AGM |  |  |
| R123 | In terms of the Company's Code of Conduct to Regulate, Monitor and Report Trading by Insiders framed pursuant to SEBI (Prohibition of Insider Trading) Regulations, [DATE] read with SEBI (Prohibition .... | Insider Trading / SAST | Closure of Trading Window |  |  |
| R124 | Pursuant to Regulation 39(3) of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], please find enclosed the information regarding loss of share certificate(s) .... | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R125 | [CO] [CO] [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R126 | Further to our communication dated [DATE], we wish to inform that the Trading Window which was closed till [DATE] shall continue to remain closed for Directors, Statutory Central .... | Insider Trading / SAST | Closure of Trading Window |  |  |
| R127 | Pursuant to Regulation 30 & 33 of Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, [DATE], this is to inform you that the Board of Directors .... | Result | Financial Results |  |  |
| R128 | Investor meeting held on Tuesday, [DATE] at Mumbai | Company Update | Analyst / Investor Meet |  |  |
| R129 | Outcome of Analysts call attached | Company Update | Analyst / Investor Meet |  |  |
| R130 | The Exchange has received the disclosure under Regulation 29(2) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, [DATE] for [ACQUIRER] | Insider Trading / SAST | Disclosures under Reg. 29(2) of SEBI (SAST) Regulations, 2011 |  |  |
| R131 | Intimation under Regulation 30 of SEBI(LODR)Regulations, [DATE] w.r.t. Investor Conference to be held in Mumbai dated [DATE] | Company Update | Analyst / Investor Meet |  |  |
| R132 | [CO] [CO] & [CO] Ltd has informed BSE regarding the details of Voting results of Postal Ballot, under Regulation 44(3) of SEBI (LODR) Regulations, [DATE]. Kindly .... | AGM/EGM | Postal Ballot |  |  |
| R133 | In terms of Regulation 30 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], it is informed that the [CO] Board of Directors in their meeting held on .... | Company Update | General |  |  |
| R134 | Grant of stock options- Employee Stock Option Scheme [DATE] | Company Update | General |  |  |
| R135 | Intimation of Trading Window Closure | Insider Trading / SAST | Closure of Trading Window |  |  |
| R136 | Intimation under Regulation 39(3) - Loss of Share Certificates | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R137 | Press Clippings of Notice of Meeting of Board of Directors | Company Update | General |  |  |
| R138 | Issuance of Duplicate Share Certificate | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R139 | Grant of Stock Options | Company Update | General |  |  |
| R140 | In terms of Regulation 30 of the Listing Regulations, we wish to inform you that the Board of Directors of the Company at its meeting held on [DATE] has inter alia: <BR> <BR> .... | Board Meeting | Outcome of Board Meeting |  |  |
| R141 | [CO] [CO] Ltdhas informed BSE that the meeting of the Board of Directors of the Company is scheduled on [DATE] ,inter alia, to consider and approve The meeting of the Board of Directors .... | Board Meeting | Board Meeting |  |  |
| R142 | Dear Sir/ Madam,<BR> <BR> Please find enclosed herewith copies of the newspaper advertisement published in Financial Express (National English Daily) and Odisha Bhaskar (Odisha daily) pertaining .... | Company Update | Newspaper Publication |  |  |
| R143 | In terms of Regulation 30 read with para A of Part A of Schedule Ill of the Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, [DATE], we .... | Company Update | Analyst / Investor Meet |  |  |
| R144 | Intimation under Regulation 39 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R145 | Resignation of Mr. Sachin Tikekar, Nominee Director | Company Update | Change in Management |  |  |
| R146 | Pursuant to Regulation 39(3) of the SEBI (Listing Obligations and Disclosure Requirements) Regulations.[DATE], please find attached the intimation letter received from our Registrars and .... | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R147 | [CO] Limited had pursuant to the Resolution Plan approved by Hon'ble National Company Law Tribunal, Kolkata Bench dated [DATE] acquired Electrosteel Steels Limited (ESL), through .... | Company Update | General |  |  |
| R148 | [CO] Signs Pacts with Rosoboronexport, Coast Guard, IIT Kanpur and TAPL | Company Update | Press Release / Media Release |  |  |
| R149 | With reference to the above subject please find attached details of communication received from TSR Darashaw Consultants Private Ltd., Registrar and Share Transfer Agent of the [CO] .... | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R150 | Pursuant to Regulation 30 of the Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, [DATE], we wish to inform that ICRA Limited (ICRA) has .... | Company Update | Credit Rating |  |  |
| R151 | Intimation regarding loss of share certificate and issue of duplicate share certificate of [CO] [CO] Limited pursuant to Regulation 39(3) of the SEBI (Listing Obligations and Disclosure .... | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R152 | Pursuant to Regulation 29 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], and all other applicable provisions, if any, this is to inform you that the Board .... | Insider Trading / SAST | Closure of Trading Window |  |  |
| R153 | Intimation regarding Investor/ Analyst Meetings scheduled, attached. | Company Update | Analyst / Investor Meet |  |  |
| R154 | Temporary shut down of Plants and Offices due to COVID19 Pandemic | Company Update | General |  |  |
| R155 | The Exchange has received Disclosure under Regulation 31(1) and 31(2) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, [DATE] on [DATE] for Brijgopal Inani | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |  |
| R156 | Conference Call with Debt Investors | Company Update | General |  |  |
| R157 | Closure of Trading Window. | Insider Trading / SAST | Closure of Trading Window |  |  |
| R158 | <table border=''1''><tr bgcolor=''#d6d6d6''><th class=''TTRow_left''> No.of Investor complaints pending at the beginning of the quarter </th><th class=''TTRow''> No.of Investor complaints received during the quarter</th><th class=''TTRow''> No.of Investor complaints disposed of during the quarter </ | Company Update | Reg. 13(3) - Statement of Investor Complaints |  |  |
| R159 | Newspaper advertisement for Notice of Board Meeting | Company Update | Newspaper Publication |  |  |
| R160 | Intimation/certificate under Regulation 7(3) of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] | Company Update | Reg. 7(3) – Compliance Certificate (RTA & Compliance Officer) |  |  |
| R161 | <b>Format of Initial Disclosure to be made by an entity identified as a Large Corporate.</b><br/><br/> <table border=''1px''><tr> <td><b>Sr. No.</b></td> <td><b>Particulars</b></td> <td><b>Details</b></td> .... | Company Update | Funds raising by issuance of Debt Securities by Large Entities |  |  |
| R162 | Pursuant to the Scheme and approval of the National Company Law Tribunal ('NCLT'), Mumbai Bench and NCLT, Kolkata Bench, the Consumer Products Business of TCL has been demerged and stands .... | Company Update | General |  |  |
| R163 | Intimation under Regulation 30 and 51 of Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, [DATE] | Company Update | Credit Rating |  |  |
| R164 | This is to inform you that due to the global outbreak of Coronavirus disease [DATE] (COVID-19) and in compliance with the directives of the Government of India / State Governments, the [CO] .... | Company Update | General |  |  |
| R165 | Trading Window for dealing in shares of the Company, for persons specified under the Code, which has been closed from [DATE] will continue to remain closed till [DATE]. | Insider Trading / SAST | Closure of Trading Window |  |  |
| R166 | Disclosure under SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] (Listing Regulations)<BR> <BR> Pursuant to Regulation 30 of Listing Regulations, please find below .... | Company Update | Analyst / Investor Meet |  |  |
| R167 | Pursuant to Regulations 30 and 33 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], please find enclosed herewith Press Release with respect to Audited Financial .... | Company Update | Press Release / Media Release |  |  |
| R168 | The Exchange has received the disclosure under Regulation 29(2) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, [DATE] for [ACQUIRER] | Insider Trading / SAST | Disclosures under Reg. 29(2) of SEBI (SAST) Regulations, 2011 |  |  |
| R169 | Pursuant to Regulation 34(1) of the Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, [DATE], we are submitting a copy of the Company''s .... | Others | Reg. 34 (1) Annual Report |  |  |
| R170 | Allotment of Debentures on Private Placement Basis. | Company Update | Allotment of Equity Shares |  |  |
| R171 | Dear Sir/Madam,<BR> <BR> Pursuant to the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] ('Listing Regulations'), We are forwarding herewith copies of newspaper .... | Company Update | Newspaper Publication |  |  |
| R172 | [CO] [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R173 | Further to our letter dated [DATE] and pursuant to Regulation 33 of the Securities and Exchange Board of [CO] (Listing Obligations and Disclosure Requirements) Regulations, [DATE], .... | Company Update | Press Release / Media Release |  |  |
| R174 | Intimation of date of the Annual General Meeting and Book Closure for payment of dividend |  Corp Action | Date of payment of Dividend |  |  |
| R175 | We would like to inform you that the 47th Annual General Meeting (AGM) of the Shareholders of the Company will be held on Friday, the [DATE] at 11.30 a.m. through Video Conference .... | AGM/EGM | AGM |  |  |
| R176 | Attached | Company Update | General |  |  |
| R177 | Copies of newspaper advertisements titled "Notice of the Thirty-fifth Annual General Meeting and E-Voting Information" published in today''s English and Hindi newspapers - The Economic .... | Company Update | Newspaper Publication |  |  |
| R178 | Newspaper Publication- Completion of dispatch of Notice of 13th Annual General Meeting and Annual Report for the F.Y. [DATE]-20<BR> | Company Update | Newspaper Publication |  |  |
| R179 | the trading window of the Company for Directors/ officers/Designated Employees covered under "[CO] code of Conduct for prevention of Insider Trading" will be closed from [DATE] .... | Insider Trading / SAST | Closure of Trading Window |  |  |
| R180 | We would like to inform that the 58th Annual General Meeting (AGM) of the Company is scheduled to be held on Wednesday, the [DATE] at 10.30 a.m. through Video Conference .... |  Corp Action | Date of payment of Dividend |  |  |
| R181 | Allotment of 18,188 equity shares of Re.1/- each to eligible employees under Employee Stock Option Plan [DATE]. | Company Update | Allotment of ESOP / ESPS |  |  |
| R182 | The Exchange has received the disclosure under Regulation 29(2) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, [DATE] for [ACQUIRER] | Insider Trading / SAST | Disclosures under Reg. 29(2) of SEBI (SAST) Regulations, 2011 |  |  |
| R183 | The Exchange has received the disclosure under Regulation 29(2) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, [DATE] for [ACQUIRER] | Insider Trading / SAST | Disclosures under Reg. 29(2) of SEBI (SAST) Regulations, 2011 |  |  |
| R184 | Allotment of 214,613 equity shares under ESOS on [DATE] | Company Update | Allotment of ESOP / ESPS |  |  |
| R185 | <table border=''1''><tr bgcolor=''#d6d6d6''><th class=''TTRow_left''> No.of Investor complaints pending at the beginning of the quarter </th><th class=''TTRow''> No.of Investor complaints received during the quarter</th><th class=''TTRow''> No.of Investor complaints disposed of during the quarter </ | Company Update | Reg. 13(3) - Statement of Investor Complaints |  |  |
| R186 | [CO] [CO] Ltdhas informed BSE that the meeting of the Board of Directors of the Company is scheduled on [DATE] ,inter alia, to consider and approve Approving, interalia, the Unaudited .... | Board Meeting | Board Meeting |  |  |
| R187 | Unaudited Standalone and Consolidated Financial Results of the [CO] for the Quarter and Half year ended [DATE] <BR> | Result | Financial Results |  |  |
| R188 | In furtherance to our captioned letter, we wish to inform you that the Board of Directors of the Company, at their meeting held on [DATE], have inter-alia considered and approved .... | Board Meeting | Outcome of Board Meeting |  |  |
| R189 | In pursuance of Regulation 30 read with sub-clause 16(g) of Clause A of Part A of Schedule III of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] ("Listing .... | Company Update | Outcome of meeting of Committee of Creditors |  |  |
| R190 | Key Performance Highlights for the quarter and half-year ended on [DATE]. | Company Update | General |  |  |
| R191 | [CO] [CO] Ltd has informed BSE that the Board of Directors of the Company at its meeting held on [DATE], inter alia, has declared Interim Dividend of Rs. 1.75 per equity share .... | Corp. Action | Dividend |  |  |
| R192 | Disclosure of Related Party Transactions on a Consolidated Basis under regulation 23(9) of SEBI(LODR)Regulations,[DATE] | Result | Financial Results |  |  |
| R193 | In continuation to the letter of outcome of the Meeting of Board of Directors of the Company dated [DATE], intimating, inter-alia, about the resignation of Ms. Sunanda .... | Company Update | Resignation of Director |  |  |
| R194 | Outcome of the Meeting of the Board of Directors of the Company | Result | Financial Results |  |  |
| R195 | Pursuant to the Regulation 23(9) of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] we enclose herewith the half-yearly disclosure of Related Party Transactions .... | Result | Financial Results |  |  |
| R196 | Pursuant to Regulation 23(9) of the Listing Regulations, please find enclosed the disclosure on Related Party Transactions on a consolidated basis for the half year ended [DATE].... | Company Update | General |  |  |
| R197 | Trading Window closure from [DATE] to [DATE] | Insider Trading / SAST | Closure of Trading Window |  |  |
| R198 | Pursuant to SEBI (Prohibition of Insider Trading) Regulations, [DATE] and Company''s Code of Conduct for Prevention of Insider Trading, please be informed that the Trading Window for dealing .... | Insider Trading / SAST | Closure of Trading Window |  |  |
| R199 | This is to inform that [CO] [CO] Limited has awarded the work for 'Construction of Balance works/ rectification of defects for the works of HEART BEAT - 2 on as is where Basis at Heartbeat .... | Company Update | General |  |  |
| R200 | The Exchange has received Disclosure under Regulation 31(1) and 31(2) of SEBI (Substantial Acquisition of Shares & Takeovers) Regulations, [DATE] on [DATE] for Glebe Trading Pvt Ltd | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |  |
| R201 | <BR> We wish to inform that pursuant to the Company's Employee Stock Option Scheme- [DATE]'''' as amended, the Nomination and Remuneration Committee has approved the allotment of 1,13,400 .... | Company Update | Allotment of ESOP / ESPS |  |  |
| R202 | [CO] [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R203 | ADF [CO] LTD.-has informed BSE that the meeting of the Board of Directors of the Company is scheduled on [DATE] ,inter alia, to consider and approve Pursuant to Regulation 29 of the .... | Board Meeting | Board Meeting |  |  |
| R204 | [CO] LTD.has informed BSE that the meeting of the Board of Directors of the Company is scheduled on [DATE] ,inter alia, to consider and approve This is to inform you that a meeting of .... | Board Meeting | Board Meeting |  |  |
| R205 | Pursuant to Regulation 30 read with Schedule III of the Listing Regulations, we wish to inform you that a conference call with Analysts/ Investors has been scheduled on Tuesday, February .... | Company Update | Analyst / Investor Meet |  |  |
| R206 | [CO] LTD.has informed BSE that the meeting of the Board of Directors of the Company is scheduled on [DATE] ,inter alia, to consider and approve Pursuant to Regulation 29 and other .... | Board Meeting | Board Meeting |  |  |
| R207 | Interim Dividend for [DATE]-21 of ? 5.50 per equity share on 48,06,16,784 equity shares of ? 10/- each. The said dividend will be remitted on or after [DATE] to the equity shareholders .... |  Corp Action | Dividend Updates |  |  |
| R208 | With reference to the captioned subject and in compliance with the regulation 30 and other applicable regulation of the SEBI (listing Obligations and Disclosure Requirements) Regulations .... | Result | Financial Results |  |  |
| R209 | Please find enclosed the intimation letter dated [DATE] received from our RTA - M/s. TSR Darashaw Consultants Private Limited, providing information regarding loss of share .... | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R210 | We have been informed by our Registrar and Share Transfer Agents ('RTAs') viz. TSR Darashaw Consultants Private Ltd ('TSRDCPL') about shifting of their registered office from 6, Haji Moosa .... | Company Update | General |  |  |
| R211 | Pursuant to Regulation 30 of the Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, [DATE], please find enclosed herewith a copy of letter .... | Company Update | General |  |  |
| R212 | The Company had issued the Bonds in [DATE] which are currently listed on the Singapore Exchange<BR> Securities Trading Limited. Pursuant to our intimation letters dated [DATE] and [DATE].... | Company Update | General |  |  |
| R213 | we hereby confirm that activities in relation to both physical and electronic share transfer facility are maintained by the Company''s Registrar and Share Transfer Agent, viz., Link Intime .... | Company Update | Reg. 7(3) – Compliance Certificate (RTA & Compliance Officer) |  |  |
| R214 | In compliance with Regulation 40(10) of the Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, [DATE], ('LODR'), please find enclosed herewith .... | Company Update | Reg. 40 (10) - PCS Certificate for Transfer / Transmission / Transposition |  |  |
| R215 | [CO] [CO] [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R216 | Certificate under regulation 74(5) of the SEBI (Depositories<BR> and Participants) Regulations, [DATE] for the Quarter ended<BR> [DATE] | Company Update | Certificate under Reg. 74 (5) of SEBI (DP) Regulations, 2018 |  |  |
| R217 | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate - as per annexure enclosed | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R218 | Submission of Compliance Certificate under Regulation 7(3) for the half year ended [DATE]. | Company Update | Reg. 7(3) – Compliance Certificate (RTA & Compliance Officer) |  |  |
| R219 | Non - applicability of SEBI circular No. SEBI/HO/DDHS/CIR/P/[DATE]/144 <BR> dated [DATE] - Fund Raising by issuance of debt securities by Large Entities<BR> | Company Update | General |  |  |
| R220 | Pursuant to the applicable provisions of the SEBI Listing Regulations, we enclose the copies of newspaper advertisement published in Financial Express, Navshakti (Marathi) and Jansatta .... | Company Update | Post Buyback Public Announcement |  |  |
| R221 | [CO] [CO] [CO] Ltd has informed BSE regarding a Press Release dated [DATE] titled "Highlights of business performance for the year ended [DATE]". | Company Update | General |  |  |
| R222 | We wish to inform you that the Company had conducted an Annual Analyst Meet with Investors / Analysts on [DATE], with respect to the Standalone and Consolidated Financial Results .... | Company Update | General |  |  |
| R223 | In terms of Regulation 30 read with Para A of Part A of Schedule III to the SEBI Listing Regulations, we wish to inform you that the management of the Company will be having a Conference .... | Company Update | Analyst / Investor Meet |  |  |
| R224 | Intimation pursuant to Regulation 30(6) of Listing Regulations, [DATE] | Company Update | Credit Rating |  |  |
| R225 | In accordance with Ministry of Railways letter dated [DATE] bearing No. [DATE]/E(O)ll/40/19, Shri V Gopi Suresh Kumar, Director (Projects), in addition to his existing responsibilities, .... | Company Update | Change in Management |  |  |
| R226 | Intimation of loss of share certificates dated [DATE] | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R227 | Disclosure under Regulation 30 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] | Company Update | Monthly Business Updates |  |  |
| R228 | We enclose herewith a Statement of Unaudited Financial Results (Consolidated and Standalone) for the quarter ended [DATE] alongwith Limited Review Report submitted by the Statutory .... | Result | Financial Results |  |  |
| R229 | Pursuant to Regulation 23(9) of the SEBI (LODR) Regulations, [DATE], we are enclosing herewith a disclosure of Related Party Transactions on a consolidated basis for the half- year ended .... | Result | Financial Results |  |  |
| R230 | This is to inform that on completion of tenure of agreement with M/s Alankit Assignments Limited, M/s Beetal Financial & Computer Services Private Limited, Beetal House, 3rd Floor, 99, .... | Company Update | Allotment of Warrants |  |  |
| R231 | [CO] Biologics and Viatris Inc. Receive Historic Approval for First Interchangeable Biosimilar Semglee® (insulin glargine-yfgn injection) for the Treatment of Diabetes. | Company Update | Press Release / Media Release |  |  |
| R232 | We wish to inform that, pursuant to Regulation 39 (3) of the SEBI (Listing Obligations and Disclosure Requirements), [DATE] the Company has issued duplicate share certificate(s) in lieu of .... | Others | Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate |  |  |
| R233 | Intimation of schedule of Analyst/Institutional Investor Meets/Call. | Company Update | Analyst / Investor Meet |  |  |
| R234 | [CO] [CO] Ltd has informed BSE that the Register of Members & Share Transfer Books of the Company will remain closed from [DATE] to [DATE] (both days inclusive) .... | AGM/EGM | Book Closure / AGM |  |  |
| R235 | [CO] [CO] [CO] Ltd has informed BSE regarding the details of Voting results of AGM, under Regulation 44(3) of SEBI (LODR) Regulations, [DATE]. Kindly .... | AGM/EGM | AGM |  |  |
| R236 | please find enclosed herewith the Annual Report of the Company for the Financial Year [DATE]-21 which includes the Notice of 23rd Annual General Meeting of the Company as Annexure-A.<BR> .... | Others | Reg. 34 (1) Annual Report |  |  |
| R237 | Shri Sukhen Kumar Bandyopadhyay has ceased to be Director (Finance) of [CO] [CO] Ltd (HCL) w.e.f. [DATE] (Afternoon) consequent upon acceptance of his resignation by the Competent .... | Company Update | Change in Directorate |  |  |
| R238 | Please find attached herewith Investor Presentation on execution of Share Purchase Agreement between [CO] [CO] Limited, CESC Limited, Haldia Energy Limited and Nominal Shareholders .... | Company Update | Investor Presentation |  |  |
| R239 | [CO] [CO] adds a large new redevelopment project in Wadala, Mumbai | Company Update | Press Release / Media Release |  |  |
| R240 | Intimation of newspaper publication in Form INC-26 regarding shifting of Registered Office of the Company | Company Update | Newspaper Publication |  |  |
| R241 | [CO]. [CO] [CO] Ltd has submitted to BSE the Shareholding Pattern for the Period Ended [DATE]. For more details, kindly Click .... | Company Update | Shareholding |  |  |
| R242 | [CO] [CO] Ltdhas informed BSE that the meeting of the Board of Directors of the Company is scheduled on [DATE] ,inter alia, to consider and approve Pursuant to Regulation 29 of .... | Board Meeting | Board Meeting |  |  |
| R243 | <table border=''1''><tr bgcolor=''#d6d6d6''><th class=''TTRow_left''> No.of Investor complaints pending at the beginning of the quarter </th><th class=''TTRow''> No.of Investor complaints received during the quarter</th><th class=''TTRow''> No.of Investor complaints disposed of during the quarter </ | Company Update | Reg. 13(3) - Statement of Investor Complaints |  |  |
| R244 | We are enclosing herewith the certificate under Regulation 74(5) of SEBI (Depositories and Participants) Regulations, [DATE] as received from Registrar and Transfer Agent of the Company i.e. .... | Company Update | Certificate under Reg. 74 (5) of SEBI (DP) Regulations, 2018 |  |  |
| R245 | Related Party Disclosure for the half year ended [DATE] | Result | Financial Results |  |  |
| R246 | [CO] [CO] LTD.has informed BSE that the meeting of the Board of Directors of the Company is scheduled on [DATE] ,inter alia, to consider and approve Further to our letter dated .... | Board Meeting | Board Meeting |  |  |
| R247 | Pursuant to Regulation 33 of SEBI (Listing Obligation and Disclosure Requirements) Regulations, [DATE], we would like to inform you that the Board of Directors of the company at their Meeting .... | Result | Financial Results |  |  |
| R248 | Regulation 30 of the SEBI (LODR) Regulations, [DATE] - Press Release | Company Update | Press Release / Media Release |  |  |
| R249 | PRESS RELEASE | Company Update | Press Release / Media Release |  |  |
| R250 | This is to inform that in terms of the Company''s Code of conduct for prevention of insider trading in the securities of [CO] [CO] Limited, framed in accordance with SEBI (Prohibition .... | Insider Trading / SAST | Closure of Trading Window |  |  |
