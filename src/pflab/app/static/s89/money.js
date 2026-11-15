/* Your money: the design's Money screen. His REAL holdings, read-only (India from the latest Kite snapshot, US entered by hand), with Claude's view where
   the thinking loop has one. Nothing here can trade; his money and the paper book are never added together. */
S89.register('money', async (el) => {
  const { rs, usd, pct, num, api, render, path } = S89;
  let tab = sessionStorage.getItem('s89:moneyTab') || 'all', sel = null;
  const V = { hold: ['#EAF0FE', '#1D3FB8'], trim: ['#FDF0E6', '#9A4209'], watch: ['#F3F2EE', '#3E4149'], add: ['#E7F5EE', '#1F6B47'], 'not yet': ['#F6F5F1', '#6B6E76'] };
  const paper = await api('/api/paper').catch(() => ({}));
  const held = {}; (paper.holdings || []).forEach((h) => { if (h.symbol) held[String(h.symbol).toUpperCase()] = h; });
  async function draw() {
    const d = await api('/api/mine?tab=' + tab);
    const rows = d.rows || [], s = d.summary || {};
    if (!rows.some((r) => r.id === sel)) sel = rows.length ? rows[0].id : null;
    const out = rows.map((r) => { const on = r.id === sel, v = r.view ? r.view.label : 'not yet';
      return { name: r.name, sub: (r.market === 'in' ? 'NSE · ' : 'US · ') + num(r.qty, r.qty % 1 ? 2 : 0) + ' units', spark: path(r.spark, 110, 30), sc: r.since_buy_pct != null && r.since_buy_pct < 0 ? '#D9620F' : '#2F5BEA',
        val: rs(r.value_inr), w: r.weight == null ? '—' : r.weight.toFixed(1) + '%', day: pct(r.day_pct), dc: (r.day_pct || 0) >= 0 ? '#1D3FB8' : '#9A4209', tot: pct(r.since_buy_pct), tc: (r.since_buy_pct || 0) >= 0 ? '#1D3FB8' : '#9A4209',
        view: v, vb: V[v][0], vf: V[v][1], conf: r.view ? 'since ' + r.view.since : '', on, bg: on ? '#F3F6FE' : '#FFFFFF', bd: on ? '#B9C8FB' : 'transparent', pick: () => { sel = r.id; draw(); } }; });
    const h = rows.find((r) => r.id === sel);
    let selVals = { name: 'No holding yet', sub: d.empty || '', price: '—', day: '', dc: '#5B5E66', line: '', area: '', stopY: '-10', stop: '—', chartLabel: 'no data', view: 'not yet', vb: V['not yet'][0], vf: V['not yet'][1],
      viewLine: "Claude's view", confW: '0%', why: '', calibText: '', qty: '—', claude: '—', next: '—', sym: '', from: '' };
    if (h) {
      const sp = h.spark || [], c = held[String(h.symbol).toUpperCase()], stop = c && c.stop != null ? Number(c.stop) : null;
      const lo = Math.min(...sp.concat(stop != null ? [stop] : [])) * 0.99, hi = Math.max(...sp) * 1.01, ln = sp.length > 1 ? path(sp, 440, 180, lo, hi) : '';
      const v = h.view ? h.view.label : 'not yet', pf = h.market === 'us' ? usd : (n) => '₹' + Number(n).toLocaleString('en-IN', { maximumFractionDigits: 1 });
      selVals = { name: h.name, sub: h.market === 'in' ? 'India · from Kite, read-only' : 'US · entered by hand until a US broker is connected', price: h.price == null ? 'price after the next check' : pf(h.price),
        day: pct(h.day_pct), dc: (h.day_pct || 0) >= 0 ? '#1D3FB8' : '#9A4209', line: ln, area: ln ? ln + ' L440 180 L0 180 Z' : '', stopY: stop != null && ln ? (4 + (1 - (stop - lo) / ((hi - lo) || 1)) * 172).toFixed(1) : '-10',
        stop: stop != null ? pf(stop) : 'none: not in Claude\'s book', chartLabel: h.name + ' over the last ' + sp.length + ' sessions' + (stop != null ? ' with the stop Claude uses' : ''),
        view: v, vb: V[v][0], vf: V[v][1], viewLine: h.view ? "Claude's view · decided " + h.view.since : "Claude's view · not formed yet", confW: h.view ? '100%' : '0%',
        why: h.view ? h.view.why : 'The thinking loop has not looked at this name yet. It looks when something changes for it.',
        calibText: h.view ? 'How often its calls come true is on Claude\'s book, under "Is it right?".' : '', qty: num(h.qty, h.qty % 1 ? 2 : 0) + ' units',
        claude: c ? (c.weight != null ? (c.weight * 100).toFixed(1) + '% of its book' : 'it holds it') : 'none', next: h.market === 'in' ? (d.state.kite === 'ok' ? 'every 5 min while open' : 'after the Kite login') : 'at the next US close',
        sym: encodeURIComponent(h.symbol), from: sp.length ? sp.length + ' sessions ago' : '' };
    }
    const total = s.value_inr || 0;
    const alloc = (d.mix || []).map((m, i) => ({ name: m.name, w: Math.round(m.w * 100) + '%', c: ['#2F5BEA', '#D9620F', '#C9A227', '#93A9F6'][i % 4] }));
    const pd = paper.days || [], pn = paper.nifty || [];
    const bookRet = pd.length > 1 ? (pd[pd.length - 1].value / pd[0].value - 1) * 100 : null, baseRet = pn.length > 1 ? (pn[pn.length - 1].value / pn[0].value - 1) * 100 : null;
    const mx = Math.max(Math.abs(bookRet || 0), Math.abs(baseRet || 0), 1);
    const race = [{ name: 'Your money', v: 'no history kept', w: '0%', c: '#D9620F' }, { name: 'Claude’s paper book', v: pct(bookRet), w: (Math.abs(bookRet || 0) / mx * 100) + '%', c: '#2F5BEA' },
      { name: tab === 'us' ? 'S&P 500' : 'Nifty 500', v: pct(baseRet), w: (Math.abs(baseRet || 0) / mx * 100) + '%', c: '#9A9DA4' }];
    const alarms = (d.alarms || []).map((a) => ({ t: a.symbol + ': ' + a.headline, s: a.at, bg: '#F6F5F1' }));
    if (!alarms.length) alarms.push({ t: 'Nothing heard about what you hold', s: 'the alarm reader checks every 15 minutes while the app is open', bg: '#F6F5F1' });
    const kite = d.state || {};
    const src = tab === 'us' ? ['No US broker connected · entered by hand', '#C9A227'] : kite.kite === 'ok' ? ['India from Kite, read-only · ' + (kite.snapshot_at || ''), '#2FA36B'] : ['Kite is not logged in · India shows the last snapshot' + (kite.snapshot_at ? ' (' + kite.snapshot_at + ')' : ': none yet'), '#D9620F'];
    const tabs = [['all', 'All'], ['in', 'India'], ['us', 'US']].map(([k, l]) => ({ label: l, on: k === tab, bg: k === tab ? '#17181C' : 'transparent', fg: k === tab ? '#FFFFFF' : '#3E4149', pick: () => { tab = k; sessionStorage.setItem('s89:moneyTab', k); draw(); } }));
    await render(el, 'money', { tabs, rows: out, sel: selVals, alloc, race, alarms, days: (h && h.spark ? h.spark.length : 60) + ' days',
      sum: { value: rs(total || null), today: s.today_inr == null ? 'no snapshot yet' : (s.today_inr >= 0 ? '+' : '−') + rs(Math.abs(s.today_inr)) + ' today', base: 'read-only · no history kept', source: src[0], dot: src[1] } });
  }
  await draw();
});
