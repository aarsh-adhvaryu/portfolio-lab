/* S89: a minimal service worker so Add to Home screen works over his private link. It keeps the page shell and the last good answer of each read-only endpoint, so a phone that cannot reach the laptop
   shows the last numbers (the page adds the "can't reach your laptop" banner itself). Nothing is cached for writes. */
const SHELL = 'pl-shell-s89';
const DATA = 'pl-data-s89';
const FILES = ['/', '/static/s89/s89.css', '/static/s89/core.js', '/static/s89/home.js', '/static/s89/money.js', '/static/s89/manage.js', '/static/s89/book.js', '/static/s89/lab.js', '/static/s89/graph.js',
  '/static/s89/chat.js', '/static/s89/agents.js', '/static/s89/usage.js', '/static/s89/settings.js', '/static/icon.svg'];
self.addEventListener('install', (e) => { e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES).catch(() => null)).then(() => self.skipWaiting())); });
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL && k !== DATA).map((k) => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', (e) => {
  const r = e.request, u = new URL(r.url);
  if (r.method !== 'GET' || u.pathname === '/api/events') return;
  if (u.pathname.startsWith('/api/')) {
    e.respondWith(fetch(r).then((res) => { if (res.ok && !u.pathname.startsWith('/api/assistant')) { const cp = res.clone(); caches.open(DATA).then((c) => c.put(r, cp)); } return res; })
      .catch(() => caches.match(r).then((m) => m || new Response(JSON.stringify({ offline: true }), { status: 503, headers: { 'Content-Type': 'application/json' } }))));
    return;
  }
  e.respondWith(fetch(r).then((res) => { const cp = res.clone(); caches.open(SHELL).then((c) => c.put(r, cp)); return res; }).catch(() => caches.match(r)));
});
