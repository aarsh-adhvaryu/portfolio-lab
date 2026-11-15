/* S89 core: helpers, the router, the menu, the operator pill, live refresh and the offline cache. Every figure comes from the backend; nothing here computes a decision. */
const S89 = (() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (x, d = 0) => (x == null || isNaN(x) ? '—' : Number(x).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d }));
  const rs = (x) => (x == null || isNaN(x) ? '—' : '₹' + Math.round(Number(x)).toLocaleString('en-IN'));
  const usd = (x) => (x == null || isNaN(x) ? '—' : '$' + Number(x).toLocaleString('en-US', { maximumFractionDigits: 2 }));
  const pct = (x, d = 1, sign = true) => (x == null || isNaN(x) ? '—' : (sign && x >= 0 ? '+' : x < 0 ? '−' : '') + Math.abs(Number(x)).toFixed(d) + '%');
  const cls = (x) => (x == null ? '' : x >= 0 ? 'up' : 'dn');
  const ago = (s) => { if (!s) return ''; const t = new Date(String(s).replace(' ', 'T')); if (isNaN(t)) return String(s).slice(0, 16); const m = Math.round((Date.now() - t) / 60000); return m < 1 ? 'just now' : m < 60 ? m + ' min ago' : m < 1440 ? Math.round(m / 60) + ' h ago' : String(s).slice(0, 10); };
  const state = { screen: 'home', lastOk: null, timers: [], cache: {} };
  const SCREENS = {};
  const NAV = [['home', 'Home'], ['money', 'Your money'], ['book', "Claude's book"], ['lab', 'Lab'], ['graph', 'Graph'], ['chat', 'Chat'], ['agents', 'Agents'], ['usage', 'Usage']];
  const BAR = [['home', 'Home'], ['money', 'Money'], ['lab', 'Lab'], ['graph', 'Graph'], ['chat', 'Chat']];
  const WIDE = ['stock', 'home', 'money', 'manage', 'book', 'lab', 'agents', 'chat'];
  const TOPICS = { home: ['portfolio', 'hq', 'settings', 'live', 'kite', 'plans', 'chat'], money: ['portfolio', 'live', 'kite'], chat: ['chat', 'plans'], usage: ['hq', 'settings'], agents: ['hq', 'settings'] };

  async function api(path, opts) {
    try {
      const r = await fetch(path, opts);
      if (!r.ok) { const t = (await r.text()).slice(0, 300); let m = t; try { m = JSON.parse(t).detail || t; } catch (e) { /* plain text */ } const e = new Error(m); e.status = r.status; throw e; }
      const j = await r.json();
      if (j && j.offline) throw Object.assign(new Error('offline'), { offline: true });
      if (!opts || !opts.method || opts.method === 'GET') { try { localStorage.setItem('s89:' + path, JSON.stringify({ at: Date.now(), j })); } catch (e) { /* storage full */ } }
      state.lastOk = Date.now(); setOffline(false);
      return j;
    } catch (e) {
      if (e.status) throw e;                                                       // a real answer from the laptop (a 4xx) is not "offline"
      setOffline(true);
      if (!opts || !opts.method || opts.method === 'GET') { try { const c = JSON.parse(localStorage.getItem('s89:' + path)); if (c) { c.j.__cached = c.at; return c.j; } } catch (e2) { /* no cache */ } }
      throw e;
    }
  }
  const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

  function setOffline(off) {
    const b = $('offline'); if (!b) return;
    if (off) { b.hidden = false; const t = state.lastOk ? new Date(state.lastOk).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : 'a while'; b.innerHTML = `<span class="t">Can't reach your laptop since ${esc(t)}</span><span class="small">Showing the last numbers it sent.</span>`; } else b.hidden = true;
  }

  function sparkline(vals, w = 90, h = 26, color = '#2F5BEA') {
    const v = (vals || []).filter((x) => x != null); if (v.length < 2) return '';
    const lo = Math.min(...v), hi = Math.max(...v), d = v.map((x, i) => (i ? 'L' : 'M') + (i / (v.length - 1) * w).toFixed(1) + ' ' + (2 + (1 - (x - lo) / ((hi - lo) || 1)) * (h - 4)).toFixed(1)).join(' ');
    return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><path d="${d}" fill="none" stroke="${color}" stroke-width="1.6"/></svg>`;
  }
  function lines(series, w = 640, h = 200, colors = ['#D9620F', '#2F5BEA', '#9A9DA4']) {
    const all = series.flatMap((s) => s.filter((x) => x != null)); if (all.length < 2) return '';
    const lo = Math.min(...all), hi = Math.max(...all);
    return `<svg width="100%" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="chart" style="max-height:${h}px">` + series.map((s, k) => {
      const d = s.map((x, i) => (i ? 'L' : 'M') + (i / Math.max(1, s.length - 1) * w).toFixed(1) + ' ' + (6 + (1 - (x - lo) / ((hi - lo) || 1)) * (h - 12)).toFixed(1)).join(' ');
      return `<path d="${d}" fill="none" stroke="${colors[k % colors.length]}" stroke-width="2" vector-effect="non-scaling-stroke"/>`;
    }).join('') + '</svg>';
  }
  const empty = (msg) => `<div class="empty">${esc(msg)}</div>`;
  const head = (a, b) => `<div class="row"><h2>${a}</h2>${b ? `<span class="muted small">${b}</span>` : ''}</div>`;

  function register(name, fn) { SCREENS[name] = fn; }
  function menu() {
    $('nav').innerHTML = NAV.map(([id, l]) => `<a href="#/${id}" class="${state.screen === id ? 'on' : ''}">${esc(l)}</a>`).join('');
    $('bar').innerHTML = BAR.map(([id, l]) => `<a href="#/${id}" class="${state.screen === id ? 'on' : ''}">${esc(l)}</a>`).join('');
    document.body.classList.toggle('wide', WIDE.includes(state.screen));
  }
  async function pill() {
    try {
      const o = await api('/api/operator'); const need = (o.open_cards || []).length;
      const ok = o.signed_in && o.thinking === 'running';
      $('pilldot').setAttribute('fill', ok ? '#2FA36B' : o.thinking === 'paused' ? '#D9620F' : '#9A9DA4');
      $('pilltxt').textContent = (o.thinking === 'paused' ? 'Thinking paused' : ok ? 'Operator thinking' : 'Operator off') + (need ? ` · ${need} thing${need > 1 ? 's' : ''} need you` : '');
    } catch (e) { $('pilltxt').textContent = 'Operator unknown'; }
  }
  async function show(name) {
    const fn = SCREENS[name] || SCREENS.home; state.screen = SCREENS[name] ? name : 'home'; menu();
    const el = $('screen'); state.timers.forEach(clearInterval); state.timers = [];
    try { await fn(el); } catch (e) { el.innerHTML = `<div class="card"><b>Could not load this screen</b><span class="muted small">${esc(e.message || e)}</span></div>`; }
    el.focus({ preventScroll: true });
  }
  function route() { const id = (location.hash.replace('#/', '') || 'home').split('/')[0]; show(id); }
  function every(ms, fn) { state.timers.push(setInterval(fn, ms)); }
  function listen() {
    if (!window.EventSource) return;
    const es = new EventSource('/api/events'); let prev = null, t = null;
    es.onmessage = (ev) => {
      let v; try { v = JSON.parse(ev.data); } catch (e) { return; }
      if (prev) { const ch = Object.keys(v).filter((k) => v[k] !== prev[k]); const want = TOPICS[state.screen]; if (ch.length && want && ch.some((k) => want.includes(k)) && !document.querySelector('#screen input:focus, #screen textarea:focus')) { clearTimeout(t); t = setTimeout(() => show(state.screen), 600); } }
      prev = v;
    };
  }
  function start() {
    menu(); window.addEventListener('hashchange', route); route(); pill(); setInterval(pill, 60000); listen();
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => null);
  }
  return { $, esc, num, rs, usd, pct, cls, ago, api, post, sparkline, lines, empty, head, register, start, every, show, state };
})();
