"use client";

import { useEffect, useState } from "react";

// Hai đích DUY NHẤT còn lại trên PWA (PRD §14 cột "Điện thoại"). Đây là nguồn sự thật DUY NHẤT — guard
// bên dưới SUY RA trực tiếp từ danh sách này, không phải một danh sách viết tay song song. Trước đây
// `isHiddenOnPwa` tự liệt kê `/jobs`/`/cv-check`, nghĩa là route (hr) tiếp theo ai đó thêm vào sẽ bị
// gỡ khỏi menu (không nằm trong mảng này) nhưng vẫn vào được bằng URL (không nằm trong deny-list) —
// đúng lỗ hổng mà một-nguồn-sự-thật phải chặn. Suy từ allow-list này ra guard thì route mới mặc định
// BỊ ẨN cho tới khi chủ động thêm vào đây (an toàn theo hướng đóng), thay vì mặc định HIỆN.
export const PWA_NAV_HREFS: readonly string[] = ["/applications", "/review"];

// Hiện = khớp CHÍNH XÁC một href trong PWA_NAV_HREFS, hoặc là route con của nó (`/applications/42`).
// Mọi pathname khác — kể cả `/`, tiền tố của mọi đường dẫn — đều bị ẩn vì không khớp phần tử nào.
export function isHiddenOnPwa(pathname: string): boolean {
  return !PWA_NAV_HREFS.some((href) => pathname === href || pathname.startsWith(`${href}/`));
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
