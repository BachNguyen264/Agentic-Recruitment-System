"use client";

import { useQuery } from "@tanstack/react-query";
import type { HealthMetrics } from "@ars/shared-types";
import { ServiceStatus } from "@/components/ServiceStatus";
import { getHealthMetrics } from "@/lib/admin";

// Tab 3 — Hạ tầng. Hai lớp KHÁC nhau, cố ý để cạnh nhau:
//   1. `ServiceStatus` (GET /api/health) — "Postgres/Qdrant còn sống không". Dùng lại NGUYÊN component
//      đã có ở bảng điều hành; nó cũng đang render ở `(hr)/page.tsx` và hai chỗ dùng CHUNG cache
//      (queryKey ["health"], staleTime Infinity) nên mở cả hai màn KHÔNG tốn thêm lượt ping nào.
//   2. `/api/health/metrics` — "tài nguyên nào sắp cạn". Thuần RAM, không chạm dịch vụ ngoài.

function num(v: number | null | undefined): string {
  return v == null ? "—" : String(v);
}

/** "3 / 15". Mẫu số vắng thì chỉ hiện tử số — đừng in "3 / —" như thể trần là một giá trị. */
function ratio(value: number | null | undefined, max: number | null | undefined): string {
  return max == null ? num(value) : `${num(value)} / ${max}`;
}

function formatBytes(bytes: number | null): string {
  if (bytes == null) return "—";
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatUptime(seconds: number | null): string {
  if (seconds == null) return "—";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h > 0) return `${h} giờ ${m} phút`;
  if (m > 0) return `${m} phút`;
  return `${total} giây`;
}

function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-divider px-4 py-2 last:border-b-0">
      <span className="text-[13px] text-ink/75">
        {label}
        {note && <span className="block text-xs text-ink/55">{note}</span>}
      </span>
      <span className="flex-none font-heading text-[15px] font-bold tabular-nums">{value}</span>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-xl border-2 border-divider bg-surface">
      <p className="border-b-2 border-divider px-4 py-2 text-[13px] font-semibold">{title}</p>
      {children}
    </div>
  );
}

