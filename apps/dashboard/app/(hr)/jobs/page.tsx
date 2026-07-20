"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { JobPosting } from "@ars/shared-types";
import { btn, EmptyState, PageHeader, Tag, Toggle } from "@/components/ui";
import { archiveJob, getJobs, restoreJob, setGate, setJobStatus } from "@/lib/api";
import { formatSalary, isValidRubric, jobStatusLabel } from "@/lib/jobs";

function fmtDate(iso: string): string {
  return iso.slice(0, 10); // YYYY-MM-DD (xác định, tránh lệch hydrate do timezone)
}

// Tông thẻ trạng thái JD — mở (xanh) · nháp (hổ phách, còn việc phải làm) · đóng/lưu-trữ (trung tính).
function statusTone(status: string): "ok" | "warn" | "neutral" {
  if (status === "OPEN") return "ok";
  if (status === "DRAFT") return "warn";
  return "neutral";
}

export default function JobsPage() {
  const qc = useQueryClient();
  const [showArchived, setShowArchived] = useState(false); // JD-4: xem JD đã lưu trữ
  const [busyId, setBusyId] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { data, isLoading, isError, error } = useQuery<JobPosting[]>({
    queryKey: ["jobs", showArchived ? "archived" : "active"],
    queryFn: () => getJobs(showArchived),
  });
  // Đếm cho nhãn hai tab — luôn lấy cả hai rổ để số không nhảy khi đổi tab.
  const { data: activeJobs } = useQuery<JobPosting[]>({
    queryKey: ["jobs", "active"],
    queryFn: () => getJobs(false),
  });
  const { data: archivedJobs } = useQuery<JobPosting[]>({
    queryKey: ["jobs", "archived"],
    queryFn: () => getJobs(true),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["jobs"] });
  // Tuỳ chọn dùng chung cho các mutation dạng (id → gọi API → refetch).
  const byId = (failMsg: string) => ({
    onMutate: (id: number) => {
      setBusyId(id);
      setErrorMsg(null);
    },
    onSuccess: invalidate,
    onError: (err: unknown) => setErrorMsg(String((err as Error)?.message) || failMsg),
    onSettled: () => setBusyId(null),
  });

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: "OPEN" | "CLOSED" }) =>
      setJobStatus(id, status),
    onMutate: ({ id }) => {
      setBusyId(id);
      setErrorMsg(null);
    },
    onSuccess: invalidate,
    // MỞ khi chưa rubric → backend 400 (message rõ từ setJobStatus).
    onError: (err) => setErrorMsg(String((err as Error)?.message) || "Lỗi khi đổi trạng thái JD."),
    onSettled: () => setBusyId(null),
  });
  const gateMutation = useMutation({
    mutationFn: ({
      id,
      patch,
    }: {
      id: number;
      patch: { auto_reject?: boolean; auto_invite?: boolean };
    }) => setGate(id, patch),
    onMutate: ({ id }) => {
      setBusyId(id);
      setErrorMsg(null);
    },
    onSuccess: invalidate,
    onError: (err) => setErrorMsg(String((err as Error)?.message) || "Lỗi khi đổi gate."),
    onSettled: () => setBusyId(null),
  });
  const archiveMutation = useMutation({
    mutationFn: archiveJob,
    ...byId("Lỗi khi lưu trữ JD."),
  });
  const restoreMutation = useMutation({
    mutationFn: restoreJob,
    ...byId("Lỗi khi khôi phục JD."),
  });

  const jobs = data ?? [];

  return (
    <div className="mx-auto max-w-[1000px] px-4 pb-8 pt-6 sm:px-8">
      <PageHeader
        eyebrow="Quản lý"
        title="Tin tuyển dụng"
        description="Luồng 2 bước: soạn tin (bước 1) → cấu hình rubric + câu hỏi (bước 2) → Mở JD. Gate tự động (PRD §9) bật/tắt ngay trên từng JD. JD nháp/đóng/lưu-trữ không hiện ở cổng ứng tuyển."
        actions={
          <Link href="/jobs/new" className={btn("primary")}>
            <svg
              viewBox="0 0 24 24"
              className="h-[15px] w-[15px]"
              fill="none"
              stroke="currentColor"
              strokeWidth={2.2}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M5 12h14" />
              <path d="M12 5v14" />
            </svg>
            Tạo JD mới
          </Link>
        }
      />

      {/* JD-4: bộ lọc Đang hoạt động / Đã lưu trữ */}
      <div className="flex flex-wrap gap-2">
        {[
          { archived: false, label: "Đang hoạt động", n: activeJobs?.length },
          { archived: true, label: "Đã lưu trữ", n: archivedJobs?.length },
        ].map((t) => {
          const active = showArchived === t.archived;
          return (
            <button
              key={t.label}
              type="button"
              onClick={() => setShowArchived(t.archived)}
              aria-pressed={active}
              className={`rounded-lg border-2 px-3 py-1.5 text-[13px] font-semibold transition-colors ${
                active
                  ? "border-accent bg-accent text-white"
                  : "border-divider text-ink/70 hover:bg-ink/[0.06]"
              }`}
            >
              {t.label}
              {t.n != null && (
                <span className={active ? "text-white/70" : "text-ink/40"}> ({t.n})</span>
              )}
            </button>
          );
        })}
      </div>

      {errorMsg && (
        <p
          role="alert"
          className="mt-4 rounded-lg border-2 border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700"
        >
          {errorMsg}
        </p>
      )}

      {isLoading && <p className="mt-4 text-sm text-ink/50">Đang tải danh sách JD…</p>}
      {isError && (
        <p className="mt-4 rounded-lg border-2 border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          Không tải được danh sách JD ({String((error as Error)?.message)}). Backend đã chạy ở :8000
          chưa?
        </p>
      )}

      <div className="mt-4 flex flex-col gap-3">
        {data && jobs.length === 0 && (
          <EmptyState>
            {showArchived
              ? "Chưa có JD nào được lưu trữ."
              : "Chưa có JD nào — bấm “Tạo JD mới” để đăng tin đầu tiên."}
          </EmptyState>
        )}

        {jobs.map((job) => {
          const rubricOk = isValidRubric(job.rubric);
          const isOpen = job.status === "OPEN";
          const isArchived = job.status === "ARCHIVED";
          const busy = busyId === job.id;
          const salary = formatSalary(job.salary);

          return (
            <article key={job.id} className="rounded-xl border-2 border-divider bg-canvas p-4">
              <div className="flex flex-col gap-4 sm:flex-row">
                <div className="flex min-w-0 flex-1 flex-col">
                  <div className="flex flex-wrap items-center gap-2.5">
                    <h3 className="text-[18px]">
                      <Link href={`/jobs/${job.id}/edit`} className="hover:underline">
                        {job.title}
                      </Link>
                    </h3>
                    <Tag tone={statusTone(job.status)}>{jobStatusLabel(job.status)}</Tag>
                  </div>
                  <p className="mt-1.5 text-[13px] text-ink/55">
                    JD #{job.id} · {job.rubric.length} tiêu chí rubric · tạo {fmtDate(job.created_at)}
                  </p>

                  <div className="mt-2.5 flex flex-wrap gap-2">
                    {salary && <Tag tone="neutral">{salary}</Tag>}
                    {!isArchived && !rubricOk && (
                      <Tag tone="accent" className="border border-accent">
                        Chưa cấu hình rubric
                      </Tag>
                    )}
                    {!isArchived && job.embedding_ref === null && (
                      <Tag tone="outline">Chưa embed</Tag>
                    )}
                  </div>

                  {!isArchived && (
                    <div className="mt-auto flex flex-wrap gap-2 pt-4">
                      <Link href={`/jobs/${job.id}/screening`} className={btn("secondary")}>
                        Cấu hình
                      </Link>
                      <Link href={`/jobs/${job.id}/edit`} className={btn("secondary")}>
                        Sửa
                      </Link>
                      <button
                        type="button"
                        onClick={() =>
                          statusMutation.mutate({ id: job.id, status: isOpen ? "CLOSED" : "OPEN" })
                        }
                        disabled={busy || (!isOpen && !rubricOk)}
                        title={
                          !isOpen && !rubricOk
                            ? "Cần cấu hình rubric trước khi mở (bấm Cấu hình)"
                            : undefined
                        }
                        className={btn("secondary")}
                      >
                        {busy ? "Đang lưu…" : isOpen ? "Đóng" : "Mở JD"}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          if (
                            window.confirm(
                              "Lưu trữ JD này? Nó sẽ ẩn khỏi danh sách và cổng ứng tuyển. " +
                                "Hồ sơ ứng viên và nhật ký kiểm toán được GIỮ NGUYÊN, có thể Khôi phục sau.",
                            )
                          ) {
                            archiveMutation.mutate(job.id);
                          }
                        }}
                        disabled={busy}
                        className={btn("ghost")}
                      >
                        Lưu trữ
                      </button>
                    </div>
                  )}
                </div>

                {/* Gate tự động (PRD §9) — cột phải, chỉ cho JD chưa lưu trữ */}
                {!isArchived ? (
                  <div className="flex flex-none flex-col gap-3.5 border-t-2 border-divider pt-4 sm:w-[212px] sm:border-l-2 sm:border-t-0 sm:pl-4 sm:pt-0">
                    <span className="text-xs font-semibold uppercase tracking-[0.08em] text-ink/45">
                      Gate tự động
                    </span>
                    <Toggle
                      checked={job.gate_config.auto_reject}
                      disabled={busy}
                      label="Auto-từ-chối"
                      onChange={(v) => gateMutation.mutate({ id: job.id, patch: { auto_reject: v } })}
                    />
                    <Toggle
                      checked={job.gate_config.auto_invite}
                      disabled={busy}
                      label="Auto-mời"
                      onChange={(v) => gateMutation.mutate({ id: job.id, patch: { auto_invite: v } })}
                    />
                  </div>
                ) : (
                  <div className="flex flex-none items-start">
                    <button
                      type="button"
                      onClick={() => restoreMutation.mutate(job.id)}
                      disabled={busy}
                      className={btn("secondary")}
                    >
                      {busy ? "Đang khôi phục…" : "Khôi phục"}
                    </button>
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
