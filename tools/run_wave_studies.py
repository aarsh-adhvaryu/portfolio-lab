"""Run the pre-registered event studies of docs/protocols/s79_wave_sentiment_protocol.md ONCE each, for the record (S79b items 15, 15b, 7b).

    .venv\\Scripts\\python tools\\run_wave_studies.py --pm D:\\s79_scratch\\E\\pm [--tests wave_5,wave_20,...] [--draws 10000] [--dry] [--docs]

Reads the index series and the event lists from PFLAB_DATA_DIR, the counter from the store in --pm (the registration rows are created there if the store is a scratch one).
Refuses when the protocol file is not the committed one. A test already recorded for (test, market) is skipped: a test is run once. --dry computes and prints, records nothing
(for checking a run is possible; it is NOT a second run for the record: do not use it on the real data to look and then run again). --docs writes
docs/research/wave_sentiment_results_s79.json and the marked section of docs/STUDIES.md from the recorded rows. Nothing is tuned here."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

BEGIN, END = "<!-- s79-wave-sentiment-results:begin -->", "<!-- s79-wave-sentiment-results:end -->"


def _fmt_effect(r: dict) -> str:
    if r["effect"] is None:
        return "-"
    d = json.loads(r["halves_json"] or "{}")
    if d.get("unit") == "share":
        return f"{r['effect'] * 100:+.1f} pts [{(r['ci_low'] or 0) * 100:+.1f}, {(r['ci_high'] or 0) * 100:+.1f}]"
    return f"{r['effect'] * 100:+.2f}% [{(r['ci_low'] or 0) * 100:+.2f}, {(r['ci_high'] or 0) * 100:+.2f}]"


def write_docs(con) -> None:
    from pflab.quant import index_event_study as S
    rows = S.results(con)
    out = {"protocol": S.PROTOCOL, "period": [str(S.PERIOD_START), str(S.PERIOD_END)], "written": datetime.now().isoformat(timespec="seconds"), "results": rows}
    p = REPO / S.RESULTS_JSON
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    lines = [BEGIN, "## S79b items 15, 15b, 7b: market waves, rotation, crude falls, sentiment, value area and POC migration (protocol: docs/protocols/s79_wave_sentiment_protocol.md)", "",
             "Each test ran once, 2004-2021 only (2022-2025 is spent), non-overlapping events, moving-block bootstrap (block = horizon, 10,000 draws, seed 20261108), gate: n >= 20, one-sided p <= 1 - Phi(t_needed(N)) "
             "with N read from the counter at run time, same sign in both halves, |effect| - 0.2% cost >= 0.5%. A pass reads \"followed through\"; anything else \"no reliable follow-through\". "
             "A description of history, not a forecast.", "",
             "| test | market | events (raw) | effect [95% interval] | p (one-sided) | bar t / N | halves same sign | verdict |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        d = json.loads(json.dumps(r["details"]))
        ss = d.get("same_sign")
        lines.append(f"| {r['test']} | {r['market']} | {r['n_events']} ({d.get('n_events_raw')}) | {_fmt_effect({**r, 'halves_json': json.dumps(d)})} | "
                     f"{'-' if r['p'] is None else format(r['p'], '.4f')} | {r['t_needed']:.2f} / {r['n_counter']} | {'-' if ss is None else ss} | {r['verdict']} |")
    sha = f"protocol sha {rows[0]['protocol_sha'][:12]}, code sha {rows[0]['code_sha'][:12]}" if rows else "no rows"
    lines += ["", f"Recorded in `wave_study_results_s79` ({sha}); rows also in `{S.RESULTS_JSON}`.", END]
    block = "\n".join(lines) + "\n"
    sp = REPO / "docs" / "STUDIES.md"
    txt = sp.read_text(encoding="utf-8")
    if BEGIN in txt and END in txt:
        a, b = txt.index(BEGIN), txt.index(END) + len(END)
        txt = txt[:a] + block.rstrip("\n") + txt[b:]
    else:
        txt = txt.rstrip("\n") + "\n\n" + block
    sp.write_text(txt, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pm", required=True, help="folder of the (scratch) store")
    ap.add_argument("--tests", default="")
    ap.add_argument("--markets", default="IN")
    ap.add_argument("--draws", type=int, default=10_000)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--docs", action="store_true")
    ap.add_argument("--register", action="store_true", help="seed the counter and register the studies in a scratch store")
    a = ap.parse_args()
    os.environ["PFLAB_PM_DIR"] = a.pm
    from pflab.data import data_dir
    from pflab.learner import counter, s79
    from pflab.pm import store
    from pflab.quant import index_event_study as S
    root = data_dir()
    con = store.connect(Path(a.pm) / "ledger.duckdb")
    now = datetime.now()
    if a.register:
        counter.seed(con, now)
        s79.register_all(con, now)
    psha = S.protocol_sha()                                   # raises ProtocolMismatch when the file is not the committed one
    tests = [t for t in a.tests.split(",") if t] or list(S.TESTS)
    t_need, n = S.bar_now(con)
    print(f"protocol sha {psha[:12]}  code sha {S.code_sha()[:12]}  counter N={n}  bar t_needed={t_need:.3f}  p cut={S.p_cut(t_need):.5f}  period {S.PERIOD_START}..{S.PERIOD_END}")
    frames = {}
    for market in [m for m in a.markets.split(",") if m]:
        for t in tests:
            if S.already_recorded(con, t, market):
                print(f"{t:22s} {market}: already recorded, skipped (a test is run once)")
                continue
            if t in ("value_area_return_1", "value_area_return_5", "poc_migration_5") and market not in frames:
                frames[market] = S.va_frame(market, root)
            res = S.run_test(t, market, root, con, a.draws, frames)
            eff = "-" if res.get("effect") is None else (f"{res['effect'] * 100:+.3f}" + ("%" if res.get("unit", "pct") == "pct" else " pts"))
            print(f"{t:22s} {market}: n={res['n_events']:3d}/{res['n_events_raw']:3d} base={res.get('n_baseline')} effect={eff} p={res.get('p')} same_sign={res.get('same_sign')} "
                  f"gate={res.get('gate')} -> {res['verdict']}")
            if not a.dry:
                S.record(con, res, psha, now)
    if a.docs and not a.dry:
        write_docs(con)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
