/* Portfolio Lab, the redesigned screens (S68): the Assistant is home; Research shows what the workers did and what it rests on; System shows the limits in
   force and whether anything is stuck; Portfolio opens on the figures. Loaded after app.js (it reuses its helpers and the cards it already had). */
'use strict';

/* a safe, small formatter for the assistant's words: escape first, then **bold** and "- " bullets */
function fmt(text) {
  return esc(text || '').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/^- /gm, '• ');
}
const pill = (state, label) => `<span class="pillst st-${state}">${esc(label || state)}</span>`;
const STATE_WORD = { planning: ['working', 'planning'], awaiting_approval: ['wait', 'needs your yes'], working: ['working', 'working'], reviewing: ['working', 'being reviewed'], synthesising: ['working', 'writing the answer'], done: ['done', 'finished'], blocked: ['blocked', 'stuck'], declined: ['wait', 'declined'] };
/* what a task's state means, in words (S69): waiting always says for what and how it resumes; registered is not finished; merged is not stuck */
const TASK_WORD = { queued: 'ready to run', running: 'running now', waiting: 'waiting', retry: 'will try again', needs_approval: 'waits for your yes to the plan', done: 'done', failed: 'failed', dismissed: 'replaced or dropped', held: 'held' };
function taskWord(t) {
  const w = TASK_WORD[t.status] || t.status;
  if (t.status === 'waiting' || t.status === 'retry') return `${w}: ${t.resume || t.waiting_on || 'a retry'}`;
  return w;
}
function outputWord(o) {
  if (o.kind === 'experiment') return `experiment #${esc(o.ref)} ${o.detail === 'registered' ? 'REGISTERED, not yet run (no result)' : esc(o.detail || '')}`;
  if (o.kind === 'experiment_result') return `experiment #${esc(o.ref)} RESULT: ${esc(o.detail || '')}`;
  if (o.kind === 'proposal') return `recommendation #${esc(o.ref)} ${esc(o.detail || '')}`;
  return `${esc(o.kind)} ${esc(o.ref)} ${esc(o.detail || '')}`;
}
const LOG_WORD = { merged: 'merged (a copy of what was already there, not a problem)', covered: 'covered by another investigation (not stuck)', 'plan approved': 'plan approved', 'plan declined': 'plan declined', amendment: 'new instruction', 'trigger fired': 'a watch fired', arrival: 'new file', 'experiment finished': 'experiment finished', budget: 'budget', 'budget extra': 'more budget allowed', 'proposal executed': 'your trade is in the record' };

function subnavHtml(screen, sub) {
  const items = SUBS[screen];
  if (!items || (typeof RD !== 'undefined' && RD.handles(screen, sub))) return '';          // (S78: the redesigned pages carry their own links to the advanced ones)
  return `<div class="subnav" role="tablist">${items.map(([id, label]) => `<a href="#/${screen}/${id}" class="${sub === id ? 'on' : ''}">${esc(label)}</a>`).join('')}</div>`;
}

