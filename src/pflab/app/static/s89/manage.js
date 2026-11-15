/* Add and watch: the design's Manage screen. His real US holdings entered by hand (never the paper ledger) and his watchlist (names he does not own; the alarm
   lane checks them too; up to 25). Every change goes to the backend at once and the screen re-reads it. */
S89.register('manage', async (el) => {
  const { usd, rs, pct, api, post, render } = S89;
  const f = { t: '', q: '', p: '', d: '' }, w = { n: '', m: 'India', y: '', al: { 'moves 3%+': true, news: true, results: false, 'near its 52-week low': false } };
  let fErr = '', wErr = false, timer = null;
  const setF = (k) => (e) => { f[k] = e.target.value; };
  const setW = (k) => (e) => { w[k] = e.target.value; };
  async function draw() {
    const [m, wl] = await Promise.all([api('/api/mine?tab=us'), api('/api/mine/watch')]);
    const us = (m.rows || []).map((h) => ({ t: h.symbol, name: h.price == null ? 'price after the next check' : 'last close ' + usd(h.price) + (h.price_as_of ? ' · ' + h.price_as_of : ''), d: h.bought_on || 'date not given', q: h.qty,
      qid: 'q-' + h.symbol, avg: usd(h.avg), val: h.value_inr == null ? 'next check' : rs(h.value_inr), ret: pct(h.since_buy_pct), rc: h.since_buy_pct == null ? '#5B5E66' : (h.since_buy_pct >= 0 ? '#1D3FB8' : '#9A4209'),
      setQ: (e) => { clearTimeout(timer); const v = e.target.value; timer = setTimeout(async () => { try { await post('/api/mine/us', { action: 'set', ticker: h.symbol, shares: v }); fErr = ''; } catch (x) { fErr = x.message; } draw(); }, 900); },
      remove: async () => { try { await post('/api/mine/us', { action: 'remove', ticker: h.symbol }); } catch (x) { fErr = x.message; } draw(); } }));
    const total = (m.rows || []).reduce((a, r) => a + (r.value_inr || 0), 0);
    const alerts = Object.keys(w.al).map((k) => { const on = !!w.al[k]; return { label: k, on, bg: on ? '#17181C' : '#FFFFFF', fg: on ? '#FFFFFF' : '#3E4149', bd: on ? '#17181C' : '#E6E4DD', flip: () => { w.al[k] = !on; draw(); } }; });
    const rows = (wl.rows || []).map((x) => ({ n: x.symbol, m: x.market, y: x.why || 'No reason given', px: '', note: x.note ? 'latest headline: ' + x.note : 'nothing heard yet', al: (x.alerts || []).map((l) => ({ l })),
      remove: async () => { await post('/api/mine/watch', { action: 'remove', symbol: x.symbol }); draw(); } }));
    await render(el, 'manage', {
      us, usEmpty: us.length === 0, usTotal: total ? '≈ ' + rs(total) : 'value after the next price check',
      addUs: async (e) => { e.preventDefault(); try { await post('/api/mine/us', { action: 'add', ticker: f.t, shares: f.q, avg_price: f.p, bought_on: f.d || null }); f.t = f.q = f.p = f.d = ''; fErr = ''; } catch (x) { fErr = x.message; } draw(); },
      f: { t: f.t, q: f.q, p: f.p, d: f.d, setT: setF('t'), setQ: setF('q'), setP: setF('p'), setD: setF('d'), err: !!fErr, errText: fErr },
      wl: rows, wlCount: `${wl.count} of ${wl.cap}`,
      addWl: async (e) => { e.preventDefault(); if (!w.n.trim()) { wErr = true; draw(); return; } try { await post('/api/mine/watch', { action: 'add', symbol: w.n, market: w.m, why: w.y, alerts: Object.keys(w.al).filter((k) => w.al[k]) }); w.n = ''; w.y = ''; wErr = false; } catch (x) { fErr = x.message; } draw(); },
      w: { n: w.n, m: w.m, y: w.y, setN: setW('n'), setM: setW('m'), setY: setW('y'), alerts, err: wErr },
    });
  }
  await draw();
});
