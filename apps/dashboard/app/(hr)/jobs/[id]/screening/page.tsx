"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { JobPosting, RubricCriterion } from "@ars/shared-types";
import { ScreeningConfigForm } from "@/components/ScreeningConfigForm";
import { BackArrow, btn, Tag } from "@/components/ui";
import { getJob, setJobStatus, suggestRubric, updateJob } from "@/lib/api";
import { jobStatusLabel, toJobInput } from "@/lib/jobs";

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
    <main className="mx-auto max-w-[720px] space-y-5 px-4 pb-8 pt-5 sm:px-8">
      <div>
        <Link href="/jobs" className={btn("ghost", "mb-3 !pl-0")}>
          <BackArrow /> Danh sách JD
        </Link>
        <p className="eyebrow mb-1.5">Bước 2/2 · Cấu hình sàng lọc</p>
        <h1 className="text-[26px] sm:text-[30px]">Cấu hình sàng lọc</h1>
        <p className="mt-2 max-w-[66ch] text-[13px] leading-relaxed text-ink/55">
          Rubric (bắt buộc để MỞ JD) + câu hỏi sàng lọc (tùy chọn). Chỉ HR thấy — không lộ cho ứng
          viên.
        </p>
      </div>

      {isLoading && <p className="text-sm text-ink/55">Đang tải JD…</p>}
      {isError && (
        <p className="rounded-lg border-2 border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          Không tải được JD ({String((error as Error)?.message)}).
        </p>
      )}

      {job && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border-2 border-divider bg-canvas px-4 py-3">
            <div className="min-w-0">
              <p className="truncate font-heading text-[15px] font-bold">{job.title}</p>
              <p className="text-xs text-ink/45">JD #{job.id}</p>
            </div>
            <div className="flex items-center gap-3">
              <Tag tone={job.status === "OPEN" ? "ok" : job.status === "DRAFT" ? "warn" : "neutral"}>
                {jobStatusLabel(job.status)}
              </Tag>
              <Link href={`/jobs/${job.id}/edit`} className={btn("ghost")}>
                ← Sửa tin
              </Link>
            </div>
          </div>

          {savedMsg && (
            <p className="flex items-center gap-2 rounded-xl border-2 border-ink bg-surface px-4 py-2.5 text-[13px]">
              <svg
                viewBox="0 0 24 24"
                className="h-4 w-4 flex-none"
                fill="none"
                stroke="currentColor"
                strokeWidth={2.4}
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
              >
                <path d="M20 6 9 17l-5-5" />
              </svg>
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
