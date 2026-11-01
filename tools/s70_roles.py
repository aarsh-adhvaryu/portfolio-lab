"""S70 measured seats: the paid run (protocol docs/protocols/s70_roles_protocol.md). Development only; synthetic dossiers; never the investor's record.

    python tools/s70_roles.py seed  --profile <new empty folder> [--cap 160]
    python tools/s70_roles.py pilot --profile <folder>                     (2 faulty + 1 clean review and 1 plan per model: measures the cost per call)
    python tools/s70_roles.py run   --profile <folder> [--n-fault 24] [--n-clean 4] [--plans 6] [--out results.json]
    python tools/s70_roles.py report --out results.json

Paid calls need PFLAB_PAID (set here for this process only) and the API key in the secrets file (never printed). Every call goes through `hq/llm.call`: priced
first, checked against the profile's own window cap (the hard stop for this measurement), logged in the profile's `api_calls`. The two models see the same
dossier, system text, tool and settings, one call each, interleaved item by item so that a cap reached half-way cannot favour one of them. Resumable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

MODELS = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5"}
MAX_TOKENS = 6000


def seed(profile: Path, cap: float) -> None:
    from pflab.pm import store
    if profile.exists() and any(profile.iterdir()):
        raise SystemExit(f"{profile} is not empty: a measurement profile is always new")
    pm = profile / "pm"
    (pm / "app").mkdir(parents=True)
    store.connect(pm / "ledger.duckdb").close()
    since, until = datetime.now() - timedelta(hours=1), datetime.now() + timedelta(days=2)
    (pm / "api_budget.toml").write_text(
        "[api]\nmodel = \"claude-opus-5-5\"\nmonthly_cap_rupees = 2500\ndev_monthly_cap_rupees = 0\nask_above_rupees = 100\nusd_inr = 90.0\nadopted = true\n"
        "[egress]\nnames = [\"synthname\", \"synthsurname\"]\naddress = []\n"
        f"[acceptance]\nsince = {since:%Y-%m-%dT%H:%M:%S}\nuntil = {until:%Y-%m-%dT%H:%M:%S}\ncap_rupees = {cap}\n", encoding="utf-8")
    (pm / "app" / "settings.json").write_text(json.dumps({"scheduler": False, "brain": "normal", "telegram_send": False}), encoding="utf-8")
    print(f"seeded {profile}: window cap Rs {cap} (this measurement's hard stop)")


def _open(profile: Path):
    os.environ["PFLAB_PM_DIR"] = str(profile / "pm")
    os.environ["PFLAB_PAID"] = "1"                         # the workshop's explicit switch for paid calls (src/pflab/guard.py), this process only
    os.environ.pop("PFLAB_CHANNEL", None)
    from pflab.agents import analyst as an
    from pflab.hq import egress, llm
    from pflab.pm import secrets as sec, store
    con = store.connect(profile / "pm" / "ledger.duckdb")
    return con, llm.client(sec.load()), egress.load(con), an.config()


def _call(con, client, gate, cfg, model: str, params: dict, label: str):
    from pflab.hq import llm
    s = llm.call(con, "w_review" if label.startswith("r") else "w_coord", params, client, now=datetime.now(), mode="normal", private_text="", gate=gate,
                 doc_kinds=(), topic="s70_roles", question=label, cfg=cfg, turn=1, his_order=True)
    u = s.message.usage
    return s, {"in": int(getattr(u, "input_tokens", 0) or 0) + int(getattr(u, "cache_read_input_tokens", 0) or 0), "out": int(getattr(u, "output_tokens", 0) or 0)}


def _tool_input(msg, name: str):
    for b in msg.content:
        if getattr(b, "type", "") == "tool_use" and getattr(b, "name", "") == name:
            return dict(b.input)
    return None


def review_params(model: str, item) -> dict:
    from pflab.eval import roles as R
    from pflab.hq import tools as tl, workers
    return {"model": model, "max_tokens": MAX_TOKENS, "system": [{"type": "text", "text": workers.SYSTEMS["review"]}], "thinking": {"type": "adaptive"},
            "output_config": {"effort": "medium"}, "tools": tl.definitions(frozenset({"submit_review"})),
            "messages": [{"role": "user", "content": [{"type": "text", "text": R.REVIEW_TASK + item.dossier}]}]}


def plan_params(model: str, i: int) -> dict:
    from pflab.eval import roles as R
    from pflab.hq import tools as tl, workers
    return {"model": model, "max_tokens": MAX_TOKENS, "system": [{"type": "text", "text": workers.SYSTEMS["coordinator"]}], "thinking": {"type": "adaptive"},
            "output_config": {"effort": "medium"}, "tools": tl.definitions(frozenset({"plan_mission"})),
            "messages": [{"role": "user", "content": [{"type": "text", "text": R.plan_task_text(i)}]}]}


def run(profile: Path, n_fault: int, n_clean: int, plans: int, out: Path) -> dict:
    from pflab.eval import roles as R
    con, client, gate, cfg = _open(profile)
    res = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"reviews": {}, "plans": {}}
    items = R.reviewer_set(n_fault, n_clean)
    # interleave the faulty and the clean ones so a stop part-way leaves both kinds
    order = [i for pair in zip(items[:n_fault], items[n_fault:] + [None] * n_fault) for i in pair if i is not None] + items[n_fault + n_clean:]
    order = sorted(set(order), key=lambda i: order.index(i))
    jobs = [("review", i.id, i) for i in order] + [("plan", f"p{k + 1}", k) for k in range(plans)]
    spent0 = float(con.execute("SELECT coalesce(sum(cost_inr),0) FROM api_calls WHERE status IN ('done','refused')").fetchone()[0])
    for kind, jid, payload in jobs:
        for name, model in MODELS.items():
            slot = res["reviews" if kind == "review" else "plans"].setdefault(jid, {})
            if name in slot:
                continue
            t0 = time.time()
            try:
                if kind == "review":
                    s, use = _call(con, client, gate, cfg, model, review_params(model, payload), jid)
                    got = _tool_input(s.message, "submit_review")
                    words = " ".join(str(got.get(k, "")) for k in ("findings", "checks", "revisions_json")) if got else ""
                    row = {"verdict": (got or {}).get("verdict"), "words": words, "fault": payload.fault}
                else:
                    s, use = _call(con, client, gate, cfg, model, plan_params(model, payload), jid)
                    got = _tool_input(s.message, "plan_mission")
                    try:
                        steps = json.loads((got or {}).get("steps_json", "null"))
                    except ValueError:
                        steps = None
                    row = {"steps": steps, "approach": (got or {}).get("approach", ""), "kind": R.PLANNER_TASKS[payload][0]}
                row.update({"cost": round(s.cost_inr, 2), "tokens": use, "seconds": round(time.time() - t0, 1), "stop": getattr(s.message, "stop_reason", "")})
            except Exception as e:                           # a refused call (the cap) or a provider error ends the run for this item; it is recorded, never hidden
                row = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
                slot[name] = row
                out.write_text(json.dumps(res, indent=1), encoding="utf-8")
                print(f"STOPPED at {jid} {name}: {row['error']}")
                return res
            slot[name] = row
            out.write_text(json.dumps(res, indent=1), encoding="utf-8")
            print(f"{jid:28s} {name:7s} {row.get('verdict') or ('plan' if kind == 'plan' else '-'):8s} Rs {row['cost']:6.2f}  {row['tokens']['in']:>6} in {row['tokens']['out']:>5} out  {row['seconds']:5.1f}s")
    spent = float(con.execute("SELECT coalesce(sum(cost_inr),0) FROM api_calls WHERE status IN ('done','refused')").fetchone()[0]) - spent0
    print(f"this run: Rs {spent:,.2f}")
    return res


def report(out: Path) -> dict:
    from pflab.eval import roles as R
    res = json.loads(out.read_text(encoding="utf-8"))
    items = {i.id: i for i in R.reviewer_set(24, 4)}
    summ, costs = {}, {}
    for name in MODELS:
        rows = [R.graded(items[jid], v[name].get("verdict"), v[name].get("words", "")) for jid, v in res["reviews"].items() if name in v and "error" not in v[name]]
        summ[name] = R.summarize(rows)
        costs[name] = [v[name]["cost"] for v in res["reviews"].values() if name in v and "cost" in v[name]]
    done = [jid for jid, v in res["reviews"].items() if all(n in v and "error" not in v[n] for n in MODELS)]
    # the rule is applied to the items BOTH models completed
    both = {n: R.summarize([R.graded(items[j], res["reviews"][j][n].get("verdict"), res["reviews"][j][n].get("words", "")) for j in done]) for n in MODELS}
    out_ = {"reviewer": {"summary": both, "decision": R.decide(both["opus"], both["sonnet"]) if both["opus"]["faulty"] else None,
                         "mean_cost_rs": {n: round(sum(c) / len(c), 2) if c else None for n, c in costs.items()}}}
    pl = {n: R.plan_summary([R.plan_scores(v[n]["kind"], v[n].get("steps"), v[n].get("approach", "")) for v in res["plans"].values() if n in v and "error" not in v[n]]) for n in MODELS}
    out_["planner"] = {"summary": pl, "decision": R.decide_planner(pl["opus"], pl["sonnet"]) if pl["opus"]["tasks"] else None}
    print(json.dumps(out_, indent=1))
    return out_


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["seed", "pilot", "run", "report"])
    ap.add_argument("--profile", type=Path)
    ap.add_argument("--cap", type=float, default=160.0)
    ap.add_argument("--n-fault", type=int, default=24)
    ap.add_argument("--n-clean", type=int, default=4)
    ap.add_argument("--plans", type=int, default=6)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    if a.cmd == "seed":
        seed(a.profile, a.cap)
    elif a.cmd == "pilot":
        run(a.profile, 2, 1, 1, a.profile / "pilot.json")
    elif a.cmd == "run":
        run(a.profile, a.n_fault, a.n_clean, a.plans, a.out or a.profile / "results.json")
    else:
        report(a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
