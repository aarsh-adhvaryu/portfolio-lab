/* S89 Your money: his REAL holdings, read-only (India from the latest Kite snapshot, US entered by hand), with Claude's view where the thinking loop has one. No order can be placed from here. */
S89.register('money', async (el) => {
  const { esc, rs, usd, num, pct, cls, api, sparkline, lines, empty, ago } = S89;
  let tab = sessionStorage.getItem('s89:moneyTab') || 'all', sel = null;
  async function draw() {
    const d = await api('/api/mine?tab=' + tab);
    const rows = d.rows || [], s = d.summary || {};
    sel = rows.find((r) => r.id === sel) ? sel : (rows[0] && rows[0].id);
    const cur = rows.find((r) => r.id === sel);
    const tabs = [['all', 'All'], ['in', 'India'], ['us', 'US']].map(([k, l]) => `<button data-tab="${k}" class="${tab === k ? 'on' : ''}">${l}</button>`).join('');
    const stale = d.state && d.state.kite !== 'ok' ? `<div class="banner kite"><span class="t">${d.state.kite === 'expired' || d.state.kite === 'never' ? 'Kite is not logged in' : 'Kite did not answer'}</span><span class="small">India shows the last snapshot${d.state.snapshot_at ? ' from ' + esc(d.state.snapshot_at) : ' (none yet)'}.</span><a class="btn" href="#/settings">Log in to Kite</a></div>` : '';
    const body = rows.length ? rows.map((r) => `<tr class="click ${r.id === sel ? 'sel' : ''}" data-id="${esc(r.id)}"><td><b>${esc(r.name)}</b><br><span class="small muted">${r.market === 'us' ? 'US' : 'India'} · ${num(r.qty, r.qty % 1 ? 2 : 0)} shares</span></td>
        <td>${sparkline(r.spark, 80, 24, r.since_buy_pct != null && r.since_buy_pct < 0 ? '#D9620F' : '#2F5BEA')}</td><td class="n">${rs(r.value_inr)}</td><td class="n">${r.weight == null ? '—' : r.weight.toFixed(1) + '%'}</td>
        <td class="n ${cls(r.day_pct)}">${pct(r.day_pct)}</td><td class="n ${cls(r.since_buy_pct)}">${pct(r.since_buy_pct)}</td>
        <td>${r.view ? `<span class="chip ${r.view.label === 'trim' ? 'warn' : r.view.label === 'add' ? 'ok' : 'mute'}">${esc(r.view.label)}</span>` : '<span class="muted small">not yet</span>'}</td></tr>`).join('')
      : `<tr><td colspan="7">${empty(d.empty || 'No holdings yet.')}</td></tr>`;
    const detail = cur ? `<div class="b" style="font-size:17px">${esc(cur.name)}</div><div class="small muted">${cur.market === 'us' ? 'US · ' + usd(cur.price) : 'India · ' + rs(cur.price)}${cur.price_as_of ? ' as of ' + esc(cur.price_as_of) : ''}</div>
        ${cur.spark && cur.spark.length > 1 ? lines([cur.spark], 520, 140, ['#2F5BEA']) : empty('No price history stored for this name yet.')}
        <div class="row small"><span>You hold <b>${num(cur.qty, cur.qty % 1 ? 2 : 0)}</b></span><span>Average <b>${cur.market === 'us' ? usd(cur.avg) : rs(cur.avg)}</b></span><span class="${cls(cur.since_buy_pct)}">Since buy <b>${pct(cur.since_buy_pct)}</b></span></div>
        ${cur.view ? `<div class="card" style="background:var(--accent-bg);border:0"><span class="b">Claude's view: ${esc(cur.view.label)}</span><span class="small">${esc(cur.view.why || '')}</span><span class="small muted">From the thinking loop's decision on ${esc(cur.view.since)}. How often it has been right at this confidence is on <a href="#/book">Claude's book</a>.</span></div>` : '<div class="small muted">Claude has not formed a view on this name yet.</div>'}
        <div class="row small"><a href="#/stock/${encodeURIComponent(cur.symbol)}">Open candles</a><a href="#/lab">Study it in the Lab</a><a href="#/chat">Ask about it</a></div>` : empty('Pick a holding.');
    const mix = (d.mix || []).map((m) => `<div class="row small"><span class="grow">${esc(m.name)}</span><b>${(m.w * 100).toFixed(0)}%</b></div>`).join('') || empty('Nothing to show yet.');
    const al = (d.alarms || []).map((a) => `<div class="small"><b>${esc(a.symbol)}</b> ${esc(a.headline)} <span class="muted">${esc(a.at)}</span></div>`).join('') || '<span class="small muted">Nothing heard about what you hold.</span>';
    el.innerHTML = `${stale}<div class="row"><div class="tabs">${tabs}</div><a class="btn ghost" href="#/manage" style="margin-left:auto">Add US holdings · watchlist</a></div>
      <section class="grid" style="flex:1;align-items:stretch">
        <div class="card" style="flex:2 1 620px"><div class="row"><span class="big">${rs(s.value_inr)}</span><span class="${cls(s.today_pct)}">${s.today_pct == null ? '' : pct(s.today_pct) + ' today'}</span><span class="muted small" style="margin-left:auto">${d.state && d.state.snapshot_at ? 'India from Kite, ' + esc(d.state.snapshot_at) : 'India: no Kite snapshot yet'}</span></div>
          <div class="scroll"><table><thead><tr><th>Holding</th><th>60 days</th><th class="n">Value</th><th class="n">Weight</th><th class="n">Today</th><th class="n">Since buy</th><th>Claude's view</th></tr></thead><tbody>${body}</tbody></table></div>
          <div class="small muted">Claude only watches this money. It cannot place orders here. Its own decisions go into its paper book.</div></div>
        <div class="col" style="flex:1 1 340px"><div class="card">${detail}</div>
          <div class="card"><h2>Where it sits</h2>${mix}</div>
          <div class="card"><h2>Heard about what you hold</h2>${al}</div></div>
      </section>`;
    el.querySelectorAll('[data-tab]').forEach((b) => { b.onclick = () => { tab = b.dataset.tab; sessionStorage.setItem('s89:moneyTab', tab); draw(); }; });
    el.querySelectorAll('tr[data-id]').forEach((tr) => { tr.onclick = () => { sel = tr.dataset.id; draw(); }; });
  }
  await draw();
});
