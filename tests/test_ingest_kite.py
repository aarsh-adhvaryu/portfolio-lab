"""S4 build-ahead: the read-only Kite wrapper (no key needed), login/token logic with a FAKE SDK, response
normalisers on shapes from Kite's documentation, Console tradebook import, holdings reconciliation. All
fixtures are synthetic."""
import inspect
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from pflab.ingest import kite as k
from pflab.ingest import tradebook as tb
from pflab.ledger import reconcile as rc
from pflab.ledger.book import Ledger
from pflab.ledger.events import Event, EventLog
from pflab.pm import secrets as sec
from pflab.pm import store

SRC = Path(__file__).resolve().parents[1] / "src" / "pflab"


class FakeSDK:
    """Stands in for kiteconnect.KiteConnect: every public method records the call and returns a marker."""
    calls = []

    def __init__(self, api_key=None, access_token=None, **kw):
        self.api_key, self.access_token = api_key, access_token

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def method(*a, **kw):
            FakeSDK.calls.append(name)
            return ("called", name, a, kw)
        return method


@pytest.fixture(autouse=True)
def reset_calls():
    FakeSDK.calls = []


def ro():
    return k.ReadOnlyKite("KEY", "TOKEN", factory=FakeSDK)


# --- the allowlist -------------------------------------------------------------------------------------------

def sdk_methods():
    from kiteconnect import KiteConnect
    return {n for n, _ in inspect.getmembers(KiteConnect, predicate=inspect.isfunction) if not n.startswith("_")}


def test_every_sdk_method_is_classified_exactly_once():
    names = sdk_methods()
    classified = k.READ | k.AUTH | k.FORBIDDEN
    assert names - classified == set(), f"unclassified SDK methods (read them, then classify): {sorted(names - classified)}"
    assert not (k.READ & k.FORBIDDEN) and not (k.READ & k.AUTH) and not (k.AUTH & k.FORBIDDEN)
    assert classified - names == set(), f"stale names no longer in the SDK: {sorted(classified - names)}"


@pytest.mark.parametrize("name", sorted(k.FORBIDDEN))
def test_every_mutating_method_raises_and_never_reaches_the_sdk(name):
    w = ro()
    with pytest.raises(k.TradingForbidden, match="never places or changes"):
        getattr(w, name)
    with pytest.raises(k.TradingForbidden):
        getattr(w, name)("anything", order_type="MARKET")
    assert FakeSDK.calls == []


def test_the_forbidden_set_covers_everything_that_sounds_like_trading():
    trading = {n for n in sdk_methods() if re.search(r"place|modify|cancel|exit|delete|convert|order_margins|contract_note|invalidate|renew", n)
               and n not in ("orders", "order_history", "order_trades", "mf_orders")}
    assert trading <= k.FORBIDDEN, sorted(trading - k.FORBIDDEN)


@pytest.mark.parametrize("name", sorted(k.READ | k.AUTH))
def test_read_and_auth_methods_delegate(name):
    out = getattr(ro(), name)("x")
    assert out == ("called", name, ("x",), {}) and FakeSDK.calls == [name]


def test_unknown_methods_are_refused_until_classified():
    with pytest.raises(AttributeError, match="not classified"):
        ro().some_future_sdk_method
    with pytest.raises(AttributeError):
        ro()._k_secret


def test_only_the_wrapper_touches_the_sdk_and_nothing_calls_a_trading_method():
    offenders = []
    for p in SRC.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        if p.name != "kite.py" or p.parent.name != "ingest":
            if re.search(r"^\s*(from|import)\s+kiteconnect", text, re.M):
                offenders.append(f"{p}: imports kiteconnect")
        for name in k.FORBIDDEN:
            if re.search(rf"\.{name}\(", text) and not p.name.startswith("test"):
                offenders.append(f"{p}: calls .{name}(")
    assert offenders == []


def test_real_sdk_is_what_the_wrapper_builds_by_default():
    w = k.ReadOnlyKite("KEY")
    assert type(w._k).__name__ == "KiteConnect"
    with pytest.raises(k.TradingForbidden):
        w.place_order(variety="regular", exchange="NSE", tradingsymbol="X", transaction_type="BUY",
                      quantity=1, product="CNC", order_type="MARKET")


# --- login and token -------------------------------------------------------------------------------------------

class LoginSDK(FakeSDK):
    def login_url(self):
        return "https://kite.zerodha.com/connect/login?v=3&api_key=" + self.api_key

    def generate_session(self, request_token, api_secret):
        FakeSDK.calls.append(("session", request_token, api_secret))
        return {"access_token": "ACCESS-123", "user_id": "AB1234"}


