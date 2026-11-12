"""S83 L3 (the strategist names stocks), L8 (the first picks) and the US side of the picks. A scripted fake model stands in for Opus (rule 7: no real data, no paid call)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from pflab.core import card, pick_share, picks, picks_card
from pflab.lab import first_session_s82 as first
from pflab.lab import service as lab
from pflab.lab import strategist, tools
from tests.test_s82_fills import _api_cfg, paid, scripted, tick, Msg  # noqa: F401  (fixtures and helpers)
from tests.test_s83_picks import BRK, CCC, NOW, START, TEXT, con, item, step  # noqa: F401  (the fixture: a small book with prices)


def ctx_for(con, tmp_path, now=NOW, sid=7):
    return tools.make_ctx(con, tmp_path, tmp_path, now, sid)


def score_five(con, market="IN"):
    """Five picks of the market with a one-month score each (the table of the score agent)."""
    for i in range(1, 6):
        con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, state, proposed_on) VALUES (?, ?, ?, ?, 'system', 'held', ?)", [500 + i, market, f"Y{i}", f"Y{i}", START])
        con.execute("INSERT INTO pick_scores_s83 (score_id, kind, ref_id, market, isin, horizon_months, excess_pct, return_pct, index_return_pct) VALUES (?, 'pick', ?, ?, ?, 1, 1.5, 3.0, 1.5)",
                    [800 + i, 500 + i, market, f"Y{i}"])


LEARNED = "My momentum-only picks lagged the index at one month, so I now ask for a margin trend and a clean balance sheet before I name a stock."


# --- the tools --------------------------------------------------------------------------------------------------------------------------------

def test_the_three_picks_tools_are_registered_short_and_take_no_size_price_or_weight():
    defs = {d["name"]: d for d in tools.definitions()}
    for n in ("propose_picks", "withdraw_pick", "skip_idea", "write_note"):
        assert n in defs and len(defs[n]["description"]) <= 480, (n, len(defs[n]["description"]))
    blob = json.dumps([defs[n]["input_schema"] for n in ("propose_picks", "withdraw_pick", "skip_idea")]).lower()
    for word in ("size", "price", "weight", "amount", "quantity", "qty", "percent", "share_of"):
        assert word not in blob, word
    assert set(defs["propose_picks"]["input_schema"]["properties"]) == {"market", "items", "learned_from"}
    assert set(defs["propose_picks"]["input_schema"]["properties"]["items"]["items"]["properties"]) == {"symbol", "thesis", "break_condition", "storylines", "takes_from"}
    assert len(tools.definitions()) <= 22
    assert all(len(d["description"]) < 480 for d in tools.definitions())


def test_propose_withdraw_and_skip_are_thin_wrappers_and_refusals_come_back_in_plain_words(con, tmp_path):
    ctx = ctx_for(con, tmp_path)
    text, err = tools.run(ctx, "propose_picks", {"market": "IN", "items": [{"symbol": "CCC", "thesis": TEXT, "break_condition": BRK, "storylines": []},
                                                                             {"symbol": "NOSUCH", "thesis": TEXT, "break_condition": BRK}]})
    out = json.loads(text)
    assert not err and out["ok"] and [a["symbol"] for a in out["accepted"]] == ["CCC"] and "not a listed share" in out["refused"][0]["reason"]
    row = con.execute("SELECT session_ref, source, state FROM picks_s83 WHERE symbol='CCC'").fetchone()
    assert row == ("strategist session 7", "system", "proposed") and ctx.stats["picks"] == 1
    text, err = tools.run(ctx, "propose_picks", {"market": "IN", "items": [{"symbol": "NOSUCH", "thesis": TEXT, "break_condition": BRK}]})
    out = json.loads(text)
    assert err and out["ok"] is False and "NOSUCH" in out["problem"] and "not a listed share" in out["problem"]
    text, err = tools.run(ctx, "propose_picks", {"market": "XX", "items": [item("CCC")]})
    assert err and "IN or US" in json.loads(text)["problem"]
    text, err = tools.run(ctx, "propose_picks", {"market": "IN", "items": []})
    assert err and "at least one" in json.loads(text)["problem"]
    text, err = tools.run(ctx, "skip_idea", {"market": "IN", "symbol": "DDD", "why": "too thin a story to hold for a year"})
    assert not err and json.loads(text)["ok"] and ctx.stats["skips"] == 1
    assert con.execute("SELECT symbol, session_ref FROM skips_s83").fetchone() == ("DDD", "strategist session 7")
    text, err = tools.run(ctx, "skip_idea", {"market": "IN", "symbol": "DDD", "why": "no"})
    assert err and "why you skipped" in json.loads(text)["problem"]
    text, err = tools.run(ctx, "withdraw_pick", {"market": "IN", "symbol": "CCC", "reason": "the margin trend I leaned on has turned down for two quarters"})
    assert not err and json.loads(text)["held"] is False
    assert con.execute("SELECT state FROM picks_s83 WHERE symbol='CCC'").fetchone()[0] == "withdrawn"
    text, err = tools.run(ctx, "withdraw_pick", {"market": "IN", "symbol": "ZZZ", "reason": "the margin trend I leaned on has turned down"})
    assert err and "not an active pick" in json.loads(text)["problem"]


def test_once_five_picks_have_a_score_the_batch_and_the_note_must_say_what_was_learned(con, tmp_path):
    ctx = ctx_for(con, tmp_path)
    ok = json.loads(tools.run(ctx, "write_note", {"text": "Looked at the book; nothing to change this week and no pick named."})[0])
    assert ok["ok"] and con.execute("SELECT learned FROM core_notes_s80").fetchone()[0] is None          # not needed yet
    score_five(con)
    assert picks.needs_learned(con, "IN") and not picks.needs_learned(con, "US")
    text, err = tools.run(ctx, "propose_picks", {"market": "IN", "items": [item("CCC")], "learned_from": "too short"})
    out = json.loads(text)
    assert err and "scorecard" in out["problem"] and "40" in out["problem"] and con.execute("SELECT count(*) FROM picks_s83 WHERE symbol='CCC'").fetchone()[0] == 0
    text, err = tools.run(ctx, "write_note", {"text": "A note that forgets the part about what the scorecard taught."})
    assert err and "learned" in json.loads(text)["problem"]
    text, err = tools.run(ctx, "write_note", {"text": "A note with the part about the scorecard.", "learned": "short"})
    assert err
    ok = json.loads(tools.run(ctx, "propose_picks", {"market": "IN", "items": [item("CCC")], "learned_from": LEARNED})[0])
    assert ok["ok"] and con.execute("SELECT learned_from FROM picks_s83 WHERE symbol='CCC'").fetchone()[0] == LEARNED
    ok = json.loads(tools.run(ctx, "write_note", {"text": "A note with the part about the scorecard.", "learned": LEARNED})[0])
    assert ok["ok"]
    assert lab.last_learned(con)["learned"] == LEARNED and lab.notes(con, 1)[0]["learned"] == LEARNED


# --- the session: a scripted model through the real run_session, llm.call, governor and egress ---------------------------------------------------

class Script:
    """Each create() call returns the next scripted turn: a list of (tool, input) pairs, or the text 'Done.'. The first request's first user message is kept."""
    def __init__(self, turns):
        self.turns, self.n, self.first = list(turns), 0, None
        self.messages = SimpleNamespace(count_tokens=lambda **k: SimpleNamespace(input_tokens=3000))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **p):
        if self.first is None:
            self.first = p["messages"][0]["content"][0]["text"]
            self.system = p["system"][0]["text"]
        t = self.turns[min(self.n, len(self.turns) - 1)] if self.n < len(self.turns) else None
        self.n += 1
        if t is None:
            return Msg([SimpleNamespace(type="text", text="Done.")])
        blocks = [SimpleNamespace(type="tool_use", id=f"tu{self.n}_{i}", name=name, input=inp) for i, (name, inp) in enumerate(t)]
        return Msg(blocks, "tool_use")


