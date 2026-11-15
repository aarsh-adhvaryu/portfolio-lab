/* Graph: the design's Graph screen. The storylines strip, one name in the knowledge graph (its peers by rule, the storylines, its events of the last 12 months in
   lanes, the newest event in full) and the graph's own health. Type a symbol and press Enter to look at another name. */
S89.register('graph', async (el) => {
  const { api, render } = S89;
  let sym = decodeURIComponent((location.hash.split('/')[2] || '').toUpperCase()) || sessionStorage.getItem('s89:graphSym') || '';
  async function draw() {
    const [core, g] = await Promise.all([api('/api/core').catch(() => ({})), api('/api/graph/ego?symbol=' + encodeURIComponent(sym))]);
    const st = (core.storylines || []);
    const stories = st.length ? st.slice(0, 4).map((s, i) => { const f = s.n_for != null ? s.n_for : (s.for || 0), a = s.n_against != null ? s.n_against : (s.against || 0), t = (f + a) || 1;
      return { name: s.claim || s.title || '', pct: s.probability != null ? Math.round(s.probability * 100) + '%' : '—', forN: f, agN: a, due: s.due || s.next_call || '—', forW: (f / t * 100) + '%', agW: (a / t * 100) + '%', border: i === 0 ? '2px solid #2F5BEA' : '1px solid #E6E4DD' }; })
      : [{ name: 'No open storyline yet', pct: '—', forN: 0, agN: 0, due: '—', forW: '0%', agW: '0%', border: '1px solid #E6E4DD' }];
    const cut = (x) => String(x || '').replace(/\s+-\s+https?:\/\/\S+\s*$/, '').replace(/https?:\/\/\S+/g, '').slice(0, 96);
    const ev = (g.events || []).map((x) => Object.assign({}, x, { headline: cut(x.headline) })), e = (i) => ev[i] || {};
    const dt = (x) => (x.date ? new Date(x.date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) + ' · ' + String(x.kind || '').replace(/_/g, ' ') : '—');
    const story = (i) => (g.stories || [])[i] || {};
    const yr = new Date(), y0 = new Date(yr); y0.setFullYear(yr.getFullYear() - 1); const ym = new Date(yr); ym.setMonth(yr.getMonth() - 6);
    const mon = (d) => d.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });
    const c = g.counts || {};
    const news = (g.lanes && g.lanes[4]) || [];
    await render(el, 'graph', { stories, news, g: {
      q: sym || g.symbol || '', key: (ev2) => { if (ev2.key === 'Enter') { sym = ev2.target.value.trim().toUpperCase(); sessionStorage.setItem('s89:graphSym', sym); draw(); } },
      name: g.found ? g.name : (g.empty || 'Not in the graph yet'), t1: (g.tags || [])[0] || '', t2: (g.tags || [])[1] || '', t3: (g.tags || [])[2] || '',
      p1: ((g.peers || [])[0] || {}).name || '—', p2: ((g.peers || [])[1] || {}).name || '—', p3: ((g.peers || [])[2] || {}).name || '—',
      s1p: story(0).p != null ? 'storyline · ' + Math.round(story(0).p * 100) + '%' : 'storyline', s1: story(0).claim || 'none open', s2p: story(1).p != null ? 'storyline · ' + Math.round(story(1).p * 100) + '%' : 'storyline', s2: story(1).claim || 'none open',
      e1d: dt(e(0)), e1t: e(0).headline || (ev.length ? '' : 'No events in the last 12 months'), e2d: dt(e(1)), e2t: e(1).headline || '', e3d: dt(e(2)), e3t: e(2).headline || '', e4d: dt(e(3)), e4t: e(3).headline || '',
      selAt: e(0).ts || '—', selSrc: e(0).source || '—', selUrl: /^https?:/.test(e(0).ref || '') ? e(0).ref : '#/graph', selRule: e(0).rule || '—',
      u1: e(0).severity ? 'severity · ' + e(0).severity : '', u2: e(0).kind ? 'kind · ' + String(e(0).kind).replace(/_/g, ' ') : '', u3: g.found ? ev.length + ' events this year' : '',
      st1: c.events ? Math.round(c.linked / Math.max(1, c.linked + (c.unlinked || 0)) * 1000) / 10 + '%' : '—', st2: c.unlinked != null ? String(c.unlinked) : '—', st3: c.nodes != null ? (c.nodes >= 1000 ? Math.round(c.nodes / 1000) + 'k' : String(c.nodes)) : '—',
      st4: g.audit ? (g.audit.passed ? 'passed' : 'not passed') : 'not run',
      due: g.found ? `${ev.length} events in 12 months, newest first in the panel above` : '', l0: (g.lanes || [])[0] || [], l1: (g.lanes || [])[1] || [], l2: (g.lanes || [])[2] || [], l3: (g.lanes || [])[3] || [],
      y0: mon(y0), y1: mon(ym), y2: mon(yr) } });
  }
  await draw();
});
