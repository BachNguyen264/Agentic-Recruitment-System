import { PublicShell } from "@/components/PublicShell";

// Layout CÔNG KHAI cho ứng viên — chrome riêng, TÁCH khỏi shell HR (không sidebar, không link
// /jobs /applications /review). Khung dùng chung ở components/PublicShell.
export default function ApplyLayout({ children }: { children: React.ReactNode }) {
  return (
    <PublicShell href="/apply" tagline="Nộp hồ sơ trực tuyến">
      {children}
    </PublicShell>
  );
}
