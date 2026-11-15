/* Lab: the design's Lab screen. Pairs (the largest holdings two by two, cointegration by code), Simulate (the block bootstrap of the stored history: normal, the
   March 2020 episode; "Rates up 1%" has no preset in code and says so) and Forecast (the stored forecast fan and how often past bands caught the outcome). All code, 0 tokens. */
S89.register('lab', async (el) => {
  const { rs, api, post, render } = S89;
  const st = { tab: sessionStorage.getItem('s89:labTab') || 'pairs', pair: 0, sc: 'normal', hz: 60, subj: null };
  let pairs = null, sim = null, simErr = '', fc = null;
  const K = { tied: ['tied', 'Tied together', '#EAF0FE', '#1D3FB8'], loose: ['loosely tied', 'Loosely tied', '#F3F2EE', '#3E4149'], 'not tied': ['not tied', 'Not tied', '#FDF0E6', '#9A4209'] };
  const pill = (on) => ({ bg: on ? '#17181C' : '#FFFFFF', fg: on ? '#FFFFFF' : '#3E4149', bd: on ? '#17181C' : '#E6E4DD' });
  const mk = (list, cur, set) => list.map(([k, l]) => Object.assign(pill(k === cur), { label: l, on: k === cur, pick: () => { set(k); draw(); } }));
  function pathOf(a, x0, x1, lo, hi, h, pad) { return a.map((v, i) => (i ? 'L' : 'M') + (x0 + (a.length > 1 ? i / (a.length - 1) : 0) * (x1 - x0)).toFixed(1) + ' ' + (pad + (1 - (v - lo) / ((hi - lo) || 1)) * (h - 2 * pad)).toFixed(1)).join(' ') + ' '; }
  async function ask(text) { try { await post('/api/assistant', { text, road: 'full' }); location.hash = '#/chat'; } catch (e) { alert(e.message); } }
  const pc = (x) => (x >= 1 ? '+' : '−') + Math.abs((x - 1) * 100).toFixed(1) + '%';

  async function load() {
    if (st.tab === 'pairs' && !pairs) pairs = (await api('/api/lab/pairs')).pairs || [];
    if (st.tab === 'sim' && !sim && !simErr) {
      const basis = (await api('/api/mine?tab=in')).rows.length ? 'mine' : 'paper';
      try { sim = await post('/api/lab/simulate', { scenario: st.sc, horizon: st.hz, basis }); simErr = ''; } catch (e) { sim = null; simErr = e.message; }
    }
    if (st.tab === 'fc' && !fc) fc = await api('/api/lab/forecast?market=IN' + (st.subj ? '&subject=' + encodeURIComponent(st.subj) : ''));
  }
  function pairVals() {
    const ok = (pairs || []).filter((p) => !p.error);
    if (!ok.length) return { list: [], pair: { a: '', b: '', tagLong: 'No pair yet', cb: '#F3F2EE', cf: '#3E4149', verdict: (pairs || []).length ? (pairs[0].error || 'Not enough shared history.') : 'Pairs need at least two stocks with stored prices: your Kite holdings, or Claude\'s book.', pa: '', pb: '', pz: '', zy: '75', label1: '', label2: '', stats: [], method: '', months: [] } };
    if (st.pair >= ok.length) st.pair = 0;
    const list = ok.map((p, i) => { const on = i === st.pair, k = K[p.verdict]; return { a: p.a, b: p.b, pv: p.p_value.toFixed(3), tag: k[0], cb: k[2], cf: k[3], on, bg: on ? '#F3F6FE' : '#FFFFFF', bd: on ? '#B9C8FB' : '#EFEDE6', pick: () => { st.pair = i; draw(); } }; });
    const q = ok[st.pair], k = K[q.verdict], A = q.series_a, B = q.series_b, all = A.concat(B), lo = Math.min(...all), hi = Math.max(...all);
    const z = Math.max(-3.5, Math.min(3.5, q.gap_z));
    const verdict = q.verdict === 'tied' ? `When the gap between them opens, it tends to close. Half of any gap has closed in about ${q.half_life_days} sessions. Right now the gap is ${q.gap_z.toFixed(1)} standard deviations` + (Math.abs(q.gap_z) >= 2 ? ', outside the usual band.' : ', inside the usual band.')
      : q.verdict === 'loose' ? `There is some pull back, but the test is not convincing (p-value ${q.p_value.toFixed(3)}). Treat a gap as a hint, not a signal.`
      : `They often move the same way on the same day (correlation ${q.correlation.toFixed(2)}), but the gap between them wanders and does not come back. Moving together day to day is not the same as being tied.`;
    const d = q.dates || [], months = d.length ? [0, 1, 2, 3].map((i) => new Date(d[Math.round(i * (d.length - 1) / 3)]).toLocaleDateString('en-IN', { month: 'short', year: i === 0 || i === 3 ? 'numeric' : undefined })) : [];
    return { list, pair: { a: q.a, b: q.b, tagLong: k[1], cb: k[2], cf: k[3], verdict, pa: pathOf(A, 0, 900, lo, hi, 190, 8), pb: pathOf(B, 0, 900, lo, hi, 190, 8), pz: `M0 75 L900 ${(75 - z / 3.5 * 70).toFixed(1)}`, zy: (75 - z / 3.5 * 70).toFixed(1),
      days: q.days, backtest: () => ask(`Backtest trading the gap between ${q.a} and ${q.b}: a registered study, against the index after tax.`),
      save: () => ask(`Remember for the graph: ${q.a} and ${q.b} are ${k[1].toLowerCase()} (p-value ${q.p_value.toFixed(3)}, half-life ${q.half_life_days == null ? 'none' : q.half_life_days + ' sessions'}, ${q.days} sessions to ${(q.dates || []).slice(-1)[0] || 'today'}).`),
      label1: `${q.a} and ${q.b} over ${q.days} sessions, both starting at 100`, label2: `The gap between ${q.a} and ${q.b} now: ${q.gap_z.toFixed(1)} standard deviations`, months,
      method: `Engle–Granger test on ${q.days} daily closes, hedge ratio by least squares, half-life from the gap's pull back to zero. ${q.note}.`,
      stats: [{ v: q.p_value.toFixed(3), l: 'test p-value (under 0.05 = tied)' }, { v: q.gap_z.toFixed(1) + 'σ', l: 'gap now' }, { v: q.half_life_days == null ? 'none' : q.half_life_days + ' sessions', l: 'half-life of a gap' },
        { v: q.hedge_ratio.toFixed(2), l: 'hedge ratio' }, { v: q.correlation.toFixed(2), l: 'correlation of daily moves' }, { v: String(q.days), l: 'daily closes used' }] } };
  }
  function simVals() {
    if (!sim) return { paths: [], band: '', med: '', y0: '0', y90: '0', end: st.hz + ' sessions', note: simErr || 'Working it out…', label: '', title: 'Possible futures', stats: [] };
    const P = sim.mult_paths, b = sim.band, flat = P.flat().concat(b.p10, b.p90), lo = Math.min(0.86, Math.min(...b.p10) * 0.97), hi = Math.max(...flat) * 1.01;
    const y = (v) => (6 + (1 - (v - lo) / (hi - lo)) * 348).toFixed(1);
    const top = pathOf(b.p90, 0, 900, lo, hi, 360, 6), bot = pathOf(b.p10.slice().reverse(), 900, 0, lo, hi, 360, 6).replace(/^M/, 'L');
    const whose = sim.basis === 'mine' ? 'Your money' : "Claude's book";
    return { paths: P.map((a) => ({ d: pathOf(a.map((x) => Math.max(lo, Math.min(hi, x))), 0, 900, lo, hi, 360, 6) })), band: top + bot + 'Z', med: pathOf(b.p50, 0, 900, lo, hi, 360, 6), y0: y(1), y90: y(0.9),
      end: sim.horizon === 250 ? '1 year' : sim.horizon + ' sessions', title: `${whose}, ${sim.paths_run.toLocaleString('en-IN')} possible futures`,
      note: (sim.scenario === 'covid' ? 'The days of the March 2020 fall, resampled. ' : 'Ordinary ups and downs, resampled from the stored history. ') + (sim.note || '') + ' ' + sim.caveat + '.',
      label: `${sim.paths_run} simulated paths of ${whose.toLowerCase()} over ${sim.horizon} sessions`,
      stats: [{ v: Math.round(sim.p_fall10 * 100) + '%', l: 'chance of a 10% fall at some point', c: sim.p_fall10 > 0.25 ? '#9A4209' : '#17181C' },
        { v: pc(sim.middle / sim.start_inr), l: 'middle outcome · ' + rs(sim.middle), c: '#17181C' }, { v: pc(sim.worst_1_in_20 / sim.start_inr), l: 'worst 1 in 20 · ' + rs(sim.worst_1_in_20), c: '#9A4209' },
        { v: pc(sim.best_1_in_20 / sim.start_inr), l: 'best 1 in 20 · ' + rs(sim.best_1_in_20), c: '#1D3FB8' }] };
  }
  function fcVals() {
    const none = { hist: '', mid: '', b80: '', b50: '', xNow: '720', range80: '—', range50: '—', label: '', cover: [], coverNote: '', from: '', to: '' };
    if (!fc || fc.empty || !fc.fan.length) return Object.assign(none, { coverNote: (fc && fc.empty) || 'No forecast yet.' });
    const H = fc.hist.map((x) => x[1]), last = H.length ? H[H.length - 1] : fc.base, xNow = 900 * 80 / 100, maxH = Math.max(...fc.fan.map((f) => f.h));
    const at = (k) => [last].concat(fc.fan.map((f) => f[k] || last));
    const u80 = at('q90'), l80 = at('q10'), u50 = at('q75'), l50 = at('q25'), mid = at('q50');
    const lo = Math.min(...H.concat(l80)) * 0.99, hi = Math.max(...H.concat(u80)) * 1.01;
    const band = (u, l) => pathOf(u, xNow, 900, lo, hi, 340, 8) + pathOf(l.slice().reverse(), 900, xNow, lo, hi, 340, 8).replace(/^M/, 'L') + 'Z';
    const fm = (x) => Math.round(x).toLocaleString('en-IN');
    const cv = (fc.coverage || []).find((c) => c.h === maxH) || (fc.coverage || [])[0];
    return { hist: pathOf(H, 0, xNow, lo, hi, 340, 8), mid: pathOf(mid, xNow, 900, lo, hi, 340, 8), b80: band(u80, l80), b50: band(u50, l50), xNow: xNow.toFixed(1),
      range80: fm(l80[l80.length - 1]) + ' – ' + fm(u80[u80.length - 1]), range50: fm(l50[l50.length - 1]) + ' and ' + fm(u50[u50.length - 1]),
      label: `${fc.subject}: last ${H.length} sessions and the forecast fan for the next ${maxH}`, from: H.length + ' sessions ago', to: '+' + maxH + ' session' + (maxH > 1 ? 's' : ''),
      cover: cv ? [{ l: '8-in-10 band caught the outcome', v: cv.share == null ? '—' : Math.round(cv.share * 100) + '%', t: '80%' }, { l: '9-in-10 band caught the outcome', v: cv.share90 == null ? '—' : Math.round(cv.share90 * 100) + '%', t: '90%' }] : [],
      coverNote: cv ? (cv.judge ? `From ${cv.n} scored forecasts at ${cv.h} session${cv.h > 1 ? 's' : ''}. Below the black tick means the fans are a little too narrow.` : `${cv.n} scored so far, needs 20 to judge.`) : 'None scored yet.' };
  }
  async function draw() {
    await load();
    const p = st.tab === 'pairs' ? pairVals() : { list: [], pair: pairVals().pair };
    const subjects = (fc && fc.subjects) || [];
    await render(el, 'lab', {
      tabs: mk([['pairs', 'Pairs'], ['sim', 'Simulate'], ['fc', 'Forecast']], st.tab, (k) => { st.tab = k; sessionStorage.setItem('s89:labTab', k); }),
      tabNote: { pairs: 'Which of the stocks held are tied together, so a gap between them tends to close.', sim: 'What could happen to the money, resampled from the stored history.', fc: 'Where prices could be, and how often past fans were right.' }[st.tab],
      isPairs: st.tab === 'pairs', isSim: st.tab === 'sim', isFc: st.tab === 'fc', simStart: sim ? rs(sim.start_inr) + (sim.coverage && sim.coverage.uncovered_pct > 0.5 ? ' (the ' + Math.round(sim.coverage.covered_pct) + '% with price history)' : '') : '—',
      pairs: p.list, pair: p.pair,
      scen: mk([['normal', 'Normal times'], ['covid', 'March 2020 again'], ['rates', 'Rates up 1% · tested: not supported']], st.sc, (k) => { st.sc = k; sim = null; simErr = ''; }),
      hor: mk([[20, '20 sessions'], [60, '60 sessions'], [250, '1 year']], st.hz, (k) => { st.hz = k; sim = null; simErr = ''; }), sim: simVals(),
      inst: mk(subjects.map((s) => [s, s === 'US_SP500' ? 'S&P 500' : s]), (fc && fc.subject) || '', (k) => { st.subj = k; fc = null; }), fc: fcVals() });
  }
  await draw();
});