SECRETS = sec.Secrets({"kite": {"api_key": "KEY", "api_secret": "SHHH"}})


def test_login_flow_round_trip_and_state_check(tmp_path):
    store_ = k.TokenStore(tmp_path / "tok.json")
    flow = k.LoginFlow(SECRETS, store_, LoginSDK)
    url = flow.begin()
    assert url.startswith("https://kite.zerodha.com/connect/login?v=3&api_key=KEY&redirect_params=state%3D")
    state = url.split("state%3D")[1]
    with pytest.raises(k.LoginError, match="did not succeed"):
        flow.finish({"status": "error"}, datetime(2026, 10, 7, 9, 0))
    with pytest.raises(k.LoginError, match="state does not match"):
        flow.finish({"status": "success", "request_token": "RT", "state": "forged"}, datetime(2026, 10, 7, 9, 0))
    assert store_.load(datetime(2026, 10, 7, 9, 1)) is None
    assert flow.finish({"status": "success", "request_token": "RT", "state": state}, datetime(2026, 10, 7, 9, 0)) == "ACCESS-123"
    assert ("session", "RT", "SHHH") in FakeSDK.calls and store_.load(datetime(2026, 10, 7, 9, 1)) == "ACCESS-123"
    with pytest.raises(k.LoginError):                                  # the state is single-use
        flow.finish({"status": "success", "request_token": "RT", "state": state}, datetime(2026, 10, 7, 9, 2))


def test_token_lapses_at_six_the_next_morning(tmp_path):
    s = k.TokenStore(tmp_path / "tok.json")
    s.save("T", datetime(2026, 10, 6, 10, 0))
    assert s.load(datetime(2026, 10, 7, 5, 59)) == "T" and s.load(datetime(2026, 10, 7, 6, 0)) is None
    s.save("E", datetime(2026, 10, 7, 5, 0))                           # logged in before 06:00: lapses at 06:00 the same day
    assert s.load(datetime(2026, 10, 7, 5, 59)) == "E" and s.load(datetime(2026, 10, 7, 6, 1)) is None
    assert k.TokenStore(tmp_path / "none.json").load(datetime(2026, 10, 7)) is None


def test_client_is_none_without_a_valid_token(tmp_path):
    s = k.TokenStore(tmp_path / "tok.json")
    assert k.client(SECRETS, s, datetime(2026, 10, 7, 9, 0), FakeSDK) is None
    s.save("T", datetime(2026, 10, 7, 8, 0))
    c = k.client(SECRETS, s, datetime(2026, 10, 7, 9, 0), FakeSDK)
    assert c is not None and c._k.access_token == "T"


# --- normalisers ----------------------------------------------------------------------------------------------------------

def test_holdings_funds_trades_shapes():
    h = k.holdings_frame([{"tradingsymbol": "ABC", "exchange": "NSE", "isin": "INE111A01011", "quantity": 10, "t1_quantity": 2,
                           "average_price": 100.5, "last_price": 110.0, "collateral_quantity": 0},
                          {"tradingsymbol": "GOLDBEES", "exchange": "NSE", "isin": "INF204KB17I5", "quantity": 5, "t1_quantity": 0,
                           "average_price": 60.0, "last_price": 61.0}])
    assert list(h["qty"]) == [12.0, 5.0] and list(h["isin"]) == ["INE111A01011", "INF204KB17I5"]
    assert list(h["t1"]) == [2.0, 0.0]
    f = k.funds_from_margins({"equity": {"net": 1500.5, "available": {"cash": 1400.0, "opening_balance": 1000.0},
                                          "utilised": {"debits": 99.5}}})
    assert f == {"available_cash": 1400.0, "opening_balance": 1000.0, "live_balance": 1000.0, "net": 1500.5,
                 "utilised_debits": 99.5}                       # no live_balance in the reply: the opening balance
    assert k.funds_from_margins({"equity": {"available": {"cash": 0, "opening_balance": 10.0, "live_balance": 7.5}}}
                                )["live_balance"] == 7.5
    t = k.trades_frame([{"trade_id": 123, "order_id": "9", "tradingsymbol": "ABC", "exchange": "NSE", "transaction_type": "BUY",
                         "quantity": 3, "average_price": 101.0, "fill_timestamp": datetime(2026, 10, 7, 10, 1)}], "ZER")
    assert t.iloc[0].to_dict() == {"trade_id": "123", "order_id": "9", "date": date(2026, 10, 7), "symbol": "ABC",
                                   "exchange": "NSE", "side": "buy", "qty": 3.0, "price": 101.0, "account": "ZER"}


