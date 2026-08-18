"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import type { ApplicationStatus, JobPosting, PipelineSnapshot } from "@ars/shared-types";
import { ServiceStatus } from "@/components/ServiceStatus";
import { getJobs, getPipeline } from "@/lib/api";

// Bảng điều hành (PRD §12.1 FR-HR-DASH-1) — giám sát pipeline thời gian thực.
// MỌI con số dẫn xuất từ dữ liệu THẬT (/api/applications/pipeline, /api/jobs). Không có số minh họa.

// NHỊP LÀM TƯƠI THÍCH ỨNG. Trước đây trang này gọi `GET /api/applications` cứ 5 giây một lần, mãi
// mãi, kể cả khi hệ thống rỗng — trả về TOÀN BỘ hồ sơ kèm parsed_data chỉ để vẽ vài con số. Nay hỏi
// endpoint ảnh chụp (cỡ cố định) và chỉ hỏi DỒN khi thực sự có hồ sơ đang chạy: pipeline rỗng thì
// dashboard gần như nằm im. TanStack v5 mặc định KHÔNG chạy interval khi cửa sổ mất focus, nên tab
// nền cũng không tiêu gì.
const REFRESH_RUNNING_MS = 2_000; // parser ~9s, ranker ~25s → 2s là đủ thấy từng chặng
// Nhịp lúc rỗi phải NGẮN HƠN chặng ngắn nhất của pipeline (parser ~10s đo thật). Để 15s thì một CV
// nộp ngay sau một nhịp có thể chạy hết parser trước lượt hỏi kế tiếp — HR mở dashboard nhìn thẳng
// vào màn hình mà không thấy ô parser sáng lần nào. Đây là lỗi bắt được khi chạy thử bằng trình
// duyệt, không phải suy luận: cái giá của 6s chỉ là ~250 byte mỗi lượt (payload cỡ cố định).
const REFRESH_IDLE_MS = 6_000;

// Trạng thái đang chạy trong pipeline (chưa tới điểm dừng người/kết thúc) — PRD §13.
// PHẢI khớp `DASHBOARD_ACTIVE_STATUSES` ở backend (`models/application.py`): backend dùng nó để chọn
// danh sách `active`, frontend dùng để đếm và để quyết định nhịp hỏi. Lệch nhau thì con số "Đang xử
// lý" và danh sách bên dưới nói hai chuyện khác nhau.
const IN_FLIGHT: ApplicationStatus[] = [
  "SUBMITTED", "PARSING", "RANKING", "SCREENING", "AWAITING_SCREENER", "REMINDED", "SCHEDULING",
  // SCH-2: thư mời + link đã gửi, đang chờ ứng viên tự chọn giờ — vẫn là "đang chạy", chưa kết thúc.
  "AWAITING_BOOKING",
];

// Nút pipeline cố định (PRD §5 trụ cột 1): parser → ranker → screener → scheduler.
const NODES: { key: string; label: string; caption: string; statuses: ApplicationStatus[]; icon: React.ReactNode }[] = [
  {
    key: "parser", label: "parser", caption: "CV → JSON có cấu trúc",
    statuses: ["SUBMITTED", "PARSING"],
    icon: (
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path d="M14 2v5h5" />
      </svg>
    ),
  },
  {
    key: "ranker", label: "ranker", caption: "Chấm rubric — nút quyết định",
    statuses: ["RANKING"],
    icon: (
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 3v16a2 2 0 0 0 2 2h16" /><path d="M18 17V9" /><path d="M13 17V5" /><path d="M8 17v-3" />
      </svg>
    ),
  },
  {
    key: "screener", label: "screener", caption: "Hỏi đáp qua email — bất đồng bộ",
    statuses: ["SCREENING", "AWAITING_SCREENER", "REMINDED"],
    icon: (
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <rect width="20" height="16" x="2" y="4" rx="2" /><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
      </svg>
    ),
  },
  {
    key: "scheduler", label: "scheduler", caption: "Điểm gửi thư DUY NHẤT",
    statuses: ["SCHEDULING", "AWAITING_BOOKING"],
    icon: (
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M8 2v4" /><path d="M16 2v4" /><rect width="18" height="18" x="3" y="4" rx="2" /><path d="M3 10h18" />
      </svg>
    ),
  },
];

const STATUS_LABEL: Record<string, string> = {
  SUBMITTED: "Vừa nộp", PARSING: "Đang bóc tách", RANKING: "Đang chấm điểm",
  SCREENING: "Đang sàng lọc", AWAITING_SCREENER: "Chờ ứng viên trả lời",
  REMINDED: "Đã nhắc", SCHEDULING: "Đang gửi thư", AWAITING_BOOKING: "Chờ chọn lịch",
  PENDING_REVIEW: "Chờ HR duyệt", INTERVIEW_SCHEDULED: "Đã hẹn PV", REJECTED: "Đã từ chối",
};

