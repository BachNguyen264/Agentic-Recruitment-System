"use client";

import { useEffect } from "react";

// Đăng ký service worker — CHỈ ở production (SW phá hot-reload khi dev).
export function PWARegister() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    if (process.env.NODE_ENV !== "production") {
      // Dev: gỡ SW còn sót từ lần chạy production trên cùng origin (tránh serve chunk cũ).
      navigator.serviceWorker.getRegistrations().then((regs) => regs.forEach((r) => r.unregister()));
      return;
    }
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("Đăng ký service worker thất bại:", err);
    });
  }, []);
  return null;
}
