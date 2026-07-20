import type { ApplicationDetail, AuditEntry } from "@ars/shared-types";

// Agent trace — nhật ký kiểm toán THẬT của pipeline cố định (PRD §5 trụ cột 1, §16).
//
// Dữ liệu lấy từ `GET /api/applications/{id}/audit` (bảng audit_log): mỗi dòng là một bước do chính
// pipeline ghi lại lúc chạy — node, hành động, confidence, cờ bất định, lý do leo thang. KHÔNG suy
// đoán từ trạng thái hồ sơ nữa.
//
// TRUNG THỰC VỀ THỜI GIAN: `created_at` dùng `now()` của Postgres = mốc BẮT ĐẦU GIAO DỊCH, nên các
// bước được commit chung một giao dịch mang CÙNG một mốc. Vì vậy ở đây chỉ hiện mốc thời gian, TUYỆT
// ĐỐI không tính "bước này mất bao lâu" — con số đó sẽ là bịa.

// THUẦN presentational: nhận prop, KHÔNG tự fetch (trang chi tiết lo useQuery).
interface AgentTraceProps {
  app: ApplicationDetail;
  entries: AuditEntry[] | undefined;
  isLoading?: boolean;
  isError?: boolean;
}

type Tone = "ok" | "danger" | "accent" | "neutral";

const TONE: Record<Tone, { ring: string; ink: string }> = {
  ok: { ring: "border-ink bg-ink text-canvas", ink: "text-ink" },
  danger: { ring: "border-red-500 bg-red-500 text-white", ink: "text-red-600" },
  accent: { ring: "border-accent bg-accent text-white", ink: "text-accent" },
  neutral: { ring: "border-divider bg-canvas text-ink/45", ink: "text-ink/60" },
};

// Nhãn tiếng Việt cho từng `action` backend ghi. Khớp các chỗ gọi audit_service.record:
// tasks/background.py · services/review.py · services/screening_timeout.py · agents/nodes/scheduler.py
const ACTION: Record<string, { label: string; tone: Tone }> = {
  received: { label: "Đã nhận hồ sơ — đưa vào pipeline", tone: "neutral" },
  parsed: { label: "Bóc tách CV thành dữ liệu có cấu trúc", tone: "ok" },
  parse_failed: { label: "Không đọc được CV", tone: "danger" },
  ranked: { label: "Chấm điểm theo rubric của JD", tone: "ok" },
  rank_failed: { label: "Gọi LLM chấm điểm thất bại", tone: "danger" },
  auto_reject: { label: "Gate tự-từ-chối: điểm dưới ngưỡng", tone: "accent" },
  auto_invite: { label: "Gate tự-mời: hồ sơ sạch và đạt ngưỡng", tone: "accent" },
  auto_invite_failed: { label: "Gate tự-mời: gửi thư mời thất bại", tone: "danger" },
  screener_skipped: { label: "Bỏ qua sàng lọc — JD không có câu hỏi", tone: "neutral" },
  screener_timeout: { label: "Hết hạn sàng lọc — ứng viên không phản hồi", tone: "danger" },
  screener_resumed: { label: "Ứng viên đã trả lời — chạy tiếp từ điểm dừng", tone: "ok" },
  queued_for_human_review: { label: "Đưa vào hàng đợi HR xem xét", tone: "accent" },
  stub_pass_through: { label: "Đi qua node (chưa có xử lý)", tone: "neutral" },
  approve: { label: "HR duyệt → giao scheduler mời phỏng vấn", tone: "ok" },
  reject: { label: "HR từ chối → giao scheduler gửi thư từ chối", tone: "accent" },
  email_failed: { label: "Gửi email thất bại", tone: "danger" },
  error: { label: "Lỗi kỹ thuật — chuyển HR xem xét", tone: "danger" },
};

