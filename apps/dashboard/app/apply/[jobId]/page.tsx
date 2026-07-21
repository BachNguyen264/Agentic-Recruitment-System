"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { PublicJob } from "@ars/shared-types";
import { CVFilePicker } from "@/components/CVFilePicker";
import { SafeHtml } from "@/components/SafeHtml";
import { SuccessPanel } from "@/components/SuccessPanel";
import { BackArrow, btn, Field, inputClass } from "@/components/ui";
import { getPublicJob, submitApplication } from "@/lib/api";
import { employmentTypeLabel, formatSalary, levelLabel } from "@/lib/jobs";

function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
}

// Khối văn bản định dạng của JD (mô tả/yêu cầu/quyền lợi — JD-1). Nội dung do HR soạn bằng editor
// nên là HTML → BẮT BUỘC đi qua SafeHtml (DOMPurify) trước khi render trên trang CÔNG KHAI.
function JobSection({ title, html }: { title: string; html: string }) {
  if (!html.trim()) return null;
  return (
    <section className="mt-4">
      <h2 className="font-heading text-[13px] font-bold">{title}</h2>
      <SafeHtml
        html={html}
        className="rte-content mt-2 text-[13px] leading-relaxed text-ink/80"
      />
    </section>
  );
}

export default function ApplyDetailPage({ params }: { params: { jobId: string } }) {
  const id = Number(params.jobId);

  // Khoá refetch trên đường công khai (rate-limit theo IP — xem ghi chú ở /apply). Đặc biệt
  // refetchOnWindowFocus mặc định BẬT sẽ khiến banner "vị trí không còn mở" nhảy ra ĐÈ form ứng
  // viên đang điền nếu JD vừa bị đóng — tắt tường minh.
  const jobQuery = useQuery<PublicJob>({
    queryKey: ["public-job", id],
    queryFn: () => getPublicJob(id),
    enabled: Number.isFinite(id),
    retry: false, // JD đóng/lưu-trữ/không tồn tại → 404, đừng thử lại.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    refetchOnReconnect: false,
  });

  const [email, setEmail] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const mutation = useMutation({
    mutationFn: () => submitApplication(id, email.trim(), file as File),
  });

  const canSubmit = isValidEmail(email) && file !== null && !mutation.isPending;

  // ── Sau khi nộp thành công — KHÔNG hiện điểm/trạng thái (ứng viên là khách, PRD §5) ──
  if (mutation.isSuccess) {
    return (
      <main>
        <SuccessPanel
          title="Cảm ơn bạn đã ứng tuyển!"
          action={
            <Link href="/apply" className={btn("secondary")}>
              <BackArrow /> Xem vị trí khác
            </Link>
          }
        >
          Hồ sơ đã được gửi thành công. Chúng tôi sẽ xem xét và liên hệ kết quả với bạn qua email.
        </SuccessPanel>
      </main>
    );
  }

  const job = jobQuery.data;
  const meta = job
    ? [levelLabel(job.level), employmentTypeLabel(job.employment_type)].filter(Boolean).join(" · ")
    : "";
  const salary = job ? formatSalary(job.salary) : null;

  return (
    <main>
      <Link href="/apply" className={btn("ghost", "mb-3 !pl-0")}>
        <BackArrow /> Tất cả vị trí
      </Link>

      {jobQuery.isLoading && <p className="text-[13px] text-ink/65">Đang tải vị trí…</p>}

      {jobQuery.isError && (
        <div className="rounded-xl border-2 border-divider bg-surface px-6 py-10 text-center">
          <p className="font-heading text-[15px] font-bold">
            Vị trí này không còn mở hoặc không tồn tại.
          </p>
          <p className="mx-auto mt-1.5 max-w-[44ch] text-[13px] text-ink/65">
            Tin tuyển dụng có thể đã đóng. Bạn xem các vị trí đang mở nhé.
          </p>
          <Link href="/apply" className={btn("secondary", "mt-4")}>
            Xem vị trí đang mở
          </Link>
        </div>
      )}

      {job && (
        <>
          <header>
            <h1 className="text-[26px] sm:text-[32px]">{job.title}</h1>
            {meta && <p className="mt-1.5 text-[13px] text-ink/65">{meta}</p>}
            {salary && (
              <p className="mt-2.5">
                <span className="inline-flex rounded bg-ink px-2.5 py-1 text-[12px] font-semibold text-canvas">
                  {salary}
                </span>
              </p>
            )}
          </header>

          {job.description.trim() && (
            <SafeHtml
              html={job.description}
              className="rte-content mt-4 text-[14px] leading-relaxed text-ink/85"
            />
          )}
          <JobSection title="Yêu cầu" html={job.requirements} />
          <JobSection title="Quyền lợi" html={job.benefits} />

          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (canSubmit) mutation.mutate();
            }}
            className="mt-7 border-t-2 border-divider pt-5"
          >
            <h2 className="text-[20px] sm:text-[22px]">Nộp hồ sơ</h2>

            <div className="mt-4 flex flex-col gap-4">
              <Field
                label="Email"
                required
                htmlFor="apply-email"
                hint="Chúng tôi sẽ liên hệ kết quả qua email này."
              >
                <input
                  id="apply-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="ban@example.com"
                  autoComplete="email"
                  disabled={mutation.isPending}
                  className={inputClass}
                />
              </Field>

              <Field label="CV (.pdf / .docx)" required>
                <CVFilePicker onFile={setFile} disabled={mutation.isPending} />
              </Field>
            </div>

            {mutation.isError && (
              <p
                role="alert"
                className="mt-4 rounded-xl border-2 border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700"
              >
                {String((mutation.error as Error)?.message) ||
                  "Không gửi được hồ sơ. Vui lòng thử lại."}
              </p>
            )}

            <button type="submit" disabled={!canSubmit} className={btn("primary", "mt-4")}>
              {mutation.isPending ? "Đang gửi…" : "Nộp hồ sơ"}
            </button>
          </form>
        </>
      )}
    </main>
  );
}
