/* S89 Home: Needs you, your money vs Claude's book, what it is doing now, Heard, its eyes, fall chance, the top storyline, and the three broken-state banners (Kite, plan limit, a source down). */
S89.register('home', async (el) => {
  const { esc, rs, pct, cls, ago, api, post, lines, empty } = S89;
  const d = await api('/api/home');
  const b = d.banner;
  const needs = d.needs || [];
  const needHtml = needs.length ? needs.map((n) => `<div class="need ${n.kind === 'alarm' || n.kind === 'do this' ? 'warn' : n.kind === 'fix ready' ? 'fix' : ''}" data-id="${esc(n.id)}">
      <div class="row"><span class="chip ${n.kind === 'alarm' || n.kind === 'do this' ? 'warn' : 'mute'}">${esc(n.kind)}</span><span class="muted small">${esc(n.when || '')}</span></div>
      <span class="b">${esc(n.text)}</span><span class="small">${esc(n.detail || '')}</span>
      ${n.plan_card ? `<ol class="small" style="margin:0;padding-left:18px">${(n.steps || []).map((s) => `<li>${esc(s.text)}${s.uses ? ` <span class="muted">(${esc(s.uses)})</span>` : ''}</li>`).join('')}</ol>` : ''}
      <div class="row">${n.plan_card ? `<button class="btn" data-plan="start:${n.plan_id}">Start</button><a class="btn ghost" href="#/chat" data-change="1">Change</a><button class="btn ghost" data-plan="cancel:${n.plan_id}">Cancel</button>` : n.link ? `<a class="btn" href="${esc(n.link)}">${n.kind === 'do this' ? 'Log in' : 'Open the case'}</a>` : (n.yes_no ? `<button class="btn" data-yes="${esc(n.id)}">Yes</button><button class="btn ghost" data-no="${esc(n.id)}">No</button>` : '')}</div></div>`).join('')
    : empty('Nothing needs you right now.');
  const running = (d.plans || []).map((pl) => `<div class="need" data-plan-id="${pl.plan_id}"><div class="row"><span class="chip ${pl.status === 'paused' ? 'warn' : ''}">${esc(pl.status)}</span><b class="grow">${esc(pl.title)}</b><span class="small muted">${(pl.tokens || 0).toLocaleString('en-IN')} of about ${(pl.est_tokens || 0).toLocaleString('en-IN')} tokens</span></div>
      ${(pl.steps || []).map((s) => `<div class="row small"><span>${s.status === 'done' ? '✓' : s.status === 'running' ? '…' : s.status === 'failed' ? '✗' : '○'}</span><span class="grow">${esc(s.text)}</span><span class="muted">${esc(s.status)}</span></div>`).join('')}
      ${pl.status === 'paused' ? `<div class="small">Paused at the plan's limit${pl.resume_after ? ', resumes after ' + esc(pl.resume_after) : ''}. Finished steps are kept.</div>` : ''}
      <div class="row"><button class="btn ghost" data-term="1">Open in Claude Code</button><button class="btn ghost" data-plan="cancel:${pl.plan_id}">Cancel</button></div></div>`).join('');
  const mine = d.mine || {}, paper = d.paper;
  const pv = paper && paper.value;
  const chart = paper && paper.days && paper.days.length > 1 ? lines([paper.days.map((x) => x[1]), (paper.nifty || []).map((x) => x[1])], 720, 200, ['#2F5BEA', '#9A9DA4']) : empty("Claude's paper book has no history yet. The curve appears after its first closes.");
  const heard = (d.heard || []).length ? d.heard.map((h) => `<div class="row small"><span class="chip ${h.kind === 'alarm' ? 'warn' : 'mute'}">${esc(h.kind)}</span><b>${esc(h.symbol || '')}</b><span class="grow">${esc(h.text)}</span><span class="muted">${esc(h.at)}</span></div>`).join('') : empty('Nothing heard yet today.');
  const eyes = (d.eyes || []).map((e) => `<div class="row small"><span class="dot ${e.state}"></span><span class="grow">${esc(e.name)}</span><span class="muted">${e.state === 'never' ? 'not yet' : e.state === 'down' ? 'not answering' : (e.age_min != null ? e.age_min + ' min ago' : '')}</span></div>`).join('') || empty('No source has answered yet.');
  const plan = d.plan || {};
  el.innerHTML = `
    ${b ? `<section class="banner ${esc(b.kind)}" role="status"><div class="grow"><span class="t">${esc(b.title)}</span><br><span class="small">${esc(b.text)}</span></div><a class="btn" href="${esc(b.href)}">${esc(b.cta)}</a></section>` : ''}
    <section class="grid" style="flex:1.1">
      <div class="card key" style="flex:1 1 380px"><div class="row"><b style="font-size:17px">Needs you</b><span class="chip">${needs.length}</span><span class="muted small" style="margin-left:auto">also on Telegram</span></div><div class="col scroll" id="needs">${needHtml}${running ? `<div class="small muted">Working on what you sent</div>${running}` : ''}</div></div>
      <div class="card" style="flex:1.5 1 560px">
        <div class="row" style="gap:10px 28px;align-items:flex-end">
          <a href="#/money" class="col" style="gap:0;color:inherit"><span class="small muted">Your money (read-only)</span><span class="big">${rs(mine.value_inr)}</span><span class="small ${cls(mine.today_pct)}">${mine.today_pct == null ? (mine.value_inr ? '' : 'no snapshot yet') : pct(mine.today_pct, 1) + ' today'}</span></a>
          <a href="#/book" class="col" style="gap:0;color:inherit"><span class="small muted">Claude's paper book</span><span class="big">${rs(pv)}</span><span class="small muted">${paper ? 'its own account, fake money' : 'not started'}</span></a>
        </div>
        <div class="small muted">Your money keeps only today's snapshot (no history is kept), so its curve is not drawn.</div>${chart}
      </div>
    </section>
    <section class="grid" style="flex:1">
      <div class="card" style="flex:1 1 300px"><h2>What it is doing now</h2><div class="b">${esc(plan.thinking === 'paused' ? 'Thinking paused' : plan.thinking === 'running' ? 'Thinking' : 'Not thinking')}</div>
        <div class="small muted">${d.doing && d.doing.mode ? 'Last desk session: ' + esc(d.doing.mode) : 'No desk session yet.'}</div>
        <div class="small">Plan tokens today: ${Object.entries(plan.tokens_today || {}).map(([k, v]) => `${esc(k)} ${(v.used / 1000).toFixed(0)}k`).join(' · ')}</div></div>
      <div class="card" style="flex:1.2 1 360px"><h2>Heard</h2><span class="small muted">headlines checked every 15 min against your money and your watchlist</span><a class="small" href="#/manage">Edit watchlist</a><div class="col scroll" style="gap:6px">${heard}</div></div>
      <div class="card" style="flex:1 1 280px"><div class="row"><h2>Its eyes</h2><a class="small" href="#/agents" style="margin-left:auto">Connections</a></div><div class="col" style="gap:6px">${eyes}</div></div>
      <div class="card" style="flex:1 1 260px"><span class="big">${d.fall_chance == null ? '—' : Math.round(d.fall_chance.p * 100) + '%'}</span><span class="small">chance of a fall in the next ${d.fall_chance ? d.fall_chance.horizon : 20} sessions</span><span class="small muted">${d.fall_chance == null ? 'Not worked out yet.' : 'worked out ' + esc(d.fall_chance.as_of)}</span><a class="small" href="#/lab">Simulate it</a>
        <hr style="border:0;border-top:1px solid var(--line);width:100%"><span class="small muted">Top storyline</span><span class="b small">${d.storyline ? esc(d.storyline.text) : 'None yet'}</span><a class="small" href="#/graph">Open the graph</a></div>
    </section>`;
  el.querySelectorAll('[data-plan]').forEach((bt) => { bt.onclick = async () => { const [act, id] = bt.dataset.plan.split(':'); bt.disabled = true; try { await post('/api/plans/' + id + '/' + act); S89.show('home'); } catch (e) { bt.disabled = false; bt.closest('.need').insertAdjacentHTML('beforeend', `<span class="err small">${esc(e.message)}</span>`); } }; });
  el.querySelectorAll('[data-term]').forEach((bt) => { bt.onclick = async () => { try { const r = await post('/api/operator/terminal'); bt.textContent = r.ok ? 'Opened a terminal in the operator folder' : (r.detail || 'Could not open it'); } catch (e) { bt.textContent = e.message; } }; });
  el.querySelectorAll('[data-yes],[data-no]').forEach((bt) => {
    bt.onclick = async () => {
      const id = bt.dataset.yes || bt.dataset.no, yes = !!bt.dataset.yes; bt.disabled = true;
      try {
        if (id.startsWith('card:')) await post('/api/assistant/messages/' + id.slice(5) + '/action', { action: yes ? 'yes' : 'no' });
        else if (id.startsWith('q:')) await post('/api/questions/' + id.slice(2) + '/answer', { text: yes ? 'yes' : 'no' });
        bt.closest('.need').innerHTML = `<span class="b">${yes ? 'Done. Thanks.' : 'Dropped.'}</span>`;
      } catch (e) { bt.disabled = false; bt.closest('.need').insertAdjacentHTML('beforeend', `<span class="err small">${esc(e.message)}</span>`); }
    };
  });
});
