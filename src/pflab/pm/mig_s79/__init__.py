"""S79 migrations, one module per item so parallel work never edits the same list. Each `m_*.py` defines MIGRATIONS = [(version, name, sql), ...].
Reserved version ranges: 61-65 run-on-open/modes/agenda/voice, 66-67 explanation tools (bars_1m), 68-70 forecasting, 71 replay, 72-73 transmission,
74 implied/cascade, 75-76 debate, 77 local model, 78-80 spare. A version is applied once; never edit an applied one (add a new one)."""
import importlib
import pkgutil


def collect() -> list:
    out = []
    for m in sorted(pkgutil.iter_modules(__path__), key=lambda x: x.name):
        if m.name.startswith("m_"):
            out.extend(importlib.import_module(f"{__name__}.{m.name}").MIGRATIONS)
    return out
