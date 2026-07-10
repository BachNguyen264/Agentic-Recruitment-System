"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ApplicationDetail, ApplicationListItem, ReviewDecision } from "@ars/shared-types";
import { ReviewCard } from "@/components/ReviewCard";
import { getApplication, getApplications, submitReview } from "@/lib/api";

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
  const cases = detailQueries
    .map((q) => q.data)
    .filter((d): d is ApplicationDetail => Boolean(d));

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
    <main className="mx-auto max-w-4xl space-y-6 p-8">
      <header className="space-y-1">
        <Link href="/" className="text-sm text-slate-500 hover:underline">
          ← Về dashboard
        </Link>
        <h1 className="text-2xl font-bold">Hàng đợi review</h1>
        <p className="text-sm text-slate-500">
          Các ca cần HR quyết (PRD §11). Duyệt → mời phỏng vấn; Từ chối → gửi thư từ chối. Quyết định
          giao cho scheduler thực thi.
        </p>
      </header>

      {errorMsg && (
        <p className="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {errorMsg}
        </p>
      )}

      {listQuery.isLoading && <p className="text-sm text-slate-500">Đang tải hàng đợi…</p>}
      {listQuery.isError && (
        <p className="text-sm text-red-600">
          Không tải được hàng đợi ({String((listQuery.error as Error)?.message)}). Backend đã chạy
          ở :8000 chưa?
        </p>
      )}
      {listQuery.data && pendingIds.length === 0 && (
        <p className="text-sm text-slate-400">Không có ca nào chờ HR quyết. 🎉</p>
      )}

      <div className="space-y-5">
        {cases.map((app) => (
          <ReviewCard
            key={app.id}
            app={app}
            submitting={submittingId === app.id}
            onApprove={(note) => decide(app.id, "approve", note)}
            onReject={(note) => decide(app.id, "reject", note)}
          />
        ))}
      </div>
    </main>
  );
}