def test_a_session_reads_the_scorecard_names_stocks_records_skips_and_is_not_wasted(con, tmp_path, paid):
    cl = Script([[("propose_picks", {"market": "IN", "items": [{"symbol": "CCC", "thesis": TEXT, "break_condition": BRK, "storylines": []}]}),
                  ("skip_idea", {"market": "IN", "symbol": "DDD", "why": "a story I could not tie to results in two quarters"})],
                 [("write_note", {"text": "First picks: named CCC for its steady margins; skipped DDD for want of a story."}), ("finish", {"summary": "named one pick, skipped one"})]])
    s = strategist.run_session(con, tmp_path, tmp_path, NOW, "the weekly session (re-examine the allocation)", client=cl, data={}, box=None)
    assert s["status"] == "done" and s["picks"] == 1 and s["skips"] == 1 and s["lab_runs"] == 0, s          # picks work is not a wasted session
    assert "PICKS SCORE" in cl.first and "PICKS, India" in cl.first and "share is 40%" in cl.first         # the scorecard and the sleeve are in the first message
    assert "PICKS, US" in cl.first and "propose_picks" in cl.system and "you never write a size, a price or a weight" in cl.system
    assert "do not pick stocks by hand" not in cl.system
    assert con.execute("SELECT symbol, session_ref FROM picks_s83 WHERE source='system'").fetchall() == [("CCC", f"strategist session {s['session_id']}")]
    assert lab.latest_strategist_note(con)["note"].startswith("First picks")


