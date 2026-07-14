// Layout CÔNG KHAI cho ứng viên trả lời sàng lọc (magic-link) — chrome riêng, TÁCH khỏi nav HR.
// Ứng viên vào qua link email, không duyệt trang khác → brand để dạng text (không link).
export default function ScreeningLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-4">
          <span className="text-base font-semibold tracking-tight text-slate-900">Tuyển dụng</span>
          <span className="text-xs text-slate-400">Bổ sung thông tin ứng tuyển</span>
        </div>
      </header>
      {children}
    </div>
  );
}
