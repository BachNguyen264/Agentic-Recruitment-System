"""Task 9 (EMAIL-1): `ApplicationRead.email_bounced`/`email_complained` — cờ HIỆN CHO HR trên
dashboard. Test THUẦN (không DB) vì hai trường này chỉ dẫn xuất từ `uncertainty_flags` đã có sẵn
trên object — đúng nếp `booking_no_slots`, không cần Postgres để chứng minh một phép suy ra danh
sách.

Đây chính là finding của review Task 7 (I6): cờ `email_bounced` từng VÔ HÌNH trên UI vì
`applications/page.tsx` chỉ hiện khi `status == PENDING_REVIEW` và banner ở trang chi tiết đòi
`escalation_reason` (nhánh "chỉ gắn cờ" không đặt). Test này khoá đúng MIẾNG BACKEND của việc sửa:
cờ phải tính ra True/False bất kể `status`/`escalation_reason` là gì.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.application import ApplicationRead

_NOW = datetime.now(timezone.utc)


def _read(uncertainty_flags: list[str], *, status: str = "PENDING_REVIEW") -> ApplicationRead:
    """Dựng một `ApplicationRead` hợp lệ tối thiểu — CHỈ đổi field đang kiểm (uncertainty_flags,
    status), còn lại là giá trị trung tính. `escalation_reason=None` CỐ Ý: đây chính là hình dạng
    dữ liệu thật của nhánh "chỉ gắn cờ" (bounce ở thư reject/biên nhận, mọi complaint) — cờ phải
    tính đúng dù KHÔNG có escalation_reason đi kèm.
    """
    return ApplicationRead(
        id=1,
        job_id=None,
        applicant_email="ung-vien@example.com",
        parsed_data={},
        score=None,
        score_breakdown={},
        status=status,
        confidence=None,
        uncertainty_flags=uncertainty_flags,
        escalation_reason=None,
        screener_sent_at=None,
        screener_deadline=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_email_bounced_true_when_flag_present() -> None:
    assert _read(["email_bounced"]).email_bounced is True


def test_email_bounced_false_when_flag_absent() -> None:
    assert _read([]).email_bounced is False
    assert _read(["rank_failed"]).email_bounced is False


def test_email_complained_true_when_flag_present() -> None:
    assert _read(["email_complained"]).email_complained is True


def test_email_complained_false_when_flag_absent() -> None:
    assert _read([]).email_complained is False


def test_bounced_and_complained_are_independent_flags() -> None:
    """Hai cờ RIÊNG (KHÔNG gộp) — một hồ sơ mang cả hai, hoặc chỉ một, phải tính đúng từng cái.
    Đây là chốt chặn cho việc "đừng gộp hai cái thành một nhãn" (yêu cầu global constraint)."""
    both = _read(["email_bounced", "email_complained"])
    assert both.email_bounced is True
    assert both.email_complained is True

    only_complained = _read(["email_complained"])
    assert only_complained.email_bounced is False
    assert only_complained.email_complained is True


def test_flag_ignores_status_and_escalation_reason() -> None:
    """Finding I6 (Task 7 review): banner CŨ đòi `status == PENDING_REVIEW` hoặc `escalation_reason`
    — cả hai đều SAI với nhánh "chỉ gắn cờ". Cờ mới phải tính đúng ở một hồ sơ ĐÃ QUYẾT (REJECTED)
    và KHÔNG có escalation_reason, đúng hình dạng dữ liệu thật của "thư từ chối bị bounce"."""
    row = _read(["email_bounced"], status="REJECTED")
    assert row.escalation_reason is None
    assert row.email_bounced is True


def test_reason_fields_default_to_none() -> None:
    """`email_bounce_reason`/`email_complaint_reason` CHỈ populate ở endpoint chi tiết (route tự
    gán) — construct trực tiếp qua schema (như test này) phải mặc định None, không phải chuỗi rỗng
    hay lỗi validate."""
    row = _read(["email_bounced", "email_complained"])
    assert row.email_bounce_reason is None
    assert row.email_complaint_reason is None
