"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { JobPosting, RubricCriterion } from "@ars/shared-types";
import { ScreeningConfigForm } from "@/components/ScreeningConfigForm";
import { getJob, setJobStatus, suggestRubric, updateJob } from "@/lib/api";
import { jobStatusBadgeClass, jobStatusLabel, toJobInput } from "@/lib/jobs";

type ConfigPayload = { rubric: RubricCriterion[]; questions: string[] };

export default function ScreeningConfigPage({ params }: { params: { id: string } }) {
  const id = Number(params.id);
  const router = useRouter();
  const qc = useQueryClient();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  const { data: job, isLoading, isError, error } = useQuery<JobPosting>({
    queryKey: ["job", id],
    queryFn: () => getJob(id),
    enabled: Number.isFinite(id),
  });

  // Lưu cấu hình = PUT JD với posting GIỮ NGUYÊN (từ job) + rubric/câu-hỏi mới (merge). Gate giữ nguyên.
  const mergedInput = (job: JobPosting, { rubric, questions }: ConfigPayload) => ({
    ...toJobInput(job),
    rubric,
    screener_questions: questions,
  });

  const saveMutation = useMutation({
    mutationFn: (p: ConfigPayload) => updateJob(id, mergedInput(job!, p)),
    onMutate: () => {
      setErrorMsg(null);
      setSavedMsg(null);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["job", id] });
      setSavedMsg("Đã lưu cấu hình sàng lọc.");
    },
    onError: (err) => setErrorMsg(String((err as Error)?.message) || "Lỗi khi lưu cấu hình."),
  });

  // Lưu & Mở: lưu cấu hình TRƯỚC (rubric vào DB) rồi mới đổi status OPEN (backend kiểm rubric).
  const openMutation = useMutation({
    mutationFn: async (p: ConfigPayload) => {
      await updateJob(id, mergedInput(job!, p));
      return setJobStatus(id, "OPEN");
    },
    onMutate: () => {
      setErrorMsg(null);
      setSavedMsg(null);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      router.push("/jobs");
    },
    onError: (err) => setErrorMsg(String((err as Error)?.message) || "Lỗi khi mở JD."),
  });

  return (
    <main className="mx-auto max-w-2xl space-y-6 p-8">
      <header className="space-y-1">
        <Link href="/jobs" className="text-sm text-slate-500 hover:underline">
          ← Danh sách JD
        </Link>
        <h1 className="text-2xl font-bold">Cấu hình sàng lọc</h1>
        <p className="text-sm text-slate-500">
          Bước 2/2: rubric (bắt buộc để MỞ JD) + câu hỏi sàng lọc (tùy chọn). Chỉ HR thấy — KHÔNG lộ cho
          ứng viên.
        </p>
      </header>

      {isLoading && <p className="text-sm text-slate-500">Đang tải JD…</p>}
      {isError && (
        <p className="text-sm text-red-600">
          Không tải được JD ({String((error as Error)?.message)}).
        </p>
      )}

      {job && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 bg-white px-4 py-3">
            <div className="min-w-0">
              <p className="truncate font-medium text-slate-900">{job.title}</p>
              <p className="text-xs text-slate-400">JD #{job.id}</p>
            </div>
            <div className="flex items-center gap-2">
              <span
                className={`rounded px-2 py-0.5 text-xs font-medium ${jobStatusBadgeClass(job.status)}`}
              >
                {jobStatusLabel(job.status)}
              </span>
              <Link
                href={`/jobs/${job.id}/edit`}
                className="text-sm font-medium text-slate-600 hover:text-slate-900 hover:underline"
              >
                ← Sửa tin
              </Link>
            </div>
          </div>

          {savedMsg && (
            <p className="rounded-md border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700">
              {savedMsg}
            </p>
          )}

          <ScreeningConfigForm
            key={job.id}
            initialRubric={job.rubric}
            initialQuestions={job.screener_questions}
            status={job.status}
            saving={saveMutation.isPending}
            opening={openMutation.isPending}
            errorMsg={errorMsg}
            suggestionsRemaining={job.rubric_suggestions_remaining}
            onSuggestRubric={async () => {
              // JD-3: gọi endpoint → điền sẵn form. Refresh job để badge "còn N lượt" cập nhật (count↑).
              const res = await suggestRubric(id);
              qc.invalidateQueries({ queryKey: ["job", id] });
              return res.criteria;
            }}
            onSave={(rubric, questions) => saveMutation.mutate({ rubric, questions })}
            onSaveAndOpen={(rubric, questions) => openMutation.mutate({ rubric, questions })}
          />
        </>
      )}
    </main>
  );
}
