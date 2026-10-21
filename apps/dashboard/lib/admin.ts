import type {
  AuditLogPage,
  ConfigGroup,
  ConfigUpdateResult,
  ConfigValue,
  HealthMetrics,
} from "@ars/shared-types";
import { API_BASE, getJson } from "@/lib/api";

// Khu quản trị HR (/system) — 5 endpoint của `routes/admin.py` + đồng hồ đo của `routes/health.py`.
// Tách khỏi `lib/api.ts` vì đây là màn RIÊNG của một vai (HR ở vai quản trị), hiếm dùng, và không
// một trang nào khác gọi tới.

// ── Đọc (GET) — dùng LẠI `getJson`: nó đã lo cookie + 401 → /login ────────────
export const getAdminConfig = () => getJson<ConfigGroup[]>("/api/admin/config");

// Khoảng thời gian NỬA MỞ [createdFrom, createdTo) — ISO 8601 CÓ múi giờ (backend từ chối mốc trần,
// xem `admin._created_range`). Dựng bằng `vnDayStartIso`/`vnNextDayStartIso` của lib/datetime.
export type AuditLogRange = {
  createdFrom?: string;
  createdTo?: string;
};

export type AuditLogQuery = AuditLogRange & {
  node?: string;
  limit?: number;
  offset?: number;
  applicationId?: number;
};

// `URLSearchParams` mã hoá "+" của "+07:00" thành %2B. Ghép chuỗi tay thì "+" về server thành DẤU
// CÁCH và mọi lượt lọc ngày chết 422.
function setRange(p: URLSearchParams, r: AuditLogRange): void {
  if (r.createdFrom) p.set("created_from", r.createdFrom);
  if (r.createdTo) p.set("created_to", r.createdTo);
}

export function getAuditLog(q: AuditLogQuery = {}): Promise<AuditLogPage> {
  const p = new URLSearchParams();
  if (q.node) p.set("node", q.node);
  if (q.limit != null) p.set("limit", String(q.limit));
  if (q.offset != null) p.set("offset", String(q.offset));
  if (q.applicationId != null) p.set("application_id", String(q.applicationId));
  setRange(p, q);
  const qs = p.toString();
  return getJson<AuditLogPage>(`/api/admin/audit-log${qs ? `?${qs}` : ""}`);
}

// Nguồn cho bộ lọc: CHỈ node thực sự có dữ liệu, kèm số lượng (một câu GROUP BY, payload cỡ cố định).
// Nhận CÙNG khoảng ngày với danh sách — chip phải đếm đúng tập bảng đang hiện.
export function getAuditNodes(r: AuditLogRange = {}): Promise<Record<string, number>> {
  const p = new URLSearchParams();
  setRange(p, r);
  const qs = p.toString();
  return getJson<Record<string, number>>(`/api/admin/audit-log/nodes${qs ? `?${qs}` : ""}`);
}

// Đồng hồ đo bão hoà. KHÔNG nằm trong xô rate-limit nào (`hardening._bucket` so sánh ĐÚNG BẰNG
// `/api/health`, không trùm lên đường con) và KHÔNG chạm Postgres/Qdrant — khác hẳn `/api/health`
// mà `ServiceStatus` gọi.
export const getHealthMetrics = () => getJson<HealthMetrics>("/api/health/metrics");

// ── Ghi (PUT/DELETE) — PHẢI giữ nguyên văn `detail` của backend ───────────────
/**
 * Không dùng `putJson` của `lib/api`: hàm đó nuốt thân lỗi thành "HTTP 422 khi PUT /api/admin/config".
 * Nhưng ở đây 422 CHÍNH LÀ nội dung cần đọc — `config_registry.coerce()` trả câu tiếng Việt nói rõ ô
 * nào sai và vì sao ("Điểm đạt (ngưỡng qua vòng CV): phải từ 0 trở lên (nhận -5)."). Mất câu đó thì
 * HR nhìn màn hình mà không biết phải sửa ô nào.
 */
async function sendWithDetail<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: "include",
    ...(body === undefined
      ? {}
      : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  if (res.status === 401) {
    // Cùng cách xử như `lib/api`: hết phiên giữa chừng → về /login kèm ?next để quay lại đúng chỗ.
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `/login?next=${next}`;
    }
    throw new Error("Chưa đăng nhập");
  }
  if (!res.ok) {
    const detail = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `HTTP ${res.status} khi ${method} ${path}`);
  }
  return (await res.json()) as T;
}

// Cập nhật MỘT PHẦN: chỉ gửi những ô đã đổi. Sai một ô là backend KHÔNG lưu ô nào (all-or-nothing).
export const saveAdminConfig = (values: Record<string, ConfigValue>) =>
  sendWithDetail<ConfigUpdateResult>("PUT", "/api/admin/config", { values });

export const resetAdminConfig = (key: string) =>
  sendWithDetail<ConfigUpdateResult>("DELETE", `/api/admin/config/${encodeURIComponent(key)}`);

// ── Trợ giúp hiển thị ─────────────────────────────────────────────────────────
/**
 * Giá trị một ô ở dạng CHUỖI — dạng duy nhất `<input>`/`<select>` giữ được, và cũng là dạng gửi đi.
 *
 * CỐ Ý KHÔNG ép kiểu ở client: `config_registry.coerce()` mới là chỗ biết ô nào kiểu gì, và chỉ nó
 * sinh được câu lỗi tiếng Việt đúng ô. `parseFloat` ở đây sẽ biến một ô gõ hỏng thành `NaN` → JSON
 * `null` → thông điệp "không được để trống" SAI sự thật.
 */
export function configText(value: ConfigValue): string {
  return value == null ? "" : String(value);
}

