import { PublicHeader } from "@/components/PublicHeader";

// Layout CÔNG KHAI cho ứng viên trả lời sàng lọc (magic-link) — chrome riêng, TÁCH khỏi shell HR.
// Ứng viên vào thẳng bằng link trong email, không duyệt trang nào khác → thương hiệu để dạng chữ,
// KHÔNG link về /apply (bấm nhầm là mất form đang điền dở).
export default function ScreeningLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas">
      <PublicHeader tagline="Bổ sung thông tin ứng tuyển" />
      <div className="mx-auto max-w-[720px] px-4 pb-12 pt-6 sm:px-6 sm:pt-8">{children}</div>
    </div>
  );
}
