"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { JobPostingInput } from "@ars/shared-types";
import { JobForm } from "@/components/JobForm";
import { BackArrow, btn } from "@/components/ui";
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
    <main className="mx-auto max-w-[720px] px-4 pb-8 pt-5 sm:px-8">
      <Link href="/jobs" className={btn("ghost", "mb-3 !pl-0")}>
        <BackArrow /> Danh sách JD
      </Link>
      <header className="mb-5">
        <p className="eyebrow mb-1.5">Bước 1/2 · Tin tuyển dụng</p>
        <h1 className="text-[26px] sm:text-[30px]">Tạo JD mới</h1>
        <p className="mt-2 max-w-[66ch] text-[13px] leading-relaxed text-ink/55">
          Thông tin ứng viên nhìn thấy ở cổng tuyển dụng. Lưu xong JD ở dạng{" "}
          <strong className="font-semibold text-accent-800">Nháp</strong> → sang bước cấu hình rubric
          để mở JD.
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
