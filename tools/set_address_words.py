"""Set the investor's address words in PFLAB_PM_DIR/api_budget.toml [egress] address, from his own statements (S60).

The words are taken from the address his statements print under his name (`hq.redact.address_from`), keeping only
those that are rare in public documents and repeat across statements; nothing is typed by him and nothing leaves the
PC. The egress gate then replaces these words before any text goes to the API and blocks a call that still has one.
Prints only how many words were found and how many statements were read, never the words.

    .venv\\Scripts\\python tools\\set_address_words.py            (reads D:\\portfolio_lab\\new)
    .venv\\Scripts\\python tools\\set_address_words.py --dry-run  (counts only, writes nothing)
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pflab.hq import egress, redact
from pflab.pm import secrets, store


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default=str(Path(__file__).resolve().parents[1] / "new"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    con = store.connect(store.db_path())
    gate = egress.load(con)
    if not gate.names:
        print("his name is not in api_budget.toml [egress] names: the address cannot be found under it")
        return 1
    sec = secrets.load()
    pw = [sec.get("passwords", n.split(".", 1)[1]) for n in sec.names() if n.startswith("passwords.")]
    texts, skipped = [], 0
    for f in sorted(Path(a.folder).iterdir()):
        if f.is_file() and f.suffix.lower() in (".pdf", ".xlsx", ".xls", ".csv"):
            try:
                texts.append(redact.statement_text(f, pw))
            except Exception:
                skipped += 1
    words = redact.address_from(texts, gate, redact.common_words(con))
    con.close()
    print(f"statements read {len(texts)}, not readable {skipped}; address words found {len(words)}")
    if not a.dry_run and words:
        redact.write_address(store.pm_dir() / "api_budget.toml", words)
        print(f"written to {store.pm_dir() / 'api_budget.toml'} [egress] address")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
