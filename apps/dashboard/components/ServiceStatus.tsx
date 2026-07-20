"use client";

import { useQuery } from "@tanstack/react-query";
import type { HealthStatus } from "@ars/shared-types";
import { getJson } from "@/lib/api";

// Trạng thái hạ tầng (GET /api/health). UI redesign: panel phẳng viền 2px, chấm trạng thái
// xanh/đỏ theo giá trị THẬT từ backend — không tô xanh khi dịch vụ lỗi.
function Row({ label, state }: { label: string; state: string }) {
  const ok = state === "ok";
  return (
    <div className="flex items-center justify-between border-b border-divider px-4 py-2.5 last:border-b-0">
      <span className="text-[13px] font-semibold">{label}</span>
      <span className="flex items-center gap-2 text-[13px] text-ink/60">
        <span
          className={`h-2 w-2 flex-none rounded-full ${ok ? "bg-accent" : "bg-red-500"}`}
          aria-hidden
        />
        {ok ? "hoạt động" : state}
      </span>
    </div>
  );
}

export function ServiceStatus() {
  // NHỊP HỎI: 5 PHÚT, KHÔNG phải vài giây. `/api/health` là bản kiểm SÂU — mỗi lượt ping
  // Postgres + Redis + Qdrant, và backend xếp nó chung hạn mức công khai (20 lượt/giờ, xem
  // core/hardening._bucket). Hỏi mỗi 5s = 720 lượt/giờ → 429 sau ~100 giây (panel này tự hỏng),
  // và trên bản live thì một tab dashboard mở cả ngày ≈ 17k lượt/ngày: đốt sạch hạn mức Upstash
  // free (10k lệnh/ngày) + giữ Neon không bao giờ tự ngủ. Trạng thái hạ tầng đổi rất hiếm nên
  // 5 phút là đủ; tắt refetch-khi-focus để chuyển tab không tiêu thêm lượt.
  const { data, isLoading, isError, error } = useQuery<HealthStatus>({
    queryKey: ["health"],
    queryFn: () => getJson<HealthStatus>("/api/health"),
    refetchInterval: 300_000,
    refetchOnWindowFocus: false,
  });

  return (
    <section>
      <h2 className="text-[22px]">Trạng thái dịch vụ</h2>
      <div className="mt-3 overflow-hidden rounded-xl border-2 border-divider bg-surface">
        {isLoading && <p className="px-4 py-4 text-sm text-ink/50">Đang kiểm tra…</p>}
        {isError && (
          <p className="px-4 py-4 text-sm text-red-600">
            Không gọi được backend ({String((error as Error)?.message)}). Backend đã chạy ở :8000 chưa?
          </p>
        )}
        {data && (
          <>
            <Row label="API (FastAPI)" state={data.api} />
            <Row label="Postgres (Neon)" state={data.services.postgres} />
            <Row label="Redis (Upstash)" state={data.services.redis} />
            <Row label="Qdrant Cloud" state={data.services.qdrant} />
            <div className="px-4 py-2.5 text-[13px] text-ink/55">
              Tổng thể:{" "}
              <span className={`font-bold ${data.status === "ok" ? "text-ink" : "text-red-600"}`}>
                {data.status === "ok" ? "hoạt động" : data.status}
              </span>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
