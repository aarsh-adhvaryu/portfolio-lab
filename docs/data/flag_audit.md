# Red-flag precision audit — for the investor to label

Drawn 2026-09-25. Seed **20260925**, fixed and
recorded, so the sample is reproducible and cannot be redrawn until it
looks better.

Up to 30 events per flag, at random from **2017-01-01 .. 2021-12-31**,
restricted to names in E1's eligible universe at some month-end in the
window — so every row is an event the strategy could have acted on.

**Company names and dates are masked, and there are no returns
anywhere in this file.** The question is whether the headline is the
event the flag names: a question about the keyword rules, not about the
company or the outcome. A labeller who can see the name can recall what
happened to it, and one who can see the return is being asked a
different question. The regex that caught each row is deliberately NOT
shown here either; it goes in the report written after labelling.

## How to label

Put one of these in the **label** column:

- **TRUE** — the headline is the event the flag names.
- **FALSE** — it is not.
- **UNSURE** — the headline does not say enough to tell.

UNSURE is a real answer, not a failure to decide: a headline that
cannot be judged from its own text is itself a finding about the rule.

## Population each flag was drawn from

| flag | events in window | sampled |
|---|---|---|
| AUDITOR_RESIGNATION | 110 | 30 |
| DEFAULT | 163 | 30 |
| FORENSIC_AUDIT | 14 | 14 |
| FRAUD | 118 | 30 |
| INSOLVENCY | 412 | 30 |
| PROMOTER_ENCUMBRANCE | 819 | 30 |
| RATING_DOWNGRADE | 277 | 30 |
| REGULATORY_ACTION | 154 | 30 |
| RESULTS_DELAY | 27 | 27 |

## The sample

