/** @type {import('next').NextConfig} */

// Deploy cross-domain (slice 13): frontend (Vercel) và backend (Render) là HAI SITE khác nhau, nên
// cookie auth do backend đặt là cookie BÊN-THỨ-BA. Trình duyệt điện thoại (iOS Safari/WebKit; Chrome
// Android đời mới) CHẶN cookie bên-thứ-ba mặc định → đăng nhập xong bị đá về /login (laptop desktop
// còn cho phép nên không lộ). FIX: proxy `/api/*` qua CHÍNH origin của frontend → trình duyệt gọi API
// same-origin → cookie thành FIRST-PARTY của domain frontend → chạy trên mọi thiết bị.
//
// Cách dùng:
//   - prod (Vercel): đặt env `BACKEND_ORIGIN=https://<service>.onrender.com` (server-side, KHÔNG
//     NEXT_PUBLIC) + `NEXT_PUBLIC_API_BASE=""` (rỗng → lib/api.ts gọi same-origin `/api/...`).
//   - dev: KHÔNG đặt BACKEND_ORIGIN → không rewrite; giữ `NEXT_PUBLIC_API_BASE=http://localhost:8000`
//     (localhost là same-site, cookie chạy bình thường, không cần proxy).
const backendOrigin = process.env.BACKEND_ORIGIN?.replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  // Cho phép Next transpile package workspace (TS nguồn) — không cần build dist riêng.
  transpilePackages: ["@ars/shared-types"],
  // Scaffold: bỏ qua lint khi build để khỏi chặn (chưa cấu hình eslint chi tiết).
  eslint: { ignoreDuringBuilds: true },
  // Proxy same-origin sang backend (chỉ khi BACKEND_ORIGIN được đặt — tức prod). Rewrite tới URL
  // NGOÀI được Vercel proxy ở tầng edge (KHÔNG phải serverless function 4.5MB) — nộp CV ≤10MB verify
  // lại trên bản live. Không có Next API route nào ở /api nên rewrite không đụng route nội bộ.
  async rewrites() {
    if (!backendOrigin) return [];
    return [{ source: "/api/:path*", destination: `${backendOrigin}/api/:path*` }];
  },
};

export default nextConfig;