def test_a_session_with_no_picks_and_no_lab_run_is_still_wasted(con, tmp_path, paid):
    cl = Script([[("write_note", {"text": "Nothing was done this week at all, honestly."}), ("finish", {"summary": "nothing"})]])
    s = strategist.run_session(con, tmp_path, tmp_path, NOW, "the weekly session (re-examine the allocation)", client=cl, data={}, box=None)
    assert s["status"] == "wasted"


# --- the card's PICKS section -------------------------------------------------------------------------------------------------------------------

def test_the_picks_section_has_each_pick_the_share_and_why_and_the_last_learned(con, tmp_path):
    picks.adopt_kite_holdings(con, NOW)
    out = picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s1")
    pid = out["accepted"][0]["pick_id"]
    con.execute("INSERT INTO pick_scores_s83 (score_id, kind, ref_id, market, isin, horizon_months, excess_pct, return_pct, index_return_pct) VALUES (1, 'pick', ?, 'IN', 'x', 3, 2.5, 6.0, 3.5)", [pid])
    lab.write_note(con, NOW, 3, "A note about the week with enough words in it.", learned=LEARNED)
    named = picks_card.build(con, START + timedelta(days=10))                                                    # S84 F3: named and not bought: no record yet
    assert "named, not yet held" in named["text"] and next(p for p in named["IN"]["picks"] if p["symbol"] == "CCC")["vs_index"] is None
    con.execute("INSERT INTO paper_trades VALUES (900, ?, NULL, NULL, ?, 'CCC', 'buy', 10, 100.0, 1.0, NULL, NULL, '{}')", [START + timedelta(days=1), CCC])     # its first fill: the record starts
    b = picks_card.build(con, START + timedelta(days=10))
    inb = b["IN"]
    assert inb["share"] == 0.40 and "starting share" in inb["share_why"] and inb["on"]
    ccc = next(p for p in inb["picks"] if p["symbol"] == "CCC")
    assert ccc["state"] == "proposed" and ccc["days_held"] == 10 and ccc["vs_index"]["excess_pct"] == 2.5 and ccc["break_condition"] == BRK
    kite = [p for p in inb["picks"] if p["source"] == "kite"]
    assert kite and all("Kite" in picks_card._market_text(inb) for _ in kite[:1]) and kite[0]["vs_index"] is None
    assert 0.0 <= inb["room"] <= 0.40
    assert "+2.5 points against the index at 3 month(s)" in b["text"] and "not scored yet" in b["text"] and "Breaks if:" in b["text"] and "WHAT I LEARNED" in b["text"] and "margin trend" in b["text"]
    assert b["learned"]["learned"] == LEARNED
    json.dumps({k: v for k, v in b.items() if k != "text"}, default=str)                                       # JSON-able


