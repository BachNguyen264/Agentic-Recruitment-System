"""Bóc HTML → plain-text cho embedding + LLM (JD-1).

Nội dung JD (mô tả/yêu cầu/quyền lợi) do HR soạn ở editor định dạng → lưu HTML. Định dạng CHỈ để
hiển thị: TUYỆT ĐỐI không để tag lọt vào embedding (nhiễu vector) hay prompt ranker (nhiễu điểm).
Dùng stdlib `html.parser` (KHÔNG thêm dependency). Không nhằm mục đích SANITIZE — chỉ trích text;
sanitize XSS làm ở client khi render (/apply, DOMPurify).
"""

from __future__ import annotations

from html.parser import HTMLParser

# Tag khối → xuống dòng (giữ ranh giới đoạn/mục danh sách khi bóc text).
_BLOCK_TAGS = frozenset(
    {"p", "br", "li", "div", "ul", "ol", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}
)


class _TextExtractor(HTMLParser):
    """Thu text-node; chèn newline ở ranh giới tag khối. convert_charrefs=True (mặc định) tự giải mã
    entity (&amp; → &)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:  # noqa: ARG002
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(value: str | None) -> str:
    """HTML định dạng → plain-text gọn (mỗi dòng strip, bỏ dòng rỗng). Plain-text vào thẳng (idempotent:
    không tag → gần như nguyên trạng, chỉ chuẩn hóa khoảng trắng dòng)."""
    if not value:
        return ""
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    lines = (line.strip() for line in parser.text().splitlines())
    return "\n".join(line for line in lines if line)


def html_to_lines(value: str | None) -> list[str]:
    """HTML định dạng → list dòng plain-text (bỏ dòng rỗng) — cho ranker (yêu cầu dạng bullet)."""
    text = html_to_text(value)
    return [line for line in text.splitlines() if line.strip()] if text else []
