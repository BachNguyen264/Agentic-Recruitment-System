/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Cho phép Next transpile package workspace (TS nguồn) — không cần build dist riêng.
  transpilePackages: ["@ars/shared-types"],
  // Scaffold: bỏ qua lint khi build để khỏi chặn (chưa cấu hình eslint chi tiết).
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
