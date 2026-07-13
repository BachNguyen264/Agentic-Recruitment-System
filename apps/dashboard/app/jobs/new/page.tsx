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
  const [warning, setWarning] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (input: JobPostingInput) => createJob(input),
    onMutate: () => {
      setErrorMsg(null);
      setWarning(null);
    },
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      // Embed lỗi → JD vẫn tạo: hiện cảnh báo, KHÔNG rời trang. Ngược lại về danh sách.
      if (result.embedding_warning) setWarning(result.embedding_warning);
      else router.push("/jobs");
    },
    onError: (err) => setErrorMsg(String((err as Error)?.message) || "Lỗi khi tạo JD."),
  });

  return (
    <main className="mx-auto max-w-2xl space-y-6 p-8">
      <header className="space-y-1">
        <Link href="/jobs" className="text-sm text-slate-500 hover:underline">
          ← Danh sách JD
        </Link>
        <h1 className="text-2xl font-bold">Tạo JD mới</h1>
        <p className="text-sm text-slate-500">
          Điền thông tin tin tuyển dụng. JD sẽ được embed vào Qdrant làm chuẩn đối sánh CV (PRD §7.2).
        </p>
      </header>

      <JobForm
        initial={emptyJobInput()}
        submitLabel="Tạo JD"
        submitting={mutation.isPending}
        errorMsg={errorMsg}
        warning={warning}
        onSubmit={(input) => mutation.mutate(input)}
      />
    </main>
  );
}
