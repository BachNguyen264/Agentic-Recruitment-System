"use client";

import { useRef, useState } from "react";
import { PageHeader } from "@/components/ui";
import { AuditLogTab } from "./AuditLogTab";
import { ConfigTab } from "./ConfigTab";
import { InfraTab } from "./InfraTab";

// Màn quản trị của HR (PRD §NFR-8, §16/NFR-3). Ba tab vì cùng một khán giả (HR ở vai quản trị) và
// cùng một tần suất (hiếm) — gom một chỗ thay vì rải ba mục điều hướng.
//
// KHÔNG dùng `?tab=` + `useSearchParams`: nhóm route (hr) là client component nhưng trang vẫn được
// prerender lúc build, và `useSearchParams` ở đó đòi Suspense boundary — đổi lấy khả năng dán link
// vào một tab của màn quản trị thì không đáng.

const TABS = [
  { key: "config", label: "Cấu hình" },
  { key: "audit", label: "Nhật ký kiểm toán" },
  { key: "infra", label: "Hạ tầng" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function SystemPage() {
  const [tab, setTab] = useState<TabKey>("config");
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  // Điều hướng bằng phím mũi tên + Home/End: `role="tablist"` HỨA đúng hành vi này với trình đọc
  // màn hình. Khai role mà không cài phím là hứa suông — người dùng bàn phím sẽ Tab qua từng nút
  // trong khi trình đọc đã báo với họ rằng mũi tên mới là cách di chuyển.
  const onKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = TABS.length - 1;
    let next: number | null = null;
    if (e.key === "ArrowRight") next = index === last ? 0 : index + 1;
    else if (e.key === "ArrowLeft") next = index === 0 ? last : index - 1;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = last;
    if (next === null) return;
    e.preventDefault();
    setTab(TABS[next].key);
    tabRefs.current[next]?.focus();
  };

  return (
    <div className="mx-auto max-w-[1120px] px-4 pb-8 pt-6 sm:px-8">
      <PageHeader
        eyebrow="Quản trị"
        title="Cấu hình hệ thống"
        description="Ngưỡng chấm điểm, mốc nhắc/hết hạn, lịch phỏng vấn, mô hình AI và giới hạn an toàn — đổi được ngay, không cần deploy lại. Kèm nhật ký kiểm toán mọi quyết định và số liệu hạ tầng."
      />

      <div role="tablist" aria-label="Khu quản trị" className="flex flex-wrap gap-2">
        {TABS.map((t, i) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              ref={(el) => {
                tabRefs.current[i] = el;
              }}
              type="button"
              role="tab"
              id={`tab-${t.key}`}
              aria-selected={active}
              aria-controls={`panel-${t.key}`}
              // Roving tabindex: chỉ tab ĐANG chọn nằm trong luồng Tab, các tab còn lại vào bằng
              // phím mũi tên (đúng mẫu tabs của WAI-ARIA).
              tabIndex={active ? 0 : -1}
              onClick={() => setTab(t.key)}
              onKeyDown={(e) => onKeyDown(e, i)}
              className={`rounded-lg border-2 px-3.5 py-2 text-[13px] font-semibold transition-colors ${
                active
                  ? "border-accent bg-accent text-white"
                  : "border-divider text-ink/70 hover:bg-ink/[0.06]"
              }`}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Cấu hình + Nhật ký GIỮ NGUYÊN trong cây, chỉ ẩn đi: bản nháp cấu hình chưa lưu (và bộ lọc /
          số trang của nhật ký) sẽ mất sạch nếu tháo component ra khi đổi tab — mất im lặng, không
          một lời cảnh báo. Truy vấn của chúng gắn `enabled` theo tab nên tab chưa mở KHÔNG gọi API. */}
      <div
        role="tabpanel"
        id="panel-config"
        aria-labelledby="tab-config"
        hidden={tab !== "config"}
        className="mt-5"
      >
        <ConfigTab active={tab === "config"} />
      </div>

      <div
        role="tabpanel"
        id="panel-audit"
        aria-labelledby="tab-audit"
        hidden={tab !== "audit"}
        className="mt-5"
      >
        <AuditLogTab active={tab === "audit"} />
      </div>

      {/* Hạ tầng thì NGƯỢC LẠI — RUỘT chỉ dựng khi mở. Nó chứa `ServiceStatus`, component gọi
          `/api/health` ngay lúc mount (kiểm SÂU: ping Postgres + Qdrant, và nằm trong hạn mức
          20 lượt/giờ). Giữ nó luôn mounted nghĩa là mỗi lần vào /system lại đốt một lượt ping cho
          một tab có thể HR không hề mở. Tab này cũng không có state nào đáng giữ.
          Cái VỎ `<div role="tabpanel">` thì vẫn luôn có: `aria-controls` của nút tab trỏ vào id
          này, trỏ vào một phần tử không tồn tại là ARIA hỏng. */}
      <div
        role="tabpanel"
        id="panel-infra"
        aria-labelledby="tab-infra"
        hidden={tab !== "infra"}
        className="mt-5"
      >
        {tab === "infra" && <InfraTab />}
      </div>
    </div>
  );
}
