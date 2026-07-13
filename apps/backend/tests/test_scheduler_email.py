"""Test slice 04 — scheduler.notify_decision gửi email THẬT (mock Resend).

Phủ: invite → gửi email mời (đúng recipient + template mời) + audit email_sent:invite;
reject → template từ chối + audit email_sent:reject; lỗi gửi → KHÔNG raise (nuốt có kiểm soát)
+ audit email_failed, quyết định vẫn giữ. KHÔNG gửi thật (monkeypatch email_service.send_email).
"""

from __future__ import annotations

import pytest

from app.agents.nodes import scheduler
from app.models.audit_log import AuditLog
from app.services import email_service


class FakeSession:
    """AsyncSession tối thiểu cho audit_service.record(commit=True): add/commit/refresh/flush."""

    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj) -> None:
        pass


def _audit_actions(session: FakeSession) -> list[str]:
    return [a.action for a in session.added if isinstance(a, AuditLog) and a.node == "scheduler"]


async def test_notify_invite_sends_invite_email(monkeypatch) -> None:
    captured: dict = {}

    async def fake_send(*, to: str, subject: str, html: str) -> None:
        captured.update(to=to, subject=subject, html=html)

    monkeypatch.setattr(scheduler.email_service, "send_email", fake_send)
    session = FakeSession()

    out = await scheduler.notify_decision(
        session, "invite", application_id=1, applicant_email="a@e.com",
        candidate_name="Nguyễn Văn A", job_title="Backend Intern",
    )

    assert out["email_sent"] is True
    assert captured["to"] == "a@e.com"
    assert "Nguyễn Văn A" in captured["html"] and "Backend Intern" in captured["html"]
    assert "mời" in captured["subject"].lower()
    assert "email_sent:invite" in _audit_actions(session)


async def test_notify_reject_sends_rejection_email(monkeypatch) -> None:
    captured: dict = {}

    async def fake_send(*, to: str, subject: str, html: str) -> None:
        captured.update(subject=subject, html=html)

    monkeypatch.setattr(scheduler.email_service, "send_email", fake_send)
    session = FakeSession()

    out = await scheduler.notify_decision(
        session, "reject", application_id=2, applicant_email="b@e.com",
        candidate_name="Trần Văn B", job_title="Kế toán",
    )

    assert out["email_sent"] is True
    assert "Kế toán" in captured["html"]
    assert "Kết quả ứng tuyển".lower() in captured["subject"].lower()
    assert "email_sent:reject" in _audit_actions(session)


async def test_notify_swallows_send_error(monkeypatch) -> None:
    async def boom(*, to: str, subject: str, html: str) -> None:
        raise email_service.EmailError("Resend down")

    monkeypatch.setattr(scheduler.email_service, "send_email", boom)
    session = FakeSession()

    # KHÔNG raise — quyết định 03b đã commit, email lỗi không được làm sập luồng.
    out = await scheduler.notify_decision(
        session, "invite", application_id=3, applicant_email="c@e.com",
        candidate_name="X", job_title="Y",
    )

    assert out["email_sent"] is False
    assert "email_failed" in _audit_actions(session)
