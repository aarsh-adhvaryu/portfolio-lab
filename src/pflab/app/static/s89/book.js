/* S89 Claude's book: "Is it right?" and "Its holdings", India / US. Reads the paper book and the thinking loop's scorecard; where a figure does not exist yet the screen says so. */
S89.register('book', async (el) => {
  const { esc, rs, pct, cls, api, lines, empty, num } = S89;
  let view = sessionStorage.getItem('s89:bookView') || 'right', market = sessionStorage.getItem('s89:bookMkt') || 'IN';
  const [p, core, rel] = await Promise.all([api('/api/paper'), api('/api/core').catch(() => ({})), api('/api/book/reliability').catch(() => null)]);
  const t = core.think || {};
  function reliability() {
    if (!rel) return '<span class="small muted">The reliability numbers did not answer.</span>';
    const pts = rel.points || [];
    const W = 260, H = 160, X = (v) => 24 + v * (W - 34), Y = (v) => H - 20 - v * (H - 34);
    const dots = pts.map((q) => `<circle cx="${X(q.said)}" cy="${Y(q.right)}" r="${4 + Math.min(8, q.n)}" fill="#2F5BEA" fill-opacity=".55"><title>${esc(q.word)}: said ${(q.said * 100).toFixed(0)}%, right ${(q.right * 100).toFixed(0)}% of ${q.n}</title></circle>`).join('');
    const chart = `<svg width="100%" viewBox="0 0 ${W} ${H}" role="img" aria-label="Said versus right" style="max-width:300px"><line x1="${X(0)}" y1="${Y(0)}" x2="${X(1)}" y2="${Y(1)}" stroke="#C9C6BD" stroke-dasharray="4 3"/><rect x="${X(0)}" y="${Y(1)}" width="${X(1) - X(0)}" height="${Y(0) - Y(1)}" fill="none" stroke="#E6E4DD"/>${dots}<text x="${X(0.5)}" y="${H - 4}" text-anchor="middle" font-size="10" fill="#5B5E66">it said</text><text x="6" y="${Y(0.5)}" font-size="10" fill="#5B5E66" transform="rotate(-90 6 ${Y(0.5)})">right</text></svg>`;
    return `<span class="small b">${esc(rel.text)}</span>${pts.length ? chart : '<span class="small muted">No points yet: a point needs a likelihood word used on at least one scored decision.</span>'}<span class="small muted">Dots are what it said (across) against how often it was right (up), sized by how many cases. Closer to the dashed line is better.</span>${rel.brier != null ? `<span class="small">Brier score <b>${rel.brier.toFixed(3)}</b> (lower is better; 0.25 is a coin toss).</span>` : '<span class="small muted">The Brier score is shown from 20 scored decisions.</span>'}`;
  }
  function right() {
    const days = (p.days || []).map((d) => d.value), nifty = (p.nifty || []).map((d) => d.value);
    const chart = days.length > 1 ? lines([days, nifty], 760, 220, ['#2F5BEA', '#9A9DA4']) : empty("The paper book has no closes yet, so there is no curve. It appears after its first closes.");
    const dec = p.decisions && p.decisions.length ? p.decisions.slice(0, 12).map((d) => `<div class="row small"><span class="chip mute">${esc(d.action || d.kind || '')}</span><b>${esc(d.symbol || '')}</b><span class="grow">${esc(String(d.reason || d.text || '').slice(0, 110))}</span><span class="muted">${esc(String(d.made_at || d.at || '').slice(0, 10))}</span></div>`).join('') : empty('No decisions yet.');
    return `<section class="grid"><div class="card" style="flex:2 1 600px"><h2>Growth against the baseline</h2><span class="small muted">After tax. The paper book only counts if it beats the baseline.</span>${chart}
        <div class="row small"><span>Claude's book <b>${rs(p.value)}</b></span>${p.returns ? `<span>Since start <b class="${cls(p.returns.since_start)}">${pct((p.returns.since_start || 0) * 100)}</b></span>` : ''}</div></div>
      <div class="col" style="flex:1 1 360px"><div class="card"><h2>Is it right?</h2><span class="small">${esc(t.scorecard || 'Decisions: none scored yet.')}</span>${reliability()}</div>
        <div class="card"><h2>Picks</h2><span class="small">${esc((core.picks && core.picks.line) || 'No picks yet.')}</span></div></div></section>
      <div class="card"><h2>Decisions, scored after tax</h2><div class="col scroll" style="gap:6px;max-height:260px">${dec}</div></div>
      <div class="card"><h2>What it changed about itself</h2><span class="small">${esc(t.plan || 'The weekly look has not run yet. After each Friday close it writes what worked, what did not and what to test next.')}</span></div>`;
  }
  function holdings() {
    const h = p.holdings || [];
    if (!h.length) return `<div class="card">${empty('The paper book holds nothing yet.')}</div>`;
    return `<div class="card"><h2>Its holdings</h2><div class="scroll"><table><thead><tr><th>Holding</th><th class="n">Value</th><th class="n">Weight</th><th>Stop</th><th>Thesis</th></tr></thead><tbody>${h.map((x) => `<tr><td><b>${esc(x.symbol || x.name)}</b></td><td class="n">${rs(x.value)}</td><td class="n">${x.weight != null ? (x.weight * 100).toFixed(1) + '%' : '—'}</td><td>${x.stop != null ? esc(num(x.stop, 2)) : '<span class="muted small">none</span>'}</td><td class="small">${esc(String(x.thesis || '').slice(0, 120))}</td></tr>`).join('')}</tbody></table></div></div>`;
  }
  function draw() {
    const tabs = `<div class="tabs">${[['right', 'Is it right?'], ['hold', 'Its holdings']].map(([k, l]) => `<button data-v="${k}" class="${view === k ? 'on' : ''}">${l}</button>`).join('')}</div><div class="tabs">${[['IN', 'India'], ['US', 'US']].map(([k, l]) => `<button data-m="${k}" class="${market === k ? 'on' : ''}">${l}</button>`).join('')}</div>`;
    el.innerHTML = `<div class="row"><h2 class="grow" style="margin:0">Claude's book</h2>${tabs}</div>${p.started === false ? `<div class="card">${empty(p.note || 'The paper book has not started yet.')}</div>` : (view === 'right' ? right() : holdings())}${market === 'US' ? '<div class="small muted">The US sub-book is shown inside the same account; its own split appears here once the US book has closes.</div>' : ''}`;
    el.querySelectorAll('[data-v]').forEach((b) => { b.onclick = () => { view = b.dataset.v; sessionStorage.setItem('s89:bookView', view); draw(); }; });
    el.querySelectorAll('[data-m]').forEach((b) => { b.onclick = () => { market = b.dataset.m; sessionStorage.setItem('s89:bookMkt', market); draw(); }; });
  }
  draw();
});
