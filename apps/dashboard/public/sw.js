// Service worker TỐI GIẢN cho PWA (chỉ đăng ký ở production — xem PWARegister).
// Chiến lược: cache-first CHỈ cho static bất biến (/_next/static có hash + icon/manifest).
// MỌI thứ khác — đặc biệt /api/* và dữ liệu động — đi thẳng network, KHÔNG cache
// (tránh dữ liệu cũ; API còn nằm ở origin khác :8000 nên SW vốn không đụng tới).
const CACHE = "ars-static-v1";

const STATIC_PATHS = ["/icon-192.png", "/icon-512.png", "/manifest.webmanifest"];

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isImmutableStatic =
    url.origin === self.location.origin &&
    (url.pathname.startsWith("/_next/static/") || STATIC_PATHS.includes(url.pathname));

  // Không phải GET hoặc không phải static bất biến -> để network xử lý (không cache).
  if (event.request.method !== "GET" || !isImmutableStatic) return;

  event.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const cached = await cache.match(event.request);
      if (cached) return cached;
      const response = await fetch(event.request);
      if (response.ok) cache.put(event.request, response.clone());
      return response;
    })
  );
});
