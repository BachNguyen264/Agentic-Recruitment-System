import type { ScoreBreakdownData } from "@ars/shared-types";
import { Tag } from "@/components/ui";

// THUẦN presentational: nhận prop, KHÔNG tự fetch — tái dùng ở ReviewCard.
// Chỉ hiển thị điểm rubric (điểm CHÍNH) + tín hiệu phụ; KHÔNG chứa nút duyệt/từ chối.
interface ScoreBreakdownProps {
  breakdown: ScoreBreakdownData;
  // Cờ "cần chú ý" (score_signal_mismatch/weak_match/near_threshold) là chỉ báo HÀNH ĐỘNG cho HR:
  // chỉ hiện khi hồ sơ còn chờ quyết. Mặc định true → ReviewCard (/review, luôn PENDING_REVIEW) không đổi.
  showFlags?: boolean;
  // Ẩn tiêu đề khi nhúng vào thẻ đã có tiêu đề riêng (ReviewCard).
  headless?: boolean;
}

function confidenceTone(c: number): { label: string; tone: "ok" | "warn" | "danger" } {
  if (c >= 0.8) return { label: "Cao", tone: "ok" };
  if (c >= 0.5) return { label: "Trung bình", tone: "warn" };
  return { label: "Thấp", tone: "danger" };
}

function pct(weight: number): string {
  return `${Math.round(weight * 100)}%`;
}

export function ScoreBreakdown({
  breakdown,
  showFlags = true,
  headless = false,
}: ScoreBreakdownProps) {
  const { overall_score, criteria, semantic_similarity, confidence, uncertainty_flags, summary } =
    breakdown;
  const conf = confidence != null ? confidenceTone(confidence) : null;
  const failed = uncertainty_flags.includes("rank_failed");

  return (
    <section>
      {!headless && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="mr-1 text-[20px]">Điểm đối sánh CV–JD</h2>
          {conf && (
            <Tag tone={conf.tone}>
              Tự tin: {conf.label} · {confidence!.toFixed(2)}
            </Tag>
          )}
          {showFlags &&
            uncertainty_flags.map((flag) => (
              <Tag key={flag} tone="warn">
                {flag}
              </Tag>
            ))}
        </div>
      )}

      {failed ? (
        <div className="rounded-xl border-2 border-accent bg-accent-100 px-4 py-3.5">
          <p className="font-heading font-bold text-accent-800">Chưa chấm được điểm</p>
          {/* Câu nhắc "vào hàng chờ HR" là chỉ báo HÀNH ĐỘNG — chỉ khi còn chờ quyết (showFlags).
              Hồ sơ đã quyết chỉ nêu SỰ THẬT "chấm không thành công". */}
          <p className="mt-1.5 text-[13px] text-accent-800">
            {showFlags
              ? "Ranker gặp lỗi khi chấm — ca này vào hàng chờ HR xem xét."
              : "Ranker gặp lỗi khi chấm — hồ sơ không chấm được điểm."}
          </p>
        </div>
      ) : (
        <>
          {/* Điểm tổng nổi bật */}
          <div className="rounded-xl border-2 border-divider bg-canvas p-4">
            <div className="flex items-baseline gap-2.5">
              <span className="font-heading text-[44px] font-bold leading-none">
                {overall_score != null ? overall_score : "—"}
              </span>
              <span className="text-[13px] text-ink/65">/ 100 · điểm tổng theo rubric</span>
            </div>
            {summary?.trim() && (
              <p className="mt-2.5 text-[13px] leading-relaxed text-ink/80">{summary}</p>
            )}
          </div>

          {/* Từng tiêu chí: tên + trọng số + điểm + lý do */}
          {criteria.length > 0 ? (
            <ol className="mt-3 flex flex-col gap-2">
              {criteria.map((c, i) => (
                <li key={i} className="rounded-lg border border-divider bg-canvas px-4 py-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-2.5">
                    <span className="text-[13px] font-semibold">
                      {c.criterion?.trim() || "(Tiêu chí không tên)"}
                    </span>
                    <span className="text-[13px] text-ink/65">
                      trọng số {pct(c.weight)} ·{" "}
                      <span className="font-heading font-bold text-ink">{c.score}/100</span>
                    </span>
                  </div>
                  {/* Thanh điểm (0..100) — chỉ trực quan, không đổi số liệu. */}
                  <div className="mt-2 h-1.5 w-full rounded-full bg-steel-200">
                    <div
                      className="h-1.5 rounded-full bg-ink"
                      style={{ width: `${Math.max(0, Math.min(100, c.score))}%` }}
                    />
                  </div>
                  {c.reasoning?.trim() && (
                    <p className="mt-2 text-[13px] leading-relaxed text-ink/65">{c.reasoning}</p>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <p className="mt-3 text-[13px] text-ink/65">
              Chưa có breakdown theo tiêu chí (ứng viên có thể đang chờ chấm điểm).
            </p>
          )}

          {/* Tín hiệu phụ: độ tương đồng ngữ nghĩa — KHÔNG tính vào điểm (PRD §7.2). */}
          <p className="mt-2.5 text-[13px] text-ink/65">
            Độ tương đồng ngữ nghĩa:{" "}
            <span className="font-bold text-ink">
              {semantic_similarity != null ? semantic_similarity.toFixed(4) : "—"}
            </span>{" "}
            — tham khảo, không tính điểm
          </p>
        </>
      )}
    </section>
  );
}
