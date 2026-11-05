"""S79 item 14 (A41): the model lab skeleton under tools/model_lab. Everything runs WITHOUT torch: dry runs, the dataset builder on a
synthetic ledger copy, the Modelfile, the clear failure when the [ml] extra is missing, and the guarantee that the app and the base
install never import torch."""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "tools" / "model_lab"
sys.path.insert(0, str(LAB))

import lab_common as lab          # noqa: E402
import build_dataset as bd        # noqa: E402
import train_qlora as tq          # noqa: E402
import steer as st                # noqa: E402
import merge_and_gguf as mg       # noqa: E402
import make_modelfile as mm       # noqa: E402
import run_evals as re_           # noqa: E402

ML = ("torch", "transformers", "peft", "trl", "bitsandbytes")


@pytest.fixture
def no_extra(monkeypatch):
    """Pretend the [ml] extra is absent, whatever is installed on this PC."""
    monkeypatch.setattr(lab, "have", lambda m: False)


# ---- dataset builder --------------------------------------------------------------------------------------------------------

def _ledger(path: Path, rows) -> Path:
    con = duckdb.connect(str(path))
    con.execute("""CREATE TABLE briefs (brief_id INTEGER PRIMARY KEY, isin VARCHAR NOT NULL, symbol VARCHAR, as_of DATE NOT NULL,
                   built_at TIMESTAMP NOT NULL, trigger VARCHAR, verified BOOLEAN NOT NULL, text VARCHAR NOT NULL)""")
    con.execute("""CREATE TABLE llm_runs (run_id INTEGER PRIMARY KEY, started_at TIMESTAMP NOT NULL, role VARCHAR, model VARCHAR NOT NULL,
                   model_digest VARCHAR, prompt_name VARCHAR, prompt_sha VARCHAR, sources_json VARCHAR, guard_result VARCHAR,
                   attempts INTEGER, tokens_in INTEGER, tokens_out INTEGER, seconds DOUBLE, status VARCHAR, note VARCHAR)""")
    for i, (as_of, verified, text) in enumerate(rows, 1):
        con.execute("INSERT INTO briefs VALUES (?,?,?,?,?,?,?,?)",
                    [i, f"INE{i:09d}", f"SYM{i}", as_of, "2026-11-01 10:00:00", "t", verified, text])
    con.execute("INSERT INTO llm_runs VALUES (1,'2026-11-01 10:00:00','brief','m',NULL,'p','s','[]','pass',1,1,1,1.0,'ok','')")
    con.execute("INSERT INTO llm_runs VALUES (2,'2026-11-01 10:00:00','brief','m',NULL,'p','s','[]','dropped',3,1,1,1.0,'ok','')")
    con.close()
    return path


def _rows():
    good = "Revenue rose in the quarter [F:revenue] according to the company's results filing [S1]. Margins were stable [F:margin]."
    out = [(date(2026, 1, d), True, f"{good} Note {d}.") for d in range(1, 13)]
    out.append((date(2026, 1, 20), False, "REJECTED BY THE GUARD: profit tripled to 99 crore with no citation at all anywhere here."))
    out.append((date(2026, 1, 21), True, "token sk-ant-abcdefghijklmnopqrstuvwxyz leaked into a brief text that is long enough to count."))
    out.append((date(2026, 1, 22), True, f"{good} Note 1."))                      # duplicate of the first text
    out.append((date(2026, 1, 23), True, "too short"))
    return out


def test_dataset_drops_guard_rejected_and_unsafe_rows(tmp_path):
    led = _ledger(tmp_path / "copy.duckdb", _rows())
    out = tmp_path / "ds"
    m = bd.build(led, out)
    assert m["dropped"] == {"guard_rejected": 1, "privacy": 1, "duplicate": 1, "length": 1}
    assert m["llm_runs_by_guard_result"] == {"pass": 1, "dropped": 1}
    text = (out / "train.jsonl").read_text(encoding="utf-8") + (out / "valid.jsonl").read_text(encoding="utf-8")
    assert "REJECTED BY THE GUARD" not in text and "sk-ant-" not in text
    ex = [json.loads(l) for l in text.splitlines()]
    assert len(ex) == m["kept"] == 12 and m["train"] + m["valid"] == 12
    assert all([t["role"] for t in e["messages"]] == ["system", "user", "assistant"] for e in ex)
    assert ledger_name_only(m)


