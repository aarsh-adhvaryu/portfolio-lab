"""2026-10-31: the first real run counted no fixed deposit at all. His deposits are rebuilt by the app from every input that exists (his deposit
file, each bank's deposit summary), valued from their terms when no current value is known, kept apart per bank, never double counted on a
re-drop, renewed when a later term appears, and left out (and asked about) once matured with no closing seen. Every value here is invented."""
from __future__ import annotations

import io
from datetime import date, datetime

import pandas as pd
import pytest

from pflab.app import inbox as ib
from pflab.app import runtime
from pflab.ingest import bank
from pflab.ingest import fd_summary as fs
from pflab.ingest import sniff
from pflab.pm import fd as fdm
from pflab.pm import store

NOW = datetime(2026, 10, 31, 10, 0)


def _hdfc_amount(principal, rate_pct, start, maturity):
    """An invented 'HDFC' maturity figure: SBI's arithmetic 0.01% lower, as the real summary differs."""
    raw = fdm.contract_value(fdm.FD("x", principal, rate_pct / 100, start, maturity, principal * 2, bank="SBI"), maturity)
    return round(raw * 0.9999, 2)


DEPS = [("50100000001111", 200000.0, 7.10, date(2025, 4, 1), date(2027, 9, 30)),
        ("50100000002222", 150000.0, 7.10, date(2025, 4, 1), date(2027, 9, 30)),
        ("50100000003333", 50000.0, 6.90, date(2026, 1, 15), date(2027, 1, 15))]


def summary_rows(deps=DEPS, total_off=0.0):
    rows = [["HDFC Bank Ltd."], [], ["Name :", "AN INVENTED HOLDER"], [], ["", "", "", "Fixed Deposit Summary"],
            ["Sr. No", "Account No.", "Branch", "Name", "CCY.", "Principal Amount.", "Maturity Amount", "Maturity Date", "Rate of Interest",
             "Deposit Start Date"], ["*" * 8] * 10, []]
    tp = tm = 0.0
    for i, (acct, p, r, s, e) in enumerate(deps, 1):
        m = _hdfc_amount(p, r, s, e)
        tp, tm = tp + p, tm + m
        rows.append([str(i), acct, "SOME - BRANCH", "AN INVENTED HOLDER,", "INR", f"{p:.2f}", f"{m:.2f}", e.strftime("%d %b %Y"), f"{r:.2f}",
                     s.strftime("%d %b %Y")])
    rows.append(["", "", "", "", "Total  INR", f"{tp + total_off:,.2f}", f"{tm:,.2f}", "", "", ""])
    rows.append(["* The principal amount displayed is the amount at the start of the term"])
    return rows


def xlsx(rows) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "FD Summary"
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


# --- the reader -----------------------------------------------------------------------------------------------------------------------------------

def test_a_bank_deposit_summary_is_read_checked_against_its_total_and_keeps_only_last_four_digits():
    deps = fs.parse_rows(summary_rows())
    assert [d.last4 for d in deps] == ["1111", "2222", "3333"] and deps[0].start == date(2025, 4, 1) and deps[2].rate_pct == 6.9
    assert "50100000001111" not in repr(deps) and "INVENTED" not in repr(deps)
    assert fs.bank_of(summary_rows()) == "HDFC"
    with pytest.raises(fs.SummaryError, match="Total row"):
        fs.parse_rows(summary_rows(total_off=100.0))
    assert sniff.from_rows([[str(c) for c in r] for r in summary_rows()])["kind"] == "fd_summary"


# --- valuation and the register -----------------------------------------------------------------------------------------------------------------

