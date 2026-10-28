"""The model slider (S61, PLAN A19): one model setting per job of the system.

    default    measured: `configs/models.toml [defaults]` (written by the S61 scoring tool, retired in S63, from the registered
               protocol `docs/STUDIES.md`), else the job's default below (step 1, S59, S60)
    setting    the investor's choice on the Settings screen (`settings.json` "models"), which wins over the default
    road       every Claude model goes through `hq/llm.py` (egress list, priced, governed, logged); the local model
               through `llm.client` on this PC. A job whose model fails or is refused falls to the next of its chain.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Tuple

from pflab import _toml
from pflab.hq import governor as gv

DECIDED_PATH = Path(__file__).resolve().parents[3] / "configs" / "models.toml"
LOCAL_DEFAULT = "qwen3:8b-q8_0"
IDS = {"haiku": gv.HAIKU, "sonnet": gv.SONNET, "opus": gv.OPUS}


@dataclass(frozen=True)
class Job:
    name: str
    about: str
    choices: Tuple[str, ...]
    default: str
    basis: str


JOBS: Dict[str, Job] = {j.name: j for j in [
    Job("routing", "the ask centre picks the tools a question needs", ("haiku", "local"), "haiku",
        "step 1: Haiku 96.7% vs local 95%"),
    Job("answers", "live answers on your own data, checked by the guard", ("cascade", "local", "haiku", "sonnet"),
        "cascade", "step 1: local first, Haiku when its draft fails (10 of 12); S61 job 1 measures"),
    Job("materiality", "does a filing matter to an investor holding the stock", ("haiku", "sonnet"), "haiku",
        "step 1: Haiku 86% (bar 90%); S61 job 2 measures"),
    Job("extraction", "figures read from documents, each found in the text", ("haiku", "sonnet"), "haiku",
        "step 1: Haiku F1 1.00"),
    Job("web", "web search answers, cited pages only", ("opus", "sonnet"), "opus",
        "S61 amendment 2: not scored (only 2 web questions ever asked); Opus stays"),
    Job("research", "deep research notes on a company (the doorbell)", ("opus", "sonnet"), "opus",
        "S61 job 4 (sonnet_vs_opus_protocol.md)"),
    Job("notes", "the nightly company notes (batched)", ("sonnet", "opus"), "sonnet", "S59"),
    Job("workshop", "the workshop writes calculations as code", ("opus", "sonnet"), "opus",
        "S61 job 5 (sonnet_vs_opus_protocol.md)"),
    Job("brain", "the brain's passes (the other model is its journal-only rival)", ("opus", "sonnet"), "opus",
        "protocol amendment 2: decided at 20 scored predictions each"),
    Job("gatekeeper", "whether new events deserve a brain pass", ("haiku", "sonnet"), "haiku", "S59"),
    Job("fetch", "reading a page or filing already cited", ("sonnet", "haiku", "opus"), "sonnet", "S60"),
    Job("learner_reading", "the learner screens papers and blogs and finds their testable claims",
        ("local", "haiku", "sonnet"), "local", "S62: free first (public text; a claim must quote its source and fit a "
        "coded test); Haiku when the local reply does not parse"),
    Job("learner_proposals", "the learner words changes to the brain's instructions from its own record",
        ("sonnet", "opus", "haiku"), "sonnet", "S62: weekly at most, only when the record has something new"),
    Job("brain_web", "the brain's own web lookups (it judges the cited answer itself)", ("sonnet", "haiku", "opus"),
        "sonnet", "S62: Opus cost Rs 23.65 for one lookup (search results are input); Sonnet halves it; A20 measures "
        "web on 20 real questions"),
    Job("review", "the security agent's weekly review of new code for bugs and leaks", ("sonnet", "opus", "haiku"),
        "sonnet", "S62: code only (the privacy grep passes first), about Rs 10 a review"),
    Job("mail_reading", "reading what your bank and broker emails say (they never leave this PC)", ("local",), "local",
        "S66: his emails carry his banking details: local only; numbers kept only when the email itself states them"),
]}


def decided(path: Optional[Path] = None) -> Dict[str, str]:
    p = path or DECIDED_PATH
    d = (_toml.load(p).get("defaults", {}) if p.exists() else {})
    return {k: v for k, v in d.items() if k in JOBS and v in JOBS[k].choices}


def valid(d: dict) -> Dict[str, str]:
    return {k: v for k, v in (d or {}).items() if k in JOBS and v in JOBS[k].choices}


LEARNED_NAME = "learned_models.toml"


def learned(path: Optional[Path] = None) -> Dict[str, str]:
    """S62: a job's model set by the learner from a registered comparison (`pm\\learned_models.toml`)."""
    if path is None:
        from pflab.pm import store
        path = store.pm_dir() / LEARNED_NAME
    return valid(_toml.load(path).get("models", {})) if path.exists() else {}


