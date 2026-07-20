import type {
  ApplicationDetail,
  ApplicationStatus,
  ScoreBreakdownData,
} from "@ars/shared-types";

// Gộp các trường ApplicationDetail thành prop cho ScoreBreakdown (semantic_similarity nằm trong
// score_breakdown; overall = cột score). Dùng chung: trang chi tiết + ReviewCard.
export function toBreakdown(app: ApplicationDetail): ScoreBreakdownData {
  return {
    overall_score: app.score,
    criteria: app.score_breakdown?.criteria ?? [],
    semantic_similarity: app.score_breakdown?.semantic_similarity ?? null,
    confidence: app.confidence,
    uncertainty_flags: app.uncertainty_flags ?? [],
    summary: app.score_breakdown?.summary ?? null,
  };
}

// Ba rổ dashboard (PRD §13): đang xử lý / chờ HR / kết thúc (passed | rejected).
// "passed" & "rejected" tách riêng cho bộ lọc (plan §3.5) dù PRD gộp chung rổ "kết thúc".
export type StatusBucket = "processing" | "review" | "passed" | "rejected";

// Mọi trạng thái không phải PENDING_REVIEW / INTERVIEW_SCHEDULED / REJECTED đều là "đang xử lý"
// (gồm cả REMINDED — sub-state của AWAITING_SCREENER).
export function statusBucket(status: ApplicationStatus): StatusBucket {
  if (status === "PENDING_REVIEW") return "review";
  if (status === "INTERVIEW_SCHEDULED") return "passed";
  if (status === "REJECTED") return "rejected";
  return "processing";
}

const STATUS_LABEL: Record<ApplicationStatus, string> = {
  SUBMITTED: "Đã nộp",
  PARSING: "Đang bóc tách",
  RANKING: "Đang chấm điểm",
  SCREENING: "Sàng lọc",
  AWAITING_SCREENER: "Chờ trả lời sàng lọc",
  REMINDED: "Đã nhắc",
  SCHEDULING: "Đang đặt lịch",
  PENDING_REVIEW: "Chờ HR duyệt",
  INTERVIEW_SCHEDULED: "Đã hẹn phỏng vấn",
  REJECTED: "Đã từ chối",
};

export function statusLabel(status: ApplicationStatus): string {
  return STATUS_LABEL[status] ?? status;
}

// Màu badge theo rổ — nhất quán với bảng màu slate + trạng thái ở ParsedCVResult.
const BUCKET_BADGE: Record<StatusBucket, string> = {
  processing: "bg-blue-100 text-blue-800",
  review: "bg-amber-100 text-amber-800",
  passed: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-800",
};

export function statusBadgeClass(status: ApplicationStatus): string {
  return BUCKET_BADGE[statusBucket(status)];
}

// UI redesign: tông thẻ trạng thái theo rổ — đang xử lý (nhấn cobalt) · chờ HR (hổ phách, cần
// hành động) · đạt (xanh) · từ chối (đỏ). Dùng với <Tag tone=…> của components/ui.
const BUCKET_TONE = {
  processing: "accent",
  review: "warn",
  passed: "ok",
  rejected: "danger",
} as const;

export function statusTone(status: ApplicationStatus): "accent" | "warn" | "ok" | "danger" {
  return BUCKET_TONE[statusBucket(status)];
}

// Nhãn bộ lọc theo rổ (trang danh sách).
export const BUCKET_FILTERS: { key: StatusBucket | "all"; label: string }[] = [
  { key: "all", label: "Tất cả" },
  { key: "processing", label: "Đang xử lý" },
  { key: "review", label: "Chờ HR" },
  { key: "passed", label: "Passed" },
  { key: "rejected", label: "Rejected" },
];
