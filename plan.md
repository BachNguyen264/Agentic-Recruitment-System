# SLICE — Cập nhật repo: bỏ React Native, chuyển sang PWA · plan one-shot

> **Bản chất:** plan ONE-SHOT cho một lát refactor + đồng bộ tài liệu. Xong thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Quyết định:** bỏ hẳn app mobile React Native (Expo). "App trên điện thoại" giờ là **web dashboard dạng PWA**
> (cài lên màn hình chính) — một codebase web duy nhất, responsive; không duy trì codebase mobile riêng.
> **Lý do:** nhu cầu mobile chỉ là xem thông tin + phê duyệt nhanh, không cần truy cập phần cứng/OS → PWA đủ,
> giảm một codebase. Tuân thủ `CLAUDE.md`.

---

## 1. In scope / Out of scope

**In scope:**

- Gỡ bỏ `apps/mobile` (Expo/React Native) khỏi monorepo + mọi tham chiếu build/script.
- Biến `apps/dashboard` (Next.js) thành **PWA cài được**: web app manifest + service worker tối giản + icon.
- Đảm bảo các trang hiện có responsive tốt trên khổ điện thoại.
- Cập nhật MỌI tài liệu nhắc tới mobile: `PRD.md`, `CLAUDE.md`, `docs/architecture.md`, `README.md`.
- Cập nhật cấu hình monorepo: `pnpm-workspace.yaml`, root `package.json`, `Makefile`.

**Out of scope (KHÔNG làm ở lát này):**

- KHÔNG làm push notification thật (đưa vào PRD §17 tương lai — iOS hạn chế; dùng badge in-app thay thế).
- KHÔNG xây các trang HR mới (danh sách ứng viên, review queue…) — lát sau; đây chỉ là hạ tầng PWA + dọn dẹp.
- KHÔNG đụng backend, agent/node, logic nghiệp vụ.
- KHÔNG đổi tên `apps/dashboard` (giữ tên, tránh churn; nó là app web duy nhất: public + HR + PWA).

---

## 2. Gỡ bỏ app mobile

- Xóa thư mục `apps/mobile/`.
- `pnpm-workspace.yaml`: bỏ mục `apps/mobile` nếu có.
- Root `package.json`: bỏ script liên quan mobile nếu có.
- `Makefile`: bỏ target `dev-mobile` (và target/ghi chú riêng cho Expo/mobile nếu có).
- `packages/shared-types`: GIỮ NGUYÊN (dashboard vẫn dùng). Chỉ cần chắc không còn type nào chỉ dành riêng cho mobile; nếu có thì bỏ.
- `.gitignore`: có thể bỏ các dòng riêng của Expo (không bắt buộc, vô hại nếu để lại).
- Chạy `pnpm install` lại để cập nhật lockfile sau khi bỏ workspace.

## 3. Biến dashboard thành PWA (tối giản, không thư viện nặng)

Ưu tiên cách thủ công gọn, tránh phụ thuộc dễ vỡ (không bắt buộc `next-pwa`):

- **Manifest:** thêm `app/manifest.ts` (Next.js App Router sinh ra `/manifest.webmanifest`): `name`,
  `short_name`, `start_url: "/"`, `display: "standalone"`, `background_color`, `theme_color`, `icons` (192, 512).
- **Icon:** sinh icon placeholder đơn giản (ô vuông màu + chữ/logo) kích thước 192×192 và 512×512 vào `public/`.
- **Service worker:** thêm `public/sw.js` TỐI GIẢN — precache app shell / static của Next; với request `/api/*`
  và dữ liệu động thì **network (không cache)** để tránh dữ liệu cũ. Không cần chiến lược caching phức tạp.
- **Đăng ký SW:** trong một client component (vd thêm vào `app/layout.tsx` qua một `<PWARegister/>`), đăng ký
  `sw.js` — **chỉ ở production** (`process.env.NODE_ENV === "production"`) để tránh SW phá hot-reload khi dev.
- **Meta:** thêm `themeColor` + `viewport` phù hợp (App Router: qua `export const viewport`/`metadata`).
- **Responsive:** rà các trang hiện có (`/`, `/cv-check`) hiển thị tốt trên khổ điện thoại (không tràn, chạm được).

> Ghi chú: PWA cài được cần HTTPS ở production (localhost dev thì OK). Không xử lý gì thêm ở lát này.

## 4. Cập nhật tài liệu (đồng bộ — quan trọng)

