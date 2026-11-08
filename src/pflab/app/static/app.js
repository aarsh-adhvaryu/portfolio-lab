/* Portfolio Lab dashboard (S54). Plain JavaScript, no external files: the screens fetch /api/* and redraw when the
   server's change signals (/api/events) move. Money is hidden in privacy mode. */
'use strict';

/* the screens (S68 redesign): Assistant, World, Portfolio, Research, Inbox, System, and Settings under the rail; ui.js draws the new ones */
const NAV = [['today', 'Today', '◉'], ['account', 'Account', '▤'], ['watchlist', 'Watchlist', '◌'], ['research', 'Research', '⌕'], ['assistant', 'Assistant', '✎'], ['system', 'System', '⚙']];
const OLD_SCREENS = ['world', 'portfolio'];            // S78: reachable by address only; the redesign's bar does not list them
const SUBS = {
  portfolio: [['overview', 'Overview'], ['holdings', 'Holdings and lots'], ['paper', 'Paper portfolio'], ['watch', 'Watch list']],
  research: [['overview', 'Overview'], ['work', 'Investigations'], ['recs', 'Recommendations'], ['memory', 'Memory'], ['rules', 'Rules and money'], ['plans', 'Plans and ideas'], ['sims', 'Simulations'], ['graph', 'Knowledge graph']],
  system: [['checks', 'Does it work'], ['now', 'Now'], ['limits', 'Limits and spend'], ['schedule', 'Schedule']],
};
const TITLES = { today: 'Today', account: 'Account', watchlist: 'Watchlist', assistant: 'Assistant', world: 'The world', portfolio: 'Portfolio', research: 'Research', inbox: 'Inbox and files', system: 'System', settings: 'Settings', setup: 'Setup' };

const GEAR = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>';
const POWER = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"></path><line x1="12" y1="2" x2="12" y2="12"></line></svg>';
const BUCKET_COLORS = ['#60A5FA', '#A78BFA', '#F5B942', '#4ADE9F', '#94A3B8', '#F472B6', '#38BDF8', '#FB923C'];
const BUCKET_NAMES = { equity: 'Stocks', equity_fund: 'Equity funds', debt: 'Debt', gold: 'Gold', reit_invit: 'REITs / InvITs',
  cash: 'Cash', unclassified: 'Unclassified', review: 'To review' };
const STATUS_NAMES = { 'in-band': ['in band', 'up'], 'soft-breach': ['outside soft band', 'warn'], 'hard-breach': ['outside hard band', 'down'] };
const bname = (b) => BUCKET_NAMES[b] || b;
function brief(detail) {
  /* a job's JSON result as a short line: "articles 168 · filings 1 · results 83" */
  try {
    const d = JSON.parse(detail);
    if (d && typeof d === 'object') return Object.entries(d).filter(([, v]) => typeof v !== 'object' && v !== '0' && v !== 0 && v !== false)
      .slice(0, 5).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(' · ') || 'nothing new';
  } catch (e) { /* not JSON: shown as it is */ }
  return detail;
}

const S = { screen: 'assistant', sub: '', settings: { privacy: false, theme: 'dark' }, data: {}, selected: null, pview: 'stocks',
  last: 0, pending: false, stopped: false, chat: null, mode: 'auto', draft: '', agent: 0 };

/* ---------- helpers ---------- */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function groupIN(n) {
  const s = Math.round(Math.abs(n)).toString();
  if (s.length <= 3) return s;
  const last = s.slice(-3); let rest = s.slice(0, -3); const parts = [];
  while (rest.length > 2) { parts.unshift(rest.slice(-2)); rest = rest.slice(0, -2); }
  if (rest) parts.unshift(rest);
  return parts.join(',') + ',' + last;
}
function rs(x, signed = false) {
  if (x === null || x === undefined || Number.isNaN(x)) return '—';
  if (S.settings.privacy) return '₹•••••';
  const sign = x < 0 ? '−' : (signed && x > 0 ? '+' : '');
  return sign + '₹' + groupIN(x);
}
function num(x, d = 2) {
  if (x === null || x === undefined || Number.isNaN(x)) return '—';
  return Number(x).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
}
function pct(x, d = 1, signed = false) {
  if (x === null || x === undefined || Number.isNaN(x)) return '—';
  const v = x * 100; const sign = v < 0 ? '−' : (signed && v > 0 ? '+' : '');
  return sign + Math.abs(v).toFixed(d) + '%';
}
const ud = (x) => (x === null || x === undefined) ? 'muted' : (x >= 0 ? 'up' : 'down');
function spark(vals, w = 80, h = 24) {
  if (!vals || vals.length < 2) return '';
  const mn = Math.min(...vals), mx = Math.max(...vals), r = (mx - mn) || 1;
  const pts = vals.map((v, i) => (i * w / (vals.length - 1)).toFixed(1) + ',' + (h - 2 - (v - mn) / r * (h - 4)).toFixed(1)).join(' ');
  const col = vals[vals.length - 1] >= vals[0] ? 'var(--up)' : 'var(--down)';
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.6"></polyline></svg>`;
}
function donut(segs, size = 132) {
  const r = 54, C = 2 * Math.PI * r; let acc = 0;
  const arcs = segs.map((s) => { const d = Math.max(0, s.v) * C; const o = -acc * C; acc += Math.max(0, s.v);
    return `<circle cx="66" cy="66" r="${r}" fill="none" stroke="${s.color}" stroke-width="18" stroke-dasharray="${d.toFixed(2)} ${C.toFixed(2)}" stroke-dashoffset="${o.toFixed(2)}" transform="rotate(-90 66 66)"></circle>`; }).join('');
  return `<svg width="${size}" height="${size}" viewBox="0 0 132 132" role="img" aria-label="Mix"><circle cx="66" cy="66" r="${r}" fill="none" stroke="var(--line2)" stroke-width="18"></circle>${arcs}</svg>`;
}
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.text()).slice(0, 300));
  return r.json();
}
const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

/* ---------- frame ---------- */
function renderTabs() {
  const need = (S.sys && S.sys.needs && S.sys.needs.total) || 0;
  $('tabs').innerHTML = NAV.map(([id, label, ic]) => `<a href="#/${id}" class="${S.screen === id ? 'on' : ''}"><span class="ic" aria-hidden="true">${ic}</span>${esc(label)}${id === 'assistant' && need ? `<span class="badge">${need}</span>` : ''}</a>`).join('')
;
  const g = $('gear'); if (g) g.classList.toggle('on', S.screen === 'settings' || S.screen === 'setup');
  $('ptitle').textContent = TITLES[S.screen] || 'Portfolio Lab';
  $('subnav').innerHTML = subnavHtml(S.screen, S.sub);
}
function renderStatus(d) {
  const k = d && d.kite, m = d && d.market;
  const mode = d ? { market: ['open', 'up'], pre_open: ['not open yet', 'warn'], after_close: ['closed', 'muted'], closed: ['closed today', 'muted'] }[d.mode] || [d.mode, 'muted'] : ['…', 'muted'];
  const kiteBtn = !k ? '' : k.logged_in ? `<span class="chip"><span class="conn" style="background:var(--up)"></span> Kite</span>`
    : k.state === 'waiting' ? `<span class="chip warn">Kite: finish the login in the new window…</span>`
    : `<button class="btn warnb" id="kiteLogin">Log in to Kite</button>`;
  const html = `
    <span class="chip">NSE <b class="${mode[1]}">${esc(mode[0])}</b></span>
    ${m && m.state && m.state !== 'calm' ? `<span class="chip">Market <b class="warn">${esc(m.state)}</b></span>` : ''}
    ${kiteBtn}
    ${d && d.update_ready ? '<button class="btn warnb" id="updateBtn" title="New code is on disk; it also restarts by itself after 30 minutes untouched with nothing running">Update ready: restart</button>' : ''}
    ${(() => { const s = (d && d.system) || S.sys; if (!s) return ''; const r = s.work.running;
      return `<a href="#/system/now" class="chip" style="display:flex;gap:6px;align-items:center" title="${esc(s.verdict)}">${sdot(s.state)}${r.length ? 'working: ' + esc(r.map((x) => x.job.replace(/_/g, ' ')).join(', ')) : esc(s.state === 'ok' ? 'in sync' : s.state === 'down' ? 'needs attention' : 'working, see System')}</a>`; })()}
    <button class="btn" id="power" aria-label="Stop the system" title="Stop the system">${POWER}</button>
    <a href="#/settings" class="btn rd-gear" id="gear" title="Settings" aria-label="Settings">${GEAR}</a>`;
  if ($('status').dataset.sig === html) { renderTabs(); return; }                          // nothing changed: leave the bar alone (no flicker)
  $('status').innerHTML = html; $('status').dataset.sig = html;
  renderTabs();
  const kb = $('kiteLogin'); if (kb) kb.onclick = kiteLogin;
  const ub = $('updateBtn'); if (ub) ub.onclick = async () => {
    await post('/api/restart'); S.stopped = true;
    $('screen').innerHTML = '<div class="soon"><b>Restarting onto the new code…</b><span class="muted">This window closes and a new one opens in a few seconds.</span></div>'; };
  $('power').onclick = stopSystem;
}
/* S58b: an update waits while you are using the window (a click or a key, at most every 30 s) */
let lastSeen = 0;
function seen() { const t = Date.now(); if (t - lastSeen > 30000) { lastSeen = t; post('/api/seen').catch(() => {}); } }
document.addEventListener('click', seen, true);
document.addEventListener('keydown', seen, true);
async function kiteLogin() {
  try { const r = await post('/api/kite/login'); window.open(r.url, 'kite', 'width=520,height=720'); load(true); }
  catch (e) { alert('Kite login could not start: ' + e.message); }
}
async function stopSystem() {
  if (!confirm('Stop the system? Running jobs get a minute to finish.')) return;
  await post('/api/shutdown'); S.stopped = true;
  $('screen').innerHTML = '<div class="soon"><b>The system is stopping.</b><span class="muted">You can close this window. Start it again from the desktop shortcut.</span></div>';
}

/* ---------- Command centre ---------- */
function tickerStrip(ts) {
  const newest = ts.map((t) => t.date).filter((x) => x && x !== 'live').sort().pop();       /* S66: a ticker older than the rest says so */
  const behind = (t) => t.date && t.date !== 'live' && newest && (new Date(newest) - new Date(t.date)) > 4 * 86400000;
  return `<div class="tickers">${ts.map((t) => `<div class="panel tick" ${behind(t) ? 'style="border-color:var(--warn-line)"' : ''}><span class="lbl">${esc(t.name)}${behind(t) ? ' <span class="warn">· old</span>' : ''}</span>
    <div class="row" style="justify-content:space-between;gap:8px"><span class="num" style="font-size:16px;font-weight:600">${num(t.value, t.value > 1000 ? 2 : 2)}</span>
    <span class="num small ${ud(t.change)}">${pct(t.change, 2, true)}</span></div><span class="tiny ${behind(t) ? 'warn' : 'muted'}">${t.date === 'live' ? 'live' : 'close ' + esc(t.date)}</span></div>`).join('')}</div>`;
}
function mixPanel(mx, h) {
  if (mx.error) return `<div class="panel"><span class="lbl">Mix against targets</span><p class="small warn">${esc(mx.error)}</p></div>`;
  const segs = mx.rows.map((r, i) => ({ v: r.weight, color: BUCKET_COLORS[i % BUCKET_COLORS.length], ...r }));
  return `<div class="panel" style="display:flex;flex-direction:column;gap:12px">
    <div class="row" style="justify-content:space-between"><span class="lbl">Mix against your targets</span><a href="#/portfolio" class="small">Details</a></div>
    <div class="row" style="gap:18px;align-items:center">${donut(segs)}
      <div style="display:flex;flex-direction:column;gap:7px;flex:1;min-width:0">${segs.map((s) => `
        <div class="row" style="gap:8px;font-size:13px"><span style="width:10px;height:10px;border-radius:3px;background:${s.color};flex:0 0 auto"></span>
        <span style="flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(bname(s.bucket))}</span>
        <span class="num" style="flex:0 0 52px;text-align:right">${pct(s.weight)}</span>
        <span class="num muted" style="flex:0 0 64px;text-align:right">tgt ${pct(s.target, 0)}</span></div>
        <div class="tiny ${(STATUS_NAMES[s.status] || ['', 'muted'])[1]}" style="margin:-4px 0 2px 18px">${esc((STATUS_NAMES[s.status] || [s.status])[0])}</div>`).join('')}</div></div>
    <span class="tiny muted">targets set by ${esc(mx.set_by)} from ${esc(mx.effective_from)}</span></div>`;
}
/* the portfolio today: Kite between statements (S58b); without a login, say what the figures are from */
function freshBanner(t, k) {
  if (!t) return '';
  if (t.source === 'kite' && k && k.logged_in) return '';
  const login = k && !k.logged_in ? (k.state === 'waiting' ? '<span class="chip warn">finish the login in the new window…</span>' : '<button class="btn warnb" id="kiteLogin2">Log in to Kite</button>') : '';
  return `<div class="panel row wrapr" style="gap:12px;border-color:var(--warn)"><b class="warn">${t.source === 'kite' ? 'Kite is not logged in today' : 'Not today\'s portfolio'}</b>
    <span class="small" style="flex:1 1 320px">${esc(maskRs((t.lines || []).join(' ')))}${k && !k.logged_in ? ' Log in to Kite so holdings, cash and today\'s trades are read now.' : ''}</span>${login}</div>`;
}
function todayPanel(t) {
  if (!t) return '';
  return `<div class="panel" style="display:flex;flex-direction:column;gap:6px"><span class="lbl">${t.source === 'kite' ? 'Today per Kite' : 'From your statements'}</span>
    ${(t.lines || []).map((l) => `<span class="small">${esc(maskRs(l))}</span>`).join('')}
    ${t.kite_cash !== null && t.kite_cash !== undefined ? `<span class="small">Zerodha cash per Kite <b class="num money">${rs(t.kite_cash)}</b>; statements <span class="num money">${rs(t.ledger_cash)}</span></span>` : ''}
    <span class="tiny muted">The ledger (tax lots, cost, income) changes only from your statements; the system asks for them each month.</span></div>`;
}
function taxPlanPanel(t) {
  if (!t) return '';
  if (t.error) return `<div class="panel"><span class="lbl">Tax planner</span><p class="small warn">${esc(t.error)}</p></div>`;
  const used = t.exemption ? (t.exemption - t.left) / t.exemption : 0;
  return `<div class="panel" style="display:flex;flex-direction:column;gap:8px"><span class="lbl">Tax planner (this year)</span>
    <div class="row" style="justify-content:space-between;font-size:13px"><span>Long-term gains exemption left</span><b class="num money">${rs(t.left)}</b></div>
    <div class="bar" style="height:6px"><i style="width:${(used * 100).toFixed(1)}%"></i></div>
    ${(t.lines || []).slice(1).map((l) => `<span class="small">${esc(maskRs(l))}</span>`).join('')}</div>`;
}
/* S66: the system as one picture (app/system.py): is it working, in sync, and what does it need from you */
const SDOT = { ok: 'var(--up)', warn: 'var(--warn)', down: 'var(--down)', off: 'var(--muted)' };
const sdot = (st) => `<span class="conn" style="background:${SDOT[st] || SDOT.off};flex:0 0 auto"></span>`;
const GOTO = { kite: 'kite', settings: '#/settings', inbox: '#/inbox' };
function systemHero(s) {
  if (!s) return '<div class="panel"><span class="small muted">Reading the system…</span></div>';
  const run = s.work.running.length ? `<span class="chip warn pulse">working: ${esc(s.work.running.map((r) => r.job.replace(/_/g, ' ')).join(', '))}</span>` : '<span class="chip muted">idle: nothing is due</span>';
  const rec = s.recommendations && !s.recommendations.current && s.recommendations.say
    ? `<div class="small warn" role="status">${esc(s.recommendations.say)}. They stay out of the lists until the data has caught up.</div>` : '';
  return `<div class="panel" style="display:flex;flex-direction:column;gap:12px;border-color:${s.state === 'ok' ? 'var(--line)' : s.state === 'down' ? 'var(--down)' : 'var(--warn-line)'}">
    <div class="row wrapr" style="gap:12px;justify-content:space-between"><div class="row" style="gap:10px">${sdot(s.state)}<b style="font-size:16px">The system: ${esc(s.verdict)}</b></div>${run}</div>
    ${rec}
    <div class="row wrapr" style="gap:8px">${s.connectors.map((c) => `<span class="chip" title="${esc(c.line)}" style="display:flex;gap:6px;align-items:center">${sdot(c.state)}<b>${esc(c.name)}</b><span class="muted">${esc(c.line.length > 56 ? c.line.slice(0, 54) + '…' : c.line)}</span>${c.action ? `<a href="#" data-sysgo="${esc(c.action)}" class="small">${c.action === 'kite' ? 'Log in' : 'Open'}</a>` : ''}</span>`).join('')}</div>
  </div>`;
}
function needsCard(s) {
  if (!s) return '';
  const n = s.needs;
  return `<section class="panel" style="flex:1 1 380px;display:flex;flex-direction:column;gap:6px">
    <div class="row" style="justify-content:space-between"><span class="lbl">Needs you</span><span class="small ${n.total ? 'warn' : 'up'}">${n.total ? n.total + ' open' : 'nothing'}</span></div>
    ${n.items.length ? n.items.map((i) => `<div class="item"><span class="dot" style="background:var(--warn)"></span><div style="min-width:0;flex:1"><div style="font-size:13px;line-height:1.4">${esc(i.title)}</div>
      <div class="tiny muted">${esc(i.agent)} · ${esc(i.at)} · <a href="${i.go === 'settings' ? '#/settings' : '#/inbox'}">open</a></div></div></div>`).join('')
      + (n.total > n.items.reduce((a, i) => a + i.count, 0) ? `<span class="tiny muted">and ${n.total - n.items.reduce((a, i) => a + i.count, 0)} more in Inbox and files</span>` : '')
      : '<span class="small muted">Nothing is waiting on you.</span>'}
  </section>`;
}
function workCard(s) {
  if (!s) return '';
  const w = s.work;
  return `<section class="panel" style="flex:1 1 380px;display:flex;flex-direction:column;gap:6px">
    <div class="row" style="justify-content:space-between"><span class="lbl">The system at work</span><a href="#/system/schedule" class="small">Schedule</a></div>
    ${w.running.map((r) => `<div class="item"><span class="dot pulse" style="background:var(--warn)"></span><div style="font-size:13px"><b>${esc(r.job.replace(/_/g, ' '))}</b> is running${r.since ? ' since ' + esc(r.since) : ''}</div></div>`).join('')}
    ${w.recent.map((r) => `<div class="item"><span class="dot" style="background:${r.ok ? 'var(--up)' : 'var(--down)'}"></span><div style="min-width:0"><div style="font-size:13px;line-height:1.4">${esc(r.says)}</div><div class="tiny muted">${esc(r.at)}</div></div></div>`).join('') || '<span class="small muted">Nothing has run yet.</span>'}
    ${w.failed_24h ? `<span class="tiny down">${w.failed_24h} run(s) failed in the last day (Schedule shows which)</span>` : ''}
  </section>`;
}
function syncCard(s) {
  if (!s) return '';
  const late = s.freshness.filter((f) => f.state !== 'ok').length;
  /* S67: data kept from before a failed refresh is marked RETAINED and stale, with the failure beside it */
  return `<section class="panel" style="flex:1 1 380px;display:flex;flex-direction:column;gap:2px">
    <div class="row" style="justify-content:space-between"><span class="lbl">Is it in sync?</span><span class="small ${late ? 'warn' : 'up'}">${late ? late + ' behind' : 'all current'}</span></div>
    ${s.freshness.map((f) => `<div style="padding:4px 0;border-bottom:1px solid var(--line2)" title="${esc(f.line)}"><div class="row" style="gap:8px">${sdot(f.state)}<span style="flex:1;font-size:13px">${esc(f.name)}</span>
      ${f.retained ? '<span class="chip warn" style="font-size:10px">retained, stale</span>' : ''}<span class="num small ${f.state === 'ok' ? 'muted' : f.state === 'warn' ? 'warn' : 'down'}">${esc(f.latest || 'none')}</span></div>
      ${f.retained ? `<div class="tiny warn" style="padding-left:20px">${esc(f.line.slice(f.line.indexOf('showing')))}</div>` : ''}</div>`).join('')}
  </section>`;
}
const CASE_CHIP = { queued: 'muted', running: 'warn', waiting_data: 'warn', retry: 'warn', awaiting_approval: 'warn', done: 'up', failed: 'down' };
function researchCard(s) {
  if (!s) return '';
  const w = s.work, inv = w.investigating || [], held = w.held || [], tk = w.tasks || {};
  const tkLine = Object.keys(tk).length ? Object.entries(tk).map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`).join(', ') : '';
  return `<section class="panel" style="flex:1 1 520px;display:flex;flex-direction:column;gap:8px">
    <div class="row" style="justify-content:space-between"><span class="lbl">Being looked into</span><span class="small muted">${inv.length ? inv.length + ' open' : 'nothing open'}${tkLine ? ' · tasks: ' + esc(tkLine) : ''}</span></div>
    ${inv.map((c) => `<div class="item"><span class="dot" style="background:var(--${CASE_CHIP[c.status] === 'up' ? 'up' : c.status === 'failed' ? 'down' : 'warn'})"></span><div style="min-width:0;flex:1">
      <div style="font-size:13px;line-height:1.4"><a href="#" data-case="${c.id}">${esc(c.question)}</a></div>
      <div class="tiny muted">${esc(c.status.replace(/_/g, ' '))} · since ${esc(c.since)} · evidence: ${c.evidence.for} for, ${c.evidence.against} against, ${c.evidence.missing} missing${c.evidence.stale ? ', ' + c.evidence.stale + ' stale' : ''}</div>
      ${c.waiting_for.length ? `<div class="tiny warn">waiting for: ${esc(c.waiting_for.join('; '))}. It carries on by itself when this arrives.</div>` : ''}
      ${c.error ? `<div class="tiny down">${esc(c.error)}${c.next ? ' · tries again ' + esc(c.next) : ''}</div>` : ''}</div></div>`).join('') || '<span class="small muted">No open investigation. The system opens one by itself when it finds a question nobody asked.</span>'}
    ${(w.decided || []).slice(0, 3).map((c) => `<div class="tiny muted">Decided: ${esc(c.question)} → <b>${esc(c.decision)}</b>${c.review ? ' · looks again ' + esc(c.review) : ''}</div>`).join('')}
    ${held.map((h) => `<div class="item"><span class="dot" style="background:var(--warn)"></span><div style="flex:1;font-size:13px">Held at the agents' hop limit: ${esc(h.text.slice(0, 120))}<div class="tiny muted">meant for ${esc(h.meant_for || '?')} · ${esc(h.why || '')} · since ${esc(h.since)}</div></div>
      <button class="btn" data-hrel="${h.id}" style="font-size:12px;padding:3px 9px">Run once</button><button class="btn" data-hdis="${h.id}" style="font-size:12px;padding:3px 9px">Dismiss</button></div>`).join('')}
  </section>`;
}
function changedCard(s) {
  if (!s || !s.changed) return '';
  const c = s.changed;
  return `<section class="panel" style="flex:1 1 380px;display:flex;flex-direction:column;gap:6px">
    <div class="row" style="justify-content:space-between"><span class="lbl">Since you last looked (${esc(c.since)})</span><button class="btn" id="seen" style="font-size:12px;padding:3px 9px">Mark seen</button></div>
    ${c.items.map((i) => `<div class="item"><span class="dot" style="background:${i.kind === 'failed' ? 'var(--down)' : 'var(--accent)'}"></span><div style="font-size:13px;line-height:1.4">${esc(i.text)}<div class="tiny muted">${esc(i.at)}</div></div></div>`).join('') || '<span class="small muted">Nothing new.</span>'}
    ${c.count > c.items.length ? `<span class="tiny muted">and ${c.count - c.items.length} more</span>` : ''}
  </section>`;
}
function readinessCard(s) {
  const r = s && s.readiness;
  if (!r || !r.stages || !r.stages.length) return '';
  return `<section class="panel" style="flex:1 1 380px;display:flex;flex-direction:column;gap:4px">
    <div class="row" style="justify-content:space-between"><span class="lbl">Ready to rely on?</span><span class="small ${r.ready ? 'up' : 'warn'}">${r.ready ? 'yes' : r.percent + '%'}</span></div>
    ${r.stages.map((g) => `<div style="padding:3px 0;border-bottom:1px solid var(--line2)"><div class="row" style="gap:8px">${sdot(g.state === 'done' ? 'ok' : g.state === 'partial' ? 'warn' : 'down')}<b style="font-size:13px;flex:1">${esc(g.title)}</b><span class="tiny muted">${esc(g.state)}</span></div>
      <div class="tiny muted" style="padding-left:20px">${esc(g.detail)}</div>${g.todo.map((t) => `<div class="tiny warn" style="padding-left:20px">${esc(t)}</div>`).join('')}</div>`).join('')}
    <span class="tiny muted">Read from what is reconciled and covered, not from jobs having run.</span>
  </section>`;
}
function coverageCard(s) {
  const c = s && s.coverage;
  const o = s && s.onboarding;
  const newHere = o && o.say ? `<div class="small warn" style="padding:4px 0">${esc(o.say)}</div>` : '';
  if (!c || !c.accounts.length) {
    return newHere ? `<section class="panel" style="flex:1 1 380px;display:flex;flex-direction:column;gap:4px"><span class="lbl">What I know about you</span>${newHere}${(o.unknown || []).map((u) => `<div class="tiny muted">Not yet known: ${esc(u)}</div>`).join('')}</section>` : '';
  }
  const st = c.status;
  const tone = st.label === 'complete' ? 'up' : 'warn';
  return `<section class="panel" style="flex:1 1 380px;display:flex;flex-direction:column;gap:4px">
    <div class="row" style="justify-content:space-between"><span class="lbl">Accounts found and what I can say about them</span><span class="small ${tone}">${esc(st.label)}</span></div>
    ${newHere}
    ${c.accounts.map((a) => `<div style="padding:3px 0;border-bottom:1px solid var(--line2)"><div class="row" style="gap:8px"><b style="font-size:13px;flex:1">${esc(a.account)}</b><span class="tiny muted">${esc(a.state)}</span></div>
      <div class="tiny muted">${a.covered_from ? 'statements ' + esc(a.covered_from) + ' to ' + esc(a.covered_to) + (a.statement_holes && a.statement_holes.length ? '; not covered: ' + esc(a.statement_holes.slice(0, 3).join(', ')) : '') : (a.state.startsWith('set up') ? 'no statement read yet' : '')}${a.next ? ' · ' + esc(a.next) : ''}</div>${a.key ? `<div class="row" style="gap:6px;padding-top:3px">${a.state.startsWith('left out')
        ? `<button class="btn" data-covback="${esc(a.key)}" style="font-size:11px;padding:2px 8px">Add back</button>`
        : `<button class="btn" data-covleave="${esc(a.key)}" style="font-size:11px;padding:2px 8px">Leave out for now</button>`}</div>` : ''}</div>`).join('')}
    ${c.gaps.length ? `<div class="tiny warn">${c.gaps.length} file(s) or message(s) I could not use are listed, not forgotten.</div>` : ''}
    ${(st.reasons || []).map((r) => `<div class="tiny warn">${esc(r)}</div>`).join('')}
    <div class="row wrapr" style="gap:6px"><input class="inp" id="covDecl" placeholder="An account I have but will add later (its bank and what it is)" style="flex:1 1 220px;font-size:12px"><button class="btn" id="covDeclGo" style="font-size:12px;padding:3px 9px">Leave it out for now</button></div>
    ${st.label !== 'complete' ? '<div class="row"><button class="btn" id="covConfirm" style="font-size:12px;padding:3px 9px">This is every account and every file I have</button></div>' : ''}
    <span class="tiny muted">${esc(st.note || '')}</span>
  </section>`;
}
function showCase(c) {
  const ev = c.evidence.map((e) => `<li><b>${esc(e.stance)}</b>${e.source_kind ? ' · ' + esc(e.source_kind) : ''}: ${esc(e.text)} <span class="tiny muted">(published ${esc((e.published || e.event || 'undated').toString().slice(0, 10))}, retrieved ${esc((e.retrieved || '').toString().slice(0, 10))})</span></li>`).join('');
  const calc = c.calculations.map((k) => `<li>calculation #${k.id}: ${esc(k.status)}, ${esc(k.where || '')}; data: ${esc(k.datasets.join(', '))}; result: ${esc(JSON.stringify(k.result))}</li>`).join('');
  const log = c.log.map((l) => `<li><span class="tiny muted">${esc(l.at)}</span> ${esc(l.event)}: ${esc(l.detail || '')}</li>`).join('');
  const rv = c.reviews.map((r) => `<li>${r.flags.length ? esc(r.flags.join('; ')) : 'no process problems found'}${r.outcome ? ' · outcome later: ' + esc(r.outcome) : ''}</li>`).join('');
  const box = document.createElement('dialog');
  box.style.cssText = 'max-width:760px;width:92vw;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:16px';
  box.innerHTML = `<div style="display:flex;flex-direction:column;gap:8px"><b>#${c.id} ${esc(c.question)}</b>
    <span class="small muted">${esc(c.status.replace(/_/g, ' '))} · ${c.assessment.verdict} · decision: ${esc(c.decision || 'none yet')}${c.reason ? ' (' + esc(c.reason) + ')' : ''}${c.uncertainty ? ' · uncertain: ' + esc(c.uncertainty) : ''}</span>
    ${c.assumptions.length ? `<div class="small">Assumes: ${esc(c.assumptions.join('; '))}</div>` : ''}
    <div class="small"><b>Evidence</b><ul>${ev || '<li>none yet</li>'}</ul></div>${calc ? `<div class="small"><b>Calculations</b><ul>${calc}</ul></div>` : ''}
    <div class="small"><b>Why it changed / what happened</b><ul>${log}</ul></div>${rv ? `<div class="small"><b>Review of the process</b><ul>${rv}</ul></div>` : ''}
    <button class="btn" id="caseClose">Close</button></div>`;
  document.body.appendChild(box);
  box.querySelector('#caseClose').onclick = () => { box.close(); box.remove(); };
  box.showModal();
}
function processingNote(s) {
  if (!s || !s.processing) return '';
  return `<details class="tiny muted" style="margin-top:6px"><summary>Where each thing is processed</summary>${s.processing.map((p) => `<div style="padding:2px 0"><b>${esc(p.what)}</b>: ${esc(p.where)} (${esc(p.model)}). Sends: ${esc(p.sends)}.</div>`).join('')}</details>`;
}
function wireSystem() {
  const seen = document.getElementById('seen');
  if (seen) seen.onclick = async () => { try { await post('/api/system/seen', {}); } catch (er) { alert(er.message); } S.sys = null; load(true); };
  document.querySelectorAll('[data-covleave]').forEach((b) => { b.onclick = async () => { try { await post('/api/coverage/leave_out', { key: b.dataset.covleave }); } catch (er) { alert(er.message); } S.sys = null; load(true); }; });
  document.querySelectorAll('[data-covback]').forEach((b) => { b.onclick = async () => { try { await post('/api/coverage/add_back', { key: b.dataset.covback }); } catch (er) { alert(er.message); } S.sys = null; load(true); }; });
  const cd = document.getElementById('covDeclGo');
  if (cd) cd.onclick = async () => { const t = document.getElementById('covDecl').value.trim(); if (!t) return; try { await post('/api/coverage/leave_out', { text: t }); } catch (er) { alert(er.message); } S.sys = null; load(true); };
  const cc = document.getElementById('covConfirm');
  if (cc) cc.onclick = async () => { if (!confirm('Confirm that these are all your accounts and files? I will ask again if I find another.')) return; try { await post('/api/coverage/confirm', {}); } catch (er) { alert(er.message); } S.sys = null; load(true); };
  document.querySelectorAll('[data-hrel]').forEach((b) => { b.onclick = async () => { try { await post('/api/hq/tasks/' + b.dataset.hrel + '/release', {}); } catch (er) { alert(er.message); } S.sys = null; load(true); }; });
  document.querySelectorAll('[data-hdis]').forEach((b) => { b.onclick = async () => { const why = prompt('Why dismiss it?', 'not wanted'); if (why === null) return; try { await post('/api/hq/tasks/' + b.dataset.hdis + '/dismiss', { reason: why }); } catch (er) { alert(er.message); } S.sys = null; load(true); }; });
  document.querySelectorAll('[data-case]').forEach((a) => { a.onclick = async (e) => { e.preventDefault(); try { showCase(await api('/api/cases/' + a.dataset.case)); } catch (er) { alert(er.message); } }; });
  document.querySelectorAll('[data-sysgo]').forEach((a) => { a.onclick = async (e) => {
    e.preventDefault(); const g = a.dataset.sysgo;
    if (g === 'kite') return kiteLogin();
    location.hash = GOTO[g] || '#/settings'; }; });
}
async function addNote() { const t = $('noteIn').value.trim(); if (!t) return; await post('/api/notes', { text: t }); load(true); }

