import Link from "next/link";
import { ReviewNavLink } from "@/components/ReviewNavLink";
import { ServiceStatus } from "@/components/ServiceStatus";

export default function Home() {
  return (
    <main className="mx-auto max-w-4xl space-y-8 p-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">Autonomous Recruitment System</h1>
        <p className="text-sm text-slate-500">
          Dashboard HR. Pipeline cố định:{" "}
          <span className="font-mono">parser → ranker → screener → scheduler</span> + human_review.
          Nguồn chân lý: PRD.md.
        </p>
        <p className="flex flex-wrap gap-x-4 text-sm">
          <Link href="/jobs" className="text-slate-700 underline hover:text-slate-900">
            → Quản lý JD
          </Link>
          <Link href="/applications" className="text-slate-700 underline hover:text-slate-900">
            → Danh sách ứng viên
          </Link>
          <ReviewNavLink />
          <Link href="/cv-check" className="text-slate-700 underline hover:text-slate-900">
            → Kiểm tra bóc tách CV
          </Link>
        </p>
      </header>

      <ServiceStatus />

      <footer className="border-t border-slate-200 pt-4 text-xs text-slate-400">
        parser + ranker đã chạy thật; screener / scheduler / human_review còn stub (xem PRD.md).
      </footer>
    </main>
  );
}
