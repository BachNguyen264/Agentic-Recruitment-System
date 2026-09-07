"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { AuditLogItem, AuditLogPage } from "@ars/shared-types";
import { Tag } from "@/components/ui";
import { auditNodeLabel, getAuditLog, getAuditNodes } from "@/lib/admin";
import { formatVnDateTime } from "@/lib/datetime";

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

  const { data: nodeCounts } = useQuery<Record<string, number>>({
    queryKey: ["admin", "audit-nodes"],
    queryFn: getAuditNodes,
    enabled: active,
  });

  const { data, isLoading, isError, error } = useQuery<AuditLogPage>({
    queryKey: ["admin", "audit-log", node, offset],
    queryFn: () => getAuditLog({ node: node ?? undefined, limit: PAGE_SIZE, offset }),
    enabled: active,
    placeholderData: (prev) => prev,
  });

  // Đổi bộ lọc = xem một TẬP khác ⇒ phải về trang 1. Giữ nguyên offset thì đang ở trang 4 mà lọc
  // sang một node chỉ có 12 bản ghi sẽ ra bảng RỖNG — trông hệt như "node này không có dữ liệu".
  const selectNode = (next: string | null) => {
    setNode(next);
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

  // Chip "Tất cả" cộng từ chính `nodeCounts` (GROUP BY toàn bảng) — không đếm trong trang đang xem.
  const allCount = Object.values(nodeCounts ?? {}).reduce((t, n) => t + n, 0);
  const chips: { key: string | null; label: string; count: number | null }[] = [
    { key: null, label: "Tất cả", count: nodeCounts ? allCount : null },
    ...Object.entries(nodeCounts ?? {}).map(([n, count]) => ({
      key: n,
      label: auditNodeLabel(n),
      count,
    })),
  ];

  return (
    <div>
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

      {isError && (
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
              ? "Chưa có bản ghi nào — nhật ký sẽ đầy dần khi CV chạy qua pipeline."
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
