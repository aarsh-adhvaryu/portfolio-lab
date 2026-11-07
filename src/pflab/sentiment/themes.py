"""The themes, their price proxies and the proxy series (config: configs/themes_s79b.toml). The existing risk themes (configs/themes.toml, risk/themes.py) are
separate and untouched; this file is the sentiment item's own list."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from pflab import _toml
from pflab.sentiment import THEMES_CONFIG, data_root, read_series

NONE = "none"


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    status: str
    markets: Tuple[str, ...]
    keywords: Tuple[str, ...]
    gkg_codes: Tuple[str, ...]
    industries: Tuple[str, ...]
    proxies: Tuple[str, ...]
    gdelt_groups: Tuple[str, ...] = ()

    @property
    def primary(self) -> Optional[str]:
        return self.proxies[0] if self.proxies else None


def load_config(path: Optional[Path] = None) -> dict:
    p = Path(path) if path else THEMES_CONFIG
    return _toml.load(p) if p.exists() else {}


def load_themes(market: Optional[str] = None, path: Optional[Path] = None, include_stubs: bool = False) -> Dict[str, Theme]:
    """The live themes (status "live"), optionally those of one market. A stub (status "proposed") is never returned unless asked for."""
    cfg = load_config(path)
    out: Dict[str, Theme] = {}
    for k, v in (cfg.get("theme") or {}).items():
        st = str(v.get("status", "live"))
        if st != "live" and not include_stubs:
            continue
        mk = tuple(v.get("markets", ["IN"]))
        if market is not None and market not in mk:
            continue
        out[k] = Theme(k, v.get("label", k), st, mk, tuple(x.lower() for x in v.get("keywords", [])), tuple(v.get("gkg_codes", [])),
                       tuple(x.lower() for x in v.get("industries", [])), tuple(v.get("proxies", [])), tuple(v.get("gdelt_groups", [])))
    return out


def proxy_spec(key: str, path: Optional[Path] = None) -> Optional[dict]:
    return (load_config(path).get("proxy") or {}).get(key)


def load_proxy(root, key: str, path: Optional[Path] = None) -> Optional[pd.Series]:
    """The proxy's level series (first existing candidate file), or None if none of them is on this PC."""
    spec = proxy_spec(key, path)
    if not spec:
        return None
    for f in spec.get("files", []):
        p = Path(root) / f
        if p.exists():
            s = read_series(p, tuple(spec.get("cols", ["value", "close"])))
            if s is not None:
                return s
    return None


def proxy_lag(key: str, path: Optional[Path] = None) -> int:
    spec = proxy_spec(key, path) or {}
    return int(spec.get("lag", 0))


def proxy_label(key: str, path: Optional[Path] = None) -> str:
    return (proxy_spec(key, path) or {}).get("label", key)


def propose_stub(key: str, label: str, keywords: List[str], proxies: List[str], out_dir: Optional[Path] = None, markets=("IN",)) -> Path:
    """The agenda's way to propose a theme: a config stub written for the lead (status "proposed", never read by the tools), not a live theme."""
    import re
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", key):
        raise ValueError("a theme key is lowercase letters, digits and underscores")
    if out_dir is None:
        from pflab.pm import store
        out_dir = Path(store.pm_dir()) / "theme_stubs_s79b"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    esc = lambda s: str(s).replace("\\", "\\\\").replace('"', "'")
    text = (f"# STUB for the lead: not live until it is moved into configs/themes_s79b.toml with status = \"live\".\n[theme.{key}]\nlabel = \"{esc(label)}\"\n"
            f"status = \"proposed\"\nmarkets = [{', '.join(chr(34) + m + chr(34) for m in markets)}]\n"
            f"keywords = [{', '.join(chr(34) + esc(k).lower() + chr(34) for k in keywords)}]\ngkg_codes = []\nindustries = []\n"
            f"proxies = [{', '.join(chr(34) + esc(p) + chr(34) for p in proxies)}]\n")
    p = out_dir / f"{key}.toml"
    p.write_text(text, encoding="utf-8")
    return p