const ROUTE: Record<string, string> = {
  human_review: "Định tuyến → HR xem xét",
  auto_reject: "Định tuyến → tự động từ chối",
  auto_invite: "Định tuyến → tự động mời",
  screener: "Định tuyến → sàng lọc",
  error: "Định tuyến → lỗi",
};

// Khoá = giá trị `mode` ở agents/nodes/scheduler.py (notify_decision: invite|reject;
// notify_screener: screener|screener_reminder) — KHÔNG phải tên tự đặt.
const EMAIL: Record<string, string> = {
  invite: "Đã gửi thư mời phỏng vấn",
  reject: "Đã gửi thư từ chối",
  screener: "Đã gửi email câu hỏi sàng lọc",
  screener_reminder: "Đã gửi email nhắc trả lời sàng lọc",
};

function describe(node: string, action: string): { label: string; tone: Tone } {
  // Lần chạy ĐẦU, background.py rơi node human_review vào nhánh `else` nên ghi "stub_pass_through"
  // — trong khi node đó THẬT SỰ đặt PENDING_REVIEW + lý do. Dịch thẳng sẽ thành "chưa có xử lý",
  // sai sự thật. Đường resume ghi đúng tên (`queued_for_human_review`); ở đây gộp về cùng nghĩa.
  if (node === "human_review" && action === "stub_pass_through") {
    return ACTION.queued_for_human_review;
  }
  const known = ACTION[action];
  if (known) return known;
  // Hành động có tham số: "route:<nhánh>" và "email_sent:<loại>".
  if (action.startsWith("route:")) {
    const branch = action.slice("route:".length);
    return { label: ROUTE[branch] ?? `Định tuyến → ${branch}`, tone: "accent" };
  }
  if (action.startsWith("email_sent:")) {
    const mode = action.slice("email_sent:".length);
    return { label: EMAIL[mode] ?? `Đã gửi email (${mode})`, tone: "ok" };
  }
  return { label: action, tone: "neutral" }; // chưa có nhãn → hiện thô, không nuốt sự kiện
}

function timeOf(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    day: "2-digit",
    month: "2-digit",
  });
}

// Vài trường trong `detail` đáng hiện thẳng cho HR — số liệu, không phải nội bộ kỹ thuật.
// Tên khoá khớp CHÍNH XÁC nơi backend ghi: tasks/background.py (`_parsed_summary`, nhánh ranker),
// services/review.py (`note`), agents/nodes/scheduler.py (`to`, `error`).
function facts(entry: AuditEntry): string[] {
  const d = entry.detail ?? {};
  const out: string[] = [];
  if (typeof d.score === "number") out.push(`điểm ${d.score}/100`);
  if (typeof d.semantic_similarity === "number")
    out.push(`tương đồng ngữ nghĩa ${d.semantic_similarity.toFixed(2)}`);
  if (typeof d.skills_count === "number") out.push(`${d.skills_count} kỹ năng`);
  if (typeof d.experiences_count === "number")
    out.push(`${d.experiences_count} mốc kinh nghiệm`);
  if (typeof d.education_count === "number") out.push(`${d.education_count} mốc học vấn`);
  if (typeof d.to === "string") out.push(`gửi tới ${d.to}`);
  if (typeof d.note === "string" && d.note.trim()) out.push(`ghi chú: “${d.note.trim()}”`);
  if (typeof d.error === "string" && d.error.trim()) out.push(`lỗi: ${d.error.trim()}`);
  return out;
}

function Glyph({ tone }: { tone: Tone }) {
  const stroke = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  if (tone === "danger")
    return (
      <svg viewBox="0 0 24 24" className="h-[13px] w-[13px]" {...stroke} aria-hidden>
        <path d="M18 6 6 18" />
        <path d="m6 6 12 12" />
      </svg>
    );
  if (tone === "ok")
    return (
      <svg viewBox="0 0 24 24" className="h-[13px] w-[13px]" {...stroke} aria-hidden>
        <path d="M20 6 9 17l-5-5" />
      </svg>
    );
  return <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />;
}

