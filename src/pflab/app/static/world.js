/* The World (S67 local): the whole system as one living map, with the checklist that says what is running, what is done and what is not.
   Built once, then patched in place every few seconds, so motion never restarts. Data: GET /api/world (app/world.py). Plain words only. */
const W = { sel: null, filter: 'all', sig: '', pos: {}, last: null, at: 0, timer: null };
const WSTATE = { working: 'working now', ok: 'done', late: 'due', down: 'failed', waiting: 'waiting', idle: 'idle' };
const WICON = { working: '●', ok: '✓', late: '!', down: '✕', waiting: '◔', idle: '·' };
const CX = 640, CY = 372, RING = 215;

function wsig(d) {
  return [d.senses, d.routines, d.safety, d.work_nodes, d.memory_nodes, d.guard_nodes].map((a) => (a || []).map((n) => n.id).join(',')).join('|') + '#' + (d.agents || []).map((a) => a.id).join(',');
}
const clip = (s, n) => { s = String(s || ''); return s.length > n ? s.slice(0, Math.max(1, n - 1)) + '…' : s; };
function wcard(n, x, y, w, h) {
  W.pos[n.id] = { x, y, w, h };
  return `<g class="node card st-${n.state}" data-nid="${esc(n.id)}" tabindex="0" role="button" aria-label="${esc(n.label)}">
    <rect class="body" x="${x}" y="${y}" width="${w}" height="${h}" rx="14"></rect>
    <circle class="halo" cx="${x + 18}" cy="${y + 20}" r="8"></circle><circle class="dot" cx="${x + 18}" cy="${y + 20}" r="4.5"></circle>
    <text class="ttl" x="${x + 34}" y="${y + 24}">${esc(n.label)}</text>
    <text class="sub" x="${x + 16}" y="${y + 42}" data-sub>${esc(clip(n.sub, Math.floor(w / 5.4)))}</text>
    <text class="sub bdg" x="${x + 16}" y="${y + 56}" data-badge></text></g>`;
}
function buildWorld(d) {
  W.pos = {};
  const senses = d.senses || [], rout = d.routines || [], safe = d.safety || [], work = d.work_nodes || [], mem = d.memory_nodes || [], gd = d.guard_nodes || [], ag = d.agents || [];
  let edges = '', cards = '', agents = '';
  senses.forEach((n, i) => { const y = 122 + i * 92; cards += wcard(n, 22, y, 214, 62);
    edges += `<path class="edge" id="e-${n.id}" d="M236,${y + 31} C 430,${y + 31} 470,${CY} 576,${CY}"></path><circle class="spark" id="s-${n.id}" r="3"><animateMotion dur="2.4s" repeatCount="indefinite" path="M236,${y + 31} C 430,${y + 31} 470,${CY} 576,${CY}"></animateMotion></circle>`; });
  mem.forEach((n, i) => { const y = 122 + i * 92; cards += wcard(n, 1044, y, 214, 62);
    edges += `<path class="edge" id="e-${n.id}" d="M1044,${y + 31} C 850,${y + 31} 810,${CY} 704,${CY}"></path>`; });
  gd.forEach((n, i) => { const y = 430 + i * 78; cards += wcard(n, 1044, y, 214, 62);
    edges += `<path class="edge" id="e-${n.id}" style="stroke-dasharray:2 6" d="M1044,${y + 31} C 860,${y + 31} 800,${CY + 40} 700,${CY + 30}"></path>`; });
  const band = [...work, ...rout, ...safe]; const bw = 146, gap = 10, x0 = Math.max(10, (1280 - (band.length * bw + (band.length - 1) * gap)) / 2);
  band.forEach((n, i) => { const x = x0 + i * (bw + gap), y = 752; cards += wcard(n, x, y, bw, 62);
    const p = `M${x + bw / 2},${y} C ${x + bw / 2},${y - 130} 640,${CY + 190} 640,${CY + 70}`;
    edges += `<path class="edge" id="e-${n.id}" d="${p}"></path><circle class="spark" id="s-${n.id}" r="3"><animateMotion dur="2.6s" repeatCount="indefinite" path="${p}" keyPoints="1;0" keyTimes="0;1" calcMode="linear"></animateMotion></circle>`; });
  ag.forEach((a, i) => { const ang = -Math.PI / 2 + (i * 2 * Math.PI) / ag.length, x = CX + RING * Math.cos(ang), y = CY + RING * Math.sin(ang);
    const lx = CX + (RING + 26) * Math.cos(ang), ly = CY + (RING + 26) * Math.sin(ang) + (Math.sin(ang) > 0.55 ? 11 : Math.sin(ang) < -0.55 ? -3 : 0), side = Math.cos(ang);
    const anchor = Math.abs(side) < 0.2 ? 'middle' : side > 0 ? 'start' : 'end';
    W.pos[a.id] = { x, y, r: 15 };
    edges += `<line class="spoke" id="e-${a.id}" x1="${CX + 72 * Math.cos(ang)}" y1="${CY + 72 * Math.sin(ang)}" x2="${x - 15 * Math.cos(ang)}" y2="${y - 15 * Math.sin(ang)}"></line>`;
    agents += `<g class="node agent st-${a.state}" data-nid="${esc(a.id)}" tabindex="0" role="button" aria-label="${esc(a.label)}"><g class="bob">
      <circle class="halo" cx="${x}" cy="${y}" r="19"></circle><circle class="body" cx="${x}" cy="${y}" r="15"></circle><text class="glyph" x="${x}" y="${y + 1}">${esc((a.label || a.id)[0].toUpperCase())}</text></g>
      <text class="lab" x="${lx}" y="${ly + 4}" text-anchor="${anchor}">${esc(a.label)}</text></g>`; });
  return `<svg class="wsvg" viewBox="0 0 1280 836" role="img" aria-label="The system's world: senses on the left, agents around the brain, memory and guards on the right, work along the bottom">
    <text class="zone" x="22" y="106">Senses · what brings data in</text><text class="zone" x="1044" y="106">Memory</text><text class="zone" x="1044" y="414">Guards</text>
    <text class="zone" x="${x0}" y="736">Work and routines</text><text class="zone" x="${CX}" y="${CY - RING - 52}" text-anchor="middle">Agents</text>
    <circle class="orbit" cx="${CX}" cy="${CY}" r="${RING}"></circle><circle class="orbit" cx="${CX}" cy="${CY}" r="${RING + 60}" style="opacity:.5"></circle>
    ${edges}
    <g class="node brain st-${(d.brain || {}).state || 'idle'}" data-nid="brain" tabindex="0" role="button" aria-label="The brain">
      <circle class="ring r3" cx="${CX}" cy="${CY}" r="132"></circle><circle class="ring r2" cx="${CX}" cy="${CY}" r="104"></circle><circle class="ring r1" cx="${CX}" cy="${CY}" r="86"></circle>
      <circle class="halo" cx="${CX}" cy="${CY}" r="72" style="stroke-width:2"></circle><circle class="orbbody" cx="${CX}" cy="${CY}" r="64"></circle>
      <text class="bt" x="${CX}" y="${CY - 4}">The brain</text><text class="bs" x="${CX}" y="${CY + 14}" data-bsub></text></g>
    ${cards}${agents}</svg>`;
}
function wInspector(d) {
  const id = W.sel; if (!id) return '';
  const find = (arr) => (arr || []).find((n) => n.id === id);
  const n = id === 'brain' ? { ...(d.brain || {}), label: 'The brain', id } : find(d.agents) || find(d.senses) || find(d.routines) || find(d.safety) || find(d.work_nodes) || find(d.memory_nodes) || find(d.guard_nodes);
  if (!n) return '';
  let body = '';
  if (id === 'brain') {
    const l = n.last;
    body = `<div class="k">Mode: ${esc(n.mode || '')} · ${n.passes_today || 0} pass(es) today${n.using_tool ? ' · using ' + esc(n.using_tool) + ' now' : ''}</div>
      ${l ? `<div class="k">Last pass #${l.id} at ${esc(l.at)}: ${esc(l.status)} (${esc(l.trigger)})${l.cost_inr ? ', Rs ' + l.cost_inr : ''}${l.error ? ' · ' + esc(l.error) : ''}</div>` : '<div class="k">No pass yet.</div>'}`;
  } else if (n.jobs) {
    body = `<div class="k">${esc(n.sub || '')} · ${n.done_today}/${n.of} done today</div><table><tr><th>Routine</th><th>When</th><th>State</th><th>Last</th></tr>
      ${n.jobs.map((j) => `<tr class="st-${j.state}"><td>${esc(j.job.replace(/_/g, ' '))}</td><td>${esc(j.when)}</td><td><span class="pill">${esc(WSTATE[j.state])}</span></td><td>${esc(j.last ? j.last.at.slice(5) + (j.last.status !== 'ok' ? ' ' + j.last.status : '') : 'never')}${j.last && j.last.detail ? '<div class="age">' + esc(j.last.detail) + '</div>' : ''}</td></tr>`).join('')}</table>`;
  } else if (n.does !== undefined) {
    body = `<div class="k">${esc(n.does)}</div><div class="k">${n.running} running · ${n.waiting} waiting · ${n.done_24h} done and ${n.failed_24h} failed in the last day${n.last_done ? ' · last done ' + esc(n.last_done) : ''}</div>
      ${n.doing ? `<div class="k">Doing: ${esc(n.doing)}</div>` : ''}`;
  } else {
    const dt = n.detail || {};
    body = `<div class="k">${esc(n.sub || '')}</div>${Object.entries(dt).map(([k, v]) => `<div class="k">${esc(k.replace(/_/g, ' '))}: ${esc(typeof v === 'object' ? JSON.stringify(v) : String(v))}</div>`).join('')}`;
  }
  return `<section class="glass insp st-${n.state}"><h4><span class="si">${WICON[n.state] || '·'}</span>${esc(n.label)} <span class="pill">${esc(WSTATE[n.state] || n.state)}</span>
    <button class="btn" id="wclose" style="margin-left:auto;font-size:12px;padding:2px 9px">Close</button></h4>${body}</section>`;
}
function wShell(d) {
  return `<div class="world"><div class="left">
    <div class="map" id="wmap"><div class="wtitle"><b>The world</b><span id="wupd">live</span></div>${buildWorld(d)}
      <div class="legend"><span><i style="background:var(--w-working)"></i>working now</span><span><i style="background:var(--w-ok)"></i>done</span><span><i style="background:var(--w-late)"></i>due</span>
      <span><i style="background:var(--w-wait)"></i>waiting</span><span><i style="background:var(--w-down)"></i>failed</span><span><i style="background:var(--w-idle)"></i>idle</span></div></div>
    <div class="below" id="wbelow"></div></div>
    <aside>
      <section class="glass pulsecard"><div class="orbrow"><div class="orb" id="worb"></div><div><div class="verdict" id="wverdict"></div><div class="age" id="wsys"></div></div></div>
        <div class="counts" id="wcounts"></div>
        <div class="ctrl"><button class="btn" id="wpause"></button><span class="age" style="align-self:center">Pause stops new routines; running work finishes.</span></div>
        <div class="askrow"><input id="wask" placeholder="Tell the AI what you want, or ask what it is doing…" aria-label="Ask the AI"><button class="btn primary" id="wsend">Ask</button></div></section>
      <div id="winsp"></div>
      <section class="glass"><div class="panelh"><b>Is everything running? Is it done?</b><span class="age" id="wchk"></span></div><div class="tabsm" id="wtabs"></div><div class="checks" id="wchecks"></div></section>
      <section class="glass"><div class="panelh"><b>Live activity</b><span class="age">newest first</span></div><div class="feed" id="wfeed"></div></section>
    </aside></div>`;
}
function wCounts(d) {
  const c = d.counts, items = [['working', c.working, 'working'], ['done', c.done_today, 'done today'], ['waiting', c.waiting + c.late, 'waiting'], ['down', c.down, 'failed']];
  $('wcounts').innerHTML = items.map(([k, v, l]) => `<div class="cnt ${k} ${W.filter === k ? 'on' : ''}" data-f="${k}" role="button" tabindex="0"><b>${v}</b><span>${l}</span></div>`).join('');
  document.querySelectorAll('#wcounts .cnt').forEach((el) => { el.onclick = () => { W.filter = W.filter === el.dataset.f ? 'all' : el.dataset.f; wChecks(W.last); wCounts(W.last); }; });
}
function wMatch(c) {
  const f = W.filter;
  return f === 'all' || (f === 'working' && c.state === 'working') || (f === 'done' && (c.state === 'ok' && c.done !== false)) ||
    (f === 'waiting' && (c.state === 'waiting' || c.state === 'late')) || (f === 'down' && c.state === 'down');
}
function wChecks(d) {
  const rows = d.checks.filter(wMatch);
  const groups = {}; rows.forEach((r) => { (groups[r.group] = groups[r.group] || []).push(r); });
  $('wtabs').innerHTML = [['all', 'All'], ['working', 'Running'], ['done', 'Done'], ['waiting', 'Waiting / due'], ['down', 'Not working']].map(([k, l]) => `<button class="${W.filter === k ? 'on' : ''}" data-f="${k}">${l}</button>`).join('');
  document.querySelectorAll('#wtabs button').forEach((b) => { b.onclick = () => { W.filter = b.dataset.f; wChecks(d); wCounts(d); }; });
  $('wchecks').innerHTML = Object.entries(groups).map(([g, rs]) => `<div class="cgrp">${esc(g)}</div>` + rs.map((r) => `<div class="crow st-${r.state}"><span class="si">${WICON[r.state] || '·'}</span>
    <div><div class="t">${esc(r.name)}</div><div class="d">${esc(r.detail)}</div></div><span class="w">${esc(r.done === true && r.state === 'ok' ? 'done' : (r.group === 'Connections' || r.group === 'Data') && r.state === 'late' ? 'check' : WSTATE[r.state] || r.state)}</span></div>`).join('')).join('') || '<div class="d" style="padding:10px;color:var(--w-dim)">Nothing in this view.</div>';
  const t = d.checks.length, ok = d.checks.filter((r) => r.state === 'ok' || r.state === 'idle').length;
  $('wchk').textContent = `${ok} of ${t} fine`;
}
function wBelow(d) {
  const li = d.looking_into || { investigations: [], experiments: [] }, needs = d.needs || [];
  const inv = li.investigations.map((c) => `<div class="crow st-${c.status === 'failed' ? 'down' : c.status === 'running' ? 'working' : c.status === 'waiting_data' || c.status === 'awaiting_approval' ? 'waiting' : 'ok'}"><span class="si">${c.status === 'running' ? '●' : c.status === 'waiting_data' ? '◔' : '·'}</span>
    <div><div class="t">${esc(c.question)}</div><div class="d">${esc(c.status.replace(/_/g, ' '))} · evidence ${c.evidence.for} for, ${c.evidence.against} against, ${c.evidence.missing} missing${c.waiting_for.length ? ' · waiting for ' + esc(c.waiting_for[0]) : ''}</div></div><span class="w">#${c.id}</span></div>`).join('');
  const exs = li.experiments.map((e) => `<div class="crow st-${e.status === 'running' ? 'working' : e.status === 'kept' ? 'ok' : e.status === 'waiting' ? 'waiting' : e.status === 'registered' ? 'late' : 'idle'}"><span class="si">${e.status === 'kept' ? '✓' : e.status === 'rejected' ? '×' : '·'}</span>
    <div><div class="t">${esc(e.hypothesis)}</div><div class="d">${esc(e.status)} · ${e.candidates} candidate(s) tried${e.why ? ' · ' + esc(String(e.why).slice(0, 90)) : ''}</div></div><span class="w">#${e.id}</span></div>`).join('');
  const nd = needs.map((n) => `<div class="crow st-waiting"><span class="si">◔</span><div><div class="t">${esc(n.title)}</div><div class="d">${esc(n.agent)} · ${esc(n.at)}</div></div><a class="w" href="${n.go === 'settings' ? '#/settings' : '#/inbox'}">open</a></div>`).join('');
  $('wbelow').innerHTML = `<section class="glass"><div class="panelh"><b>The AI is looking into</b><span class="age">${li.investigations.length} open</span></div><div class="checks" style="max-height:none">${inv || '<div class="d" style="padding:8px;color:var(--w-dim)">No open investigation. It opens one by itself when it finds a question nobody asked.</div>'}</div></section>
    <section class="glass"><div class="panelh"><b>Experiments</b><span class="age">a rejection is a result</span></div><div class="checks" style="max-height:none">${exs || '<div class="d" style="padding:8px;color:var(--w-dim)">None registered yet.</div>'}</div></section>
    <section class="glass"><div class="panelh"><b>Waiting on you</b><span class="age">${needs.length ? needs.length + ' shown' : 'nothing'}</span></div><div class="checks" style="max-height:none">${nd || '<div class="d" style="padding:8px;color:var(--w-dim)">Nothing is waiting on you.</div>'}</div></section>`;
}
function wFeed(d) {
  $('wfeed').innerHTML = d.feed.map((f) => `<div class="fi st-${f.tone === 'down' ? 'down' : f.tone === 'working' ? 'working' : f.tone === 'waiting' ? 'waiting' : 'ok'}"><span class="tm">${esc(f.at.slice(11, 19))}</span>
    <span class="tx"><span class="wh">${esc(f.who)}</span> · ${esc(f.text)}</span></div>`).join('') || '<div class="d" style="padding:10px;color:var(--w-dim)">Nothing has happened yet. When the first routine runs it appears here.</div>';
}
function patchWorld(d) {
  W.last = d; W.at = Date.now();
  const stateOf = (id) => { const all = [...(d.senses || []), ...(d.routines || []), ...(d.safety || []), ...(d.work_nodes || []), ...(d.memory_nodes || []), ...(d.guard_nodes || []), ...(d.agents || [])];
    return id === 'brain' ? (d.brain || {}).state || 'idle' : (all.find((n) => n.id === id) || {}).state || 'idle'; };
  document.querySelectorAll('#wmap [data-nid]').forEach((g) => {
    const id = g.dataset.nid, s = stateOf(id), cls = `node ${g.classList.contains('card') ? 'card' : g.classList.contains('agent') ? 'agent' : 'brain'} st-${s}${W.sel === id ? ' sel' : ''}`;
    if (g.getAttribute('class') !== cls) g.setAttribute('class', cls);
    const all = [...(d.senses || []), ...(d.routines || []), ...(d.safety || []), ...(d.work_nodes || []), ...(d.memory_nodes || []), ...(d.guard_nodes || [])]; const n = all.find((x) => x.id === id);
    if (n) { const sub = g.querySelector('[data-sub]'), w = (W.pos[id] || {}).w || 200; if (sub) sub.textContent = clip(n.sub, Math.floor(w / 5.4));
      const b = g.querySelector('[data-badge]'); if (b) b.textContent = n.jobs ? `${n.done_today} of ${n.of} done today` : ''; }
    const e = document.getElementById('e-' + id);
    if (e) { const on = s === 'working'; e.setAttribute('class', (e.tagName === 'line' ? 'spoke' : 'edge') + (on ? ' on' : '')); e.style.setProperty('--c', 'var(--w-working)'); }
    const sp = document.getElementById('s-' + id); if (sp) sp.style.opacity = s === 'working' ? 1 : 0;
  });
  const bs = document.querySelector('#wmap [data-bsub]'); if (bs) bs.textContent = d.brain.using_tool ? 'using ' + d.brain.using_tool : d.brain.state === 'working' ? 'thinking' : `${d.brain.passes_today || 0} pass(es) today`;
  const p = d.pulse; $('worb').className = 'orb ' + (p.tone === 'ok' ? '' : p.tone); $('wverdict').textContent = p.verdict;
  $('wsys').textContent = (p.catching_up ? p.catching_up + ' · ' : '') + (p.system_verdict || '');
  const pb = $('wpause'); pb.textContent = p.paused ? 'Resume the system' : 'Pause the system'; pb.className = 'btn' + (p.paused ? ' primary' : '');
  wCounts(d); wChecks(d); wFeed(d); wBelow(d); $('winsp').innerHTML = wInspector(d);
  const cl = $('wclose'); if (cl) cl.onclick = () => { W.sel = null; patchWorld(d); };
}
function wfix(d) {            /* agent ids get a prefix: "graph" is both an agent and a memory */
  return { ...d, agents: (d.agents || []).filter((a) => a.id !== 'brain').map((a) => ({ ...a, id: 'a:' + a.id })) };   /* the brain is the centre */
}
function renderWorld(d0) {
  const d = wfix(d0), sig = wsig(d), host = $('screen');
  if (!host.querySelector('.world') || W.sig !== sig) { W.sig = sig; host.innerHTML = wShell(d); wireWorld(); }
  patchWorld(d);
  if (!W.timer) W.timer = setInterval(worldTick, 5000);
}
function wireWorld() {
  document.querySelectorAll('#wmap [data-nid]').forEach((g) => {
    const pick = () => { W.sel = W.sel === g.dataset.nid ? null : g.dataset.nid; patchWorld(W.last); };
    g.onclick = pick; g.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } };
  });
  $('wpause').onclick = async () => { try { await post('/api/world/pause', { paused: !W.last.pulse.paused }); } catch (er) { alert(er.message); } worldTick(); };
  const ask = async () => { const q = $('wask').value.trim(); if (!q) return; const r = await post('/api/chats/0/messages', { text: q, mode: 'auto' }); S.chat = r.chat_id; S.mode = 'auto'; location.hash = '#/ai'; };
  $('wsend').onclick = ask; $('wask').onkeydown = (e) => { if (e.key === 'Enter') ask(); };
}
async function worldTick() {
  if (S.screen !== 'world' || document.hidden) return;
  try { patchWorld(wfix(await api('/api/world'))); } catch (e) { const u = $('wupd'); if (u) u.textContent = 'not reachable: ' + e.message.slice(0, 60); }
}
setInterval(() => { const u = $('wupd'); if (u && S.screen === 'world' && W.at) u.textContent = `live · updated ${Math.max(0, Math.round((Date.now() - W.at) / 1000))} s ago`; }, 1000);
