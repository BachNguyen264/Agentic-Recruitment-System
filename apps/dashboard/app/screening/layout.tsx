import { PublicShell } from "@/components/PublicShell";

// Layout CÔNG KHAI cho ứng viên trả lời sàng lọc (magic-link) — chrome riêng, TÁCH khỏi shell HR.
// Ứng viên vào thẳng bằng link trong email, không duyệt trang nào khác → KHÔNG truyền `href`
// (bấm nhầm logo là mất form đang điền dở, mà token chỉ dùng được một lần).
export default function ScreeningLayout({ children }: { children: React.ReactNode }) {
  return <PublicShell tagline="Bổ sung thông tin ứng tuyển">{children}</PublicShell>;
}
