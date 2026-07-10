# SLICE 03b — human_review THẬT (ReviewCard + duyệt/từ chối → delegate scheduler) · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** biến điểm đến `human_review` từ stub thành khâu THẬT — HR xem ReviewCard (tóm tắt + điểm +
> lý do leo thang) rồi Duyệt/Từ chối; quyết định delegate cho `scheduler` (điểm thực thi duy nhất) + ghi audit_log.
> Đây là mảnh cốt lõi của câu chuyện human-in-the-loop.
> Tham chiếu: PRD §11 (ReviewCard + FR-HR), §12.1 (FR-HR-REVIEW-1), §13 (trạng thái). Tuân thủ `CLAUDE.md`.
>
> **RANH GIỚI với scheduler (lát 04):** `scheduler` GIỮ stub — khi được gọi, chỉ GHI LOG "sẽ gửi thư mời/từ chối"
> (KHÔNG gửi email thật). Email thật = lát 04. 03b thiết lập luồng delegate + chuyển trạng thái + audit.
> **KHÔNG dùng LangGraph checkpointer/interrupt** ở lát này (ca review đã kết thúc graph; approve/reject gọi
> scheduler trực tiếp). Suspend/resume bền = lát 08a (Screener), đừng kéo vào.

---

## 1. In scope / Out of scope

**In scope:**

- Component `ReviewCard` (thuần presentational + callback): tóm tắt ứng viên + `ScoreBreakdown` (tái dùng 03a) +
  `escalation_reason` + đề xuất hệ thống + ô ghi chú + nút Duyệt/Từ chối.
- Trang hàng đợi `/review`: liệt kê ca PENDING_REVIEW → render ReviewCard có hành động.
- Backend: endpoint `POST /api/applications/{id}/review {decision, note}` → gọi scheduler (stub) + chuyển trạng
  thái + ghi audit_log. Đảm bảo detail trả `escalation_reason` (+ recommendation nhẹ).
- `scheduler` (stub) nhận "mode" (invite/reject) → ghi log ý định (KHÔNG email thật). Điểm thực thi DUY NHẤT.
- Badge số ca chờ (PENDING_REVIEW) ở điều hướng (PRD §12.4 FR-NOTI-2 — badge in-app).

**Out of scope (KHÔNG làm):**

- KHÔNG gửi email thật (scheduler vẫn stub — lát 04). KHÔNG Google Calendar.
- KHÔNG gate rank/mời (lát 03c/08d). KHÔNG checkpointer/interrupt (lát 08a).
- KHÔNG route approve → screener (screener chưa thật): approve → scheduler(mời) → đặt lịch thẳng; resume-vào-pipeline là việc của lát Screener.
- KHÔNG bảng ReviewCase mới (dùng audit_log cho bản ghi quyết định — đủ cho FR-HR-5; bảng §16 để sau nếu cần lịch sử review giàu hơn).
- KHÔNG đụng parser/ranker/policy logic.

---

## 2. Prerequisites

- Có ca PENDING_REVIEW để test: upload CV lệch ngành hoặc CV có `score_signal_mismatch` cho job_id=2 (sẽ vào review).
- shadcn/ui, TanStack Query, lib/api.ts đã có. Lệnh Node chạy PowerShell.

---

## 3. Việc cần làm

### 3.1 Backend — endpoint quyết định · `app/api/routes/applications.py` (+ service)

- `POST /api/applications/{id}/review` body `{decision: "approve" | "reject", note: str | None}`:
  1. Lấy application; **validate** `status == PENDING_REVIEW`, nếu không → 409 (tránh quyết định 2 lần / sai trạng thái).
  2. **Delegate scheduler** (điểm thực thi duy nhất): gọi node/logic scheduler với mode = `invite` (approve) hoặc
     `reject`. Scheduler stub GHI LOG "sẽ gửi thư mời + tạo lịch" / "sẽ gửi thư từ chối" — KHÔNG email thật.
  3. Chuyển trạng thái (PRD §13): approve → `INTERVIEW_SCHEDULED`; reject → `REJECTED`.
  4. Ghi `audit_log`: node="human_review", action="approve"/"reject", detail={note, decided_by (placeholder cho tới khi có auth)}.
     (Thêm dòng audit cho bước scheduler nếu tiện.)
  5. Trả application đã cập nhật.
- Đảm bảo `GET /api/applications/{id}` trả `escalation_reason` (thêm nếu 03a chưa có) + một field `recommendation`
  nhẹ dẫn xuất (score ≥ SCORE_PASS_THRESHOLD & không cờ nặng → "mời"; score thấp → "cân nhắc từ chối"; có
  `score_signal_mismatch`/cờ → "xem kỹ"). Recommendation chỉ là gợi ý hiển thị, KHÔNG tự quyết.

### 3.2 Scheduler stub nhận mode · `app/agents/nodes/scheduler.py`

- Cho scheduler nhận quyết định/mode (invite/reject); ghi log rõ ý định gửi email tương ứng. GIỮ stub (không
  gửi thật). Mục đích: là điểm delegate duy nhất để lát 04 chỉ việc thay log → gửi email thật, không sửa luồng review.

### 3.3 shared-types · `packages/shared-types/src/index.ts`

- `ReviewDecision = "approve" | "reject"`; `ReviewRequest = {decision, note?}`; mở rộng `ApplicationDetail` với
  `escalation_reason`, `recommendation`.

