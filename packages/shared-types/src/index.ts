// Type dùng chung (scaffold) — phản chiếu schema backend (PRD §16).
// Khớp với app/schemas (backend Python). Khi backend đổi -> cập nhật ở đây.

export type ServiceState = "ok" | string; // "ok" hoặc "error: <Type>"

export interface HealthStatus {
  status: "ok" | "degraded";
  api: "ok";
  services: {
    postgres: ServiceState;
    redis: ServiceState;
    qdrant: ServiceState;
  };
}

// ── Auth HR (slice 09, PRD §4) — CHỈ HR Admin; ứng viên là guest ──
// Khớp HrUserRead (backend GET /api/auth/me + trả về login). KHÔNG có password_hash.
export interface HrUser {
  id: number;
  email: string;
}

// Trạng thái CV — khớp state machine PRD §13.
export type ApplicationStatus =
  | "SUBMITTED"
  | "PARSING"
  | "RANKING"
  | "SCREENING"
  | "AWAITING_SCREENER"
  | "REMINDED"
  | "SCHEDULING"
  | "PENDING_REVIEW"
  | "INTERVIEW_SCHEDULED"
  | "REJECTED";

export interface Application {
  id: number;
  job_id: number | null;
  applicant_email: string;
  cv_file_ref: string | null;
  status: ApplicationStatus;
  score: number | null;
  confidence: number | null;
  uncertainty_flags: string[];
  escalation_reason: string | null;
  screener_sent_at: string | null;
  screener_deadline: string | null;
  created_at: string;
  updated_at: string;
}

// ── Màn HR danh sách/chi tiết ứng viên (slice 03a, CHỈ ĐỌC) — khớp ApplicationRead (backend) ──

// Item danh sách: đủ để hiển thị dòng ứng viên (không cần parsed_data/breakdown — giữ nhẹ).
export interface ApplicationListItem {
  id: number;
  applicant_email: string;
  job_id: number | null;
  status: ApplicationStatus;
  score: number | null;
  confidence: number | null;
  uncertainty_flags: string[];
  created_at: string;
}

// Một tiêu chí rubric đã chấm (khớp ranker._reconcile_criteria: tên+trọng số từ JD, điểm từ LLM).
export interface Criterion {
  criterion: string | null;
  weight: number;
  score: number;
  reasoning: string;
}

// score_breakdown lưu trong DB (JSONB) — khớp tasks/background.py: {criteria, summary, semantic_similarity}.
export interface ScoreBreakdownRaw {
  criteria: Criterion[];
  summary: string | null;
  semantic_similarity: number | null;
}

// Gợi ý hiển thị cho ReviewCard (PRD §11) — dẫn xuất từ score+flags, KHÔNG tự quyết. Khớp backend.
export type Recommendation = "invite" | "consider_reject" | "review_carefully";

// Một cặp hỏi–đáp sàng lọc đã lưu — hiện cho HR (khớp ApplicationRead.screener_answers backend).
export interface ScreenerAnswer {
  question: string;
  answer: string;
}

// Chi tiết: list item + parsed_data + breakdown. escalation_reason + recommendation cho ReviewCard.
export interface ApplicationDetail extends ApplicationListItem {
  parsed_data: ParsedCV | null;
  score_breakdown: ScoreBreakdownRaw;
  escalation_reason: string | null;
  recommendation: Recommendation;
  screener_answers: ScreenerAnswer[]; // [] khi chưa/không sàng lọc (08b)
}

// human_review (PRD §11): HR duyệt/từ chối một ca PENDING_REVIEW.
export type ReviewDecision = "approve" | "reject";

export interface ReviewRequest {
  decision: ReviewDecision;
  note?: string | null;
}

// Prop cho component ScoreBreakdown (thuần presentational — tái dùng ở ReviewCard, lát human_review).
// Chuẩn hóa từ ApplicationDetail: gộp overall + criteria + tín hiệu phụ + confidence/flags vào một chỗ.
export interface ScoreBreakdownData {
  overall_score: number | null;
  criteria: Criterion[];
  semantic_similarity: number | null;
  confidence: number | null;
  uncertainty_flags: string[];
  summary?: string | null;
}

