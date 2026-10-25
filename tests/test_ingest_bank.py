"""S6 build-ahead: bank statement parse, classification, events, dividend matching. Every statement line below
is SYNTHETIC (written in the style of Indian bank narrations, not copied from a real SBI export); the rules are
uncalibrated until a real statement is available."""
import io
from datetime import date

import openpyxl
import pandas as pd
import pytest

from pflab.ingest import bank
from pflab.ledger.book import Ledger
from pflab.ledger.events import Event, EventLog

HEAD = """Account Name :,SYNTHETIC INVESTOR,,,,,
Account Number :,00000000000,,,,,
Statement From : 01-05-2026 to 30-09-2026,,,,,,
,,,,,,
Txn Date,Value Date,Description,Ref No./Cheque No.,Debit,Credit,Balance
"""
FOOT = ",,,,,,\nStatement Summary,,,,,,\n"


def csv_of(lines, opening=10_000.0):
    bal, out = opening, []
    for d, desc, deb, cre in lines:
        bal += cre - deb
        out.append(f'{d},{d},"{desc}",REF,{deb or ""},{cre or ""},{bal:.2f}')
    return HEAD + "\n".join(out) + "\n" + FOOT


LINES = [
    ("04 May 2026", "UPI/DR/613/ZERODHA BROKING LTD/okaxis", 5000.0, 0),                    # to the broker
    ("12 May 2026", "NACH CR-DIVIDEND ACMELTD FINAL DIV 2025-26", 0, 450.0),
    ("15 May 2026", "CREDIT INTEREST SB 01-04-2026 TO 30-06-2026", 0, 87.5),
    ("20 May 2026", "BY TRANSFER-CAMS REDEMPTION PROCEEDS", 0, 2000.0),
    ("22 May 2026", "SGB 2.50% 2028 SERIES I INT CREDIT", 0, 625.0),
    ("23 May 2026", "UPI/CR/ZERODHA BROKING LTD WITHDRAWAL", 0, 1500.0),                   # from the broker
    ("01 Jun 2026", "IPO REFUND ACME INFRA APPLICATION MONEY", 0, 15000.0),
    ("03 Jun 2026", "INCOME TAX DEPT TDS REFUND CPC", 0, 300.0),
    ("05 Jun 2026", "NEFT-MYSTERY PRIVATE LIMITED-INV 77", 0, 1234.0),                      # no rule matches
    ("06 Jun 2026", "BSE STAR MF SIP PURCHASE", 1000.0, 0),
    ("07 Jun 2026", "SMS ALERT CHARGES 1QTR", 17.7, 0),
    ("09 Jun 2026", "ADVANCE TAX CHALLAN OLTAS", 2000.0, 0),
    ("10 Jun 2026", "NCD COUPON INTEREST ACME FIN", 0, 800.0),
]


# --- parse -----------------------------------------------------------------------------------------------------

def test_parse_csv_with_preamble_footer_and_balance_check():
    df = bank.parse(csv_of(LINES))
    assert len(df) == len(LINES) and df["date"].iloc[0] == date(2026, 5, 4) and df.attrs["opening_balance"] == pytest.approx(10_000.0)
    assert df["debit"].iloc[0] == 5000.0 and df["credit"].iloc[1] == 450.0 and df["description"].iloc[1].startswith("NACH CR-DIVIDEND")
    assert df["balance"].iloc[-1] == pytest.approx(10_000 - 5000 + 450 + 87.5 + 2000 + 625 + 1500 + 15000 + 300 + 1234 - 1000 - 17.7 - 2000 + 800)


def test_parse_xlsx_matches_csv():
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in __import__("csv").reader(io.StringIO(csv_of(LINES))):
        ws.append([float(c) if c.replace(".", "", 1).isdigit() else c for c in row])
    buf = io.BytesIO()
    wb.save(buf)
    pd.testing.assert_frame_equal(bank.parse(buf.getvalue()), bank.parse(csv_of(LINES)), check_dtype=False)


