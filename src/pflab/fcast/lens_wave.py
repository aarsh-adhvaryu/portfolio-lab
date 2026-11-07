"""The wave lens (S79b item 15) registers itself with the plug-in interface: `plugins._load_builtin` imports this module and calls `register_lens()`.
The lens itself is `pflab.quant.waves.lens_frame` (shadow mode until admitted by its live score)."""
from __future__ import annotations


def register_lens() -> None:
    from pflab.quant import waves
    waves.register_lens()
