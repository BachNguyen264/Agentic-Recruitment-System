import type {
  ApplicationDetail,
  ApplicationListItem,
  HrUser,
  JobMutationResult,
  JobPosting,
  JobPostingInput,
  ParseCvResponse,
  PublicJob,
  PublicSubmitResult,
  ReviewDecision,
  RubricSuggestResult,
  ScreenerForm,
  ScreenerSubmitResult,
} from "@ars/shared-types";

// Base URL backend.
//   - prod: để TRỐNG (bỏ NEXT_PUBLIC_API_BASE) → API_BASE="" → gọi SAME-ORIGIN `/api/*`; Vercel rewrite
//     (xem next.config) proxy sang backend Render. Nhờ vậy cookie auth thành FIRST-PARTY của domain
//     frontend → đăng nhập chạy trên ĐIỆN THOẠI (iOS/Android chặn cookie bên-thứ-ba nếu gọi thẳng backend).
//   - dev: mặc định http://localhost:8000 (localhost là same-site, cookie chạy bình thường, không cần proxy).
//   - Đặt NEXT_PUBLIC_API_BASE tường minh = URL backend để ép gọi THẲNG (thoát proxy) nếu cần.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ??
  (process.env.NODE_ENV === "production" ? "" : "http://localhost:8000");

// Auth slice 09: MỌI request gửi kèm cookie (credentials) để backend đọc JWT httpOnly. Cross-domain
// (Vercel+Render) hoạt động nhờ CORS allow_credentials + cookie SameSite=None (cấu hình qua ENV).
const CREDENTIALS: RequestCredentials = "include";

// 401 giữa phiên (hết hạn/đăng xuất nơi khác) trên các call DỮ LIỆU HR → về /login. CHỈ ở browser;
// tránh vòng lặp khi đã ở /login. Các call auth (login/getMe/logout) KHÔNG dùng đường này (tự xử lý).
function redirectToLogin(): void {
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/login?next=${next}`;
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { credentials: CREDENTIALS });
  if (res.status === 401) {
    redirectToLogin();
    throw new Error("Chưa đăng nhập");
  }
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
    credentials: CREDENTIALS,
  });
  if (res.status === 401) {
    redirectToLogin();
    throw new Error("Chưa đăng nhập");
  }
  if (!res.ok) throw new Error(`HTTP ${res.status} khi ${method} ${path}`);
  return (await res.json()) as T;
}

// ── Auth HR (slice 09, PRD §4) ──
// login: KHÔNG đi qua redirect chung — sai mật khẩu (401) hiện lỗi INLINE ở form. Message chung từ
// backend (không lộ email tồn tại).
export async function login(email: string, password: string): Promise<HrUser> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    credentials: CREDENTIALS,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? "Đăng nhập thất bại.");
  }
  return (await res.json()) as HrUser;
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE}/api/auth/logout`, { method: "POST", credentials: CREDENTIALS });
}

// getMe: dùng cho guard trang HR. Trả HrUser nếu đã đăng nhập; null nếu 401 (guard tự redirect —
// KHÔNG dùng redirect chung để layout kiểm soát trạng thái loading/lỗi). Lỗi khác (backend sập) → ném.
export async function getMe(): Promise<HrUser | null> {
  const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: CREDENTIALS });
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`HTTP ${res.status} khi kiểm tra phiên đăng nhập`);
  return (await res.json()) as HrUser;
}

// ── Màn HR ứng viên (slice 03a, CHỈ ĐỌC) ──
export const getApplications = () =>
  getJson<ApplicationListItem[]>("/api/applications");

export const getApplication = (id: number) =>
  getJson<ApplicationDetail>(`/api/applications/${id}`);

// ── Quản lý JD (slice 05) ──
// JD-4: mặc định (archived=false) ẨN JD đã lưu trữ; archived=true → chỉ JD ARCHIVED (màn "Đã lưu trữ").
export const getJobs = (archived = false) =>
  getJson<JobPosting[]>(`/api/jobs?archived=${archived}`);

// JD đơn (dùng cho ngữ cảnh chấm điểm ở trang chi tiết + nạp form sửa).
export const getJob = (id: number) => getJson<JobPosting>(`/api/jobs/${id}`);

export const createJob = (input: JobPostingInput) =>
  postJson<JobMutationResult>("/api/jobs", input);

export const updateJob = (id: number, input: JobPostingInput) =>
  putJson<JobMutationResult>(`/api/jobs/${id}`, input);