### 3.4 `lib/api.ts`

- `submitReview(id, decision, note): Promise<ApplicationDetail>` → POST endpoint 3.1.
- (đã có `getApplications`/`getApplication` từ 03a; dùng lại, lọc PENDING_REVIEW cho hàng đợi).

### 3.5 Component `ReviewCard` · `components/ReviewCard.tsx`

- **Thuần presentational** + nhận callback `onApprove(note)` / `onReject(note)`.
- Hiển thị: tóm tắt ứng viên (tên + kỹ năng chính + kinh nghiệm nổi bật từ parsed_data); `ScoreBreakdown` (tái dùng);
  `escalation_reason` nổi bật (vì sao vào review); `recommendation` (gợi ý hệ thống); ô ghi chú; nút Duyệt/Từ chối.
- Dùng shadcn (Card/Badge/Button/Textarea…). Style nhất quán 03a.

### 3.6 Trang `/review` · `app/review/page.tsx`

- Fetch application PENDING_REVIEW → render danh sách `ReviewCard` có hành động.
- Duyệt/Từ chối qua TanStack Query `useMutation(submitReview)` → khi thành công, invalidate query (ca rời hàng đợi).
- Trạng thái: loading / empty ("không có ca chờ") / error. Đang submit → disable nút, tránh double-click.

### 3.7 Điều hướng + badge

- Link `/review` từ trang chủ / nav. Badge hiển thị **số ca PENDING_REVIEW** (đếm từ getApplications). Cập nhật sau khi quyết định.

---

## 4. Verify (chạy thật)

1. Tạo vài ca PENDING_REVIEW: upload CV lệch ngành (kế toán) cho job_id=2 (điểm thấp → review) và/hoặc CV có `score_signal_mismatch`.
2. `make dev-backend` + `make dev-dashboard`; mở `/review` → thấy các ReviewCard (tóm tắt + điểm từng tiêu chí + lý do + đề xuất). Badge hiện đúng số ca.
3. **Duyệt** một ca → trạng thái thành INTERVIEW_SCHEDULED, ca rời hàng đợi, badge giảm; backend LOG "sẽ gửi thư mời + tạo lịch"; audit_log có dòng human_review action=approve.
4. **Từ chối** một ca (kèm ghi chú) → REJECTED; backend LOG "sẽ gửi thư từ chối"; audit_log có dòng action=reject + note.
5. Gọi lại review trên ca đã quyết → 409 (không quyết 2 lần).
6. Kiểm `/applications` (03a): trạng thái ứng viên đã cập nhật (passed/rejected) + bộ lọc rổ đúng.
7. `make test` xanh; `pnpm --filter dashboard build` PASS.

---

## 5. Definition of Done

- [ ] `/review` hiển thị hàng đợi ca PENDING_REVIEW dưới dạng ReviewCard (tóm tắt + ScoreBreakdown + escalation_reason + đề xuất).
- [ ] Duyệt → INTERVIEW_SCHEDULED; Từ chối → REJECTED; cả hai delegate scheduler (stub log) + ghi audit_log.
- [ ] Endpoint validate trạng thái (chỉ PENDING_REVIEW mới quyết được; else 409).
- [ ] scheduler là điểm delegate duy nhất (log ý định email; KHÔNG gửi thật — dành lát 04).
- [ ] `ReviewCard` thuần presentational (nhận callback), tái dùng `ScoreBreakdown`.
- [ ] Badge số ca chờ hoạt động; trạng thái phản ánh sang /applications.
- [ ] KHÔNG gate, KHÔNG email thật, KHÔNG checkpointer, KHÔNG đụng parser/ranker/policy.
- [ ] `make test` xanh; `pnpm build` PASS.

---

## 6. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ động vào: review endpoint + scheduler-nhận-mode (stub) + ReviewCard + /review + shared-types/api + badge/nav.
- Đây là MUTATION đầu tiên của app → cẩn thận: validate trạng thái, xử lý lỗi, invalidate query sau thành công, chống double-submit.
- scheduler GIỮ stub (chỉ nhận mode + log); KHÔNG gửi email/Calendar thật (lát 04).
- approve → scheduler(mời) thẳng (KHÔNG route qua screener — screener chưa thật; resume-vào-pipeline là lát Screener).
- Bản ghi quyết định qua audit_log (đủ FR-HR-5); KHÔNG thêm bảng ReviewCase (để sau nếu cần).
- Component tái dùng ScoreBreakdown; ReviewCard presentational. Style nhất quán 03a; shadcn, không thêm lib UI.
- Commit nhỏ (vd `feat(api): endpoint review approve/reject + delegate scheduler stub`, `feat(agents): scheduler nhận mode (stub log)`, `feat(ui): ReviewCard tái dùng ScoreBreakdown`, `feat(ui): trang /review + badge số ca chờ`).
- Nghiệp vụ chưa rõ → tra **PRD.md** (§11, §13). PRD chưa đủ → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, lệnh verify, checklist DoD.

---

## 7. Lát kế tiếp (KHÔNG làm bây giờ)

**03c Gate rank** (auto-từ-chối dùng score + gate_config, PRD §9) hoặc **04 Scheduler email thật** (biến log ý định
thành email gửi đi). Sau đó GĐ2 (đăng JD UI + nộp CV công khai + storage). Xem ROADMAP.md.
