# Red-flag precision audit — draft labels for Aarsh to review

**Draft by Claude, 2026-09-25. Aarsh reviews and edits; his final version is the record.**
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

## Summary of the draft

| flag | sampled | TRUE | FALSE | UNSURE | precision T/(T+F) | confirmed share T/n |
|---|---|---|---|---|---|---|
| AUDITOR_RESIGNATION | 30 | 29 | 1 | 0 | 97% | 97% |
| DEFAULT | 30 | 24 | 0 | 6 | 100% | 80% |
| FORENSIC_AUDIT | 14 | 9 | 1 | 4 | 90% | 64% |
| FRAUD | 30 | 18 | 7 | 5 | 72% | 60% |
| INSOLVENCY | 30 | 22 | 7 | 1 | 76% | 73% |
| PROMOTER_ENCUMBRANCE | 30 | 30 | 0 | 0 | 100% | 100% |
| RATING_DOWNGRADE | 30 | 7 | 1 | 22 | 88% | 23% |
| REGULATORY_ACTION | 30 | 20 | 2 | 8 | 91% | 67% |
| RESULTS_DELAY | 27 | 23 | 3 | 1 | 88% | 85% |
| **all** | 251 | 182 | 22 | 47 | 89% | 73% |

## The labels

| row | flag | label | reason |
|---|---|---|---|
| 1 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 2 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 3 | AUDITOR_RESIGNATION | FALSE | clarification denying rumours of a resignation |
| 4 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 5 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 6 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 7 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 8 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 9 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 10 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 11 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 12 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 13 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 14 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 15 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 16 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 17 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 18 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 19 | AUDITOR_RESIGNATION | TRUE | audit committee's views on an auditor's resignation |
| 20 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 21 | AUDITOR_RESIGNATION | TRUE | auditor resigned (partner appointed to a board) |
| 22 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 23 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 24 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 25 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 26 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 27 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 28 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 29 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 30 | AUDITOR_RESIGNATION | TRUE | statutory (or joint) auditor resignation disclosed |
| 31 | DEFAULT | TRUE | default on interest/principal stated |
| 32 | DEFAULT | TRUE | default on interest/principal stated |
| 33 | DEFAULT | TRUE | default on interest/principal stated |
| 34 | DEFAULT | TRUE | default on interest/principal stated |
| 35 | DEFAULT | TRUE | default on interest/principal stated |
| 36 | DEFAULT | TRUE | default on interest/principal stated |
| 37 | DEFAULT | TRUE | default on interest/principal stated |
| 38 | DEFAULT | UNSURE | SEBI default-disclosure format; can report no default |
| 39 | DEFAULT | TRUE | default on interest/principal stated |
| 40 | DEFAULT | TRUE | default on interest/principal stated |
| 41 | DEFAULT | TRUE | default on interest/principal stated |
| 42 | DEFAULT | UNSURE | SEBI default-disclosure format; can report no default |
| 43 | DEFAULT | TRUE | default on interest/principal stated |
| 44 | DEFAULT | UNSURE | SEBI default-disclosure format; can report no default |
| 45 | DEFAULT | TRUE | default on interest/principal stated |
| 46 | DEFAULT | TRUE | default on interest/principal stated |
| 47 | DEFAULT | TRUE | default on interest/principal stated |
| 48 | DEFAULT | TRUE | default on interest/principal stated |
| 49 | DEFAULT | TRUE | default on interest/principal stated |
| 50 | DEFAULT | TRUE | default on interest/principal stated |
| 51 | DEFAULT | TRUE | default on interest/principal stated |
| 52 | DEFAULT | TRUE | default on interest/principal stated |
| 53 | DEFAULT | TRUE | default on interest/principal stated |
| 54 | DEFAULT | TRUE | default on interest/principal stated |
| 55 | DEFAULT | TRUE | default on interest/principal stated |
| 56 | DEFAULT | UNSURE | quarterly default disclosure; may be nil |
| 57 | DEFAULT | TRUE | default on interest/principal stated |
| 58 | DEFAULT | TRUE | default on interest/principal stated |
| 59 | DEFAULT | UNSURE | SEBI default-disclosure format; can report no default |
| 60 | DEFAULT | UNSURE | SEBI default-disclosure format; can report no default |
| 61 | FORENSIC_AUDIT | UNSURE | news clarification; what is being audited is unclear |
| 62 | FORENSIC_AUDIT | UNSURE | news clarification; what is being audited is unclear |
| 63 | FORENSIC_AUDIT | TRUE | forensic audit appointed in the company's fraud case |
| 64 | FORENSIC_AUDIT | TRUE | forensic auditor appointed |
| 65 | FORENSIC_AUDIT | TRUE | forensic auditor appointed |
| 66 | FORENSIC_AUDIT | TRUE | resolution professional appointed a forensic auditor |
| 67 | FORENSIC_AUDIT | TRUE | lenders moving to a forensic audit of the company's books |
| 68 | FORENSIC_AUDIT | TRUE | forensic audit of the company's accounts ordered |
| 69 | FORENSIC_AUDIT | UNSURE | forensic findings about another party using the company's data |
| 70 | FORENSIC_AUDIT | TRUE | board acted on a forensic audit report |
| 71 | FORENSIC_AUDIT | UNSURE | 'Forensic Audit' with no detail |
| 72 | FORENSIC_AUDIT | FALSE | company denies a forensic audit was initiated |
| 73 | FORENSIC_AUDIT | TRUE | SEBI appointed a forensic auditor |
| 74 | FORENSIC_AUDIT | TRUE | forensic auditors appointed |
| 75 | FRAUD | TRUE | arrests in a fraud case named after the company |
| 76 | FRAUD | UNSURE | fraud charge on an individual; company's role unclear |
| 77 | FRAUD | TRUE | company found a suspected Rs 280 cr fraud |
| 78 | FRAUD | TRUE | fraud charge on the company |
| 79 | FRAUD | TRUE | large fraud at the company reported as news about it |
| 80 | FRAUD | TRUE | large fraud at the company reported as news about it |
| 81 | FRAUD | TRUE | large fraud at the company reported as news about it |
| 82 | FRAUD | TRUE | company faces serious-fraud investigation |
| 83 | FRAUD | TRUE | CBI complaint against the company for fraud |
| 84 | FRAUD | UNSURE | fraud case clarification; company's role hidden by masking |
| 85 | FRAUD | UNSURE | fraud case clarification; company's role hidden by masking |
| 86 | FRAUD | TRUE | fraud amount in the company's case |
| 87 | FRAUD | UNSURE | fraud case clarification; company's role hidden by masking |
| 88 | FRAUD | FALSE | routine lender report of a (borrower) fraud to RBI |
| 89 | FRAUD | TRUE | company's own officers booked or arrested for fraud |
| 90 | FRAUD | TRUE | bank heads booked for fraud |
| 91 | FRAUD | TRUE | whistleblower allegations against the company |
| 92 | FRAUD | TRUE | company's own officers booked or arrested for fraud |
| 93 | FRAUD | TRUE | report finds siphoning of funds |
| 94 | FRAUD | TRUE | whistleblower allegations against the company |
| 95 | FRAUD | FALSE | a contract for fraud-management software |
| 96 | FRAUD | TRUE | whistleblower allegations against the company |
| 97 | FRAUD | FALSE | routine lender report of a (borrower) fraud to RBI |
| 98 | FRAUD | FALSE | an alliance for fraud-prevention technology |
| 99 | FRAUD | TRUE | regulators investigating a whistleblower complaint |
| 100 | FRAUD | FALSE | lender clarifying its exposure to a borrower's fraud |
| 101 | FRAUD | TRUE | company's accounts declared fraud by a lender |
| 102 | FRAUD | FALSE | routine lender report of a (borrower) fraud to RBI |
| 103 | FRAUD | UNSURE | statutory format says it is not known whether there is fraud |
| 104 | FRAUD | FALSE | lender reporting a borrower's fraud |
| 105 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 106 | INSOLVENCY | FALSE | subsidiary's insolvency, not the company's |
| 107 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 108 | INSOLVENCY | UNSURE | writ petition about an insolvency process; whose is unclear |
| 109 | INSOLVENCY | FALSE | an award from 'IBC InfoMedia'; not insolvency |
| 110 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 111 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 112 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 113 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 114 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 115 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 116 | INSOLVENCY | FALSE | another named entity's CIRP |
| 117 | INSOLVENCY | FALSE | liquidation of a foreign step-down subsidiary |
| 118 | INSOLVENCY | FALSE | a subsidiary's CIRP (JIL), filed by the parent |
| 119 | INSOLVENCY | FALSE | petition against a subsidiary |
| 120 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 121 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 122 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 123 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 124 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 125 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 126 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 127 | INSOLVENCY | FALSE | a subsidiary's CIRP (JIL), filed by the parent |
| 128 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 129 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 130 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 131 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 132 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 133 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 134 | INSOLVENCY | TRUE | insolvency proceedings concerning the company itself |
| 135 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 136 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 137 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 138 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 139 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 140 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 141 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 142 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 143 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 144 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 145 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 146 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 147 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 148 | PROMOTER_ENCUMBRANCE | TRUE | revised threshold disclosure |
| 149 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 150 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 151 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 152 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 153 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 154 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 155 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 156 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 157 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 158 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 159 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 160 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 161 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 162 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 163 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 164 | PROMOTER_ENCUMBRANCE | TRUE | statutory reasons-for-encumbrance disclosure (threshold disclosure) |
| 165 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 166 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 167 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 168 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 169 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 170 | RATING_DOWNGRADE | UNSURE | outlook revision; direction not stated |
| 171 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 172 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 173 | RATING_DOWNGRADE | TRUE | rating downgraded |
| 174 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 175 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 176 | RATING_DOWNGRADE | TRUE | rating downgraded |
| 177 | RATING_DOWNGRADE | FALSE | a subsidiary's rating |
| 178 | RATING_DOWNGRADE | TRUE | news clarification about a downgrade of the company |
| 179 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 180 | RATING_DOWNGRADE | TRUE | rating downgraded |
| 181 | RATING_DOWNGRADE | TRUE | news clarification about a downgrade of the company |
| 182 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 183 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 184 | RATING_DOWNGRADE | UNSURE | placed under review for downgrade; not yet a downgrade |
| 185 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 186 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 187 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 188 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 189 | RATING_DOWNGRADE | TRUE | news clarification about a downgrade of the company |
| 190 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 191 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 192 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 193 | RATING_DOWNGRADE | UNSURE | 'revision' in rating; direction not stated |
| 194 | RATING_DOWNGRADE | TRUE | rating downgraded |
| 195 | REGULATORY_ACTION | TRUE | CBI booked the company's officials |
| 196 | REGULATORY_ACTION | TRUE | CBI booked the company's officials |
| 197 | REGULATORY_ACTION | TRUE | SFIO questioned the company's CFO |
| 198 | REGULATORY_ACTION | TRUE | CBI FIR against the company's promoter |
| 199 | REGULATORY_ACTION | TRUE | SEBI ex parte order involving the company's MD |
| 200 | REGULATORY_ACTION | TRUE | CBI booked the company's director-finance |
| 201 | REGULATORY_ACTION | TRUE | CBI booked the company's director-finance |
| 202 | REGULATORY_ACTION | UNSURE | court order in the 2G case; direction not stated |
| 203 | REGULATORY_ACTION | TRUE | SEBI adjudication order imposing a penalty |
| 204 | REGULATORY_ACTION | UNSURE | CBI case; company's role unclear |
| 205 | REGULATORY_ACTION | TRUE | CBI investigation of the company |
| 206 | REGULATORY_ACTION | TRUE | CBI investigation of the company |
| 207 | REGULATORY_ACTION | UNSURE | CBI case over fraud at a branch; target unclear |
| 208 | REGULATORY_ACTION | TRUE | CBI complaint against the company |
| 209 | REGULATORY_ACTION | UNSURE | SFIO awaiting approval; no action yet |
| 210 | REGULATORY_ACTION | UNSURE | CBI action in a borrower scam; company's role unclear |
| 211 | REGULATORY_ACTION | TRUE | bank heads booked by CBI |
| 212 | REGULATORY_ACTION | TRUE | bank heads booked by CBI |
| 213 | REGULATORY_ACTION | UNSURE | CBI action in a borrower scam; company's role unclear |
| 214 | REGULATORY_ACTION | UNSURE | SFIO received complaints; no action |
| 215 | REGULATORY_ACTION | UNSURE | SFIO received complaints; no action |
| 216 | REGULATORY_ACTION | TRUE | SFIO to probe the company |
| 217 | REGULATORY_ACTION | TRUE | ED attached the company's assets |
| 218 | REGULATORY_ACTION | FALSE | tax department WITHDREW an attachment (favourable) |
| 219 | REGULATORY_ACTION | FALSE | company denies a CBI raid on it |
| 220 | REGULATORY_ACTION | TRUE | SEBI adjudication order |
| 221 | REGULATORY_ACTION | TRUE | ED raided the company's premises |
| 222 | REGULATORY_ACTION | TRUE | SEBI impounding order and show-cause against the CFO |
| 223 | REGULATORY_ACTION | TRUE | SEBI penalty on the company |
| 224 | REGULATORY_ACTION | TRUE | SEBI penalty on the company |
| 225 | RESULTS_DELAY | FALSE | SEBI's blanket one-month Ind-AS extension, not a company delay |
| 226 | RESULTS_DELAY | UNSURE | one-month extension availed; likely the blanket Ind-AS relief |
| 227 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 228 | RESULTS_DELAY | FALSE | SEBI's blanket one-month Ind-AS extension, not a company delay |
| 229 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 230 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 231 | RESULTS_DELAY | FALSE | delay in voting results, not financial results |
| 232 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 233 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 234 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 235 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 236 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 237 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 238 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 239 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 240 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 241 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 242 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 243 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 244 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 245 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 246 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 247 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 248 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 249 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 250 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
| 251 | RESULTS_DELAY | TRUE | company delays or expects to delay its results |
