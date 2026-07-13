import type {
  ApplicationDetail,
  ApplicationListItem,
  JobMutationResult,
  JobPosting,
  JobPostingInput,
  ParseCvResponse,
  PublicJob,
  PublicSubmitResult,
  ReviewDecision,
} from "@ars/shared-types";

// Base URL backend — đọc từ env (NEXT_PUBLIC_API_BASE), mặc định localhost:8000.
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status} khi GET ${path}`);
  return (await res.json()) as T;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  return sendJson<T>("POST", path, body);
}

export async function putJson<T>(path: string, body: unknown): Promise<T> {
  return sendJson<T>("PUT", path, body);
}

export async function patchJson<T>(path: string, body: unknown): Promise<T> {
  return sendJson<T>("PATCH", path, body);
}

async function sendJson<T>(method: string, path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} khi ${method} ${path}`);
  return (await res.json()) as T;
}

// ── Màn HR ứng viên (slice 03a, CHỈ ĐỌC) ──
export const getApplications = () =>
  getJson<ApplicationListItem[]>("/api/applications");

export const getApplication = (id: number) =>
  getJson<ApplicationDetail>(`/api/applications/${id}`);

// ── Quản lý JD (slice 05) ──
export const getJobs = () => getJson<JobPosting[]>("/api/jobs");

// JD đơn (dùng cho ngữ cảnh chấm điểm ở trang chi tiết + nạp form sửa).
export const getJob = (id: number) => getJson<JobPosting>(`/api/jobs/${id}`);

export const createJob = (input: JobPostingInput) =>
  postJson<JobMutationResult>("/api/jobs", input);

export const updateJob = (id: number, input: JobPostingInput) =>
  putJson<JobMutationResult>(`/api/jobs/${id}`, input);

// Đóng/mở JD (đổi status — KHÔNG xóa).
export const setJobStatus = (id: number, status: "OPEN" | "CLOSED") =>
  patchJson<JobPosting>(`/api/jobs/${id}/status`, { status });

// MUTATION human_review (PRD §11): HR duyệt/từ chối một ca PENDING_REVIEW.
export const submitReview = (id: number, decision: ReviewDecision, note: string | null) =>
  postJson<ApplicationDetail>(`/api/applications/${id}/review`, { decision, note });

// ── Công khai (ứng viên guest — slice 07) ──
export const getOpenJobs = () => getJson<PublicJob[]>("/api/public/jobs");
export const getPublicJob = (id: number) => getJson<PublicJob>(`/api/public/jobs/${id}`);

// Nộp CV công khai (multipart: job_id + email + file). Lỗi validate server → ném message rõ.
export async function submitApplication(
  jobId: number,
  email: string,
  file: File,
): Promise<PublicSubmitResult> {
  const form = new FormData();
  form.append("job_id", String(jobId));
  form.append("applicant_email", email);
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/public/applications`, { method: "POST", body: form });
  if (!res.ok) {
    // Backend trả {detail} (vd JD đã đóng / file sai) — hiện message thân thiện cho ứng viên.
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `HTTP ${res.status} khi nộp hồ sơ`);
  }
  return (await res.json()) as PublicSubmitResult;
}

// Upload CV -> POST /api/agents/parse-cv (multipart). KHÔNG tự set Content-Type:
// để browser tự thêm boundary cho FormData.
export async function parseCv(file: File): Promise<ParseCvResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/agents/parse-cv`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} khi phân tích CV`);
  return (await res.json()) as ParseCvResponse;
}
