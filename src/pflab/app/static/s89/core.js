/* S90 core: the app's one front end. Each screen is the APPROVED DESIGN's own markup (static/s89/tpl/<screen>.html, built from design_s89 by
   tools/build_screens.py) filled with real data: a screen module computes the same values the design's sample script did, from the backend.
   The template language is the design's: {{path}} holes, <sc-for list as>, <sc-if value>, onClick / onSubmit / onChange handlers.
   Nothing here computes a decision; every figure comes from an endpoint, or the screen says "not yet". */
const S89 = (() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (x, d = 0) => (x == null || isNaN(x) ? '—' : Number(x).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d }));
  const rs = (x) => (x == null || isNaN(x) ? '—' : (x < 0 ? '−₹' : '₹') + Math.round(Math.abs(Number(x))).toLocaleString('en-IN'));
  const rsd = (x) => (x == null || isNaN(x) ? '—' : (x >= 0 ? '+₹' : '−₹') + Math.round(Math.abs(Number(x))).toLocaleString('en-IN'));
  const usd = (x) => (x == null || isNaN(x) ? '—' : '$' + Number(x).toLocaleString('en-US', { maximumFractionDigits: 2 }));
  const pct = (x, d = 1, sign = true) => (x == null || isNaN(x) ? '—' : (sign && x >= 0 ? '+' : x < 0 ? '−' : '') + Math.abs(Number(x)).toFixed(d) + '%');
  const kTok = (n) => (n == null ? '—' : n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1000 ? Math.round(n / 1000) + 'k' : String(Math.round(n)));
  const ago = (s) => { if (!s) return ''; const t = new Date(String(s).replace(' ', 'T')); if (isNaN(t)) return String(s).slice(0, 16); const m = Math.round((Date.now() - t) / 60000); return m < 1 ? 'just now' : m < 60 ? m + ' min ago' : m < 1440 ? Math.round(m / 60) + ' h ago' : t.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }); };
  const C = { blue: '#1D3FB8', orange: '#9A4209', mute: '#5B5E66', ink: '#17181C', ink2: '#3E4149' };
  const state = { screen: 'home', lastOk: null, timers: [], tpl: {}, ver: '' };
  const SCREENS = {};
  const NAV = [['home', 'Home'], ['money', 'Your money'], ['book', "Claude's book"], ['lab', 'Lab'], ['graph', 'Graph'], ['chat', 'Chat'], ['agents', 'Agents'], ['usage', 'Usage']];
  const BAR = [['home', 'Home'], ['money', 'Money'], ['lab', 'Lab'], ['graph', 'Graph'], ['chat', 'Chat']];
  const TOPICS = { home: ['portfolio', 'hq', 'settings', 'live', 'kite', 'plans', 'chat'], money: ['portfolio', 'live', 'kite'], chat: ['chat', 'plans'], usage: ['hq'], agents: ['hq', 'settings'], settings: ['settings', 'kite'] };

  /* ---- data ---- */
  async function api(path, opts) {
    try {
      const r = await fetch(path, opts);
      if (!r.ok) { const t = (await r.text()).slice(0, 300); let m = t; try { m = JSON.parse(t).detail || t; } catch (e) { /* plain text */ } const e = new Error(m); e.status = r.status; throw e; }
      const j = await r.json();
      if (j && j.offline) throw Object.assign(new Error('offline'), { offline: true });
      if (!opts || !opts.method || opts.method === 'GET') { try { localStorage.setItem('s89:' + path, JSON.stringify({ at: Date.now(), j })); } catch (e) { /* full */ } }
      state.lastOk = Date.now(); offline(false);
      return j;
    } catch (e) {
      if (e.status) throw e;
      offline(true);
      if (!opts || !opts.method || opts.method === 'GET') { try { const c = JSON.parse(localStorage.getItem('s89:' + path)); if (c) { c.j.__cached = c.at; return c.j; } } catch (e2) { /* none */ } }
      throw e;
    }
  }
  const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  function offline(off) {
    const b = $('offline'); if (!b) return;
    b.hidden = !off;
    if (off) b.querySelector('.t').textContent = "Can't reach your laptop since " + (state.lastOk ? new Date(state.lastOk).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : 'a while') + ' · showing the last numbers it sent';
  }

  /* ---- the design's template language ---- */
  const HOLE = /\{\{\s*([\w.]+)\s*\}\}/g;
  function get(scope, path) {
    path = String(path).replace(/[{}]/g, '').trim();
    if (path === 'true') return true; if (path === 'false') return false;
    let v = scope; for (const k of path.split('.')) { if (v == null) return undefined; v = v[k]; }
    return v;
  }
  const interp = (s, scope) => s.replace(HOLE, (m, p) => { const v = get(scope, p); return v == null ? '' : String(v); });
  const BOOL = ['checked', 'selected', 'disabled', 'open'];
  function child(scope, as, item, i) { const s = Object.create(scope); s[as] = item; s[as + 'I'] = i; return s; }
  function proc(node, scope) {
    if (node.nodeType === 3) { if (node.nodeValue.indexOf('{{') >= 0) node.nodeValue = interp(node.nodeValue, scope); return [node]; }
    if (node.nodeType !== 1) return [node];
    const tag = node.localName.toLowerCase();
    if (tag === 'sc-for') {
      const list = get(scope, node.getAttribute('list')) || [], as = node.getAttribute('as'), out = [];
      list.forEach((item, i) => { const s = child(scope, as, item, i); [...node.childNodes].forEach((ch) => out.push(...proc(ch.cloneNode(true), s))); });
      return out;
    }
    if (tag === 'sc-if') { if (!get(scope, node.getAttribute('value'))) return []; const out = []; [...node.childNodes].forEach((ch) => out.push(...proc(ch.cloneNode(true), scope))); return out; }
    if (node.hasAttribute('data-for')) {
      const list = get(scope, node.getAttribute('data-for')) || [], as = node.getAttribute('data-as');
      node.removeAttribute('data-for'); node.removeAttribute('data-as');
      return list.map((item, i) => proc(node.cloneNode(true), child(scope, as, item, i))[0]);
    }
    for (const a of [...node.attributes]) {
      const n = a.name;
      if (n.startsWith('hint-')) { node.removeAttribute(n); continue; }
      if (a.value.indexOf('{{') < 0) continue;
      if (n.startsWith('on')) {
        const fn = get(scope, a.value); node.removeAttribute(n);
        if (typeof fn === 'function') {
          let ev = n.slice(2);
          if (ev === 'change' && (tag === 'input' || tag === 'textarea') && !['checkbox', 'radio'].includes(node.getAttribute('type'))) ev = 'input';
          node.addEventListener(ev, fn);
        }
        continue;
      }
      if (BOOL.includes(n)) { const v = get(scope, a.value); if (v && v !== 'false') { node.setAttribute(n, ''); node[n] = true; } else { node.removeAttribute(n); node[n] = false; } continue; }
      const v = interp(a.value, scope); node.setAttribute(n, v); if (n === 'value' && 'value' in node) { node.value = v; node.__v = v; }
    }
    for (const ch of [...node.childNodes]) { const res = proc(ch, scope); if (res.length === 1 && res[0] === ch) continue; res.forEach((r) => node.insertBefore(r, ch)); ch.remove(); }
    if (node.__v != null && tag === 'select') node.value = node.__v;                // a select takes its value once its options exist
    return [node];
  }
  async function template(name) {
    if (!state.tpl[name]) { const r = await fetch('/static/s89/tpl/' + name + '.html?v=' + state.ver); if (!r.ok) throw new Error('no template ' + name); state.tpl[name] = await r.text(); }
    return state.tpl[name];
  }
  /* render(el, 'home', vals): the design's markup with the values; keeps the scroll of every scrolling panel and the focus and text of the field being typed in */
  async function render(el, name, vals) {
    const html = await template(name);
    const t = document.createElement('template'); t.innerHTML = html;
    const frag = document.createDocumentFragment();
    [...t.content.childNodes].forEach((n) => proc(n, vals).forEach((x) => frag.appendChild(x)));
    const scrolls = [...el.querySelectorAll('*')].filter((e) => e.scrollTop > 0).map((e) => e.scrollTop);
    const act = document.activeElement && el.contains(document.activeElement) && document.activeElement.getAttribute('aria-label');
    el.replaceChildren(frag);
    const frame = [...el.querySelectorAll('div')].slice(0, 3).find((d) => /padding/.test(d.getAttribute('style') || '')) || el.querySelector('div');   // the design's padded frame
    if (frame) frame.insertBefore(header(), frame.firstChild);
    [...el.querySelectorAll('*')].filter((e) => e.scrollHeight > e.clientHeight + 4 && getComputedStyle(e).overflowY !== 'visible').forEach((e, i) => { if (scrolls[i]) e.scrollTop = scrolls[i]; });
    if (act) { const f = el.querySelector(`[aria-label="${CSS.escape(act)}"]`); if (f) { f.focus(); if (f.setSelectionRange && f.value) f.setSelectionRange(f.value.length, f.value.length); } }
  }

  /* ---- the one header (the design's) ---- */
  const pillState = { text: 'Starting…', color: '#9A9DA4' };
  function header() {
    const h = document.createElement('header');
    h.style.cssText = 'flex: none; display: flex; flex-wrap: wrap; align-items: center; gap: 12px 24px';
    const link = (id, label) => `<a href="#/${id}" ${state.screen === id ? 'aria-current="page" style="padding: 7px 12px; border-radius: 999px; background: #17181C; color: #FFFFFF; text-decoration: none; font-weight: 500"' : 'style="padding: 7px 12px; border-radius: 999px; color: #3E4149; text-decoration: none; font-weight: 500"'}>${esc(label)}</a>`;
    h.innerHTML = `<a href="#/home" style="display: flex; align-items: center; gap: 10px; text-decoration: none; color: #17181C"><svg width="26" height="26" viewBox="0 0 28 28" aria-hidden="true"><circle cx="14" cy="14" r="12" fill="none" stroke="#2F5BEA" stroke-width="2.5"></circle><circle cx="14" cy="14" r="4.5" fill="#2F5BEA"></circle></svg><span style="font-family: 'Space Grotesk', Inter, sans-serif; font-weight: 700; font-size: 18px">Portfolio Lab</span></a>
      <nav aria-label="Main" class="pl-nav" style="display: flex; flex-wrap: wrap; gap: 2px">${NAV.map(([id, l]) => link(id, l)).join('')}</nav>
      <div style="margin-left: auto; display: flex; align-items: center; gap: 8px"><a href="#/home" id="pill" style="display: inline-flex; align-items: center; gap: 8px; padding: 7px 12px; border-radius: 999px; background: #FFFFFF; border: 1px solid #E6E4DD; font-weight: 500; color: #17181C; text-decoration: none"><svg width="10" height="10" aria-hidden="true"><circle cx="5" cy="5" r="5" fill="${pillState.color}"></circle></svg><span>${esc(pillState.text)}</span></a>
      <a href="#/settings" aria-label="Settings" style="width: 40px; height: 40px; border-radius: 999px; border: 1px solid #E6E4DD; background: #FFFFFF; color: #3E4149; display: flex; align-items: center; justify-content: center"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true"><circle cx="12" cy="12" r="8" stroke-width="3" stroke-dasharray="3.14 3.14"></circle><circle cx="12" cy="12" r="5.5" stroke-width="2"></circle><circle cx="12" cy="12" r="2" stroke-width="2"></circle></svg></a></div>`;
    return h;
  }
  async function pill() {
    try {
      const o = await api('/api/operator'); const need = (o.open_cards || []).length;
      const ok = o.signed_in && o.thinking === 'running';
      pillState.color = ok ? '#2FA36B' : o.thinking === 'paused' ? '#D9620F' : '#9A9DA4';
      pillState.text = (o.thinking === 'paused' ? 'Thinking paused' : ok ? 'Operator thinking' : 'Operator off') + (need ? ` · ${need} thing${need > 1 ? 's' : ''} need you` : '');
    } catch (e) { pillState.text = 'Operator unknown'; }
    const p = $('pill'); if (p) { p.querySelector('circle').setAttribute('fill', pillState.color); p.querySelector('span').textContent = pillState.text; }
  }

  /* ---- small drawing helpers the screens share (the design's own) ---- */
  function path(vals, w, h, lo, hi, top = 4) {
    const v = (vals || []).filter((x) => x != null); if (v.length < 2) return '';
    lo = lo == null ? Math.min(...v) : lo; hi = hi == null ? Math.max(...v) : hi;
    return v.map((x, i) => (i ? 'L' : 'M') + (i / (v.length - 1) * w).toFixed(1) + ' ' + (top + (1 - (x - lo) / ((hi - lo) || 1)) * (h - 2 * top)).toFixed(1)).join(' ');
  }

  /* ---- the router ---- */
  function register(name, fn) { SCREENS[name] = fn; }
  function bar() {
    const b = $('bar'); if (!b) return;
    b.innerHTML = BAR.map(([id, l]) => `<a href="#/${id}" class="${state.screen === id ? 'on' : ''}">${esc(l)}</a>`).join('');
  }
  async function show(name) {
    const fn = SCREENS[name] || SCREENS.home; state.screen = SCREENS[name] ? name : 'home';
    state.timers.forEach(clearInterval); state.timers = [];
    const el = $('screen');
    try { await fn(el); } catch (e) { el.innerHTML = `<div style="padding: 28px; font: 14px Inter, sans-serif"><b>Could not load this screen</b><br><span style="color: #5B5E66">${esc(e.message || e)}</span></div>`; }
    bar();
  }
  function route() { show((location.hash.replace('#/', '') || 'home').split('/')[0]); }
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
    state.ver = document.documentElement.dataset.ver || String(Date.now());
    window.addEventListener('hashchange', route); route(); pill(); setInterval(pill, 60000); listen();
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => null);
  }
  return { $, esc, num, rs, rsd, usd, pct, kTok, ago, C, api, post, render, path, register, start, every, show, state, pill };
})();
