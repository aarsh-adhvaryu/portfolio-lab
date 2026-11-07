"""The 5-6 Nov 2026 real-path check for the overnight items (S79b), on an ISOLATED rehearsal profile and the workshop's real market data.

    python tools/realpath_s79b.py --profile D:\\s79_scratch\\realpath\\prof [--day 2026-11-06] [--model] [--out report.md]

The week: the US midterm result (read as AI-regulation negative, oil positive), crude down about 18% in a week, the Nasdaq/semis sell-off, Asia falling, record FII buying in
India, the book up. Runs every new tool through the real registry on that date, builds the situation (optionally with the real local model) and prints a plain summary:
what each tool said, and the situation report in two lines. Nothing here reads the investor's profile or the app's store.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

DATA = r"D:\portfolio_lab\data"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--day", default="2026-11-06")
    ap.add_argument("--model", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    prof = Path(a.profile)
    os.environ["PFLAB_DATA_DIR"] = DATA
    if not prof.exists():
        import subprocess
        subprocess.run([sys.executable, str(Path(__file__).parent / "rehearse.py"), "seed", "--profile", str(prof), "--window-cap", "0"], check=True)
    pm = prof / "pm"
    os.environ["PFLAB_PM_DIR"] = str(pm)
    from pflab.app import runtime
    from pflab.hq import egress, tools as tl
    from pflab.pm import store
    con = store.connect(pm / "ledger.duckdb")
    day = date.fromisoformat(a.day)
    now = datetime(day.year, day.month, day.day, 21, 0)
    rt = runtime.Runtime(pm, Path(DATA), Path(r"D:\portfolio_lab"), con=con, clock=lambda: now)
    ctx = tl.Ctx(rt, None, "m", False, {}, egress.Gate(), now, role="quant", allowed=frozenset(tl.TOOLS))
    lines = [f"# 5-6 Nov real-path check (as of {day})", ""]

    def call(name, args=None):
        t0 = time.time()
        t = tl.TOOLS.get(name)
        if t is None:
            lines.append(f"- {name}: tool not registered")
            return {}
        try:
            r = t.fn(ctx, args or {})
        except Exception as e:
            lines.append(f"- {name}: FAILED {type(e).__name__}: {str(e)[:160]}")
            return {}
        lines.append(f"- {name} ({time.time() - t0:.1f}s): " + json.dumps(r, default=str)[:420])
        return r if isinstance(r, dict) else {}

    try:
        from pflab.fcast import run as fr
        out = fr.catch_up(con, "IN", day)
        lines.append(f"- fcast.catch_up: {json.dumps(out, default=str)[:300]}")
    except Exception as e:
        lines.append(f"- fcast.catch_up: FAILED {type(e).__name__}: {str(e)[:160]}")
    for name, args in (("macro_attribution", {"market": "IN", "date": a.day}), ("wave_detector", {"market": "IN", "date": a.day}), ("sentiment", {"market": "IN", "date": a.day}),
                       ("theme_exposure", {"market": "IN", "date": a.day}), ("event_calendar", {"market": "IN", "date": a.day}),
                       ("volume_profile", {"market": "IN", "symbol": "NIFTY 50", "date": a.day}), ("transmission", {"market": "IN", "date": a.day}),
                       ("forecast_now", {"market": "IN"}), ("fall_risk", {"market": "IN"}), ("breadth", {"market": "IN", "date": a.day}),
                       ("implied_dist", {"market": "IN", "date": a.day}), ("construct", {}), ("benchmark", {}), ("lenses", {"market": "IN"}), ("provenance", {}), ("agenda", {})):
        call(name, args)
    try:
        from pflab.situation import build
        r = build.run(rt, "IN", day, now, "deep", use_model=a.model, force="full" if a.model else "code")
        txt = r.get("text", "")
        lines += ["", "## Situation report", "", txt, "", f"claims {r.get('n_claims')} | coded only {r.get('coded_only')} | rejected figures {len(r.get('rejected') or [])}"]
        lines += ["", "### In two lines", ""]
        sec = [l for l in txt.splitlines() if l.strip()]
        lines += [" ".join(sec[:2])[:600]]
    except Exception as e:
        lines.append(f"- situation.build: FAILED {type(e).__name__}: {str(e)[:200]}")
    text = "\n".join(lines)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
