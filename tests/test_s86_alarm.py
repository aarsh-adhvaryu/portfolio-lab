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
    assert r2["lanes"]["red"] == 0 and r2["lanes"]["amber"] == 1
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
