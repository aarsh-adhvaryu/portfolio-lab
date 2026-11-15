/* Home: the design's Main screen. Needs you, your money vs Claude's book, what it is doing now, Heard, its eyes, the fall gauge and the top storyline,
   with the three broken-state banners (Kite, plan limit, a source down) driven by real state. */
S89.register('home', async (el) => {
  const { esc, rs, rsd, pct, ago, api, post, render, path } = S89;
  const answered = {};
  const KIND = { 'do this': ['#9A4209', '#FDF0E6'], alarm: ['#9A4209', '#FDF0E6'], 'fix ready': ['#1D3FB8', '#F3F6FE'], plan: ['#1D3FB8', '#F3F6FE'], question: ['#3E4149', '#F6F5F1'] };
  const BANNER = { kite: ['#FDF0E6', '#F0A56E', '#9A4209'], down: ['#FDF0E6', '#F0A56E', '#9A4209'], plan: ['#EAF0FE', '#B9C8FB', '#1D3FB8'] };
  const STAGES = ['Perceive', 'Storylines', 'Forecast', 'Simulate', 'Decide', 'Act', 'Score'];
  const STAGE_OF = { alarm: 0, collect: 0, prices: 0, filings: 0, news_s81_topup: 0, kg2_nightly: 0, catch_up: 0, data_s79b: 0, sec_8k: 0, story_daily: 1, situation: 1, forecast_loop: 2, fcast: 2,
    stress_daily: 3, sims: 3, think_loop: 4, strategist: 4, lab_close: 4, core_loop: 5, session_job: 5, us_session: 5, us_close: 5, preopen_job: 5, pick_score: 6, week_check: 6, fills_calibrate: 6 };

  async function act(n, yes) {
    try {
      if (n.id.startsWith('card:')) await post('/api/assistant/messages/' + n.msg_id + '/action', { action: yes ? 'yes' : 'no' });
      else if (n.id.startsWith('q:')) await post('/api/questions/' + n.qid + '/answer', { text: yes ? 'yes' : 'no' });
      else if (n.id.startsWith('plan:')) await post('/api/plans/' + n.plan_id + '/' + (yes ? 'start' : 'cancel'));
      answered[n.id] = yes ? 'yes' : 'no';
    } catch (e) { answered[n.id] = 'error:' + e.message; }
    draw();
  }
  async function draw() {
    const d = await api('/api/home');
    const b = d.banner;
    const banner = b ? { on: true, bg: BANNER[b.kind][0], bd: BANNER[b.kind][1], fg: BANNER[b.kind][2], t: b.title, s: b.text, cta: b.cta, href: b.href } : { on: false };
    const seen = new Set(), needs = (d.needs || []).filter((n) => { const k = String(n.text || '').slice(0, 120); if (seen.has(k)) return false; seen.add(k); return true; }).map((n) => {
      const [kc, bg] = KIND[n.kind] || KIND.question, a = answered[n.id];
      const link = !!n.link, plan = !!n.plan_card, fix = n.kind === 'fix ready';
      const err = a && a.startsWith('error:');
      return { kind: n.kind, kc, bg: a && !err ? '#F6F5F1' : bg, when: n.when || '', t: n.text, s: plan ? n.detail + ' · ' + (n.steps || []).map((s) => s.n + '. ' + s.text).join(' · ') : (n.detail || ''),
        open: !a || err, done: !!a && !err, isLink: link, isAsk: !link, href: n.link || '#', yes: link ? (n.kind === 'do this' ? 'Log in' : 'Open the case') : plan ? 'Start' : fix ? 'Yes, apply' : 'Yes',
        no: plan ? 'Cancel' : 'No', hasMore: plan || fix, more: plan ? 'Change it in the chat' : 'See the changes', moreHref: '#/chat',
        doneText: err ? a.slice(6) : a === 'yes' ? (plan ? 'Started. The steps tick off as they finish.' : 'Done.') : (plan ? 'Cancelled. Nothing ran.' : 'Noted.'),
        onYes: () => act(n, true), onNo: () => act(n, false) };
    });
    const paper = d.paper || null, mine = d.mine || {};
    const days = paper && paper.days ? paper.days.filter((x) => x[1] != null) : [], nifty = paper && paper.nifty ? paper.nifty.filter((x) => x[1] != null) : [];
    const bk = days.map((x) => x[1] / days[0][1] * 100), bs = nifty.map((x) => x[1] / nifty[0][1] * 100);
    const all = bk.concat(bs), lo = Math.min(...all) * 0.995, hi = Math.max(...all) * 1.005;
    const lines = { book: bk.length > 1 ? path(bk, 900, 220, lo, hi, 6) : '', base: bs.length > 1 ? path(bs, 900, 220, lo, hi, 6) : '', you: '' };
    const months = days.length > 1 ? [0, 1, 2, 3].map((k) => { const x = days[Math.round(k * (days.length - 1) / 3)][0]; return new Date(x).toLocaleDateString('en-IN', { month: 'short', day: k === 3 ? undefined : 'numeric' }); }) : ['', '', '', ''];
    const bkRet = bk.length > 1 ? bk[bk.length - 1] - 100 : null, bsRet = bs.length > 1 ? bs[bs.length - 1] - 100 : null;
    const race = days.length > 1 ? `Since it started: Claude ${pct(bkRet)} · baseline ${pct(bsRet)} · yours is not kept as history` : "Claude's book has no closes yet";
    const bookToday = days.length > 1 ? days[days.length - 1][1] - days[days.length - 2][1] : null;
    const plan = d.plan || {};
    const JOB = { candles_5m: 'fetched five-minute candles', investigation_daily: 'worked on the day’s saved study', bars_1m: 'recorded minute bars', collect: 'collected the day’s data', prices: 'updated prices', filings: 'read company filings', news_s81_topup: 'read the news', alarm: 'checked headlines on what you hold',
      conductor: 'checked every job is on time', forecast_loop: 'made and scored forecasts', fcast: 'made forecasts', story_daily: 'updated the storylines', kg2_nightly: 'updated the knowledge graph',
      guards: 'checked the limits', tradecheck: 'checked your Kite holdings', desk: 'Claude’s daily desk session', desk_us: 'Claude’s US morning session', paper: 'marked Claude’s book at the close',
      us_session: 'watched the US session', catch_up: 'caught up after the laptop was off', backup: 'backed up the record', week_check: 'checked its first week', problems_week: 'listed problems',
      operator_plans: 'worked on a plan you started', think: 'thought a case through', sims: 'ran the night’s simulation', summary_evening: 'wrote the evening report', summary_morning: 'wrote the morning plan' };
    const whatOf = {}; (d.recent || []).forEach((r) => { if (r.what) whatOf[r.job] = r.what.charAt(0).toLowerCase() + r.what.slice(1); });
    const plain = (j) => JOB[j] || whatOf[j] || String(j || '').replace(/_s\d+\w*$/, '').replace(/_/g, ' ');
    const tk = Object.values(plan.tokens_today || {}).reduce((a, x) => a + Number(x.used || 0), 0);
    const steps = (d.recent || []).map((r, i) => ({ name: `${String(r.at).slice(11, 16)} · ${plain(r.job)}${r.status === 'failed' ? ' (failed)' : ''}`, fg: i === 0 ? '#FFFFFF' : '#C9CBD1', w: i === 0 ? 700 : 500,
      dot: r.status === 'failed' ? '#F0A56E' : (i === 0 ? '#7F9AF4' : '#3E4F86'), ring: i === 0 ? '#B9C8FB' : '#3A3C44' }));
    if (!steps.length) steps.push({ name: 'nothing has run yet', fg: '#C9CBD1', w: 500, dot: '#2B2D33', ring: '#3A3C44' });
    const lj = d.last_job, paused = plan.thinking === 'paused';
    const tokLine = ` Claude used ${S89.kTok(tk)} tokens of your plan today (Usage shows where).`;
    const doing = paused ? { big: 'Thinking paused', small: `Until ${plan.paused_until || 'the reset'}. Stops and rails still run without the model.`, when: 'plan limit', dot: '#9A9DA4', pulse: '' }
      : lj ? { big: lj.finished_at ? 'Watching' : 'Working', small: `Now: ${plain(lj.job)}. Next: ${(d.status || {}).next || 'its agenda'}.` + tokLine, when: ago(lj.finished_at || lj.started_at), dot: lj.status === 'failed' ? '#F0A56E' : '#7F9AF4', pulse: lj.finished_at ? '' : 'pl-pulse' }
      : { big: 'Starting', small: 'No job has run yet in this session.' + tokLine, when: '', dot: '#9A9DA4', pulse: '' };
    const heard = (d.heard || []).map((h) => ({ k: h.kind, kc: h.kind === 'alarm' ? '#9A4209' : '#3E4149', bg: h.kind === 'alarm' ? '#FDF0E6' : '#F6F5F1', t: (h.symbol ? h.symbol + ': ' : '') + h.text, s: h.at }));
    if (!heard.length) heard.push({ k: 'quiet', kc: '#6B6E76', bg: '#FBFAF7', t: 'Nothing heard yet', s: 'the alarm reader checks every 15 minutes while the app is open' });
    const eyes = (d.eyes || []).map((e) => { const ok = e.state === 'ok', off = e.state === 'never';
      return { n: e.name, s: e.state === 'down' ? 'not answering' : off ? 'not yet' : (e.age_min != null ? (e.age_min < 60 ? e.age_min + ' min ago' : Math.round(e.age_min / 60) + ' h ago') : ''),
        fill: ok ? '#2FA36B' : (off ? '#FFFFFF' : '#D9620F'), stroke: ok ? '#2FA36B' : (off ? '#9A9DA4' : '#D9620F'), sc: ok || off ? '#5B5E66' : '#9A4209', sw: ok || off ? 500 : 700 }; });
    ((d.status || {}).rows || []).slice().reverse().forEach((r) => eyes.unshift({ n: r.name, s: r.text, fill: r.state === 'ok' ? '#2FA36B' : (r.state === 'bad' ? '#D9620F' : '#FFFFFF'), stroke: r.state === 'ok' ? '#2FA36B' : (r.state === 'bad' ? '#D9620F' : '#C9A227'), sc: r.state === 'bad' ? '#9A4209' : '#5B5E66', sw: 500 }));
    eyes.unshift({ n: 'Claude on your plan', s: plan.signed_in ? (paused ? 'paused till ' + (plan.paused_until || 'reset') : 'signed in') : 'not signed in', fill: plan.signed_in && !paused ? '#2FA36B' : '#D9620F', stroke: plan.signed_in && !paused ? '#2FA36B' : '#D9620F', sc: plan.signed_in && !paused ? '#5B5E66' : '#9A4209', sw: plan.signed_in && !paused ? 500 : 700 });
    const f = d.fall_chance, frac = f ? Math.min(1, f.p / 0.4) : 0, ang = Math.PI * (1 - frac);
    const fall = f ? { v: Math.round(f.p * 100) + '%', t: `chance of a ${f.drop_pct ? Math.round(f.drop_pct) + '% ' : ''}fall in the next ${f.horizon} sessions`, aria: `${Math.round(f.p * 100)} percent chance of a fall in the next ${f.horizon} sessions`,
      nx: (120 + 72 * Math.cos(ang)).toFixed(1), ny: (110 - 72 * Math.sin(ang)).toFixed(1) } : { v: '—', t: 'chance of a fall: not worked out yet', aria: 'not worked out yet', nx: '120', ny: '38' };
    const st = d.storyline;
    const story = st ? { w: st.probability != null ? Math.round(st.probability * 100) + '%' : '0%', p: st.probability != null ? Math.round(st.probability * 100) + '%' : '—', t: st.claim || '', s: st.more ? `${st.more} more storyline${st.more > 1 ? 's' : ''} in the graph` : 'the only open storyline' } : { w: '0%', p: '—', t: 'No open storyline yet', s: 'they open as the graph reads the news' };
    const c = d.counts || {};
    await render(el, 'home', { banner, needs, needCount: needs.filter((n) => n.open).length, steps, doing, heard, eyes, lines, months, race,
      money: { v: rs(mine.value_inr), s: mine.value_inr == null ? 'no Kite snapshot yet' : (mine.today_pct == null ? 'as of ' + (mine.snapshot_at || 'the last snapshot') : pct(mine.today_pct) + ' today'), c: mine.today_pct != null && mine.today_pct < 0 ? '#9A4209' : '#1D3FB8' },
      book: { v: rs(paper && paper.value), s: paper ? (bookToday != null ? rsd(bookToday) + ' since the last close' : 'its own account, fake money') : 'not started', c: bookToday != null && bookToday < 0 ? '#9A4209' : '#1D3FB8' },
      counts: { a: c.checks == null ? '—' : c.checks, al: 'jobs today', b: c.forecasts == null ? '—' : c.forecasts, bl: 'forecasts', c: c.filings == null ? '—' : c.filings, cl: 'filings' }, fall, story });
  }
  await draw();
});
