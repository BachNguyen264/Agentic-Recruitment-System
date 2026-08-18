"""Test EMAIL-1 — bảng lưu vết giao hàng + thứ bậc trạng thái.

Không cần DB: đây là bất biến của MÔ HÌNH (từ vựng `kind` + luật chuyển trạng thái). Phần chạm
DB thật nằm ở `test_webhook_resend.py` (gated).
"""

from __future__ import annotations

import pytest

from app.agents.nodes import scheduler
from app.models.audit_log import AuditLog
from app.models.email_delivery import (
    _RANK,
    DeliveryStatus,
    EmailDelivery,
    EmailKind,
    outranks,
)


def test_kind_values_match_scheduler_modes() -> None:
    """`kind` PHẢI là đúng chuỗi `mode` mà scheduler dùng — audit ghi `email_sent:{mode}`, nên đặt
    tên thứ hai là tạo hai từ vựng cho một thứ và không đối soát audit ↔ delivery được nữa."""
    assert {k.value for k in EmailKind} == {
        "invite", "reject", "screener", "screener_reminder",
        "booking_confirmed", "interview_reminder", "booking_reminder", "booking_cancelled",
        "submission_ack",
    }


def test_delivered_outranks_sent() -> None:
    assert outranks(DeliveryStatus.DELIVERED.value, DeliveryStatus.SENT.value)


def test_bounce_can_arrive_after_delivered() -> None:
    """Máy chủ nhận báo lại bounce SAU khi đã nhận thư — chuyện thật, phải áp được."""
    assert outranks(DeliveryStatus.BOUNCED.value, DeliveryStatus.DELIVERED.value)


def test_late_delivered_never_erases_bounce() -> None:
    assert not outranks(DeliveryStatus.DELIVERED.value, DeliveryStatus.BOUNCED.value)


def test_duplicate_event_is_noop() -> None:
    """Resend gửi lại sự kiện trùng là bình thường — cùng hạng thì KHÔNG áp lại (idempotent)."""
    for s in DeliveryStatus:
        assert not outranks(s.value, s.value)


def test_every_status_has_a_rank() -> None:
    """Thiếu MỘT hạng là sự kiện đó không bao giờ ghi được vào cột, mà KHÔNG lỗi nào bật ra.

    `_RANK.get(x, -1)` cho mã lạ trả -1, nên `outranks` luôn False. Test trên
    (`test_duplicate_event_is_noop`) KHÔNG bắt được vì nó so một giá trị với CHÍNH NÓ — vẫn False
    dù thành viên đó có mặt trong `_RANK` hay không. Đây là lưới cho cái hố đó.
    """
    for s in DeliveryStatus:
        assert s.value in _RANK, f"{s.value} thiếu trong _RANK — sự kiện sẽ bị bỏ qua trong im lặng"


def test_send_failure_outranks_sent_and_delivered() -> None:
    """`email.failed` phải ghi đè được `SENT` (đường thường) và cả `DELIVERED` tới muộn.

    Resend KHÔNG bảo đảm thứ tự sự kiện. Hai cái này mâu thuẫn nhau về mặt vật lý, nên khi cả hai
    cùng tới thì tin cái XẤU — bỏ sót một cảnh báo tốn kém hơn nhiều so với giữ thừa một cảnh báo.
    """
    assert outranks(DeliveryStatus.FAILED.value, DeliveryStatus.SENT.value)
    assert outranks(DeliveryStatus.FAILED.value, DeliveryStatus.DELIVERED.value)
    assert not outranks(DeliveryStatus.DELIVERED.value, DeliveryStatus.FAILED.value)


def test_bounce_outranks_send_failure() -> None:
    """Hai tín hiệu xấu loại trừ nhau; nếu vẫn cùng tới thì bounce thắng vì nó GIÀU thông tin hơn
    (phản hồi SMTP thật, nói về chính địa chỉ ứng viên) — `failed` thường nói về phía TA."""
    assert outranks(DeliveryStatus.BOUNCED.value, DeliveryStatus.FAILED.value)
    assert not outranks(DeliveryStatus.FAILED.value, DeliveryStatus.BOUNCED.value)


