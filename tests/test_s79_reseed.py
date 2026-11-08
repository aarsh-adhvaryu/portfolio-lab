"""S79 item 2 (A45): the system's account and paper book re-seeded from Kite holdings only, the old paper record archived, the 40-session gate counting from the new seed,
the system's own allocation target (rails in code, reviewed by the independent review, drift and the gap handed to the manager), and ETFs of any kind buyable. Synthetic."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta

import duckdb
import pytest

from pflab.hq import missions, tools as tl
from pflab.ledger import events as ev, system
from pflab.paper import allocation, book, funds, manager, rails, reseed
from pflab.pm import store
from tests.test_s68_autonomy import CFG, rt  # noqa: F401  (the fixture)

AAA, BBB, OLDX = "INE000A01011", "INE000B01012", "INE000X01019"
GOLD, NDQ, SGB = "INF000G01001", "INF000N01002", "IN0020230010"
NEWETF, NEWSGB = "INF999Z01009", "IN0020210111"
COIN = "INF000C01003"
DAYS = [date(2026, 10, 26) + timedelta(days=k) for k in range(0, 80) if (date(2026, 10, 26) + timedelta(days=k)).weekday() < 5]
NOW = datetime(2026, 11, 6, 16, 0)
SEED_DAY = date(2026, 11, 6)
PX = {AAA: 60.0, BBB: 40.0, OLDX: 10.0, GOLD: 58.0, NDQ: 130.0, SGB: 6100.0, COIN: 25.0, NEWETF: 70.0, NEWSGB: 6200.0}
HOLD = [dict(tradingsymbol="AAA", exchange="NSE", isin=AAA, quantity=100, t1_quantity=0, average_price=50.0, last_price=60.0),
        dict(tradingsymbol="BBB", exchange="NSE", isin=BBB, quantity=40, t1_quantity=0, average_price=30.0, last_price=40.0),
        dict(tradingsymbol="GOLDETF", exchange="NSE", isin=GOLD, quantity=200, t1_quantity=0, average_price=55.0, last_price=58.0),
        dict(tradingsymbol="NDQETF", exchange="NSE", isin=NDQ, quantity=50, t1_quantity=2, average_price=120.0, last_price=130.0),
        dict(tradingsymbol="SGBMAR30", exchange="NSE", isin=SGB, quantity=8, t1_quantity=0, average_price=0.0, last_price=6100.0)]       # an inherited SGB: no purchase price


def _inst(c, isin, cls, tc, sym, name, sec=None):
    c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, ?, 'synthetic', now())",
              [isin, cls, tc, sym, name, sec])


@pytest.fixture
def con(tmp_path, monkeypatch):
    pm = tmp_path / "pm"
    pm.mkdir()
    monkeypatch.setenv("PFLAB_PM_DIR", str(pm))
    c = store.connect(pm / "ledger.duckdb")
    _inst(c, AAA, "equity", "EQUITY", "AAA", "AAA Ltd", "IT")
    _inst(c, BBB, "equity", "EQUITY", "BBB", "BBB Ltd", "Banks")
    _inst(c, OLDX, "equity", "EQUITY", "OLDX", "OLDX Ltd", "Pharma")
    _inst(c, GOLD, "etf", "LISTED_NONEQUITY", "GOLDETF", "Gold ETF")
    _inst(c, NDQ, "etf", "REVIEW", "NDQETF", "Nasdaq 100 ETF")
    _inst(c, SGB, "sgb", "SGB", "SGBMAR30", "Sovereign Gold Bond 2030")
    _inst(c, COIN, "mutual_fund", "DEBT_MF", "COINFUND", "Some Fund")
    for d in DAYS:
        for isin, px in PX.items():
            c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d, px])
    # the OLD store: his statements' accounts (Zerodha demat, a bank, an off-Kite Coin folio), an FD, the system's own earlier trade, and the old paper record
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZERODHA', 'demat', 'Zerodha')")
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('HDFCBANK', 'bank', 'a bank')")
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('COIN', 'folio', 'Zerodha Coin')")
    log = ev.EventLog()
    log.append(ev.Event(kind="deposit", account_id="ZERODHA", date=date(2024, 1, 1), amount=1_000_000.0))
    log.append(ev.Event(kind="deposit", account_id="HDFCBANK", date=date(2024, 1, 1), amount=2_000_000.0))
    log.append(ev.Event(kind="deposit", account_id="COIN", date=date(2024, 1, 1), amount=100_000.0))
    log.append(ev.Event(kind="buy", account_id="ZERODHA", date=date(2024, 1, 10), isin=OLDX, qty=500.0, price=8.0, ref="stmt:1"))
    log.append(ev.Event(kind="buy", account_id="ZERODHA", date=date(2026, 11, 3), isin=AAA, qty=5.0, price=58.0, ref="sys:order:7"))
    log.append(ev.Event(kind="buy", account_id="COIN", date=date(2024, 2, 1), isin=COIN, qty=1000.0, price=20.0, ref="stmt:2"))
    ev.save(c, log, datetime(2026, 11, 3))
    system.derive(c, datetime(2026, 11, 3))
    c.execute("INSERT INTO fds (fd_id, bank, principal, rate, term_start, maturity, maturity_amount, status, source, loaded_at) VALUES ('FD1', 'a bank', 100000, 7.0, ?, ?, 107000, 'open', 'stmt', now())",
              [date(2025, 1, 1), date(2027, 1, 1)])
    for d in (date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)):
        c.execute("INSERT INTO paper_days VALUES (?, 600000, 500000, 100000, 0, '{}')", [d])
    c.execute("INSERT INTO paper_decisions (decision_id, made_at, case_id, action, isin, symbol, reason, status) VALUES (1, ?, NULL, 'BUY', ?, 'AAA', 'old reason for a buy here', 'executed')", [datetime(2026, 11, 2, 10), AAA])
    c.execute("INSERT INTO paper_orders VALUES (1, ?, 1, ?, 'AAA', 'buy', NULL, 5000, 'filled', ?, '')", [datetime(2026, 11, 2, 10), AAA, date(2026, 11, 3)])
    c.execute("INSERT INTO paper_trades VALUES (1, ?, 1, 1, ?, 'AAA', 'buy', 5, 58, 1, NULL, NULL, '{}')", [date(2026, 11, 3), AAA])
    c.execute("INSERT INTO paper_claims VALUES (1, 1, ?, 'BUY', 'add', ?, 58, NULL, 7, ?, NULL, NULL, NULL)", [AAA, date(2026, 11, 3), date(2026, 11, 10)])
    c.execute("INSERT INTO paper_lessons VALUES (1, now(), 'k', 'a lesson learned on the old book', 3, 'lesson-key', NULL)")
    return c


def _reseed(con, tmp_path, **kw):
    return reseed.reseed(con, HOLD, NOW, backup_dir=tmp_path / "backups", **kw)


# --- the re-seed ---------------------------------------------------------------------------------------------------------------------

def test_the_account_is_exactly_the_kite_holdings_and_nothing_else(con, tmp_path):
    out = _reseed(con, tmp_path)
    assert out["done"] and out["seed_date"] == str(SEED_DAY) and out["positions"] == 5
    assert sorted(r[0] for r in con.execute("SELECT account_id FROM accounts").fetchall()) == ["SYSBANK", "SYSBROKER"]      # no bank, no Coin folio, no Zerodha statement account
    assert con.execute("SELECT count(*) FROM lots WHERE account_id <> 'SYSBROKER'").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM events WHERE account_id NOT IN ('SYSBANK','SYSBROKER')").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM fds").fetchone()[0] == 0                                                          # the FD is gone
    pos = {i: q for i, q in con.execute("SELECT isin, sum(qty) FROM lots GROUP BY 1").fetchall()}
    assert pos == {AAA: 100.0, BBB: 40.0, GOLD: 200.0, NDQ: 52.0, SGB: 8.0}                                                    # (T1 quantity counts); OLDX and the Coin fund are gone
    cost = {i: c for i, c in con.execute("SELECT isin, cost_per_unit FROM lots").fetchall()}
    assert cost[AAA] == pytest.approx(50.0) and cost[GOLD] == pytest.approx(55.0)                                              # Kite's average price
    assert abs(book.cash(con) - 500_000.0) < 0.01 and abs(funds.bank_cash(con)) < 0.01                                          # the fake Rs 5,00,000 sits at the broker
    assert system.active() and system.settings()["seed_date"] == str(SEED_DAY) and system.settings()["topup_month_max"] == 50_000.0


def test_an_sgb_with_no_purchase_price_starts_at_the_days_close_and_is_flagged_inherited(con, tmp_path):
    out = _reseed(con, tmp_path)
    assert out["cost_unknown"] == ["SGBMAR30"]
    ref = con.execute("SELECT ref, price FROM events WHERE isin=?", [SGB]).fetchone()
    assert ref[0].endswith(":cost_unknown") and ref[1] == pytest.approx(6100.0)
    v = manager.book_view(con, SEED_DAY)
    by = {h["symbol"]: h for h in v["holdings"]}
    assert by["SGBMAR30"]["cost_known"] is False and by["AAA"]["cost_known"] is True and by["SGBMAR30"]["gain"] == pytest.approx(0.0)


def test_the_old_paper_record_is_archived_labelled_and_nothing_is_deleted(con, tmp_path):
    out = _reseed(con, tmp_path)
    a = out["archive"]
    assert a["label"] == f"paper record 2026-11-02 to {SEED_DAY}, archived by A45"
    for t, n in (("paper_decisions", 1), ("paper_orders", 1), ("paper_trades", 1), ("paper_claims", 1), ("paper_days", 4)):
        assert con.execute(f"SELECT count(*) FROM {t}_archive_s79 WHERE archive_label = ?", [a["label"]]).fetchone()[0] == n
    assert con.execute("SELECT count(*) FROM paper_decisions").fetchone()[0] == 0 and con.execute("SELECT count(*) FROM paper_claims").fetchone()[0] == 0     # the live record starts empty
    assert con.execute("SELECT count(*) FROM paper_lessons").fetchone()[0] == 1                                                  # what it learned stays
    assert con.execute("SELECT count(*) FROM events_archive_s79 WHERE ref LIKE 'sys:%'").fetchone()[0] == 1                      # the system's own earlier trade is kept as history
    assert con.execute("SELECT label FROM paper_archive_s79").fetchone()[0] == a["label"]
    chk = duckdb.connect(out["backup"]["file"], read_only=True)                                                                 # the safety copy opens and holds the old store
    assert chk.execute("SELECT count(*) FROM fds").fetchone()[0] == 1 and chk.execute("SELECT count(*) FROM accounts").fetchone()[0] == 3
    chk.close()


def test_the_gate_and_the_scorecard_count_from_the_new_seed_day(con, tmp_path):
    _reseed(con, tmp_path)
    assert con.execute("SELECT min(day) FROM paper_days").fetchone()[0] == SEED_DAY and book.started(con) == SEED_DAY
    assert manager.gate(con, None)["status"].startswith("0 of 40 sessions")                                                      # day one of the new book
    book.catch_up(con, date(2026, 12, 10), datetime(2026, 12, 10, 18))
    n = len([d for d in DAYS if SEED_DAY < d <= date(2026, 12, 10)])
    assert book.returns(con)["sessions"] == n and book.returns(con)["since"] == str(SEED_DAY)
    assert manager.gate(con, None)["status"].startswith(f"{n} of 40 sessions")                                                   # not 4 + n: the old days are not counted
    book.catch_up(con, date(2027, 1, 12), datetime(2027, 1, 12, 18))
    assert "too early" not in manager.gate(con, None)["status"]                                                                   # 40 sessions after the new seed: the gate judges


def test_run_twice_does_nothing_unless_forced(con, tmp_path):
    first = _reseed(con, tmp_path)
    snap = reseed.snapshot(con)
    second = _reseed(con, tmp_path)
    assert second["done"] is False and second["skipped"] and reseed.snapshot(con) == snap
    assert len(list((tmp_path / "backups").iterdir())) == 1                                                                       # no second backup either
    third = _reseed(con, tmp_path, force=True)
    assert third["done"] and third["forced"] and con.execute("SELECT count(*) FROM reseed_s79").fetchone()[0] == 2
    assert first["archive"]["id"] != third["archive"]["id"]


def test_a_failure_changes_nothing(con, tmp_path, monkeypatch):
    before = reseed.snapshot(con)
    flag = system.flag_path()
    monkeypatch.setattr(book, "mark", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        _reseed(con, tmp_path)
    assert reseed.snapshot(con) == before and not flag.exists()
    assert con.execute("SELECT count(*) FROM reseed_s79").fetchone()[0] == 0
    with pytest.raises(ValueError):
        reseed.reseed(con, [], NOW, backup_dir=tmp_path / "backups")                                                              # no holdings: nothing to seed from
    with pytest.raises(ValueError):
        reseed.reseed(con, [dict(tradingsymbol="ZZZ", quantity=5, average_price=1.0)], NOW, backup_dir=tmp_path / "backups")        # no ISIN the record can find
    assert reseed.snapshot(con) == before


def test_an_unknown_etf_and_sgb_are_registered_from_the_listing(con, tmp_path):
    h = HOLD + [dict(tradingsymbol="NEWGOLDBEES", exchange="NSE", isin=NEWETF, quantity=10, t1_quantity=0, average_price=65.0, last_price=70.0),
                dict(tradingsymbol="SGBNOV31", exchange="NSE", isin=NEWSGB, quantity=3, t1_quantity=0, average_price=0.0, last_price=6200.0)]
    out = reseed.reseed(con, h, NOW, backup_dir=tmp_path / "backups")
    assert set(out["registered_instruments"]) == {NEWETF, NEWSGB}
    assert con.execute("SELECT asset_class FROM instruments WHERE isin=?", [NEWETF]).fetchone()[0] == "etf"
    assert con.execute("SELECT asset_class FROM instruments WHERE isin=?", [NEWSGB]).fetchone()[0] == "sgb"
    assert con.execute("SELECT price FROM events WHERE isin=?", [NEWSGB]).fetchone()[0] == pytest.approx(6200.0)


def test_his_targets_file_is_never_touched(con, tmp_path):
    t = system.flag_path().parent / "targets.toml"
    t.write_text('[targets]\nequity = 0.6\n', encoding="utf-8")
    h0 = hashlib.sha256(t.read_bytes()).hexdigest()
    _reseed(con, tmp_path)
    allocation.propose_allocation(con, {"equity": 70, "gold": 10, "international": 10, "cash": 10}, "a long-term split of the book for the next years, with reasons given", NOW)
    allocation.settle(con, NOW)
    assert hashlib.sha256(t.read_bytes()).hexdigest() == h0


# --- the allocation target ------------------------------------------------------------------------------------------------------------

def test_validate_target_holds_the_rails_in_code():
    ok = allocation.validate_target({"equity": 60, "gold": 15, "international": 15, "cash": 10}, {"IT": 20, "Banks": 25})
    assert ok["ok"] and ok["classes"]["gold"] == 15
    assert not allocation.validate_target({"equity": 60, "gold": 15, "international": 15, "cash": 5})["ok"]                       # sums to 95
    assert not allocation.validate_target({"equity": 110, "gold": 0, "international": 0, "cash": -10})["ok"]                       # borrowing / negative cash
    assert "no short sales" in " ".join(allocation.validate_target({"equity": 120, "gold": -20, "international": 0, "cash": 0})["problems"])
    assert not allocation.validate_target({"equity": 60, "gold": 15, "international": 15, "cash": 10}, {"IT": 26})["ok"]           # sector rail 25%
    assert not allocation.validate_target({"equity": 30, "gold": 30, "international": 20, "cash": 20}, {"IT": 20, "Banks": 20})["ok"]   # sectors more than equity
    bad = allocation.validate_target({"equity": 50, "gold": 20, "international": 10, "cash": 10, "futures": 10})
    assert not bad["ok"] and "no F&O" in " ".join(bad["problems"])
    assert not allocation.validate_target({"equity": 100, "bitcoin": 0, "gold": 0, "international": 0, "cash": 0})["ok"]
    assert not allocation.validate_target({"equity": "lots", "gold": 0, "international": 0, "cash": 0})["ok"]


def test_drift_and_the_gap_the_manager_works_from(con, tmp_path):
    _reseed(con, tmp_path)
    h = book.holdings(con, SEED_DAY)
    tgt = {"classes": {"equity": 40.0, "gold": 10.0, "international": 5.0, "cash": 45.0}, "sectors": {"IT": 10.0, "Banks": 5.0}}
    d = allocation.drift(h, tgt)
    by = {c["name"]: c for c in d["classes"]}
    total = h["value"]
    assert d["total"] == pytest.approx(total, abs=0.01)
    assert by["equity"]["actual_pct"] == pytest.approx(100 * (100 * 60 + 40 * 40) / total, abs=0.01)
    assert by["gold"]["actual_pct"] == pytest.approx(100 * (200 * 58 + 8 * 6100) / total, abs=0.01)                                  # gold ETF and the SGB are one class
    assert by["international"]["actual_pct"] == pytest.approx(100 * 52 * 130 / total, abs=0.01)                                       # the Nasdaq ETF
    assert by["cash"]["actual_pct"] == pytest.approx(100 * 500_000 / total, abs=0.01)
    assert by["cash"]["gap_pct"] == pytest.approx(by["cash"]["target_pct"] - by["cash"]["actual_pct"], abs=0.01)
    g = allocation.trade_toward(h, tgt)
    assert [x["name"] for x in g["trim"]][0] == "cash" and not g["in_band"] and g["add"]
    assert "sizing" in g["note"]
    same = {"classes": {c["name"]: c["actual_pct"] for c in d["classes"]}, "sectors": {}}
    assert allocation.trade_toward(h, same)["in_band"]


def _mission(con, rt):
    return missions.create(con, NOW, "Paper portfolio: the first review of the portfolio", pm_dir=rt.pm_dir, origin="paper", budget="standard")["case_id"]


def _review(con, cid, outcome, at):
    con.execute("INSERT INTO hq_case_reviews VALUES (?,?,?,?,?,?)", [store.next_id(con, "hq_case_reviews", "review_id"), cid, at, "{}", outcome, "notes of the reviewer"])


def _ctx(rt, role="quant", tid=None):
    return tl.Ctx(rt, 1, "m", False, {}, None, NOW, role=role, task_id=tid)


REASONS = "The book is mostly shares today. Gold has protected it in falls, a foreign index adds a different economy, and cash lets the team wait for prices it set from calculations."


def test_the_target_is_proposed_by_the_team_and_active_only_after_the_independent_review(con, rt, tmp_path):
    _reseed(con, tmp_path)
    assert allocation.review_due(con, NOW)["due"] and allocation.review_due(con, NOW)["first"]                                      # the first review proposes the first target
    assert allocation.reasons(con, NOW) and "no allocation target" in allocation.reasons(con, NOW)[0]
    cid = _mission(con, rt)
    args = {"equity_pct": 60, "gold_pct": 15, "international_pct": 15, "cash_pct": 10, "sectors": "IT:20, Banks:15", "reasons": REASONS, "case_id": cid}
    out = tl.TOOLS["propose_allocation"].fn(_ctx(rt), args)
    assert out["stored"] and out["status"] == "proposed" and allocation.active_target(con) is None
    assert not allocation.review_due(con, NOW)["due"]                                                                                # in flight: waiting for the review
    allocation.settle(con, NOW)
    assert allocation.active_target(con) is None                                                                                      # the mission has not finished
    _review(con, cid, "approve", NOW + timedelta(hours=1))
    con.execute("UPDATE hq_missions SET state='done' WHERE case_id=?", [cid])
    assert allocation.settle(con, NOW + timedelta(hours=2))[0]["status"] == "active"
    act = allocation.active_target(con)
    assert act["classes"] == {"equity": 60.0, "gold": 15.0, "international": 15.0, "cash": 10.0} and act["sectors"] == {"IT": 20.0, "Banks": 15.0}
    assert act["review_due"] == (NOW + timedelta(hours=2)).date() + timedelta(days=7) and act["verdict"] == "approve"
    assert allocation.settle(con, NOW + timedelta(hours=3)) == []                                                                    # idempotent
    # the weekly review re-examines it
    assert not allocation.review_due(con, NOW + timedelta(days=3))["due"] and allocation.review_due(con, NOW + timedelta(days=8))["due"]
    again = allocation.propose_allocation(con, {"equity": 60, "gold": 15, "international": 15, "cash": 10}, REASONS + " Re-examined: nothing changed.", NOW + timedelta(days=8),
                                          sectors={"IT": 20, "Banks": 15})
    assert again["reaffirmed"] and allocation.active_target(con)["review_due"] == (NOW + timedelta(days=15)).date()


def test_a_rejected_or_revised_target_never_becomes_active_and_a_new_one_supersedes_the_old(con, rt, tmp_path):
    _reseed(con, tmp_path)
    cid = _mission(con, rt)
    a = allocation.propose_allocation(con, {"equity": 90, "gold": 0, "international": 0, "cash": 10}, REASONS, NOW, case_id=cid)
    _review(con, cid, "reject", NOW + timedelta(hours=1))
    con.execute("UPDATE hq_missions SET state='done' WHERE case_id=?", [cid])
    assert allocation.settle(con, NOW + timedelta(hours=2))[0]["status"] == "reviewed"
    assert allocation.active_target(con) is None and a["target_id"] == 1
    cid2 = missions.create(con, NOW + timedelta(days=1), "Paper portfolio: weekly review of the allocation", pm_dir=rt.pm_dir, origin="paper", budget="standard")["case_id"]
    b = allocation.propose_allocation(con, {"equity": 70, "gold": 10, "international": 10, "cash": 10}, REASONS, NOW + timedelta(days=1), case_id=cid2)
    c = allocation.propose_allocation(con, {"equity": 65, "gold": 15, "international": 10, "cash": 10}, REASONS, NOW + timedelta(days=1), case_id=cid2)      # revised inside the mission
    assert con.execute("SELECT status FROM system_allocation_s79 WHERE target_id=?", [b["target_id"]]).fetchone()[0] == "superseded"
    _review(con, cid2, "approve", NOW + timedelta(days=1, hours=1))
    con.execute("UPDATE hq_missions SET state='done' WHERE case_id=?", [cid2])
    allocation.settle(con, NOW + timedelta(days=1, hours=2))
    assert allocation.active_target(con)["target_id"] == c["target_id"]
    d = allocation.propose_allocation(con, {"equity": 50, "gold": 20, "international": 20, "cash": 10}, REASONS, NOW + timedelta(days=9))
    allocation.review_target(con, d["target_id"], "approved", "the reviewer agrees", NOW + timedelta(days=9))
    assert allocation.active_target(con)["target_id"] == d["target_id"]
    assert con.execute("SELECT status FROM system_allocation_s79 WHERE target_id=?", [c["target_id"]]).fetchone()[0] == "superseded"


def test_only_the_paper_teams_quant_and_coordinator_may_propose_and_the_rails_refuse(con, rt, tmp_path):
    _reseed(con, tmp_path)
    cid = _mission(con, rt)
    args = {"equity_pct": 60, "gold_pct": 15, "international_pct": 15, "cash_pct": 10, "reasons": REASONS, "case_id": cid}
    assert "only the coordinator and the quant" in tl.TOOLS["propose_allocation"].fn(_ctx(rt, "review"), args)["problem"]
    assert "only the coordinator and the quant" in tl.TOOLS["propose_allocation"].fn(_ctx(rt, "research"), args)["problem"]
    assert "paper-portfolio mission" in tl.TOOLS["propose_allocation"].fn(_ctx(rt), {**args, "case_id": 999})["problem"]
    over = tl.TOOLS["propose_allocation"].fn(_ctx(rt), {**args, "equity_pct": 80})
    assert over["stored"] is False and "100%" in over["problem"]
    sec = tl.TOOLS["propose_allocation"].fn(_ctx(rt), {**args, "sectors": "IT:30"})
    assert sec["stored"] is False and "25%" in sec["problem"]
    assert "propose_allocation" in tl.WORKER_ONLY and tl.validate(tl.TOOLS["propose_allocation"], {k: v for k, v in args.items() if k != "case_id"}) is None
    assert con.execute("SELECT count(*) FROM system_allocation_s79").fetchone()[0] == 0


def test_the_read_tool_answers_with_no_arguments_before_and_after_a_target(con, rt, tmp_path):
    assert tl.TOOLS["system_allocation"].kind == "read" and "system_allocation" in tl.TOOLS
    out = tl.TOOLS["system_allocation"].fn(_ctx(rt), {})                                                                              # before any re-seed: harmless, never raises
    assert isinstance(out, dict) and out["active"] is None
    _reseed(con, tmp_path)
    out = tl.TOOLS["system_allocation"].fn(_ctx(rt), {})
    assert out["active"] is None and "ALLOCATION" in out["playbook"] and out["review"]["due"]
    t = allocation.propose_allocation(con, {"equity": 40, "gold": 10, "international": 5, "cash": 45}, REASONS, NOW, sectors={"IT": 10})
    allocation.review_target(con, t["target_id"], "approve", "ok", NOW)
    out = tl.TOOLS["system_allocation"].fn(_ctx(rt), {})
    assert out["active"]["target_id"] == t["target_id"] and out["drift"]["classes"] and out["gaps"]["trim"][0]["name"] == "cash"
    assert out["review"]["due_on"] == str(NOW.date() + timedelta(days=7)) and "not the investor" in out["how"]
    text = allocation.dossier_text(con, SEED_DAY)
    assert "ITS OWN ALLOCATION TARGET" in text and "TRIM cash" in text and "paper_decide" in text
    assert "ITS OWN ALLOCATION TARGET" in manager.dossier_text(con, _mission(con, rt), NOW)                                           # the team reads it first
    assert allocation.playbook_text().count("propose_allocation") >= 1


# --- ETFs of any kind -------------------------------------------------------------------------------------------------------------------

def test_gold_index_and_international_etfs_may_be_bought_inside_the_etf_rail(con, rt, tmp_path):
    _reseed(con, tmp_path)
    total = book.holdings(con, SEED_DAY)["value"]
    for isin, held in ((GOLD, 200 * 58.0), (NDQ, 52 * 130.0)):
        assert rails.buy_room(con, isin, SEED_DAY) == pytest.approx(rails.MAX_ETF * total - held, abs=0.01) and rails.buy_room(con, isin, SEED_DAY) > 0
    assert rails.buy_room(con, SGB, SEED_DAY) == 0.0                                                                                  # an SGB cannot be bought (rail kept)
    cid = _mission(con, rt)
    r = manager.decide(con, NOW, cid, {"action": "BUY", "symbol": "NDQETF", "amount_rupees": 90_000, "reason": "a foreign index adds a different economy to a book of Indian shares",
                                         "alternatives": "keep the cash; buy a gold ETF instead"})
    assert r["stored"] and r["amount_rupees"] == pytest.approx(90_000)
    big = manager.decide(con, NOW, cid, {"action": "BUY", "symbol": "GOLDETF", "amount_rupees": 400_000, "reason": "gold has protected the book in earlier falls, so more of it is wanted",
                                           "alternatives": "keep the cash; buy the international ETF"})
    assert big["stored"] and big["amount_rupees"] < 400_000 and "the rails" in big["sized"]                                          # cut to the 35% ETF rail
    oid = book.place(con, NOW, r["decision_id"], NDQ, "buy", amount=90_000)
    con.execute("UPDATE paper_orders SET placed_at=? WHERE order_id=?", [datetime(2026, 11, 6, 10), oid])
    done = book.fill(con, date(2026, 11, 9), datetime(2026, 11, 9, 18))
    assert len(done) == 1 and abs(book.positions(con)[NDQ] - (52 + 90_000 // 130)) < 1e-9 and funds.broker_cash(con) < 500_000


def test_an_etf_not_in_the_master_or_without_a_close_still_cannot_be_bought(con, tmp_path):
    _reseed(con, tmp_path)
    assert rails.buy_room(con, "INF000Q01099", SEED_DAY) == 0.0
    _inst(con, "INF000Q01099", "etf", "REVIEW", "NOCLOSE", "No Close ETF")
    assert rails.buy_room(con, "INF000Q01099", SEED_DAY) == 0.0
