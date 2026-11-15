/* Usage: the design's Usage screen. The plan's tokens today against the sum of the day budgets, quick vs full answers, what the tokens bought, tokens by day for 30 days,
   today's split by purpose, and the agents' model runs per day. Tokens only: the plan has no per-token price. */
S89.register('usage', async (el) => {
  const { api, render, kTok } = S89;
  const d = await api('/api/usage/plan');
  const used = d.used || {}, bud = d.budgets || {}, calls = d.calls || {}, st = d.state || {};
  const U = Object.values(used).reduce((a, x) => a + x, 0), B = Object.values(bud).reduce((a, x) => a + x, 0), f = B ? Math.min(1, U / B) : 0, C = 2 * Math.PI * 56;
  const nq = calls.chat_light || 0, nf = calls.chat || 0, n = nq + nf;
  const ser = d.series || [], mx = Math.max(1, ...ser.map((s) => s.work + s.full + s.quick)), step = 720 / Math.max(1, ser.length);
  const days = ser.map((s, i) => { const h1 = s.work / mx * 160, h2 = s.full / mx * 160, h3 = s.quick / mx * 160, x = i * step + (step - 16) / 2;
    return { x: x.toFixed(1), y1: (170 - h1).toFixed(1), h1: h1.toFixed(1), y2: (170 - h1 - h2).toFixed(1), h2: h2.toFixed(1), y3: (170 - h1 - h2 - h3).toFixed(1), h3: h3.toFixed(1) }; });
  const lbl = (s) => (s ? new Date(s).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '');
  const NAMES = [['desk', 'Daily desk', '#2F5BEA'], ['cases', 'Cases and alarms', '#1D3FB8'], ['chat', 'Full answers', '#D9620F'], ['chat_light', 'Quick answers', '#C9C6BD'], ['build', 'Fixer', '#5B2A86']];
  const split = NAMES.map(([k, l, c]) => ({ name: l, amt: kTok(used[k] || 0) + ' of ' + kTok(bud[k] || 0), w: (bud[k] ? Math.min(100, (used[k] || 0) / bud[k] * 100) : 0).toFixed(0) + '%', c }));
  const hm = Math.max(1, ...(d.heat || []).flatMap((r) => r.cells));
  const heat = (d.heat || []).map((r) => ({ name: r.name, cells: r.cells.map((v) => ({ bg: v ? `rgba(47, 91, 234, ${(0.18 + 0.82 * v / hm).toFixed(2)})` : '#F3F2EE' })) }));
  const b = d.bought || {};
  await render(el, 'usage', { days, split, heat, u: {
    aria: `${kTok(U)} tokens used of the ${kTok(B)} daily budget`, dash: f > 0.005 ? `${(f * C).toFixed(1)} ${C.toFixed(1)}` : `0 ${C.toFixed(1)}`, pct: Math.round(f * 100) + '%', used: kTok(U), budget: kTok(B),
    state: st.thinking === 'paused' ? 'thinking paused' + (st.paused_until ? ' until ' + st.paused_until.slice(11) : '') : st.signed_in ? 'thinking running · signed in on your plan' : 'not signed in',
    nq, nf, aq: nq ? 'about ' + kTok((used.chat_light || 0) / nq) + ' tokens each' : 'none today', af: nf ? 'about ' + kTok((used.chat || 0) / nf) + ' tokens each' : 'none today',
    wq: n ? (nq / n * 100).toFixed(0) + '%' : '0%', wf: n ? (nf / n * 100).toFixed(0) + '%' : '0%', roadLine: n ? `${nq} of ${n} chat answers took the quick road` : 'No chat answers today yet',
    b1: b.desk || 0, b2: b.cases || 0, b3: b.fixes_waiting || 0, b3l: (b.fixes_waiting === 1 ? 'fix' : 'fixes') + ' waiting for your Yes', b4: b.builds || 0,
    x0: lbl(ser.length && ser[0].day), x1: lbl(ser.length && ser[Math.floor(ser.length / 2)].day), x2: lbl(ser.length && ser[ser.length - 1].day), left: kTok(Math.max(0, B - U)) } });
});
