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
      <span className="flex items-center gap-2 text-[13px] text-ink/65">
        <span
          className={`h-2 w-2 flex-none rounded-full ${ok ? "bg-accent" : "bg-red-500"}`}
          aria-hidden
        />
        {ok ? "hoạt động" : state}
      </span>
    </div>
  );
}

function clockOf(ms: number): string {
  return new Date(ms).toLocaleTimeString("vi-VN", { hour12: false });
}

// Nút bấm-để-kiểm. Hiện ở HAI chỗ (cạnh dòng "Tổng thể", và một mình khi lần nạp ĐẦU hỏng nên chưa
// có gì để hiện) — cùng một hành động thì phải cùng một cái nút, không phải hai bản sao rời nhau.
function RecheckButton({ busy, onClick }: { busy: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className="rounded-lg border-2 border-divider bg-canvas px-2.5 py-1 text-[12px] font-semibold hover:bg-ink/5 disabled:cursor-not-allowed disabled:opacity-55"
    >
      {busy ? "Đang kiểm…" : "Kiểm tra lại"}
    </button>
  );
}

export function ServiceStatus() {
  // KIỂM THEO YÊU CẦU, KHÔNG theo nhịp. Panel này không đóng góp tính năng nào — nó chỉ trả lời câu
  // "hạ tầng còn sống không", thứ HR hỏi khi NGHI NGỜ chứ không phải mỗi vài phút. Mà `/api/health`
  // là bản kiểm SÂU: mỗi lượt ping Postgres + Redis + Qdrant, và backend xếp nó chung hạn mức công
  // khai 20 lượt/giờ theo IP (`core/hardening._bucket`). Hỏi tự động = một tab mở cả ngày vẫn đốt
  // hạn mức Upstash free và giữ Neon không bao giờ tự ngủ, đổi lại không có gì.
  //
  // Nạp MỘT lần lúc mở trang (panel trống trông như hỏng), sau đó chỉ chạy khi HR bấm:
  // `staleTime: Infinity` + tắt mọi refetch tự động ⇒ đi ra đi vào dashboard trong cùng phiên KHÔNG
  // gọi lại. Vì dữ liệu nay là ẢNH CHỤP chứ không còn tươi, panel PHẢI nói rõ nó chụp lúc mấy giờ.
  const { data, isLoading, isFetching, isError, error, dataUpdatedAt, refetch } =
    useQuery<HealthStatus>({
      queryKey: ["health"],
      queryFn: () => getJson<HealthStatus>("/api/health"),
      refetchInterval: false,
      staleTime: Infinity,
      refetchOnMount: false,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    });

  // 429 = chạm hạn mức 20 lượt/giờ, KHÔNG phải backend sập. Hai chuyện này dẫn tới hai hành động
  // khác hẳn nhau (ngồi đợi vs đi cứu hệ thống) nên không được hiện chung một câu.
  const message = String((error as Error)?.message ?? "");
  const throttled = message.includes("429");

  return (
    <section>
      <h2 className="text-[22px]">Trạng thái dịch vụ</h2>
      <div className="mt-3 overflow-hidden rounded-xl border-2 border-divider bg-surface">
        {isLoading && <p className="px-4 py-4 text-sm text-ink/65">Đang kiểm tra…</p>}

        {/* Lỗi KHÔNG xoá kết quả lần kiểm trước: mất nó thì HR không còn gì để so sánh. */}
        {isError && (
          <p className="border-b border-divider bg-red-50 px-4 py-3 text-[13px] text-red-700">
            {throttled
              ? "Đã kiểm quá nhiều lần trong một giờ (giới hạn 20 lượt). Chờ ít phút rồi thử lại — đây là giới hạn chống lạm dụng, không phải sự cố hệ thống."
              : `Không gọi được backend (${message}).`}
          </p>
        )}

        {data && (
          <>
            <Row label="API (FastAPI)" state={data.api} />
            <Row label="Postgres (Neon)" state={data.services.postgres} />
            <Row label="Redis (Upstash)" state={data.services.redis} />
            <Row label="Qdrant Cloud" state={data.services.qdrant} />
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4 py-2.5">
              <span className="text-[13px] text-ink/65">
                Tổng thể:{" "}
                <span className={`font-bold ${data.status === "ok" ? "text-ink" : "text-red-600"}`}>
                  {data.status === "ok" ? "hoạt động" : data.status}
                </span>
                {dataUpdatedAt > 0 && (
                  <span className="text-ink/50"> · lúc {clockOf(dataUpdatedAt)}</span>
                )}
              </span>
              <RecheckButton busy={isFetching} onClick={() => void refetch()} />
            </div>
          </>
        )}

        {/* Lần nạp đầu hỏng → chưa có `data` nên khối trên không hiện; vẫn phải có đường bấm lại,
            nếu không panel kẹt ở thông báo lỗi cho tới khi HR tải lại cả trang. */}
        {isError && !data && (
          <div className="px-4 py-3">
            <RecheckButton busy={isFetching} onClick={() => void refetch()} />
          </div>
        )}
      </div>
    </section>
  );
}
