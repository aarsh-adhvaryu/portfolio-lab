/* Claude's book: the design's Calibration screen. "Is it right?" (its curve against the index, how sure it said it was against how often it was right, every decision
   and how it scored, what it changed about itself) and "Its holdings" (stops, the 12-month tax clock, thesis), India and US. Below 20 scored decisions it says so. */
S89.register('book', async (el) => {
  const { api, render, path, num } = S89;
  let book = sessionStorage.getItem('s89:book') || 'in', view = sessionStorage.getItem('s89:bookView') || 'right';
  const VB = { right: ['#EAF0FE', '#1D3FB8'], wrong: ['#FDF0E6', '#9A4209'], open: ['#F3F2EE', '#3E4149'] };
  const KC = { equity: '#D9620F', etf: '#2F5BEA', index: '#2F5BEA', gold: '#C9A227', cash: '#D3D0C7' };
  async function draw() {
    const d = await api('/api/book?market=' + (book === 'us' ? 'US' : 'IN'));
    const days = d.days || [], nifty = d.nifty || [];
    const c = days.map((x) => x[1] / days[0][1] * 100), b = nifty.map((x) => x[1] / nifty[0][1] * 100);
    const all = c.concat(b), lo = Math.min(...all) * 0.995, hi = Math.max(...all) * 1.005;
    const curve = { claude: c.length > 1 ? path(c, 900, 260, lo, hi, 6) : '', base: b.length > 1 ? path(b, 900, 260, lo, hi, 6) : '', you: '' };
    const marks = (d.log || []).filter((l) => days.length > 1).map((l) => { const i = days.findIndex((x) => String(x[0]) >= l.when); return i < 0 ? null : { x: (i / (days.length - 1) * 900).toFixed(1), label: l.when + ' · weekly look' }; }).filter(Boolean);
    const rel = d.rel || {}, px = (v) => 30 + (Math.min(90, Math.max(40, v)) - 40) / 50 * 200, py = (v) => 210 - (Math.min(90, Math.max(40, v)) - 40) / 50 * 200;
    const points = (rel.points || []).map((p) => ({ said: Math.round(p.said * 100) + '%', act: Math.round(p.right * 100) + '%', l: p.word, x: px(p.said * 100).toFixed(1), y: py(p.right * 100).toFixed(1), yp: py(p.said * 100).toFixed(1), r: (4 + p.n / 2.5).toFixed(1) }));
    const dec = (d.dec || []).map((x) => ({ when: x.when, what: x.what, said: x.said, res: x.res, v: x.v, vb: VB[x.v][0], vf: VB[x.v][1] }));
    if (!dec.length) dec.push({ when: '', what: 'No decisions yet', said: 'Every decision is scored at 5, 20 and 60 sessions, after tax.', res: '', v: 'open', vb: VB.open[0], vf: VB.open[1] });
    const log = (d.log || []).map((l) => ({ when: l.when, kind: l.kind, t: l.t, after: l.after }));
    if (!log.length) log.push({ when: '', kind: 'not yet', t: 'The weekly look runs after the first Friday close the app is open for.', after: 'It writes what worked, what did not and what to test next; it never changes a rule by itself.' });
    const blue = '#2F5BEA', orange = '#D9620F', lb = '#93A9F6';
    const rows = (d.hold || []).map((h) => { const w = h.weight || 0, lt = h.days_left != null && h.days_left <= 0;
      return { name: h.name, sleeve: h.kind === 'cash' ? 'reserve and cash' : (h.kind || '') + (h.you ? ' · you hold it too' : ''), color: KC[h.kind] || (book === 'us' ? lb : orange), weight: w.toFixed(1) + '%', barW: Math.min(w / 55 * 100, 100) + '%',
        ret: h.ret == null ? '—' : (h.ret >= 0 ? '+' : '−') + Math.abs(h.ret).toFixed(1) + '%', rc: (h.ret || 0) >= 0 ? '#1D3FB8' : '#9A4209',
        stopW: h.stop_pct == null ? '0%' : Math.min(h.stop_pct / 35 * 100, 100) + '%', stopC: h.stop_pct != null && h.stop_pct < 10 ? orange : lb, stop: h.stop_pct == null ? 'no stop' : h.stop_pct.toFixed(0) + '% away',
        clock: h.days_left == null ? '—' : lt ? 'long-term' : h.days_left + ' days left', thesis: h.plan ? 'intact' : 'n/a', tc: h.plan ? blue : '#C9C6BD' }; });
    const kinds = {}; (d.hold || []).forEach((h) => { const k = h.kind === 'cash' ? 'Cash' : (h.kind === 'equity' ? 'Stocks' : 'Funds'); kinds[k] = (kinds[k] || 0) + (h.weight || 0); });
    const MC = { Funds: blue, Stocks: orange, Cash: '#D3D0C7' };
    const mix = [{ l: 'Now', o: 1, parts: Object.keys(kinds).map((k) => ({ w: kinds[k].toFixed(0) + '%', c: MC[k] })) }];
    const r = d.rules || {};
    const tabs = [['in', 'India book'], ['us', 'US book']].map(([k, l]) => ({ label: l, on: k === book, bg: k === book ? '#17181C' : 'transparent', fg: k === book ? '#FFFFFF' : '#3E4149', pick: () => { book = k; sessionStorage.setItem('s89:book', k); draw(); } }));
    const views = [['right', 'Is it right?'], ['hold', 'Its holdings']].map(([k, l]) => ({ label: l, on: k === view, bg: k === view ? '#17181C' : 'transparent', fg: k === view ? '#FFFFFF' : '#3E4149', pick: () => { view = k; sessionStorage.setItem('s89:bookView', k); draw(); } }));
    const fri = new Date(); fri.setDate(fri.getDate() + ((5 - fri.getDay() + 7) % 7 || 7));
    const months = days.length > 1 ? [0, 1, 2, 3, 4, 5].map((k) => new Date(days[Math.round(k * (days.length - 1) / 5)][0]).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })) : [];
    await render(el, 'book', { months, views, tabs, isRight: view === 'right', isHold: view === 'hold', toHold: () => { view = 'hold'; draw(); },
      kpis: (d.kpis || []).map((k) => ({ v: k.v, l: k.l })), baseName: book === 'us' ? 'S&P 500' : 'Nifty 500', curve, marks, rel: points,
      relNote: rel.text || '', brier: rel.brier == null ? '—' : rel.brier.toFixed(3), brierX: rel.brier == null ? '0%' : (Math.min(rel.brier / 0.3, 1) * 100).toFixed(0) + '%', dec, log,
      nextLook: 'next look: after the close on ' + fri.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' }),
      hold: { rows, kpis: (d.hold_kpis || []).map((k) => ({ v: k.v, l: k.l, c: '#17181C' })), mix, legend: Object.keys(kinds).map((k) => ({ n: k, c: MC[k] })),
        rules: [{ v: String(r.stops == null ? '—' : r.stops), l: 'stops watched' }, { v: String(r.trades == null ? '—' : r.trades), l: 'trades so far' }, { v: String(r.over_rails == null ? '—' : r.over_rails), l: 'over a rail' }, { v: r.breaker || '—', l: 'the fall breaker' }] } });
  }
  await draw();
});
