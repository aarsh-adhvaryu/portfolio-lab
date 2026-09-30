# Red-flag precision audit — reference labels

**Reviewed and confirmed by Aarsh, 2026-09-30. This file is the reference
every A1 reader is scored against** (`docs/notes/A1-reader-plan.md`, which
records its SHA-256). Drafted by Claude 2026-09-25; Aarsh kept every draft
label and added the SUBTYPE scheme below (2026-09-30). The 21 rating
revisions (UNCLEAR) are resolved from their attachments,
`docs/data/rating_pdf_labels.md` (directions confirmed by Aarsh 2026-09-30):
DOWN → TRUE / AT_COMPANY, except 171 (a wholly owned subsidiary's rating,
read from the unmasked letter) → FALSE / RELATED_ENTITY; UP and NO CHANGE →
FALSE / NOT_EVENT; the 4 scanned (165–168) and 1 missing (172) stay UNCLEAR.
Of the 16 readable letters: 7 downgrades, 3 upgrades, 6 no change.

## Subtype (added 2026-09-30, Aarsh)

The audit's question — "is this the flag's event, about the company
itself?" — counts a lender's loss to a borrower's fraud, or a subsidiary's
insolvency, as FALSE. Each is still a risk event for the company, of a
different kind, so every row also carries a subtype:

| subtype | means | rows |
|---|---|---|
| AT_COMPANY | done by, happened to, or alleged against the company or its people (every TRUE row) | 188 |
| AGAINST_COMPANY | the company is the victim or the lender (88, 97, 100, 102, 104) | 5 |
| RELATED_ENTITY | a subsidiary or other named entity (106, 116, 117, 118, 119, 127, 171, 177) | 8 |
| NOT_EVENT | the word in another sense, a denial, a favourable outcome, a blanket regulatory extension (3, 72, 95, 98, 109, 218, 219, 225, 228, 231; rating letters 169, 170, 174, 185, 186, 190–193) | 19 |
| UNCLEAR | every UNSURE row | 31 |
| **all** | | **251** |

| flag | AT_COMPANY | AGAINST_COMPANY | RELATED_ENTITY | NOT_EVENT | UNCLEAR |
|---|---|---|---|---|---|
| AUDITOR_RESIGNATION | 29 | 0 | 0 | 1 | 0 |
| DEFAULT | 24 | 0 | 0 | 0 | 6 |
| FORENSIC_AUDIT | 9 | 0 | 0 | 1 | 4 |
| FRAUD | 18 | 5 | 0 | 2 | 5 |
| INSOLVENCY | 22 | 0 | 6 | 1 | 1 |
| PROMOTER_ENCUMBRANCE | 30 | 0 | 0 | 0 | 0 |
| RATING_DOWNGRADE | 13 | 0 | 2 | 9 | 6 |
| REGULATORY_ACTION | 20 | 0 | 0 | 2 | 8 |
| RESULTS_DELAY | 23 | 0 | 0 | 3 | 1 |

## How the draft was made

Labelled from the masked headlines in `docs/data/flag_audit.md` only: no
returns, no company names, no dates, no regexes. One disclosure: Claude had
already seen E2-A's aggregate per-flag results before labelling. The written
criteria below are the protection, and they were applied the same way to
every flag.

## Criteria, fixed before labelling

The only question: is the headline, as written, the event the flag names,
about the filing company itself?

- **TRUE**: the headline states that event happened to, or was done by or
  against, the company (its management, promoters or employees count).
- **FALSE**: it is about a different entity (a subsidiary, a borrower,
  another company), a denial, a favourable outcome, or the word used in
  another sense.
- **UNSURE**: the headline does not say enough (a rating change with no
  direction; a statutory format that can report nothing; the company's role
  hidden by the masking).

Per flag:

| flag | TRUE means |
|---|---|
| AUDITOR_RESIGNATION | the statutory or joint auditor resigned; the reason does not matter |
| DEFAULT | a default on interest or principal is stated; a SEBI-format disclosure that states none is UNSURE |
| FORENSIC_AUDIT | a forensic audit of the company or its accounts was ordered, appointed or reported on |
| FRAUD | fraud by or at the company, or a material fraud against it reported as news about it; a lender's routine report of a borrower's fraud, and fraud-prevention products, are FALSE |
| INSOLVENCY | insolvency or liquidation proceedings against the company itself; a subsidiary's are FALSE |
| PROMOTER_ENCUMBRANCE | the statutory reasons-for-encumbrance disclosure at the 50%/20% threshold |
| RATING_DOWNGRADE | a rating of the company was lowered; "revision" with no direction, outlook changes and reviews are UNSURE; a subsidiary's rating is FALSE |
| REGULATORY_ACTION | an action by SEBI, SAT, ED, CBI or SFIO against the company or its officers; denials and favourable outcomes are FALSE; complaints merely received are UNSURE |
| RESULTS_DELAY | the company itself delays or expects to delay financial results; a regulator's blanket extension and delays of other filings are FALSE |

