/* S78: the redesigned screens (the design the investor approved on 2026-11-02): Today (one page), Account, Watchlist, Research overview, System checks, and the Settings abilities.
   Loaded after ui.js; it reuses app.js's helpers ($, esc, api, post, rs, pct, num, spark). Every figure comes from the backend; nothing here computes a decision. */
const RD = (() => {
  const ST = { up: 'up', warn: 'warn', info: 'info', down: 'down', mute: 'mute' };
  const chip = (kind, text) => `<span class="rd-chip ${ST[kind] || 'mute'}">${esc(text)}</span>`;
  const when = (s) => { if (!s) return ''; const t = new Date(String(s).replace(' ', 'T')); if (isNaN(t)) return String(s).slice(0, 16); const m = Math.round((Date.now() - t) / 60000); return m < 1 ? 'just now' : m < 60 ? m + ' min ago' : m < 1440 ? Math.round(m / 60) + ' h ago' : String(s).slice(5, 16); };
  const LOOP = { live_watch: 'Live watch', daily_look: 'Daily look', postmortem: 'Postmortem', weekly_review: 'Weekly review' };
  const DEC = { executed: ['up', 'Done'], not_approved: ['warn', 'Refused by the review'], proposed: ['info', 'Waiting for the review'] };
  const ACT = { BUY: 'up', ADD: 'up', REDUCE: 'warn', SELL: 'warn', HOLD: 'up', WAIT: 'info' };

  function line(vals, w, h, lo, hi) { if (!vals.length) return ''; return vals.map((v, i) => ((i / Math.max(1, vals.length - 1)) * w).toFixed(1) + ',' + (h - 4 - ((v - lo) / (hi - lo || 1)) * (h - 8)).toFixed(1)).join(' '); }
  function ring(done, of, label) { const c = 2 * Math.PI * 42; return `<svg width="56" height="56" viewBox="0 0 104 104" role="img" aria-label="${esc(label)}" style="flex:none"><circle cx="52" cy="52" r="42" fill="none" stroke="var(--line)" stroke-width="12"></circle><circle cx="52" cy="52" r="42" fill="none" stroke="var(--up)" stroke-width="12" stroke-linecap="round" stroke-dasharray="${(c * Math.min(1, done / of)).toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 52 52)"></circle></svg>`; }

  /* ---- Today: one page ---- */
  function today(d, sc) {
    if (!d.started) return `<div class="rd-card"><span class="rd-lbl">The account</span><div class="muted">${esc(d.note || 'Starting…')}</div></div>`;
    const days = d.days || [], nifty = d.nifty || [];
    const vals = days.map((x) => x.value), nv = nifty.map((x) => x.value);
    const all = vals.concat(nv), lo = Math.min(...all), hi = Math.max(...all);
    const last = vals[vals.length - 1], prev = vals.length > 1 ? vals[vals.length - 2] : last;
    const dayChg = last - prev, r = d.returns || {}, gate = d.gate || {};
    const sinceN = nv.length > 1 ? nv[nv.length - 1] / nv[0] - 1 : null;
    const holds = (d.holdings || []).slice(0, 6).map((h) => ({ name: h.symbol, w: h.weight, c: h.weight > 0.1 ? 'var(--warn)' : 'var(--up)' }));
    holds.push({ name: 'Cash', w: (d.cash || 0) / (d.value || 1), c: 'var(--btn-line)' });
    const acts = ['live_watch', 'daily_look', 'postmortem', 'weekly_review'].map((k) => (d.acts || []).find((a) => a.loop === k)).filter(Boolean);
    const decs = (d.recent_decisions || []).slice(0, 3);
    const les = (d.lessons || []).slice(0, 2);
    const checks = sc && sc.run ? sc.counts : null;
    return `<div class="rd-grid3">
      <section class="rd-card" style="grid-row:1 / span 2;padding:20px 22px">
        <div class="rd-row" style="justify-content:space-between;align-items:flex-start;flex-wrap:wrap">
          <div><div class="rd-lbl">The account · fake money, its own ledger</div><div class="rd-big">${rs(d.value)}</div>
            <div class="small" style="margin-top:4px"><b class="${ud(dayChg)}">${rs(dayChg, true)} on the last day</b> <span class="muted">· since the start ${r.twr != null ? pct(r.twr, 1, true) : '—'}${sinceN != null ? ' · Nifty 500 ' + pct(sinceN, 1, true) : ''}</span></div></div>
          <div class="small" style="display:flex;gap:12px"><span><span style="display:inline-block;width:18px;height:3px;background:var(--up);vertical-align:middle;margin-right:6px"></span>Account</span><span><span style="display:inline-block;width:18px;height:3px;background:var(--accent);vertical-align:middle;margin-right:6px"></span>Nifty 500</span></div></div>
        ${vals.length > 1 ? `<svg viewBox="0 0 640 190" preserveAspectRatio="none" style="flex:1;min-height:120px;width:100%" role="img" aria-label="The account against the Nifty 500">
          ${[47, 95, 143].map((y) => `<line x1="0" y1="${y}" x2="640" y2="${y}" stroke="var(--line)"></line>`).join('')}
          ${nv.length > 1 ? `<polyline points="${line(nv, 640, 190, lo, hi)}" fill="none" stroke="var(--accent)" stroke-width="2.2" vector-effect="non-scaling-stroke"></polyline>` : ''}
          <polyline points="${line(vals, 640, 190, lo, hi)}" fill="none" stroke="var(--up)" stroke-width="3" stroke-linecap="round" vector-effect="non-scaling-stroke"></polyline></svg>`
          : `<div class="muted small" style="flex:1;display:flex;align-items:center">The line appears after its second marked day.</div>`}
        <div style="display:flex;gap:10px;flex-wrap:wrap">
          <div class="rd-stat"><span>Broker cash</span><b>${rs(d.cash)}</b></div>
          <div class="rd-stat"><span>Bank · top-up room ${d.topup ? rs(d.topup.room) : ''}</span><b>${rs(d.bank)}</b></div>
          <div class="rd-stat"><span>Fall from its high · stops buying at 12%</span><b>${pct(Math.abs((d.breaker || {}).drawdown || 0), 1)}</b></div></div>
        <div class="rd-row" style="border-top:1px solid var(--line);padding-top:12px;flex-wrap:wrap;gap:16px">
          ${ring(d.sessions || 0, 40, (d.sessions || 0) + ' of 40 sessions')}
          <div style="flex:1 1 180px"><b class="small">Proving itself: ${d.sessions || 0} of 40 sessions</b><div class="small muted">${esc((gate.status || '').slice(0, 130))}</div></div>
          <div style="flex:1 1 180px"><div class="small rd-row" style="justify-content:space-between"><span>Its API money this month</span><span>${rs((d.money || {}).this_month)} of ${rs((d.money || {}).monthly)}</span></div>
            <div style="height:8px;border-radius:5px;background:var(--line);margin-top:6px;overflow:hidden"><div style="height:100%;width:${Math.min(100, 100 * ((d.money || {}).this_month || 0) / ((d.money || {}).monthly || 1))}%;background:var(--warn)"></div></div></div></div>
      </section>
      <section class="rd-card"><div class="rd-row" style="justify-content:space-between"><h2><a href="#/account">What it owns →</a></h2><span class="small muted">line = 10% limit</span></div>
        <div style="display:flex;flex-direction:column;gap:9px;justify-content:space-between;flex:1">${holds.map((h) => `<div class="rd-row"><span style="flex:0 0 84px;font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis">${esc(h.name)}</span><div class="rd-bar" style="flex:1"><i style="width:${Math.min(100, h.w * 500)}%;background:${h.c}"></i><u></u></div><span style="flex:0 0 46px;text-align:right;font-size:12px;font-weight:600">${pct(h.w, 1)}</span></div>`).join('')}</div></section>
      <section class="rd-card"><div class="rd-row" style="justify-content:space-between"><h2><a href="#/system/checks">It never sits idle →</a></h2><span class="small muted">last act</span></div>
        <div style="display:flex;flex-direction:column;gap:9px;justify-content:space-between;flex:1">${acts.length ? acts.map((a) => `<div class="rd-row" style="align-items:flex-start"><span class="rd-dot" style="background:var(--up)"></span><div style="min-width:0"><div style="font-size:13px;font-weight:600">${esc(LOOP[a.loop] || a.loop)} <span class="muted" style="font-weight:500">· ${esc(when(a.at))}</span></div><div class="small soft" style="line-height:1.35">${esc(String(a.what).replace(/^daily look: |^postmortem: /, '').slice(0, 110))}</div></div></div>`).join('') : '<div class="muted small">Its loops have not acted yet.</div>'}</div></section>
      <section class="rd-card"><h2><a href="#/watchlist">What it decided · waits on →</a></h2>
        <div style="display:flex;flex-direction:column;gap:8px;flex:1;justify-content:space-between">${decs.length ? decs.map((x) => { const s = DEC[x.status] || ['mute', x.status]; return `<a href="#/watchlist" class="rd-item rd-row" style="text-decoration:none;color:var(--text)">${chip(ACT[x.action] || 'mute', x.action)}<div style="flex:1;min-width:0"><div style="font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(x.symbol || 'cash')} · ${esc((x.reason || '').slice(0, 60))}</div><div class="small ${s[0] === 'warn' ? 'warn' : 'up'}" style="font-weight:600">${esc(s[1])}</div></div></a>`; }).join('') : '<div class="muted small">No decision yet.</div>'}</div></section>
      <section class="rd-card"><h2><a href="#/research">Right now · learned →</a></h2>
        ${d.working_on ? `<div class="rd-item small"><b style="color:var(--accent)">WORKING</b> The team is looking into investigation #${d.working_on}.</div>` : '<div class="rd-item small muted">The team is idle: nothing needs a review today.</div>'}
        ${les.map((l) => `<div class="small soft" style="border-top:1px solid var(--line);padding-top:8px;line-height:1.45">${esc(l.text)}</div>`).join('')}
        ${checks ? `<a href="#/system/checks" class="small" style="margin-top:auto">${checks.ok} of ${sc.total} self-checks pass${checks.bad ? ' · ' + checks.bad + ' failing' : ''} →</a>` : ''}</section>
    </div>
    <div class="rd-ask"><label for="rdAsk" style="position:absolute;left:-9999px">Ask the system, or drop a file</label><input id="rdAsk" placeholder="Ask, tell it something, or drop a file in the Assistant…"><button class="btn primary" id="rdSend">Send</button></div>`;
  }
  function wireToday() {
    const go = async () => { const t = ($('rdAsk') || {}).value; if (!t || !t.trim()) return; try { await post('/api/assistant', { text: t.trim(), context: 'sent from Today' }); } catch (e) { alert(e.message); } location.hash = '#/assistant'; };
    if ($('rdSend')) { $('rdSend').onclick = go; $('rdAsk').onkeydown = (e) => { if (e.key === 'Enter') go(); }; }
  }

  /* ---- Account ---- */
  function account(d) {
    if (!d.started) return `<div class="rd-card"><div class="muted">${esc(d.note || '')}</div></div>`;
    const rows = (d.holdings || []);
    const inv = rows.reduce((a, h) => a + (h.value || 0), 0);
    const cols = 'grid-template-columns:1.5fr .7fr .9fr .9fr 1.7fr .8fr';
    const ev = (d.trades || []).slice(0, 5).map((t) => ({ kind: t.side.toUpperCase(), cls: t.side === 'buy' ? 'up' : 'warn', what: `${num(t.qty, 0)} of ${t.symbol} at ${num(t.price)}`, detail: `charges ${rs(t.charges)}${t.tax ? ' · est. tax ' + rs(t.tax) : ''}`, when: t.day }))
      .concat((d.moves || []).slice(0, 4).map((m) => ({ kind: m.kind, cls: 'mute', what: `${m.what} ${rs(m.amount)}`, detail: m.by ? 'by ' + m.by : '', when: m.day }))).slice(0, 7);
    const room = d.topup ? d.topup.room : 0, max = d.topup ? d.topup.max : 50000;
    return `<div class="rd-two" style="grid-template-columns:1.7fr 1fr;grid-template-rows:auto 1fr">
      <section class="rd-card" style="grid-column:1 / span 2;flex-direction:row;flex-wrap:wrap;gap:28px;align-items:center;padding:14px 22px">
        <div><div class="rd-lbl">Account value</div><div style="font-size:32px;font-weight:700;font-variant-numeric:tabular-nums">${rs(d.value)}</div></div>
        <div><div class="small muted">Shares and bonds</div><b style="font-size:19px">${rs(inv)}</b></div><div><div class="small muted">Broker cash</div><b style="font-size:19px">${rs(d.cash)}</b></div>
        <div><div class="small muted">Bank</div><b style="font-size:19px">${rs(d.bank)}</b></div>
        <div class="small muted" style="margin-left:auto;max-width:280px;line-height:1.45">Not your money: the system's own account, started from your Zerodha holdings, with fake cash. Its fills happen only inside a market session.</div></section>
      <section class="rd-card"><div class="rd-row" style="justify-content:space-between"><h2>What it owns</h2><span class="small muted">oldest purchases are sold first</span></div>
        <div class="rd-table rd-th" style="${cols}"><span>Name</span><span style="text-align:right">Qty</span><span style="text-align:right">Cost</span><span style="text-align:right">Value</span><span>Share of the account</span><span style="text-align:right">Gain</span></div>
        <div style="display:flex;flex-direction:column;gap:7px;flex:1;justify-content:flex-start;overflow:auto">${rows.map((h) => `<div class="rd-table rd-tr" style="${cols}">
          <div><b>${esc(h.symbol)}</b><div class="small muted">${esc(h.sector || h.kind || '')}</div></div><span style="text-align:right">${num(h.qty, 0)}</span>
          <span style="text-align:right" class="${h.cost_known === false ? 'warn' : ''}">${h.cost_known === false ? 'unknown' : (h.qty ? rs((h.value - h.gain) / h.qty) : '—')}</span><b style="text-align:right">${rs(h.value)}</b>
          <div class="rd-bar" style="height:10px"><i style="width:${Math.min(100, h.weight * 500)}%;background:${h.weight > 0.1 ? 'var(--warn)' : 'var(--up)'}"></i><u></u></div>
          <b class="${ud(h.gain)}" style="text-align:right">${h.cost_known === false ? '—' : rs(h.gain, true)}</b></div>`).join('')}</div>
        <div class="small muted">The line on each bar is the 10% limit for one company. “Unknown” cost is a holding inherited with no purchase price: no gain or tax is claimed on it.</div></section>
      <div style="display:flex;flex-direction:column;gap:14px;min-height:0">
        <section class="rd-card"><h2>Add money to its bank</h2><div class="rd-row small" style="justify-content:space-between"><span>Room this month</span><b>${rs(room)} of ${rs(max)}</b></div>
          <div style="height:8px;border-radius:5px;background:var(--line);overflow:hidden"><div style="height:100%;width:${max ? Math.min(100, 100 * room / max) : 0}%;background:var(--up)"></div></div>
          <div class="rd-row"><label for="rdAmt" style="position:absolute;left:-9999px">Amount to add</label><input id="rdAmt" class="inp" inputmode="numeric" placeholder="₹ amount" style="flex:1;min-width:0"><button class="btn primary" id="rdTop">Add</button></div>
          <div class="small muted" style="line-height:1.45">You or the system may add up to ₹50,000 a month. The bank moves it to the broker when a buy needs cash. Each addition is logged with who made it.</div><div class="small warn" id="rdTopMsg"></div></section>
        <section class="rd-card" style="flex:1"><h2>Every move, newest first</h2><div style="display:flex;flex-direction:column;gap:8px;flex:1;justify-content:flex-start">${ev.length ? ev.map((e) => `<div class="rd-row" style="align-items:flex-start">${chip(e.cls, e.kind)}<div style="flex:1;min-width:0"><div style="font-size:13px;font-weight:600">${esc(e.what)}</div><div class="small muted">${esc(e.detail)}</div></div><span class="small muted">${esc(e.when)}</span></div>`).join('') : '<div class="muted small">No trade or move yet.</div>'}</div></section></div></div>`;
  }
  function wireAccount() {
    const b = $('rdTop'); if (!b) return;
    b.onclick = async () => { const v = Number(String(($('rdAmt') || {}).value || '').replace(/[^0-9.]/g, '')); if (!v) { $('rdTopMsg').textContent = 'Type an amount in rupees.'; return; }
      try { await post('/api/paper/topup', { amount: v }); S.last = 0; load(true); } catch (e) { $('rdTopMsg').textContent = e.message; } };
  }

  /* ---- Watchlist ---- */
  function wlTag(w) { return w.status === 'triggered' ? ['up', 'TRIGGERED'] : w.status === 'near' ? ['warn', 'NEAR'] : ['info', 'WAITING']; }
  function wlRule(w) { return w.kind === 'zone' ? `Wants ₹${num(w.zone_low || 0, 0)}–${num(w.zone_high, 0)}` : w.kind === 'fall_from_high' ? `Wants a ${w.fall_pct}% fall from its year's high` + (w.zone_high ? ` (about ₹${num(w.zone_high, 0)})` : '') : `Spend cash in tranches if the market falls ${w.fall_pct}% from its high`; }
  function watchlist(items) {
    const sel = items.find((w) => w.watch_id === S.wsel) || items[0];
    const n = (s) => items.filter((w) => w.status === s).length;
    const zone = (w) => { if (w.kind === 'market_fall' || !w.zone_high) return ''; const lo = (w.zone_low || w.zone_high) * 0.82, hi = Math.max(w.price || 0, w.zone_high) * 1.08, p = (v) => ((v - lo) / (hi - lo)) * 100;
      return `<div class="rd-zone"><b style="left:${p(w.zone_low || w.zone_high).toFixed(1)}%;width:${Math.max(2, p(w.zone_high) - p(w.zone_low || w.zone_high)).toFixed(1)}%"></b>${w.price ? `<i style="left:${p(w.price).toFixed(1)}%;background:${w.status === 'near' ? 'var(--warn)' : 'var(--accent)'}"></i>` : ''}</div>`; };
    return `<section class="rd-card" style="flex-direction:row;flex-wrap:wrap;gap:26px;align-items:center;padding:14px 22px">
      <div><div class="rd-lbl">The system's watchlist</div><div style="font-size:15px;font-weight:600;max-width:440px;line-height:1.4;margin-top:2px">Ideas it likes but will not buy yet. It waits for the price or the news to reach the point its own calculation set.</div></div>
      <div style="display:flex;gap:22px;margin-left:auto">${[[items.length, 'on the list', ''], [n('near'), 'near its point', 'var(--warn)'], [n('triggered'), 'triggered', 'var(--up)']].map((x) => `<div><div style="font-size:26px;font-weight:700;color:${x[2]}">${x[0]}</div><div class="small muted">${x[1]}</div></div>`).join('')}</div></section>
      <div class="rd-two" style="grid-template-columns:1.25fr 1fr">
      <section class="rd-card"><div class="rd-row" style="justify-content:space-between"><h2>Waiting for the right time</h2><span class="small muted">band = the zone it wants · dot = the price now</span></div>
        <div style="display:flex;flex-direction:column;gap:8px;flex:1;overflow:auto">${items.length ? items.map((w) => { const t = wlTag(w); return `<button class="rd-wl ${sel && sel.watch_id === w.watch_id ? 'on' : ''}" data-wl="${w.watch_id}"><div class="rd-row"><b>${esc(w.symbol)}</b><span class="small muted">${esc(w.kind.replace(/_/g, ' '))}</span><span style="margin-left:auto">${chip(t[0], t[1])}</span></div>${zone(w)}<div class="rd-row small soft" style="justify-content:space-between"><span>${esc(wlRule(w))}</span><span class="${w.status === 'near' ? 'warn' : 'muted'}" style="font-weight:600">${w.price ? '₹' + num(w.price) : ''}${w.gap_pct != null ? ' · ' + (w.gap_pct >= 0 ? w.gap_pct + '% above' : Math.abs(w.gap_pct) + '% inside') : ''}</span></div></button>`; }).join('')
          : '<div class="muted small" style="line-height:1.5">Nothing is waiting yet. When research finds an idea worth waiting for, it adds it here with a zone from its own calculation. You can also ask in the Assistant: “put X on the watchlist at ₹… to ₹…”.</div>'}</div></section>
      <section class="rd-card" style="border-color:${sel && sel.status !== 'waiting' ? 'var(--warn)' : 'var(--line)'}">${sel ? `<div class="rd-row" style="flex-wrap:wrap">${chip(wlTag(sel)[0], wlTag(sel)[1])}<span style="font-size:20px;font-weight:700">${esc(sel.symbol)}</span></div>
        <div class="small soft" style="line-height:1.5">${esc(sel.reason)}</div>
        <div style="display:flex;gap:10px;flex-wrap:wrap"><div class="rd-stat"><span>Its point</span><b style="font-size:14px">${esc(wlRule(sel))}</b></div><div class="rd-stat"><span>Where the number came from</span><b style="font-size:14px">${esc(sel.calc_ref || '—')}</b></div></div>
        <div class="small muted">Added ${esc(String(sel.added_at).slice(0, 10))} by ${esc(sel.by)} · ${sel.age_days} days${sel.stale ? ' · <span class="warn">old: is the reason still true?</span>' : ''}${sel.note ? ' · ' + esc(sel.note) : ''}</div>
        <div style="font-weight:600;font-size:12px;color:var(--muted)">What happens next</div>
        <div class="rd-row" style="flex-wrap:wrap;gap:6px">${['Point reached', 'The team looks again', 'The independent review', 'Buy, wait or hold', 'Scored later'].map((t, i) => `${i ? '<span class="muted">→</span>' : ''}${chip(i === 0 && sel.status === 'triggered' ? 'up' : 'mute', t)}`).join('')}</div>
        <div class="small muted" style="margin-top:auto;line-height:1.45">Reaching the point never buys by itself. The system adds a name when research finds it worth waiting for and takes it off when the reason is gone. You can add or remove one from the chat.</div>` : '<div class="muted small">Select an item to see why it is waiting.</div>'}</section></div>`;
  }
  function wireWatchlist() { document.querySelectorAll('[data-wl]').forEach((b) => { b.onclick = () => { S.wsel = Number(b.dataset.wl); S.last = 0; load(true); }; }); }

  /* ---- Research overview ---- */
  const FLOW = [['ASK', 'a move, a date or you', 'var(--muted)'], ['RESEARCH', 'sources, for and against', 'var(--accent)'], ['QUANT', 'checked numbers', 'var(--warn)'], ['DECIDE', 'buy, hold, wait…', 'var(--up)'], ['REVIEW', 'independent check', 'var(--down)'], ['SCORE', 'later, vs the Nifty 500', '#A9C4FF']];
  function research(inv, ideas, d) {
    const work = (inv.investigations || []).slice(0, 4);
    const ST2 = { working: ['info', 'WORKING'], planning: ['info', 'PLANNING'], reviewing: ['info', 'REVIEW'], synthesising: ['info', 'WRITING'], done: ['up', 'DONE'], blocked: ['down', 'STUCK'], awaiting_approval: ['warn', 'NEEDS YES'], declined: ['mute', 'DECLINED'] };
    return `<div class="rd-two" style="grid-template-columns:1fr 1.15fr">
      <section class="rd-card" style="padding:20px 22px;gap:14px"><div><div class="rd-lbl">Why research exists</div><div style="font-size:23px;font-weight:700;letter-spacing:-.02em;line-height:1.25;margin-top:6px">Prices alone cannot tell it why something moved, or what it is missing.</div></div>
        ${[['1', 'info', 'It finds what prices cannot show', 'Results, filings, news and the reason a stock fell, each with a dated source. Without this it would be guessing.'], ['2', 'warn', 'It looks for evidence against its own idea', 'Every decision must carry the case against it. An idea nobody argued with has not been checked.'], ['3', 'up', 'A second mind checks the first', 'An independent reviewer re-runs the calculations and objects. That is how mistakes are caught before they cost money.']]
          .map((r) => `<div class="rd-item rd-row" style="align-items:flex-start;gap:12px"><span class="rd-chip ${r[1]}" style="border-radius:50%;width:26px;height:26px;display:flex;align-items:center;justify-content:center;padding:0">${r[0]}</span><div><div style="font-size:14px;font-weight:600">${r[2]}</div><div class="small soft" style="line-height:1.45;margin-top:2px">${r[3]}</div></div></div>`).join('')}
        <div style="font-size:13px;font-weight:600;color:var(--muted)">How one look runs</div>
        <div class="rd-row" style="flex-wrap:wrap;gap:6px;align-items:stretch">${FLOW.map((f, i) => `<div style="flex:1 1 90px;display:flex;align-items:center;gap:6px"><div class="rd-item" style="flex:1;text-align:center;border:1px solid ${f[2]}"><div style="font-size:12px;font-weight:700;color:${f[2]}">${f[0]}</div><div style="font-size:11px;color:var(--muted);line-height:1.3;margin-top:3px">${f[1]}</div></div>${i < FLOW.length - 1 ? '<span class="muted">→</span>' : ''}</div>`).join('')}</div>
        <div class="small muted" style="margin-top:auto;line-height:1.5">A look costs about ₹60–100 and starts only when something moves, a watchlist point is reached, you ask, or the weekly review is due. Past lessons and checked calculations are reused.</div></section>
      <div style="display:flex;flex-direction:column;gap:14px;min-height:0">
        <section class="rd-card" style="flex:1.3"><div class="rd-row" style="justify-content:space-between"><h2>What the team is looking into</h2><span class="small muted">${rs((d.money || {}).this_month)} of ${rs((d.money || {}).monthly)} this month</span></div>
          <div style="display:flex;flex-direction:column;gap:8px;flex:1;overflow:auto">${work.length ? work.map((w) => { const s = ST2[w.state] || ['mute', w.state]; return `<a class="rd-item rd-row" href="#/research/work" style="text-decoration:none;color:var(--text)">${chip(s[0], s[1])}<div style="flex:1;min-width:0"><div style="font-size:14px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(w.goal)}</div><div class="small muted">${esc((w.blocker || w.current_action || w.next_trigger || '').slice(0, 110))}</div></div></a>`; }).join('') : '<div class="muted small">Nothing is being looked into right now.</div>'}</div></section>
        <div class="rd-two" style="grid-template-columns:1fr 1fr;flex:1">
          <section class="rd-card"><h2>Ideas it tests on old years</h2>${(ideas.ideas || []).length ? ideas.ideas.map((i) => `<div class="rd-row small soft" style="align-items:flex-start;line-height:1.4">${chip(i.decision === 'pass' ? 'up' : i.decision === 'fail' ? 'down' : 'mute', (i.decision || i.status || 'pending').toUpperCase())}<span>${esc(String(i.claim).slice(0, 110))}</span></div>`).join('') : '<div class="small muted">None registered yet.</div>'}<div class="small muted" style="margin-top:auto">${esc(ideas.counter || 'Each test counts, so the bar for the next one rises.')}</div></section>
          <section class="rd-card"><h2>What it remembers</h2><div class="small soft" style="line-height:1.5">Past conclusions, the evidence that went against them, and calculations already checked. A new look starts from these, not from zero.</div><a class="small" href="#/research/memory" style="margin-top:auto">Ask it about a subject →</a></section></div></div></div>`;
  }

  /* ---- System checks ---- */
  function system(sc) {
    if (!sc.run) return `<div class="rd-card"><span class="rd-lbl">Does everything work?</span><div class="muted">The first full check runs tonight at 02:10, or press the button.</div><button class="btn primary" id="rdRun" style="align-self:flex-start">Run all checks now</button><div class="small muted" id="rdRunMsg"></div></div>`;
    const c = sc.counts, tot = sc.total;
    const colr = { ok: 'var(--up)', warn: 'var(--warn)', bad: 'var(--down)' };
    return `<section class="rd-card" style="flex-direction:row;flex-wrap:wrap;gap:24px;align-items:center;padding:14px 22px">
      ${ring(c.ok, tot, c.ok + ' of ' + tot + ' checks pass')}
      <div style="flex:1 1 280px"><div style="font-size:24px;font-weight:700;letter-spacing:-.02em">${c.ok} of ${tot} checks pass${c.bad ? ` · <span class="down">${c.bad} failing</span>` : ''}${c.warn ? ` · <span class="warn">${c.warn} could not run</span>` : ''}</div>
        <div class="small muted" style="line-height:1.45;margin-top:2px">Every agent, tool and model is tested by the system itself every night. A failing tool is not used until it passes again, and you get an alert. “Could not run” means it needs something this install lacks today (no Kite login, no Docker): never counted as a failure.</div></div>
      <div style="display:flex;flex-direction:column;gap:6px;align-items:flex-end"><button class="btn primary" id="rdRun">Run all checks now</button><span class="small muted" id="rdRunMsg">last full run ${esc(sc.run.at)}</span></div></section>
      <div class="rd-checks">${sc.groups.map((g) => `<section class="rd-card" style="border-color:${g.bad ? 'var(--down)' : 'var(--line)'}"><div class="rd-row" style="justify-content:space-between"><h2>${esc(g.title)}</h2><b class="small" style="color:${g.bad ? colr.bad : g.ok === g.total ? colr.ok : colr.warn}">${g.ok} of ${g.total}</b></div>
        <div style="display:flex;flex-direction:column;gap:6px;flex:1;min-height:0;overflow:auto">${g.items.map((i) => `<div class="rd-row" style="align-items:flex-start"><span class="rd-dot" style="background:${colr[i.status]}"></span><div style="min-width:0;flex:1"><div style="font-size:12px;font-weight:600">${esc(i.name.replace(/^probe: /, ''))}</div><div style="font-size:11px;color:${i.status === 'ok' ? 'var(--muted)' : colr[i.status]};line-height:1.35">${esc(i.note || '')}</div></div></div>`).join('')}</div></section>`).join('')}</div>`;
  }
  function wireSystem() { const b = $('rdRun'); if (!b) return; b.onclick = async () => { b.disabled = true; $('rdRunMsg').textContent = 'checking…'; try { await post('/api/selfcheck/run', {}); } catch (e) { $('rdRunMsg').textContent = e.message; } S.last = 0; load(true); }; }

  /* ---- Settings: what the AI may see and use ---- */
  const ABIL = [['charts', 'Look at charts', 'NEW', 'Candlesticks with volume and averages, as a picture plus the figures: for every agent and the assistant.'], ['kite_live', 'Kite live data', 'DATA', 'Live prices for fills and the watchlist, and Kite candles. Read only; orders are blocked in code.'],
    ['web', 'Search the web', 'RESEARCH', 'News, filings and the reason a stock moved. Never with your holdings in the question.'], ['calculations', 'Run its own calculations', 'SAFE', 'Code runs in a closed box: no network, read only, killed at its time limit.'], ['local_first', 'Local model first', 'FREE', 'Small jobs and the front of the chat run on this PC at no cost.']];
  function abilities(s, redraw) {
    const el = $('abilitiesP'); if (!el) return;
    const on = (k) => (s.abilities || {})[k] !== false;
    el.innerHTML = `<span class="lbl">What the AI may see and use</span><span class="small muted">Switch one off and no agent can use it: it is checked where it is used. Nothing here can place an order.</span>
      ${ABIL.map(([k, n, tag, help]) => `<div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><span>${esc(n)} <span class="rd-chip info" style="margin-left:6px">${tag}</span></span><span class="small muted">${esc(help)}</span></div><button class="toggle ${on(k) ? 'on' : ''}" role="switch" aria-checked="${on(k)}" aria-label="${esc(n)}" data-ab="${k}"><i></i></button></div>`).join('')}
      <div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><span>Weekend and holiday work <span class="rd-chip mute" style="margin-left:6px">ALWAYS ON</span></span><span class="small muted">The learner, postmortems and the daily look run every day: it never sits idle.</span></div></div>
      <div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><span>Place real orders <span class="rd-chip down" style="margin-left:6px">BLOCKED</span></span><span class="small muted">There is no such ability. It is refused in code, not by a setting.</span></div></div>`;
    el.querySelectorAll('[data-ab]').forEach((b) => { b.onclick = async () => { const k = b.dataset.ab; S.settings = await post('/api/settings', { abilities: { [k]: !on(k) } }); redraw(); }; });
  }

  /* ---- the entry points app.js calls ---- */
  const handles = (screen, sub) => screen === 'today' || screen === 'account' || screen === 'watchlist' || (screen === 'research' && sub === 'overview') || (screen === 'system' && sub === 'checks');
  async function load(screen, sub, fresh) {
    const wrap = (html) => `<div class="rd-fit" style="display:flex;flex-direction:column;gap:14px">${html}</div>`;
    if (screen === 'today') { const [d, sc] = await Promise.all([api('/api/paper'), api('/api/selfcheck').catch(() => null)]); if (fresh()) { $('screen').innerHTML = wrap(today(d, sc)); wireToday(); } }
    else if (screen === 'account') { const d = await api('/api/paper'); if (fresh()) { $('screen').innerHTML = wrap(account(d)); wireAccount(); } }
    else if (screen === 'watchlist') { const d = await api('/api/watchlist'); if (fresh()) { $('screen').innerHTML = wrap(watchlist(d.items || [])); wireWatchlist(); } }
    else if (screen === 'research') { const [inv, ideas, d] = await Promise.all([api('/api/investigations').catch(() => ({ investigations: [] })), api('/api/learner/ideas').catch(() => ({ ideas: [] })), api('/api/paper').catch(() => ({}))]); if (fresh()) $('screen').innerHTML = wrap(research(inv, ideas, d)); }
    else if (screen === 'system') { const sc = await api('/api/selfcheck'); if (fresh()) { $('screen').innerHTML = wrap(system(sc)); wireSystem(); } }
  }
  return { handles, load, abilities };
})();
