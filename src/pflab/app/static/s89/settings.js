/* Settings: the design's Settings screen, and everything the old Settings held. Account (Kite login, Telegram, US holdings, phone, the Claude plan sign-in, tokens today);
   the settings (the chat's road, Telegram, the jobs, live prices, how much runs, the brain, the nightly simulation, the drop folder, what the AI may use, the backup folder,
   his limits, the token budgets, fixes to the app, the NSE address, the operator terminal, this release); standing instructions; the first-week check; Problems. */
S89.register('settings', async (el) => {
  const { api, post, render, kTok, ago } = S89;
  let editBudgets = false, kiteMsg = '', drafts = {};
  const pills = (list, cur, set) => list.map(([k, l]) => { const on = k === cur; return { label: l, on: String(on), bg: on ? '#17181C' : '#FFFFFF', fg: on ? '#FFFFFF' : '#3E4149', bd: on ? '#17181C' : '#E6E4DD', w: on ? 600 : 500, pick: () => set(k) }; });
  const sw = (on, flip) => ({ sw: true, on: String(!!on), bg: on ? '#2F5BEA' : '#C9C6BD', kx: on ? '21px' : '3px', flip });
  const save = async (changes, ask) => { if (ask && !confirm(ask)) return; try { await post('/api/settings', changes); } catch (e) { alert(e.message); } draw(); };
  const ABIL = [['charts', 'Look at charts', 'candlesticks with volume, as a picture plus the figures'], ['kite_live', 'Kite live data', 'live prices and candles; read only, orders are blocked in code'],
    ['web', 'Search the web', 'news, filings and why a stock moved; never with your holdings in the question'], ['calculations', 'Run its own calculations', 'in a closed box: no network, read only, a time limit'],
    ['local_first', 'Local model first', 'small jobs and the alarm reader run on this PC']];
  const BUD = [['budget_chat_light', 'Quick answers'], ['budget_chat', 'Full answers'], ['budget_desk', 'Daily desk'], ['budget_cases', 'Cases and alarms'], ['budget_build', 'Fixes']];
  async function kite() {
    kiteMsg = 'Opening the Kite login…'; draw();
    const w = window.open('', 'kite', 'width=520,height=720');
    try { const r = await post('/api/kite/login'); if (w) w.location = r.url; else window.open(r.url, '_blank'); kiteMsg = 'Log in in the window that opened; this line turns green when Kite answers.'; }
    catch (e) { if (w) w.close(); kiteMsg = 'Kite login could not start: ' + e.message; }
    draw();
  }
  async function draw() {
    const [s, op, ks, rl, wk, pr, rel] = await Promise.all([api('/api/settings'), api('/api/operator').catch(() => ({})), api('/api/kite/status').catch(() => ({})), api('/api/rules').catch(() => ({})),
      api('/api/week').catch(() => ({})), api('/api/problems').catch(() => ({})), api('/api/release').catch(() => ({}))]);
    const o = s.operator || {}, tk = op.tokens_today || {};
    const U = Object.values(tk).reduce((a, x) => a + Number(x.used || 0), 0), B = Object.values(tk).reduce((a, x) => a + Number(x.budget || 0), 0);
    const kiteOk = ks.token_today, waiting = ks.login === 'waiting', failed = String(ks.login || '').startsWith('failed');
    if (kiteMsg && !waiting && (kiteOk || failed)) kiteMsg = '';
    const acct = [
      { name: 'Kite', fill: kiteOk ? '#2FA36B' : '#FFFFFF', ring: kiteOk ? '#2FA36B' : failed ? '#D9620F' : '#C9A227',
        sub: kiteMsg || (kiteOk ? 'logged in today · needed every trading morning' : waiting ? 'waiting for Kite: finish the login in the Kite window' : failed ? String(ks.login).replace(/^failed: /, 'last try failed: ') : 'not logged in today · your Indian prices are the last snapshot'),
        btn: kiteOk ? 'Log in again' : 'Log in to Kite', go: kite },
      { name: 'Telegram', fill: s.telegram_send ? '#2FA36B' : '#FFFFFF', ring: s.telegram_send ? '#2FA36B' : '#C9A227', sub: s.telegram_send ? 'on · alerts and chat on your phone' : 'messages are held · switch on below' },
      { name: 'US holdings', fill: '#FFFFFF', ring: '#C9A227', sub: 'entered by hand · no US broker connected', link: 'Edit holdings and watchlist', href: '#/manage' },
      { name: 'Phone', fill: '#2FA36B', ring: '#2FA36B', sub: 'open this app in your phone’s browser over your private link, then Add to Home screen · no APK' },
      { name: 'Claude plan sign-in', fill: op.signed_in ? '#2FA36B' : '#FFFFFF', ring: op.signed_in ? '#2FA36B' : '#D9620F',
        sub: op.signed_in ? 'signed in · no API key in use, so nothing is billed outside your plan' : 'not signed in: ' + (op.detail || 'open the operator below and sign in with your Claude account'),
        btn: 'Open the operator in Claude Code', go: async () => { try { const r = await post('/api/operator/terminal'); if (r && r.ok === false) alert(r.detail || 'Could not open it.'); } catch (e) { alert(e.message); } } }];
    const ab = (k) => (s.abilities || {})[k] !== false;
    const rows = [
      { head: 'CHAT AND MESSAGES', name: 'Chat answers', sub: 'Auto sends plain questions the quick way, and files, links and studies to the full operator', pills: pills([['auto', 'Auto'], ['quick', 'Quick'], ['full', 'Full']], s.chat_road || 'auto', (k) => save({ chat_road: k })) },
      Object.assign({ name: 'Telegram messages', sub: 'the 15:45 report, and anything that matters today' }, sw(s.telegram_send, () => save({ telegram_send: !s.telegram_send }, s.telegram_send ? null : 'Turn on Telegram? Held messages are delivered at the next tick.'))),
      Object.assign({ head: 'THE SYSTEM', name: 'Run the jobs while the app is open', sub: 'collect, prices, research, forecasts, guards' }, sw(s.scheduler, () => save({ scheduler: !s.scheduler }))),
      Object.assign({ name: 'Live prices in market hours', sub: 'Kite read-only quotes every minute, after the day’s login' }, sw(s.live_prices, () => save({ live_prices: !s.live_prices }))),
      { name: 'How much runs on its own', sub: { off: 'nothing on its own; prices and screens still work', light: 'data and checks only', full: 'every job; a 10,000-path simulation nightly', marathon: 'every job and a 100,000-path simulation nightly' }[s.preset] || '',
        pills: pills([['off', 'Off'], ['light', 'Light'], ['full', 'Full'], ['marathon', 'Marathon']], s.preset, (k) => save({ preset: k })) },
      { name: 'The thinking', sub: 'how often the AI may think; it never trades', pills: pills([['off', 'Off'], ['economy', 'Economy'], ['normal', 'Normal']], s.brain, (k) => save({ brain: k })) },
      { name: 'Nightly simulation after', sub: 'the hour the night’s simulation may start', pills: pills([18, 19, 20, 21, 22, 23].map((h) => [h, h + ':00']), s.sims_hour, (k) => save({ sims_hour: k })) },
      Object.assign({ name: 'Take files from the drop folder', sub: 'files placed in the drop folder reach the chat by themselves' }, sw(s.drop_watch, () => save({ drop_watch: !s.drop_watch }))),
      ...ABIL.map(([k, n, sub], i) => Object.assign({ head: i === 0 ? 'WHAT THE AI MAY USE' : '', name: n, sub }, sw(ab(k), () => save({ abilities: { [k]: !ab(k) } })))),
      { name: 'Place real orders', sub: 'there is no such ability: it is refused in code, not by a setting' },
      { name: 'Backup folder', sub: 'the nightly copy of the record goes here (outside the app’s folder)', input: 'text', val: drafts.backup != null ? drafts.backup : (s.backup_dir || ''), ph: 'D:\\PL_backup',
        set: (e) => { drafts.backup = e.target.value; }, key: (e) => { if (e.key === 'Enter') save({ backup_dir: (drafts.backup || '').trim() }); }, save: () => save({ backup_dir: (drafts.backup != null ? drafts.backup : s.backup_dir || '').trim() }) },
      { head: 'LIMITS AND BUDGETS', name: 'Your limits', sub: '10% a stock · 25% a sector · only you change these; tell the chat and it waits for your Yes', btn: 'Change in chat',
        go: () => { try { sessionStorage.setItem('s89:draft', 'I want to change my limits: '); } catch (e) { /* none */ } location.hash = '#/chat'; } },
      { name: 'Daily token budgets', sub: BUD.map(([k, l]) => `${l.toLowerCase()} ${kTok((tk[k.replace('budget_', '')] || {}).budget)}`).join(' · ') + ' · thinking pauses when a budget or the plan limit is reached',
        btn: editBudgets ? 'Done' : 'Edit', go: () => { editBudgets = !editBudgets; draw(); } },
      ...(editBudgets ? BUD.map(([k, l]) => { const cur = (tk[k.replace('budget_', '')] || {}).budget;
        return { name: l + ' a day', sub: 'tokens; today ' + kTok((tk[k.replace('budget_', '')] || {}).used || 0) + ' used', input: 'number', val: drafts[k] != null ? drafts[k] : String(cur || ''), ph: 'tokens',
          set: (e) => { drafts[k] = e.target.value; }, key: () => null,
          save: () => { const v = Number(drafts[k] != null ? drafts[k] : cur); if (!(v >= 0 && v <= 5000000)) return alert('Between 0 and 5,000,000 tokens.'); delete drafts[k]; save({ operator: { [k]: Math.round(v) } }); } }; }) : []),
      Object.assign({ name: 'Fixes to the app', sub: 'it writes the fix on its own branch and runs the tests; nothing goes in until you say Yes' }, sw(o.build_on !== false, () => save({ operator: { build_on: o.build_on === false } }))),
      { name: 'NSE data address', sub: o.nse_mcp_url ? 'set · used for full answers when NSE is on in Agents' : 'off until set · the NSE connection’s https address', input: 'url', val: drafts.nse != null ? drafts.nse : (o.nse_mcp_url || ''), ph: 'https://…',
        set: (e) => { drafts.nse = e.target.value; }, key: () => null, save: () => { const v = (drafts.nse != null ? drafts.nse : o.nse_mcp_url || '').trim(); delete drafts.nse; save({ operator: { nse_mcp_url: v } }); } },
      { head: 'THIS RELEASE', name: rel.tag || 'workshop copy', sub: rel.is_app ? `installed ${String(rel.installed_on || '').slice(0, 10)}${rel.previous_tag ? ' · before it ' + rel.previous_tag : ''} · the app takes the newest release at its next start` : 'not an installed app' }];
    const fmtUntil = (u) => (u ? 'until ' + new Date(u).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : 'no end date');
    const rules = (rl.active || []).map((r) => ({ name: r.text || r.name, sub: fmtUntil(r.until) + (r.kind === 'hold_name' ? ' · stops still apply' : ''),
      undo: async () => { try { await post('/api/rules/' + r.rule_id + '/undo'); } catch (e) { alert(e.message); } draw(); } }))
      .concat((rl.waiting || []).map((r) => ({ name: r.text || r.name, sub: 'waiting for your Yes in the chat', undo: null })));
    if (!rules.length) rules.push({ name: 'None', sub: 'tell the chat, for example “pause gold buys till 20 Nov”', undo: null });
    const ST = { PASS: ['#E3F4EA', '#1F7A4D'], FAIL: ['#FDE8E1', '#B23B12'], 'NOT TESTED': ['#F3F2EE', '#5B5E66'] };
    const checks = (wk.criteria || []).map((c) => { const k = String(c.status || '').toUpperCase(), col = ST[k] || ST['NOT TESTED']; return { t: c.name.replace(/_/g, ' '), bg: col[0], tx: col[1] }; });
    const day = wk.day || 0, of = wk.of || 7;
    const prow = (pr.rows || []).slice(0, 6).map((p) => ({ t: p.text || p.title || p.kind || 'problem', s: [p.times > 1 ? p.times + ' times' : '', p.last_seen ? 'last ' + ago(p.last_seen) : ''].filter(Boolean).join(' · ') }));
    await render(el, 'settings', { acct, rows, rules, checks,
      tok: { used: kTok(U), budget: kTok(B), w: (B ? Math.min(100, U / B * 100) : 0).toFixed(0) + '%' },
      wk: { day: wk.armed_at ? `day ${day} of ${of}` : 'starts at the first open on or after ' + new Date(wk.arm_from || '2026-11-16').toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' }),
        w: (day / of * 100).toFixed(0) + '%', note: wk.verdict === 'pass' ? `Passed: bug fixes only from ${wk.freeze_from || 'today'} for 60 days.` : wk.verdict === 'fail' ? 'Did not pass: the failures are fixed first.' : 'When all pass: 60 days of bug fixes only.' },
      pr: { n: (pr.rows || []).length, rows: prow.length ? prow : [{ t: 'Nothing on the list', s: 'the last 7 days' }], copyLabel: 'Copy the list',
        copy: async (e) => { try { await navigator.clipboard.writeText(pr.text || 'No problems.'); e.target.textContent = 'Copied'; } catch (x) { alert(pr.text || 'No problems.'); } } } });
  }
  await draw();
  S89.every(4000, () => { if (document.activeElement && el.contains(document.activeElement) && document.activeElement.tagName === 'INPUT') return; api('/api/kite/status').then((k) => { if (k.login === 'waiting' || kiteMsg) draw(); }).catch(() => null); });
});

/* "#/kite" (Home's Log in buttons): start the Kite login at once, then show Settings, where the Kite line follows it. */
S89.register('kite', async () => {
  const w = window.open('', 'kite', 'width=520,height=720');
  try { const r = await S89.post('/api/kite/login'); if (w) w.location = r.url; else window.open(r.url, '_blank'); }
  catch (e) { if (w) w.close(); alert('Kite login could not start: ' + e.message); }
  location.replace('#/settings');
});