def test_the_book_card_carries_the_picks_section_in_text_and_json(con):
    picks.adopt_kite_holdings(con, NOW)
    step(con, date(2026, 11, 2))
    row = con.execute("SELECT text, facts_json FROM core_cards_s80 ORDER BY day DESC LIMIT 1").fetchone()
    assert "PICKS, India" in row[0] and "WHAT I LEARNED (last note): nothing written yet" in row[0]
    facts = json.loads(row[1])
    assert facts["picks"]["IN"]["share"] == 0.40 and facts["picks"]["learned"] is None and "text" not in facts["picks"]


# --- L8: the first picks -----------------------------------------------------------------------------------------------------------------------------

def test_the_first_session_and_the_first_picks_are_one_session_and_both_keys_move_together(con, tmp_path, scripted, monkeypatch):
    monkeypatch.setattr(strategist, "due", lambda c, n: [])
    now = datetime(2026, 11, 12, 10, 0)
    out = tick(con, tmp_path, now)
    assert scripted["n"] == 1 and out["first_session_s82"] == "done"
    assert first.state(con)["status"] == "done" and first.state(con, first.KEY_PICKS)["status"] == "done" and first.state(con, first.KEY_PICKS)["session_id"] == first.state(con)["session_id"]
    assert tick(con, tmp_path, now + timedelta(days=2)).get("nothing_due") and scripted["n"] == 1
    assert first.reasons(con, now + timedelta(days=30)) == []


def test_after_the_s82_session_only_the_picks_session_runs_and_once(con, tmp_path, scripted, monkeypatch):
    monkeypatch.setattr(strategist, "due", lambda c, n: [])
    now = datetime(2026, 11, 12, 10, 0)
    first._write(con, now - timedelta(days=3), "done", "the first session ran", session_id=1, cost=10.0)             # the S82 session ran before this release
    assert first.reasons(con, now) == [first.REASON_PICKS]
    seen = []
    import pflab.lab.strategist as st
    real = st.run_session

    def spy(con_, pm, root, n, reason, **kw):
        seen.append(reason)
        return scripted_run(con_, pm, root, n, reason, **kw)
    scripted_run = strategist.run_session                                                              # the scripted stand-in from the fixture
    monkeypatch.setattr(st, "run_session", spy)
    out = tick(con, tmp_path, now)
    assert len(seen) == 1 and first.REASON_PICKS[:40] in seen[0] and first.REASON not in seen[0] and out["first_session_s82"] == "done"
    assert tick(con, tmp_path, now + timedelta(days=1)).get("nothing_due")
    assert first.state(con)["attempts"] == 1                                                              # the S82 key was not touched again
    del real


def test_his_kite_stocks_are_adopted_at_that_first_open(con, tmp_path, scripted, monkeypatch):
    monkeypatch.setattr(strategist, "due", lambda c, n: [])
    assert con.execute("SELECT count(*) FROM picks_s83").fetchone()[0] == 0
    tick(con, tmp_path, datetime(2026, 10, 30, 10, 0))
    assert con.execute("SELECT count(*) FROM picks_s83 WHERE source='kite' AND state='held'").fetchone()[0] == 3
    assert picks.adopt_kite_holdings(con, datetime(2026, 10, 30, 10, 0)) == []                            # idempotent


