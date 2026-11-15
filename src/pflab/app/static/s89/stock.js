/* One stock: the design's Stock screen. Daily or weekly candles with volume, the volume profile (worked out here from the same candles), the stop and plan Claude's
   book uses, the graph's events on the time axis, what the stored features see, and the forecast range. Opened from Your money ("Open candles") and the Graph. */
S89.register('stock', async (el) => {
  const { api, render, num, pct } = S89;
  const sym = decodeURIComponent((location.hash.split('/')[2] || '').toUpperCase());
  let tf = sessionStorage.getItem('s89:stockTf') || 'day';
  async function draw() {
    let d;
    try { d = await api('/api/stock/' + encodeURIComponent(sym || 'NONE') + '?tf=' + tf); } catch (e) { d = { symbol: sym, empty: sym ? e.message : 'Open a stock from Your money or from the Graph.' }; }
    const bars = (d.bars || []).slice(-60), n = bars.length;
    const lo0 = n ? Math.min(...bars.map((b) => b.l)) : 0, hi0 = n ? Math.max(...bars.map((b) => b.h)) : 1, stop = d.stop != null ? Number(d.stop) : null;
    const fq = d.forecast && d.forecast.quantiles ? d.forecast.quantiles : null, last = n ? bars[n - 1].c : 0;
    const fHi = fq ? last * (1 + Number(fq['0.9'] || fq['0.95'] || 0)) : null, fLo = fq ? last * (1 + Number(fq['0.1'] || fq['0.05'] || 0)) : null;
    const lo = Math.min(lo0, stop != null && stop > lo0 * 0.75 ? stop : lo0, fLo || lo0) * 0.995, hi = Math.max(hi0, fHi || hi0) * 1.005;
    const y = (p) => 300 - (p - lo) / ((hi - lo) || 1) * 270;
    const mv = Math.max(1, ...bars.map((b) => b.v));
    const step = n > 1 ? Math.min(11.5, 690 / n) : 11.5;
    const candles = bars.map((b, i) => { const x = 24 + i * step, up = b.c >= b.o, vh = b.v / mv * 70;
      return { x: x.toFixed(1), cx: (x + 3.5).toFixed(1), hi: y(b.h).toFixed(1), lo: y(b.l).toFixed(1), top: Math.min(y(b.o), y(b.c)).toFixed(1), h: Math.max(Math.abs(y(b.o) - y(b.c)), 1.5).toFixed(1), col: up ? '#2F5BEA' : '#D9620F', vy: (392 - vh).toFixed(1), vh: vh.toFixed(1) }; });
    const lx = 24 + (n - 1) * step + 3.5;
    let fan = '', fanMid = '';
    if (fq && n) { fan = `M${lx.toFixed(1)} ${y(last).toFixed(1)} L${(lx + 160).toFixed(1)} ${y(fHi).toFixed(1)} L${(lx + 160).toFixed(1)} ${y(fLo).toFixed(1)} Z`; fanMid = `M${lx.toFixed(1)} ${y(last).toFixed(1)} L${(lx + 160).toFixed(1)} ${y(last * (1 + Number(fq['0.5'] || 0))).toFixed(1)}`; }
    const B = 14, w = (hi0 - lo0) / B || 1, vol = new Array(B).fill(0);
    bars.forEach((b) => { const k = Math.min(B - 1, Math.max(0, Math.floor(((b.h + b.l + b.c) / 3 - lo0) / w))); vol[k] += b.v; });
    const vmax = Math.max(1, ...vol), poc = vol.indexOf(vmax), tot = vol.reduce((a, x) => a + x, 0);
    let a = poc, z = poc, acc = vol[poc]; while (acc < tot * 0.7 && (a > 0 || z < B - 1)) { if (z < B - 1 && (a === 0 || vol[z + 1] >= vol[a - 1])) acc += vol[++z]; else acc += vol[--a]; }
    const prof = vol.map((v, k) => ({ y: (y(lo0 + (k + 0.5) * w) - 7.5).toFixed(1), w: Math.max(2, v / vmax * 190).toFixed(1), fill: k === poc ? '#17181C' : (k >= a && k <= z ? '#93A9F6' : '#D3D0C7') }));
    const pocP = lo0 + (poc + 0.5) * w, vaTop = y(lo0 + (z + 1) * w), vaBot = y(lo0 + a * w);
    const evs = (d.events || []).map((e) => { const i = bars.findIndex((b) => b.d >= e.date); return i < 0 ? null : { x: (24 + i * step + 3.5).toFixed(1), k: String(e.kind || '?').charAt(0).toUpperCase(), t: String(e.kind || '').replace(/_/g, ' ').slice(0, 14) }; }).filter(Boolean).slice(0, 6);
    const obs = d.sees ? (d.sees.observations || d.sees.obs || []) : [];
    const sees = obs.length ? obs.slice(0, 5) : ['no stored features for this name'];
    const stopPct = stop != null && last ? (1 - stop / last) * 100 : null, pl = d.plan;
    const tfs = [['day', 'Day'], ['week', 'Week'], ['5min', '5 min · needs Kite']].map(([k, l]) => ({ label: l, bg: k === tf ? '#FFFFFF' : 'transparent', fg: k === tf ? '#17181C' : '#3E4149', w: k === tf ? 600 : 500,
      pick: () => { if (k === '5min') return; tf = k; sessionStorage.setItem('s89:stockTf', k); draw(); } }));
    const rLo = fq ? Math.min(fLo, last) * 0.97 : 0, rHi = fq ? Math.max(fHi, last) * 1.03 : 1, rp = (v) => (fq ? ((v - rLo) / ((rHi - rLo) || 1) * 100).toFixed(1) + '%' : '0%');
    const title = [d.symbol, d.mine ? `you hold ${num(d.mine.qty)}` : null, d.book_weight != null ? `${d.book_weight.toFixed(1)}% of Claude's book` : 'not in Claude\'s book'].filter(Boolean).join(' · ');
    await render(el, 'stock', { candles, fan, fanMid, prof, evs, sees, tfs,
      stopY: stop != null ? y(stop).toFixed(1) : '-50', stopLbl: stop != null ? (y(stop) + 4).toFixed(1) : '-50', pocY: n ? y(pocP).toFixed(1) : '-50', pocLbl: n ? (y(pocP) - 6).toFixed(1) : '-50',
      vaTop: n ? vaTop.toFixed(1) : '0', vaH: n ? Math.max(0, vaBot - vaTop).toFixed(1) : '0',
      s: { title: d.empty ? (d.symbol || 'One stock') : title, name: d.symbol || '', n, price: n ? '₹' + Number(last).toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—',
        day: n > 1 ? pct((last / bars[n - 2].c - 1) * 100) + (tf === 'week' ? ' this week' : ' today') : (d.empty || ''),
        stopText: stop != null ? `stop ₹${num(stop, 0)} · ${stopPct.toFixed(0)}% below` : 'no stop: not in Claude\'s book', stopPct: stopPct != null ? stopPct.toFixed(0) + '% below' : 'none',
        target: pl && pl.target != null ? '₹' + num(pl.target, 0) : 'none', tax: pl && pl.tax_boundary ? (new Date(pl.tax_boundary) <= new Date() ? 'long-term' : 'long-term from ' + pl.tax_boundary) : '—', thesis: pl ? 'intact' : 'not in the book',
        range: fq ? '₹' + num(fLo, 0) + ' – ₹' + num(fHi, 0) : 'no stored forecast', rangeLabel: fq ? '8 in 10 chance' : '', sym: encodeURIComponent(d.symbol || ''), bl: rp(fLo), bw: fq ? ((fHi - fLo) / ((rHi - rLo) || 1) * 100).toFixed(1) + '%' : '0%', bm: fq ? rp(last) : '-10%' } });
  }
  await draw();
});
