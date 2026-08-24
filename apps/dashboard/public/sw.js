// Service worker cho PWA (chỉ đăng ký ở production — xem PWARegister).
//
// Ba nhánh, theo đúng thứ tự này:
//   1. RSC (`?_rsc=`)  -> mạng, hỏng thì 503 NGAY (ép Next chuyển sang điều hướng cứng)
//   2. điều hướng       -> mạng trước, hỏng thì trả trang /offline đã precache
//   3. /_next/static/*  -> cache-first (URL có content-hash nên thực sự bất biến)
// Mọi thứ khác đi thẳng network, KHÔNG cache.
//
// KHÔNG cache phản hồi API và KHÔNG cache trang nào khác. Từ slice 13, `/api/*` là SAME-ORIGIN
// (Vercel rewrite) nên nó ĐI QUA fetch handler này — comment cũ nói API nằm ở origin khác là SAI.
// Khoá của CacheStorage là URL đầy đủ, mà `/screening/{token}` và `/booking/{token}` mang token
// bearer TRONG ĐƯỜNG DẪN: ghi chúng vào cache là lưu một credential còn sống trên máy ứng viên,
// sống lâu hơn TTL và sống qua cả lượt vô hiệu one-time (NFR-4).
//
// Đổi tên CACHE để vô hiệu toàn bộ cache đã phát hành (activate sẽ dọn tên cũ).
const CACHE = "ars-static-v3";
const OFFLINE_URL = "/offline";

self.addEventListener("install", (event) => {
  self.skipWaiting();
  // `.catch` là BẮT BUỘC, không phải phòng xa: waitUntil bị reject thì SW mới KHÔNG BAO GIỜ activate
  // và client kẹt ở bản cũ vĩnh viễn, không có đường cứu ngoài xoá site data. Chỉ cần một lượt fetch
  // hỏng (đang mất mạng lúc kiểm cập nhật, hoặc lần deploy đầu SW lên trước route) là dính.
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.add(new Request(OFFLINE_URL, { cache: "reload" })))
      .catch(() => {})
  );
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
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  const sameOrigin = url.origin === self.location.origin;

  // (1) Điều hướng phía client của App Router KHÔNG phải `mode: "navigate"` — Next gọi
  // `fetch(url + "?_rsc=…")` không truyền `mode`, nên nó mặc định là "cors". Không bắt riêng thì
  // request này chờ hết timeout TCP/DNS rồi Next mới tự chuyển sang điều hướng cứng. Trả 503 ngay
  // khiến Next hard-nav lập tức, và lượt hard-nav đó rơi đúng vào nhánh (2).
  // TUYỆT ĐỐI không trả HTML của /offline cho request _rsc — Next sẽ cố parse nó như RSC payload.
  if (sameOrigin && (url.searchParams.has("_rsc") || request.headers.get("RSC") === "1")) {
    event.respondWith(fetch(request).catch(() => new Response("", { status: 503 })));
    return;
  }

  // (2) Điều hướng: mạng trước, KHÔNG ghi cache.
  // Chỉ dự phòng khi `fetch` REJECT (không dựng nổi kết nối). KHÔNG dự phòng khi `!res.ok`: Render
  // ngủ hoặc Cloudflare 502 thì fetch RESOLVE với 5xx, và gắn nhãn "bạn đang offline" cho một sự cố
  // backend là chẩn đoán sai — repo đã trả giá cho đúng loại nhầm lẫn này (docs/deploy-live-issues.md).
  if (sameOrigin && request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(async () => {
        const cached = await caches.match(OFFLINE_URL);
        return (
          cached ??
          new Response("<h1>Mất kết nối máy chủ</h1>", {
            status: 503,
            headers: { "content-type": "text/html; charset=utf-8" },
          })
        );
      })
    );
    return;
  }

  // (3) Tài nguyên tĩnh bất biến -> cache-first.
  if (sameOrigin && url.pathname.startsWith("/_next/static/")) {
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
      })
    );
  }
  // còn lại: không gọi respondWith -> trình duyệt tự xử lý, không cache.
});
