# PWA-1 — Tinh gọn màn hình PWA + trang offline · Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Khi HR mở app từ icon đã cài (standalone), PWA chỉ còn Đăng nhập + Ứng viên (chỉ đọc) + Hàng đợi review; mất mạng thì hiện một trang "Mất kết nối" có thương hiệu thay vì màn lỗi của trình duyệt.

**Architecture:** Toàn bộ là frontend, không đụng backend, không migration. Nhận diện standalone bằng `matchMedia` + `navigator.standalone`, giải một lần sau khi mount, và layout `(hr)` **tự dựng cổng chờ riêng** (không mượn cổng `getMe` — xem Global Constraints). Điều hướng lọc từ 5 mục còn 2; route bị ẩn thì `router.replace("/review")`. Trang offline là một route TĨNH ngoài nhóm `(hr)`, được service worker precache lúc install và phục vụ khi điều hướng thất bại.

**Tech Stack:** Next.js 14.2.35 (App Router) · React 18 · TanStack Query v5.101 · Tailwind 3.4 thuần · Service Worker viết tay (`public/sw.js`)

**Spec:** `docs/superpowers/specs/2026-08-24-pwa-mobile.md` (§3.4–3.8, §6). Đọc spec cùng plan — plan này lập luận DỰA TRÊN spec đó.

**Đã ship trước plan này:** BUG-1 (`be1adc5`) — seed `onlineManager`, nhánh `fetchStatus === "paused"`, `networkMode: "always"` ở mutation duyệt. Plan này giả định các thay đổi đó ĐÃ có trong `main`.

## Global Constraints

- **KHÔNG thêm thư viện UI.** Tailwind thuần + component tự viết (CLAUDE.md). shadcn/ui không được cài.
- **KHÔNG dùng `any`** (CLAUDE.md: full typing). `navigator.standalone` là API không chuẩn ⇒ mở rộng type, không ép `any`.
- **KHÔNG đụng `apps/backend`.** PWA-1 là frontend thuần. Không migration, không endpoint mới.
- **KHÔNG sửa `components/ui.tsx` `btn()`** — đã bị cắt khỏi phạm vi (spec §10). 44px là WCAG 2.5.5 **AAA**; mức AA (2.5.8) là 24×24 và `ghost` 25.5px đã đạt. Repo đã chọn sửa theo từng chỗ gọi (CVT-1).
- **KHÔNG sửa `app/manifest.ts`** — giữ `start_url: "/"` (spec §4.8). Guard tự chuyển `/` → `/review`.
- **KHÔNG đặt `defaultOptions` vào `app/providers.tsx`** — nó là provider GỐC, bọc cả luồng ứng viên công khai (`/apply`, `/booking`, `/screening`). Xem gotcha trong `docs/AI_GUIDE.md`.
- **KHÔNG `cache.put` trong nhánh điều hướng của service worker.** Khoá CacheStorage là URL đầy đủ, mà `/screening/{token}` và `/booking/{token}` mang token bearer trong đường dẫn ⇒ cache lại là lưu credential còn sống trên máy ứng viên. Chỉ `/offline` được ghi, và chỉ lúc `install`.
- **Cổng chờ:** PWA-1 **phải** tự dựng cổng cho `usePwaMode()`. Sau BUG-1, `onlineManager` được seed từ `navigator.onLine`, nên mở app lúc offline làm query `me` bị *paused* ⇒ `isLoading` false ở render đầu ⇒ cổng cũ không giữ nữa.
- **Chữ dùng "máy chủ", không dùng "Internet".** `navigator.onLine` vẫn `true` khi dính captive portal hoặc router mất upstream.
- **Chạy lệnh đúng shell:** Node/pnpm/tsc → **PowerShell** (Git Bash vỡ vì fnm). git/make → **Bash, KHÔNG dùng `cd`** (dùng `git -C` / `make -C`).
- **KHÔNG có test runner cho frontend** trong repo này (`apps/dashboard/package.json` không có script test). Mỗi task verify bằng **trình duyệt thật** qua chrome-devtools MCP + `pnpm --filter dashboard typecheck`. Các bước verify dưới đây là lệnh chạy được, không phải mô tả.
- **Service worker chỉ đăng ký ở production** (`components/PWARegister.tsx:9-13` chủ động GỠ đăng ký ở dev). Task 7 **bắt buộc** verify bằng `pnpm --filter dashboard build` rồi `pnpm --filter dashboard start`, không phải `next dev`.

---

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `PRD.md` | Bảng §14 thành đầy đủ + ghi chú §14 nói đúng cơ chế + NFR-4 + FR-PWA-1 | 1 |
| `ROADMAP.md` | Ghi PWA-1 vào hàng đợi slice | 1 |
| `apps/dashboard/lib/pwa.ts` | **MỚI** — `usePwaMode()`, hằng `PWA_NAV_HREFS` / `PWA_HIDDEN_MATCHERS`. Một nguồn duy nhất cho "màn nào có trên PWA" | 2 |
| `apps/dashboard/app/(hr)/layout.tsx` | Cổng chờ riêng · lọc NAV · bỏ hamburger khi standalone · guard route ẩn | 2, 3, 4 |
| `apps/dashboard/app/(hr)/applications/page.tsx` | Danh sách thẻ dưới `md`, giữ bảng từ `md` trở lên | 5 |
| `apps/dashboard/app/(hr)/applications/[id]/page.tsx` | Ẩn 6 phần tử tương tác + 3 khối vỏ khi standalone | 6 |
| `apps/dashboard/app/offline/page.tsx` | **MỚI** — Server Component, không `"use client"`, chỉ thẻ `<a>` | 7 |
| `apps/dashboard/public/sw.js` | v3: precache `/offline`, nhánh RSC, nhánh điều hướng network-first không ghi cache | 7 |

---

## Task 1: Sửa PRD + ROADMAP (làm TRƯỚC mọi code)

Sau slice này bảng §14 không còn là mô tả — nó thành **spec mà guard thi hành**. Route nào không có trong bảng là ca chưa định nghĩa.

**Files:**
- Modify: `PRD.md:454-465` (bảng §14 + ghi chú), `PRD.md:474` (NFR-4), `PRD.md` §12.3 (thêm FR-PWA-1)
- Modify: `ROADMAP.md`

- [ ] **Step 1: Thêm 2 dòng còn thiếu vào bảng §14**

