"""S5 build-ahead: CAS import through casparser's typed models. The statements below are SYNTHETIC models built
in code (no real CAS PDF is available to test against); casparser itself is exercised only on a non-PDF."""
from datetime import date
from decimal import Decimal

import pytest
from casparser.types import (Bond, CASData, DematAccount, DematOwner, Equity, Folio, InvestorInfo, MutualFund,
                             NSDLCASData, Scheme, SchemeValuation, StatementPeriod, TransactionData)

from pflab.calc import returns as rt
from pflab.ingest import cas
from pflab.ledger.book import Ledger
from pflab.ledger.events import Event, EventLog
from pflab.pm import store

FUND, FUND2 = "INF000A01AB9", "INF000B01AC7"
INV = InvestorInfo(name="Synthetic Investor", email="x@example.com", address="-", mobile="0")


def txn(d, typ, units, nav, amount, desc="x", balance=None):
    return TransactionData(date=d, description=desc, amount=Decimal(str(amount)) if amount is not None else None,
                           units=Decimal(str(units)) if units is not None else None,
                           nav=Decimal(str(nav)) if nav is not None else None,
                           balance=Decimal(str(balance)) if balance is not None else None, type=typ)


def scheme(name, isin, txns, close, amfi=None, **kw):
    return Scheme(scheme=name, rta_code="X", rta="CAMS", isin=isin, amfi=amfi, open=Decimal("0"), close=Decimal(str(close)),
                  close_calculated=Decimal(str(close)),
                  valuation=SchemeValuation(date=date(2026, 9, 30), nav=Decimal("20"), value=Decimal(str(close * 20))), transactions=txns, **kw)


def cams(schemes, warnings=()):
    return CASData(statement_period=StatementPeriod(**{"from": "2025-04-01", "to": "2026-09-30"}),
                   folios=[Folio(folio="1234/56", amc="Synthetic MF", schemes=schemes)], investor_info=INV,
                   cas_type="DETAILED", file_type="CAMS", parse_warnings=list(warnings))


def basic_cas():
    t = [txn("2025-04-10", "PURCHASE", 100.000, 10.0, 1000.0),
         txn("2025-04-10", "STAMP_DUTY_TAX", None, None, 0.05),
         txn("2025-06-05", "PURCHASE_SIP", 49.505, 10.10, 500.0),
         txn("2025-09-01", "DIVIDEND_REINVEST", 5.0, 12.0, 60.0),
         txn("2026-01-15", "REDEMPTION", -40.0, 15.0, -600.0),
         txn("2026-01-15", "STT_TAX", None, None, 0.01)]
    return cams([scheme("Synthetic Flexi Fund - Direct - Growth", FUND, t, close=114.505)])


# --- CAMS / KFin ------------------------------------------------------------------------------------------------

def test_events_replay_to_the_statement_totals_and_costs():
    imp = cas.cams_events(basic_cas(), tax_class_of=lambda i: "EQUITY")
    assert imp.manual == [] and imp.unmapped == [] and imp.accounts[0]["account_id"] == "Synthetic MF:1234/56"
    led = Ledger.replay(EventLog(imp.events))
    acc = "Synthetic MF:1234/56"
    assert led.holdings(FUND, acc) == pytest.approx(114.505)
    assert led.cash_balance(acc) == pytest.approx(0.0, abs=1e-9)                   # a folio never holds cash
    ver = cas.verify_against_statement(basic_cas(), led)
    assert ver["ok"].all() and ver.iloc[0]["ledger_units"] == pytest.approx(114.505)
    lots = led.lots.lots(acc, FUND)
    assert [(l.acq_date, round(l.qty, 3)) for l in lots] == [(date(2025, 4, 10), 60.0), (date(2025, 6, 5), 49.505), (date(2025, 9, 1), 5.0)]
    assert lots[0].cost_per_unit == pytest.approx(10.0) and lots[0].tax_class == "EQUITY"        # cost = statement amount
    (c,) = led.realised
    assert c.qty == pytest.approx(40.0) and c.proceeds == pytest.approx(600.0) and c.gain == pytest.approx(200.0)
    assert [i.gross for i in led.income] == [60.0] and led.income[0].kind == "dividend"