def test_no_client_or_no_cap_room_says_no_picks_yet_and_never_raises(con, tmp_path, scripted, monkeypatch):
    from pflab.agents import analyst as an
    monkeypatch.setattr(strategist, "due", lambda c, n: [])
    now = datetime(2026, 11, 12, 10, 0)
    assert first.picks_line(con).startswith("no picks yet: the first picks session has not run")

    def no_key():
        raise RuntimeError("no API key in secrets.toml")
    out = tick(con, tmp_path, now, client_fn=no_key)
    assert "no cloud client" in out["skipped"] and scripted["n"] == 0
    line = first.picks_line(con)
    assert line.startswith("no picks yet: waiting: no cloud client") and "his Kite stocks, the core and SPY" in line
    assert first.state(con)["status"] == "waiting" and first.state(con, first.KEY_PICKS)["status"] == "waiting"
    monkeypatch.setattr(an, "config", lambda path=None: _api_cfg(cap=0.0))
    out = tick(con, tmp_path, now + timedelta(days=1))
    assert "no paid cap" in out["first_session_s82"] and scripted["n"] == 0
    assert "no picks yet: waiting: no paid cap" in first.picks_line(con)
    ex = card.today_extras(con)
    assert ex["picks"]["line"].startswith("no picks yet") and ex["picks"]["IN"]["share"] == 0.40


def test_a_failed_first_picks_session_leaves_the_book_as_it_is_and_stops_after_two_paid_failures(con, tmp_path, paid, monkeypatch):
    monkeypatch.setattr(strategist, "due", lambda c, n: [])
    monkeypatch.setattr(strategist, "run_session", lambda con_, *a, **k: {"session_id": 9, "status": "failed", "cost_inr": 3.0})
    before = con.execute("SELECT count(*) FROM picks_s83 WHERE source='system'").fetchone()[0]
    for k in range(4):
        tick(con, tmp_path, datetime(2026, 11, 12, 10, 0) + timedelta(days=k))
    assert first.state(con, first.KEY_PICKS)["paid_attempts"] == 2 and con.execute("SELECT count(*) FROM picks_s83 WHERE source='system'").fetchone()[0] == before
    assert "failed 2 times" in first.picks_line(con)


def test_once_the_system_has_a_pick_the_no_picks_line_goes_away(con):
    picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s1")
    assert first.picks_line(con) is None


# --- the US sub-book holds picked stocks: SPY never under 30%, a stock at most 10%, at most 12 stocks ------------------------------------------------

@pytest.fixture
def ucon(tmp_path, monkeypatch):
    from pflab.pm import store
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "data"))
    c = store.connect(tmp_path / "u.duckdb")
    c.execute("INSERT INTO fx_rates VALUES (?, 'USDINR_FBIL', 90.0, 'test')", [date(2026, 10, 28)])
    return c


UDAYS = [d.date() for d in pd.bdate_range("2026-08-03", "2026-11-06")]


def write_bars(tmp_path, sym, base, drift=0.001, volume=1_000_000.0):
    p = tmp_path / "data" / "us" / "raw"
    p.mkdir(parents=True, exist_ok=True)
    rows = []
    for k, d in enumerate(UDAYS):
        c = base * (1 + drift) ** k * (1 + (0.01 if k % 2 else -0.01) * (1 + len(sym) % 3))
        rows.append((d, c - 0.3, c + 0.5, c - 0.5, c, c, volume, 0.0))
    pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "adj_close", "volume", "dividend"]).to_parquet(p / f"{sym}.parquet")


def us_setup(ucon, tmp_path, stocks=("STKA",)):
    for d in [date(2026, 10, 30)] + UDAYS:
        ucon.execute("INSERT INTO fx_rates VALUES (?, 'USDINR_FBIL', 90.0, 'test') ON CONFLICT DO NOTHING", [d])
    ucon.execute("INSERT INTO paper_cash VALUES (?,?,?,?,?,?)", [1, date(2026, 10, 1), 2_000_000.0, "seed", "test cash", datetime(2026, 11, 3, 7, 0)])
    write_bars(tmp_path, "SPY", 100.0)
    for s in stocks:
        write_bars(tmp_path, s, 50.0)


UCFG = {"on": True, "slippage_bps": 5.0, "min_trade_usd": 10.0}