Chèn ngay sau `PRD.md:462` (dòng `| Thống kê / vòng học ... |`), giữ nguyên căn cột của bảng:

```markdown
| Kiểm tra CV                           | ✅     | ❌                   | —             |
| Huỷ / gửi lại link đặt lịch           | ✅     | ❌                   | —             |
```

Dòng thứ hai gỡ mâu thuẫn với **FR-BOOK-4** (`PRD.md:400-402`), vốn ghi HR huỷ lịch + gửi lại link "từ dashboard" — mà PWA CHÍNH LÀ dashboard trên điện thoại. Không thêm dòng này thì slice ship một hồi quy so với yêu cầu đã ghi.

- [ ] **Step 2: Sửa ghi chú §14**

Thay `PRD.md:464-465`:

```markdown
> Chỉ một app web (Next.js), responsive; cột "Điện thoại" là ưu tiên hiển thị trên màn hình nhỏ,
> không phải app riêng.
```

thành:

```markdown
> Chỉ một app web (Next.js), responsive — KHÔNG có codebase mobile riêng (§6). Cột "Điện thoại" áp
> dụng khi app chạy ở **chế độ đã cài (standalone)**: mở cùng địa chỉ bằng trình duyệt trên điện
> thoại vẫn thấy ĐỦ mọi màn. Chọn standalone thay vì theo bề rộng màn hình để một cửa sổ desktop bị
> thu nhỏ không bị cắt mất chức năng.
```

- [ ] **Step 3: Thêm mệnh đề vào NFR-4**

Nối vào cuối `PRD.md:474`:

```markdown
  PWA **không lưu dữ liệu nghiệp vụ xuống đĩa thiết bị**: service worker chỉ cache tài nguyên tĩnh
  có content-hash và trang "Mất kết nối"; tuyệt đối không cache phản hồi API, không cache trang mang
  token (`/screening/{token}`, `/booking/{token}`).
```

- [ ] **Step 4: Thêm FR-PWA-1 vào §12.3**

Chèn cuối mục **12.3 Pipeline / Agent** (trước dòng `### 12.4 Thông báo` ở `PRD.md:390`) — ID theo đúng nếp `FR-<AREA>-<n>`:

```markdown
- **FR-PWA-1 (PWA rút gọn + offline):** khi chạy ở chế độ đã cài, PWA chỉ hiển thị Đăng nhập, Ứng
  viên (danh sách + chi tiết rút gọn, CHỈ ĐỌC) và Hàng đợi review; các màn còn lại theo cột "Điện
  thoại" của §14 bị ẩn khỏi điều hướng VÀ chặn ở đường dẫn (đưa về hàng đợi kèm giải thích). Mất kết
  nối thì hiện trang "Mất kết nối" có thương hiệu, KHÔNG hiện dữ liệu nghiệp vụ đã cache (NFR-4).
```

- [ ] **Step 5: Ghi PWA-1 vào ROADMAP**

Thêm PWA-1 vào hàng đợi slice theo nếp `PREFIX-n` đang dùng (SCH-1, EMAIL-2, CVT-1, DASH-1). Ghi rõ **phần việc giao diện của PWA-1 là kéo Phase-7 lên sớm** so với quy tắc `ROADMAP.md:261` ("UI polish is its own end-phase"), và lý do được phép: sau khi cắt 6 hạng mục (spec §10), phần còn lại là **lọc điều hướng + guard route + danh sách responsive**, tức là hành vi tính năng chứ không phải trang trí.

- [ ] **Step 6: Commit**

```bash
git -C "d:/Web/Project/DATN" add PRD.md ROADMAP.md
git -C "d:/Web/Project/DATN" commit -m "docs(pwa): PRD §14 đầy đủ + FR-PWA-1 + NFR-4 cấm cache dữ liệu nghiệp vụ

Bảng §14 sau PWA-1 thành spec mà guard thi hành nên phải đầy đủ: thêm dòng
'Kiểm tra CV' và 'Huỷ / gửi lại link đặt lịch'. Dòng thứ hai gỡ mâu thuẫn với
FR-BOOK-4 (ghi HR làm hai việc đó 'từ dashboard', mà PWA là dashboard trên
điện thoại) — không có nó thì PWA-1 ship một hồi quy so với yêu cầu đã ghi.

Ghi chú §14 sửa lại cho khớp cơ chế thật: rút gọn theo chế độ ĐÃ CÀI, không
theo bề rộng màn hình."
```

---

## Task 2: `usePwaMode()` + cổng chờ riêng ở layout HR

**Files:**
- Create: `apps/dashboard/lib/pwa.ts`
- Modify: `apps/dashboard/app/(hr)/layout.tsx`

**Interfaces:**
- Consumes: không có (task đầu tiên của phần code)
- Produces:
  - `usePwaMode(): boolean | undefined` — `undefined` = chưa biết (chưa mount xong), `true` = đang chạy standalone, `false` = tab trình duyệt
  - `PWA_NAV_HREFS: readonly string[]` = `["/applications", "/review"]`
  - `isHiddenOnPwa(pathname: string): boolean`

- [ ] **Step 1: Viết `lib/pwa.ts`**

```ts
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
```

- [ ] **Step 2: Kiểm typecheck qua ngay**

Chạy trong **PowerShell**:

```
pnpm --filter dashboard typecheck
```

Kỳ vọng: không lỗi. Nếu `navigator.standalone` báo lỗi type thì `IosNavigator` chưa được áp — sửa, đừng dùng `any`.

- [ ] **Step 3: Dựng cổng chờ ở layout HR**

Trong `apps/dashboard/app/(hr)/layout.tsx`:

Thêm vào khối import (Task 3 và 4 sẽ nới thêm tên vào chính dòng này khi cần — task này chỉ dùng `usePwaMode`):

```tsx
import { usePwaMode } from "@/lib/pwa";
```

Ngay sau dòng khai báo `const qc = useQueryClient();`, thêm:

```tsx
  const isPwa = usePwaMode();
```

Rồi chèn cổng chờ **NGAY TRƯỚC** `if (isLoading) {`:

```tsx
  // PWA-1: chưa biết đang standalone hay không thì CHƯA vẽ gì. Không có cổng này, lần render đầu
  // vẽ đủ 5 mục điều hướng rồi effect mới rút còn 2 — người dùng thấy menu nháy.
  //
  // Trước BUG-1, cổng `isLoading` bên dưới vô tình che được việc này (query `me` luôn "fetching" ở
  // render đầu). BUG-1 seed `onlineManager` từ `navigator.onLine`, nên mở app lúc offline làm query
  // bị *paused* ⇒ `isLoading` false ngay từ đầu ⇒ cổng đó KHÔNG còn giữ. Phải có cổng riêng.
  if (isPwa === undefined) {
    return <div className="p-8 text-sm text-ink/65">Đang tải…</div>;
  }
```

- [ ] **Step 4: Verify cổng chờ không làm hỏng đường thường**

Chạy dev server (Bash, KHÔNG `cd`):

```bash
uv run --directory "d:/Web/Project/DATN/apps/backend" python -m app
```

PowerShell, cửa sổ khác:

```
pnpm --filter dashboard dev
```

Đăng nhập `admin@ars.local` (mật khẩu ở `.env`, biến `HR_ADMIN_PASSWORD`) rồi mở `http://localhost:3000/review`.
Kỳ vọng: trang hiện bình thường, đủ 5 mục điều hướng (Task 3 mới lọc), không kẹt ở chữ "Đang tải…".

- [ ] **Step 5: Commit**

```bash
git -C "d:/Web/Project/DATN" add apps/dashboard/lib/pwa.ts "apps/dashboard/app/(hr)/layout.tsx"
git -C "d:/Web/Project/DATN" commit -m "feat(pwa): usePwaMode() + cổng chờ riêng ở layout HR

Nhận diện chế độ đã cài bằng matchMedia (3 display-mode) + navigator.standalone
cho iOS. Giải một lần trong effect, không gắn listener — display-mode không đổi
trong vòng đời một document.

Cổng chờ PHẢI là của riêng usePwaMode: sau BUG-1, onlineManager được seed từ
navigator.onLine nên mở app lúc offline làm query me bị paused, isLoading thành
false ngay render đầu, và cổng cũ không còn giữ."
```

---

## Task 3: Lọc điều hướng còn 2 mục + bỏ hamburger khi standalone

**Files:**
- Modify: `apps/dashboard/app/(hr)/layout.tsx`

**Interfaces:**
- Consumes: `usePwaMode()`, `PWA_NAV_HREFS` từ Task 2
- Produces: không có API mới

- [ ] **Step 1: Lọc mảng NAV**

Nới dòng import của Task 2 thành:

```tsx
import { PWA_NAV_HREFS, usePwaMode } from "@/lib/pwa";
```

Ngay trước câu `return (` cuối cùng của `HrLayout`, thêm:

```tsx
  // PWA-1 (PRD §14): ở chế độ đã cài chỉ còn Ứng viên + Hàng đợi review. Bảng điều hành, Tin tuyển
  // dụng, Kiểm tra CV đều là ❌ ở cột "Điện thoại". Mở cùng địa chỉ bằng TRÌNH DUYỆT vẫn đủ 5 mục.
  const navItems = isPwa ? NAV.filter((item) => PWA_NAV_HREFS.includes(item.href)) : NAV;
```

Rồi đổi chỗ lặp điều hướng từ `{NAV.map((item) => {` thành `{navItems.map((item) => {`.

- [ ] **Step 2: Bỏ hamburger khi standalone**

Trong thanh trên cùng chỉ-điện-thoại (khối `lg:hidden`), bọc nút mở menu bằng điều kiện. Đổi:

```tsx
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            aria-label="Mở menu điều hướng"
            aria-expanded={navOpen}
            className="flex h-9 w-9 flex-none items-center justify-center rounded-lg border-2 border-divider hover:bg-ink/5"
          >
```

thành:

```tsx
          {/* PWA-1: ở chế độ đã cài chỉ còn 2 đích, mà thanh trên cùng đã có link "/review" kèm số
              đếm — ngăn kéo không còn gì để mở. Giữ lại thì thành hai lớp điều hướng cho hai màn. */}
          {!isPwa && (
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            aria-label="Mở menu điều hướng"
            aria-expanded={navOpen}
            className="flex h-9 w-9 flex-none items-center justify-center rounded-lg border-2 border-divider hover:bg-ink/5"
          >
```

và đóng `)}` ngay sau `</button>` tương ứng.

⚠ Ở chế độ standalone, sidebar dưới `lg` vẫn `invisible` + `-translate-x-full` nên không lọt vào thứ tự Tab — **giữ nguyên** cả hai class đó (`layout.tsx:186-189` ghi rõ `invisible` là load-bearing cho a11y, không phải trang trí).

- [ ] **Step 3: Verify bằng trình duyệt thật ở chế độ standalone giả lập**

`next dev` đang chạy. Dùng chrome-devtools MCP, mở `http://localhost:3000/review` với `initScript` giả lập standalone (khớp cả hai đường nhận diện):

```js
Object.defineProperty(Navigator.prototype, 'standalone', { get: () => true, configurable: true });
```

Rồi chạy:

```js
() => {
  const links = Array.from(document.querySelectorAll('nav a')).map(a => a.getAttribute('href'));
  const hamburger = document.querySelector('[aria-label="Mở menu điều hướng"]');
  return { navLinks: links, hasHamburger: Boolean(hamburger) };
}
```

Kỳ vọng chính xác: `{"navLinks":["/applications","/review"],"hasHamburger":false}`

- [ ] **Step 4: Verify đường trình duyệt KHÔNG bị rút gọn**

Mở lại `http://localhost:3000/review` **không có** `initScript`, chạy lại đúng đoạn script trên.

Kỳ vọng: `navLinks` có đủ 5 mục `["/", "/applications", "/review", "/jobs", "/cv-check"]` và `hasHamburger: true`. Đây là điều kiện đã chốt — mở bằng trình duyệt phải thấy đủ site.

- [ ] **Step 5: Commit**

```bash
git -C "d:/Web/Project/DATN" add "apps/dashboard/app/(hr)/layout.tsx"
git -C "d:/Web/Project/DATN" commit -m "feat(pwa): điều hướng còn 2 mục + bỏ hamburger ở chế độ đã cài

PRD §14: Bảng điều hành / Tin tuyển dụng / Kiểm tra CV đều ❌ ở cột Điện thoại.
Thanh trên cùng đã có link /review kèm số đếm nên ngăn kéo không còn gì để mở.
Giữ nguyên invisible + -translate-x-full ở sidebar (load-bearing cho a11y)."
```

