import type { JobPosting, JobPostingInput, RubricCriterion } from "@ars/shared-types";

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

// Badge trạng thái JD — OPEN đang nhận CV; CLOSED đã đóng; khác (DRAFT legacy) trung tính.
export function jobStatusBadgeClass(status: string): string {
  if (status === "OPEN") return "bg-green-100 text-green-800";
  if (status === "CLOSED") return "bg-slate-200 text-slate-600";
  return "bg-amber-100 text-amber-800";
}

export function jobStatusLabel(status: string): string {
  if (status === "OPEN") return "Đang mở";
  if (status === "CLOSED") return "Đã đóng";
  return status;
}

// Giá trị form rỗng (chế độ TẠO).
export function emptyJobInput(): JobPostingInput {
  return {
    title: "",
    description: "",
    requirements: [""],
    rubric: [{ criterion: "", weight: 0 }],
    screener_questions: [""],
    gate_config: { auto_reject: false, auto_invite: false },
  };
}

// Nạp JD hiện tại vào form (chế độ SỬA). Giữ ≥1 dòng để danh sách động không rỗng hẳn.
export function toJobInput(job: JobPosting): JobPostingInput {
  return {
    title: job.title,
    description: job.description,
    requirements: job.requirements.length ? [...job.requirements] : [""],
    rubric: job.rubric.length ? job.rubric.map((c) => ({ ...c })) : [{ criterion: "", weight: 0 }],
    screener_questions: job.screener_questions.length ? [...job.screener_questions] : [""],
    gate_config: { ...job.gate_config },
  };
}