/* ---------- Portfolio ---------- */
function tiles(items) {
  const heat = (c) => c === null || c === undefined ? 'var(--line2)' : c >= 0.015 ? '#166B4A' : c >= 0.003 ? '#1F5A40' : c > -0.003 ? '#2A3445' : c > -0.015 ? '#7A2E2E' : '#9B2C2C';
  const rows = [items.slice(0, 3), items.slice(3, 7), items.slice(7, 14)].filter((r) => r.length);
  return `<div style="display:flex;flex-direction:column;gap:4px;height:300px">${rows.map((r) => `<div style="display:flex;gap:4px;flex:${r.reduce((a, x) => a + x.w, 0).toFixed(4)} 1 0;min-height:0">
    ${r.map((t) => `<button data-isin="${esc(t.isin || '')}" title="${esc(t.name)} · ${pct(t.w)}" style="flex:${t.w.toFixed(4)} 1 0;min-width:0;overflow:hidden;background:${heat(t.c)};border:1px solid var(--bg);border-radius:6px;color:#F8FAFC;text-align:left;padding:8px;cursor:${t.isin ? 'pointer' : 'default'};display:flex;flex-direction:column;justify-content:space-between">
      <span style="font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(t.name)}</span><span class="num" style="font-size:12px">${pct(t.w)}${t.c !== undefined && t.c !== null ? ' · ' + pct(t.c, 2, true) : ''}</span></button>`).join('')}</div>`).join('')}</div>`;
}
function renderPortfolio(d) {
  const h = d.holdings, t = d.tax || {};
  const realised = t.realised ? Object.values(t.realised).reduce((a, b) => a + b, 0) : null;
  const taxSoFar = t.new !== undefined ? Math.min(t.new, t.old) : null;
  const total = Object.values(h.buckets).reduce((a, b) => a + b, 0) || 1;
  let items;
  if (S.pview === 'buckets') items = Object.entries(h.buckets).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ name: bname(k), w: v / total }));
  else if (S.pview === 'sectors') items = d.sectors.map((s) => ({ name: s.sector, w: s.weight }));
  else items = h.rows.filter((r) => r.value).map((r) => ({ name: r.symbol || r.isin, w: r.weight, c: r.change, isin: r.isin }));
  const sel = h.rows.find((r) => r.isin === d.selected);
  const perKite = new Set(((h.today || {}).diffs || []).map((x) => x.isin));
  $('screen').innerHTML = `
  ${freshBanner(h.today, (S.data.command || {}).kite)}
  <div class="cols">${[['Net worth', rs(h.net_worth), h.today ? (h.today.source === 'kite' ? 'today per Kite' : 'from statements to ' + h.today.documents_to) : ''], ['Invested (cost)', rs(h.invested_cost), ''], ['Unrealised', rs(h.unrealised, true), h.invested_cost ? pct(h.unrealised / h.invested_cost, 1, true) : ''],
    ['Realised this FY', realised === null ? '—' : rs(realised, true), t.realised ? Object.entries(t.realised).filter(([, v]) => v).map(([k, v]) => `${k} ${rs(v, true)}`).join(' · ') || 'none' : ''],
    ['Tax so far (est.)', taxSoFar === null ? '—' : rs(taxSoFar), t.cheaper ? `cheaper: ${t.cheaper} regime` : (t.error || '')],
    ['Change in 12 months', d.growth && d.growth.total_change !== undefined ? rs(d.growth.total_change, true) : '—',
     d.growth && d.growth.total_change !== undefined ? `money in ${rs(d.growth.money_put_in, true)} · gains ${rs(d.growth.realised_gains + d.growth.unrealised_change, true)} · income ${rs(d.growth.income, true)} · charges ${rs(-d.growth.charges, true)}` : ((d.growth || {}).error || '')]].map(([l, v, n]) =>
    `<div class="panel" style="flex:1 1 200px;display:flex;flex-direction:column;gap:4px"><span class="lbl">${l}</span><span class="num money" style="font-size:20px;font-weight:600">${v}</span><span class="tiny muted">${esc(n)}</span></div>`).join('')}</div>
  <div class="row wrapr" style="gap:8px"><span class="lbl">View by</span>
    ${[['buckets', 'Bucket'], ['sectors', 'Sector'], ['stocks', 'Stock']].map(([id, l]) => `<button class="btn ${S.pview === id ? 'primary' : ''}" data-view="${id}">${l}</button>`).join('')}
    <span class="small muted" style="margin-left:auto">size = weight · colour = today's move · click a stock for its tax lots</span></div>
  <div class="cols">
    <section class="panel" style="flex:3 1 640px">${tiles(items)}</section>
    <section class="panel" style="flex:2 1 360px;display:flex;flex-direction:column;gap:10px">
      <span class="lbl">Sector exposure (direct stocks)</span>
      ${d.sectors.slice(0, 10).map((s) => `<div style="display:flex;flex-direction:column;gap:4px"><div class="row" style="justify-content:space-between;font-size:13px"><span>${esc(s.sector)}</span><span class="num">${pct(s.weight)}</span></div><div class="bar"><i style="width:${(s.weight * 100).toFixed(1)}%"></i></div></div>`).join('') || '<span class="small muted">No direct stocks.</span>'}
      <span class="tiny muted">Look-through of fund holdings joins in a later part.</span>
    </section>
  </div>
  <div class="cols">
    <section class="panel" style="flex:3 1 640px;display:flex;flex-direction:column;gap:10px">
      <span class="lbl">Every position</span>
      <div class="scroll"><table style="min-width:680px"><thead><tr><th>Name</th><th>Bucket</th><th>Qty</th><th>Price</th><th>Value</th><th>Cost</th><th>P&amp;L</th><th>Weight</th></tr></thead><tbody>
      ${h.rows.map((r) => `<tr class="click ${r.isin === d.selected ? 'sel' : ''}" data-isin="${esc(r.isin)}"><td><b>${esc(r.symbol || r.isin)}</b><br><span class="tiny muted">${esc(r.name || '')}</span></td><td>${esc(r.bucket)}</td>
        <td class="num">${num(r.qty, r.qty % 1 ? 3 : 0)}${perKite.has(r.isin) ? ' <span class="tiny warn">per Kite</span>' : ''}</td><td class="num">${num(r.price)}${r.stale ? ' <span class="tiny warn">stale</span>' : ''}</td><td class="num money">${rs(r.value)}</td>
        <td class="num money">${rs(r.cost)}</td><td class="num money ${ud(r.unrealised)}">${rs(r.unrealised, true)}</td><td class="num">${pct(r.weight)}</td></tr>`).join('')}
      </tbody></table></div>
    </section>
    <section class="stack" style="flex:2 1 400px">
      ${todayPanel(h.today)}
      ${taxPlanPanel(d.taxplan)}
      <div class="panel" style="display:flex;flex-direction:column;gap:10px">
        <span class="lbl">Tax lots ·${esc(sel ? sel.symbol || sel.isin : '—')}</span>
        <div class="scroll"><table><thead><tr><th>Bought</th><th>Qty</th><th>Cost/unit</th><th>Gain</th><th>Long-term</th><th title="extra tax this year if sold today through this lot (FIFO), cheaper regime">Tax if sold to here</th></tr></thead><tbody>
        ${d.lots.map((l) => `<tr><td class="num">${esc(l.bought)}</td><td class="num">${num(l.qty, l.qty % 1 ? 3 : 0)}</td><td class="num">${num(l.cost_per_unit)}</td>
          <td class="num money ${ud(l.gain)}">${rs(l.gain, true)}</td><td class="small">${l.long_term ? '<span class="up">yes</span>' : l.long_term_from ? 'from ' + esc(l.long_term_from) : '—'}</td>
          <td class="num money">${l.tax_through === null || l.tax_through === undefined ? '—' : rs(l.tax_through)}${l.waiting_saves ? `<br><span class="tiny up">wait: saves ${rs(l.waiting_saves)}</span>` : ''}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">No lots.</td></tr>'}
        </tbody></table></div>
        <span class="tiny muted">FIFO, from the ledger; tax from the tax engine (dated rules), at today's price, before fees.</span>
      </div>
      <div class="panel" style="display:flex;flex-direction:column;gap:8px">
        <span class="lbl">Fixed deposits</span>
        ${h.fds.length ? h.fds.map((f) => `<div class="row" style="justify-content:space-between;font-size:13px;padding:4px 0;border-bottom:1px solid var(--line2)"><span>matures ${esc(f.maturity)}${f.reserve ? ' · reserve' : ''}</span><span class="num money">${rs(f.value)}${f.estimate ? ' <span class="tiny warn">est.</span>' : ''}</span></div>`).join('') : '<span class="small muted">None open.</span>'}
      </div>
    </section>
  </div>`;
  document.querySelectorAll('[data-view]').forEach((b) => { b.onclick = () => { S.pview = b.dataset.view; renderPortfolio(d); }; });
  const k2 = $('kiteLogin2'); if (k2) k2.onclick = kiteLogin;
  document.querySelectorAll('[data-isin]').forEach((b) => { if (b.dataset.isin) b.onclick = () => { S.selected = b.dataset.isin; load(true); }; });
}

/* ---------- Schedule (54e): presets, catch-up, checklists, the nightly simulation ---------- */
const PRESET_NAMES = { off: 'Off', light: 'Light', full: 'Full', marathon: 'Marathon' };
function lastRun(r) {
  const l = r.last_run;
  if (!l) return '<span class="muted">never</span>';
  const cls = { ok: 'up', failed: 'down', running: 'warn' }[l.status] || 'muted';
  const took = l.seconds === null ? '' : l.seconds < 90 ? ` · ${l.seconds} s` : ` · ${(l.seconds / 60).toFixed(1)} min`;
  const why = l.detail ? `<br><span class="muted">${esc(l.detail)}</span>` : '';
  const asked = r.asked && r.asked.startsWith('skipped') ?`<br><span class="muted">your run: ${esc(r.asked)}</span>` : '';
  return `<span class="${cls}">${esc(l.status)}</span> <span class="muted">${esc(l.at.slice(5))}${took}</span>${why}${asked}`;
}
function renderSchedule(d) {
  const lists = d.checklists.map((l) => { const done = l.items.filter((i) => i.done).length;
    return `<div style="background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px">
      <div class="row" style="justify-content:space-between"><b>${esc(l.name)}</b><span class="row" style="gap:8px"><span class="tiny muted">${done} of ${l.items.length}</span><button class="btn" style="min-height:28px;padding:4px 10px" data-closelist="${esc(l.name)}">Close</button></span></div>
      <div class="bar" style="height:6px"><i style="width:${(done / l.items.length * 100).toFixed(0)}%"></i></div>
      ${l.items.map((i) => `<label class="row small" style="gap:8px;align-items:flex-start;cursor:pointer"><input type="checkbox" ${i.done ? 'checked' : ''} data-tick="${i.id}" style="margin-top:2px"><span style="${i.done ? 'text-decoration:line-through;opacity:.65' : ''}">${esc(i.text)}</span></label>`).join('')}</div>`; }).join('');
  $('screen').innerHTML = `<div class="cols">
    <section class="stack" style="flex:2 1 640px">
      <div class="panel" style="display:flex;flex-direction:column;gap:10px">
        <span class="lbl">How much the system does while it runs</span>
        <div class="row wrapr" style="gap:8px">${Object.keys(PRESET_NAMES).map((k) => `<button class="btn ${d.preset === k ? 'primary' : ''}" data-preset="${k}">${PRESET_NAMES[k]}</button>`).join('')}</div>
        <span class="small soft">${esc(d.presets[d.preset])}</span>
        <span class="small muted">${d.offline_h !== null && d.offline_h > 1 ? `The system was off for ${d.offline_h} hours; ` : ''}${d.catch_up.length ? `due now and run at the next tick: ${esc(d.catch_up.join(', '))}` : 'nothing is waiting to catch up'}.</span>
        <span class="small muted">Nightly simulation: ${d.sims.paths ? `${groupIN(d.sims.paths)} paths after ${String(d.sims_hour).padStart(2, '0')}:00` : 'off under this preset'}${d.sims.last ? ` · last run ${esc(d.sims.last.slice(0, 16).replace('T', ' '))} (${groupIN(d.sims.last_paths)} paths)` : ''}${d.sims.running ? ' · <span class="warn">running now</span>' : ''}</span>
      </div>
      <section class="panel" style="display:flex;flex-direction:column;gap:6px">
        <span class="lbl">The system's jobs</span>
        <span class="small muted">The times are for when you are away; any job runs now with Run (one job at a time, in the order asked).${d.wanted.length ? ` Waiting to run: ${esc(d.wanted.join(', '))}.` : ''}</span>
        <div class="scroll"><table><thead><tr><th>Job</th><th>When</th><th>Runs</th><th>Due now</th><th>Last run</th><th>Last success</th><th>Why</th><th></th></tr></thead><tbody>
        ${d.jobs.map((r) => `<tr><td><b>${esc(r.job)}</b></td><td>${esc(r.when)}</td><td>${r.why.startsWith('disabled') ? '<span class="muted">off (see why)</span>' : r.on ? '<span class="up">yes</span>' : r.job === 'outbox' ? '<span class="muted">held until Telegram is on</span>' : '<span class="muted">not under this preset</span>'}</td><td>${r.due ? '<span class="warn">due</span>' : '<span class="muted">no</span>'}</td><td class="small" style="text-align:left">${lastRun(r)}</td><td class="num">${esc(r.last_success || 'never')}</td><td class="small muted" style="text-align:left">${esc(r.why)}</td><td>${r.runnable ? `<button class="btn" style="min-height:28px;padding:4px 10px" data-runjob="${esc(r.job)}" ${r.queued || (r.last_run && r.last_run.status === 'running') ? 'disabled' : ''}>${r.queued ? 'Waiting' : r.last_run && r.last_run.status === 'running' ? 'Running' : 'Run'}</button>` : ''}</td></tr>`).join('')}
        </tbody></table></div>${S.runMsg ? `<span class="small warn">${esc(S.runMsg)}</span>` : ''}</section>
    </section>
    <section class="stack" style="flex:1 1 380px">
      <div class="panel" style="display:flex;flex-direction:column;gap:10px">
        <span class="lbl">Checklists</span>
        <div class="row wrapr" style="gap:6px"><label class="small" for="clT" style="position:absolute;left:-9999px">Checklist</label><select id="clT" class="inp" style="flex:0 1 auto">${Object.entries(d.templates).map(([k, n]) => `<option value="${esc(k)}">${esc(k)} (${n})</option>`).join('')}</select>
          <label for="clS" style="position:absolute;left:-9999px">For</label><input id="clS" class="inp" placeholder="for (a company, a month…)"><button class="btn primary" id="clGo">Start</button></div>
        ${S.clMsg ? `<span class="small warn">${esc(S.clMsg)}</span>` : ''}
        ${lists || '<span class="small muted">No checklist open. Sticky notes stay on the Command centre.</span>'}
      </div>
    </section></div>`;
  document.querySelectorAll('[data-preset]').forEach((b) => { b.onclick = async () => { S.settings = await post('/api/settings', { preset: b.dataset.preset }); load(true); }; });
  document.querySelectorAll('[data-runjob]').forEach((b) => { b.onclick = async () => {
    b.disabled = true; S.runMsg = '';
    try { await post(`/api/jobs/${encodeURIComponent(b.dataset.runjob)}/run`, {}); } catch (e) { S.runMsg = e.message; }
    load(true); }; });
  clearTimeout(S.schedT);                       // a job running: follow it every 5 s
  if (d.busy || d.wanted.length || d.jobs.some((r) => r.last_run && r.last_run.status === 'running')) S.schedT = setTimeout(() => { if (S.screen === 'schedule') load(false); }, 5000);
  document.querySelectorAll('[data-tick]').forEach((b) => { b.onchange = async () => { await post(`/api/notes/${b.dataset.tick}/toggle`); load(true); }; });
  document.querySelectorAll('[data-closelist]').forEach((b) => { b.onclick = async () => { if (!confirm('Close this checklist?')) return; await post('/api/checklists/close', { name: b.dataset.closelist }); load(true); }; });
  $('clGo').onclick = async () => { S.clMsg = '';
    try { await post('/api/checklists', { template: $('clT').value, subject: $('clS').value }); $('clS').value = ''; } catch (e) { S.clMsg = e.message; }
    load(true); };
}
function toggleRow(key, name, help, on) {
  return `<div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><span>${esc(name)}</span><span class="small muted">${esc(help)}</span></div>
    <button class="toggle ${on ? 'on' : ''}" role="switch" aria-checked="${on}" aria-label="${esc(name)}" data-set="${key}"><i></i></button></div>`;
}
function renderSettings(s) {
  const redraw = () => { if (S.screen === 'settings') renderSettings(S.settings); };   // never over another screen
  $('screen').innerHTML = `<div class="cols">
    <section class="panel" style="flex:1 1 420px"><span class="lbl">Appearance</span>
      <div class="setting"><span style="flex:1">Theme</span>${['dark', 'light', 'system'].map((t) => `<button class="btn ${s.theme === t ? 'primary' : ''}" data-theme="${t}">${t === 'system' ? 'Follow Windows' : t[0].toUpperCase() + t.slice(1)}</button>`).join('')}</div>
      ${toggleRow('privacy', 'Privacy mode', 'hides rupee amounts (for screen sharing); percentages stay', s.privacy)}
    </section>
    <section class="panel" style="flex:1 1 420px"><span class="lbl">The system</span>
      ${toggleRow('scheduler', 'Run the jobs while this window is open', 'collect, prices, research, forecasts, guards, the conductor', s.scheduler)}
      ${toggleRow('live_prices', 'Live prices in market hours', 'Kite read-only quotes every minute, after the day\'s login', s.live_prices)}
      ${toggleRow('telegram_send', 'Send Telegram messages', 'OFF until switch-on: the held alerts stay held', s.telegram_send)}
      <div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><span>Preset</span><span class="small muted">how much runs on its own (details on the Schedule screen)</span></div>${Object.keys(PRESET_NAMES).map((k) => `<button class="btn ${s.preset === k ? 'primary' : ''}" data-spreset="${k}">${PRESET_NAMES[k]}</button>`).join('')}</div>
      <div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><span>The brain</span><span class="small muted">how often it may think (it asks and tells you and orders research, capped a day; never trades)</span></div>${BRAIN_MODES.map(([k, n]) => `<button class="btn ${s.brain === k ? 'primary' : ''}" data-sbrain="${k}">${n}</button>`).join('')}</div>
      ${toggleRow('drop_watch', 'Take files from the drop folder', 'files placed in D:\\portfolio_lab\\drop go to the inbox by themselves', s.drop_watch)}
      <div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><label for="simsHour">Nightly simulation after</label><span class="small muted">Full: 10,000 paths; Marathon: 100,000</span></div><select id="simsHour" class="inp" style="flex:0 0 auto">${[18, 19, 20, 21, 22, 23].map((h) => `<option value="${h}" ${s.sims_hour === h ? 'selected' : ''}>${h}:00</option>`).join('')}</select></div>
    </section>
    <section class="panel" style="flex:1 1 420px" id="abilitiesP"><span class="lbl">What the AI may see and use</span></section>
    <section class="panel" style="flex:1 1 420px"><span class="lbl">Setup</span><span class="small muted">your accounts, the start date and the files the ledger still needs</span>
      <a class="btn primary" href="#/setup" style="align-self:flex-start">Open Setup</a></section>
    <section class="panel" style="flex:1 1 420px" id="releaseP"><span class="lbl">This release</span><span class="small muted">loading…</span></section>
    <section class="panel" style="flex:1 1 420px" id="featuresP"><span class="lbl">Beta features</span><span class="small muted">loading…</span></section>
    <section class="panel" style="flex:1 1 420px" id="secretsP"><span class="lbl">Keys and passwords</span><span class="small muted">loading…</span></section>
    <section class="panel" style="flex:1 1 640px" id="modelsP"><span class="lbl">Models: one per job</span><span class="small muted">loading…</span></section>
    <section class="panel" style="flex:1 1 420px"><span class="lbl">Never, whatever the settings</span>
      ${['Place an order or a GTT', 'Change targets, limits or the stock list', 'Move money', 'Send personal data out of this PC'].map((t) => `<div class="setting small soft"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg> ${esc(t)}</div>`).join('')}
    </section></div>`;
  document.querySelectorAll('[data-set]').forEach((b) => { b.onclick = async () => {
    const k = b.dataset.set;
    if (k === 'telegram_send' && !s.telegram_send && !confirm('Turn on Telegram? Held alerts will be delivered at the next tick.')) return;
    S.settings = await post('/api/settings', { [k]: !s[k] }); applyTheme(); redraw(); }; });
  document.querySelectorAll('[data-theme]').forEach((b) => { b.onclick = async () => { S.settings = await post('/api/settings', { theme: b.dataset.theme }); applyTheme(); redraw(); }; });
  document.querySelectorAll('[data-spreset]').forEach((b) => { b.onclick = async () => { S.settings = await post('/api/settings', { preset: b.dataset.spreset }); redraw(); }; });
  document.querySelectorAll('[data-sbrain]').forEach((b) => { b.onclick = async () => { S.settings = await post('/api/settings', { brain: b.dataset.sbrain }); redraw(); }; });
  $('simsHour').onchange = async () => { S.settings = await post('/api/settings', { sims_hour: Number($('simsHour').value) }); redraw(); };
  if (typeof RD !== 'undefined') RD.abilities(s, redraw);
  renderRelease();
  renderFeatures(redraw);
  renderSecrets();
  renderModels(redraw);
}
/* S65: which release this is; updating needs the store free, so the launcher does it at each start (pflab update) */
async function renderRelease() {
  const el = $('releaseP'); if (!el) return;
  let d;
  try { d = await api('/api/release'); } catch (e) { el.innerHTML = `<span class="lbl">This release</span><span class="small warn">${esc(e.message)}</span>`; return; }
  el.innerHTML = d.is_app
    ? `<span class="lbl">This release · ${esc(d.channel)}</span><div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><span>${esc(d.tag)} <span class="small muted">installed ${esc(d.installed_on)}</span></span>
       <span class="small muted">Updates install by themselves: each start of Portfolio Lab takes the newest release first (the store backed up first; your record is never wiped). ${d.previous_tag ? 'To undo the last update: pflab update --rollback (previous: ' + esc(d.previous_tag) + ').' : ''}</span></div></div>`
    : `<span class="lbl">This release · ${esc(d.channel)}</span><span class="small muted">This is the workshop (beta): it develops releases and does not update itself; it sends nothing outward unless told.</span>`;
}
/* S65: Setup (ingest/setup_sources.py): the accounts and the start date write sources.toml; the files still needed are listed */
function renderSetup(d) {
  const need = d.needed.length ? `<ul>${d.needed.map((t) => `<li>${esc(t)}</li>`).join('')}</ul><span class="small muted">Drop each one in Inbox and files (any name: it is recognised by what is inside).</span>`
    : '<span class="small up">Nothing missing: the ledger can be built.</span>';
  const accts = d.exists ? Object.entries(d.accounts).map(([n, v]) => `<tr><td>${esc(n)}</td><td>${esc(v.kind)}</td><td>${esc(v.bank || v.provider || '')}</td><td>${esc(v.last4 ? '…' + v.last4 : (v.cas_dp || ''))}</td></tr>`).join('') : '';
  const form = d.exists ? `<span class="small muted">Your accounts file exists (start ${esc(d.start)}). Setup never replaces it; to change an account, edit sources.toml.</span>` : `
    <div class="row wrapr" style="gap:6px"><label class="small">Start date <input id="suStart" class="inp" type="date" style="flex:0 0 150px"></label>
      <label class="small">Zerodha account name <input id="suBroker" class="inp" value="zer" style="flex:0 0 100px"></label>
      <label class="small">Its demat DP id (8 characters, optional) <input id="suDp" class="inp" style="flex:0 0 120px"></label></div>
    <span class="small muted">Bank accounts: a name you choose, the bank, the LAST FOUR digits only, and a name for its file password (optional).</span>
    <div id="suBanks"></div><button class="btn" id="suAddBank">Add a bank account</button>
    <button class="btn primary" id="suSave" style="align-self:flex-start">Save the setup</button>`;
  const pr = !d.exists && d.proposal ? d.proposal : null;
  const prop = pr && pr.answers.banks.length ? `<div class="panel" style="display:flex;flex-direction:column;gap:6px"><b>Found in the files you dropped</b>
      <span class="small">${esc(Object.entries(pr.files).map(([k, n]) => n + ' ' + k).join(', '))}${pr.banks_unread ? ` · ${pr.banks_unread} bank file(s) could not be read (a password missing?)` : ''}</span>
      <span class="small">Zerodha account ${esc(pr.answers.broker.account)}; bank accounts: ${pr.answers.banks.map((b) => esc(b.bank) + ' ending ' + esc(b.last4)).join(', ')}</span>
      <label class="small">Start of your history <input id="prStart" class="inp" type="date" value="${esc(pr.answers.start)}" style="flex:0 0 150px"></label>
      <span class="small muted">${esc(pr.note)}</span><button class="btn primary" id="prUse" style="align-self:flex-start">Use these accounts</button></div>`
    : (!d.exists ? '<span class="small muted">Drop your statements in Inbox and files first: I will read the accounts from them and propose the setup here.</span>' : '');
  const all = d.exists ? '<button class="btn primary" id="applyAll" style="align-self:flex-start">Add everything to the ledger</button><span class="small muted">One rebuild from every checked document; written only when every check passes.</span><div id="applyOut" class="small"></div>' : '';
  $('screen').innerHTML = `<div class="cols"><section class="panel" style="flex:1 1 520px"><span class="lbl">Setup · accounts and start date</span>${prop}${all}${form}
      ${accts ? `<div class="scroll"><table><thead><tr><th>Name</th><th>Kind</th><th>Bank</th><th>Ends</th></tr></thead><tbody>${accts}</tbody></table></div>` : ''}</section>
    <section class="panel" style="flex:1 1 420px"><span class="lbl">Files still needed</span>${need}</section>
    <section class="panel" style="flex:1 1 100%"><span class="lbl">By hand · an IPO allotment, or a holding with no history here</span>
      <span class="small muted">Your record is built from every statement by itself, a minute after a file arrives; what does not match is named under Needs from you with what closes it.</span>
      <div class="row wrapr" style="gap:6px" id="ipoF">${[['ipo_id', 'IPO id'], ['funding_account', 'paid from (account name)'], ['demat_account', 'demat account name'], ['isin', 'ISIN'], ['symbol', 'symbol'], ['qty', 'shares allotted'], ['price', 'issue price'], ['allot_date', 'allotment date'], ['bank_date', 'bank line date'], ['bank_amount', 'bank line amount']].map(([k, p]) => `<input class="inp" data-f="${k}" placeholder="${p}" style="flex:0 0 150px">`).join('')}
        <button class="btn" data-ledger="ipo" data-write="0">Check IPO</button><button class="btn primary" data-ledger="ipo" data-write="1">Add IPO to the ledger</button></div>
      <div class="row wrapr" style="gap:6px" id="costF">${[['account', 'account name'], ['isin', 'ISIN'], ['cost_per_unit', 'cost per unit'], ['acquired', 'acquired on (date)'], ['basis', 'what the cost is based on']].map(([k, p]) => `<input class="inp" data-f="${k}" placeholder="${p}" style="flex:0 0 ${k === 'basis' ? 260 : 150}px">`).join('')}
        <button class="btn" data-ledger="opening-cost" data-write="0">Check cost</button><button class="btn primary" data-ledger="opening-cost" data-write="1">Add cost to the ledger</button></div>
      <div class="row wrapr" style="gap:6px" id="fdF">${[['id', 'deposit no. LAST 4 digits'], ['bank', 'bank, e.g. SBI'], ['principal', 'amount'], ['rate_pct', 'rate % a year'], ['start', 'start date'], ['maturity', 'maturity date'], ['maturity_amount', 'maturity amount (as the bank shows)'], ['instruction', 'on maturity (optional)']].map(([k, p]) => `<input class="inp" data-f="${k}" placeholder="${p}" style="flex:0 0 ${k === 'maturity_amount' ? 230 : 150}px">`).join('')}
        <button class="btn" data-fd="0">Check deposit</button><button class="btn primary" data-fd="1">Add deposit</button></div>
      <div id="ledgerOut" class="small"></div></section></div>`;
  document.querySelectorAll('[data-fd]').forEach((b) => { b.onclick = async () => {
    const fields = {}; $('fdF').querySelectorAll('[data-f]').forEach((i) => { fields[i.dataset.f] = i.value.trim(); });
    try { const r = await post('/api/fd', { fields, write: b.dataset.fd === '1' }); $('ledgerOut').innerHTML = `<b class="up">${r.written ? 'Deposit added; ' + r.deposits + ' on file.' : 'The terms reproduce the bank\'s maturity amount.'}</b>`; }
    catch (e) { $('ledgerOut').innerHTML = `<b class="down">${esc(e.message)}</b>`; }
  }; });
  if ($('prUse')) $('prUse').onclick = async () => { try { await post('/api/setup', { ...pr.answers, start: $('prStart').value }); load(true); } catch (e) { alert(e.message); } };
  if ($('applyAll')) $('applyAll').onclick = async () => {
    $('applyOut').textContent = 'Building the ledger from every document…';
    try {
      const r = await post('/api/inbox/apply-all', {});
      $('applyOut').innerHTML = r.waiting_for ? `<b class="warn">Still waiting for:</b> ${esc(r.waiting_for.join('; '))}` : r.why ? esc(r.why)
        : `<b class="${r.written ? 'up' : 'down'}">${r.written ? 'Written: ' + r.documents + ' document(s), ' + r.events + ' events.' : r.failed + ' check(s) failed: nothing written.'}</b><ul>${(r.checks || []).map((c) => `<li class="${c.ok ? 'up' : 'down'}">${c.ok ? 'PASS' : 'FAIL'} ${esc(c.name)}</li>`).join('')}</ul>`;
    } catch (e) { $('applyOut').innerHTML = `<b class="down">${esc(e.message)}</b>`; }
  };
  document.querySelectorAll('[data-ledger]').forEach((b) => { b.onclick = async () => {
    const box = b.closest('.row'); const fields = {}; box.querySelectorAll('[data-f]').forEach((i) => { fields[i.dataset.f] = i.value.trim(); });
    try {
      const r = await post('/api/ledger/' + b.dataset.ledger, { fields, write: b.dataset.write === '1' });
      $('ledgerOut').innerHTML = (r.waiting_for && r.waiting_for.length ? `<b class="warn">${r.kept ? 'Kept.' : 'Not checked yet.'}</b> Still waiting for: ${esc(r.waiting_for.join('; '))}` :
        `<b class="${r.failed ? 'down' : 'up'}">${r.written ? 'Written to the ledger. ' : ''}${r.failed ? r.failed + ' check(s) failed' : 'all checks pass'}</b><ul>${r.checks.map((c) => `<li class="${c.ok ? 'up' : 'down'}">${c.ok ? 'PASS' : 'FAIL'} ${esc(c.name)}${c.ok ? '' : ' · ' + esc(JSON.stringify(c.detail))}</li>`).join('')}</ul>`);
    } catch (e) { $('ledgerOut').innerHTML = `<b class="down">${esc(e.message)}</b>`; }
  }; });
  if (d.exists) return;
  const addBank = () => { const r = document.createElement('div'); r.className = 'row wrapr'; r.style.gap = '6px';
    r.innerHTML = '<input class="inp bn" placeholder="name, e.g. main" style="flex:0 0 120px"><input class="inp bb" placeholder="bank, e.g. SBI" style="flex:0 0 100px"><input class="inp bl" maxlength="4" placeholder="last 4" style="flex:0 0 70px"><input class="inp bp" placeholder="password name, e.g. SBI_PW" style="flex:0 0 190px">';
    $('suBanks').appendChild(r); };
  addBank(); $('suAddBank').onclick = addBank;
  $('suSave').onclick = async () => {
    const banks = [...document.querySelectorAll('#suBanks .row')].map((r) => ({ name: r.querySelector('.bn').value, bank: r.querySelector('.bb').value, last4: r.querySelector('.bl').value, password_name: r.querySelector('.bp').value })).filter((b) => b.name || b.last4);
    try { await post('/api/setup', { start: $('suStart').value, broker: { account: $('suBroker').value, cas_dp: $('suDp').value }, banks }); load(true); } catch (e) { alert(e.message); }
  };
}
/* S65: keys and passwords go to %USERPROFILE%\.pflab\secrets.toml; the form is write-only (a value is never shown or sent back) */
async function renderSecrets() {
  const el = $('secretsP'); if (!el) return;
  let d;
  try { d = await api('/api/secrets'); } catch (e) { el.innerHTML = `<span class="lbl">Keys and passwords</span><span class="small warn">${esc(e.message)}</span>`; return; }
  const rows = [];
  Object.entries(d.fields).forEach(([sec, fs]) => fs.forEach(([k, what]) => rows.push([sec, k, what])));
  d.passwords_asked.forEach((n) => rows.push(['passwords', n, 'Password for the statement file ' + n]));
  el.innerHTML = '<span class="lbl">Keys and passwords · typed here go to your secrets file, never shown again</span>' + rows.map(([sec, k, what]) => {
    const on = d.status[sec + '.' + k];
    return `<div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><span>${esc(what)}</span><span class="small ${on ? 'up' : 'muted'}">${on ? 'set' : 'not set'}</span></div>
      <input class="inp" type="password" autocomplete="off" placeholder="${on ? 'change…' : 'type it…'}" style="flex:0 0 150px" data-sec="${esc(sec)}" data-key="${esc(k)}"><button class="btn" data-savesec="${esc(sec)}|${esc(k)}">Save</button></div>`;
  }).join('');
  el.querySelectorAll('[data-savesec]').forEach((b) => { b.onclick = async () => {
    const [sec, k] = b.dataset.savesec.split('|');
    const inp = el.querySelector(`input[data-sec="${sec}"][data-key="${k}"]`);
    if (!inp.value.trim()) return;
    try { await post('/api/secrets', { section: sec, key: k, value: inp.value }); inp.value = ''; renderSecrets(); } catch (e) { alert(e.message); }
  }; });
}
/* S65: beta features (configs/features.toml): built and tested, not yet trusted with money; his switch wins over the channel's default */
async function renderFeatures(redraw) {
  const el = $('featuresP'); if (!el) return;
  let d;
  try { d = await api('/api/features'); } catch (e) { el.innerHTML = `<span class="lbl">Beta features</span><span class="small warn">${esc(e.message)}</span>`; return; }
  el.innerHTML = `<span class="lbl">Beta features · channel ${esc(d.channel)}</span>` + d.features.map((f) =>
    `<div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><span>${esc(f.title)}${f.beta ? ' <b class="warn">BETA</b>' : ''}</span><span class="small muted">${esc(f.about)}</span></div>
     <button class="toggle ${f.on ? 'on' : ''}" role="switch" aria-checked="${f.on}" aria-label="${esc(f.title)}" data-feat="${esc(f.name)}"><i></i></button></div>`).join('');
  el.querySelectorAll('[data-feat]').forEach((b) => { b.onclick = async () => {
    const f = d.features.find((x) => x.name === b.dataset.feat);
    if (!f.on && !confirm('Turn on ' + f.title + '? It is a beta feature.')) return;
    S.settings = await post('/api/settings', { features: { [f.name]: !f.on } }); redraw(); }; });
}
/* S61: the model slider. Each job's measured default is marked; a choice of yours wins until you take the default back. */
const MODEL_NAMES = { local: 'Local', cascade: 'Local, then Haiku', haiku: 'Haiku', sonnet: 'Sonnet', opus: 'Opus' };
async function renderModels(redraw) {
  const el = $('modelsP');
  if (!el) return;
  let rows;
  try { rows = await (await fetch('/api/models')).json(); } catch (e) { el.innerHTML = `<span class="lbl">Models</span><span class="small warn">${esc(e.message)}</span>`; return; }
  el.innerHTML = `<span class="lbl">Models: one per job</span><span class="tiny muted">Cheaper models where a pre-registered test found them as good (docs/STUDIES.md); every paid call is still priced and capped.</span>`
    + rows.map((r) => `<div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><span>${esc(r.job)}</span><span class="small muted">${esc(r.about)} · default ${esc(MODEL_NAMES[r.default] || r.default)} (${esc(r.basis)})</span></div>
      ${r.choices.map((c) => `<button class="btn ${r.chosen === c ? 'primary' : ''}" data-mjob="${esc(r.job)}" data-m="${esc(c)}">${esc(MODEL_NAMES[c] || c)}${c === r.default ? ' ·' : ''}</button>`).join('')}
      ${r.yours ? `<button class="btn" data-mjob="${esc(r.job)}" data-m="default">use the default</button>` : ''}</div>`).join('');
  el.querySelectorAll('[data-mjob]').forEach((b) => { b.onclick = async () => {
    S.settings = await post('/api/settings', { models: { [b.dataset.mjob]: b.dataset.m } }); redraw(); }; });
}
const BRAIN_MODES = [['off', 'Off'], ['economy', 'Economy'], ['normal', 'Normal']];
const TASK_CLS = { done: 'up', failed: 'down', running: 'warn', queued: 'muted', held: 'warn', needs_approval: 'warn', waiting: 'warn', retry: 'warn', dismissed: 'muted' };
const inr = (x) => '₹' + Number(x || 0).toLocaleString('en-IN', { maximumFractionDigits: x < 10 ? 2 : 0 });
function meter(used, cap) {
  const f = cap > 0 ? Math.min(1, used / cap) : 0;
  return `<div class="bar" style="height:6px"><i style="width:${(f * 100).toFixed(0)}%;${f > 0.8 ? 'background:var(--warn)' : ''}"></i></div>`;
}
/* The agents' controls (S59, now part of the World): order any agent, the board, spend against the limits, the brain's journal, suggestions, reminders.
   hqParts builds the panels from GET /api/hq; hqWire attaches their buttons. The World (world.js) shows them under its map. */
const priv = (s) => S.settings.privacy ? String(s || '').replace(/(Rs\.?|₹|INR)\s?[\d,]+(\.\d+)?(\s?(crore|lakh))?/gi, '₹•••••') : s;   // privacy mode in words too
function hqParts(d) {
  const sp = d.spend, b = d.brain;
  const opts = d.agents.map((a) => `<option value="${esc(a.name)}" ${(S.hqAgent || 'receptionist') === a.name ? 'selected' : ''}>${esc(a.title)}</option>`).join('');
  const tasks = d.tasks.map((t) => `<tr><td class="num">#${t.id}</td><td class="small">${esc(t.from === 'investor' ? 'you' : t.from)} → <b>${esc(t.title)}</b>${t.hops ? ` <span class="tiny muted">hop ${t.hops}</span>` : ''}${t.channel !== 'dashboard' ? ` <span class="tiny muted">${esc(t.channel)}</span>` : ''}</td>
    <td class="small" style="text-align:left;max-width:520px">${esc(t.text.slice(0, 160))}${t.result ? `<details><summary class="tiny muted">answer${t.route.length ? ' · ' + esc(t.route.join(' → ').slice(0, 120)) : ''}</summary><div class="small" style="white-space:pre-wrap">${esc(t.result)}</div></details>` : ''}</td>
    <td><span class="${TASK_CLS[t.status] || 'muted'}">${esc(t.status.replace('_', ' '))}</span></td><td class="num small">${t.cost ? inr(t.cost) : ''}</td><td class="small muted">${esc(String(t.created).slice(5, 16))}</td></tr>`).join('');
  const agents = d.agents.map((a) => `<tr><td><b>${esc(a.title)}</b><br><span class="tiny muted">${esc(a.name)}</span></td><td class="small" style="text-align:left">${esc(a.does)}<br><span class="tiny muted">reads ${esc(a.reads)} · writes ${esc(a.writes)}</span></td>
    <td class="small">${esc(a.model)}</td><td class="num">${a.month ? inr(a.month) : '—'}</td><td class="num">${a.today ? inr(a.today) : '—'}</td><td class="num">${a.calls || ''}${a.over_limit ? ` <span class="warn tiny">${a.over_limit} over limit</span>` : ''}</td>
    <td class="small muted">${a.last ? `#${a.last.id} ${esc(a.last.status)}` : ''}</td><td><button class="btn" style="min-height:28px;padding:4px 10px" data-hqpick="${esc(a.name)}">Order</button></td></tr>`).join('');
  const others = sp.others || [];
  const layers = sp.layers.map((l) => `<div class="stack" style="gap:4px"><div class="row" style="justify-content:space-between"><span class="small"><b>${esc(l.layer)}</b></span><span class="tiny muted">month ${inr(l.month)} of ${inr(l.share)} · today ${inr(l.today)} of ${inr(l.day_cap)}</span></div>${meter(l.month, l.share)}</div>`).join('');
  const journal = b.journal.map((p) => `<div style="background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px">
    <div class="row" style="justify-content:space-between"><span class="small"><b>${esc(p.trigger)}</b> · ${esc(p.role === 'gate' ? 'gatekeeper' : p.role)} · ${esc(p.model.replace('claude-', ''))}</span><span class="tiny muted">${esc(String(p.at).slice(5, 16))}${p.cost ? ' · ' + inr(p.cost) : ''} · <span class="${p.status === 'done' || p.status === 'wake' ? 'up' : p.status === 'skipped' ? 'muted' : 'warn'}">${esc(p.status)}</span></span></div>
    ${p.note ? `<span class="small" style="white-space:pre-wrap">${esc(priv(p.note))}</span>` : ''}
    ${p.decisions.length ? `<ul class="small" style="margin:0;padding-left:18px">${p.decisions.map((x) => `<li><b>${esc(x.action)}</b>${x.action === 'investigate' ? ` (${esc(x.agent)})` : ''} ${esc(x.subject)}: <span class="soft">${esc(priv(x.reason))}</span> <span class="tiny muted">${esc(x.priority)}</span></li>`).join('')}</ul>` : ''}
    ${p.tools && p.tools.length ? `<details><summary class="tiny muted">${p.tools.length} tool call(s): ${esc([...new Set(p.tools.map((t) => t.tool))].join(', ').slice(0, 140))}</summary><ul class="tiny soft" style="margin:0;padding-left:18px">${p.tools.map((t) => `<li>turn ${t.turn} <b>${esc(t.tool)}</b> <span class="${t.status === 'ran' ? 'muted' : 'warn'}">${esc(t.status)}</span> ${esc(JSON.stringify(t.args).slice(0, 120))}</li>`).join('')}</ul></details>` : ''}
    ${p.events.length ? `<details><summary class="tiny muted">${p.events.length} event(s) it saw</summary><ul class="tiny soft" style="margin:0;padding-left:18px">${p.events.map((e) => `<li>${esc(e)}</li>`).join('')}</ul></details>` : ''}
    ${p.error ? `<span class="tiny warn">${esc(p.error)}</span>` : ''}
    ${p.status === 'done' ? `<div class="row" style="gap:6px"><span class="tiny muted">Did this matter?</span>${[[true, 'Mattered'], [false, 'Did not']].map(([v, n]) => `<button class="btn ${p.mattered === v ? 'primary' : ''}" style="min-height:24px;padding:2px 8px;font-size:12px" data-hqmark="${p.id}" data-v="${v}">${n}</button>`).join('')}</div>` : ''}</div>`).join('');
  const sc = Object.entries(b.scorecard.models).map(([m, s]) => `<div class="small">${esc(m.replace('claude-', ''))}: ${s.hits} of ${s.n} came true${s.n >= 20 && s.brier !== null ? ` · Brier ${s.brier.toFixed(3)}` : ' (scores from 20)'}${s.brier_base !== undefined && s.n >= 20 ? ` · base rate ${s.brier_base.toFixed(3)}` : ''}</div>`).join('');
  const preds = d.predictions.map((p) => `<tr><td class="small" style="text-align:left">${esc(p.claim)}</td><td class="small">${esc(p.model.replace('claude-', ''))}</td><td class="num">${(p.confidence * 100).toFixed(0)}%</td><td class="num">${p.base_rate === null ? '—' : (p.base_rate * 100).toFixed(0) + '%'}</td><td class="small">${esc(p.due)}</td><td class="small">${p.outcome === null ? (p.detail ? esc(p.detail) : '<span class="muted">open</span>') : `<span class="${p.outcome ? 'up' : 'down'}">${p.outcome ? 'came true' : 'did not'}</span> <span class="tiny muted">${esc(p.detail || '')}</span>`}</td></tr>`).join('');
  const orderP = `<div class="panel" style="display:flex;flex-direction:column;gap:10px">
        <span class="lbl">Order an agent</span>
        <div class="row wrapr" style="gap:6px"><label for="hqA" style="position:absolute;left:-9999px">Agent</label><select id="hqA" class="inp" style="flex:0 1 auto">${opts}</select>
          <label for="hqT" style="position:absolute;left:-9999px">What to do</label><input id="hqT" class="inp" style="flex:1 1 300px" placeholder="what to do (the receptionist routes plain words; on Telegram: /calc, /sim, /web …)"><button class="btn primary" id="hqGo">Send</button></div>
        ${S.hqMsg ? `<span class="small warn">${esc(S.hqMsg)}</span>` : ''}
        <span class="tiny muted">Answers appear on the board below; orders from Telegram are answered there too. Agents hand work to each other up to 3 hops; a longer chain goes to the brain.</span>
      </div>`;
  const boardP = `<section class="panel" style="display:flex;flex-direction:column;gap:6px"><span class="lbl">The board</span>
        ${tasks ? `<div class="scroll"><table><thead><tr><th>#</th><th>Who</th><th>Task and answer</th><th>Status</th><th>Cost</th><th>When</th></tr></thead><tbody>${tasks}</tbody></table></div>` : '<span class="small muted">No tasks yet. Order an agent above, or message the bot.</span>'}
      </section>`;
  const agentsP = `<section class="panel" style="display:flex;flex-direction:column;gap:6px"><span class="lbl">The agents</span>
        <div class="scroll"><table><thead><tr><th>Agent</th><th>Does</th><th>Model</th><th>This month</th><th>Today</th><th>Calls</th><th>Last task</th><th></th></tr></thead><tbody>${agents}</tbody></table></div>
        ${others.length ? `<span class="tiny muted">Also spent by the system's own paths: ${others.map((a) => `${esc(a.agent)} ${inr(a.month)}`).join(' · ')}</span>` : ''}
      </section>`;
  const spendP = `<div class="panel" style="display:flex;flex-direction:column;gap:8px">
        <span class="lbl">API spend this month</span>
        <div class="row" style="justify-content:space-between"><span><b>${inr(sp.month)}</b> <span class="small muted">of ${inr(sp.cap)}</span></span><span class="small muted">${inr(sp.left)} left</span></div>
        ${meter(sp.month, sp.cap)}${layers}
        <span class="tiny muted">Every call is priced before it is made; one over a limit is not made (shown as "over limit").</span>
      </div>`;
  const brainP = `<div class="panel" style="display:flex;flex-direction:column;gap:8px">
        <div class="row" style="justify-content:space-between"><span class="lbl">The brain</span><span class="tiny ${b.shadow ? 'warn' : 'up'}">${b.shadow ? `shadow mode${b.shadow_since ? ' since ' + esc(b.shadow_since) : ''}: it journals, acts on nothing` : 'acting: asks and tells you, orders research (capped a day); never trades'}</span></div>
        <div class="row wrapr" style="gap:6px">${BRAIN_MODES.map(([k, n]) => `<button class="btn ${b.mode === k ? 'primary' : ''}" data-hqbrain="${k}">${n}</button>`).join('')}<button class="btn" id="hqThink">Think now</button></div>
        <span class="tiny muted">Wakes on something new and material (a cheap check first), a morning review on trading days, a reflection on Saturdays. Opus looks with tools (at most 8 turns, each priced first); Sonnet does the same as its cheaper rival.</span>
        ${sc || '<span class="small muted">No prediction scored yet.</span>'}
        <div class="stack" style="gap:8px">${journal || '<span class="small muted">No pass yet.</span>'}</div>
      </div>`;
  const predsP = d.predictions.length ? `<div class="panel"><span class="lbl">Predictions</span><div class="scroll"><table><thead><tr><th>Claim</th><th>By</th><th>Conf.</th><th>Base</th><th>Due</th><th>Outcome</th></tr></thead><tbody>${preds}</tbody></table></div></div>` : '';
  const rec = d.suggestion_record || { kinds: {}, luck: {}, open: 0 };
  const sugs = (d.suggestions || []).map((x) => `<div style="border-top:1px solid var(--line);padding-top:6px;display:flex;flex-direction:column;gap:4px">
    <div class="row" style="justify-content:space-between"><span class="small"><b>${esc(x.kind)}</b> ${esc(x.symbol || '')} <span class="tiny muted">${esc(x.model.replace('claude-', ''))} · ${esc(String(x.at).slice(5, 16))} · scored in ${x.horizon} days</span></span>
      <span class="tiny ${x.quality === 'sound' ? 'up' : 'warn'}" title="${esc(x.quality_why || '')}">${esc(x.quality || '')}</span></div>
    <span class="small">${esc(priv(x.text))}</span>${x.reasoning ? `<details><summary class="tiny muted">why</summary><span class="small soft">${esc(priv(x.reasoning))}</span></details>` : ''}
    <div class="row wrapr" style="gap:6px">${x.outcome ? `<span class="small ${x.outcome === 'good' ? 'up' : x.outcome === 'bad' ? 'down' : 'muted'}">${esc(x.outcome)}</span>${x.outcome_json && x.outcome_json.excess_pct !== undefined ? ` <span class="tiny muted">${x.outcome_json.stock_pct >= 0 ? '+' : ''}${x.outcome_json.stock_pct}% vs Nifty 500 ${x.outcome_json.nifty500_pct >= 0 ? '+' : ''}${x.outcome_json.nifty500_pct}%</span>` : ''}` : ''}
      ${[['taken', 'Taken'], ['declined', 'Declined']].map(([v, n]) => `<button class="btn ${x.answer === v ? 'primary' : ''}" style="min-height:24px;padding:2px 8px;font-size:12px" data-hqsug="${x.id}" data-v="${v}">${n}</button>`).join('')}
      ${x.answer_source === 'portfolio' ? '<span class="tiny muted">seen in your portfolio</span>' : ''}</div></div>`).join('');
  const sugP = `<div class="panel" style="display:flex;flex-direction:column;gap:6px"><span class="lbl">Suggestions</span>
        <span class="tiny muted">Every suggestion is scored at its horizon on what the stock did against the Nifty 500, taken or declined (declined ones on paper). Under 20 a count, not a rate.</span>
        ${Object.keys(rec.kinds).length ? Object.entries(rec.kinds).map(([k, v]) => `<div class="small">${esc(k)}: ${esc(v.rate)} good <span class="tiny muted">(${v.good} of ${v.n})</span></div>`).join('') + `<span class="tiny muted">sound but went badly: ${rec.luck.sound_bad || 0} · weak or unsound but went well: ${(rec.luck.unsound_good || 0) + (rec.luck.weak_good || 0)} · open ${rec.open}</span>` : `<span class="small muted">Nothing scored yet${rec.open ? ` (${rec.open} open)` : ''}.</span>`}
        ${sugs || '<span class="small muted">No suggestion yet.</span>'}</div>`;
  const followP = `<div class="panel" style="display:flex;flex-direction:column;gap:6px"><span class="lbl">Since your decisions</span>
        ${d.followups.length ? d.followups.map((f) => `<div class="small"><b>${esc(f.subject || '—')}</b> <span class="tiny muted">${esc(f.at)}</span>: ${esc(f.text.slice(0, 140))} <span class="${f.since.change_pct >= 0 ? 'up' : 'down'}">${f.since.change_pct >= 0 ? '+' : ''}${f.since.change_pct.toFixed(1)}%</span> <span class="tiny muted">to ${esc(f.since.to)}</span></div>`).join('') : '<span class="small muted">No decision about a company in the last 120 days (/decide SYMBOL: text on Telegram).</span>'}
        ${d.other_decisions ? `<span class="tiny muted">${d.other_decisions} other decision(s) kept (not about a company).</span>` : ''}
      </div>`;
  const readersP = `<div class="panel" style="display:flex;flex-direction:column;gap:6px"><span class="lbl">Readers (latest)</span>
        ${d.readings.length ? d.readings.map((r) => `<div class="small"><span class="${r.material === 'yes' ? 'warn' : 'muted'}">${esc(r.material)}</span> ${esc(r.kind)}: ${esc((r.summary || r.title || '').slice(0, 200))}${r.dropped ? ` <span class="tiny muted">${r.dropped} figure(s) dropped</span>` : ''} <span class="tiny muted">· ${esc(r.where || '')}</span></div>`).join('') : '<span class="small muted">Nothing read yet.</span>'}
      </div>`;
  const remP = `<div class="panel" style="display:flex;flex-direction:column;gap:6px"><span class="lbl">Reminders and the drop folder</span>
        ${d.reminders.length ? d.reminders.map((r) => `<div class="small row" style="justify-content:space-between"><span>${esc(r.due.slice(5))} · ${esc(r.text)}</span><button class="btn" style="min-height:26px;padding:2px 8px" data-hqrem="${r.id}">Cancel</button></div>`).join('') : '<span class="small muted">No reminder (say "remind me to … tomorrow at 9").</span>'}
        <span class="tiny muted">Drop folder: ${esc(d.drop.folder)} · ${d.drop.on ? 'watched' : 'not watched (Settings)'}</span>
      </div>`;
  const running = d.tasks.filter((t) => t.status === 'running').length, waiting = d.tasks.filter((t) => t.status === 'queued').length;
  return { orderP, boardP, agentsP, spendP, brainP, predsP, sugP, followP, readersP, remP, running, waiting };
}
/* The buttons inside the agents' panels. `again` re-reads /api/hq and redraws whatever shows them. */
function hqWire(root, again) {
  const on = (id, ev, fn) => { const el = root.querySelector('#' + id); if (el) el[ev] = fn; };
  on('hqA', 'onchange', () => { S.hqAgent = root.querySelector('#hqA').value; });
  const send = async () => { const text = root.querySelector('#hqT').value.trim(); S.hqMsg = '';
    try { await post('/api/hq/order', { agent: root.querySelector('#hqA').value, text }); root.querySelector('#hqT').value = ''; } catch (e) { S.hqMsg = e.message; }
    again(); };
  on('hqGo', 'onclick', send);
  on('hqT', 'onkeydown', (e) => { if (e.key === 'Enter') send(); });
  root.querySelectorAll('[data-hqpick]').forEach((b) => { b.onclick = () => { S.hqAgent = b.dataset.hqpick; const a = root.querySelector('#hqA');
    if (a) { a.value = S.hqAgent; root.querySelector('#hqT').focus(); } }; });
  root.querySelectorAll('[data-hqbrain]').forEach((x) => { x.onclick = async () => { S.settings = await post('/api/settings', { brain: x.dataset.hqbrain }); again(); }; });
  root.querySelectorAll('[data-hqmark]').forEach((x) => { x.onclick = async () => { await post(`/api/hq/passes/${x.dataset.hqmark}/mark`, { mattered: x.dataset.v === 'true' }); again(); }; });
  root.querySelectorAll('[data-hqsug]').forEach((x) => { x.onclick = async () => { await post(`/api/hq/suggestions/${x.dataset.hqsug}/answer`, { answer: x.dataset.v }); again(); }; });
  root.querySelectorAll('[data-hqrem]').forEach((x) => { x.onclick = async () => { await post(`/api/hq/reminders/${x.dataset.hqrem}/cancel`); again(); }; });
  on('hqThink', 'onclick', async () => { try { await post('/api/hq/order', { agent: 'brain', text: '' }); } catch (e) { S.hqMsg = e.message; } again(); });
}
/* ---------- AI centre (54b) ---------- */
function chipStyle(step) {
  const s = step.toLowerCase();
  if (s.includes('opus')) return 'background:#2A1730;border-color:#6B2F6E;color:#F0ABFC';
  if (s.includes('local') || s.includes('pc') || s.includes('guard') || s.includes('egress')) return 'background:#0F2A1F;border-color:#1F5A40;color:#86EFAC';
  if (s.includes('error') || s.includes('blocked')) return 'background:#2A1215;border-color:#7A2E2E;color:#FCA5A5';
  return 'background:#0F1A2B;border-color:#1E3A5F;color:#93C5FD';
}
/* source tags ([F:fact], [S1], [W2], [D3], [inf]) as small muted markers: the claim stays readable, the source visible */
const tags = (html) => html.replace(/\[(F:[^\]\s]+|S\d+|W\d+|D\d+|inf)\]/g, (m, t) =>
  `<sup class="tiny muted" title="${t.startsWith('F:') ? 'fact from the system: ' + t.slice(2) : t === 'inf' ? 'inference' : 'source ' + t}">${t.startsWith('F:') ? 'f' : t}</sup>`);
async function openReport(id) {
  const d = await api('/api/doc?id=' + encodeURIComponent(id));
  const o = document.createElement('div');
  o.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:50;padding:20px';
  o.innerHTML = `<div class="panel" style="max-width:860px;width:100%;max-height:85vh;overflow:auto;display:flex;flex-direction:column;gap:10px">
    <div class="row" style="justify-content:space-between"><b>${esc(d.title)}</b><button class="btn" id="closeRep">Close</button></div>
    <span class="tiny muted">${esc(d.source)} · ${esc(d.published)}</span>
    <div style="white-space:pre-wrap;line-height:1.6">${esc(d.text)}</div>
    ${d.documents && d.documents.length ? `<span class="lbl">Documents</span><div class="small muted" style="white-space:pre-wrap">${esc(d.documents.join('\n'))}</div>` : ''}</div>`;
  document.body.appendChild(o);
  o.onclick = (e) => { if (e.target === o) o.remove(); };
  $('closeRep').onclick = () => o.remove();
}

/* ---------- Watch list (54c) ---------- */
const VERDICT = { 'IN ZONE': ['var(--up)', '#1F5A40'], 'ABOVE ZONE': ['var(--soft)', 'var(--line)'], RICH: ['var(--warn)', '#5C4A1E'], NO: ['var(--down)', '#7A2E2E'], 'NO DATA': ['var(--muted)', 'var(--line)'] };
const vbadge = (v) => { const c = VERDICT[v] || VERDICT['NO DATA']; return `<span class="tiny" style="font-weight:700;padding:2px 8px;border-radius:6px;color:${c[0]};border:1px solid ${c[1]};white-space:nowrap">${esc(v || '…')}</span>`; };
function zoneBar(z) {
  if (!z.price) return '';
  const lo = Math.min(z.low, z.bottom), hi = Math.max(z.high, z.price), span = (hi - lo) || 1;
  const pos = (x) => ((x - lo) / span * 100).toFixed(1) + '%';
  return `<div style="position:relative;height:50px;margin:6px 0">
    <div style="position:absolute;left:0;right:0;top:20px;height:10px;border-radius:999px;background:var(--line2)"></div>
    <div style="position:absolute;left:${pos(z.bottom)};width:${((z.top - z.bottom) / span * 100).toFixed(1)}%;top:20px;height:10px;border-radius:999px;background:#1F5A40"></div>
    <div style="position:absolute;left:${pos(z.price)};top:12px;width:3px;height:26px;background:var(--text);border-radius:2px"></div>
    <span class="num tiny" style="position:absolute;left:${pos(z.price)};top:0">now ${num(z.price)}</span>
    <span class="num tiny up" style="position:absolute;left:${pos(z.bottom)};top:36px">zone ${num(z.bottom, 0)}-${num(z.top, 0)}</span></div>
    <div class="row tiny muted" style="justify-content:space-between"><span class="num">${num(lo, 0)}</span><span>1-year range</span><span class="num">${num(hi, 0)}</span></div>`;
}
function renderWatch(d) {
  const rows = d.rows || [];
  const sel = rows.find((r) => r.isin === S.wsel) || rows[0];
  if (sel) S.wsel = sel.isin;
  const z = sel ? sel.zone : {};
  const card = (t, v, x) => `<div style="background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:6px;flex:1 1 220px"><span class="lbl">${t}</span><span class="num" style="font-size:16px;font-weight:600">${v}</span><span class="small soft" style="line-height:1.45">${x}</span></div>`;
  $('screen').innerHTML = `
  <section class="panel" style="display:flex;flex-direction:column;gap:8px">
    <div class="row wrapr">
      <label for="addSym" class="lbl" style="white-space:nowrap">Add a name</label>
      <input id="addSym" class="inp" style="max-width:220px" placeholder="NSE symbol, e.g. ABCLTD">
      <button class="btn primary" id="addBtn">Add and study it</button>
      <label for="ideaIn" class="lbl" style="white-space:nowrap;margin-left:12px">Check my idea</label>
      <input id="ideaIn" class="inp" placeholder="e.g. buy VOLTMOTORS for ₹50,000?">
      <button class="btn" id="ideaBtn">Check</button>
    </div>
    <div id="ideaOut" class="small soft" style="line-height:1.55"></div>
    <span class="tiny muted">${d.computing ? 'Studying the list now (guards, results, 100,000 paths per name): about a minute.' : `Computed ${esc(String(d.at).replace('T', ' ').slice(0, 16))} with ${num(d.paths, 0)} paths per name · refreshed every 6 hours`} <button class="btn" id="wRefresh" style="padding:3px 10px;min-height:26px">Refresh now</button></span>
  </section>
  <div class="cols">
    <section class="panel" style="flex:1 1 320px;display:flex;flex-direction:column;gap:6px">
      <span class="lbl">Names · ${rows.length}</span>
      ${rows.map((r) => `<button class="btn" data-w="${esc(r.isin)}" style="display:flex;align-items:center;gap:10px;text-align:left;background:var(--panel2);border-color:${sel && r.isin === sel.isin ? 'var(--accent)' : 'var(--line)'}">
        ${vbadge(r.zone.verdict)}<span style="flex:1;min-width:0;display:flex;flex-direction:column"><b>${esc(r.symbol)}</b><span class="tiny muted">${r.on_list ? 'on the list' : 'held'} · guard ${esc(r.guard)}</span></span>
        <span class="num small">${r.zone.price ? num(r.zone.price) : '—'}</span></button>`).join('') || '<span class="small muted">No names yet.</span>'}
    </section>
    ${sel ? `<section class="panel" style="flex:3 1 720px;display:flex;flex-direction:column;gap:12px">
      <div class="row wrapr" style="justify-content:space-between">
        <div style="display:flex;flex-direction:column"><span style="font-size:20px;font-weight:700">${esc(sel.symbol)}</span><span class="small muted">${esc(sel.name || '')}</span></div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">${vbadge(z.verdict)}<span class="small">${esc(z.headline || '')}</span></div>
      </div>
      ${zoneBar(z)}
      ${z.price ? `<div class="cols" style="gap:10px">
        ${card('Where it has been', `${num(z.low, 0)}-${num(z.high, 0)}`, `1-year range; 20th / 40th percentile ${num(z.p20, 0)} / ${num(z.p40, 0)}; ${pct(z.share_below_p40, 0)} of sessions at or below ${num(z.p40, 0)}`)}
        ${card('What the price assumes', z.implied_growth !== null && z.implied_growth !== undefined ? pct(z.implied_growth) + ' a year' : '—', z.implied_growth !== null && z.implied_growth !== undefined ? `earnings growth for 10 years at ${num(z.price)} (12% return asked); its last year: ${z.growth !== null && z.growth !== undefined ? pct(z.growth) : 'not on record'}${z.fair ? `; at that growth the price would be ${num(z.fair, 0)}` : ''}` : 'no positive earnings on record: the range alone sets the zone')}
        ${z.price <= z.top ? card('Price against the zone', 'already inside', `${num(z.bottom, 0)}-${num(z.top, 0)}; chance of touching ${num(z.bottom, 0)} within ${z.horizon} sessions: ${esc(z.touch_bottom.text)}`)
          : card(`Chance of touching ${num(z.top, 0)}`, esc(z.touch_top.text), `within ${z.horizon} sessions, from its own past daily moves (direction removed); ${num(z.bottom, 0)}: ${esc(z.touch_bottom.text)}`)}
      </div>` : ''}
      <div class="cols" style="gap:14px">
        <div style="flex:1 1 320px;display:flex;flex-direction:column;gap:6px"><span class="lbl">Guard and what it watches</span>
          <div class="small">Guard <b>${esc(sel.guard)}</b>${sel.reasons.length ? ': ' + esc(sel.reasons.slice(0, 3).join('; ')) : ''}</div>
          <div class="small soft">${sel.flags_7d} research flag(s) in 7 days · ${sel.quarters} quarters of results on record</div>
          ${sel.results.map((x) => `<div class="small soft">${esc(x)}</div>`).join('')}</div>
        <div style="flex:1 1 300px;display:flex;flex-direction:column;gap:8px"><span class="lbl">Asks you</span>
          ${sel.asks.length ? sel.asks.map((a) => `<div class="note"><span>${esc(a)}</span></div>`).join('') : '<span class="small muted">Nothing needed.</span>'}
          <div class="row wrapr">${z.top ? `<button class="btn" id="alertZone">Alert me in the zone (≤ ${num(z.top, 0)})</button>` : ''}${sel.on_list ? `<button class="btn" id="rmName">Remove from list</button>` : ''}</div>
          <div class="row"><select id="wKind" class="inp" style="max-width:110px"><option value="below">below</option><option value="above">above</option></select><input id="wLevel" class="inp" style="max-width:140px" placeholder="price"><button class="btn" id="wAdd">Add watch</button></div></div>
      </div>
      <span class="tiny muted" style="line-height:1.5;border-top:1px solid var(--line);padding-top:8px">The zone is a calculation, an ESTIMATE: where the price has been, what growth the price assumes, and the chance of touching a level given its own past moves. It is not a forecast of direction or a tested signal; the decision is yours.</span>
    </section>` : ''}
  </div>
  <section class="panel" style="display:flex;flex-direction:column;gap:6px">
    <span class="lbl">Your price watches</span>
    ${d.watches.map((w) => `<div class="row" style="justify-content:space-between;border-bottom:1px solid var(--line2);padding:6px 0"><span><b>${esc(w.symbol)}</b> ${esc(w.kind)} <span class="num">${num(w.level)}</span> <span class="tiny muted">${esc(w.note || '')}</span></span><span class="tiny muted">${w.hits ? `hit ${w.hits}× · last ${esc(w.last_hit)}` : 'not hit yet'} <button class="btn" style="padding:3px 10px;min-height:26px" data-unwatch="${w.id}">Remove</button></span></div>`).join('') || '<span class="small muted">None. A watch sends a message and a notification when the price crosses it (live in market hours, else at the close); never an order.</span>'}
  </section>`;
  document.querySelectorAll('[data-w]').forEach((b) => { b.onclick = () => { S.wsel = b.dataset.w; renderWatch(d); }; });
  $('addBtn').onclick = async () => { const s = $('addSym').value.trim(); if (!s) return; try { const r = await post('/api/watch/add', { symbol: s }); $('ideaOut').textContent = `Added ${r.symbol} (guard ${r.guard}). Its zone appears after the refresh (about a minute).`; } catch (e) { $('ideaOut').textContent = 'Not added: ' + e.message; } };
  $('ideaBtn').onclick = async () => { const t = $('ideaIn').value.trim(); if (!t) return; const r = await post('/api/idea', { text: t }); $('ideaOut').innerHTML = (r.verdict ? `<b class="${r.verdict === 'yes' ? 'up' : r.verdict === 'no' ? 'down' : 'warn'}">${esc(r.verdict.toUpperCase())}.</b> ` : '') + esc(r.answer); };
  $('wRefresh').onclick = async () => { await post('/api/watch/refresh'); $('wRefresh').textContent = 'Refreshing…'; };
  if ($('alertZone')) $('alertZone').onclick = async () => { await post('/api/watches', { isin: sel.isin, symbol: sel.symbol, kind: 'below', level: z.top, note: 'zone top' }); load(true); };
  if ($('rmName')) $('rmName').onclick = async () => { if (!confirm(`Remove ${sel.symbol} from your list?`)) return; await post('/api/watch/remove', { symbol: sel.symbol }); load(true); };
  if ($('wAdd')) $('wAdd').onclick = async () => { const lv = parseFloat($('wLevel').value.replace(/,/g, '')); if (!lv) return; await post('/api/watches', { isin: sel.isin, symbol: sel.symbol, kind: $('wKind').value, level: lv }); load(true); };
  document.querySelectorAll('[data-unwatch]').forEach((b) => { b.onclick = () => api(`/api/watches/${b.dataset.unwatch}`, { method: 'DELETE' }).then(() => load(true)); });
}

/* ---------- Research and plans (54c) ---------- */
function techChart(c) {
  if (!c || !c.close || c.close.length < 2) return '';
  const all = c.close.concat(c.ma50.filter((x) => x !== null), c.ma200.filter((x) => x !== null));
  const mn = Math.min(...all), mx = Math.max(...all), W = 640, H = 180, n = c.close.length;
  const line = (a) => a.map((v, i) => v === null ? null : `${(i * W / (n - 1)).toFixed(1)},${(H - 6 - (v - mn) / ((mx - mn) || 1) * (H - 12)).toFixed(1)}`).filter(Boolean).join(' ');
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="Price with 50 and 200 session averages">
    <polyline points="${line(c.close)}" fill="none" stroke="var(--text)" stroke-width="1.5"></polyline>
    <polyline points="${line(c.ma50)}" fill="none" stroke="#60A5FA" stroke-width="1.3"></polyline>
    <polyline points="${line(c.ma200)}" fill="none" stroke="#F5B942" stroke-width="1.3" stroke-dasharray="4 3"></polyline></svg>
    <div class="row wrapr tiny soft" style="gap:14px"><span>— price</span><span style="color:#60A5FA">— 50-session average</span><span style="color:#F5B942">- - 200-session average</span><span class="muted">${esc(c.dates[0])} to ${esc(c.dates[c.dates.length - 1])}</span></div>`;
}
/* S64: a line chart from {dates, lines:[{name,y}], guides:[{y,label}]}: the maths block's plots (tools only, no model) */
function lineSvg(pl, H = 130) {
  if (!pl || pl.error || !pl.lines || !pl.dates || pl.dates.length < 2) return '<span class="tiny muted">no series</span>';
  const W = 640, ys = pl.lines.flatMap((l) => l.y).concat((pl.guides || []).map((g) => g.y));
  const mn = Math.min(...ys), mx = Math.max(...ys), n = pl.dates.length;
  const Y = (v) => (H - 8 - (v - mn) / ((mx - mn) || 1) * (H - 16)).toFixed(1);
  const cols = ['var(--text)', '#60A5FA', '#F5B942'];
  const guides = (pl.guides || []).map((g) => `<line x1="0" x2="${W}" y1="${Y(g.y)}" y2="${Y(g.y)}" stroke="var(--line)" stroke-dasharray="4 3"></line><text x="${W - 4}" y="${Number(Y(g.y)) - 3}" text-anchor="end" font-size="10" fill="var(--muted)">${esc(g.label)}</text>`).join('');
  const lines = pl.lines.map((l, k) => `<polyline points="${l.y.map((v, i) => `${(i * W / (n - 1)).toFixed(1)},${Y(v)}`).join(' ')}" fill="none" stroke="${cols[k % 3]}" stroke-width="1.5"></polyline>`).join('');
  return `<div class="tiny soft">${esc(pl.title)}</div><svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="${esc(pl.title)}">${guides}${lines}</svg><div class="tiny muted">${esc(pl.dates[0])} to ${esc(pl.dates[n - 1])}</div>`;
}
function mathsBlock(m) {
  const c = m.capm || {}, p = (m.process || {}).price || {}, sp = (m.process || {}).spread_to_sector || {}, mv = m.moves_with || {};
  return `<div class="small soft"><b>CAPM.</b> ${esc(c.sentence || c.error || 'no fit')}${c.expected_return_pct != null ? ` · CAPM expected return ${c.expected_return_pct}% a year <span class="tiny muted">(${esc(c.expected_return_label || 'estimate')})</span>` : ''}</div>
    <div class="small soft"><b>Process.</b> Its price ${esc(p.sentence || 'n/a')}${sp.sentence ? `; its spread to the ${esc((sp.sector_index || '').replace('SECTOR_', '').replace('_TRI', ''))} index ${esc(sp.sentence)}` : ''}. <span class="tiny muted">A description, never a signal.</span></div>
    <div class="small soft"><b>Moves with.</b> ${(mv.peers || []).length ? (mv.peers || []).slice(0, 6).map((x) => `${esc(x.peer)} (corr ${x.corr_5y === null ? '—' : x.corr_5y.toFixed(2)}${x.cointegrated_after_bh ? ', cointegrated' : ''}${x.stable_share !== null ? `, held ${(x.stable_share * 100).toFixed(0)}% of windows` : ''})`).join(' · ') : esc(mv.note || 'no peers in the last weekly run')} <span class="tiny muted">${esc(mv.label || '')}${mv.run ? ' · ' + esc(mv.run.text) : ''}</span></div>
    <div class="cols" style="gap:16px">${['price_fan', 'rolling_beta', 'spread_z'].filter((k) => (m.plots || {})[k]).map((k) => `<div style="flex:1 1 300px">${lineSvg(m.plots[k])}</div>`).join('')}</div>`;
}
async function loadMaths(isin) {
  const box = $('mathsBox');
  if (!box || !isin) return;
  try { const m = await api('/api/maths?isin=' + encodeURIComponent(isin)); if ($('mathsBox')) $('mathsBox').innerHTML = mathsBlock(m); }
  catch (e) { if ($('mathsBox')) $('mathsBox').innerHTML = '<span class="small muted">Maths not available: ' + esc(e.message) + '</span>'; }
}
const rng = (r) => r ? `${num(r.low)}–${num(r.high)}` : '<span class="muted">at NAV</span>';
const maskRs = (t) => S.settings.privacy ? String(t).replace(/(Rs|₹)\s?[\d,]+(\.\d+)?( (mn|cr|lakh))?/g, '$1 •••••') : String(t);
function ringCol(x) {
  return `<div><span class="num">${x.names}</span> names · largest <span class="num">${pct(x.largest)}</span> of the stock part · <span class="num">${x.sectors}</span> sectors known${x.fall ? ` · fall beyond 35% in a year: <span class="num">${esc(x.fall.text)}</span>` : ''}</div>`;
}
function planCard(p) {
  const r = p.ring || {};
  return `<div style="background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:flex;flex-direction:column;gap:10px">
    <div class="row wrapr" style="justify-content:space-between"><span><b>${esc(p.source)}</b> <span class="small muted">· due ${esc(p.due)} · </span><span class="money">${rs(p.amount)}</span>${p.estimate ? ' <span class="tiny muted">(estimate: payout net of TDS)</span>' : ''}</span>
      <span class="tiny muted">version of ${esc(p.made)} · checked ${esc(p.checked)} · priced at today's prices</span></div>
    ${p.changes ? `<span class="tiny soft">Since the last version: ${esc(p.changes.join('; '))}</span>` : ''}
    <div class="row wrapr small" style="gap:8px">${p.buckets.map((b) => `<span class="chip">${esc(bname(b.bucket))} <span class="money">${rs(b.rupees)}</span></span>`).join('')}${p.unspent > 1 ? `<span class="chip muted">unspent <span class="money">${rs(p.unspent)}</span></span>` : ''}</div>
    ${p.how.length ? `<div class="scroll"><table><thead><tr><th>Fund / ETF</th><th>Units</th><th>Amount</th><th>Buy around</th><th>Zone</th></tr></thead><tbody>
      ${p.how.map((h) => `<tr><td>${esc(h.name)}</td><td class="num">${num(h.units, h.units % 1 ? 3 : 0)}</td><td class="num money">${rs(h.cost)}</td><td class="num">${rng(h.range)}</td><td>${h.range ? vbadge(h.verdict) : ''}</td></tr>`).join('')}</tbody></table></div>` : ''}
    ${p.stocks.length ? `<div class="scroll"><table style="min-width:760px"><thead><tr><th>Stock</th><th>Qty</th><th>Price</th><th>Amount</th><th>Buy around</th><th>Zone</th><th style="text-align:left">Why · ticket</th></tr></thead><tbody>
      ${p.stocks.map((b) => `<tr><td><b>${esc(b.symbol)}</b></td><td class="num">${b.qty}</td><td class="num">${num(b.price)}</td><td class="num money">${rs(b.cost)}</td><td class="num">${rng(b.range)}</td><td>${vbadge(b.verdict)}</td>
        <td style="text-align:left" class="small soft">${esc(maskRs(b.why))}<br>${b.tickets.map((x) => esc(maskRs(x))).join('<br>')}</td></tr>`).join('')}</tbody></table></div>` : '<span class="small muted">No direct-stock buys in this plan.</span>'}
    ${r.shown ? `<div style="border:1px dashed var(--btn-line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px">
      <span class="lbl">The outer ring · an idea, not a rule</span><span class="small soft">${esc(r.why)}</span>
      ${r.possible ? `<span class="small">${r.buys.map((b) => `<b>${esc(b.symbol)}</b> ${b.qty} around ${rng(b.range)} ${vbadge(b.verdict)}`).join(' &nbsp; ')}</span>
        <div class="cols small" style="gap:14px"><div style="flex:1 1 260px"><span class="lbl">The plan above</span>${ringCol(r.plan)}</div><div style="flex:1 1 260px"><span class="lbl">The ring instead</span>${ringCol(r.ring)}</div></div>
        <span class="tiny muted">Fall chances: your stocks alone (their own prices; the equal-weight Nifty 500 before a name listed), the same random draws for both.</span>` : ''}</div>` : ''}
    ${p.skipped && p.skipped.length ? `<span class="tiny muted">Skipped by the guards: ${esc(p.skipped.join(', '))}</span>` : ''}
    ${S.settings.privacy ? '' : `<details><summary class="small" style="cursor:pointer">The bucket plan behind it</summary><pre class="small soft" style="white-space:pre-wrap;font-family:var(--mono)">${esc(p.bucket_text)}</pre></details>`}
  </div>`;
}
function renderResearch(d) {
  const t = d.technicals, st = d.plan_status || {};
  $('screen').innerHTML = `
  <div class="cols">
    <section class="panel" style="flex:3 1 640px;display:flex;flex-direction:column;gap:10px">
      <div class="row wrapr" style="justify-content:space-between"><span class="lbl">Ready plans for the next money</span><span class="tiny muted">${st.at ? 'kept current; last refresh ' + esc(String(st.at).replace('T', ' ').slice(0, 16)) : 'being prepared…'} · proposals, not orders: you place every trade</span></div>
      ${st.error ? `<div class="small warn">${esc(st.error)}</div>` : ''}
      ${d.plans.map(planCard).join('') || '<span class="small muted">No plan yet: no FD tranche or monthly amount is set, or the first refresh is running.</span>'}
      <span class="tiny muted">The plans are the tested advisor (S45). "Buy around" and "Zone" describe the price (the buy zone); they do not change the plan until a pre-registered study shows that waiting for the zone beats buying at once.</span>
      <div class="cols" style="gap:10px">
        <div style="flex:1 1 300px;background:#1A1215;border:1px solid #7A2E2E;border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px">
          <span class="lbl down">Not buying now: the guards say no</span>
          ${d.hold_off.filter((h) => h.kind === 'guard').map((h) => `<div class="small"><b>${esc(h.symbol)}</b> ${esc(h.why)}</div>`).join('') || '<span class="small muted">None.</span>'}
        </div>
        <div style="flex:1 1 300px;background:var(--warn-bg);border:1px solid var(--warn-line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px">
          <span class="lbl warn">Above its zone or rich · results due (information; buying at once is what the study supports)</span>
          ${d.hold_off.filter((h) => h.kind !== 'guard').map((h) => `<div class="small"><b>${esc(h.symbol)}</b> ${esc(h.why)}</div>`).join('') || '<span class="small muted">None.</span>'}
        </div>
      </div>
      <div class="row wrapr"><label for="amt" class="small muted">Re-plan with another amount (₹)</label><input id="amt" class="inp" style="max-width:180px" placeholder="e.g. 200000"><button class="btn" id="replan">Re-plan</button>
        <label for="idea2" class="small muted" style="margin-left:10px">Check my idea</label><input id="idea2" class="inp" placeholder="e.g. add ₹50,000 to DELTAIT?"><button class="btn" id="idea2Btn">Check</button></div>
      <div id="idea2Out" class="small soft"></div>
    </section>
    <section class="stack" style="flex:2 1 380px">
      <div class="panel" style="display:flex;flex-direction:column;gap:6px"><span class="lbl">Results: range before, surprise after</span>
        ${d.results.map((x) => `<div class="small soft" style="padding:4px 0;border-bottom:1px solid var(--line2)">${esc(x)}</div>`).join('') || '<span class="small muted">No ranges yet (8 consecutive quarters needed).</span>'}</div>
      <div class="panel" style="display:flex;flex-direction:column;gap:6px"><span class="lbl">Analyst notes (Opus)</span>
        ${d.notes.map((n) => `<div class="row" style="justify-content:space-between;gap:8px"><span class="small" style="min-width:0">${esc(n.title)}<br><span class="tiny muted">${esc(n.at)}</span></span><button class="btn" style="padding:3px 10px;min-height:26px" data-report="${esc(n.id)}">Open</button></div>`).join('') || '<span class="small muted">None yet.</span>'}</div>
    </section>
  </div>
  <div class="cols">
    <section class="panel" style="flex:2 1 520px;display:flex;flex-direction:column;gap:6px"><span class="lbl">What changed · 7 days</span>
      ${d.flags.map((f) => `<div class="item"><span class="num tiny muted" style="width:92px;flex:0 0 auto">${esc(f.at)}</span><span class="tiny" style="padding:2px 8px;border-radius:999px;border:1px solid var(--line);flex:0 0 auto">${esc(f.kind)}</span><span class="small" style="min-width:0"><b>${esc(f.symbol || '')}</b> ${esc(f.detail)}</span></div>`).join('') || '<span class="small muted">Nothing new.</span>'}</section>
    <section class="panel" style="flex:2 1 520px;display:flex;flex-direction:column;gap:8px">
      <div class="row wrapr" style="justify-content:space-between"><span class="lbl">Technicals · a description, not a signal</span>
        <select id="techSel" class="inp" style="max-width:220px">${d.names.map((n) => `<option value="${esc(n.isin)}" ${n.isin === d.selected ? 'selected' : ''}>${esc(n.symbol)}</option>`).join('')}</select></div>
      ${t ? techChart(t.chart) + `<div class="cols small" style="gap:16px">${[['Close', num(t.close)], ['RSI 14', t.rsi14 === null ? '—' : num(t.rsi14, 1)], ['ATR 14', t.atr14 === null ? '—' : num(t.atr14)], ['52 weeks', `${num(t.low52, 0)}-${num(t.high52, 0)}`], ['Volume vs 20-day', t.volume_ratio ? num(t.volume_ratio, 2) + '×' : '—']].map(([k, v]) => `<div><span class="lbl">${k}</span><br><span class="num">${v}</span></div>`).join('')}</div>` : '<span class="small muted">No price history in the bhavcopy for this name.</span>'}
    </section>
  </div>
  <section class="panel" style="display:flex;flex-direction:column;gap:8px"><span class="lbl">Business at a glance · filed results, holders, peers, concalls (our own data, descriptions)</span>
    <div id="bizBox"><span class="small muted">Gathering…</span></div></section>
  <section class="panel" style="display:flex;flex-direction:column;gap:8px"><span class="lbl">The maths · beta, process, who it moves with (tools only, descriptions)</span>
    <div id="mathsBox"><span class="small muted">Working it out…</span></div></section>
  <section class="panel" style="display:flex;flex-direction:column;gap:8px"><span class="lbl">Scoreboard · your book, the system's suggestions on paper, equal-weight Nifty 500, Nifty 500 (the same money on the same days)</span>
    <div id="twinBox"><span class="small muted">Loading…</span></div></section>
  <section class="panel" style="display:flex;flex-direction:column;gap:8px"><span class="lbl">US sleeve · dollar trades and money sent abroad (entered by hand until a statement parser exists)</span>
    <div id="usBox"><span class="small muted">Loading…</span></div></section>
  <section class="panel" style="display:flex;flex-direction:column;gap:8px"><span class="lbl">Scans · information, not evidence until tested</span>
    <div id="scanBox"><span class="small muted">Loading…</span></div></section>`;
  loadMaths(d.selected);
  loadBusiness(d.selected);
  loadTwin();
  loadUs();
  loadScans();
  $('replan').onclick = async () => { const a = parseFloat($('amt').value.replace(/,/g, '')); if (!a) return; await post('/api/plan', { amount: a }); $('replan').textContent = 'Planning…'; };
  $('idea2Btn').onclick = async () => { const t2 = $('idea2').value.trim(); if (!t2) return; const r = await post('/api/idea', { text: t2 }); $('idea2Out').innerHTML = (r.verdict ? `<b class="${r.verdict === 'yes' ? 'up' : r.verdict === 'no' ? 'down' : 'warn'}">${esc(r.verdict.toUpperCase())}.</b> ` : '') + esc(r.answer); };
  $('techSel').onchange = () => { S.rsel = $('techSel').value; load(true); };
  document.querySelectorAll('[data-report]').forEach((b) => { b.onclick = () => openReport(b.dataset.report); });
}