---

## Task 4: Guard đường dẫn cho màn bị ẩn

Ẩn khỏi menu là chưa đủ: gõ tay `/jobs`, bấm link cũ trong lịch sử, hoặc bookmark đều lọt vào giao diện desktop bị bóp trên màn 390px.

**Files:**
- Modify: `apps/dashboard/app/(hr)/layout.tsx`

**Interfaces:**
- Consumes: `usePwaMode()`, `isHiddenOnPwa()` từ Task 2
- Produces: query param `?pwa_hidden=1` trên `/review` (Task 4 tự đọc, không task nào khác dùng)

- [ ] **Step 1: Chuyển hướng khi vào màn bị ẩn**

Nới dòng import của Task 2/3 thành:

```tsx
import { isHiddenOnPwa, PWA_NAV_HREFS, usePwaMode } from "@/lib/pwa";
```

Thêm effect ngay sau effect chuyển hướng `/login` đang có:

```tsx
  // PWA-1: màn bị ẩn mà vẫn vào được bằng URL thì coi như chưa ẩn. `?pwa_hidden=1` để trang đích
  // giải thích vì sao người dùng bị đưa đi chỗ khác — chuyển hướng câm lặng đọc như lỗi.
  useEffect(() => {
    if (isPwa && isHiddenOnPwa(pathname)) {
      router.replace("/review?pwa_hidden=1");
    }
  }, [isPwa, pathname, router]);
```

- [ ] **Step 2: Chặn nháy nội dung trong lúc chuyển hướng**

`router.replace` là bất đồng bộ nên trang bị ẩn vẫn kịp vẽ một khung hình. Thêm ngay dưới cổng chờ của Task 2:

```tsx
  // Đang chuyển hướng (effect ở trên) — không vẽ nội dung màn bị ẩn dù chỉ một khung hình.
  if (isPwa && isHiddenOnPwa(pathname)) {
    return <div className="p-8 text-sm text-ink/65">Đang chuyển về hàng đợi…</div>;
  }
```

- [ ] **Step 3: Hiện dải giải thích ở `/review`**

Trong `apps/dashboard/app/(hr)/review/page.tsx`, thêm import:

```tsx
import { useSearchParams } from "next/navigation";
```

Trong `ReviewPage`, sau `const [errorMsg, setErrorMsg] = useState<string | null>(null);`:

```tsx
  // PWA-1: guard ở layout đưa người dùng tới đây khi họ mở một màn chỉ có trên bản máy tính.
  // Tự tắt sau 6s — đây là lời giải thích một lần, không phải cảnh báo thường trực.
  const searchParams = useSearchParams();
  const [hiddenNotice, setHiddenNotice] = useState(false);
  useEffect(() => {
    if (searchParams.get("pwa_hidden") !== "1") return;
    setHiddenNotice(true);
    const t = setTimeout(() => setHiddenNotice(false), 6000);
    return () => clearTimeout(t);
  }, [searchParams]);
```

Thêm `useEffect` vào import `react` đang có (`import { useEffect, useState } from "react";`).

Rồi chèn ngay trên khối `{errorMsg && (`:

```tsx
      {hiddenNotice && (
        <p className="mb-4 rounded-lg border-2 border-divider bg-ink/[0.03] px-4 py-2.5 text-sm text-ink/70">
          Màn bạn vừa mở chỉ có trên bản máy tính. Đã đưa bạn về hàng đợi duyệt.
        </p>
      )}
```

- [ ] **Step 4: Bọc `Suspense` cho `useSearchParams`**

`useSearchParams` trong App Router bắt buộc phải nằm dưới một `Suspense` boundary, nếu không `next build` **đỏ** với lỗi *"useSearchParams() should be wrapped in a suspense boundary"*. Tách phần thân trang thành một component nội bộ và bọc lại:

```tsx
export default function ReviewPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-ink/65">Đang tải hàng đợi…</div>}>
      <ReviewQueue />
    </Suspense>
  );
}
```

Đổi tên hàm cũ thành `function ReviewQueue() {` (bỏ `export default`), và thêm `Suspense` vào import `react`.

- [ ] **Step 5: Verify guard**

Với `initScript` giả lập standalone (như Task 3), mở `http://localhost:3000/jobs`, đợi 1s rồi chạy:

```js
() => ({ path: location.pathname, search: location.search, body: document.body.innerText.slice(0, 120) })
```

Kỳ vọng: `path` = `/review`, `search` = `?pwa_hidden=1`, và `body` chứa "Màn bạn vừa mở chỉ có trên bản máy tính".

Lặp lại với `/` và `/cv-check` — cả hai đều phải về `/review`.

- [ ] **Step 6: Verify `/applications` KHÔNG bị chặn nhầm**

Vẫn ở chế độ standalone giả lập, mở `http://localhost:3000/applications`.

Kỳ vọng: `location.pathname` = `/applications` (không bị đá đi). Đây là phép thử cho lỗi `/` khớp-tiền-tố — nếu `isHiddenOnPwa` dùng `startsWith("/")` thay vì so bằng thì **mọi** route đều bị chặn.

- [ ] **Step 7: Build để chắc `Suspense` đúng**

PowerShell:

```
pnpm --filter dashboard build
```

Kỳ vọng: `✓ Compiled successfully` và **không** có lỗi `useSearchParams`.

- [ ] **Step 8: Commit**

```bash
git -C "d:/Web/Project/DATN" add "apps/dashboard/app/(hr)/layout.tsx" "apps/dashboard/app/(hr)/review/page.tsx"
git -C "d:/Web/Project/DATN" commit -m "feat(pwa): chặn đường dẫn tới màn đã ẩn, đưa về hàng đợi kèm giải thích

Ẩn khỏi menu là chưa đủ — gõ tay URL, bấm link cũ hay bookmark đều lọt vào
giao diện desktop bị bóp trên 390px. Kèm chốt chặn render để không nháy nội
dung màn bị ẩn trong lúc router.replace chạy.

useSearchParams bắt buộc nằm dưới Suspense, nếu không next build đỏ."
```

---

## Task 5: `/applications` — danh sách thẻ dưới `md`

Bảng hiện tại là `min-w-[640px]` trong `overflow-x-auto`: ở 390px nó cuộn ngang trong khung, và cột "Trạng thái" — thứ HR cần nhất — nằm ngoài tầm nhìn cho tới khi cuộn.