def test_a_deposit_with_no_current_value_is_an_estimate_from_its_terms_and_another_bank_ends_on_its_own_figure():
    d = fs.parse_rows(summary_rows())[0]
    f = fdm.FD("1111", d.principal, d.rate_pct / 100, d.start, d.maturity, d.maturity_amount, bank="HDFC")
    assert fdm.check(f) == d.maturity_amount and abs(fdm.contract_value(f, f.maturity) - d.maturity_amount) < 0.01
    v = fdm.value(f, date(2026, 10, 31))
    assert v.value > d.principal and "no current value read yet" in v.method and v.as_of == d.start
    with pytest.raises(fdm.FDError):                                                            # 1% off is a typing slip, not a convention
        fdm.check(fdm.FD("9", d.principal, d.rate_pct / 100, d.start, d.maturity, d.maturity_amount * 1.01, bank="HDFC"))


def _sbi(fd_id, start=date(2025, 6, 1), maturity=date(2027, 6, 1), p=100000.0):
    f = fdm.FD(fd_id, p, 0.07, start, maturity, 1.0, bank="SBI")
    return fdm.FD(fd_id, p, 0.07, start, maturity, round(fdm.contract_value(f, maturity), 2), bank="SBI", opened=start)


def test_the_register_keeps_one_deposit_per_bank_and_number_renews_on_a_later_term_and_tells_banks_apart():
    deps = fs.parse_rows(summary_rows())
    s1 = {"bank": "HDFC", "deposits": deps, "observed": datetime(2026, 10, 1), "source": "a"}
    fds, notes = fdm.register([_sbi("1111"), _sbi("4444")], [s1, {**s1, "observed": datetime(2026, 10, 2)}])
    ids = sorted(f.fd_id for f in fds)
    assert ids == ["2222", "3333", "4444", "HDFC-1111", "SBI-1111"] and notes["from_summaries"] == 3      # the same summary twice: once
    renewed = fs.Deposit("3333", 50000.0, _hdfc_amount(50000.0, 7.0, date(2027, 1, 15), date(2028, 1, 15)), date(2027, 1, 15), date(2028, 1, 15), 7.0)
    fds2, notes2 = fdm.register([], [s1, {"bank": "HDFC", "deposits": [renewed], "observed": datetime(2027, 1, 20), "source": "b"}])
    f = next(x for x in fds2 if x.fd_id == "3333")
    assert len(fds2) == 3 and f.term_start == date(2027, 1, 15) and f.opened == date(2026, 1, 15) and len(notes2["renewed"]) == 1


