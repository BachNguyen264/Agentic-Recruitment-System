"use client";

import { useState } from "react";
import type { ApplicationDetail, Recommendation } from "@ars/shared-types";
import { ScoreBreakdown } from "@/components/ScoreBreakdown";
import { toBreakdown } from "@/lib/applications";

// THUẦN presentational: nhận callback onApprove/onReject, KHÔNG tự fetch/mutate (page lo useMutation).
// `note` là state form cục bộ (thu ghi chú rồi đẩy lên callback) — không phá tính presentational.
interface ReviewCardProps {
  app: ApplicationDetail;
  onApprove: (note: string) => void;
  onReject: (note: string) => void;
  submitting?: boolean;
}

const RECO: Record<Recommendation, { label: string; cls: string }> = {
  invite: { label: "Đề xuất: Mời", cls: "bg-green-100 text-green-800" },
  consider_reject: { label: "Đề xuất: Cân nhắc từ chối", cls: "bg-red-100 text-red-800" },
  review_carefully: { label: "Đề xuất: Xem kỹ", cls: "bg-amber-100 text-amber-800" },
};

export function ReviewCard({ app, onApprove, onReject, submitting = false }: ReviewCardProps) {
  const [note, setNote] = useState("");
  const reco = RECO[app.recommendation];
  const skills = app.parsed_data?.skills ?? [];
  const topExp = app.parsed_data?.experiences?.[0];

  return (
    <article className="space-y-4 rounded-lg border border-slate-200 bg-white p-5">
      {/* Header: tên + email + đề xuất hệ thống */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-lg font-semibold text-slate-900">
            {app.parsed_data?.full_name?.trim() || app.applicant_email}
          </h3>
          <p className="text-xs text-slate-400">
            {app.applicant_email} · JD #{app.job_id ?? "—"}
          </p>
        </div>
        {reco && (
          <span className={`shrink-0 rounded px-2 py-0.5 text-sm font-medium ${reco.cls}`}>
            {reco.label}
          </span>
        )}
      </div>

      {/* Tóm tắt ứng viên: kỹ năng chính + kinh nghiệm nổi bật */}
      {(skills.length > 0 || topExp) && (
        <div className="space-y-1.5 text-sm">
          {skills.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {skills.slice(0, 8).map((s, i) => (
                <span key={`${s}-${i}`} className="rounded bg-slate-100 px-2 py-0.5 text-slate-700">
                  {s}
                </span>
              ))}
            </div>
          )}
          {topExp && (
            <p className="text-slate-600">
              {topExp.title?.trim() || "—"}
              {topExp.company?.trim() ? ` · ${topExp.company}` : ""}
              {topExp.duration?.trim() ? ` (${topExp.duration})` : ""}
            </p>
          )}
        </div>
      )}

      {/* Lý do vào review (escalation) — nổi bật */}
      {app.escalation_reason?.trim() && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
          <span className="font-medium">Vì sao vào review: </span>
          {app.escalation_reason}
        </div>
      )}

      {/* Điểm từng tiêu chí (tái dùng ScoreBreakdown từ 03a) */}
      <ScoreBreakdown breakdown={toBreakdown(app)} />

      {/* Ghi chú + hành động */}
      <div className="space-y-2 border-t border-slate-100 pt-3">
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Ghi chú (tùy chọn) — lý do duyệt/từ chối…"
          rows={2}
          disabled={submitting}
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 disabled:bg-slate-50"
        />
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={submitting}
            onClick={() => onApprove(note)}
            className="rounded-md bg-green-700 px-4 py-2 text-sm font-medium text-white hover:bg-green-800 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-green-600"
          >
            {submitting ? "Đang xử lý…" : "Duyệt → mời phỏng vấn"}
          </button>
          <button
            type="button"
            disabled={submitting}
            onClick={() => onReject(note)}
            className="rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
          >
            Từ chối
          </button>
        </div>
      </div>
    </article>
  );
}
