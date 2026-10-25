"""Views of the knowledge graph (S38): an interactive 3D page and an Obsidian vault. Both are written under
PFLAB_PM_DIR (personal: holdings and list are in them) and never published.

    html       3d-force-graph 1.80.0 (pinned, from jsDelivr): nodes coloured by kind, sized by degree; click a node to
               focus it, hover for the label. Documents are limited to the last `days` so the picture stays readable.
    obsidian   one Markdown note per company / sector / you, with [[wiki links]] along current edges and the recent
               documents listed; open the folder as a vault and use Graph view.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

COLOURS = {"person": "#e45756", "company": "#4c78a8", "sector": "#54a24b", "filing": "#b279a2", "result": "#f58518",
           "article": "#9d755d", "theme": "#bab0ac", "org": "#72b7b2", "verdict": "#eeca3b"}


def export(con, days: int = 30, asof: Optional[date] = None, with_entities: bool = False) -> dict:
    asof = asof or date.today()
    since = datetime.combine(asof - timedelta(days=days), datetime.min.time())
    now = datetime.combine(asof, datetime.max.time())
    edges = con.execute("""SELECT e.src, e.rel, e.dst FROM kg_edges e LEFT JOIN kg_docs d ON d.doc_id = e.src
                           WHERE e.valid_from <= ? AND (e.valid_to IS NULL OR e.valid_to > ?)
                             AND (d.doc_id IS NULL OR d.published_at >= ?)""", [now, now, since]).fetchall()
    if not with_entities:
        edges = [e for e in edges if e[1] not in ("has_theme", "names")]
    ids = {x for s, _, d in edges for x in (s, d)}
    nodes = con.execute(f"SELECT node_id, kind, name FROM kg_nodes WHERE node_id IN ({','.join('?' * len(ids))})",
                        list(ids)).fetchall() if ids else []
    deg = {}
    for s, _, d in edges:
        deg[s] = deg.get(s, 0) + 1
        deg[d] = deg.get(d, 0) + 1
    return {"nodes": [{"id": i, "kind": k, "name": (n or i)[:120], "deg": deg.get(i, 0)} for i, k, n in nodes],
            "links": [{"source": s, "target": d, "rel": r} for s, r, d in edges]}


def html(data: dict, path: Path) -> Path:
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Portfolio graph</title>
<script src="https://cdn.jsdelivr.net/npm/3d-force-graph@1.80.0/dist/3d-force-graph.min.js"></script>
<style>body{{margin:0;background:#0b0e14;color:#ddd;font-family:system-ui,sans-serif}}#g{{width:100vw;height:100vh}}
#k{{position:fixed;top:10px;left:12px;font-size:13px;background:#0b0e14cc;padding:8px 10px;border-radius:6px}}
#k span{{display:inline-block;width:10px;height:10px;border-radius:50%;margin:0 4px 0 10px}}</style></head>
<body><div id="k"></div><div id="g"></div><script>
const D={json.dumps(data)}; const C={json.dumps(COLOURS)};
document.getElementById('k').innerHTML='Portfolio knowledge graph '+Object.entries(C).map(([k,c])=>`<span style="background:${{c}}"></span>${{k}}`).join('');
const G=ForceGraph3D()(document.getElementById('g')).graphData(D).backgroundColor('#0b0e14')
 .nodeLabel(n=>`${{n.kind}}: ${{n.name}}`).nodeColor(n=>C[n.kind]||'#999').nodeVal(n=>1+Math.sqrt(n.deg||1)*(n.kind==='company'||n.kind==='person'?3:1))
 .linkLabel(l=>l.rel).linkOpacity(0.25).linkDirectionalParticles(l=>l.rel==='owns'?2:0)
 .onNodeClick(n=>{{const d=60,r=1+d/Math.hypot(n.x,n.y,n.z);G.cameraPosition({{x:n.x*r,y:n.y*r,z:n.z*r}},n,1200);}});
</script></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path


def _slug(s: str) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]", " ", s)                       # control characters (seen in NSDL names)
    return re.sub(r"[\\/:*?\"<>|#^\[\]]", "-", s).strip()[:80] or "untitled"


def obsidian(con, out: Path, days: int = 30, asof: Optional[date] = None) -> int:
    """One note per company, sector and the investor; links along current edges; recent documents listed in the note."""
    from pflab.kg import graph as g
    asof = asof or date.today()
    data = export(con, days, asof)
    names = {n["id"]: n["name"] for n in data["nodes"]}
    keep = {n["id"] for n in data["nodes"] if n["kind"] in ("person", "company", "sector", "verdict")}
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for nid in keep:
        lines = [f"# {names[nid]}", f"kind: {nid.split(':')[0]}", ""]
        for l in data["links"]:
            if l["source"] == nid and l["target"] in keep:
                lines.append(f"- {l['rel']} [[{_slug(names[l['target']])}]]")
            elif l["target"] == nid and l["source"] in keep:
                lines.append(f"- {l['rel']} (from) [[{_slug(names[l['source']])}]]")
        if nid.startswith("company:"):
            tl = g.timeline(con, nid, asof - timedelta(days=days), limit=25)
            if len(tl):
                lines += ["", "## Recent documents"]
                lines += [f"- {r.published_at:%Y-%m-%d} {r.kind}: {r.title}" + (f" ({r.url})" if r.url else "") for r in tl.itertuples()]
        (out / f"{_slug(names[nid])}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        n += 1
    return n