def test_quote_fn_maps_isin_to_symbol_and_skips_unknown():
    class K:
        def ltp(self, *keys):
            K.keys = keys
            return {"NSE:ABC": {"last_price": 111.0}, "NSE:ZZZ": {"last_price": 0}}

    fn = k.make_quote_fn(K(), {"INE111A01011": "ABC", "INE222B01012": "ZZZ"})
    assert fn(["INE111A01011", "INE222B01012", "INE333C01013"]) == {"INE111A01011": 111.0}
    assert K.keys == ("NSE:ABC", "NSE:ZZZ") and fn(["INE333C01013"]) == {}


def test_quote_fn_feeds_the_live_poller(tmp_path):
    from pflab.pm import prices
    con = store.connect(tmp_path / "l.duckdb")

    class K:
        def ltp(self, *keys):
            return {"NSE:ABC": {"last_price": 123.5}}

    poller = prices.LivePoller(con, ["INE111A01011"], k.make_quote_fn(K(), {"INE111A01011": "ABC"}))
    assert poller.poll(datetime(2026, 10, 7, 10, 0)) == 1
    assert prices.latest_price(con, "INE111A01011", date(2026, 10, 7)).value == 123.5


# --- tradebook ----------------------------------------------------------------------------------------------------------------

CSV = """symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time
ABC,INE111A01011,2026-05-04,NSE,EQ,EQ,buy,false,10,100.50,T1,O1,2026-05-04T10:00:00
ABC,INE111A01011,2026-05-04,NSE,EQ,EQ,buy,false,5,101.00,T2,O1,2026-05-04T10:00:05
GOLDBEES,INF204KB17I5,2026-05-11,NSE,EQ,EQ,buy,false,100,60.00,T3,O2,2026-05-11T09:30:00
ABC,INE111A01011,2026-08-03,NSE,EQ,EQ,sell,false,12,120.00,T4,O3,2026-08-03T11:00:00
"""


def test_tradebook_parse_and_events_replay_to_lots():
    df = tb.parse(CSV)
    assert list(df["trade_id"]) == ["T1", "T2", "T3", "T4"] and df["isin"].iloc[0] == "INE111A01011"
    events, rep = tb.to_events(df, "ZER", tax_class_of=lambda i: "EQUITY")
    assert rep["events"] == 4 and rep["buy_value"] == pytest.approx(10 * 100.5 + 5 * 101 + 100 * 60) and rep["sell_value"] == 1440.0
    assert any("charges" in m for m in rep["missing"]) and any("deposits" in m for m in rep["missing"])
    log = EventLog([Event("deposit", "ZER", date(2026, 5, 1), amount=50_000.0), *events])
    led = Ledger.replay(log)
    assert led.holdings("INE111A01011") == 3 and led.holdings("INF204KB17I5") == 100
    assert [(c.acq_date, c.qty) for c in led.realised] == [(date(2026, 5, 4), 10), (date(2026, 5, 4), 2)]   # FIFO
    assert [e.ref for e in events] == ["T1", "T2", "T3", "T4"]


def test_tradebook_import_is_idempotent_by_trade_id():
    df = tb.parse(CSV)
    events, _ = tb.to_events(df, "ZER")
    again, rep = tb.to_events(df, "ZER", existing_refs={e.ref for e in events})
    assert again == [] and rep["skipped_existing"] == 4 and rep["events"] == 0
    part, rep = tb.to_events(df, "ZER", existing_refs={"T1", "T2"})
    assert [e.ref for e in part] == ["T3", "T4"] and rep["first_date"] == date(2026, 5, 11)


def _console_xlsx(path, drop_sheet_name=False):
    """Console's .xlsx layout: a Client ID preamble, then Title Case headers; trade ids as numbers."""
    import openpyxl
    import zipfile
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Client ID", "ZZ0001"])
    ws.append([])
    ws.append(["Symbol", "ISIN", "Trade Date", "Exchange", "Segment", "Series", "Trade Type", "Auction",
               "Quantity", "Price", "Trade ID", "Order ID", "Order Execution Time"])
    for line in CSV.strip().splitlines()[1:]:
        c = line.split(",")
        ws.append(c[:8] + [float(c[8]), float(c[9]), 900 + int(c[10][1:]), c[11], c[12]])
    wb.save(path)
    if drop_sheet_name:                       # the shape of a real Console export openpyxl refuses
        zin = zipfile.ZipFile(path)
        items = {i.filename: zin.read(i.filename) for i in zin.infolist()}
        zin.close()
        items["xl/workbook.xml"] = re.sub(rb'<sheet name="[^"]*" ', b"<sheet ", items["xl/workbook.xml"])
        with zipfile.ZipFile(path, "w") as zout:
            for name, data in items.items():
                zout.writestr(name, data)
    return path


