"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ApplicationListItem } from "@ars/shared-types";
import { getApplications } from "@/lib/api";
import {
  BUCKET_FILTERS,
  statusBadgeClass,
  statusBucket,
  statusLabel,
  type StatusBucket,
} from "@/lib/applications";

// Định dạng thời gian xác định (tránh lệch hydrate do locale/timezone): "YYYY-MM-DD HH:mm".
function fmtDate(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

function Row({ app }: { app: ApplicationListItem }) {
  return (
    <Link
      href={`/applications/${app.id}`}
      className="block rounded-md border border-slate-200 bg-white px-4 py-3 transition-colors hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-medium text-slate-900">{app.applicant_email}</p>
          <p className="mt-0.5 text-xs text-slate-400">
            JD #{app.job_id ?? "—"} · {fmtDate(app.created_at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-slate-500">
            Điểm:{" "}
            <span className="font-semibold text-slate-800">
              {app.score != null ? app.score : "—"}
            </span>
          </span>
          <span
            className={`rounded px-2 py-0.5 text-sm font-medium ${statusBadgeClass(app.status)}`}
          >
            {statusLabel(app.status)}
          </span>
        </div>
      </div>
      {app.uncertainty_flags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {app.uncertainty_flags.map((flag) => (
            <span
              key={flag}
              className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800"
            >
              {flag}
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}

export default function ApplicationsPage() {
  const [bucket, setBucket] = useState<StatusBucket | "all">("all");
  const { data, isLoading, isError, error } = useQuery<ApplicationListItem[]>({
    queryKey: ["applications"],
    queryFn: getApplications,
    refetchInterval: 5000, // pipeline chạy nền — cập nhật khi CV chuyển trạng thái.
  });

  const apps = data ?? [];
  const counts = apps.reduce<Record<string, number>>((acc, a) => {
    const b = statusBucket(a.status);
    acc[b] = (acc[b] ?? 0) + 1;
    return acc;
  }, {});
  const filtered = bucket === "all" ? apps : apps.filter((a) => statusBucket(a.status) === bucket);

  return (
    <main className="mx-auto max-w-4xl space-y-6 p-8">
      <header className="space-y-1">
        <Link href="/" className="text-sm text-slate-500 hover:underline">
          ← Về dashboard
        </Link>
        <h1 className="text-2xl font-bold">Ứng viên</h1>
        <p className="text-sm text-slate-500">
          Danh sách CV đã nộp kèm điểm + trạng thái (PRD §13). Bấm một ứng viên để xem chi tiết
          điểm. Chỉ đọc — duyệt/từ chối là bước sau.
        </p>
      </header>

      {/* Bộ lọc theo ba rổ trạng thái */}
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
              className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 ${
                active
                  ? "border-slate-800 bg-slate-800 text-white"
                  : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
              }`}
            >
              {f.label} <span className={active ? "text-slate-300" : "text-slate-400"}>({n})</span>
            </button>
          );
        })}
      </div>

      {isLoading && <p className="text-sm text-slate-500">Đang tải danh sách…</p>}
      {isError && (
        <p className="text-sm text-red-600">
          Không tải được danh sách ({String((error as Error)?.message)}). Backend đã chạy ở :8000
          chưa?
        </p>
      )}
      {data && filtered.length === 0 && (
        <p className="text-sm text-slate-400">
          {apps.length === 0
            ? "Chưa có ứng viên nào — nộp CV qua trang công khai để pipeline chạy."
            : "Không có ứng viên trong rổ này."}
        </p>
      )}

      <div className="space-y-2">
        {filtered.map((app) => (
          <Row key={app.id} app={app} />
        ))}
      </div>
    </main>
  );
}
