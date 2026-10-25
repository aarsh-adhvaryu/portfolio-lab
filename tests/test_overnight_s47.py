"""Overnight additions: S47 tuning runner (FAKE model), deep-research queue and batch polling (FAKE API). SYNTHETIC."""
import json
from datetime import date, datetime
from types import SimpleNamespace as NS

import pytest

from pflab.agents import analyst as an
from pflab.agents import researcher as rs
from pflab.llm import tuning
from pflab.pm import store


def reply(obj):
    return NS(text=json.dumps(obj), digest="d", tokens_in=1, tokens_out=1, seconds=0.0)


def test_materiality_tuning_picks_on_train_and_judges_on_test(tmp_path):
    (tmp_path / "llm_eval").mkdir()
    train = [{"text": f"Outcome of board meeting {k}", "gold": "material"} for k in range(10)] + \
            [{"text": f"Newspaper advertisement {k}", "gold": "routine"} for k in range(10)]
    test = [{"text": "Outcome of board meeting X", "gold": "material"}, {"text": "Newspaper advertisement X", "gold": "routine"}]
    (tmp_path / "llm_eval" / "materiality.json").write_text(json.dumps(train), encoding="utf-8")
    (tmp_path / "llm_eval" / "materiality_r2.json").write_text(json.dumps(test), encoding="utf-8")

    def chat(model, messages, **kw):          # answers well only with the definitions (v1, v2)
        sys_, text = messages[0]["content"], messages[1]["content"]
        good = "Routine: newspaper" in sys_
        return reply({"label": ("routine" if "Newspaper" in text else "material") if good else "material"})
    r = tuning.run("materiality", "m", tmp_path, chat=chat, log=lambda s: None)
    assert r["train"]["v0"] == 0.5 and r["train"]["v1"] == 1.0 and r["best"] == "v1"      # tie v1/v2: the simpler
    assert r["test"] == {"v1": 1.0, "v0": 0.5} and r["adopt"]
    assert json.loads((tmp_path / "llm_eval" / "tuning" / "materiality.json").read_text())["best"] == "v1"


def test_writing_split_is_by_company():
    split = tuning.writing_tasks(None, [{"symbol": s} for s in "ABCDEFG"], [date(2026, 7, 17), date(2026, 8, 17)])
    tr, te = {s for s, _ in split["train"]}, {s for s, _ in split["test"]}
    assert not tr & te and len(tr | te) == 7 and len(split["train"]) == 2 * len(tr)


class FakeAPI:
    def __init__(self):
        self.batches, self.polls = [], 0
        self.messages = NS(count_tokens=lambda **kw: NS(input_tokens=3000),
                           batches=NS(create=self._create, retrieve=self._get, results=self._results))

    def _create(self, requests):
        self.batches.append(list(requests))
        return NS(id=f"b{len(self.batches)}")

    def _get(self, bid):
        self.polls += 1
        return NS(processing_status="ended" if self.polls >= 2 else "in_progress")

    def _results(self, bid):
        msg = NS(content=[NS(type="text", text="The board approved results [D1].", citations=[])], stop_reason="end_turn",
                 usage=NS(input_tokens=3000, output_tokens=400))
        return [NS(custom_id=r["custom_id"], result=NS(type="succeeded", message=msg)) for r in self.batches[-1]]


def _store(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES ('INE000A01011', 'isin', 'equity', 'listed_equity', TRUE, 'AAA', 'Aaa Limited', 'synthetic', now())""")
    return con


def test_deep_queue_sends_flagged_or_all_and_reuses_recent_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(an, "config", lambda path=None: {"model": an.MODEL, "cap": 1500.0, "ask_above": 100.0,
                                                          "usd_inr": 90.0, "adopted": True})
    monkeypatch.setattr(an, "private_values", lambda con: an.Private())
    con = _store(tmp_path)
    api = FakeAPI()
    lst = [{"symbol": "AAA", "isin": "INE000A01011"}]
    now = datetime(2026, 10, 17, 23, 0)
    assert rs.deep_queue(con, date(2026, 10, 17), lst, client=api, now=now) == {}          # nothing flagged
    assert rs.deep_queue(con, date(2026, 10, 17), lst, everyone=True, client=api, now=now) == {"AAA": "queued"}
    assert an.submit_batch(con, api, now) == "b1"
    db = tmp_path / "l.duckdb"
    con.close()
    got = an.collect_until_done(lambda: store.connect(db), api, minutes=60, poll_s=0, sleep=lambda s: None)
    assert got == {"done": 1, "failed": 0, "pending": 0} and api.polls == 2
    con = store.connect(db)
    assert len(an.recent_notes(con, datetime(2026, 10, 17))) == 1
    later = datetime(2026, 10, 20, 23, 0)                                                  # within 14 days: reused
    assert rs.deep_queue(con, date(2026, 10, 20), lst, everyone=True, client=api, now=later) == {"AAA": "reused"}
