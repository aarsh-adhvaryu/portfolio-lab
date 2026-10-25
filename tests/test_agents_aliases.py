"""S43: the context tool finds list companies by name from the list file and the instrument master, never from
names written in the code. SYNTHETIC companies."""
import re

import pandas as pd

from pflab.agents import tools
from pflab.kg import build as kb
from pflab.plan import stock_list as sl

STOCKS = [{"symbol": "ALPHAGRN", "isin": "INE000A01011", "aliases": ["alpha green"]},
          {"symbol": "ALPHAPWR", "isin": "INE000A01022"},
          {"symbol": "BETAFIN", "isin": "INE000B01011"},
          {"symbol": "GMX", "isin": "INE000C01011", "aliases": ["gmx"]}]
NAMES = {"INE000A01011": "Alpha Green Energy Limited", "INE000A01022": "Alpha Power Limited",
         "INE000B01011": "Betafin Finance Ltd", "INE000C01011": "Gamma Exchange Limited"}


def fake_universe(con, stocks):
    return pd.DataFrame([{"isin": s["isin"], "symbol": s["symbol"], "scrip": None, "aliases": s.get("aliases", []),
                          "name": NAMES[s["isin"]], "sector": None} for s in stocks])


def hits(qa, q):
    return sorted(s for s, ns in qa.items() if any(re.search(r"\b" + re.escape(n) + r"\b", q, re.I) for n in ns))


def test_names_come_from_the_list_and_the_master(monkeypatch):
    monkeypatch.setattr(kb, "universe", fake_universe)
    qa = tools.question_aliases(None, STOCKS)
    assert hits(qa, "why did alpha green fall?") == ["ALPHAGRN"]              # alias from the list file
    assert hits(qa, "news on Alpha Power") == ["ALPHAPWR"]                   # legal name, suffix stripped
    assert hits(qa, "anything on alpha?") == []                              # shared first word: never guessed
    assert hits(qa, "betafin results") == ["BETAFIN"]                        # unique first word
    assert hits(qa, "is gmx listed?") == ["GMX"]


def test_aliases_survive_a_rewrite_of_the_list(tmp_path):
    p = tmp_path / "stock_list.toml"
    p.write_text("# my list\n", encoding="utf-8")
    sl._write(STOCKS, p)
    assert sl.load(p) == STOCKS and p.read_text(encoding="utf-8").startswith("# my list\n")


def test_no_company_names_in_the_context_tool():
    import inspect
    src = inspect.getsource(tools.context) + inspect.getsource(tools.question_aliases)
    assert not re.search(r'"[a-z ]{3,}"\s*:\s*"[A-Z]{3,}"', src)              # no {"name": "SYMBOL"} table
