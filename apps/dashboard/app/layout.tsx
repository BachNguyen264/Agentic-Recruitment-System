import "./globals.css";
import type { Metadata, Viewport } from "next";
import { PWARegister } from "@/components/PWARegister";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "ARS — Dashboard HR",
  description: "Hệ thống tuyển dụng tự trị (scaffold). Nguồn chân lý: PRD.md.",
};

// PWA: theme màu thanh trạng thái + viewport chuẩn cho màn hình điện thoại.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0f172a",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">
        <Providers>{children}</Providers>
        <PWARegister />
      </body>
    </html>
  );
}
