/* S89b Lab: Pairs, Simulate and Forecast. All three are worked out by code from stored data ("worked out by the Lab tools, 0 tokens"); a preset the code does not have is a disabled button that says "not built yet". */
S89.register('lab', async (el) => {
  const { esc, rs, api, post, lines, empty } = S89;
  let tab = sessionStorage.getItem('s89:labTab') || 'pairs', res = null, err = '', sim = null, simErr = '', busy = false;
  const o = { scenario: 'normal', horizon: 60, basis: 'paper', market: 'IN' };
  const VERDICT = { tied: ['ok', 'Tied: they tend to come back together'], loose: ['mute', 'Loose: some link, not reliable'], 'not tied': ['warn', 'Not tied: no stable link'] };
  const presets = await api('/api/lab/presets').catch(() => ({ scenarios: [], horizons: [20, 60, 250] }));
  const fc = await api('/api/lab/forecast?market=' + o.market).catch(() => null);
  function pairs() {
    const r = res;
    const out = r ? `<div class="row"><span class="chip ${VERDICT[r.verdict][0]}">${esc(VERDICT[r.verdict][1])}</span><span class="small muted">${esc(r.label)} · ${r.days} shared days</span></div>
      ${lines([r.series_a, r.series_b], 760, 220, ['#2F5BEA', '#D9620F'])}<div class="row small"><span><span class="dot" style="background:#2F5BEA"></span>${esc(r.a)}</span><span><span class="dot" style="background:#D9620F"></span>${esc(r.b)}</span><span class="muted">both set to 100 at the start</span></div>
      <div class="row"><div class="card"><span class="muted small">Gap today</span><b class="big">${r.gap_z}σ</b></div><div class="card"><span class="muted small">p-value</span><b class="big">${r.p_value}</b></div><div class="card"><span class="muted small">Hedge ratio</span><b class="big">${r.hedge_ratio}</b></div>
      <div class="card"><span class="muted small">Half-life</span><b class="big">${r.half_life_days == null ? 'none' : r.half_life_days + ' d'}</b></div><div class="card"><span class="muted small">Correlation</span><b class="big">${r.correlation}</b></div></div>
      <span class="small muted">${esc(r.note)}. A pair is a description of the past; a trading rule from it is a registered study first.</span>` : empty('Pick two names and press Study it.');
    return `<form class="row" id="pairForm"><label>First name<input name="a" required maxlength="20" style="width:130px" autocapitalize="characters"></label><label>Second name<input name="b" required maxlength="20" style="width:130px" autocapitalize="characters"></label><button class="btn" type="submit">Study it</button></form>${err ? `<div class="err">${esc(err)}</div>` : ''}${out}`;
  }
  function simulate() {
    const sc = (presets.scenarios || []).map((s) => `<button type="button" data-sc="${esc(s.key)}" class="${o.scenario === s.key ? 'on' : ''}" ${s.enabled ? '' : 'disabled'} title="${esc(s.why)}">${esc(s.label)}${s.enabled ? '' : ' · not built yet'}</button>`).join('');
    const hz = (presets.horizons || []).map((h) => `<button type="button" data-hz="${h}" class="${o.horizon === h ? 'on' : ''}">${h} sessions</button>`).join('');
    const bs = [['mine', 'Your money today'], ['paper', "Claude's book"]].map(([k, l]) => `<button type="button" data-bs="${k}" class="${o.basis === k ? 'on' : ''}">${l}</button>`).join('');
    let out = busy ? '<div class="muted">Working it out…</div>' : empty('Choose a scenario, a horizon and whose money, then press Run. They are never added together.');
    if (simErr) out = `<div class="err">${esc(simErr)}</div>`;
    if (sim) {
      out = `<div class="row"><span class="chip">${esc(sim.label)}</span><span class="small muted">${sim.paths_run.toLocaleString('en-IN')} paths of ${sim.horizon} sessions · ${esc(sim.worked_out)}</span></div>
        ${lines(sim.paths || [], 760, 220, ['#9CB3F2'])}
        <div class="row"><div class="card"><span class="muted small">Worst 1 in 20</span><b class="big">${rs(sim.worst_1_in_20)}</b></div><div class="card"><span class="muted small">Middle</span><b class="big">${rs(sim.middle)}</b></div><div class="card"><span class="muted small">Best 1 in 20</span><b class="big">${rs(sim.best_1_in_20)}</b></div>
          <div class="card"><span class="muted small">Chance of a 10% fall on the way</span><b class="big">${(sim.p_fall10 * 100).toFixed(0)}%</b><span class="small muted">± ${(sim.p_fall10_se * 100).toFixed(1)} points</span></div></div>
        <span class="small muted">Starting from ${rs(sim.start_inr)}. ${esc(sim.note || '')} ${esc(sim.caveat)}.</span>`;
    }
    return `<div class="col"><div class="row"><span class="small muted">Scenario</span><div class="tabs" id="scs">${sc}</div></div><div class="row"><span class="small muted">Horizon</span><div class="tabs" id="hzs">${hz}</div><span class="small muted">Whose money</span><div class="tabs" id="bss">${bs}</div><button class="btn" id="runSim">Run</button></div>${out}</div>`;
  }
  function forecast() {
    if (!fc) return empty('The forecast did not answer.');
    if (fc.empty) return empty(fc.empty);
    const f = fc.fan || [];
    const pts = ['q5', 'q25', 'q50', 'q75', 'q95'].map((k) => f.map((x) => x[k]));
    const cov = (fc.coverage || []).map((c) => `<div class="row small"><b>${c.h} session${c.h > 1 ? 's' : ''}</b><span class="grow">${esc(c.text)}</span><span class="chip ${c.judge ? 'ok' : 'mute'}">${c.judge ? 'judged' : 'too few'}</span></div>`).join('') || '<span class="small muted">Nothing scored yet.</span>';
    return `<div class="row"><span class="chip mute">${esc(fc.subject || '')}</span><span class="small muted">${esc(fc.forecaster || '')} forecaster · made ${esc(fc.as_of)} · ${esc(fc.worked_out)}</span></div>
      ${f.length > 1 ? lines(pts, 760, 220, ['#C9D4F7', '#9CB3F2', '#2F5BEA', '#9CB3F2', '#C9D4F7']) : '<div class="small muted">Only the 1-session band is stored so far, so there is no fan to draw yet.</div>'}
      <div class="row small">${f.map((x) => `<span>${x.h}d: ${S89.num(x.q5, 0)} to ${S89.num(x.q95, 0)}</span>`).join('')}</div><h2>How often the band was right</h2>${cov}`;
  }
  function draw() {
    const body = tab === 'pairs' ? pairs() : tab === 'sim' ? simulate() : forecast();
    el.innerHTML = `<div class="row"><h2 class="grow" style="margin:0">Lab</h2><div class="tabs">${[['pairs', 'Pairs'], ['sim', 'Simulate'], ['fc', 'Forecast']].map(([k, l]) => `<button data-t="${k}" class="${tab === k ? 'on' : ''}">${l}</button>`).join('')}</div></div><div class="card">${body}<span class="small muted">Worked out by the Lab tools, 0 tokens.</span></div>`;
    el.querySelectorAll('[data-t]').forEach((b) => { b.onclick = () => { tab = b.dataset.t; sessionStorage.setItem('s89:labTab', tab); draw(); }; });
    const f = document.getElementById('pairForm');
    if (f) f.onsubmit = async (ev) => { ev.preventDefault(); const v = Object.fromEntries(new FormData(f)); err = ''; try { res = await post('/api/lab/pair', v); } catch (e) { err = e.message; res = null; } draw(); };
    el.querySelectorAll('[data-sc]').forEach((b) => { b.onclick = () => { o.scenario = b.dataset.sc; draw(); }; });
    el.querySelectorAll('[data-hz]').forEach((b) => { b.onclick = () => { o.horizon = Number(b.dataset.hz); draw(); }; });
    el.querySelectorAll('[data-bs]').forEach((b) => { b.onclick = () => { o.basis = b.dataset.bs; draw(); }; });
    const r = document.getElementById('runSim');
    if (r) r.onclick = async () => { busy = true; simErr = ''; sim = null; draw(); try { sim = await post('/api/lab/simulate', o); } catch (e) { simErr = e.message; } busy = false; draw(); };
  }
  draw();
});
