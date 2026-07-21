import Link from "next/link";
import { Logo } from "@/components/Logo";

// Thanh đầu trang CÔNG KHAI — dùng chung cho /apply và /screening để hai bề mặt ứng viên không
// trôi dạt khác nhau.
//
// Dùng ĐÚNG dấu hiệu HireFlow như mọi bề mặt khác. Bản thiết kế bàn giao vẽ header này bằng một
// icon "layers" chung chung — icon đó xuất hiện ĐÚNG MỘT LẦN trong cả bundle và không thuộc bộ
// nhận diện nào, trong khi dấu hiệu HireFlow có mặt ở sidebar HR lẫn bản PWA điện thoại. Tức phần
// công khai bị bỏ sót lúc đổi thương hiệu, không phải chủ ý tách thương hiệu.
//
// `href` chỉ truyền ở /apply (ứng viên duyệt qua lại giữa danh sách và chi tiết). Ở /screening
// ứng viên vào thẳng bằng magic-link trong email, không có gì để duyệt → để dạng chữ, không link
// (bấm nhầm là mất form đang điền dở, mà token chỉ dùng được một lần).
export function PublicHeader({ href, tagline }: { href?: string; tagline: string }) {
  // Chỉ "HireFlow", KHÔNG kèm hậu tố: ngữ cảnh đã nằm ở tagline bên phải ("Nộp hồ sơ trực tuyến"
  // / "Bổ sung thông tin ứng tuyển"), thêm "· Tuyển dụng" là nói hai lần cùng một ý.
  const brand = <Logo size={24} />;

  return (
    <header className="border-b-2 border-divider bg-canvas">
      <div className="mx-auto flex max-w-[720px] items-center justify-between gap-3 px-4 py-3 sm:px-6">
        {href ? (
          <Link href={href} className="rounded focus-visible:outline-offset-4">
            {brand}
          </Link>
        ) : (
          brand
        )}
        <span className="text-right text-xs text-ink/65">{tagline}</span>
      </div>
    </header>
  );
}