**Files:**
- Modify: `apps/dashboard/app/(hr)/applications/page.tsx`

**Interfaces:**
- Consumes: `applicationStatusLabel`, `applicationStatusTone`, `isEmailFlag` (đã import sẵn trong file)
- Produces: không có API mới

- [ ] **Step 1: Tách phần cờ dùng chung cho cả bảng lẫn thẻ**

Trên `export default function ApplicationsPage()`, thêm:

```tsx
// Dùng chung cho bảng (desktop) và thẻ (điện thoại) — hai bản chép tay song song chính là cách cờ
// email thứ tư được thêm vào một bên rồi im lặng vắng mặt ở bên kia.
function StatusCell({ a }: { a: ApplicationListItem }) {
  const otherFlags = a.uncertainty_flags.filter((f) => !isEmailFlag(f));
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Tag tone={applicationStatusTone(a)}>{applicationStatusLabel(a)}</Tag>
      {a.email_complained && <Tag tone="danger">🚫 Đã báo cáo spam</Tag>}
      {a.email_bounced && <Tag tone="danger">⚠ Email không gửi được</Tag>}
      {a.email_send_failed && <Tag tone="danger">⛔ Hệ thống chưa gửi được thư</Tag>}
      {a.status === "PENDING_REVIEW" && otherFlags.length > 0 && (
        <span className="text-xs font-semibold text-accent">{otherFlags.join(" · ")}</span>
      )}
    </div>
  );
}
```

Rồi trong ô `<td>` cột "Trạng thái" của bảng, thay toàn bộ `<div className="flex flex-wrap items-center gap-2">…</div>` bằng `<StatusCell a={a} />`.

- [ ] **Step 2: Ẩn bảng dưới `md`**

Đổi `<div className="overflow-x-auto">` (khối bọc `<table>`) thành:

```tsx
          <div className="hidden overflow-x-auto md:block">
```

- [ ] **Step 3: Thêm danh sách thẻ, chỉ hiện dưới `md`**

Ngay sau `</div>` đóng khối bảng ở Step 2, thêm:

```tsx
          {/* Điện thoại: bảng min-w-[640px] buộc cuộn ngang và đẩy cột Trạng thái ra ngoài tầm nhìn.
              Thẻ xếp dọc cho cả bốn thông tin cùng lúc. CẢ THẺ là link (bảng chỉ ô đầu là link, mà
              cả hàng lại đổi màu khi rê chuột — hứa một vùng bấm không tồn tại). */}
          <ul className="divide-y divide-divider md:hidden">
            {filtered.map((a) => (
              <li key={a.id}>
                <Link
                  href={`/applications/${a.id}`}
                  className="flex flex-col gap-2 px-4 py-3 hover:bg-ink/[0.04]"
                >
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-[34px] w-[34px] flex-none items-center justify-center rounded-lg bg-steel-200 font-heading text-[13px] font-bold">
                      {initialsOf(a.applicant_email)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-semibold">
                        {a.applicant_email.split("@")[0]}
                      </span>
                      <span className="block truncate text-xs text-ink/65">{a.applicant_email}</span>
                    </span>
                    <span className="flex-none font-heading text-base font-bold">
                      {a.score != null ? a.score : "—"}
                    </span>
                  </div>
                  <p className="text-[13px] text-ink/75">
                    {a.job_id ? (jobTitle.get(a.job_id) ?? `JD #${a.job_id}`) : "—"}
                  </p>
                  <StatusCell a={a} />
                </Link>
              </li>
            ))}
          </ul>
```

- [ ] **Step 4: Verify ở 390px**

Dùng chrome-devtools MCP, đặt viewport rồi mở trang:

- `emulate` với `viewport` = `390x844x3,mobile,touch`
- mở `http://localhost:3000/applications`

Chạy:

```js
() => ({
  bodyScrollsSideways: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  tableVisible: Boolean(document.querySelector('table')?.offsetParent),
  cardCount: document.querySelectorAll('ul.md\\:hidden > li').length,
})
```

Kỳ vọng: `bodyScrollsSideways: false`, `tableVisible: false`, `cardCount` > 0 (bằng số hồ sơ đang lọc).

- [ ] **Step 5: Verify desktop không đổi**

`emulate` với `viewport` = `1440x900x1`, tải lại `/applications`, chạy lại script trên.

Kỳ vọng: `tableVisible: true`, `cardCount: 0`.

- [ ] **Step 6: Commit**

```bash
git -C "d:/Web/Project/DATN" add "apps/dashboard/app/(hr)/applications/page.tsx"
git -C "d:/Web/Project/DATN" commit -m "feat(pwa): danh sách ứng viên dạng thẻ dưới md

Bảng min-w-[640px] ở 390px đẩy cột Trạng thái ra ngoài tầm nhìn cho tới khi
cuộn ngang. Thẻ cho cả bốn thông tin cùng lúc, và CẢ THẺ là link — bảng chỉ ô
đầu là link nhưng cả hàng đổi màu khi rê chuột, hứa một vùng bấm không có thật.

StatusCell tách ra dùng chung để cờ email không lệch giữa hai bản hiển thị."
```

---

## Task 6: `/applications/[id]` — chỉ đọc khi standalone

Spec §4.8: trang này có **6 phần tử tương tác** (1 Link + 5 button) và **3 khối vỏ** sẽ mồ côi nếu chỉ ẩn nút. Link "Về danh sách ứng viên" là điều hướng, **giữ lại**; 5 button còn lại là hành động, ẩn hết.

**Files:**
- Modify: `apps/dashboard/app/(hr)/applications/[id]/page.tsx`

**Interfaces:**
- Consumes: `usePwaMode()` từ Task 2
- Produces: không có API mới

- [ ] **Step 1: Thêm cờ chỉ-đọc**

Thêm import:

```tsx
import { usePwaMode } from "@/lib/pwa";
```

Trong component, cạnh các hook khác:

```tsx
  // PWA-1 (PRD §14): trên bản đã cài, màn chi tiết là CHỈ ĐỌC. Ba hành động ở đây — tải CV gốc, huỷ
  // lịch, gửi lại link — đều rời khỏi app hoặc GỬI EMAIL THẬT cho ứng viên, và không hành động nào
  // nằm trong cột "Điện thoại" của §14. Mọi quyết định dồn về /review.
  //
  // Đây là lựa chọn HIỂN THỊ, KHÔNG phải siết backend: endpoint vẫn mở, và mở cùng địa chỉ này bằng
  // trình duyệt trên chính máy đó vẫn thấy đủ nút. Đừng "làm chắc" nó thành thay đổi backend.
  const readOnly = usePwaMode() === true;
```

