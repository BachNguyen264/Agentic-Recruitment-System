"use client";

import { Suspense, useEffect, useState } from "react";
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
import { getApplication, getApplications, getJobs, submitReview } from "@/lib/api";

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

  // Hàng đợi = ca PENDING_REVIEW (lấy từ list, tái dùng 03a) → fetch detail cho mỗi ca (ReviewCard
  // cần parsed_data + breakdown + recommendation).
  const listQuery = useQuery<ApplicationListItem[]>({
    queryKey: ["applications"],
    queryFn: getApplications,
    refetchInterval: 5000,
  });
  const pendingIds = (listQuery.data ?? [])
    .filter((a) => a.status === "PENDING_REVIEW")
    .map((a) => a.id);

  const detailQueries = useQueries({
    queries: pendingIds.map((id) => ({
      queryKey: ["application", id],
      queryFn: () => getApplication(id),
    })),
  });
  const cases = detailQueries.map((q) => q.data).filter((d): d is ApplicationDetail => Boolean(d));

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
    },
    onSuccess: (_data, { id }) => {
      // Ca rời hàng đợi + badge giảm: refetch list; làm mới cả detail đã quyết.
      qc.invalidateQueries({ queryKey: ["applications"] });
      qc.invalidateQueries({ queryKey: ["application", id] });
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

      {listQuery.isLoading && <p className="text-sm text-ink/65">Đang tải hàng đợi…</p>}
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
      {listQuery.data && pendingIds.length === 0 && (
        <EmptyState>Không có ca nào chờ HR quyết. Hàng đợi trống.</EmptyState>
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
    </div>
  );
}
