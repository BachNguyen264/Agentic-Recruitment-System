"use client";

import Link from "next/link";
import { useState } from "react";
import type { ApplicationDetail, Recommendation } from "@ars/shared-types";
import { ScreenerAnswers } from "@/components/ScreenerAnswers";
import { btn, inputClass, Tag, type TagTone } from "@/components/ui";

// THUẦN presentational: nhận callback onApprove/onReject, KHÔNG tự fetch/mutate (page lo useMutation).
// `note` là state form cục bộ (thu ghi chú rồi đẩy lên callback) — không phá tính presentational.
interface ReviewCardProps {
  app: ApplicationDetail;
  jobTitle?: string;
  onApprove: (note: string) => void;
  onReject: (note: string) => void;
  submitting?: boolean;
}

const RECO: Record<Recommendation, { label: string; tone: TagTone }> = {
  invite: { label: "Đề xuất: Mời", tone: "ok" },
  consider_reject: { label: "Đề xuất: Cân nhắc từ chối", tone: "danger" },
  review_carefully: { label: "Đề xuất: Xem kỹ", tone: "warn" },
};

export function ReviewCard({
  app,
  jobTitle,
  onApprove,
  onReject,
  submitting = false,
}: ReviewCardProps) {
  const [note, setNote] = useState("");
  const reco = RECO[app.recommendation];
  const skills = app.parsed_data?.skills ?? [];
  const topExp = app.parsed_data?.experiences?.[0];
  const criteria = app.score_breakdown?.criteria ?? [];
  const rankFailed = (app.uncertainty_flags ?? []).includes("rank_failed");

  return (
    <article className="rounded-xl border-2 border-divider bg-surface p-5">
      {/* Header: tên + email·vị trí + đề xuất hệ thống */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[19px]">
            {app.parsed_data?.full_name?.trim() || app.applicant_email.split("@")[0]}
          </h3>
          <p className="mt-0.5 text-[13px] text-ink/65">
            {app.applicant_email} · {jobTitle ?? (app.job_id ? `JD #${app.job_id}` : "Chưa gắn JD")}
          </p>
        </div>
        {reco && <Tag tone={reco.tone}>{reco.label}</Tag>}
      </div>

      {/* Tóm tắt ứng viên: kỹ năng chính + kinh nghiệm nổi bật */}
      {skills.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {skills.slice(0, 8).map((s, i) => (
            <Tag key={`${s}-${i}`} tone="neutral">
              {s}
            </Tag>
          ))}
        </div>
      )}
      {topExp && (
        <p className="mt-2 text-[13px] text-ink/70">
          {topExp.title?.trim() || "—"}
          {topExp.company?.trim() ? ` · ${topExp.company}` : ""}
          {topExp.duration?.trim() ? ` (${topExp.duration})` : ""}
        </p>
      )}

      {/* Lý do vào review (escalation) — nổi bật, đây là thứ HR cần đọc trước khi quyết */}
      {app.escalation_reason?.trim() && (
        <p className="mt-3 rounded-r-lg border-l-[3px] border-accent bg-accent-100 px-3 py-2.5 text-[13px] text-accent-800">
          <strong className="font-bold">Vì sao vào review: </strong>
          {app.escalation_reason}
        </p>
      )}

      {/* Câu trả lời sàng lọc (08b) — hiển thị khi ứng viên đã trả lời */}
      {app.screener_answers.length > 0 && (
        <div className="mt-3">
          <ScreenerAnswers answers={app.screener_answers} />
        </div>
      )}

      {/* Điểm rubric — bản GỌN cho hàng đợi (chi tiết đầy đủ ở trang chi tiết) */}
      {rankFailed ? (
        <p className="mt-3.5 rounded-lg border-2 border-accent bg-accent-100 px-4 py-3 text-[13px] font-semibold text-accent-800">
          Chưa chấm được điểm — Ranker gặp lỗi, ca này cần HR xem xét thủ công.
        </p>
      ) : (
        <>
          <div className="mt-3.5 flex items-baseline gap-2.5">
            <span className="font-heading text-[30px] font-bold leading-none">
              {app.score != null ? app.score : "—"}
            </span>
            <span className="text-[13px] text-ink/65">/ 100 điểm rubric</span>
          </div>
          {criteria.length > 0 && (
            <div className="mt-2.5 grid gap-x-4 gap-y-2 sm:grid-cols-2">
              {criteria.map((c, i) => (
                <div key={i}>
                  <div className="flex justify-between gap-2 text-xs">
                    <span className="truncate">{c.criterion?.trim() || "(không tên)"}</span>
                    <span className="flex-none font-bold">{c.score}</span>
                  </div>
                  <div className="mt-1 h-1 rounded-full bg-steel-200">
                    <div
                      className="h-1 rounded-full bg-ink"
                      style={{ width: `${Math.max(0, Math.min(100, c.score))}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Ghi chú + hành động. Nhãn nút NÊU RÕ hệ quả (đều gửi email thật cho ứng viên). */}
      <div className="mt-4 border-t border-divider pt-3.5">
        <label htmlFor={`note-${app.id}`} className="sr-only">
          Ghi chú quyết định
        </label>
        <textarea
          id={`note-${app.id}`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Ghi chú (tùy chọn) — lý do duyệt/từ chối…"
          rows={2}
          disabled={submitting}
          className={`${inputClass} bg-canvas`}
        />
        <div className="mt-2.5 flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            disabled={submitting}
            onClick={() => onApprove(note)}
            className={btn("primary")}
          >
            <svg
              viewBox="0 0 24 24"
              className="h-[15px] w-[15px]"
              fill="none"
              stroke="currentColor"
              strokeWidth={2.4}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M20 6 9 17l-5-5" />
            </svg>
            {submitting ? "Đang xử lý…" : "Duyệt → mời phỏng vấn"}
          </button>
          <button
            type="button"
            disabled={submitting}
            onClick={() => onReject(note)}
            className={btn("secondary")}
          >
            Từ chối → gửi thư từ chối
          </button>
          <Link href={`/applications/${app.id}`} className={btn("ghost", "ml-auto")}>
            Xem chi tiết đầy đủ →
          </Link>
        </div>
      </div>
    </article>
  );
}
