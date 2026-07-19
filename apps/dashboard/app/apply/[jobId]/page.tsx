"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { PublicJob } from "@ars/shared-types";
import { CVFilePicker } from "@/components/CVFilePicker";
import { SafeHtml } from "@/components/SafeHtml";
import { getPublicJob, submitApplication } from "@/lib/api";
import { employmentTypeLabel, formatSalary, levelLabel } from "@/lib/jobs";

function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
}

export default function ApplyDetailPage({ params }: { params: { jobId: string } }) {
  const id = Number(params.jobId);

  const jobQuery = useQuery<PublicJob>({
    queryKey: ["public-job", id],
    queryFn: () => getPublicJob(id),
    enabled: Number.isFinite(id),
    retry: false, // JD đóng/không tồn tại → 404, đừng retry.
  });

  const [email, setEmail] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const mutation = useMutation({
    mutationFn: () => submitApplication(id, email.trim(), file as File),
  });

  const canSubmit = isValidEmail(email) && file !== null && !mutation.isPending;

  // ── Màn xác nhận (sau khi nộp thành công) — KHÔNG hiện điểm/trạng thái ──
  if (mutation.isSuccess) {
    return (
      <main className="mx-auto max-w-2xl p-6 sm:p-8">
        <div className="rounded-md border border-green-200 bg-green-50 px-6 py-10 text-center">
          <p className="text-lg font-semibold text-green-800">Cảm ơn bạn đã ứng tuyển! 🎉</p>
          <p className="mx-auto mt-2 max-w-md text-sm text-green-700">
            Hồ sơ của bạn đã được gửi thành công. Chúng tôi sẽ xem xét và liên hệ với bạn qua email.
          </p>
          <Link
            href="/apply"
            className="mt-6 inline-block rounded-md border border-green-300 bg-white px-4 py-2 text-sm font-medium text-green-800 hover:bg-green-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-green-500"
          >
            ← Xem vị trí khác
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl space-y-6 p-6 sm:p-8">
      <Link href="/apply" className="text-sm text-slate-500 hover:underline">
        ← Tất cả vị trí
      </Link>

      {jobQuery.isLoading && <p className="text-sm text-slate-500">Đang tải vị trí…</p>}
      {jobQuery.isError && (
        <div className="rounded-md border border-slate-200 bg-white px-6 py-10 text-center">
          <p className="text-sm font-medium text-slate-700">
            Vị trí này không còn mở hoặc không tồn tại.
          </p>
          <Link
            href="/apply"
            className="mt-4 inline-block text-sm font-medium text-slate-700 underline hover:text-slate-900"
          >
            Xem các vị trí đang mở
          </Link>
        </div>
      )}

      {jobQuery.data && (
        <>
          <header className="space-y-3">
            <h1 className="text-2xl font-bold text-slate-900">{jobQuery.data.title}</h1>

            {/* Meta hướng-ứng-viên (JD-1): cấp bậc · loại việc · lương */}
            {(levelLabel(jobQuery.data.level) ||
              employmentTypeLabel(jobQuery.data.employment_type) ||
              formatSalary(jobQuery.data.salary)) && (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                {levelLabel(jobQuery.data.level) && (
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-slate-700">
                    {levelLabel(jobQuery.data.level)}
                  </span>
                )}
                {employmentTypeLabel(jobQuery.data.employment_type) && (
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-slate-700">
                    {employmentTypeLabel(jobQuery.data.employment_type)}
                  </span>
                )}
                {formatSalary(jobQuery.data.salary) && (
                  <span className="rounded-full bg-green-100 px-3 py-1 font-medium text-green-800">
                    {formatSalary(jobQuery.data.salary)}
                  </span>
                )}
              </div>
            )}

            {/* Mô tả / Yêu cầu / Quyền lợi: văn bản định dạng → SANITIZE (DOMPurify) trước khi render */}
            {jobQuery.data.description.trim() && (
              <SafeHtml
                html={jobQuery.data.description}
                className="rte-content text-sm text-slate-600"
              />
            )}
            {jobQuery.data.requirements.trim() && (
              <div className="pt-2">
                <p className="text-sm font-medium text-slate-700">Yêu cầu</p>
                <SafeHtml
                  html={jobQuery.data.requirements}
                  className="rte-content mt-1 text-sm text-slate-600"
                />
              </div>
            )}
            {jobQuery.data.benefits.trim() && (
              <div className="pt-2">
                <p className="text-sm font-medium text-slate-700">Quyền lợi</p>
                <SafeHtml
                  html={jobQuery.data.benefits}
                  className="rte-content mt-1 text-sm text-slate-600"
                />
              </div>
            )}
          </header>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (canSubmit) mutation.mutate();
            }}
            className="space-y-4 border-t border-slate-200 pt-6"
          >
            <h2 className="text-lg font-semibold text-slate-900">Nộp hồ sơ</h2>

            <div className="space-y-1.5">
              <label htmlFor="email" className="block text-sm font-medium text-slate-700">
                Email <span className="text-red-500">*</span>
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="ban@example.com"
                autoComplete="email"
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
              />
              <p className="text-xs text-slate-400">Chúng tôi sẽ liên hệ kết quả qua email này.</p>
            </div>

            <div className="space-y-1.5">
              <span className="block text-sm font-medium text-slate-700">
                CV <span className="text-red-500">*</span>
              </span>
              <CVFilePicker onFile={setFile} disabled={mutation.isPending} />
            </div>

            {mutation.isError && (
              <p className="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
                {String((mutation.error as Error)?.message) || "Không gửi được hồ sơ. Vui lòng thử lại."}
              </p>
            )}

            <button
              type="submit"
              disabled={!canSubmit}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 disabled:opacity-50"
            >
              {mutation.isPending ? "Đang gửi…" : "Nộp hồ sơ"}
            </button>
          </form>
        </>
      )}
    </main>
  );
}
