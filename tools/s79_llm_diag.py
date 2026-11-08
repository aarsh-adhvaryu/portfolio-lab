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
FAST_CANDIDATES = ("gemma4:12b", "qwen3.5:9b")                  # S79b item 17 (docs/protocols/s79_seats_protocol.md); registered as role seat-fast-candidate
THINKER_CANDIDATES = ("qwen3:30b-a3b", "qwen3.6-35b-a3b", "gemma4-26b-a4b")   # registered as role seat-thinker-candidate before the guarded window (tools/s79_thinker_window.py)


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
    if model in FAST_CANDIDATES:
        registry.require_registered("seat-fast-candidate", model, datetime.now())      # S79b item 17: registered before the run
    if model in THINKER_CANDIDATES:
        registry.require_registered("seat-thinker-candidate", model, datetime.now())
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


def decide_fast(write_pick: bool) -> int:
    """S79b item 17: the FAST seat among the incumbent (arm A) and the candidates with a complete arm A. --write-pick appends the winner row."""
    from pflab import _toml
    from pflab.llm import registry, s79_eval as se
    base = se.load_arm(results_dir("A", BASE))
    cands = {m: se.load_arm(results_dir("A", m)) for m in FAST_CANDIDATES}
    cands = {m: v for m, v in cands.items() if v}
    out_d = {}
    for m, v in cands.items():
        d = se.decide_fast(base, v)
        out_d[m] = d
        print(m, "chosen" if d["chosen"] else "not chosen", d["checks"])
        if "mean4" in d:
            print("   mean of the four scores", {k: round(x, 4) for k, x in d["mean4"].items()}, " p90 s", {k: (round(x, 2) if x else x) for k, x in d["p90"].items()},
                  " vram MiB", d["cand"]["gpu_peak_mib"])
    res = se.pick_fast(base, cands)
    winner = res["winner"] or BASE
    print("FAST seat:", winner, "(incumbent kept)" if winner == BASE else "(challenger wins)")
    out = results_dir("decision", "fast")
    out.mkdir(parents=True, exist_ok=True)
    (out / "decision_fast.json").write_text(json.dumps({"winner": winner, "decisions": out_d}, indent=1, default=str), encoding="utf-8")
    if write_pick:
        now = datetime.now().replace(microsecond=0)
        # one row per tested challenger (its evaluation result; the registration above is unchanged), then the seat row
        text = "\n# S79b item 17 results (appended; the registrations above are unchanged).\n"
        for m, d in out_d.items():
            text += (f"[[pick]]\nrole = \"seat-fast-candidate-result\"\nmodel = \"{m}\"\nregistered_at = {now.isoformat()}\nprotocol = \"docs/protocols/s79_seats_protocol.md\"\n"
                     f"evaluated_at = {now.isoformat()}\ndecision = \"{'chosen' if m == winner else 'not chosen'}\"\n\n")
        why = ("challenger beats qwen3:8b-q8_0 under the registered FAST rule" if winner != BASE else "incumbent kept: no challenger passed the registered FAST rule")
        text += (f"[[pick]]\nrole = \"seat-fast\"\nmodel = \"{winner}\"\nregistered_at = {now.isoformat()}\nprotocol = \"docs/protocols/s79_seats_protocol.md\"\n"
                 f"evaluated_at = {now.isoformat()}\ndecision = \"chosen fast seat ({why})\"\n")
        with open(registry.PICKS_PATH, "a", encoding="utf-8") as f:
            f.write(text)
        _toml.load(registry.PICKS_PATH)                       # must still parse
        print("appended pick rows to configs/llm_models.toml")
    return 0


