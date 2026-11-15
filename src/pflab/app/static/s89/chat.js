/* S89 Chat: one conversation (laptop and Telegram). Only the message list scrolls. Each reply shows its road (quick / full / ack), tokens and model. Pickers: road (Auto / Quick / Full) and model. */
S89.register('chat', async (el) => {
  const { esc, api, post } = S89;
  const ROADS = [['auto', 'Auto'], ['quick', 'Quick'], ['full', 'Full']];
  const MODELS = [['', "Agent's default"], ['haiku', 'Haiku 5.5'], ['sonnet', 'Sonnet 5.5'], ['opus', 'Opus 5.5']];
  let road = localStorage.getItem('s89:road') || 'auto', model = localStorage.getItem('s89:model') || '';
  const meta = (m) => { const o = m.meta_obj || {}; const bits = []; if (o.path) bits.push(o.path); else if (m.meta) return esc(String(m.meta).split(' · ').slice(0, 5).join(' · ')); if (o.model) bits.push(String(o.model).replace('claude-', '')); if (o.tokens != null) bits.push(Number(o.tokens).toLocaleString('en-IN') + ' tokens'); if (o.tools && o.tools.length) bits.push('used: ' + o.tools.join(', ')); return esc(bits.join(' · ')); };
  async function draw(keepText) {
    const d = await api('/api/assistant');
    const msgs = (d.messages || []).map((m) => {
      const user = (m.role || '') === 'user';
      const acts = (m.actions || []).map((a) => `<button class="btn ${a.id === 'yes' ? '' : 'ghost'}" data-card="${esc(m.msg_id || m.id)}" data-act="${esc(a.id)}">${esc(a.label || a.id)}</button>`).join(' ');
      return `<div class="msg ${user ? 'user' : 'bot'}">${esc(m.text || (m.status === 'pending' ? 'Working on it…' : ''))}${acts ? `<div class="row" style="margin-top:6px">${acts}</div>` : ''}${user ? '' : `<span class="meta">${meta(m)}</span>`}</div>`;
    }).join('') || S89.empty('Ask anything about your money or the paper book. A plain question is answered on the quick road.');
    const q = (d.queue || []).length ? `<div class="small muted">Working on what you sent: ${(d.queue || []).length} item(s)</div>` : '';
    const typed = keepText != null ? keepText : (document.getElementById('chatIn') || {}).value || '';
    el.innerHTML = `<div class="row"><h2 class="grow" style="margin:0">Chat</h2><div class="tabs" id="roads">${ROADS.map(([k, l]) => `<button data-road="${k}" class="${road === k ? 'on' : ''}">${l}</button>`).join('')}</div>
        <select id="chatModel" aria-label="Model">${MODELS.map(([k, l]) => `<option value="${k}" ${model === k ? 'selected' : ''}>${l}</option>`).join('')}</select><button class="btn ghost" id="chatNew">New chat</button></div>
      <div class="card" style="flex:1;min-height:0"><div class="msgs" id="msgs" role="log">${msgs}</div>${q}
        <form class="row" id="chatForm"><textarea id="chatIn" rows="2" class="grow" placeholder="Ask, or say what you want done" aria-label="Message">${esc(typed)}</textarea><button class="btn" type="submit">Send</button></form>
        <span class="small muted">A change (watchlist, a US holding, an agent's model) always waits for your Yes. These answers draw on your plan's limits and the daily budgets.</span></div>`;
    const box = document.getElementById('msgs'); box.scrollTop = box.scrollHeight;
    el.querySelectorAll('[data-road]').forEach((b) => { b.onclick = () => { road = b.dataset.road; localStorage.setItem('s89:road', road); draw(); }; });
    document.getElementById('chatModel').onchange = (e) => { model = e.target.value; localStorage.setItem('s89:model', model); };
    document.getElementById('chatNew').onclick = async () => { await post('/api/assistant/new'); draw(''); };
    el.querySelectorAll('[data-card]').forEach((b) => { b.onclick = async () => { b.disabled = true; try { await post('/api/assistant/messages/' + b.dataset.card + '/action', { action: b.dataset.act }); draw(); } catch (e) { b.disabled = false; alert(e.message); } }; });
    document.getElementById('chatForm').onsubmit = async (ev) => {
      ev.preventDefault(); const t = document.getElementById('chatIn').value.trim(); if (!t) return;
      const body = { text: t }; if (road !== 'auto') body.road = road; if (model) body.model = model;
      try { await post('/api/assistant', body); draw(''); } catch (e) { alert(e.message); }
    };
    document.getElementById('chatIn').onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); document.getElementById('chatForm').requestSubmit(); } };
  }
  await draw();
  S89.every(4000, () => { if (!document.getElementById('chatIn') || document.getElementById('chatIn').value === '') draw(''); });
});
