"""S79 tools, one module per item. Each `t_*.py` defines TOOLS = [Tool(...), ...] (pflab.hq.tools.Tool; kind "read" for analysis tools).
Every call is journaled with its call id by the tool loop (hq_tool_calls); a number in agent text must cite a call id (see t_explain)."""
import importlib
import pkgutil


def collect() -> list:
    out = []
    for m in sorted(pkgutil.iter_modules(__path__), key=lambda x: x.name):
        if m.name.startswith("t_"):
            out.extend(importlib.import_module(f"{__name__}.{m.name}").TOOLS)
    return out


def names() -> tuple:
    return tuple(t.name for t in collect())