def _xlsx_bytes(text):
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in __import__("csv").reader(io.StringIO(text)):
        ws.append([float(c) if c.replace(".", "", 1).isdigit() else c for c in row])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_password_protected_xlsx_is_decrypted_in_memory(tmp_path):
    from msoffcrypto.format.ooxml import OOXMLFile
    plain = _xlsx_bytes(csv_of(LINES))
    enc = io.BytesIO()
    OOXMLFile(io.BytesIO(plain)).encrypt("s3cret", enc)
    p = tmp_path / "AccountStatement.xlsx"
    p.write_bytes(enc.getvalue())
    pd.testing.assert_frame_equal(bank.parse(str(p), password="s3cret"), bank.parse(csv_of(LINES)), check_dtype=False)
    assert sorted(x.name for x in tmp_path.iterdir()) == ["AccountStatement.xlsx"]      # nothing decrypted on disk
    with pytest.raises(bank.StatementError, match="password-protected"):
        bank.parse(str(p))
    with pytest.raises(bank.StatementError, match="wrong password"):
        bank.parse(str(p), password="nope")


def test_hdfc_style_headers_and_separator_row_parse():
    """HDFC: Narration / Withdrawal Amt. / Deposit Amt. / Closing Balance, dd/mm/yy, a ******** row under the header."""
    head = "Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance\n********,,,,,,\n"
    body = "04/05/26,UPI-ZERODHA BROKING,R1,04/05/26,5000,,5000.00\n12/05/26,ACME DIV,R2,12/05/26,,450,5450.00\n"
    df = bank.parse(head + body)
    assert list(df["date"]) == [date(2026, 5, 4), date(2026, 5, 12)]
    assert list(df["debit"]) == [5000.0, 0.0] and list(df["credit"]) == [0.0, 450.0] and df["ref"].iloc[1] == "R2"
    assert df.attrs["opening_balance"] == pytest.approx(10_000.0)


def test_a_statement_that_does_not_add_up_is_refused():
    bad = csv_of(LINES).replace("15 May 2026,15 May 2026,\"CREDIT INTEREST SB 01-04-2026 TO 30-06-2026\",REF,,87.5,", "15 May 2026,15 May 2026,\"CREDIT INTEREST SB 01-04-2026 TO 30-06-2026\",REF,,88.5,")
    with pytest.raises(bank.StatementError, match="balance breaks at row 3"):
        bank.parse(bad)
    with pytest.raises(bank.StatementError, match="no header"):
        bank.parse("a,b,c\n1,2,3\n")


# --- classify -----------------------------------------------------------------------------------------------------------

def test_every_sample_line_gets_its_category():
    df = bank.classify(bank.parse(csv_of(LINES)))
    assert list(df["category"]) == ["broker_transfer", "dividend", "interest", "mf_redemption", "sgb_interest", "broker_transfer",
                                    "ipo_refund", "tax_refund", "unclassified", "mf_purchase", "bank_charges", "tax_payment", "bond_interest"]
    assert pd.isna(df["rule_id"].iloc[8]) and df["rule_id"].iloc[1] == "dividend"
    assert df["direction"].iloc[0] == "debit" and df["direction"].iloc[1] == "credit"
    assert df["ref_id"].is_unique


def test_direction_matters_in_the_rules():
    df = bank.classify(bank.parse(csv_of([("04 May 2026", "UPI ZERODHA", 100.0, 0), ("05 May 2026", "UPI ZERODHA", 0, 50.0),
                                          ("06 May 2026", "BSE STAR MF", 0, 70.0)])))
    assert list(df["rule_id"]) == ["broker_out", "broker_in", "mf_redemption"]                 # same words, different rules by direction


