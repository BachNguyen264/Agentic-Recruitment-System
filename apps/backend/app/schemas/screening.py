"""Schemas Screener magic-link (08b) — projection AN TOÀN cho ứng viên guest (PRD §7.3, §10, §12.2).

BẢO MẬT: endpoint công khai CHỈ trả câu hỏi + tiêu đề JD. Trường không khai báo ở đây KHÔNG được
serialize (như PublicJobRead) → KHÔNG lộ rubric/gate/điểm/parsed_data/trạng thái nội bộ.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


class PublicScreeningRead(BaseModel):
    """GET /public/screening/{token}: CHỈ tiêu đề JD + bộ câu hỏi (ảnh chụp lúc gửi)."""

    job_title: str
    questions: list[str]


# Mỗi câu trả lời tối đa 5000 ký tự (chống input phình / DoS lưu trữ); tối đa 50 câu.
_Answer = Annotated[str, StringConstraints(max_length=5000)]


class ScreeningSubmit(BaseModel):
    """Body POST: câu trả lời theo THỨ TỰ câu hỏi. Cắt số lượng + độ dài ở biên (defense-in-depth;
    service còn cắt lại khi lưu)."""

    answers: list[_Answer] = Field(default_factory=list, max_length=50)


class ScreeningSubmitResponse(BaseModel):
    status: str
    message: str
