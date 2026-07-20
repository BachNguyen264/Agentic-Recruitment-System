import { PublicHeader } from "@/components/PublicHeader";

// Layout CÔNG KHAI cho ứng viên — chrome riêng, TÁCH khỏi shell HR (không sidebar, không link
// /jobs /applications /review).
//
// Dùng cuộn của TÀI LIỆU (min-h-screen), KHÔNG dựng khung cuộn lồng như shell HR: trang công khai
// chỉ có một cột nội dung, thêm khung cuộn trong chỉ tổ sinh thanh cuộn thứ hai trên điện thoại.
export default function ApplyLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas">
      <PublicHeader href="/apply" tagline="Nộp hồ sơ trực tuyến" />
      <div className="mx-auto max-w-[720px] px-4 pb-12 pt-6 sm:px-6 sm:pt-8">{children}</div>
    </div>
  );
}