| File                   | Sửa gì                                                                                                                                                                     |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PRD.md`               | §1.3, §6, §11 (FR-HR-3), §14, §17 — đổi "app mobile React Native" → "web PWA trên điện thoại"; đưa push vào §17. Xem wording bên dưới.                                     |
| `CLAUDE.md`            | Mục stack: "Mobile: React Native / Expo…" → "PWA: web dashboard cài được trên điện thoại cho HR (không codebase mobile riêng)". Bỏ mọi nhắc React Native/Expo.             |
| `docs/architecture.md` | Đổi mọi nhắc mobile → PWA; nếu có sơ đồ/nhánh mobile thì mô tả lại là "web PWA".                                                                                           |
| `README.md`            | Bỏ `make dev-mobile` + hướng dẫn Expo; thêm dòng "web là PWA, cài trên điện thoại qua Add to Home Screen". Giữ ghi chú lệnh Node chạy PowerShell (vẫn đúng cho pnpm/next). |

**Wording mới cho các mục PRD (áp đúng, không tự chế thêm):**

- §1.3: "Trên điện thoại, chính web này (dạng PWA cài được lên màn hình chính) cho HR phê duyệt nhanh khi di chuyển."
- §6: "Trên điện thoại: web dạng PWA (cài lên màn hình chính) — HR xem CV + duyệt human_review nhanh. Một app web duy nhất, responsive; KHÔNG có codebase mobile riêng."
- §11 FR-HR-3: "Trên điện thoại (PWA): giao diện rút gọn, responsive (tóm tắt + điểm + lý do + 2 nút) để duyệt nhanh. Thông báo: badge số ca chờ hiển thị trong app. (Web push đẩy thật: xem §17.)"
- §14 (bảng): đổi tiêu đề cột "Mobile HR" → "Điện thoại (PWA, HR)"; giữ nguyên các chức năng (xem CV, duyệt review = ✓; giám sát agent, quản lý JD, thống kê = ✗). Thêm một dòng ghi chú dưới bảng: "Chỉ một app web (Next.js), responsive; cột 'Điện thoại' là ưu tiên hiển thị trên màn hình nhỏ, không phải app riêng."
- §17 (thêm dòng): "Web push notification xuyên nền tảng cho HR (đặc biệt trên iOS, vốn hạn chế PWA push)."

> Giữ nguyên tắc: PRD là nguồn chân lý — sau lát này PRD phải phản ánh đúng rằng mobile = PWA.

## 5. Verify

1. `pnpm install` OK; `apps/mobile` đã biến mất; không còn tham chiếu mobile trong workspace/Makefile/package.json.
2. `make dev-dashboard`; mở `http://localhost:3000` — trang chạy bình thường, `/cv-check` vẫn hoạt động.
3. `pnpm --filter dashboard build` (production) PASS; kiểm tra `/manifest.webmanifest` truy cập được.
4. Ở bản production/preview: DevTools → Application → Manifest hiện đúng name/icons; Service Worker đăng ký OK;
   trình duyệt cho phép "Install app" / "Add to Home Screen".
5. Thu nhỏ cửa sổ / DevTools device mode (khổ điện thoại) → các trang hiện có responsive, không tràn.
6. `grep -ri "react-native\|expo\|apps/mobile" .` (trừ node_modules, git history) → không còn kết quả trong tài liệu/config.

## 6. Definition of Done

- [ ] `apps/mobile` đã xóa; `pnpm-workspace.yaml`/`package.json`/`Makefile` sạch tham chiếu mobile; `pnpm install` OK.
- [ ] `pnpm --filter dashboard build` PASS; `/manifest.webmanifest` + icon 192/512 tồn tại.
- [ ] Service worker đăng ký ở production; app "Install/Add to Home Screen" được; API không bị cache (dữ liệu tươi).
- [ ] Các trang hiện có responsive trên khổ điện thoại.
- [ ] `PRD.md` §1.3/§6/§11/§14/§17 đã cập nhật đúng wording ở mục 4; push nằm ở §17.
- [ ] `CLAUDE.md`, `docs/architecture.md`, `README.md` không còn nhắc React Native/Expo; mô tả PWA.
- [ ] `grep` không còn "react-native"/"expo"/"apps/mobile" trong tài liệu & config.

## 7. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ làm: gỡ mobile + PWA hạ tầng cho dashboard + cập nhật tài liệu/config. KHÔNG đụng backend/agent/logic.
- Đơn giản trước: PWA tối giản (manifest + SW cơ bản + icon), không thư viện nặng, không caching phức tạp,
  KHÔNG push thật. Đừng đẻ thêm việc ngoài mục 2–4.
- SW không cache API/dữ liệu động (tránh dữ liệu cũ); SW chỉ bật ở production.
- Commit nhỏ theo bước (vd `chore(repo): remove react-native mobile app`, `feat(pwa): manifest + service worker + icons`, `docs: sync mobile→PWA in PRD/CLAUDE/architecture/README`).
- Kết thúc: in tóm tắt thay đổi, kết quả verify, checklist DoD đã đạt.
