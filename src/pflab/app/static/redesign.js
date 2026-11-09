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

  function donut(rows) {
    const R = 58, C = 2 * Math.PI * R; let off = 0;
    const segs = rows.filter((r) => r.w > 0).map((r) => { const len = C * r.w; const x = `<circle r="${R}" cx="80" cy="80" fill="none" stroke="${r.c}" stroke-width="24" stroke-dasharray="${Math.max(0, len - 1.5).toFixed(1)} ${(C - len + 1.5).toFixed(1)}" stroke-dashoffset="${(-off).toFixed(1)}" transform="rotate(-90 80 80)"><title>${esc(r.name)} ${(r.w * 100).toFixed(1)}%</title></circle>`; off += len; return x; }).join('');
    return `<svg width="190" height="190" viewBox="0 0 160 160" role="img" aria-label="Where the account sits" style="flex:none"><circle r="${R}" cx="80" cy="80" fill="none" stroke="var(--line)" stroke-width="24"></circle>${segs}<text x="80" y="76" text-anchor="middle" font-size="11" fill="var(--muted)">invested</text><text x="80" y="95" text-anchor="middle" font-size="20" font-weight="700" fill="currentColor">${(100 - (rows[rows.length - 1].w * 100)).toFixed(0)}%</text></svg>`;
  }

  /* ---- Today: one page ---- */
  /* ---- the v2 core on Today (S80): spend by use, the champion against the plain baseline, the open storylines. Every figure comes from /api/core. ---- */
  const cp = (x, dg = 1) => (x == null ? '—' : pct(x, dg, true));
  function coreCards(cv) {
    if (!cv) return '';
    const sp = cv.spend, po = cv.policies, st = cv.storylines;
    const spend = sp ? `<section class="rd-card"><h2>What the strategist costs</h2>
        <div class="rd-row small" style="justify-content:space-between"><span>This month</span><b>${rs(sp.month.total)}</b></div>
        <div class="small muted">strategist ${rs(sp.month.strategist)} · checker ${rs(sp.month.checker)} · escalation ${rs(sp.month.escalation)}</div>
        <div class="small">${sp.lab_runs} lab runs · ${sp.challengers_added} challengers added · ${sp.promotions} promotions${sp.runs_per_100_rupees != null ? ` <span class="muted">(${sp.runs_per_100_rupees} runs, ${sp.challengers_per_100_rupees} challengers per Rs 100)</span>` : ''}</div>
        ${sp.next_session_budget != null ? `<div class="small muted">next session may spend ${rs(typeof sp.next_session_budget === 'object' ? (sp.next_session_budget.rupees != null ? sp.next_session_budget.rupees : 0) : sp.next_session_budget)}</div>` : ''}</section>` : '';
    const row = (n, h) => `<div class="rd-row small" style="justify-content:space-between"><span>${esc(n)}</span><span>${h ? `${cp(h.cagr)} a year · ${cp(h.excess_cagr)} over the Nifty 500` : 'not run yet'}</span></div>`;
    const pol = po ? `<section class="rd-card"><h2>The policy that trades</h2>
        <div class="small"><b>${esc(po.champion || 'none yet')}</b>${po.since ? ` <span class="muted">since ${esc(po.since)}</span>` : ''} <span class="muted">· ${po.closes_run} closes run, ${po.closes_with_trades} with trades</span></div>
        <div class="small muted" style="margin-top:4px">Tested on 2005 to 2017, after tax and charges</div>
        ${row('Champion', po.champion_history)}${row('Plain baseline', po.baseline_history)}
        ${po.book_vs_benchmark ? `<div class="small" style="margin-top:4px">Live: the book ${cp(po.book_vs_benchmark.book, 2)} against ${cp(po.book_vs_benchmark.benchmark, 2)} for its benchmark since ${esc(po.book_vs_benchmark.since)}</div>` : '<div class="small muted">No live score yet: it starts after the book has marked days.</div>'}
        ${po.held_back_by_index_limit ? `<div class="small warn" style="margin-top:4px">${po.held_back_by_index_limit} challenger(s) are held back only by the index rule (after tax and charges: at most ${Math.round(po.index_limit * 100)} points a year behind with no deeper fall, or ${Math.round(po.index_rule.b_max_lag * 100)} points behind with a fall a third smaller)</div>` : ''}
        ${po.challengers.length ? `<div class="small muted" style="margin-top:4px">Challengers</div>` + po.challengers.map((c) => `<div class="rd-row small" style="justify-content:space-between"><span>${esc(c.policy)}</span><span>${c.shadow_sessions != null ? c.shadow_sessions + ' of 20 sessions · ' + cp(c.shadow_excess, 2) + ' against the champion' : 'not scored'}</span></div><div class="small muted">${c.slice ? 'trades ' + Math.round(c.slice * 100) + '% of the book: ' : 'no slice: '}${esc(String(c.slice_why || '').slice(0, 140))}</div>`).join('') : '<div class="small muted">No challenger yet.</div>'}</section>` : '';
    const sto = st ? `<section class="rd-card"><h2>What is driving the market</h2>
        ${st.length ? st.map((s) => `<div class="small" style="line-height:1.4"><b>${s.direction === 'up' ? '▲' : '▼'} ${Math.round(s.probability * 100)}%</b> ${esc(String(s.claim).slice(0, 150))}<div class="muted">influence ${s.influence.toFixed(2)} · ${s.scored} scored (${s.good} right), ${s.pending} pending · opened ${esc(s.opened_on)}</div></div>`).join('') : '<div class="small muted">No open storyline. The system opens one when a few signals line up.</div>'}</section>` : '';
    return (spend || pol || sto) ? `<div class="rd-row" style="gap:14px;align-items:stretch;flex-wrap:wrap">${[pol, sto, spend].filter(Boolean).map((h) => h.replace('<section class="rd-card"', '<section class="rd-card" style="flex:1 1 300px"')).join('')}</div>` : '';
  }
  function today(d, sc, cv) {
    if (!d.started) return `<div class="rd-card"><span class="rd-lbl">The account</span><div class="muted">${esc(d.note || 'Starting…')}</div></div>`;
    const days = d.days || [], nifty = d.nifty || [];
    const vals = days.map((x) => x.value), nv = nifty.map((x) => x.value);
    const all = vals.concat(nv), lo = Math.min(...all), hi = Math.max(...all);
    const last = vals[vals.length - 1], prev = vals.length > 1 ? vals[vals.length - 2] : last;
    const dayChg = last - prev, r = d.returns || {}, gate = d.gate || {};
    const sinceN = nv.length > 1 ? nv[nv.length - 1] / nv[0] - 1 : null;
    const holds = (d.holdings || []).slice(0, 6).map((h, i) => ({ name: h.symbol, w: h.weight, c: BUCKET_COLORS[i % BUCKET_COLORS.length], over: h.weight > 0.1 }));
    holds.push({ name: 'Cash', w: (d.cash || 0) / (d.value || 1), c: '#475569' });
    const acts = ['live_watch', 'daily_look', 'postmortem', 'weekly_review'].map((k) => (d.acts || []).find((a) => a.loop === k)).filter(Boolean);
    const decs = (d.recent_decisions || []).slice(0, 3);
    const les = (d.lessons || []).slice(0, 2);
    const checks = sc && sc.run ? sc.counts : null, mon = d.money || {};
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
          : `<div class="rd-row" style="flex:1;gap:26px;justify-content:center;min-height:0">${donut(holds)}<div style="display:flex;flex-direction:column;gap:7px;min-width:0">${holds.map((h) => `<div class="rd-row small"><span class="rd-dot" style="background:${h.c};margin:0"></span><span style="min-width:90px">${esc(h.name)}</span><b>${pct(h.w, 1)}</b></div>`).join('')}<span class="small muted" style="margin-top:6px;max-width:230px;line-height:1.4">The value line starts after its second marked day: after the next close.</span></div></div>`}
        <div style="display:flex;gap:10px;flex-wrap:wrap">
          <div class="rd-stat"><span>Broker cash</span><b>${rs(d.cash)}</b></div>
          <div class="rd-stat"><span>Bank · top-up room ${d.topup ? rs(d.topup.room) : ''}</span><b>${rs(d.bank)}</b></div>
          <div class="rd-stat"><span>Fall from its high · stops buying at 12%</span><b>${pct(Math.abs((d.breaker || {}).drawdown || 0), 1)}</b></div></div>
        <div class="rd-row" style="border-top:1px solid var(--line);padding-top:12px;flex-wrap:wrap;gap:16px">
          ${ring(d.sessions || 0, 40, (d.sessions || 0) + ' of 40 sessions')}
          <div style="flex:1 1 180px"><b class="small">Proving itself: ${d.sessions || 0} of 40 sessions</b><div class="small muted">${esc((gate.status || '').slice(0, 130))}</div></div>
          <div style="flex:1 1 180px"><div class="small rd-row" style="justify-content:space-between"><span>API money this month</span><span>${rs(mon.total != null ? mon.total : mon.this_month)} of ${rs(mon.cap || mon.monthly)}</span></div>
            <div style="height:8px;border-radius:5px;background:var(--line);margin-top:6px;overflow:hidden"><div style="height:100%;width:${Math.min(100, 100 * ((mon.total != null ? mon.total : mon.this_month) || 0) / ((mon.cap || mon.monthly) || 1))}%;background:var(--warn)"></div></div>
            <div class="small muted" style="margin-top:4px">the paper team may use ${rs(mon.monthly)} of it</div></div></div>
      </section>
      <section class="rd-card"><div class="rd-row" style="justify-content:space-between"><h2><a href="#/account">What it owns →</a></h2><span class="small muted">line = 10% limit</span></div>
        <div style="display:flex;flex-direction:column;gap:9px;justify-content:space-between;flex:1">${holds.map((h) => `<div class="rd-row"><span style="flex:0 0 84px;font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis">${esc(h.name)}</span><div class="rd-bar" style="flex:1"><i style="width:${Math.min(100, h.w * 500)}%;background:${h.over ? 'var(--warn)' : h.c}"></i><u></u></div><span style="flex:0 0 46px;text-align:right;font-size:12px;font-weight:600">${pct(h.w, 1)}</span></div>`).join('')}</div></section>
      <section class="rd-card"><div class="rd-row" style="justify-content:space-between"><h2><a href="#/system/checks">It never sits idle →</a></h2><span class="small muted">last act</span></div>
        <div style="display:flex;flex-direction:column;gap:9px;justify-content:space-between;flex:1">${acts.length ? acts.map((a) => `<div class="rd-row" style="align-items:flex-start"><span class="rd-dot" style="background:var(--up)"></span><div style="min-width:0"><div style="font-size:13px;font-weight:600">${esc(LOOP[a.loop] || a.loop)} <span class="muted" style="font-weight:500">· ${esc(when(a.at))}</span></div><div class="small soft" style="line-height:1.35">${esc(String(a.what).replace(/^daily look: |^postmortem: /, '').slice(0, 110))}</div></div></div>`).join('') : '<div class="muted small">Its loops have not acted yet.</div>'}</div></section>
      <section class="rd-card"><h2><a href="#/watchlist">What it decided · waits on →</a></h2>
        <div style="display:flex;flex-direction:column;gap:8px;flex:1;justify-content:space-between">${decs.length ? decs.map((x) => { const s = DEC[x.status] || ['mute', x.status]; return `<a href="#/watchlist" class="rd-item rd-row" style="text-decoration:none;color:var(--text)">${chip(ACT[x.action] || 'mute', x.action)}<div style="flex:1;min-width:0"><div style="font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(x.symbol || 'cash')} · ${esc((x.reason || '').slice(0, 60))}</div><div class="small ${s[0] === 'warn' ? 'warn' : 'up'}" style="font-weight:600">${esc(s[1])}</div></div></a>`; }).join('') : '<div class="muted small">No decision yet.</div>'}</div></section>
      <section class="rd-card"><h2><a href="#/research">Right now · learned →</a></h2>
        ${d.working_on ? `<div class="rd-item small"><b style="color:var(--accent)">WORKING</b> The team is looking into investigation #${d.working_on}.</div>` : '<div class="rd-item small muted">The team is idle: nothing needs a review today.</div>'}
        ${les.map((l) => `<div class="small soft" style="border-top:1px solid var(--line);padding-top:8px;line-height:1.45">${esc(l.text)}</div>`).join('')}
        ${checks ? `<a href="#/system/checks" class="small" style="margin-top:auto">${checks.ok} of ${sc.total} self-checks pass${checks.bad ? ' · ' + checks.bad + ' failing' : ''} →</a>` : ''}</section>
    </div>
    ${coreCards(cv)}
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
    return `<div class="rd-two" style="grid-template-columns:minmax(0,1.7fr) minmax(0,1fr);grid-template-rows:auto minmax(0,1fr)">
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
      <div class="rd-two" style="grid-template-columns:minmax(0,1.25fr) minmax(0,1fr)">
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

  /* ---- Research: one page, pictures first ---- */
  const FLOW = [['EVENTS', 'filings, news, flows', 'var(--muted)', 'M12 2a10 10 0 100 20 10 10 0 000-20zm0 5v6m0 3v1'], ['STORYLINES', 'what drives the market', 'var(--accent)', 'M11 4a7 7 0 100 14 7 7 0 000-14zm10 17l-5-5'], ['POLICY', 'the promoted rule decides', 'var(--warn)', 'M4 20V10m6 10V4m6 16v-7m6 7H2'], ['EXITS', 'stops, targets, tax', 'var(--up)', 'M5 12l5 5 9-10'], ['RAILS', 'limits, in code', 'var(--down)', 'M3 12s4-7 9-7 9 7 9 7-4 7-9 7-9-7-9-7zm9-3a3 3 0 100 6 3 3 0 000-6z'], ['SCORE', 'after tax, vs holding', '#A9C4FF', 'M3 17l6-6 4 4 8-8']];
  const icon = (p, c) => `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${p}"></path></svg>`;
  function research(inv, ideas, d, cv) {
    const stories = ((cv || {}).storylines || []).slice(0, 4);
    const list = ideas.ideas || [], cnt = (k) => list.filter((i) => (i.decision || '') === k).length, tests = parseInt(String(ideas.counter || '0'), 10) || 0;
    const bar = [['pass', 'passed', 'var(--up)'], ['fail', 'failed', 'var(--down)'], ['same', 'no better than simple', 'var(--warn)'], ['untestable', 'untestable', 'var(--line)']];
    const why = [['info', 'M11 4a7 7 0 100 14 7 7 0 000-14zm10 17l-5-5', 'Finds what prices cannot show', 'filings, results, news, with dates'], ['warn', 'M12 3l9 16H3L12 3zm0 6v4m0 3v1', 'Tests before it trades', 'every rule is replayed on 2005-2017 after tax and charges, with a luck test'], ['up', 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z', 'Held to the index', 'a rule trades only if it stays near the Nifty 500 after tax']];
    return `<div class="rd-two" style="grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);grid-template-rows:minmax(0,1fr)">
      <section class="rd-card" style="padding:22px;gap:16px"><div class="rd-lbl">How it decides</div>
        <div style="font-size:24px;font-weight:700;letter-spacing:-.02em;line-height:1.25">The AI writes and tests rules. Code decides every number and places every paper trade.</div>
        <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px">${why.map((w) => `<div class="rd-item" style="display:flex;flex-direction:column;gap:6px">${icon(w[1], `var(--${w[0] === 'info' ? 'accent' : w[0]})`)}<b style="font-size:14px">${w[2]}</b><span class="small muted" style="line-height:1.4">${w[3]}</span></div>`).join('')}</div>
        <div class="rd-lbl" style="margin-top:4px">One close, start to finish</div>
        <div style="display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:6px;align-items:stretch">${FLOW.map((f, i) => `<div style="display:flex;flex-direction:column;align-items:center;gap:6px;position:relative">
          <div style="width:100%;border:1px solid ${f[2]};border-radius:12px;padding:12px 4px;display:flex;flex-direction:column;align-items:center;gap:6px;background:var(--panel2)">${icon(f[3], f[2])}<b style="font-size:11px;letter-spacing:.04em;color:${f[2]}">${f[0]}</b><span style="font-size:10.5px;color:var(--muted);text-align:center;line-height:1.3">${f[1]}</span></div>${i < 5 ? `<span class="muted" style="position:absolute;right:-9px;top:34px;font-size:12px">›</span>` : ''}</div>`).join('')}</div>
        <div class="rd-row small muted" style="margin-top:auto;flex-wrap:wrap;gap:14px"><span>A strategist session costs at most ₹300 and starts when a reason appears (weekly, a probation slice, a thesis break), or when you ask in the chat.</span></div></section>
      <div style="display:flex;flex-direction:column;gap:14px;min-height:0;min-width:0">
        <section class="rd-card" style="flex:1.2"><div class="rd-row" style="justify-content:space-between"><h2>Watching now</h2><span class="small muted">open storylines</span></div>
          <div style="display:flex;flex-direction:column;gap:8px;flex:1;min-height:0;justify-content:flex-start">${stories.length ? stories.map((x) => `<a class="rd-item rd-row" href="#/today" style="text-decoration:none;color:var(--text);min-width:0">${chip(x.direction === 'up' ? 'up' : 'warn', Math.round(x.probability * 100) + '%')}<span style="flex:1;min-width:0;font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(x.claim)}">${esc(x.claim)}</span></a>`).join('') : '<div class="rd-item small muted">No open storyline. The system opens one when a few signals line up.</div>'}</div></section>
        <section class="rd-card" style="flex:1"><div class="rd-row" style="justify-content:space-between"><h2>Ideas tested on old years</h2><span class="rd-row" style="gap:6px"><b style="font-size:22px">${tests}</b><span class="small muted">tests counted</span></span></div>
          ${list.length ? `<div style="display:flex;height:12px;border-radius:6px;overflow:hidden;background:var(--panel2)">${bar.map((b) => cnt(b[0]) ? `<i title="${cnt(b[0])} ${b[1]}" style="flex:${cnt(b[0])};background:${b[2]}"></i>` : '').join('')}</div>
          <div class="rd-row small muted" style="flex-wrap:wrap;gap:12px">${bar.filter((b) => cnt(b[0])).map((b) => `<span><span class="rd-dot" style="display:inline-block;margin:0 5px 0 0;background:${b[2]}"></span>${cnt(b[0])} ${b[1]}</span>`).join('')}</div>` : '<div class="small muted">None yet.</div>'}
          <div class="small muted" style="margin-top:auto">Each test raises the bar for the next one. What fails is never used.</div></section>
        <div class="small muted rd-row" style="gap:14px;flex-wrap:wrap">Advanced: <a href="#/research/work">experiments</a><a href="#/research/memory">memory</a><a href="#/research/rules">rules and money</a><a href="#/research/sims">simulations</a><a href="#/research/graph">knowledge graph</a></div></div></div>`;
  }

  /* ---- System: does it work (the run is shown happening) ---- */
  const GCOL = { ok: 'var(--up)', warn: 'var(--warn)', bad: 'var(--down)' };
  function system(sc, d, rel) {
    const running = !!sc.running, tot = sc.total || 0, c = sc.counts || { ok: 0, warn: 0, bad: 0 }, exp = sc.expected || 66;
    if (!running && !sc.run) return `<div class="rd-card" style="align-items:flex-start"><span class="rd-lbl">Does everything work?</span><div style="font-size:22px;font-weight:700">Not checked yet.</div><div class="muted small">It checks itself every night at 02:10, or now:</div><button class="btn primary" id="rdRun">Run all checks now</button></div>`;
    const frac = running ? Math.min(1, tot / exp) : (tot ? c.ok / tot : 0), c2 = 2 * Math.PI * 42;
    const last = running && sc.groups.length ? sc.groups[sc.groups.length - 1].items.slice(-1)[0] : null;
    const money = d && d.money ? d.money : {}, cap = money.cap || 0, tm = money.total != null ? money.total : money.this_month || 0;
    return `<section class="rd-card" style="flex-direction:row;gap:22px;align-items:center;padding:16px 24px">
      <svg width="76" height="76" viewBox="0 0 104 104" role="img" aria-label="${c.ok} of ${tot}" style="flex:none"><circle cx="52" cy="52" r="42" fill="none" stroke="var(--line)" stroke-width="11"></circle><circle cx="52" cy="52" r="42" fill="none" stroke="${running ? 'var(--accent)' : c.bad ? 'var(--down)' : 'var(--up)'}" stroke-width="11" stroke-linecap="round" stroke-dasharray="${(c2 * frac).toFixed(1)} ${c2.toFixed(1)}" transform="rotate(-90 52 52)" style="transition:stroke-dasharray .5s"></circle><text x="52" y="58" text-anchor="middle" font-size="26" font-weight="700" fill="currentColor">${running ? tot : c.ok}</text></svg>
      <div style="flex:1;min-width:0"><div style="font-size:26px;font-weight:700;letter-spacing:-.02em">${running ? `Checking… ${tot} of about ${exp}` : `${c.ok} of ${tot} checks pass`}${!running && c.bad ? ` · <span class="down">${c.bad} failing</span>` : ''}${!running && c.warn ? ` · <span class="warn">${c.warn} could not run</span>` : ''}</div>
        <div class="small muted" style="margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${running ? (last ? 'now: ' + esc(last.name.replace(/^probe: /, '')) : 'starting…') : 'Every agent, tool and model is tested every night. A failing tool is not used until it passes.'}</div></div>
      <div style="display:flex;flex-direction:column;gap:6px;align-items:flex-end"><button class="btn primary" id="rdRun" ${running ? 'disabled' : ''}>${running ? 'Running…' : 'Run all checks now'}</button><span class="small muted">${running ? '' : 'last run ' + esc(sc.run.at.slice(5))}</span></div></section>
      <div class="rd-checks">${sc.groups.map((g) => { const odd = g.items.filter((i) => i.status !== 'ok');
        return `<section class="rd-card" style="border-color:${g.bad ? 'var(--down)' : 'var(--line)'};padding:14px 16px;gap:10px"><div class="rd-row" style="justify-content:space-between"><h2 style="font-size:15px">${esc(g.title)}</h2><b class="small" style="color:${g.bad ? GCOL.bad : g.ok === g.total ? GCOL.ok : GCOL.warn}">${g.ok}/${g.total}</b></div>
          <div style="display:flex;flex-wrap:wrap;gap:7px">${g.items.map((i) => `<span class="rd-pip" title="${esc(i.name.replace(/^probe: /, '') + ' — ' + (i.note || ''))}" style="background:${GCOL[i.status]}"></span>`).join('')}</div>
          <div style="display:flex;flex-direction:column;gap:5px;min-height:0;overflow:hidden">${odd.slice(0, 3).map((i) => `<div class="rd-row" style="align-items:flex-start;gap:8px"><span class="rd-dot" style="background:${GCOL[i.status]};margin-top:4px"></span><div style="min-width:0"><div style="font-size:12px;font-weight:600">${esc(i.name.replace(/^probe: /, ''))}</div><div style="font-size:11px;color:${GCOL[i.status]};line-height:1.3">${esc((i.note || '').slice(0, 70))}</div></div></div>`).join('')}${odd.length > 3 ? `<span class="small muted">+${odd.length - 3} more</span>` : ''}${!odd.length ? '<span class="small muted">All good.</span>' : ''}</div></section>`; }).join('')}</div>
      <div class="rd-row" style="gap:14px;flex-wrap:wrap">
        <section class="rd-card" style="flex:1 1 300px;flex-direction:row;align-items:center;gap:14px;padding:12px 18px"><div style="flex:1"><div class="rd-lbl">API money this month</div><div class="rd-bar" style="margin-top:8px;height:10px"><i style="width:${cap ? Math.min(100, 100 * tm / cap) : 0}%;background:var(--warn)"></i></div></div><b style="font-size:18px">${rs(tm)} <span class="small muted" style="font-weight:500">of ${rs(cap)}</span></b></section>
        <section class="rd-card" style="flex:1 1 300px;flex-direction:row;align-items:center;gap:14px;padding:12px 18px"><div style="flex:1"><div class="rd-lbl">This release</div><b>${esc((rel && rel.tag) || '—')}</b></div><span class="small muted rd-row" style="gap:14px;flex-wrap:wrap">Advanced: <a href="#/system/now">now</a><a href="#/system/limits">limits</a><a href="#/system/schedule">schedule</a></span></section></div>`;
  }
  function wireSystem(sc) {
    const b = $('rdRun');
    if (b) b.onclick = async () => { b.disabled = true; try { await post('/api/selfcheck/run', {}); } catch (e) { alert(e.message); } S.last = 0; load(true); };
  }

  /* ---- Settings: what the AI may see and use ---- */
  const ABIL = [['charts', 'Look at charts', 'NEW', 'Candlesticks with volume and averages, as a picture plus the figures: for every agent and the assistant.'], ['kite_live', 'Kite live data', 'DATA', 'Live prices for fills and the watchlist, and Kite candles. Read only; orders are blocked in code.'],
    ['web', 'Search the web', 'RESEARCH', 'News, filings and the reason a stock moved. Never with your holdings in the question.'], ['calculations', 'Run its own calculations', 'SAFE', 'Code runs in a closed box: no network, read only, killed at its time limit.'], ['local_first', 'Local model first', 'FREE', 'Small jobs and the front of the chat run on this PC at no cost.']];
  function abilities(s, redraw) {
    const el = $('abilitiesP'); if (!el) return;
    const on = (k) => (s.abilities || {})[k] !== false;
    el.innerHTML = `<span class="lbl">What the AI may see and use</span><span class="small muted">Switch one off and no agent can use it: it is checked where it is used. Nothing here can place an order.</span>
      ${ABIL.map(([k, n, tag, help]) => `<div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><span>${esc(n)} <span class="rd-chip info" style="margin-left:6px">${tag}</span></span><span class="small muted">${esc(help)}</span></div><button class="toggle ${on(k) ? 'on' : ''}" role="switch" aria-checked="${on(k)}" aria-label="${esc(n)}" data-ab="${k}"><i></i></button></div>`).join('')}
      <div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><span>Weekend and holiday work <span class="rd-chip mute" style="margin-left:6px">ALWAYS ON</span></span><span class="small muted">The learner, postmortems and the daily look run every day: it never sits idle.</span></div></div>
      <div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><label for="bkDir">Backup folder</label><span class="small muted">the nightly copy of the ledger goes here (outside the app's folder)</span></div><input id="bkDir" class="inp" style="flex:0 1 260px" value="${esc(s.backup_dir || '')}" placeholder="D:\\PL_backup"><button class="btn" id="bkSave">Save</button></div>
      <div class="setting"><div style="flex:1;display:flex;flex-direction:column;gap:2px"><span>Place real orders <span class="rd-chip down" style="margin-left:6px">BLOCKED</span></span><span class="small muted">There is no such ability. It is refused in code, not by a setting.</span></div></div>`;
    $('bkSave').onclick = async () => { S.settings = await post('/api/settings', { backup_dir: $('bkDir').value.trim() }); redraw(); };
    el.querySelectorAll('[data-ab]').forEach((b) => { b.onclick = async () => { const k = b.dataset.ab; S.settings = await post('/api/settings', { abilities: { [k]: !on(k) } }); redraw(); S.last = 0; load(true); }; });       // (the reload settles a draw that was already under way)
  }

  /* ---- the entry points app.js calls ---- */
  const handles = (screen, sub) => screen === 'today' || screen === 'account' || screen === 'watchlist' || (screen === 'research' && sub === 'overview') || (screen === 'system' && sub === 'checks');
  function paint(html, wire) {
    const el = $('screen'), sig = String(html.length) + ':' + html;
    if (el.dataset.sig === sig && el.firstElementChild && el.firstElementChild.classList.contains('rd-fit')) return;       // nothing changed: do not redraw (no flicker)
    keepInputs(() => { el.innerHTML = `<div class="rd-fit" style="display:flex;flex-direction:column;gap:14px">${html}</div>`; el.dataset.sig = sig; });
    wire();
  }
  let autoRan = false;
  function staleRun(sc) {
    if (autoRan || !sc || sc.running) return;
    const at = sc.run ? new Date(String(sc.run.at).replace(' ', 'T')) : null;
    if (!at || isNaN(at) || Date.now() - at > 6 * 3600e3) { autoRan = true; post('/api/selfcheck/run', {}).then(() => { S.last = 0; load(true); }).catch(() => {}); }
  }
  let pollT = null;
  function pollWhileRunning(sc) {                                    // the run is shown happening: look again every second while it goes (one timer, whatever was redrawn)
    if (!sc || !sc.running || pollT) return;
    pollT = setTimeout(() => { pollT = null; if (S.screen === 'system' && S.sub === 'checks') load(true); }, 1000);
  }
  async function loadScreen(screen, sub, fresh) {
    if (screen === 'today') { const [d, sc, cv] = await Promise.all([api('/api/paper'), api('/api/selfcheck').catch(() => null), api('/api/core').catch(() => null)]); if (fresh()) paint(today(d, sc, cv), wireToday); }
    else if (screen === 'account') { const d = await api('/api/paper'); if (fresh()) paint(account(d), wireAccount); }
    else if (screen === 'watchlist') { const d = await api('/api/watchlist'); if (fresh()) paint(watchlist(d.items || []), wireWatchlist); }
    else if (screen === 'research') { const [inv, ideas, d, cv] = await Promise.all([api('/api/investigations').catch(() => ({ investigations: [] })), api('/api/learner/ideas?limit=12').catch(() => ({ ideas: [] })), api('/api/paper').catch(() => ({})), api('/api/core').catch(() => null)]); if (fresh()) paint(research(inv, ideas, d, cv), () => {}); }
    else if (screen === 'system') { const [sc, d, rel] = await Promise.all([api('/api/selfcheck'), api('/api/paper').catch(() => ({})), api('/api/release').catch(() => ({}))]); staleRun(sc); if (fresh()) { paint(system(sc, d, rel), () => wireSystem(sc)); pollWhileRunning(sc); } }
  }
  return { handles, load: loadScreen, abilities };
})();
