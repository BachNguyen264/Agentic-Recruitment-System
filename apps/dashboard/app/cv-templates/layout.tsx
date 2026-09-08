import { PublicShell } from "@/components/PublicShell";

// Layout CÔNG KHAI cho kho CV mẫu — cùng chrome ứng viên như /apply. Nằm NGOÀI nhóm `app/(hr)/`
// nên layout HR (shell sidebar + guard gọi /api/auth/me) không hề được nạp: khách chưa đăng nhập
// vào thẳng được, và bundle của trang này KHÔNG kéo theo code HR.
//
// Container rộng hơn /apply (1040px so với 720px): 720px không đủ cho lưới 3 cột — ba thẻ bị bóp
// còn ~210px mỗi thẻ thì tên ngành xuống dòng giữa chừng. `PublicShell` áp con số này cho CẢ header
// lẫn nội dung nên hai bên không thể lệch (bẫy 160px cũ).
//
// Logo dẫn về /apply chứ không về chính trang này: kho mẫu là chỗ ghé ngang, đích đến của ứng
// viên vẫn là danh sách vị trí.
export default function CvTemplatesLayout({ children }: { children: React.ReactNode }) {
  return (
    <PublicShell href="/apply" tagline="Mẫu CV miễn phí" maxWidth="max-w-[1040px]">
      {children}
    </PublicShell>
  );
}