def ledger_name_only(m) -> bool:
    return m["ledger_copy"] == "copy.duckdb"            # the manifest keeps the file name, never a path


def test_dataset_split_is_by_time_and_validation_is_latest(tmp_path):
    led = _ledger(tmp_path / "copy.duckdb", _rows())
    m = bd.build(led, tmp_path / "ds", valid_fraction=0.25)
    assert m["valid"] == 3 and m["train"] == 9
    assert m["train_last_as_of"] < m["valid_first_as_of"]


def test_dataset_refuses_the_live_store_and_the_apps_folder(tmp_path, monkeypatch):
    pm = tmp_path / "pm"
    pm.mkdir()
    live = _ledger(pm / "ledger.duckdb", _rows())
    monkeypatch.setenv("PFLAB_PM_DIR", str(pm))
    with pytest.raises(bd.LedgerRefused, match="live store"):
        bd.check_is_copy(live)
    appdir = tmp_path / "PortfolioLabApp" / "pm"
    appdir.mkdir(parents=True)
    with pytest.raises(bd.LedgerRefused, match="app"):
        bd.check_is_copy(_ledger(appdir / "copy.duckdb", _rows()))
    assert bd.main(["--ledger", str(tmp_path / "missing.duckdb"), "--out", str(tmp_path / "o")]) == 2


def test_dataset_without_briefs_table_is_refused(tmp_path):
    p = tmp_path / "empty.duckdb"
    duckdb.connect(str(p)).close()
    assert bd.main(["--ledger", str(p), "--out", str(tmp_path / "o")]) == 2


def test_dataset_uses_the_prompt_column_when_the_journal_keeps_one(tmp_path):
    led = _ledger(tmp_path / "copy.duckdb", _rows())
    con = duckdb.connect(str(led))
    con.execute("ALTER TABLE briefs ADD COLUMN prompt VARCHAR")
    con.execute("UPDATE briefs SET prompt='Facts: [F:revenue]=12. Write the brief.' WHERE brief_id=1")
    con.close()
    bd.build(led, tmp_path / "ds", valid_fraction=0.0)
    first = json.loads((tmp_path / "ds" / "train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first["messages"][1]["content"].startswith("Facts:") and first["meta"]["has_prompt"]


# ---- train_qlora ------------------------------------------------------------------------------------------------------------

def _dataset_root(tmp_path: Path, n: int = 4) -> Path:
    (tmp_path / "datasets").mkdir()
    ex = {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}, {"role": "assistant", "content": "a [F:x]"}]}
    for name in ("train", "valid"):
        (tmp_path / "datasets" / f"{name}.jsonl").write_text((json.dumps(ex) + "\n") * n, encoding="utf-8")
    return tmp_path


def test_config_file_is_valid_and_complete():
    cfg = tq.load_config(lab.CONFIG)
    assert cfg["lora"]["r"] == 16 and "q_proj" in cfg["lora"]["target_modules"] and cfg["train"]["seed"]
    assert cfg["quant"]["load_in_4bit"] and cfg["train"]["gradient_checkpointing"]


def test_train_dry_run_prints_the_plan_and_exits_zero_without_the_extra(tmp_path, capsys, no_extra):
    root = _dataset_root(tmp_path)
    assert tq.main(["--dry-run", "--root", str(root), "--min-examples", "1"]) == 0
    out = capsys.readouterr().out
    assert "optimiser steps" in out and "NOT installed" in out and "nvidia-smi -lgc 210,2100" in out and "nothing was trained" in out


def test_train_dry_run_rejects_a_bad_dataset(tmp_path, capsys):
    assert tq.main(["--dry-run", "--root", str(tmp_path)]) == 2                      # no dataset at all
    root = _dataset_root(tmp_path)
    assert tq.main(["--dry-run", "--root", str(root)]) == 2                          # 4 examples < min_examples 50
    assert "min_examples" in capsys.readouterr().err
    (root / "datasets" / "train.jsonl").write_text(json.dumps({"messages": [{"role": "user", "content": "x"}, {"role": "user", "content": "y"}]}) + "\n")
    assert tq.main(["--dry-run", "--root", str(root), "--min-examples", "1"]) == 2   # does not end with an assistant turn


def test_train_real_path_fails_clearly_without_the_extra(tmp_path, capsys, no_extra):
    root = _dataset_root(tmp_path)
    assert tq.main(["--root", str(root), "--min-examples", "1"]) == lab.EXIT_MISSING_EXTRA
    err = capsys.readouterr().err
    assert "not installed" in err and "torch" in err and "pip install" in err and "Traceback" not in err