## Summary of the labels (TRUE / FALSE / UNSURE)

| flag | sampled | TRUE | FALSE | UNSURE | precision T/(T+F) | confirmed share T/n |
|---|---|---|---|---|---|---|
| AUDITOR_RESIGNATION | 30 | 29 | 1 | 0 | 97% | 97% |
| DEFAULT | 30 | 24 | 0 | 6 | 100% | 80% |
| FORENSIC_AUDIT | 14 | 9 | 1 | 4 | 90% | 64% |
| FRAUD | 30 | 18 | 7 | 5 | 72% | 60% |
| INSOLVENCY | 30 | 22 | 7 | 1 | 76% | 73% |
| PROMOTER_ENCUMBRANCE | 30 | 30 | 0 | 0 | 100% | 100% |
| RATING_DOWNGRADE | 30 | 13 | 11 | 6 | 54% | 43% |
| REGULATORY_ACTION | 30 | 20 | 2 | 8 | 91% | 67% |
| RESULTS_DELAY | 27 | 23 | 3 | 1 | 88% | 85% |
| **all** | 251 | 188 | 32 | 31 | 85% | 75% |

## The labels

| row | flag | label | subtype | reason |
|---|---|---|---|---|
| 1 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 2 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 3 | AUDITOR_RESIGNATION | FALSE | NOT_EVENT | clarification denying rumours of a resignation |
| 4 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 5 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 6 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 7 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 8 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 9 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 10 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 11 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 12 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 13 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 14 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 15 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 16 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 17 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 18 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 19 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | audit committee's views on an auditor's resignation |
| 20 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 21 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | auditor resigned (partner appointed to a board) |
| 22 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 23 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 24 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 25 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 26 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 27 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 28 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 29 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 30 | AUDITOR_RESIGNATION | TRUE | AT_COMPANY | statutory (or joint) auditor resignation disclosed |
| 31 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 32 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 33 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 34 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 35 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 36 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 37 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 38 | DEFAULT | UNSURE | UNCLEAR | SEBI default-disclosure format; can report no default |
| 39 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 40 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 41 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 42 | DEFAULT | UNSURE | UNCLEAR | SEBI default-disclosure format; can report no default |
| 43 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 44 | DEFAULT | UNSURE | UNCLEAR | SEBI default-disclosure format; can report no default |
| 45 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 46 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 47 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 48 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 49 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 50 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 51 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 52 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 53 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 54 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 55 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 56 | DEFAULT | UNSURE | UNCLEAR | quarterly default disclosure; may be nil |
| 57 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 58 | DEFAULT | TRUE | AT_COMPANY | default on interest/principal stated |
| 59 | DEFAULT | UNSURE | UNCLEAR | SEBI default-disclosure format; can report no default |
| 60 | DEFAULT | UNSURE | UNCLEAR | SEBI default-disclosure format; can report no default |
| 61 | FORENSIC_AUDIT | UNSURE | UNCLEAR | news clarification; what is being audited is unclear |
| 62 | FORENSIC_AUDIT | UNSURE | UNCLEAR | news clarification; what is being audited is unclear |
| 63 | FORENSIC_AUDIT | TRUE | AT_COMPANY | forensic audit appointed in the company's fraud case |
| 64 | FORENSIC_AUDIT | TRUE | AT_COMPANY | forensic auditor appointed |
| 65 | FORENSIC_AUDIT | TRUE | AT_COMPANY | forensic auditor appointed |
| 66 | FORENSIC_AUDIT | TRUE | AT_COMPANY | resolution professional appointed a forensic auditor |
| 67 | FORENSIC_AUDIT | TRUE | AT_COMPANY | lenders moving to a forensic audit of the company's books |
| 68 | FORENSIC_AUDIT | TRUE | AT_COMPANY | forensic audit of the company's accounts ordered |
| 69 | FORENSIC_AUDIT | UNSURE | UNCLEAR | forensic findings about another party using the company's data |
| 70 | FORENSIC_AUDIT | TRUE | AT_COMPANY | board acted on a forensic audit report |
| 71 | FORENSIC_AUDIT | UNSURE | UNCLEAR | 'Forensic Audit' with no detail |
| 72 | FORENSIC_AUDIT | FALSE | NOT_EVENT | company denies a forensic audit was initiated |
| 73 | FORENSIC_AUDIT | TRUE | AT_COMPANY | SEBI appointed a forensic auditor |
| 74 | FORENSIC_AUDIT | TRUE | AT_COMPANY | forensic auditors appointed |
| 75 | FRAUD | TRUE | AT_COMPANY | arrests in a fraud case named after the company |
| 76 | FRAUD | UNSURE | UNCLEAR | fraud charge on an individual; company's role unclear |
| 77 | FRAUD | TRUE | AT_COMPANY | company found a suspected Rs 280 cr fraud |
| 78 | FRAUD | TRUE | AT_COMPANY | fraud charge on the company |
| 79 | FRAUD | TRUE | AT_COMPANY | large fraud at the company reported as news about it |
| 80 | FRAUD | TRUE | AT_COMPANY | large fraud at the company reported as news about it |
| 81 | FRAUD | TRUE | AT_COMPANY | large fraud at the company reported as news about it |
| 82 | FRAUD | TRUE | AT_COMPANY | company faces serious-fraud investigation |
| 83 | FRAUD | TRUE | AT_COMPANY | CBI complaint against the company for fraud |
| 84 | FRAUD | UNSURE | UNCLEAR | fraud case clarification; company's role hidden by masking |
| 85 | FRAUD | UNSURE | UNCLEAR | fraud case clarification; company's role hidden by masking |
| 86 | FRAUD | TRUE | AT_COMPANY | fraud amount in the company's case |
| 87 | FRAUD | UNSURE | UNCLEAR | fraud case clarification; company's role hidden by masking |
| 88 | FRAUD | FALSE | AGAINST_COMPANY | routine lender report of a (borrower) fraud to RBI |
| 89 | FRAUD | TRUE | AT_COMPANY | company's own officers booked or arrested for fraud |
| 90 | FRAUD | TRUE | AT_COMPANY | bank heads booked for fraud |
| 91 | FRAUD | TRUE | AT_COMPANY | whistleblower allegations against the company |
| 92 | FRAUD | TRUE | AT_COMPANY | company's own officers booked or arrested for fraud |
| 93 | FRAUD | TRUE | AT_COMPANY | report finds siphoning of funds |
| 94 | FRAUD | TRUE | AT_COMPANY | whistleblower allegations against the company |
| 95 | FRAUD | FALSE | NOT_EVENT | a contract for fraud-management software |
| 96 | FRAUD | TRUE | AT_COMPANY | whistleblower allegations against the company |
| 97 | FRAUD | FALSE | AGAINST_COMPANY | routine lender report of a (borrower) fraud to RBI |
| 98 | FRAUD | FALSE | NOT_EVENT | an alliance for fraud-prevention technology |
| 99 | FRAUD | TRUE | AT_COMPANY | regulators investigating a whistleblower complaint |
| 100 | FRAUD | FALSE | AGAINST_COMPANY | lender clarifying its exposure to a borrower's fraud |
| 101 | FRAUD | TRUE | AT_COMPANY | company's accounts declared fraud by a lender |
| 102 | FRAUD | FALSE | AGAINST_COMPANY | routine lender report of a (borrower) fraud to RBI |
| 103 | FRAUD | UNSURE | UNCLEAR | statutory format says it is not known whether there is fraud |
| 104 | FRAUD | FALSE | AGAINST_COMPANY | lender reporting a borrower's fraud |
| 105 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 106 | INSOLVENCY | FALSE | RELATED_ENTITY | subsidiary's insolvency, not the company's |
| 107 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 108 | INSOLVENCY | UNSURE | UNCLEAR | writ petition about an insolvency process; whose is unclear |
| 109 | INSOLVENCY | FALSE | NOT_EVENT | an award from 'IBC InfoMedia'; not insolvency |
| 110 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 111 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 112 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 113 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 114 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 115 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 116 | INSOLVENCY | FALSE | RELATED_ENTITY | another named entity's CIRP |
| 117 | INSOLVENCY | FALSE | RELATED_ENTITY | liquidation of a foreign step-down subsidiary |
| 118 | INSOLVENCY | FALSE | RELATED_ENTITY | a subsidiary's CIRP (JIL), filed by the parent |
| 119 | INSOLVENCY | FALSE | RELATED_ENTITY | petition against a subsidiary |
| 120 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 121 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 122 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 123 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 124 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 125 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 126 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 127 | INSOLVENCY | FALSE | RELATED_ENTITY | a subsidiary's CIRP (JIL), filed by the parent |
| 128 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 129 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 130 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 131 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 132 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 133 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 134 | INSOLVENCY | TRUE | AT_COMPANY | insolvency proceedings concerning the company itself |
| 135 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 136 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 137 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 138 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 139 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 140 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 141 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 142 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 143 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 144 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 145 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 146 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 147 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 148 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | revised threshold disclosure |
| 149 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 150 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 151 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 152 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 153 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 154 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 155 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 156 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 157 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 158 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 159 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 160 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 161 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 162 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 163 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 164 | PROMOTER_ENCUMBRANCE | TRUE | AT_COMPANY | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 165 | RATING_DOWNGRADE | UNSURE | UNCLEAR | 'revision' in rating; direction not stated |
| 166 | RATING_DOWNGRADE | UNSURE | UNCLEAR | 'revision' in rating; direction not stated |
| 167 | RATING_DOWNGRADE | UNSURE | UNCLEAR | 'revision' in rating; direction not stated |
| 168 | RATING_DOWNGRADE | UNSURE | UNCLEAR | 'revision' in rating; direction not stated |
| 169 | RATING_DOWNGRADE | FALSE | NOT_EVENT | attachment: rating upgraded (rating_pdf_labels.md, 2026-09-30) |
| 170 | RATING_DOWNGRADE | FALSE | NOT_EVENT | attachment: reaffirmed or outlook-only, no rating change (rating_pdf_labels.md, 2026-09-30) |
| 171 | RATING_DOWNGRADE | FALSE | RELATED_ENTITY | attachment: a wholly owned subsidiary's rating downgraded (rating_pdf_labels.md, 2026-09-30) |
| 172 | RATING_DOWNGRADE | UNSURE | UNCLEAR | 'revision' in rating; direction not stated |
| 173 | RATING_DOWNGRADE | TRUE | AT_COMPANY | rating downgraded |
| 174 | RATING_DOWNGRADE | FALSE | NOT_EVENT | attachment: reaffirmed or outlook-only, no rating change (rating_pdf_labels.md, 2026-09-30) |
| 175 | RATING_DOWNGRADE | TRUE | AT_COMPANY | attachment: rating downgraded (rating_pdf_labels.md, 2026-09-30) |
| 176 | RATING_DOWNGRADE | TRUE | AT_COMPANY | rating downgraded |
| 177 | RATING_DOWNGRADE | FALSE | RELATED_ENTITY | a subsidiary's rating |
| 178 | RATING_DOWNGRADE | TRUE | AT_COMPANY | news clarification about a downgrade of the company |
| 179 | RATING_DOWNGRADE | TRUE | AT_COMPANY | attachment: rating downgraded (rating_pdf_labels.md, 2026-09-30) |
| 180 | RATING_DOWNGRADE | TRUE | AT_COMPANY | rating downgraded |
| 181 | RATING_DOWNGRADE | TRUE | AT_COMPANY | news clarification about a downgrade of the company |
| 182 | RATING_DOWNGRADE | TRUE | AT_COMPANY | attachment: rating downgraded (rating_pdf_labels.md, 2026-09-30) |
| 183 | RATING_DOWNGRADE | TRUE | AT_COMPANY | attachment: rating downgraded (rating_pdf_labels.md, 2026-09-30) |
| 184 | RATING_DOWNGRADE | UNSURE | UNCLEAR | placed under review for downgrade; not yet a downgrade |
| 185 | RATING_DOWNGRADE | FALSE | NOT_EVENT | attachment: reaffirmed or outlook-only, no rating change (rating_pdf_labels.md, 2026-09-30) |
| 186 | RATING_DOWNGRADE | FALSE | NOT_EVENT | attachment: rating upgraded (rating_pdf_labels.md, 2026-09-30) |
| 187 | RATING_DOWNGRADE | TRUE | AT_COMPANY | attachment: rating downgraded (rating_pdf_labels.md, 2026-09-30) |
| 188 | RATING_DOWNGRADE | TRUE | AT_COMPANY | attachment: rating downgraded (rating_pdf_labels.md, 2026-09-30) |
| 189 | RATING_DOWNGRADE | TRUE | AT_COMPANY | news clarification about a downgrade of the company |
| 190 | RATING_DOWNGRADE | FALSE | NOT_EVENT | attachment: reaffirmed or outlook-only, no rating change (rating_pdf_labels.md, 2026-09-30) |
| 191 | RATING_DOWNGRADE | FALSE | NOT_EVENT | attachment: reaffirmed or outlook-only, no rating change (rating_pdf_labels.md, 2026-09-30) |
| 192 | RATING_DOWNGRADE | FALSE | NOT_EVENT | attachment: reaffirmed or outlook-only, no rating change (rating_pdf_labels.md, 2026-09-30) |
| 193 | RATING_DOWNGRADE | FALSE | NOT_EVENT | attachment: rating upgraded (rating_pdf_labels.md, 2026-09-30) |
| 194 | RATING_DOWNGRADE | TRUE | AT_COMPANY | rating downgraded |
| 195 | REGULATORY_ACTION | TRUE | AT_COMPANY | CBI booked the company's officials |
| 196 | REGULATORY_ACTION | TRUE | AT_COMPANY | CBI booked the company's officials |
| 197 | REGULATORY_ACTION | TRUE | AT_COMPANY | SFIO questioned the company's CFO |
| 198 | REGULATORY_ACTION | TRUE | AT_COMPANY | CBI FIR against the company's promoter |
| 199 | REGULATORY_ACTION | TRUE | AT_COMPANY | SEBI ex parte order involving the company's MD |
| 200 | REGULATORY_ACTION | TRUE | AT_COMPANY | CBI booked the company's director-finance |
| 201 | REGULATORY_ACTION | TRUE | AT_COMPANY | CBI booked the company's director-finance |
| 202 | REGULATORY_ACTION | UNSURE | UNCLEAR | court order in the 2G case; direction not stated |
| 203 | REGULATORY_ACTION | TRUE | AT_COMPANY | SEBI adjudication order imposing a penalty |
| 204 | REGULATORY_ACTION | UNSURE | UNCLEAR | CBI case; company's role unclear |
| 205 | REGULATORY_ACTION | TRUE | AT_COMPANY | CBI investigation of the company |
| 206 | REGULATORY_ACTION | TRUE | AT_COMPANY | CBI investigation of the company |
| 207 | REGULATORY_ACTION | UNSURE | UNCLEAR | CBI case over fraud at a branch; target unclear |
| 208 | REGULATORY_ACTION | TRUE | AT_COMPANY | CBI complaint against the company |
| 209 | REGULATORY_ACTION | UNSURE | UNCLEAR | SFIO awaiting approval; no action yet |
| 210 | REGULATORY_ACTION | UNSURE | UNCLEAR | CBI action in a borrower scam; company's role unclear |
| 211 | REGULATORY_ACTION | TRUE | AT_COMPANY | bank heads booked by CBI |
| 212 | REGULATORY_ACTION | TRUE | AT_COMPANY | bank heads booked by CBI |
| 213 | REGULATORY_ACTION | UNSURE | UNCLEAR | CBI action in a borrower scam; company's role unclear |
| 214 | REGULATORY_ACTION | UNSURE | UNCLEAR | SFIO received complaints; no action |
| 215 | REGULATORY_ACTION | UNSURE | UNCLEAR | SFIO received complaints; no action |
| 216 | REGULATORY_ACTION | TRUE | AT_COMPANY | SFIO to probe the company |
| 217 | REGULATORY_ACTION | TRUE | AT_COMPANY | ED attached the company's assets |
| 218 | REGULATORY_ACTION | FALSE | NOT_EVENT | tax department WITHDREW an attachment (favourable) |
| 219 | REGULATORY_ACTION | FALSE | NOT_EVENT | company denies a CBI raid on it |
| 220 | REGULATORY_ACTION | TRUE | AT_COMPANY | SEBI adjudication order |
| 221 | REGULATORY_ACTION | TRUE | AT_COMPANY | ED raided the company's premises |
| 222 | REGULATORY_ACTION | TRUE | AT_COMPANY | SEBI impounding order and show-cause against the CFO |
| 223 | REGULATORY_ACTION | TRUE | AT_COMPANY | SEBI penalty on the company |
| 224 | REGULATORY_ACTION | TRUE | AT_COMPANY | SEBI penalty on the company |
| 225 | RESULTS_DELAY | FALSE | NOT_EVENT | SEBI's blanket one-month Ind-AS extension, not a company delay |
| 226 | RESULTS_DELAY | UNSURE | UNCLEAR | one-month extension availed; likely the blanket Ind-AS relief |
| 227 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 228 | RESULTS_DELAY | FALSE | NOT_EVENT | SEBI's blanket one-month Ind-AS extension, not a company delay |
| 229 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 230 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 231 | RESULTS_DELAY | FALSE | NOT_EVENT | delay in voting results, not financial results |
| 232 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 233 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 234 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 235 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 236 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 237 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 238 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 239 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 240 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 241 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 242 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 243 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 244 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 245 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 246 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 247 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 248 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 249 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 250 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
| 251 | RESULTS_DELAY | TRUE | AT_COMPANY | company delays or expects to delay its results |
