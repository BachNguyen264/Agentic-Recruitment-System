import type { MetadataRoute } from "next";

// Web app manifest — Next sinh /manifest.webmanifest + tự chèn <link rel="manifest">.
// PWA cài được lên màn hình chính (PRD §6: một app web duy nhất, không codebase mobile riêng).
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Autonomous Recruitment System",
    short_name: "ARS",
    description: "Hệ thống tuyển dụng tự trị — dashboard HR + cổng nộp CV.",
    start_url: "/",
    display: "standalone",
    background_color: "#f8fafc", // slate-50 — khớp nền body
    theme_color: "#0f172a", // slate-900
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
