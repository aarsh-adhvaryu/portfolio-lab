"""S49 retrieval comparison with a FAKE question writer and FAKE embeddings. SYNTHETIC."""
from datetime import date, datetime

import numpy as np
import pytest

from pflab.agents import memory as mem
from pflab.agents import memory_compare as mc
from pflab.kg import graph as g
from pflab.pm import store


def test_ranking_pieces_by_hand():
    items = [{"text": "credit rating downgrade by agency", "at": datetime(2026, 10, 1)},
             {"text": "board approves dividend payout", "at": datetime(2026, 10, 2)},
             {"text": "dividend record date fixed", "at": datetime(2026, 10, 3)}]
    assert mc.rank_words("When is the dividend record date?", items)[0] == 2
    assert mc.fuse([0, 1, 2], [2, 1, 0])[:2] in ([0, 2], [2, 0]) and mc.fuse([1, 0], [1, 2])[0] == 1
    assert mc.metrics([[1, 0, 2], [5, 6, 7, 8, 9, 4]], [0, 4]) == {"recall@5": 0.5, "mrr": pytest.approx((0.5 + 1 / 6) / 2)}


def test_run_end_to_end_and_the_rule(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    topics = ["dividend", "rating", "acquisition", "order", "auditor", "pledge", "results", "buyback"]
    for k in range(90):
        t = topics[k % len(topics)]
        g.doc(con, "filing", f"k{k}", datetime(2026, 9, 1 + k % 28), f"Company {k} files about {t} matter number {k}",
              source="BSE")
    mem.remember(con, "decision", "keep the target mix at the any-day fall chance", subject="mix", now=datetime(2026, 10, 17))
    vocab = {t: i for i, t in enumerate(topics)}

    def fake_embed(method, path, payload, timeout):         # embeddings that know the topic word only
        out = []
        for s in payload["input"]:
            v = np.zeros(len(topics) + 1)
            for t, i in vocab.items():
                if t in s.lower():
                    v[i] = 1.0
            v[-1] = 0.01
            out.append(v.tolist())
        return {"embeddings": out}

    llm = lambda prompt: "Which " + prompt.split("TEXT:\n")[1].split()[4] + " news came out?"   # the topic word
    r = mc.run(con, date(2026, 10, 17), llm, tmp_path, transport=fake_embed, log=lambda s: None)
    assert r["items"] == 91 and r["questions"] == 80
    assert set(r["test"]) == {"words", "embed", "hybrid"} and r["chosen_on_dev"] in ("embed", "hybrid")
    assert (tmp_path / "llm_eval" / "memory_compare.json").exists()


def test_the_adopted_lookup_caches_embeddings_and_falls_back_to_words(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    g.doc(con, "filing", "a", datetime(2026, 10, 1), "Board approves a buyback of shares at a premium", source="BSE")
    g.doc(con, "filing", "b", datetime(2026, 10, 2), "Credit rating agency reaffirms the long term rating", source="BSE")
    g.doc(con, "filing", "c", datetime(2026, 10, 20), "Credit rating downgraded after the date asked about", source="BSE")
    mem.remember(con, "decision", "no more buys of power utilities this year", subject="power", now=datetime(2026, 10, 5))
    calls = []

    def fake_embed(method, path, payload, timeout):
        calls.append(len(payload["input"]))
        return {"embeddings": [[1.0 if "rating" in s.lower() else 0.0, 1.0 if "buy" in s.lower() else 0.0, 0.1]
                               for s in payload["input"]]}
    cache = tmp_path / "pm" / "lookup.npz"
    hits = mc.lookup(con, "what did the rating agency say?", date(2026, 10, 17), k=2, cache=cache, transport=fake_embed)
    assert "reaffirms" in hits[0]["text"] and all("downgraded" not in h["text"] for h in hits)   # nothing after asof
    assert cache.exists() and calls == [3, 1]                     # three items embedded once, then the question
    mc.lookup(con, "power utilities decision", date(2026, 10, 17), cache=cache, transport=fake_embed)
    assert calls == [3, 1, 1]                                     # cached: only the new question is embedded

    def down(*a):
        raise ConnectionError("ollama is not running")
    hits = mc.lookup(con, "buyback premium", date(2026, 10, 17), k=1, cache=tmp_path / "x.npz", transport=down)
    assert "buyback" in hits[0]["text"]                           # words alone
