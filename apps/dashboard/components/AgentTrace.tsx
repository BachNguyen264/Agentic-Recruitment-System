import type { ApplicationDetail } from "@ars/shared-types";

// Agent trace — trạng thái TỪNG NODE của pipeline cố định (PRD §5 trụ cột 1, §7).
//
// TRUNG THỰC VỀ DỮ LIỆU: ApplicationRead không trả audit_log (nhật ký chỉ đọc được ở /system → Nhật
// ký kiểm toán), nên ở đây KHÔNG có mốc thời gian/tool-call từng bước. Mọi trạng thái dưới đây SUY
// RA từ dữ liệu THẬT của hồ sơ (parsed_data · score · uncertainty_flags · screener_answers · status)
// — không bịa. Khi nào chi tiết hồ sơ đọc audit_log thì thay phần suy luận này bằng dữ liệu thật.

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
  // SCH-2: AWAITING_BOOKING = ĐÃ quyết mời + ĐÃ gửi thư, chỉ còn chờ ứng viên chọn giờ. Xếp chung
  // với "đã quyết" cho các bước TRƯỚC scheduler, nếu không trace sẽ vẽ ranker/screener như đang chờ.
  const invited = s === "AWAITING_BOOKING";
  const pastRanker = app.score != null || flags.includes("rank_failed") || decided || invited;
  const answers = app.screener_answers ?? [];

  // parser
  let parser: NodeState = "pending";
  let parserNote = "Chưa chạy — hồ sơ vừa nộp.";
  if (flags.includes("parse_failed")) {
    parser = "failed";
    parserNote = "Không đọc được CV — hồ sơ chuyển HR xem xét.";
  } else if (app.parsed_data) {
    parser = "done";
    const nSkills = app.parsed_data.skills?.length ?? 0;
    const nExp = app.parsed_data.experiences?.length ?? 0;
    parserNote = `Đã đọc CV: ${nSkills} kỹ năng, ${nExp} mục kinh nghiệm.`;
  } else if (s === "PARSING") {
    parser = "active";
    parserNote = "Đang đọc CV và trích thông tin.";
  }

  // ranker
  let ranker: NodeState = "pending";
  let rankerNote = "Chờ bước đọc CV xong.";
  if (flags.includes("rank_failed")) {
    ranker = "failed";
    rankerNote = "Chấm điểm bị lỗi — chuyển HR xem xét.";
  } else if (app.score != null) {
    ranker = "done";
    const n = app.score_breakdown?.criteria?.length ?? 0;
    rankerNote = `Chấm ${n} tiêu chí của JD → điểm tổng ${app.score}/100.`;
  } else if (s === "RANKING") {
    ranker = "active";
    rankerNote = "Đang chấm điểm theo tiêu chí của JD.";
  }

  // screener (JD-2b: TÙY CHỌN — JD không câu hỏi thì bỏ qua)
  let screener: NodeState = "pending";
  let screenerNote = "Chờ kết quả chấm điểm.";
  if (answers.length > 0) {
    screener = "done";
    // Chỉ đường tới khối câu trả lời: trên trang chi tiết nó nằm DƯỚI khối điểm (dài) — HR hỏi
    // "câu trả lời nằm đâu" là đã bỏ lỡ nó một lần.
    screenerNote = `Ứng viên đã trả lời ${answers.length} câu hỏi sàng lọc — xem mục "Câu trả lời sàng lọc" bên dưới.`;
  } else if (flags.includes("no_response")) {
    screener = "failed";
    screenerNote = "Ứng viên không trả lời trong thời hạn — chuyển HR xem xét (không tự động từ chối).";
  } else if (s === "AWAITING_SCREENER" && flags.includes("email_send_failed")) {
    // Dịch vụ gửi TỪ CHỐI thư câu hỏi: hồ sơ vẫn đứng ở AWAITING_SCREENER (đúng thiết kế, để HR gửi
    // lại được) nhưng ứng viên có thể CHƯA TỪNG có link. Vẽ "đang chờ ứng viên" ở đây là trạng thái
    // nói dối — đúng thứ trace này cam kết không làm (quan sát thật trên prod 06/10/2026).
    screener = "failed";
    screenerNote = "Thư câu hỏi KHÔNG gửi được — ứng viên có thể chưa nhận được link (xem cảnh báo phía trên).";
  } else if (s === "AWAITING_SCREENER") {
    // Không tách nhánh "đã nhắc": nhắc là SỰ KIỆN chứ không phải trạng thái, hồ sơ vẫn đứng nguyên ở
    // AWAITING_SCREENER (mốc nằm ở `screening_session.reminded_at`). Nhánh cũ không bao giờ chạy.
    screener = "waiting";
    screenerNote = "Đã gửi câu hỏi qua email — đang chờ ứng viên trả lời.";
  } else if (pastRanker && (decided || invited || s === "PENDING_REVIEW")) {
    screener = "skipped";
    // KHÔNG khẳng định mù "JD không có câu hỏi": hồ sơ DƯỚI NGƯỠNG bị route_after_ranker đưa thẳng
    // sang human_review/auto-reject, KHÔNG BAO GIỜ tới screener — nói "bỏ qua vì JD không có câu hỏi"
    // là sai sự thật. recommendation (dẫn xuất từ điểm) phân biệt được: "consider_reject" ⟺ dưới
    // ngưỡng và không cờ; "invite" ⟺ đạt ngưỡng (tới đây tức JD không câu hỏi vì ca có câu hỏi đã
    // rẽ nhánh answers/AWAITING ở trên).
    // Ca dưới ngưỡng đã REJECTED có thể do gate auto-từ-chối HOẶC do HR từ chối sau review — dữ liệu
    // hồ sơ không phân biệt được, nên chỉ nói điều đúng cho cả hai (prod 18/10: ca gate tự từ chối
    // từng hiện "chuyển thẳng HR").
    if (app.recommendation === "consider_reject" && s === "PENDING_REVIEW") {
      screenerNote = "Điểm dưới ngưỡng đạt → chuyển thẳng HR duyệt, không qua bước sàng lọc.";
    } else if (app.recommendation === "consider_reject") {
      screenerNote = "Điểm dưới ngưỡng đạt → hồ sơ không đi tới bước sàng lọc.";
    } else if (app.recommendation === "invite") {
      screenerNote = "Đạt ngưỡng nhưng JD không có câu hỏi sàng lọc → bỏ qua bước này.";
    } else {
      screenerNote = "Hồ sơ này không đi qua bước sàng lọc.";
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
    // SCH-2: tới được đây nghĩa là ứng viên đã TỰ CHỌN giờ (không phải HR chốt hộ) — PRD §10b.
    // KHÔNG khẳng định họ đã nhận thư xác nhận: booking_flow gắn escalation_reason đúng khi gửi
    // hỏng, và nói bừa "đã nhận" ở đây khiến HR bỏ qua ca cần gọi tay.
    schedulerNote = app.escalation_reason?.trim()
      ? "Ứng viên đã chọn giờ, nhưng thư xác nhận CHƯA gửi được — cần báo thủ công."
      : "Đã gửi thư mời; ứng viên đã chọn giờ và nhận thư xác nhận kèm lịch.";
  } else if (s === "AWAITING_BOOKING") {
    // Thư mời + link ĐÃ tới tay ứng viên. Để rơi vào nhánh mặc định "chờ quyết định" là nói dối:
    // quyết định xong lâu rồi, quả bóng đang ở sân ứng viên và HR không phải làm gì cả.
    scheduler = "waiting";
    schedulerNote = "Đã gửi thư mời kèm link đặt lịch — đang chờ ứng viên chọn giờ.";
  } else if (s === "REJECTED" && flags.includes("email_send_failed")) {
    // Quyết định đã ghi nhưng dịch vụ gửi TỪ CHỐI lá thư — "Đã gửi thư từ chối" ở đây là nói dối
    // đúng loại mà nhánh screener phía trên cũng vừa sửa (prod 06/10/2026).
    scheduler = "failed";
    schedulerNote = "Đã quyết định từ chối, nhưng thư từ chối KHÔNG gửi được — ứng viên chưa được báo kết quả (xem cảnh báo phía trên).";
  } else if (s === "REJECTED") {
    scheduler = "done";
    schedulerNote = "Đã gửi thư từ chối.";
  } else if (s === "SCHEDULING") {
    scheduler = "active";
    schedulerNote = "Đang gửi thư cho ứng viên.";
  }

  return [
    { key: "parser", label: "Parser", state: parser, note: parserNote },
    { key: "ranker", label: "Ranker", state: ranker, note: rankerNote },
    { key: "screener", label: "Screener", state: screener, note: screenerNote },
    { key: "scheduler", label: "Scheduler", state: scheduler, note: schedulerNote },
  ];
}

export function AgentTrace({ app }: { app: ApplicationDetail }) {
  const nodes = deriveNodes(app);
  const inReview = app.status === "PENDING_REVIEW";

  return (
    <section className="rounded-xl border-2 border-divider bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <h2 className="text-[20px]">Quá trình xử lý</h2>
        <span className="text-xs text-ink/65">Parser → Ranker → Screener → Scheduler</span>
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
                      độ tin cậy {app.confidence.toFixed(2)}
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
            Human review · đang chờ HR quyết định
          </p>
        </div>
      )}

      <p className="mt-3 border-t border-divider pt-2.5 text-xs text-ink/65">
        Trạng thái từng bước suy ra từ dữ liệu hồ sơ. Mốc thời gian chi tiết xem ở Cấu hình → Nhật
        ký kiểm toán.
      </p>
    </section>
  );
}