/* ---------- inbox and files (54d) ---------- */
const STEP_COL = { done: 'var(--up)', failed: 'var(--down)', todo: 'var(--muted)' };
async function upload(file, opts = {}) {
  const h = { 'X-Filename': encodeURIComponent(file.name || 'pasted.png') };
  if (opts.kind) h['X-Kind'] = opts.kind;
  if (opts.account) h['X-Account'] = opts.account;
  if (opts.chat) h['X-Chat'] = String(opts.chat);
  const r = await fetch('/api/inbox/upload', { method: 'POST', headers: h, body: file });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText); }
  return r.json();
}
async function uploadAll(files, opts) {
  const out = [];
  for (const f of files) {
    try { const r = await upload(f, opts); out.push(r.duplicate ? `${f.name}: already in the inbox` : `${f.name}: received`); }
    catch (e) { out.push(`${f.name}: ${e.message}`); }
  }
  S.inboxMsg = out.join(' · ');
  load(true);
}
function pastedFiles(e) {
  const items = [...(e.clipboardData ? e.clipboardData.items : [])].filter((i) => i.kind === 'file');
  return items.map((i, n) => { const f = i.getAsFile(); return f.name && f.name !== 'image.png' ? f : new File([f], `screenshot-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}${n ? '-' + n : ''}.png`, { type: f.type }); });
}
function detailText(d) {
  /* a check's detail: text, or a list of differences (each a row with fields): readable either way */
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((x) => (x && typeof x === 'object') ? Object.entries(x).map(([k, v]) => `${k} ${v}`).join(', ') : String(x)).join('; ');
  if (d && typeof d === 'object') return Object.entries(d).map(([k, v]) => `${k} ${v}`).join(', ');
  return String(d ?? '');
}
function itemCard(it, privacy) {
  const steps = it.steps.map((x, i, a) => `<span class="row" style="gap:4px"><span class="tiny" style="color:${STEP_COL[x.state]}">${x.state === 'done' ? '✓' : x.state === 'failed' ? '✗' : '○'} ${esc(x.name)}</span>${i < a.length - 1 ? '<span class="muted tiny">→</span>' : ''}</span>`).join('');
  const r = it.result || {};
  let body = '';
  if (r.error) body += `<span class="small down">${esc(r.error)}</span>`;
  if (r.note && !(r.checks || []).length) body += `<span class="small soft">${esc(r.note)}</span>`;
  if (it.status === 'in the ledger') body += `<span class="small"><span class="up">in your record</span>${r.events !== undefined ? ` · ${r.events} entries` : ''}${r.failed ? ` · <span class="warn">${r.failed} difference(s) with your files: see Needs from you</span>` : ''}</span>`;
  else if ((r.checks || []).length) body += `<details ${r.failed ? 'open' : ''}><summary class="small">${it.status === 'in the ledger' ? '<span class="up">in your record</span> · ' : ''}${r.failed ? `<span class="warn">${r.failed} difference(s) with your files</span>` : `<span class="up">all ${r.checks.length} checks pass</span>`}${r.events !== undefined ? ` · ${r.events} entries` : ''}</summary>
    <div class="small" style="display:flex;flex-direction:column;gap:3px;margin-top:6px">${r.checks.map((c) => `<span><span class="${c.ok ? 'up' : 'down'}">${c.ok ? 'PASS' : 'FAIL'}</span> ${esc(c.name)}${c.ok || privacy ? '' : ` <span class="muted">${esc(detailText(c.detail).slice(0, 300))}</span>`}</span>`).join('')}
    ${(r.notes || []).length ? `<span class="muted">${r.notes.length} note(s)${privacy ? '' : ': ' + esc(r.notes.slice(0, 4).join(' · '))}</span>` : ''}</div></details>`;
  if (it.text) body += `<details><summary class="small">text read on this PC (${it.text.split('\n').length} lines)</summary><div class="small soft" style="white-space:pre-wrap;margin-top:6px;max-height:220px;overflow:auto">${esc(it.text)}</div></details>`;
  if (r.summary) body += `<div class="small" style="background:var(--panel2);border-radius:8px;padding:8px 10px;line-height:1.5">${tags(esc(r.summary))}${r.checked ? '' : ' <span class="tiny muted">(no checked summary)</span>'}</div>`;
  if (r.facts !== undefined) body += `<span class="small soft">${r.sheets} sheet(s) · ${r.facts} figure(s) · ${r.companies} company link(s)${(r.kinds || []).length ? ' · ' + esc(r.kinds.join(', ')) : ''}</span>`;
  const acts = [];
  if (it.status === 'ready') acts.push(`<button class="btn primary" data-iact="apply" data-iid="${it.id}">Add to the ledger</button>`);
  if (it.kind === 'screenshot' && it.text) acts.push(`<button class="btn" data-iact="read" data-iid="${it.id}">Read it</button>`, `<button class="btn" data-iact="research" data-iid="${it.id}">Research it</button>`);
  if (it.status !== 'in the ledger') acts.push(`<button class="btn" data-idel="${it.id}">Remove</button>`);
  const col = it.status === 'failed' || it.status === 'checks failed' ? 'var(--down)' : it.status === 'working' ? 'var(--warn)' : 'var(--up)';
  return `<div style="background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:7px">
    <div class="row" style="justify-content:space-between;gap:8px"><span style="min-width:0"><b style="word-break:break-all">${esc(it.name)}</b> <span class="tiny muted">${esc(it.label)}${it.account ? ' · ' + esc(it.account) : ''}${it.chat_id ? ' · from a chat' : ''}${r.existed ? ' · this file was already in place' : ''}</span></span>
      <span class="tiny" style="color:${col};white-space:nowrap">${esc(it.status)}</span></div>
    <div class="row wrapr" style="gap:4px">${steps}</div>${body}
    <div class="row wrapr" style="gap:6px;justify-content:space-between"><span class="tiny muted">${esc(String(it.created).slice(0, 16))}${it.cleaned ? ' · image deleted, text kept' : ''}</span><span class="row" style="gap:6px">${acts.join('')}</span></div></div>`;
}
function renderInbox(d) {
  /* (2026-10-30) a file already read into the record or the graph leaves the main list: what is left is what still needs a look */
  const isDone = (it) => ['in the ledger', 'in the graph', 'in the store'].includes(it.status) || (it.kind === 'screenshot' && it.status === 'read');
  const active = (d.items || []).filter((it) => !isDone(it)), done = (d.items || []).filter(isDone);
  const privacy = !!S.settings.privacy;
  const kinds = [['', 'Recognise it'], ['tradebook', 'Console tradebook'], ['contract_note', 'Contract notes'], ['funds_ledger', 'Console funds ledger'], ['cas', 'Depository CAS'], ['bank', 'Bank statement'], ['screenshot', 'Screenshot'], ['market', 'Market-data export'], ['other', 'Other']];
  $('screen').innerHTML = `
  <div class="cols">
    <section class="stack" style="flex:2 1 620px">
      <div class="panel" id="drop" tabindex="0" style="display:flex;flex-direction:column;gap:10px;border-style:dashed;align-items:center;text-align:center;padding:26px 16px">
        <b style="font-size:15px">Drop files here, paste a screenshot (Ctrl+V), or pick files</b>
        <span class="small soft" style="max-width:640px;line-height:1.55">Everything is read on this PC. Statements are checked by a dry-run rebuild of the ledger before anything is written; screenshots are read by Windows' own OCR and the image is deleted after ${d.image_days} days (the text stays); market exports and other files go into the knowledge graph.</span>
        <div class="row wrapr" style="gap:8px;justify-content:center">
          <label class="small" for="ikind">This is</label><select id="ikind" class="inp" style="width:auto">${kinds.map(([v, l]) => `<option value="${v}" ${S.ikind === v ? 'selected' : ''}>${l}</option>`).join('')}</select>
          <span id="iaccWrap" style="display:${S.ikind === 'bank' ? 'inline-flex' : 'none'};gap:6px;align-items:center"><label class="small" for="iacc">account</label><select id="iacc" class="inp" style="width:auto">${d.accounts.map((a) => `<option ${S.iacc === a ? 'selected' : ''}>${esc(a)}</option>`).join('') || '<option value="">no bank account in sources.toml</option>'}</select></span>
          <input type="file" id="ifile" multiple style="display:none"><button class="btn primary" id="ipick">Pick files</button></div>
        ${S.inboxMsg ? `<span class="small warn">${esc(S.inboxMsg)}</span>` : ''}
      </div>
      <div class="panel" style="display:flex;flex-direction:column;gap:10px">
        <div class="row" style="justify-content:space-between"><span class="lbl">Files</span><span class="small muted">${active.length} need a look or are being read · ${done.length} done</span></div>
        ${active.map((it) => itemCard(it, privacy)).join('') || '<span class="small muted">Nothing waiting: every file is read.</span>'}
        ${done.length ? `<details><summary class="small">Done (${done.length}): read into your record or the knowledge graph. Nothing to do; kept for the record and its rebuilds.</summary>
          <div style="display:flex;flex-direction:column;gap:6px;margin-top:8px">${done.map((it) => `<div class="small row" style="justify-content:space-between;gap:8px;border-bottom:1px solid var(--line2);padding:3px 0">
            <span>${esc(it.name)} <span class="muted">· ${esc(it.label)}</span></span><span class="tiny up">${esc(it.status === 'read' ? 'read' : it.status)}</span></div>`).join('')}</div></details>` : ''}
      </div>
    </section>
    <section class="stack" style="flex:1 1 360px">
      <div class="panel" style="display:flex;flex-direction:column;gap:10px">
        <div class="row" style="justify-content:space-between"><span class="lbl">Needs from you</span><span class="small warn">${d.needs.length} open</span></div>
        ${d.needs.map((q) => `<div style="background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:8px">
          <span style="font-size:13px;line-height:1.45">${esc(q.text)}</span><span class="tiny muted">${esc(q.agent)} · ${esc(q.at)}</span>
          <div class="row"><input class="inp" id="na${q.id}" placeholder="Your answer"><button class="btn" data-nanswer="${q.id}">Answer</button></div></div>`).join('') || '<span class="small muted">Nothing needed.</span>'}
      </div>
      <div class="panel small soft" style="display:flex;flex-direction:column;gap:6px;line-height:1.55">
        <span class="lbl">What goes where</span>
        <span><b>Statements</b> (Console tradebook, contract notes, funds ledger, CAS, bank): kept in the project's new/ folder and listed in sources.app.toml beside your sources.toml; your file is never rewritten. A fresh download may overlap an older one: repeated trades are counted once.</span>
        <span><b>Screenshots</b> (IPO allotments, GPay, news): the text is kept, the image goes after ${d.image_days} days. "Research it" sends only the text, and only past the egress check.</span>
        <span><b>Tijori / Screener exports</b>: inbox/market, which the analyst may read.</span>
      </div>
      <div class="panel" style="display:flex;flex-direction:column;gap:6px"><span class="lbl">Cleanup log</span>
        ${(d.cleanup || []).map((c) => `<div class="small soft" style="border-bottom:1px solid var(--line2);padding:4px 0"><span class="tiny muted">${esc(String(c.at || '').replace('T', ' ').slice(0, 16))} · ${esc(c.what)}</span><br>${c.names_merged} names merged (${c.into_companies} into your companies) · ${c.copies_marked} syndicated copies set aside · ${c.notes_ended} older notes ended${c.asked ? ` · ${c.asked} asked of you` : ''}</div>`).join('') || '<span class="small muted">Nothing cleaned yet: the knowledge-graph job runs it at night.</span>'}
        <span class="tiny muted">Exact matches are cleaned automatically; anything unsure about your companies is asked under "Needs from you". Nothing is deleted: a merged name is kept as an alias, a copy points at its original.</span>
      </div>
    </section>
  </div>`;
  const kind = $('ikind'); kind.onchange = () => { S.ikind = kind.value; $('iaccWrap').style.display = kind.value === 'bank' ? 'inline-flex' : 'none'; };
  const acc = $('iacc'); if (acc) acc.onchange = () => { S.iacc = acc.value; };
  const opts = () => ({ kind: S.ikind || '', account: S.ikind === 'bank' ? ($('iacc').value || '') : '' });
  $('ipick').onclick = () => $('ifile').click();
  $('ifile').onchange = () => uploadAll([...$('ifile').files], opts());
  const drop = $('drop');
  drop.ondragover = (e) => { e.preventDefault(); drop.style.borderColor = 'var(--accent)'; };
  drop.ondragleave = () => { drop.style.borderColor = ''; };
  drop.ondrop = (e) => { e.preventDefault(); drop.style.borderColor = ''; uploadAll([...e.dataTransfer.files], opts()); };
  document.querySelectorAll('[data-iact]').forEach((b) => { b.onclick = async () => {
    if (b.dataset.iact === 'apply' && !confirm('Rebuild your record with this document now? (It also happens by itself within minutes.) What does not match is named in Needs from you.')) return;
    b.disabled = true;
    try { const r = await post(`/api/inbox/${b.dataset.iid}/${b.dataset.iact}`); if (b.dataset.iact === 'research') { if (r.skipped) { alert(r.why); return; } location.hash = '#/assistant'; return; } }
    catch (e) { S.inboxMsg = e.message; }
    load(true); }; });
  document.querySelectorAll('[data-idel]').forEach((b) => { b.onclick = async () => { if (!confirm('Remove this file from the inbox and delete it?')) return; try { await api(`/api/inbox/${b.dataset.idel}`, { method: 'DELETE' }); } catch (e) { S.inboxMsg = e.message; } load(true); }; });
  document.querySelectorAll('[data-nanswer]').forEach((b) => { b.onclick = async () => { const v = $('na' + b.dataset.nanswer).value.trim(); if (!v) return; await post(`/api/questions/${b.dataset.nanswer}/answer`, { text: v }); load(true); }; });
}
document.addEventListener('paste', (e) => {
  const files = pastedFiles(e);
  if (!files.length) return;
  if (S.screen === 'inbox') { e.preventDefault(); uploadAll(files, { kind: S.ikind === 'bank' ? '' : (S.ikind || '') }); }
  else if (S.screen === 'assistant') { e.preventDefault(); attachToAssistant(files); }
});