def write_learned(job: str, value: str, why: str, path: Optional[Path] = None) -> None:
    if job not in JOBS or value not in JOBS[job].choices:
        raise ValueError(f"{job} = {value!r} is not a choice")
    if path is None:
        from pflab.pm import store
        path = store.pm_dir() / LEARNED_NAME
    cur = {**learned(path), job: value}
    path.write_text("# Written by the learner (S62, learner/record.py) from registered comparisons; the investor's Settings win.\n"
                    f"# Last: {job} = {value}: {why[:200]}\n[models]\n" + "".join(f'{k} = "{v}"\n' for k, v in sorted(cur.items())),
                    encoding="utf-8")


def _settings(settings: Optional[dict]) -> dict:
    if settings is not None:
        return settings
    from pflab.app import settings as st
    from pflab.pm import store
    return st.load(store.pm_dir())


def choice(job: str, settings: Optional[dict] = None, path: Optional[Path] = None) -> str:
    """The investor's setting, else the learner's (a registered comparison), else the measured default, else the job's own."""
    s = valid(_settings(settings).get("models") or {})
    try:
        ln = learned()
    except Exception:
        ln = {}
    return s.get(job) or ln.get(job) or decided(path).get(job) or JOBS[job].default


def model_id(job: str, settings: Optional[dict] = None) -> str:
    c = choice(job, settings)
    if c in ("local", "cascade"):
        from pflab.llm import registry
        return registry.chosen("general") or LOCAL_DEFAULT
    return IDS[c]


NAMES = {"local": "local qwen3 8B", "cascade": "local qwen3 8B, then Haiku 5.5 when the guard rejects its draft",
         "haiku": "Haiku 5.5", "sonnet": "Sonnet 5.5", "opus": "Opus 5.5"}


def label(job: str, settings: Optional[dict] = None) -> str:
    """The model words for a job as it is NOW (his setting, the learner's, the measured default): what the agent lists show, so
    the text can never drift from what runs (S65)."""
    return NAMES[choice(job, settings)]


def labels(settings: Optional[dict] = None) -> Dict[str, str]:
    """`{job}` -> words for every job, plus `{brain_rival}` (the brain's journal-only rival is the other of Opus and Sonnet) and
    `{workshop_check}` (the workshop's independent second writing is always the other model)."""
    out = {j: label(j, settings) for j in JOBS}
    other = lambda c: NAMES["sonnet" if c == "opus" else "opus"]            # noqa: E731
    out["brain_rival"] = other(choice("brain", settings))
    out["workshop_check"] = other(choice("workshop", settings))
    return out


def listing(settings: Optional[dict] = None) -> List[dict]:
    s = _settings(settings)
    mine, dec = valid(s.get("models") or {}), decided()
    return [{"job": j.name, "about": j.about, "choices": list(j.choices), "default": dec.get(j.name, j.default),
             "basis": "measured (configs/models.toml)" if j.name in dec else j.basis, "chosen": choice(j.name, s),
             "yours": j.name in mine} for j in JOBS.values()]


# --- callables for the ask centre ---------------------------------------------------------------------------------------

@dataclass
class Road:
    """What a Claude callable needs: the ledger, the client, the egress gate and the brain setting (for the limits)."""
    con: object
    client: object
    gate: object
    mode: str = "economy"
    cfg: Optional[dict] = None


def road(con, settings: Optional[dict] = None) -> Optional[Road]:
    """The API road from this PC's secrets; None when there is no key (the local model and keywords then serve)."""
    from pflab.agents import analyst as an
    from pflab.hq import egress
    from pflab.pm import secrets as sec
    try:
        client = an.make_client(sec.load())
    except Exception:
        return None
    return Road(con, client, egress.load(con), _settings(settings).get("brain", "economy"))


