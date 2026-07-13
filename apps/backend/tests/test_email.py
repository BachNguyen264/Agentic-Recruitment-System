"""Test slice 04 — email layer (template cố định + email_service qua Resend).

MOCK Resend (KHÔNG gửi thật, không tốn quota, không phụ thuộc mạng). Phủ: template điền đúng
tên+vị trí; ESCAPE HTML trong tên (chống injection từ nội dung CV vào email); email_service
yêu cầu API key + bọc lỗi Resend thành EmailError + truyền đúng from/to/subject/html.
"""

from __future__ import annotations

import pytest

from app.services import email_service
from app.services.email_templates import invite_email, rejection_email


# ── template (cố định, điền placeholder) ─────────────────────────────────────


def test_invite_template_fills_name_and_title() -> None:
    subject, html = invite_email("Trần Văn B", "Kỹ sư Backend")
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
    _, html = invite_email("<script>alert(1)</script>", "Dev")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_templates_fallback_when_empty() -> None:
    subject, html = invite_email("", "")
    assert "Ứng viên" in html  # fallback tên
    assert subject  # vẫn có tiêu đề


def test_subject_is_single_line() -> None:
    # Tiêu đề dùng cho email header — không được chứa newline (chống header injection).
    subject, _ = invite_email("A", "Backend\r\nBcc: x@e.com")
    assert "\n" not in subject and "\r" not in subject


# ── email_service (Resend) — mock, không gửi thật ────────────────────────────


async def test_send_email_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "resend_api_key", None)
    with pytest.raises(email_service.EmailError):
        await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")


async def test_send_email_wraps_resend_error(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")

    def boom(to: str, subject: str, html: str) -> None:
        raise RuntimeError("network down")

    monkeypatch.setattr(email_service, "_send_sync", boom)
    with pytest.raises(email_service.EmailError):
        await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")


async def test_send_email_success_passes_params(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    captured: dict = {}

    def fake_send(to: str, subject: str, html: str) -> None:
        captured.update(to=to, subject=subject, html=html)

    monkeypatch.setattr(email_service, "_send_sync", fake_send)
    await email_service.send_email(to="a@e.com", subject="Mời", html="<p>xin chào</p>")
    assert captured == {"to": "a@e.com", "subject": "Mời", "html": "<p>xin chào</p>"}
