"use client";

import { useEffect } from "react";

// Đăng ký service worker — CHỈ ở production (SW phá hot-reload khi dev).
export function PWARegister() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("Đăng ký service worker thất bại:", err);
    });
  }, []);
  return null;
}
