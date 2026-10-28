"""The fixed drafting task set for the research-model pick (docs/STUDIES.md, registered
2026-10-06 before any evaluation). Tasks are generated from a seed, never tuned; the metric is the first-
attempt pass rate of `guard.check_all`. `evaluate` refuses to run a role/model that was not registered
before the run."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional

from pflab.llm import guard as g
from pflab.llm import registry as reg

SEED = 20261006
N_TASKS = 40
PROMPT_NAME = "draft_note_v1"
PROMPT_TEMPLATE = (
    "You write a short note for an investor. Use ONLY the FACTS and SOURCES below.\n"
    "Rules: write exactly 3 sentences. Write every number as digits exactly as given in the facts (you may round to "
    "fewer decimals). Never calculate a new number. End every sentence with a citation: [F:name] for a fact or [S1], "
    "[S2] for a source. Quote a source only verbatim inside double quotes, followed by its tag. Do not spell numbers "
    "out in words.\n\nFACTS:\n{facts}\n\nSOURCES:\n{sources}\n\nWrite the note.")

_COMPANIES = ["Alpha Industries", "Beta Foods", "Gamma Pharma", "Delta Motors", "Epsilon Power", "Zeta Textiles", "Eta Chemicals"]
_EVENTS = ["delay in submission of financial results", "appointment of a new statutory auditor", "revision of credit rating",
           "board approval of a rights issue", "resignation of the chief financial officer", "receipt of a large export order"]


@dataclass(frozen=True)
class Task:
    task_id: int
    facts: Dict
    sources: Dict[str, str]
    prompt: str


def _fmt(v) -> str:
    if isinstance(v, date):
        return v.strftime("%d-%b-%Y")
    if isinstance(v, tuple):
        return f"{v[0]:,.2f} {v[1]}"
    if isinstance(v, float) and abs(v) < 1.0:
        return f"{v:.4f}"
    return f"{v:,.2f}" if isinstance(v, float) else str(v)


def build(seed: int = SEED, n: int = N_TASKS) -> List[Task]:
    rng = random.Random(seed)
    tasks = []
    for i in range(n):
        co = rng.choice(_COMPANIES)
        ev = rng.choice(_EVENTS)
        q = date(2026, 6, 30)
        facts: Dict = {
            "revenue_ttm": (round(rng.uniform(5_000, 900_000), 2), "million"),
            "net_margin": round(rng.uniform(0.01, 0.30), 4),
            "pe_ttm": round(rng.uniform(6, 60), 1),
            "eps_ttm": round(rng.uniform(2, 120), 2),
            "price": round(rng.uniform(40, 4_000), 2),
            "quarter_end": q - timedelta(days=91 * rng.randint(0, 2)),
            "n_quarters": rng.choice([4, 6, 8]),
        }
        if rng.random() < 0.5:
            facts["yoy_revenue"] = round(rng.uniform(-0.2, 0.4), 4)
        amt = round(rng.uniform(1.0, 90.0), 1)
        sources = {"S1": f'{co} informed the exchange of a {ev} and stated that "the amount involved is Rs {amt} crore".',
                   "S2": f"{co} filed this on {rng.randint(1, 28)} {rng.choice(['July', 'August', 'September'])} 2026 under Regulation 30."}
        facts_txt = "\n".join(f"{k}: {_fmt(v)}" for k, v in facts.items())
        src_txt = "\n".join(f"[{k}] {v}" for k, v in sources.items())
        tasks.append(Task(i, facts, sources, PROMPT_TEMPLATE.format(facts=facts_txt, sources=src_txt)))
    return tasks


@dataclass
class EvalResult:
    model: str
    n: int
    first_pass: int
    within_retries: int
    tokens_per_second: Optional[float]
    seconds: float
    run_ids: List[int]

    @property
    def first_attempt_pass_rate(self) -> float:
        return self.first_pass / self.n if self.n else 0.0


def evaluate(con, model: str, role: str, llm_factory: Callable[[str], Callable[[str], str]], tasks: Optional[List[Task]] = None,
             now: Optional[datetime] = None, retries: int = 2) -> EvalResult:
    """Run the fixed tasks against `model` (refuses if its pick was not registered earlier). `llm_factory(model)` returns a
    prompt -> text callable. Every draft is logged in `llm_runs`."""
    import time as _t
    now = now or datetime.now()
    reg.require_registered(role, model, now)
    tasks = tasks if tasks is not None else build()
    llm = llm_factory(model)
    first = within = 0
    rids: List[int] = []
    t_all = _t.time()
    for t in tasks:
        t0 = _t.time()
        started = datetime.now()
        out = g.guarded_generate(llm, t.prompt, t.facts, t.sources, retries)
        first += int(out.ok and out.attempts == 1)
        within += int(out.ok)
        rids.append(reg.log_run(con, started, model, role=role, prompt_name=PROMPT_NAME, prompt_sha=reg.sha(PROMPT_TEMPLATE),
                                sources=list(t.sources), guard_result="pass" if out.ok else "dropped", attempts=out.attempts,
                                seconds=round(_t.time() - t0, 2), status="ok", note=f"task {t.task_id}"))
    return EvalResult(model, len(tasks), first, within, None, round(_t.time() - t_all, 2), rids)
