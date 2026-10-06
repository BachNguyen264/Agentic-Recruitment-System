"""Gửi lại thư khi dịch vụ gửi TỪ CHỐI (PRD FR-SCR-7, FR-NOTI-3) — phần THUẦN, không cần Postgres.

Vì sao có tính năng này (quan sát trên PROD 06/10/2026): sender rơi về `onboarding@resend.dev`, Resend
trả 403 cho mọi người nhận, thư sàng lọc không rời hệ thống — hồ sơ đứng ở `AWAITING_SCREENER` tới 72h
mà ứng viên không hề có link, và HR không có nút nào để cứu.

Phủ:
  1) `resendable_email`: thư nào gửi lại được ở trạng thái nào. Đây là hợp đồng mà NÚT trên UI dựa vào
     (AI_GUIDE: nút HR ánh xạ một điều kiện backend thì backend phải trả cờ đó) — sai ở đây là HR thấy
     nút rồi bấm ra 409, hoặc tệ hơn, gửi thư cho người đã báo spam.
  2) Route `POST /api/applications/{id}/email/resend`: nằm sau `require_hr`, và dịch `ResendError`
     ra đúng mã HTTP (409 = không có gì để gửi lại, 502 = dịch vụ gửi vẫn từ chối).

Hành vi trên DB thật (phiên mới, khoá, gỡ cờ trước khi gửi) ở `test_email_resend_db.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import settings
from app.core.database import get_session
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.application import Application
from app.models.hr_user import HrUser
from app.services import email_resend

_NOW = datetime.now(timezone.utc)


# ── 1) Thư nào gửi lại được ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "flags", "want"),
    [
        # Hai ca DUY NHẤT không còn đường cứu nào khác.
        ("AWAITING_SCREENER", ["email_send_failed"], "screener"),
        ("REJECTED", ["email_send_failed"], "reject"),
        # Cờ khác đi kèm không làm mất quyền gửi lại.
        ("AWAITING_SCREENER", ["cv_truncated", "email_send_failed"], "screener"),
        # Thư CHƯA hỏng → không có gì để "gửi lại" (đây không phải kênh nhắc tuỳ ý).
        ("AWAITING_SCREENER", [], None),
        ("REJECTED", [], None),
        # Bounce là chuyện KHÁC: địa chỉ chết thì gửi lại vào đúng địa chỉ đó là vô ích.
        ("AWAITING_SCREENER", ["email_bounced"], None),
        # Ứng viên đã báo spam → TUYỆT ĐỐI không gửi thêm (hại danh tiếng gửi của CẢ hệ thống).
        ("REJECTED", ["email_send_failed", "email_complained"], None),
        ("AWAITING_SCREENER", ["email_send_failed", "email_complained"], None),
        # Thư mời có đường cứu riêng sẵn (duyệt lại / gửi lại link đặt lịch) — không lặp đường thứ hai.
        ("PENDING_REVIEW", ["email_send_failed"], None),
        ("AWAITING_BOOKING", ["email_send_failed"], None),
        # Thư biên nhận (xác nhận lịch, nhắc PV): ứng viên ĐÃ thấy kết quả trên web.
        ("INTERVIEW_SCHEDULED", ["email_send_failed"], None),
    ],
)
def test_resendable_email(status: str, flags: list[str], want: str | None) -> None:
    assert email_resend.resendable_email(status, flags) == want


def test_resendable_email_tolerates_null_flags() -> None:
    """`uncertainty_flags` của hàng cũ có thể là NULL trong DB — không được nổ."""
    assert email_resend.resendable_email("AWAITING_SCREENER", None) is None


def test_pipeline_item_exposes_send_failure_but_not_the_flag_list() -> None:
    """Dòng "Đang chạy trực tiếp" trên dashboard từng ghi "Chờ ứng viên trả lời" cho đúng hồ sơ #244
    mà ứng viên chưa hề có link. Cần CỜ để nói thật — nhưng payload phải giữ cỡ cố định (endpoint
    này được hỏi lại vài giây một lần), nên chỉ lộ một bool, không lộ cả danh sách cờ."""
    from app.schemas.application import PipelineItem

    failed = PipelineItem.model_validate(
        _row(status="AWAITING_SCREENER", flags=["cv_truncated", "email_send_failed"])
    ).model_dump()
    assert failed["email_send_failed"] is True
    assert "uncertainty_flags" not in failed

    fine = PipelineItem.model_validate(_row(status="AWAITING_SCREENER", flags=None)).model_dump()
    assert fine["email_send_failed"] is False


def _row(*, status: str, flags: list[str] | None) -> Application:
    row = Application(job_id=7, applicant_email="ung-vien@example.com", status=status,
                      uncertainty_flags=flags)
    row.id = 1
    return row


# ── 2) Route ─────────────────────────────────────────────────────────────────


def _user() -> HrUser:
    u = HrUser(email="admin@ars.local", password_hash=hash_password("Correct1!"))
    u.id = 1
    return u


class _AuthSession:
    """Chỉ phục vụ `require_hr` (get HrUser). Nghiệp vụ được thay bằng stub ở từng test."""

    async def get(self, model, pk):  # noqa: ANN001
        return _user() if (model is HrUser and pk == 1) else None


def _client() -> httpx.AsyncClient:
    async def _fake_session():
        yield _AuthSession()

    app.dependency_overrides[get_session] = _fake_session
    transport = httpx.ASGITransport(app=app)  # KHÔNG chạy lifespan → không chạm Neon.
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _authed(c: httpx.AsyncClient) -> None:
    c.cookies.set(settings.auth_cookie_name, create_access_token("1"))


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _app_row(app_id: int) -> Application:
    row = Application(
        job_id=7, applicant_email="ung-vien@example.com", status="AWAITING_SCREENER",
        parsed_data={}, score=95.5, score_breakdown={}, uncertainty_flags=[],
    )
    row.id = app_id
    row.created_at = _NOW
    row.updated_at = _NOW
    return row


async def test_resend_route_requires_hr() -> None:
    """Đường này gửi email THẬT cho ứng viên — chưa đăng nhập phải bị chặn TRƯỚC handler."""
    async with _client() as c:
        r = await c.post("/api/applications/5/email/resend")
    assert r.status_code == 401


@pytest.mark.parametrize("code", [404, 409, 502])
async def test_resend_route_maps_resend_error_to_status(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    async def fake_resend(_session, application_id: int):  # noqa: ANN001
        raise email_resend.ResendError(f"lý do {application_id}", status_code=code)

    monkeypatch.setattr(email_resend, "resend_failed_email", fake_resend)
    async with _client() as c:
        _authed(c)
        r = await c.post("/api/applications/5/email/resend")
    assert r.status_code == code
    assert r.json()["detail"] == "lý do 5"


async def test_resend_route_returns_application_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resend(_session, application_id: int):  # noqa: ANN001
        return _app_row(application_id)

    monkeypatch.setattr(email_resend, "resend_failed_email", fake_resend)
    async with _client() as c:
        _authed(c)
        r = await c.post("/api/applications/5/email/resend")
    assert r.status_code == 200
    assert r.json()["id"] == 5
    assert r.json()["status"] == "AWAITING_SCREENER"
