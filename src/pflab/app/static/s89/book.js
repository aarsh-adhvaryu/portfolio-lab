/* S89 Claude's book: "Is it right?" and "Its holdings", India / US. Reads the paper book and the thinking loop's scorecard; where a figure does not exist yet the screen says so. */
S89.register('book', async (el) => {
  const { esc, rs, pct, cls, api, lines, empty, num } = S89;
  let view = sessionStorage.getItem('s89:bookView') || 'right', market = sessionStorage.getItem('s89:bookMkt') || 'IN';
  const [p, core] = await Promise.all([api('/api/paper'), api('/api/core').catch(() => ({}))]);
  const t = core.think || {};
  function right() {
    const days = (p.days || []).map((d) => d.value), nifty = (p.nifty || []).map((d) => d.value);
    const chart = days.length > 1 ? lines([days, nifty], 760, 220, ['#2F5BEA', '#9A9DA4']) : empty("The paper book has no closes yet, so there is no curve. It appears after its first closes.");
    const dec = p.decisions && p.decisions.length ? p.decisions.slice(0, 12).map((d) => `<div class="row small"><span class="chip mute">${esc(d.action || d.kind || '')}</span><b>${esc(d.symbol || '')}</b><span class="grow">${esc(String(d.reason || d.text || '').slice(0, 110))}</span><span class="muted">${esc(String(d.made_at || d.at || '').slice(0, 10))}</span></div>`).join('') : empty('No decisions yet.');
    return `<section class="grid"><div class="card" style="flex:2 1 600px"><h2>Growth against the baseline</h2><span class="small muted">After tax. The paper book only counts if it beats the baseline.</span>${chart}
        <div class="row small"><span>Claude's book <b>${rs(p.value)}</b></span>${p.returns ? `<span>Since start <b class="${cls(p.returns.since_start)}">${pct((p.returns.since_start || 0) * 100)}</b></span>` : ''}</div></div>
      <div class="col" style="flex:1 1 360px"><div class="card"><h2>Is it right?</h2><span class="small">${esc(t.scorecard || 'Decisions: none scored yet.')}</span>
        <span class="small muted">A reliability chart (said X%, right Y%) and the Brier score appear once 20 decisions are scored; before that the sample is too small to judge.</span></div>
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