def test_acceptance_every_credit_is_classified_or_listed():
    df = bank.classify(bank.parse(csv_of(LINES)))
    a = bank.acceptance(df, date(2026, 5, 1))
    assert a["credits"] == 9 and a["classified"] == 8 and a["unclassified"] == 1
    assert a["unclassified_lines"] == [{"date": date(2026, 6, 5), "description": "NEFT-MYSTERY PRIVATE LIMITED-INV 77", "credit": 1234.0}]
    assert bank.acceptance(df, date(2026, 6, 6))["credits"] == 1


@pytest.mark.parametrize("desc,cat", [                   # 2026-10-14 calibration, synthetic lines in the real shapes
    ("CEMTEX DEP ITDTAX REFUND 2025-26 ABCDE0000F", "tax_refund"),
    ("0000HLY INT-IN0020200000", "sgb_interest"),
    ("INTEREST PAID TILL 30-SEP-2026", "interest"),
    ("DEP TFR NEFT*IBKL0000*ICMS0000*LICMDOPH-LIC MD", "insurance_payout"),
    ("UPIRET-000000-000", "refund"),
    ("UPI-SHOP PVT-SHOP.REFUNDS@AXISBANK-UTIB000-000-REFUND FOR ORDER", "refund"),
    ("UPI-PHONEPE-MERCHANT@YESBANK-YESB000-000-R02 PHONEPE REVERS", "refund"),
    ("UPI-A FRIEND-FRIEND@OKAXIS-UTIB000-000-UPI", "upi_receipt"),
    ("UPI-ZERODHA BROKING LTD-SIGNUP@HDFCBANK-HDFC000-000-ZERODHA REFUND 556", "verification"),
])
def test_calibrated_credit_patterns(desc, cat):
    df = bank.classify(bank.parse(csv_of([("04 May 2026", desc, 0, 10.0)])))
    assert df["category"].iloc[0] == cat


def test_sbi_wrapped_narrations_are_rebuilt():
    assert bank._unwrap("INTERES\n T CREDIT") == "INTEREST CREDIT"
    assert bank._unwrap("NEFT*LICMDOPH-LIC \n MD") == "NEFT*LICMDOPH-LIC MD"
    df = bank.classify(bank.parse(csv_of([("04 May 2026", "CEMTEX DEP   ITDTAX RE\n FUND 2025-26", 0, 10.0)])))
    assert df["description"].iloc[0] == "CEMTEX DEP   ITDTAX REFUND 2025-26" and df["category"].iloc[0] == "tax_refund"


def test_local_rules_come_first_and_a_missing_file_is_fine(tmp_path):
    local = tmp_path / bank.LOCAL_RULES_NAME
    local.write_text("[[rule]]\nid = 'own'\ncategory = 'own_transfer'\ndirection = 'credit'\npatterns = ['MY NAME']\n")
    df = bank.parse(csv_of([("04 May 2026", "UPI-MY NAME-ME@OKAXIS-UPI", 0, 10.0)]))
    assert bank.classify(df, rules=bank.load_rules(local=local))["category"].iloc[0] == "own_transfer"
    assert bank.classify(df)["category"].iloc[0] == "upi_receipt"
    assert bank.load_rules(local=tmp_path / "absent.toml") == bank.load_rules()


def test_custom_rules_can_replace_the_defaults():
    df = bank.classify(bank.parse(csv_of([("04 May 2026", "SALARY ACME", 0, 100.0)])),
                       rules=[{"id": "salary", "category": "salary", "direction": "credit", "patterns": ["SALARY"],
                               "_rx": [__import__("re").compile("SALARY", 2)]}])
    assert df["category"].iloc[0] == "salary"


# --- events ------------------------------------------------------------------------------------------------------------------

def replay(df, matches=None, **kw):
    evs, rep = bank.to_events(df, "SBI", "ZER", matches=matches, **kw)
    return Ledger.replay(EventLog(evs)), evs, rep


def test_ledger_bank_cash_equals_the_statement_closing_balance():
    df = bank.classify(bank.parse(csv_of(LINES)))
    led, evs, rep = replay(df)
    chk = bank.check_closing_balance(df, led, "SBI")
    assert chk["ok"] and chk["ledger_cash"] == pytest.approx(chk["statement_closing"])
    assert led.cash_balance("ZER") == pytest.approx(5000 - 1500)                      # broker side of the two transfers


