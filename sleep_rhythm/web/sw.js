// Cache-first app shell, so the app opens at once even while a free server wakes up.
// The server replaces __SHELL_VERSION__ with a hash of the shell files: any change to
// them installs a new worker that caches the whole new shell at once, so old and new
// files are never mixed. API requests and other URLs are never cached.
const CACHE = 'rhythm-shell-__SHELL_VERSION__';
const SHELL = ['/', '/index.html', '/style.css', '/app.js', '/utils.js', '/icon.svg', '/icon-192.png', '/icon-512.png', '/manifest.webmanifest'];
self.addEventListener('install', e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener('activate', e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('rhythm-shell-') && k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== self.location.origin || !SHELL.includes(u.pathname)) return;
  e.respondWith(caches.open(CACHE).then(async cache => {
    const hit = await cache.match(e.request, {ignoreSearch: true});
    if (hit) return hit;
    try {
      const r = await fetch(e.request);
      if (r.ok && r.type === 'basic') cache.put(e.request, r.clone());
      return r;
    } catch {
      return (e.request.mode === 'navigate' && await cache.match('/')) || Response.error();
    }
  }));
});
