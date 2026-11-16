"""S94: `tools/reach.py` (what the app can still reach) on a tiny synthetic package: a lazy import, a name in a string, a relative import, a loader that loads by name, and a module nothing reaches."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _tool():
    spec = importlib.util.spec_from_file_location("reach_tool", Path(__file__).resolve().parents[1] / "tools" / "reach.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_reach_follows_lazy_imports_strings_relatives_and_declared_loaders(tmp_path):
    r = _tool()
    pk = tmp_path / "src" / "pflab"
    (pk / "sub").mkdir(parents=True)
    (pk / "__init__.py").write_text("", encoding="utf-8")
    (pk / "root.py").write_text("def go():\n    from pflab import lazy\n    return 'pflab.named:run'\n", encoding="utf-8")
    (pk / "lazy.py").write_text("from .sub import leaf\n", encoding="utf-8")
    (pk / "named.py").write_text("import pflab.loader\n", encoding="utf-8")
    (pk / "loader.py").write_text("X = 1\n", encoding="utf-8")
    (pk / "plug_one.py").write_text("X = 1\n", encoding="utf-8")
    (pk / "orphan.py").write_text("from pflab import lazy\n", encoding="utf-8")
    (pk / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (pk / "sub" / "leaf.py").write_text("X = 1\n", encoding="utf-8")
    mods = r.modules(tmp_path / "src")
    edges = r.graph(mods)
    assert edges["pflab.root"] == {"pflab", "pflab.lazy", "pflab.named"} and "pflab.sub.leaf" in edges["pflab.lazy"]
    live = r.reachable(mods, edges, ["pflab.root"], loads={"pflab.loader": ["pflab.plug_"]})
    assert set(mods) - live == {"pflab.orphan"}                                                 # it imports live code, but nothing imports it
    assert "pflab.plug_one" not in r.reachable(mods, edges, ["pflab.root"], loads={})           # without the declared loader the plug-in is not found: loaders must be declared


def test_the_declared_loaders_and_roots_name_real_modules():
    r = _tool()
    mods = r.modules()
    missing = [m for m in list(r.ROOTS) + list(r.LOADS) if m not in mods]
    assert not missing, f"tools/reach.py names modules that no longer exist (update ROOTS / LOADS in the same commit as the deletion): {missing}"