def test_broker_transfers_are_internal_not_contributions():
    led, evs, rep = replay(bank.classify(bank.parse(csv_of(LINES))))
    kinds = {e.kind for e in evs}
    assert "cash_transfer" in kinds
    flows = {d: a for d, _acc, a in led.contributions}
    assert flows[date(2026, 5, 4)] == 10_000.0 and date(2026, 5, 23) not in flows      # only the opening balance; transfers are internal
    assert flows[date(2026, 5, 20)] == 2000.0 and flows[date(2026, 6, 6)] == -1000.0     # MF redemption in, MF purchase out
    assert flows[date(2026, 6, 1)] == 15000.0                                              # unmatched credit kinds default to deposit


def test_income_lines_become_income_and_fees_become_charges():
    led, evs, rep = replay(bank.classify(bank.parse(csv_of(LINES))))
    assert sorted((i.kind, i.gross) for i in led.income) == [("interest", 87.5), ("interest", 450.0), ("interest", 625.0), ("interest", 800.0)]
    assert [(f.amount, f.origin) for f in led.fees] == [(17.7, "charge")]
    assert len(rep["unmatched_dividends"]) == 1 and rep["unmatched_dividends"][0]["credit"] == 450.0
    assert [u["credit"] for u in rep["unclassified"]] == [1234.0]


def test_import_is_idempotent_and_broker_account_is_required():
    df = bank.classify(bank.parse(csv_of(LINES)))
    evs, _ = bank.to_events(df, "SBI", "ZER")
    again, rep = bank.to_events(df, "SBI", "ZER", existing_refs={e.ref for e in evs})
    assert again == [] and rep["skipped_existing"] == len(df)
    with pytest.raises(bank.StatementError, match="broker account"):
        bank.to_events(df, "SBI", None)


# --- dividends ----------------------------------------------------------------------------------------------------------------

FEED = pd.DataFrame([dict(isin="INE111A01011", ex_date=date(2026, 5, 2), dividend_per_share=9.0),
                     dict(isin="INE222B01012", ex_date=date(2026, 5, 3), dividend_per_share=4.5),
                     dict(isin="INE333C01013", ex_date=date(2025, 1, 1), dividend_per_share=9.0)])      # far outside the window
HELD = {"INE111A01011": 50.0, "INE222B01012": 100.0, "INE333C01013": 50.0}


def qty_on(isin, day):
    return HELD.get(isin, 0.0)


def div_df(credit, desc="NACH CR-DIVIDEND ACMELTD"):
    return bank.classify(bank.parse(csv_of([("12 May 2026", desc, 0, credit)])))


def test_dividend_credit_matches_dividend_per_share_times_quantity():
    m = bank.match_dividends(div_df(450.0), FEED[FEED["isin"] != "INE222B01012"], qty_on)
    r = m.iloc[0]
    assert (r["isin"], r["qty"], r["gross"], r["tds"], r["kind"], r["ambiguous"]) == ("INE111A01011", 50.0, 450.0, 0.0, "gross", False)


def test_dividend_net_of_tds_is_recognised():
    m = bank.match_dividends(div_df(405.0), FEED[FEED["isin"] == "INE111A01011"], qty_on)
    r = m.iloc[0]
    assert r["kind"] == "net_tds" and r["gross"] == 450.0 and r["tds"] == pytest.approx(45.0)


def test_dividend_outside_window_or_amount_does_not_match():
    assert bank.match_dividends(div_df(450.0), FEED[FEED["isin"] == "INE333C01013"], qty_on).empty         # ex-date a year earlier
    assert bank.match_dividends(div_df(461.0), FEED[FEED["isin"] == "INE111A01011"], qty_on).empty         # not within the tolerance
    assert bank.match_dividends(div_df(450.0), FEED[FEED["isin"] == "INE111A01011"], lambda i, d: 0.0).empty   # nothing held then