export function AgentTrace({ app, entries, isLoading, isError }: AgentTraceProps) {
  const inReview = app.status === "PENDING_REVIEW";
  const rows = entries ?? [];

  return (
    <section className="rounded-xl border-2 border-divider bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <h2 className="text-[20px]">Agent trace</h2>
        <span className="text-xs text-ink/50">parser → ranker → screener → scheduler</span>
      </div>

      {isLoading && <p className="mt-4 text-[13px] text-ink/50">Đang tải nhật ký kiểm toán…</p>}
      {isError && (
        <p className="mt-4 rounded-lg border-2 border-red-200 bg-red-50 px-4 py-2.5 text-[13px] text-red-700">
          Không tải được nhật ký kiểm toán của hồ sơ này.
        </p>
      )}
      {!isLoading && !isError && rows.length === 0 && (
        <p className="mt-4 text-[13px] text-ink/50">
          Chưa có bước nào được ghi — hồ sơ vừa nộp, pipeline chưa chạy xong.
        </p>
      )}

      {rows.length > 0 && (
        <ol className="mt-4">
          {rows.map((e, i) => {
            const { label, tone } = describe(e.node, e.action);
            const st = TONE[tone];
            const last = i === rows.length - 1;
            const detailFacts = facts(e);
            return (
              <li key={e.id} className="flex gap-3.5">
                <div className="flex flex-none flex-col items-center">
                  <span
                    className={`flex h-[26px] w-[26px] items-center justify-center rounded-full border-2 ${st.ring}`}
                  >
                    <Glyph tone={tone} />
                  </span>
                  {!last && <span className="w-0.5 flex-1 bg-divider" style={{ minHeight: 14 }} />}
                </div>

                <div className={`min-w-0 flex-1 ${last ? "" : "pb-3.5"}`}>
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span className="font-heading text-[14px] font-bold">{e.node}</span>
                    <time dateTime={e.created_at} className="text-xs tabular-nums text-ink/45">
                      {timeOf(e.created_at)}
                    </time>
                    {e.confidence != null && (
                      <span className="text-xs font-semibold text-accent">
                        confidence {e.confidence.toFixed(2)}
                      </span>
                    )}
                  </div>

                  <p className={`mt-0.5 text-[13px] leading-relaxed ${st.ink}`}>{label}</p>

                  {detailFacts.length > 0 && (
                    <p className="mt-0.5 text-xs text-ink/55">{detailFacts.join(" · ")}</p>
                  )}

                  {e.uncertainty_flags.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {e.uncertainty_flags.map((f) => (
                        <span
                          key={f}
                          className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-semibold text-amber-800"
                        >
                          {f}
                        </span>
                      ))}
                    </div>
                  )}

                  {e.escalation_reason?.trim() && (
                    <p className="mt-1.5 border-l-2 border-divider pl-2.5 text-xs text-ink/65">
                      {e.escalation_reason}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {/* Điểm dừng con người — chỉ hiện khi hồ sơ ĐANG chờ HR (chỉ báo hành động). */}
      {inReview && (
        <div className="mt-1 flex items-center gap-3 rounded-lg border-2 border-accent bg-accent-100 px-4 py-3">
          <svg
            viewBox="0 0 24 24"
            className="h-5 w-5 flex-none text-accent-800"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M18 21a8 8 0 0 0-16 0" />
            <circle cx="10" cy="8" r="5" />
          </svg>
          <p className="text-[13px] font-semibold text-accent-800">
            human_review · đang chờ HR quyết định
          </p>
        </div>
      )}

      {rows.length > 0 && (
        <p className="mt-3 border-t border-divider pt-2.5 text-xs text-ink/45">
          Ghi trực tiếp từ bảng <span className="font-semibold">audit_log</span> (append-only). Các
          bước lưu chung một giao dịch dùng chung mốc thời gian, nên đây là thứ tự thực thi — không
          phải thời lượng từng bước.
        </p>
      )}
    </section>
  );
}
