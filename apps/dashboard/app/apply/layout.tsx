import Link from "next/link";

// Layout CÔNG KHAI cho ứng viên — chrome riêng, TÁCH khỏi nav HR (không link /jobs /applications /review).
export default function ApplyLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-4">
          <Link href="/apply" className="text-base font-semibold tracking-tight text-slate-900">
            Tuyển dụng
          </Link>
          <span className="text-xs text-slate-400">Nộp hồ sơ trực tuyến</span>
        </div>
      </header>
      {children}
    </div>
  );
}
