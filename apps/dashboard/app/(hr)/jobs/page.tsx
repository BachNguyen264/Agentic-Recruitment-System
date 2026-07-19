"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { JobPosting } from "@ars/shared-types";
import { getJobs, setGate, setJobStatus } from "@/lib/api";
import { isValidRubric, jobStatusBadgeClass, jobStatusLabel } from "@/lib/jobs";

function fmtDate(iso: string): string {
  return iso.slice(0, 10); // YYYY-MM-DD (xác định, tránh lệch hydrate do timezone)
}

export default function JobsPage() {
  const qc = useQueryClient();
  const [togglingId, setTogglingId] = useState<number | null>(null);
  const [gatingId, setGatingId] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { data, isLoading, isError, error } = useQuery<JobPosting[]>({
    queryKey: ["jobs"],
    queryFn: getJobs,
  });

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: "OPEN" | "CLOSED" }) =>
      setJobStatus(id, status),
    onMutate: ({ id }) => {
      setTogglingId(id);
      setErrorMsg(null);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
    // MỞ khi chưa rubric → backend 400 (message rõ từ setJobStatus).
    onError: (err) => setErrorMsg(String((err as Error)?.message) || "Lỗi khi đổi trạng thái JD."),
    onSettled: () => setTogglingId(null),
  });

  const gateMutation = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: { auto_reject?: boolean; auto_invite?: boolean } }) =>
      setGate(id, patch),
    onMutate: ({ id }) => {
      setGatingId(id);
      setErrorMsg(null);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
    onError: (err) => setErrorMsg(String((err as Error)?.message) || "Lỗi khi đổi gate."),
    onSettled: () => setGatingId(null),
  });

  const jobs = data ?? [];

  return (
    <main className="mx-auto max-w-4xl space-y-6 p-8">
      <header className="space-y-1">
        <Link href="/" className="text-sm text-slate-500 hover:underline">
          ← Về dashboard
        </Link>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-2xl font-bold">Tin tuyển dụng (JD)</h1>
          <Link
            href="/jobs/new"
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
          >
            + Tạo JD mới
          </Link>
        </div>
        <p className="text-sm text-slate-500">
          Quản lý JD: soạn tin (bước 1) → cấu hình rubric/câu hỏi (bước 2) → Mở JD. Gate tự động (PRD §9)
          bật/tắt ngay trên từng JD. JD nháp/đóng KHÔNG hiện ở trang ứng tuyển.
        </p>
      </header>

      {errorMsg && (
        <p className="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {errorMsg}
        </p>
      )}

      {isLoading && <p className="text-sm text-slate-500">Đang tải danh sách JD…</p>}
      {isError && (
        <p className="text-sm text-red-600">
          Không tải được danh sách JD ({String((error as Error)?.message)}). Backend đã chạy ở :8000
          chưa?
        </p>
      )}
      {data && jobs.length === 0 && (
        <div
          role="status"
          className="rounded-md border border-dashed border-slate-300 bg-white px-6 py-12 text-center"
        >
          <p className="text-sm font-medium text-slate-700">Chưa có JD nào.</p>
          <p className="mt-1 text-sm text-slate-500">Bấm “Tạo JD mới” để đăng tin đầu tiên.</p>
        </div>
      )}

      <ul className="space-y-2">
        {jobs.map((job) => {
          const rubricOk = isValidRubric(job.rubric);
          const isOpen = job.status === "OPEN";
          return (
            <li
              key={job.id}
              className="rounded-md border border-slate-200 bg-white px-4 py-3 transition-colors hover:border-slate-300"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <Link
                    href={`/jobs/${job.id}/edit`}
                    className="font-medium text-slate-900 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
                  >
                    {job.title}
                  </Link>
                  <p className="mt-0.5 text-xs text-slate-400">
                    JD #{job.id} · {job.rubric.length} tiêu chí rubric · tạo {fmtDate(job.created_at)}
                  </p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${jobStatusBadgeClass(job.status)}`}
                    >
                      {jobStatusLabel(job.status)}
                    </span>
                    {!rubricOk && (
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
                        Chưa cấu hình rubric
                      </span>
                    )}
                    {job.embedding_ref === null && (
                      <span className="rounded bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700">
                        Chưa embed
                      </span>
                    )}
                  </div>
                  {/* Gate tự động (PRD §9) — bật/tắt ngay trên JD (JD-2a) */}
                  <div className="mt-2 flex flex-wrap items-center gap-4">
                    <label className="flex items-center gap-1.5 text-xs text-slate-600">
                      <input
                        type="checkbox"
                        checked={job.gate_config.auto_reject}
                        disabled={gatingId === job.id}
                        onChange={(e) =>
                          gateMutation.mutate({ id: job.id, patch: { auto_reject: e.target.checked } })
                        }
                        className="h-3.5 w-3.5 rounded border-slate-300"
                      />
                      Gate auto-từ-chối
                    </label>
                    <label className="flex items-center gap-1.5 text-xs text-slate-600">
                      <input
                        type="checkbox"
                        checked={job.gate_config.auto_invite}
                        disabled={gatingId === job.id}
                        onChange={(e) =>
                          gateMutation.mutate({ id: job.id, patch: { auto_invite: e.target.checked } })
                        }
                        className="h-3.5 w-3.5 rounded border-slate-300"
                      />
                      Gate auto-mời
                    </label>
                  </div>
                </div>

                <div className="flex shrink-0 flex-col items-end gap-2">
                  <div className="flex items-center gap-2">
                    <Link
                      href={`/jobs/${job.id}/screening`}
                      className="rounded-md border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
                    >
                      Cấu hình
                    </Link>
                    <Link
                      href={`/jobs/${job.id}/edit`}
                      className="rounded-md border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
                    >
                      Sửa
                    </Link>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      statusMutation.mutate({ id: job.id, status: isOpen ? "CLOSED" : "OPEN" })
                    }
                    disabled={togglingId === job.id || (!isOpen && !rubricOk)}
                    aria-label={isOpen ? `Đóng JD ${job.title}` : `Mở JD ${job.title}`}
                    title={
                      !isOpen && !rubricOk
                        ? "Cần cấu hình rubric trước khi mở (bấm Cấu hình)"
                        : undefined
                    }
                    className="rounded-md border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 disabled:opacity-50"
                  >
                    {togglingId === job.id ? "Đang lưu…" : isOpen ? "Đóng" : "Mở JD"}
                  </button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </main>
  );
}
