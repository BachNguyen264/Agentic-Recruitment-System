"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ApplicationListItem, JobPosting } from "@ars/shared-types";
import { PageHeader, Tag } from "@/components/ui";
import { getApplications, getJobs } from "@/lib/api";
import {
  BUCKET_FILTERS,
  statusBucket,
  statusLabel,
  statusTone,
  type StatusBucket,
} from "@/lib/applications";

function initialsOf(email: string): string {
  const name = email.split("@")[0] ?? "";
  const parts = name.split(/[._-]+/).filter(Boolean);
  return ((parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2)) || "??").toUpperCase();
}

export default function ApplicationsPage() {
  const [bucket, setBucket] = useState<StatusBucket | "all">("all");
  const { data, isLoading, isError, error } = useQuery<ApplicationListItem[]>({
    queryKey: ["applications"],
    queryFn: getApplications,
    refetchInterval: 5000, // pipeline chạy nền — cập nhật khi CV chuyển trạng thái.
  });
  // Tên vị trí cho từng hồ sơ (thiết kế hiện cột "Vị trí" thay cho "JD #id").
  const { data: jobs } = useQuery<JobPosting[]>({
    queryKey: ["jobs", "active"],
    queryFn: () => getJobs(),
  });
  const jobTitle = new Map((jobs ?? []).map((j) => [j.id, j.title]));

  const apps = data ?? [];
  const counts = apps.reduce<Record<string, number>>((acc, a) => {
    const b = statusBucket(a.status);
    acc[b] = (acc[b] ?? 0) + 1;
    return acc;
  }, {});
  const filtered = bucket === "all" ? apps : apps.filter((a) => statusBucket(a.status) === bucket);

  return (
    <div className="mx-auto max-w-[1120px] px-4 pb-8 pt-6 sm:px-8">
      <PageHeader
        eyebrow="Danh sách hồ sơ"
        title="Ứng viên"
        description="Toàn bộ CV đã nộp kèm điểm và trạng thái theo bốn rổ pipeline (PRD §13). Bấm một hàng để mở chi tiết điểm và agent trace."
      />

      {/* Bộ lọc theo rổ trạng thái */}
      <div className="flex flex-wrap gap-2">
        {BUCKET_FILTERS.map((f) => {
          const n = f.key === "all" ? apps.length : (counts[f.key] ?? 0);
          const active = bucket === f.key;
          return (
            <button
              key={f.key}
              type="button"
              onClick={() => setBucket(f.key)}
              aria-pressed={active}
              className={`rounded-lg border-2 px-3 py-1.5 text-[13px] font-semibold transition-colors ${
                active
                  ? "border-accent bg-accent text-white"
                  : "border-divider text-ink/70 hover:bg-ink/[0.06]"
              }`}
            >
              {f.label} <span className={active ? "text-white" : "text-ink/65"}>({n})</span>
            </button>
          );
        })}
      </div>

      {isError && (
        <p className="mt-4 rounded-lg border-2 border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          Không tải được danh sách ({String((error as Error)?.message)}). Vui lòng thử lại.
        </p>
      )}

      <div className="mt-4 overflow-hidden rounded-xl border-2 border-divider bg-canvas">
        {isLoading && <p className="px-4 py-6 text-sm text-ink/65">Đang tải danh sách…</p>}

        {!isLoading && filtered.length === 0 && (
          <p className="px-6 py-10 text-center text-[13px] text-ink/65">
            {apps.length === 0
              ? "Chưa có ứng viên nào — nộp CV qua cổng tuyển dụng công khai để pipeline chạy."
              : "Không có ứng viên trong rổ này."}
          </p>
        )}

        {filtered.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-sm">
              <thead>
                <tr>
                  {["Ứng viên", "Vị trí", "Điểm", "Trạng thái"].map((h, i) => (
                    <th
                      key={h}
                      className={`border-b-2 border-divider px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink/65 ${
                        i === 2 ? "text-right" : "text-left"
                      }`}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((a) => (
                  <tr key={a.id} className="border-b border-divider last:border-b-0 hover:bg-ink/[0.04]">
                    <td className="px-3 py-2">
                      <Link href={`/applications/${a.id}`} className="flex items-center gap-2.5">
                        <span className="flex h-[34px] w-[34px] flex-none items-center justify-center rounded-lg bg-steel-200 font-heading text-[13px] font-bold">
                          {initialsOf(a.applicant_email)}
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate font-semibold">
                            {a.applicant_email.split("@")[0]}
                          </span>
                          <span className="block truncate text-xs text-ink/65">
                            {a.applicant_email}
                          </span>
                        </span>
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-ink/75">
                      {a.job_id ? (jobTitle.get(a.job_id) ?? `JD #${a.job_id}`) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-heading text-base font-bold">
                      {a.score != null ? a.score : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Tag tone={statusTone(a.status)}>{statusLabel(a.status)}</Tag>
                        {/* Cờ "cần chú ý" chỉ là chỉ báo HÀNH ĐỘNG cho HR → CHỈ hiện khi còn chờ
                            quyết. Hồ sơ đã quyết chỉ hiện trạng thái cuối. */}
                        {a.status === "PENDING_REVIEW" && a.uncertainty_flags.length > 0 && (
                          <span className="text-xs font-semibold text-accent">
                            {a.uncertainty_flags.join(" · ")}
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
