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
  // SCH-2: thư mời + link đặt lịch đã gửi, chờ ứng viên tự chọn giờ (PRD §10b).
  | "AWAITING_BOOKING"
  | "PENDING_REVIEW"
  | "INTERVIEW_SCHEDULED"
  | "REJECTED";

// ── Ảnh chụp pipeline cho bảng điều hành (PRD §12.1 FR-HR-DASH-1) ──
// Đây là đường bảng điều hành hỏi lại DỒN NHẤT (2s khi có tác tử chạy), nên payload cố ý có KÍCH
// THƯỚC CỐ ĐỊNH: 11 con số + tối đa 6 dòng. (Trước đây bảng điều hành poll `GET /api/applications`
// mỗi 5 giây — trả TOÀN BỘ hồ sơ kèm parsed_data, phình theo số ứng viên, và đếm sai vì backend cắt
// ở 100 bản ghi mới nhất. Badge sidebar ở `(hr)/layout` thì VẪN đi đường cũ đó — chưa chuyển.)
export interface PipelineItem {
  id: number;
  applicant_email: string;
  job_id: number | null;
  status: ApplicationStatus;
}

export interface PipelineSnapshot {
  // ĐỦ mọi trạng thái PRD §13, kể cả trạng thái đang có 0 hồ sơ.
  counts: Record<ApplicationStatus, number>;
  active: PipelineItem[];
}

export interface Application {
  id: number;
  job_id: number | null;
  applicant_email: string;
  // Slice 06: backend KHÔNG trả `cv_file_ref` nữa (path/key storage là chi tiết nội bộ — trước đây
  // lộ đường dẫn tuyệt đối của server). Chỉ có cờ has_cv; tải file qua GET /api/applications/{id}/cv.
  has_cv: boolean;
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
  // SCH-3 (FR-BOOK-6): ứng viên ĐÃ mở link nhưng kho khung giờ trống rỗng. Trường RIÊNG chứ không
  // suy từ status, vì "chưa bấm link" và "bấm rồi mà hết lịch" đều đứng ở AWAITING_BOOKING — gộp
  // hai cái thành một nhãn là đổ lỗi cho người không có lỗi.
  booking_no_slots?: boolean;
  // EMAIL-1: thư MỜI/SÀNG LỌC không tới được ứng viên (webhook Resend báo bounce). Dẫn xuất từ
  // uncertainty_flags ở backend nên có ở CẢ danh sách lẫn chi tiết mà không tốn thêm truy vấn nào.
  email_bounced?: boolean;
  // Ứng viên đã bấm "đây là spam" trên một lá thư ĐÃ TỚI NƠI — RIÊNG với email_bounced (hai tình
  // huống cần hai cách xử TRÁI NGƯỢC: bounce ⇒ tìm địa chỉ đúng; complaint ⇒ NGỪNG gửi cho người này).
  email_complained?: boolean;
  // Dịch vụ gửi KHÔNG đẩy được thư đi (webhook Resend báo email.failed) — thư chưa hề rời hệ thống.
  // RIÊNG với email_bounced: bounce ⇒ địa chỉ ứng viên có vấn đề, tìm kênh khác; failed ⇒ phía TA
  // có vấn đề (hạn mức/domain/khoá API), sửa rồi gửi lại chính địa chỉ đó.
  email_send_failed?: boolean;
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
  // Lịch phỏng vấn ứng viên đã tự chọn (SCH-2 · PRD §10b). null = chưa chọn.
  interview: BookedInterview | null;
  // Đã TỪNG được phát liên kết đặt lịch chưa (SCH-3) — gương của điều kiện backend dùng để chặn
  // "Gửi lại link". Không có nó thì nút hiện ở mọi ca PENDING_REVIEW rồi 409 khi bấm.
  has_booking_link: boolean;
  // Có file CV gốc để tải không (slice 06). Bytes lấy qua GET /api/applications/{id}/cv (require_hr).
  has_cv: boolean;
  // Lý do bounce rút gọn — chỉ có ở endpoint chi tiết. Cờ nói "có chuyện", câu này nói "chuyện gì".
  email_bounce_reason: string | null;
  // Lý do complaint tương tự — RIÊNG cột, Resend hiếm khi kèm chi tiết cho loại này nên thường null.
  email_complaint_reason: string | null;
  // Lý do KỸ THUẬT khi không gửi đi được (Resend `failed.reason`, vd "reached_daily_quota").
  email_send_failure_reason: string | null;
}