- [ ] **Step 2: Ẩn khối tải CV gốc (nút + vỏ + báo lỗi)**

Đổi điều kiện bọc từ `{app.has_cv && (` thành:

```tsx
            {app.has_cv && !readOnly && (
```

Khối này đã bao trọn `<div className="flex flex-none flex-col items-end gap-1">` (nút + `<span role="alert">`), nên một điều kiện là đủ — không để lại cột flex rỗng.

- [ ] **Step 3: Ẩn nút huỷ lịch, GIỮ panel lịch**

Panel `app.interview` là **nội dung** (giờ phỏng vấn đã chốt) — HR trên điện thoại vẫn cần đọc. Chỉ ẩn nút bên trong. Đổi:

```tsx
              {app.status === "INTERVIEW_SCHEDULED" &&
                (confirmingCancel ? (
```

thành:

```tsx
              {app.status === "INTERVIEW_SCHEDULED" && !readOnly &&
                (confirmingCancel ? (
```

Ẩn nút "Huỷ lịch phỏng vấn" cũng gỡ luôn đường vào hai nút xác nhận (chúng chỉ hiện khi `confirmingCancel`, mà chỉ nút đó bật cờ).

- [ ] **Step 4: Ẩn panel gửi lại link**

Panel này **mô tả một hành động**, nên ẩn cả panel chứ không riêng nút — để lại thì HR đọc một lời hứa không bấm được. Đổi:

```tsx
          {canResend && (
```

thành:

```tsx
          {canResend && !readOnly && (
```

- [ ] **Step 5: Ẩn báo lỗi thao tác lịch**

`scheduleError` chỉ do hai mutation vừa ẩn sinh ra ⇒ chết theo. Đổi:

```tsx
          {scheduleError && (
```

thành:

```tsx
          {scheduleError && !readOnly && (
```

- [ ] **Step 6: KHÔNG đụng `AgentTrace`**

`PRD.md:458` ghi "Chi tiết CV (parse, điểm, **trace**) — ✅ rút gọn" cho điện thoại. **Giữ nguyên** `<AgentTrace app={app} />`. Bỏ nó đi là mâu thuẫn với dòng PRD vừa được Task 1 xác nhận.

- [ ] **Step 7: Verify chế độ chỉ đọc**

Với `initScript` giả lập standalone, viewport `390x844x3,mobile,touch`, mở một hồ sơ có lịch phỏng vấn (lấy id từ `curl` dưới đây), rồi chạy:

```js
() => {
  const txt = document.body.innerText;
  return {
    buttons: Array.from(document.querySelectorAll('button')).map(b => b.textContent.trim()),
    hasBackLink: Boolean(document.querySelector('a[href="/applications"]')),
    hasTrace: txt.includes('Agent') || txt.includes('trace'),
    mentionsResend: txt.includes('Gửi lại link đặt lịch'),
  };
}
```

Kỳ vọng: `buttons` là mảng **rỗng**, `hasBackLink: true`, `hasTrace: true`, `mentionsResend: false`.

Lấy id hồ sơ có lịch (Bash):

```bash
curl -s -b "$COOKIES" -H 'Origin: http://localhost:3000' http://localhost:8000/api/applications/pipeline
```

- [ ] **Step 8: Verify trình duyệt vẫn đủ nút**

Mở đúng URL đó **không có** `initScript`, chạy lại script trên.

Kỳ vọng: `buttons` chứa ít nhất một trong "Tải CV gốc" / "Huỷ lịch phỏng vấn" / "Gửi lại link đặt lịch".

- [ ] **Step 9: Commit**

```bash
git -C "d:/Web/Project/DATN" add "apps/dashboard/app/(hr)/applications/[id]/page.tsx"
git -C "d:/Web/Project/DATN" commit -m "feat(pwa): chi tiết ứng viên chỉ-đọc ở chế độ đã cài

Ẩn cả 5 nút hành động cùng khối vỏ của chúng — ẩn riêng nút thì còn lại một
cột flex rỗng và một panel mô tả hành động không ai bấm được. Giữ Link về danh
sách (điều hướng, không phải hành động), giữ panel lịch phỏng vấn và panel hết
khung giờ (nội dung), giữ AgentTrace theo PRD §14 dòng 458.

Đây là lựa chọn hiển thị, KHÔNG siết backend: endpoint vẫn mở và mở cùng địa
chỉ bằng trình duyệt trên chính máy đó vẫn thấy đủ nút."
```

---

## Task 7: Trang `/offline` + service worker v3

**Files:**
- Create: `apps/dashboard/app/offline/page.tsx`
- Modify: `apps/dashboard/public/sw.js`

**Interfaces:**
- Consumes: không có
- Produces: route `/offline` (SW precache theo đúng đường dẫn này)

- [ ] **Step 1: Viết trang `/offline`**

```tsx
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Mất kết nối — HireFlow" };

// TUYỆT ĐỐI KHÔNG thêm "use client" vào file này.
// Service worker chỉ `cache.add("/offline")` — tức chỉ lưu HTML. Các chunk JS của route này thì
// CHƯA AI từng tải (không ai chủ động vào /offline lúc đang online), mà nhánh `/_next/static/` của
// sw.js là cache-khi-fetch-lần-đầu chứ không phải precache. Nên trang sẽ VẼ được nhưng KHÔNG
// hydrate: mọi nút React ở đây là nút chết. Thẻ <a> thường là một lượt điều hướng thật, đi qua
// nhánh network-first và chạy ngay khi có mạng trở lại.
//
// Chữ phải TRUNG TÍNH, không mang giọng HR: PWARegister đăng ký SW ở scope "/" (app/layout.tsx),
// nên trang này cũng phục vụ ứng viên mất sóng giữa chừng ở /apply, /screening, /booking.
export default function OfflinePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-[520px] flex-col justify-center px-6 py-12 text-center">
      <p className="font-heading text-[13px] font-bold uppercase tracking-[0.08em] text-ink/65">
        HireFlow
      </p>
      <h1 className="mt-3 text-[28px] sm:text-[32px]">Mất kết nối máy chủ</h1>
      <p className="mx-auto mt-3 max-w-[42ch] text-[14px] leading-relaxed text-ink/70">
        Thiết bị của bạn hiện không liên lạc được với máy chủ HireFlow. Dữ liệu không được lưu trên
        máy nên trang này chưa hiển thị được nội dung nào — hãy kiểm tra kết nối rồi thử lại.
      </p>
      <p className="mt-6">
        <a
          href="/review"
          className="inline-flex min-h-11 items-center justify-center rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-white hover:bg-accent-600"
        >
          Thử lại
        </a>
      </p>
    </main>
  );
}
```

