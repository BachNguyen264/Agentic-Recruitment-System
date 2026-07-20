import type { MetadataRoute } from "next";

// Web app manifest — Next sinh /manifest.webmanifest + tự chèn <link rel="manifest">.
// PWA cài được lên màn hình chính (PRD §6: một app web duy nhất, không codebase mobile riêng).
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "HireFlow — Hệ thống tuyển dụng tự trị",
    short_name: "HireFlow",
    description: "Sàng lọc CV tự động bằng pipeline đa tác tử — dashboard HR + cổng nộp CV.",
    start_url: "/",
    display: "standalone",
    background_color: "#ffffff", // khớp nền canvas
    theme_color: "#1f6feb", // cobalt — màu nhấn thương hiệu
    icons: [
      { src: "/hireflow-192.png", sizes: "192x192", type: "image/png" },
      { src: "/hireflow-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