/* ---------- Simulations (54e) ---------- */
const MIX_COLORS = { current: BUCKET_COLORS[0], target: BUCKET_COLORS[1], 'what-if': BUCKET_COLORS[2] };
const MIX_NAMES = { current: 'Your mix today', target: 'Your target mix', 'what-if': 'What-if mix' };
const ASSET_NAMES = { mine: 'Your stocks (today\'s names and weights)', stocks: 'Equal-weight Nifty 500', n500: 'Nifty 500 index fund', mom50: 'Momentum 50 fund', gold: 'Gold', debt: 'Debt (none held)', cash: 'Cash' };
function xMoney(mult, inv) { return S.settings.privacy || !inv ? `${num(mult, 2)}×` : `${rs(mult * inv)} (${num(mult, 2)}×)`; }
function fanChart(f, color, inv) {
  const W = 760, H = 290, L = 46, Rt = 12, T = 12, B = 30, M = f.months;
  const lo = Math.min(1, ...f.p5) * 0.95, hi = Math.max(...f.p95) * 1.03;
  const x = (m) => L + (m) / M * (W - L - Rt), y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const pts = (a) => a.map((v, i) => `${x(i + 1).toFixed(1)},${y(v).toFixed(1)}`);
  const band = (a, b) => `M${x(0)},${y(1)} L${pts(a).join(' L')} L${pts(b).reverse().join(' L')} Z`;
  const ticks = []; const step = (hi - lo) > 2 ? 0.5 : (hi - lo) > 1 ? 0.25 : 0.1;
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto" role="img" aria-label="Fan chart of the value of one rupee">
    ${ticks.map((v) => `<line x1="${L}" x2="${W - Rt}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line2)" stroke-width="1"></line><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${v.toFixed(2)}×</text>`).join('')}
    <line x1="${L}" x2="${W - Rt}" y1="${y(1)}" y2="${y(1)}" stroke="var(--muted)" stroke-dasharray="3 4" stroke-width="1"></line>
    ${Array.from({ length: M / 12 + 1 }, (_, k) => `<text x="${x(12 * k)}" y="${H - 8}" text-anchor="middle" font-size="11" fill="var(--muted)">${k ? k + 'y' : 'now'}</text>`).join('')}
    <path d="${band(f.p5, f.p95)}" fill="${color}" opacity=".16"></path>
    <path d="${band(f.p25, f.p75)}" fill="${color}" opacity=".32"></path>
    <polyline points="${x(0)},${y(1)} ${pts(f.p50).join(' ')}" fill="none" stroke="${color}" stroke-width="2"></polyline>
    <text x="${x(M) - 4}" y="${y(f.p50[M - 1]) - 8}" text-anchor="end" font-size="11" fill="var(--text)">median ${f.p50[M - 1].toFixed(2)}×</text>
    <line id="fanX" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="var(--muted)" stroke-width="1" visibility="hidden"></line>
    <rect id="fanHit" x="${L}" y="${T}" width="${W - L - Rt}" height="${H - T - B}" fill="transparent"></rect></svg>`;
}
function scatter(fr, mixes) {
  const W = 520, H = 300, L = 46, Rt = 12, T = 12, B = 34;
  const vx = fr.map((p) => p.vol), ry = fr.map((p) => p.ret);
  const x0 = 0, x1 = Math.max(...vx) * 1.05, y0 = Math.min(0, ...ry), y1 = Math.max(...ry) * 1.08;
  const x = (v) => L + (v - x0) / (x1 - x0) * (W - L - Rt), y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  const marks = Object.entries(mixes).map(([k, m], i) => `<circle cx="${x(m.point.vol)}" cy="${y(m.point.ret)}" r="6" fill="${MIX_COLORS[k]}" stroke="var(--panel)" stroke-width="2"><title>${esc(MIX_NAMES[k])}: ${pct(m.point.ret)} a year, volatility ${pct(m.point.vol)}, worst fall ${pct(m.point.worst_fall_any_day)}</title></circle><text x="${x(m.point.vol) + 9}" y="${y(m.point.ret) + 4 + (i - 1) * 13}" font-size="11" fill="var(--text)">${esc(MIX_NAMES[k])}</text>`).join('');
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto" role="img" aria-label="Return against volatility for random mixes">
    ${[0, 0.05, 0.1, 0.15, 0.2].filter((v) => v <= y1).map((v) => `<line x1="${L}" x2="${W - Rt}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line2)"></line><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${(v * 100).toFixed(0)}%</text>`).join('')}
    ${[0, 0.05, 0.1, 0.15, 0.2, 0.25].filter((v) => v <= x1).map((v) => `<text x="${x(v)}" y="${H - 16}" text-anchor="middle" font-size="11" fill="var(--muted)">${(v * 100).toFixed(0)}%</text>`).join('')}
    <text x="${(L + W) / 2}" y="${H - 2}" text-anchor="middle" font-size="11" fill="var(--muted)">volatility a year →</text>
    ${fr.map((p) => `<circle cx="${x(p.vol).toFixed(1)}" cy="${y(p.ret).toFixed(1)}" r="2.2" fill="${p.worst_fall_any_day <= -0.35 ? 'var(--down)' : 'var(--muted)'}" opacity=".45"></circle>`).join('')}
    ${marks}</svg>`;
}
function renderSims(d) {
  const r = d.result, privacy = !!S.settings.privacy;
  S.simMix = S.simMix || 'current';
  const wi = S.whatif || { mine: 30, stocks: 10, n500: 20, mom50: 0, gold: 15, debt: 0, cash: 25 };
  const tot = Object.values(wi).reduce((a, b) => a + b, 0) || 1;
  const runBox = `<div class="panel" style="display:flex;flex-direction:column;gap:10px">
    <span class="lbl">Run</span>
    <div class="row wrapr" style="gap:8px"><label class="small" for="simPaths">Paths</label><select id="simPaths" class="inp" style="flex:0 0 auto">${d.paths_choices.map((p) => `<option value="${p}" ${(S.simPaths || 10000) === p ? 'selected' : ''}>${groupIN(p)}</option>`).join('')}</select>
      <label class="small" for="simYears">Years</label><select id="simYears" class="inp" style="flex:0 0 auto">${[1, 2, 3, 4, 5].map((y) => `<option ${(S.simYears || 5) === y ? 'selected' : ''}>${y}</option>`).join('')}</select>
      <button class="btn primary" id="simRun" ${d.running ? 'disabled' : ''}>${d.running ? 'Running…' : 'Run now'}</button></div>
    <span class="lbl" style="margin-top:4px">What-if mix (shares are scaled to 100%)</span>
    ${Object.keys(wi).map((a) => `<div class="row small" style="gap:8px"><label for="wi_${a}" style="flex:0 0 210px">${esc(ASSET_NAMES[a])}</label><input type="range" id="wi_${a}" min="0" max="100" step="5" value="${wi[a]}" style="flex:1"><span class="num" style="flex:0 0 44px;text-align:right">${(wi[a] / tot * 100).toFixed(0)}%</span></div>`).join('')}
    <span class="tiny muted">${d.nightly_paths ? `Nightly: ${groupIN(d.nightly_paths)} paths after ${d.sims_hour}:00 (${esc(PRESET_NAMES[d.preset])} preset)` : `No nightly run under the ${esc(PRESET_NAMES[d.preset])} preset`}. 100,000 paths take about half a minute.</span>
    ${d.error ? `<span class="small down">${esc(d.error)}</span>` : ''}</div>`;
  if (!r) { $('screen').innerHTML = `<div class="cols"><section class="stack" style="flex:2 1 600px"><div class="soon"><b>No simulation yet</b><span class="soft">Run one, or it runs tonight under the Full and Marathon presets.</span></div></section><section class="stack" style="flex:1 1 380px">${runBox}</section></div>`; bindSims(d); return; }
  const mixes = r.mixes, keys = Object.keys(mixes); if (!mixes[S.simMix]) S.simMix = keys[0];
  const m = mixes[S.simMix], f = m.fan, ys = Object.keys(f.years);
  const cols = keys.map((k) => `<th style="color:var(--text)"><span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${MIX_COLORS[k]};margin-right:6px"></span>${esc(MIX_NAMES[k])}</th>`).join('');
  const row = (name, fn) => `<tr><td>${name}</td>${keys.map((k) => `<td class="num">${fn(mixes[k])}</td>`).join('')}</tr>`;
  const eps = mixes[keys[0]].stress.episodes;
  $('screen').innerHTML = `<div class="cols">
    <section class="stack" style="flex:2 1 640px">
      <div class="panel" style="display:flex;flex-direction:column;gap:10px">
        <div class="row wrapr" style="justify-content:space-between"><span class="lbl">The value of 1 rupee, ${groupIN(r.paths)} paths over ${r.years} years</span>
          <div class="row" style="gap:6px">${keys.map((k) => `<button class="btn ${S.simMix === k ? 'primary' : ''}" data-mix="${k}">${esc(MIX_NAMES[k])}</button>`).join('')}</div></div>
        <div style="position:relative">${fanChart(f, MIX_COLORS[S.simMix], r.invested)}<div id="fanTip" class="small" style="position:absolute;top:8px;left:60px;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:6px 10px;pointer-events:none;display:none"></div></div>
        <div class="row wrapr tiny muted" style="gap:14px"><span>dark band: half the paths (p25 to p75)</span><span>light band: 90 of 100 paths (p5 to p95)</span><span>line: the median</span><span>dashed: what you put in</span></div>
        ${r.mine ? `<span class="small soft">Your stocks: ${r.mine.names} names at today's weights; ${pct(r.mine.own_share, 0)} of the history is their own prices, the rest (before a stock listed) is the equal-weight Nifty 500.</span>` : ''}
        <span class="small soft">Mix: ${Object.entries(m.mix).filter(([, v]) => v > 0.004).map(([a, v]) => `${esc(ASSET_NAMES[a])} ${pct(v, 0)}`).join(' · ')}</span>
      </div>
      <div class="panel" style="display:flex;flex-direction:column;gap:8px"><span class="lbl">Side by side</span>
        <div class="scroll"><table><thead><tr><th></th>${cols}</tr></thead><tbody>
        ${row('Chance of a fall beyond 35% on any day', (x) => `${esc(x.fall.text)}`)}
        ${ys.map((y) => row(`Median after ${y} year${y === '1' ? '' : 's'}`, (x) => `${xMoney(x.fan.years[y].p50, r.invested)} <span class="tiny muted">± ${num(x.fan.years[y].se_p50, 3)}</span>`)).join('')}
        ${row(`Bad case after ${ys[ys.length - 1]} years (p5)`, (x) => xMoney(x.fan.years[ys[ys.length - 1]].p5, r.invested))}
        ${row(`Good case after ${ys[ys.length - 1]} years (p95)`, (x) => xMoney(x.fan.years[ys[ys.length - 1]].p95, r.invested))}
        ${row('Chance of less than you put in at the end', (x) => pct(x.fan.p_loss_at_end))}
        ${row('Median growth a year', (x) => pct(x.fan.median_cagr))}
        </tbody></table></div>
        <span class="tiny muted">± is the standard error from 10 batches of paths; a fall chance is shown only when its error is at most 0.5 points (the small-numbers rule). History: ${esc(r.history)}. Run ${esc(r.at.slice(0, 16).replace('T', ' '))}. An estimate from one history, not a forecast.</span>
      </div>
      <div class="panel" style="display:flex;flex-direction:column;gap:8px"><span class="lbl">Stress tests: each mix through dated episodes</span>
        <div class="scroll"><table><thead><tr><th>Episode</th>${cols}</tr></thead><tbody>
        ${eps.map((e, i) => `<tr><td>${esc(e.name)} <span class="tiny muted">${esc(e.from)} to ${esc(e.to)}</span></td>${keys.map((k) => { const x = mixes[k].stress.episodes[i]; return `<td class="num">${x.covered ? `<span class="${ud(x.return)}">${pct(x.return, 1, true)}</span> <span class="tiny muted">worst ${pct(x.worst_fall)}</span>` : '<span class="muted">before the history</span>'}</td>`; }).join('')}</tr>`).join('')}
        ${row('Its own worst fall in the whole history', (x) => `<span class="down">${pct(x.stress.worst.fall)}</span> <span class="tiny muted">${esc(x.stress.worst.peak)} → ${esc(x.stress.worst.trough)}, back ${esc(x.stress.worst.recovered || 'not yet')}</span>`)}
        </tbody></table></div></div>
    </section>
    <section class="stack" style="flex:1 1 380px">${runBox}
      <div class="panel" style="display:flex;flex-direction:column;gap:8px"><span class="lbl">The frontier</span>
        ${scatter(r.frontier, mixes)}
        <div class="row wrapr tiny muted" style="gap:12px"><span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--muted)"></span> a random mix of the five assets</span><span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--down)"></span> one that fell more than 35% on some day</span></div>
        <span class="tiny muted">Return and volatility a year over the history; up and to the left is better. ${r.frontier.length} of the mixes drawn.</span></div>
      <div class="panel" style="display:flex;flex-direction:column;gap:8px"><span class="lbl">Scenarios on your holdings · oil, the rupee, a US crash</span>
        <div id="scenBox"><span class="small muted">Working it out…</span></div></div>
    </section></div>`;
  bindSims(d, f, r);
  loadScenarios();
}
/* S64: business at a glance (hq/business.py): 12 quarters, holders, peers ranked, concall filings; what is missing is said */
function bizBlock(b) {
  const L = (x) => Array.isArray(x) ? x.map((y) => `<div class="tiny">${esc(y)}</div>`).join('') || '<span class="tiny muted">none</span>' : `<span class="tiny muted">${esc(x)}</span>`;
  const q = b.results_12_quarters || [], p = b.peers || {}, h = b.holders || {};
  const n = (v, d = 1) => v === null || v === undefined ? '—' : Number(v).toLocaleString('en-IN', { maximumFractionDigits: d });
  return `<div class="scroll"><table><thead><tr><th>Quarter</th><th>Revenue Cr</th><th>Net profit Cr</th><th>Net margin %</th><th>Revenue vs year ago %</th><th>EPS</th></tr></thead><tbody>
    ${q.map((r) => `<tr><td>${esc(r.quarter)}</td><td class="num">${n(r.revenue_cr, 0)}</td><td class="num">${n(r.net_profit_cr, 0)}</td><td class="num">${n(r.net_margin_pct)}</td><td class="num">${n(r.revenue_yoy_pct)}</td><td class="num">${n(r.eps, 2)}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">No filed quarters on record.</td></tr>'}</tbody></table></div>
    <span class="tiny muted">Quarters with gaps in the filings are shown as they are; nothing is filled in. ${esc(b.segment_revenue || '')}</span>
    <div class="cols" style="gap:16px"><div style="flex:1 1 300px"><span class="lbl">Promoters and institutions</span>${L(h.promoters_by_quarter)}${L(h.institutions_by_quarter)}</div>
      <div style="flex:1 1 300px"><span class="lbl">Deals and insider filings (a year)</span>${L(h.bulk_block_deals)}${L(h.insider_and_sast)}</div></div>
    <span class="lbl">Peers · ${esc(p.industry || 'no industry label')}${p.with_results_on_record ? ' · ' + p.with_results_on_record + ' of ' + p.names_in_industry + ' with results on record' : ''}</span>
    ${(p.rows || []).length ? `<div class="scroll"><table><thead><tr><th>Name</th><th>P/E</th><th>rank</th><th>Net margin %</th><th>rank</th><th>Revenue growth 1y %</th><th>rank</th></tr></thead><tbody>
      ${p.rows.map((r) => `<tr ${r.self ? 'style="font-weight:600"' : ''}><td>${esc(r.symbol)}</td><td class="num">${n(r.pe)}</td><td class="num">${n(r.pe_rank, 0)}</td><td class="num">${n(r.net_margin_pct)}</td><td class="num">${n(r.margin_rank, 0)}</td><td class="num">${n(r.revenue_growth_1y_pct)}</td><td class="num">${n(r.growth_rank, 0)}</td></tr>`).join('')}</tbody></table></div>` : ''}
    <span class="tiny muted">${esc(p.note || '')}</span>
    <span class="lbl">Concall, presentation and transcript filings</span>
    ${(b.concall_and_presentations || []).map((d) => `<div class="tiny">${esc(d.date)} <a href="${esc(d.url || '#')}" target="_blank" rel="noopener">${esc(d.title)}</a></div>`).join('') || '<span class="tiny muted">none in the graph</span>'}
    <span class="lbl">Operating KPIs</span><span class="tiny muted">${esc(b.operating_kpis || '')}</span>`;
}
async function loadBusiness(isin) {
  try { const b = await api('/api/business?isin=' + encodeURIComponent(isin)); if ($('bizBox')) $('bizBox').innerHTML = bizBlock(b); }
  catch (e) { if ($('bizBox')) $('bizBox').innerHTML = '<span class="small muted">Not available: ' + esc(e.message) + '</span>'; }
}
/* S65: the scoreboard (plan/twin.py): four books with the same money; values only until 60 sessions; gaps are descriptions, never an edge */
async function loadTwin() {
  const box = $('twinBox'); if (!box) return;
  try {
    const d = await api('/api/twin');
    if (!d.started) { box.innerHTML = `<span class="small muted">${esc(d.note)}</span>`; return; }
    const names = { REAL: 'Your book', SYSTEM: "The system's suggestions (paper)", EW: 'Equal-weight Nifty 500 (the bar)', N500: 'Nifty 500' };
    const inr = (x) => Math.round(x).toLocaleString('en-IN');
    box.innerHTML = `<div class="scroll"><table><thead><tr><th>Book</th><th>Started at</th><th>Now</th>${d.vs_equal_weight ? '<th>vs the bar</th>' : ''}</tr></thead><tbody>${
      Object.entries(d.books).map(([b, v]) => `<tr><td>${esc(names[b] || b)}</td><td class="num">${inr(v.start)}</td><td class="num">${inr(v.value)}</td>${d.vs_equal_weight ? `<td class="num">${b === 'EW' ? '—' : inr(d.vs_equal_weight[b])}</td>` : ''}</tr>`).join('')}</tbody></table></div>
      <span class="small muted">Since ${esc(d.since)}, ${d.sessions} session(s), money added Rs ${inr(d.money_added)}, ${d.system_trades} paper trade(s). ${esc(d.note)}</span>`;
  } catch (e) { box.innerHTML = '<span class="small muted">Not available: ' + esc(e.message) + '</span>'; }
}
/* S64 Phase 6: the US sleeve (ledger/foreign.py): positions, the LRS year, and two small forms */
async function loadUs() {
  const box = $('usBox'); if (!box) return;
  try {
    const d = await api('/api/us');
    if (d.enabled === false) { box.innerHTML = `<span class="small muted">${esc(d.note)}</span>`; return; }
    const fx = d.fx ? d.fx[0] : null;
    const inr = (x) => Math.round(x).toLocaleString('en-IN');
    box.innerHTML = `<span class="small">Sent abroad this financial year (${esc(d.lrs.fy)}): USD ${inr(d.lrs.usd)} (Rs ${inr(d.lrs.inr)}), TCS Rs ${inr(d.lrs.tcs_inr)}; room under the USD 250,000 limit: USD ${inr(d.lrs.room_usd)}.${fx ? ' Rate ' + fx.toFixed(2) + ' (' + esc(d.fx_label) + ').' : ' No exchange rate stored yet.'}</span>
      ${d.sleeve_plan ? `<span class="small">Your sleeve: ${(d.sleeve_plan.share * 100).toFixed(1)}% from ${esc(d.sleeve_plan.start)}, about Rs ${inr(d.sleeve_plan.amount_inr)}. To keep TCS low, send ${d.sleeve_plan.by_financial_year.map((r) => 'Rs ' + inr(r.amount_inr) + ' in ' + esc(r.fy)).join(', then ')} (one lump would carry Rs ${inr(d.sleeve_plan.tcs_if_one_lump_inr)} TCS, a credit when you file; estimate).</span>` : ''}
      ${d.positions.length ? `<div class="scroll"><table><thead><tr><th>Name</th><th>Shares</th><th>Cost USD</th></tr></thead><tbody>${d.positions.map((p) => `<tr><td>${esc(p.symbol)}</td><td class="num">${p.qty}</td><td class="num">${inr(p.cost_usd)}</td></tr>`).join('')}</tbody></table></div>` : '<span class="small muted">No US holdings recorded.</span>'}
      <div class="row wrapr" style="gap:6px"><input id="usD" class="inp" type="date" style="flex:0 0 150px"><input id="usS" class="inp" placeholder="symbol" style="flex:0 0 90px">
        <select id="usSide" class="inp" style="flex:0 0 80px"><option>buy</option><option>sell</option></select><input id="usQ" class="inp" placeholder="shares" style="flex:0 0 90px">
        <input id="usP" class="inp" placeholder="USD per share" style="flex:0 0 120px"><input id="usC" class="inp" placeholder="fees USD" style="flex:0 0 90px"><button class="btn primary" id="usAdd">Add trade</button></div>
      <div class="row wrapr" style="gap:6px"><input id="rD" class="inp" type="date" style="flex:0 0 150px"><input id="rU" class="inp" placeholder="USD sent" style="flex:0 0 110px">
        <input id="rI" class="inp" placeholder="rupees paid" style="flex:0 0 120px"><input id="rT" class="inp" placeholder="TCS rupees (blank: estimate)" style="flex:0 0 190px"><button class="btn" id="rAdd">Add remittance</button></div>`;
    $('usAdd').onclick = async () => { try { await post('/api/us/trade', { date: $('usD').value, symbol: $('usS').value, side: $('usSide').value, qty: Number($('usQ').value), price: Number($('usP').value), charges: Number($('usC').value || 0) }); loadUs(); } catch (e) { alert(e.message); } };
    $('rAdd').onclick = async () => { try { const r = await post('/api/us/remit', { date: $('rD').value, usd: Number($('rU').value), inr: Number($('rI').value), tcs: $('rT').value === '' ? null : Number($('rT').value) }); alert('Recorded. TCS Rs ' + inr(r.tcs_inr) + ' (' + r.tcs_basis + ')'); loadUs(); } catch (e) { alert(e.message); } };
  } catch (e) { box.innerHTML = '<span class="small muted">Not available: ' + esc(e.message) + '</span>'; }
}
/* S64: scanners (quant/scan.py): saved scans over his names; a hit can become a price watch; none is a signal */
async function loadScans() {
  const box = $('scanBox'); if (!box) return;
  try {
    const d = await api('/api/scans');
    const rows = d.scans.map((s) => {
      const r = (d.results || {})[s.scan_id], hits = r ? r.hits : [];
      return `<div style="display:flex;flex-direction:column;gap:3px"><div class="row wrapr" style="gap:8px;justify-content:space-between"><b class="small">${esc(s.name)}</b>
        <span class="tiny" style="padding:2px 8px;border-radius:999px;border:1px solid var(--line)">${esc(s.label)}</span></div>
        <span class="tiny muted">${esc(s.conditions)} · ${esc(s.universe)}${s.active ? '' : ' · off'}${r ? ' · run ' + esc(r.at) + ': ' + hits.length + ' of ' + r.checked : ' · not run yet'}</span>
        ${hits.slice(0, 12).map((h) => `<div class="row small" style="gap:8px"><b>${esc(h.symbol)}</b><span class="tiny muted" style="flex:1">${esc(h.why.join('; '))}</span><button class="btn" data-watch="${esc(h.isin)}|${esc(h.symbol)}|${h.close}">Watch</button></div>`).join('')}</div>`;
    }).join('<hr style="border:0;border-top:1px solid var(--line);width:100%">');
    box.innerHTML = rows + `<hr style="border:0;border-top:1px solid var(--line);width:100%"><span class="lbl">New scan</span>
      <div class="row wrapr" style="gap:8px"><input id="scName" class="inp" placeholder="name" style="flex:1 1 160px"><input id="scCond" class="inp" placeholder="price_below_sma:50; volume_spike:2" style="flex:2 1 260px">
        <select id="scUni" class="inp" style="flex:0 0 auto"><option value="list">my names</option><option value="holdings">holdings</option><option value="nifty500">Nifty 500</option></select>
        <button class="btn primary" id="scMake">Save</button></div>
      <span class="tiny muted" style="white-space:pre-line">Conditions, joined by ';' (a hit needs all):
${esc(d.help)}</span>
      <span class="tiny muted">A scan used as a buying rule counts only after the learner has tested it on data it never saw; until then it is a description. Runs each evening; hits on your names go into the evening summary.</span>`;
    $('scMake').onclick = async () => { try { await post('/api/scans', { name: $('scName').value, conditions: $('scCond').value, universe: $('scUni').value }); loadScans(); } catch (e) { alert(e.message); } };
    box.querySelectorAll('[data-watch]').forEach((b) => { b.onclick = async () => {
      const [isin, sym, close] = b.dataset.watch.split('|'); const lv = prompt('Alert me when ' + sym + ' falls to (price):', (Number(close) * 0.97).toFixed(2));
      if (!lv) return; try { await post('/api/watches', { isin, symbol: sym, kind: 'below', level: Number(lv), note: 'from a scan' }); b.textContent = 'Watching'; } catch (e) { alert(e.message); } }; });
  } catch (e) { box.innerHTML = '<span class="small muted">Scans not available: ' + esc(e.message) + '</span>'; }
}
/* S64: scenario chains from historical betas (risk/scenarios.py): a description, never a forecast */
function scenBlock(all) {
  const rs = (x) => (x < 0 ? '-' : '+') + 'Rs ' + groupIN(Math.abs(Math.round(x)));
  return Object.values(all).map((v) => v.error ? `<span class="small muted">${esc(v.scenario)}: ${esc(v.error)}</span>` : `<div style="display:flex;flex-direction:column;gap:3px">
    <b class="small">${esc(v.label)}</b><span class="tiny muted">${esc(v.chain)}</span>
    <span class="small"><span class="${v.total < 0 ? 'down' : 'up'}">${rs(v.total)}</span> <span class="tiny muted">(${rs(v.total_range[0])} to ${rs(v.total_range[1])}, about 2 standard errors) on Rs ${groupIN(Math.round(v.modelled_value))} of stocks and index funds</span></span>
    <span class="tiny muted">${v.rows.slice(0, 3).map((r) => esc(r.symbol) + ' ' + rs(r.impact)).join(' · ')}${v.not_modelled.length ? ' · not modelled: ' + v.not_modelled.length + ' holdings (gold, debt, cash, or too little history)' : ''}</span></div>`).join('<hr style="border:0;border-top:1px solid var(--line);width:100%">')
    + '<span class="tiny muted">From historical betas; a description, not a forecast. A beta mixes calm and rough months, and a rupee fall in the past came with selling of shares, so it is a co-movement, not a cause.</span>';
}
async function loadScenarios() {
  try { const m = await api('/api/scenarios'); if ($('scenBox')) $('scenBox').innerHTML = scenBlock(m); }
  catch (e) { if ($('scenBox')) $('scenBox').innerHTML = '<span class="small muted">Scenarios not available: ' + esc(e.message) + '</span>'; }
}
function bindSims(d, f, r) {
  const ps = $('simPaths'); ps.onchange = () => { S.simPaths = Number(ps.value); };
  const yr = $('simYears'); yr.onchange = () => { S.simYears = Number(yr.value); };
  S.whatif = S.whatif || { mine: 30, stocks: 10, n500: 20, mom50: 0, gold: 15, debt: 0, cash: 25 };
  Object.keys(S.whatif).forEach((a) => { const el = $('wi_' + a); el.onchange = () => { S.whatif[a] = Number(el.value); renderSims(d); }; });
  $('simRun').onclick = async () => {
    const custom = {}; Object.entries(S.whatif).forEach(([a, v]) => { custom[a] = v / 100; });
    try { await post('/api/sims/run', { paths: S.simPaths || 10000, years: S.simYears || 5, custom }); S.simMix = 'what-if'; } catch (e) { alert(e.message); }
    load(true); };
  document.querySelectorAll('[data-mix]').forEach((b) => { b.onclick = () => { S.simMix = b.dataset.mix; renderSims(d); }; });
  const hit = $('fanHit'); if (!hit || !f) return;
  const svg = hit.ownerSVGElement, tip = $('fanTip'), line = $('fanX');
  hit.onmousemove = (e) => {
    const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY; const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    const L = 46, W = 760, Rt = 12; const mth = Math.max(1, Math.min(f.months, Math.round((p.x - L) / (W - L - Rt) * f.months)));
    const xx = L + mth / f.months * (W - L - Rt); line.setAttribute('x1', xx); line.setAttribute('x2', xx); line.setAttribute('visibility', 'visible');
    const i = mth - 1;
    tip.style.display = 'block';
    tip.innerHTML = `<b>after ${mth >= 12 ? (mth / 12).toFixed(mth % 12 ? 1 : 0) + ' years' : mth + ' months'}</b><br>good case (p95) ${xMoney(f.p95[i], r.invested)}<br>median ${xMoney(f.p50[i], r.invested)}<br>bad case (p5) ${xMoney(f.p5[i], r.invested)}`;
  };
  hit.onmouseleave = () => { tip.style.display = 'none'; line.setAttribute('visibility', 'hidden'); };
}

/* ---------- Knowledge graph (54e) ---------- */
const KIND_COLORS = { company: BUCKET_COLORS[0], sector: BUCKET_COLORS[1], verdict: BUCKET_COLORS[2], org: BUCKET_COLORS[3], person: BUCKET_COLORS[5], theme: BUCKET_COLORS[6] };
const KIND_NAMES = { company: 'Companies (yours and watched)', sector: 'Sectors', verdict: 'Guard verdicts', org: 'Organisations', person: 'People', theme: 'Themes (news)' };
/* Fruchterman-Reingold (1991): repulsion k²/d, attraction d²/k, a cooling step, a weak pull to the centre */
function layout(nodes, edges, W, H) {
  const idx = {}; const n = nodes.length || 1, k = Math.sqrt(W * H / n) * 0.75;
  nodes.forEach((v, i) => { idx[v.id] = i; const a = i * 2.39996, r = 20 + 12 * Math.sqrt(i); v.x = W / 2 + Math.cos(a) * r; v.y = H / 2 + Math.sin(a) * r; });
  const E = edges.filter((e) => idx[e.a] !== undefined && idx[e.b] !== undefined).map((e) => [idx[e.a], idx[e.b], e.w]);
  const steps = 400;
  for (let it = 0; it < steps; it++) {
    const t = (W / 12) * (1 - it / steps) + 0.5;
    const dx = new Float64Array(n), dy = new Float64Array(n);
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      let ex = nodes[i].x - nodes[j].x, ey = nodes[i].y - nodes[j].y; const d = Math.sqrt(ex * ex + ey * ey) || 0.01; const f = k * k / d / d;
      ex *= f; ey *= f; dx[i] += ex; dy[i] += ey; dx[j] -= ex; dy[j] -= ey; }
    E.forEach(([i, j]) => { const ex = nodes[i].x - nodes[j].x, ey = nodes[i].y - nodes[j].y; const d = Math.sqrt(ex * ex + ey * ey) || 0.01; const f = d / k;
      dx[i] -= ex * f; dy[i] -= ey * f; dx[j] += ex * f; dy[j] += ey * f; });
    nodes.forEach((v, i) => { dx[i] += (W / 2 - v.x) * 0.05; dy[i] += (H / 2 - v.y) * 0.05 * (W / H);
      const m = Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) || 1; v.x += dx[i] / m * Math.min(m, t); v.y += dy[i] / m * Math.min(m, t);
      v.x = Math.max(24, Math.min(W - 120, v.x)); v.y = Math.max(16, Math.min(H - 16, v.y)); });
  }
  return E;
}
/* The knowledge graph in 3-D (2026-10-30, his ask): the same nodes and links as the flat map, laid out in space. Drag to turn, wheel to zoom,
   click a dot for its documents. Plain canvas: no library, nothing fetched. It turns slowly by itself until touched. */
