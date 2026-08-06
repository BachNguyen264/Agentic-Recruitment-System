"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ApplicationDetail, JobPosting } from "@ars/shared-types";
import { AgentTrace } from "@/components/AgentTrace";
import { ParsedCVResult } from "@/components/ParsedCVResult";
import { ScoreBreakdown } from "@/components/ScoreBreakdown";
import { ScreenerAnswers } from "@/components/ScreenerAnswers";
import { SafeHtml } from "@/components/SafeHtml";
import { BackArrow, btn, Tag } from "@/components/ui";
import {
  cancelInterview,
  downloadCv,
  getApplication,
  getJob,
  resendBookingLink,
} from "@/lib/api";
import {
  applicationStatusLabel,
  applicationStatusTone,
  toBreakdown,
} from "@/lib/applications";
// Cùng hàm với trang chọn giờ của ứng viên: HR và ứng viên phải đọc ra CÙNG một mốc (lib/datetime).
import { formatVnDateTime } from "@/lib/datetime";

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

  // ── Quản lý lịch (SCH-3 §3.4) — hai nút này GHÉP LẠI chính là "đổi lịch". Cố ý không viết luồng
  // dời-lịch một-chạm: dời lịch thầm lặng thì ứng viên nhận một giờ mới do người khác chọn hộ, đúng
  // thứ mà cả tính năng pull-scheduling này sinh ra để bỏ.
  const queryClient = useQueryClient();
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const onScheduleChanged = (updated: ApplicationDetail) => {
    setConfirmingCancel(false);
    queryClient.setQueryData(["application", id], updated);
    void queryClient.invalidateQueries({ queryKey: ["applications"] });
  };
  const cancelSchedule = useMutation({
    mutationFn: () => cancelInterview(id),
    onSuccess: onScheduleChanged,
  });
  const resendLink = useMutation({
    mutationFn: () => resendBookingLink(id),
    onSuccess: onScheduleChanged,
  });
  const scheduleError = cancelSchedule.error ?? resendLink.error;
  const canResend = app?.status === "PENDING_REVIEW" || app?.status === "AWAITING_BOOKING";

  return (
    <div className="mx-auto max-w-[1120px] px-4 pb-8 pt-5 sm:px-8">
      <Link href="/applications" className={btn("ghost", "mb-3 !pl-0")}>
        <BackArrow /> Về danh sách ứng viên
      </Link>

      {appQuery.isLoading && <p className="text-sm text-ink/65">Đang tải chi tiết…</p>}
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
                <Tag tone={applicationStatusTone(app)}>{applicationStatusLabel(app)}</Tag>
              </div>
              <p className="mt-1 text-[13px] text-ink/65">
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

          {/* Lý do cần HR xem xét (PRD §11) — chỉ báo HÀNH ĐỘNG. Hiện ở BA trạng thái, mỗi cái một
              lý do: còn chờ quyết; đã hẹn nhưng có cờ (SCH-2: thư xác nhận gửi hỏng → HR gọi thủ
              công); và đang chờ chọn lịch sau khi ứng viên HUỶ (SCH-3 — họ tự chọn lại được, HR chỉ
              cần BIẾT). Bỏ vế nào thì cái cờ đó không có ai đọc. */}
          {(app.status === "PENDING_REVIEW" ||
            app.status === "INTERVIEW_SCHEDULED" ||
            app.status === "AWAITING_BOOKING") &&
            app.escalation_reason?.trim() && (
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
                {app.status === "INTERVIEW_SCHEDULED"
                  ? "Cần HR xử lý thủ công"
                  : app.status === "AWAITING_BOOKING"
                    ? "Ứng viên đã huỷ lịch"
                    : "Cần HR xem xét"}
              </p>
              <p className="mt-1.5 text-[13px] text-accent-800">{app.escalation_reason}</p>
            </div>
            )}

          {/* Lịch phỏng vấn ứng viên đã TỰ CHỌN (SCH-2 · PRD §10b) + nút huỷ (SCH-3). Đặt trên
              cùng vì với một hồ sơ đã hẹn thì đây là thông tin HR cần nhất. */}
          {app.interview && (
            <div className="mt-4 rounded-xl border-2 border-emerald-200 bg-emerald-50 px-4 py-3">
              <p className="flex items-center gap-2 font-heading text-[13px] font-bold text-emerald-900">
                <svg
                  viewBox="0 0 24 24"
                  className="h-4 w-4 shrink-0"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <path d="M8 2v4" />
                  <path d="M16 2v4" />
                  <rect width="18" height="18" x="3" y="4" rx="2" />
                  <path d="M3 10h18" />
                </svg>
                Lịch phỏng vấn đã chốt
              </p>
              <p className="mt-1.5 text-[13px] text-emerald-900">
                {formatVnDateTime(app.interview.start_at)} (giờ Việt Nam) — ứng viên tự chọn.
              </p>

              {/* Huỷ lịch (SCH-3). Hai bước: huỷ một buổi phỏng vấn đã hẹn là hành động ứng viên
                  sẽ nhận email ngay, không được để lỡ tay bấm trúng. */}
              {app.status === "INTERVIEW_SCHEDULED" &&
                (confirmingCancel ? (
                  <div className="mt-3">
                    <p className="text-[13px] text-emerald-900">
                      Huỷ lịch này? Khung giờ được nhả lại ngay, ứng viên nhận email báo huỷ, và hồ
                      sơ quay về hàng chờ HR. Muốn ứng viên chọn giờ khác thì bấm tiếp{" "}
                      <strong>Gửi lại link đặt lịch</strong>.
                    </p>
                    <div className="mt-2.5 flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={cancelSchedule.isPending}
                        onClick={() => cancelSchedule.mutate()}
                        className={btn("primary")}
                      >
                        {cancelSchedule.isPending ? "Đang huỷ…" : "Xác nhận huỷ lịch"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmingCancel(false)}
                        className={btn("secondary")}
                      >
                        Giữ lịch
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirmingCancel(true)}
                    className={btn("secondary", "mt-3")}
                  >
                    Huỷ lịch phỏng vấn
                  </button>
                ))}
            </div>
          )}

          {/* Hết khung giờ (SCH-3 · FR-BOOK-6): ứng viên ĐÃ bấm link nhưng lịch công ty trống rỗng.
              Nói rõ ai đang chặn — nhãn trạng thái đã đổi, nhưng HR còn cần biết PHẢI LÀM GÌ. */}
          {app.status === "AWAITING_BOOKING" && app.booking_no_slots && (
            <div className="mt-4 rounded-xl border-2 border-amber-300 bg-amber-50 px-4 py-3">
              <p className="font-heading text-[13px] font-bold text-amber-900">
                Hết khung giờ — ứng viên không đặt lịch được
              </p>
              <p className="mt-1.5 text-[13px] text-amber-900">
                Ứng viên đã mở liên kết nhưng không còn khung giờ trống nào trong cửa sổ đặt lịch.
                Đây là giới hạn lịch của công ty, không phải ứng viên chậm trễ — hãy nới{" "}
                <code>BOOKING_MAX_PER_DAY</code> / <code>BOOKING_WINDOW_DAYS</code>, hoặc huỷ bớt
                buổi không cần thiết. Liên kết vẫn còn hiệu lực: có giờ trống là ứng viên đặt được ngay.
              </p>
            </div>
          )}

          {/* Gửi lại link đặt lịch — nửa còn lại của "đổi lịch", và cũng là đường cứu khi thư mời
              đầu rơi vào thư rác hoặc liên kết đã hết hạn. */}
          {canResend && (
            <div className="mt-4 rounded-xl border-2 border-divider bg-surface px-4 py-3">
              <p className="font-heading text-[13px] font-bold">Gửi lại link đặt lịch</p>
              <p className="mt-1 text-[13px] text-ink/70">
                Phát một liên kết MỚI (hạn tính lại từ đầu) và gửi lại thư mời cho ứng viên. Liên
                kết cũ sẽ ngừng hoạt động.
              </p>
              <button
                type="button"
                disabled={resendLink.isPending}
                onClick={() => resendLink.mutate()}
                className={btn("secondary", "mt-2.5")}
              >
                {resendLink.isPending ? "Đang gửi…" : "Gửi lại link đặt lịch"}
              </button>
            </div>
          )}

          {scheduleError && (
            <p
              role="alert"
              className="mt-3 rounded-xl border-2 border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700"
            >
              {String((scheduleError as Error)?.message) || "Thao tác lịch không thành công."}
            </p>
          )}

          <div className="mt-5 grid items-start gap-6 lg:grid-cols-[1.55fr_1fr]">
            {/* TRÁI: trace + điểm + câu trả lời sàng lọc */}
            <div className="flex min-w-0 flex-col gap-5">
              <AgentTrace app={app} />

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
                  <h2 className="mb-2.5 text-xs font-semibold uppercase tracking-[0.08em] text-ink/65">
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