def test_unknown_status_never_applied() -> None:
    """Mã lạ (Resend thêm sự kiện mới) KHÔNG được lọt vào cột status."""
    assert not outranks("OPENED", DeliveryStatus.SENT.value)


def test_model_column_default_is_sent() -> None:
    """Cột `status` phải mặc định SENT ở TẦNG MODEL (không phải chỉ ở `_dispatch`): mọi đường ghi
    một hàng giao hàng đều bắt đầu từ 'đã gửi', và webhook chỉ nâng cấp lên từ đó."""
    assert EmailDelivery.__table__.c.status.default.arg == DeliveryStatus.SENT.value
    assert EmailDelivery.__table__.c.resend_email_id.unique is True
    assert EmailDelivery.__table__.c.bounce_reason.nullable is True


# ── Task 2: _dispatch ghi hàng email_delivery cho mỗi thư gửi THÀNH CÔNG ─────


class FakeSession:
    """AsyncSession tối thiểu — cùng khuôn với tests/test_scheduler_email.py."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def refresh(self, _obj) -> None:
        pass


def _deliveries(session: FakeSession) -> list[EmailDelivery]:
    return [o for o in session.added if isinstance(o, EmailDelivery)]


async def _async_value(value):  # noqa: ANN001, ANN202
    return value


async def test_dispatch_records_delivery_row(monkeypatch) -> None:
    async def fake_send(*, to, subject, html, attachments=None):  # noqa: ANN001, ANN003
        return "email_abc123"

    monkeypatch.setattr(scheduler.email_service, "send_email", fake_send)
    session = FakeSession()

    out = await scheduler.notify_decision(
        session, "invite", application_id=42, applicant_email="a@e.com",
        candidate_name="A", job_title="Backend",
        booking_url="http://localhost:3000/booking/tok", deadline_text="72 giờ",
    )

    assert out["email_sent"] is True
    rows = _deliveries(session)
    assert len(rows) == 1
    assert rows[0].resend_email_id == "email_abc123"
    assert rows[0].kind == EmailKind.INVITE.value
    assert rows[0].application_id == 42
    assert rows[0].recipient == "a@e.com"
    assert rows[0].status == DeliveryStatus.SENT.value


async def test_dispatch_skips_delivery_row_when_no_email_id(monkeypatch) -> None:
    """Không có id thì webhook không bao giờ tra được — hàng đó vô dụng, đừng ghi rác."""

    async def fake_send(*, to, subject, html, attachments=None):  # noqa: ANN001, ANN003
        return None

    monkeypatch.setattr(scheduler.email_service, "send_email", fake_send)
    session = FakeSession()
    await scheduler.notify_decision(
        session, "reject", application_id=43, applicant_email="b@e.com",
        candidate_name="B", job_title="Kế toán",
    )
    assert _deliveries(session) == []
    assert any(isinstance(o, AuditLog) for o in session.added)  # audit VẪN ghi


async def test_dispatch_records_no_row_when_send_fails(monkeypatch) -> None:
    async def boom(*, to, subject, html, attachments=None):  # noqa: ANN001, ANN003
        raise scheduler.email_service.EmailError("Resend down")

    monkeypatch.setattr(scheduler.email_service, "send_email", boom)
    session = FakeSession()
    out = await scheduler.notify_decision(
        session, "reject", application_id=44, applicant_email="c@e.com",
        candidate_name="C", job_title="X",
    )
    assert out["email_sent"] is False
    assert _deliveries(session) == []


async def test_dispatch_uses_mode_verbatim_as_kind(monkeypatch) -> None:
    """Bất biến từ vựng, kiểm qua ĐƯỜNG THẬT: `kind` của hàng ghi ra phải khớp hậu tố của dòng audit
    `email_sent:{mode}`. Hai giá trị đó lệch nhau là lúc audit và vết giao hàng thôi đối soát được."""
    monkeypatch.setattr(
        scheduler.email_service, "send_email",
        lambda **_kw: _async_value("e_mode"),  # xem helper bên dưới
    )
    session = FakeSession()
    await scheduler.notify_screener(
        session, application_id=7, applicant_email="a@e.com", candidate_name="A",
        job_title="B", form_url="http://x.test/screening/t", deadline_text="72 giờ",
        reminder=True,
    )
    kind = _deliveries(session)[0].kind
    actions = [a.action for a in session.added if isinstance(a, AuditLog)]
    assert f"email_sent:{kind}" in actions
    assert kind == EmailKind.SCREENER_REMINDER.value


# ── Giữ nhịp + retry (EMAIL-1 §3.3) ──────────────────────────────────────────
from app.services import email_service


@pytest.fixture
def paced(monkeypatch):
    """Thời gian + sleep được TIÊM VÀO (như RateLimiter của hardening) — test không ngủ thật."""
    clock = {"t": 1000.0}
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(email_service, "_monotonic", lambda: clock["t"])
    monkeypatch.setattr(email_service, "_sleep", fake_sleep)
    monkeypatch.setattr(email_service, "_last_send_at", 0.0)
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email_service.settings, "email_min_interval_ms", 550)
    monkeypatch.setattr(email_service.settings, "email_max_retries", 3)
    return slept


async def test_consecutive_sends_keep_min_interval(paced, monkeypatch) -> None:
    """Ba lượt gửi liên tiếp phải cách nhau ≥ EMAIL_MIN_INTERVAL_MS — sweep bắn cả cụm là chuyện thường."""
    monkeypatch.setattr(email_service, "_send_sync", lambda *a: {"id": "e"})
    for _ in range(3):
        await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")
    # lượt đầu không phải chờ; hai lượt sau mỗi lượt ngủ đúng 0.55s
    assert [round(s, 3) for s in paced if s > 0] == [0.55, 0.55]


def _resend_error(code, error_type):  # noqa: ANN001, ANN202
    from resend.exceptions import ResendError

    return ResendError(code=code, error_type=error_type, message="x", suggested_action="")


async def test_retries_on_burst_rate_limit_then_succeeds(paced, monkeypatch) -> None:
    calls = {"n": 0}

    def flaky(*_a):  # noqa: ANN002, ANN202
        calls["n"] += 1
        if calls["n"] == 1:
            raise _resend_error("429", "rate_limit_exceeded")
        return {"id": "e_ok"}

    monkeypatch.setattr(email_service, "_send_sync", flaky)
    assert await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>") == "e_ok"
    assert calls["n"] == 2


async def test_failed_attempt_still_paces_next_retry(paced, monkeypatch) -> None:
    """Khoá bất biến "mốc thời gian phải cập nhật ở nhánh LỖI" (review độc lập bắt bằng mutation:
    xoá dòng `_last_send_at = _monotonic()` trong `except` của `_paced_send` → test cũ vẫn xanh hết,
    vì backoff của lượt lỗi đầu tiên thường ĐÃ đủ dài để lấn hết khoảng giữ nhịp một cách tình cờ).

    Ép `_backoff_seconds` về một giá trị CỐ ĐỊNH NHỎ HƠN khoảng giữ nhịp (0.1s < 0.55s) để hai cơ
    chế — "chờ backoff" và "chờ đủ giữ nhịp kể từ lượt chạm Resend gần nhất" — tách bạch được trong
    danh sách `slept`: đúng thì có CẢ HAI (backoff 0.1s RỒI giữ-nhịp 0.45s còn thiếu, vì lượt lỗi
    ĐÃ tính là "chạm Resend" lúc 1000.0 + 0.0, backoff xong đồng hồ mới ở 1000.1, còn thiếu 0.45s
    mới đủ 0.55s kể từ lượt lỗi). Mất dòng cập nhật mốc thì `_last_send_at` bị đóng băng ở giá trị
    trước lượt gọi này (do `paced` đặt = 0.0), nên `wait` ở vòng lặp kế tiếp âm rất sâu → CHỈ còn
    một khoảng ngủ (0.1s backoff), thiếu hẳn khoảng giữ-nhịp 0.45s — assertion dưới đây ĐỎ."""
    monkeypatch.setattr(email_service, "_backoff_seconds", lambda attempt: 0.1)
    calls = {"n": 0}

    def flaky(*_a):  # noqa: ANN002, ANN202
        calls["n"] += 1
        if calls["n"] == 1:
            raise _resend_error("429", "rate_limit_exceeded")
        return {"id": "e_ok"}

    monkeypatch.setattr(email_service, "_send_sync", flaky)
    assert await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>") == "e_ok"
    assert [round(s, 3) for s in paced] == [0.1, 0.45]


async def test_does_not_retry_permanent_error(paced, monkeypatch) -> None:
    """400 = địa chỉ sai định dạng. Thử lại 3 lần chỉ tốn 3 lượt gọi và vẫn hỏng y hệt."""
    calls = {"n": 0}

    def bad(*_a):  # noqa: ANN002, ANN202
        calls["n"] += 1
        raise _resend_error("400", "validation_error")

    monkeypatch.setattr(email_service, "_send_sync", bad)
    with pytest.raises(email_service.EmailError):
        await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")
    assert calls["n"] == 1


async def test_daily_quota_is_distinguishable_and_not_retried(paced, monkeypatch) -> None:
    """Cạn quota ngày là tài nguyên DÙNG CHUNG cạn: mọi ứng viên khác cũng câm. Phải phân biệt được."""
    calls = {"n": 0}

    def quota(*_a):  # noqa: ANN002, ANN202
        calls["n"] += 1
        raise _resend_error("429", "daily_quota_exceeded")

    monkeypatch.setattr(email_service, "_send_sync", quota)
    with pytest.raises(email_service.EmailQuotaExhausted):
        await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")
    assert calls["n"] == 1


async def test_gives_up_after_max_retries(paced, monkeypatch) -> None:
    calls = {"n": 0}

    def always_429(*_a):  # noqa: ANN002, ANN202
        calls["n"] += 1
        raise _resend_error("429", "rate_limit_exceeded")

    monkeypatch.setattr(email_service, "_send_sync", always_429)
    with pytest.raises(email_service.EmailError):
        await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")
    assert calls["n"] == 4  # 1 lượt đầu + 3 lần thử lại


# ── Idempotency key khi retry (review độc lập I3) ────────────────────────────
# Resend gói MỌI lỗi transport (timeout đọc, mất kết nối — resend/request.py) thành lỗi được
# `_classify` xếp "retry được". Nếu timeout xảy ra SAU KHI Resend đã nhận thư, thử lại KHÔNG
# idempotency key sẽ tạo ra một lá thư THỨ HAI — ứng viên nhận hai thư mời/từ chối, và mỗi bản
# trùng còn đốt thêm quota của kênh email DUY NHẤT của cả hệ thống. Rủi ro này KHÔNG tồn tại trước
# khi task này thêm retry (trước đây một lượt lỗi là lỗi luôn, không có lượt hai).


async def test_retry_reuses_same_idempotency_key(paced, monkeypatch) -> None:
    """Mọi lần thử của CÙNG một lượt gửi LOGIC (429 rồi thành công) phải mang ĐÚNG MỘT khoá —
    khoá sinh MỘT LẦN trước vòng retry, không phải mỗi lần thử một khoá riêng."""
    keys_seen: list[str] = []
    calls = {"n": 0}

    def flaky(to, subject, html, text, attachments, idempotency_key):  # noqa: ANN001, ANN202
        keys_seen.append(idempotency_key)
        calls["n"] += 1
        if calls["n"] == 1:
            raise _resend_error("429", "rate_limit_exceeded")
        return {"id": "e_ok"}

    monkeypatch.setattr(email_service, "_send_sync", flaky)
    assert await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>") == "e_ok"
    assert calls["n"] == 2
    assert len(keys_seen) == 2
    assert keys_seen[0] == keys_seen[1]  # cùng khoá cho cả hai lần thử của MỘT lượt gửi


async def test_separate_sends_get_different_idempotency_keys(paced, monkeypatch) -> None:
    """Hai lượt gửi LOGIC riêng biệt (hai email khác nhau) phải mang khoá KHÁC nhau — nếu không,
    Resend sẽ coi lượt gửi thứ hai là bản lặp của lượt thứ nhất và từ chối gửi nó."""
    keys_seen: list[str] = []

    def ok(to, subject, html, text, attachments, idempotency_key):  # noqa: ANN001, ANN202
        keys_seen.append(idempotency_key)
        return {"id": "e"}

    monkeypatch.setattr(email_service, "_send_sync", ok)
    await email_service.send_email(to="a@e.com", subject="s1", html="<p>h1</p>")
    await email_service.send_email(to="a@e.com", subject="s2", html="<p>h2</p>")
    assert len(keys_seen) == 2
    assert keys_seen[0] != keys_seen[1]


async def test_dispatch_does_not_touch_db_before_sending(monkeypatch) -> None:
    """Retry kéo dài lượt gửi tới ~8s. Nếu `_dispatch` chạm DB TRƯỚC khi gửi thì nó mở một
    transaction và ôm một connection của pool suốt ngần ấy — Load boundary cấm (pool chỉ 15).
    Khoá bằng test vì đây là loại lỗi không có triệu chứng cho tới lúc tải cao."""
    touched_before_send: list[str] = []
    sent = {"done": False}

    class TrackingSession(FakeSession):
        def add(self, obj) -> None:
            if not sent["done"]:
                touched_before_send.append(type(obj).__name__)
            super().add(obj)

        async def flush(self) -> None:
            if not sent["done"]:
                touched_before_send.append("flush")

    async def fake_send(*, to, subject, html, attachments=None):  # noqa: ANN001, ANN003
        sent["done"] = True
        return "e_1"

    monkeypatch.setattr(scheduler.email_service, "send_email", fake_send)
    await scheduler.notify_decision(
        TrackingSession(), "reject", application_id=1, applicant_email="a@e.com",
        candidate_name="A", job_title="B",
    )
    assert touched_before_send == []


async def test_dispatch_commits_exactly_once_after_adding_delivery_row(monkeypatch) -> None:
    """Bất biến "hàng EmailDelivery và dòng AuditLog nằm CÙNG MỘT transaction" (Task 2) không có
    test nào canh trực tiếp: `FakeSession.commit()` gốc không đếm số lần gọi, nên một cài đặt lỡ
    tách delivery-row và audit ra HAI lượt commit riêng vẫn pass y hệt các test khác ở trên. Test
    này khoá bất biến đó: một lượt gửi thành công phải ⇒ đúng MỘT lần `commit()`, và hàng
    `EmailDelivery` phải được `add()` TRƯỚC lần commit đó (không phải add sau, hoặc add rồi commit
    hai lần)."""
    commit_count = {"n": 0}
    added_before_commit: list[str] = []

    class TrackingSession(FakeSession):
        def add(self, obj) -> None:
            if commit_count["n"] == 0:
                added_before_commit.append(type(obj).__name__)
            super().add(obj)

        async def commit(self) -> None:
            commit_count["n"] += 1
            await super().commit()

    async def fake_send(*, to, subject, html, attachments=None):  # noqa: ANN001, ANN003
        return "e_commit"

    monkeypatch.setattr(scheduler.email_service, "send_email", fake_send)
    session = TrackingSession()
    out = await scheduler.notify_decision(
        session, "reject", application_id=1, applicant_email="a@e.com",
        candidate_name="A", job_title="B",
    )

    assert out["email_sent"] is True
    assert commit_count["n"] == 1
    assert "EmailDelivery" in added_before_commit
