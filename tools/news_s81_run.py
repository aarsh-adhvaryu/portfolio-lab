"""Run the S81 one-year news collection (S81 B7). Resumable; stop with a STOP file or at --until.

    $env:PYTHONPATH = "<worktree>\\src"
    D:\\portfolio_lab\\.venv\\Scripts\\python.exe tools\\news_s81_run.py --root D:\\PortfolioLabApp\\data --until 05:10

  --build-scope   (re)build `<root>/kg/scope.json` from the app's market data before running (done automatically when the file is missing)
  --find          add the names the system finds itself (code rule, at most 40) to the text scope, then run
  --no-text       rows only (the GKG day files), no article pages
  --days N        how far back (default 365)
Stop: create `<root>/news_s81/STOP` (the run ends cleanly after the pages in hand). Log: `<root>/news_s81/collect.log` (counts only).
"""
import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pflab.kg2 import news, scope  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("PFLAB_DATA_DIR", r"D:\PortfolioLabApp\data"))
    ap.add_argument("--until", default="05:10", help="HH:MM local time (the next one); 'none' = no time limit")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--build-scope", action="store_true")
    ap.add_argument("--find", action="store_true")
    ap.add_argument("--no-text", action="store_true")
    a = ap.parse_args()
    root = Path(a.root)
    pidf = news.news_dir(root) / "run.pid"
    pidf.parent.mkdir(parents=True, exist_ok=True)
    if pidf.exists():
        try:
            old = int(pidf.read_text().strip())
            os.kill(old, 0)
            print(f"already running (pid {old})")
            return 2
        except (ValueError, OSError):
            pass
    pidf.write_text(str(os.getpid()))
    try:
        stop = news.news_dir(root) / "STOP"
        if stop.exists():
            stop.unlink()
        if a.build_scope or not scope.scope_path(root).exists():
            sc = scope.build_scope(root)
            print(f"scope built: {len(sc['names'])} names, {sum(1 for n in sc['names'] if n['text'])} with text")
        if a.find:
            print("found names added to text scope:", scope.apply_found(root, scope.find_names(root)))
        until = None
        if a.until != "none":
            h, m = map(int, a.until.split(":"))
            until = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
            if until <= datetime.now():
                until += timedelta(days=1)
        r = news.run(root, days_back=a.days, until=until, text=not a.no_text, log=print)
        print(r)
        return 0
    finally:
        try:
            pidf.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
