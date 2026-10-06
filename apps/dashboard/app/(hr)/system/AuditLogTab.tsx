"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { AuditLogItem, AuditLogPage } from "@ars/shared-types";
import { inputClass, Tag } from "@/components/ui";
import { auditNodeLabel, getAuditLog, getAuditNodes, type AuditLogRange } from "@/lib/admin";
import { formatVnDateTime, vnDayStartIso, vnNextDayStartIso } from "@/lib/datetime";

// Tab 2 — Nhật ký kiểm toán (PRD §16 / NFR-3 / FR-PIPE-4). Trước slice này bảng `audit_log` được 8
// service ghi rất dày nhưng KHÔNG có đường đọc nào; muốn tra phải vào thẳng Postgres.

// `detail` JSONB có thể khá nặng nên trang nhỏ hơn danh sách hồ sơ (50).
const PAGE_SIZE = 25;

// Cột cuối không có nhãn (nút mở rộng) — `colSpan` của hàng chi tiết phải khớp số cột này.
const COLUMNS: { key: string; label: string; align?: "right" }[] = [
  { key: "time", label: "Thời gian" },
  { key: "node", label: "Bước" },
  { key: "action", label: "Hành động" },
  { key: "applicant", label: "Ứng viên" },
  { key: "confidence", label: "Tự tin", align: "right" },
  { key: "reason", label: "Lý do leo thang" },
  { key: "expand", label: "", align: "right" },
];