def test_a_us_pick_is_bought_beside_spy_and_spy_stays_at_least_30_percent(ucon, tmp_path):
    from pflab.us import adapter, book, picks_wire
    us_setup(ucon, tmp_path)
    assert pick_share.on("US"), "[picks.us] on is true in configs/core.toml"
    out = picks.propose(ucon, datetime(2026, 11, 3, 7, 0), "US", [item("STKA")], session_ref="s1")
    assert [a["symbol"] for a in out["accepted"]] == ["STKA"], out
    adapter.close_us(ucon, datetime(2026, 11, 3, 7, 0), tmp_path / "data", UCFG)                         # the first session: the account opens, buys are ordered
    sides = {r[0]: r[1] for r in ucon.execute("SELECT symbol, side FROM us_orders_s81").fetchall()}
    assert sides == {"SPY": "buy", "STKA": "buy"}
    adapter.close_us(ucon, datetime(2026, 11, 4, 7, 0), tmp_path / "data", UCFG)                         # the orders fill at the next open
    pos = book.positions(ucon, date(2026, 11, 3))
    assert len(pos) == 2
    row = ucon.execute("SELECT value_usd, holdings_json FROM us_days_s81 ORDER BY day DESC LIMIT 1").fetchone()
    h = json.loads(row[1])
    w = {k: v["value_usd"] / row[0] for k, v in h.items()}
    stka = next(v for k, v in w.items() if k != "SPY" and "SPY" not in k and v < 0.2)
    assert 0.03 < stka <= 0.10 + 1e-9                                                                    # on its way to the 10% stock rail (the sub-book is funded in tranches: bought gradually)
    reasons = [r[0] for r in ucon.execute("SELECT reason FROM us_orders_s81 WHERE symbol IN ('SPY', 'STKA') ORDER BY order_id").fetchall()]
    assert any("SPY" not in r and "target 10.0%" in r for r in reasons[:2]) and any("target 85.0%" in r for r in reasons[:2])
    spy = max(w.values())
    assert spy >= 0.30
    assert ucon.execute("SELECT state FROM picks_s83 WHERE symbol='STKA'").fetchone()[0] in ("buying", "held")
    run_note = ucon.execute("SELECT note FROM us_runs_s81 ORDER BY day DESC LIMIT 1").fetchone()[0]
    assert "core: SPY" in run_note
    assert picks_wire.symbols(ucon) == ["STKA"]


def test_the_picks_total_is_held_so_that_spy_keeps_its_floor_and_a_withdrawn_pick_is_sold(ucon, tmp_path):
    from pflab.us import data, picks_wire, policy
    us_setup(ucon, tmp_path, stocks=tuple(f"S{i:02d}" for i in range(12)))
    now = datetime(2026, 11, 9, 7, 0)
    out = picks.propose(ucon, now, "US", [item(f"S{i:02d}") for i in range(12)], session_ref="s1")
    assert len(out["accepted"]) == 12, out["refused"]
    extra = picks.propose(ucon, now, "US", [item("S12")], session_ref="s1")
    assert extra["accepted"] == [] and extra["refused"]                                                   # a 13th stock is refused (bars missing too, but the count says it)
    syms = picks_wire.symbols(ucon)
    bars = data.load(["SPY"] + syms, tmp_path / "data")
    ucon.execute("INSERT INTO us_account_s81 VALUES (1, ?, 1.0, 90.0, 'FBIL', 10000.0, 0.10, 'test', ?)", [date(2026, 11, 2), now])
    from pflab.us import book
    book.add_cash(ucon, now, date(2026, 11, 2), 10_000.0, "transfer", "test")
    ucon.execute("INSERT INTO us_days_s81 VALUES (?,?,?,?,?,?,?)", [date(2026, 11, 2), 10_000.0, 10_000.0, 90.0, "FBIL", 900_000.0, "{}"])
    st = picks.attach(ucon, policy.build(ucon, date(2026, 11, 6), bars, UCFG, tmp_path / "data", now, pick_syms=syms), "US")
    pw = picks_wire.extra_weights(ucon, st)
    total = sum(pw["extra"].values())
    assert len(pw["extra"]) == 12 and all(v <= 0.10 + 1e-9 for v in pw["extra"].values())
    assert total <= 0.95 - 0.30 + 1e-9 and pw["core_total"] >= 0.30 - 1e-9                                 # SPY's target is never under the 30% floor
    dec = policy.decide(st, extra=pw["extra"], core_total=pw["core_total"])
    spy_key = next(r["isin"] for r in st["rows"] if r["symbol"] == "SPY")
    assert dec["weights"][spy_key] >= 0.30 - 1e-9 and sum(dec["weights"].values()) <= 0.95 + 1e-9
    # a withdrawn pick that is held gets a target of zero
    k = next(r["isin"] for r in st["rows"] if r["symbol"] == "S00")
    ucon.execute("UPDATE picks_s83 SET state='withdrawn' WHERE symbol='S00'")
    ucon.execute("INSERT INTO us_lots_s81 VALUES (1, ?, 'S00', ?, 20.0, 50.0, 90.0, 'FBIL', 'fill')", [k, date(2026, 11, 2)])
    st = picks.attach(ucon, policy.build(ucon, date(2026, 11, 6), bars, UCFG, tmp_path / "data", now, pick_syms=syms), "US")
    pw = picks_wire.extra_weights(ucon, st)
    assert pw["extra"]["S00"] == 0.0 and any("withdrawn pick is sold" in n for n in pw["notes"])


