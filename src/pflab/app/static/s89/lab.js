/* S89 Lab: Pairs (worked out by code: cointegration, z-score, hedge ratio, half-life, correlation, a coded verdict, 0 tokens). Simulate and Forecast say plainly that they are not wired in this build. */
S89.register('lab', async (el) => {
  const { esc, api, post, lines, empty } = S89;
  let tab = sessionStorage.getItem('s89:labTab') || 'pairs', res = null, err = '';
  const VERDICT = { tied: ['ok', 'Tied: they tend to come back together'], loose: ['mute', 'Loose: some link, not reliable'], 'not tied': ['warn', 'Not tied: no stable link'] };
  function pairs() {
    const r = res;
    const out = r ? `<div class="row"><span class="chip ${VERDICT[r.verdict][0]}">${esc(VERDICT[r.verdict][1])}</span><span class="small muted">${esc(r.label)} · ${r.days} shared days</span></div>
      ${lines([r.series_a, r.series_b], 760, 220, ['#2F5BEA', '#D9620F'])}<div class="row small"><span><span class="dot" style="background:#2F5BEA"></span>${esc(r.a)}</span><span><span class="dot" style="background:#D9620F"></span>${esc(r.b)}</span><span class="muted">both set to 100 at the start</span></div>
      <div class="row"><div class="card"><span class="muted small">Gap today</span><b class="big">${r.gap_z}σ</b></div><div class="card"><span class="muted small">p-value</span><b class="big">${r.p_value}</b></div><div class="card"><span class="muted small">Hedge ratio</span><b class="big">${r.hedge_ratio}</b></div>
      <div class="card"><span class="muted small">Half-life</span><b class="big">${r.half_life_days == null ? 'none' : r.half_life_days + ' d'}</b></div><div class="card"><span class="muted small">Correlation</span><b class="big">${r.correlation}</b></div></div>
      <span class="small muted">${esc(r.note)}. A pair is a description of the past; a trading rule from it is a registered study first.</span>` : empty('Pick two names and press Study it.');
    return `<form class="row" id="pairForm"><label>First name<input name="a" required maxlength="20" style="width:130px" autocapitalize="characters"></label><label>Second name<input name="b" required maxlength="20" style="width:130px" autocapitalize="characters"></label><button class="btn" type="submit">Study it</button></form>${err ? `<div class="err">${esc(err)}</div>` : ''}${out}`;
  }
  function draw() {
    const body = tab === 'pairs' ? pairs() : empty(tab === 'sim' ? 'Simulate is not wired in this build: the Monte Carlo runs on its own schedule and its result is on Home when it exists.' : 'Forecast fans and their coverage are not shown in this build yet.');
    el.innerHTML = `<div class="row"><h2 class="grow" style="margin:0">Lab</h2><div class="tabs">${[['pairs', 'Pairs'], ['sim', 'Simulate'], ['fc', 'Forecast']].map(([k, l]) => `<button data-t="${k}" class="${tab === k ? 'on' : ''}">${l}</button>`).join('')}</div></div><div class="card">${body}</div>`;
    el.querySelectorAll('[data-t]').forEach((b) => { b.onclick = () => { tab = b.dataset.t; sessionStorage.setItem('s89:labTab', tab); draw(); }; });
    const f = document.getElementById('pairForm');
    if (f) f.onsubmit = async (ev) => { ev.preventDefault(); const v = Object.fromEntries(new FormData(f)); err = ''; try { res = await post('/api/lab/pair', v); } catch (e) { err = e.message; res = null; } draw(); };
  }
  draw();
});