/* ---------- the assistant ---------- */
function bubble(m, prevQ) {
  const me = m.role === 'me', note = (m.mode || '').startsWith('note:') || m.channel === 'system';
  const pending = m.status === 'working' || m.status === 'queued';
  const steps = (m.route || []).filter((r) => r && r !== 'the system, unprompted').map((r) => `<span class="step">${esc(r)}</span>`).join('');
  const body = pending ? `<span class="warn">${esc(m.meta && m.meta.startsWith('working') ? m.meta : (m.text && m.text.endsWith('…') ? m.text : 'Working on it…'))}</span>` : fmt(m.text);
  const acts = (m.actions || []).length ? `<div class="row" style="gap:8px;margin-top:6px">${m.actions.map((a) => `<button class="btn ${a.id === 'yes' ? 'primary' : ''}" data-card="${m.id}" data-act="${esc(a.id)}">${esc(a.label || a.id)}</button>`).join('')}</div>` : '';
  const files = (m.attachments || []).length ? `<div class="tiny muted">${m.attachments.map((a) => '⎘ ' + esc(a.name)).join(' · ')}</div>` : '';
  return `<div class="bub ${me ? 'me' : note ? 'ai sys' : 'ai'}">
    ${!me && steps && !pending ? `<div class="steps">${steps}</div>` : ''}
    <div class="body">${note ? '<div class="tiny muted" style="margin-bottom:4px">from the system</div>' : ''}${body}${files}${acts}</div>
    ${m.report ? `<button class="btn" style="align-self:flex-start" data-report="${esc(m.report)}">Open the saved note</button>` : ''}
    ${m.status === 'failed' ? '<span class="tiny down">not answered</span>' : ''}
    <span class="tiny muted">${m.channel === 'telegram' ? '<span class="chip" title="sent from Telegram">Telegram</span> ' : ''}${esc(!me && !note && !pending ? m.meta || '' : '')}${!me && !note && m.meta && !pending ? ' · ' : ''}${esc(m.at || '')}</span></div>`;
}
function threadHtml(msgs) {
  if (!msgs.length) {
    const asks = ['Is everything working, and what are you doing right now?', 'What needs me today?', 'How are the picks doing against the index so far?',
      'Compare putting 10 lakh in now, in 10 monthly parts, or keeping cash until a fall.', 'What does history say about selling an IPO allotment on listing day?'];
    return `<div style="margin:auto;display:flex;flex-direction:column;gap:12px;align-items:center;max-width:560px;text-align:center">
      <b style="font-size:17px">Talk to it like a colleague who never sleeps.</b>
      <span class="muted">It discusses ideas, answers from your reconciled record, runs calculations and scenarios, and can ask the strategist to look into something. What it finds comes back here.</span>
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
      <dt>Next</dt><dd>${esc(c.next_trigger || '—')}</dd><dt>Last progress</dt><dd>${esc(c.last_useful_progress || '—')}</dd>
      <dt>Instructions</dt><dd>version ${c.instruction_version || '—'}${c.awaiting_approval ? ' <b class="warn">· a plan waits for your yes</b>' : ''}</dd>
      ${(c.triggers || []).filter((t) => t.status === 'active').length ? `<dt>Watching</dt><dd>${(c.triggers || []).filter((t) => t.status === 'active').map((t) => esc(t.describe)).join('; ')}</dd>` : ''}
      ${(c.experiments_pending || []).length ? `<dt class="warn">Experiment</dt><dd class="warn">${c.experiments_pending.map((e) => '#' + e.id + ' ' + esc(e.status)).join(', ')}: not finished, so no conclusion yet</dd>` : ''}</dl>
    ${c.awaiting_approval ? `<div class="row" style="gap:8px"><button class="btn primary" data-approve="${c.case_id}">Approve the plan</button><button class="btn" data-decline="${c.case_id}">Decline</button></div>` : ''}</div>`;
}
function wireMissionButtons(root) {
  (root || document).querySelectorAll('[data-approve]').forEach((b) => { b.onclick = async (e) => { e.stopPropagation(); try { await post(`/api/investigations/${b.dataset.approve}/approve`, { note: '' }); } catch (x) { alert(x.message); } load(true); }; });
  (root || document).querySelectorAll('[data-decline]').forEach((b) => { b.onclick = async (e) => { e.stopPropagation(); try { await post(`/api/investigations/${b.dataset.decline}/decline`, { note: '' }); } catch (x) { alert(x.message); } load(true); }; });
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
function paperCard(p) {
  if (!p || !p.started) return '';
  return `<div class="card"><span class="lbl">The account</span><span class="num money" style="font-size:24px;font-weight:600">${rs(p.value)}</span>
    <span class="tiny muted">fake money, the system's own account · cash ${rs(p.cash)}</span><a href="#/account" class="small">Account</a></div>`;
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
        <div class="row"><input class="inp" id="qa${q.id}" placeholder="Answer, paste a link or a file path"><button class="btn" data-attach="${q.id}" aria-label="Attach a file to this answer" title="Attach a file (a PDF, a sheet, a screenshot)">⎘</button><button class="btn" data-answer="${q.id}">Answer</button></div>
        <input type="file" id="qf${q.id}" multiple style="display:none"></div>`).join('')}
      ${qs.length > 4 ? `<span class="tiny muted">and ${qs.length - 4} more: ask me about them in the chat</span>` : ''}
      ${others.slice(0, 3).map((i) => `<div class="item"><span class="dot" style="background:var(--warn)"></span><div style="font-size:13px">${esc(i.title)}<div class="tiny muted"><a href="${i.go === 'settings' ? '#/settings' : '#/assistant'}">open</a></div></div></div>`).join('')}
      ${!qs.length && !others.length ? '<span class="small muted">Nothing is waiting on you.</span>' : ''}</div>
    ${paperCard(h.paper)}
    ${h.policy ? `<div class="card"><span class="lbl">Spending</span><span class="small">${h.policy.policy === 'acceptance' ? `Acceptance window: Rs ${num(h.policy.window.spent, 0)} of Rs ${num(h.policy.window.cap, 0)} until ${esc(h.policy.window.until.slice(0, 10))}` : `This month Rs ${num(h.policy.month_spent, 0)} of Rs ${num(h.policy.cap, 0)}`}</span>
      <div class="bar" style="height:6px"><i style="width:${Math.min(100, (h.policy.window ? h.policy.window.spent / h.policy.window.cap : h.policy.month_spent / (h.policy.cap || 1)) * 100).toFixed(1)}%"></i></div>
      <a href="#/system/limits" class="small">Every limit in force</a></div>` : ''}</div>`;
}
async function renderAssistant(h, inv, cmd, sys) {
  const screen = $('screen');
  if (!$('thread')) {
    screen.innerHTML = `<div class="asst"><section class="card" style="padding:12px 14px"><div class="row" id="chatBar" style="gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px"></div><div class="thread" id="thread"></div>
      <div class="row wrapr" id="stageTray" style="gap:6px;margin:6px 0 0"></div>
      <div class="row wrapr" style="gap:8px;margin:6px 0 0;align-items:center"><span class="tiny muted" id="queueLine"></span><span style="flex:1"></span>
        <label class="tiny muted" for="modelPick">Model</label><select id="modelPick" class="inp" style="width:auto"></select>
        <label class="tiny muted" for="thinkPick">Thinking</label><select id="thinkPick" class="inp" style="width:auto"></select></div>
      <div class="composer"><input type="file" id="chatFile" multiple style="display:none"><button class="btn" id="attachBtn" aria-label="Attach files" title="Attach one or more files (PDF, Excel, CSV, a screenshot), then write and press Send">⎘</button>
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
    $('chatFile').onchange = () => { attachToAssistant([...$('chatFile').files]); $('chatFile').value = ''; };
    paintStage();
    const sec = screen.querySelector('.asst > section');             // S77: drop a file anywhere on the conversation; it is read here and the model sees what was read
    sec.ondragover = (e) => { e.preventDefault(); sec.classList.add('dropping'); };
    sec.ondragleave = () => sec.classList.remove('dropping');
    sec.ondrop = (e) => { e.preventDefault(); sec.classList.remove('dropping'); const fs = [...(e.dataTransfer ? e.dataTransfer.files : [])]; if (fs.length) attachToAssistant(fs); };
    inp.focus();
  }
  const bar = $('chatBar');                                       // S78: New chat, and the earlier ones
  const barHtml = `<button class="btn" id="newChat" title="Start a clean conversation; the old one is kept under Earlier">+ New chat</button>`
    + ((h.earlier || []).length ? `<span class="tiny muted">Earlier</span>` + h.earlier.map((e) => `<button class="btn" data-earlier="${e.id}" title="${esc(e.updated)}">${esc(e.title)}</button>`).join('') : '');
  if (bar.dataset.html !== barHtml) {
    bar.innerHTML = barHtml; bar.dataset.html = barHtml;
    $('newChat').onclick = async () => { try { await post('/api/assistant/new', {}); } catch (e) { alert(e.message); } S.threadHtml = ''; S.threadSeen = false; load(true); };
    bar.querySelectorAll('[data-earlier]').forEach((b) => { b.onclick = async () => { try { await post('/api/assistant/open/' + b.dataset.earlier, {}); } catch (e) { alert(e.message); } S.threadHtml = ''; S.threadSeen = false; load(true); }; });
  }
  paintPicker(h);
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
    wireMissionButtons($('arail'));
    document.querySelectorAll('[data-attach]').forEach((b) => { const q = b.dataset.attach; b.onclick = () => $('qf' + q).click(); $('qf' + q).onchange = async () => { const fs = [...$('qf' + q).files]; if (!fs.length) return; await uploadToChat(fs); await post(`/api/questions/${q}/answer`, { text: 'Attached: ' + fs.map((f) => f.name).join(', ') }); load(true); }; });
    document.querySelectorAll('[data-answer]').forEach((b) => { b.onclick = async () => { const v = $('qa' + b.dataset.answer).value.trim(); if (!v) return; await post(`/api/questions/${b.dataset.answer}/answer`, { text: v }); load(true); }; });
  }
  th.querySelectorAll('[data-sugg]').forEach((b) => { b.onclick = () => sendAssistant(b.dataset.sugg); });
  th.querySelectorAll('[data-card]').forEach((b) => { b.onclick = async () => { try { await post(`/api/assistant/messages/${b.dataset.card}/action`, { action: b.dataset.act }); } catch (e) { alert(e.message); } S.threadHtml = ''; load(true); }; });
  th.querySelectorAll('[data-report]').forEach((b) => { b.onclick = () => openReport(b.dataset.report); });
  S.asst = h;
}
/* S85: the model and thinking picker (Auto by default) and the queue line ("Working on what you sent") */
function paintPicker(h) {
  const m = $('modelPick'), t = $('thinkPick');
  if (!m || !t) return;
  const prefs = h.prefs || {}, models = h.models || [{ key: 'auto', label: 'Auto' }];
  const mh = models.map((x) => `<option value="${esc(x.key)}">${esc(x.label)}</option>`).join('');
  if (m.dataset.h !== mh) { m.innerHTML = mh; m.dataset.h = mh; m.onchange = () => { post('/api/assistant/prefs', { model: m.value }).catch((e) => alert(e.message)); }; }
  const th = ['auto'].concat(h.thinking || ['low', 'medium', 'high', 'max']).map((x) => `<option value="${esc(x)}">${esc(x === 'auto' ? 'Auto' : x)}</option>`).join('');
  if (t.dataset.h !== th) { t.innerHTML = th; t.dataset.h = th; t.onchange = () => { post('/api/assistant/prefs', { thinking: t.value === 'auto' ? null : t.value }).catch((e) => alert(e.message)); }; }
  if (document.activeElement !== m) m.value = prefs.model_key || 'auto';
  if (document.activeElement !== t) t.value = prefs.thinking || 'auto';
  const q = $('queueLine'); if (q) { const open = (h.queue || []); q.textContent = open.length ? 'Working on what you sent: ' + open.map((i) => i.progress || i.state).join('; ') : ''; }
}
async function sendAssistant(text, context) {
  const inp = $('chatIn') || $('dockIn');
  let q = (text ?? (inp ? inp.value : '')).trim();
  const staged = text === undefined && $('chatIn') ? (S.staged || []) : [];
  if (!q && !staged.length) return;
  const btn = $('sendBtn');
  let ids = [];
  if (staged.length) {
    if (btn) { btn.disabled = true; btn.textContent = `Sending ${staged.length} file${staged.length > 1 ? 's' : ''}…`; }
    for (const f of staged) {
      try { const r = await stageFile(f); if (r.upload_id) ids.push(r.upload_id); } catch (e) { alert(`${f.name}: ${e.message}`); }
    }
    if (btn) { btn.disabled = false; btn.textContent = 'Send'; }
    S.staged = []; paintStage();
  }
  if (text === undefined && inp) { inp.value = ''; S.draft = ''; inp.style.height = 'auto'; }
  try { await post('/api/assistant', { text: q, context: context || '', files: ids }); } catch (e) { alert(e.message); }
  load(true); dockRefresh();
}
async function stageFile(f) {                                          // S85: the file goes with the message; the intake checks it locally, then reads it
  const r = await fetch('/api/assistant/files', { method: 'POST', headers: { 'x-filename': encodeURIComponent(f.name) }, body: f });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
/* S78: files are staged in a tray and go WITH the message (any number of them): choose, write, press Send. */
function attachToAssistant(files) {
  S.staged = (S.staged || []).concat(files.filter((f) => !(S.staged || []).some((x) => x.name === f.name && x.size === f.size)));
  paintStage();
}
function paintStage() {
  const t = $('stageTray'); if (!t) return;
  const fs = S.staged || [];
  t.innerHTML = fs.map((f, i) => `<span class="chip" style="gap:6px">⎘ ${esc(f.name)} <span class="tiny muted">${f.size > 1048576 ? (f.size / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(f.size / 1024)) + ' KB'}</span> <button class="btn" data-unstage="${i}" aria-label="Remove ${esc(f.name)}" style="padding:0 6px;min-height:0">×</button></span>`).join('');
  t.querySelectorAll('[data-unstage]').forEach((b) => { b.onclick = () => { S.staged.splice(Number(b.dataset.unstage), 1); paintStage(); }; });
}
async function uploadToChat(files) {                                   // at once (an answer to one of its questions), not staged
  const h = S.asst || await api('/api/assistant');
  await uploadAll(files, { chat: h.chat_id });
}
async function settled(ids, ms = 90000) {                              // the files are read before the message goes, so the assistant finds what they say
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const d = await api('/api/inbox').catch(() => ({ items: [] }));
    const mine = (d.items || []).filter((i) => ids.includes(i.id));
    if (mine.length && mine.every((i) => (i.steps || []).every((s) => s.state !== 'todo') || ['in the graph', 'blocked', 'failed'].includes(i.status))) return;
    await new Promise((r) => setTimeout(r, 1500));
  }
}
async function showMission(cid) {
  const d = await api('/api/cases/' + cid);
  const m = d.mission;
  const ans = m && m.answer;
  const box = document.createElement('dialog');
  box.style.cssText = 'max-width:900px;width:94vw;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:12px;padding:18px;max-height:90vh;overflow:auto';
  const vers = (m && m.plan_versions) || [];
  const tasks = (m && m.tasks) || [];
  box.innerHTML = `<div style="display:flex;flex-direction:column;gap:10px"><b style="font-size:16px">${esc(d.question || (m && m.goal) || '')}</b>
    ${m ? `<div class="row wrapr" style="gap:6px">${pill((STATE_WORD[m.state] || ['wait'])[0], (STATE_WORD[m.state] || ['', m.state])[1])}<span class="chip">snapshot ${esc(m.snapshot)}</span><span class="chip">instructions v${m.instruction_version || '—'}</span><span class="chip">review round ${m.round}</span>
        <span class="chip">spent Rs ${num((m.budget || {}).spent, 0)} of Rs ${num((m.budget || {}).cap, 0)}</span>${ans && ans.review_verdict ? `<span class="chip">independent review: ${esc(ans.review_verdict)}</span>` : ''}</div>
      ${m.blocker ? `<div class="note"><span><b>Why it waits:</b> ${esc(m.blocker)}</span></div>` : ''}
      <div class="small"><b>Next trigger:</b> ${esc(m.next_trigger || '—')}</div>
      ${m.awaiting_approval ? `<div class="row" style="gap:8px"><button class="btn primary" data-approve="${cid}">Approve the plan (nothing is ordered; it starts the research and calculations)</button><button class="btn" data-decline="${cid}">Decline</button></div>` : ''}
      ${tasks.some((t) => t.wait_kind === 'budget') ? `<div class="row" style="gap:8px"><button class="btn primary" id="mRunNow">Run it now</button><span class="tiny muted">Skips today's day limit for this investigation only; the monthly cap and its own budget still hold.</span></div>` : ''}
      ${(m.blocker || '').includes('used Rs') ? `<div class="row" style="gap:8px"><button class="btn warnb" id="mMore">Allow Rs 150 more for this investigation</button><span class="tiny muted">The parked work resumes; nothing is thrown away.</span></div>` : ''}
      <div class="small"><b>Instructions and plan</b><ul>${vers.map((v) => `<li>v${v.version} <span class="chip">${esc(v.status)}</span> <span class="tiny muted">${esc(v.source)} · ${esc(v.at)}${v.decided_by ? ' · ' + esc(v.decided_by) : ''}</span><br>${esc(v.instruction)}${v.steps.length ? `<br><span class="tiny muted">steps: ${v.steps.map((x) => esc(x.key) + ' (' + esc(x.role) + ')').join(', ')}</span>` : ''}</li>`).join('') || '<li>none</li>'}</ul></div>
      <div class="small"><b>Tasks</b> <span class="tiny muted">(who owns what, what it waits for, which instruction version it ran under)</span>
        <div class="scroll"><table style="min-width:780px"><thead><tr><th>#</th><th>Owner</th><th>What</th><th>State</th><th>Depends on</th><th>v</th><th>Started</th><th>Finished</th><th>Made</th></tr></thead><tbody>
        ${tasks.map((t) => `<tr><td>${t.id}</td><td>${esc(t.role)}</td><td class="small" style="text-align:left">${esc(t.what || '')}</td><td class="small" style="text-align:left">${esc(taskWord(t))}</td><td>${(t.depends_on || []).map((x) => '#' + x).join(', ') || '—'}</td><td>${t.instruction_version ?? '—'}</td><td class="tiny">${esc((t.started || '').slice(11) || '—')}</td><td class="tiny">${esc((t.finished || '').slice(11) || '—')}</td><td class="tiny">${Object.entries(t.outputs || {}).map(([k, v]) => v + ' ' + esc(k)).join(', ') || '—'}</td></tr>`).join('')}</tbody></table></div></div>
      <div class="small"><b>What it made</b><ul>${m.outputs.map((o) => `<li>${outputWord(o)} <span class="tiny muted">(task #${o.task ?? 'the system'})</span></li>`).join('') || '<li>nothing yet</li>'}</ul></div>
      ${(m.triggers || []).length ? `<div class="small"><b>Watching (checked by the system)</b><ul>${m.triggers.map((t) => `<li>${esc(t.describe)} <span class="chip">${esc(t.status)}</span>${t.note ? ' ' + esc(t.note) : ''}</li>`).join('')}</ul></div>` : (ans ? '<div class="small warn">No executable watch is set: the "watching next" sentence below is only a sentence.</div>' : '')}
      ${ans ? `<div class="small"><b>Answer</b>${ans.change ? ` <span class="chip">${esc(ans.change)}</span>` : ''}<div style="white-space:pre-wrap;line-height:1.55;margin-top:4px">${fmt(ans.answer)}</div><div style="margin-top:6px"><b>What could invalidate it:</b> ${esc(ans.limitations)}</div><div><b>Watching next:</b> ${esc(ans.monitor_next)}</div></div>` : ''}` : ''}
    ${m ? `<div class="small"><b>Change an instruction</b> <span class="tiny muted">(applies at once; a change of the question or of a money rule waits for your yes)</span>
      <div class="row"><input class="inp" id="mAmend" placeholder="e.g. Also use a 0.5% charge on every trade"><button class="btn" id="mAmendGo">Send</button></div>
      <label class="tiny"><input type="checkbox" id="mScope"> this changes the question</label> <label class="tiny"><input type="checkbox" id="mFin"> this touches an amount or rule of my money</label></div>` : ''}
    <div class="small"><b>Evidence</b><ul>${(d.evidence || []).map((e) => `<li><b>${esc(e.stance)}</b> ${esc(e.source_kind || '')}: ${esc(e.text)} <span class="tiny muted">(published ${esc(String(e.published || e.event || 'undated').slice(0, 10))})</span></li>`).join('') || '<li>none yet</li>'}</ul></div>
    <div class="small"><b>Calculations</b><ul>${(d.calculations || []).map((k) => `<li>#${k.id} ${esc(k.status)}, ${esc(k.where || '')}: ${esc(JSON.stringify(k.result).slice(0, 300))}</li>`).join('') || '<li>none</li>'}</ul></div>
    <div class="small"><b>Independent reviews</b><ul>${(d.reviews || []).map((r) => `<li>${esc(r.outcome || 'process check')}: ${esc((r.note || (r.flags || []).join('; ') || '').slice(0, 400))}</li>`).join('') || '<li>none yet</li>'}</ul></div>
    <div class="small"><b>Why it changed</b><ul>${(d.log || []).slice(-14).map((l) => `<li><span class="tiny muted">${esc(l.at)}</span> ${esc(LOG_WORD[l.event] || l.event)}: ${esc(String(l.detail || '').slice(0, 180))}</li>`).join('')}</ul></div>
    <div class="row" style="gap:8px">${m && m.state === 'blocked' ? '<button class="btn warnb" id="mRetry">Try the failed steps again</button><button class="btn" id="mDrop">Drop this investigation</button>' : ''}<button class="btn" id="mClose">Close</button></div></div>`;
  document.body.appendChild(box);
  box.querySelector('#mClose').onclick = () => { box.close(); box.remove(); };
  const db = box.querySelector('#mDrop');
  if (db) db.onclick = async () => { try { await post(`/api/investigations/${cid}/drop`); } catch (e) { alert(e.message); } box.close(); box.remove(); load(true); };
  const rb = box.querySelector('#mRetry');
  if (rb) rb.onclick = async () => { try { await post(`/api/investigations/${cid}/retry`); } catch (e) { alert(e.message); } box.close(); box.remove(); load(true); };
  const rn = box.querySelector('#mRunNow');
  if (rn) rn.onclick = async () => { try { await post(`/api/investigations/${cid}/run_now`); } catch (e) { alert(e.message); } box.close(); box.remove(); load(true); };
  const more = box.querySelector('#mMore');
  if (more) more.onclick = async () => { try { await post(`/api/investigations/${cid}/allow`, { rupees: 150 }); } catch (e) { alert(e.message); } box.close(); box.remove(); load(true); };
  const am = box.querySelector('#mAmendGo');
  if (am) am.onclick = async () => { const t = box.querySelector('#mAmend').value.trim(); if (!t) return; try { await post(`/api/investigations/${cid}/amend`, { instruction: t, scope_change: box.querySelector('#mScope').checked, financial_policy: box.querySelector('#mFin').checked }); } catch (e) { alert(e.message); return; } box.close(); box.remove(); load(true); };
  wireMissionButtons(box);
  box.showModal();
}
/* a recommendation: the direction, the facts the system computed, what is missing, the review, and what he can do with it (S69) */
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
        <span class="tiny muted">Old investigations are kept here for the record. New questions go through the Assistant, which can ask the strategist; the answer comes back in the Assistant.</span></div>
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
  wireMissionButtons();
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

/* ---------- S75: working memory, house rules, the envelope and the scorecard ---------- */
const MEM_WORD = { method_reused: 'a checked calculation re-run', conclusion_cited: 'an earlier conclusion cited', contradiction_addressed: 'a contradiction taken up', question_closed: 'an open request closed' };
function memoryList(title, items, empty) {
  return `<div class="card"><span class="lbl">${esc(title)}</span>${items.length ? items.join('') : `<div class="small muted">${esc(empty)}</div>`}</div>`;
}
function renderMemory(d) {
  const e = d.effects_last_30_days || {};
  const used = e.investigations_that_used_it || 0, off = e.investigations_offered_memory || 0;
  const kinds = Object.entries(e.by_kind || {}).map(([k, n]) => `${esc(MEM_WORD[k] || k)} ${n}`).join(' · ') || 'nothing yet';
  const about = S.memAbout || '';
  const has = (d.subjects || []).length > 0;
  const concl = (d.conclusions || []).map((c) => `<div class="item"><span class="chip">${c.status === 'older' ? 'older view' : 'current'}</span>
      <div style="flex:1"><b>#${c.case_id}</b> ${esc(c.at || '')}: <b>${esc(c.decision)}</b> — ${esc(c.reason || c.answer || '')}
      ${c.review ? `<div class="tiny muted">independent review: ${esc(c.review)}</div>` : ''}${c.limits ? `<div class="tiny muted">limits then: ${esc(c.limits)}</div>` : ''}
      ${c.newer_case ? `<div class="tiny warn">investigation #${c.newer_case} is newer on the same subject</div>` : ''}</div></div>`);
  const contra = (d.contradictions || []).map((x) => `<div class="item"><div style="flex:1">${esc(x.text)}<div class="tiny muted">${esc(x.at || '')}${x.after_conclusion ? ' · came after the conclusion' : ''}</div></div></div>`);
  const methods = (d.methods || []).map((m) => `<div class="item"><div style="flex:1"><b>${esc(m.tool)}</b> (${esc(m.params)})<div class="tiny muted">calculation #${m.calc_id} in investigation #${m.case_id} · ${esc(m.how)}</div></div></div>`);
  const changed = (d.changed || []).map((x) => `<div class="item"><div style="flex:1">${esc(x)}</div></div>`);
  const open = (d.open || []).map((x) => `<div class="item"><div style="flex:1">${esc(x.what)}</div></div>`);
  $('screen').insertAdjacentHTML('beforeend', `<div class="cols"><section class="stack" style="flex:2 1 560px">
      <div class="card"><span class="lbl">Does memory change the work?</span>
        <div style="font-size:26px;font-weight:600;margin:4px 0">${used} of ${off}</div>
        <div class="small muted">recent investigations were offered something from memory and used it (last ${e.days || 30} days)</div>
        <div class="tiny muted" style="margin-top:4px">${kinds}</div>
        <div class="tiny muted" style="margin-top:4px">Counted by what the work really did with it, not by how much is stored.</div></div>
      <div class="card"><span class="lbl">Ask memory about a subject</span>
        <div class="row" style="gap:6px;margin-top:6px"><input id="memAbout" placeholder="a company, a sector, a theme or a question" value="${esc(about)}" style="flex:1"><button class="btn primary" id="memGo">Recall</button></div></div>
      ${has ? '' : (about ? '<div class="card"><span class="small muted">Nothing earlier is recorded on that subject.</span></div>' : '')}
      ${has ? memoryList('What was concluded before, and why', concl, 'Nothing was concluded before.') : ''}
      ${has ? memoryList('What goes against it', contra, 'Nothing has come up against it.') : ''}
      ${has ? memoryList('Already checked (re-run, not rewritten)', methods, 'No checked calculation yet.') : ''}
      ${has ? memoryList('What changed since', changed, 'Nothing recorded.') : ''}
      ${has ? memoryList('Still open', open, 'Nothing open.') : ''}</section></div>`);
  const go = () => { S.memAbout = $('memAbout').value.trim(); load(true); };
  $('memGo').onclick = go;
  $('memAbout').onkeydown = (ev) => { if (ev.key === 'Enter') go(); };
}
function renderRules(rl, env, sc) {
  const act = (rl.active || []).map((r) => `<div class="item"><div style="flex:1"><b>${esc(r.name)}</b> <span class="chip">${esc(r.kind.replace(/_/g, ' '))}</span> <span class="tiny muted">v${r.version} · ${esc(String(r.at).slice(0, 10))}</span>
      <div class="small">${esc(r.text)}</div></div><button class="btn" data-undo="${r.rule_id}">Undo</button></div>`);
  const wait = (rl.waiting || []).map((r) => `<div class="item"><div style="flex:1"><b>${esc(r.name)}</b> <span class="chip warn">waits for your yes</span>
      <div class="small">${esc(r.text)}</div><div class="tiny muted">About money, so it applies only after you say yes.</div></div>
      <button class="btn primary" data-rdec="yes" data-rid="${r.rule_id}">Yes</button><button class="btn" data-rdec="no" data-rid="${r.rule_id}">No</button></div>`);
  const trows = (sc.table || []).map((t) => `<tr><td>${esc(t.action)}</td><td>${esc((t.market_state || '').replace(/_/g, ' '))}</td><td>${t.n}</td><td>${t.good}</td>
      <td>${t.rate != null ? (t.rate * 100).toFixed(0) + '%' : '<span class="muted">' + esc(t.note || '') + '</span>'}</td><td>${t.skeptical_rate != null ? (t.skeptical_rate * 100).toFixed(0) + '%' : ''}</td></tr>`);
  const props = (sc.proposals || []).slice(0, 12).map((p) => `<div class="item"><div style="flex:1"><b>Proposal #${p.proposal_id}</b>: ${esc(p.verdict)}
      <div class="tiny muted">${(p.horizons || []).map((h) => `${h.days} days ${esc(h.outcome)}`).join(' · ')}</div></div></div>`);
  $('screen').insertAdjacentHTML('beforeend', `<div class="cols"><section class="stack" style="flex:1 1 460px">
      <div class="card"><div class="row" style="justify-content:space-between"><span class="lbl">House rules</span><span class="tiny muted">version ${rl.version}</span></div>
        ${act.join('') || '<div class="small muted">None yet. Tell the assistant how the system should work from now on, for example "no new tech until I say".</div>'}
        <div class="tiny muted" style="margin-top:6px">Every agent reads these. A rule that touches no money takes effect at once; Undo brings back the version it replaced.</div></div>
      ${wait.length ? `<div class="card"><span class="lbl">Waiting for your yes</span>${wait.join('')}</div>` : ''}
      <div class="card"><span class="lbl">Monthly envelope</span><div class="small" style="margin-top:6px">${esc(env.in_words || '')}</div>
        ${env.active ? `<dl class="facts"><dt>Available now</dt><dd>${esc(rs(env.available_now))}</dd><dt>Bought since ${esc(env.start)}</dt><dd>${esc(rs(env.bought_since_start))}</dd>${env.overspent_by ? `<dt class="warn">Over by</dt><dd class="warn">${esc(rs(env.overspent_by))}</dd>` : ''}</dl>` : ''}</div></section>
    <section class="stack" style="flex:1 1 460px"><div class="card"><span class="lbl">How the recommendations have turned out</span>
        ${trows.length ? `<table class="tbl"><thead><tr><th>Decision</th><th>Market</th><th>Scored</th><th>Held</th><th>Rate</th><th>Skeptical</th></tr></thead><tbody>${trows.join('')}</tbody></table>`
          : '<div class="small muted">Nothing is scored yet: each recommendation is checked at 5, 20 and 60 sessions.</div>'}
        <div class="tiny muted" style="margin-top:6px">A rate is shown only from 20 scored claims. The skeptical rate is what it is probably at least. This describes; it never changes a limit.</div></div>
      <div class="card"><span class="lbl">Recent recommendations</span>${props.join('') || '<div class="small muted">None yet.</div>'}</div></section></div>`);
  document.querySelectorAll('[data-undo]').forEach((b) => { b.onclick = async () => { try { await post(`/api/rules/${b.dataset.undo}/undo`, {}); } catch (x) { alert(x.message); } load(true); }; });
  document.querySelectorAll('[data-rdec]').forEach((b) => { b.onclick = async () => { try { await post(`/api/rules/${b.dataset.rid}/decide`, { yes: b.dataset.rdec === 'yes' }); } catch (x) { alert(x.message); } load(true); }; });
}

/* ---------- S76: the paper portfolio the system runs by itself ---------- */
function renderPaper(d) {
  if (!d.started) { $('screen').insertAdjacentHTML('beforeend', `<div class="card"><span class="lbl">Paper portfolio</span><div class="small muted" style="margin-top:6px">${esc(d.note || '')}</div></div>`); return; }
  const r = d.returns || {}, g = d.gate || {}, m = d.money || {};
  const hold = (d.holdings || []).map((h) => `<tr><td><b>${esc(h.symbol)}</b><div class="tiny muted">${esc(h.sector || h.kind || '')}</div></td><td>${num(h.qty, 0)}</td><td>${rs(h.value)}</td><td>${pct(h.weight)}</td><td class="${ud(h.gain)}">${rs(h.gain, true)}</td></tr>`);
  const dec = (d.recent_decisions || []).map((x) => `<div class="item"><span class="chip ${x.status === 'executed' ? '' : 'warn'}">${esc(x.status.replace(/_/g, ' '))}</span>
      <div style="flex:1"><b>${esc(x.action)} ${esc(x.symbol || 'cash')}</b>${x.amount ? ' ' + rs(x.amount) : ''}${x.fraction ? ' ' + pct(x.fraction, 0) + ' of the holding' : ''} <span class="tiny muted">${esc(x.at)} · investigation #${x.case_id}</span>
      <div class="small">${esc(x.reason)}</div></div></div>`);
  const trades = (d.trades || []).map((t) => `<tr><td>${esc(t.day)}</td><td>${esc(t.side)}</td><td>${esc(t.symbol || '')}</td><td>${num(t.qty, 0)}</td><td>${num(t.price)}</td><td>${rs(t.charges)}</td><td>${t.tax != null ? rs(t.tax) : ''}</td></tr>`);
  const inputs = (d.inputs || []).map((i) => `<div class="item"><span class="chip">${esc(i.status)}</span><div style="flex:1">${esc(i.text)}${i.answer ? `<div class="tiny muted">${esc(i.answer.slice(0, 400))}</div>` : ''}</div></div>`);
  const rec = (d.record || {}).by_action || [];
  const recRows = rec.map((x) => `<tr><td>${esc(x.action)}</td><td>${x.n}</td><td>${x.good}</td><td>${x.rate != null ? pct(x.rate, 0) : '<span class="muted">from 20</span>'}</td><td>${x.skeptical_rate != null ? pct(x.skeptical_rate, 0) : ''}</td></tr>`);
  $('screen').insertAdjacentHTML('beforeend', `<div class="cols"><section class="stack" style="flex:2 1 560px">
      <div class="card"><div class="row" style="justify-content:space-between"><span class="lbl">Paper portfolio</span><span class="tiny muted">since ${esc(d.started)} · run by the system, no approvals</span></div>
        <div style="font-size:26px;font-weight:600;margin:4px 0">${rs(d.value)}</div>
        <div class="small">${r.twr != null ? `Return since the start ${pct(r.twr, 1, true)} (money added taken out), worst fall ${pct(r.worst_fall, 1)}, ${r.sessions} session(s).` : 'No session since the start yet.'} Cash ${rs(d.cash)}.</div>
        ${d.days && d.days.length > 1 ? `<div style="margin-top:6px">${spark(d.days.map((x) => x.value), 320, 40)}</div>` : ''}
        <div class="tiny muted" style="margin-top:6px">A copy of your portfolio without FDs (the US sleeve comes later). The promoted policy decides at every close, code sizes and fills at the close with charges and tax. Nothing reaches a broker.</div></div>
      <div class="card"><span class="lbl">Holdings</span>${hold.length ? `<table class="tbl"><thead><tr><th>Name</th><th>Qty</th><th>Value</th><th>Weight</th><th>Gain</th></tr></thead><tbody>${hold.join('')}</tbody></table>` : '<div class="small muted">All in cash.</div>'}
        ${(d.over_rails || []).length ? `<div class="small warn" style="margin-top:6px">${d.over_rails.map(esc).join('<br>')}</div>` : ''}
        <div class="tiny muted" style="margin-top:6px">Rails: ${Object.entries(d.rails || {}).map(([k, v]) => esc(k + ': ' + v)).join(' · ')}</div></div>
      <div class="card"><span class="lbl">Its decisions</span>${dec.join('') || '<div class="small muted">None yet: the first review is under way or due.</div>'}
        ${d.working_on ? `<div class="tiny muted" style="margin-top:6px">Working now: investigation #${d.working_on}</div>` : ''}</div>
      <div class="card"><span class="lbl">Trades on paper</span>${trades.length ? `<table class="tbl"><thead><tr><th>Day</th><th>Side</th><th>Name</th><th>Qty</th><th>Price</th><th>Charges</th><th>Tax</th></tr></thead><tbody>${trades.join('')}</tbody></table>` : '<div class="small muted">None yet.</div>'}
        <div class="tiny muted" style="margin-top:6px">Tax is an estimate from the lots (first in, first out), taken from the cash at each sale; cess and surcharge are not added.</div></div></section>
    <section class="stack" style="flex:1 1 400px">
      <div class="card"><span class="lbl">Is its judgement holding up?</span><div class="small" style="margin-top:4px">${esc((d.record || {}).summary || '')}</div>
        ${recRows.length ? `<table class="tbl"><thead><tr><th>Decision</th><th>Scored</th><th>Held</th><th>Rate</th><th>Skeptical</th></tr></thead><tbody>${recRows.join('')}</tbody></table>` : ''}
        <div class="tiny muted" style="margin-top:6px">Each decision is checked after 7, 28, 84 and 182 days against the Nifty 500 (keeping cash: against what cash earned).</div></div>
      <div class="card"><span class="lbl">Gate to your real money</span><div class="small" style="margin-top:4px">${esc(g.status || '')}</div>
        ${g.paper_return != null ? `<dl class="facts"><dt>Paper</dt><dd>${pct(g.paper_return, 1, true)} · worst ${pct(g.paper_worst_fall, 1)}</dd><dt>Nifty 500</dt><dd>${pct(g.nifty500_return, 1, true)} · worst ${pct(g.nifty500_worst_fall, 1)}</dd></dl>` : ''}
        <div class="tiny muted" style="margin-top:4px">The system's book is its own: nothing here is an order for your real money.</div></div>
      <div class="card"><span class="lbl">Its money</span><div class="small" style="margin-top:4px">${rs(m.this_month)} of ${rs(m.monthly)} this month on the strategist and the checks.</div></div></section></div>`);
}