// JD — khớp JobPostingRead (backend). Dùng cho ngữ cảnh chấm điểm (trang chi tiết) + quản lý JD (slice 05).
export interface RubricCriterion {
  criterion: string;
  weight: number;
}

// Hai gate cấu hình theo JD (PRD §9). auto_invite dành cho vòng Screener (kích hoạt sau).
export interface GateConfig {
  auto_reject: boolean;
  auto_invite: boolean;
}

export interface JobPosting {
  id: number;
  title: string;
  description: string;
  requirements: string[];
  rubric: RubricCriterion[];
  screener_questions: string[];
  gate_config: GateConfig;
  status: string; // OPEN | CLOSED | DRAFT (legacy) — badge xử lý mọi giá trị.
  embedding_ref: string | null; // null = chưa embed (embedding lỗi / JD legacy).
  created_at: string;
  updated_at: string;
}

// Payload tạo/sửa JD (form dùng chung) — khớp JobPostingCreate (backend).
export interface JobPostingInput {
  title: string;
  description: string;
  requirements: string[];
  rubric: RubricCriterion[];
  screener_questions: string[];
  gate_config: GateConfig;
}

// Trả về POST/PUT /api/jobs — khớp JobPostingCreateResult: JD + cảnh báo nếu embed lỗi (JD vẫn lưu).
export interface JobMutationResult {
  job: JobPosting;
  embedding_warning: string | null;
}

// ── Công khai (ứng viên guest — slice 07) ──
// JD projection AN TOÀN — khớp PublicJobRead (backend). KHÔNG có rubric/gate_config/screener_questions
// (cố ý: ứng viên không được thấy tiêu chí chấm).
export interface PublicJob {
  id: number;
  title: string;
  description: string;
  requirements: string[];
  created_at: string;
}

// Xác nhận nộp CV — khớp PublicSubmitResponse. KHÔNG có điểm/trạng thái (ứng viên không thấy).
export interface PublicSubmitResult {
  application_id: number;
  message: string;
}

// ── Sàng lọc công khai (screener magic-link — slice 08b) ──
// Form câu hỏi từ GET /api/public/screening/{token} — khớp PublicScreeningRead (backend).
// CHỈ tiêu đề JD + câu hỏi (KHÔNG lộ rubric/điểm/parsed_data).
export interface ScreenerForm {
  job_title: string;
  questions: string[];
}

// Xác nhận nộp câu trả lời — khớp ScreeningSubmitResponse (backend). KHÔNG lộ điểm/trạng thái.
export interface ScreenerSubmitResult {
  status: string;
  message: string;
}

// Parser (PRD §7.1) — khớp app/schemas/parsed_cv.py (backend). Mọi trường có thể null/rỗng.
export interface Experience {
  company: string | null;
  title: string | null;
  duration: string | null;
  summary: string | null;
}

export interface Education {
  school: string | null;
  degree: string | null;
  field: string | null;
  year: string | null;
}

export interface Certificate {
  name: string | null;
  detail: string | null;
  year: string | null;
}

export interface Language {
  name: string | null;
  proficiency: string | null;
}

export interface OtherItem {
  label: string | null;
  content: string | null;
}

export interface ParsedCV {
  full_name: string | null;
  email: string | null;
  phone: string | null;
  skills: string[];
  experiences: Experience[];
  education: Education[];
  total_years_experience: number | null;
  professional_summary: string | null;
  // slice 01c — mặc định [] (tương thích ngược với parsed_data cũ có thể thiếu).
  certificates: Certificate[];
  languages: Language[];
  awards: string[];
  other: OtherItem[];
}

// Trả về của POST /api/agents/parse-cv — khớp ParseCVResponse (app/schemas/agent.py).
export interface ParseCvResponse {
  parsed_data: ParsedCV | null;
  confidence: number;
  uncertainty_flags: string[];
  escalation_reason: string | null;
}
