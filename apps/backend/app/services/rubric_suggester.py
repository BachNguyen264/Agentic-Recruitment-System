"""rubric_suggester — AI ĐỀ XUẤT rubric từ JD (JD-3, PRD §12.1 FR-HR-RUBRIC-1, trụ cột 4).

Lần dùng LLM thứ 3: parser=TRÍCH XUẤT · ranker=CHẤM · suggester=ĐỀ XUẤT (suy luận). Đọc JD (tiêu đề +
mô tả + yêu cầu, cấp bậc làm NGỮ CẢNH) → structured output list {criterion, weight, reasoning} → HR
CHỈNH/LƯU (KHÔNG tự áp — "AI đề xuất, HR duyệt"). AI TĂNG CƯỜNG năng lực HR (bắc cầu khoảng trống
chuyên môn), KHÔNG auto-hóa quyết định.

Gotchas (CLAUDE.md): reasoning model (gpt-5-mini) → `reasoning_effort`, KHÔNG `temperature` (set
temperature là lỗi). PLAIN-TEXT vào LLM (bóc HTML mô tả/yêu cầu — như JD-1; tag định dạng KHÔNG lọt
vào prompt). Literal `{{}}` để str.format không nuốt.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.html_text import html_to_lines, html_to_text
from app.core.logging import get_logger
from app.schemas.rubric_suggest import RubricSuggestion

logger = get_logger("app.services.rubric_suggester")

# Cấp bậc → nhãn ngữ cảnh (giúp LLM cân trọng số: senior/lead nặng kinh nghiệm + leadership).
_LEVEL_LABELS = {
    "intern": "Thực tập sinh",
    "fresher": "Fresher (mới ra trường)",
    "junior": "Junior",
    "mid": "Middle",
    "senior": "Senior",
    "lead": "Lead / Trưởng nhóm",
    "manager": "Manager / Quản lý",
}

_PROMPT_TEMPLATE = """Bạn là chuyên gia tuyển dụng thiết kế RUBRIC chấm điểm CV cho một tin tuyển dụng (JD).

NHIỆM VỤ: từ JD dưới đây, đề xuất 3-6 TIÊU CHÍ cốt lõi để chấm mức phù hợp của ứng viên, kèm TRỌNG SỐ.

NGUYÊN TẮC:
- Mỗi tiêu chí là một TRỤC NĂNG LỰC rõ ràng, có thể chấm từ CV (vd "Kinh nghiệm Node.js", "Kỹ năng \
lãnh đạo/dẫn dắt", "Kiến thức hệ thống phân tán"). KHÔNG bịa tiêu chí không có căn cứ trong JD.
- TRỌNG SỐ (0..1) phản ánh MỨC QUAN TRỌNG của tiêu chí VỚI VỊ TRÍ NÀY, KHÔNG chia đều hời hợt. Cân theo \
CẤP BẬC: cấp cao (senior/lead/manager) → kinh nghiệm sâu + lãnh đạo/ra quyết định nặng hơn; cấp thấp \
(intern/fresher/junior) → nền tảng + khả năng học nặng hơn. Tổng các trọng số NÊN ≈ 1.
- `reasoning`: 1 câu ngắn vì sao tiêu chí này + mức trọng số này hợp với JD (để HR tham khảo).
- Đây là ĐỀ XUẤT để HR chỉnh — ưu tiên bám sát nội dung JD hơn là liệt kê chung chung.

===== JD =====
Vị trí: {title}
Cấp bậc: {level}
Mô tả:
{description}
Yêu cầu:
{requirements}
"""


def model_label() -> str:
    """Nhãn model + chế độ — phân biệt cấu hình khi benchmark (plan §5)."""
    effort = (settings.rubric_suggest_reasoning_effort or "").strip()
    mode = f"reasoning_effort={effort}" if effort else "temperature=0"
    return f"{settings.rubric_suggest_model} ({mode})"


class RubricSuggestError(Exception):
    """Gọi LLM đề xuất rubric thất bại (key sai, mạng, quota, parse...)."""


def build_suggester_chat():
    """ChatOpenAI cấu hình được: reasoning (reasoning_effort) vs non-reasoning (temperature=0).

    Đối xứng ranker.build_ranker_chat — đổi model/effort CHỈ bằng .env (benchmark plan §5). Reasoning
    model (gpt-5-mini): `reasoning_effort`, KHÔNG temperature (langchain-openai BỎ temperature cho model
    reasoning; set là lỗi). Rỗng → non-reasoning (temperature=0).
    """
    from langchain_openai import ChatOpenAI

    effort = (settings.rubric_suggest_reasoning_effort or "").strip()
    if effort:
        return ChatOpenAI(
            model=settings.rubric_suggest_model,
            reasoning_effort=effort,
            api_key=settings.openai_api_key,
        )
    return ChatOpenAI(
        model=settings.rubric_suggest_model,
        temperature=0,
        api_key=settings.openai_api_key,
    )


def build_suggester_llm():
    """ChatOpenAI (theo env) + structured output RubricSuggestion — client đề xuất rubric."""
    return build_suggester_chat().with_structured_output(RubricSuggestion)


def _build_prompt(*, title: str, description: str, requirements: str, level: str | None) -> str:
    # PLAIN-TEXT vào LLM (bóc HTML — như JD-1). requirements → bullet từng dòng.
    reqs = html_to_lines(requirements)
    level_label = _LEVEL_LABELS.get(level or "", "Không nêu")
    return _PROMPT_TEMPLATE.format(
        title=title.strip() or "(không nêu)",
        level=level_label,
        description=html_to_text(description) or "(không nêu)",
        requirements="\n".join(f"- {r}" for r in reqs) or "(không nêu)",
    )


async def suggest_rubric(
    *,
    title: str,
    description: str,
    requirements: str,
    level: str | None = None,
    llm: Any | None = None,
) -> list[dict]:
    """JD (plain-text) → list {criterion, weight, reasoning} đề xuất. Lỗi LLM → RubricSuggestError.

    `llm` cho phép inject mock trong test. KHÔNG chạm DB — caller lo cap/count + persist.
    """
    prompt = _build_prompt(
        title=title, description=description, requirements=requirements, level=level
    )
    try:
        client = llm or build_suggester_llm()
        result: RubricSuggestion = await client.ainvoke(prompt)
    except Exception as exc:  # noqa: BLE001 — gói mọi lỗi provider/parse thành tín hiệu rõ ràng
        logger.warning("rubric_suggester: lỗi gọi LLM — %s", exc)
        raise RubricSuggestError(f"Lỗi gọi LLM khi gợi ý rubric: {exc}") from exc
    return [c.model_dump() for c in result.criteria]
