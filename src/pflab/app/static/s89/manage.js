/* S89 Add and watch: his real US holdings entered by hand (never the paper ledger) and his watchlist (names he does not own; the alarm lane checks them too; up to 25). */
S89.register('manage', async (el) => {
  const { esc, usd, pct, cls, api, post, empty, num } = S89;
  const sel = new Set(['moves 3%+', 'news']);
  async function draw(msg) {
    const [m, w] = await Promise.all([api('/api/mine?tab=us'), api('/api/mine/watch')]);
    const us = m.rows || [], total = us.reduce((a, r) => a + (r.value_inr || 0), 0);
    const usRows = us.length ? us.map((h) => `<tr><td><b>${esc(h.symbol)}</b><br><span class="small muted">${h.bought_on ? 'since ' + esc(h.bought_on) : ''}</span></td>
        <td><input type="number" step="any" min="0" value="${esc(h.qty)}" data-set="${esc(h.symbol)}" aria-label="Shares of ${esc(h.symbol)}" style="width:90px"></td><td class="n">${usd(h.avg)}</td>
        <td class="n">${h.value_inr ? S89.rs(h.value_inr) : '<span class="muted small">next check</span>'}</td><td class="n ${cls(h.since_buy_pct)}">${pct(h.since_buy_pct)}</td><td><button class="btn ghost" data-rm="${esc(h.symbol)}">Remove</button></td></tr>`).join('')
      : `<tr><td colspan="6">${empty('No US holdings yet. Add one above.')}</td></tr>`;
    const alerts = (w.alerts || []).map((a) => `<button type="button" class="btn ghost" data-al="${esc(a)}" style="${sel.has(a) ? 'background:var(--accent-bg);border-color:var(--accent)' : ''}">${esc(a)}</button>`).join('');
    const wl = (w.rows || []).length ? w.rows.map((x) => `<div class="card" style="gap:4px"><div class="row"><b>${esc(x.symbol)}</b><span class="chip mute">${esc(x.market)}</span>${(x.alerts || []).map((a) => `<span class="chip">${esc(a)}</span>`).join('')}<button class="btn ghost" data-wrm="${esc(x.symbol)}" style="margin-left:auto">Stop watching</button></div>
        ${x.why ? `<span class="small">${esc(x.why)}</span>` : ''}<span class="small muted">Claude: ${x.note ? 'latest headline: ' + esc(x.note) : 'nothing heard yet'}</span></div>`).join('') : empty('Nothing on the watchlist yet.');
    el.innerHTML = `<div class="row"><a href="#/money">Your money</a><span class="muted">/</span><b>Add and watch</b></div><div class="muted small">Everything here stays on your laptop. Claude reads it; it never places orders.</div>
      ${msg ? `<div class="banner ${msg.err ? 'warn' : 'plan'}"><span class="${msg.err ? 'err' : 'b'}">${esc(msg.text)}</span></div>` : ''}
      <section class="grid" style="align-items:flex-start">
        <div class="card" style="flex:1.3 1 560px"><h2>Your real US investments · entered by hand</h2><span class="small muted">until you connect a US broker · ${total ? S89.rs(total) : 'value after the next price check'}</span>
          <form class="row" id="usForm"><label>Ticker<input name="ticker" required maxlength="6" style="width:90px" autocapitalize="characters"></label><label>Shares<input name="shares" type="number" step="any" min="0" required style="width:90px"></label>
            <label>Average price ($)<input name="avg_price" type="number" step="any" min="0" required style="width:120px"></label><label>Bought on<input name="bought_on" type="date"></label><button class="btn" type="submit">Add</button></form>
          <div class="scroll"><table><thead><tr><th>Holding</th><th>Shares</th><th class="n">Avg price</th><th class="n">Value today</th><th class="n">Since buy</th><th></th></tr></thead><tbody>${usRows}</tbody></table></div>
          <span class="small muted">Prices come from the US bars feed. Selling? Lower the shares, or remove it. This record is yours alone: it never touches Claude's paper book.</span></div>
        <div class="card" style="flex:1 1 420px"><h2>Watchlist</h2><span class="small muted">names you do not own yet that Claude watches for you · ${w.count} of ${w.cap}</span>
          <form class="row" id="wlForm"><label>Name or ticker<input name="symbol" required maxlength="20" style="width:140px" autocapitalize="characters"></label><label>Market<select name="market"><option>India</option><option>US</option></select></label>
            <label>Why you are watching (optional)<input name="why" maxlength="200" style="width:200px"></label><div class="col" style="gap:4px"><span class="small muted">Tell me when</span><div class="row" id="alerts" style="gap:4px">${alerts}</div></div><button class="btn" type="submit">Watch</button></form>
          <div class="col">${wl}</div><span class="small muted">The alarm reader checks every name each 15 minutes, so each one adds a little to its tokens. Up to ${w.cap} names.</span></div>
      </section>`;
    const fail = (e) => draw({ err: true, text: e.message });
    $f('usForm').onsubmit = async (ev) => { ev.preventDefault(); const f = Object.fromEntries(new FormData(ev.target)); try { await post('/api/mine/us', { action: 'add', ...f }); draw({ text: 'Added ' + f.ticker.toUpperCase() + '.' }); } catch (e) { fail(e); } };
    $f('wlForm').onsubmit = async (ev) => { ev.preventDefault(); const f = Object.fromEntries(new FormData(ev.target)); try { await post('/api/mine/watch', { action: 'add', ...f, alerts: [...sel] }); draw({ text: 'Watching ' + f.symbol.toUpperCase() + '.' }); } catch (e) { fail(e); } };
    el.querySelectorAll('[data-set]').forEach((i) => { i.onchange = async () => { try { await post('/api/mine/us', { action: 'set', ticker: i.dataset.set, shares: i.value }); draw({ text: 'Updated ' + i.dataset.set + '.' }); } catch (e) { fail(e); } }; });
    el.querySelectorAll('[data-rm]').forEach((b) => { b.onclick = async () => { try { await post('/api/mine/us', { action: 'remove', ticker: b.dataset.rm }); draw({ text: 'Removed ' + b.dataset.rm + '.' }); } catch (e) { fail(e); } }; });
    el.querySelectorAll('[data-wrm]').forEach((b) => { b.onclick = async () => { try { await post('/api/mine/watch', { action: 'remove', symbol: b.dataset.wrm }); draw({ text: 'Stopped watching ' + b.dataset.wrm + '.' }); } catch (e) { fail(e); } }; });
    el.querySelectorAll('[data-al]').forEach((b) => { b.onclick = () => { sel.has(b.dataset.al) ? sel.delete(b.dataset.al) : sel.add(b.dataset.al); b.style.cssText = sel.has(b.dataset.al) ? 'background:var(--accent-bg);border-color:var(--accent)' : ''; }; });
  }
  const $f = (id) => document.getElementById(id);
  await draw();
});
