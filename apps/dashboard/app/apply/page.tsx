"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import type { PublicJob } from "@ars/shared-types";
import { getOpenJobs } from "@/lib/api";
import { htmlToPlainText } from "@/lib/jobs";

export default function ApplyListPage() {
  const { data, isLoading, isError } = useQuery<PublicJob[]>({
    queryKey: ["public-jobs"],
    queryFn: getOpenJobs,
  });

  const jobs = data ?? [];

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-6 sm:p-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold text-slate-900">Vị trí đang tuyển</h1>
        <p className="text-sm text-slate-500">
          Chọn một vị trí để xem chi tiết và nộp hồ sơ. Chỉ cần email và CV (PDF/DOCX) — không cần
          tạo tài khoản.
        </p>
      </header>

      {isLoading && <p className="text-sm text-slate-500">Đang tải vị trí…</p>}
      {isError && (
        <p className="text-sm text-red-600">
          Không tải được danh sách vị trí. Vui lòng thử lại sau.
        </p>
      )}
      {data && jobs.length === 0 && (
        <div
          role="status"
          className="rounded-md border border-dashed border-slate-300 bg-white px-6 py-12 text-center"
        >
          <p className="text-sm font-medium text-slate-700">Hiện chưa có vị trí nào đang mở.</p>
          <p className="mt-1 text-sm text-slate-500">Vui lòng quay lại sau nhé.</p>
        </div>
      )}

      <ul className="space-y-3">
        {jobs.map((job) => (
          <li key={job.id}>
            <Link
              href={`/apply/${job.id}`}
              className="block rounded-md border border-slate-200 bg-white px-5 py-4 transition-colors hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
            >
              <p className="font-medium text-slate-900">{job.title}</p>
              {htmlToPlainText(job.description) && (
                <p className="mt-1 line-clamp-2 text-sm text-slate-500">
                  {htmlToPlainText(job.description)}
                </p>
              )}
              <span className="mt-2 inline-block text-sm font-medium text-slate-700">
                Xem &amp; nộp hồ sơ →
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
