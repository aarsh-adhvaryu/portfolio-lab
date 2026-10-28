"""S65: the agent lists, the model slider and the docs say the same thing; the model words come from what actually runs."""
import re
from pathlib import Path

import pytest

from pflab.app import views
from pflab.hq import models, roster
from pflab.llm import registry

ROOT = Path(__file__).resolve().parents[1]


def text(a):
    return next(r["model"] for r in roster.listing({}) if r["name"] == a)


def test_the_agents_model_words_follow_the_slider():
    assert "Sonnet 5.5 writes the code, Opus 5.5 writes it again" in text("calc")
    mine = {"models": {"workshop": "opus", "research": "opus", "brain": "sonnet", "learner_reading": "haiku"}}
    by = {r["name"]: r["model"] for r in roster.listing(mine)}
    assert "Opus 5.5 writes the code, Sonnet 5.5 writes it again" in by["calc"]
    assert by["research"].startswith("Opus 5.5") and by["brain"].startswith("Sonnet 5.5 with tools (Opus 5.5 as its")
    assert by["learner"].startswith("Haiku 5.5 reads")
    assert all("{" not in v for v in by.values())                                   # every placeholder was filled


def test_the_dashboards_agent_table_has_no_stale_model_names():
    words = models.labels({})
    rows = [(n, m.format(**words)) for n, js, m, *_ in views.ROSTER]
    assert all("{" not in m for _, m in rows)
    d = dict(rows)
    assert "Sonnet 5.5 writes the code, Opus 5.5 writes it again" in d["Workshop"]
    assert d["Analyst"].startswith("Sonnet 5.5 (the doorbell)") and "Opus 5.5 for web search" in d["Analyst"]
    swapped = models.labels({"models": {"workshop": "opus"}})
    assert "Opus 5.5 writes the code" in dict((n, m.format(**swapped)) for n, js, m, *_ in views.ROSTER)["Workshop"]


def test_every_slider_job_has_words_and_the_other_model_is_the_check():
    w = models.labels({})
    assert set(models.JOBS) <= set(w) and w["workshop_check"] == "Opus 5.5" and w["brain_rival"] == "Sonnet 5.5"
    assert models.label("answers", {"models": {"answers": "cascade"}}).startswith("local qwen3 8B, then Haiku")


def test_the_local_model_is_the_one_the_docs_name():
    assert registry.chosen("general") == models.LOCAL_DEFAULT == "qwen3:8b-q8_0"
    for doc in ("CLAUDE.md", "docs/BUILT.md"):
        assert models.LOCAL_DEFAULT in (ROOT / doc).read_text(encoding="utf-8") or doc.endswith("BUILT.md") and "qwen3:8b-q8_0" in (ROOT / doc).read_text(encoding="utf-8")


def test_built_md_lists_every_board_agent_and_the_right_count():
    built = (ROOT / "docs" / "BUILT.md").read_text(encoding="utf-8")
    n = len(roster.ROSTER)
    assert f"**{n} agents on the board**" in built
    for a in roster.ROSTER.values():
        assert a.title.lower() in built.lower() or a.name in built, a.name
    assert f"the {len(views.ROSTER)} job-level agents" in built


def test_built_md_lists_every_job_and_every_brain_tool():
    from pflab.hq import tools
    from pflab.service import jobs
    built = (ROOT / "docs" / "BUILT.md").read_text(encoding="utf-8")
    for j in jobs.REGISTRY:
        assert f"| {j} " in built or f"| {j} /" in built or f"/ {j} |" in built, j
    for t in tools.TOOLS:
        assert t in built, t
