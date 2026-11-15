/* Agents: the design's Agents screen. Each agent's model and thinking level (kept and read at the start of its next run), its tools and skills, its last run and tokens today; the
   connections that load for full answers only (off by default) and the operator's skills. */
S89.register('agents', async (el) => {
  const { api, post, render, kTok, ago } = S89;
  const LABEL = { 'claude-haiku-5-5': 'Haiku 5.5', 'claude-sonnet-5-5': 'Sonnet 5.5', 'claude-opus-5-5': 'Opus 5.5' };
  const WHAT = { quick: 'Plain questions in the chat: a short prompt, five small tools, at most 4 turns', full: 'Files, links, studies and builds: a Claude Code session in its own folder',
    desk: 'The working session after the Indian close and in the US morning', case: 'Thinks a case through: class, options, likelihood word', alarm: 'Reads fast headlines and filings every 15 minutes',
    fixer: 'Writes a fix on its own branch; nothing merges without your Yes', weekly: 'The weekly look back: candidates for new studies, never a live change' };
  const NAMES = { kite: ['Kite', 'read-only: holdings and prices'], nse: ['NSE', 'filings and announcements'], tijori: ['Tijori', 'company facts'] };
  const sw = (on) => ({ on: String(on), bg: on ? '#2F5BEA' : '#C9C6BD', kx: on ? '21px' : '3px' });
  const chip = (t, k) => ({ t, bg: k === 'mcp' ? '#EAF0FE' : k === 'skill' ? '#F4ECFB' : '#F3F2EE', fg: k === 'mcp' ? '#1D3FB8' : k === 'skill' ? '#5B2A86' : '#3E4149' });
  async function save(body) { try { await post('/api/agents', body); } catch (e) { alert(e.message); } draw(); }
  async function draw() {
    const [d, op] = await Promise.all([api('/api/agents'), api('/api/operator').catch(() => ({}))]);
    const s = d.switches || {}, mcpOn = ['kite', 'nse', 'tijori'].filter((k) => s[k]);
    const agents = (d.agents || []).map((a) => {
      const today = Number(a.tokens_today || 0), ranToday = a.last_run && a.last_run.slice(0, 10) === new Date().toISOString().slice(0, 10);
      const chips = [chip(a.tools, 'tool')];
      if (a.key === 'full') { mcpOn.forEach((k) => chips.push(chip(NAMES[k][0], 'mcp'))); (d.skills || []).slice(0, 4).forEach((k) => chips.push(chip(k.name.replace(/_/g, ' '), 'skill'))); }
      return { id: a.key, name: a.label, what: WHAT[a.key] || '', status: a.key === 'alarm' ? 'LOCAL' : ranToday ? 'RAN TODAY' : a.last_run ? 'IDLE' : 'NOT YET',
        sb: ranToday ? '#E3F4EA' : '#F3F2EE', sf: ranToday ? '#1F7A4D' : '#5B5E66', model: a.model || '', effort: a.thinking || '',
        setModel: (e) => save({ agent: a.key, model: e.target.value }), setEffort: (e) => save({ agent: a.key, thinking: e.target.value }),
        dflt: a.changed ? `your choice · default ${LABEL[a.default_model] || a.default_model || '—'}, ${a.default_thinking}` : 'default setting', dfc: a.changed ? '#1D3FB8' : '#5B5E66', chips,
        last: a.last_run ? 'last run ' + ago(a.last_run) : 'no run yet', tok: kTok(today) + (a.budget ? ' of ' + kTok(a.budget) + ' today' : ' today') };
    });
    const mcps = ['kite', 'nse', 'tijori'].map((k) => Object.assign({ name: NAMES[k][0], note: NAMES[k][1] + ' · full answers only', flip: () => save({ switch: k, on: !s[k] }) }, sw(!!s[k])));
    const acct = [Object.assign({ name: 'Mail, calendar and drive connectors', flip: () => save({ switch: 'connectors', on: !s.connectors }) }, sw(!!s.connectors))];
    const skills = (d.skills || []).map((k) => ({ n: k.name.replace(/_/g, ' '), u: String(k.description || '').split(/[:.]\s/)[0].replace(/^(.{52}).*$/, (m, a) => a.replace(/\s+\S*$/, '') + '…') }));
    const ok = op.signed_in;
    await render(el, 'agents', { agents, mcps, acct, skills: skills.length ? skills : [{ n: 'none yet', u: '' }],
      models: (d.models || []).map((m) => ({ v: m, l: LABEL[m] || m })), efforts: (d.levels || []).map((m) => ({ v: m, l: m })),
      op: { dot: ok ? '#2FA36B' : '#D9620F', text: ok ? 'signed in on your plan · no API key' : 'not signed in · see Settings' } });
  }
  await draw();
});
