import type { JobPosting, JobPostingInput, RubricCriterion, SalaryInfo } from "@ars/shared-types";

// ── JD-1: nhãn cho dropdown + hiển thị (level / loại việc / lương) ──
export const LEVEL_OPTIONS: { value: string; label: string }[] = [
  { value: "intern", label: "Thực tập sinh" },
  { value: "fresher", label: "Fresher" },
  { value: "junior", label: "Junior" },
  { value: "mid", label: "Middle" },
  { value: "senior", label: "Senior" },
  { value: "lead", label: "Lead" },
  { value: "manager", label: "Manager" },
];

export const EMPLOYMENT_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "full_time", label: "Toàn thời gian" },
  { value: "part_time", label: "Bán thời gian" },
  { value: "contract", label: "Hợp đồng" },
  { value: "internship", label: "Thực tập" },
];

export function levelLabel(value: string | null): string | null {
  if (!value) return null;
  return LEVEL_OPTIONS.find((o) => o.value === value)?.label ?? value;
}

export function employmentTypeLabel(value: string | null): string | null {
  if (!value) return null;
  return EMPLOYMENT_TYPE_OPTIONS.find((o) => o.value === value)?.label ?? value;
}

// Chuỗi hiển thị lương (null = chưa nhập gì). "Thỏa thuận" thắng min/max.
export function formatSalary(s: SalaryInfo | null | undefined): string | null {
  if (!s) return null;
  if (s.negotiable) return "Thỏa thuận";
  const cur = s.currency || "VND";
  const fmt = (n: number) => n.toLocaleString("vi-VN");
  if (s.min != null && s.max != null) return `${fmt(s.min)} – ${fmt(s.max)} ${cur}`;
  if (s.min != null) return `Từ ${fmt(s.min)} ${cur}`;
  if (s.max != null) return `Đến ${fmt(s.max)} ${cur}`;
  return null;
}

export function emptySalary(): SalaryInfo {
  return { min: null, max: null, currency: "VND", negotiable: false };
}

// Bóc HTML → plain-text cho ĐOẠN XEM TRƯỚC (card danh sách /apply). Nội dung định dạng (JD-1) chỉ
// render đầy đủ ở trang chi tiết (SafeHtml); ở card thì hiện text trơn, cắt dòng — KHÔNG lộ tag thô.
export function htmlToPlainText(html: string): string {
  return html
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}

// Tổng trọng số rubric (validate MỀM: nên ≈ 1.0). Ranker vốn chuẩn hóa lại theo trọng số,
// nên lệch 1.0 KHÔNG chặn cứng — chỉ cảnh báo hướng dẫn HR (plan §3.5).
export const WEIGHT_TARGET = 1.0;
export const WEIGHT_TOLERANCE = 0.01; // sai số float khi cộng dồn

export function weightSum(rubric: RubricCriterion[]): number {
  return rubric.reduce((acc, c) => acc + (Number.isFinite(c.weight) ? c.weight : 0), 0);
}

export function isWeightBalanced(rubric: RubricCriterion[]): boolean {
  return Math.abs(weightSum(rubric) - WEIGHT_TARGET) <= WEIGHT_TOLERANCE;
}

// Rubric đủ để MỞ JD (JD-2a — khớp backend is_valid_rubric): ≥1 tiêu chí + tổng trọng số > 0.
// KHÔNG ép tổng ≈ 1 (validate mềm/gợi ý UI riêng — ranker tự chuẩn hóa).
export function isValidRubric(rubric: RubricCriterion[]): boolean {
  return rubric.length > 0 && weightSum(rubric) > 0;
}

// Badge trạng thái JD — DRAFT nháp (JD-2a); OPEN đang nhận CV; CLOSED đã đóng; ARCHIVED lưu trữ (JD-4).
export function jobStatusBadgeClass(status: string): string {
  if (status === "OPEN") return "bg-green-100 text-green-800";
  if (status === "CLOSED") return "bg-slate-200 text-slate-600";
  if (status === "DRAFT") return "bg-amber-100 text-amber-800";
  if (status === "ARCHIVED") return "bg-slate-100 text-slate-400";
  return "bg-slate-100 text-slate-500";
}

export function jobStatusLabel(status: string): string {
  if (status === "OPEN") return "Đang mở";
  if (status === "CLOSED") return "Đã đóng";
  if (status === "DRAFT") return "Nháp";
  if (status === "ARCHIVED") return "Đã lưu trữ";
  return status;
}

// Giá trị form rỗng (chế độ TẠO). JD-1: mô tả/yêu cầu/quyền lợi là văn bản định dạng (chuỗi HTML).
// JD-2a: rubric/câu-hỏi cấu hình ở màn 2 (JD đã lưu) → tạo mới KHÔNG kèm rubric/câu-hỏi (rỗng → DRAFT).
export function emptyJobInput(): JobPostingInput {
  return {
    title: "",
    description: "",
    requirements: "",
    level: null,
    salary: emptySalary(),
    benefits: "",
    employment_type: null,
    rubric: [],
    screener_questions: [],
    gate_config: { auto_reject: false, auto_invite: false },
  };
}

// Nạp JD hiện tại vào form (chế độ SỬA). Giữ ≥1 dòng cho danh sách động (rubric/câu hỏi) không rỗng hẳn.
export function toJobInput(job: JobPosting): JobPostingInput {
  return {
    title: job.title,
    description: job.description,
    requirements: job.requirements,
    level: job.level,
    salary: job.salary ? { ...job.salary } : emptySalary(),
    benefits: job.benefits,
    employment_type: job.employment_type,
    rubric: job.rubric.length ? job.rubric.map((c) => ({ ...c })) : [{ criterion: "", weight: 0 }],
    screener_questions: job.screener_questions.length ? [...job.screener_questions] : [""],
    gate_config: { ...job.gate_config },
  };
}
