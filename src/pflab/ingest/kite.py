"""Read-only Kite Connect client (PLAN S4). The system never places, modifies or cancels an order.

`ReadOnlyKite` is an ALLOWLIST over the official `kiteconnect` SDK: only the names in `READ` and
`AUTH` reach it. Every order, GTT, mutual-fund order/SIP and position-conversion method is in
`FORBIDDEN` and raises `TradingForbidden` the moment it is accessed; order-shaped calculators
(`order_margins`, `basket_order_margins`, `get_virtual_contract_note`) are forbidden too, so no
order payload ever leaves this process. A method the SDK adds that is in none of the sets raises
as unknown, and `tests/test_ingest_kite.py` fails until someone classifies it. This is the only
module in `src/` allowed to import `kiteconnect`.

Daily login: the access token expires about 06:00 the next day and automating the login (TOTP) is
against Zerodha's terms, so `LoginFlow` only builds the login URL and exchanges the request token
the dashboard's /kite/callback receives (S30). The token lives in `%USERPROFILE%\\.pflab`, outside
the repo.
"""
from __future__ import annotations

import json
import secrets as _secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import quote

import pandas as pd

READ = frozenset({
    "holdings", "positions", "trades", "margins", "quote", "ltp", "ohlc", "historical_data", "instruments",
    "mf_holdings", "mf_instruments", "mf_orders", "mf_sips", "orders", "order_history", "order_trades",
    "profile", "get_gtts", "get_gtt", "get_auction_instruments", "trigger_range",
})
AUTH = frozenset({"login_url", "generate_session", "set_access_token", "set_session_expiry_hook"})
FORBIDDEN = frozenset({
    "place_order", "modify_order", "cancel_order", "exit_order", "place_autoslice_order",
    "place_gtt", "modify_gtt", "delete_gtt",
    "place_mf_order", "cancel_mf_order", "place_mf_sip", "modify_mf_sip", "cancel_mf_sip",
    "convert_position",
    "order_margins", "basket_order_margins", "get_virtual_contract_note",
    "invalidate_access_token", "invalidate_refresh_token", "renew_access_token",
})
TOKEN_EXPIRY_HOUR = 6


class TradingForbidden(RuntimeError):
    """The system has no trading path (PLAN §1)."""


class ReadOnlyKite:
    def __init__(self, api_key: str, access_token: Optional[str] = None, factory: Optional[Callable] = None):
        if factory is None:
            from kiteconnect import KiteConnect as factory      # the only import of the SDK in src/
        self._k = factory(api_key=api_key, access_token=access_token)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in FORBIDDEN:
            raise TradingForbidden(f"Kite.{name} is forbidden: this system never places or changes orders, GTTs, "
                                   "SIPs or positions. The investor places every trade himself.")
        if name in READ or name in AUTH:
            return getattr(self._k, name)
        raise AttributeError(f"Kite.{name} is not classified: add it to READ, AUTH or FORBIDDEN in "
                             "pflab/ingest/kite.py after reading what it does")


# --- token and login -----------------------------------------------------------------------------------------

def default_token_path() -> Path:
    return Path.home() / ".pflab" / "kite_token.json"


def token_expiry(created: datetime) -> datetime:
    """Zerodha access tokens lapse at about 06:00 the next day."""
    nxt = datetime.combine(created.date() + timedelta(days=1), time(TOKEN_EXPIRY_HOUR))
    return nxt if created.time() >= time(TOKEN_EXPIRY_HOUR) else datetime.combine(created.date(), time(TOKEN_EXPIRY_HOUR))


class TokenStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_token_path()

    def save(self, access_token: str, now: datetime) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"access_token": access_token, "created_at": now.isoformat()}), encoding="utf-8")

    def load(self, now: datetime) -> Optional[str]:
        """The token if it exists and has not lapsed, else None (EOD data only, flagged)."""
        if not self.path.exists():
            return None
        d = json.loads(self.path.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(d["created_at"])
        return d["access_token"] if now < token_expiry(created) else None


class LoginError(RuntimeError):
    pass


class LoginFlow:
    """Two steps around the browser: `begin` -> the URL the investor opens; `finish` <- the callback query."""

    def __init__(self, secrets, store: Optional[TokenStore] = None, factory: Optional[Callable] = None):
        self.secrets, self.store, self.factory = secrets, store or TokenStore(), factory
        self._state: Optional[str] = None

    def begin(self) -> str:
        kite = ReadOnlyKite(self.secrets.get("kite", "api_key"), factory=self.factory)
        self._state = _secrets.token_urlsafe(16)
        return kite.login_url() + "&redirect_params=" + quote(f"state={self._state}", safe="")

    def finish(self, params: Dict[str, str], now: datetime) -> str:
        """Exchange the callback's request_token for an access token and store it. Refuses a callback whose
        status is not success or whose state does not match the one `begin` issued."""
        if params.get("status") != "success" or not params.get("request_token"):
            raise LoginError(f"Kite login did not succeed: {params.get('status')!r}")
        if self._state is None or params.get("state") != self._state:
            raise LoginError("login callback state does not match: ignoring it")
        kite = ReadOnlyKite(self.secrets.get("kite", "api_key"), factory=self.factory)
        data = kite.generate_session(params["request_token"], self.secrets.get("kite", "api_secret"))
        self.store.save(data["access_token"], now)
        self._state = None
        return data["access_token"]


def client(secrets, store: Optional[TokenStore] = None, now: Optional[datetime] = None,
           factory: Optional[Callable] = None) -> Optional[ReadOnlyKite]:
    """A logged-in read-only client, or None when there is no valid token today (the caller then falls back
    to end-of-day data and says so)."""
    from pflab import activation
    if activation.is_pending():                            # a fresh profile reaches no broker until the investor's first launch
        return None
    tok = (store or TokenStore()).load(now or datetime.now())
    return ReadOnlyKite(secrets.get("kite", "api_key"), tok, factory) if tok else None


# --- normalisers (pure; Kite's documented response shapes) -------------------------------------------------------

def holdings_frame(rows: List[dict]) -> pd.DataFrame:
    """kite.holdings() -> isin, symbol, exchange, qty (settled + T1), t1 (bought in the last sessions, not yet
    settled), avg_price, last_price, pledged. Checked on real data 2026-10-17: quantity + t1_quantity equals
    opening_quantity."""
    out = []
    for r in rows:
        t1 = float(r.get("t1_quantity", 0) or 0)
        qty = float(r.get("quantity", 0) or 0) + t1
        out.append(dict(isin=r.get("isin"), symbol=r.get("tradingsymbol"), exchange=r.get("exchange"), qty=qty, t1=t1,
                        avg_price=float(r.get("average_price", 0) or 0), last_price=float(r.get("last_price", 0) or 0),
                        pledged=float(r.get("collateral_quantity", 0) or 0)))
    return pd.DataFrame(out, columns=["isin", "symbol", "exchange", "qty", "t1", "avg_price", "last_price", "pledged"])


def funds_from_margins(m: dict) -> dict:
    """kite.margins() (equity segment) -> cash figures. `live_balance` is the account's cash now; `available.cash`
    read 0.00 on real data while the balance was not (2026-10-17: the S4 "margins shows 0" puzzle), so the
    balance, not that field, is compared with the ledger."""
    eq = m.get("equity", m)
    av = eq.get("available", {})
    return {"available_cash": float(av.get("cash", 0.0)), "opening_balance": float(av.get("opening_balance", 0.0)),
            "live_balance": float(av.get("live_balance", av.get("opening_balance", 0.0))),
            "net": float(eq.get("net", 0.0)), "utilised_debits": float((eq.get("utilised") or {}).get("debits", 0.0))}


def trades_frame(rows: List[dict], account: str) -> pd.DataFrame:
    """kite.trades() (today's executions) -> trade_id, order_id, date, symbol, side, qty, price, account."""
    out = []
    for r in rows:
        ts = r.get("fill_timestamp") or r.get("exchange_timestamp") or r.get("order_timestamp")
        d = ts.date() if isinstance(ts, datetime) else pd.Timestamp(ts).date()
        out.append(dict(trade_id=str(r["trade_id"]), order_id=str(r.get("order_id", "")), date=d,
                        symbol=r["tradingsymbol"], exchange=r.get("exchange"),
                        side="buy" if str(r["transaction_type"]).upper() == "BUY" else "sell",
                        qty=float(r["quantity"]), price=float(r["average_price"]), account=account))
    return pd.DataFrame(out, columns=["trade_id", "order_id", "date", "symbol", "exchange", "side", "qty", "price", "account"])


def day_frame(positions: dict) -> pd.DataFrame:
    """kite.positions() -> today's delivery (CNC) change per symbol: qty = day buys - day sells, with the day's buy and
    sell prices. Holdings carry the opening quantity until the next day, so this is what moves them today; intraday
    (MIS) trades end flat and are left out."""
    out = []
    for r in (positions or {}).get("net", []):
        if str(r.get("product", "")).upper() != "CNC":
            continue
        b, s = float(r.get("day_buy_quantity", 0) or 0), float(r.get("day_sell_quantity", 0) or 0)
        if b == s == 0:
            continue
        out.append(dict(symbol=r.get("tradingsymbol"), exchange=r.get("exchange"), qty=b - s,
                        buy_price=float(r.get("day_buy_price", 0) or 0), sell_price=float(r.get("day_sell_price", 0) or 0)))
    return pd.DataFrame(out, columns=["symbol", "exchange", "qty", "buy_price", "sell_price"])


def mf_frame(rows: List[dict]) -> pd.DataFrame:
    """kite.mf_holdings() (Coin) -> isin (Kite's tradingsymbol for a fund is its ISIN), symbol (the fund's name), qty,
    avg_price, last_price."""
    out = [dict(isin=r.get("tradingsymbol"), symbol=r.get("fund"), qty=float(r.get("quantity", 0) or 0),
                avg_price=float(r.get("average_price", 0) or 0), last_price=float(r.get("last_price", 0) or 0))
           for r in rows or [] if float(r.get("quantity", 0) or 0)]
    return pd.DataFrame(out, columns=["isin", "symbol", "qty", "avg_price", "last_price"])


def make_quote_fn(kite: ReadOnlyKite, symbol_by_isin: Dict[str, str], exchange: str = "NSE") -> Callable[[List[str]], Dict[str, float]]:
    """A `prices.LivePoller` quote function: isin list -> {isin: last price} through kite.ltp (1 request, up to 500
    instruments). ISINs with no known trading symbol are skipped, not guessed."""
    def quote_fn(isins: List[str]) -> Dict[str, float]:
        keys = {f"{exchange}:{symbol_by_isin[i]}": i for i in isins if i in symbol_by_isin}
        if not keys:
            return {}
        got = kite.ltp(*keys)
        return {keys[k]: float(v["last_price"]) for k, v in got.items() if k in keys and v.get("last_price")}
    return quote_fn
