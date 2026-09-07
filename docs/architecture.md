# Kiến trúc (tóm tắt) — Autonomous Recruitment System

> Tài liệu này CHỈ tóm tắt để định hướng code. **Nguồn chân lý đầy đủ: [`../PRD.md`](../PRD.md).**
> Khi mâu thuẫn → PRD đúng. Giai đoạn: **cả 5 node đã THẬT và đã chạy end-to-end trên bản deploy
> thật.** Trạng thái chi tiết từng lát: [`../CLAUDE.md`](../CLAUDE.md).

## 4 trụ cột thiết kế (PRD §5)

1. **Luồng cố định để dự đoán & kiểm toán** — thứ tự agent + nhánh rẽ do graph quy định trước.
   **KHÔNG Supervisor Agent** (lựa chọn có chủ đích).
2. **Tự trị CÓ GIỚI HẠN ở tầng agent** — trong mỗi node agent tự chọn tool (function calling), bị giới
   hạn số bước. Pipeline cố định ở tầng điều phối.
3. **An toàn trước case lạ** — mỗi agent trả `confidence` + `uncertainty_flags`; dưới ngưỡng → `human_review`.
4. **Cải thiện dần bán tự động có người duyệt** — phát hiện mẫu từ `audit_log` → đề xuất → HR duyệt.

## Pipeline (PRD §7–§8)

```
START → parser → ranker → [gate rank] ──đạt──→ screener ──[gate mời]──→ scheduler → END
                               │  (suspend/resume, có hạn giờ)   │
                               └──cần người──→ human_review ◄────┘
```

Hai điểm rẽ, KHÔNG phải một: `route_after_ranker` (gate auto-từ-chối) và `route_after_screener`
(gate auto-mời) — xem docstring `agents/graph.py`. Sau khi scheduler gửi thư mời, hồ sơ sang
`AWAITING_BOOKING`; ứng viên tự chọn giờ xong mới thành `INTERVIEW_SCHEDULED` (PRD §10b).

| Node           | Vai trò (PRD)                          | Hiện trạng                                          |
| -------------- | -------------------------------------- | --------------------------------------------------- |
| `parser`       | CV (PDF/DOCX) → JSON (§7.1)             | ✅ THẬT — OpenAI `gpt-4.1-mini` structured output    |
| `ranker`       | đối sánh CV–JD + chấm điểm; **quyết định** (§7.2) | ✅ THẬT — `gpt-5-mini` chấm rubric; embedding phụ |
| `screener`     | gửi câu hỏi + magic-link, **suspend/resume** (§7.3, §10) | ✅ THẬT — `interrupt()` + AsyncPostgresSaver, hạn giờ/nhắc |
| `scheduler`    | **điểm gửi email DUY NHẤT** (mời/từ chối) (§7.4) | ✅ THẬT — Resend + 6 loại thư đặt lịch      |
| `human_review` | HR quyết, kèm **ReviewCard** (§11)      | ✅ THẬT — ReviewCard + duyệt/từ chối, ghi audit      |
| `gate`         | thi hành hai gate cấu hình theo JD (§9) | ✅ THẬT — `agents/nodes/gate.py`                     |

Hai **gate** cấu hình (PRD §9, mặc định TẮT): `auto-từ-chối` (sau ranker), `auto-mời` (sau screener).
Bất biến FR-GATE-2: ca bất định LUÔN vào `human_review`, bất kể gate.

## Thành phần & vị trí code

| Lớp        | Công nghệ                       | Vị trí                                  |
| ---------- | ------------------------------- | --------------------------------------- |
| Backend    | FastAPI + LangGraph             | [`apps/backend/app`](../apps/backend/app) |
| ↳ pipeline | LangGraph state/nodes/policy    | `app/agents/`                           |
| ↳ data     | SQLAlchemy 2 async + Alembic    | `app/models/`, `apps/backend/alembic/`  |
| ↳ async    | FastAPI BackgroundTasks         | `app/tasks/background.py`               |
| Dashboard  | Next.js 14 + TanStack Query     | [`apps/dashboard`](../apps/dashboard)   |
| PWA (điện thoại) | web dashboard cài được — không codebase riêng | [`apps/dashboard`](../apps/dashboard) |
| Types      | TS dùng chung                   | [`packages/shared-types`](../packages/shared-types) |
| Hạ tầng    | Neon · Qdrant · Cloudflare R2   | managed (xem `.env.example`)            |

## Bền vững & async (PRD §10, NFR-1/2)

- Mỗi CV = một pipeline độc lập, chạy song song; CV chờ Screener KHÔNG nghẽn CV khác.
- Screener **suspend/resume**: LangGraph `interrupt` + **Postgres checkpointer** (`AsyncPostgresSaver`
  trên Neon — CHẠY THẬT; `MemorySaver` chỉ là fallback khi checkpointer chưa setup). KHÔNG worker
  polling: không dựng thêm hàng đợi ngoài phải nuôi.

## Chừa chỗ kiến trúc (đã có)

- `RecruitmentState`: `confidence`, `uncertainty_flags`, `escalation_reason`, `require_human_review`,
  `score`, `score_breakdown`, `semantic_similarity`, `awaiting_screener`, `screener_answers`.
- `policy.should_review()` route theo giá trị thật; test `test_graph` phủ **cả 2 nhánh** (`force_review`).
- `audit_log` đủ cột (node, action, confidence, uncertainty_flags, escalation_reason, detail) — PRD §16.

## TODO trỏ PRD (lát sau)

Google Calendar (hiện dùng `.ics` qua seam `IcsProvider`), Zalo OA (tuỳ chọn),
vòng học bán tự động (§5 trụ cột 4), chống prompt-injection, analytics.