// Đóng/mở JD (đổi status — KHÔNG xóa). MỞ (OPEN) có thể bị backend chặn 400 nếu JD chưa rubric (JD-2a)
// → surface {detail} ("cần rubric…") thay vì "HTTP 400" chung, để UI hiện thông báo rõ.
export async function setJobStatus(id: number, status: "OPEN" | "CLOSED"): Promise<JobPosting> {
  const res = await fetch(`${API_BASE}/api/jobs/${id}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
    credentials: CREDENTIALS,
  });
  if (res.status === 401) {
    redirectToLogin();
    throw new Error("Chưa đăng nhập");
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `HTTP ${res.status} khi đổi trạng thái JD`);
  }
  return (await res.json()) as JobPosting;
}

// Bật/tắt gate auto (auto_reject/auto_invite) theo JD — partial (JD-2a: gate ở danh sách JD). PATCH /gate (03c/08d).
export const setGate = (id: number, patch: { auto_reject?: boolean; auto_invite?: boolean }) =>
  patchJson<JobPosting>(`/api/jobs/${id}/gate`, patch);

// JD-4 soft-delete: Lưu trữ JD (→ ARCHIVED, ẩn khỏi list+/apply, GIỮ hồ sơ) / Khôi phục (→ CLOSED).
export const archiveJob = (id: number) => postJson<JobPosting>(`/api/jobs/${id}/archive`, {});
export const restoreJob = (id: number) => postJson<JobPosting>(`/api/jobs/${id}/restore`, {});

// AI gợi ý rubric (JD-3, PRD §12.1). Đọc JD đã lưu → LLM đề xuất tiêu chí+trọng số để HR chỉnh/lưu.
// Hết lượt (cap 3/JD) → backend 429 với {detail} → surface message rõ ("hết lượt gợi ý…").
export async function suggestRubric(id: number): Promise<RubricSuggestResult> {
  const res = await fetch(`${API_BASE}/api/jobs/${id}/suggest-rubric`, {
    method: "POST",
    credentials: CREDENTIALS,
  });
  if (res.status === 401) {
    redirectToLogin();
    throw new Error("Chưa đăng nhập");
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `HTTP ${res.status} khi gợi ý rubric`);
  }
  return (await res.json()) as RubricSuggestResult;
}

// MUTATION human_review (PRD §11): HR duyệt/từ chối một ca PENDING_REVIEW.
export const submitReview = (id: number, decision: ReviewDecision, note: string | null) =>
  postJson<ApplicationDetail>(`/api/applications/${id}/review`, { decision, note });

// Tải CV gốc (slice 06). Endpoint STREAM trong khu HR (require_hr) — KHÔNG dùng public URL.
// Tải bằng fetch (không phải thẻ <a>) để cookie đi kèm nhất quán như mọi call khác, kể cả khi
// backend ở domain khác lúc deploy, và để bắt được 401 → về /login.
export async function downloadCv(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/applications/${id}/cv`, { credentials: CREDENTIALS });
  if (res.status === 401) {
    redirectToLogin();
    throw new Error("Chưa đăng nhập");
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `HTTP ${res.status} khi tải CV`);
  }
  // Tên file lấy từ Content-Disposition backend đặt (CV-<id>.<đuôi>).
  const disposition = res.headers.get("content-disposition") ?? "";
  const match = /filename="?([^"]+)"?/i.exec(disposition);
  const filename = match?.[1] ?? `CV-${id}`;

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url); // không giữ blob trong bộ nhớ (CV = dữ liệu cá nhân)
  }
}

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
  // Public (guest) — không cần cookie; credentials include vô hại + nhất quán.
  const res = await fetch(`${API_BASE}/api/public/applications`, {
    method: "POST",
    body: form,
    credentials: CREDENTIALS,
  });
  if (!res.ok) {
    // Backend trả {detail} (vd JD đã đóng / file sai) — hiện message thân thiện cho ứng viên.
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `HTTP ${res.status} khi nộp hồ sơ`);
  }
  return (await res.json()) as PublicSubmitResult;
}

// ── Sàng lọc công khai (screener magic-link — slice 08b) ──
// Lấy câu hỏi theo token. Token sai/hết hạn/đã nộp → backend trả {detail} → ném message rõ cho UI.
export async function getScreener(token: string): Promise<ScreenerForm> {
  const res = await fetch(`${API_BASE}/api/public/screening/${encodeURIComponent(token)}`, {
    credentials: CREDENTIALS,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `HTTP ${res.status} khi tải câu hỏi`);
  }
  return (await res.json()) as ScreenerForm;
}

// Nộp câu trả lời (JSON: answers theo thứ tự câu hỏi). Lỗi token → ném {detail} thân thiện.
export async function submitScreener(
  token: string,
  answers: string[],
): Promise<ScreenerSubmitResult> {
  const res = await fetch(`${API_BASE}/api/public/screening/${encodeURIComponent(token)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers }),
    credentials: CREDENTIALS,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `HTTP ${res.status} khi gửi câu trả lời`);
  }
  return (await res.json()) as ScreenerSubmitResult;
}

// Upload CV -> POST /api/agents/parse-cv (multipart). KHÔNG tự set Content-Type:
// để browser tự thêm boundary cho FormData.
export async function parseCv(file: File): Promise<ParseCvResponse> {
  const form = new FormData();
  form.append("file", file);
  // /api/agents/* nay là HR-only (slice 09) — /cv-check nằm trong khu vực đã đăng nhập.
  const res = await fetch(`${API_BASE}/api/agents/parse-cv`, {
    method: "POST",
    body: form,
    credentials: CREDENTIALS,
  });
  if (res.status === 401) {
    redirectToLogin();
    throw new Error("Chưa đăng nhập");
  }
  if (!res.ok) throw new Error(`HTTP ${res.status} khi phân tích CV`);
  return (await res.json()) as ParseCvResponse;
}
