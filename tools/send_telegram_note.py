"""Send ONE message to the investor's Telegram from the workshop (the morning report of an unattended run, S81). The workshop sends nothing outward unless told: this tool sets the
`--live` flag itself, so it is run only when a note is really meant for him.

    .venv\\Scripts\\python tools\\send_telegram_note.py FILE.txt

The secrets file is read by the sender only; nothing from it is printed. A message over Telegram's limit is split. Exit code 0 sent, 2 not configured, 1 failed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pflab import guard
from pflab.pm import secrets
from pflab.service import telegram as tgm


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print("usage: send_telegram_note.py FILE.txt")
        return 2
    text = Path(argv[0]).read_text(encoding="utf-8").strip()
    if not text:
        print("the file is empty")
        return 2
    guard.set_flags(live=True)
    try:
        tgm.make_sender(secrets.load())(text)
    except tgm.TelegramNotConfigured as e:
        print(f"not configured: {e}")
        return 2
    except Exception as e:
        print(f"send failed: {type(e).__name__}")
        return 1
    print(f"sent ({len(text)} characters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