| row | flag | headline (masked) | category | subcategory | label |
|---|---|---|---|---|---|
| 1 | AUDITOR_RESIGNATION | We wish to inform you that M/s. Price Waterhouse Chartered Accountants LLP have resigned as the Statutory Auditors of the Company vide their letter dated [DATE]. The Board of .... | Company Update | Resignation of Statutory Auditors |  |
| 2 | AUDITOR_RESIGNATION | This is to inform that M/s. Price Waterhouse & Co Chartered Accountants LLP, (FRN 304026E/300009) Statutory Auditors of the Company, vide letter dated [DATE] have resigned from .... | Company Update | Resignation of Statutory Auditors |  |
| 3 | AUDITOR_RESIGNATION | We understand that there are unconfirmed rumours in the market relating to the resignation of Statutory Auditors of the Company. <BR> <BR> The Company wishes to clarify that the Company .... | Company Update | General |  |
| 4 | AUDITOR_RESIGNATION | This is to inform that M/s. Price Waterhouse Chartered Accountants LLP, (FRN012754N/N500016), Statutory Auditors of the Company, vide their letter dated [DATE] have resigned from .... | Company Update | Resignation of Statutory Auditors |  |
| 5 | AUDITOR_RESIGNATION | Pursuant to Regulation 30 of Securities and Exchange Board of India (Listing Obligations & Disclosure Requirements) Regulations, [DATE], we would like to inform you that Mr. Hrushikesh S. .... | Company Update | Resignation of Statutory Auditors |  |
| 6 | AUDITOR_RESIGNATION | This is to inform you that one of our Joint Statutory Auditors i.e. M/s S S A Y & Associates, Chartered Accountants, (Firm Registration No. 012493N) vide their letter dated [DATE].... | Company Update | Resignation of Statutory Auditors |  |
| 7 | AUDITOR_RESIGNATION | This is to inform you pursuant to the regulation 30 of SEBI (Listing Obligations & Disclosure Requirements) Regulations, [DATE] that the Company has received intimation from its Statutory .... | Company Update | Resignation of Statutory Auditors |  |
| 8 | AUDITOR_RESIGNATION | Dear Sir/Madam <BR> <BR> Pursuant to Regulation 30 read with Para A of Part A of Schedule III of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], we would like .... | Company Update | Resignation of Statutory Auditors |  |
| 9 | AUDITOR_RESIGNATION | M/s. Khandelwal Kakani & Co., offered its resignation as on<BR> [DATE]. Consequent to which,Board of Directors in their meeting held on [DATE] appointed M/s SPJV & Company, Chartered .... | Company Update | Resignation of Statutory Auditors |  |
| 10 | AUDITOR_RESIGNATION | We would like to intimate that M/s. Pamita Doshi & Co., Chartered Accountants (Firm Registration no. 141976W), Statutory Auditor of the company has resigned due to their pre occupation .... | Company Update | Resignation of Statutory Auditors |  |
| 11 | AUDITOR_RESIGNATION | Pursuant to Regulation 30 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], we hereby inform that the present Statutory Auditors of the Company M/s. Sekhar & .... | Company Update | Resignation of Statutory Auditors |  |
| 12 | AUDITOR_RESIGNATION | Pursuant to Regulation 30 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], kindly note that M/s. Varma & Varma, Chartered Accountants, have resigned as Statutory .... | Company Update | Resignation of Statutory Auditors |  |
| 13 | AUDITOR_RESIGNATION | Disclosure under Regulation 30 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] ('the Regulations') <BR> <BR> In continuation of our letter dated [DATE].... | Company Update | Resignation of Statutory Auditors |  |
| 14 | AUDITOR_RESIGNATION | [CO] [CO] - Intimation regarding resignation of M/s. Deloitte Haskins & Sells LLP as statutory auditors and appointment of M/s Lodha & Co as statutory auditors in the casual vacancy. | Company Update | Resignation of Statutory Auditors |  |
| 15 | AUDITOR_RESIGNATION | Intimation for informing that one of the joint statutory auditors of the Company viz., Deloitte Haskins & Sells LLP (Firm Regn. No. 117366W/W-100018), vide their letter dated [DATE].... | Company Update | Resignation of Statutory Auditors |  |
| 16 | AUDITOR_RESIGNATION | Resignation of Statutory Auditor of the Company | Company Update | Resignation of Statutory Auditors |  |
| 17 | AUDITOR_RESIGNATION | M/s. Batliboi, Purohit & Darbari, Chartered Accountants, Statutory Auditors of the Company, have resigned with effect from the conclusion of the meeting of the Board of Directors of the .... | Company Update | Appointment of Statutory Auditor/s |  |
| 18 | AUDITOR_RESIGNATION | Pursuant to Regulation 30 (2) of SEBI (Listing Obligation and Disclosure Requirement) Regulation, [DATE]; we wish to inform you that M/s. Deloitte Haskins & Sells LLP (Firm Registration no: .... | Company Update | Resignation of Statutory Auditors |  |
| 19 | AUDITOR_RESIGNATION | Please find attached herewith views of audit committee as required vide the aforesaid circular of SEBI regarding disclosure of audit committee's view upon resignation of auditor.<BR> <BR> .... | Company Update | General |  |
| 20 | AUDITOR_RESIGNATION | In pursuance of Regulation 30 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] read with SEBI circular No. CIR/CFD/CMD1/114/[DATE] dated [DATE], this .... | Company Update | Resignation of Statutory Auditors |  |
| 21 | AUDITOR_RESIGNATION | Please note that Mr. Sanjeev Maheshwari (one of the senior partners of M/s. GMJ & Co, Chartered Accountants) has been nominated by the Central Government as a non-official director on the .... | Company Update | Resignation of Statutory Auditors |  |
| 22 | AUDITOR_RESIGNATION | Resignation of statutory auditor | Company Update | Resignation of Statutory Auditors |  |
| 23 | AUDITOR_RESIGNATION | The Audit Committee of the RPP [CO] Project Limited in their meeting held Today i.e. [DATE],considered and approved the resignation of Auditor and appointment of New Auditor of the .... | Company Update | Meeting Updates |  |
| 24 | AUDITOR_RESIGNATION | In pursuance of Regulation 30 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] read with SEBI circular No. CIR/CFD/CMD1/114/[DATE] dated [DATE]<BR> [DATE], this .... | Company Update | Resignation of Statutory Auditors |  |
| 25 | AUDITOR_RESIGNATION | [CO] [CO] Limited informed the exchange regardiing Resignation of Statutory Auditors. | Company Update | Resignation of Statutory Auditors |  |
| 26 | AUDITOR_RESIGNATION | Disclosure under Regulation 30 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] - Change of Statutory Auditors | Company Update | Resignation of Statutory Auditors |  |
| 27 | AUDITOR_RESIGNATION | Dear Sir,<BR> In pursuance of Regulation 30 of SEBI (Listing Obligations and Disclosure Requirements)<BR> Regulations,[DATE] read with SEBI circular No. CIR/CFD/CMD1/114/[DATE] dated [DATE].... | Company Update | Resignation of Statutory Auditors |  |
| 28 | AUDITOR_RESIGNATION | Disclosure under Regulation 30 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], as amended (the "SEBI Listing Regulations, [DATE]") - Resignation of Statutory Auditors. | Company Update | Resignation of Statutory Auditors |  |
| 29 | AUDITOR_RESIGNATION | Change in Statutory Auditors - Disclosure under Regulation 30 read with Schedule III of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] - Resignation of Statutory Auditors | Company Update | Resignation of Statutory Auditors |  |
| 30 | AUDITOR_RESIGNATION | Intimation under Regulation 30 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] (Listing Regulations) - change in statutory auditors | Company Update | Resignation of Statutory Auditors |  |
| 31 | DEFAULT | [CO] [CO] [CO] Ltd has informed BSE regarding "Default in Payment of principal and interest due on Non-Convertible Debentures (NCDs)". | Company Update | General |  |
| 32 | DEFAULT | [CO] [CO] [CO] Ltd has informed BSE regarding "Default in Payment of interest due on Non-Convertible Debentures (NCDs). | Company Update | General |  |
| 33 | DEFAULT | [CO] [CO] [CO] Ltd has informed BSE regarding "Default in Payment of Interest due on Non-Convertible Debentures (NCDs)". | Company Update | General |  |
| 34 | DEFAULT | [CO] [CO] [CO] Ltd has informed BSE regarding "Default in Payment of Interest due on Non-Convertible Debentures (NCDs)". | Company Update | General |  |
| 35 | DEFAULT | [CO] [CO] [CO] Ltd has informed BSE regarding "Default in Payment of Interest due on Non-Convertible Debentures (NCDs)". | Company Update | General |  |
| 36 | DEFAULT | [CO] [CO] [CO] Ltd has informed BSE regarding "Default in Payment of Interest due on Non-Convertible Debentures (NCDs)". | Company Update | General |  |
| 37 | DEFAULT | [CO] [CO] [CO] Ltd has informed BSE regarding "Default in Payment of Interest due on Non-Convertible Debentures (NCDs)". | Company Update | General |  |
| 38 | DEFAULT | Pursuant to the captioned SEBI Circular, please find enclosed disclosure of defaults on payment of interest / repayment of principal amount on loans from banks / financial institution and .... | Company Update | General |  |
| 39 | DEFAULT | Intimation pursuant to Regulation 51(2) of LODR - Default in Payment of Interest due on Non-Convertible Debentures (NCDs) | Company Update | General |  |
| 40 | DEFAULT | Intimation pursuant to Regulation 51(2) of LODR - Default in Payment of Interest due on Non-Convertible Debentures (NCDs) | Company Update | General |  |
| 41 | DEFAULT | Intimation pursuant to Regulation 51(2) of LODR - Default in Payment of Interest due on Non-Convertible Debentures (NCDs) | Company Update | General |  |
| 42 | DEFAULT | DISCLOSURE PURSUANT TO CIRCULAR NO SEBI/HO/CFD/CMD1/CIR/P/[DATE]/140 DATED [DATE] REGARDING DEFAULT IN PAYMENT OF INTEREST / REPAYMENT OF PRINCIPAL AMOUNT ON LOANS FROM BANKS / .... | Company Update | General |  |
| 43 | DEFAULT | Please find attached herewith the Intimation regarding default in payment of interest due on Non-Convertible Debentures (NCDs) | Company Update | General |  |
| 44 | DEFAULT | Disclosure of defaults on payment of interest / repayment of principal amount on loans from banks / financial institutions | Company Update | General |  |
| 45 | DEFAULT | Intimation pursuant to Regulation 51(2) of LODR - Default in Payment of Interest due on Non-Convertible Debentures (NCDs) | Company Update | General |  |
| 46 | DEFAULT | Intimation pursuant to Regulation 51(2) of LODR - Default in Payment of Interest due on Non-Convertible Debentures (NCDs) | Company Update | General |  |
| 47 | DEFAULT | Intimation pursuant to Regulation 51(2) of LODR - Default in Payment of Interest due on Non-Convertible Debentures (NCDs) | Company Update | General |  |
| 48 | DEFAULT | Intimation pursuant to Regulation 51(2) of LODR - Default in Payment of Interest due on Non-Convertible Debentures (NCDs) | Company Update | General |  |
| 49 | DEFAULT | Intimation pursuant to Regulation 51(2) of LODR - Default in Payment of Interest due on Non-Convertible Debentures (NCDs) | Company Update | General |  |
| 50 | DEFAULT | Intimation under Regulation 51(2) of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] [SEBI (LODR)] - Default in Payment of Interest due on Non-Convertible Debentures .... | Company Update | General |  |
| 51 | DEFAULT | Intimation pursuant to Regulation 51(2) of LODR - Default in Payment of Interest due on Non-Convertible Debentures (NCDs) | Company Update | General |  |
| 52 | DEFAULT | Intimation under Regulations 30 and 51(2) of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] - Default in payment of interest / principal due on Non-Convertible .... | Company Update | General |  |
| 53 | DEFAULT | Intimation pursuant to Regulation 51(2) of LODR - Default in Payment of Interest due on Non-Convertible Debentures (NCDs) | Company Update | General |  |
| 54 | DEFAULT | Intimation pursuant to Regulation 51(2) of LODR - Default in Payment of Interest due on Non-Convertible Debentures (NCDs) | Company Update | General |  |
| 55 | DEFAULT | Intimation under Regulation 51(2) of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] [SEBI (LODR)) - Default in Payment of Interest due on Non-Convertible Debentures .... | Company Update | General |  |
| 56 | DEFAULT | The disclosure of defaults on payment of interest/ repayment of principal amount on loans from banks/ financial institution by the Company for the quarter ended [DATE] is submitted .... | Company Update | General |  |
| 57 | DEFAULT | Intimation under Regulation 51(2) of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] [SEBI (LODR)] - Default in Payment of Interest due on Non-Convertible Debentures .... | Company Update | General |  |
| 58 | DEFAULT | Intimation under Regulation 51(2) of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] [SEBI (LODR)] - Default in Payment of Interest due on Non-Convertible Debentures .... | Company Update | General |  |
| 59 | DEFAULT | In terms of the captioned SEBI circular, we enclose herewith the relevant disclosure of defaults on payment of interest/repayment of principal amount on loans from banks/financial institutions .... | Company Update | General |  |
| 60 | DEFAULT | In terms of the captioned SEBI circular, we enclose herewith the relevant disclosure of defaults on payment of interest/repayment of principal amount on loans from banks/financial institutions .... | Company Update | General |  |
| 61 | FORENSIC_AUDIT | The [CO] had sought clarification from [CO] [CO] [CO] of [CO] Ltd with respect to news appearing in Livemint on [DATE] titled "Sebi seeks forensic audit of MCX's .... | Company Update | Clarification |  |
| 62 | FORENSIC_AUDIT | The [CO] has sought clarification from [CO] [CO] [CO] of [CO] Ltd with respect to news article appearing on Livemint on [DATE] titled "SEBI seeks forensic audit .... | Company Update | Clarification |  |
| 63 | FORENSIC_AUDIT | The Exchange has sought clarification from [CO] [CO] [CO] with respect to news article appearing on The Economic Times- [DATE] titled "PNB Appoints BDO for Forensic Audit .... | Company Update | Clarification |  |
| 64 | FORENSIC_AUDIT | Appointment of Forensic Auditor & Updates on matters under Insolvency & Bankruptcy Code, [DATE]. | Company Update | General |  |
| 65 | FORENSIC_AUDIT | Appointment of Forensic Auditor & Updates on matters under Insolvency & Bankruptcy Code, [DATE]. | Company Update | General |  |
| 66 | FORENSIC_AUDIT | [CO] [CO] [CO] Limited informed the Exchanges that the Resolution Professional CA Ms. Rita Gupta had appointed M/s. M.K. Aggarwal & Co., as Forensic Auditor to look into the .... | Company Update | General |  |
| 67 | FORENSIC_AUDIT | With reference to news appeared on : CNBC TV18 dated [DATE] quoting "Lenders move towards conducting forensic audit into books of [CO] [CO] after allegations of fraud/siphoning .... | Company Update | Clarification |  |
| 68 | FORENSIC_AUDIT | With reference to news appeared in www.business-standard.com dated [DATE] quoting, "SBI orders forensic audit of Jet's accounts from [DATE] to [DATE]", Jet [CO] [CO] .... | Company Update | Clarification |  |
| 69 | FORENSIC_AUDIT | The [CO] had sought clarification from [CO] [CO] [CO] of [CO] Ltd with reference to the media report, "Forensic auditors indicate IGIDR used data shared by MCX to develop .... | Company Update | Clarification |  |
| 70 | FORENSIC_AUDIT | The Board of [CO] [CO] Ltd. in its meeting today has considered the report of the forensic audit and it has decided to terminate the employment of Mr. Rajesh Mokashi as MD & CEO of [CO] .... | Company Update | General |  |
| 71 | FORENSIC_AUDIT | Forensic Audit | Company Update | General |  |
| 72 | FORENSIC_AUDIT | UPL denies reporting in certain section of the media that SEBI has initiated a forensic audit with respect to the whistle-blower complaint. UPL is asking SEBI to inquire about this and .... | Company Update | Press Release / Media Release |  |
| 73 | FORENSIC_AUDIT | Appointment of Forensic Auditor by SEBI. | Company Update | General |  |
| 74 | FORENSIC_AUDIT | This is to inform that the Board at its meeting held on [DATE] noted the appointment of KPMG Assurance and Consulting Services LLP and DmKH & Co. as the Forensic Auditors of the .... | Company Update | General |  |
| 75 | FRAUD | [CO] [CO] [CO] Ltd has informed BSE regarding "Press Coverage - Two more arrested in [CO] [CO] Fraud Case ". | Company Update | General |  |
| 76 | FRAUD | The Exchange had sought clarification from [CO] [CO] Ltd with respect to news appearing in Mint on [DATE] titled "CBI charges Mallya with fraud, criminal conspiracy." .... | Company Update | Clarification |  |
| 77 | FRAUD | The [CO] has come across a suspected fraud involving Rs.280.70 crores based on preliminary investigation report and the detailed investigation is on. | Company Update | General |  |
| 78 | FRAUD | The Exchange had sought clarification from [CO] [CO] Ltd with respect to news appearing in Times of India - [DATE] titled "Fraud charge on [CO] Infra in insolvency court" .... | Company Update | Clarification |  |
| 79 | FRAUD | The Exchange has sought clarification from [CO] [CO] Ltd with respect to news article appearing on http://www.thehindu.com - [DATE] titled "PNB fraud - ED summons Nirav .... | Company Update | Clarification |  |
| 80 | FRAUD | The Exchange has sought clarification from [CO] [CO] [CO] with respect to news article appearing on www.business-standard.com - [DATE] titled "Govt asks fraud-hit [CO] .... | Company Update | Clarification |  |
| 81 | FRAUD | The Exchange has sought clarification from [CO] [CO] [CO] with respect to news article appearing on economictimes.indiatimes.com - [DATE] titled "Fraud-hit PNB looking .... | Company Update | Clarification |  |
| 82 | FRAUD | The Exchange had sought clarification from [CO] [CO] Ltd with respect to news appearing in www.timesofindia.com - [DATE] titled "Fortis, [CO] face serious fraud .... | Company Update | Clarification |  |
| 83 | FRAUD | Fresh CBI Complaint against Chirag Computers maker For 515 crore fraud - Livemint.pdf | Company Update | General |  |
| 84 | FRAUD | The Exchange has sought clarification from [CO] [CO] with respect to news article appearing on www.thehindu.com - [DATE] titled "ED attaches 38.07 cr. in [CO] fraud case against .... | Company Update | Clarification |  |
| 85 | FRAUD | The Exchange had sought clarification from [CO] [CO] with respect to news article appearing in www.thehindu.com - [DATE] "ED attaches 38.07 cr. in [CO] fraud case against Abhijeet Group". .... | Company Update | Clarification |  |
| 86 | FRAUD | The Exchange has sought clarification from [CO] [CO] [CO] with respect to news Flash appearing on CNBC TV18 - [DATE] titled "CBI to Special Court: Fraud amount by Gitanjali .... | Company Update | Clarification |  |
| 87 | FRAUD | The Exchange has sought clarification from [CO] [CO] of [CO] with respect to news article appearing on www.ndtv.com - [DATE] titled "CBI Files Rs. 1,394 crore [CO] Fraud Case .... | Company Update | Clarification |  |
| 88 | FRAUD | [CO] reports fraud to RBI. | Company Update | General |  |
| 89 | FRAUD | News clarification 'CBI books ex-GM of [CO] for Rs.445.32 crore fraud." | Company Update | General |  |
| 90 | FRAUD | The Exchange has sought clarification from [CO] [CO] with respect to news article appearing on timesofindia.com - [DATE] titled "CBI books two PSB heads, ex-IDBI chief for fraud". .... | Company Update | Clarification |  |
| 91 | FRAUD | The Exchange has sought clarification from [CO] Ltd with respect to news article appearing on The Economics Times - [DATE] titled "[CO] whistleblower raises fresh concerns .... | Company Update | Clarification |  |
| 92 | FRAUD | The Exchange has sought clarification from [CO] of [CO] with respect to news article Newspaper-www.freepressjournal.in - [DATE] "[CO] of [CO] fraud: CBI arrests former GM and DGM .... | Company Update | Clarification |  |
| 93 | FRAUD | The Exchange had sought clarification from Jet [CO] [CO] Ltd with reference to the media report, "Regional Director report finds instances of siphoning of funds".<BR><BR>Jet [CO] .... | Company Update | Clarification |  |
| 94 | FRAUD | Clarification on news appearing in Media with regard to Whistle Blower Complaint against the Company | Company Update | General |  |
| 95 | FRAUD | VIVA Kuwait renews a multi-year contract for Revenue Assurance and Fraud Management with [CO] | Company Update | Press Release / Media Release |  |
| 96 | FRAUD | Clarifications in relation to certain media reports on fresh whistleblower complaints | Company Update | General |  |
| 97 | FRAUD | [CO] Reports Fraud To RBI. | Company Update | General |  |
| 98 | FRAUD | Press Release- [CO] and RAG announce first of its kind alliance to leverage Blockchain for combatting fraud. | Company Update | Press Release / Media Release |  |
| 99 | FRAUD | As disclosed previously, the Company had received letters from regulatory authorities seeking information on the anonymous whistleblower investigation. The Company continues to cooperate .... | Company Update | General |  |
| 100 | FRAUD | This has reference to the news item circulating regarding alleged fraud to the tune of Rs.7926 Crore by M/s Transstroy India Ltd . In this regard, it is clarified that the company was enjoying .... | Company Update | General |  |
| 101 | FRAUD | This is with reference to the clarification sought by your good office on media report captioned 'SBI declares <BR> accounts of Anil Ambani''s three [CO] Group firms fraud' and subsequently .... | Company Update | General |  |
| 102 | FRAUD | Reporting of Fraud to RBI. | Company Update | General |  |
| 103 | FRAUD | With reference to your email dated [DATE] the information is provided below:<BR> 1. Nature of fraud/default/arrest: - At this point in time, it is not known whether there is any fraud/default. .... | Company Update | General |  |
| 104 | FRAUD | Disclosure of Information under Regulation 30 of the SEBI (LODR)<BR> Regulations, [DATE]: Reporting of Borrowal Fraud of [CO]''s Exposure | Company Update | General |  |
| 105 | INSOLVENCY | Dear Sir/Madam <BR> <BR> This is further to our intimation dated [DATE] regarding the application filed by Corporation Bank for initiation of Corporate Insolvency Resolution Process .... | Company Update | General |  |
| 106 | INSOLVENCY | National Company Law Tribunal ('Tribunal') under Section 7(2) of Insolvency and Bankruptcy Code, [DATE] ('The Code') has admitted an application from Union Bank of India for our wholly owned .... | Company Update | Award of Order / Receipt of Order |  |
| 107 | INSOLVENCY | Update on hearing before Hon'ble NCLT on Petition filed by IDBI Bank under Insolvency and Bankruptcy Code. | Company Update | General |  |
| 108 | INSOLVENCY | Update on the hearing before Hon'ble Supreme Court of Writ Petition filed in respect of Insolvency Resolution Process under Insolvency and Bankruptcy Code. | Company Update | General |  |
| 109 | INSOLVENCY | <BR> Please find enclosed a copy of Media Release on our company has received 'India's Most Trusted Company Award- [DATE]' from IBC InfoMedia Pvt. Ltd. (A Division of International Brand .... | Company Update | Press Release / Media Release |  |
| 110 | INSOLVENCY | Updates in the matter of liquidation proceedings filed by LIC Housing Finance Ltd. in the NCLT against the Company.<BR> <BR> <BR> <BR> Furtherance to our earlier letter dated [DATE], .... | Company Update | Press Release / Media Release |  |
| 111 | INSOLVENCY | [CO] [CO] [CO] Limited submitted with exchanges Copy of Interim Order in the matter filed under IBC, [DATE] against the Company.As per the said order, the Insolvency process which .... | Company Update | General |  |
| 112 | INSOLVENCY | Intimation for Extension of Time in completion of Corporate Insolvency Resolution Process (CIRP) of [CO] [CO] Limited. | Company Update | General |  |
| 113 | INSOLVENCY | [CO] [CO] Limited is under Corporate Insolvency Resolution Process and Shri Anuj Jain was appointed Interim Resolution Professional (Now Resolution Professional).<BR> <BR> In terms .... | Insider Trading / SAST | Closure of Trading Window |  |
| 114 | INSOLVENCY | We refer to the intimation made to the Stock Exchanges on [DATE] regarding commencement of Corporate Insolvency Resolution Process (CIRP) and appointment of Interim Resolution .... | Company Update | Updates - Corporate Insolvency Resolution Process  (CIRP) |  |
| 115 | INSOLVENCY | This is to inform you that pursuant to Regulation 29 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE], the Resolution Professional (RP) of the Company is proposing .... | Company Update | General |  |
| 116 | INSOLVENCY | Intimation of Commencement of Corporate Insolvency Resolution Process (CIRP) and appointment of Interim Resolution Professional (IRP) / Resolution Professional (RP) of Nakshatra World Limited .... | Company Update | General |  |
| 117 | INSOLVENCY | Liquidation of [CO] Netherlands Holdings B.V, a step down subsidiary of the Company. | Company Update | General |  |
| 118 | INSOLVENCY | Reference to the Corporate Insolvency Resolution Process of Jaypee Infratech Limited (JIL) and our previous intimation vide letter dated [DATE], wherein it was informed that [CO] .... | Company Update | General |  |
| 119 | INSOLVENCY | This is in connection with the petition filed under section 7 of Insolvency and Bankruptcy Code, [DATE] by GUARANTCO LTD. a Mauritius based entity against CALCOM CEMENT INDIA LIMITED, a subsidiary .... | Company Update | Press Release / Media Release |  |
| 120 | INSOLVENCY | This has with reference to the captioned subject this is to apprise you regarding the Public Announcement of the initiation of corporate insolvency resolution process and call for the submission .... | Company Update | Public Announcement |  |
| 121 | INSOLVENCY | Sub: Disclosure under Regulation 30 (2) read with Schedule III of Securities and Exchange Board of India (Listing Obligations & Disclosure Requirements) Regulations, [DATE] - Extension in .... | Company Update | Updates - Corporate Insolvency Resolution Process  (CIRP) |  |
| 122 | INSOLVENCY | In view of the undergoing Corporate Insolvency Resolution Process ('CIRP) of [CO] Limited ('the Company') under the provisions of Insolvency and Bankruptcy Code, [DATE] ('Code'), the Resolution .... | Company Update | Meeting Updates |  |
| 123 | INSOLVENCY | The meeting of Resolution Professional and KMP was held on [DATE] under the supervision and control of Mr. Shailendra Ajmera, Resolution Professional, whereby, 229100 (Two .... | Company Update | General |  |
| 124 | INSOLVENCY | Disclosure under Regulation 30 of the SEBI (Listing Obligation & Disclosure Requirements) Regulation, [DATE] read with Schedule III, Part A, Clause A, sub-clause 16(f) in respect of material .... | Company Update | Replacement of Interim Resolution Professional (IRP) |  |
| 125 | INSOLVENCY | Intimation for Invitation of Scheme of Compromise and Arrangement under Section 230 of the Companies Act, [DATE] | Company Update | Liquidation - Corporate Insolvency Resolution Process  (CIRP) |  |
| 126 | INSOLVENCY | A copy of the order passed by the Hon''ble Supreme Court on [DATE] is attached. | Company Update | Updates - Corporate Insolvency Resolution Process  (CIRP) |  |
| 127 | INSOLVENCY | Reference to the Corporate Insolvency Resolution Process of Jaypee Infratech Limited (JIL) and our previous intimation dated [DATE] wherein status of hearing in<BR> the case .... | Company Update | General |  |
| 128 | INSOLVENCY | Consideration and approval of the Un-audited Financial Results (Standalone and Consolidated) for the First quarter ended [DATE] | Company Update | Updates - Corporate Insolvency Resolution Process  (CIRP) |  |
| 129 | INSOLVENCY | Updates on Corporate Insolvency Resolution Process (CIRP). Enclosing Order of the Hon'ble NCLT. | Company Update | General |  |
| 130 | INSOLVENCY | Listing of matter of Resolution Plan at Hon''ble NCLT, Principal Bench, Delhi | Company Update | Updates - Corporate Insolvency Resolution Process  (CIRP) |  |
| 131 | INSOLVENCY | Disclosure under Regulation 30 of Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, [DATE] (LODR) read with sub clause 16(h) of Para A .... | Company Update | Updates - Corporate Insolvency Resolution Process  (CIRP) |  |
| 132 | INSOLVENCY | Updates of next date of hearing | Company Update | Updates - Corporate Insolvency Resolution Process  (CIRP) |  |
| 133 | INSOLVENCY | Outcome of Meeting of Resolution Professional & Directors | Result | Financial Results |  |
| 134 | INSOLVENCY | Update on the next date of hearing at Hon''ble NCLT, Principal Bench, New Delhi | Company Update | Updates - Corporate Insolvency Resolution Process  (CIRP) |  |
| 135 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on October .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 136 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on October .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 137 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on October .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 138 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on October .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 139 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on October .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 140 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on October .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 141 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on October .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 142 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on December .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 143 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on December .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 144 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on December .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 145 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on February .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 146 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on March .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 147 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on March .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 148 | PROMOTER_ENCUMBRANCE | The Exchange has received the revised Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 149 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on September .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 150 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on September .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 151 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on September .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 152 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on October .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 153 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on January .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 154 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on January .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 155 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on February .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 156 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on March .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 157 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on May .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 158 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on May .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 159 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on June .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 160 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on July .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 161 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on July .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 162 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on August .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 163 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on August .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 164 | PROMOTER_ENCUMBRANCE | The Exchange has received the Disclosures of reasons for encumbrance by promoter of listed companies under Reg. 31(1) read with Regulation 28(3) of SEBI (SAST) Regulations, [DATE] on October .... | Insider Trading / SAST | Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011 |  |
| 165 | RATING_DOWNGRADE | Revision in Credit Rating by CRISIL Limited | Company Update | Credit Rating |  |
| 166 | RATING_DOWNGRADE | Revision in Credit Rating. | Company Update | Credit Rating |  |
| 167 | RATING_DOWNGRADE | [CO] [CO] [CO] Limited Intimation on Revision in Credit Ratings pursuant to Regulation 30 of SEBI(LODR) Regulations , [DATE] | Company Update | Credit Rating |  |
| 168 | RATING_DOWNGRADE | Revision in Credit Rating | Company Update | Credit Rating |  |
| 169 | RATING_DOWNGRADE | Revision in credit rating | Company Update | Credit Rating |  |
| 170 | RATING_DOWNGRADE | [CO] [CO] Limited has informed the Exchange regarding revision in Credit Rating outlook by CRISIL. | Company Update | Credit Rating |  |
| 171 | RATING_DOWNGRADE | Intimation of Revision in Credit Rating<BR> <BR> Pursuant to Regulation 30 read along with Schedule III of SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] ('the .... | Company Update | Credit Rating |  |
| 172 | RATING_DOWNGRADE | In terms of the provisions of Regulation 30 of Listing Regulations, it is hereby informed that there has been a revision in the credit ratings by CRISIL Limited w.r.t Debt Instruments/facilities .... | Company Update | Credit Rating |  |
| 173 | RATING_DOWNGRADE | PRESS RELEASE - YES [CO]'S foreign currency issuer rating downgraded to Ba1 from Baa3 by Moody''s Investors Service; Outlook changed to negative | Company Update | Press Release / Media Release |  |
| 174 | RATING_DOWNGRADE | Please find attached herewith Intimation under Regulation 30 of SEBI (Listing Obligations and Disclosure Requirements), [DATE] regarding revision in Credit Rating of [CO] [CO] Limited | Company Update | Credit Rating |  |
| 175 | RATING_DOWNGRADE | Intimation of Revision in Credit Rating pursuant to Regulation 30 of the SEBI (Listing Obligations & Disclosure Requirements) Regulations, [DATE]. | Company Update | Credit Rating |  |
| 176 | RATING_DOWNGRADE | ICRA downgrades YES [CO]'s Long-Term ratings with Negative Outlook; Ratings removed from 'Watch with Negative Implications' | Company Update | Credit Rating |  |
| 177 | RATING_DOWNGRADE | Revision in Credit Rating of Wholly Owned Subsidiary | Company Update | General |  |
| 178 | RATING_DOWNGRADE | The Exchange has sought clarification from [CO] [CO] Ltd with respect to news article appearing on www.thehindubusinessline.com [DATE], titled "Fitch downgrades IDR ratings of .... | Company Update | Clarification |  |
| 179 | RATING_DOWNGRADE | Intimation of Revision in Credit Rating | Company Update | Credit Rating |  |
| 180 | RATING_DOWNGRADE | We wish to inform you that [CO] Ratings and Research has downgraded the Company's Long term Credit Rating to 'IND BBB-' from 'IND BBB' and maintained it on Rating watch Negative.<BR> .... | Company Update | Credit Rating |  |
| 181 | RATING_DOWNGRADE | The Exchange has sought clarification from [CO] [CO] Ltd with respect to news article appearing on www.business-standard.com [DATE], titled "ICRA downgrades [CO] [CO] to default". .... | Company Update | Clarification |  |
| 182 | RATING_DOWNGRADE | Revision in Credit Rating of the company | Company Update | Credit Rating |  |
| 183 | RATING_DOWNGRADE | Revision in Credit Ratings | Company Update | Credit Rating |  |
| 184 | RATING_DOWNGRADE | PRESS RELEASE - Moody's places Yes [CO]'s ratings under review for downgrade | Company Update | Press Release / Media Release |  |
| 185 | RATING_DOWNGRADE | Intimation of revision in Credit Rating | Company Update | Credit Rating |  |
| 186 | RATING_DOWNGRADE | Revision in Credit rating for debt programme and bank facilities of [CO] [CO] Limited by CRISIL | Company Update | Credit Rating |  |
| 187 | RATING_DOWNGRADE | [CO] [CO] Limited has informed regarding revision in Credit Rating by Brickworks | Company Update | Credit Rating |  |
| 188 | RATING_DOWNGRADE | [CO] [CO] Ltd has informed BSE regarding "Intimation of Revision in Credit Rating". | Company Update | Credit Rating |  |
| 189 | RATING_DOWNGRADE | The Exchange had sought clarification from [CO] Ltd with respect to news article appearing on infralive.com [DATE] titled "CRISIL downgrades ratings for [CO] to B as business .... | Company Update | Clarification |  |
| 190 | RATING_DOWNGRADE | Revision in Credit Rating | Company Update | Credit Rating |  |
| 191 | RATING_DOWNGRADE | Revision in Credit Rating. | Company Update | Credit Rating |  |
| 192 | RATING_DOWNGRADE | Intimation of Revision in Credit Rating | Company Update | Credit Rating |  |
| 193 | RATING_DOWNGRADE | Intimation of Revision in Credit Ratings | Company Update | Credit Rating |  |
| 194 | RATING_DOWNGRADE | With reference to the above subject, we wish to inform you that ACUITE RATINGS & RESEARCH LIMITED, the Credit Rating Agency, have downgraded the credit rating of the Company vide its Letter .... | Company Update | Credit Rating |  |
| 195 | REGULATORY_ACTION | The Exchange has sought clarification from [CO] [CO] Ltd with respect to news article appearing on dnaindia.com on [DATE] titled "CBI books [CO] [CO] officials for Rs 100.57 crore .... | Company Update | General |  |
| 196 | REGULATORY_ACTION | The Exchange had sought clarification from [CO] [CO] Ltd with respect to news appearing on dnaindia.com on [DATE] titled "CBI books [CO] [CO] officials for Rs 100.57 crore deposits .... | Company Update | General |  |
| 197 | REGULATORY_ACTION | With reference to news flashed on BTVi dated [DATE] quoting "SFIO grilled Bhushan [CO]'s CFO Nitn Johri; Allegation- Rs 5,000 Cr Re-routed Via Hawala Operators To Promoters", Bhushan .... | Company Update | Clarification |  |
| 198 | REGULATORY_ACTION | The Exchange had sought clarification from [CO] [CO] Ltd with respect to news article appearing on CNBC TV18 on [DATE] titled "CBI files FIR against Dilip Jiwrajka of [CO] [CO]" .... | Company Update | Clarification |  |
| 199 | REGULATORY_ACTION | We wish to inform you that Mr Bharat K Sheth, Deputy Chairman and Managing Director has intimated to the [CO] that SEBI has passed an Order dated [DATE] as an ex parte ad interim .... | Company Update | General |  |
| 200 | REGULATORY_ACTION | This has reference to BSE mail dated [DATE] seeking clarification on recent news item appearing in Financial Express dated [DATE], titled 'CBI books [CO] director-finance .... | Company Update | General |  |
| 201 | REGULATORY_ACTION | The Exchange has sought clarification from [CO] Ltd with respect to news article appearing on Financial Express on [DATE] titled "CBI books [CO] director-finance for corruption" .... | Company Update | Clarification |  |
| 202 | REGULATORY_ACTION | Press Release - Order Passed by Hon. CBI Special Court today in Connection with 2G Spectrum Case. | Company Update | Press Release / Media Release |  |
| 203 | REGULATORY_ACTION | The Company has learnt that SEBI uploaded on its website an order dated [DATE] passed by an adjudicating officer of SEBI (Ref no Adjudication Order No RA/DPS/271/[DATE]) imposing .... | Company Update | General |  |
| 204 | REGULATORY_ACTION | The Exchange has sought clarification from [CO] [CO] [CO] with respect to news article appearing on www.business-standard.com on [DATE] titled "CBI registers Rs 800-million .... | Company Update | Clarification |  |
| 205 | REGULATORY_ACTION | The Exchange has sought clarification from [CO] Ltd with respect to news article appearing on www.thehindu.com on [DATE] titled "CBI to investigate [CO], MMTC, others over coal imports" .... | Company Update | Clarification |  |
| 206 | REGULATORY_ACTION | With reference to news item appearing in The Hindu dated [DATE] captioned " CBI to investigate NTPC, [CO], others over coal imports", please find the clarification from the company enclosed. .... | Company Update | General |  |
| 207 | REGULATORY_ACTION | The Exchange has sought clarification from [CO] [CO] [CO] with respect to news article appearing on Times of India - [DATE] titled "CBI unearths fraud at Barmer PNB, files .... | Company Update | Clarification |  |
| 208 | REGULATORY_ACTION | Fresh CBI Complaint against Chirag Computers maker For 515 crore fraud - Livemint.pdf | Company Update | General |  |
| 209 | REGULATORY_ACTION | The Exchange had sought clarification from [CO] [CO] Ltd with respect to news appearing on www.moneycontrol.com on [DATE] titled "SFIO awaits ministry nod to investigate .... | Company Update | Clarification |  |
| 210 | REGULATORY_ACTION | The Exchange had sought clarification from [CO] of [CO] with respect to news appearing www.business-standard.com - [DATE] titled "Rs 29-bn Rotomac case: CBI questions former .... | Company Update | Clarification |  |
| 211 | REGULATORY_ACTION | The Exchange has sought clarification from [CO] [CO] with respect to news article appearing on timesofindia.com - [DATE] titled "CBI books two PSB heads, ex-IDBI chief for fraud". .... | Company Update | Clarification |  |
| 212 | REGULATORY_ACTION | The Exchange has sought clarification from [CO] [CO] with respect to news article appearing on timesofindia.com - [DATE] titled "CBI books two PSB heads, ex-IDBI chief for fraud". .... | Company Update | Clarification |  |
| 213 | REGULATORY_ACTION | The Exchange had sought clarification from [CO] of [CO] with respect to news article appearing onwww.thehindu.com - [DATE] "CBI files four more cases in Srijan scam".<BR><BR>[CO] .... | Company Update | Clarification |  |
| 214 | REGULATORY_ACTION | The Exchange had sought clarification from [CO] & [CO] Ltd with respect to news article appearing on www.moneycontrol.com- [DATE] "SFIO receives complaints against ICICI Bank, LT" .... | Company Update | Clarification |  |
| 215 | REGULATORY_ACTION | The Exchange has sought clarification from [CO] [CO] Ltd with respect to news article appearing on www.moneycontrol.com- [DATE] titled "SFIO receives complaints against [CO] [CO], LT". .... | Company Update | Clarification |  |
| 216 | REGULATORY_ACTION | Clarification regarding the News Item appearing in Times of India, Hyderabad Edition dated 16th Day of [DATE] about [CO] [CO] Limited ('Company') titled 'SFIO to probe .... | Company Update | General |  |
| 217 | REGULATORY_ACTION | With reference to news appeared in www.economictimes.indiatimes.com dated [DATE] quoting, " Coal scam: Enforcement Directorate attaches assets worth over Rs 117 crore of company", .... | Company Update | Clarification |  |
| 218 | REGULATORY_ACTION | We would like to inform you that the Income Tax Department., vide its letter dated [DATE] (received by the company on [DATE]), has withdrawn the provisional attachment .... | Company Update | General |  |
| 219 | REGULATORY_ACTION | This is to inform you that no raid of CBI has happened on Indiabulls Group or any of its offices. The CBI Raids have happened on Yes bank/ Rana Kapoor who have their offices in Indiabulls .... | Company Update | General |  |
| 220 | REGULATORY_ACTION | Adjudication Order passed by SEBI | Company Update | General |  |
| 221 | REGULATORY_ACTION | The Exchange has sought clarification from Cox & [CO] Ltd with respect to news article appearing on www.ndtv.com [DATE] titled "Enforcement Directorate Raids Premises Of Cox and .... | Company Update | Clarification |  |
| 222 | REGULATORY_ACTION | We hereby inform you that SEBI has passed an Impounding Order cum Show Cause notice bearing no. WTM/GM/IVD/14/[DATE]-21 dated [DATE] against Mr. L. Kishore Babu, Chief Financial Officer .... | Company Update | General |  |
| 223 | REGULATORY_ACTION | The Adjudicating Officer of SEBI has imposed a monetary penalty of Rs 1 Crore on the Company on [DATE] for alleged failure to close the trading window as prescribed under SEBI (Prohibition .... | Company Update | General |  |
| 224 | REGULATORY_ACTION | The Company has received an adjudication order dated [DATE] from SEBI imposing a penalty under SEBI (Prohibition of Fraudulent and Unfair Trade Practices relating to Securities Market .... | Company Update | General |  |
| 225 | RESULTS_DELAY | We are pleased to inform you that our Company is implementing IND-AS and keeping in view SEBI Circular dated [DATE] allowing extension by one month for submission of Financial Results .... | Company Update | General |  |
| 226 | RESULTS_DELAY | Availing extension of one month in submission of Unaudited Financial Results for the quarter ended [DATE] | Company Update | Meeting Updates |  |
| 227 | RESULTS_DELAY | <BR> Application for Extension of time for submission of Unaudited Financial Results of the Company along with the Limited Review Report and statement of Assets and Liabilities for half .... | Company Update | General |  |
| 228 | RESULTS_DELAY | We are pleased to inform you that our Company is implementing IND-AS and keeping in view SEBI Circular dated [DATE] allowing extension by one month for submission of Financial Results .... | Company Update | General |  |
| 229 | RESULTS_DELAY | Dear Sir/Madam,<BR> <BR> Application for extension of time for submission of un-audited Financial Results along with Limited Review Report and Statements of Assets and Liabilities for half .... | Company Update | General |  |
| 230 | RESULTS_DELAY | We hereby request to please take the reasons disclosed in the attached letter in respect to the delay in submission of financial results for the quarter ended [DATE] on record | Company Update | General |  |
| 231 | RESULTS_DELAY | Please find attached herewith announcement of Comments made by Board of Directors of the Company for delay in Submission of Voting results | Company Update | General |  |
| 232 | RESULTS_DELAY | Seeking permission for submitting delayed Annual Audited Financial Results | Company Update | General |  |
| 233 | RESULTS_DELAY | Letter by the Company for delay in submission of audited financial results for 4th quarter and year ended [DATE] is enclosed herewith. | Company Update | General |  |
| 234 | RESULTS_DELAY | Disclosure of reasons for delay in submission of financial results for the Quarter ended [DATE] | Company Update | General |  |
| 235 | RESULTS_DELAY | We refer to our letter dated [DATE] and [DATE] whereby we informed you about the delay in the submission of audited financial results of the Company for the 4th quarter and .... | Company Update | General |  |
| 236 | RESULTS_DELAY | Please find enclosed letter for delay in submission of unaudited financial results for 1st quarter ended [DATE]. | Company Update | General |  |
| 237 | RESULTS_DELAY | Please find attached enclosed the letter in relation to delay in submission of financial results for the 2nd quarter and half year ended [DATE]. | Company Update | General |  |
| 238 | RESULTS_DELAY | Delay in submission of financial results for the 1st quarter ended [DATE] and 2nd quarter and half year ended [DATE]. | Company Update | General |  |
| 239 | RESULTS_DELAY | Disclosure of reasons for anticipated delay in submission of financial results under Regulation 33 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] read with .... | Result | Financial Results |  |
| 240 | RESULTS_DELAY | Delay in audited financial results for [DATE] | Result | Financial Results |  |
| 241 | RESULTS_DELAY | We refer to our letter dated [DATE] requesting extension of 30 days for submission of Results for Quarter and Year ended [DATE]. <BR> We wish to inform that receipt of .... | Company Update | General |  |
| 242 | RESULTS_DELAY | Disclosure of reasons for anticipated delay in submission of financial results under Regulation 33 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] read with .... | Result | Financial Results |  |
| 243 | RESULTS_DELAY | Delay in [DATE] quarter unaudited financial results | Result | Financial Results |  |
| 244 | RESULTS_DELAY | Disclosure of reason for delay in submission of Financial Results for the Quarter and Half-Year ended [DATE], Pursuant to the SEBI Circular CIR/CFD/CMD1/142/[DATE] dated 19th .... | Company Update | General |  |
| 245 | RESULTS_DELAY | We refer to our earlier letter dated [DATE] regarding 'Disclosure of reason for delay in submission of Financial Results for the Quarter and Half Year ended [DATE]', .... | Company Update | General |  |
| 246 | RESULTS_DELAY | Disclosure of reasons for delay in submission of financial results under regulation 33 of the SEBI (LODR), [DATE] for the year ended [DATE] as per SEBI Circular No. CIR/CFD/CMD-1/142/[DATE] .... | Company Update | General |  |
| 247 | RESULTS_DELAY | Disclosure of reason for the delay in submission of financial results of [CO] [CO] Limited for the financial year ended on [DATE] and for the quarter ended on that date, .... | Company Update | General |  |
| 248 | RESULTS_DELAY | Disclosure of reason for the delay in submission of financial results of [CO] [CO] Limited for the financial year ended on [DATE] and for the quarter ended on that date, .... | Company Update | General |  |
| 249 | RESULTS_DELAY | Disclosure of reasons for anticipated delay in submission of financial results under Regulation 33 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, [DATE] [SEBI .... | Result | Financial Results |  |
| 250 | RESULTS_DELAY | Disclosure of reason for delay in submission of financial results of [CO] [CO] Limited for the quarter ended on [DATE] and for the half year ended on that date, .... | Result | Financial Results |  |
| 251 | RESULTS_DELAY | With reference to our letter dated [DATE] regarding the reasons for anticipated delay in submission of unaudited financial results for the quarter and half year ended [DATE].... | Company Update | General |  |
