import "./globals.css";
import type { Metadata, Viewport } from "next";
import { Be_Vietnam_Pro, Manrope } from "next/font/google";
import { PWARegister } from "@/components/PWARegister";
import { Providers } from "./providers";

// UI redesign: chữ tiêu đề + thân — nạp qua next/font (self-host, không chặn render, không gọi
// Google lúc chạy). BẮT BUỘC subset "vietnamese": thiếu nó thì dấu tiếng Việt rơi về font dự phòng
// → chữ lệch nét NGAY GIỮA CÂU ("Bảng điều hành").
//
// Thiết kế gốc dùng Sora cho tiêu đề, NHƯNG Sora chỉ có subset latin/latin-ext (next/font báo lỗi
// lúc build) — toàn bộ giao diện là tiếng Việt nên không dùng được. Thay bằng Be Vietnam Pro: cùng
// chất geometric-grotesque, cùng dải đậm 700/800, và vốn được thiết kế cho dấu tiếng Việt.
const heading = Be_Vietnam_Pro({
  subsets: ["latin", "vietnamese"],
  weight: ["400", "600", "700", "800"],
  variable: "--font-heading", // đổi từ --font-sora: font thật là Be Vietnam Pro, không phải Sora
  display: "swap",
});
const manrope = Manrope({
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-manrope",
  display: "swap",
});

export const metadata: Metadata = {
  title: "HireFlow — Hệ thống tuyển dụng tự trị",
  description:
    "HireFlow — sàng lọc CV tự động bằng pipeline đa tác tử, HR quyết định ở các điểm dừng.",
  icons: {
    icon: "/hireflow-192.png",
    shortcut: "/favicon.ico",
    apple: "/hireflow-192.png",
  },
};

// PWA: theme màu thanh trạng thái + viewport chuẩn cho màn hình điện thoại.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#1f6feb",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi" className={`${heading.variable} ${manrope.variable}`}>
      <body className="min-h-screen">
        <Providers>{children}</Providers>
        <PWARegister />
      </body>
    </html>
  );
}
