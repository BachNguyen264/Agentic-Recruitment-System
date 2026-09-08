import { PublicHeader } from "@/components/PublicHeader";

// Khung trang CÔNG KHAI (ứng viên) — dùng chung cho `/apply`, `/screening`, `/booking`,
// `/cv-templates`. Bốn layout đó trước đây chép tay cùng một cây JSX và chỉ khác ba tham số.
//
// Gộp lại KHÔNG phải vì đỡ vài dòng, mà vì một cái bẫy CÓ THẬT: bề rộng truyền cho `PublicHeader`
// phải KHỚP bề rộng container nội dung ngay dưới nó — header trải hết bề ngang nhưng hàng bên
// trong căn giữa, nên hai số lệch nhau là logo/tagline thụt vào so với tiêu đề (đo thật ở
// /cv-templates: lệch 160px mỗi bên). Khi hai chỗ nằm trong CÙNG một component và đọc CÙNG một
// biến, cái bẫy đó đóng vĩnh viễn thay vì phải nhớ mỗi lần thêm route công khai mới.
//
// Dùng cuộn của TÀI LIỆU (min-h-screen), KHÔNG dựng khung cuộn lồng như shell HR: trang công khai
// chỉ có một cột nội dung, thêm khung cuộn trong chỉ tổ sinh thanh cuộn thứ hai trên điện thoại.
export function PublicShell({
  tagline,
  href,
  maxWidth = "max-w-[720px]",
  children,
}: {
  /** Chú thích ngắn bên phải logo — nói cho ứng viên biết họ đang ở màn nào. */
  tagline: string;
  /** Đích của logo. BỎ TRỐNG ở màn vào-thẳng-bằng-magic-link (/screening, /booking): ở đó không có
   *  gì để duyệt, mà bấm nhầm là mất form đang điền dở. */
  href?: string;
  /** Đổi CẢ header lẫn container nội dung — không có cách nào để hai bên lệch nhau. */
  maxWidth?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-canvas">
      <PublicHeader href={href} tagline={tagline} maxWidth={maxWidth} />
      <div className={`mx-auto ${maxWidth} px-4 pb-12 pt-6 sm:px-6 sm:pt-8`}>{children}</div>
    </div>
  );
}
