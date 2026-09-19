"""Test slice 04 — email layer (template cố định + email_service qua Resend).

MOCK Resend (KHÔNG gửi thật, không tốn quota, không phụ thuộc mạng). Phủ: template điền đúng
vị trí + chào trung tính (KHÔNG chữ nào từ CV vào thư); ESCAPE HTML trong vị trí; email_service
yêu cầu API key + bọc lỗi Resend thành EmailError + truyền đúng from/to/subject/html.
"""

from __future__ import annotations

import pytest

from app.services import email_service
from app.services.email_templates import invite_email, rejection_email

# SCH-2: thư mời BẮT BUỘC kèm link tự đặt lịch (PRD §10b.1) — không còn thư mời "sẽ liên hệ sau".
_LINK = "http://localhost:3000/booking/tok123"


def _invite(title):
    return invite_email(title, booking_url=_LINK, deadline_text="72 giờ")


# ── template (cố định, điền placeholder) ─────────────────────────────────────


def test_invite_template_fills_title_and_neutral_greeting() -> None:
    subject, html = _invite("Kỹ sư Backend")
    assert _LINK in html  # thư mời PHẢI mang link, nếu không ứng viên mắc kẹt
    assert "Chào bạn," in html
    assert "Kỹ sư Backend" in html
    assert "Kỹ sư Backend" in subject  # subject nêu vị trí


def test_rejection_template_fills_title() -> None:
    subject, html = rejection_email("Kế toán")
    assert "Chào bạn," in html
    assert "Kế toán" in html
    assert subject  # có tiêu đề


def test_no_template_accepts_candidate_text() -> None:
    """Chống trạm phát thư (TN-5 P6): người nộp tự chọn địa chỉ nhận, nên KHÔNG chữ nào do họ kiểm
    soát được phép vào thư. Trước đây tên bóc từ CV (`parsed_data.full_name`) vào lời chào — nhét
    "full_name = <quảng cáo>" vào CV là có thư mang domain công ty gửi tới bất kỳ ai. Khoá ở CHỮ KÝ
    hàm: không còn tham số nào để nối tên lại vào."""
    import inspect

    from app.services import email_templates

    builders = [
        f for name, f in inspect.getmembers(email_templates, inspect.isfunction)
        if name.endswith("_email") and f.__module__ == email_templates.__name__
    ]
    assert len(builders) == 8
    for f in builders:
        params = set(inspect.signature(f).parameters)
        assert not params & {"candidate_name", "name", "full_name"}, f.__name__


def test_templates_escape_html_in_title() -> None:
    _, html = _invite("<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_templates_fallback_when_empty() -> None:
    subject, html = _invite("")
    assert "vị trí ứng tuyển" in html  # fallback vị trí
    assert subject  # vẫn có tiêu đề


def test_subject_is_single_line() -> None:
    # Tiêu đề dùng cho email header — không được chứa newline (chống header injection).
    subject, _ = _invite("Backend\r\nBcc: x@e.com")
    assert "\n" not in subject and "\r" not in subject


def test_interview_reminder_keeps_raw_url_for_text_part() -> None:
    """`html_to_text` BỎ href, chỉ giữ text-node. Thư nhắc trước buổi PV mà chỉ có <a> thì bản text
    mất nút huỷ — đúng lúc ứng viên cần nó nhất. Mọi template có link đều in cả URL thô."""
    from datetime import datetime, timedelta, timezone

    from app.core.html_text import html_to_text
    from app.services.email_templates import interview_reminder_email

    start = datetime(2026, 8, 20, 2, 0, tzinfo=timezone.utc)
    _, html = interview_reminder_email(
        "Backend", start_at=start, end_at=start + timedelta(hours=1),
        manage_url="http://x.test/booking/tok",
    )
    assert "http://x.test/booking/tok" in html_to_text(html)


# ── email_service (Resend) — mock, không gửi thật ────────────────────────────


async def test_send_email_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "resend_api_key", None)
    with pytest.raises(email_service.EmailError):
        await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")


