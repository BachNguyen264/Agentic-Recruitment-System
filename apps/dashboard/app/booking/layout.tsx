import { PublicShell } from "@/components/PublicShell";

// Layout CÔNG KHAI cho ứng viên chọn giờ phỏng vấn (SCH-2 · PRD §10b). Nằm NGOÀI nhóm `(hr)` nên
// không có guard đăng nhập và không kéo theo shell HR — Next.js tách bundle theo route, trang này
// chỉ tải đúng thứ nó cần (bài học JD-1).
//
// KHÔNG truyền `href`: người mở link này đã được MỜI phỏng vấn — dẫn họ về danh sách vị trí chỉ
// làm họ phân tâm khỏi việc duy nhất cần làm ở đây là chọn giờ.
export default function BookingLayout({ children }: { children: React.ReactNode }) {
  return <PublicShell tagline="Đặt lịch phỏng vấn">{children}</PublicShell>;
}
