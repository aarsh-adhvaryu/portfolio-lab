"""S73: the daily loop. The monthly envelope with carry-forward (his example: Rs 50,000 a month until January, unspent carries over), the scorecard that scores each recommendation
claim by claim ("partly right" is literal), and the daily review that looks at everything standing by code. Synthetic data only."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from pflab.app import assistant, chat
from pflab.hq import daily, rules, scorecard
from pflab.plan import envelope
from pflab.service import jobs
from tests.test_s68_autonomy import AAA, NOW, con, rt  # noqa: F401  (fixtures)

TODAY = date(2026, 11, 20)


def _buy(con, d, qty, price, eid):
    con.execute("INSERT INTO events (event_id, kind, account_id, trade_date, isin, qty, price, amount, ingested_at) VALUES (?, 'buy', 'Z', ?, ?, ?, ?, ?, now())", [eid, d, AAA, qty, price, qty * price])


def _envelope(con, **machine):
    m = {"amount_rupees": 50000, "until": "2027-01-31", "carry_over": True, **machine}
    r = rules.propose(con, datetime(2026, 11, 2), "monthly_envelope", "I invest Rs 50,000 a month till January; unspent carries over", m)
    rules.decide(con, datetime(2026, 11, 2), r["rule_id"], True)
    return r


def _index(highs_then):
    """A daily index: a year of 100 rising to 120, then `highs_then`."""
    days = pd.bdate_range(end="2026-11-20", periods=300)
    v = np.linspace(100, 120, 300)
    v[-len(highs_then):] = highs_then
    return pd.Series(v, index=days)


# --- the envelope ----------------------------------------------------------------------------------------------------------------

def test_no_envelope_until_he_says_yes(con):
    r = rules.propose(con, datetime(2026, 11, 2), "monthly_envelope", "I invest Rs 50,000 a month", {"amount_rupees": 50000})
    s = envelope.status(con, TODAY)
    assert s["active"] is False and s["pending"] and "No monthly envelope" in envelope.explain(s) and "Waiting for your yes" in envelope.explain(s)
    rules.decide(con, datetime(2026, 11, 2), r["rule_id"], True)
    assert envelope.status(con, TODAY)["active"] is True


def test_unspent_money_carries_into_the_next_month(con):
    _envelope(con)
    s = envelope.status(con, date(2026, 11, 20))
    assert s["allowance_so_far"] == 50000 and s["available_now"] == 50000 and s["months_left"] == 2          # November counts; December, January to come
    s = envelope.status(con, date(2026, 12, 15))                                                              # nothing bought in November
    assert s["months_counted"] == 2 and s["allowance_so_far"] == 100000 and s["available_now"] == 100000
    _buy(con, date(2026, 12, 3), 100, 300.0, 1)                                                              # Rs 30,000 bought
    s = envelope.status(con, date(2026, 12, 15))
    assert s["bought_since_start"] == 30000 and s["bought_this_month"] == 30000 and s["available_now"] == 70000 and s["overspent_by"] == 0


def test_buying_more_than_has_been_made_available_shows_as_an_overspend(con):
    _envelope(con)
    _buy(con, date(2026, 11, 5), 400, 200.0, 1)                                                               # Rs 80,000 against Rs 50,000
    s = envelope.status(con, date(2026, 11, 20))
    assert s["available_now"] == 0 and s["overspent_by"] == 30000 and "over by Rs 30,000" in envelope.explain(s)


def test_without_carry_over_only_this_months_sum_counts(con):
    _envelope(con, carry_over=False)
    _buy(con, date(2026, 11, 5), 100, 100.0, 1)
    s = envelope.status(con, date(2026, 12, 10))
    assert s["available_now"] == 50000 and s["carry_over"] is False                                           # December is a fresh Rs 50,000; November's unspent is gone


def test_it_ends_on_the_date_he_gave(con):
    _envelope(con)
    s = envelope.status(con, date(2027, 2, 10))
    assert s["finished"] is True and s["months_counted"] == 3 and s["allowance_so_far"] == 150000


def test_only_shares_count_not_funds_or_other_instruments(con):
    _envelope(con)
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES ('INF000F01011', 'isin', 'mutual_fund', 'equity_fund', FALSE, 'FUND', 'A Fund', 'synthetic', now())""")
    con.execute("INSERT INTO events (event_id, kind, account_id, trade_date, isin, qty, price, amount, ingested_at) VALUES (9, 'buy', 'Z', ?, 'INF000F01011', 10, 5000, 50000, now())", [date(2026, 11, 6)])
    assert envelope.status(con, date(2026, 11, 20))["bought_since_start"] == 0


