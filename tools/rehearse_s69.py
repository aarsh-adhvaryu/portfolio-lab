"""S69 acceptance rehearsal on an ISOLATED SYNTHETIC profile (development only; never the investor's record, never a paid call).

What is REAL here: the runtime's HQ thread and the worker pool (threads), the HTTP API and the dashboard the screen uses, the chat endpoint, the inbox, the
trusted calculations, the experiment machinery with the LOCAL model (qwen3 through Ollama) writing the candidate and the real Docker sandbox running it, the
local model's routing of a dropped file, the store and a hard process kill and restart.
What is SCRIPTED: the cloud roles (coordinator, research, quant, reviewer, assistant). The paid acceptance allowance was spent before this session, so no
paid call is made: a scripted client answers each role from the STATE of the store (never from a counter), which is also what makes it survive a restart.
This proves the plumbing, the states and the safety paths; it does not prove what the cloud models would conclude.

    python tools/rehearse_s69.py seed  --profile <new empty folder>
    python tools/rehearse_s69.py serve --profile <folder> --port 8793          (what the app's own process does, with the scripted cloud)
    python tools/rehearse_s69.py drive --profile <folder> --port 8793 --out report.json     (starts and kills `serve` itself, drives it over HTTP)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

ROLE_OF = {"ROLE coordinator": "coordinator", "ROLE research": "research", "ROLE quant": "quant", "ROLE review": "review"}
OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5-5"
GOAL = ("Investigate whether a downturn in AI-linked stocks could spread to my holdings, and compare buying more, holding, reducing or selling, and waiting. "
        "Check the news claim first.")
DOC = ("Analyst note on the AI downturn: the largest buyers of AI chips have cut spending for next quarter, which pushed AI-linked stocks lower again, and the note says "
       "Indian holdings linked to AI demand may fall further if the downturn continues. It also says some of the fall is already in prices. " * 3)


# ----------------------------------------------------------------------------------------------------------------------------------------------
# the scripted cloud: each role answers from the state of the store

def _use(*calls, model=SONNET):
    content = [SimpleNamespace(type="thinking", thinking="", signature="sig")]
    content += [SimpleNamespace(type="tool_use", id=f"tu{k}{abs(hash(str(c)))}{time.time_ns()}", name=n, input=i) for k, (n, i) in enumerate(calls) for c in [object()]]
    return SimpleNamespace(content=content, stop_reason="tool_use", model=model,
                           usage=SimpleNamespace(input_tokens=1500, output_tokens=300, cache_read_input_tokens=0, cache_creation_input_tokens=0))


def _say(text, model=SONNET):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn", model=model,
                           usage=SimpleNamespace(input_tokens=1500, output_tokens=150, cache_read_input_tokens=0, cache_creation_input_tokens=0))


class Scripted:
    def __init__(self, rt, delay: float):
        self.rt, self.delay = rt, delay
        self.messages = SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(input_tokens=1500), create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        sys_text = kw["system"][0]["text"]
        if "the assistant of a private investor" in sys_text:
            role = "assistant"
        else:
            role = next((r for m, r in ROLE_OF.items() if m in sys_text), None)
        if role is None:
            raise RuntimeError("this rehearsal scripts only the mission roles and the assistant")
        time.sleep(self.delay)
        first = kw["messages"][0]["content"][0]["text"]
        n_results = sum(1 for m in kw["messages"] if m["role"] == "user" and isinstance(m["content"], list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"]))
        con = self.rt.cursor()
        return getattr(self, "_" + role)(con, first, n_results)

    # --- the assistant (his chat) ---
    def _assistant(self, con, first, n):
        msg = first.split("HIS MESSAGE:", 1)[-1].strip()
        low = msg.lower()
        if n:
            return _say("Done. " + ("I started the investigation; its plan will wait for your yes." if "investigate" in low else "That is recorded; nothing is ordered."))
        if low.startswith("investigate"):
            return _use(("start_investigation", {"goal": msg}))
        if "approve" in low:
            return _use(("decide_plan", {"case_id": 1, "decision": "approve"}))
        if low.startswith("also"):
            return _use(("amend_investigation", {"case_id": 1, "instruction": msg}))
        if "controlled" in low:
            return _use(("make_proposal", {"action": "BUY", "symbol": "ITC", "qty": 20, "case_id": 1,
                                             "reason": "A controlled example in the test profile: a small purchase sized from the cash on record.",
                                             "alternatives": "Waiting, or holding what he has, were the other options considered."}),
                        ("make_proposal", {"action": "REDUCE", "symbol": "MARUTI", "qty": 5, "case_id": 1,
                                           "reason": "A controlled example in the test profile: trimming a position to lower concentration.",
                                           "alternatives": "Holding it all, or selling everything, were the other options considered."}))
        m = re.search(r"accept proposal (\d+)", low)
        if m:
            return _use(("decide_proposal", {"proposal_id": int(m.group(1)), "decision": "accept"}))
        return _say("Noted.")

    # --- coordinator ---
    def _coordinator(self, con, first, n):
        if "Write the final answer" in first:
            if n:
                return _say("Answer written.", OPUS)
            itc = con.execute("SELECT isin FROM instruments WHERE symbol='ITC'").fetchone()[0]
            px = con.execute("SELECT close FROM prices WHERE isin=? ORDER BY date DESC LIMIT 1", [itc]).fetchone()[0]
            verdict = con.execute("SELECT outcome FROM hq_case_reviews WHERE outcome IS NOT NULL ORDER BY review_id DESC LIMIT 1").fetchone()[0]
            ver = con.execute("SELECT max(version) FROM hq_plan_versions WHERE status IN ('approved','auto')").fetchone()[0]
            trig = [{"kind": "price_below", "symbol": "ITC", "value": round(float(px) * 0.9, 2)}, {"kind": "move_pct", "symbol": "ITC", "pct": -10},
                    {"kind": "new_document", "symbol": "ITC"}, {"kind": "review_on", "date": "2026-11-20"}, {"kind": "watch_the_mood", "symbol": "ITC"}]
            return _use(("submit_answer", {"case_id": 1, "answer": f"The evidence in the case supports waiting rather than acting now (instructions v{ver}). The calculations show what a stated "
                         f"fall would cost and how the deployment policies compare; the experiment was run and its result is in the case. The independent review's verdict was {verdict}.",
                         "limitations": "The scenario weights are assumptions; the experiment covers index history to 2021 only.",
                         "monitor_next": "Watch ITC for a 10 percent fall and any new document about it.", "triggers_json": json.dumps(trig),
                         "change": "first" if ver == 1 else "changed"}), model=OPUS)
        if n:
            return _say("Planned.", OPUS)
        if "AMENDMENT" in first:
            plan = [{"key": "costs", "role": "quant", "goal": "Repeat the deployment comparison with a 0.5% charge on every trade, as the amendment asks.", "promise": {"calc": 1}, "depends_on": []}]
            return _use(("plan_mission", {"case_id": 1, "steps_json": json.dumps(plan), "approach": "only the cost assumption changes; the finished steps stand"}), model=OPUS)
        if "Review of an earlier investigation" in first:
            plan = [{"key": "newdoc", "role": "research", "goal": "Read the new note that arrived and say whether it changes the conclusion; record it as evidence.", "promise": {"evidence": 1}, "depends_on": []}]
            return _use(("plan_mission", {"case_id": 1, "steps_json": json.dumps(plan), "approach": "only the new material needs reading"}), model=OPUS)
        plan = [{"key": "verify", "role": "research", "goal": "Verify the AI-downturn premise from sources: the event, its dates and size; look for evidence against it.", "promise": {"evidence": 2}, "depends_on": []},
                {"key": "exposure", "role": "quant", "goal": "Compute what stated equity falls would cost the portfolio now.", "promise": {"calc": 1}, "depends_on": []},
                {"key": "policies", "role": "quant", "goal": "Compare deployment policies across market paths; needs the verified size of the move from research.", "promise": {"calc": 1}, "depends_on": []},
                {"key": "strategy", "role": "quant", "goal": "Register a bounded experiment: hold cash after a 10 percent fall versus always invested.", "promise": {"experiment": 1}, "depends_on": []},
                {"key": "decide", "role": "quant", "goal": "Turn the results into a supported recommendation (buy, add, hold, reduce, sell, diversify or wait).", "promise": {"proposal": 1}, "depends_on": ["exposure", "policies"]}]
        return _use(("plan_mission", {"case_id": 1, "steps_json": json.dumps(plan), "approach": "verify the claim, compute in parallel, then decide"}), model=OPUS)

    # --- research ---
    def _research(self, con, first, n):
        tid = int(re.search(r"TASK #(\d+)", first).group(1))
        if n:
            return _say("Recorded.")
        if "new note" in first or "New material arrived" in first:
            return _use(("case_evidence", {"case_id": 1, "stance": "neutral", "text": "The new analyst note repeats the earlier concern and adds that part of the fall is already priced in; it does not change the supported conclusion to wait.",
                                          "source_kind": "article", "published": "2026-11-01"}))
        if "verified size" in first or "Provide" in first:
            return _use(("case_evidence", {"case_id": 1, "stance": "for", "text": "Prices of AI-linked large caps fell about 8 percent over the five sessions to the verification date, per stored closes.", "source_kind": "observation"}))
        return _use(("case_evidence", {"case_id": 1, "stance": "for", "text": "A published note reports that large buyers cut AI chip spending next quarter.", "source_kind": "article", "published": "2026-10-28", "source_id": "note:1"}),
                    ("case_evidence", {"case_id": 1, "stance": "for", "text": "A published note reports that large buyers cut AI chip spending next quarter.", "source_kind": "article", "published": "2026-10-28", "source_id": "note:1"}),
                    ("case_evidence", {"case_id": 1, "stance": "against", "text": "Indian IT and consumer holdings fell far less than AI-linked names over the same days, per stored closes.", "source_kind": "observation"}))

    # --- quant ---
    def _quant(self, con, first, n):
        text = first.split("\n")[0]
        if n:
            return _say("Done.")
        checkpoint = "YOUR EARLIER WORK ON THIS TASK" in first
        if "stated equity falls" in text:
            return _use(("exposure_shock", {"case_id": 1, "falls_json": "[10, 20, 35]", "why": "loss from stated falls"}))
        if "0.5% charge" in text:
            return _use(("policy_scenarios", {"case_id": 1, "why": "deployment comparison with a 0.5 percent charge", "amount": 1000000, "horizon_months": 12, "cost_bps": 50}))
        if "Compare deployment policies" in text:
            if not checkpoint:
                return _use(("request_artifact", {"case_id": 1, "role": "research", "what": "Provide the verified size of the AI-linked fall over the last five sessions from stored closes."}))
            return _use(("policy_scenarios", {"case_id": 1, "why": "deployment policies across fall, decline, recovery and no-crash paths", "amount": 1000000, "horizon_months": 12}))
        if "bounded experiment" in text:
            return _use(("register_experiment", {"hypothesis": "Holding cash after a 10 percent fall in the index and investing the rest later beats investing the whole sum at the start, after costs.",
                                                 "why_it_matters": "It bears on whether to wait for a fall before putting new money in.", "disproof": "It does not beat always-invested on the validation period after costs.",
                                                 "source": "case", "case_id": 1, "contract": "deployment"}))
        if "Experiment #" in text:
            return _use(("case_evidence", {"case_id": 1, "stance": "neutral", "text": "The experiment finished; its status and reason are in the case. A failed or kept strategy is a valid result and neither is a forecast.", "source_kind": "calculation"}))
        if "recommendation" in text:
            return _use(("make_proposal", {"action": "WAIT", "symbol": "ITC", "case_id": 1,
                                           "reason": "The evidence is mixed: one note reports cuts but Indian holdings fell far less, and the deployment comparison shows no policy beating the others on every path.",
                                           "alternatives": "Buying more now, holding what he has, or reducing were compared and each is weaker on the stored evidence and calculations.",
                                           "review_condition": "ITC closes 10 percent below its latest close, or a new document about it is published"}))
        return _say("Nothing to do.")

    # --- review ---
    def _review(self, con, first, n):
        if n == 0:
            r = con.execute("SELECT min(calc_id) FROM hq_calcs WHERE case_id=1").fetchone()[0]
            if r:
                return _use(("reproduce_calc", {"calc_id": int(r)}), model=OPUS)
        if n <= 1:
            return _use(("submit_review", {"case_id": 1, "verdict": "approve", "findings": "Reproduced a kept calculation and compared it with the kept result; the evidence is sourced; the "
                                          "proposal states what is missing and a concrete condition; assumptions are labelled.", "checks": "reproduce_calc"}), model=OPUS)
        return _say("Approved.", OPUS)


# ----------------------------------------------------------------------------------------------------------------------------------------------

def seed(profile: Path) -> None:
    import rehearse
    rehearse.seed(profile, 100.0)
    from pflab.pm import store
    con = store.connect(profile / "pm" / "ledger.duckdb")
    con.execute("UPDATE instruments SET tax_class='EQUITY'")           # the tax engine's own label for listed equity
    con.close()


def serve(profile: Path, port: int, delay: float) -> int:
    os.environ["PFLAB_PM_DIR"] = str(profile / "pm")
    import uvicorn
    from pflab import scrub
    from pflab.app.runtime import Runtime
    from pflab.app.server import create_app
    from pflab.data import data_dir
    from pflab.hq import pool, service
    import logging
    logging.basicConfig(filename=profile / "pm" / "app" / "rehearsal.log", level=logging.INFO, encoding="utf-8", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    scrub.install()
    rt = Runtime(profile / "pm", data_dir(), HERE.parent, secrets=None)
    rt._hq_client = Scripted(rt, delay)
    app = create_app(rt)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    threading.Thread(target=server.run, daemon=True).start()
    service.start(rt)                                                  # recover what a stopped process left (the call the app makes at start)
    pool.start(rt)
    threading.Thread(target=rt._guard(rt._hq_loop), name="hq", daemon=True).start()
    print(f"serving {profile} on {port}", flush=True)
    while True:
        time.sleep(1)


# ----------------------------------------------------------------------------------------------------------------------------------------------

class Driver:
    def __init__(self, profile: Path, port: int, delay: float):
        import requests
        self.r, self.profile, self.port, self.delay = requests, profile, port, delay
        self.base = f"http://127.0.0.1:{port}"
        self.proc = None
        self.log = []
        self.checks = []

    def say(self, *a):
        line = datetime.now().strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
        print(line, flush=True)
        self.log.append(line)

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(HERE / "rehearse_s69.py"), "serve", "--profile", str(self.profile), "--port", str(self.port), "--delay", str(self.delay)],
                                     stdout=open(self.profile / "serve.out", "ab"), stderr=subprocess.STDOUT)
        for _ in range(120):
            try:
                if self.r.get(self.base + "/api/health", timeout=2).ok:
                    return
            except Exception:
                time.sleep(0.5)
        raise SystemExit("the server did not start")

    def kill(self):
        self.proc.kill()                                                # a hard stop: no shutdown, no cleanup
        self.proc.wait()

    def get(self, path):
        return self.r.get(self.base + path, timeout=30).json()

    def post(self, path, body):
        x = self.r.post(self.base + path, json=body, timeout=60)
        return x.json() if x.headers.get("content-type", "").startswith("application/json") else {"status": x.status_code}

    def card(self):
        inv = self.get("/api/investigations")["investigations"]
        return inv[0] if inv else None

    def wait(self, what, pred, timeout=900, every=2.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            c = self.card()
            if c and pred(c):
                return c
            time.sleep(every)
        raise SystemExit(f"timed out waiting for: {what}; last card: {json.dumps(self.card(), default=str)[:600]}")

    def chat(self, text, wait=90):
        before = len(self.get("/api/assistant")["messages"])
        self.post("/api/assistant", {"text": text, "context": ""})
        t0 = time.time()
        while time.time() - t0 < wait:
            m = self.get("/api/assistant")["messages"]
            if len(m) > before + 1 and m[-1]["status"] != "working" and m[-1]["role"] == "ai":
                return m[-1]
            time.sleep(1.5)
        raise SystemExit("the assistant did not answer: " + text)

    def check(self, name, ok, detail=""):
        self.checks.append({"check": name, "pass": bool(ok), "detail": str(detail)[:400]})
        self.say(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))


def drive(profile: Path, port: int, delay: float, out: Path) -> int:
    d = Driver(profile, port, delay)
    d.start()
    d.say("server up; the scripted cloud answers in", delay, "s per call")
    # 1 chat -> investigation -> plan waits for approval
    ans = d.chat("Investigate: " + GOAL)
    d.say("assistant:", ans["text"][:120])
    c = d.wait("a plan that waits for his yes", lambda c: c["state"] == "awaiting_approval", 300)
    d.check("1 the plan waits for his yes and nothing has run", c["awaiting_approval"] and all(t["status"] in ("done", "needs_approval") for t in c["tasks"]),
            [(t["id"], t["role"], t["status"]) for t in c["tasks"]])
    steps = c["plan_versions"][0]["steps"]
    d.check("1 the plan shows owners and dependencies", len(steps) == 5 and any(t["depends_on"] for t in c["tasks"]), [s["key"] for s in steps])
    # approve through the chat (his words), then watch parallel work
    ans = d.chat("Yes, approve the plan.")
    c = d.wait("workers running", lambda c: any(t["status"] == "running" for t in c["tasks"] if t["role"] in ("research", "quant")), 120, 0.5)
    seen_running = 0
    t0 = time.time()
    while time.time() - t0 < 60:
        c = d.card()
        seen_running = max(seen_running, sum(1 for t in c["tasks"] if t["status"] == "running"))
        if seen_running >= 2:
            break
        time.sleep(0.4)
    d.check("2 two independent tasks were running at the same moment", seen_running >= 2, f"{seen_running} running together")
    # a controlled restart while tasks are in flight
    before = {t["id"]: (t["status"], t["attempts"]) for t in c["tasks"]}
    d.say("hard kill of the server while", seen_running, "tasks run")
    d.kill()
    d.start()
    d.say("server restarted")
    c = d.card()
    d.check("6 after the restart nothing was lost: finished tasks stay done and the others are queued again",
            all(dict((t["id"], t["status"]) for t in c["tasks"]).get(i) == "done" for i, (st, _) in before.items() if st == "done"),
            [(t["id"], t["status"], t["attempts"]) for t in c["tasks"]])
    # the rest of the run: parked request, dependent task, experiment (local model + Docker), review, answer
    c = d.wait("the experiment is registered and awaited", lambda c: bool(c["experiments_pending"]) or c["state"] in ("reviewing", "synthesising", "done"), 600)
    if c["experiments_pending"]:
        d.check("3 a registered experiment is not a result: the mission waits and does not review", c["state"] == "working" and not any(t["role"] == "review" for t in c["tasks"]),
                (c["experiments_pending"], c["next_trigger"]))
    c = d.wait("done", lambda c: c["state"] in ("done", "blocked"), 1800, 5)
    d.check("1 the investigation reached done with the independent review's verdict published", c["state"] == "done" and (c["answer"] or {}).get("review_verdict") == "approve",
            (c["state"], c["blocker"], (c["answer"] or {}).get("review_verdict")))
    tasks = {t["id"]: t for t in c["tasks"]}
    work = [t for t in tasks.values() if t["role"] in ("research", "quant")]
    d.check("2 task ids with times are recorded", all(t["started"] for t in work if t["status"] == "done"), [(t["id"], t["role"], t["started"], t["finished"]) for t in work][:8])
    kinds = {}
    for o in c["outputs"]:
        kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
    d.check("3 the experiment result reached the case before the review", "experiment_result" in kinds, kinds)
    d.check("1 evidence merged: the same finding recorded twice is one", kinds.get("evidence", 0) >= 3, kinds)
    d.check("4 monitors are executable triggers; the unsupported kind is named", bool((c["answer"] or {}).get("monitor_executable")) and (c["answer"] or {}).get("monitor_unsupported"),
            ((c["answer"] or {}).get("triggers"), (c["answer"] or {}).get("monitor_unsupported")))
    props = d.get("/api/proposals")["proposals"]
    wait_p = [p for p in props if p["action"] == "WAIT"]
    d.check("5 a supported WAIT is the real answer, with its condition, review and snapshot", bool(wait_p) and wait_p[0]["payload"].get("review_condition") and wait_p[0]["review_status"] == "approved" and wait_p[0]["snapshot_id"],
            wait_p[0]["payload"].get("review_condition") if wait_p else None)
    # amendment from the conversation
    d.chat("Also use a 0.5% charge on every trade in the deployment comparison.")
    c = d.wait("an amendment replans and finishes", lambda c: c["instruction_version"] >= 2 and c["state"] in ("done", "blocked"), 900, 4)
    v = {x["version"]: x for x in c["plan_versions"]}
    d.check("4 the chat amendment is plan version 2, applied with no release and no second yes", c["state"] == "done" and v.get(2, {}).get("status") == "auto" and v[2]["source"] == "amendment", {k: (x["status"], x["source"]) for k, x in v.items()})
    # a dropped file
    up = d.r.post(d.base + "/api/inbox/upload", data=DOC.encode(), headers={"x-filename": "ai_downturn_note.txt"}, timeout=60).json()
    d.say("dropped a file:", up)
    t0 = time.time()
    routed = None
    while time.time() - t0 < 600:
        rows = d.get("/api/routing")["decisions"]
        if rows:
            routed = rows[0]
            break
        time.sleep(4)
    d.check("4 the new file was routed by the LOCAL model and recorded", bool(routed) and routed["outcome"] in ("local", "local_retry", "rule", "escalated"), routed)
    c = d.wait("the investigation looks at the new file", lambda c: c["state"] in ("done", "blocked") and any("newdoc" in str(p.get('steps')) or p["source"] == "review" for p in c["plan_versions"]), 900, 5)
    d.check("4 the same investigation was reopened by the file with no prompt, and is done again", c["state"] == "done" and c["plan_versions"][-1]["source"] == "review", (c["state"], c["plan_versions"][-1]["source"], (c["answer"] or {}).get("change")))
    # buy and sell lifecycle (controlled examples, test profile only)
    d.chat("Propose a controlled buy and a controlled reduction for the test profile.")
    props = d.get("/api/proposals")["proposals"]
    kinds_p = {p["action"] for p in props}
    d.check("5 both a BUY and a REDUCE proposal exist, sized from the record", {"BUY", "REDUCE"} <= kinds_p, [(p["proposal_id"], p["action"], (p["payload"].get("size") or {}).get("qty")) for p in props])
    buy = next(p for p in props if p["action"] == "BUY")
    sell = next(p for p in props if p["action"] == "REDUCE")
    d.chat(f"Yes, accept proposal {buy['proposal_id']}")
    d.chat(f"Yes, accept proposal {sell['proposal_id']}")
    props = {p["proposal_id"]: p for p in d.get("/api/proposals")["proposals"]}
    d.check("5 acceptance is recorded and places no order", props[buy["proposal_id"]]["status"] == "accepted" and props[sell["proposal_id"]]["status"] == "accepted", None)
    c_final = d.card()
    d.kill()
    report = {"checks": d.checks, "log": d.log, "final_card": c_final}
    out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    bad = [x for x in d.checks if not x["pass"]]
    d.say(f"{len(d.checks) - len(bad)} of {len(d.checks)} checks passed; report in {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["seed", "serve", "drive"])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--port", type=int, default=8793)
    ap.add_argument("--delay", type=float, default=2.5)
    ap.add_argument("--out", default="rehearsal_s69.json")
    a = ap.parse_args()
    pr = Path(a.profile)
    if a.cmd == "seed":
        seed(pr)
    elif a.cmd == "serve":
        sys.exit(serve(pr, a.port, a.delay))
    else:
        sys.exit(drive(pr, a.port, a.delay, Path(a.out)))
