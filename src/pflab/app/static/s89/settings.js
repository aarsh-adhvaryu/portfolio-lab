/* S89 Settings: plan sign-in, the Kite login, token budgets, the problems list, and the links to the places that hold the rest. The old settings stay at /classic until the first week has passed. */
S89.register('settings', async (el) => {
  const { esc, api, ago, empty } = S89;
  const [o, a, p] = await Promise.all([api('/api/operator'), api('/api/agents').catch(() => null), api('/api/problems').catch(() => null)]);
  const bud = Object.entries(o.tokens_today || {}).map(([k, v]) => `<div class="row small"><span class="grow">${esc(k)}</span><b>${((v.budget || 0) / 1000).toFixed(0)}k a day</b></div>`).join('');
  const probs = p && (p.rows || p.problems || p.items) ? (p.rows || p.problems || p.items) : (Array.isArray(p) ? p : []);
  const prow = probs.length ? probs.slice(0, 10).map((x) => `<div class="small"><b>${esc(x.kind || '')}</b> ${esc(x.text || x.line || '')} <span class="muted">${esc(ago(x.last_seen))}</span></div>`).join('') : empty('No problems on the list.');
  el.innerHTML = `<h2 style="margin:0">Settings</h2><section class="grid" style="align-items:flex-start">
    <div class="card" style="flex:1 1 360px"><h2>Your Claude plan</h2><div class="row"><span class="chip ${o.signed_in ? 'ok' : 'warn'}">${o.signed_in ? 'Signed in' : 'Not signed in'}</span><span class="small muted">${esc(o.method || '')}</span></div>
      <div class="small">${o.thinking === 'paused' ? 'Thinking is paused until ' + esc(o.paused_until || 'the reset') + '.' : 'Thinking is ' + esc(o.thinking || 'unknown') + '.'}</div>${o.detail ? `<div class="small err">${esc(o.detail)}</div>` : ''}
      <button class="btn ghost" id="term">Open the operator in Claude Code</button><span class="small muted" id="termMsg"></span></div>
    <div class="card" style="flex:1 1 360px"><h2>Kite login</h2><span class="small">Takes 20 seconds each trading morning. India prices stay at the last snapshot until you log in.</span><a class="btn" href="/classic#/settings">Log in to Kite</a></div>
    <div class="card" style="flex:1 1 320px"><h2>Token budgets</h2>${bud}<span class="small muted">Set in the configuration (the operator section). The Usage screen shows today against them.</span></div>
    <div class="card" style="flex:1 1 320px"><h2>Your US holdings</h2><span class="small">Entered by hand; they never touch Claude's paper book.</span><a class="btn ghost" href="#/manage">Add and watch</a></div>
    <div class="card" style="flex:1 1 420px"><h2>Problems</h2>${prow}</div>
    <div class="card" style="flex:1 1 320px"><h2>More</h2><span class="small">Limits, the week check and the older screens are still at <a href="/classic#/settings">the classic view</a> until the first week has passed.</span></div></section>`;
  document.getElementById('term').onclick = async () => { try { const r = await S89.post('/api/operator/terminal'); document.getElementById('termMsg').textContent = r.ok ? 'Opened a terminal in the operator folder.' : (r.detail || 'Could not open it.'); } catch (e) { document.getElementById('termMsg').textContent = e.message; } };
});