const G3 = { yaw: 0.6, pitch: 0.35, zoom: 1, auto: true, raf: 0 };
function layout3d(nodes, E) {
  const n = nodes.length || 1, k = 90;
  nodes.forEach((v, i) => { const t = i * 2.39996, z = 1 - 2 * (i + 0.5) / n, r = Math.sqrt(1 - z * z) * 150;
    v.X = Math.cos(t) * r; v.Y = Math.sin(t) * r; v.Z = z * 150; });
  for (let step = 0, temp = 30; step < 260; step++, temp *= 0.985) {
    const f = nodes.map(() => [0, 0, 0]);
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      const a = nodes[i], b = nodes[j], dx = a.X - b.X, dy = a.Y - b.Y, dz = a.Z - b.Z, d2 = dx * dx + dy * dy + dz * dz + 0.01, rep_ = k * k / d2;
      f[i][0] += dx * rep_; f[i][1] += dy * rep_; f[i][2] += dz * rep_; f[j][0] -= dx * rep_; f[j][1] -= dy * rep_; f[j][2] -= dz * rep_; }
    E.forEach(([i, j]) => { const a = nodes[i], b = nodes[j], dx = a.X - b.X, dy = a.Y - b.Y, dz = a.Z - b.Z, d = Math.sqrt(dx * dx + dy * dy + dz * dz) + 0.01, att = d / (k * 2.5);
      f[i][0] -= dx * att; f[i][1] -= dy * att; f[i][2] -= dz * att; f[j][0] += dx * att; f[j][1] += dy * att; f[j][2] += dz * att; });
    nodes.forEach((v, i) => { f[i][0] -= v.X * 0.08; f[i][1] -= v.Y * 0.08; f[i][2] -= v.Z * 0.08; });   /* a pull to the centre: separate groups stay in view */
    nodes.forEach((v, i) => { const m = Math.hypot(...f[i]) || 1, s_ = Math.min(m, temp) / m; v.X += f[i][0] * s_; v.Y += f[i][1] * s_; v.Z += f[i][2] * s_; });
  }
  /* centred and scaled to a fixed sphere, so the camera always sees all of it (a free layout can end far bigger than the view) */
  const cx = nodes.reduce((a, v) => a + v.X, 0) / n, cy_ = nodes.reduce((a, v) => a + v.Y, 0) / n, cz = nodes.reduce((a, v) => a + v.Z, 0) / n;
  const far = Math.max(1, ...nodes.map((v) => Math.hypot(v.X - cx, v.Y - cy_, v.Z - cz)));
  nodes.forEach((v) => { v.X = (v.X - cx) / far * 170; v.Y = (v.Y - cy_) / far * 170; v.Z = (v.Z - cz) / far * 170; });
}
function draw3d(cv, nodes, E, rad) {
  const ctx = cv.getContext('2d'), W = cv.width, H = cv.height, cy = Math.cos(G3.yaw), sy = Math.sin(G3.yaw), cp = Math.cos(G3.pitch), sp = Math.sin(G3.pitch);
  const css = getComputedStyle(document.body), line = css.getPropertyValue('--line').trim() || '#334', text = css.getPropertyValue('--text').trim() || '#ddd';
  nodes.forEach((v) => { const x = v.X * cy - v.Z * sy, z1 = v.X * sy + v.Z * cy, y = v.Y * cp - z1 * sp, z = v.Y * sp + z1 * cp, per = 520 / (520 + z) * G3.zoom;
    v.sx = W / 2 + x * per * 1.6; v.sy = H / 2 + y * per * 1.6; v.sz = z; v.sp = per; });
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = 'rgba(148,163,184,0.45)'; ctx.globalAlpha = 1;
  E.forEach(([i, j, w]) => { ctx.lineWidth = Math.min(3, 0.6 + Math.log1p(w) / 2); ctx.beginPath(); ctx.moveTo(nodes[i].sx, nodes[i].sy); ctx.lineTo(nodes[j].sx, nodes[j].sy); ctx.stroke(); });
  ctx.globalAlpha = 1;
  [...nodes].sort((a, b) => b.sz - a.sz).forEach((v) => {               /* far first: near dots cover far ones */
    const r = Math.max(2, rad(v) * v.sp * 1.3), fade = Math.max(0.35, Math.min(1, 1.1 - v.sz / 400));
    ctx.globalAlpha = fade; ctx.fillStyle = KIND_COLORS[v.kind] || '#888'; ctx.beginPath(); ctx.arc(v.sx, v.sy, r, 0, 6.2832); ctx.fill();
    if (v.owned) { ctx.strokeStyle = text; ctx.lineWidth = 2; ctx.stroke(); }
    if (!['org', 'person', 'theme'].includes(v.kind) || (v.docs || 0) > 3) { ctx.fillStyle = text; ctx.font = `${v.kind === 'company' ? 600 : 400} ${Math.round(11 * Math.max(0.8, v.sp))}px system-ui`;
      ctx.fillText(v.label, v.sx + r + 3, v.sy + 4); }
  });
  ctx.globalAlpha = 1;
}
function graph3d(nodes, edges, rad) {
  const cv = $('g3d'); if (!cv) return;
  const idx = {}; nodes.forEach((v, i) => { idx[v.id] = i; });
  const E = edges.filter((e) => idx[e.a] !== undefined && idx[e.b] !== undefined).map((e) => [idx[e.a], idx[e.b], e.w]);
  layout3d(nodes, E);
  cancelAnimationFrame(G3.raf);
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const tick = () => { if (!document.body.contains(cv)) return; if (G3.auto && !reduce) G3.yaw += 0.003; draw3d(cv, nodes, E, rad); G3.raf = requestAnimationFrame(tick); };
  let drag = null;
  cv.onmousedown = (e) => { drag = { x: e.clientX, y: e.clientY, moved: false }; G3.auto = false; };
  window.onmouseup = () => { drag = null; };
  cv.onmousemove = (e) => { if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
    G3.yaw += dx * 0.008; G3.pitch = Math.max(-1.4, Math.min(1.4, G3.pitch + dy * 0.008)); drag.x = e.clientX; drag.y = e.clientY; };
  cv.onwheel = (e) => { e.preventDefault(); G3.zoom = Math.max(0.4, Math.min(3, G3.zoom * (e.deltaY < 0 ? 1.1 : 0.9))); };
  cv.onclick = (e) => { const b = cv.getBoundingClientRect(), x = (e.clientX - b.left) * cv.width / b.width, y = (e.clientY - b.top) * cv.height / b.height;
    let best = null, bd = 400; nodes.forEach((v) => { const d = (v.sx - x) ** 2 + (v.sy - y) ** 2; if (d < bd) { bd = d; best = v; } });
    if (best) graphNode(best.id, nodes); };
  tick();
}
function renderGraph(d) {
  if (d.off) { $('screen').innerHTML = `<div class="card"><span class="lbl">Knowledge graph</span><div style="font-size:18px;font-weight:600;margin:6px 0">Switched off</div><div class="small muted">${esc(d.why || '')}</div></div>`; return; }
  const W = 1000, H = 640, nodes = d.nodes, E = layout(nodes, d.edges, W, H);
  const rad = (n) => n.kind === 'company' ? 7 + Math.min(10, Math.sqrt(n.docs || 0) / 2) : 3 + Math.min(6, Math.sqrt(n.docs || 0) / 2);
  const labelled = new Set(nodes.filter((n) => n.kind !== 'theme' && n.kind !== 'org' && n.kind !== 'person').map((n) => n.id)
    .concat(nodes.filter((n) => ['org', 'person', 'theme'].includes(n.kind)).sort((a, b) => b.docs - a.docs).slice(0, 18).map((n) => n.id)));
  const months = d.growth.map((g) => g.month), sel = S.gUpto ?? months.length;
  const totals = d.growth.map((g) => (g.filing || 0) + (g.article || 0) + (g.result || 0) + (g.analyst_note || 0)), mx = Math.sqrt(Math.max(1, ...totals));
  const bh = (t) => Math.max(1, Math.sqrt(t) / mx * 60);
  $('screen').innerHTML = `<div class="cols">
    <section class="stack" style="flex:3 1 720px">
      <div class="panel" style="display:flex;flex-direction:column;gap:10px">
        <div class="row wrapr" style="justify-content:space-between"><span class="lbl">Around your companies${d.upto ? ', as of ' + esc(d.upto) : ', today'}</span>
          <span class="small muted">${groupIN(d.totals.docs)} documents · ${groupIN(d.totals.nodes)} things · ${groupIN(d.totals.edges)} dated links in the whole graph</span></div>
        <div class="row wrapr" style="gap:10px">${Object.keys(KIND_NAMES).map((k) => `<label class="row small" style="gap:5px;cursor:pointer"><input type="checkbox" data-gkind="${k}" ${d.kinds.includes(k) ? 'checked' : ''} ${k === 'company' ? 'disabled' : ''}><span style="width:10px;height:10px;border-radius:50%;background:${KIND_COLORS[k]}"></span>${esc(KIND_NAMES[k])}</label>`).join('')}</div>
        <div class="row" style="gap:6px">${[['3d', '3-D (drag to turn, wheel to zoom)'], ['2d', 'Flat']].map(([k, l]) => `<button class="btn ${(S.gView || '3d') === k ? 'primary' : ''}" data-gview="${k}" style="font-size:12px;padding:3px 10px">${l}</button>`).join('')}
          ${nodes.length ? '' : '<span class="small warn">Nothing to draw yet: the graph fills as your companies, their filings and news are read (it follows your holdings and watch list).</span>'}</div>
        ${(S.gView || '3d') === '3d' ? `<canvas id="g3d" width="1000" height="640" style="width:100%;height:auto;background:var(--panel2);border-radius:10px;cursor:grab" aria-label="Knowledge graph in 3-D"></canvas>` : ''}
        <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;background:var(--panel2);border-radius:10px;${(S.gView || '3d') === '3d' ? 'display:none' : ''}" role="img" aria-label="Knowledge graph around your companies">
          ${E.map(([i, j, w]) => `<line x1="${nodes[i].x.toFixed(1)}" y1="${nodes[i].y.toFixed(1)}" x2="${nodes[j].x.toFixed(1)}" y2="${nodes[j].y.toFixed(1)}" stroke="var(--line)" stroke-width="${Math.min(3, 0.6 + Math.log1p(w) / 2).toFixed(2)}"></line>`).join('')}
          ${nodes.map((n) => `<g data-gnode="${esc(n.id)}" style="cursor:pointer"><circle cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="${rad(n).toFixed(1)}" fill="${KIND_COLORS[n.kind]}" stroke="${n.owned ? 'var(--text)' : 'var(--panel2)'}" stroke-width="2"><title>${esc(n.label)} (${esc(n.kind)}${n.docs ? ', ' + n.docs + ' documents' : ''}${n.owned ? ', you own it' : n.watched ? ', watched' : ''})</title></circle>
            ${labelled.has(n.id) ? `<text x="${(n.x + rad(n) + 3).toFixed(1)}" y="${(n.y + 4).toFixed(1)}" font-size="${n.kind === 'company' ? 12 : 10}" font-weight="${n.kind === 'company' ? 600 : 400}" fill="${n.kind === 'company' ? 'var(--text)' : 'var(--muted)'}">${esc(String(n.label).slice(0, 28))}</text>` : ''}</g>`).join('')}
        </svg>
        <span class="tiny muted">A ring marks a company you own. Size: how many documents. A line joins a company to what its documents name at least twice; the six most named of each kind are drawn. Click any dot.</span>
      </div>
      <div class="panel" style="display:flex;flex-direction:column;gap:8px"><span class="lbl">How the graph grew (documents a month, by their own date; bar height on a square-root scale, hover for the count)</span>
        <svg viewBox="0 0 ${months.length * 26} 70" style="width:100%;height:70px" preserveAspectRatio="none" role="img" aria-label="Documents a month">
          ${totals.map((t, i) => `<rect x="${i * 26 + 3}" y="${66 - bh(t)}" width="20" height="${bh(t)}" rx="3" fill="${i < sel ? 'var(--accent)' : 'var(--line)'}"><title>${months[i]}: ${t} documents</title></rect>`).join('')}</svg>
        <div class="row" style="gap:10px"><label class="small" for="gSlide">As of</label><input type="range" id="gSlide" min="1" max="${months.length}" value="${sel}" style="flex:1"><span class="num small" style="flex:0 0 80px">${sel >= months.length ? 'today' : esc(months[sel - 1])}</span></div>
      </div>
    </section>
    <section class="stack" style="flex:1 1 320px"><div class="panel" id="gSide" style="display:flex;flex-direction:column;gap:8px"><span class="lbl">Details</span><span class="small muted">Click a dot to see its latest documents or the companies it is named with.</span></div></section></div>`;
  document.querySelectorAll('[data-gkind]').forEach((b) => { b.onchange = () => { S.gKinds = [...document.querySelectorAll('[data-gkind]:checked')].map((x) => x.dataset.gkind); load(true); }; });
  const sl = $('gSlide'); sl.onchange = () => { S.gUpto = Number(sl.value) >= months.length ? null : Number(sl.value); S.gUptoDate = S.gUpto ? months[S.gUpto - 1] : null; load(true); };
  document.querySelectorAll('[data-gnode]').forEach((g) => { g.onclick = () => graphNode(g.dataset.gnode, nodes); });
  document.querySelectorAll('[data-gview]').forEach((b) => { b.onclick = () => { S.gView = b.dataset.gview; renderGraph(d); }; });
  if ((S.gView || '3d') === '3d') graph3d(nodes, d.edges, rad);
}
async function graphNode(id, nodes) {
  const n = nodes.find((x) => x.id === id) || { label: id, kind: '' };
  const d = await api('/api/graph/node?id=' + encodeURIComponent(id) + (S.gUptoDate ? '&upto=' + S.gUptoDate : ''));
  const name = (cid) => (nodes.find((x) => x.id === cid) || { label: cid }).label;
  $('gSide').innerHTML = `<span class="lbl">${esc(KIND_NAMES[n.kind] || n.kind)}</span><b style="font-size:15px">${esc(n.label)}</b>
    ${n.by_kind ? `<span class="small soft">${Object.entries(n.by_kind).map(([k, v]) => `${v} ${esc(k.replace('_', ' '))}${v === 1 ? '' : 's'}`).join(' · ')}</span>` : ''}
    ${d.docs ? d.docs.map((x) => `<button class="btn" style="text-align:left;display:flex;flex-direction:column;gap:2px" data-doc="${esc(x.id)}"><span style="font-weight:600">${esc(x.title || x.id)}</span><span class="tiny muted">${esc(x.kind)} · ${esc(x.source || '')} · ${esc(x.at)}</span></button>`).join('') || '<span class="small muted">No documents yet.</span>' : ''}
    ${d.companies ? `<span class="small muted">Named in the documents of:</span>${d.companies.map((c) => `<span class="small">${esc(name(c.id))} <span class="muted">(${c.docs} documents)</span></span>`).join('')}` : ''}`;
  document.querySelectorAll('[data-doc]').forEach((b) => { b.onclick = () => openReport(b.dataset.doc); });
}

