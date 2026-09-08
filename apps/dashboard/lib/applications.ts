import type {
  ApplicationDetail,
  ApplicationStatus,
  ScoreBreakdownData,
} from "@ars/shared-types";

// Ba cờ email (EMAIL-1 · EMAIL-2) đã có banner/Tag RIÊNG bằng tiếng Việt ở mọi màn HR — KHÔNG đổ
// THÊM token thô vào dòng cờ "cần chú ý". MỘT danh sách duy nhất, dùng chung cho mọi chỗ lọc: hai
// danh sách viết tay song song chính là cách một cờ email thứ tư được thêm vào một bên rồi im lặng
// vắng mặt ở bên kia — đúng lớp lỗi mà `_NEGATIVE = frozenset(_STATUS_FLAG)` bên
// `services/email_delivery.py` đã dựng rào.
const EMAIL_FLAGS: readonly string[] = ["email_bounced", "email_complained", "email_send_failed"];

export function isEmailFlag(flag: string): boolean {
  return EMAIL_FLAGS.includes(flag);
}

// Gộp các trường ApplicationDetail thành prop cho ScoreBreakdown (semantic_similarity nằm trong
// score_breakdown; overall = cột score). Dùng chung: trang chi tiết + ReviewCard.
export function toBreakdown(app: ApplicationDetail): ScoreBreakdownData {
  return {
    overall_score: app.score,
    criteria: app.score_breakdown?.criteria ?? [],
    semantic_similarity: app.score_breakdown?.semantic_similarity ?? null,
    confidence: app.confidence,
    // Khối ĐIỂM chỉ nói chuyện của ranker (score_signal_mismatch / weak_match / near_threshold).
    // Cờ email đã có banner riêng ở đầu trang — lọt vào đây thì vừa trùng lặp vừa đọc như lỗi ranker.
    uncertainty_flags: (app.uncertainty_flags ?? []).filter((f) => !isEmailFlag(f)),
    summary: app.score_breakdown?.summary ?? null,
  };
}

// Ba rổ dashboard (PRD §13): đang xử lý / chờ HR / kết thúc (passed | rejected).
// "passed" & "rejected" tách riêng cho bộ lọc (plan §3.5) dù PRD gộp chung rổ "kết thúc".
export type StatusBucket = "processing" | "review" | "passed" | "rejected";

// Mọi trạng thái không phải PENDING_REVIEW / INTERVIEW_SCHEDULED / REJECTED đều là "đang xử lý"
// (gồm cả giai đoạn đã gửi nhắc — vẫn là AWAITING_SCREENER).
// Bốn hàm/hằng dưới đây KHÔNG export: chúng chỉ phục vụ các API công khai của chính file này
// (`applicationStatusLabel` / `applicationStatusTone` / `STATUSES_IN_BUCKET` / `bucketTotal`).
// Hạ xuống nội bộ để `noUnusedLocals` bắt được ngay nếu sau này chúng thật sự chết — export ra
// ngoài là tự tắt cái lưới đó.
function statusBucket(status: ApplicationStatus): StatusBucket {
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
  SCHEDULING: "Đang đặt lịch",
  // SCH-2: thư mời + link ĐÃ gửi — quả bóng đang ở sân ứng viên, HR không phải làm gì.
  AWAITING_BOOKING: "Chờ ứng viên chọn lịch",
  PENDING_REVIEW: "Chờ HR duyệt",
  INTERVIEW_SCHEDULED: "Đã hẹn phỏng vấn",
  REJECTED: "Đã từ chối",
};

function statusLabel(status: ApplicationStatus): string {
  return STATUS_LABEL[status] ?? status;
}

// SCH-3 (FR-BOOK-6): "chờ ứng viên chọn lịch" và "hết khung giờ" là HAI chuyện khác nhau, dù hồ sơ
// đứng ở cùng một trạng thái. Cái đầu là quả bóng ở sân ứng viên; cái sau là LỊCH CỦA CÔNG TY đang
// chặn — HR phải mở thêm khung giờ thì ứng viên mới đặt được. Dùng chung một nhãn cho cả hai là để
// HR ngồi chờ một người vốn đang không có gì để bấm.
export function applicationStatusLabel(app: {
  status: ApplicationStatus;
  booking_no_slots?: boolean;
}): string {
  if (app.status === "AWAITING_BOOKING" && app.booking_no_slots) {
    return "Hết khung giờ — cần mở thêm lịch";
  }
  return statusLabel(app.status);
}

