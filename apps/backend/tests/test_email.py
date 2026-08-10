"""Test slice 04 — email layer (template cố định + email_service qua Resend).

MOCK Resend (KHÔNG gửi thật, không tốn quota, không phụ thuộc mạng). Phủ: template điền đúng
tên+vị trí; ESCAPE HTML trong tên (chống injection từ nội dung CV vào email); email_service
yêu cầu API key + bọc lỗi Resend thành EmailError + truyền đúng from/to/subject/html.
"""

from __future__ import annotations

import pytest

from app.services import email_service
from app.services.email_templates import booking_confirmed_email, invite_email, rejection_email

# SCH-2: thư mời BẮT BUỘC kèm link tự đặt lịch (PRD §10b.1) — không còn thư mời "sẽ liên hệ sau".
_LINK = "http://localhost:3000/booking/tok123"


def _invite(name, title):
    return invite_email(name, title, booking_url=_LINK, deadline_text="72 giờ")


# ── template (cố định, điền placeholder) ─────────────────────────────────────


def test_invite_template_fills_name_and_title() -> None:
    subject, html = _invite("Trần Văn B", "Kỹ sư Backend")
    assert _LINK in html  # thư mời PHẢI mang link, nếu không ứng viên mắc kẹt
    assert "Trần Văn B" in html
    assert "Kỹ sư Backend" in html
    assert "Kỹ sư Backend" in subject  # subject nêu vị trí


def test_rejection_template_fills_name_and_title() -> None:
    subject, html = rejection_email("Nguyễn Thị C", "Kế toán")
    assert "Nguyễn Thị C" in html
    assert "Kế toán" in html
    assert subject  # có tiêu đề


def test_templates_escape_html_in_name() -> None:
    # Tên lấy từ CV (không tin cậy) — phải escape để không chèn HTML/script vào email.
    _, html = _invite("<script>alert(1)</script>", "Dev")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_templates_fallback_when_empty() -> None:
    subject, html = _invite("", "")
    assert "Ứng viên" in html  # fallback tên
    assert subject  # vẫn có tiêu đề


def test_subject_is_single_line() -> None:
    # Tiêu đề dùng cho email header — không được chứa newline (chống header injection).
    subject, _ = _invite("A", "Backend\r\nBcc: x@e.com")
    assert "\n" not in subject and "\r" not in subject


# ── email_service (Resend) — mock, không gửi thật ────────────────────────────


async def test_send_email_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "resend_api_key", None)
    with pytest.raises(email_service.EmailError):
        await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")


async def test_send_email_wraps_resend_error(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")

    def boom(to: str, subject: str, html: str, attachments) -> None:
        raise RuntimeError("network down")

    monkeypatch.setattr(email_service, "_send_sync", boom)
    with pytest.raises(email_service.EmailError):
        await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")


async def test_send_email_success_passes_params(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    captured: dict = {}

    def fake_send(to: str, subject: str, html: str, attachments) -> dict:
        captured.update(to=to, subject=subject, html=html, attachments=attachments)
        return {"id": "email_test"}

    monkeypatch.setattr(email_service, "_send_sync", fake_send)
    await email_service.send_email(to="a@e.com", subject="Mời", html="<p>xin chào</p>")
    assert captured == {
        "to": "a@e.com", "subject": "Mời", "html": "<p>xin chào</p>", "attachments": [],
    }


async def test_send_email_encodes_attachment_base64(monkeypatch) -> None:
    """SCH-2: `.ics` đính kèm phải tới Resend dưới dạng BASE64 — gửi bytes thô là Resend từ chối."""
    import base64

    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    captured: dict = {}

    def fake_send(to: str, subject: str, html: str, attachments) -> dict:
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
    # key `from`, `to` bọc thành list. Bắt lỗi sai key ('from_') / to chưa bọc list.
    import resend

    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email_service.settings, "email_from", "onboarding@resend.dev")
    captured: dict = {}

    def fake_resend_send(params: dict) -> dict:
        captured.update(params)
        return {"id": "email_123"}

    monkeypatch.setattr(resend.Emails, "send", fake_resend_send)
    await email_service.send_email(to="a@e.com", subject="Mời", html="<p>hi</p>")

    assert captured["from"] == "onboarding@resend.dev"
    assert captured["to"] == ["a@e.com"]  # phải là list
    assert captured["subject"] == "Mời"
    assert captured["html"] == "<p>hi</p>"
