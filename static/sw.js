// ApnaGhar Service Worker v2.0
const CACHE_NAME = 'apnaghar-v2';

// Only cache true static assets — NEVER cache HTML pages
const STATIC_ASSETS = [
  '/static/logo.png',
  '/static/icon-192x192.png',
  '/static/icon-512x512.png',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  // Delete ALL old caches (including apnaghar-v1 which cached '/')
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);

  // Never intercept HTML pages — always fetch fresh from server
  const isHTML = event.request.headers.get('accept')?.includes('text/html');
  if (isHTML) return;

  // Never intercept admin or upload routes
  if (url.pathname.startsWith('/admin') || url.pathname.startsWith('/uploads')) return;

  // For static assets only: cache-first strategy
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then(cached => {
        if (cached) return cached;
        return fetch(event.request).then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          }
          return response;
        });
      })
    );
  }
  // All other requests (API calls, etc.) go straight to network
});
