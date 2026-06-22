"use client";

import { useQuery } from "@tanstack/react-query";
import type { HealthStatus } from "@ars/shared-types";
import { getJson } from "@/lib/api";

function Dot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block h-3 w-3 rounded-full ${ok ? "bg-green-500" : "bg-red-500"}`}
      aria-hidden
    />
  );
}

function Row({ label, state }: { label: string; state: string }) {
  const ok = state === "ok";
  return (
    <div className="flex items-center justify-between rounded-md border border-slate-200 bg-white px-4 py-2">
      <span className="font-medium">{label}</span>
      <span className="flex items-center gap-2 text-sm">
        <Dot ok={ok} />
        <span className={ok ? "text-green-700" : "text-red-700"}>{state}</span>
      </span>
    </div>
  );
}

export function ServiceStatus() {
  const { data, isLoading, isError, error } = useQuery<HealthStatus>({
    queryKey: ["health"],
    queryFn: () => getJson<HealthStatus>("/api/health"),
    refetchInterval: 5000,
  });

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">Trạng thái dịch vụ</h2>
      {isLoading && <p className="text-sm text-slate-500">Đang kiểm tra…</p>}
      {isError && (
        <p className="text-sm text-red-600">
          Không gọi được backend ({String((error as Error)?.message)}). Backend đã chạy ở :8000 chưa?
        </p>
      )}
      {data && (
        <div className="space-y-2">
          <Row label="API (FastAPI)" state={data.api} />
          <Row label="Postgres (Neon)" state={data.services.postgres} />
          <Row label="Redis (Upstash)" state={data.services.redis} />
          <Row label="Qdrant Cloud" state={data.services.qdrant} />
          <p className="pt-1 text-sm text-slate-500">
            Tổng thể: <span className="font-medium">{data.status}</span>
          </p>
        </div>
      )}
    </section>
  );
}