def test_ambiguity_is_flagged_and_a_symbol_in_the_narration_breaks_the_tie():
    feed = pd.DataFrame([dict(isin="INE111A01011", ex_date=date(2026, 5, 2), dividend_per_share=9.0),
                         dict(isin="INE444D01014", ex_date=date(2026, 5, 3), dividend_per_share=9.0)])
    held = {"INE111A01011": 50.0, "INE444D01014": 50.0}
    m = bank.match_dividends(div_df(450.0), feed, lambda i, d: held[i])
    assert bool(m.iloc[0]["ambiguous"]) is True
    m2 = bank.match_dividends(div_df(450.0), feed, lambda i, d: held[i], symbols={"INE444D01014": "ZEDCO", "INE111A01011": "ACMELTD"})
    assert m2.iloc[0]["isin"] == "INE111A01011" and bool(m2.iloc[0]["ambiguous"]) is False
    m3 = bank.match_dividends(div_df(450.0, "NACH CR-DIVIDEND ZEDCO LTD"), feed, lambda i, d: held[i], symbols={"INE444D01014": "ZEDCO", "INE111A01011": "ACMELTD"})
    assert m3.iloc[0]["isin"] == "INE444D01014"


def test_matched_dividend_becomes_a_dividend_event_with_tds_and_isin():
    df = div_df(405.0)
    m = bank.match_dividends(df, FEED[FEED["isin"] == "INE111A01011"], qty_on)
    matches = {r.ref_id: dict(isin=r.isin, gross=r.gross, tds=r.tds) for r in m.itertuples()}
    led, evs, rep = replay(df, matches)
    (inc,) = led.income
    assert (inc.kind, inc.isin, inc.gross, round(inc.tds, 2), round(inc.net, 2)) == ("dividend", "INE111A01011", 450.0, 45.0, 405.0)
    assert rep["unmatched_dividends"] == [] and led.cash_balance("SBI") == pytest.approx(df["balance"].iloc[-1])


def test_own_transfers_on_two_statements_pair_one_to_one():
    rules = [{"id": "own", "category": "own_transfer", "direction": d, "patterns": ["SELF"],
              "_rx": [__import__("re").compile("SELF")]} for d in ("credit", "debit")]
    a = bank.classify(bank.parse(csv_of([("04 May 2026", "IMPS SELF TO B", 500.0, 0), ("09 May 2026", "IMPS SELF TO B", 500.0, 0)])), rules)
    b = bank.classify(bank.parse(csv_of([("05 May 2026", "IMPS SELF FROM A", 0, 500.0), ("20 May 2026", "IMPS SELF FROM X", 0, 500.0)])), rules)
    (p,) = bank.pair_own_transfers({"A": a, "B": b})
    assert (p["from_account"], p["to_account"], p["date"], p["amount"]) == ("A", "B", date(2026, 5, 4), 500.0)
    assert p["from_ref"] == f"bank:A:{a['ref_id'].iloc[0]}" and p["to_ref"] == f"bank:B:{b['ref_id'].iloc[0]}"


def test_broker_verification_pennies_are_not_broker_transfers():
    df = bank.classify(bank.parse(csv_of([
        ("02 Jun 2026", "UPI-ZERODHA BROKING LTD-ZERODHABROKINGSIGNUP@HDFCBANK-UPI", 1.0, 0),
        ("02 Jun 2026", "UPI-ZERODHA BROKING LTD-ZERODHABROKINGSIGNUP@HDFCBANK-ZERODHA REFUND 556", 0, 1.0),
        ("19 Aug 2026", "DEP TFR IMPS/000/RE1-XX413-ZERODHA /DOMIMPS01", 0, 1.0),
        ("24 Aug 2026", "WDL TFR INB Zerodha Broking Limited", 500.0, 0)])))
    assert list(df["category"]) == ["verification", "verification", "verification", "broker_transfer"]
