"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { JobPosting, JobPostingInput } from "@ars/shared-types";
import { JobForm } from "@/components/JobForm";
import { BackArrow, btn } from "@/components/ui";
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
    <main className="mx-auto max-w-[720px] px-4 pb-8 pt-5 sm:px-8">
      <Link href="/jobs" className={btn("ghost", "mb-3 !pl-0")}>
        <BackArrow /> Danh sách JD
      </Link>
      <header className="mb-5">
        <p className="eyebrow mb-1.5">Bước 1/2 · Tin tuyển dụng</p>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-[26px] sm:text-[30px]">Sửa tin tuyển dụng</h1>
          <Link href={`/jobs/${id}/screening`} className={btn("secondary")}>
            Cấu hình sàng lọc →
          </Link>
        </div>
        <p className="mt-2 max-w-[66ch] text-[13px] leading-relaxed text-ink/65">
          Chỉ nội dung tin tuyển dụng (ứng viên thấy). Rubric + câu hỏi sàng lọc ở màn “Cấu hình sàng
          lọc”. Chỉ re-embed khi tiêu đề/mô tả/yêu cầu đổi.
        </p>
      </header>

      {isLoading && <p className="text-sm text-ink/65">Đang tải JD…</p>}
      {isError && (
        <p className="rounded-lg border-2 border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          Không tải được JD ({String((error as Error)?.message)}). Vui lòng thử lại.
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
