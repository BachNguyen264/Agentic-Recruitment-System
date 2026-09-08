"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  ApplicationDetail,
  ApplicationListItem,
  JobPosting,
  ReviewDecision,
} from "@ars/shared-types";
import { ReviewCard } from "@/components/ReviewCard";
import { EmptyState, PageHeader } from "@/components/ui";
import { getApplication, getApplications, getJobs, getPipeline, submitReview } from "@/lib/api";

// Số ca dựng cùng lúc. Mỗi thẻ = 1 request chi tiết (~9 câu SQL), nên đây thực chất là trần fan-out
// vào pool 15 connection của Neon, không phải một lựa chọn thẩm mỹ. 20 cũng vừa đủ một màn cuộn.
const PAGE_SIZE = 20;

// BUG-1: `fetch` ném TypeError khi không dựng nổi kết nối (mất mạng, DNS hỏng, máy chủ không với
// tới được) — thông điệp gốc là "Failed to fetch", tiếng Anh, không được đổ thẳng vào giao diện
// toàn tiếng Việt. Nói rõ quyết định CHƯA gửi: đây là chỗ HR cần biết chắc mình phải làm lại.
function decisionErrorMessage(err: unknown): string {
  if (err instanceof TypeError) {
    return "Mất kết nối máy chủ — quyết định CHƯA được gửi. Hãy thử lại khi có mạng.";
  }
  const msg = (err as Error)?.message;
  return msg ? `Lỗi khi gửi quyết định: ${msg}` : "Lỗi khi gửi quyết định.";
}

export default function ReviewPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-ink/65">Đang tải hàng đợi…</div>}>
      <ReviewQueue />
    </Suspense>
  );
}

