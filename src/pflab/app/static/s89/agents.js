/* S89 Agents: model and thinking per agent (a change applies from the next run), tokens today, last run, and the switches for the connections that load for full answers only (off by default). */
S89.register('agents', async (el) => {
  const { esc, api, post } = S89;
  async function draw(msg) {
    const d = await api('/api/agents');
    const rows = (d.agents || []).map((a) => `<tr><td><b>${esc(a.label)}</b><br><span class="small muted">${esc(a.tools)}</span></td>
      <td><select data-m="${esc(a.key)}" aria-label="Model of ${esc(a.label)}">${(d.models || []).map((m) => `<option ${m === a.model ? 'selected' : ''}>${esc(m)}</option>`).join('')}</select></td>
      <td><select data-t="${esc(a.key)}" aria-label="Thinking of ${esc(a.label)}">${(d.levels || []).map((m) => `<option ${m === a.thinking ? 'selected' : ''}>${esc(m)}</option>`).join('')}</select></td>
      <td class="small">${esc(a.last_run || 'not yet')}</td><td class="n small">${((a.tokens_today || 0) / 1000).toFixed(1)}k${a.budget ? ' of ' + (a.budget / 1000).toFixed(0) + 'k' : ''}</td><td class="small muted">${esc(a.applies)}${a.changed ? ' · changed' : ''}</td></tr>`).join('');
    const NAMES = { kite: 'Kite (read-only)', nse: 'NSE', tijori: 'Tijori', connectors: 'Your account connectors (mail, calendar, drive)' };
    const sw = Object.entries(d.switches || {}).map(([k, on]) => `<label class="row"><input type="checkbox" data-sw="${esc(k)}" ${on ? 'checked' : ''}> ${esc(NAMES[k] || k)}</label>`).join('');
    el.innerHTML = `<div class="row"><h2 class="grow" style="margin:0">Agents and tools</h2>${d.signed_in ? '<span class="chip ok">Signed in on your plan</span>' : '<span class="chip warn">Not signed in</span>'}</div>
      ${msg ? `<div class="banner plan"><span class="b">${esc(msg)}</span></div>` : ''}
      <div class="card"><div class="scroll"><table><thead><tr><th>Agent</th><th>Model</th><th>Thinking</th><th>Last run</th><th class="n">Tokens today</th><th>When it applies</th></tr></thead><tbody>${rows}</tbody></table></div>
        <span class="small muted">The model and thinking level you pick are kept and read at the start of the next run. Only the quick and full chat roads read them today; the other agents keep the setting for when their job reads it.</span></div>
      <div class="card"><h2>Connections</h2>${sw}<span class="small muted">${esc(d.switch_note || '')} Switching one here records your choice; a connection is loaded for a full answer only when its address is set in the configuration.</span></div>`;
    el.querySelectorAll('select[data-m],select[data-t]').forEach((s) => { s.onchange = async () => { const k = s.dataset.m || s.dataset.t; const body = { agent: k }; body[s.dataset.m ? 'model' : 'thinking'] = s.value; try { await post('/api/agents', body); draw('Saved. It applies from the next run.'); } catch (e) { alert(e.message); } }; });
    el.querySelectorAll('input[data-sw]').forEach((c) => { c.onchange = async () => { try { await post('/api/agents', { switch: c.dataset.sw, on: c.checked }); draw('Saved.'); } catch (e) { alert(e.message); } }; });
  }
  await draw();
});
