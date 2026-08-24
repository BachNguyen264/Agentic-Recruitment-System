"use client";

import { useEffect, useState } from "react";

// Hai đích DUY NHẤT còn lại trên PWA (PRD §14 cột "Điện thoại"). Đây là nguồn sự thật cho CẢ điều
// hướng lẫn guard đường dẫn — hai danh sách viết tay song song chính là cách một màn được gỡ khỏi
// menu nhưng vẫn vào được bằng URL.
export const PWA_NAV_HREFS: readonly string[] = ["/applications", "/review"];

// `/` phải khớp CHÍNH XÁC — nó là tiền tố của mọi đường dẫn khác.
export function isHiddenOnPwa(pathname: string): boolean {
  if (pathname === "/") return true; // bảng điều hành
  return pathname.startsWith("/jobs") || pathname.startsWith("/cv-check");
}

// Hỏi CẢ BA display-mode chứ không riêng `standalone`: Android đôi khi cài ra `minimal-ui`, và
// `fullscreen` cũng là "đã cài". Hỏi mỗi `standalone` là chép giá trị của manifest sang chỗ thứ hai.
const STANDALONE_QUERY =
  "(display-mode: standalone), (display-mode: minimal-ui), (display-mode: fullscreen)";

// iOS Safari KHÔNG hỗ trợ display-mode cho web app trên Màn hình chính — nó dùng `navigator.standalone`
// (API không chuẩn, thiếu trong type của TS nên phải mở rộng; CLAUDE.md cấm `any`).
type IosNavigator = Navigator & { standalone?: boolean };

/**
 * `undefined` khi CHƯA biết (lần render đầu / SSR). Nơi gọi PHẢI chờ giá trị khác `undefined` rồi
 * mới vẽ điều hướng — nếu không sẽ nháy đủ 5 mục rồi mới rút còn 2.
 *
 * Giải MỘT LẦN trong effect, KHÔNG gắn listener: display-mode không đổi trong vòng đời một document
 * (rời app ra trình duyệt là mở document MỚI), nên listener chỉ là code chết.
 */
export function usePwaMode(): boolean | undefined {
  const [standalone, setStandalone] = useState<boolean | undefined>(undefined);

  useEffect(() => {
    const byDisplayMode = window.matchMedia(STANDALONE_QUERY).matches;
    const byIos = (navigator as IosNavigator).standalone === true;
    setStandalone(byDisplayMode || byIos);
  }, []);

  return standalone;
}