function initialsOf(email: string): string {
  const name = email.split("@")[0] ?? "";
  const parts = name.split(/[._-]+/).filter(Boolean);
  return ((parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2)) || "??").toUpperCase();
}

function StatTile({
  label, value, caption, action, accent = false,
}: {
  label: string; value: number; caption?: string; action?: React.ReactNode; accent?: boolean;
}) {
  return (
    <div className={`rounded-xl border-2 p-4 ${accent ? "border-accent bg-accent" : "border-divider bg-surface"}`}>
      {/* text-white đặc trên accent (#1f6feb) = 4.63:1 ĐẠT AA; white/80 chỉ 3.54:1 (trượt, chữ nhỏ) */}
      <p className={`text-xs font-semibold uppercase tracking-[0.08em] ${accent ? "text-white" : "text-ink/65"}`}>
        {label}
      </p>
      <p className={`mt-2.5 font-heading text-[40px] font-bold leading-none ${accent ? "text-white" : ""}`}>
        {value}
      </p>
      {action ?? <p className={`mt-1.5 text-[13px] ${accent ? "text-white" : "text-ink/65"}`}>{caption}</p>}
    </div>
  );
}

// Một ô node trong pipeline. `running` = có hồ sơ đang đứng ở node này NGAY BÂY GIỜ.
// Mọi hiệu ứng đều nằm sau `motion-safe:` — người bật "giảm chuyển động" của hệ điều hành vẫn phải
// đọc được trạng thái, nên chữ "đang chạy" (không phải animation) mới là tín hiệu chính thức.
function NodeCard({
  label, caption, icon, count, running,
}: {
  label: string; caption: string; icon: React.ReactNode; count: number; running: boolean;
}) {
  return (
    <div
      className={`flex min-w-0 flex-1 flex-col gap-2 rounded-lg border-2 bg-canvas p-3 ${
        running ? "border-accent motion-safe:animate-pulse-ring" : "border-divider"
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`flex h-[26px] w-[26px] flex-none items-center justify-center rounded ${
            running ? "bg-accent text-white" : "bg-steel-200 text-ink/70"
          }`}
        >
          {icon}
        </span>
        <span className="font-heading text-[13px] font-bold">{label}</span>
        {running && (
          <span className="ml-auto flex-none rounded bg-accent-100 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-accent-800">
            đang chạy
          </span>
        )}
      </div>
      {/* `key={count}` để React gắn phần tử MỚI mỗi lần số đổi — đó là cách phát lại animation nảy
          mà không cần state/timer nào. */}
      <p key={count} className="font-heading text-[30px] font-bold leading-none motion-safe:animate-count-pop">
        {count}
      </p>
      <p className="text-xs leading-snug text-ink/65">{caption}</p>
      {/* Thanh chạy vô định: node đang làm việc nhưng không biết trước bao lâu. Luôn chiếm chỗ (kể
          cả lúc rỗi) để ô không nhảy layout mỗi khi hồ sơ đi qua. */}
      <div className="mt-auto h-1 overflow-hidden rounded-full bg-steel-200" aria-hidden>
        {running && (
          <div className="h-full w-1/3 rounded-full bg-accent motion-safe:animate-indeterminate" />
        )}
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { data: snapshot, isLoading, isError } = useQuery<PipelineSnapshot>({
    queryKey: ["pipeline"],
    queryFn: getPipeline,
    // Nhịp quyết định bằng CHÍNH dữ liệu vừa nhận: còn hồ sơ đang chạy thì bám sát, hết thì thả ra.
    refetchInterval: (query) => {
      const counts = query.state.data?.counts;
      if (!counts) return REFRESH_IDLE_MS;
      return IN_FLIGHT.some((s) => (counts[s] ?? 0) > 0) ? REFRESH_RUNNING_MS : REFRESH_IDLE_MS;
    },
  });
  const { data: jobs } = useQuery<JobPosting[]>({ queryKey: ["jobs", "active"], queryFn: () => getJobs() });

  const counts = snapshot?.counts;
  const countOf = (statuses: ApplicationStatus[]) =>
    statuses.reduce((sum, s) => sum + (counts?.[s] ?? 0), 0);

  const cProcessing = countOf(IN_FLIGHT);
  const cReview = countOf(["PENDING_REVIEW"]);
  const cPassed = countOf(["INTERVIEW_SCHEDULED"]);
  const cRejected = countOf(["REJECTED"]);
  const cDone = cPassed + cRejected;
  const anyRunning = cProcessing > 0;

  const jobTitle = new Map((jobs ?? []).map((j) => [j.id, j.title]));
  const inflight = snapshot?.active ?? [];

  const autoReject = (jobs ?? []).filter((j) => j.gate_config.auto_reject).length;
  const autoInvite = (jobs ?? []).filter((j) => j.gate_config.auto_invite).length;
  const gateLabel = (n: number) => (n > 0 ? `${n} JD bật` : "Tắt toàn hệ thống");

  return (
    <div className="mx-auto max-w-[1120px] px-4 pb-8 pt-6 sm:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow mb-1.5">Giám sát pipeline · thời gian thực</p>
          <h1 className="text-[28px] sm:text-[38px]">Bảng điều hành</h1>
        </div>
        {/* Nói ĐÚNG nhịp đang chạy. Câu cũ ("mỗi 5 giây") sẽ thành sai ngay khi trang tự thả nhịp
            lúc rỗi — và một dòng trạng thái nói sai về chính nó thì tệ hơn là không có. */}
        <p className="flex items-center gap-2.5 text-[13px] text-ink/65">
          <span
            className={`h-2 w-2 flex-none rounded-full ${
              anyRunning ? "bg-accent motion-safe:animate-pulse-dot" : "bg-steel-400"
            }`}
            aria-hidden
          />
          {anyRunning ? "Đang chạy · làm tươi mỗi 2 giây" : "Pipeline rỗi · làm tươi mỗi 6 giây"}
        </p>
      </div>

      <hr className="my-4 h-0.5 border-0 bg-divider" />

      {/* Không đọc được danh sách hồ sơ → mọi chỉ số dưới đây là 0 GIẢ (query lỗi trả mảng rỗng).
          Nói thẳng thay vì để HR đọc "Chờ HR duyệt: 0" tưởng hàng đợi trống (comment đầu file cam
          kết "MỌI con số dẫn xuất từ dữ liệu THẬT" — hiện 0 khi chưa đọc được là vi phạm cam kết đó). */}
      {isError && (
        <p
          role="alert"
          className="mb-4 rounded-xl border-2 border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          Không tải được danh sách hồ sơ — các chỉ số bên dưới có thể chưa đúng. Đang thử lại tự động…
        </p>
      )}

      {/* Bốn chỉ số chính */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Đang xử lý" value={cProcessing} caption="CV đang chạy pipeline" />
        <StatTile
          label="Chờ HR duyệt"
          value={cReview}
          accent
          action={
            <Link href="/review" className="mt-1 inline-block text-[13px] font-semibold text-white underline-offset-4 hover:underline">
              Mở hàng đợi →
            </Link>
          }
        />
        <StatTile label="Đã hẹn PV" value={cPassed} caption="Tổng cộng" />
        <StatTile label="Đã từ chối" value={cRejected} caption="Tổng cộng" />
      </div>

      {/* Pipeline đa tác tử */}
      <div className="mt-8 flex items-center justify-between gap-4">
        <h2 className="text-[22px]">Pipeline đa tác tử</h2>
        <p className="text-[13px] text-ink/65">Luồng cố định · không Supervisor</p>
      </div>
      <div className="mt-4 rounded-xl border-2 border-divider bg-surface p-4 pb-4 sm:p-6">
        <div className="flex flex-col items-stretch gap-3 md:flex-row md:gap-0">
          {NODES.map((n, i) => {
            const count = countOf(n.statuses);
            // Mũi tên sáng lên khi node PHÍA SAU nó đang có hồ sơ — đọc ra là "hồ sơ vừa chảy qua
            // đây", đúng hướng parser → ranker → screener → scheduler.
            const nextRunning = i < NODES.length - 1 && countOf(NODES[i + 1].statuses) > 0;
            return (
              <div key={n.key} className="flex flex-1 items-stretch">
                <NodeCard
                  label={n.label}
                  caption={n.caption}
                  icon={n.icon}
                  count={count}
                  running={count > 0}
                />
                {i < NODES.length - 1 && (
                  <div
                    className={`hidden w-[34px] flex-none items-center justify-center md:flex ${
                      nextRunning ? "text-accent" : "text-ink/40"
                    }`}
                    aria-hidden
                  >
                    <svg
                      viewBox="0 0 24 24"
                      className={`h-5 w-5 ${nextRunning ? "motion-safe:animate-flow-dot" : ""}`}
                      fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
                    >
                      <path d="M5 12h14" /><path d="m12 5 7 7-7 7" />
                    </svg>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Nhánh human_review — điểm dừng con người (PRD §5 trụ cột 3) */}
        <div className="mt-3 flex flex-col items-stretch gap-3 border-t-2 border-dashed border-divider pt-3 lg:flex-row">
          <div className="flex flex-1 items-center gap-3 rounded-lg border-2 border-accent bg-accent-100 px-4 py-3">
            <svg viewBox="0 0 24 24" className="h-5 w-5 flex-none text-accent-800" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 21a8 8 0 0 0-16 0" /><circle cx="10" cy="8" r="5" /><path d="M22 20c0-3.37-2-6.5-4-8a5 5 0 0 0-.45-8.3" />
            </svg>
            <div className="min-w-0 flex-1">
              <p className="font-heading text-sm font-bold text-accent-800">human_review · điểm dừng con người</p>
              <p className="text-[13px] text-accent-800/85">
                Ca bất định (parse_failed · weak_match · no_response · sát ngưỡng) luôn về đây, bất kể gate.
              </p>
            </div>
            <p className="font-heading text-[30px] font-bold leading-none text-accent-800">{cReview}</p>
          </div>
          <div className="flex items-center gap-3 rounded-lg border-2 border-divider bg-canvas px-4 py-3 lg:w-[200px] lg:flex-none">
            <div className="flex-1">
              <p className="font-heading text-sm font-bold">Kết thúc</p>
              <p className="text-xs text-ink/65">hẹn PV / từ chối</p>
            </div>
            <p className="font-heading text-[26px] font-bold leading-none">{cDone}</p>
          </div>
        </div>
      </div>

      {/* Đang chạy trực tiếp + trạng thái dịch vụ */}
      <div className="mt-8 grid gap-6 lg:grid-cols-[1.55fr_1fr]">
        <section>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-[22px]">Đang chạy trực tiếp</h2>
            <Link href="/applications" className="text-[13px] font-semibold text-accent underline-offset-4 hover:underline">
              Tất cả ứng viên →
            </Link>
          </div>
          <div className="mt-3 overflow-hidden rounded-xl border-2 border-divider">
            {isLoading && <p className="px-4 py-6 text-sm text-ink/65">Đang tải…</p>}
            {isError && (
              <p className="px-4 py-8 text-center text-sm text-red-700">
                Không tải được danh sách. Đang thử lại…
              </p>
            )}
            {/* KHÔNG khẳng định "không có hồ sơ nào đang chạy" khi query đang lỗi (chưa đọc được) */}
            {!isLoading && !isError && inflight.length === 0 && (
              <p className="px-4 py-8 text-center text-sm text-ink/65">
                Không có hồ sơ nào đang chạy. CV mới nộp sẽ hiện ở đây.
              </p>
            )}
            {inflight.map((a) => (
              <Link
                key={a.id}
                href={`/applications/${a.id}`}
                className="flex items-center gap-3 border-b border-divider px-4 py-3 last:border-b-0 hover:bg-ink/[0.04]"
              >
                <span className="flex h-[34px] w-[34px] flex-none items-center justify-center rounded-lg bg-steel-200 font-heading text-[13px] font-bold">
                  {initialsOf(a.applicant_email)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{a.applicant_email}</span>
                  <span className="block truncate text-xs text-ink/65">
                    {a.job_id ? (jobTitle.get(a.job_id) ?? `JD #${a.job_id}`) : "Không gắn JD"}
                  </span>
                </span>
                <span className="flex flex-none items-center gap-2">
                  <span className="h-[7px] w-[7px] rounded-full bg-accent motion-safe:animate-pulse-dot" aria-hidden />
                  <span className="hidden text-[13px] text-ink/65 sm:inline">
                    {STATUS_LABEL[a.status] ?? a.status}
                  </span>
                </span>
              </Link>
            ))}
          </div>
        </section>

        <section className="space-y-4">
          <ServiceStatus />

          <div>
            <div className="rounded-xl border-2 border-divider bg-canvas p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.08em] text-ink/65">
                Hai gate cấu hình
              </p>
              <div className="mt-3 flex items-center justify-between">
                <span className="text-[13px]">Auto-từ-chối</span>
                <span className="rounded bg-steel-100 px-2.5 py-1 text-[11px] font-semibold text-steel-800">
                  {gateLabel(autoReject)}
                </span>
              </div>
              <div className="mt-2.5 flex items-center justify-between">
                <span className="text-[13px]">Auto-mời</span>
                <span className="rounded bg-steel-100 px-2.5 py-1 text-[11px] font-semibold text-steel-800">
                  {gateLabel(autoInvite)}
                </span>
              </div>
              <Link
                href="/jobs"
                className="mt-4 block rounded-lg border-2 border-divider px-3 py-2 text-center text-[13px] font-semibold hover:bg-ink/5"
              >
                Cấu hình theo JD →
              </Link>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