@pytest.mark.parametrize("nameless", [False, True])
def test_tradebook_parses_console_xlsx_like_the_csv(tmp_path, nameless):
    p = _console_xlsx(tmp_path / "tradebook.xlsx", drop_sheet_name=nameless)
    before = p.read_bytes()
    df, ref = tb.parse(str(p)), tb.parse(CSV)
    assert list(df["trade_id"]) == ["901", "902", "903", "904"]
    cols = ["isin", "symbol", "date", "side", "qty", "price", "order_id", "exchange", "series"]
    pd.testing.assert_frame_equal(df[cols], ref[cols])
    assert p.read_bytes() == before           # the repair is in memory only


def test_tradebook_sets_ipo_allotments_aside_and_reports_them():
    ipo_line = "NEWCO,,2026-08-12,NSE,EQ,EQ,buy,false,15,1200,IPO,IPO,2026-08-12T09:30:00\n"
    df = tb.parse(CSV + ipo_line)
    assert list(df["trade_id"]) == ["T1", "T2", "T3", "T4"]
    assert df.attrs["ipo_allotments"] == [{"symbol": "NEWCO", "date": date(2026, 8, 12), "qty": 15,
                                           "price": 1200, "exchange": "NSE"}]
    events, rep = tb.to_events(df, "ZER")
    assert len(events) == 4 and rep["ipo_allotments"][0]["qty"] == 15
    assert any("IPO allotment" in m for m in rep["missing"])
    assert "ipo_allotments" not in tb.to_events(tb.parse(CSV), "ZER")[1]


def test_tradebook_xlsx_without_header_is_refused(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.append(["Client ID", "ZZ0001"])
    wb.save(tmp_path / "x.xlsx")
    with pytest.raises(tb.TradebookError, match="no header row"):
        tb.parse(str(tmp_path / "x.xlsx"))


@pytest.mark.parametrize("mutate,msg", [
    (lambda s: s.replace("trade_id,order_id", "tid,order_id"), "missing columns"),
    (lambda s: s.replace(",buy,false,10,", ",short,false,10,"), "unknown trade_type"),
    (lambda s: s.replace(",10,100.50,", ",0,100.50,"), "non-positive"),
    (lambda s: s.replace("INE111A01011,2026-05-04,NSE,EQ,EQ,buy,false,10", ",2026-05-04,NSE,EQ,EQ,buy,false,10"), "no ISIN"),
    (lambda s: s.replace("T2", "T1"), "duplicate trade_id"),
])
def test_tradebook_errors_are_loud(mutate, msg):
    with pytest.raises(tb.TradebookError, match=msg):
        tb.parse(mutate(CSV))


# --- holdings reconciliation (S4 acceptance logic) ----------------------------------------------------------------------------------

def test_kite_holdings_equal_ledger_holdings_is_no_breaks():
    events, _ = tb.to_events(tb.parse(CSV), "ZER")
    led = Ledger.replay(EventLog([Event("deposit", "ZER", date(2026, 5, 1), amount=50_000.0), *events]))
    kite_df = k.holdings_frame([{"tradingsymbol": "ABC", "isin": "INE111A01011", "quantity": 3, "t1_quantity": 0},
                                {"tradingsymbol": "GOLDBEES", "isin": "INF204KB17I5", "quantity": 100, "t1_quantity": 0}])
    src = dict(zip(kite_df["isin"], kite_df["qty"]))
    assert rc.holdings_breaks("kite", src, led.positions(), account="ZER").empty


def test_breaks_are_found_and_saved(tmp_path):
    led_pos = {("ZER", "INE111A01011"): 3.0, ("ZER", "INF204KB17I5"): 100.0, ("OTHER", "INE111A01011"): 50.0}
    b = rc.holdings_breaks("kite", {"INE111A01011": 4.0, "INE999Z01017": 7.0}, led_pos, account="ZER")
    got = b.set_index("isin")
    assert set(got.index) == {"INE111A01011", "INF204KB17I5", "INE999Z01017"}
    assert "differ by -1" in got.loc["INE111A01011", "note"] and "not at the source" in got.loc["INF204KB17I5", "note"]
    assert "not in the ledger" in got.loc["INE999Z01017", "note"]
    assert len(rc.holdings_breaks("kite", {"INE111A01011": 53.0}, led_pos)) == 1                     # all accounts: 3 + 50 = 53; gold missing at source
    con = store.connect(tmp_path / "l.duckdb")
    assert rc.save_breaks(con, b, "run-1") == 3
    assert con.execute("SELECT count(*) FROM recon_breaks WHERE status='open'").fetchone()[0] == 3
