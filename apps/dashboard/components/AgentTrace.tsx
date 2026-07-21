import type { ApplicationDetail } from "@ars/shared-types";

// Agent trace — trạng thái TỪNG NODE của pipeline cố định (PRD §5 trụ cột 1, §7).
//
// TRUNG THỰC VỀ DỮ LIỆU: backend CHƯA có endpoint nhật ký kiểm toán (audit_log nằm trong DB nhưng
// ApplicationRead không trả ra), nên ở đây KHÔNG có mốc thời gian/tool-call từng bước. Mọi trạng thái
// dưới đây SUY RA từ dữ liệu THẬT của hồ sơ (parsed_data · score · uncertainty_flags · screener_answers
// · status) — không bịa. Khi nào expose audit_log thì thay phần suy luận này bằng dữ liệu thật.

type NodeState = "done" | "active" | "failed" | "waiting" | "skipped" | "pending";

const STATE_STYLE: Record<NodeState, { ring: string; dot: string; text: string }> = {
  done: { ring: "border-ink bg-ink", dot: "text-canvas", text: "xong" },
  active: { ring: "border-accent bg-accent", dot: "text-white", text: "đang chạy" },
  failed: { ring: "border-red-500 bg-red-500", dot: "text-white", text: "lỗi" },
  waiting: { ring: "border-accent bg-canvas", dot: "text-accent", text: "đang chờ" },
  skipped: { ring: "border-divider bg-steel-200", dot: "text-ink/65", text: "bỏ qua" },
  pending: { ring: "border-divider bg-canvas", dot: "text-ink/30", text: "chưa chạy" },
};

function Glyph({ state }: { state: NodeState }) {
  const cls = "h-[15px] w-[15px]";
  const stroke = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  if (state === "done")
    return (
      <svg viewBox="0 0 24 24" className={cls} {...stroke} aria-hidden>
        <path d="M20 6 9 17l-5-5" />
      </svg>
    );
  if (state === "failed")
    return (
      <svg viewBox="0 0 24 24" className={cls} {...stroke} aria-hidden>
        <path d="M18 6 6 18" />
        <path d="m6 6 12 12" />
      </svg>
    );
  if (state === "skipped")
    return (
      <svg viewBox="0 0 24 24" className={cls} {...stroke} aria-hidden>
        <path d="M5 12h14" />
      </svg>
    );
  // active / waiting / pending → chấm tròn
  return <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />;
}

