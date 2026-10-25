"""Daily Kite login and a read-only check against the ledger (PLAN S4).

    python tools/kite_login.py            # prints the login URL, waits up to 5 minutes for Kite's redirect

Listens on the redirect URL registered for the Kite app (secrets.toml [kite] redirect_url, default
http://127.0.0.1:5000/redirect), exchanges the request token for the day's access token (stored under
%USERPROFILE%\\.pflab), then makes READ-ONLY calls only: profile, holdings, funds. Holdings are reconciled with
the ledger's Zerodha account; differences are printed and saved as recon breaks. No order method is
reachable through the wrapper.
"""
from __future__ import annotations

import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from pflab.ingest import kite as k
from pflab.ledger import events as ev
from pflab.ledger import reconcile
from pflab.ledger.book import Ledger
from pflab.pm import secrets, store

ACCOUNT = "ZER"


def wait_for_token(flow: k.LoginFlow, redirect: str, timeout: int = 300) -> str:
    u = urlparse(redirect)
    got = {}
    done = threading.Event()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urlparse(self.path)
            if q.path != u.path:
                self.send_response(404)
                self.end_headers()
                return
            params = {a: b[0] for a, b in parse_qs(q.query).items()}
            try:
                got["token"] = flow.finish(params, datetime.now())
                msg = "Kite login done. You can close this tab."
            except Exception as e:
                got["error"] = str(e)
                msg = f"Kite login failed: {e}"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(msg.encode())
            done.set()

        def log_message(self, *a):
            pass

    srv = HTTPServer((u.hostname, u.port or 80), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        if not done.wait(timeout):
            raise TimeoutError("no redirect from Kite within the time limit")
    finally:
        srv.shutdown()
    if "error" in got:
        raise k.LoginError(got["error"])
    return got["token"]


def main() -> int:
    s = secrets.load()
    redirect = s.get("kite", "redirect_url") if s.has("kite", "redirect_url") else "http://127.0.0.1:5000/redirect"
    flow = k.LoginFlow(s)
    url = flow.begin()
    print(f"Open this URL and log in to Kite (it also opens in your browser):\n  {url}")
    webbrowser.open(url)
    wait_for_token(flow, redirect)
    kc = k.client(s)
    prof = kc.profile()
    print(f"Logged in: user {prof.get('user_id')}; broker {prof.get('broker')}")
    h = k.holdings_frame(kc.holdings())
    funds = k.funds_from_margins(kc.margins())
    print(f"Kite holdings: {len(h)} lines; available cash {funds['available_cash']:,.2f}")
    con = store.connect()
    led = Ledger.replay(ev.load(con))
    br = reconcile.holdings_breaks("kite", dict(zip(h["isin"], h["qty"])), led.positions(), account=ACCOUNT)
    if br.empty:
        print(f"PASS  Kite holdings = ledger {ACCOUNT} holdings ({len(h)} ISINs)")
    else:
        reconcile.save_breaks(con, br, f"kite-{datetime.now():%Y%m%dT%H%M%S}")
        print("FAIL  Kite holdings differ from the ledger:")
        print(br[["isin", "a_value", "b_value", "note"]].to_string(index=False))
    return 0 if br.empty else 1


if __name__ == "__main__":
    sys.exit(main())