/** Nhãn cho giá trị mặc định / lựa chọn rỗng. Chuỗi rỗng mà in ra "" thì trông như thiếu dữ liệu. */
export const BLANK_LABEL = "(để trống)";

export function configDefaultLabel(value: ConfigValue): string {
  const text = configText(value);
  return text === "" ? BLANK_LABEL : text;
}

// Nhãn tiếng Việt cho node trong nhật ký (xem docstring `routes/admin.py`); node lạ (dữ liệu cũ) rơi
// về chính chuỗi gốc thay vì biến mất. `gate` có mặt vì node gate cũng ghi audit (auto-từ-chối, và
// thư mời khi auto-mời).
const NODE_LABEL: Record<string, string> = {
  parser: "Đọc CV",
  ranker: "Chấm điểm",
  screener: "Sàng lọc",
  scheduler: "Gửi thư / đặt lịch",
  human_review: "HR duyệt",
  gate: "Chế độ tự động",
  system: "Hệ thống",
};

export function auditNodeLabel(node: string): string {
  return NODE_LABEL[node] ?? node;
}

// Nhãn cho `action`. Mã gốc VẪN hiện cạnh nhãn ở AuditLogTab — nó là khoá đối soát với code (grep
// ngược ra nơi ghi). Mã chưa có nhãn rơi về chính nó. Tên action tra từ các lệnh
// `audit_service.record(...)` của backend, KHÔNG đoán.
const ACTION_LABEL: Record<string, string> = {
  received: "Nhận hồ sơ",
  parsed: "Đọc CV xong",
  parse_failed: "Không đọc được CV",
  ranked: "Chấm điểm xong",
  rank_failed: "Chấm điểm bị lỗi",
  auto_reject: "Tự động từ chối",
  auto_invite: "Tự động mời",
  screener_skipped: "Bỏ qua bước sàng lọc",
  screener_resumed: "Nhận câu trả lời sàng lọc",
  screener_timeout: "Hết hạn trả lời sàng lọc",
  screener_resent: "Gửi lại thư sàng lọc",
  rejection_resent: "Gửi lại thư từ chối",
  queued_for_human_review: "Chuyển HR duyệt",
  // Lượt chạy ĐẦU ghi bước human_review bằng mã này (lượt resume thì ghi `queued_for_human_review`) —
  // nghĩa thật là "hồ sơ vào bước ở cột Bước".
  stub_pass_through: "Vào bước này",
  approve: "HR duyệt",
  reject: "HR từ chối",
  error: "Lỗi kỹ thuật",
  stuck_reconciled: "Xử lý hồ sơ bị kẹt",
  booking_invite_sent: "Gửi thư mời đặt lịch",
  booking_invite_failed: "Gửi thư mời đặt lịch thất bại",
  booking_confirmed: "Ứng viên chốt lịch",
  booking_cancelled: "Huỷ lịch phỏng vấn",
  booking_no_slots: "Hết khung giờ trống",
  booking_no_response: "Ứng viên không chọn giờ",
  email_failed: "Gửi thư thất bại",
  email_send_failed: "Dịch vụ gửi thư báo lỗi",
  email_bounced: "Thư bị trả về",
  email_complained: "Ứng viên báo thư là spam",
  config_updated: "Đổi cấu hình",
  config_reset: "Khôi phục cấu hình mặc định",
};

// Hai họ action có hậu tố: `route:<nhánh>` (background) và `email_sent:<loại thư>` (scheduler).
const ROUTE_LABEL: Record<string, string> = {
  screener: "sàng lọc",
  human_review: "HR duyệt",
  auto_reject: "tự động từ chối",
  auto_invite: "tự động mời",
};

const EMAIL_KIND_LABEL: Record<string, string> = {
  invite: "thư mời",
  reject: "thư từ chối",
  screener: "câu hỏi sàng lọc",
  screener_reminder: "thư nhắc trả lời sàng lọc",
  booking_confirmed: "thư xác nhận lịch",
  interview_reminder: "thư nhắc phỏng vấn",
  booking_reminder: "thư nhắc chọn lịch",
  booking_cancelled: "thư báo huỷ lịch",
};

export function auditActionLabel(action: string): string {
  const known = ACTION_LABEL[action];
  if (known) return known;
  const sep = action.indexOf(":");
  if (sep > 0) {
    const head = action.slice(0, sep);
    const tail = action.slice(sep + 1);
    if (head === "route") return `Chuyển sang ${ROUTE_LABEL[tail] ?? tail}`;
    if (head === "email_sent") return `Đã gửi ${EMAIL_KIND_LABEL[tail] ?? tail}`;
  }
  return action;
}

// Một số lượt ghi đặt MÃ vào cột lý do thay vì câu chữ (vd `technical_error`, `no_slots`) — dịch
// những mã đó; câu tiếng Việt đầy đủ thì giữ nguyên.
const REASON_CODE_LABEL: Record<string, string> = {
  technical_error: "Lỗi kỹ thuật khi xử lý hồ sơ",
  resume_error: "Lỗi kỹ thuật khi xử lý câu trả lời sàng lọc",
  stuck_pipeline: "Hồ sơ bị kẹt quá lâu ở một bước",
  invite_email_failed: "Gửi thư mời thất bại",
  booking_email_failed: "Gửi thư xác nhận lịch thất bại",
  no_slots: "Hết khung giờ trống",
  booking_cancelled: "Lịch phỏng vấn bị huỷ",
  email_bounced: "Thư bị trả về",
  email_complained: "Ứng viên báo thư là spam",
  email_send_failed: "Dịch vụ gửi thư báo lỗi",
};

export function auditReasonLabel(reason: string): string {
  return REASON_CODE_LABEL[reason] ?? reason;
}