/* ---------- loading and live updates ---------- */
function applyTheme() {
  document.documentElement.dataset.theme = S.settings.theme || 'dark';
  document.body.classList.toggle('hide-money', false);
}
async function load(force = false) {
  if (S.stopped) return;
  const now = Date.now();
  if (!force && now - S.last < 2500) { if (!S.pending) { S.pending = true; setTimeout(() => { S.pending = false; load(true); }, 2600 - (now - S.last)); } return; }
  S.last = now;
  // 2026-10-24: a slow load finishing after a click on another tab drew its old screen over the new one (Settings
  // "popped back"). A load draws only while its screen is showing and when no newer load has drawn already.
  const screen = S.screen, gen = (S.gen = (S.gen || 0) + 1);
  const showing = () => S.screen === screen;
  const fresh = () => showing() && gen > (S.drawn || 0) && ((S.drawn = gen), true);
  try {
    let cmd = S.data.command;
    if (!cmd || screen === 'portfolio' && S.sub === 'overview') { cmd = await api('/api/command'); if (!showing()) return; S.data.command = cmd; }
    if (!S.sys || Date.now() - (S.sysAt || 0) > (screen === 'system' && !(typeof RD !== 'undefined' && RD.handles(screen, S.sub)) ? 4000 : 60000)) { try { S.sys = await api('/api/system'); S.sysAt = Date.now(); } catch (e) { /* the chip is simply left out */ } }
    S.settings = { ...S.settings, ...cmd.settings, abilities: S.settings.abilities, backup_dir: S.settings.backup_dir }; applyTheme();   // (the cached command snapshot never overwrites what he just switched)   // privacy and theme on every screen
    renderStatus(cmd); renderTabs();
    const sub = S.sub;
    if (typeof RD !== 'undefined' && RD.handles(screen, sub)) {          // S78: the redesigned screens (redesign.js)
      await RD.load(screen, sub, fresh);
      const sh0 = $('subnav'); if (sh0) sh0.innerHTML = subnavHtml(S.screen, S.sub);
      paintDock(); return;
    }
    if (screen === 'assistant') {
      const [h, inv, pol, paper] = await Promise.all([api('/api/assistant'), api('/api/investigations').catch(() => ({ investigations: [] })), api('/api/policy').catch(() => null), api('/api/paper').catch(() => null)]);
      if (!showing()) return; h.policy = pol; h.paper = paper; S.drawn = gen; renderAssistant(h, inv.investigations, cmd, S.sys); paintDock(); return;
    }
    if (screen === 'portfolio' && sub === 'overview') { const d = cmd; if (fresh()) keepInputs(() => { $('screen').innerHTML = ''; renderPortfolioOverview(d); }); }
    else if (screen === 'portfolio' && sub === 'holdings') { const d = await api('/api/portfolio' + (S.selected ? '?isin=' + encodeURIComponent(S.selected) : '')); if (fresh()) renderPortfolio(d); }
    else if (screen === 'portfolio' && sub === 'paper') { const d = await api('/api/paper'); if (fresh()) keepInputs(() => { $('screen').innerHTML = ''; renderPaper(d); }); }
    else if (screen === 'portfolio' && sub === 'watch') { const d = await api('/api/watch'); if (fresh()) keepInputs(() => renderWatch(d)); }
    else if (screen === 'world') { const d = await api('/api/world'); if (fresh()) renderWorld(d); }
    else if (screen === 'research' && sub === 'work') { const d = await api('/api/investigations'); if (fresh()) keepInputs(() => { $('screen').innerHTML = ''; renderInvestigations(d); }); }
    else if (screen === 'research' && sub === 'recs') { const [d, r] = await Promise.all([api('/api/proposals'), api('/api/routing').catch(() => ({ decisions: [] }))]); if (fresh()) keepInputs(() => { $('screen').innerHTML = ''; renderProposals(d, r); }); }
    else if (screen === 'research' && sub === 'memory') { const d = await api('/api/recall?' + new URLSearchParams({ about: S.memAbout || '' })); if (fresh()) keepInputs(() => { $('screen').innerHTML = ''; renderMemory(d); }); }
    else if (screen === 'research' && sub === 'rules') { const [rl, env, sc] = await Promise.all([api('/api/rules'), api('/api/envelope'), api('/api/scorecard')]); if (fresh()) keepInputs(() => { $('screen').innerHTML = ''; renderRules(rl, env, sc); }); }
    else if (screen === 'research' && sub === 'plans') { const d = await api('/api/research' + (S.rsel ? '?isin=' + encodeURIComponent(S.rsel) : '')); if (fresh()) keepInputs(() => renderResearch(d)); }
    else if (screen === 'research' && sub === 'sims') { const d = await api('/api/sims'); if (fresh()) renderSims(d); }
    else if (screen === 'research' && sub === 'graph') { const d = await api('/api/graph?' + new URLSearchParams({ kinds: (S.gKinds || ['company', 'sector', 'verdict', 'org', 'person']).join(','), ...(S.gUptoDate ? { upto: S.gUptoDate } : {}) })); if (fresh()) renderGraph(d); }
    else if (screen === 'inbox') { const d = await api('/api/inbox'); if (fresh()) keepInputs(() => renderInbox(d)); }
    else if (screen === 'system' && sub === 'now') { const s = S.sys; if (fresh()) keepInputs(() => { $('screen').innerHTML = systemNowHtml(s, cmd); wireSystem(); }); }
    else if (screen === 'system' && sub === 'limits') { const p = await api('/api/policy'); if (fresh()) { $('screen').innerHTML = ''; renderLimits(p); } }
    else if (screen === 'system' && sub === 'schedule') { const d = await api('/api/schedule'); if (fresh()) keepInputs(() => renderSchedule(d)); }
    else if (screen === 'settings') { const d = await api('/api/settings'); if (fresh()) { S.settings = d; renderSettings(d); } }
    else if (screen === 'setup') { const d = await api('/api/setup'); if (fresh()) renderSetup(d); }
    const sh = $('subnav'); if (sh) sh.innerHTML = subnavHtml(S.screen, S.sub);
    paintDock();
  } catch (e) {
    if (showing()) $('screen').innerHTML = `<div class="soon"><b>Could not load this screen</b><span class="small muted">${esc(e.message)}</span></div>`;
  }
}
function route() {
  const [id, sub] = (location.hash.replace('#/', '') || 'today').split('/');
  const was = S.screen + '/' + S.sub;
  const legacy = { command: ['system', 'now'], ai: ['assistant', ''], schedule: ['system', 'schedule'], sims: ['research', 'sims'], graph: ['research', 'graph'], watch: ['portfolio', 'watch'], inbox: ['assistant', ''] };
  let screen = id, subv = sub || '';
  if (legacy[id]) [screen, subv] = legacy[id];
  const valid = NAV.some(([t]) => t === screen) || OLD_SCREENS.includes(screen) || screen === 'settings' || screen === 'setup';
  S.screen = valid ? screen : 'today';
  const subs = SUBS[S.screen];
  S.sub = subs ? (subs.some(([k]) => k === subv) ? subv : subs[0][0]) : '';
  if (S.screen + '/' + S.sub !== was) { $('screen').innerHTML = '<div class="soon"><span class="muted">Loading…</span></div>'; S.threadHtml = null; S.threadSeen = false; }
  renderTabs(); load(true);
}
const TOPICS = { today: ['live', 'portfolio', 'hq', 'settings'], account: ['live', 'portfolio', 'settings'], watchlist: ['live', 'watch', 'hq', 'settings'], assistant: ['chat', 'hq', 'notifications', 'inbox', 'settings'], world: ['hq', 'inbox', 'activity', 'health', 'command', 'settings'], portfolio: ['live', 'portfolio', 'watch', 'settings'],
  research: ['research', 'hq', 'watch', 'sims', 'settings'], inbox: ['inbox', 'settings'], system: ['activity', 'health', 'hq', 'notes', 'settings'], settings: ['settings', 'kite'], setup: ['inbox', 'settings'] };