function deriveNodes(app: ApplicationDetail) {
  const flags = app.uncertainty_flags ?? [];
  const s = app.status;
  const decided = s === "INTERVIEW_SCHEDULED" || s === "REJECTED";
  const pastRanker = app.score != null || flags.includes("rank_failed") || decided;
  const answers = app.screener_answers ?? [];

  // parser
  let parser: NodeState = "pending";
  let parserNote = "Chưa chạy — hồ sơ vừa nộp.";
  if (flags.includes("parse_failed")) {
    parser = "failed";
    parserNote = "Không đọc/bóc tách được CV — hồ sơ chuyển HR xem xét.";
  } else if (app.parsed_data) {
    parser = "done";
    const nSkills = app.parsed_data.skills?.length ?? 0;
    const nExp = app.parsed_data.experiences?.length ?? 0;
    parserNote = `CV → JSON có cấu trúc: ${nSkills} kỹ năng, ${nExp} mốc kinh nghiệm.`;
  } else if (s === "PARSING") {
    parser = "active";
    parserNote = "Đang bóc tách CV thành dữ liệu có cấu trúc.";
  }

  // ranker
  let ranker: NodeState = "pending";
  let rankerNote = "Chờ dữ liệu bóc tách từ parser.";
  if (flags.includes("rank_failed")) {
    ranker = "failed";
    rankerNote = "Gọi LLM chấm điểm thất bại — chuyển HR xem xét.";
  } else if (app.score != null) {
    ranker = "done";
    const n = app.score_breakdown?.criteria?.length ?? 0;
    rankerNote = `Chấm ${n} tiêu chí rubric → điểm tổng ${app.score}/100.`;
  } else if (s === "RANKING") {
    ranker = "active";
    rankerNote = "Đang chấm rubric có suy luận.";
  }

  // screener (JD-2b: TÙY CHỌN — JD không câu hỏi thì bỏ qua)
  let screener: NodeState = "pending";
  let screenerNote = "Chờ kết quả chấm điểm.";
  if (answers.length > 0) {
    screener = "done";
    screenerNote = `Ứng viên đã trả lời ${answers.length} câu hỏi sàng lọc.`;
  } else if (flags.includes("no_response")) {
    screener = "failed";
    screenerNote = "Hết hạn không phản hồi — chuyển HR xem xét (KHÔNG tự từ chối).";
  } else if (s === "AWAITING_SCREENER" || s === "REMINDED") {
    screener = "waiting";
    screenerNote =
      s === "REMINDED"
        ? "Đã gửi nhắc — đang chờ ứng viên trả lời trước hạn."
        : "Đã gửi câu hỏi qua email — đang chờ ứng viên trả lời.";
  } else if (pastRanker && (decided || s === "PENDING_REVIEW")) {
    screener = "skipped";
    // KHÔNG khẳng định mù "JD không có câu hỏi": hồ sơ DƯỚI NGƯỠNG bị route_after_ranker đưa thẳng
    // sang human_review/auto-reject, KHÔNG BAO GIỜ tới screener — nói "bỏ qua vì JD không có câu hỏi"
    // là sai sự thật. recommendation (dẫn xuất từ điểm) phân biệt được: "consider_reject" ⟺ dưới
    // ngưỡng và không cờ; "invite" ⟺ đạt ngưỡng (tới đây tức JD không câu hỏi vì ca có câu hỏi đã
    // rẽ nhánh answers/AWAITING ở trên).
    if (app.recommendation === "consider_reject") {
      screenerNote = "Điểm dưới ngưỡng đạt → pipeline chuyển thẳng HR, không tới bước sàng lọc.";
    } else if (app.recommendation === "invite") {
      screenerNote = "Đạt ngưỡng nhưng JD không có câu hỏi sàng lọc → pipeline bỏ qua bước này.";
    } else {
      screenerNote = "Pipeline không đi qua bước sàng lọc ở hồ sơ này.";
    }
  } else if (s === "SCREENING") {
    screener = "active";
    screenerNote = "Đang khởi tạo vòng sàng lọc.";
  }

  // scheduler — điểm gửi thư DUY NHẤT
  let scheduler: NodeState = "pending";
  let schedulerNote = "Chờ quyết định (tự động hoặc HR).";
  if (s === "INTERVIEW_SCHEDULED") {
    scheduler = "done";
    schedulerNote = "Đã gửi thư mời phỏng vấn.";
  } else if (s === "REJECTED") {
    scheduler = "done";
    schedulerNote = "Đã gửi thư từ chối.";
  } else if (s === "SCHEDULING") {
    scheduler = "active";
    schedulerNote = "Đang gửi thư cho ứng viên.";
  }

  return [
    { key: "parser", label: "parser", state: parser, note: parserNote },
    { key: "ranker", label: "ranker", state: ranker, note: rankerNote },
    { key: "screener", label: "screener", state: screener, note: screenerNote },
    { key: "scheduler", label: "scheduler", state: scheduler, note: schedulerNote },
  ];
}

export function AgentTrace({ app }: { app: ApplicationDetail }) {
  const nodes = deriveNodes(app);
  const inReview = app.status === "PENDING_REVIEW";

  return (
    <section className="rounded-xl border-2 border-divider bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <h2 className="text-[20px]">Agent trace</h2>
        <span className="text-xs text-ink/65">parser → ranker → screener → scheduler</span>
      </div>

      <ol className="mt-4">
        {nodes.map((n, i) => {
          const st = STATE_STYLE[n.state];
          const last = i === nodes.length - 1;
          return (
            <li key={n.key} className="flex gap-3.5">
              <div className="flex flex-none flex-col items-center">
                <span
                  className={`flex h-[30px] w-[30px] items-center justify-center rounded-full border-2 ${st.ring} ${st.dot}`}
                >
                  <Glyph state={n.state} />
                </span>
                {!last && <span className="w-0.5 flex-1 bg-divider" style={{ minHeight: 18 }} />}
              </div>
              <div className={`min-w-0 flex-1 ${last ? "" : "pb-4"}`}>
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="font-heading text-[15px] font-bold">{n.label}</span>
                  <span className="text-xs text-ink/65">{st.text}</span>
                  {n.key === "ranker" && app.confidence != null && n.state === "done" && (
                    <span className="text-xs font-semibold text-accent">
                      confidence {app.confidence.toFixed(2)}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-[13px] leading-relaxed text-ink/80">{n.note}</p>
              </div>
            </li>
          );
        })}
      </ol>

      {/* Nhánh điểm dừng con người — chỉ hiện khi hồ sơ ĐANG chờ HR (chỉ báo hành động). */}
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

      <p className="mt-3 border-t border-divider pt-2.5 text-xs text-ink/65">
        Trạng thái từng node suy ra từ dữ liệu hồ sơ. Mốc thời gian + tool-call chi tiết nằm trong
        audit_log (chưa mở qua API).
      </p>
    </section>
  );
}
