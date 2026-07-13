"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import type { ApplicationDetail, JobPosting } from "@ars/shared-types";
import { ParsedCVResult } from "@/components/ParsedCVResult";
import { ScoreBreakdown } from "@/components/ScoreBreakdown";
import { getApplication, getJob } from "@/lib/api";
import { statusBadgeClass, statusLabel, toBreakdown } from "@/lib/applications";

export default function ApplicationDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);

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

  return (
    <main className="mx-auto max-w-4xl space-y-6 p-8">
      <Link href="/applications" className="text-sm text-slate-500 hover:underline">
        ← Về danh sách ứng viên
      </Link>

      {appQuery.isLoading && <p className="text-sm text-slate-500">Đang tải chi tiết…</p>}
      {appQuery.isError && (
        <p className="text-sm text-red-600">
          Không tải được ứng viên #{params.id} (
          {String((appQuery.error as Error)?.message)}). Ứng viên có tồn tại không?
        </p>
      )}

      {app && (
        <>
          <header className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="mr-1 text-2xl font-bold">{app.applicant_email}</h1>
              <span
                className={`rounded px-2 py-0.5 text-sm font-medium ${statusBadgeClass(app.status)}`}
              >
                {statusLabel(app.status)}
              </span>
            </div>
            <p className="text-sm text-slate-500">
              {jobQuery.data ? (
                <>
                  Ứng tuyển: <span className="font-medium text-slate-700">{jobQuery.data.title}</span>{" "}
                  (JD #{app.job_id})
                </>
              ) : app.job_id != null ? (
                <>JD #{app.job_id}</>
              ) : (
                <>Chưa gắn JD</>
              )}
            </p>
          </header>

          {/* Lý do cần HR xem xét (PRD §11) — chỉ báo HÀNH ĐỘNG: CHỈ hiện khi còn chờ quyết
              (PENDING_REVIEW). Hồ sơ đã quyết chỉ xem trạng thái cuối, không nhắc "cần xem xét" (BUG B). */}
          {app.status === "PENDING_REVIEW" && app.escalation_reason?.trim() && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <p className="font-medium">Cần HR xem xét</p>
              <p className="mt-1 text-amber-800">{app.escalation_reason}</p>
            </div>
          )}

          {/* Điểm đối sánh + từng tiêu chí (tái dùng ở ReviewCard). Cờ "cần chú ý" chỉ hiện khi
              còn chờ quyết — hồ sơ đã quyết xem điểm sạch, không badge cờ (BUG B). */}
          <ScoreBreakdown breakdown={toBreakdown(app)} showFlags={app.status === "PENDING_REVIEW"} />

          {/* Ngữ cảnh JD: yêu cầu chính, để HR biết ứng viên được chấm dựa trên gì. */}
          {jobQuery.data && jobQuery.data.requirements.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-lg font-semibold">Yêu cầu JD</h2>
              <ul className="list-disc space-y-0.5 rounded-md border border-slate-200 bg-white px-4 py-3 pl-8 text-sm text-slate-700">
                {jobQuery.data.requirements.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </section>
          )}

          {/* Dữ liệu bóc tách (tái dùng ParsedCVResult; ẩn badge confidence — ScoreBreakdown đã lo) */}
          <ParsedCVResult
            parsed_data={app.parsed_data}
            confidence={app.confidence ?? 1}
            uncertainty_flags={app.uncertainty_flags.filter((f) => f === "parse_failed")}
            escalation_reason={app.escalation_reason}
            showConfidence={false}
          />
        </>
      )}
    </main>
  );
}