def test_require_names_what_is_missing(no_extra):
    with pytest.raises(lab.MissingExtra, match="torch, peft"):
        lab.require("torch", "peft")


# ---- steering ---------------------------------------------------------------------------------------------------------------

def test_steering_direction_maths():
    import numpy as np
    pos = [[2.0, 0.0, 0.0], [4.0, 0.0, 0.0]]
    neg = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    unit, norm = st.direction(pos, neg)
    assert np.allclose(unit, [1, 0, 0]) and norm == pytest.approx(3.0)
    assert np.allclose(st.steered(np.zeros((2, 3)), unit, 4.0), [[4, 0, 0], [4, 0, 0]])
    zero, n0 = st.direction(pos, pos)
    assert n0 == 0 and not zero.any()
    with pytest.raises(st.SteerConfigError):
        st.direction([[1.0, 2.0]], [[1.0, 2.0], [3.0, 4.0]])


def test_steer_dry_run_and_failure_modes(tmp_path, capsys, no_extra):
    assert st.main(["--dry-run"]) == 0
    assert "contrastive pairs" in capsys.readouterr().out
    assert st.main(["compute"]) == lab.EXIT_MISSING_EXTRA
    assert "not installed" in capsys.readouterr().err
    bad = tmp_path / "bad.toml"
    bad.write_text('[model]\nbase="x"\n[steer]\nname="n"\nlayer=3\nalpha=1.0\n[prompts]\npositive=["a","b"]\nnegative=["c"]\n', encoding="utf-8")
    assert st.main(["--config", str(bad), "--dry-run"]) == 2


# ---- merge / GGUF -----------------------------------------------------------------------------------------------------------

def test_merge_and_gguf_prints_the_exact_commands(tmp_path, capsys):
    cmds = mg.commands(tmp_path / "merged", tmp_path / "gguf", Path("llama.cpp"), "Q8_0", "lab")
    assert cmds[0][1].endswith("convert_hf_to_gguf.py") and "--outtype" in cmds[0] and cmds[0][-1] == "f16"
    assert cmds[1][-1] == "Q8_0" and cmds[1][-2].endswith("lab-q8_0.gguf")
    assert len(mg.commands(tmp_path, tmp_path, Path("l"), "F16")) == 1
    assert mg.main(["--dry-run", "--adapter", str(tmp_path / "a"), "--llama-cpp", "llama.cpp"]) == 0
    out = capsys.readouterr().out
    assert "convert_hf_to_gguf.py" in out and "llama-quantize" in out and "make_modelfile.py" in out and "nothing was merged" in out


def test_merge_without_extra_fails_clearly(tmp_path, capsys, no_extra):
    (tmp_path / "adapter").mkdir()
    (tmp_path / "adapter" / "adapter_config.json").write_text("{}", encoding="utf-8")
    ll = tmp_path / "llama"
    ll.mkdir()
    (ll / "convert_hf_to_gguf.py").write_text("", encoding="utf-8")
    assert mg.main(["--adapter", str(tmp_path / "adapter"), "--llama-cpp", str(ll)]) == lab.EXIT_MISSING_EXTRA
    assert mg.main(["--adapter", str(tmp_path / "nope"), "--llama-cpp", str(ll)]) == 2


# ---- Modelfile --------------------------------------------------------------------------------------------------------------

def test_modelfile_content():
    t = mm.modelfile("D:/x/model-q8_0.gguf")
    assert t.startswith("FROM D:/x/model-q8_0.gguf\n")
    assert 'TEMPLATE """' in t and "<|im_start|>" in t and "{{ .Content }}" in t and "<think>" in t
    for line in ("PARAMETER temperature 0.7", "PARAMETER top_p 0.8", "PARAMETER top_k 20", "PARAMETER min_p 0.0",
                 "PARAMETER stop <|im_start|>", "PARAMETER stop <|im_end|>"):
        assert line in t
    assert "PARAMETER temperature 0.6" in mm.modelfile("m.gguf", "thinking") and "PARAMETER top_p 0.95" in mm.modelfile("m.gguf", "thinking")
    assert 'SYSTEM """be brief"""' in mm.modelfile("m.gguf", system="be brief")
    with pytest.raises(ValueError):
        mm.modelfile("m.gguf", "weird")


