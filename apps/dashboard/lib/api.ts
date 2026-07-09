import type {
  ApplicationDetail,
  ApplicationListItem,
  JobPosting,
  ParseCvResponse,
} from "@ars/shared-types";

// Base URL backend — đọc từ env (NEXT_PUBLIC_API_BASE), mặc định localhost:8000.
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status} khi GET ${path}`);
  return (await res.json()) as T;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} khi POST ${path}`);
  return (await res.json()) as T;
}

// ── Màn HR ứng viên (slice 03a, CHỈ ĐỌC) ──
export const getApplications = () =>
  getJson<ApplicationListItem[]>("/api/applications");

export const getApplication = (id: number) =>
  getJson<ApplicationDetail>(`/api/applications/${id}`);

// JD của ứng viên (tiêu đề + rubric) để hiển thị ngữ cảnh chấm điểm ở trang chi tiết.
export const getJob = (id: number) => getJson<JobPosting>(`/api/jobs/${id}`);

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
