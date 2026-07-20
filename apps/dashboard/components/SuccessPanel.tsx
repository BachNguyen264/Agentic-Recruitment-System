// Panel xác nhận cho ứng viên — dùng ở CẢ hai đường: nộp CV xong (/apply) và gửi câu trả lời
// sàng lọc xong (/screening). Cùng một khoảnh khắc trong trải nghiệm nên phải trông giống nhau.
//
// TUYỆT ĐỐI không hiện điểm/trạng thái/kết quả đối sánh: ứng viên là khách, chỉ HR thấy những thứ
// đó (PRD §5 — "fire and forget"). Ở đây chỉ xác nhận đã nhận và nói rõ bước tiếp theo là email.
export function SuccessPanel({
  title,
  children,
  action,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div
      role="status"
      className="rounded-xl border-2 border-ink bg-surface px-6 py-8 text-center sm:py-10"
    >
      <span
        aria-hidden
        className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-ink text-canvas"
      >
        <svg
          viewBox="0 0 24 24"
          className="h-6 w-6"
          fill="none"
          stroke="currentColor"
          strokeWidth={2.4}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M20 6 9 17l-5-5" />
        </svg>
      </span>
      <h2 className="mt-4 text-[22px] sm:text-[24px]">{title}</h2>
      <p className="mx-auto mt-2 max-w-[44ch] text-[14px] leading-relaxed text-ink/65">
        {children}
      </p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
