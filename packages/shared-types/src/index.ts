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

export type PipelineBranch = "auto" | "human_review";

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

export interface AgentTraceStep {
  node: string;
  status: string | null;
  confidence: number | null;
  uncertainty_flags: string[];
  require_human_review: boolean;
}

export interface RunDemoResponse {
  branch: PipelineBranch;
  final_status: string;
  confidence: number | null;
  require_human_review: boolean;
  escalation_reason: string | null;
  trace: AgentTraceStep[];
  messages: string[];
}

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