// Hết khung giờ là việc CẦN HR LÀM (mở thêm lịch), nên tô như rổ "chờ HR" chứ không phải như một
// hồ sơ đang chạy êm.
export function applicationStatusTone(app: {
  status: ApplicationStatus;
  booking_no_slots?: boolean;
}): "accent" | "warn" | "ok" | "danger" {
  if (app.status === "AWAITING_BOOKING" && app.booking_no_slots) return "warn";
  return statusTone(app.status);
}

// UI redesign: tông thẻ trạng thái theo rổ — đang xử lý (nhấn cobalt) · chờ HR (hổ phách, cần
// hành động) · đạt (xanh) · từ chối (đỏ). Dùng với <Tag tone=…> của components/ui.
const BUCKET_TONE = {
  processing: "accent",
  review: "warn",
  passed: "ok",
  rejected: "danger",
} as const;

function statusTone(status: ApplicationStatus): "accent" | "warn" | "ok" | "danger" {
  return BUCKET_TONE[statusBucket(status)];
}

// Nhãn bộ lọc theo rổ (trang danh sách).
export const BUCKET_FILTERS: { key: StatusBucket | "all"; label: string }[] = [
  { key: "all", label: "Tất cả" },
  { key: "processing", label: "Đang xử lý" },
  { key: "review", label: "Chờ HR" },
  { key: "passed", label: "Đạt" },
  { key: "rejected", label: "Từ chối" },
];

// Mọi trạng thái PRD §13, theo đúng thứ tự pipeline. NGUỒN DUY NHẤT cho hai suy dẫn bên dưới.
const ALL_STATUSES: readonly ApplicationStatus[] = [
  "SUBMITTED",
  "PARSING",
  "RANKING",
  "SCREENING",
  "AWAITING_SCREENER",
  "SCHEDULING",
  "AWAITING_BOOKING",
  "PENDING_REVIEW",
  "INTERVIEW_SCHEDULED",
  "REJECTED",
];

// B1: rổ → danh sách trạng thái để LỌC Ở SERVER (`?status=` lặp nhiều lần).
//
// SUY RA từ `statusBucket` chứ KHÔNG chép tay: hai bảng song song là cách một trạng thái mới được
// thêm vào `statusBucket` rồi im lặng vắng mặt ở bộ lọc — hồ sơ mang trạng thái đó sẽ biến mất khỏi
// mọi rổ mà không có lỗi nào. `all` = undefined (không gửi `?status=`) chứ KHÔNG phải liệt kê đủ 11
// trạng thái: URL ngắn hơn, và hồ sơ mang trạng thái lạ (dữ liệu cũ) vẫn hiện ra thay vì bị nuốt.
export const STATUSES_IN_BUCKET: Record<
  StatusBucket | "all",
  readonly ApplicationStatus[] | undefined
> = {
  all: undefined,
  processing: ALL_STATUSES.filter((s) => statusBucket(s) === "processing"),
  review: ALL_STATUSES.filter((s) => statusBucket(s) === "review"),
  passed: ALL_STATUSES.filter((s) => statusBucket(s) === "passed"),
  rejected: ALL_STATUSES.filter((s) => statusBucket(s) === "rejected"),
};

// Tổng số hồ sơ của một rổ, tính từ `counts` của `/applications/pipeline` (GROUP BY toàn bảng).
// Việc gom trạng thái nào vào rổ nào VẪN do client giữ — đúng như docstring `PipelineSnapshot` yêu
// cầu ("đó là cách đọc PRD, không phải dữ liệu; nhân đôi nó xuống backend chỉ tạo thêm một chỗ để
// hai bên lệch nhau").
export function bucketTotal(
  counts: Record<string, number> | undefined,
  bucket: StatusBucket | "all",
): number | null {
  if (!counts) return null;
  const entries = Object.entries(counts);
  if (bucket === "all") return entries.reduce((t, [, n]) => t + n, 0);
  return entries
    .filter(([s]) => statusBucket(s as ApplicationStatus) === bucket)
    .reduce((t, [, n]) => t + n, 0);
}