// Khung giờ phỏng vấn đã chốt — khớp BookedInterview (backend).
export interface BookedInterview {
  start_at: string;
  end_at: string;
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

// ── JD-1: trường hướng-ứng-viên (PRD §16, §8.1) ──
export type JobLevel =
  | "intern" | "fresher" | "junior" | "mid" | "senior" | "lead" | "manager";
export type EmploymentType = "full_time" | "part_time" | "contract" | "internship";

// Lương JD — khớp SalaryInfo (backend). negotiable = "Thỏa thuận" → bỏ qua min/max.
export interface SalaryInfo {
  min: number | null;
  max: number | null;
  currency: "VND" | "USD";
  negotiable: boolean;
}

// Hai gate cấu hình theo JD (PRD §9). auto_invite dành cho vòng Screener (kích hoạt sau).
export interface GateConfig {
  auto_reject: boolean;
  auto_invite: boolean;
}

export interface JobPosting {
  id: number;
  title: string;
  description: string; // JD-1: văn bản định dạng (HTML)
  requirements: string; // JD-1: văn bản định dạng (HTML) — không còn list
  level: string | null; // JobLevel; permissive cho JD legacy
  salary: SalaryInfo;
  benefits: string; // JD-1: văn bản định dạng (HTML)
  employment_type: string | null; // EmploymentType; permissive cho JD legacy
  rubric: RubricCriterion[];
  screener_questions: string[];
  gate_config: GateConfig;
  status: string; // OPEN | CLOSED | DRAFT (legacy) — badge xử lý mọi giá trị.
  embedding_ref: string | null; // null = chưa embed (embedding lỗi / JD legacy).
  // JD-3: số lần AI đã gợi ý rubric + số lượt còn lại (backend là nguồn chân lý của cap). CHỈ HR thấy.
  rubric_suggestion_count: number;
  rubric_suggestions_remaining: number;
  created_at: string;
  updated_at: string;
}

// ── JD-3: AI gợi ý rubric (PRD §12.1 FR-HR-RUBRIC-1) ──
// Một tiêu chí AI đề xuất — khớp SuggestedCriterion (backend). reasoning để HR tham khảo (tùy chọn).
export interface SuggestedCriterion {
  criterion: string;
  weight: number;
  reasoning: string;
}

// Trả về POST /api/jobs/{id}/suggest-rubric — khớp RubricSuggestResponse (backend).
export interface RubricSuggestResult {
  criteria: SuggestedCriterion[];
  used: number;
  remaining: number;
  model_used: string;
}

// Payload tạo/sửa JD (form dùng chung) — khớp JobPostingCreate (backend).
export interface JobPostingInput {
  title: string;
  description: string;
  requirements: string;
  level: string | null;
  salary: SalaryInfo;
  benefits: string;
  employment_type: string | null;
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
  description: string; // JD-1: văn bản định dạng (HTML) — render qua SafeHtml (DOMPurify)
  requirements: string; // JD-1: văn bản định dạng (HTML)
  level: string | null;
  salary: SalaryInfo;
  benefits: string; // JD-1: văn bản định dạng (HTML)
  employment_type: string | null;
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

// ── Đặt lịch phỏng vấn — trang công khai /booking/[token] (SCH-2 · PRD §10b) ──
// Khớp PublicBookingRead/BookingConfirmResponse (backend). Projection AN TOÀN: chỉ tiêu đề JD +
// tên + khung giờ. KHÔNG điểm/rubric/gate/trạng thái — ứng viên là khách (PRD §5).

export interface BookingSlot {
  booking_id: number;
  start_at: string; // ISO có múi giờ — hiển thị LUÔN quy về Asia/Ho_Chi_Minh
  end_at: string;
}

export interface BookingView {
  job_title: string;
  candidate_name: string;
  // Đã chốt lịch → hiện "bạn đã đặt lúc X", KHÔNG render danh sách chọn. Đây là TRẠNG THÁI bình
  // thường (token không one-time nên mở lại link là chuyện thường), không phải lỗi.
  already_booked: boolean;
  booked_start_at: string | null;
  booked_end_at: string | null;
  slots: BookingSlot[];
  // Hạn giữ chỗ chung cả lượt — UI đếm ngược theo mốc này (hold KHÔNG được gia hạn khi tải lại).
  hold_expires_at: string | null;
}

export interface BookingConfirmResult {
  job_title: string;
  start_at: string;
  end_at: string;
  // Để UI nói THẬT thay vì hứa một email có thể chưa gửi được.
  email_sent: boolean;
}

// Kết quả huỷ lịch của ứng viên (SCH-3 · PRD §10b.6, FR-BOOK-4).
export interface BookingCancelResult {
  // false = không có gì để huỷ (bấm hai lần / HR đã huỷ trước). TRẠNG THÁI, không phải lỗi.
  cancelled: boolean;
  job_title: string;
  // Liên kết cũ còn hạn → mời chọn giờ khác NGAY. Hết hạn → "Bộ phận Tuyển dụng sẽ liên hệ".
  // Hai câu dẫn tới hai hành vi hoàn toàn khác nhau nên UI không được đoán bừa.
  can_rebook: boolean;
  email_sent: boolean;
}
