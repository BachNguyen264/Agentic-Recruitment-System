import type { ScoreBreakdownData } from "@ars/shared-types";

// THUẦN presentational: nhận prop, KHÔNG tự fetch — tái dùng ở ReviewCard (lát human_review sau).
// Chỉ hiển thị điểm rubric (điểm CHÍNH) + tín hiệu phụ; KHÔNG chứa nút duyệt/từ chối (mutation là lát sau).
interface ScoreBreakdownProps {
  breakdown: ScoreBreakdownData;
  // Cờ "cần chú ý" (score_signal_mismatch/weak_match/near_threshold) là chỉ báo HÀNH ĐỘNG cho HR:
  // chỉ hiện khi hồ sơ còn chờ quyết. Mặc định true → ReviewCard (/review, luôn PENDING_REVIEW) không đổi.
  showFlags?: boolean;
}

function confidenceStyle(c: number): { label: string; cls: string } {
  if (c >= 0.8) return { label: "Cao", cls: "bg-green-100 text-green-800" };
  if (c >= 0.5) return { label: "Trung bình", cls: "bg-amber-100 text-amber-800" };
  return { label: "Thấp", cls: "bg-red-100 text-red-800" };
}

function pct(weight: number): string {
  return `${Math.round(weight * 100)}%`;
}

export function ScoreBreakdown({ breakdown, showFlags = true }: ScoreBreakdownProps) {
  const { overall_score, criteria, semantic_similarity, confidence, uncertainty_flags, summary } =
    breakdown;
  const conf = confidence != null ? confidenceStyle(confidence) : null;
  const failed = uncertainty_flags.includes("rank_failed");

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-1 text-lg font-semibold">Điểm đối sánh CV–JD</h2>
        {conf && (
          <span className={`rounded px-2 py-0.5 text-sm font-medium ${conf.cls}`}>
            Tự tin: {conf.label} · {confidence!.toFixed(2)}
          </span>
        )}
        {showFlags &&
          uncertainty_flags.map((flag) => (
            <span
              key={flag}
              className="rounded bg-amber-100 px-2 py-0.5 text-sm font-medium text-amber-800"
            >
              {flag}
            </span>
          ))}
      </div>

      {failed ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <p className="font-medium">Chưa chấm được điểm</p>
          {/* Câu nhắc "vào hàng chờ HR" là chỉ báo HÀNH ĐỘNG — chỉ khi còn chờ quyết (showFlags).
              Hồ sơ đã quyết chỉ nêu SỰ THẬT "chấm không thành công", không nhắc còn trong hàng đợi (BUG B). */}
          <p className="mt-1 text-red-700">
            {showFlags
              ? "Ranker gặp lỗi khi chấm — ca này vào hàng chờ HR xem xét."
              : "Ranker gặp lỗi khi chấm — hồ sơ không chấm được điểm."}
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {/* Điểm tổng nổi bật */}
          <div className="rounded-md border border-slate-200 bg-white px-4 py-3">
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold text-slate-900">
                {overall_score != null ? overall_score : "—"}
              </span>
              <span className="text-sm text-slate-500">/ 100 (điểm tổng theo rubric)</span>
            </div>
            {summary?.trim() && (
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{summary}</p>
            )}
          </div>

          {/* Từng tiêu chí: tên + trọng số + điểm + lý do */}
          {criteria.length > 0 ? (
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-slate-700">
                Chi tiết theo tiêu chí ({criteria.length})
              </h3>
              <ol className="space-y-2">
                {criteria.map((c, i) => (
                  <li
                    key={i}
                    className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                      <span className="font-medium text-slate-900">
                        {c.criterion?.trim() || "(Tiêu chí không tên)"}
                      </span>
                      <span className="text-slate-500">
                        trọng số {pct(c.weight)} ·{" "}
                        <span className="font-semibold text-slate-800">{c.score}/100</span>
                      </span>
                    </div>
                    {/* Thanh điểm (0..100) — chỉ trực quan, không đổi số liệu. */}
                    <div className="mt-1.5 h-1.5 w-full rounded-full bg-slate-100">
                      <div
                        className="h-1.5 rounded-full bg-slate-500"
                        style={{ width: `${Math.max(0, Math.min(100, c.score))}%` }}
                      />
                    </div>
                    {c.reasoning?.trim() && (
                      <p className="mt-2 text-slate-600">{c.reasoning}</p>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              Chưa có breakdown theo tiêu chí (ứng viên có thể đang chờ chấm điểm).
            </p>
          )}

          {/* Tín hiệu phụ: độ tương đồng ngữ nghĩa — KHÔNG tính vào điểm (PRD §7.2, plan §3.4). */}
          <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-2 text-sm">
            <span className="text-slate-700">
              Độ tương đồng ngữ nghĩa:{" "}
              <span className="font-medium text-slate-900">
                {semantic_similarity != null ? semantic_similarity.toFixed(4) : "—"}
              </span>
            </span>
            <span className="ml-1 text-slate-400">— tham khảo, không tính điểm</span>
          </div>
        </div>
      )}
    </section>
  );
}
