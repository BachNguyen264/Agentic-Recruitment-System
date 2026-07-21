"use client";

import { useState } from "react";
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

export default function ReviewPage() {
  const qc = useQueryClient();
  const [submittingId, setSubmittingId] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

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
    onError: (err) => setErrorMsg(String((err as Error)?.message) || "Lỗi khi gửi quyết định."),
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

      {errorMsg && (
        <p
          role="alert"
          className="mb-4 rounded-lg border-2 border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700"
        >
          {errorMsg}
        </p>
      )}

      {listQuery.isLoading && <p className="text-sm text-ink/65">Đang tải hàng đợi…</p>}
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