function ReviewQueue() {
  const qc = useQueryClient();
  const [submittingId, setSubmittingId] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Sau khi thẻ biến mất, focus rơi về <body> và người dùng bàn phím mất chỗ đứng. Đưa focus tới
  // dòng xác nhận để trình đọc màn hình đọc nó và phím Tab tiếp tục từ đúng chỗ.
  const noticeRef = useRef<HTMLParagraphElement | null>(null);
  useEffect(() => {
    if (notice) noticeRef.current?.focus();
  }, [notice]);

  // PWA-1: guard ở layout đưa người dùng tới đây khi họ mở một màn chỉ có trên bản máy tính.
  // Tự tắt sau 6s — đây là lời giải thích một lần, không phải cảnh báo thường trực.
  const searchParams = useSearchParams();
  const [hiddenNotice, setHiddenNotice] = useState(false);
  useEffect(() => {
    if (searchParams.get("pwa_hidden") !== "1") return;
    setHiddenNotice(true);
    const t = setTimeout(() => setHiddenNotice(false), 6000);
    return () => clearTimeout(t);
  }, [searchParams]);

  // Hàng đợi = ca PENDING_REVIEW, hỏi ĐÚNG trạng thái đó ở SERVER + phân trang PAGE_SIZE.
  //
  // Trước B1/B2 đây là chỗ tốn nhất hệ thống: tải "100 hồ sơ mới nhất" (kèm parsed_data) rồi lọc
  // PENDING_REVIEW phía client, sau đó bắn MỘT request chi tiết cho MỖI ca — 100 request × ~9 câu
  // SQL = ~900 round-trip vào một pool 15 connection, mỗi lần mount. Trên prod 206 hồ sơ, cửa sổ 100
  // dòng đó còn rơi trọn vào mẻ probe nên hàng đợi vừa nặng vừa GIẤU 86 ca đã chấm điểm sạch.
  const [offset, setOffset] = useState(0);
  const listQuery = useQuery<ApplicationListItem[]>({
    queryKey: ["applications", "review", offset],
    queryFn: () => getApplications({ status: ["PENDING_REVIEW"], limit: PAGE_SIZE, offset }),
    refetchInterval: 15_000,
    placeholderData: (prev) => prev, // bấm "Tải thêm" không nháy trắng cả hàng đợi
  });
  const pendingIds = (listQuery.data ?? []).map((a) => a.id);

  // Tổng số ca chờ duyệt lấy từ `counts` (GROUP BY toàn bảng) — một TRANG không bao giờ biết tổng.
  const { data: pipeline } = useQuery({
    queryKey: ["pipeline"],
    queryFn: getPipeline,
    refetchInterval: 15_000,
  });
  const totalPending = pipeline?.counts?.PENDING_REVIEW ?? null;

  const detailQueries = useQueries({
    queries: pendingIds.map((id) => ({
      queryKey: ["application", id],
      queryFn: () => getApplication(id),
      // `new QueryClient()` ở providers.tsx là mặc định trần ⇒ staleTime:0 +
      // refetchOnMount/onWindowFocus:true: mỗi lần alt-tab hay quay lại trang là bắn LẠI toàn bộ
      // đợt detail. Đặt TẠI ĐÂY chứ TUYỆT ĐỐI KHÔNG ở QueryClient gốc — nó bọc cả luồng ứng viên
      // công khai (nộp CV, đặt lịch, sàng lọc); đổi ở đó là âm thầm đổi hành vi của khách.
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      retry: 1, // mặc định 3 → một đợt lỗi tự nhân bốn lần tải
    })),
  });
  // Hàng đợi được lọc SERVER theo PENDING_REVIEW, nên MỖI lần duyệt/từ chối rút một dòng khỏi đúng
  // tập đang phân trang. Dọn sạch trang cuối để lại `offset` trỏ ra ngoài tập ⇒ empty state bị chặn
  // bởi `offset === 0`, dòng "Đang hiện" bị chặn bởi `cases.length > 0`, và khối phân trang in
  // "21–20 / 20". Lùi một trang thay vì để màn hình trắng. (Giữ nguyên cổng `offset === 0` ở empty
  // state: bỏ nó sẽ in "Hàng đợi trống" ở trang 2 trong khi trang 1 còn 20 ca — đúng "0 GIẢ" mà
  // `/applications` cùng đợt này đang chống.)
  useEffect(() => {
    if (listQuery.data && pendingIds.length === 0 && offset > 0) {
      setOffset((o) => Math.max(0, o - PAGE_SIZE));
    }
  }, [listQuery.data, pendingIds.length, offset]);

  const cases = detailQueries.map((q) => q.data).filter((d): d is ApplicationDetail => Boolean(d));
  // Query hỏng bị `filter(Boolean)` NUỐT IM LẶNG: thẻ đơn giản không hiện, không báo gì.
  const failedCount = detailQueries.filter((q) => q.isError).length;
  const loadingDetails = detailQueries.some((q) => q.isLoading);
  // ĐƯỜNG LÙI khi `/pipeline` hỏng (`totalPending == null`): không có nhánh này thì nút "Trang sau"
  // biến mất và hàng đợi duyệt bị nhốt ở 20 ca đầu — trong khi những ca còn lại vẫn đang chờ người.
  // Một trang đầy ĐÚNG bằng PAGE_SIZE là dấu hiệu đủ tin cậy rằng còn trang nữa.
  const hasMore =
    totalPending != null
      ? offset + pendingIds.length < totalPending
      : pendingIds.length === PAGE_SIZE;

  // Tên vị trí cho từng ca (ReviewCard hiện "email · vị trí" thay cho "JD #id").
  const { data: jobs } = useQuery<JobPosting[]>({
    queryKey: ["jobs", "active"],
    queryFn: () => getJobs(),
  });
  const jobTitle = new Map((jobs ?? []).map((j) => [j.id, j.title]));

  const mutation = useMutation({
    // BUG-1: mặc định `networkMode: "online"` khiến mutation lúc mất mạng bị TẠM DỪNG chứ không
    // hỏng — `onMutate` vẫn chạy (nút kẹt "Đang xử lý…" vĩnh viễn vì chỉ `onSettled` mới xoá cờ),
    // rồi `resumePausedMutations()` TỰ PHÁT LẠI khi có mạng trở lại, có thể là lúc HR đã bỏ đi.
    // Quyết định đó GỬI EMAIL THẬT cho ứng viên (FR-HR-4) và ghi audit_log (FR-HR-5) — không được
    // phép tự chạy sau lưng người bấm. "always" = bắn ngay, hỏng ngay, không bao giờ xếp hàng.
    //
    // Đặt TẠI ĐÂY chứ TUYỆT ĐỐI KHÔNG ở QueryClient gốc: `app/providers.tsx` bọc CẢ luồng ứng viên
    // công khai (nộp CV, đặt lịch, trả lời sàng lọc) — đổi ở đó là âm thầm đổi hành vi của khách.
    networkMode: "always",
    mutationFn: ({ id, decision, note }: { id: number; decision: ReviewDecision; note: string }) =>
      submitReview(id, decision, note),
    onMutate: ({ id }) => {
      setSubmittingId(id);
      setErrorMsg(null);
      setNotice(null);
    },
    onSuccess: (data, { id, decision }) => {
      // Ca rời hàng đợi + badge giảm: refetch list; làm mới cả detail đã quyết.
      qc.invalidateQueries({ queryKey: ["applications"] });
      qc.invalidateQueries({ queryKey: ["application", id] });
      // Badge sidebar nay đọc `["pipeline"]` — quên dòng này thì con số không giảm sau khi duyệt.
      qc.invalidateQueries({ queryKey: ["pipeline"] });

      // Thẻ biến mất là toàn bộ phản hồi mà HR nhận được cho một hành động GỬI EMAIL THẬT và
      // KHÔNG HOÀN TÁC ĐƯỢC. Nội dung phải đọc từ `data.status`, KHÔNG hardcode "đã gửi thư mời":
      // `dispatch_booking_invite` khi gửi mail hỏng sẽ đặt LẠI PENDING_REVIEW + escalation_reason mà
      // route VẪN trả HTTP 200 ⇒ ca ở LẠI hàng đợi. Nói "đã gửi" lúc đó là nói dối người dùng.
      const stillPending = data?.status === "PENDING_REVIEW";
      setNotice(
        stillPending
          ? `Hồ sơ #${id}: quyết định đã ghi nhận nhưng THƯ CHƯA GỬI ĐƯỢC — hồ sơ vẫn ở hàng đợi, xem lý do trong thẻ.`
          : decision === "approve"
            ? `Đã duyệt hồ sơ #${id} — thư mời kèm link đặt lịch đã gửi cho ứng viên.`
            : `Đã từ chối hồ sơ #${id} — thư từ chối đã gửi cho ứng viên.`,
      );
    },
    onError: (err) => setErrorMsg(decisionErrorMessage(err)),
    onSettled: () => setSubmittingId(null),
  });

  const decide = (id: number, decision: ReviewDecision, note: string) =>
    mutation.mutate({ id, decision, note });

  return (
    <div className="mx-auto max-w-[900px] px-4 pb-8 pt-6 sm:px-8">
      <PageHeader
        eyebrow="Human-in-the-loop"
        title="Hàng đợi review"
        description={
          <>
            Mỗi ca kèm ReviewCard (tóm tắt + điểm + lý do).{" "}
            <strong className="font-semibold text-ink">Duyệt</strong> → giao scheduler mời phỏng vấn;{" "}
            <strong className="font-semibold text-ink">Từ chối</strong> → scheduler gửi thư từ chối.
            Mọi quyết định ghi vào audit_log.
          </>
        }
      />

      {hiddenNotice && (
        <p
          role="status"
          className="mb-4 rounded-lg border-2 border-divider bg-ink/[0.03] px-4 py-2.5 text-sm text-ink/70"
        >
          Màn bạn vừa mở chỉ có trên bản máy tính. Đã đưa bạn về hàng đợi duyệt.
        </p>
      )}

      {errorMsg && (
        <p
          role="alert"
          className="mb-4 rounded-lg border-2 border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700"
        >
          {errorMsg}
        </p>
      )}

      {notice && (
        <p
          ref={noticeRef}
          role="status"
          tabIndex={-1}
          className="mb-4 rounded-lg border-2 border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm text-emerald-800 outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          {notice}
        </p>
      )}

      {/* Query chi tiết hỏng bị `filter(Boolean)` nuốt im lặng — không có dòng này thì ca đó chỉ đơn
          giản KHÔNG xuất hiện, và HR tưởng hàng đợi ngắn hơn thực tế. Đây là ca mất-hồ-sơ, không
          phải ca xấu-giao-diện. */}
      {failedCount > 0 && (
        <p
          role="alert"
          className="mb-4 rounded-lg border-2 border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800"
        >
          {failedCount} ca không tải được chi tiết nên chưa hiện ở đây. Tải lại trang để thử lại.
        </p>
      )}

      {listQuery.isLoading && <p className="text-sm text-ink/65">Đang tải hàng đợi…</p>}
      {/* 20 request chi tiết đang bay: list đã xong (isLoading=false) nhưng chưa thẻ nào dựng được ⇒
          không có dòng này thì dưới tiêu đề là một khoảng trắng CÂM, kéo dài 6–19s sau mỗi lần
          Render free tỉnh dậy. */}
      {!listQuery.isLoading && loadingDetails && cases.length === 0 && (
        <p className="text-sm text-ink/65">Đang tải chi tiết {pendingIds.length} ca…</p>
      )}
      {/* BUG-1: mất mạng thì query bị TẠM DỪNG chứ không lỗi — isLoading/isError đều false và data
          undefined, nên không có dòng này thì trang chỉ còn tiêu đề và một khoảng trống câm. */}
      {listQuery.fetchStatus === "paused" && !listQuery.data && (
        <p className="rounded-lg border-2 border-divider bg-ink/[0.03] px-4 py-2.5 text-sm text-ink/65">
          Mất kết nối máy chủ — chưa tải được hàng đợi. Sẽ tự thử lại khi có mạng trở lại.
        </p>
      )}
      {listQuery.isError && (
        <p className="rounded-lg border-2 border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          Không tải được hàng đợi ({String((listQuery.error as Error)?.message)}). Vui lòng thử lại.
        </p>
      )}
      {listQuery.data && pendingIds.length === 0 && offset === 0 && (
        <EmptyState>Không có ca nào chờ HR quyết. Hàng đợi trống.</EmptyState>
      )}

      {/* "Đang hiện X trong Y" — tổng lấy từ `counts` (GROUP BY toàn bảng), KHÔNG đếm trong trang.
          Đây chính là chỗ giao diện cũ nói dối: nó dựng đúng những gì tải được rồi im lặng, nên 100
          thẻ trông y hệt "tất cả các ca". */}
      {totalPending != null && cases.length > 0 && (
        <p className="mb-3 text-[13px] text-ink/65">
          Đang hiện <strong className="font-semibold text-ink">{offset + cases.length}</strong> trong{" "}
          <strong className="font-semibold text-ink">{totalPending}</strong> ca chờ duyệt.
        </p>
      )}

      <div className="flex flex-col gap-4">
        {cases.map((app) => (
          <ReviewCard
            key={app.id}
            app={app}
            jobTitle={app.job_id ? jobTitle.get(app.job_id) : undefined}
            submitting={submittingId === app.id}
            onApprove={(note) => decide(app.id, "approve", note)}
            onReject={(note) => decide(app.id, "reject", note)}
          />
        ))}
      </div>

      {/* Phân trang: "Trang sau" (không phải "tải thêm dồn"), vì mỗi thẻ kéo theo một request chi
          tiết — cộng dồn 100 thẻ là quay về đúng cái N+1 vừa sửa. */}
      {(hasMore || offset > 0) && (
        <div className="mt-6 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            disabled={offset === 0 || listQuery.isFetching}
            className="rounded-lg border-2 border-divider px-4 py-2 text-[13px] font-semibold text-ink/70 transition-colors hover:bg-ink/[0.06] disabled:cursor-not-allowed disabled:opacity-40"
          >
            ← Trang trước
          </button>
          <span className="text-[13px] text-ink/65">
            {/* Chỉ in phạm vi khi trang THẬT SỰ có dòng — nếu không sẽ ra "21–20 / 20". */}
            {pendingIds.length > 0
              ? `${offset + 1}–${offset + pendingIds.length}${totalPending != null ? ` / ${totalPending}` : ""}`
              : "Trang này đã trống"}
          </span>
          <button
            type="button"
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
            disabled={!hasMore || listQuery.isFetching}
            className="rounded-lg border-2 border-divider px-4 py-2 text-[13px] font-semibold text-ink/70 transition-colors hover:bg-ink/[0.06] disabled:cursor-not-allowed disabled:opacity-40"
          >
            Trang sau →
          </button>
        </div>
      )}
    </div>
  );
}
