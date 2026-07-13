"""Template email CỐ ĐỊNH cho Scheduler (PRD §7.4). KHÔNG sinh bằng LLM — nhất quán + an toàn
pháp lý (cùng lý do bộ câu hỏi Screener cố định). Chỉ điền {candidate_name}, {job_title}.

An toàn: tên lấy từ CV (không tin cậy) → ESCAPE HTML trước khi nhúng vào thân email; tiêu đề
(email header) → bỏ newline chống header injection.
"""

from __future__ import annotations

import html as _html


def _esc(value: str | None, *, fallback: str) -> str:
    text = (value or "").strip()
    return _html.escape(text) if text else fallback


def _subject_safe(value: str | None, *, fallback: str) -> str:
    text = " ".join((value or "").split()) or fallback  # gộp whitespace/newline về 1 dòng
    return text


def _wrap(body: str) -> str:
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.6;'
        f'color:#0f172a;max-width:560px">{body}'
        '<p style="margin-top:24px">Trân trọng,<br/>Bộ phận Tuyển dụng</p></div>'
    )


def invite_email(candidate_name: str | None, job_title: str | None) -> tuple[str, str]:
    """Thư mời phỏng vấn — chúc mừng, nêu vị trí, nói sẽ liên hệ sắp lịch. Trả (subject, html)."""
    name = _esc(candidate_name, fallback="Ứng viên")
    title = _esc(job_title, fallback="vị trí ứng tuyển")
    subject = _subject_safe(
        f"Thư mời phỏng vấn — vị trí {job_title}" if job_title else "Thư mời phỏng vấn",
        fallback="Thư mời phỏng vấn",
    )
    html = _wrap(
        f"<p>Kính gửi {name},</p>"
        f"<p>Chúc mừng bạn! Sau khi xem xét hồ sơ, chúng tôi trân trọng mời bạn tham gia phỏng vấn "
        f"cho vị trí <strong>{title}</strong>.</p>"
        "<p>Bộ phận Tuyển dụng sẽ liên hệ với bạn trong thời gian sớm nhất để sắp xếp lịch phỏng "
        "vấn cụ thể. Mong sớm được trao đổi cùng bạn.</p>"
    )
    return subject, html


def rejection_email(candidate_name: str | None, job_title: str | None) -> tuple[str, str]:
    """Thư từ chối — cảm ơn, rất tiếc chưa phù hợp, chúc may mắn. Trả (subject, html)."""
    name = _esc(candidate_name, fallback="Ứng viên")
    title = _esc(job_title, fallback="vị trí ứng tuyển")
    subject = _subject_safe(
        f"Kết quả ứng tuyển — vị trí {job_title}" if job_title else "Kết quả ứng tuyển",
        fallback="Kết quả ứng tuyển",
    )
    html = _wrap(
        f"<p>Kính gửi {name},</p>"
        f"<p>Cảm ơn bạn đã quan tâm và ứng tuyển vị trí <strong>{title}</strong> tại công ty "
        "chúng tôi.</p>"
        "<p>Sau khi cân nhắc kỹ lưỡng, rất tiếc hồ sơ của bạn chưa phù hợp với yêu cầu vị trí ở "
        "thời điểm này. Chúng tôi sẽ lưu hồ sơ và liên hệ khi có cơ hội phù hợp hơn.</p>"
        "<p>Chúc bạn nhiều may mắn và thành công trên con đường sự nghiệp.</p>"
    )
    return subject, html
