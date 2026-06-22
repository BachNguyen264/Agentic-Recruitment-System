import "./globals.css";
import type { Metadata } from "next";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "ARS — Dashboard HR",
  description: "Hệ thống tuyển dụng tự trị (scaffold). Nguồn chân lý: PRD.md.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">{<Providers>{children}</Providers>}</body>
    </html>
  );
}
