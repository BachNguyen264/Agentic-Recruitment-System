# Kiến trúc (tóm tắt) — Autonomous Recruitment System

> Tài liệu này CHỈ tóm tắt để định hướng code. **Nguồn chân lý đầy đủ: [`../PRD.md`](../PRD.md).**
> Khi mâu thuẫn → PRD đúng. Giai đoạn hiện tại: **scaffold** (node stub, UI placeholder).

## 4 trụ cột thiết kế (PRD §5)

1. **Luồng cố định để dự đoán & kiểm toán** — thứ tự agent + nhánh rẽ do graph quy định trước.
   **KHÔNG Supervisor Agent** (lựa chọn có chủ đích).
2. **Tự trị CÓ GIỚI HẠN ở tầng agent** — trong mỗi node agent tự chọn tool (function calling), bị giới
   hạn số bước. Pipeline cố định ở tầng điều phối.
3. **An toàn trước case lạ** — mỗi agent trả `confidence` + `uncertainty_flags`; dưới ngưỡng → `human_review`.
4. **Cải thiện dần bán tự động có người duyệt** — phát hiện mẫu từ `audit_log` → đề xuất → HR duyệt.

## Pipeline (PRD §7–§8)

```
START → parser → ranker → [should_review?] ──no──→ screener → scheduler → END
                                   │
                                   └──yes──→ human_review → END
```

| Node           | Vai trò (PRD)                          | Scaffold                              |
| -------------- | -------------------------------------- | ------------------------------------- |
| `parser`       | CV (PDF/DOCX) → JSON (§7.1)             | stub pass-through                     |
| `ranker`       | đối sánh CV–JD + chấm điểm; **quyết định** (§7.2) | stub set confidence; đọc cờ demo |
| `screener`     | gửi câu hỏi + magic-link, **suspend/resume** (§7.3, §10) | stub pass-through (chưa suspend) |
| `scheduler`    | **điểm gửi email DUY NHẤT** (mời/từ chối) (§7.4) | stub pass-through              |
| `human_review` | HR quyết, kèm **ReviewCard** (§11)      | set require_human_review + reason     |

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
| Mobile     | Expo (React Native)             | [`apps/mobile`](../apps/mobile)         |
| Types      | TS dùng chung                   | [`packages/shared-types`](../packages/shared-types) |
| Hạ tầng    | Neon · Upstash · Qdrant         | managed (xem `.env.example`)            |

## Bền vững & async (PRD §10, NFR-1/2)

- Mỗi CV = một pipeline độc lập, chạy song song; CV chờ Screener KHÔNG nghẽn CV khác.
- Screener **suspend/resume**: LangGraph `interrupt` + **Postgres checkpointer** (phase sau; scaffold dùng
  `MemorySaver`). KHÔNG worker polling Redis (giữ free-tier Upstash).

## Chừa chỗ kiến trúc (đã có ở scaffold)

- `RecruitmentState`: `confidence`, `uncertainty_flags`, `escalation_reason`, `require_human_review`,
  `awaiting_screener`, `screener_answers`.
- `policy.should_review()` route được; `run-demo` chạy **cả 2 nhánh**.
- `audit_log` đủ cột (node, action, confidence, uncertainty_flags, escalation_reason, detail) — PRD §16.

## TODO trỏ PRD (phase sau)

LLM trong pipeline (`ENABLE_LLM`), parse CV thật, RAG/Qdrant, gate (§9), Screener async (§10),
ReviewCard (§11), email/Calendar/Zalo, vòng học bán tự động (§5 trụ cột 4).
