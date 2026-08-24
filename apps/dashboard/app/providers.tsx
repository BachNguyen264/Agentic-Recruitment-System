"use client";

import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

// BUG-1: TanStack khởi tạo `onlineManager` với `online = true` CỨNG và chỉ gắn listener
// `online`/`offline` — nó KHÔNG BAO GIỜ đọc `navigator.onLine` (xem query-core/onlineManager.js).
// Hệ quả: mở app khi máy ĐÃ offline sẵn (bật máy bay rồi mới mở PWA) thì không có sự kiện chuyển
// trạng thái nào để bắt, thư viện tưởng đang online, query vẫn chạy thật và `fetch` ném TypeError.
// Seed một lần lúc dựng client để trạng thái ban đầu khớp thực tế — đây là ĐIỀU KIỆN TIÊN QUYẾT để
// nhánh `fetchStatus === "paused"` ở layout HR có cơ hội chạy.
//
// Đặt trong initializer của useState (chạy TRƯỚC lần render đầu) chứ không phải useEffect: cổng chờ
// ở layout đọc trạng thái ngay ở render đầu tiên, effect thì chạy sau — quá muộn.
// Guard PHẢI là `window`, KHÔNG phải `navigator`: Node 24 CÓ sẵn `globalThis.navigator` (thêm từ
// Node 21) nhưng nó KHÔNG có `onLine` → `navigator.onLine` là `undefined`. Nếu guard bằng
// `typeof navigator === "undefined"` thì lúc SSR ta gọi `setOnline(undefined)`, mà `onlineManager`
// là SINGLETON CẤP MODULE dùng chung cho MỌI request trên server → cả tiến trình render thành
// "offline" vĩnh viễn → query bị pause khi SSR → HTML server khác client → VỠ HYDRATION trên mọi
// trang, gồm cả luồng ứng viên công khai. Đã tái hiện thật rồi mới sửa.
function seedOnlineState(): void {
  if (typeof window === "undefined") return; // SSR
  if (typeof navigator.onLine !== "boolean") return; // môi trường không có API này
  onlineManager.setOnline(navigator.onLine);
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => {
    seedOnlineState();
    return new QueryClient();
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
