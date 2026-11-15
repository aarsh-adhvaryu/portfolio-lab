/* Chat: the design's Chat screen. One conversation for the laptop and Telegram. Each reply shows its road (quick / full), tokens, model and tools. Pickers: road (Auto / Quick / Full)
   and model. The side shows the operator (signed in, today's tokens against the budgets), the Yes/No cards waiting for him, what the intake is working on, and his standing instructions. */
S89.register('chat', async (el) => {
  const { api, post, render, kTok } = S89;
  const ROADS = [['auto', 'Auto'], ['quick', 'Quick'], ['full', 'Full']];
  const MODELS = [['', 'Agent’s default'], ['haiku', 'Haiku 5.5'], ['sonnet', 'Sonnet 5.5'], ['opus', 'Opus 5.5']];
  const HINTS = { auto: 'Auto: plain questions go quick; files, links and studies go full', quick: 'Quick: short answer, small tools, about 6k tokens', full: 'Full: files, the Lab, MCPs and skills, about 20–30k tokens' };
  const ss = (k, v) => { try { if (v === undefined) return sessionStorage.getItem(k); sessionStorage.setItem(k, v); } catch (e) { return null; } return v; };
  let road = ss('s89:road'), model = ss('s89:model') || '', draft = ss('s89:draft') || '', files = [], busy = false;
  const pills = (list, cur, set) => list.map(([k, l]) => { const on = k === cur; return { label: l, on: String(on), bg: on ? '#17181C' : '#FFFFFF', fg: on ? '#FFFFFF' : '#3E4149', bd: on ? '#17181C' : '#E6E4DD', pick: () => { set(k); draw(); } }; });
  const btn = (label, go, dark) => ({ label, go, bg: dark ? '#17181C' : '#FFFFFF', fg: dark ? '#FFFFFF' : '#17181C', bd: dark ? '#17181C' : '#C9C6BD' });
  const answer = async (id, act) => { try { await post('/api/assistant/messages/' + id + '/action', { action: act }); } catch (e) { alert(e.message); } draw(); };
  const acts = (m) => (m.actions || []).map((a) => btn(a.label || a.id, () => answer(m.id, a.id), a.id === 'yes'));
  const when = (s) => { if (!s) return ''; const d = new Date(String(s).replace(' ', 'T')); return isNaN(d) ? s : d.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); };
  function meta(m) {
    const o = m.meta_obj || {}, bits = [];
    if ((m.role || '') === 'user') return 'You · ' + (m.channel === 'telegram' ? 'Telegram · ' : '') + when(m.at);
    if (m.channel === 'system' || String(m.mode || '').startsWith('note:')) return 'From the system · ' + when(m.at);
    if (o.path) bits.push(o.path === 'light' ? 'quick' : o.path);
    if (o.model || m.model) bits.push(String(o.model || m.model).replace('claude-', ''));
    if (o.tokens != null) bits.push(kTok(o.tokens) + ' tokens');
    if (!bits.length && m.meta) return String(m.meta).split(' · ').slice(0, 4).join(' · ');
    bits.push(when(m.finished || m.at));
    return bits.join(' · ');
  }
  async function attach() {
    const inp = document.createElement('input'); inp.type = 'file'; inp.multiple = true;
    inp.onchange = async () => {
      for (const f of inp.files) {
        try { const r = await fetch('/api/assistant/files', { method: 'POST', headers: { 'x-filename': encodeURIComponent(f.name) }, body: f }); if (!r.ok) throw new Error((await r.text()).slice(0, 200)); files.push(await r.json()); }
        catch (e) { alert(f.name + ': ' + e.message); }
      }
      draw();
    };
    inp.click();
  }
  async function send(ev) {
    if (ev && ev.preventDefault) ev.preventDefault();
    const t = draft.trim(); if ((!t && !files.length) || busy) return;
    busy = true;
    const body = { text: t || 'Please read the attached file.' };
    body.road = road; if (model) body.model = model; if (files.length) body.files = files.map((f) => f.upload_id);
    try { await post('/api/assistant', body); draft = ''; ss('s89:draft', ''); files = []; } catch (e) { alert(e.message); }
    busy = false; draw();
  }
  async function draw() {
    const [d, op, rl] = await Promise.all([api('/api/assistant'), api('/api/operator').catch(() => ({})), api('/api/rules').catch(() => ({}))]);
    const all = d.messages || [];
    const msgs = all.map((m) => {
      const user = (m.role || '') === 'user', sys = m.channel === 'system' || String(m.mode || '').startsWith('note:');
      const a = acts(m), att = m.attachments || [], o = m.meta_obj || {};
      return { side: user ? 'flex-end' : 'flex-start', align: user ? 'flex-end' : 'flex-start', maxw: user ? '72%' : '86%', meta: meta(m),
        text: m.text || (m.status === 'pending' || m.status === 'working' ? 'Working on it…' : ''), bg: user ? '#17181C' : sys ? '#EEF2FE' : '#F6F5F1', fg: user ? '#FFFFFF' : '#17181C',
        radius: user ? '18px 18px 4px 18px' : '18px 18px 18px 4px', hasQuote: false, quote: '',
        hasFile: att.length > 0, file: att.map((x) => x.name || x.path || 'file').join(', '),
        hasChips: false, chips: [], hasUsed: !user && (o.tools || []).length > 0, used: 'used: ' + (o.tools || []).slice(0, 6).join(', '),
        hasLink: false, link: '', href: '#', hasActs: a.length > 0, acts: a };
    });
    if (!msgs.length) msgs.push({ side: 'flex-start', align: 'flex-start', maxw: '86%', meta: 'Claude', text: 'Ask anything about your money or Claude’s book. A plain question is answered on the quick road; files, links and studies go to the full road.', bg: '#F6F5F1', fg: '#17181C', radius: '18px 18px 18px 4px' });
    const earlier = d.earlier || [];
    const chats = [{ title: 'This chat', when: all.length ? when(all[all.length - 1].at) : 'new', bg: '#FFFFFF', weight: 600, open: (e) => e.preventDefault() }]
      .concat(earlier.map((c) => ({ title: c.title || 'Earlier chat', when: when(c.updated), bg: 'transparent', weight: 500,
        open: async (e) => { e.preventDefault(); try { await post('/api/assistant/open/' + c.id); } catch (x) { alert(x.message); } draw(); } })));
    const tk = op.tokens_today || {}, bud = (k, l, c) => { const t = tk[k] || {}, u = Number(t.used || 0), b = Number(t.budget || 0); return { l, v: kTok(u) + ' of ' + kTok(b), w: (b ? Math.min(100, u / b * 100) : 0).toFixed(0) + '%', c }; };
    const byId = Object.fromEntries(all.map((m) => [m.id, m]));
    const cards = (op.open_cards || []).slice(0, 3).map((c) => { const m = byId[c.msg_id], a = m ? acts(m) : [];
      const lines = String(c.text || '').split('\n').filter(Boolean);
      const short = (t, n) => (t.length > n ? t.slice(0, n).replace(/\s+\S*$/, '') + '…' : t);
      return { head: 'Waiting for your Yes · nothing changes until you answer', text: short(lines[0] || 'A question for you', 170), sub: short(lines.slice(1, 3).join(' · '), 120),
        acts: a.length ? a : [btn('Yes', () => answer(c.msg_id, 'yes'), true), btn('No', () => answer(c.msg_id, 'no'))] }; });
    const qs = (d.queue || []).map((q) => ({ name: (q.kind || 'message').replace(/_/g, ' ') + (q.channel === 'telegram' ? ' · Telegram' : ''), state: q.state === 'working' ? 'reading' : 'waiting', p: q.state === 'working' ? Math.max(15, Math.min(95, Number(q.progress || 0) * 100)).toFixed(0) + '%' : '4%' }));
    if (!qs.length) qs.push({ name: 'Nothing waiting', state: 'all answered', p: '0%' });
    const fmtUntil = (u) => (u ? 'until ' + new Date(u).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : 'no end date');
    const rules = (rl.active || []).map((r) => ({ name: r.text || r.name, sub: fmtUntil(r.until) + (r.kind === 'hold_name' ? ' · stops still apply' : ''),
      undo: async () => { try { await post('/api/rules/' + r.rule_id + '/undo'); } catch (e) { alert(e.message); } draw(); } }))
      .concat((rl.waiting || []).map((r) => ({ name: r.text || r.name, sub: 'waiting for your Yes', undo: null })));
    if (!rules.length) rules.push({ name: 'None', sub: 'say “pause gold buys till 20 Nov” or “keep a stock through its results” and it shows here', undo: null });
    const ok = op.signed_in && op.thinking === 'running';
    const old = el.querySelector('[role="log"]'), stick = !old || old.scrollHeight - old.scrollTop - old.clientHeight < 80;
    await render(el, 'chat', { chats, msgs, cards, queue: qs, rules,
      roads: pills(ROADS, road, (k) => { road = k; ss('s89:road', k); }), models: pills(MODELS, model, (k) => { model = k; ss('s89:model', k); }),
      hint: files.length ? 'Attached: ' + files.map((f) => f.name).join(', ') : HINTS[road], draft, setDraft: (e) => { draft = e.target.value; ss('s89:draft', draft); }, send, attach,
      newChat: async () => { try { await post('/api/assistant/new'); } catch (e) { alert(e.message); } draw(); },
      budgets: [bud('chat_light', 'Quick answers today', '#93A9F6'), bud('chat', 'Full answers today', '#2F5BEA')],
      op: { dot: ok ? '#2FA36B' : op.thinking === 'paused' ? '#D9620F' : '#9A9DA4',
        text: op.signed_in ? (op.thinking === 'paused' ? 'signed in · thinking paused' + (op.paused_until ? ' until ' + op.paused_until.slice(11) : '') : 'signed in · thinking running') : 'not signed in · see Settings' } });
    const log = el.querySelector('[role="log"]'); if (log && stick) log.scrollTop = log.scrollHeight;
  }
  if (!road) { try { road = (await api('/api/settings')).chat_road || 'auto'; } catch (e) { road = 'auto'; } }
  await draw();
  S89.every(5000, () => { const q = document.getElementById('chat-in'); if (!q || document.activeElement !== q || !q.value) draw(); });
});
