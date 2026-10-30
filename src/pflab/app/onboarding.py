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
    "Hello. I know nothing about you yet, and I will not guess. I will read what you let me (your email for statements, your broker "
    "through Kite) and keep learning. Everything I say will be marked as checked, estimated or unknown. To start, please tell me in "
    "one reply: (1) what the money is for and by when (for example a PhD in 2028, a house, nothing in particular); (2) how much of it "
    "must stay untouched as cash; (3) the largest fall you could accept without wanting to sell; (4) any other mailbox or account "
    "that holds money (another bank, a second email, a broker) so I look there too. Answer in plain words; skip what you do not know."
)


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
    return {"new": is_new(con), "unknown": u,
            "say": ("I am new here: " + "; ".join(u[:3])) if u and is_new(con) else None}
