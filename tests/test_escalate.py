"""S56 escalation chain: the same question always takes the same road (fixed rules), each step says why it moved on, his
own data never leaves (a portfolio question stops at the facts), a recent note is reused, spending waits inside the
doorbell, and the fall flags send a company that falls on its own to the researcher."""
from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from pflab.agents import analyst as an
from pflab.agents import escalate as es
from pflab.agents import researcher as rs
from pflab.agents import workshop as wk

ASOF = date(2026, 10, 23)
NOW = datetime(2026, 10, 23, 12, 0)


@pytest.mark.parametrize("q,isins,kind", [
    ("what is my net worth", [], "own"),
    ("show my FDs and when they mature", [], "own"),
    ("how much tax have I paid this year", [], "calc"),          # local tools first; rows never leave
    ("what is the largest fall of the Nifty 50 since 2020", [], "calc"),
    ("why did ACME fall this week", ["INE000Y01019"], "company"),
    ("ACME", ["INE000Y01019"], "company"),
    ("what is the GMP of the upcoming IPO", [], "outside"),
    ("what does Tijori Premium cost", [], "outside"),
])
def test_the_kind_is_fixed_by_rules(q, isins, kind):
    assert es.kind_of(q, isins) == kind


class Spy:
    def __init__(self, **ret):
        self.calls, self.ret = [], ret

    def fn(self, name):
        def f(*a, **k):
            self.calls.append(name)
            r = self.ret[name]
            if isinstance(r, Exception):
                raise r
            return r
        return f

    def fns(self):
        return {n: self.fn(n) for n in ("local", "workshop", "note", "deep", "web")}


def local(verified, text="facts"):
    return SimpleNamespace(verified=verified, text=text, tools=["networth"])


@pytest.fixture(autouse=True)
def req(monkeypatch):
    def deep_request(con, q, asof, urgent=True):
        return an.Request(q, "ACME" if "ACME" in q else "general", [], ["INE000Y01019"] if "ACME" in q else [], urgent)
    monkeypatch.setattr(an, "deep_request", deep_request)


def go(q, spy):
    return es.run(None, q, ASOF, pm_dir=None, root=None, now=NOW, fns=spy.fns())


def test_his_own_data_never_leaves():
    s = Spy(local=local(True, "Your net worth is ..."))
    r = go("what is my net worth", s)
    assert r.text == "Your net worth is ..." and s.calls == ["local"] and len(r.steps) == 1
    s = Spy(local=local(False, "FACTS"))
    r = go("what is my net worth", s)
    assert r.text == "FACTS" and s.calls == ["local"] and "does not leave this PC" in r.steps[-1].why


def test_a_calculation_goes_to_the_workshop(monkeypatch):
    monkeypatch.setattr(wk, "render", lambda w: "RESULT")
    s = Spy(local=local(False), workshop=SimpleNamespace(status="checked", writer="opus"))
    r = go("what is the largest fall of the Nifty 50 since 2020", s)
    assert s.calls == ["local", "workshop"] and r.text == "RESULT" and r.status == "done"
    assert "opus writes the code" in r.steps[-1].who and "second method" in r.steps[-1].outcome


def test_a_company_question_reuses_a_recent_note_before_paying():
    s = Spy(local=local(True), note=(7, datetime(2026, 10, 20), "the note"))
    r = go("why did ACME fall this week", s)
    assert s.calls == ["local", "note"] and r.text == "the note" and "not bought twice" in r.steps[-1].why
    assert "going further" in r.steps[0].why


def test_opus_answers_when_nothing_else_does_and_spending_waits_for_a_yes():
    s = Spy(local=local(False), note=None, deep=an.Outcome("done", "Opus note [D1]", None, 12.5))
    r = go("why did ACME fall this week", s)
    assert s.calls == ["local", "note", "deep"] and r.text == "Opus note [D1]" and r.cost == 12.5
    assert es.route(r)[-1].endswith("₹12.50")
    s = Spy(local=local(False, "FACTS"), note=None, deep=an.NeedsApproval("about Rs 150, above Rs 100"))
    r = go("why did ACME fall this week", s)
    assert r.status == "needs_approval" and "FACTS" in r.text and r.steps[-1].outcome == "waits for your yes"
    s = Spy(local=local(False, "FACTS"), note=None, deep=an.Outcome("blocked", "a ledger amount is in the question"))
    r = go("why did ACME fall this week", s)
    assert r.status == "failed" and "ledger amount" in r.text and "FACTS" in r.text


def test_the_outside_world_goes_to_web_search():
    s = Spy(local=local(False), web=an.Outcome("done", "cited answer [W1]", None, 3.0))
    r = go("what is the GMP of the upcoming IPO", s)
    assert s.calls == ["local", "web"] and r.steps[-1].who == "Opus with web search"
    s = Spy(local=local(False, "F"), web=an.NotAdopted("the analyst is off"))
    assert go("what is the GMP of the upcoming IPO", s).status == "failed"


def test_a_company_specific_fall_is_flagged(monkeypatch):
    rng = np.random.default_rng(3)
    days = pd.bdate_range(end="2026-10-16", periods=300)
    m = pd.Series(rng.normal(0.0004, 0.01, len(days)), index=days)
    own = 0.9 * m + rng.normal(0, 0.008, len(days))
    own.iloc[-5:] = [-0.04, -0.035, -0.03, -0.03, -0.025]             # it falls ~15% while the market does not
    m.iloc[-5:] = [0.002, 0.001, 0.0, 0.001, 0.002]
    px = 100 * (1 + own).cumprod()
    from pflab.app import research as rsx
    monkeypatch.setattr(rsx, "closes", lambda con, root, isin, asof, years=2: px)
    f = rs.fall_flags(None, "x", "INE000A01001", "AAA", ASOF, m)
    assert len(f) == 1 and f[0].kind == "fall" and f[0].ref == "fall5@2026-10-16"
    assert f[0].detail.startswith("company-specific fall") and "standard deviations" in f[0].detail
    calm = 100 * (1 + 0.9 * m).cumprod()
    monkeypatch.setattr(rsx, "closes", lambda con, root, isin, asof, years=2: calm)
    assert rs.fall_flags(None, "x", "INE000A01001", "AAA", ASOF, m) == []


def test_a_tijori_export_goes_to_the_analyst_unless_switched_off(monkeypatch):
    from pathlib import Path

    from pflab.agents import inbox
    t = pd.DataFrame({"Metric": ["Revenue", "EBITDA"], "FY25": [100.0, 20.0]})
    monkeypatch.setattr(an, "config", lambda path=None: {})                      # the default: on (The investor 2026-10-23)
    assert inbox.shareable(Path("tijori_export.xlsx"), True, t, "")
    monkeypatch.setattr(an, "config", lambda path=None: {"tijori_to_analyst": False})
    assert not inbox.shareable(Path("tijori_export.xlsx"), True, t, "")
    assert inbox.shareable(Path("screener_export.xlsx"), True, t, "")          # Screener: unchanged
