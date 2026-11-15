/* S89 Graph: the open storylines (what the system thinks is driving the market) and the knowledge graph. When the graph is off (its nightly audit has not passed) the screen says why. */
S89.register('graph', async (el) => {
  const { esc, api, empty } = S89;
  const [core, g] = await Promise.all([api('/api/core').catch(() => ({})), api('/api/graph').catch(() => ({ off: true, why: 'The graph did not answer.' }))]);
  const st = core.storylines || [];
  const stories = st.length ? st.map((s) => `<div class="card" style="flex:1 1 260px"><span class="b">${s.direction === 'up' ? '▲' : '▼'} ${Math.round((s.probability || 0) * 100)}%</span><span>${esc(s.claim || s.title || s.text || '')}</span><span class="small muted">${esc(s.calls_due || '')}</span></div>`).join('') : `<div class="card" style="flex:1">${empty('No open storylines yet.')}</div>`;
  const nodes = (g.nodes || []).slice(0, 60);
  const body = g.off ? empty(g.why || 'The knowledge graph is off until its nightly audit passes.') : (nodes.length ? `<div class="row">${nodes.map((n) => `<a class="chip mute" href="#/stock/${encodeURIComponent(n.symbol || n.label || n.name || n.id)}" title="${esc(n.kind || '')}">${esc(n.label || n.name || n.id)}</a>`).join('')}</div><span class="small muted">${(g.nodes || []).length} nodes, ${(g.edges || []).length} links</span>` : empty('The graph has no nodes yet.'));
  el.innerHTML = `<h2 style="margin:0">Graph</h2><div class="grid">${stories}</div><div class="card"><h2>Knowledge graph</h2>${body}</div>`;
});
