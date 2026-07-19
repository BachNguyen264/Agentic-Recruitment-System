"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { JobPostingInput } from "@ars/shared-types";
import { JobForm } from "@/components/JobForm";
import { createJob } from "@/lib/api";
import { emptyJobInput } from "@/lib/jobs";

export default function NewJobPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (input: JobPostingInput) => createJob(input),
    onMutate: () => setErrorMsg(null),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      // JD-2a: JD mới lưu ở dạng NHÁP (DRAFT) → sang màn "Cấu hình sàng lọc" (rubric cần JD đã lưu).
      router.push(`/jobs/${result.job.id}/screening`);
    },
    onError: (err) => setErrorMsg(String((err as Error)?.message) || "Lỗi khi tạo JD."),
  });

  return (
    <main className="mx-auto max-w-2xl space-y-6 p-8">
      <header className="space-y-1">
        <Link href="/jobs" className="text-sm text-slate-500 hover:underline">
          ← Danh sách JD
        </Link>
        <h1 className="text-2xl font-bold">Tin tuyển dụng mới</h1>
        <p className="text-sm text-slate-500">
          Bước 1/2: điền thông tin tin tuyển dụng (ứng viên thấy). Lưu xong JD ở dạng{" "}
          <span className="font-medium text-amber-700">Nháp</span> → sang bước cấu hình rubric để mở JD.
        </p>
      </header>

      <JobForm
        initial={emptyJobInput()}
        submitLabel="Lưu & sang cấu hình sàng lọc"
        submitting={mutation.isPending}
        errorMsg={errorMsg}
        onSubmit={(input) => mutation.mutate(input)}
      />
    </main>
  );
}
