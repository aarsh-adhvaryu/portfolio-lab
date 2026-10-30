"""S67 (2026-10-30, his ask): the knowledge graph in 3-D, in a REAL browser (headless Edge), on a synthetic graph: the canvas draws without a
script error, turns by itself, and the flat view is still one press away."""
from __future__ import annotations

import os
import socket
import threading
import time
from datetime import datetime, timedelta

import pytest

pytest.importorskip("websockets")
from tests import _edge  # noqa: E402

pytestmark = [pytest.mark.ui, pytest.mark.skipif(not os.path.exists(_edge.EDGE), reason="Microsoft Edge is not installed here")]
NOW = datetime(2026, 10, 30, 21, 0)


def test_the_graph_turns_in_3d_and_the_flat_view_remains(tmp_path, monkeypatch):
    import uvicorn
    from pflab.app import runtime
    from pflab.app.server import create_app
    from pflab.kg import graph as g
    from pflab.pm import store
    (tmp_path / "pm").mkdir()
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    con = store.connect(tmp_path / "l.duckdb")
    for isin, sym in (("INE000A01011", "ALPHA"), ("INE000B01011", "BETA")):
        con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', "
                    "'listed_equity', TRUE, ?, ?, 'synthetic', now())", [isin, sym, sym + " Ltd"])
        g.node(con, f"company:{isin}", "company", sym)
        g.node(con, f"sector:{sym}", "sector", "Sector " + sym)
        g.edge(con, f"company:{isin}", "in_sector", f"sector:{sym}", NOW - timedelta(days=30), "synthetic")
    rt = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = uvicorn.Server(uvicorn.Config(create_app(rt), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    time.sleep(2.5)
    steps = [("JSON.stringify({canvas: !!document.getElementById('g3d'), yaw: G3.yaw})", 1.2),
             ("JSON.stringify({yaw: G3.yaw})", 0.1),
             ("document.querySelector('[data-gview=\"2d\"]').click(); 1", 0.8),
             ("JSON.stringify({canvas: !!document.getElementById('g3d'), dots: document.querySelectorAll('[data-gnode]').length})", 0.1)]
    try:
        errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/graph", str(tmp_path / "g.png"), 1400, 900, 5, steps)
    finally:
        srv.should_exit = True
    import json
    assert errors == [], errors
    a, b, flat = json.loads(res[0]), json.loads(res[1]), json.loads(res[3])
    assert a["canvas"] and b["yaw"] > a["yaw"]                                                 # drawn, and turning by itself
    assert not flat["canvas"] and flat["dots"] >= 4                                            # the flat map is still there