function listen() {
  const es = new EventSource('/api/events');
  let prev = null;
  es.onmessage = (ev) => {
    const v = JSON.parse(ev.data);
    if (prev) {
      const changed = Object.keys(v).filter((k) => v[k] !== prev[k]);
      const want = TOPICS[S.screen];
      S.data.command = null;
      if (changed.length && (!want || changed.some((k) => want.includes(k) || k === 'kite' || k === 'command'))) load(false);
    }
    prev = v;
  };
  es.onerror = () => { if (S.stopped) es.close(); };
}
/* typed text and focus survive a redraw */
/* Someone is in the middle of an answer: a redraw now would move the page under the cursor (the first real launch asked 30 questions at once and
   the screen refreshed after every one). The redraw waits until the box is left or empty; nothing typed is ever lost. */
function typing() {
  const a = document.activeElement;
  if (!a || !a.matches || !a.matches('#screen input:not([type=checkbox]):not([type=radio]):not([type=range]), #screen textarea') || a.id === 'chatIn') return false;   // (the assistant's composer is patched, never redrawn)
  return String(a.value || '').length > 0;
}
const catchUp = () => { if (S.deferred && !typing()) { S.deferred = false; load(true); } };
document.addEventListener('focusout', () => { if (S.deferred) setTimeout(catchUp, 350); });
setInterval(catchUp, 2000);                                                                // (a window that has lost focus sends no focusout)
function keepInputs(render) {
  if (typing()) { S.deferred = true; return; }
  const vals = {}; let focus = null;
  const scrollY = window.scrollY, scrolls = [...document.querySelectorAll('#screen .scroll')].map((e) => [e.scrollTop, e.scrollLeft]);
  document.querySelectorAll('#screen input[id], #screen select[id]').forEach((el) => { if (el.value) vals[el.id] = el.value; });
  if (document.activeElement && document.activeElement.id) focus = document.activeElement.id;
  render();
  Object.entries(vals).forEach(([id, v]) => { const el = $(id); if (el && !el.value && el.type !== 'range') el.value = v; });
  if (focus && $(focus)) { const el = $(focus); el.focus(); if (el.setSelectionRange && el.value) el.setSelectionRange(el.value.length, el.value.length); }
  if (Math.abs(window.scrollY - scrollY) > 2) window.scrollTo(0, scrollY);                    // the page stays where he was reading
  document.querySelectorAll('#screen .scroll').forEach((e, i) => { if (scrolls[i]) { e.scrollTop = scrolls[i][0]; e.scrollLeft = scrolls[i][1]; } });
}
setInterval(() => { $('clock').textContent = new Date().toLocaleString('en-IN', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }); }, 1000);
setInterval(() => load(false), 60000);
window.addEventListener('hashchange', route);
/* start once every script (ui.js, world.js) has been read */
document.addEventListener('DOMContentLoaded', () => { route(); listen(); });
