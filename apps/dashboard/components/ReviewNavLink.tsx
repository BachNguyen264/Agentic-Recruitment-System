"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import type { ApplicationListItem } from "@ars/shared-types";
import { getApplications } from "@/lib/api";

// Link tới /review + badge số ca PENDING_REVIEW (PRD §12.4 FR-NOTI-2 — badge in-app).
// Dùng chung queryKey ["applications"] với /review + /applications → quyết định xong badge tự giảm.
export function ReviewNavLink() {
  const { data } = useQuery<ApplicationListItem[]>({
    queryKey: ["applications"],
    queryFn: getApplications,
    refetchInterval: 5000,
  });
  const count = (data ?? []).filter((a) => a.status === "PENDING_REVIEW").length;

  return (
    <Link href="/review" className="text-slate-700 underline hover:text-slate-900">
      <span>→ Hàng đợi review</span>
      {count > 0 && (
        <span
          aria-label={`${count} hồ sơ chờ duyệt`}
          className="ml-1.5 rounded-full bg-amber-500 px-1.5 py-0.5 text-xs font-medium text-white no-underline"
        >
          {count}
        </span>
      )}
    </Link>
  );
}
