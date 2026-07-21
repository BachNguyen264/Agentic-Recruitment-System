"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import type { PublicJob } from "@ars/shared-types";
import { EmptyState } from "@/components/ui";
import { getOpenJobs } from "@/lib/api";
import { employmentTypeLabel, formatSalary, htmlToPlainText, levelLabel } from "@/lib/jobs";

export default function ApplyListPage() {
  // Khoá refetch trên đường công khai (rate-limit theo IP): tải MỘT lần rồi thôi. Trước đây comment
  // nói "KHÔNG refetchOnWindowFocus" nhưng object KHÔNG hề tắt — refetchOnWindowFocus/OnMount/
  // OnReconnect mặc định BẬT (QueryClient trần). Ứng viên chuyển tab qua lại đốt quota rồi POST hồ
  // sơ bị 429 → mất bài dự tuyển. Nay tắt tường minh cả bốn.
  const { data, isLoading, isError } = useQuery<PublicJob[]>({
    queryKey: ["public-jobs"],
    queryFn: getOpenJobs,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    refetchOnReconnect: false,
  });

  const jobs = data ?? [];

  return (
    <main>
      <h1 className="text-[30px] sm:text-[36px]">Vị trí đang tuyển</h1>
      <p className="mt-2 max-w-[60ch] text-[14px] leading-relaxed text-ink/65">
        Chọn một vị trí để xem chi tiết và nộp hồ sơ. Chỉ cần email và CV (PDF/DOCX) — không cần tạo
        tài khoản.
      </p>

      {isLoading && <p className="mt-5 text-[13px] text-ink/65">Đang tải vị trí…</p>}
      {isError && (
        <p
          role="alert"
          className="mt-5 rounded-xl border-2 border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700"
        >
          Không tải được danh sách vị trí. Vui lòng thử lại sau.
        </p>
      )}
      {data && jobs.length === 0 && (
        <div className="mt-5">
          <EmptyState>
            Hiện chưa có vị trí nào đang mở. Bạn quay lại sau nhé — chúng tôi đăng tin thường xuyên.
          </EmptyState>
        </div>
      )}

      <ul className="mt-5 flex flex-col gap-3">
        {jobs.map((job) => {
          const summary = htmlToPlainText(job.description);
          // Meta hướng-ứng-viên (JD-1). KHÔNG có rubric/gate/câu-hỏi-sàng-lọc ở đây — PublicJob
          // (backend) đã cắt sẵn, đừng bao giờ thêm vào: lộ rubric là ứng viên viết CV để lách điểm.
          const meta = [levelLabel(job.level), employmentTypeLabel(job.employment_type)]
            .filter(Boolean)
            .join(" · ");
          const salary = formatSalary(job.salary);

          return (
            <li key={job.id}>
              <Link
                href={`/apply/${job.id}`}
                className="group block rounded-xl border-2 border-divider bg-canvas px-5 py-4 transition-colors hover:border-ink/40 hover:bg-surface"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <span className="font-heading text-[18px] font-bold sm:text-[19px]">
                    {job.title}
                  </span>
                  {meta && <span className="text-[13px] text-ink/65">{meta}</span>}
                </div>

                {summary && (
                  <p className="mt-2 line-clamp-2 text-[13px] leading-relaxed text-ink/65">
                    {summary}
                  </p>
                )}

                <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                  <span className="font-heading text-[13px] font-bold text-accent">
                    Xem &amp; nộp hồ sơ →
                  </span>
                  {salary && (
                    <span className="rounded bg-ink px-2.5 py-0.5 text-[11px] font-semibold text-canvas">
                      {salary}
                    </span>
                  )}
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </main>
  );
}