def test_a_second_certificate_of_the_same_year_keeps_the_first(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    fdm.save_interest(con, 2026, [{"fd_id": "1111", "paid": 10.0, "accrued": 0.0, "tds": 1.0}], "cert A")
    fdm.save_interest(con, 2026, [{"fd_id": "HDFC-2222", "paid": 20.0, "accrued": 0.0, "tds": 2.0}], "cert B")
    fdm.save_interest(con, 2026, [{"fd_id": "1111", "paid": 11.0, "accrued": 0.0, "tds": 1.1}], "cert A")       # the same certificate again
    facts = fdm.interest_facts(con)
    assert facts[("1111", 2026)]["paid"] == 11.0 and facts[("HDFC-2222", 2026)]["paid"] == 20.0 and len(facts) == 2


# --- the app's own path ---------------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(ib, "_start", lambda rt, iid: ib._process(rt, iid))
    monkeypatch.setattr(sniff, "passwords_from_secrets", lambda: [])
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def _his_file(rt, *fds):
    rt.pm_dir.joinpath("fd_holdings.toml").write_text("as_of = 2026-10-15\n" + "".join(
        f"\n[[fd]]\nid = \"{f.fd_id}\"\nbank = \"SBI\"\nprincipal = {f.principal}\nrate_pct = {f.rate * 100}\nstart = {f.term_start}\n"
        f"maturity = {f.maturity}\nmaturity_amount = {f.maturity_amount}\n" for f in fds), encoding="utf-8")


def test_dropping_a_summary_counts_its_deposits_and_a_redrop_restart_or_rerun_changes_nothing(rt):
    from pflab.calc import networth
    _his_file(rt, _sbi("4444"))
    raw = xlsx(summary_rows())
    r = ib.receive(rt, "FDSummary_Oct.xlsx", raw)
    assert r["kind"] == "fd_summary"
    assert ib._item(rt, r["id"])["status"] == "in the store"
    nw = networth.build(rt.cursor(), date(2026, 10, 31))
    assert sorted(nw["fds"]["fd_id"]) == ["1111", "2222", "3333", "4444"] and nw["fds"]["estimate"].all()
    assert set(nw["fds"]["bank"]) == {"HDFC", "SBI"} and nw["fd_excluded"] == []
    total = float(nw["fds"]["value"].sum())
    assert ib.receive(rt, "FDSummary_Oct.xlsx", raw)["duplicate"]                                  # the same file again
    ib.receive(rt, "FDSummary_Oct (1).xlsx", xlsx(summary_rows()) + b"")                           # a fresh export of the same summary
    ib.deposits_now(rt)                                                                           # a rerun (a restart, the job)
    assert len(fdm.load(rt.cursor())) == 4
    assert float(networth.build(rt.cursor(), date(2026, 10, 31))["fds"]["value"].sum()) == pytest.approx(total)


def test_a_summary_filed_as_other_by_an_older_version_is_read_again_and_counted(rt):
    p = rt.pm_dir / "inbox" / "fdsummary.xlsx"
    p.parent.mkdir(parents=True)
    p.write_bytes(xlsx(summary_rows()))
    rt.cursor().execute("INSERT INTO inbox_items (item_id, name, kind, path, sha, status, result_json, created_at, updated_at) "
                        "VALUES (1, 'fdsummary.xlsx', 'other', ?, 'abc', 'kept', '{}', ?, ?)", [str(p), NOW, NOW])
    before = ib.deposits_fingerprint(rt)
    out = ib.deposits_now(rt)
    assert out["reclassified"] == 1 and out["deposits"] == 3 and ib._item(rt, 1)["kind"] == "fd_summary"
    assert ib.deposits_fingerprint(rt) != before and ib.deposits_fingerprint(rt) == ib.deposits_fingerprint(rt)


def test_a_matured_deposit_is_left_out_named_and_asked_about_once(rt):
    from pflab.agents import questions
    from pflab.calc import networth
    _his_file(rt, _sbi("4444"), _sbi("5555", start=date(2024, 6, 1), maturity=date(2026, 6, 1)))
    ib.deposits_now(rt)
    nw = networth.build(rt.cursor(), date(2026, 10, 31))
    assert list(nw["fds"]["fd_id"]) == ["4444"] and nw["fd_excluded"][0]["fd_id"] == "5555" and "matured" in nw["fd_excluded"][0]["why"]
    ib.deposits_now(rt)
    qs = [t for _, k, t in questions.open_questions(rt.cursor()) if "maturity" in t]
    assert len(qs) == 1 and "SBI ending 5555" in qs[0]


def test_his_deposit_file_goes_with_him_through_a_fresh_start():
    from pflab.pm import fresh
    assert "fd_holdings.toml" in fresh.CHOICES


def test_the_setup_form_can_give_the_banks_current_value_and_keeps_the_summary_deposits(rt):
    _his_file(rt, _sbi("4444"))
    ib.receive(rt, "FDSummary_Oct.xlsx", xlsx(summary_rows()))
    f = _sbi("6666")
    e = fdm.entry("6666", "SBI", f.principal, 7.0, f.term_start, f.maturity, f.maturity_amount, current_value=f.principal * 1.05,
                  value_on=date(2026, 10, 30))
    fdm.add_to_file(rt.pm_dir / "fd_holdings.toml", e)
    ib.deposits_now(rt)
    got = {x.fd_id: x for x in fdm.load(rt.cursor())}
    assert set(got) == {"1111", "2222", "3333", "4444", "6666"} and got["6666"].anchor_date == date(2026, 10, 30)
    assert fdm.value(got["6666"], date(2026, 10, 30)) == pytest.approx(f.principal * 1.05)


def test_a_zerodha_contract_note_pdf_is_recognised_as_a_ledger_document():
    text = "Zerodha Broking Ltd. CONTRACT NOTE CUM TAX INVOICE Contract Note No: CNT-26/27-0000001 Trade Date: 16/10/2026"
    assert sniff.from_text(text)["kind"] == "contract_note"
    assert sniff.from_text("Zerodha transaction with holding statement")["kind"] == "other"


# --- the ledger's last differences (2026-10-31) --------------------------------------------------------------------------------------------

def test_a_day_with_no_contract_note_takes_its_charges_from_the_brokers_settlement():
    from pflab.ingest import contract_note as cn
    from pflab.ledger.events import Event
    ev = [Event("buy", "ZER", date(2026, 10, 16), isin="INE000A01011", qty=10, price=1000.0, ref="t1"),
          Event("buy", "ZER", date(2026, 10, 16), isin="INE000A01029", qty=5, price=400.0, ref="t2"),
          Event("sell", "ZER", date(2026, 10, 20), isin="INE000A01011", qty=10, price=1100.0, ref="t3", fees={"brokerage": 1.0}),
          Event("buy", "ZER", date(2026, 10, 22), isin="INE000A01029", qty=1, price=400.0, ref="t4")]
    settle = {date(2026, 10, 16): -12000.0 - 15.40, date(2026, 10, 22): -400.0 + 50.0}           # the 22nd: a credit, not charges
    out, rep = cn.fees_from_settlements(ev, settle)
    f1, f2 = out[0].fees, out[1].fees
    assert rep["days"] == {"2026-10-16": 15.4} and rep["trades"] == 2
    assert f1["stt"] == 10.0 and f2["stt"] == 2.0 and sum(f1.values()) + sum(f2.values()) == pytest.approx(15.4)
    assert out[2].fees == {"brokerage": 1.0} and out[3].fees == {}                                      # a note day untouched; a bad day refused
    assert any("not charges" in why for _, why in rep["skipped"])
    assert out[0].cost_fee_total == pytest.approx(f1["charges_console"])                               # STT is no cost for capital gains


def test_a_line_he_called_his_own_transfer_that_is_a_zerodha_payout_is_matched_as_one():
    from pflab.ingest import bank_labels as bl
    df = pd.DataFrame([dict(date=date(2026, 8, 8), description="NEFT CR ZERODHA", debit=0.0, credit=4000.5, balance=0.0, ref="", value_date=date(2026, 8, 8))])
    df = bank.classify(df, rules=[])
    df["category"], df["rule_id"] = "own_transfer", "label_x"                                          # his label
    flows = pd.DataFrame({"date": [date(2026, 8, 7)], "amount": [-4000.5]})
    out, rep = bl.auto_label({"HDFC_0001": df}, flows)
    assert rep["broker"] == 1 and out["HDFC_0001"]["category"].iloc[0] == "broker_transfer"


def test_every_balance_is_traced_to_its_source_with_its_basis(rt):
    from pflab.app import readiness
    from pflab.pm import trace
    _his_file(rt, _sbi("4444"))
    ib.receive(rt, "FDSummary_Oct.xlsx", xlsx(summary_rows()))
    readiness.open_gap(rt.cursor(), "ledger:diff:pay-in", "ledger", "not in any bank statement given: 2026-10-26 +5,000.00", NOW)
    rows = {(r["what"], r["account"]): r for r in trace.build(rt.cursor(), date(2026, 10, 31))}
    hd = rows[("deposits", "HDFC")]
    assert hd["n"] == 3 and hd["basis"] == "estimate" and "bank summary" in hd["sources"][0] and hd["method"]
    assert rows[("deposits", "SBI")]["n"] == 1 and ("difference", "pay-in") in rows and rows[("net worth", "all")]["value"] > 0
    assert "from:" in trace.render(list(rows.values()))
