/* Portfolio Lab, the redesigned screens (S68): the Assistant is home; Research shows what the workers did and what it rests on; System shows the limits in
   force and whether anything is stuck; Portfolio opens on the figures. Loaded after app.js (it reuses its helpers and the cards it already had). */
'use strict';

/* a safe, small formatter for the assistant's words: escape first, then **bold** and "- " bullets */
function fmt(text) {
  return esc(text || '').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/^- /gm, '• ');
}
const pill = (state, label) => `<span class="pillst st-${state}">${esc(label || state)}</span>`;
const STATE_WORD = { planning: ['working', 'planning'], working: ['working', 'working'], reviewing: ['working', 'being reviewed'], synthesising: ['working', 'writing the answer'], done: ['done', 'finished'], blocked: ['blocked', 'stuck'] };

function subnavHtml(screen, sub) {
  const items = SUBS[screen];
  if (!items) return '';
  return `<div class="subnav" role="tablist">${items.map(([id, label]) => `<a href="#/${screen}/${id}" class="${sub === id ? 'on' : ''}">${esc(label)}</a>`).join('')}</div>`;
}

/* ---------- the assistant ---------- */
function bubble(m, prevQ) {
  const me = m.role === 'me', note = (m.mode || '').startsWith('note:');
  const steps = (m.route || []).filter((r) => r && r !== 'the system, unprompted').map((r) => `<span class="step">${esc(r)}</span>`).join('');
  const body = m.status === 'working' ? `<span class="warn">${esc(m.meta && m.meta.startsWith('working') ? m.meta : 'Working on it…')}</span>` : fmt(m.text);
  return `<div class="bub ${me ? 'me' : note ? 'ai sys' : 'ai'}">
    ${!me && steps && m.status !== 'working' ? `<div class="steps">${steps}</div>` : ''}
    <div class="body">${note ? '<div class="tiny muted" style="margin-bottom:4px">from the system</div>' : ''}${body}</div>
    ${m.report ? `<button class="btn" style="align-self:flex-start" data-report="${esc(m.report)}">Open the saved note</button>` : ''}
    ${m.status === 'failed' ? '<span class="tiny down">not answered</span>' : ''}
    <span class="tiny muted">${esc(!me && !note && m.status !== 'working' ? m.meta || '' : '')}${!me && !note && m.meta && m.status !== 'working' ? ' · ' : ''}${esc(m.at || '')}</span></div>`;
}
function threadHtml(msgs) {
  if (!msgs.length) {
    const asks = ['Is everything working, and what are you doing right now?', 'What needs me today?', 'Investigate my concern that a China-related AI sell-off could spread to my investments.',
      'Compare putting 10 lakh in now, in 10 monthly parts, or keeping cash until a fall.', 'What does history say about selling an IPO allotment on listing day?'];
    return `<div style="margin:auto;display:flex;flex-direction:column;gap:12px;align-items:center;max-width:560px;text-align:center">
      <b style="font-size:17px">Talk to it like a colleague who never sleeps.</b>
      <span class="muted">It discusses ideas, answers from your reconciled record, runs calculations and scenarios, and starts investigations that research, quant and review workers carry out in the background. Their progress and results come back here.</span>
      <div class="row wrapr" style="gap:6px;justify-content:center">${asks.map((a) => `<button class="btn" data-sugg="${esc(a)}" style="font-size:12px;padding:5px 10px;text-align:left">${esc(a)}</button>`).join('')}</div></div>`;
  }
  return msgs.map((m) => bubble(m)).join('');
}
function missionCard(c) {
  const st = STATE_WORD[c.state] || ['wait', c.state];
  const outs = {}; (c.outputs || []).forEach((o) => { outs[o.kind] = (outs[o.kind] || 0) + 1; });
  return `<div class="card" data-mission="${c.case_id}" style="cursor:pointer">
    <div class="row" style="justify-content:space-between;gap:8px"><b style="font-size:13px;line-height:1.35">${esc(String(c.goal).slice(0, 120))}${c.goal.length > 120 ? '…' : ''}</b>${pill(st[0], st[1])}</div>
    <dl class="facts"><dt>Owner</dt><dd>${esc(c.owner || '—')}</dd><dt>Now</dt><dd>${esc(c.current_action || (c.state === 'done' ? 'finished' : '—'))}</dd>
      <dt>Made</dt><dd>${Object.keys(outs).length ? Object.entries(outs).map(([k, v]) => `${v} ${esc(k)}`).join(', ') : 'nothing yet'}</dd>
      ${c.blocker ? `<dt class="warn">Waiting</dt><dd class="warn">${esc(c.blocker)}</dd>` : ''}
      <dt>Next</dt><dd>${esc(c.next_trigger || '—')}</dd><dt>Last progress</dt><dd>${esc(c.last_useful_progress || '—')}</dd></dl></div>`;
}
function todayCard(d) {
  const h = d && d.holdings;
  if (!h) return '';
  const dayPct = h.investable ? h.day_change / (h.investable - h.day_change) : null;
  return `<div class="card"><span class="lbl">Today</span><span class="num money" style="font-size:24px;font-weight:600">${rs(h.net_worth)}</span>
    <span class="small">Day <b class="num ${ud(h.day_change)}">${rs(h.day_change, true)} (${pct(dayPct, 2, true)})</b></span>
    <span class="tiny muted">${h.today ? (h.today.source === 'kite' ? 'per Kite ' + esc(String(h.today.snapshot_at).replace('T', ' ')) : 'from statements to ' + esc(h.today.documents_to)) : ''}${h.stale ? ` · ${h.stale} stale price(s)` : ''}${h.fd_estimated ? ' · FD values ESTIMATED' : ''}</span>
    <a href="#/portfolio/overview" class="small">Portfolio</a></div>`;
}
function railHtml(h, inv, cmd, sys) {
  const working = (inv || []).filter((c) => !['done'].includes(c.state));
  const done = (inv || []).filter((c) => c.state === 'done').slice(0, 2);
  const qs = h.questions || [];
  const others = (sys && sys.needs ? sys.needs.items : []).filter((i) => !qs.length || !String(i.agent || '').includes('question'));
  return `<div class="stack">
    <div class="card"><div class="row" style="justify-content:space-between"><span class="lbl">Working on</span><a href="#/research/work" class="small">All</a></div>
      ${working.length ? working.map(missionCard).join('') : '<span class="small muted">Nothing running. Ask for an investigation, or let it find its own.</span>'}${done.map(missionCard).join('')}</div>
    <div class="card"><div class="row" style="justify-content:space-between"><span class="lbl">Needs you</span><span class="small ${qs.length || others.length ? 'warn' : 'up'}">${qs.length || others.length ? (qs.length + others.length) + ' open' : 'nothing'}</span></div>
      ${qs.slice(0, 4).map((q) => `<div style="background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:9px 11px;display:flex;flex-direction:column;gap:6px">
        <span style="font-size:13px;line-height:1.45">${esc(q.text.length > 260 ? q.text.slice(0, 258) + '…' : q.text)}</span><span class="tiny muted">${esc(q.agent)} · ${esc(q.at)}</span>
        <div class="row"><input class="inp" id="qa${q.id}" placeholder="Your answer"><button class="btn" data-answer="${q.id}">Answer</button></div></div>`).join('')}
      ${qs.length > 4 ? `<span class="tiny muted">and ${qs.length - 4} more in Inbox and files</span>` : ''}
      ${others.slice(0, 3).map((i) => `<div class="item"><span class="dot" style="background:var(--warn)"></span><div style="font-size:13px">${esc(i.title)}<div class="tiny muted"><a href="${i.go === 'settings' ? '#/settings' : '#/inbox'}">open</a></div></div></div>`).join('')}
      ${!qs.length && !others.length ? '<span class="small muted">Nothing is waiting on you.</span>' : ''}</div>
    ${todayCard(cmd)}
    ${h.policy ? `<div class="card"><span class="lbl">Spending</span><span class="small">${h.policy.policy === 'acceptance' ? `Acceptance window: Rs ${num(h.policy.window.spent, 0)} of Rs ${num(h.policy.window.cap, 0)} until ${esc(h.policy.window.until.slice(0, 10))}` : `This month Rs ${num(h.policy.month_spent, 0)} of Rs ${num(h.policy.cap, 0)}`}</span>
      <div class="bar" style="height:6px"><i style="width:${Math.min(100, (h.policy.window ? h.policy.window.spent / h.policy.window.cap : h.policy.month_spent / (h.policy.cap || 1)) * 100).toFixed(1)}%"></i></div>
      <a href="#/system/limits" class="small">Every limit in force</a></div>` : ''}</div>`;
}
async function renderAssistant(h, inv, cmd, sys) {
  const screen = $('screen');
  if (!$('thread')) {
    screen.innerHTML = `<div class="asst"><section class="card" style="padding:12px 14px"><div class="thread" id="thread"></div>
      <div class="composer"><input type="file" id="chatFile" multiple style="display:none"><button class="btn" id="attachBtn" aria-label="Attach a file" title="Attach files or paste a screenshot (Ctrl+V): read on this PC, shown in Inbox and files">⎘</button>
        <label for="chatIn" style="position:absolute;left:-9999px">Your message</label>
        <textarea id="chatIn" rows="1" placeholder="Ask, discuss, or give it work… (Enter sends, Shift+Enter for a new line)"></textarea><button class="btn primary" id="sendBtn">Send</button></div>
      <span class="tiny muted">Local first. It never places an order or changes a target or limit. Anything that leaves this PC passes the privacy check; numbers it writes must come from a tool.</span></section>
      <aside id="arail"></aside></div>`;
    const inp = $('chatIn');
    inp.value = S.draft || '';
    inp.oninput = () => { S.draft = inp.value; inp.style.height = 'auto'; inp.style.height = Math.min(160, inp.scrollHeight) + 'px'; };
    inp.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAssistant(); } };
    inp.onpaste = (e) => { const fs = pastedFiles(e); if (fs.length) { e.preventDefault(); attachToAssistant(fs); } };
    $('sendBtn').onclick = () => sendAssistant();
    $('attachBtn').onclick = () => $('chatFile').click();
    $('chatFile').onchange = () => attachToAssistant([...$('chatFile').files]);
    inp.focus();
  }
  const th = $('thread'), near = th.scrollHeight - th.scrollTop - th.clientHeight < 80;
  const html = threadHtml(h.messages);
  if (S.threadHtml !== html) { th.innerHTML = html; S.threadHtml = html; if (near || !S.threadSeen) th.scrollTop = th.scrollHeight; S.threadSeen = true; }
  /* the right rail is repainted unless an answer is being typed in it */
  const a = document.activeElement;
  if (a && /^qa\d+$/.test(a.id) && a.value) S.deferred = true;                  // an answer is being typed: the rail is drawn again when he leaves the box
  else {
    const keep = {}; document.querySelectorAll('#arail input[id^="qa"]').forEach((i) => { if (i.value) keep[i.id] = i.value; });
    $('arail').innerHTML = railHtml(h, inv, cmd, sys);
    Object.entries(keep).forEach(([id, v]) => { const i = $(id); if (i) i.value = v; });
    document.querySelectorAll('[data-mission]').forEach((c) => { c.onclick = () => showMission(Number(c.dataset.mission)); });
    document.querySelectorAll('[data-answer]').forEach((b) => { b.onclick = async () => { const v = $('qa' + b.dataset.answer).value.trim(); if (!v) return; await post(`/api/questions/${b.dataset.answer}/answer`, { text: v }); load(true); }; });
  }
  th.querySelectorAll('[data-sugg]').forEach((b) => { b.onclick = () => sendAssistant(b.dataset.sugg); });
  th.querySelectorAll('[data-report]').forEach((b) => { b.onclick = () => openReport(b.dataset.report); });
  S.asst = h;
}
async function sendAssistant(text, context) {
  const inp = $('chatIn') || $('dockIn');
  const q = (text ?? (inp ? inp.value : '')).trim();
  if (!q) return;
  if (text === undefined && inp) { inp.value = ''; S.draft = ''; inp.style.height = 'auto'; }
  try { await post('/api/assistant', { text: q, context: context || '' }); } catch (e) { alert(e.message); }
  load(true); dockRefresh();
}
async function attachToAssistant(files) {
  const h = S.asst || await api('/api/assistant');
  await uploadAll(files, { chat: h.chat_id });
}
async function showMission(cid) {
  const d = await api('/api/cases/' + cid);
  const m = d.mission;
  const ans = m && m.answer;
  const box = document.createElement('dialog');
  box.style.cssText = 'max-width:820px;width:92vw;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:12px;padding:18px';
  box.innerHTML = `<div style="display:flex;flex-direction:column;gap:10px"><b style="font-size:16px">${esc(d.question || (m && m.goal) || '')}</b>
    ${m ? `<div class="row wrapr" style="gap:6px">${pill((STATE_WORD[m.state] || ['wait'])[0], (STATE_WORD[m.state] || ['', m.state])[1])}<span class="chip">snapshot ${esc(m.snapshot)}</span><span class="chip">review round ${m.round}</span></div>
      <div class="small"><b>Tasks</b><ul>${m.tasks.map((t) => `<li>#${t.id} ${esc(t.role)}: ${esc(t.status)}${t.waiting_on ? ' (waiting for ' + esc(t.waiting_on) + ')' : ''}</li>`).join('')}</ul></div>
      <div class="small"><b>What it made</b><ul>${m.outputs.map((o) => `<li>${esc(o.kind)} ${esc(o.ref)} ${esc(o.detail || '')} <span class="tiny muted">(task #${o.task})</span></li>`).join('') || '<li>nothing yet</li>'}</ul></div>
      ${m.blocker ? `<div class="note"><span>${esc(m.blocker)}</span></div>` : ''}
      ${ans ? `<div class="small"><b>Answer</b><div style="white-space:pre-wrap;line-height:1.55;margin-top:4px">${fmt(ans.answer)}</div><div style="margin-top:6px"><b>What could invalidate it:</b> ${esc(ans.limitations)}</div><div><b>Watching next:</b> ${esc(ans.monitor_next)}</div></div>` : ''}` : ''}
    <div class="small"><b>Evidence</b><ul>${(d.evidence || []).map((e) => `<li><b>${esc(e.stance)}</b> ${esc(e.source_kind || '')}: ${esc(e.text)} <span class="tiny muted">(published ${esc(String(e.published || e.event || 'undated').slice(0, 10))})</span></li>`).join('') || '<li>none yet</li>'}</ul></div>
    <div class="small"><b>Calculations</b><ul>${(d.calculations || []).map((k) => `<li>#${k.id} ${esc(k.status)}${k.contained ? ', in the sandbox' : ''}: ${esc(JSON.stringify(k.result).slice(0, 300))}</li>`).join('') || '<li>none</li>'}</ul></div>
    <div class="small"><b>Independent reviews</b><ul>${(d.reviews || []).map((r) => `<li>${esc(r.outcome || 'process check')}: ${esc((r.note || (r.flags || []).join('; ') || '').slice(0, 400))}</li>`).join('') || '<li>none yet</li>'}</ul></div>
    <div class="row" style="gap:8px">${m && m.state === 'blocked' ? '<button class="btn warnb" id="mRetry">Try the failed steps again</button>' : ''}<button class="btn" id="mClose">Close</button></div></div>`;
  document.body.appendChild(box);
  box.querySelector('#mClose').onclick = () => { box.close(); box.remove(); };
  const rb = box.querySelector('#mRetry');
  if (rb) rb.onclick = async () => { try { await post(`/api/investigations/${cid}/retry`); } catch (e) { alert(e.message); } box.close(); box.remove(); load(true); };
  box.showModal();
}

/* ---------- the assistant, one click away on every other screen ---------- */
function dockHtml() {
  if (S.screen === 'assistant') return '';
  const msgs = ((S.asst && S.asst.messages) || []).slice(-8);
  return `<button class="btn primary dockbtn" id="dockBtn">${S.dockOpen ? 'Close' : 'Ask the assistant'}</button>
    ${S.dockOpen ? `<div class="card dockpanel"><div class="row" style="justify-content:space-between"><b>Assistant</b><a href="#/assistant" class="small">Open fully</a></div>
      <div class="thread" id="dockThread">${threadHtml(msgs)}</div>
      <div class="composer"><textarea id="dockIn" rows="1" placeholder="About this screen, or anything…"></textarea><button class="btn primary" id="dockSend">Send</button></div></div>` : ''}`;
}
function paintDock() {
  const d = $('dock');
  if (!d) return;
  const html = dockHtml();
  const typed = $('dockIn') ? $('dockIn').value : '';
  if (d.dataset.h === html) return;
  d.dataset.h = html; d.innerHTML = html;
  if ($('dockIn')) { $('dockIn').value = typed; $('dockIn').onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); dockSend(); } }; if (S.dockOpen) $('dockIn').focus(); }
  if ($('dockBtn')) $('dockBtn').onclick = () => { S.dockOpen = !S.dockOpen; if (S.dockOpen) dockRefresh(); else paintDock(); };
  if ($('dockSend')) $('dockSend').onclick = dockSend;
  const t = $('dockThread'); if (t) { t.scrollTop = t.scrollHeight; t.querySelectorAll('[data-sugg]').forEach((b) => { b.onclick = () => dockSend(b.dataset.sugg); }); }
}
async function dockSend(text) {
  const inp = $('dockIn');
  const q = (text ?? (inp ? inp.value : '')).trim();
  if (!q) return;
  if (inp) inp.value = '';
  try { await post('/api/assistant', { text: q, context: `the ${TITLES[S.screen] || S.screen} screen${S.sub ? ', ' + S.sub : ''}` }); } catch (e) { alert(e.message); }
  dockRefresh();
}
async function dockRefresh() {
  try { S.asst = await api('/api/assistant'); } catch (e) { return; }
  const d = $('dock'); if (d) d.dataset.h = '';
  paintDock();
}
setInterval(() => { if (S.dockOpen && S.screen !== 'assistant') dockRefresh(); }, 4000);

/* ---------- research: what the workers did ---------- */
function expRow(e) {
  return `<tr><td>#${e.id} ${esc(String(e.hypothesis).slice(0, 110))}</td><td>${esc(e.contract || 'index_timing')}</td><td>${esc(e.status)}</td><td>${(e.candidates ?? 0)}</td><td class="small" style="text-align:left">${esc(String(e.why || e.decision_why || '').slice(0, 160))}</td></tr>`;
}
function renderInvestigations(d) {
  const inv = d.investigations || [], ex = d.experiments || [], calcs = d.calcs || [];
  $('screen').insertAdjacentHTML('beforeend', `<div class="cols">
    <section class="stack" style="flex:2 1 520px">
      <div class="card"><div class="row" style="justify-content:space-between"><span class="lbl">Investigations</span><span class="small muted">${inv.length}</span></div>
        <div class="row"><input class="inp" id="invGoal" placeholder="Something to investigate, in your words…"><button class="btn primary" id="invGo">Investigate</button></div>
        <span class="tiny muted">A coordinator plans it, research and quant workers do it, an independent reviewer checks it. It runs in the background and reports in the Assistant.</span></div>
      ${inv.map(missionCard).join('') || '<div class="card"><span class="small muted">None yet.</span></div>'}
    </section>
    <section class="stack" style="flex:1 1 380px">
      <div class="card"><span class="lbl">Strategy experiments (counted: the bar rises with every variant)</span>
        <div class="scroll"><table><thead><tr><th>Question</th><th>Contract</th><th>Status</th><th>Tries</th><th>Why</th></tr></thead><tbody>${ex.map(expRow).join('') || '<tr><td colspan="5" class="muted">None registered.</td></tr>'}</tbody></table></div>
        <span class="tiny muted">${d.tests_counted !== undefined ? d.tests_counted + ' variants tested in all. ' : ''}A rejection is a result. A hypothesis no evaluation contract fits is shown as unsupported and is never run.</span></div>
      <div class="card"><span class="lbl">Calculations and scenarios (reproducible)</span>
        ${calcs.map((c) => `<div class="item"><span class="dot" style="background:${c.status === 'checked' ? 'var(--up)' : 'var(--warn)'}"></span><div style="min-width:0"><div class="small">#${c.id} ${esc(String(c.question).slice(0, 110))}</div><div class="tiny muted">${esc(c.status)} · ${c.trusted ? 'trusted code' : 'sandbox'} · case ${c.case_id ?? '—'} · ${esc(c.at)}</div></div></div>`).join('') || '<span class="small muted">None yet.</span>'}</div>
    </section></div>`);
  document.querySelectorAll('[data-mission]').forEach((c) => { c.onclick = () => showMission(Number(c.dataset.mission)); });
  $('invGo').onclick = async () => { const g = $('invGoal').value.trim(); if (!g) return; try { await post('/api/investigations', { goal: g }); $('invGoal').value = ''; load(true); } catch (e) { alert(e.message); } };
}

/* ---------- system: is it working, what is in force ---------- */
function renderLimits(p) {
  const w = p.window;
  const rows = p.limits.map((l) => `<tr><td style="text-align:left">${esc(l.limit)}</td><td>${esc(String(l.value))}</td><td style="text-align:left" class="small">${esc(l.set_in)}</td><td style="text-align:left" class="small muted">${esc(l.why)}</td><td>${l.live ? 'at once' : 'at restart'}</td><td class="${l.state === 'in force' ? '' : 'warn'}">${esc(l.state)}</td></tr>`).join('');
  $('screen').insertAdjacentHTML('beforeend', `<div class="card"><div class="row wrapr" style="justify-content:space-between"><span class="lbl">Spending policy now: ${esc(p.policy)}</span><span class="small muted">${esc(p.channel)} channel · brain set to ${esc(p.mode)}</span></div>
    ${w ? `<div class="small">Acceptance window ${esc(w.since)} to ${esc(w.until)}: spent <b class="num">Rs ${num(w.spent, 0)}</b> of <b class="num">Rs ${num(w.cap, 0)}</b> (Rs ${num(w.left, 0)} left). ${esc(w.note)}</div><div class="bar"><i style="width:${Math.min(100, w.spent / w.cap * 100).toFixed(1)}%"></i></div>`
      : `<div class="small">Normal policy: this month Rs ${num(p.month_spent, 0)} of Rs ${num(p.cap, 0)}.</div>`}
    <span class="tiny muted">Edits to api_budget.toml [policy] and [acceptance] take effect on the next paid call; nothing needs a restart. Inside the window only its own cap holds; it ends by itself.</span></div>
    <div class="card"><span class="lbl">Every limit that can refuse a paid call</span><div class="scroll"><table style="min-width:820px"><thead><tr><th>Limit</th><th>Value</th><th>Set in</th><th>Why</th><th>Edit takes effect</th><th>State</th></tr></thead><tbody>${rows}</tbody></table></div></div>`);
}
function systemNowHtml(s, d) {
  return `${systemHero(s)}<div class="cols">${needsCard(s)}${workCard(s)}${syncCard(s)}</div><div class="cols">${researchCard(s)}${changedCard(s)}${readinessCard(s)}${coverageCard(s)}</div>`;
}

/* ---------- portfolio: opens on the figures ---------- */
function renderPortfolioOverview(d) {
  const h = d.holdings, mc = d.montecarlo || {}, m = d.market || {};
  const heads = (d.notifications || []).filter((n) => n.kind !== 'question');
  const dayPct = h.investable ? h.day_change / (h.investable - h.day_change) : null;
  const rows = h.rows.slice(0, 14);
  $('screen').insertAdjacentHTML('beforeend', `${tickerStrip(d.tickers || [])}${freshBanner(h.today, d.kite)}
  <div class="cols"><section class="stack" style="flex:1 1 330px">
      <div class="card"><span class="lbl">Net worth</span><span class="num money" style="font-size:34px;font-weight:600">${rs(h.net_worth)}</span>
        <div class="row wrapr small" style="gap:16px"><span>Today <b class="num ${ud(h.day_change)}">${rs(h.day_change, true)} (${pct(dayPct, 2, true)})</b></span><span>Unrealised <b class="num ${ud(h.unrealised)}">${rs(h.unrealised, true)}</b></span></div>
        <span class="tiny muted">investable ${rs(h.investable)} · reserve FDs ${rs(h.reserve)} · cash ${rs(h.cash)}${h.stale ? ` · ${h.stale} stale price(s)` : ''}${h.fd_estimated ? ' · FD values ESTIMATED' : ''}</span>
        <span class="tiny ${h.today && h.today.source === 'kite' ? 'muted' : 'warn'}">${h.today ? (h.today.source === 'kite' ? `holdings and cash per Kite ${esc(String(h.today.snapshot_at).replace('T', ' '))} · statements to ${esc(h.today.documents_to)}` : `from statements to ${esc(h.today.documents_to)}`) : ''}</span></div>
      ${mixPanel(d.mix, h)}
      <div class="card"><span class="lbl">Your 35% fall limit</span>
        <div style="font-size:13px;line-height:1.55">Chance of a fall beyond 35% on any day within a year: <b class="num">${esc((mc.tail || {}).text || 'not run yet')}</b> <span class="muted">${mc.paths ? `(${num(mc.paths, 0)} paths, history ${esc(mc.history)}, run ${esc(String(mc.at).slice(0, 16).replace('T', ' '))})` : ''}</span></div>
        <div style="font-size:13px">Market (Nifty) below its high: <b class="num">${pct(m.drawdown)}</b> · dip rule ${m.dip_active ? '<b class="warn">active</b>' : 'not triggered'}</div>
        <div class="row"><button class="btn" id="mcRun">Run the simulation now</button><span class="tiny muted">ESTIMATE from past joint returns</span></div></div></section>
    <section class="card" style="flex:2 1 560px"><div class="row" style="justify-content:space-between"><span class="lbl">Holdings</span><span class="small muted">${h.rows.length} positions · <a href="#/portfolio/holdings">all and lots</a></span></div>
      <div class="scroll"><table style="min-width:640px"><thead><tr><th>Name</th><th>Qty</th><th>Price</th><th>Day</th><th>Value</th><th>Weight</th><th>P&amp;L</th><th>20 sessions</th></tr></thead><tbody>
      ${rows.map((r) => `<tr><td><b>${esc(r.symbol || r.isin)}</b><br><span class="tiny muted">${esc(r.sector || r.bucket || '')}</span></td><td class="num">${num(r.qty, r.qty % 1 ? 3 : 0)}</td><td class="num">${num(r.price)}${r.price_kind === 'live' ? ' <span class="tiny up">live</span>' : ''}</td>
        <td class="num ${ud(r.change)}">${pct(r.change, 2, true)}</td><td class="num money">${rs(r.value)}</td><td class="num">${pct(r.weight)}</td><td class="num money ${ud(r.unrealised)}">${r.cost_unknown ? '<span class="chip warn" title="bought before the statements begin: its cost is not in your record. Add it in Setup (opening cost) and the gain appears">cost unknown</span>' : rs(r.unrealised, true)}</td><td>${spark(r.spark)}</td></tr>`).join('')}</tbody></table>
      ${h.cost_unknown && h.cost_unknown.holdings.length ? `<span class="tiny warn">${h.cost_unknown.holdings.length} holding(s) have no purchase record; their gain is unknown and left out of the totals above.</span>` : ''}</div></section>
    <section class="stack" style="flex:1 1 320px">
      <div class="card"><div class="row" style="justify-content:space-between"><span class="lbl">From your watch list</span><a href="#/portfolio/watch" class="small">All</a></div>
        ${(d.nudges || []).map((w) => `<div class="item">${vbadge(w.verdict)}<span class="small" style="min-width:0"><b>${esc(w.symbol)}</b> ${esc(w.text)}${w.price ? ` · now ${num(w.price)}` : ''}</span></div>`).join('') || '<span class="small muted">Being studied: zones appear after the first refresh.</span>'}</div>
      <div class="card"><div class="row" style="justify-content:space-between"><span class="lbl">Worth a look</span><span class="small muted">${heads.length}</span></div>
        ${heads.length ? heads.map((n) => `<div class="item"><span class="dot" style="background:${n.kind === 'held' ? 'var(--muted)' : 'var(--accent)'}"></span><div style="min-width:0"><div style="font-size:13px;line-height:1.4">${esc(n.text)}</div><div class="tiny muted">${esc(n.meta)} · ${esc(n.at)}</div></div></div>`).join('') : '<span class="small muted">Nothing new.</span>'}</div>
      <div class="card"><span class="lbl">Your notes for the system</span>
        <div class="row wrapr" style="gap:8px">${d.notes.length ? d.notes.map((n) => `<div class="note ${n.done ? 'done' : ''}"><button aria-label="Mark done" data-toggle="${n.id}">${n.done ? '✓' : '○'}</button><span>${esc(n.text)}</span><button aria-label="Remove note" data-del="${n.id}">×</button></div>`).join('') : '<span class="small muted">No notes.</span>'}</div>
        <div class="row"><label for="noteIn" class="small muted" style="white-space:nowrap">Add a note</label><input id="noteIn" class="inp" placeholder="e.g. Research a company before its results"><button class="btn" id="noteAdd">Add</button></div></div></section></div>`);
  const k2 = $('kiteLogin2'); if (k2) k2.onclick = kiteLogin;
  $('mcRun').onclick = async () => { await post('/api/montecarlo/run'); $('mcRun').textContent = 'Running… (a minute or two)'; };
  $('noteAdd').onclick = addNote; $('noteIn').onkeydown = (e) => { if (e.key === 'Enter') addNote(); };
  document.querySelectorAll('[data-toggle]').forEach((b) => { b.onclick = () => post(`/api/notes/${b.dataset.toggle}/toggle`).then(() => load(true)); });
  document.querySelectorAll('[data-del]').forEach((b) => { b.onclick = () => api(`/api/notes/${b.dataset.del}`, { method: 'DELETE' }).then(() => load(true)); });
  document.querySelectorAll('[data-isin]').forEach((b) => { b.onclick = () => { S.selected = b.dataset.isin; location.hash = '#/portfolio/holdings'; }; });
}
