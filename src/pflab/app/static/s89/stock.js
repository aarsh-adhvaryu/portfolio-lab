/* S89b One stock: daily or weekly candles with volume, the volume profile, the stop Claude's book uses, the graph's events, what the stored features see, the forecast band and the book's plan for it. All from stored data. */
S89.register('stock', async (el) => {
  const { esc, num, rs, api, empty, pct, cls } = S89;
  const sym = decodeURIComponent((location.hash.split('/')[2] || '').toUpperCase());
  let tf = sessionStorage.getItem('s89:stockTf') || 'day';
  if (!sym) { el.innerHTML = `<h2 style="margin:0">One stock</h2><div class="card">${empty('Open a stock from Your money or from a Graph node.')}</div>`; return; }
  async function draw() {
    let d;
    try { d = await api('/api/stock/' + encodeURIComponent(sym) + '?tf=' + tf); } catch (e) { el.innerHTML = `<div class="row"><a href="#/money">Your money</a><span class="muted">/</span><b>${esc(sym)}</b></div><div class="card">${empty(e.message)}</div>`; return; }
    if (d.empty) { el.innerHTML = `<div class="row"><a href="#/money">Your money</a><span class="muted">/</span><b>${esc(sym)}</b></div><div class="card">${empty(d.empty)}</div>`; return; }
    const bars = d.bars || [], W = 820, H = 260, VH = 60, lo = Math.min(...bars.map((b) => b.l)), hi = Math.max(...bars.map((b) => b.h)), mv = Math.max(1, ...bars.map((b) => b.v));
    const X = (i) => 8 + (i + 0.5) * ((W - 16) / bars.length), Y = (p) => 6 + (1 - (p - lo) / ((hi - lo) || 1)) * (H - 12), bw = Math.max(2, (W - 16) / bars.length * 0.62);
    const candles = bars.map((b, i) => { const up = b.c >= b.o, c = up ? '#2F5BEA' : '#D9620F'; return `<line x1="${X(i)}" x2="${X(i)}" y1="${Y(b.h)}" y2="${Y(b.l)}" stroke="${c}"/><rect x="${X(i) - bw / 2}" y="${Y(Math.max(b.o, b.c))}" width="${bw}" height="${Math.max(1, Math.abs(Y(b.o) - Y(b.c)))}" fill="${c}"/>`; }).join('');
    const vols = bars.map((b, i) => `<rect x="${X(i) - bw / 2}" y="${VH - b.v / mv * VH}" width="${bw}" height="${b.v / mv * VH}" fill="#C9CBD1"/>`).join('');
    const stop = d.stop != null && d.stop >= lo && d.stop <= hi ? `<line x1="0" x2="${W}" y1="${Y(d.stop)}" y2="${Y(d.stop)}" stroke="#D9620F" stroke-dasharray="5 4"/><text x="${W - 4}" y="${Y(d.stop) - 4}" text-anchor="end" font-size="11" fill="#9A4209">stop ${num(d.stop, 2)}</text>` : '';
    const pm = Math.max(1, ...(d.profile || []).map((p) => p.v));
    const prof = (d.profile || []).map((p) => `<rect x="${W + 6}" y="${Y(p.high)}" width="${p.v / pm * 90}" height="${Math.max(1, Y(p.low) - Y(p.high) - 1)}" fill="#E1E4EC"/>`).join('');
    const fc = d.forecast ? `<div class="small">Forecast band (next sessions): ${Object.entries(d.forecast.quantiles).filter(([k]) => ['0.05', '0.95'].includes(k)).map(([k, v]) => `${k === '0.05' ? 'low' : 'high'} ${pct(v * 100, 1, false)}`).join(' · ')} <span class="muted">made ${esc(d.forecast.as_of)}</span></div>` : '<div class="small muted">No stored forecast for this name.</div>';
    const ev = (d.events || []).length ? d.events.map((e) => `<div class="small"><span class="chip mute">${esc(e.kind)}</span> ${esc(e.text)} <span class="muted">${esc(e.at)}</span></div>`).join('') : '<span class="small muted">No events in the graph for this name in the last 60 days.</span>';
    const sees = d.sees ? Object.entries(d.sees).filter(([, v]) => typeof v !== 'object').slice(0, 8).map(([k, v]) => `<div class="row small"><span class="grow muted">${esc(k.replace(/_/g, ' '))}</span><b>${esc(typeof v === 'number' ? num(v, 2) : v)}</b></div>`).join('') : '<span class="small muted">No stored features.</span>';
    const plan = d.plan ? `<div class="row small"><span>Stop <b>${num(d.plan.stop, 2)}</b></span><span>Target <b>${d.plan.target != null ? num(d.plan.target, 2) : '—'}</b></span><span class="muted">opened ${esc(d.plan.opened_on)}</span></div>` : `<span class="small muted">${esc(d.note || '')}</span>`;
    el.innerHTML = `<div class="row"><a href="#/money">Your money</a><span class="muted">/</span><b style="font-size:17px">${esc(d.symbol)}</b><div class="tabs" style="margin-left:auto">${[['day', 'Day'], ['week', 'Week']].map(([k, l]) => `<button data-tf="${k}" class="${tf === k ? 'on' : ''}">${l}</button>`).join('')}<button disabled title="${esc(d.intraday)}">5 min · needs Kite</button></div></div>
      <section class="grid"><div class="card" style="flex:2 1 640px"><svg width="100%" viewBox="0 0 ${W + 100} ${H}" role="img" aria-label="Candles" style="max-height:300px">${candles}${stop}${prof}</svg>
        <svg width="100%" viewBox="0 0 ${W + 100} ${VH}" role="img" aria-label="Volume" style="max-height:70px">${vols}</svg><span class="small muted">${bars.length} ${tf === 'week' ? 'weeks' : 'days'} from stored prices; the grey bars on the right are the volume profile, worked out here.</span></div>
        <div class="col" style="flex:1 1 320px"><div class="card"><h2>Its plan for this stock</h2>${plan}</div><div class="card"><h2>What it sees</h2>${sees}</div><div class="card"><h2>Forecast</h2>${fc}</div></div></section>
      <div class="card"><h2>Events</h2>${ev}</div>`;
    el.querySelectorAll('[data-tf]').forEach((b) => { b.onclick = () => { tf = b.dataset.tf; sessionStorage.setItem('s89:stockTf', tf); draw(); }; });
  }
  await draw();
});