async def test_send_email_wraps_resend_error(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    calls = {"n": 0}

    def boom(to: str, subject: str, html: str, text: str, attachments, idempotency_key: str) -> None:
        calls["n"] += 1
        raise RuntimeError("network down")

    monkeypatch.setattr(email_service, "_send_sync", boom)
    with pytest.raises(email_service.EmailError):
        await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")
    # RuntimeError KHÔNG phải ResendError nên `_classify` hỏng-mở về "retry" — lỗi không rõ hình
    # dạng thì thử lại là hành vi MONG MUỐN, không phải tai nạn. 4 = 1 lượt đầu + 3 lần thử lại.
    assert calls["n"] == 4


async def test_send_email_success_passes_params(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    captured: dict = {}

    def fake_send(
        to: str, subject: str, html: str, text: str, attachments, idempotency_key: str
    ) -> dict:
        captured.update(to=to, subject=subject, html=html, text=text, attachments=attachments)
        return {"id": "email_test"}

    monkeypatch.setattr(email_service, "_send_sync", fake_send)
    await email_service.send_email(to="a@e.com", subject="Mời", html="<p>xin chào</p>")
    assert captured == {
        "to": "a@e.com", "subject": "Mời", "html": "<p>xin chào</p>",
        "text": "xin chào",  # dẫn xuất từ html khi caller không tự truyền text
        "attachments": [],
    }


async def test_send_email_encodes_attachment_base64(monkeypatch) -> None:
    """SCH-2: `.ics` đính kèm phải tới Resend dưới dạng BASE64 — gửi bytes thô là Resend từ chối."""
    import base64

    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    captured: dict = {}

    def fake_send(
        to: str, subject: str, html: str, text: str, attachments, idempotency_key: str
    ) -> dict:
        captured["attachments"] = attachments
        return {"id": "email_test"}

    monkeypatch.setattr(email_service, "_send_sync", fake_send)
    await email_service.send_email(
        to="a@e.com", subject="s", html="<p>h</p>",
        attachments=[("phong-van.ics", b"BEGIN:VCALENDAR\r\n", "text/calendar")],
    )
    att = captured["attachments"][0]
    assert att["filename"] == "phong-van.ics"
    assert att["content_type"] == "text/calendar"
    assert base64.b64decode(att["content"]) == b"BEGIN:VCALENDAR\r\n"


async def test_send_email_returns_resend_id(monkeypatch) -> None:
    """ID trả về là KHOÁ ĐỐI CHIẾU với webhook — mất nó là mất khả năng phát hiện bounce."""
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email_service, "_send_sync", lambda *a: {"id": "email_xyz"})
    assert await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>") == "email_xyz"


async def test_send_email_tolerates_missing_id(monkeypatch) -> None:
    """Resend không trả id → thư VẪN coi là đã gửi (nó đã bay đi), chỉ mất đường theo dõi."""
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email_service, "_send_sync", lambda *a: {})
    assert await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>") is None


async def test_send_email_builds_resend_payload(monkeypatch) -> None:
    # Chạy _send_sync THẬT (chỉ mock resend.Emails.send) → khoá đúng shape payload Resend:
    # key `from`, `to` bọc thành list, VÀ `options.idempotency_key` có mặt (EMAIL-1 — chống thư
    # trùng khi retry, xem `_paced_send`). Bắt lỗi sai key ('from_') / to chưa bọc list / thiếu khoá.
    import resend

    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email_service.settings, "email_from", "onboarding@resend.dev")
    captured: dict = {}
    captured_options: dict = {}

    def fake_resend_send(params: dict, options: dict | None = None) -> dict:
        captured.update(params)
        captured_options.update(options or {})
        return {"id": "email_123"}

    monkeypatch.setattr(resend.Emails, "send", fake_resend_send)
    await email_service.send_email(to="a@e.com", subject="Mời", html="<p>hi</p>")

    assert captured["from"] == "onboarding@resend.dev"
    assert captured["to"] == ["a@e.com"]  # phải là list
    assert captured["subject"] == "Mời"
    assert captured["html"] == "<p>hi</p>"
    assert captured_options["idempotency_key"]  # non-rỗng — chống thư trùng khi retry


async def test_payload_includes_reply_to_and_text(monkeypatch) -> None:
    """Reply phải về hòm thư HR thật, và multipart (text + html) giảm tín hiệu spam."""
    import resend

    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email_service.settings, "email_reply_to", "tuyendung@congty.vn")
    monkeypatch.setattr(email_service, "_last_send_at", 0.0)
    captured: dict = {}
    # `options=None`: `_send_sync` thật (Task 3) gọi `resend.Emails.send(payload, options={...})`
    # để mang idempotency key qua retry — mock phải nhận tham số đó, không chỉ `p`.
    monkeypatch.setattr(
        resend.Emails, "send", lambda p, options=None: captured.update(p) or {"id": "e"}
    )

    await email_service.send_email(
        to="a@e.com", subject="Mời", html="<p>Xin chào</p><p>http://x.test/booking/tok</p>"
    )

    assert captured["reply_to"] == "tuyendung@congty.vn"
    assert "Xin chào" in captured["text"]
    assert "http://x.test/booking/tok" in captured["text"]  # LINK không được rơi mất ở bản text
    assert "<p>" not in captured["text"]


async def test_reply_to_omitted_when_not_configured(monkeypatch) -> None:
    import resend

    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email_service.settings, "email_reply_to", None)
    monkeypatch.setattr(email_service, "_last_send_at", 0.0)
    captured: dict = {}
    monkeypatch.setattr(
        resend.Emails, "send", lambda p, options=None: captured.update(p) or {"id": "e"}
    )
    await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")
    assert "reply_to" not in captured
