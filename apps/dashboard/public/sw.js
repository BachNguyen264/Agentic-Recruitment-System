// Service worker TỐI GIẢN cho PWA (chỉ đăng ký ở production — xem PWARegister).
// Chiến lược: cache-first CHỈ cho /_next/static/* — URL có content-hash nên thực sự bất biến.
// MỌI thứ khác (trang HTML, /api/*, icon/manifest — URL không hash) đi thẳng network, KHÔNG cache
// (tránh dữ liệu/asset cũ; API còn nằm ở origin khác :8000 nên SW vốn không đụng tới).
// Đổi tên CACHE khi cần vô hiệu toàn bộ cache đã phát hành (activate sẽ dọn tên cũ).
const CACHE = "ars-static-v2";

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
    url.origin === self.location.origin && url.pathname.startsWith("/_next/static/");

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
