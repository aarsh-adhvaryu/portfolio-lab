"""The workshop's outward guard (S65): the beta checkout sends nothing outward and makes no paid call unless told.

    telegram   a message to the investor's phone (and polling his bot): only with PFLAB_LIVE=1 (the global `--live` flag)
    paid       a call to the paid API (Anthropic): only with PFLAB_PAID=1 (the global `--paid` flag), and then counted against
               the separate development cap `dev_monthly_cap_rupees` in api_budget.toml (default 0: raised only by him)
    register   a scheduled task or a shortcut for the live system: only an installed app registers its tick (tools/register_tasks.ps1
               refuses without release.toml)

On the stable channel (the installed app) nothing here blocks: the app's own switches (Settings) decide. The block is by channel,
not by a flag a script could forget: a checkout without release.toml is `beta` (src/pflab/release.py).
"""
from __future__ import annotations

import os
from typing import Optional

from pflab import release


class OutwardBlocked(RuntimeError):
    pass


FLAGS = {"telegram": "PFLAB_LIVE", "paid": "PFLAB_PAID"}
HOW = {"telegram": "run it with the global --live flag (pflab --live ...) to send from the workshop",
       "paid": "run it with the global --paid flag (pflab --paid ...); it counts against dev_monthly_cap_rupees in api_budget.toml",
       "register": "scheduled tasks and shortcuts belong to the installed app (tools/install_app.ps1)"}


def blocked(kind: str) -> Optional[str]:
    """Why `kind` is blocked right now, or None."""
    if kind not in HOW:
        raise ValueError(kind)
    if release.channel() != "beta":
        return None
    if kind in FLAGS and os.environ.get(FLAGS[kind]) == "1":
        return None
    return f"the workshop (beta channel) does not send outward: {HOW[kind]}"


def require(kind: str) -> None:
    why = blocked(kind)
    if why:
        raise OutwardBlocked(why)


def set_flags(paid: bool = False, live: bool = False) -> None:
    """The CLI's global flags, for this process only."""
    if paid:
        os.environ["PFLAB_PAID"] = "1"
    if live:
        os.environ["PFLAB_LIVE"] = "1"
