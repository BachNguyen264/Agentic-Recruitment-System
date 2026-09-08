"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { PublicJob } from "@ars/shared-types";
import { btn, EmptyState } from "@/components/ui";
import { getOpenJobs } from "@/lib/api";
import { employmentTypeLabel, formatSalary, htmlToPlainText, levelLabel } from "@/lib/jobs";

// Số vị trí hiện mỗi lượt. Backend chặn `limit ≤ 100` cho đường công khai; xin thêm bằng nút
// "Xem thêm" thay vì phân trang có số trang: ứng viên đang DUYỆT để chọn, không tra cứu theo trang,
// và mỗi lượt bấm là một request đếm vào hạn mức theo IP — bắt họ lật qua lật lại là tự siết mình.
const PAGE_SIZE = 20;

export default function ApplyListPage() {
  const [limit, setLimit] = useState(PAGE_SIZE);
  // Khoá refetch trên đường công khai (rate-limit theo IP): tải MỘT lần rồi thôi. Trước đây comment
  // nói "KHÔNG refetchOnWindowFocus" nhưng object KHÔNG hề tắt — refetchOnWindowFocus/OnMount/
  // OnReconnect mặc định BẬT (QueryClient trần). Ứng viên chuyển tab qua lại đốt quota rồi POST hồ
  // sơ bị 429 → mất bài dự tuyển. Nay tắt tường minh cả bốn.
  const { data, isLoading, isError } = useQuery<PublicJob[]>({
    queryKey: ["public-jobs", limit],
    // Bọc trong arrow: TanStack truyền QueryFunctionContext làm tham số ĐẦU, mà `getOpenJobs` nay
    // nhận `JobQuery` — đưa thẳng thì context lọt vào chỗ tham số phân trang.
    queryFn: () => getOpenJobs({ limit }),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    refetchOnReconnect: false,
    // Giữ danh sách cũ trên màn khi đang xin thêm — nhấp nháy về "Đang tải" làm mất chỗ đang đọc.
    placeholderData: (prev) => prev,
  });

  const jobs = data ?? [];
  // Không có endpoint đếm cho đường công khai (cố ý: thêm một câu SQL cho người lạ gọi). Một trang
  // đầy ĐÚNG bằng `limit` là dấu hiệu đủ tin cậy rằng còn nữa. Trước đây route cắt cứng 100 và
  // KHÔNG có dấu hiệu nào cho ứng viên biết danh sách đã bị cắt — vị trí cũ hơn không bao giờ hiện.
  const hasMore = jobs.length === limit;

  return (
    <main>
      <h1 className="text-[30px] sm:text-[36px]">Vị trí đang tuyển</h1>
      <p className="mt-2 max-w-[60ch] text-[14px] leading-relaxed text-ink/65">
        Chọn một vị trí để xem chi tiết và nộp hồ sơ. Chỉ cần email và CV (PDF/DOCX) — không cần tạo
        tài khoản.
      </p>

      {/* Lối vào kho CV mẫu. Ở trang DANH SÁCH này điều hướng cùng tab là an toàn: chưa có form
          nào đang điền dở để mất (khác trang chi tiết — xem ghi chú ở /apply/[jobId]). */}
      <p className="mt-3 text-[13px] text-ink/65">
        Chưa có CV?{" "}
        <Link href="/cv-templates" className="font-heading font-bold text-accent hover:underline">
          Tải CV mẫu về ngay →
        </Link>
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

      {hasMore && (
        <div className="mt-5 flex justify-center">
          <button
            type="button"
            onClick={() => setLimit((n) => n + PAGE_SIZE)}
            disabled={isLoading}
            className={btn("ghost")}
          >
            {isLoading ? "Đang tải…" : "Xem thêm vị trí"}
          </button>
        </div>
      )}
    </main>
  );
}