def test_bank_flows_are_the_external_flows_for_xirr():
    led = Ledger.replay(EventLog(cas.cams_events(basic_cas()).events))
    flows = rt.external_flows(led)
    assert [(d, a) for d, a in flows] == [(date(2025, 4, 10), 1000.0), (date(2025, 6, 5), 500.0), (date(2026, 1, 15), -600.0)]
    r = rt.xirr(led, 114.505 * 20.0, date(2026, 9, 30))                              # 2,290 today
    assert 0.1 < r < 1.0


def test_stt_stamp_and_tds_rows_are_not_double_counted():
    imp = cas.cams_events(basic_cas())
    assert not any("STT" in (e.ref or "") or "STAMP" in (e.ref or "") for e in imp.events)
    assert sum(1 for e in imp.events if e.kind == "buy") == 3 and sum(1 for e in imp.events if e.kind == "sell") == 1


def test_unsupported_types_leave_the_whole_scheme_out_with_a_reason():
    t = [txn("2025-04-10", "PURCHASE", 100.0, 10.0, 1000.0), txn("2025-09-01", "SWITCH_IN_MERGER", 100.0, 10.0, 1000.0)]
    ok = [txn("2025-04-10", "PURCHASE", 10.0, 10.0, 100.0)]
    imp = cas.cams_events(cams([scheme("Merged Fund", FUND, t, close=200.0), scheme("Plain Fund", FUND2, ok, close=10.0)]))
    assert len(imp.manual) == 1 and "SWITCH_IN_MERGER" in imp.manual[0] and "Merged Fund" in imp.manual[0]
    assert {e.isin for e in imp.events if e.isin} == {FUND2}                         # nothing of the odd scheme imported
    ver = cas.verify_against_statement(cams([scheme("Merged Fund", FUND, t, close=200.0)]), Ledger.replay(EventLog(imp.events)))
    assert not ver["ok"].iloc[0]


def test_scheme_without_isin_uses_the_amfi_code_or_is_reported(tmp_path):
    s = scheme("No ISIN Fund", None, [txn("2025-04-10", "PURCHASE", 10.0, 10.0, 100.0)], close=10.0, amfi="100")
    assert cas.cams_events(cams([s])).unmapped == ["Synthetic MF 1234/56 No ISIN Fund"]
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("INSERT INTO amfi_schemes (scheme_code, isin_1, name, source_doc_sha, ingested_at) VALUES ('100', ?, 'x', 's', now())", [FUND])
    imp = cas.cams_events(cams([s]), by_amfi=cas.amfi_isin_lookup(con))
    assert imp.unmapped == [] and {e.isin for e in imp.events if e.isin} == {FUND}


def test_import_is_idempotent():
    first = cas.cams_events(basic_cas())
    again = cas.cams_events(basic_cas(), existing_refs={e.ref for e in first.events})
    assert again.events == [] and again.skipped_existing == len(first.events)
    half = cas.cams_events(basic_cas(), existing_refs={e.ref for e in first.events[:4]})
    assert len(half.events) == len(first.events) - 4


def test_parse_warnings_from_casparser_are_surfaced():
    imp = cas.cams_events(cams([scheme("F", FUND, [txn("2025-04-10", "PURCHASE", 10.0, 10.0, 100.0)], close=10.0)],
                                warnings=["row dropped in scheme F"]))
    assert imp.warnings == ["row dropped in scheme F"]


def test_a_statement_total_mismatch_is_flagged():
    bad = basic_cas()
    bad.folios[0].schemes[0].close = Decimal("120")
    ver = cas.verify_against_statement(bad, Ledger.replay(EventLog(cas.cams_events(basic_cas()).events)))
    assert not ver["ok"].iloc[0] and "differ by -5.4950" in ver["note"].iloc[0]


def test_casparser_is_called_for_real_on_a_non_pdf(tmp_path):
    f = tmp_path / "not_a_cas.pdf"
    f.write_bytes(b"this is not a pdf")
    with pytest.raises(Exception):
        cas.parse_pdf(f, "PASSWORD")


# --- CDSL / NSDL -----------------------------------------------------------------------------------------------------

