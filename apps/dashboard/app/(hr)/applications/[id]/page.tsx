"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { ApplicationDetail, AuditEntry, JobPosting } from "@ars/shared-types";
import { AgentTrace } from "@/components/AgentTrace";
import { ParsedCVResult } from "@/components/ParsedCVResult";
import { ScoreBreakdown } from "@/components/ScoreBreakdown";
import { ScreenerAnswers } from "@/components/ScreenerAnswers";
import { SafeHtml } from "@/components/SafeHtml";
import { BackArrow, btn, Tag } from "@/components/ui";
import { downloadCv, getApplication, getApplicationAudit, getJob } from "@/lib/api";
import { statusLabel, statusTone, toBreakdown } from "@/lib/applications";

function initialsOf(email: string): string {
  const name = email.split("@")[0] ?? "";
  const parts = name.split(/[._-]+/).filter(Boolean);
  return ((parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2)) || "??").toUpperCase();
}

export default function ApplicationDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);

  // Tải CV gốc (slice 06) — stream qua backend, cần đăng nhập (require_hr).
  const cvDownload = useMutation({ mutationFn: () => downloadCv(id) });

  const appQuery = useQuery<ApplicationDetail>({
    queryKey: ["application", id],
    queryFn: () => getApplication(id),
    enabled: Number.isFinite(id),
  });
  const app = appQuery.data;

  const jobQuery = useQuery<JobPosting>({
    queryKey: ["job", app?.job_id],
    queryFn: () => getJob(app!.job_id!),
    enabled: app?.job_id != null,
  });

  // Nhật ký kiểm toán (PRD §16) — nguồn THẬT cho Agent trace.
  const auditQuery = useQuery<AuditEntry[]>({
    queryKey: ["application", id, "audit"],
    queryFn: () => getApplicationAudit(id),
    enabled: Number.isFinite(id),
  });

  return (
    <div className="mx-auto max-w-[1120px] px-4 pb-8 pt-5 sm:px-8">
      <Link href="/applications" className={btn("ghost", "mb-3 !pl-0")}>
        <BackArrow /> Về danh sách ứng viên
      </Link>

      {appQuery.isLoading && <p className="text-sm text-ink/50">Đang tải chi tiết…</p>}
      {appQuery.isError && (
        <p className="rounded-lg border-2 border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          Không tải được ứng viên #{params.id} ({String((appQuery.error as Error)?.message)}). Ứng
          viên có tồn tại không?
        </p>
      )}

      {app && (
        <>
          <div className="flex flex-wrap items-start gap-4">
            <span className="flex h-14 w-14 flex-none items-center justify-center rounded-xl bg-ink font-heading text-xl font-bold text-canvas">
              {initialsOf(app.applicant_email)}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-[26px] sm:text-[30px]">{app.applicant_email.split("@")[0]}</h1>
                <Tag tone={statusTone(app.status)}>{statusLabel(app.status)}</Tag>
              </div>
              <p className="mt-1 text-[13px] text-ink/55">
                {app.applicant_email}
                {jobQuery.data ? (
                  <>
                    {" · "}Ứng tuyển:{" "}
                    <span className="font-semibold text-ink">{jobQuery.data.title}</span>
                  </>
                ) : app.job_id != null ? (
                  <> · JD #{app.job_id}</>
                ) : (
                  <> · Chưa gắn JD</>
                )}
              </p>
            </div>

            {/* Tải CV gốc (slice 06): stream qua backend có kiểm đăng nhập — KHÔNG public URL. */}
            {app.has_cv && (
              <div className="flex flex-none flex-col items-end gap-1">
                <button
                  type="button"
                  onClick={() => cvDownload.mutate()}
                  disabled={cvDownload.isPending}
                  className={btn("secondary")}
                >
                  <svg
                    viewBox="0 0 24 24"
                    className="h-[15px] w-[15px]"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden
                  >
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="7 10 12 15 17 10" />
                    <line x1="12" x2="12" y1="15" y2="3" />
                  </svg>
                  {cvDownload.isPending ? "Đang tải…" : "Tải CV gốc"}
                </button>
                {cvDownload.isError && (
                  <span role="alert" className="text-xs text-red-600">
                    {String((cvDownload.error as Error)?.message) || "Không tải được CV."}
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Lý do cần HR xem xét (PRD §11) — chỉ báo HÀNH ĐỘNG: CHỈ hiện khi còn chờ quyết. */}
          {app.status === "PENDING_REVIEW" && app.escalation_reason?.trim() && (
            <div className="mt-4 rounded-xl border-2 border-accent bg-accent-100 px-4 py-3">
              <p className="flex items-center gap-2 font-heading text-[13px] font-bold text-accent-800">
                <svg
                  viewBox="0 0 24 24"
                  className="h-4 w-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2.2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
                  <path d="M12 9v4" />
                  <path d="M12 17h.01" />
                </svg>
                Cần HR xem xét
              </p>
              <p className="mt-1.5 text-[13px] text-accent-800">{app.escalation_reason}</p>
            </div>
          )}

          <div className="mt-5 grid items-start gap-6 lg:grid-cols-[1.55fr_1fr]">
            {/* TRÁI: trace + điểm + câu trả lời sàng lọc */}
            <div className="flex min-w-0 flex-col gap-5">
              <AgentTrace
                app={app}
                entries={auditQuery.data}
                isLoading={auditQuery.isLoading}
                isError={auditQuery.isError}
              />

              {/* Cờ "cần chú ý" chỉ hiện khi còn chờ quyết — hồ sơ đã quyết xem điểm sạch. */}
              <ScoreBreakdown
                breakdown={toBreakdown(app)}
                showFlags={app.status === "PENDING_REVIEW"}
              />

              <ScreenerAnswers answers={app.screener_answers} />
            </div>

            {/* PHẢI: dữ liệu bóc tách + yêu cầu JD */}
            <div className="flex min-w-0 flex-col gap-4">
              <div className="rounded-xl border-2 border-divider bg-canvas p-4">
                <ParsedCVResult
                  parsed_data={app.parsed_data}
                  confidence={app.confidence ?? 1}
                  uncertainty_flags={app.uncertainty_flags.filter((f) => f === "parse_failed")}
                  escalation_reason={app.escalation_reason}
                  showConfidence={false}
                />
              </div>

              {/* Ngữ cảnh JD: HR biết ứng viên được chấm dựa trên gì. JD-1: yêu cầu là văn bản
                  định dạng → render qua SafeHtml (sanitize + khôi phục bullet). */}
              {jobQuery.data && jobQuery.data.requirements.trim() && (
                <section className="rounded-xl border-2 border-divider bg-canvas p-4">
                  <h2 className="mb-2.5 text-xs font-semibold uppercase tracking-[0.08em] text-ink/50">
                    Yêu cầu JD
                  </h2>
                  <SafeHtml
                    html={jobQuery.data.requirements}
                    className="rte-content text-[13px] leading-relaxed text-ink/80"
                  />
                </section>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