def test_make_modelfile_writes_the_file(tmp_path, capsys):
    out = tmp_path / "Modelfile.t"
    assert mm.main(["--gguf", "g.gguf", "--tag", "t", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("FROM g.gguf") and "ollama create t" in capsys.readouterr().out


# ---- run_evals: the app's harness, a fake model -----------------------------------------------------------------------------

class _Reply:
    def __init__(self, text):
        self.text, self.digest, self.tokens_in, self.tokens_out, self.seconds = text, "d", 1, 1, 0.01


def _fake_chat(model, messages, fmt=None, num_predict=0, **kw):
    props = (fmt or {}).get("properties", {})
    if "tools" in props:
        return _Reply('{"tools": ["nothing"]}')
    if "label" in props:
        return _Reply('{"label": "routine"}')
    return _Reply('{"kind": "other"}')


def test_run_evals_limits_every_task_and_keeps_the_apps_shape(tmp_path):
    d = tmp_path / "llm_eval"
    d.mkdir()
    (d / "extraction.json").write_text(json.dumps([{"text": f"t{i}", "gold": {"kind": "other"}} for i in range(5)]), encoding="utf-8")
    (d / "materiality.json").write_text(json.dumps([{"text": f"h{i}", "gold": "routine"} for i in range(5)]), encoding="utf-8")
    res = re_.run("fake:1", 1, ("routing", "extraction", "materiality"), limit=2, chat=_fake_chat, root=tmp_path)
    assert set(res) >= {"model", "scores", "passes", "detail", "run_at", "harness"}
    assert len(res["detail"]["routing"]) == 2 and len(res["detail"]["extraction"]) == 2
    assert res["scores"]["extraction_f1"] == 1.0 and res["scores"]["materiality"] == 1.0
    assert res["harness"]["smoke"] is True
    assert set(res["passes"]) == {"routing", "answers_final", "extraction_f1", "materiality", "latency_p90_s"}
    from pflab.llm import eval12                                          # the harness is restored after the limited run
    assert len(eval12.routing_set()) > 2


def test_run_evals_full_run_needs_a_registered_pick():
    assert re_.main(["--tag", "never-registered-tag:1"]) == 2             # rule 10: refused before any call
    assert re_.check_registered("qwen3:8b-q8_0", 1, None, smoke=False)["role"] == "eval12"
    assert re_.check_registered("never-registered-tag:1", 1, None, smoke=True) is None


def test_run_evals_result_path_marks_smoke_runs(tmp_path):
    assert re_.out_path(tmp_path, "qwen3:8b-q8_0", 3).name == "qwen3_8b-q8_0.smoke.json"
    assert re_.out_path(tmp_path, "qwen3:8b-q8_0", None).name == "qwen3_8b-q8_0.json"


# ---- the app and the base install never import torch ------------------------------------------------------------------------

def test_importing_the_app_and_the_lab_loads_no_ml_library(tmp_path):
    script = tmp_path / "probe.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT / 'src')!r}); sys.path.insert(0, {str(LAB)!r})\n"
        "import pflab, pflab.cli, pflab.llm.client, pflab.llm.eval12, pflab.hq.tools\n"
        "import lab_common, build_dataset, train_qlora, steer, merge_and_gguf, make_modelfile, run_evals\n"
        f"print('loaded:' + ','.join(m for m in {ML!r} if m in sys.modules))\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-800:]
    assert r.stdout.strip().splitlines()[-1] == "loaded:"


def test_base_install_does_not_depend_on_the_ml_extra():
    py = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    base = " ".join(py["dependencies"]).lower()
    assert not any(m in base for m in ML + ("peft", "gguf", "datasets", "accelerate"))
    ml = py["optional-dependencies"]["ml"]
    assert {"torch", "transformers", "peft", "trl", "bitsandbytes"} <= {d.split("==")[0] for d in ml}
    assert all("==" in d for d in ml)                                      # pinned exactly
    lock = ROOT / "requirements.lock"
    if lock.exists():
        assert not any(m in lock.read_text(encoding="utf-8").lower() for m in ("torch==", "transformers==", "bitsandbytes=="))


def test_lab_gitignore_covers_weights_and_datasets():
    g = (LAB / ".gitignore").read_text(encoding="utf-8")
    for pat in ("outputs/", "datasets/", "*.gguf", "*.safetensors", "*.jsonl"):
        assert pat in g