export function InfraTab() {
  // ĐỌC MỘT LẦN + nút làm mới, KHÔNG poll. Endpoint này rẻ (thuần RAM) nên poll không hại DB, nhưng
  // nó cũng không phải đồng hồ thời gian thực của ai cả: HR mở tab này khi NGHI NGỜ, không phải để
  // ngồi nhìn. Vì dữ liệu là ẢNH CHỤP, panel phải nói rõ nó chụp lúc mấy giờ.
  const { data, isLoading, isError, error, isFetching, dataUpdatedAt, refetch } =
    useQuery<HealthMetrics>({
      queryKey: ["admin", "health-metrics"],
      queryFn: getHealthMetrics,
      refetchInterval: false,
      staleTime: Infinity,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    });

  return (
    <div className="space-y-6">
      <ServiceStatus />

      <section>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-[22px]">Tài nguyên tiến trình</h2>
            <p className="mt-1 max-w-[70ch] text-[13px] leading-relaxed text-ink/65">
              Đo ĐÚNG MỘT tiến trình backend — chính tiến trình vừa trả lời yêu cầu này. Bằng chứng
              bão hoà là hàng đợi &gt; 0, không phải riêng số luồng đang sống (luồng rảnh vẫn được
              giữ lại nên con số đó chỉ tăng).
            </p>
          </div>
          <button
            type="button"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="rounded-lg border-2 border-divider bg-canvas px-2.5 py-1 text-[12px] font-semibold hover:bg-ink/5 disabled:cursor-not-allowed disabled:opacity-55"
          >
            {isFetching ? "Đang đo…" : "Đo lại"}
          </button>
        </div>

        {isLoading && <p className="mt-3 text-sm text-ink/65">Đang đo…</p>}

        {isError && (
          <p
            role="alert"
            className="mt-3 rounded-lg border-2 border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700"
          >
            Không đọc được số liệu ({String((error as Error)?.message)}).
          </p>
        )}

        {data && (
          <>
            {/* Endpoint tự cứu khi đọc số hỏng: nó trả dict-toàn-null kèm tên exception thay vì 500.
                Không nói ra thì một bảng toàn dấu gạch trông như "hệ thống đang rỗi". */}
            {data.error && (
              <p className="mt-3 rounded-lg border-2 border-amber-300 bg-amber-50 px-4 py-2.5 text-[13px] text-amber-900">
                Backend không đọc được đồng hồ đo ({data.error}) — mọi ô dưới đây là rỗng vì lý do
                kỹ thuật, không phải vì hệ thống đang nhàn.
              </p>
            )}

            {dataUpdatedAt > 0 && (
              <p className="mt-3 text-[13px] text-ink/55">
                Ảnh chụp lúc {new Date(dataUpdatedAt).toLocaleTimeString("vi-VN", { hour12: false })}
              </p>
            )}

            <div className="mt-3 grid gap-4 md:grid-cols-2">
              <Panel title="Pool Postgres (SQLAlchemy)">
                <Metric
                  label="Đang mượn / trần"
                  value={ratio(data.db_pool.checked_out, data.db_pool.max)}
                />
                <Metric label="Đang rảnh" value={num(data.db_pool.checked_in)} />
                <Metric
                  label="Overflow"
                  value={num(data.db_pool.overflow)}
                  note="Số ÂM là bình thường — pool cơ sở còn chỗ trống."
                />
              </Panel>

              <Panel title="Pool checkpointer (LangGraph)">
                <Metric
                  label="Đang mượn / trần"
                  value={ratio(data.checkpointer_pool.checked_out, data.checkpointer_pool.max)}
                />
                <Metric label="Đang rảnh" value={num(data.checkpointer_pool.available)} />
                <Metric
                  label="Đang xếp hàng"
                  value={num(data.checkpointer_pool.waiting)}
                  note="Pool RIÊNG, cạn độc lập với pool ở trên."
                />
              </Panel>

              <Panel title="Thread pool asyncio (parser · R2 · email)">
                <Metric
                  label="Luồng đã sinh / trần"
                  value={ratio(data.executor.threads_alive, data.executor.max_workers)}
                />
                <Metric label="Đang xếp hàng" value={num(data.executor.queue_depth)} />
              </Panel>

              <Panel title="Thread pool anyio (đường nhận CV)">
                <Metric
                  label="Đang mượn / trần"
                  value={ratio(data.anyio_threads.borrowed, data.anyio_threads.total_tokens)}
                />
                <Metric label="Đang chờ token" value={num(data.anyio_threads.waiting)} />
              </Panel>

              <Panel title="Thread pool lưu trữ (R2)">
                <Metric
                  label="Luồng đã sinh / trần"
                  value={ratio(
                    data.storage_executor.threads_alive,
                    data.storage_executor.max_workers,
                  )}
                />
                <Metric label="Đang xếp hàng" value={num(data.storage_executor.queue_depth)} />
              </Panel>

              <Panel title="Pipeline chấm CV">
                <Metric
                  label="Đang chạy / trần đồng thời"
                  value={ratio(data.pipelines.in_flight, data.pipelines.limit)}
                />
                <Metric
                  label="Đang chờ tới lượt"
                  value={num(data.pipelines.queued)}
                  note="Chỉ đếm lượt chạy ĐẦU của một CV — không đếm lượt resume của Screener."
                />
                <Metric
                  label="Đã chạy / xong / hỏng"
                  value={`${num(data.pipelines.started_total)} · ${num(
                    data.pipelines.finished_total,
                  )} · ${num(data.pipelines.failed_total)}`}
                />
              </Panel>

              <Panel title="Tiến trình">
                <Metric
                  label="Bộ nhớ (RSS)"
                  value={formatBytes(data.rss_bytes)}
                  note="Chỉ đo được trên Linux (prod) — máy dev Windows luôn là dấu gạch."
                />
                <Metric label="Thời gian chạy" value={formatUptime(data.uptime_seconds)} />
                <Metric label="Số CPU" value={num(data.cpu_count)} />
              </Panel>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
