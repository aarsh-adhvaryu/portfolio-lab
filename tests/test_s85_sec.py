"""S85 `sec`: US company filings from the SEC (8-K items 5.02, 4.01, 4.02) into the graph. Recorded-shape fixtures with synthetic companies (rule 7: no real name, holding or amount); a fake HTTP
session and a fake clock stand in for the SEC, so nothing waits and nothing leaves the PC."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

import duckdb
import pandas as pd
import pytest

from pflab import markets
from pflab.ingest import sec_8k as ing
from pflab.kg import events as kev
from pflab.kg2 import audit, build as kb, classify, filing_time as ft, sec_8k as kg
from pflab.pm import store
from pflab.pm.mig_s79 import collect as collect_migrations

from test_s81_kg import GROUPS, root  # noqa: F401  (the fixture is used by name)
from test_s82_kg import _audit_con

ASOF = date(2026, 6, 30)
NOW = datetime(2026, 6, 30, 20, 0)                       # IST wall time, a Tuesday evening
UA = "Zed Tester zed.marker@example.invalid"             # the contact header: must never show up anywhere
CIK = 1234567
KEY = "ZZ0001234567"
CO = "Example Dynamics Inc"


@pytest.fixture(autouse=True)
def _contact(monkeypatch):
    monkeypatch.setenv("PFLAB_SEC_USER_AGENT", UA)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


# ------------------------------------------------------------------ a fake SEC

class Resp:
    def __init__(self, text="", code=200, headers=None):
        self.text, self.status_code, self.headers = text, code, headers or {}


class Clock:
    """A clock that only moves when something sleeps, so pacing can be measured."""

    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class FakeSession:
    """routes: url -> text | Resp | list of those (served in order, the last repeats). Records every call with its headers."""

    def __init__(self, routes, clock=None):
        self.routes, self.calls, self.clock = dict(routes), [], clock

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, dict(headers or {}), self.clock.now() if self.clock else None))
        r = self.routes.get(url)
        if r is None:
            return Resp("", 404)
        if isinstance(r, list):
            r = r.pop(0) if len(r) > 1 else r[0]
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, Resp) else Resp(r)


def _client(routes, clock=None, **kw):
    clock = clock or Clock()
    return ing.Client(session=FakeSession(routes, clock), sleep=clock.sleep, clock=clock.now, **kw), clock


def _subs(filings, cik=CIK, name=CO):
    cols = {"accessionNumber": [], "filingDate": [], "acceptanceDateTime": [], "form": [], "primaryDocument": [], "items": []}
    for f in filings:
        cols["accessionNumber"].append(f["accn"])
        cols["filingDate"].append(f["filed"])
        cols["acceptanceDateTime"].append(f["accepted"])
        cols["form"].append(f["form"])
        cols["primaryDocument"].append(f.get("doc", f["accn"].replace("-", "") + ".htm"))
        cols["items"].append(f.get("items", ""))
    return json.dumps({"cik": str(cik), "name": name, "tickers": ["EXDY"], "filings": {"recent": cols, "files": []}})


def _url(accn, cik=CIK, doc=None):
    return ing.ARCHIVE.format(cik=cik, acc=accn.replace("-", ""), doc=doc or accn.replace("-", "") + ".htm")


def _html(*items, hidden=True):
    """A trimmed real layout: a cover page, an inline-XBRL hidden header, the items, the exhibit item and the signature."""
    head = ("<ix:header><ix:hidden><ix:nonnumeric>HIDDEN-XBRL-VALUE 0001234567</ix:nonnumeric></ix:hidden></ix:header>" if hidden else "")
    cover = ("<div>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</div><div>FORM 8-K</div><div>CURRENT REPORT</div>"
             f"<div>{CO}</div><div>Check the appropriate box below if the Form 8-K filing is intended to simultaneously satisfy the filing obligation of the registrant</div>")
    body = "".join(f"<p><b>Item {n}</b> {title}</p>" + "".join(f"<p>{para}</p>" for para in paras) for n, title, paras in items)
    return f"<html><head><title>8-K</title><style>p{{margin:0}}</style></head><body>{head}{cover}{body}<p>Item 9.01 Financial Statements and Exhibits.</p><p>SIGNATURE</p><p>Pursuant to the requirements, the registrant has duly caused this report to be signed.</p></body></html>"


T502 = "Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers; Compensatory Arrangements of Certain Officers."
T401 = "Changes in Registrant's Certifying Accountant."
T402 = "Non-Reliance on Previously Issued Financial Statements or a Related Audit Report or Completed Interim Review."

CEO_FIRED = ('On June 28, 2026, the Board of Directors (the "Board") of Example Dynamics Inc. (the "Company") terminated the employment of Jane Roe as Chief Executive Officer of the Company, '
             'effective immediately. The Board appointed John Poe, a director of the Company, as interim Chief Executive Officer.')
AUD_RESIGNED = ('On June 25, 2026, Example Audit LLP ("EA") notified the Company that it resigned as the Company\'s independent registered public accounting firm, effective immediately. '
                'There were no disagreements with EA on any matter of accounting principles or practices, financial statement disclosure, or auditing scope or procedure, which disagreements, '
                'if not resolved to the satisfaction of EA, would have caused it to make reference thereto in its reports. There were no reportable events as defined in Item 304(a)(1)(v) of Regulation S-K.')
NON_RELIANCE = ('On June 24, 2026, the Audit Committee of the Board concluded that the Company\'s previously issued financial statements for the fiscal year ended December 31, 2025 '
                'should no longer be relied upon because of errors in the recognition of revenue.')


def _filings():
    return [
        {"accn": "0001234567-26-000011", "form": "8-K", "filed": "2026-06-29", "accepted": "2026-06-29T14:02:11.000Z", "items": "5.02,9.01"},
        {"accn": "0001234567-26-000012", "form": "8-K", "filed": "2026-06-26", "accepted": "2026-06-26T21:30:00.000Z", "items": "4.02"},
        {"accn": "0001234567-26-000013", "form": "8-K", "filed": "2026-06-20", "accepted": "2026-06-20T12:00:00.000Z", "items": "2.02,9.01"},       # earnings: not wanted
        {"accn": "0001234567-26-000014", "form": "10-Q", "filed": "2026-06-18", "accepted": "2026-06-18T20:00:00.000Z", "items": ""},
        {"accn": "0001234567-26-000015", "form": "8-K", "filed": "2026-03-01", "accepted": "2026-03-01T14:00:00.000Z", "items": "5.02"},             # older than the look-back
        {"accn": "0001234567-26-000016", "form": "8-K/A", "filed": "2026-06-28", "accepted": "2026-06-28T14:00:00.000Z", "items": "5.02"},           # an amendment: the original carries it
        {"accn": "0001234567-26-000017", "form": "8-K", "filed": "2026-06-29", "accepted": "2026-06-29T15:00:00.000Z", "items": "4.01,9.01"},
    ]


def _routes():
    return {ing.SUBMISSIONS.format(cik=CIK): _subs(_filings()),
            _url("0001234567-26-000011"): _html(("5.02", T502, [CEO_FIRED])),
            _url("0001234567-26-000012"): _html(("4.02", T402, [NON_RELIANCE])),
            _url("0001234567-26-000017"): _html(("4.01", T401, [AUD_RESIGNED]))}


ENTRY = {"cik": CIK, "isin": KEY, "symbol": "EXDY"}


# ------------------------------------------------------------------ the index: parsing and filtering

def test_the_index_gives_only_the_8ks_with_a_wanted_item_inside_the_look_back():
    j = json.loads(_subs(_filings()))
    df = ing.wanted_filings(j, datetime(2026, 5, 31))
    assert sorted(df["accn"]) == ["0001234567-26-000011", "0001234567-26-000012", "0001234567-26-000017"]
    assert dict(zip(df["accn"], df["wanted"]))["0001234567-26-000011"] == ["5.02"]                 # 9.01 is not read
    assert df[df["accn"] == "0001234567-26-000017"]["wanted"].iloc[0] == ["4.01"]
    assert ing.wanted_filings({"filings": {"recent": {}}}, datetime(2026, 5, 31)).empty            # a company with no filings


def test_the_items_cover_exactly_the_three_the_brief_names_and_the_kind_is_on_the_closed_list():
    assert ing.WANTED == ("5.02", "4.01", "4.02")
    assert "accounting_concern" in classify.THESIS_BREAK_KINDS and "accounting_concern" in classify.KINDS and "accounting_concern" in classify.MODEL_PICKS
    assert not classify.validate({"kind": "accounting_concern", "severity": "high"})


# ------------------------------------------------------------------ the text of a filing

def test_html_becomes_text_with_the_hidden_xbrl_header_dropped_and_items_cut_at_the_next_heading():
    t = ing.html_to_text(_html(("5.02", T502, [CEO_FIRED]), ("4.01", T401, [AUD_RESIGNED])))
    assert "HIDDEN-XBRL-VALUE" not in t and "<" not in t
    s = ing.sections(t, ["5.02", "4.01"])
    assert set(s) == {"5.02", "4.01"} and not s["5.02"]["fallback"]
    assert "terminated the employment of Jane Roe" in s["5.02"]["text"] and "resigned as the Company" not in s["5.02"]["text"]       # 5.02 stops where 4.01 starts
    assert "Financial Statements and Exhibits" not in s["4.01"]["text"] and "duly caused" not in s["4.01"]["text"]                          # the exhibit item and the signature are cut


def test_inline_xbrl_documents_with_an_xml_declaration_and_a_hidden_div_are_read_line_by_line():
    page = "<?xml version='1.0' encoding='utf-8'?>" + _html(("5.02", T502, [CEO_FIRED])).replace("<ix:header>", "<div style=\"display:none\"><ix:header>").replace("</ix:header>", "</ix:header></div>")
    t = ing.html_to_text(page)
    assert "HIDDEN-XBRL-VALUE" not in t and t.count(chr(10)) >= 8                                        # real filings arrive like this; a regex fallback would give one line
    assert not ing.sections(t, ["5.02"])["5.02"]["fallback"]


def test_a_thin_space_inside_the_item_heading_and_a_title_in_its_own_cell_are_read():
    page = ("<html><body><table><tr><td>Item&#8201;5.02</td><td>" + T502 + "</td></tr></table><p>" + CEO_FIRED + "</p>"
            "<table><tr><td>Item&#8201;9.01</td><td>Financial Statements and Exhibits.</td></tr></table></body></html>")
    s = ing.sections(ing.html_to_text(page), ["5.02"])
    assert not s["5.02"]["fallback"] and "terminated the employment" in s["5.02"]["text"] and "Financial Statements and Exhibits" not in s["5.02"]["text"]
    assert kg.headline("5.02", s["5.02"]["text"]).startswith("8-K item 5.02: On June 28, 2026")


def test_an_item_the_sec_lists_but_the_text_does_not_head_falls_back_to_the_documents_start_and_says_so():
    s = ing.sections("An unusual layout with no item headings. The Board terminated the employment of the Chief Executive Officer.", ["5.02"])
    assert s["5.02"]["fallback"] and "terminated" in s["5.02"]["text"]
    assert ing.sections("", ["5.02"]) == {}


# ------------------------------------------------------------------ the classification rules (code only)

CASES_502 = [
    # (text, kind, severity)
    (CEO_FIRED, "leadership_crisis", "high"),
    ("On June 28, 2026, John Poe notified the Board that he resigned as Chief Executive Officer of the Company, effective immediately. His resignation was not the result of any disagreement with the Company.",
     "leadership_crisis", "high"),
    ("Mary Doe, the Company's Chief Financial Officer, has been placed on administrative leave pending the outcome of a review.", "leadership_crisis", "high"),
    ("The Audit Committee has commenced an investigation relating to the conduct of the Company's Chief Executive Officer.", "leadership_crisis", "high"),
    ("Mr. Poe resigned as Chairman of the Board. Mr. Poe resigned following a disagreement with the Board regarding the Company's strategy.", "leadership_crisis", "high"),
    ("The Board removed John Poe, the Company's founder, from his position as Chairman.", "leadership_crisis", "high"),
    ("Effective immediately, the Company's Chief Financial Officer, Mary Doe, ceased to serve in that role. The Company has begun a search for a successor.", "leadership_crisis", "high"),
    ("On November 11, 2026, the Board accepted the resignation of Jane Roe, as the Company's President, Chief Executive Officer and member of the Board, effective immediately. Following Ms. Roe's "
     "resignation, the Board appointed the Chief Financial Officer as interim Chief Executive Officer. The Board also appointed Sam Lee as Chair. Mr. Lee has been the Managing Partner of a private family "
     "office since 2004.", "leadership_crisis", "high"),                                      # real shape found on the first real run: a reason word in a later biography must not hide it
    ("The Board terminated the employment of Mr. Poe as Chief Executive Officer, effective today. Mr. Poe had served since 2019.", "leadership_crisis", "high"),             # "Mr." ends no sentence
    ("On October 22, 2026, the Company amended its Executive Severance Plan to remove the Company's Chief Executive Officer as a participant and terminated the individual change of control agreements. Upon a "
     "termination without cause or a resignation for good reason within 24 months following a change in control, the Chief Executive Officer is entitled to a cash payment.", "management_change", "medium"),         # not a crisis
    # not a shock (shapes found on the real run: a compensation plan, and another person's termination date next to the words "CEO onboarding")
    ("The Board adopted the Executive Severance Plan. Participants, including the Chief Executive Officer, are eligible for benefits if terminated without cause.", "management_change", "low"),
    ("Shaun Andrews, Executive Vice President, Chief Marketing Officer, is leaving the Company. In consideration of his completion of CEO onboarding support, the Committee approved the accelerated "
     "vesting of an award. All amounts due in connection with his termination will be subject to a release of claims.", "management_change", "medium"),      # not a crisis (medium is the known imprecision of a nearby "CEO")
    ("John Poe, the Company's Chief Executive Officer, will retire effective December 31, 2026. The Board appointed Jane Roe as Chief Executive Officer, effective January 1, 2027.", "management_change", "medium"),
    ("Mary Doe notified the Company that she resigned as Chief Financial Officer, effective immediately, to pursue other opportunities.", "management_change", "medium"),
    ("John Poe resigned as Chief Executive Officer for health reasons, effective immediately, and will remain as a director.", "management_change", "medium"),
    ("The Board appointed Mary Doe as Chief Financial Officer, effective July 15, 2026.", "management_change", "low"),
    ("An independent director, Sam Lee, resigned from the Board effective immediately. His resignation was not due to a disagreement.", "management_change", "low"),
    ("Sam Lee resigned as chair of the audit committee, effective immediately.", "management_change", "low"),
    ("In connection with the appointment, the Company terminated the prior employment agreement with the Chief Executive Officer and entered into a new agreement.", "management_change", "low"),
    ("The Board approved the Company's 2026 Equity Incentive Plan, subject to stockholder approval.", "routine", "low"),
]
CASES_401 = [
    (AUD_RESIGNED, "auditor_resignation", "high"),
    ("The Audit Committee approved the engagement of EY. Deloitte, the Company's current independent registered public accounting firm, will continue until the audit is complete and is dismissed effective upon "
     "completion. There were (i) no \"disagreements\" within the meaning of Item 304(a)(1)(iv) of Regulation S-K, which disagreements, if not resolved, would have caused Deloitte to make reference thereto; and "
     "(ii) no \"reportable events\". Neither the Company nor anyone on its behalf has consulted with EY regarding: (i) the application of accounting principles; (ii) any matter that was the subject of a "
     "\"disagreement\"; or (iii) any \"reportable event\" within the meaning of Item 304(a)(1)(v).", "routine", "low"),       # real shape (a planned change of auditor): the line about the NEW auditor is no disagreement
    ('On June 25, 2026, the Audit Committee dismissed Example Audit LLP ("EA") as the Company\'s independent registered public accounting firm. There were no disagreements with EA on any matter of '
     'accounting principles or practices, which disagreements, if not resolved to the satisfaction of EA, would have caused it to make reference thereto in its reports. There were no reportable events.',
     "routine", "low"),
    ('On June 25, 2026, the Audit Committee dismissed Example Audit LLP as the Company\'s independent registered public accounting firm. During the fiscal year, the Company had a disagreement with EA '
     'regarding the accounting treatment of revenue recognition.', "auditor_resignation", "high"),
    ('On June 25, 2026, Example Audit LLP informed the Company that it declined to stand for re-election as the Company\'s independent registered public accounting firm. There were no disagreements.',
     "auditor_resignation", "medium"),
    ('Example Audit LLP was dismissed. EA advised the Company of the following reportable events: material weaknesses in internal control over financial reporting.', "auditor_resignation", "high"),
]


@pytest.mark.parametrize("text,kind,sev", CASES_502)
def test_item_502_rules(text, kind, sev):
    got = kg.classify_item("5.02", text)
    assert got[:2] == (kind, sev), got


@pytest.mark.parametrize("text,kind,sev", CASES_401)
def test_item_401_rules(text, kind, sev):
    got = kg.classify_item("4.01", text)
    assert got[:2] == (kind, sev), got


def test_item_402_is_always_an_accounting_concern_high_and_every_answer_is_on_the_closed_lists():
    assert kg.classify_item("4.02", NON_RELIANCE)[:2] == ("accounting_concern", "high")
    for item, cases in (("5.02", CASES_502), ("4.01", CASES_401)):
        for text, _k, _s in cases:
            k, s, why = kg.classify_item(item, text)
            assert k in classify.KINDS and s in classify.SEVERITIES and why


def test_the_headline_drops_the_printed_title_and_says_the_item():
    h = kg.headline("5.02", "Item 5.02 " + T502 + "\n" + CEO_FIRED)
    assert h.startswith("8-K item 5.02: On June 28, 2026") and "Departure of Directors" not in h and len(h) <= 230


# ------------------------------------------------------------------ the collector

def test_collect_stores_the_wanted_filings_once_and_a_second_look_fetches_no_document(con, root):
    client, _ = _client(_routes())
    r = ing.collect(con, root, [ENTRY], NOW, client=client)
    assert r["asked"] == 1 and r["stored"] == 3 and r["by_item"] == {"5.02": 1, "4.02": 1, "4.01": 1} and r["problems"] == []
    assert r["requests"] == 4                                                       # the index and three documents; nothing for the earnings 8-K, the 10-Q, the amendment or the old one
    files = sorted(p.name for p in kg.raw_dir(root).glob("*.json"))
    assert files == ["0001234567-26-000011.json", "0001234567-26-000012.json", "0001234567-26-000017.json"]
    rec = json.loads((kg.raw_dir(root) / files[0]).read_text(encoding="utf-8"))
    assert rec["isin"] == KEY and rec["cik"] == CIK and rec["accepted_utc"] == "2026-06-29T14:02:11" and set(rec["sections"]) == {"5.02"}
    assert con.execute("SELECT count(*) FROM sec_8k_s85 WHERE status='stored'").fetchone()[0] == 3
    before = {p.name: p.read_bytes() for p in kg.raw_dir(root).glob("*.json")}
    again = ing.collect(con, root, [ENTRY], NOW + timedelta(hours=3), client=client)               # due again (90 minutes passed): the index is read, no document is
    assert again["asked"] == 1 and again["stored"] == 0 and again["requests"] == r["requests"] + 1
    assert {p.name: p.read_bytes() for p in kg.raw_dir(root).glob("*.json")} == before
    assert con.execute("SELECT count(*) FROM sec_8k_s85").fetchone()[0] == 3
    soon = ing.collect(con, root, [ENTRY], NOW + timedelta(hours=3, minutes=5), client=client)    # asked five minutes ago: not due, no request at all
    assert soon["asked"] == 0 and soon["not_due"] == 1 and soon["requests"] == again["requests"]


def test_a_failed_document_is_retried_later_and_given_up_after_the_tries(con, root):
    routes = _routes()
    routes[_url("0001234567-26-000011")] = Resp("", 500)
    client, _ = _client(routes, retries=1)
    r = ing.collect(con, root, [ENTRY], NOW, client=client)
    assert r["stored"] == 2 and r["failed_documents"] == 1
    assert con.execute("SELECT status, tries FROM sec_8k_s85 WHERE accession='0001234567-26-000011'").fetchone() == ("fetch_failed", 1)
    routes[_url("0001234567-26-000011")] = _html(("5.02", T502, [CEO_FIRED]))
    r2 = ing.collect(con, root, [ENTRY], NOW + timedelta(hours=3), client=_client(routes)[0])
    assert r2["stored"] == 1 and con.execute("SELECT status FROM sec_8k_s85 WHERE accession='0001234567-26-000011'").fetchone()[0] == "stored"


def test_requests_are_paced_to_at_most_four_a_second_and_a_429_backs_off_then_succeeds(con, root):
    routes = _routes()
    routes[_url("0001234567-26-000012")] = [Resp("", 429, {"Retry-After": "7"}), _html(("4.02", T402, [NON_RELIANCE]))]
    client, clock = _client(routes)
    r = ing.collect(con, root, [ENTRY], NOW, client=client)
    assert r["stored"] == 3 and r["problems"] == []
    times = [c[2] for c in client._session.calls]
    assert len(times) == 5                                                            # four fetches and the one retried
    for k in range(len(times) - 3):                                                   # any four consecutive requests span at least 0.75 s: no more than 4 in a second
        assert times[k + 3] - times[k] >= 0.75 - 1e-9
    assert any(s >= 7 for s in clock.slept)                                           # Retry-After was honoured
    assert any("429" in x for x in client.log)


def test_a_403_waits_once_then_stops_the_run_with_a_visible_line_and_no_exception(con, root):
    client, clock = _client({ing.SUBMISSIONS.format(cik=CIK): Resp("", 403), ing.SUBMISSIONS.format(cik=7654321): _subs([], 7654321)})
    ents = [ENTRY, {"cik": 7654321, "isin": "ZZ0007654321", "symbol": "OTHR"}]
    r = ing.collect(con, root, ents, NOW, client=client)
    assert r["stored"] == 0 and r["stopped"] and "refused" in r["stopped"] and len(r["problems"]) == 1
    assert len(client._session.calls) == 2 and clock.slept and max(clock.slept) >= 10          # one patient retry, then stop; the second company was not asked
    assert con.execute("SELECT count(*) FROM sec_8k_cik_s85").fetchone()[0] == 0


def test_without_a_contact_nothing_is_requested(con, root, monkeypatch):
    monkeypatch.delenv("PFLAB_SEC_USER_AGENT")
    monkeypatch.setattr(ing.sec_edgar, "user_agent", lambda: ing.sec_edgar.DEFAULT_USER_AGENT)
    client = ing.Client(session=FakeSession({}), sleep=lambda s: None)
    r = ing.collect(con, root, [ENTRY], NOW, client=client)
    assert r["stored"] == 0 and r["stopped"] and client._session.calls == []


def test_the_contact_header_goes_only_in_the_request_and_never_into_a_log_a_row_a_file_or_a_message(con, root, caplog):
    caplog.set_level(logging.DEBUG)
    routes = _routes()
    routes[_url("0001234567-26-000011")] = ConnectionError(f"connection reset while sending headers User-Agent: {UA}")
    client, _ = _client(routes, retries=1)
    r = ing.collect(con, root, [ENTRY], NOW, client=client)
    assert all(c[1].get("User-Agent") == UA for c in client._session.calls)                      # it IS sent to the SEC
    marker = "zed.marker"
    blob = json.dumps(r, default=str) + repr(client) + " ".join(client.log) + caplog.text
    assert marker not in blob and "Zed Tester" not in blob
    for t in ("sec_8k_s85", "sec_8k_cik_s85"):
        assert marker not in json.dumps(con.execute(f"SELECT * FROM {t}").fetchall(), default=str)
    for p in kg.raw_dir(root).glob("*"):
        assert marker not in p.read_text(encoding="utf-8")
    assert any("<contact>" in x for x in client.log) or "<contact>" in blob


# ------------------------------------------------------------------ the graph

def _filled_root(root, con, extra=()):
    ing.collect(con, root, [ENTRY], NOW, client=_client(_routes())[0])
    for rec in extra:
        ing.write_raw(root, rec)
    return root


def _raw(accn, items, accepted, filed, key=KEY, cik=CIK):
    return {"version": 1, "accession": accn, "cik": cik, "isin": key, "symbol": "EXDY", "company": CO, "filed": filed, "accepted_utc": accepted, "items_listed": ",".join(items), "form": "8-K",
            "doc_url": "x", "sections": {i: "Item " + i + " title\n" + CEO_FIRED for i in items}, "fallback_items": []}


def test_the_graph_makes_one_event_per_filing_and_item_with_the_acceptance_time_in_ist_and_the_cik_key(root, con):
    _filled_root(root, con)
    g = kb.build(root, ASOF, groups=GROUPS)
    ev = g["event"]
    sec = ev[ev["source"].str.startswith("SEC EDGAR 8-K item ")]
    assert sorted(sec["source"]) == ["SEC EDGAR 8-K item 4.01", "SEC EDGAR 8-K item 4.02", "SEC EDGAR 8-K item 5.02"]
    a = sec[sec["ref"] == "0001234567-26-000011"].iloc[0]
    assert (a["isin"], a["kind"], a["severity"], a["ts_rule"]) == (KEY, "leadership_crisis", "high", "release_time")
    assert a["ts"] == datetime(2026, 6, 29, 19, 32, 11) and a["event_date"] == date(2026, 6, 29)                    # 14:02:11 UTC is 19:32:11 IST
    assert a["link_rule"] == "sec:cik_pseudo_isin" and "CIK 0001234567" in a["link_proof"] and "0001234567-26-000011" in a["link_proof"]
    kinds = dict(zip(sec["source"], zip(sec["kind"], sec["severity"])))
    assert kinds["SEC EDGAR 8-K item 4.02"] == ("accounting_concern", "high") and kinds["SEC EDGAR 8-K item 4.01"] == ("auditor_resignation", "high")
    n = g["node"][g["node"]["isin"] == KEY].iloc[0]
    assert n["name"] == CO and n["origin"] == "us_filing" and n["symbol"] == "EXDY"
    assert g["stats"]["sec_8k_events"] == 3 and g["stats"]["sec_8k_files"] == 3
    assert (g["event"][~g["event"]["source"].str.startswith("SEC EDGAR")]["isin"] != KEY).all()                     # the Indian rows are as before


def test_the_rebuild_is_byte_identical_and_the_nightly_audit_passes_with_us_filings_in_the_graph(root, con):
    _filled_root(root, con, [_raw("0001234567-26-000020", ["5.02"], "2026-06-30T21:00:00.000", "2026-06-30")])     # accepted 02:30 IST on 1 July: before that day's open, so in this build
    g1, g2 = kb.build(root, ASOF, groups=GROUPS), kb.build(root, ASOF, groups=GROUPS)
    assert kb.hash_tables(g1) == kb.hash_tables(g2)
    assert (g1["event"]["ref"] == "0001234567-26-000020").any()
    res = audit.run_audit(_audit_con(), root, ASOF, graph=g1, store=False)
    bad = {c["name"]: c for c in res["checks"] if c["gating"] and not c["passed"]}
    assert not bad, bad


def test_point_in_time_a_filing_accepted_after_the_next_indian_open_is_not_in_the_graph_yet(root, con):
    late = _raw("0001234567-26-000021", ["5.02"], "2026-07-01T05:00:00.000", "2026-07-01")                          # 10:30 IST on 1 July, after the 09:15 open
    _filled_root(root, con, [late])
    g = kb.build(root, ASOF, groups=GROUPS)
    assert not (g["event"]["ref"] == "0001234567-26-000021").any() and g["stats"]["sec_8k_after_asof"] == 1
    assert (kb.build(root, date(2026, 7, 1), groups=GROUPS)["event"]["ref"] == "0001234567-26-000021").any()      # the next day's build has it
    assert kg.known_by(ASOF) == datetime(2026, 7, 1, 9, 15)


def test_a_filing_with_no_acceptance_time_is_used_from_the_next_us_trading_open_a58(root, con):
    friday = _raw("0001234567-26-000022", ["4.02"], None, "2026-06-26")
    _filled_root(root, con, [friday])
    g = kb.build(root, ASOF, groups=GROUPS)
    r = g["event"][g["event"]["ref"] == "0001234567-26-000022"].iloc[0]
    assert r["ts_rule"] == ft.RULE_DERIVED and r["ts"] == ft.next_open(date(2026, 6, 26), "US") and r["ts"].date() == date(2026, 6, 29)    # Friday -> Monday's US open
    assert r["event_date"] == date(2026, 6, 26) and "no acceptance time" in r["link_proof"] and r["link_rule"].endswith("_no_acceptance_time")
    res = audit.run_audit(_audit_con(), root, ASOF, graph=g, store=False)
    checks = {c["name"]: c for c in res["checks"]}
    assert checks["derived_time_rule"]["passed"] and checks["point_in_time"]["passed"], (checks["derived_time_rule"], checks["point_in_time"])
    on_asof = _raw("0001234567-26-000023", ["4.02"], None, "2026-06-30")                                            # dated today: its time is tomorrow evening's US open
    ing.write_raw(root, on_asof)
    assert not (kb.build(root, ASOF, groups=GROUPS)["event"]["ref"] == "0001234567-26-000023").any()


def test_an_unreadable_raw_file_is_counted_never_fatal(root, con):
    _filled_root(root, con)
    (kg.raw_dir(root) / "broken.json").write_text("{not json", encoding="utf-8")
    assert kb.build(root, ASOF, groups=GROUPS)["stats"]["sec_8k_unreadable"] == 1


def test_a_graph_with_no_us_filings_is_unchanged(root):
    g = kb.build(root, ASOF, groups=GROUPS)
    assert g["stats"]["sec_8k_events"] == 0 and (g["node"]["origin"] != "us_filing").all()


# ------------------------------------------------------------------ the store: the loop sees it at once

def _graph_on(con, monkeypatch, passed=True):
    monkeypatch.setenv("PFLAB_KG2", "on")
    day = markets.get("IN").session_closed_by(NOW)
    con.execute("INSERT INTO kg2_audit VALUES (?,?,?,?)", [day, passed, "[]", NOW])


def test_new_events_reach_the_store_at_once_when_the_graph_is_loaded_and_never_twice(root, con, monkeypatch):
    _filled_root(root, con)
    assert ing.sync_store(con, root, NOW) == {"graph_loaded": False}                       # the graph's switch is off or its audit has not passed: nothing is readable
    _graph_on(con, monkeypatch)
    r = ing.sync_store(con, root, NOW)
    assert r == {"graph_loaded": True, "events_added": 3, "nodes_added": 1}
    assert ing.sync_store(con, root, NOW)["events_added"] == 0
    rows = con.execute("SELECT source, kind, severity FROM kg2_event WHERE isin=? ORDER BY source", [KEY]).fetchall()
    assert rows == [("SEC EDGAR 8-K item 4.01", "auditor_resignation", "high"), ("SEC EDGAR 8-K item 4.02", "accounting_concern", "high"), ("SEC EDGAR 8-K item 5.02", "leadership_crisis", "high")]
    nightly = kb.build(root, ASOF, groups=GROUPS)["event"]                                  # the nightly rebuild makes the same rows: the store's ids match the build's
    assert set(nightly[nightly["isin"] == KEY]["event_id"]) == {r[0] for r in con.execute("SELECT event_id FROM kg2_event WHERE isin=?", [KEY]).fetchall()}


def test_a_failed_audit_means_nothing_is_added(root, con, monkeypatch):
    _filled_root(root, con)
    _graph_on(con, monkeypatch, passed=False)
    assert ing.sync_store(con, root, NOW) == {"graph_loaded": False}
    assert con.execute("SELECT count(*) FROM kg2_event").fetchone()[0] == 0


def test_the_watch_reader_finds_a_us_filing_under_the_key_the_book_holds_it_by(root, con, monkeypatch):
    _filled_root(root, con)
    _graph_on(con, monkeypatch)
    ing.sync_store(con, root, NOW)
    since, until = datetime(2026, 6, 26), NOW
    assert {e["kind"] for e in kev.material_events(con, [KEY], since, until)} == {"leadership_crisis", "accounting_concern", "auditor_resignation"}
    real, sym = "US0000000042", "US:EXDY"
    con.execute("INSERT INTO instrument_alias VALUES (?,?,?)", [KEY, real, date(2026, 1, 1)])
    con.execute("INSERT INTO instrument_alias VALUES (?,?,?)", [sym, KEY, date(2026, 1, 1)])
    for held in (real, sym):                                                                 # a real ISIN, or the symbol key, both reach the CIK key's events
        ev = kev.material_events(con, [held], since, until)
        assert len(ev) == 3 and {e["isin"] for e in ev} == {held}
    assert kev.material_events(con, ["INE000X00000"], since, until) == []                    # an Indian ISIN with no alias is unchanged
    assert {e["kind"] for e in kev.material_events(con, [real], since, datetime(2026, 6, 29, 12, 0))} == {"accounting_concern"}      # time-filtered by `until`: only the 26 June filing by then


def test_the_thinking_loops_thesis_signal_sees_a_us_filing_on_a_held_name(root, con, monkeypatch):
    from pflab.think import watch
    _filled_root(root, con)
    _graph_on(con, monkeypatch)
    ing.sync_store(con, root, NOW)
    entry = {"isin": "US:EXDY", "symbol": "EXDY", "name": "EXDY", "market": "US", "exposure_inr": 1000.0, "exposure_pct": 0.01, "why": "held", "held": True}
    con.execute("INSERT INTO instrument_alias VALUES (?,?,?)", ["US:EXDY", KEY, date(2026, 1, 1)])
    sigs = watch._thesis_signals(con, [entry], date(2026, 6, 30), NOW, watch.settings())
    assert {s["detail"]["kind"] for s in sigs} == {"leadership_crisis", "accounting_concern", "auditor_resignation"} and all(s["signal"] == "thesis_event" for s in sigs)


# ------------------------------------------------------------------ whom to ask

def _us_name(con, isin, sym, etf=False):
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at, market) VALUES (?, 'pseudo', ?, 'FOREIGN', TRUE, ?, ?, 'synthetic', now(), 'US')",
                [isin, "etf" if etf else "equity", sym, sym + " Inc"])


def test_the_scope_is_the_us_names_picked_skipped_or_held_never_a_fund_and_the_sp500_is_a_switch(con, tmp_path):
    _us_name(con, "ZZ0000000101", "PICK")
    _us_name(con, "ZZ0000000102", "SKIP")
    _us_name(con, "ZZ0000000103", "FUND", etf=True)
    for k, (isin, sym) in enumerate((("ZZ0000000101", "PICK"), ("ZZ0000000103", "FUND"))):
        con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, state, proposed_on) VALUES (?, 'US', ?, ?, 'held', ?)", [k + 1, isin, sym, date(2026, 6, 1)])
    con.execute("INSERT INTO skips_s83 (skip_id, market, isin, symbol, why, skipped_on) VALUES (1, 'US', 'US:SKIP', 'SKIP', 'too pricey', ?)", [date(2026, 6, 10)])
    ciks = {"SKIP": 102, "PICK": 101, "FUND": 103, "AAAA": 201, "BBBB": 202}
    out = ing.scope_entries(con, ASOF, tmp_path, "book", ciks=ciks)
    assert [(e["cik"], e["isin"]) for e in out] == [(101, "ZZ0000000101"), (102, "ZZ0000000102")]                  # the skipped name (symbol key) is asked by its CIK; the fund is not asked
    html = "<table><tr><th>Symbol</th></tr><tr><td>AAAA</td></tr><tr><td>BBBB</td></tr><tr><td>PICK</td></tr></table>"
    wide = ing.scope_entries(con, ASOF, tmp_path, "sp500", ciks=ciks, get_html=lambda u: html)
    assert [e["cik"] for e in wide] == [101, 102, 201, 202]
    assert ing.scope_entries(con, ASOF, tmp_path, "book", ciks=ciks) == out                                          # the default stays the book


def test_the_scope_setting_defaults_to_the_book_and_reads_core_toml():
    assert ing.scope_setting() == "book"
    from pflab import think
    assert think.settings()["sec_scope"] == "book"


# ------------------------------------------------------------------ the job

def test_the_job_end_to_end_with_a_fake_sec_stores_events_and_reports_counts(root, con, monkeypatch):
    _graph_on(con, monkeypatch)
    client, _ = _client(_routes())
    r = ing.run_job(con, root, NOW, client=client, entries=[ENTRY], force=True)
    assert r["stored"] == 3 and r["scope"] == "book" and r["graph"]["events_added"] == 3 and r["problems"] == []
    assert con.execute("SELECT count(*) FROM kg2_event WHERE isin=?", [KEY]).fetchone()[0] == 3


def test_the_job_skips_with_a_reason_when_there_is_nobody_to_ask_and_when_the_window_is_closed(root, con):
    assert "no US name" in ing.run_job(con, root, NOW, entries=[], force=True)["skipped"]
    saturday = datetime(2026, 6, 27, 14, 0)                                                      # 04:30 on Saturday in New York
    assert "no filings" in ing.run_job(con, root, saturday, entries=[ENTRY], last_success=saturday - timedelta(hours=2))["skipped"]
    assert ing.due_window(con, saturday, saturday - timedelta(hours=8)) is None                    # the app just started after a gap: it catches up
    assert ing.due_window(con, NOW, NOW - timedelta(hours=2)) is None                              # Tuesday 10:30 in New York: inside the SEC's hours


def test_the_job_is_registered_disabled_without_a_contact_and_follows_the_app_open_rule(monkeypatch):
    from pflab.service import tasks, ondemand  # noqa: F401  (registers every job)
    from pflab.service.jobs import REGISTRY, Ctx
    job = REGISTRY["sec_8k"]
    ctx = Ctx(con=None, now=NOW, pm_dir=None, data_root=None, repo=None)
    assert job.enabled_fn(ctx)[0] is True
    monkeypatch.delenv("PFLAB_SEC_USER_AGENT")
    monkeypatch.setattr("pflab.us.instruments.sec_contact_configured", lambda: False)
    ok, why = job.enabled_fn(ctx)
    assert ok is False and "user_agent" in why
    assert ondemand.MAX_AGE_H["sec_8k"] == 3
    from pflab.app import world
    assert world.GROUP_OF["sec_8k"] == "filings"


def test_the_migration_creates_the_two_tables_in_its_range(con):
    mine = [m for m in collect_migrations() if m[1].startswith("sec_8k")]
    assert [m[0] for m in mine] == [275, 276]
    for t in ("sec_8k_s85", "sec_8k_cik_s85"):
        assert con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name=?", [t]).fetchone()[0] == 1
