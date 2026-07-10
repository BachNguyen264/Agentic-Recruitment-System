# SLICE — Dọn dẹp: xóa data demo + gỡ Run demo · plan one-shot

> **Bản chất:** plan ONE-SHOT dọn dẹp. Xong thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** (1) xóa dữ liệu demo/test còn sót trong Neon để danh sách ứng viên sạch; (2) gỡ tính năng
> "Run demo" (nút + endpoint) giờ đã thừa, vì luồng thật (upload CV → parser+ranker → /applications) đã thay thế.
> Tuân thủ `CLAUDE.md`.

---

## 1. In scope / Out of scope

**In scope:**

- Xóa dữ liệu demo/test trong Neon (application, job_posting test, audit_log).
- Gỡ Run demo GỌN CẢ HAI ĐẦU: frontend `AgentTracePanel` + backend endpoint `run-demo` (+ schema demo nếu có).

**Out of scope (KHÔNG đụng — GIỮ LẠI):**

- GIỮ `ServiceStatus` ở trang chủ (khác Run demo; vẫn hữu ích xem hạ tầng sống).
- GIỮ `agent_graph`, `should_review`, các node (parser/ranker/…), endpoint `parse-cv`, `rank-cv` — hạ tầng thật.
- KHÔNG đụng logic agent/pipeline/policy; KHÔNG xóa schema/bảng DB (chỉ xóa DỮ LIỆU, không đổi cấu trúc).
- KHÔNG xóa dữ liệu JD "thật" nếu bạn muốn giữ để test tiếp (xem mục 2 — hỏi trước nếu không chắc).

---

## 2. Xóa dữ liệu demo (Neon)

- Xác định phạm vi xóa: các application + audit_log từ bước verify. Với job_posting: giữ hay xóa tùy — nếu bạn
  còn dùng JD id=2 (Backend Intern) để test lát sau thì GIỮ; chỉ xóa JD test/rác (vd row legacy id=1, JD "Kế toán" nếu không cần).
- **QUAN TRỌNG:** nếu xóa job_posting, phải dọn kèm **vector JD trong Qdrant** (điểm có payload `{job_id}` tương ứng)
  để Qdrant không còn vector mồ côi. Nếu chỉ xóa DB mà để vector lại → lệch dữ liệu.
- Cách làm: viết một script nhỏ (`scripts/reset_demo_data.py`) xóa có kiểm soát (theo id hoặc theo điều kiện),
  HOẶC dùng Neon SQL editor xóa tay. Ưu tiên script để lặp lại được + kèm bước xóa vector Qdrant tương ứng.
- Nếu KHÔNG chắc row nào nên giữ/xóa → DỪNG, liệt kê cho người dùng xác nhận trước khi xóa.

## 3. Gỡ Run demo

**Frontend:**

- Xóa `components/AgentTracePanel.tsx` và mọi chỗ import/dùng nó (chủ yếu trang chủ `app/page.tsx`).
- Xóa hàm gọi `run-demo` trong `lib/api.ts` (nếu có) + kiểu liên quan trong `shared-types` (nếu chỉ dùng cho demo).
- Trang chủ sau khi gỡ: GIỮ `ServiceStatus`; bố cục còn lại gọn gàng, không để khoảng trống vỡ.

**Backend:**

- Xóa endpoint `POST /api/agents/run-demo` trong `app/api/routes/agents.py` + schema demo riêng (nếu có, vd trong `schemas/agent.py`).
- GIỮ `parse-cv`, `rank-cv` và mọi thứ khác trong file.
- Dọn import thừa do việc xóa tạo ra (chỉ phần mình xóa).

**Test:**

- Xóa/không còn test cho run-demo (vd trong `test_graph.py` nếu có test gọi run-demo endpoint). GIỮ test compile graph +
  test parser/ranker. `make test` phải vẫn xanh sau khi gỡ.

---

## 4. Verify

1. `make dev-backend` + `make dev-dashboard`; trang chủ hiện `ServiceStatus` (3 dịch vụ xanh), KHÔNG còn Run demo, bố cục không vỡ.
2. `GET /docs`: KHÔNG còn `run-demo`; `parse-cv` + `rank-cv` vẫn còn.
3. `/applications`: danh sách sạch (không còn data demo/test rác).
4. Nếu giữ JD id=2: `search-test`/rank vẫn chạy (JD + vector còn nguyên).
5. `make test` xanh; `pnpm --filter dashboard build` PASS.

## 5. Definition of Done

- [ ] Data demo/test đã xóa trong Neon; nếu xóa JD thì vector Qdrant tương ứng cũng đã xóa (không mồ côi).
- [ ] `AgentTracePanel` + endpoint `run-demo` (+ schema demo) đã gỡ gọn cả hai đầu.
- [ ] `ServiceStatus`, `agent_graph`, các node, `parse-cv`, `rank-cv` GIỮ NGUYÊN.
- [ ] Trang chủ không vỡ bố cục; `/docs` không còn run-demo; `/applications` sạch.
- [ ] `make test` xanh; `pnpm build` PASS; không đụng schema/bảng DB (chỉ xóa dữ liệu).

## 6. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ xóa data + gỡ Run demo (nút + endpoint + schema/test của riêng nó). KHÔNG đụng hạ tầng thật hay logic agent.
- Xóa có phẫu thuật: chỉ dọn import/kiểu do việc xóa tạo ra; không refactor lan man.
- Nếu không chắc row DB nào nên giữ → DỪNG, hỏi trước khi xóa.
- Commit nhỏ (vd `chore(db): script reset_demo_data + dọn data test (kèm vector Qdrant)`, `chore(ui): gỡ AgentTracePanel khỏi trang chủ`, `chore(api): gỡ endpoint run-demo`).
- Kết thúc: in tóm tắt thay đổi + xác nhận DoD.