def depository():
    def acct(name, typ, dp, cl, eq, mf=(), bonds=()):
        return DematAccount(name=name, type=typ, dp_id=dp, client_id=cl, folios=1, balance=Decimal("0"),
                            owners=[DematOwner(name="Synthetic Investor", PAN="AAAAA0000A")], equities=list(eq),
                            mutual_funds=list(mf), bonds=list(bonds))
    zer = acct("Zerodha Broking", "CDSL", "12000000", "00001111",
               [Equity(name="Stock A", isin="INE111A01011", num_shares=Decimal("15"), price=Decimal("120"), value=Decimal("1800"))],
               [MutualFund(name="Fund X", isin=FUND, balance=Decimal("10"), nav=Decimal("20"), value=Decimal("200"))])
    old = acct("Old Broker", "NSDL", "IN300000", "12345678",
               [Equity(name="Stock B", isin="INE222B01012", num_shares=Decimal("100"), price=Decimal("50"), value=Decimal("5000"))],
               bonds=[Bond(isin="INE333C07013", num_bonds=Decimal("5"), value=Decimal("5100"), market_price=Decimal("1020"))])
    return NSDLCASData(accounts=[zer, old], statement_period=StatementPeriod(**{"from": "2026-09-01", "to": "2026-09-30"}),
                       investor_info=INV, file_type="CDSL")


def test_demat_accounts_dormant_demat_is_flagged_read_only():
    accts = {a["account_id"]: a for a in cas.demat_accounts(depository(), dormant=["NSDL:IN300000:12345678"])}
    assert set(accts) == {"CDSL:12000000:00001111", "NSDL:IN300000:12345678"}
    assert accts["NSDL:IN300000:12345678"]["dormant"] and accts["NSDL:IN300000:12345678"]["read_only"]
    assert not accts["CDSL:12000000:00001111"]["dormant"] and not accts["CDSL:12000000:00001111"]["read_only"]


def test_holdings_snapshot_has_every_account_and_kind():
    s = cas.holdings_snapshot(depository())
    assert len(s) == 4 and set(s["kind"]) == {"equity", "mutual_fund", "bond"}
    assert s.set_index("isin").loc["INE222B01012", "account"] == "NSDL:IN300000:12345678"
    assert s["value"].sum() == pytest.approx(1800 + 200 + 5000 + 5100)


def test_opening_lots_without_cost_are_cost_zero_and_listed():
    snap = cas.holdings_snapshot(depository())
    evs, unknown = cas.opening_events(snap, date(2026, 9, 30), {"CDSL:12000000:00001111": "ZER"})
    assert len(evs) == 4 and len(unknown) == 4 and all("cost and purchase date unknown" in u for u in unknown)
    led = Ledger.replay(EventLog([Event("deposit", "ZER", date(2026, 1, 1), amount=1.0)] + [e for e in evs if e.account_id == "ZER"]))
    assert led.holdings("INE111A01011", "ZER") == 15 and led.lots.lots("ZER", "INE111A01011")[0].cost_per_unit == 0.0


def test_opening_lots_with_known_cost_keep_date_and_cost():
    snap = cas.holdings_snapshot(depository())
    known = {"NSDL:IN300000:12345678": {"INE222B01012": (date(2015, 3, 2), 3_000.0)}}
    evs, unknown = cas.opening_events(snap, date(2026, 9, 30), cost_of=lambda a, i: known.get(a, {}).get(i))
    assert len(unknown) == 3
    led = Ledger.replay(EventLog([e for e in evs if e.account_id.startswith("NSDL") and e.isin in (None, "INE222B01012")]))
    (lot,) = led.lots.lots("NSDL:IN300000:12345678", "INE222B01012")
    assert (lot.acq_date, lot.qty, lot.cost) == (date(2015, 3, 2), 100, pytest.approx(3_000.0))


def test_bond_rows_read_one_column_off_are_recovered_only_when_they_add_up():
    from types import SimpleNamespace as NS
    from pflab.ingest import cas as c
    shifted = NS(isin="IN0020000001", num_bonds="4777.00", market_price=None, value="153972.40",
                 face_value="15397.24", maturity_date="10", coupon_frequency="25-May-2029")
    assert c._bond_qty_price(shifted) == (10.0, 15397.24)
    normal = NS(isin="IN0020000001", num_bonds="10", market_price=None, value="152860.20",
                face_value="4777.00", maturity_date="25-May-2029")
    assert c._bond_qty_price(normal) == (10.0, pytest.approx(15286.02))
    bad = NS(isin="IN0020000001", num_bonds="10", market_price="100.0", value="5000.0", face_value=None, maturity_date=None)
    with pytest.raises(ValueError, match="not the stated value"):
        c._bond_qty_price(bad)
