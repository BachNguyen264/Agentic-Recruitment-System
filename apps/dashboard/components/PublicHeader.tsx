import Link from "next/link";

// Thanh đầu trang CÔNG KHAI — dùng chung cho /apply và /screening để hai bề mặt ứng viên không
// trôi dạt khác nhau. Thương hiệu ở đây là "Tuyển dụng" (mặt tiền của công ty), KHÔNG phải
// "HireFlow" — HireFlow là tên công cụ nội bộ của HR, ứng viên không cần biết.
//
// `href` chỉ truyền ở /apply (ứng viên duyệt qua lại giữa danh sách và chi tiết). Ở /screening
// ứng viên vào thẳng bằng magic-link trong email, không có gì để duyệt → để dạng chữ, không link.
export function PublicHeader({ href, tagline }: { href?: string; tagline: string }) {
  const brand = (
    <span className="flex items-center gap-2.5">
      <span
        aria-hidden
        className="flex h-5 w-5 flex-none items-center justify-center rounded bg-accent"
      >
        <svg
          viewBox="0 0 24 24"
          className="h-3 w-3"
          fill="none"
          stroke="#fff"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M12 2 2 7l10 5 10-5-10-5Z" />
          <path d="m2 17 10 5 10-5" />
          <path d="m2 12 10 5 10-5" />
        </svg>
      </span>
      <span className="font-heading text-[16px] font-bold tracking-tight">Tuyển dụng</span>
    </span>
  );

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
        <span className="text-right text-xs text-ink/45">{tagline}</span>
      </div>
    </header>
  );
}
