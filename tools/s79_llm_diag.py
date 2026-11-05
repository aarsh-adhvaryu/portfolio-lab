"""S79 item 13: diagnose the local model, run the registered comparisons, decide, record. Development only (free, local).

    python tools/s79_llm_diag.py diagnose [--db COPY_OF_LEDGER.duckdb]     # counts only; never open the app's own file: pass a copy
    python tools/s79_llm_diag.py run --arm A|B|C [--model M] [--kinds text,json]
    python tools/s79_llm_diag.py decide-sampling
    python tools/s79_llm_diag.py decide-moe [--write-pick]
    python tools/s79_llm_diag.py report                                    # (re)writes the S79 item 13 results section of docs/STUDIES.md from the result files
    python tools/s79_llm_diag.py record                                    # the two comparisons into the learner's counter (the store in PFLAB_PM_DIR)

Protocol: docs/protocols/s79_local_model_protocol.md (registered before any run). Results: <data>/llm_eval/results_s79/<arm>__<model>/.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

BASE = "qwen3:8b-q8_0"
MOE = "qwen3:30b-a3b"


def results_dir(arm: str, model: str) -> Path:
    from pflab.data import data_dir
    return data_dir() / "llm_eval" / "results_s79" / f"{arm}__{model.replace(':', '_')}"


def diagnose(db: str) -> int:
    import duckdb
    con = duckdb.connect(db, read_only=True)
    try:
        n, lo, hi = con.execute("select count(*), min(started_at), max(started_at) from llm_runs").fetchone()
    except Exception as e:
        print(f"no llm_runs in {db}: {e}")
        return 1
    print(f"llm_runs: {n} calls, {lo} to {hi}")
    if not n:
        return 0
    rows = con.execute("select coalesce(role,'(none)'), status, coalesce(note,''), tokens_out, seconds from llm_runs").fetchall()
    top = Counter(r[3] for r in rows if r[3]).most_common(1)
    by = defaultdict(list)
    for role, status, note, tok, sec in rows:
        by[role].append((status, note, tok, sec))
    print("task kind              calls  failed  labelled(loop/trunc/empty/format)  max_tokens  median_s")
    for role, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
        failed = sum(1 for x in v if x[0] != "ok")
        lab = Counter(x[1] for x in v if x[1] in ("loop", "truncated", "empty", "format"))
        cap = sum(1 for x in v if x[2] >= 2500)             # the known long-reply cap (workshop writer): a reply that used all of it
        secs = sorted(x[3] for x in v)
        print(f"{role:22s} {len(v):5d} {failed:7d}  {dict(lab) or '-'!s:34s} {max(x[2] for x in v):9d}  {secs[len(secs) // 2]:8.1f}"
              + (f"   (at the 2500-token cap: {cap})" if cap else ""))
    print("The table keeps tokens, seconds, status and note, not the text: loops and truncations are read from the note label (written from S79 on)"
          " or from tokens at a known cap. Inability (a wrong answer with a clean finish) is measured on the scored eval sets.")
    return 0


def run(a) -> int:
    from pflab.data import data_dir
    from pflab.llm import registry, s79_eval as se
    model = a.model or (MOE if a.arm == "C" else BASE)
    if model == MOE:
        registry.require_registered("eval-s79-moe", model, datetime.now())
    kinds = [k for k in (a.kinds or "").split(",") if k]
    if a.arm == "C" and not kinds:
        d = results_dir("decision", "sampling")
        f = d / "decision_sampling.json"
        kinds = json.loads(f.read_text(encoding="utf-8"))["adopt_kinds"] if f.exists() else []
    out = results_dir(a.arm, model)
    print(f"arm {a.arm} model {model} sampling kinds {kinds if a.arm == 'C' else ('all' if a.arm == 'B' else 'none')} -> {out}")
    try:
        se.run_arm(a.arm, model, out, data_dir(), kinds=kinds, tasks=a.tasks.split(",") if a.tasks else se.TASKS)
    except se.GpuLost as e:
        print(f"STOP: the GPU is lost or not answering ({e}). Partial results kept; use Restart (not Shut down), then rerun the same command to resume.")
        return 2
    return 0


def decide_sampling() -> int:
    from pflab.llm import s79_eval as se
    a, b = se.load_arm(results_dir("A", BASE)), se.load_arm(results_dir("B", BASE))
    d = se.decide_sampling(a, b)
    out = results_dir("decision", "sampling")
    out.mkdir(parents=True, exist_ok=True)
    (out / "decision_sampling.json").write_text(json.dumps(d, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: d[k] for k in ("adopt_kinds", "text", "json")}, indent=1))
    for k in ("A", "B"):
        s = d[k]
        print(k, {x: (round(v, 3) if isinstance(v, float) else v) for x, v in s.items() if not isinstance(v, dict)})
        print("  text labels", {x: round(v, 3) for x, v in s["text_labels"].items()}, " json labels", {x: round(v, 3) for x, v in s["json_labels"].items()})
    return 0


def decide_moe(write_pick: bool) -> int:
    from pflab.llm import registry, s79_eval as se
    base = se.load_arm(results_dir("C", BASE)) or se.load_arm(results_dir("A", BASE))
    kinds_file = results_dir("decision", "sampling") / "decision_sampling.json"
    moe = se.load_arm(results_dir("C", MOE))
    if not base or not moe:
        print("need the 8b arm (C or A) and the MoE arm C first")
        return 1
    d = se.decide_moe(base, moe)
    out = results_dir("decision", "moe")
    out.mkdir(parents=True, exist_ok=True)
    (out / "decision_moe.json").write_text(json.dumps(d, indent=1, default=str), encoding="utf-8")
    print("chosen:", d["chosen"], d["checks"])
    print("p_better", {k: round(v, 4) for k, v in d["p_better"].items()}, "p_worse", {k: round(v, 4) for k, v in d["p_worse"].items()})
    for k in ("base", "moe"):
        print(k, {x: (round(v, 3) if isinstance(v, float) else v) for x, v in d[k].items() if not isinstance(v, dict)})
    if write_pick:
        now = datetime.now().replace(microsecond=0)
        decision = ("chosen general+routing (S79 item 13: beats qwen3:8b-q8_0 under the registered rule, latency and VRAM bound met)" if d["chosen"]
                    else "not chosen")
        pick = registry.pick_for("eval-s79-moe") or {}
        text = ("\n# S79 item 13 result (appended; the registration above is unchanged): " + ("adopted" if d["chosen"] else "not adopted") + ".\n"
                "[[pick]]\nrole = \"eval-s79-moe-result\"\n"
                f"model = \"{MOE}\"\nregistered_at = {now.isoformat()}\nsize_gb = {pick.get('size_gb', 19.0)}\n"
                "protocol = \"docs/protocols/s79_local_model_protocol.md\"\n"
                f"evaluated_at = {now.isoformat()}\ndecision = \"{decision}\"\n")
        with open(registry.PICKS_PATH, "a", encoding="utf-8") as f:
            f.write(text)
        print("appended a pick row to configs/llm_models.toml:", decision)
    return 0


def record() -> int:
    from pflab.learner import counter
    from pflab.llm import s79_eval as se
    from pflab.pm import store
    con = store.connect()
    now = datetime.now()
    a, b = se.load_arm(results_dir("A", BASE)), se.load_arm(results_dir("B", BASE))
    ds = se.decide_sampling(a, b)
    counter.record(con, now, "study", "s79_llm_sampling", {"model": BASE, "adopt_kinds": ds["adopt_kinds"]}, n_dev=sum(t["n"] for t in a.values()),
                   passed=bool(ds["adopt_kinds"]), note="s79_llm:sampling_vs_default")
    for arm, res, model in (("A", a, BASE), ("B", b, BASE)):
        se.store_rows(con, "sampling", arm, model, se.summarise(res), now)
    moe = se.load_arm(results_dir("C", MOE))
    if moe:
        base = se.load_arm(results_dir("C", BASE)) or a
        dm = se.decide_moe(base, moe)
        counter.record(con, now, "study", "s79_llm_moe", {"model": MOE, "checks": dm["checks"]}, n_dev=sum(t["n"] for t in moe.values()),
                       passed=dm["chosen"], note="s79_llm:moe_vs_8b")
        se.store_rows(con, "moe", "C", MOE, se.summarise(moe), now)
    print(counter.line(con))
    return 0


MARK0, MARK1 = "<!-- s79-llm-results:begin -->", "<!-- s79-llm-results:end -->"


def _fmt(s: dict, keys) -> str:
    return " | ".join("-" if s.get(k) is None else (f"{s[k]:.3f}" if isinstance(s[k], float) else str(s[k])) for k in keys)


def report() -> int:
    """The results section of docs/STUDIES.md, rebuilt from whatever result files exist (idempotent, between two markers)."""
    from pflab.llm import s79_eval as se
    a, b = se.load_arm(results_dir("A", BASE)), se.load_arm(results_dir("B", BASE))
    keys = ["routing", "answers_final", "answers_first", "extraction_f1", "materiality", "answers_median_s", "answers_p90_s", "routing_call_median_s",
            "tokens_per_s", "text_fail_rate", "json_fail_rate", "gpu_peak_mib"]
    lines = [MARK0, "## S79 item 13: local model sampling and a larger MoE (protocol: docs/protocols/s79_local_model_protocol.md)", "",
             "Diagnosis (counts only): the app's `llm_runs` (a copy of its ledger, 31 calls, 2026-11-02 to 11-03) shows no failed call and no labelled loop; "
             "two `workshop_writer` replies used the whole 2,500-token cap (truncation risk). The table keeps no text, so from S79 on `client.chat` writes the "
             "`diag` label (ok, truncated, empty, loop, format) into `note` and keeps Ollama's `done_reason`.", "",
             "| arm | model | " + " | ".join(keys) + " |", "|---|---|" + "---|" * len(keys)]
    rows = {}
    for arm, model, res in (("A old default", BASE, a), ("B Qwen sampling", BASE, b), ("C 8b adopted kinds", BASE, se.load_arm(results_dir("C", BASE))),
                            ("C MoE", MOE, se.load_arm(results_dir("C", MOE)))):
        if res and all(t in res for t in se.TASKS):
            rows[arm] = se.summarise(res)
            lines.append(f"| {arm} | {model} | " + _fmt(rows[arm], keys) + " |")
        elif res:
            lines.append(f"| {arm} | {model} | incomplete: {sorted(res)} |")
    ds = results_dir("decision", "sampling") / "decision_sampling.json"
    if ds.exists():
        d = json.loads(ds.read_text(encoding="utf-8"))
        lines += ["", f"**Sampling decision:** adopted kinds {d['adopt_kinds'] or 'none'}; text checks {d['text']}; json checks {d['json']}."]
    dm = results_dir("decision", "moe") / "decision_moe.json"
    if dm.exists():
        d = json.loads(dm.read_text(encoding="utf-8"))
        lines += ["", f"**MoE decision:** {'chosen' if d['chosen'] else 'not chosen'}; checks {d['checks']}; sign-test p (MoE better) "
                  f"{ {k: round(v, 4) for k, v in d['p_better'].items()} }, (MoE worse) { {k: round(v, 4) for k, v in d['p_worse'].items()} }."]
    lines += ["", MARK1]
    block = "\n".join(lines) + "\n"
    f = Path(__file__).resolve().parents[1] / "docs" / "STUDIES.md"
    t = f.read_text(encoding="utf-8")
    if MARK0 in t:
        t = t[:t.index(MARK0)] + block + t[t.index(MARK1) + len(MARK1) + 1:]
    else:
        t = t.rstrip("\n") + "\n\n" + block
    f.write_text(t, encoding="utf-8")
    print("docs/STUDIES.md updated;", len(rows), "complete arms")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("diagnose")
    d.add_argument("--db", required=True)
    r = sub.add_parser("run")
    r.add_argument("--arm", required=True, choices=["A", "B", "C"])
    r.add_argument("--model", default=None)
    r.add_argument("--kinds", default="")
    r.add_argument("--tasks", default="")
    sub.add_parser("decide-sampling")
    m = sub.add_parser("decide-moe")
    m.add_argument("--write-pick", action="store_true")
    sub.add_parser("record")
    sub.add_parser("report")
    a = ap.parse_args()
    if a.cmd == "diagnose":
        return diagnose(a.db)
    if a.cmd == "run":
        return run(a)
    if a.cmd == "decide-sampling":
        return decide_sampling()
    if a.cmd == "decide-moe":
        return decide_moe(a.write_pick)
    if a.cmd == "report":
        return report()
    return record()


if __name__ == "__main__":
    raise SystemExit(main())
