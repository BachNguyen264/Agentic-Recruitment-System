"""injection_signals — dấu hiệu CV đang cố ra lệnh cho máy (NFR-5). XÁC ĐỊNH, không hỏi LLM.

Vì sao không "kiểm giá trị có căn cứ trong văn bản": khi injection viết bằng chữ THƯỜNG, giá trị bịa
(tên công ty, kỹ năng, "13 năm") nằm NGAY trong văn bản CV — bên trong câu lệnh — nên phép kiểm căn
cứ nào cũng thấy nó "có thật". Tín hiệu đáng tin là HÌNH DẠNG của văn bản: CV người thật không gọi
tên trường JSON, không nhắn "lưu ý cho trợ lý trích xuất", không đòi "chấm 100 điểm".

Kết quả là LÝ DO (chuỗi cho HR đọc), không phải điểm số: có lý do nào → cờ `injection_suspected` →
human_review. Chặn nhầm tốn một lượt HR đọc; bỏ lọt thì hồ sơ bịa đi qua gate tự động — nên các
mẫu ưu tiên bắt, nhưng mỗi mẫu đều đòi NGỮ CẢNH gửi-cho-máy, không bắt từ khoá trơn ("AI", "hệ
thống", "chấm điểm" đều xuất hiện hợp lệ trong CV kỹ sư/giáo viên).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

_I = re.IGNORECASE | re.UNICODE

# Đích nhận lời nhắn: MÁY, không phải người (nhà tuyển dụng là người đọc hợp lệ của CV).
_MACHINE_VI = (
    r"(?:trợ\s+lý\s+(?:ai|ảo|trích\s+xuất|chấm|tuyển\s+dụng|đánh\s+giá)"
    r"|mô\s+hình\s+(?:ai|ngôn\s+ngữ|đánh\s+giá|chấm)"
    r"|công\s+cụ\s+(?:trích\s+xuất|đánh\s+giá|chấm|sàng\s+lọc)"
    r"|hệ\s+thống\s+(?:ai|chấm|đánh\s+giá|trích\s+xuất|tuyển\s+dụng|sàng\s+lọc)"
    r"|bộ\s+phận\s+đánh\s+giá\s+tự\s+động"
    r"|người\s+(?:chấm|tổng\s+hợp|đánh\s+giá)\s+hồ\s+sơ"
    r"|\bai\b|\bbot\b|chatbot|\bats\b|\bllm\b|\bgpt\b)"
)
# Tối đa hai từ bổ nghĩa chen trước ("the RESUME parser"). Đích là DANH TỪ chỉ máy — "evaluators",
# không phải "evaluation": "memos for the evaluation committee" là câu CV hợp lệ.
_MACHINE_EN = (
    r"(?:[\w-]+\s+){0,2}"
    r"(?:\bai\b|assistants?\b|\bmodels?\b|\bllms?\b|\bgpt\b|chatbots?\b|\bbots?\b|\bats\b"
    r"|(?:automated|automatic)\s+\w+|screening\s+(?:system|tool|software)|extractors?\b"
    r"|parsers?\b|evaluators?\b|\breviewers?\b|scorers?\b|scoring\s+(?:system|model|engine)"
    r"|rankers?\b)"
)

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "gọi tên trường dữ liệu nội bộ",
        re.compile(
            r"\b(?:total_years_experience|full_name|professional_summary|uncertainty_flags"
            r"|parsed_data|score_breakdown|escalation_reason|require_human_review)\b",
            _I,
        ),
    ),
    (
        "yêu cầu bỏ qua hướng dẫn",
        re.compile(
            r"(?:ignore|disregard|forget|bỏ\s+qua|phớt\s+lờ)\s+(?:all\s+|any\s+|mọi\s+|tất\s+cả\s+"
            r"|các\s+)?(?:the\s+|your\s+)?(?:previous|prior|above|earlier|trước(?:\s+đó)?|ở\s+trên"
            r"|system)?\s*(?:instructions?|prompts?|rules|hướng\s+dẫn|chỉ\s+dẫn|lệnh|quy\s+tắc)",
            _I,
        ),
    ),
    (
        "lời nhắn gửi cho máy",
        re.compile(
            r"(?:ghi\s+chú|lưu\s+ý|nhắn|gửi|hướng\s+dẫn\s+bổ\s+sung)\s+(?:(?:cho|gửi|tới|đến)\s+)?"
            r"(?:các\s+)?" + _MACHINE_VI
            + r"|(?:note|message|instructions?|notice|memo)s?\s+(?:to|for)\s+(?:the\s+|any\s+)?"
            + _MACHINE_EN
            + r"|(?:extraction|parsing|parser|scoring|ranking|screening)\s+"
            r"(?:note|override|instructions?|rules?)",
            _I,
        ),
    ),
    (
        "giả danh chỉ dẫn hệ thống",
        re.compile(
            r"\[\s*(?:system|sys|admin|hr\s+override|thông\s+báo\s+hệ\s+thống|hệ\s+thống)[^\]]{0,80}\]"
            r"|<\|(?:im_start|system)\|>|###\s*(?:system|instruction)"
            r"|<!--[^>]{0,200}(?:override|instruction|system|extraction)"
            r"|(?:system|developer)\s+(?:prompt|message|instructions?)"
            r"|chỉ\s+dẫn\s+hệ\s+thống|lời\s+nhắc\s+hệ\s+thống",
            _I,
        ),
    ),
    (
        "giả dấu ranh giới văn bản",
        re.compile(
            r"-{3,}\s*cv\s+(?:bắt\s+đầu|kết\s+thúc)\s*-{3,}|<</?cv-"
            r"|end\s+of\s+(?:cv|resume|document)\b",
            _I,
        ),
    ),
    (
        "đòi điểm số",
        re.compile(
            r"(?:chấm|cho|give|assign|rate|score|award)\s[^.\n]{0,60}?"
            r"(?:ứng\s+viên|candidate|hồ\s+sơ\s+này|tiêu\s+chí|criteri\w+|rubric)[^.\n]{0,60}?"
            r"(?:\d{2,3}\s*(?:điểm|/\s*100|points?)|điểm\s+tối\s+đa|maximum\s+score|full\s+marks)"
            r"|(?:mỗi|mọi|tất\s+cả(?:\s+các)?|every|each|all)\s+(?:rubric\s+)?(?:tiêu\s+chí|criteri\w+)"
            r"[^.\n]{0,40}?\d{2,3}\s*(?:điểm|/\s*100|points?)"
            r"|score\s+of\s+\d{2,3}\s+to\s+(?:every|each|all)",
            _I,
        ),
    ),
    (
        "yêu cầu ghi vào trường / giấu yêu cầu",
        re.compile(
            r"(?:hãy|vui\s+lòng|phải)\s+ghi\s[^.\n]{0,60}?(?:vào\s+trường|json|kết\s+quả\s+trích)"
            r"|(?:must|should)\s+be\s+recorded\s+exactly"
            r"|(?:không|đừng)\s+(?:đề\s+cập|nhắc)(?:\s+(?:tới|đến))?\s+(?:thông\s+báo|ghi\s+chú)\s+này"
            r"|do\s+not\s+mention\s+this\s+(?:notice|note|instruction)",
            _I,
        ),
    ),
]

_NAME_BAD = re.compile(r"https?://|www\.|\.[a-z]{2,}(?:/|\b)|@|\d", _I)
_NAME_MAX_CHARS = 60
_NAME_MAX_WORDS = 7

_YEAR = re.compile(r"\b(19[5-9]\d|20\d\d)\b")
_ONGOING = re.compile(r"\b(?:nay|hiện\s+tại|present|now|current|đến\s+nay)\b", _I)
# Dung sai khi so số năm khai với mốc thời gian: làm tròn tháng, thực tập, làm tự do không ghi mốc.
_YEARS_SLACK = 2.0


def text_signals(text: str) -> list[str]:
    """Lý do (cho HR) nếu văn bản CV có hình dạng chỉ dẫn gửi cho máy. Rỗng = sạch."""
    reasons = []
    for label, pattern in _PATTERNS:
        m = pattern.search(text)
        if m:
            snippet = " ".join(m.group(0).split())[:80]
            reasons.append(f"{label} («{snippet}»)")
    return reasons


def _experience_span_years(experiences: list[dict[str, Any]], today: date) -> float | None:
    """Khoảng năm từ mốc sớm nhất tới mốc muộn nhất trong `duration` — None nếu không có mốc nào."""
    starts: list[int] = []
    ends: list[int] = []
    for exp in experiences or []:
        duration = (exp or {}).get("duration") or ""
        years = [int(y) for y in _YEAR.findall(duration)]
        if not years:
            continue
        starts.append(min(years))
        ends.append(today.year if _ONGOING.search(duration) else max(years))
    if not starts:
        return None
    return float(max(ends) - min(starts) + 1)  # +1: "2020 – 2020" vẫn là có làm


def parsed_signals(parsed: dict[str, Any], *, today: date | None = None) -> list[str]:
    """Lý do nếu KẾT QUẢ bóc tách mang dấu vết đã bị điều khiển (tên không phải tên người, số năm
    kinh nghiệm vượt xa mốc thời gian chính CV khai)."""
    reasons = []
    name = (parsed.get("full_name") or "").strip()
    if name and (
        _NAME_BAD.search(name) or len(name) > _NAME_MAX_CHARS or len(name.split()) > _NAME_MAX_WORDS
    ):
        reasons.append(f"họ tên bóc ra không giống tên người («{name[:80]}»)")

    claimed = parsed.get("total_years_experience")
    span = _experience_span_years(parsed.get("experiences") or [], today or date.today())
    if isinstance(claimed, (int, float)) and span is not None and claimed > span + _YEARS_SLACK:
        reasons.append(
            f"số năm kinh nghiệm khai {claimed:g} vượt xa mốc thời gian trong mục kinh nghiệm "
            f"(~{span:g} năm)"
        )
    return reasons