def test_with_no_picks_the_us_decision_is_what_it_was(ucon, tmp_path):
    from pflab.us import data, picks_wire, policy
    us_setup(ucon, tmp_path, stocks=())
    bars = data.load(["SPY"], tmp_path / "data")
    st = policy.build(ucon, date(2026, 11, 6), bars, UCFG, tmp_path / "data", datetime(2026, 11, 9, 7, 0))
    st["value"] = st["cash"] = 1000.0
    assert picks_wire.extra_weights(ucon, st) == {"extra": {}, "core_total": 0.95, "notes": []}
    dec = policy.decide(st)
    assert list(dec["weights"].values()) == [pytest.approx(0.95)]


# --- L6: the longterm share is the picks rule's ---------------------------------------------------------------------------------------------------

def test_the_baselines_longterm_share_is_the_picks_rule_and_core_is_what_is_left(con):
    from pflab import core
    from pflab.core import sleeves
    sh = sleeves.target_shares(con, core.settings(), None)
    assert sh["longterm"] == pytest.approx(0.40) and sh["core"] == pytest.approx(0.60) and sh["index"] == pytest.approx(0.40) and "picks rule" in sh["source"]
    con.execute("INSERT INTO sleeve_share_s83 (change_id, market, decided_on, old_share, new_share, reason, figures_json) VALUES (1, 'IN', ?, 0.40, 0.45, 'ahead of the index', '{}')", [START])
    sh = sleeves.target_shares(con, core.settings(), None)
    assert sh["longterm"] == pytest.approx(0.45) and sh["core"] == pytest.approx(0.55) and sh["index"] == pytest.approx(0.35) and sh["gold"] == pytest.approx(0.10)
    assert sh["international"] == pytest.approx(0.10)
    s = step(con, date(2026, 11, 2))
    assert s is not None


def test_a_proposal_that_changes_the_longterm_share_is_taken_for_the_rest_and_told_so(con, tmp_path):
    ctx = ctx_for(con, tmp_path)
    args = {"classes": {"equity": 85, "gold": 10, "international": 0, "cash": 5}, "sleeves": {"core": 50, "longterm": 50}, "sectors": {},
            "reasons": "Put the idle cash into the index and keep a gold slice for a crash; the longterm share is whatever the picks rule says."}
    text, err = tools.run(ctx, "propose_allocation", args)
    out = json.loads(text)
    assert not err and out["ok"], out
    assert "set by the picks rule" in out["longterm_share"] and "stays at 40%" in out["longterm_share"]
    assert out["sleeves"] == {"core": 60.0, "longterm": 40.0}
    again = json.loads(tools.run(ctx, "propose_allocation", {**args, "sleeves": {"core": 60, "longterm": 40}, "classes": {"equity": 84, "gold": 10, "international": 1, "cash": 5}})[0])
    assert again["ok"] and "longterm_share" not in again                                              # the live share asked for: nothing to tell


