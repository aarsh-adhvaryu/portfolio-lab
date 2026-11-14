"""S86 the alarm lane (A73-A78): the collector's parsing and politeness, the lanes by code, the RED path (Heard line before any model, freeze, case outside the cap, decision told, four times), the
same story from several outlets, rumour then denial, a source going blind and coming back, the gap's message, the raw lines and the graph. Synthetic companies only (rule 7); a fake HTTP session
stands in for the sources, so nothing waits and nothing reaches the net."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from email.utils import format_datetime
from datetime import timezone

import pytest

from pflab.ingest import headlines as ing
from pflab.kg2 import headlines as kg
from pflab.think import alarm, cases
from tests.test_s80_core import AAA, BBB, GLD, NOW, con  # noqa: F401  (the fixture)

NAME = "Aardvark Industries"
T0 = datetime(2026, 10, 30, 11, 20)                       # a session day, 11:20 IST


@pytest.fixture(autouse=True)
def _named(con, monkeypatch, tmp_path):
    con.execute("UPDATE instruments SET name=? WHERE isin=?", [NAME + " Ltd", AAA])
    con.execute("UPDATE instruments SET name='Bobcat Holdings Ltd' WHERE isin=?", [BBB])
    monkeypatch.setattr("pflab.think.watch._index", lambda market, root=None: None)
    monkeypatch.setattr("pflab.kg2.classify.model_classify", lambda *a, **k: None)             # no real model in a test; the lane's own model hook is tested with a fake


def rss(items):
    """A Google-News-shaped RSS document from (title, outlet, published naive IST)."""
    rows = ""
    for t, o, p in items:
        utc = (p - timedelta(hours=5, minutes=30)).replace(tzinfo=timezone.utc)
        rows += f"<item><title>{t} - {o}</title><link>https://x.invalid/{abs(hash(t)) % 10 ** 8}</link><pubDate>{format_datetime(utc, usegmt=True)}</pubDate><source url='https://x.invalid'>{o}</source></item>"
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>q</title>{rows}</channel></rss>"


class Resp:
    def __init__(self, text="", code=200):
        self.text, self.status_code, self.headers = text, code, {}


class Net:
    """A fake net: `routes` maps a source host to a text (or a status code); every ask is counted."""

    def __init__(self, routes):
        self.routes, self.asked = routes, []

    def get(self, url, headers=None, timeout=None):
        self.asked.append(url)
        host = "google_news" if "news.google" in url else "yahoo" if "yahoo" in url else "gdelt_doc"
        r = self.routes.get(host, "")
        if callable(r):
            r = r(url)
        return Resp(r, 200) if isinstance(r, str) else Resp("", int(r))


def client(routes):
    return ing.Client(Net(routes), sleep=lambda s: None, clock=lambda: 0.0)


def entries_for(con, root):
    return ing.scope_entries(con, NOW.date(), root)


def fake_think(decide="hold"):
    calls = []

    def fn(c, now, cid):
        calls.append(cid)
        cases.add_step(c, cid, now, "answer_ok", payload={})
        cases.record_decision(c, cid, now.date(), isin=None, symbol="AAA", rule_option=decide, model_option=decide, acted_option=decide, reason="test")
        return {"ok": True, "state": "open"}
    fn.calls = calls
    return fn


def tg(con, kind="alarm"):
    return [r[0] for r in con.execute("SELECT text FROM outbox WHERE kind=? ORDER BY msg_id", [kind]).fetchall()]


RED_TITLE = f"{NAME} CEO ousted by board with immediate effect"


# ------------------------------------------------------------------ parsing, scope and the lanes

def test_rss_is_parsed_with_outlet_and_time_in_ist():
    items = ing.parse_rss(rss([(RED_TITLE, "Reuters", T0)]), "google_news")
    assert items[0]["outlet"] == "Reuters" and items[0]["published"] == T0 and items[0]["title"].startswith(NAME)


def test_scope_has_the_held_names_with_aliases(con, tmp_path):
    es = {e["symbol"]: e for e in entries_for(con, tmp_path)}
    assert es["AAA"]["held"] and es["AAA"]["red_ok"] and "aardvark industries" in es["AAA"]["aliases"] and es["AAA"]["exposure_pct"] > 0


def test_lanes_red_needs_a_thesis_break_kind_and_the_name_in_the_headline(con, tmp_path):
    e = {e["symbol"]: e for e in entries_for(con, tmp_path)}["AAA"]
    assert alarm.lane_of(RED_TITLE, e)[0] == "red"
    assert alarm.lane_of(f"{NAME} opens a new plant in the south", e)[0] == "amber"
    assert alarm.lane_of("A rival CEO ousted by board with immediate effect", e)[0] == "grey"          # the company's name is not in it
    watched = dict(e, red_ok=False)
    assert alarm.lane_of(RED_TITLE, watched)[0] == "amber"                                                # a name only watched: never RED


# ------------------------------------------------------------------ the RED path

def test_a_red_headline_is_heard_frozen_opened_and_thought_in_the_same_run(con, tmp_path):
    think = fake_think()
    net = client({"google_news": rss([(RED_TITLE, "Reuters", T0 - timedelta(minutes=6))])})
    r = alarm.run(con, T0, tmp_path, client=net, entries=entries_for(con, tmp_path), sources=("google_news",), think_fn=think, tell_fn=lambda c, n, cid: None)
    assert len(r["alarms"]) == 1 and r["lanes"]["red"] == 1
    heard = tg(con)[0]
    assert heard.startswith("Heard at 11:20:") and "AAA" in heard and "Looking into it now" in heard and "Reuters" in heard
    a = con.execute("SELECT published_at, first_seen_at, case_opened_at, telegram_queued_at, decided_at, freeze_id, case_id FROM alarm_s86").fetchone()
    assert (a[1] - a[0]) == timedelta(minutes=6) and a[2] == T0 and a[3] == T0 and a[4] == T0 and a[6] == think.calls[0]
    assert con.execute("SELECT opened_by FROM think_cases_s84 WHERE case_id=?", [a[6]]).fetchone()[0] == "alarm"
    assert alarm.status(con, T0.date())["median_heard_min"] == pytest.approx(6.0)
    # the alarm's own freeze is lifted once the case decided (the decision was not a freeze)
    assert cases.is_frozen(con, AAA, T0.date()) is None


def test_the_freeze_holds_while_the_case_has_not_decided(con, tmp_path):
    net = client({"google_news": rss([(RED_TITLE, "Reuters", T0)])})
    alarm.run(con, T0, tmp_path, client=net, entries=entries_for(con, tmp_path), sources=("google_news",), think_fn=lambda c, n, cid: {"ok": False, "failed": "his cap was reached"})
    f = cases.is_frozen(con, AAA, T0.date())
    assert f is not None and "unconfirmed" in f["reason"]
    assert tg(con) and con.execute("SELECT decided_at FROM alarm_s86").fetchone()[0] is None


def test_the_same_story_from_five_outlets_is_one_heard_and_one_case(con, tmp_path):
    items = [(RED_TITLE, o, T0) for o in ("Reuters", "WSJ", "CNBC", "Mint", "Bloomberg")]
    items = [(t + f" ({k})", o, p) for k, (t, o, p) in enumerate(items)]
    think = fake_think()
    r = alarm.run(con, T0, tmp_path, client=client({"google_news": rss(items)}), entries=entries_for(con, tmp_path), sources=("google_news",), think_fn=think, tell_fn=lambda c, n, cid: None)
    assert len(tg(con)) == 1 and len(think.calls) == 1
    assert con.execute("SELECT count(*), max(joined_items) FROM alarm_s86").fetchone() == (1, 4)
    assert len(con.execute("SELECT 1 FROM think_cases_s84").fetchall()) == 1


def test_a_name_the_book_does_not_hold_sends_no_message(con, tmp_path):
    other = dict(entries_for(con, tmp_path)[0], isin="INE999Z01019", symbol="ZZZ", name="Zebra Works", held=False, red_ok=False, exposure_inr=0.0, exposure_pct=0.0, aliases=["zebra works"], tickers=[])
    r = alarm.run(con, T0, tmp_path, client=client({"google_news": rss([("Zebra Works CEO ousted by board with immediate effect", "Reuters", T0)])}), entries=[other], sources=("google_news",))
    assert r["lanes"] == {"red": 0, "amber": 1, "grey": 0} and tg(con) == []


def test_a_rumour_then_the_denial_freezes_then_lifts_and_nothing_is_sold(con, tmp_path):
    think = fake_think("hold")
    es = entries_for(con, tmp_path)
    alarm.run(con, T0, tmp_path, client=client({"google_news": rss([(RED_TITLE, "Blog", T0)])}), entries=es, sources=("google_news",), think_fn=think, tell_fn=lambda c, n, cid: None)
    assert cases.is_frozen(con, AAA, T0.date()) is None                                                  # decided: hold, so the freeze is lifted
    r2 = alarm.run(con, T0 + timedelta(minutes=15), tmp_path, client=client({"google_news": rss([(f"{NAME} denies CEO report, calls it false", "Reuters", T0 + timedelta(minutes=12))])}),
                   entries=es, sources=("google_news",), think_fn=think, tell_fn=lambda c, n, cid: None)
    assert r2["lanes"]["red"] == 0 and r2["lanes"]["amber"] == 1 and len(r2["denials"]) == 1
    assert con.execute("SELECT count(*) FROM think_signals_s84 WHERE detail_json LIKE '%denies CEO report%' AND case_id IS NOT NULL").fetchone()[0] == 1       # the denial is in the case beside the rumour
    assert con.execute("SELECT count(*) FROM think_decisions_s84 WHERE acted_option LIKE 'sell%' OR acted_option LIKE 'trim%'").fetchone()[0] == 0


def test_more_than_six_heard_a_day_become_one_summary_line(con, tmp_path):
    es = entries_for(con, tmp_path)
    for k in range(8):
        e = dict(es[0], isin=f"INE90{k}Z01011", symbol=f"S{k}", name=f"Name{k} Works", aliases=[f"name{k} works"], tickers=[])
        alarm.run(con, T0 + timedelta(minutes=k), tmp_path, client=client({"google_news": rss([(f"Name{k} Works CEO ousted by board with immediate effect", "Reuters", T0)])}), entries=[e],
                  sources=("google_news",), think_fn=lambda c, n, cid: {"ok": False, "failed": "x"})
    heard = [t for t in tg(con) if t.startswith("Heard")]
    assert len(heard) == 6 and len([t for t in tg(con) if "limit 6 a day" in t]) == 1


def test_a_slow_alarm_becomes_a_problems_line_with_its_cause(con, tmp_path):
    late = T0 - timedelta(minutes=70)
    alarm.run(con, T0, tmp_path, client=client({"google_news": rss([(RED_TITLE, "Reuters", late)])}), entries=entries_for(con, tmp_path), sources=("google_news",), think_fn=fake_think(),
              tell_fn=lambda c, n, cid: None)
    cause = con.execute("SELECT slow_cause FROM alarm_s86").fetchone()[0]
    assert "source was late" in cause
    assert con.execute("SELECT count(*) FROM session_log_s81 WHERE what LIKE '%from first published to heard%'").fetchone()[0] == 1


# ------------------------------------------------------------------ the eyes

def test_a_source_failing_for_three_hours_is_said_once_and_its_return_once(con, tmp_path):
    es = entries_for(con, tmp_path)
    good = rss([(f"{NAME} opens a plant", "Reuters", T0)])
    t = T0
    for k in range(13):                                                 # 3 hours of 15-minute passes: yahoo answers an error, google keeps answering
        t = T0 + timedelta(minutes=15 * k)
        alarm.run(con, t, tmp_path, client=client({"google_news": good, "yahoo": 503}), entries=es, sources=("google_news", "yahoo"), force=True)
    blind = [x for x in tg(con) if "not getting" in x]
    assert len(blind) == 1 and "Yahoo" in blind[0] and "Other sources keep watching" in blind[0]
    assert alarm.last_try(con) == t
    alarm.run(con, t + timedelta(minutes=15), tmp_path, client=client({"google_news": good, "yahoo": rss([])}), entries=es, sources=("google_news", "yahoo"), force=True)
    assert len([x for x in tg(con) if "answering again" in x]) == 1
    alarm.run(con, t + timedelta(minutes=30), tmp_path, client=client({"google_news": good, "yahoo": rss([])}), entries=es, sources=("google_news", "yahoo"), force=True)
    assert len([x for x in tg(con) if "answering again" in x]) == 1


def test_a_refused_source_is_a_problems_line_not_an_exception(con, tmp_path):
    r = alarm.run(con, T0, tmp_path, client=client({"gdelt_doc": 429}), entries=entries_for(con, tmp_path), sources=("gdelt_doc",))
    assert any("gdelt_doc" in p for p in r["problems"]) and r["by_source"]["gdelt_doc"]["refused"] == 1


def test_politeness_one_name_per_request_and_gdelt_for_held_names_only(con, tmp_path):
    net = Net({"google_news": rss([]), "gdelt_doc": "{}"})
    c = ing.Client(net, sleep=lambda s: None, clock=lambda: 0.0)
    ing.collect(con, tmp_path, entries_for(con, tmp_path), T0, client=c, sources=("google_news", "gdelt_doc"))
    assert all(len(u) < 400 for u in net.asked) and len([u for u in net.asked if "gdelt" in u]) <= ing.GDELT_MAX_PER_RUN
    assert not any("AAA" in u or "100" in u for u in net.asked)                                      # nothing about his book is in a request


# ------------------------------------------------------------------ the gap

def test_after_a_gap_the_backlog_message_comes_first(con, tmp_path):
    es = entries_for(con, tmp_path)
    alarm.record_eye(con, "google_news", T0 - timedelta(days=2), ok=True, items=1)              # the last time the lane looked: two days ago
    pub = T0 - timedelta(days=1, hours=3)
    think = fake_think()
    r = alarm.run(con, T0, tmp_path, client=client({"google_news": rss([(RED_TITLE, "Reuters", pub)])}), entries=es, sources=("google_news",), think_fn=think, tell_fn=lambda c, n, cid: None)
    msg = [t for t in tg(con) if t.startswith("Off from")]
    assert len(msg) == 1 and "AAA" in msg[0] and "Looking into 1 now" in msg[0]
    assert not [t for t in tg(con) if t.startswith("Heard")]                                    # a gap's items are not "heard" one by one
    assert r["gap"]["red"] == 1 and len(think.calls) == 1
    assert con.execute("SELECT mode FROM alarm_s86").fetchone()[0] == "gap"


def test_a_gap_with_nothing_found_is_one_line_too(con, tmp_path):
    alarm.record_eye(con, "google_news", T0 - timedelta(days=3), ok=True)
    alarm.run(con, T0, tmp_path, client=client({"google_news": rss([])}), entries=entries_for(con, tmp_path), sources=("google_news",))
    assert [t for t in tg(con) if t.startswith("Off from") and "Nothing serious found" in t]


# ------------------------------------------------------------------ raw lines and the graph

def test_items_are_stored_once_with_both_times_and_counted_from_first_seen(con, tmp_path):
    es = entries_for(con, tmp_path)
    for k in range(2):
        alarm.run(con, T0 + timedelta(minutes=15 * k), tmp_path, client=client({"google_news": rss([(RED_TITLE, "Reuters", T0 - timedelta(hours=2))])}), entries=es, sources=("google_news",), force=True,
                  think_fn=fake_think(), tell_fn=lambda c, n, cid: None)
    assert con.execute("SELECT count(*) FROM headlines_s86").fetchone()[0] == 1
    ev, st = kg.events(tmp_path, T0.date())
    assert len(ev) == 1 and ev[0]["ts"] == T0                                                     # the event's time is the first-seen time, not the publication time
    assert (tmp_path / "headlines_s86").exists()


def test_the_graph_rebuild_gives_the_same_events_and_waits_for_the_next_day_after_the_cutoff(con, tmp_path):
    es = entries_for(con, tmp_path)
    alarm.run(con, datetime(2026, 10, 30, 22, 0), tmp_path, client=client({"google_news": rss([(RED_TITLE, "Reuters", datetime(2026, 10, 30, 21, 40))])}), entries=es, sources=("google_news",),
              think_fn=fake_think(), tell_fn=lambda c, n, cid: None)
    a, _ = kg.events(tmp_path, date(2026, 10, 30))
    b, _ = kg.events(tmp_path, date(2026, 10, 30))
    assert a == b and len(a) == 1 and a[0]["ts_rule"] == "seen_time" and a[0]["kind"] == "leadership_crisis" and a[0]["isin"] == AAA
    nxt, _ = kg.events(tmp_path, date(2026, 10, 29))                                              # an earlier day's build does not know it
    assert nxt == []
    assert kg.event_id(kg.item_id(AAA, RED_TITLE + " - Reuters")) == a[0]["event_id"]


def test_the_switch_off_does_nothing(con, tmp_path, monkeypatch):
    monkeypatch.setattr(alarm, "on", lambda: False)
    assert alarm.run(con, T0, tmp_path, client=client({}), entries=entries_for(con, tmp_path))["off"] is True


# ------------------------------------------------------------------ H3: the company's own filing reaches the loop the same day

def test_an_indian_filing_at_1120_is_heard_and_a_case_by_1140(con, tmp_path):
    import pandas as pd
    from pflab.data import bse_scrip_isin
    d = date(2026, 10, 30)
    (tmp_path / "bse_announcements" / "2026").mkdir(parents=True)
    pd.DataFrame([{"scrip_code": "500001", "headline": "Resignation of the statutory auditors of the Company", "category": "Company Update", "subcategory": "Auditors",
                   "dissem_dt": datetime(2026, 10, 30, 11, 20), "news_dt": None}]).to_parquet(tmp_path / "bse_announcements" / "2026" / f"{d.isoformat()}.parquet")
    monkey = pd.DataFrame([{"scrip_code": "500001", "isin": AAA}])
    import pflab.data.bse_scrip_isin as b
    orig = b.load
    b.load = lambda root: monkey
    try:
        think = fake_think()
        r = alarm.run(con, datetime(2026, 10, 30, 11, 35), tmp_path, client=client({"google_news": rss([])}), entries=entries_for(con, tmp_path), sources=("google_news",), think_fn=think,
                      tell_fn=lambda c, n, cid: None)
    finally:
        b.load = orig
    assert len(r["alarms"]) == 1 and tg(con)[0].startswith("Heard at 11:35") and "BSE filing" in tg(con)[0] and len(think.calls) == 1


# ------------------------------------------------------------------ H7: the fast-forward

def _gap_run(con, tmp_path, pub, think=None, now=datetime(2026, 10, 30, 16, 0), prev=datetime(2026, 10, 26, 18, 0)):
    from pflab.think import fastforward
    alarm.record_eye(con, "google_news", prev, ok=True)
    return alarm.run(con, now, tmp_path, client=client({"google_news": rss([(RED_TITLE, "Reuters", pub)])}), entries=entries_for(con, tmp_path), sources=("google_news",),
                     think_fn=think or fake_think(), tell_fn=lambda c, n, cid: None, gap=fastforward.hook())


def test_the_gap_is_replayed_as_a_ghost_and_the_cost_of_being_off_is_in_the_message(con, tmp_path):
    from pflab.paper import book
    held_before = dict(book.positions(con))
    r = _gap_run(con, tmp_path, datetime(2026, 10, 27, 10, 0))
    g = con.execute("SELECT option, source, label, fill_price, live_price, qty, cost_of_being_off_inr, decided_at FROM ghost_s86").fetchall()
    assert len(g) == 1 and g[0][0] == "sell" and g[0][1] == "code" and g[0][2] == "replayed_while_off" and g[0][5] > 0
    assert g[0][7] == datetime(2026, 10, 27, 10, 0) + timedelta(minutes=15)                         # publication + the lane's own default delay
    assert g[0][6] == pytest.approx(g[0][5] * (g[0][3] - g[0][4]))
    msg = [t for t in tg(con) if t.startswith("Off from")][0]
    assert "Had I been on: sells AAA" in msg and ("cost Rs" in msg or "saved Rs" in msg)
    assert dict(book.positions(con)) == held_before                                                # the REAL book was not touched by the replay
    assert r["gap"]["fast_forward"]["ghosts"][0]["symbol"] == "AAA"


def test_a_gap_is_not_replayed_twice_and_one_before_the_release_is_not_replayed(con, tmp_path, monkeypatch):
    from pflab.think import fastforward as ff
    _gap_run(con, tmp_path, datetime(2026, 10, 27, 10, 0))
    assert ff.run_gap(con, datetime(2026, 10, 30, 16, 0), tmp_path, datetime(2026, 10, 26, 18, 0), [])["skipped"] == "this gap was replayed already"
    monkeypatch.setattr(ff, "release_start", lambda: date(2026, 10, 28))
    r = ff.run_gap(con, datetime(2026, 10, 30, 16, 0), tmp_path, datetime(2026, 10, 26, 18, 0), [])
    assert "before this release" in r["skipped"]


def test_ghost_decisions_are_scored_in_their_own_column(con, tmp_path):
    from pflab.think import fastforward as ff
    _gap_run(con, tmp_path, datetime(2026, 10, 20, 10, 0), prev=datetime(2026, 10, 19, 18, 0), now=datetime(2026, 10, 26, 16, 0))
    n = ff.score_ghosts(con, date(2026, 10, 30))
    sc = ff.scorecard(con)
    assert n >= 1 and sc["label"] == "replayed_while_off" and sc["right"]["5"]["scored"] == 1 and sc["decisions"] == 1
    assert ff.scorecard_line(con).startswith("While off (replayed_while_off)")
    assert ff.score_ghosts(con, date(2026, 10, 30)) == 0                                            # idempotent


def test_the_switch_off_replays_nothing(con, tmp_path, monkeypatch):
    from pflab.think import fastforward as ff
    monkeypatch.setattr(ff, "enabled", lambda: False)
    assert ff.hook() is None


# ------------------------------------------------------------------ W2.2: one name, one day, one sale order whichever road decides first

def test_the_case_sale_and_the_exit_managers_thesis_sale_never_both_place_an_order_for_one_name(con, tmp_path):
    from pflab.core import exits
    day = date(2026, 10, 30)
    now = datetime(2026, 10, 30, 11, 20)
    exits.backfill_plans(con, day, "IN", now)
    con.execute("UPDATE exit_plans_s81 SET thesis_break_kinds=? WHERE isin=? AND market='IN'", [json.dumps(["leadership_crisis", "auditor_resignation"]), AAA])
    plan = exits._plans(con, "IN", isin=AAA)[0]
    from pflab.paper import book
    pos = float(book.positions(con)[AAA])
    cfg = exits.settings()
    first = exits._sell(con, now, day, plan, AAA, "case", pos, pos, 100.0, "the case decided to sell", cfg, override_guard=True, ref=f"case:1:{day}")
    assert first is not None
    ev = {"isin": AAA, "kind": "leadership_crisis", "severity": "high", "ts": datetime(2026, 10, 30, 11, 25), "source": "bse_announcement", "ref": "r9", "text": "ceo ousted"}
    second = exits.check_thesis(con, day, [ev], prices={AAA: 100.0})
    assert second == []                                                                            # the exit manager's own sale is held back: one road sold, one order exists
    assert con.execute("SELECT count(*) FROM exit_events_s81 WHERE isin=? AND side='sell' AND status='emitted'", [AAA]).fetchone()[0] == 1


# ------------------------------------------------------------------ W2.4: a reserve buy is not cut by the fall gauge for its first 10 sessions

def test_a_reserve_buy_is_protected_from_the_fall_gauge_for_ten_sessions(con):
    from pflab.core import baseline_v2
    from pflab.think import reserve
    day = date(2026, 10, 30)
    cases.add_step(con, 1, datetime(2026, 10, 28, 12, 0), "part", payload={"isin": GLD, "symbol": "GLDBEES", "n": 1, "of": 3, "inr": 5000.0, "day": "2026-10-28"})
    cases.add_step(con, 1, datetime(2026, 9, 1, 12, 0), "part", payload={"isin": BBB, "symbol": "BBB", "n": 1, "of": 3, "inr": 5000.0, "day": "2026-09-01"})        # long ago: not protected
    w = reserve.protected_weights(con, day, "IN", 1_000_000.0)
    assert w == {GLD: pytest.approx(0.005)}


# ------------------------------------------------------------------ the protocol amendment for the ghost column

def test_amendment_a3_is_counted_once_and_the_protocol_stays_ok(con):
    from pflab.learner import s84
    s84.register_thinking_live(con, NOW)
    assert s84.register_thinking_amendment_a2(con, NOW) == ["s84:thinking_live_a2"]
    assert s84.register_thinking_amendment_a3(con, NOW) == ["s84:thinking_live_a3"] and s84.register_thinking_amendment_a3(con, NOW) == []
    assert s84.protocol_ok(con)["unchanged"] is True


# ------------------------------------------------------------------ H1: the daily collection covers the held names too (merge_held is wired)

def test_the_held_names_are_merged_into_the_news_scope_once(con, tmp_path):
    from pflab.kg2 import scope as sc
    sc._atomic_write(sc.scope_path(tmp_path), json.dumps({"version": 1, "names": [], "extra_isins": []}))
    es = entries_for(con, tmp_path)
    n = alarm.merge_scope(tmp_path, es)
    got = {x["isin"]: x for x in sc.load(tmp_path)["names"]}
    assert n >= 1 and AAA in got and got[AAA]["text"] and "aardvark industries" in got[AAA]["aliases"]
    assert alarm.merge_scope(tmp_path, es) == 0                                                   # unchanged names: the file is not rewritten


# ------------------------------------------------------------------ the lane beside a busy writer: its own thread, its own cursor, no lost write, no late tick

def test_the_lane_runs_on_its_own_cursor_beside_a_busy_writer_without_losing_a_write(con, tmp_path):
    import threading
    import time
    con.execute("CREATE TABLE busy_s86 (k INTEGER, ts TIMESTAMP)")
    es = entries_for(con, tmp_path)
    errs, late = [], []
    stop = threading.Event()

    def lane():
        cur = con.cursor()
        try:
            for k in range(6):
                alarm.run(cur, T0 + timedelta(minutes=15 * k), tmp_path, client=client({"google_news": rss([(f"{NAME} opens plant number {k}", "Reuters", T0)])}), entries=es, sources=("google_news",), force=True)
        except Exception as e:
            errs.append(repr(e))
        finally:
            stop.set()

    t = threading.Thread(target=lane)
    t.start()
    cur2, n, prev = con.cursor(), 0, time.monotonic()
    while not stop.is_set():                                                                     # the "session loop": a tick every few milliseconds that must never wait long
        t0 = time.monotonic()
        cur2.execute("INSERT INTO busy_s86 VALUES (?, now())", [n])
        late.append(time.monotonic() - t0)
        n += 1
        time.sleep(0.005)
    t.join()
    assert errs == [] and con.execute("SELECT count(*) FROM busy_s86").fetchone()[0] == n and n > 0
    assert con.execute("SELECT count(*) FROM headlines_s86").fetchone()[0] == 6
    assert max(late) < 5.0                                                                       # no tick of the writer was held for seconds by the lane


# ------------------------------------------------------------------ H2: the local model reads the leads the rules cannot place; the volume rule needs something serious

def test_a_lead_the_rules_miss_is_read_by_the_local_model_and_only_a_high_break_is_red(con, tmp_path):
    lead = f"{NAME} opens investigation into its chief's relationship with a suspected foreign agent"
    es = entries_for(con, tmp_path)
    think = fake_think()
    r = alarm.run(con, T0, tmp_path, client=client({"google_news": rss([(lead, "CNBC", T0 - timedelta(minutes=5))])}), entries=es, sources=("google_news",), think_fn=think,
                  tell_fn=lambda c, n, cid: None, model_fn=lambda t: {"kind": "leadership_crisis", "severity": "high"})
    assert r["lanes"]["red"] == 1 and len(think.calls) == 1 and tg(con)[0].startswith("Heard")
    from pflab.kg2 import classify
    assert any(v["kind"] == "leadership_crisis" for v in classify.load_cache(tmp_path).values())            # cached, so the graph's rebuild gives the same kind
    con.execute("DELETE FROM headlines_s86")
    r2 = alarm.run(con, T0 + timedelta(hours=9), tmp_path, client=client({"google_news": rss([(f"{NAME} faces questions over a supplier", "CNBC", T0 + timedelta(hours=9))])}), entries=es,
                   sources=("google_news",), think_fn=think, tell_fn=lambda c, n, cid: None, model_fn=lambda t: {"kind": "regulatory_action", "severity": "medium"})
    assert r2["lanes"]["red"] == 0                                                                          # a medium guess of the small model is not a paid case


def test_many_outlets_on_mundane_stories_is_not_an_alarm_but_many_with_a_serious_one_is(con, tmp_path):
    e = entries_for(con, tmp_path)[0]
    cfg = alarm.settings()
    for k in range(30):                                                                                     # a norm: 30 busy hours of one outlet
        con.execute("INSERT INTO headlines_s86 (item_id, isin, title, source, published, first_seen, outlet) VALUES (?,?,?,?,?,?,?)",
                    [f"h{k}", AAA, f"{NAME} routine {k}", "google_news", T0 - timedelta(hours=40 + k), T0 - timedelta(hours=40 + k), "Wire"])
    for k, o in enumerate(("Reuters", "WSJ", "CNBC", "Mint")):
        con.execute("INSERT INTO headlines_s86 (item_id, isin, title, source, published, first_seen, outlet) VALUES (?,?,?,?,?,?,?)",
                    [f"m{k}", AAA, f"{NAME} stock on a losing streak, what comes next {k}", "google_news", T0 - timedelta(minutes=10), T0, o])
    assert alarm.burst(con, T0, e, cfg) is None                                                             # four outlets, nothing serious in them: no alarm
    con.execute("UPDATE headlines_s86 SET title=? WHERE item_id='m0'", [f"{NAME} CEO ousted by board with immediate effect"])
    assert alarm.burst(con, T0, e, cfg) is not None


# ------------------------------------------------------------------ S86b C2(b): the four REDs of the live hour as fixtures

def test_the_live_hours_four_reds_through_the_current_rules():
    al, tk = ing._aliases("Nvidia Corp", "NVDA", "US")
    e = {"isin": "ZZ0001045810", "symbol": "NVDA", "market": "US", "name": "Nvidia Corp", "held": True, "red_ok": True, "aliases": al, "tickers": tk}
    preview = "Here's How Much Traders Expect Nvidia Stock to Move After Earnings Next Week - Investopedia"
    streak = "Nvidia's stock is on a losing streak not seen in 14 years. What comes next? - MarketWatch"
    downgrade = "HSBC downgrades Nvidia, says stock to struggle until new CEO named - CNBC"
    opinion = "Alex Kantrowitz explains why Jensen Huang's ouster as Nvidia CEO is 'good for America' - CNBC"
    assert alarm.lane_of(preview, e)[0] == "amber" and alarm.lane_of(streak, e)[0] == "amber"          # the two earnings / streak stories are not RED by kind, and not by volume alone any more
    assert alarm.lane_of(downgrade, e)[:2] == ("red", "rating_downgrade")                                # the genuine downgrade is
    assert alarm.lane_of(opinion, e)[0] == "red"                                                         # an opinion piece on a real ouster is still RED by kind: the rules cannot tell commentary from news (listed, not tuned to one headline)


# ------------------------------------------------------------------ S86b C2(c): the top ten members of a held fund join the scope, with their look-through rupees

def test_the_ten_largest_members_of_a_held_fund_join_the_scope_hourly_and_can_be_red(con, tmp_path, monkeypatch):
    from pflab.think import exposure
    members = {}
    for k in range(12):
        isin = f"INE7{k:02d}Z01019"
        con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, 'synthetic', now())",
                    [isin, f"M{k}", f"Member{k} Works Ltd"])
        members[isin] = 0.20 - 0.01 * k
    fw = {"funds": {"INF000X01019": {"symbol": "NIFTYBEES", "market": "IN", "value_inr": 100000.0, "weights": members, "basis": "NIFTY50 weights (stored)"}}, "uncovered": [], "whole_inr": 1_000_000.0}
    monkeypatch.setattr(exposure, "fund_weights", lambda con_, day, root=None: fw)
    es = entries_for(con, tmp_path)
    via = [e for e in es if e.get("through_fund")]
    assert len(via) == 10 and all(e["red_ok"] and not e["held"] and e["exposure_inr"] > 0 for e in via)
    assert max(e["exposure_inr"] for e in via) == pytest.approx(20000.0) and "through a fund" in via[0]["why"]
    e = via[0]
    assert alarm.lane_of(f"{e['name'].replace(' Ltd', '')} CEO ousted by board with immediate effect", e)[0] == "red"                  # A73's exposure rule applies unchanged
    assert "through funds: NIFTYBEES" in alarm.funds_text(con, NOW.date())
    monkeypatch.setattr(exposure, "fund_weights", lambda con_, day, root=None: {"funds": {}, "uncovered": [{"symbol": "NIFTYBEES", "why": "no member data for NIFTY50"}], "whole_inr": 1.0})
    assert alarm.funds_text(con, NOW.date()).startswith("through funds: not known")
    # asked hourly, not every pass
    net = Net({"google_news": rss([])})
    c = ing.Client(net, sleep=lambda s: None, clock=lambda: 0.0)
    monkeypatch.setattr(exposure, "fund_weights", lambda con_, day, root=None: fw)
    ing.collect(con, tmp_path, entries_for(con, tmp_path), T0, client=c, sources=("google_news",))
    first = len(net.asked)
    ing.collect(con, tmp_path, entries_for(con, tmp_path), T0 + timedelta(minutes=15), client=c, sources=("google_news",))
    assert len(net.asked) - first <= 3                                                                                                # only the held names again; the ten members wait for the hour
