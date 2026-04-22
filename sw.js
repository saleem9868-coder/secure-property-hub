// ApnaGhar Service Worker v1.0
const CACHE_NAME = 'apnaghar-v1';
const OFFLINE_URL = '/';

// Core assets to cache immediately
const STATIC_ASSETS = [
  '/',
  '/static/logo.png',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png',
];

// Install — cache core assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activate — clean old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch — network first, fallback to cache
self.addEventListener('fetch', event => {
  // Only handle GET requests
  if (event.request.method !== 'GET') return;

  // Skip admin, API, upload routes — always fetch fresh
  const url = new URL(event.request.url);
  if (url.pathname.startsWith('/admin') ||
      url.pathname.startsWith('/uploads') ||
      url.pathname.startsWith('/debug')) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then(response => {
        // Cache successful responses for static assets
        if (response.ok && (
          url.pathname.startsWith('/static/') ||
          url.pathname === '/'
        )) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => {
        // Offline fallback — return cached version or homepage
        return caches.match(event.request) || caches.match(OFFLINE_URL);
      })
  );
});
