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

export type AuditLogQuery = {
  node?: string;
  limit?: number;
  offset?: number;
  applicationId?: number;
};

export function getAuditLog(q: AuditLogQuery = {}): Promise<AuditLogPage> {
  const p = new URLSearchParams();
  if (q.node) p.set("node", q.node);
  if (q.limit != null) p.set("limit", String(q.limit));
  if (q.offset != null) p.set("offset", String(q.offset));
  if (q.applicationId != null) p.set("application_id", String(q.applicationId));
  const qs = p.toString();
  return getJson<AuditLogPage>(`/api/admin/audit-log${qs ? `?${qs}` : ""}`);
}

// Nguồn cho bộ lọc: CHỈ node thực sự có dữ liệu, kèm số lượng (một câu GROUP BY, payload cỡ cố định).
export const getAuditNodes = () => getJson<Record<string, number>>("/api/admin/audit-log/nodes");

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

// Nhãn tiếng Việt cho node trong nhật ký. Chỉ 6 node (xem docstring `routes/admin.py`); node lạ
// (dữ liệu cũ) rơi về chính chuỗi gốc thay vì biến mất.
const NODE_LABEL: Record<string, string> = {
  parser: "Bóc tách CV",
  ranker: "Chấm điểm",
  screener: "Sàng lọc",
  scheduler: "Gửi thư / đặt lịch",
  human_review: "HR duyệt",
  system: "Hệ thống",
};

export function auditNodeLabel(node: string): string {
  return NODE_LABEL[node] ?? node;
}
