"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { JobPosting, JobPostingInput } from "@ars/shared-types";
import { JobForm } from "@/components/JobForm";
import { getJob, updateJob } from "@/lib/api";
import { toJobInput } from "@/lib/jobs";

export default function EditJobPage({ params }: { params: { id: string } }) {
  const id = Number(params.id);
  const router = useRouter();
  const qc = useQueryClient();
  const [warning, setWarning] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { data: job, isLoading, isError, error } = useQuery<JobPosting>({
    queryKey: ["job", id],
    queryFn: () => getJob(id),
    enabled: Number.isFinite(id),
  });

  const mutation = useMutation({
    mutationFn: (input: JobPostingInput) => updateJob(id, input),
    onMutate: () => {
      setErrorMsg(null);
      setWarning(null);
    },
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["job", id] });
      // Re-embed lỗi → JD vẫn cập nhật: hiện cảnh báo, KHÔNG rời trang. Ngược lại về danh sách.
      if (result.embedding_warning) setWarning(result.embedding_warning);
      else router.push("/jobs");
    },
    onError: (err) => setErrorMsg(String((err as Error)?.message) || "Lỗi khi lưu JD."),
  });

  return (
    <main className="mx-auto max-w-2xl space-y-6 p-8">
      <header className="space-y-1">
        <Link href="/jobs" className="text-sm text-slate-500 hover:underline">
          ← Danh sách JD
        </Link>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-2xl font-bold">Sửa tin tuyển dụng</h1>
          <Link
            href={`/jobs/${id}/screening`}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
          >
            Cấu hình sàng lọc →
          </Link>
        </div>
        <p className="text-sm text-slate-500">
          Chỉ nội dung tin tuyển dụng (ứng viên thấy). Rubric + câu hỏi sàng lọc ở màn “Cấu hình sàng
          lọc”. Chỉ re-embed khi tiêu đề/mô tả/yêu cầu đổi.
        </p>
      </header>

      {isLoading && <p className="text-sm text-slate-500">Đang tải JD…</p>}
      {isError && (
        <p className="text-sm text-red-600">
          Không tải được JD ({String((error as Error)?.message)}). Backend đã chạy ở :8000 chưa?
        </p>
      )}

      {job && (
        <JobForm
          key={job.id}
          initial={toJobInput(job)}
          submitLabel="Lưu thay đổi"
          submitting={mutation.isPending}
          errorMsg={errorMsg}
          warning={warning}
          onSubmit={(input) => mutation.mutate(input)}
        />
      )}
    </main>
  );
}