def tokens(text: str, r: Road) -> Tuple[str, Dict[str, str]]:
    """The investor 2026-10-25: what the local model sees, every model sees. The facts are code-made and carry his FD and
    account numbers, which no answer needs: the ledger's ids go as letter tokens ([ID-A], [ID-B]: no digit for the
    guard to read as a number), anything else identifying through `redact`; returns (text, token -> id) so the reply
    gets the real ids back on this PC."""
    from pflab.hq import redact
    back: Dict[str, str] = {}
    for i in sorted(r.gate.ids, key=len, reverse=True):
        if i in text:
            tok = f"[ID-{chr(65 + len(back) % 26)}{'' if len(back) < 26 else len(back) // 26}]"
            back[tok] = i
            text = text.replace(i, tok)
    return redact.redact(text, r.gate, lines=False)[0], back


def restore(text: str, back: Dict[str, str]) -> str:
    for tok, i in back.items():
        text = text.replace(tok, i)
    return text


def agent_for(model: str) -> str:
    return "wording" if model == gv.HAIKU else "worker"


def claude_llm(r: Road, model: str, system: str = "", max_out: int = 1500, effort: str = "low",
               topic: str = "answer") -> Callable[[str], str]:
    """prompt -> text on a Claude model through the governed road (his portfolio may go; identity never)."""
    from datetime import datetime
    from pflab.hq import llm

    def call(prompt: str) -> str:
        prompt, back = tokens(prompt, r)
        p = {"model": model, "max_tokens": max_out, "output_config": {"effort": effort},
             "messages": [{"role": "user", "content": prompt}]}
        if system:
            p["system"] = system
        return restore(llm.call(r.con, agent_for(model), p, r.client, now=datetime.now(), mode=r.mode,
                                private_text=prompt, gate=r.gate, doc_kinds=("portfolio",), topic=topic,
                                question=prompt[:200], cfg=r.cfg).text, back)
    return call


def claude_chat(r: Road, model: str, agent: str = "router") -> Callable:
    """eval12's Chat signature (model, messages, fmt, num_predict) on a Claude model: a JSON schema goes in the system."""
    from datetime import datetime
    from pflab.hq import llm

    def chat(_model, messages, fmt=None, num_predict=400, **_):
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        if fmt:
            system += "\nReply with JSON only, matching this JSON schema: " + json.dumps(fmt)
        user = tokens("\n".join(m["content"] for m in messages if m["role"] != "system"), r)[0]
        p = {"model": model, "max_tokens": max(1024, num_predict * 4), "output_config": {"effort": "low"},
             "system": system, "messages": [{"role": "user", "content": user}]}
        s = llm.call(r.con, agent, p, r.client, now=datetime.now(), mode=r.mode, private_text=user, gate=r.gate,
                     doc_kinds=("portfolio",), topic="routing", question=user[-200:], cfg=r.cfg)
        return SimpleNamespace(text=s.text, tokens_in=None, tokens_out=None, seconds=None, digest=None)
    return chat


def router(con, settings: Optional[dict] = None, r: Optional[Road] = None) -> Tuple[Optional[str], Optional[Callable]]:
    """(model, chat) for the ask centre's routing; (None, None) leaves it to keywords."""
    c = choice("routing", settings)
    if c == "haiku":
        r = r or road(con, settings)
        if r is not None:
            return gv.HAIKU, claude_chat(r, gv.HAIKU)
    from pflab.llm import client, registry
    m = registry.chosen("routing")
    return (m, client.chat) if m else (None, None)


def answer_chain(con, system: str, settings: Optional[dict] = None, r: Optional[Road] = None) -> List[Tuple[str, Callable]]:
    """The models that draft a live answer, in order: the next one tries when a draft fails the guard."""
    from pflab.llm import client
    c = choice("answers", settings)
    local = lambda: client.as_llm(model_id("answers", settings), system, num_predict=500)    # noqa: E731
    names = {"cascade": ["local", "haiku"], "local": ["local"], "haiku": ["haiku"], "sonnet": ["sonnet"]}[c]
    out = []
    for n in names:
        if n == "local":
            out.append(("local", local()))
        else:
            r = r or road(con, settings)
            if r is not None:
                out.append((n, claude_llm(r, IDS[n], system, effort="medium" if n == "haiku" else "low")))
    return out