- [ ] **Step 2: Viết lại `public/sw.js`**

Thay TOÀN BỘ nội dung file:

```js
// Service worker cho PWA (chỉ đăng ký ở production — xem PWARegister).
//
// Ba nhánh, theo đúng thứ tự này:
//   1. RSC (`?_rsc=`)  -> mạng, hỏng thì 503 NGAY (ép Next chuyển sang điều hướng cứng)
//   2. điều hướng       -> mạng trước, hỏng thì trả trang /offline đã precache
//   3. /_next/static/*  -> cache-first (URL có content-hash nên thực sự bất biến)
// Mọi thứ khác đi thẳng network, KHÔNG cache.
//
// KHÔNG cache phản hồi API và KHÔNG cache trang nào khác. Từ slice 13, `/api/*` là SAME-ORIGIN
// (Vercel rewrite) nên nó ĐI QUA fetch handler này — comment cũ nói API nằm ở origin khác là SAI.
// Khoá của CacheStorage là URL đầy đủ, mà `/screening/{token}` và `/booking/{token}` mang token
// bearer TRONG ĐƯỜNG DẪN: ghi chúng vào cache là lưu một credential còn sống trên máy ứng viên,
// sống lâu hơn TTL và sống qua cả lượt vô hiệu one-time (NFR-4).
//
// Đổi tên CACHE để vô hiệu toàn bộ cache đã phát hành (activate sẽ dọn tên cũ).
const CACHE = "ars-static-v3";
const OFFLINE_URL = "/offline";

self.addEventListener("install", (event) => {
  self.skipWaiting();
  // `.catch` là BẮT BUỘC, không phải phòng xa: waitUntil bị reject thì SW mới KHÔNG BAO GIỜ activate
  // và client kẹt ở bản cũ vĩnh viễn, không có đường cứu ngoài xoá site data. Chỉ cần một lượt fetch
  // hỏng (đang mất mạng lúc kiểm cập nhật, hoặc lần deploy đầu SW lên trước route) là dính.
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.add(new Request(OFFLINE_URL, { cache: "reload" })))
      .catch(() => {})
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  const sameOrigin = url.origin === self.location.origin;

  // (1) Điều hướng phía client của App Router KHÔNG phải `mode: "navigate"` — Next gọi
  // `fetch(url + "?_rsc=…")` không truyền `mode`, nên nó mặc định là "cors". Không bắt riêng thì
  // request này chờ hết timeout TCP/DNS rồi Next mới tự chuyển sang điều hướng cứng. Trả 503 ngay
  // khiến Next hard-nav lập tức, và lượt hard-nav đó rơi đúng vào nhánh (2).
  // TUYỆT ĐỐI không trả HTML của /offline cho request _rsc — Next sẽ cố parse nó như RSC payload.
  if (sameOrigin && (url.searchParams.has("_rsc") || request.headers.get("RSC") === "1")) {
    event.respondWith(fetch(request).catch(() => new Response("", { status: 503 })));
    return;
  }

  // (2) Điều hướng: mạng trước, KHÔNG ghi cache.
  // Chỉ dự phòng khi `fetch` REJECT (không dựng nổi kết nối). KHÔNG dự phòng khi `!res.ok`: Render
  // ngủ hoặc Cloudflare 502 thì fetch RESOLVE với 5xx, và gắn nhãn "bạn đang offline" cho một sự cố
  // backend là chẩn đoán sai — repo đã trả giá cho đúng loại nhầm lẫn này (docs/deploy-live-issues.md).
  if (sameOrigin && request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(async () => {
        const cached = await caches.match(OFFLINE_URL);
        return (
          cached ??
          new Response("<h1>Mất kết nối máy chủ</h1>", {
            status: 503,
            headers: { "content-type": "text/html; charset=utf-8" },
          })
        );
      })
    );
    return;
  }

  // (3) Tài nguyên tĩnh bất biến -> cache-first.
  if (sameOrigin && url.pathname.startsWith("/_next/static/")) {
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
      })
    );
  }
  // còn lại: không gọi respondWith -> trình duyệt tự xử lý, không cache.
});
```

- [ ] **Step 3: Build + chạy bản production (bắt buộc — dev GỠ service worker)**

PowerShell:

```
pnpm --filter dashboard build
```

Kỳ vọng: trong bảng route có dòng `○ /offline` (Static). Nếu nó là `ƒ` thì file đã lỡ thành client component — quay lại Step 1.

Dừng `next dev` rồi chạy:

```
pnpm --filter dashboard start
```

- [ ] **Step 4: Verify service worker đã cài và đã precache**

Mở `http://localhost:3000/review` (bản production, cổng 3000), đăng nhập, rồi chạy:

```js
async () => {
  const reg = await navigator.serviceWorker.ready;
  const keys = await caches.keys();
  const c = await caches.open('ars-static-v3');
  const offline = await c.match('/offline');
  return { active: Boolean(reg.active), cacheNames: keys, offlinePrecached: Boolean(offline) };
}
```

Kỳ vọng: `active: true`, `cacheNames` chứa `"ars-static-v3"` và **không** còn `"ars-static-v2"`, `offlinePrecached: true`.

- [ ] **Step 5: Verify trang offline khi tải nguội**

`emulate` với `networkConditions: "Offline"`, rồi `navigate_page` tới `http://localhost:3000/review`, chạy:

```js
() => ({ text: document.body.innerText.slice(0, 200), hasRetry: Boolean(document.querySelector('a[href="/review"]')) })
```

Kỳ vọng: `text` chứa "Mất kết nối máy chủ" và `hasRetry: true`. **Không** được là màn lỗi của Chrome.

- [ ] **Step 6: Verify KHÔNG có gì lọt vào cache ngoài `/offline` và static**

Vẫn đang Offline, chạy:

```js
async () => {
  const c = await caches.open('ars-static-v3');
  const keys = await c.keys();
  const paths = keys.map(r => new URL(r.url).pathname);
  return {
    total: paths.length,
    nonStatic: paths.filter(p => !p.startsWith('/_next/static/')),
    hasApi: paths.some(p => p.startsWith('/api/')),
    hasToken: paths.some(p => p.startsWith('/screening/') || p.startsWith('/booking/')),
  };
}
```

Kỳ vọng chính xác: `nonStatic` đúng bằng `["/offline"]`, `hasApi: false`, `hasToken: false`. Đây là phép thử cho ràng buộc NFR-4 ở Global Constraints — nếu `hasToken: true` thì nhánh điều hướng đang ghi cache, sửa ngay.

- [ ] **Step 7: Verify điều hướng trong app lúc offline không treo**

Vẫn Offline, nối lại mạng bằng `networkConditions: "Fast 4G"`, mở `/review`, rồi chuyển lại `Offline` và bấm link "Ứng viên" trong điều hướng. Đo thời gian tới lúc thấy trang offline:

```js
() => ({ path: location.pathname, text: document.body.innerText.slice(0, 120) })
```

Kỳ vọng: trong vòng vài giây (không phải chờ timeout ~30s) hiện trang "Mất kết nối". Nếu treo lâu thì nhánh RSC ở Step 2 chưa khớp — kiểm lại `url.searchParams.has("_rsc")`.

- [ ] **Step 8: Commit**

```bash
git -C "d:/Web/Project/DATN" add apps/dashboard/app/offline/page.tsx apps/dashboard/public/sw.js
git -C "d:/Web/Project/DATN" commit -m "feat(pwa): trang Mất kết nối + service worker v3

Ba nhánh theo thứ tự: RSC -> 503 ngay (điều hướng client-side của App Router
đi qua ?_rsc= với mode cors nên KHÔNG lọt vào nhánh navigate; không bắt riêng
thì người dùng ngồi chờ hết timeout TCP); điều hướng -> mạng trước, hỏng thì
trả /offline; /_next/static -> cache-first.

KHÔNG cache.put ở nhánh điều hướng: khoá CacheStorage là URL đầy đủ mà
/screening/{token} và /booking/{token} mang token bearer trong đường dẫn (NFR-4).

.catch quanh waitUntil(cache.add) là bắt buộc — waitUntil reject thì SW mới
không bao giờ activate và client kẹt bản cũ vĩnh viễn.

Dự phòng chỉ khi fetch REJECT, không khi !res.ok: Render ngủ / Cloudflare 502
resolve với 5xx, gắn nhãn 'bạn đang offline' cho sự cố backend là chẩn đoán sai.

/offline là Server Component không 'use client': cache.add chỉ lưu HTML, chunk
JS của route chưa ai từng tải nên trang sẽ vẽ mà KHÔNG hydrate — nút React ở đó
sẽ là nút chết. Thẻ <a> thường thì luôn chạy."
```

---

## Task 8: Kiểm tổng thể trước khi khép slice

**Files:** không sửa file nào — chỉ chạy và đọc kết quả.

- [ ] **Step 1: Typecheck + build**

PowerShell:

```
pnpm --filter dashboard typecheck
pnpm --filter dashboard build
```

Kỳ vọng: cả hai xanh; bảng route có `○ /offline`.

- [ ] **Step 2: Test backend (lưới an toàn — PWA-1 lẽ ra không đụng backend)**

Bash:

```bash
make -C "d:/Web/Project/DATN" test
```

Kỳ vọng: pass, số test **không giảm** so với `475 passed, 66 skipped` ở BUG-1. Nếu có test đỏ thì slice này đã lỡ đụng backend — trái Global Constraints.

- [ ] **Step 3: Đọc console ở MỘT trang công khai**

Bản production đang chạy, mở `http://localhost:3000/apply`, `list_console_messages` với `types: ["error"]`.

Kỳ vọng: **không có** message nào. Bước này không thừa: gotcha `navigator` của Node 24 (`docs/AI_GUIDE.md`) là lỗi mà `tsc` im, `next build` xanh, và chỉ lộ ra khi đọc console ở một trang CÔNG KHAI — đường HR không lộ vì nó vốn phải chờ `getMe`.

- [ ] **Step 4: Đối chiếu bảng §14**

Với `initScript` giả lập standalone, lần lượt mở `/`, `/jobs`, `/cv-check`, `/applications`, `/review` và ghi lại `location.pathname` sau 1s.

Kỳ vọng: ba đường đầu về `/review`; hai đường sau giữ nguyên. Khớp đúng cột "Điện thoại" của bảng §14 sau Task 1.

- [ ] **Step 5: Cập nhật CLAUDE.md + AI_GUIDE.md**

Thêm PWA-1 vào bảng trạng thái/đoạn tóm tắt trong `CLAUDE.md` (**giữ gọn** — file này nạp mỗi session). Bẫy mới phát hiện trong lúc làm → ghi vào `docs/AI_GUIDE.md`, **không** nhồi vào CLAUDE.md.

- [ ] **Step 6: Commit + push**

```bash
git -C "d:/Web/Project/DATN" add CLAUDE.md docs/AI_GUIDE.md
git -C "d:/Web/Project/DATN" commit -m "docs(pwa): ghi PWA-1 vào CLAUDE.md + gotcha vào AI_GUIDE"
git -C "d:/Web/Project/DATN" push origin main
```

---

## Không thuộc phạm vi plan này

Web Push (NOTI-1a/1b) — **plan riêng**, viết SAU khi PWA-1 vào `main`, vì NOTI-1a thêm listener `push`/`notificationclick` vào chính `sw.js` mà Task 7 vừa viết lại. Kèm theo đó là các mục sửa PRD §3.1–3.3 và §3.9 (gỡ push khỏi §17): **chưa** làm bây giờ — sửa PRD nói push đã trong phạm vi trong khi chưa có push nào là làm PRD nói dối.

Đã cắt khỏi phạm vi ở spec §10 và **không** được lén đưa lại: thanh tab dưới cùng · sửa `btn()` toàn app · đổi badge sang `/pipeline` · banner `useOnline` thường trực · đổi `start_url`/`manifest.ts` · cache dữ liệu nghiệp vụ để xem offline.
