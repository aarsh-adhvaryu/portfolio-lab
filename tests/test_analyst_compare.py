"""S44 comparison harness: question set fixed by seed, blind sheet, the registered rule. SYNTHETIC."""
import json

from pflab.agents import analyst_compare as ac

STOCKS = [{"symbol": f"S{k}", "isin": f"INE00000{k:04d}"} for k in range(10)]


def test_prepare_is_fixed_by_its_seed(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    p = ac.prepare(STOCKS, {"S1": "Sone Limited"})
    h = ac.sha(p)
    assert len(json.loads(p.read_text(encoding="utf-8"))) == 20
    assert ac.sha(ac.prepare(STOCKS, {"S1": "Sone Limited"})) == h


def test_rubric_by_hand():
    known = {"1100.0", "2026", "17"}
    good = ac.measures("Revenue was 1,100.0 million in 2026 [D1]. The filings do not say why [inf].", known)
    bad = ac.measures("Revenue was 1,250 million [S1]. Margins rose to 17 percent last year.", known)
    assert good == {"numbers_found": 1.0, "cited": 1.0} and bad == {"numbers_found": 0.5, "cited": 0.5}
    assert ac.judge(good, bad) == "a" and ac.judge(None, bad) == "b" and ac.judge(None, None) == "tie"
    assert ac.judge({"numbers_found": 1.0, "cited": 0.9}, {"numbers_found": 0.97, "cited": 0.88}) == "tie"
    assert ac.measures("(no answer passed the guard)", known) is None


def test_blind_sheet_and_rule(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    ans = [{"n": k, "question": f"q{k}", "local": f"local {k}", "api": f"api {k}", "api_cost_inr": 5.0}
           for k in range(1, 21)]
    (ac.folder() / "answers.json").write_text(json.dumps(ans), encoding="utf-8")
    text = ac.sheet().read_text(encoding="utf-8")
    key = json.loads((ac.folder() / "key.json").read_text(encoding="utf-8"))
    assert "api 1" in text and "local 1" in text and set(key.values()) == {"X", "Y"}   # both orders occur
    assert ac.score() == {"done": False, "rated": 0, "of": 20}
    choose = {n: (k if int(n) <= 14 else ("TIE" if int(n) <= 16 else ("Y" if k == "X" else "X"))) for n, k in key.items()}
    (ac.folder() / "choices.toml").write_text("[choices]\n" + "\n".join(f'"{n}" = "{c}"' for n, c in choose.items()),
                                              encoding="utf-8")
    s = ac.score()
    assert s["done"] and s["api_share"] == 0.75 and s["cost_rupees"] == 100.0 and s["adopt"]   # 14 + 2 x 0.5 = 15/20