def decide_thinker(model: str, ram_headroom: float, crashes: int, subset: bool = False, write_pick: bool = False) -> int:
    """THINKER rule (docs/protocols/s79_seats_protocol.md). --subset: the matched subset of Amendment 1 (arm AM, results written by tools/s79_thinker_window.py)."""
    from pflab import _toml
    from pflab.llm import registry, s79_eval as se
    arm = "AM" if subset else "A"
    base, cand = se.load_arm(results_dir(arm, BASE)), se.load_arm(results_dir(arm, model))
    d = se.decide_thinker(base, cand, ram_headroom, crashes)
    out = results_dir("decision", "thinker")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"decision_thinker__{model.replace(':', '_')}.json").write_text(json.dumps(d, indent=1, default=str), encoding="utf-8")
    print(model, "chosen" if d["chosen"] else "not chosen", d["checks"])
    if write_pick:
        now = datetime.now().replace(microsecond=0).isoformat()
        verdict = "chosen" if d["chosen"] else "not chosen"
        text = ("\n# S79b item 17 THINKER result (appended; the registration above is unchanged).\n"
                f'[[pick]]\nrole = "seat-thinker-candidate-result"\nmodel = "{model}"\nregistered_at = {now}\n'
                f'protocol = "docs/protocols/s79_seats_protocol.md"\nevaluated_at = {now}\ndecision = "{verdict}"\n')
        if d["chosen"]:
            text += (f'\n[[pick]]\nrole = "seat-thinker"\nmodel = "{model}"\nregistered_at = {now}\nprotocol = "docs/protocols/s79_seats_protocol.md"\n'
                     f'evaluated_at = {now}\ndecision = "chosen thinker seat (beats qwen3:8b-q8_0 under the registered THINKER rule on the matched subset)"\n')
        with open(registry.PICKS_PATH, "a", encoding="utf-8") as f:
            f.write(text)
        _toml.load(registry.PICKS_PATH)                       # must still parse
        print("appended pick rows to configs/llm_models.toml")
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
                            ("C MoE", MOE, se.load_arm(results_dir("C", MOE))),
                            *[(f"A FAST candidate", m, se.load_arm(results_dir("A", m))) for m in FAST_CANDIDATES]):
        if res and all(t in res for t in se.TASKS):
            rows[arm] = se.summarise(res)
            lines.append(f"| {arm} | {model} | " + _fmt(rows[arm], keys) + " |")
        elif res:
            lines.append(f"| {arm} | {model} | incomplete: {sorted(res)} |")
    ds = results_dir("decision", "sampling") / "decision_sampling.json"
    if ds.exists():
        d = json.loads(ds.read_text(encoding="utf-8"))
        lines += ["", f"**Sampling decision:** adopted kinds {d['adopt_kinds'] or 'none'}; text checks {d['text']}; json checks {d['json']}."]
    df = results_dir("decision", "fast") / "decision_fast.json"
    if df.exists():
        d = json.loads(df.read_text(encoding="utf-8"))
        lines += ["", f"**FAST seat (S79b item 17, docs/protocols/s79_seats_protocol.md):** {d['winner']}; per candidate: "
                  + "; ".join(f"{m} {'chosen' if x['chosen'] else 'not chosen'} {x['checks']}" for m, x in d["decisions"].items()) + "."]
    am = se.load_arm(results_dir("AM", BASE))
    th_lines = []
    if am:
        th_lines.append("| AM (matched subset, incumbent) | " + BASE + " | " + _fmt(se.summarise(am), keys) + " |")
    for m in THINKER_CANDIDATES:
        w = results_dir("decision", "thinker") / f"window__{m.replace(':', '_')}.json"
        dj = results_dir("decision", "thinker") / f"decision_thinker__{m.replace(':', '_')}.json"
        wj = json.loads(w.read_text(encoding="utf-8")) if w.exists() else {}
        dd = json.loads(dj.read_text(encoding="utf-8")) if dj.exists() else {}
        res = se.load_arm(results_dir("AM", m))
        if res and all(t in res for t in se.TASKS):
            th_lines.append(f"| AM (matched subset) | {m} | " + _fmt(se.summarise(res), keys) + " |")
        meas = ""
        if wj:
            b = wj.get("bench") or {}
            meas = (f"{wj.get('verdict')}{' (' + wj.get('reason', '') + ')' if wj.get('reason') else ''}; load {wj.get('load_s')} s; generation {b.get('gen_tps')} tok/s, prompt {b.get('prompt_tps')} tok/s; "
                    f"peak GPU {wj.get('peak_gpu_mib')} MiB, peak temp {wj.get('peak_temp_c')} C, min free RAM {wj.get('min_free_ram_gb')} GB, free RAM after load {wj.get('ram_after_load_gb')} GB")
        if not wj and not dd:
            continue
        th_lines.append(f"<!-- {m} --> " + (f"{m}: {'chosen' if dd.get('chosen') else 'not chosen'} {dd.get('checks')}; " if dd else f"{m}: ") + meas)
    if th_lines:
        lines += ["", "**THINKER seat, guarded window (S79b item 17, Amendment 1: matched subset routing 60 / answers 20 / extraction 40 / materiality 60):**", "",
                  "| arm | model | " + " | ".join(keys) + " |", "|---|---|" + "---|" * len(keys)] + [x for x in th_lines if x.startswith("|")] + [""]                  + ["- " + x.split("--> ", 1)[1] for x in th_lines if x.startswith("<!--")]
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
    f = sub.add_parser("decide-fast")
    f.add_argument("--write-pick", action="store_true")
    t = sub.add_parser("decide-thinker")
    t.add_argument("--model", required=True)
    t.add_argument("--ram-headroom", type=float, required=True)
    t.add_argument("--crashes", type=int, default=0)
    t.add_argument("--subset", action="store_true", help="the matched subset of Amendment 1 (arm AM)")
    t.add_argument("--write-pick", action="store_true")
    a = ap.parse_args()
    if a.cmd == "decide-fast":
        return decide_fast(a.write_pick)
    if a.cmd == "decide-thinker":
        return decide_thinker(a.model, a.ram_headroom, a.crashes, a.subset, a.write_pick)
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
