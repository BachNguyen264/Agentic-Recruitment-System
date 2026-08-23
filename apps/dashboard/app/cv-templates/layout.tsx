import { PublicHeader } from "@/components/PublicHeader";

// Layout CÔNG KHAI cho kho CV mẫu — cùng chrome ứng viên như /apply (PublicHeader, không sidebar,
// không link HR). Nằm NGOÀI nhóm `app/(hr)/` nên layout HR (shell sidebar + guard gọi
// /api/auth/me) không hề được nạp: khách chưa đăng nhập vào thẳng được, và bundle của trang này
// KHÔNG kéo theo code HR.
//
// Container rộng hơn /apply (1040px so với 720px): 720px không đủ cho lưới 3 cột — ba thẻ bị bóp
// còn ~210px mỗi thẻ thì tên ngành xuống dòng giữa chừng.
//
// Logo dẫn về /apply chứ không về chính trang này: kho mẫu là chỗ ghé ngang, đích đến của ứng
// viên vẫn là danh sách vị trí.
export default function CvTemplatesLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas">
      {/* `maxWidth` phải đi CÙNG bề rộng container ngay dưới — để mặc định 720px thì logo và
          tagline thụt vào 160px so với tiêu đề và lưới, trông như lỗi render. */}
      <PublicHeader href="/apply" tagline="Mẫu CV miễn phí" maxWidth="max-w-[1040px]" />
      <div className="mx-auto max-w-[1040px] px-4 pb-12 pt-6 sm:px-6 sm:pt-8">{children}</div>
    </div>
  );
}
