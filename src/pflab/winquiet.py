"""S78: no console window ever pops up from a background process (2026-11-02: terminals kept flashing on his screen while the app probed Docker, git and the GPU).
On Windows every child process started by the app gets CREATE_NO_WINDOW unless the caller chose its own flags. Idempotent; a no-op elsewhere."""
from __future__ import annotations

import os
import subprocess

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_CONSOLE = 0x00000010
_done = False


def apply() -> bool:
    global _done
    if os.name != "nt" or _done:
        return False
    orig = subprocess.Popen.__init__

    def init(self, *args, **kwargs):
        flags = kwargs.get("creationflags", 0) or 0
        if not flags & (DETACHED_PROCESS | CREATE_NEW_CONSOLE):          # a caller that asked for a detached or visible process keeps it
            kwargs["creationflags"] = flags | CREATE_NO_WINDOW
        orig(self, *args, **kwargs)

    subprocess.Popen.__init__ = init
    _done = True
    return True
