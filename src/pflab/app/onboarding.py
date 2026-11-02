"""The first conversation (S67 local). A new profile knows nothing about him, like a new Claude account: chat works from the first click, and
the system says plainly what it does not know yet and asks ONCE, in one grouped question, for the few things only he can give. As it
reads his sources the list of unknowns shrinks by itself (each line is computed from the store, never typed).

Nothing here guesses: a goal, a horizon or a risk limit is unknown until he answers. A profile that already has accounts (the running
app) gets no welcome.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

AGENT = "companion"
KEY = "onboarding:welcome"

WELCOME = (
    "Hello. I know nothing about you yet, and I will not guess. I read only what you give me: the files you drop in Inbox and files, and "
    "your broker through Kite (read-only) when you log in. Everything I say will be marked as checked, estimated or unknown. To start, "
    "please tell me in one reply: (1) what the money is for and by when (for example a PhD in 2028, a house, nothing in particular); "
    "(2) how much of it must stay untouched as cash; (3) the largest fall you could accept without wanting to sell; (4) any account "
    "that holds money which you will NOT add now (inactive, no login), so I write it down as left out instead of asking again. "
    "The list of what to bring is on the World screen under 'What to bring'. Answer in plain words; skip what you do not know."
)

# What he can bring, in the order that unlocks the most first. Each item says what it is, why, and where it comes from; the state is computed from
# what the system already holds, never typed. `kinds` are inbox kinds (app/inbox.py KIND_LABEL).
BRING = [
    ("tradebook", "Zerodha Console tradebook, every year you traded", "every buy and sell: this builds your holdings and the tax lots",
     "console.zerodha.com > Reports > Tradebook (one file per financial year)", ("tradebook",)),
    ("funds", "Zerodha Console funds ledger", "cash in and out of the broker: needed for what is free to invest",
     "console.zerodha.com > Reports > Ledger", ("funds_ledger",)),
    ("contract_notes", "Zerodha contract notes (PDF), if you have them", "exact charges and settlement dates per trade",
     "Zerodha's emails or Console > Reports > Contract notes", ("contract_note",)),
    ("cas", "Depository statement (CAS) from NSDL or CDSL / CAMS", "every mutual fund, share and bond in your name, whichever broker holds it",
     "nsdl.co.in or cdslindia.com (CAS), or camsonline.com / kfintech.com", ("cas",)),
    ("bank", "A bank statement for each bank account you want counted", "salary, SIPs, transfers to the broker and deposits",
     "your bank's net banking > Statements (PDF or Excel; the file password is asked for by name)", ("bank",)),
    ("fd", "Fixed deposit interest certificate or statement for each deposit", "principal, rate and maturity: the plans use them",
     "your bank's net banking > Deposits > Interest certificate", ("fd_certificate",)),
    ("screens", "Screenshots of anything you cannot download", "an app screen showing a holding, an FD or a balance is read like a file",
     "paste it (Ctrl+V) or drop the image in Inbox and files", ("screenshot",)),
    ("gift", "GIFT City / US statements, if you hold US stocks", "the small US sleeve",
     "your GIFT City broker's statements", ("gift_city",)),
]


def bring_list(con) -> List[dict]:
    """What the system still needs from him, with what it already holds. State: have | missing. A line he does not need (no US stocks, no
    contract notes) is simply left missing: it never blocks anything, and he can say so in the chat."""
    from pflab.ledger import system
    if system.active():                                      # S77: the account is the system's own: no statements, deposits or forms; only the Kite login feeds it
        return [{"id": "kite", "what": "Log in to Kite each trading morning", "why": "read-only: live prices for what the system holds; it can never place an order",
                 "where": "the Log in to Kite button", "state": "missing", "detail": "once per trading day"}]
    have = {}
    try:
        have = {k: n for k, n in con.execute("SELECT kind, count(*) FROM inbox_items WHERE status <> 'removed' GROUP BY 1").fetchall()}
    except Exception:
        pass
    out = []
    for key, what, why, where, kinds in BRING:
        n = sum(int(have.get(k, 0)) for k in kinds)
        out.append({"id": key, "what": what, "why": why, "where": where, "state": "have" if n else "missing",
                    "detail": f"{n} file(s) in Inbox" if n else "not given yet"})
    n_fd = 0
    try:
        n_fd = int(con.execute("SELECT count(*) FROM fds").fetchone()[0])
    except Exception:
        pass
    out.append({"id": "fd_form", "what": "Each fixed deposit once, in Setup's deposit form", "why": "the system checks it against the bank's maturity amount",
                "where": "Settings > Open Setup > deposits", "state": "have" if n_fd else "missing", "detail": f"{n_fd} deposit(s) entered" if n_fd else "none entered yet"})
    out.append({"id": "ipos", "what": "Each IPO allotment once, in Setup's IPO form", "why": "an allotment is in no statement until it is listed",
                "where": "Settings > Open Setup > IPOs", "state": "missing", "detail": "only if you applied to IPOs"})
    out.append({"id": "passwords", "what": "The password of each locked file", "why": "so the system can open it on this PC",
                "where": "Settings > Keys and passwords, under the name it gives; it asks only when a file is locked", "state": "missing",
                "detail": "asked by name when needed"})
    out.append({"id": "kite", "what": "Log in to Kite each trading morning", "why": "read-only: holdings, cash and trades; it can never place an order",
                "where": "the Log in to Kite button", "state": "missing", "detail": "once per trading day"})
    out.append({"id": "answers", "what": "One reply to the first question, and how much you add each month", "why": "the goal, the cash to keep and the fall you can accept are yours",
                "where": "Needs from you", "state": "have" if con.execute("SELECT count(*) FROM memory WHERE kind='answer' AND subject LIKE 'onboarding:%'").fetchone()[0] else "missing",
                "detail": "answered" if con.execute("SELECT count(*) FROM memory WHERE kind='answer' AND subject LIKE 'onboarding:%'").fetchone()[0] else "not answered yet"})
    return out


def unknowns(con) -> List[str]:
    """What the system does not know yet, from the store."""
    out = []
    n = lambda sql: con.execute(sql).fetchone()[0]
    if not n("SELECT count(*) FROM accounts"):
        out.append("which accounts you have: none have been read yet")
    elif not n("SELECT count(*) FROM events"):
        out.append("what happened in your accounts: no transactions have been read yet")
    if not n("SELECT count(*) FROM memory WHERE kind='answer' AND subject LIKE 'onboarding:%'"):
        out.append("your goals, the cash that must stay untouched and the fall you can accept: you have not told me yet")
    if not n("SELECT count(*) FROM prices"):
        out.append("market prices: none collected yet")
    return out


def is_new(con) -> bool:
    return not con.execute("SELECT count(*) FROM accounts").fetchone()[0] and not con.execute("SELECT count(*) FROM events").fetchone()[0]


def welcome(con, now: datetime) -> Optional[int]:
    """Queue the one grouped first question for a new, activated profile. None when it is not new, is still waiting for the icon, or
    the question was already asked."""
    from pflab import activation
    from pflab.agents import questions
    if activation.is_pending() or not is_new(con):
        return None
    return questions.ask(con, AGENT, KEY, WELCOME, now)


def briefing(con) -> dict:
    """For the dashboard and the chat's status tool: empty when nothing is unknown."""
    u = unknowns(con)
    return {"new": is_new(con), "unknown": u, "bring": bring_list(con),
            "say": ("I am new here: " + "; ".join(u[:3])) if u and is_new(con) else None}
