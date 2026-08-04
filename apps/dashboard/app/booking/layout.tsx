import { PublicHeader } from "@/components/PublicHeader";

// Layout CÔNG KHAI cho ứng viên chọn giờ phỏng vấn (SCH-2 · PRD §10b). Nằm NGOÀI nhóm `(hr)` nên
// không có guard đăng nhập và không kéo theo shell HR — Next.js tách bundle theo route, trang này
// chỉ tải đúng thứ nó cần (bài học JD-1).
//
// KHÔNG link về /apply: người mở link này đã được MỜI phỏng vấn — dẫn họ về danh sách vị trí chỉ
// làm họ phân tâm khỏi việc duy nhất cần làm ở đây là chọn giờ.
export default function BookingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas">
      <PublicHeader tagline="Đặt lịch phỏng vấn" />
      <div className="mx-auto max-w-[720px] px-4 pb-12 pt-6 sm:px-6 sm:pt-8">{children}</div>
    </div>
  );
}