function Row({
  item,
  expanded,
  onToggle,
}: {
  item: AuditLogItem;
  expanded: boolean;
  onToggle: () => void;
}) {
  const hasDetail = Object.keys(item.detail).length > 0;
  const panelId = `audit-detail-${item.id}`;

  return (
    <>
      <tr className="border-b border-divider align-top last:border-b-0">
        <td className="whitespace-nowrap px-3 py-2 text-ink/75">
          {formatVnDateTime(item.created_at)}
        </td>
        <td className="px-3 py-2">
          <Tag tone="neutral">{auditNodeLabel(item.node)}</Tag>
        </td>
        {/* `action` giữ NGUYÊN chuỗi kỹ thuật ("route:human_review", "email_sent:invite"): nó là
            khoá đối soát với code, dịch sang tiếng Việt là mất khả năng grep ngược lại nguồn ghi. */}
        <td className="px-3 py-2 font-mono text-xs text-ink">{item.action}</td>
        <td className="px-3 py-2">
          {item.application_id == null ? (
            <span className="text-ink/55">hệ thống</span>
          ) : (
            <Link
              href={`/applications/${item.application_id}`}
              className="text-accent hover:underline"
            >
              {item.applicant_email ?? `Hồ sơ #${item.application_id}`}
            </Link>
          )}
        </td>
        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
          {item.confidence == null ? "—" : item.confidence.toFixed(2)}
        </td>
        <td className="px-3 py-2 text-ink/75">{item.escalation_reason ?? "—"}</td>
        <td className="px-3 py-2 text-right">
          {hasDetail ? (
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={expanded}
              aria-controls={panelId}
              className="rounded-lg border-2 border-divider px-2.5 py-1 text-xs font-semibold hover:bg-ink/[0.06]"
            >
              {expanded ? "Ẩn" : "Chi tiết"}
            </button>
          ) : (
            <span className="text-ink/55">—</span>
          )}
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-divider">
          <td colSpan={COLUMNS.length} className="px-3 pb-3">
            <pre
              id={panelId}
              className="ars-scroll overflow-x-auto rounded-lg border-2 border-divider bg-surface p-3 text-xs leading-relaxed"
            >
              {JSON.stringify(item.detail, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}

export function AuditLogTab({ active }: { active: boolean }) {
  const [node, setNode] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(() => new Set<number>());
  // Ngày theo giờ VN, dạng YYYY-MM-DD của <input type="date">; "" = không giới hạn phía đó. Cả hai
  // đầu tính TRỌN NGÀY: "đến 06/10" nghĩa là hết 23:59 ngày 06/10 (gửi lên mốc đầu ngày 07/10).
  const [fromDay, setFromDay] = useState("");
  const [toDay, setToDay] = useState("");
  // `min`/`max` của ô ngày chỉ ràng buộc bộ chọn — gõ tay vẫn ra khoảng ngược, và Chrome cho gõ cả
  // năm 5–6 chữ số (ô date nhận tới năm 275760; bắt gặp thật khi kiểm). Chặn ở đây (so chuỗi
  // YYYY-MM-DD là so ngày) thay vì để backend trả 422 rồi hiện như "không tải được nhật ký".
  // Năm 1970–2999 (khớp chốt chặn backend `admin._created_range`): ngoài khoảng đó backend trả 422, và
  // năm 0000–0099 còn bị `Date.UTC` hiểu thành 1900–1999 khi tính mốc ngày hôm sau.
  const wellFormed = (day: string) =>
    day === "" ||
    (/^\d{4}-\d{2}-\d{2}$/.test(day) && Number(day.slice(0, 4)) >= 1970 && Number(day.slice(0, 4)) <= 2999);
  const malformed = !wellFormed(fromDay) || !wellFormed(toDay);
  const reversed = !malformed && fromDay !== "" && toDay !== "" && fromDay > toDay;
  const badRange = malformed || reversed;
  // Chỉ dựng mốc khi ngày HỢP LỆ: với năm vượt giới hạn của `Date` (vd 275760), `toISOString()`
  // trong `vnNextDayStartIso` NÉM lỗi và làm sập cả tab — chứ không chỉ ra một khoảng sai.
  const range: AuditLogRange = badRange
    ? {}
    : {
        createdFrom: fromDay ? vnDayStartIso(fromDay) : undefined,
        createdTo: toDay ? vnNextDayStartIso(toDay) : undefined,
      };

  // Số đếm theo bước đi theo CÙNG khoảng ngày — chip "Tất cả (n)" phải khớp tổng của bảng bên dưới.
  const { data: nodeCounts } = useQuery<Record<string, number>>({
    queryKey: ["admin", "audit-nodes", fromDay, toDay],
    queryFn: () => getAuditNodes(range),
    enabled: active && !badRange,
  });

  const { data: fetched, isLoading, isError, error } = useQuery<AuditLogPage>({
    queryKey: ["admin", "audit-log", node, offset, fromDay, toDay],
    queryFn: () => getAuditLog({ node: node ?? undefined, limit: PAGE_SIZE, offset, ...range }),
    enabled: active && !badRange,
    placeholderData: (prev) => prev,
  });
  // Khoảng sai thì query tắt nhưng `placeholderData` vẫn giữ bảng của khoảng TRƯỚC — hiện nó ra là
  // trình bày dữ liệu cũ như thể thuộc khoảng mới. Không hiện gì ngoài lời nhắc.
  const data = badRange ? undefined : fetched;

  // Đổi bộ lọc = xem một TẬP khác ⇒ phải về trang 1. Giữ nguyên offset thì đang ở trang 4 mà lọc
  // sang một node chỉ có 12 bản ghi sẽ ra bảng RỖNG — trông hệt như "node này không có dữ liệu".
  const selectNode = (next: string | null) => {
    setNode(next);
    setOffset(0);
  };
  const changeDays = (from: string, to: string) => {
    setFromDay(from);
    setToDay(to);
    setOffset(0);
  };

  const toggle = (id: number) =>
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const hasMore = offset + items.length < total;

  // Chip "Tất cả" cộng từ chính `nodeCounts` (GROUP BY trong khoảng ngày đang lọc) — không đếm trong
  // trang đang xem.
  const allCount = Object.values(nodeCounts ?? {}).reduce((t, n) => t + n, 0);
  const chips: { key: string | null; label: string; count: number | null }[] = [
    { key: null, label: "Tất cả", count: nodeCounts ? allCount : null },
    ...Object.entries(nodeCounts ?? {}).map(([n, count]) => ({
      key: n,
      label: auditNodeLabel(n),
      count,
    })),
  ];
  // Thu hẹp khoảng ngày có thể làm bước ĐANG CHỌN không còn bản ghi nào ⇒ chip của nó biến mất khỏi
  // danh sách trong khi bộ lọc vẫn đang áp — bảng rỗng mà không thấy vì sao. Giữ chip đó với số 0.
  if (nodeCounts && node !== null && !(node in nodeCounts)) {
    chips.push({ key: node, label: auditNodeLabel(node), count: 0 });
  }
  const filteringDays = fromDay !== "" || toDay !== "";

  return (
    <div>
      {/* Lọc theo ngày (giờ VN, trọn ngày ở cả hai đầu). Đặt TRƯỚC chip bước: khoanh thời gian là câu
          hỏi đầu tiên khi tra một sự cố ("hôm qua có gì?"), và số trên chip đi theo khoảng này. */}
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="flex w-[170px] flex-col gap-1">
          <label htmlFor="audit-from" className="text-[13px] font-semibold text-ink/70">
            Từ ngày
          </label>
          <input
            id="audit-from"
            type="date"
            value={fromDay}
            max={toDay || undefined}
            onChange={(e) => changeDays(e.target.value, toDay)}
            className={inputClass}
          />
        </div>
        <div className="flex w-[170px] flex-col gap-1">
          <label htmlFor="audit-to" className="text-[13px] font-semibold text-ink/70">
            Đến ngày
          </label>
          <input
            id="audit-to"
            type="date"
            value={toDay}
            min={fromDay || undefined}
            onChange={(e) => changeDays(fromDay, e.target.value)}
            className={inputClass}
          />
        </div>
        {filteringDays && (
          <button
            type="button"
            onClick={() => changeDays("", "")}
            className="rounded-lg border-2 border-divider px-3 py-1.5 text-[13px] font-semibold text-ink/70 transition-colors hover:bg-ink/[0.06]"
          >
            Xoá lọc ngày
          </button>
        )}
      </div>
      {badRange && (
        <p role="alert" className="mb-4 text-[13px] font-semibold text-red-700">
          {malformed
            ? "Ngày không hợp lệ — năm phải từ 1970 đến 2999."
            : "“Từ ngày” phải trước hoặc bằng “Đến ngày”."}
        </p>
      )}

      {/* Bộ lọc theo node — chỉ hiện node THỰC SỰ có dữ liệu (endpoint /audit-log/nodes chỉ trả
          những node đã ghi), nên không có chip nào bấm vào ra bảng rỗng. */}
      <div className="flex flex-wrap gap-2">
        {chips.map((c) => {
          const isActive = node === c.key;
          return (
            <button
              key={c.key ?? "__all__"}
              type="button"
              onClick={() => selectNode(c.key)}
              aria-pressed={isActive}
              className={`rounded-lg border-2 px-3 py-1.5 text-[13px] font-semibold transition-colors ${
                isActive
                  ? "border-accent bg-accent text-white"
                  : "border-divider text-ink/70 hover:bg-ink/[0.06]"
              }`}
            >
              {c.label}{" "}
              <span className={isActive ? "text-white" : "text-ink/65"}>({c.count ?? "…"})</span>
            </button>
          );
        })}
      </div>

      {/* Khoảng ngày sai thì query đã tắt — lỗi còn treo (nếu có) thuộc về một lượt tải cũ, hiện nó
          cạnh lời nhắc ở trên là hai thông báo đỏ nói hai chuyện. */}
      {isError && !badRange && (
        <p
          role="alert"
          className="mt-4 rounded-lg border-2 border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700"
        >
          Không tải được nhật ký ({String((error as Error)?.message)}). Vui lòng thử lại.
        </p>
      )}

      {/* Thiếu dòng này thì một trang đầy trông y hệt "toàn bộ dữ liệu". */}
      {data && items.length > 0 && (
        <p className="mt-4 text-[13px] text-ink/65">
          Đang hiện{" "}
          <strong className="font-semibold text-ink">
            {offset + 1}–{offset + items.length}
          </strong>{" "}
          trong <strong className="font-semibold text-ink">{total}</strong> bản ghi.
        </p>
      )}

      <div className="mt-4 overflow-hidden rounded-xl border-2 border-divider bg-canvas">
        {isLoading && <p className="px-4 py-6 text-sm text-ink/65">Đang tải nhật ký…</p>}

        {/* Cổng `data &&`: lúc fetch HỎNG thì `data` là undefined — không có cổng này màn hình in
            "Chưa có bản ghi nào" như một SỰ THẬT, ngay dưới banner đỏ báo lỗi tải. */}
        {!isLoading && data && items.length === 0 && (
          <p className="px-6 py-10 text-center text-[13px] text-ink/65">
            {node === null
              ? filteringDays
                ? "Không có bản ghi nào trong khoảng ngày đã chọn."
                : "Chưa có bản ghi nào — nhật ký sẽ đầy dần khi CV chạy qua pipeline."
              : filteringDays
                ? "Không có bản ghi nào của bước này trong khoảng ngày đã chọn."
                : "Không có bản ghi nào của bước này."}
          </p>
        )}

        {items.length > 0 && (
          <div className="ars-scroll overflow-x-auto">
            <table className="w-full min-w-[900px] border-collapse text-sm">
              <thead>
                <tr>
                  {COLUMNS.map((col) => (
                    <th
                      key={col.key}
                      className={`border-b-2 border-divider px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink/65 ${
                        col.align === "right" ? "text-right" : "text-left"
                      }`}
                    >
                      {col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <Row
                    key={item.id}
                    item={item}
                    expanded={expanded.has(item.id)}
                    onToggle={() => toggle(item.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {(hasMore || offset > 0) && (
        <div className="mt-4 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            disabled={offset === 0 || isLoading}
            className="rounded-lg border-2 border-divider px-4 py-2 text-[13px] font-semibold text-ink/70 transition-colors hover:bg-ink/[0.06] disabled:cursor-not-allowed disabled:opacity-40"
          >
            ← Trang trước
          </button>
          <span className="text-[13px] text-ink/65">
            Trang {Math.floor(offset / PAGE_SIZE) + 1} / {Math.max(1, Math.ceil(total / PAGE_SIZE))}
          </span>
          <button
            type="button"
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
            disabled={!hasMore || isLoading}
            className="rounded-lg border-2 border-divider px-4 py-2 text-[13px] font-semibold text-ink/70 transition-colors hover:bg-ink/[0.06] disabled:cursor-not-allowed disabled:opacity-40"
          >
            Trang sau →
          </button>
        </div>
      )}
    </div>
  );
}
