"use client";

import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import type { JobPosting } from "@ars/shared-types";
import { getJobs } from "@/lib/api";

// Bảng tra `job_id → tiêu đề JD`, dùng chung cho ba màn HR có cột/dòng "Vị trí"
// (`/applications`, `/review`, bảng điều hành).
//
// Vì sao phải nạp CẢ HAI rổ: `getJobs()` mặc định `archived=false`, tức BỎ QUA mọi JD đã lưu trữ.
// Hồ sơ gắn vào một JD đã lưu trữ (JD-4 giữ nguyên hồ sơ khi lưu trữ) sẽ rơi vào nhánh dự phòng
// `JD #<id>` VĨNH VIỄN — và đó chính là những hồ sơ CŨ, tức lúc cần đọc tên vị trí nhất thì màn
// hình lại chỉ đưa ra một con số. Ba màn trước đây chép tay cùng một lỗi này ở ba chỗ.
//
// Khoá query riêng (`["jobs","titles",…]`) chứ không dùng chung khoá với danh sách JD ở `/jobs`:
// màn đó phân trang theo `offset` nên cùng một khoá sẽ chở hai hình dạng dữ liệu khác nhau. Tiền tố
// `["jobs"]` vẫn giữ để `invalidateQueries({ queryKey: ["jobs"] })` sau khi sửa/lưu-trữ JD làm tươi
// luôn bảng tên này.
const TITLE_PAGE_LIMIT = 200; // trần `limit` của backend cho router HR

export function useJobTitles(): Map<number, string> {
  const results = useQueries({
    queries: ([false, true] as const).map((archived) => ({
      queryKey: ["jobs", "titles", archived ? "archived" : "active"],
      queryFn: () => getJobs(archived, { limit: TITLE_PAGE_LIMIT }),
      // Tên vị trí gần như không đổi trong một phiên làm việc — không cần hỏi lại mỗi lần mount.
      staleTime: 5 * 60_000,
      refetchOnWindowFocus: false,
    })),
  });

  // `results` là mảng MỚI mỗi lần render nên không dùng được làm dependency; bám vào chính mảng
  // dữ liệu (TanStack giữ nguyên tham chiếu khi dữ liệu không đổi).
  const active = results[0].data;
  const archived = results[1].data;

  return useMemo(() => {
    const map = new Map<number, string>();
    for (const job of [...(active ?? []), ...(archived ?? [])] as JobPosting[]) {
      map.set(job.id, job.title);
    }
    return map;
  }, [active, archived]);
}