# --- L6: the index fallback leaves the picks alone; a variant is judged at the live picks share ---------------------------------------------------------

def test_the_index_fallback_changes_neither_picks_sleeve_nor_their_positions(con):
    from pflab.lab import alloc_lab
    from pflab.paper import allocation, book
    from pflab.us import book as usbook
    picks.adopt_kite_holdings(con, NOW)
    picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s1")
    for i, (k, sym) in enumerate((("ZZ0000000011", "USA"), ("ZZ0000000012", "USB"))):                                   # two held US picks in the sub-book
        con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, thesis, break_condition, storylines_json, state, proposed_on, state_changed_on) "
                    "VALUES (?, 'US', ?, ?, 'system', ?, ?, '[]', 'held', ?, ?)", [300 + i, k, sym, TEXT, BRK, START, START])
        con.execute("INSERT INTO us_lots_s81 VALUES (?, ?, ?, ?, 5.0, 50.0, 90.0, 'FBIL', 'fill')", [i + 1, k, sym, START])
    snap = lambda: (con.execute("SELECT * FROM picks_s83 ORDER BY pick_id").fetchall(), {k: round(v, 6) for k, v in book.positions(con).items()}, usbook.positions(con, START),
                    con.execute("SELECT count(*) FROM paper_orders").fetchone()[0], pick_share.share(con, "IN")["share"], pick_share.share(con, "US")["share"])
    before = snap()
    out = alloc_lab.adopt_index_only(con, datetime(2026, 11, 2, 9, 0), "after tax and charges the current allocation fails the index rule; holding the index passes it")
    assert out["adopted"], out
    res = alloc_lab.rescope_old_index_only(con, datetime(2026, 11, 2, 9, 5))
    assert res == {"rescoped": False} or res.get("rescoped") in (True, False)
    assert snap() == before                                                                                  # both picks sleeves, their positions and their shares are untouched
    sl = json.loads(con.execute("SELECT sleeves_json FROM allocation_sleeves_s81 WHERE target_id=?", [out["target_id"]]).fetchone()[0])
    assert sl["longterm"] == pytest.approx(40.0) and sl["core"] == pytest.approx(60.0)                       # the target keeps the picks rule's longterm share


def test_a_candidate_and_a_proposal_are_judged_at_the_live_picks_share(con, tmp_path):
    from pflab.lab import alloc_lab
    con.execute("INSERT INTO sleeve_share_s83 (change_id, market, decided_on, old_share, new_share, reason, figures_json) VALUES (1, 'IN', ?, 0.40, 0.45, 'ahead of the index', '{}')", [START])
    assert alloc_lab.default_params(con=con)["longterm"] == pytest.approx(0.45) and alloc_lab.default_params()["longterm"] == pytest.approx(0.40)
    assert alloc_lab.candidates(con=con)[alloc_lab.DEFAULT_ID]["params"]["longterm"] == pytest.approx(0.45)
    assert alloc_lab.index_only_params(con=con)["longterm"] == pytest.approx(0.45)
    p = alloc_lab.proposal_params({"gold": 10, "international": 0, "cash": 5}, {"core": 50, "longterm": 50}, con)
    assert p["longterm"] == pytest.approx(0.45) and p["idx"] == pytest.approx(0.55 - 0.15)                    # the asked 50 is ignored; the core is what is left
    out = alloc_lab.propose(con, tmp_path, datetime(2026, 11, 2, 9, 0), {"equity": 85, "gold": 10, "international": 0, "cash": 5}, {"core": 50, "longterm": 50},
                            "Put the idle cash into the index and keep a gold slice for a crash; the longterm share is the picks rule's.")
    assert out["ok"] and out["sleeves"]["longterm"] == pytest.approx(45.0) and "set by the picks rule" in out["longterm_share"]