def test_the_dip_tranche_is_extra_money_only_while_the_market_is_far_enough_below_its_high(con):
    _envelope(con)
    r = rules.propose(con, datetime(2026, 11, 2), "dip_tranche", "An extra Rs 25,000 when the market is 10% below its high", {"extra_rupees": 25000, "below_high_pct": 10})
    rules.decide(con, datetime(2026, 11, 2), r["rule_id"], True)
    calm = envelope.status(con, TODAY, _index([119, 118, 119]))
    assert calm["dip"]["triggered"] is False and "available_now_with_dip" not in calm
    fall = envelope.status(con, TODAY, _index([110, 105, 104]))                                               # 104 against a high of 120: 13.3% below
    assert fall["dip"]["triggered"] is True and fall["available_now_with_dip"] == 75000 and "TRIGGERED" in envelope.explain(fall)
    assert envelope.status(con, TODAY, None)["dip"]["market_below_high_pct"] is None                          # no index: unknown, never assumed


# --- the scorecard ---------------------------------------------------------------------------------------------------------------

def _proposal(con, pid, action, made, price=100.0, isin=AAA):
    pay = {"action": action, "reason": "r", "price": {"value": price, "as_of": str(made.date())}}
    con.execute("INSERT INTO hq_proposals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [pid, made, made, None, action, isin, "AAA", "proposed", "reviewed", 1, "snap", "v1", json.dumps(pay), "[]", None, None])


def _closes(con, start, series):
    for i, v in enumerate(series):
        con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [AAA, start + timedelta(days=i), float(v)])


def test_a_rate_is_shown_only_from_twenty_scored_claims(con):
    def add(n, good, bad, state="pullback", action="BUY"):
        for i in range(good + bad):
            cid = con.execute("SELECT coalesce(max(claim_id), 0) + 1 FROM hq_claims").fetchone()[0]
            con.execute("INSERT INTO hq_claims (claim_id, proposal_id, isin, action, kind, made_at, ref_date, ref_close, state, horizon_days, due_on, outcome) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [cid, cid, AAA, action, "add", NOW, NOW.date(), 100.0, state, 28, NOW.date(), "good" if i < good else "bad"])
    add(0, 5, 2)
    t = scorecard.table(con)
    assert t[0]["n"] == 7 and "rate" not in t[0] and "a count, not a conclusion" in t[0]["note"]
    add(0, 14, 6, state="deep")
    deep = next(r for r in scorecard.table(con) if r["market_state"] == "deep")
    assert deep["n"] == 20 and deep["rate"] == 0.7 and deep["skeptical_rate"] < deep["rate"]                  # the skeptical rate is below the plain one
    assert scorecard.skeptical(0, 0) is not None


# --- the daily review ------------------------------------------------------------------------------------------------------------

def _rt(rt, tmp_path):
    rt.data_root = tmp_path          # no index file there: the review must cope
    return rt


def test_the_review_tells_him_once_a_day_what_stands(rt, con, tmp_path):
    _envelope(con)
    rules.propose(con, NOW, "max_position", "No holding above 8%", {"max_weight_pct": 8})
    out = daily.review(_rt(rt, tmp_path), NOW)
    assert out["told"] is True and out["lines"] >= 2
    msg = con.execute("SELECT text FROM chat_messages WHERE mode = ? ", [f"note:review:{NOW.date()}"]).fetchone()[0]
    assert "Envelope: Rs 50,000 a month" in msg and "Waiting for your yes (about money): No holding above 8%" in msg
    assert daily.review(rt, NOW)["told"] is False                                                             # the same day is not told twice


def test_a_quiet_day_says_so(rt, con, tmp_path):
    out = daily.review(_rt(rt, tmp_path), NOW)
    msg = con.execute("SELECT text FROM chat_messages WHERE mode LIKE 'note:review:%'").fetchone()[0]
    assert "Nothing needs you today" in msg and out["lines"] == 0


def test_one_part_failing_is_said_and_never_stops_the_rest(rt, con, tmp_path, monkeypatch):
    _envelope(con)
    monkeypatch.setattr(daily, "_scans", lambda r: (_ for _ in ()).throw(RuntimeError("boom")))
    out = daily.review(_rt(rt, tmp_path), NOW)
    msg = con.execute("SELECT text FROM chat_messages WHERE mode LIKE 'note:review:%'").fetchone()[0]
    assert "a part of the review failed: RuntimeError" in msg and "Envelope:" in msg and out["failed"] == ["RuntimeError"]


def test_forward_tests_are_in_the_review(rt, con, tmp_path):
    con.execute("INSERT INTO forward_months (claim, formed_on, status, formed_at) VALUES ('F1', ?, 'formed', now())", [date(2026, 10, 1)])
    con.execute("INSERT INTO forward_months (claim, formed_on, status, formed_at, settled_at) VALUES ('F1', ?, 'settled', now(), now())", [date(2026, 9, 1)])
    daily.review(_rt(rt, tmp_path), NOW)
    assert "F1 2/1" in con.execute("SELECT text FROM chat_messages WHERE mode LIKE 'note:review:%'").fetchone()[0]


# --- the schedule and the morning pass -------------------------------------------------------------------------------------------

def test_the_review_is_a_job_at_20_past_9_in_the_evening():
    from pflab.service import tasks  # noqa: F401  (importing registers the jobs)
    j = jobs.REGISTRY["review"]
    assert (j.schedule.hour, j.schedule.minute) == (21, 20)

