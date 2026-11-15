/* S89 Usage: the plan's tokens by purpose against the day's budgets, and by day. Tokens only: no rupees anywhere (the plan has no per-token price). */
S89.register('usage', async (el) => {
  const { esc, api, empty } = S89;
  const o = await api('/api/operator');
  const days = [...Array(7)].map((_, i) => { const d = new Date(Date.now() - (6 - i) * 86400000); return d.toISOString().slice(0, 10); });
  const per = await Promise.all(days.map((d) => api('/api/usage?day=' + d).catch(() => null)));
  const tk = o.tokens_today || {}, NAMES = { chat_light: 'Quick answers', chat: 'Full operator', desk: 'Daily desk', cases: 'Cases and alarms', build: 'Fixer' };
  const bars = Object.entries(tk).map(([k, v]) => { const f = v.budget ? Math.min(100, v.used / v.budget * 100) : 0; return `<div class="col" style="gap:3px"><div class="row small"><b>${esc(NAMES[k] || k)}</b><span class="muted" style="margin-left:auto">${(v.used / 1000).toFixed(1)}k of ${((v.budget || 0) / 1000).toFixed(0)}k today</span></div>
      <div style="height:10px;border-radius:6px;background:var(--line)"><div style="height:10px;border-radius:6px;width:${f}%;background:${f > 85 ? 'var(--orange)' : 'var(--accent)'}"></div></div></div>`; }).join('');
  const tot = per.map((p) => (p && p.today ? (p.today.tokens_in || 0) + (p.today.tokens_out || 0) : 0)), mx = Math.max(1, ...tot);
  const byDay = `<div class="bars" role="img" aria-label="Tokens by day">${tot.map((t) => `<i title="${t.toLocaleString('en-IN')}" style="height:${Math.max(2, t / mx * 100)}%"></i>`).join('')}</div><div class="row small muted" style="justify-content:space-between">${days.map((d) => `<span>${d.slice(8)}</span>`).join('')}</div>`;
  const purposes = (per[per.length - 1] && per[per.length - 1].by_purpose) || [];
  const prow = purposes.length ? purposes.map((p) => `<div class="row small"><span class="grow">${esc(p.purpose)}</span><span>${p.calls} calls</span><b>${(((p.tokens_in || 0) + (p.tokens_out || 0)) / 1000).toFixed(1)}k</b></div>`).join('') : empty('No calls yet today.');
  el.innerHTML = `<div class="row"><h2 class="grow" style="margin:0">Usage · plan tokens</h2>${o.thinking === 'paused' ? `<span class="chip warn">Thinking paused until ${esc(o.paused_until || 'the reset')}</span>` : `<span class="chip ok">${o.signed_in ? 'Signed in on your plan' : 'Not signed in'}</span>`}</div>
    <section class="grid"><div class="card" style="flex:1 1 420px"><h2>Today against the day's budgets</h2>${bars || empty('No budgets reported.')}<span class="small muted">A purpose that spends its day stops until tomorrow; the code-only parts go on. Budgets are in Settings.</span></div>
      <div class="card" style="flex:1 1 420px"><h2>Last 7 days</h2>${byDay}<span class="small muted">Tokens in and out as Claude Code reports them (cache reads included).</span></div>
      <div class="card" style="flex:1 1 320px"><h2>Today by purpose</h2>${prow}</div></section>`;
});
