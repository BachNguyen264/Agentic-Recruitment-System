"""parser node — THẬT (PRD §7.1).

CV (PDF/DOCX) -> trích text -> LLM OpenAI (structured output) -> `ParsedCV` JSON
+ `confidence` (heuristic xác định) + cờ `parse_failed`. Lỗi đọc/LLM KHÔNG làm sập pipeline.

`ENABLE_LLM=false` (hoặc không có file CV trong state) -> giữ hành vi stub cũ (PRD §17, không
phá run-demo/test_graph). Cờ `ENABLE_LLM` ở slice này CHỈ node parser đọc.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.state import RecruitmentState
from app.core.config import settings
from app.core.logging import get_logger
from app.models.application import ApplicationStatus
from app.schemas.parsed_cv import ParsedCV
from app.services.storage import StorageError, get_storage
from app.tools.cv_reader import CVReadError, extract_text

logger = get_logger("app.agents.parser")

# Số trường lõi để chấm confidence (heuristic — KHÔNG hỏi LLM tự chấm). PRD §7.1.
_CORE_FIELD_COUNT = 5

_PROMPT = (
    "Bạn là trợ lý trích xuất thông tin từ CV/hồ sơ ứng tuyển. "
    "Trích các trường yêu cầu từ văn bản CV dưới đây. "
    "CHỈ dùng thông tin CÓ THẬT trong CV — KHÔNG suy đoán, KHÔNG bịa. "
    "Trường nào không tìm thấy thì để trống (None) hoặc danh sách rỗng. "
    "CV có thể bằng tiếng Việt hoặc tiếng Anh.\n\n"
    "QUY TẮC XẾP THÔNG TIN (quan trọng — để `other` không thành thùng rác):\n"
    "1. LUÔN ưu tiên xếp thông tin vào đúng trường CÓ CẤU TRÚC: full_name, email, phone, "
    "professional_summary (mục tiêu/tóm tắt nghề nghiệp), total_years_experience, skills, experiences, "
    "education, certificates (chứng chỉ như TOEIC/IELTS/AWS — chứng chỉ NGOẠI NGỮ chuẩn hóa cũng vào "
    "đây, điểm/cấp độ để ở `detail`), languages (ngôn ngữ + mức tự đánh giá; KHÔNG lặp lại chứng chỉ đã "
    "ở certificates), awards (giải thưởng/thành tích).\n"
    "2. `other` là LƯỚI AN TOÀN — CHỈ dùng cho khối CV KHÔNG thuộc bất kỳ trường nào ở trên "
    "(vd: Sở thích, Người tham chiếu, Hoạt động ngoại khóa). Mỗi khối một {{label, content}}.\n"
    "3. TUYỆT ĐỐI KHÔNG đặt chứng chỉ/ngôn ngữ/giải thưởng vào `other` — chúng đã có trường riêng.\n\n"
    "----- CV BẮT ĐẦU -----\n{cv_text}\n----- CV KẾT THÚC -----"
)


def _confidence(parsed: ParsedCV) -> float:
    """Tỉ lệ trường lõi có dữ liệu / 5 (xác định). PRD §7.1: confidence theo chất lượng bóc tách."""
    got = sum(
        (
            bool(parsed.full_name),
            bool(parsed.email or parsed.phone),
            bool(parsed.skills),
            bool(parsed.experiences),
            bool(parsed.education),
        )
    )
    return round(got / _CORE_FIELD_COUNT, 2)


def _failed(reason: str) -> dict:
    """Kết quả parse thất bại — cờ parse_failed + confidence 0.0 (PRD §7.1, §13)."""
    return {
        "parsed_data": None,
        "confidence": 0.0,
        "uncertainty_flags": ["parse_failed"],
        "escalation_reason": reason,
    }


def _build_parser_llm():
    """ChatOpenAI structured-output cho ParsedCV. Tách ra để test mock/inject dễ."""
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model=settings.parser_model, temperature=0, api_key=settings.openai_api_key)
    return llm.with_structured_output(ParsedCV)


def parse_cv(data: bytes, name: str, *, llm: Any | None = None) -> dict:
    """Lõi parser (KHÔNG chạm DB, KHÔNG I/O storage): BYTES CV -> LLM -> ParsedCV + confidence + flags.

    Nhận sẵn bytes (slice 06: CV có thể ở đĩa hoặc R2 — người gọi lấy qua seam storage). `name` là
    tên file/key, chỉ để chọn bộ đọc theo đuôi. Dùng chung bởi node (pipeline) và endpoint
    /agents/parse-cv. `llm` cho phép inject mock trong test. Trả dict:
    `{parsed_data, confidence, uncertainty_flags, escalation_reason}`.
    """
    try:
        text = extract_text(data, name)
    except CVReadError as exc:
        logger.info("parser: parse_failed khi đọc %s — %s", name, exc)
        return _failed(str(exc))

    try:
        client = llm or _build_parser_llm()
        parsed: ParsedCV = client.invoke(_PROMPT.format(cv_text=text))
    except Exception as exc:  # noqa: BLE001 — lỗi LLM/API KHÔNG được làm sập pipeline (PRD §7.1)
        logger.warning("parser: lỗi gọi LLM cho %s — %s", name, exc)
        return _failed(f"Lỗi gọi LLM khi parse CV: {exc}")

    return {
        "parsed_data": parsed.model_dump(),
        "confidence": _confidence(parsed),
        "uncertainty_flags": [],
        "escalation_reason": None,
    }


async def parser_node(state: RecruitmentState) -> dict:
    """Node pipeline. Lấy KEY CV từ state.input.cv_path → bytes qua seam storage; persist do background.

    ASYNC (slice 06): đọc CV giờ là I/O mạng khi STORAGE_BACKEND=r2 → phải await storage.get.
    (ranker_node vốn đã async; graph chạy lẫn sync/async qua `ainvoke` — xem CLAUDE.md.)
    """
    cv_key = (state.get("input") or {}).get("cv_path")

    if not settings.enable_llm or not cv_key:
        # Stub (scaffold) — giữ nguyên hành vi cũ để không phá run-demo/test_graph.
        return {
            "status": ApplicationStatus.PARSING.value,
            "scratchpad": {**state.get("scratchpad", {}), "parsed": True},
            "confidence": 1.0,
            "uncertainty_flags": [],
            "messages": ["[parser] stub pass-through (ENABLE_LLM=false hoặc không có file CV)"],
        }

    # Lỗi storage (mất file / R2 lỗi / key cũ trước slice 06) KHÔNG làm sập pipeline → parse_failed
    # + escalation, giống lỗi đọc file (PRD §7.1).
    try:
        data = await get_storage().get(cv_key)
    except StorageError as exc:
        logger.warning("parser: không lấy được CV %s — %s", cv_key, exc)
        result = _failed(f"Không đọc được file CV từ storage: {exc}")
    else:
        # parse_cv ĐỒNG BỘ (PyMuPDF/python-docx + gọi LLM sync) → PHẢI offload sang thread. Node này
        # là async (để await storage) nên KHÔNG còn được LangGraph tự chạy trong executor như hồi
        # còn `def`; gọi thẳng sẽ CHẶN event loop suốt vài giây (mọi request khác đứng hình).
        result = await asyncio.to_thread(parse_cv, data, cv_key)

    failed = "parse_failed" in result["uncertainty_flags"]
    if failed:
        msg = f"[parser] parse_failed — {result['escalation_reason']}"
    else:
        name = (result["parsed_data"] or {}).get("full_name")
        msg = f"[parser] OK — confidence={result['confidence']}, name={name!r}"

    return {
        "status": ApplicationStatus.PARSING.value,
        "parsed_data": result["parsed_data"],
        "confidence": result["confidence"],
        "uncertainty_flags": result["uncertainty_flags"],
        "escalation_reason": result["escalation_reason"],
        "scratchpad": {**state.get("scratchpad", {}), "parsed": not failed},
        "messages": [msg],
    }
