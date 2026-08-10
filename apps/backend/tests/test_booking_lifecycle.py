"""Test SCH-3 — vòng đời lịch phỏng vấn. PRD §10b.6, §12.4 FR-BOOK-3/4/6, §13.

Mock email/DB (KHÔNG gửi thật, KHÔNG chạm Neon). Phủ những quyết định dễ hỏng NHẤT của lát này:

  A) **KHÔNG auto-reject ở bất kỳ nhánh nào** — hết hạn/huỷ đều về NGƯỜI. Đây là bất biến xuyên dự
     án (im lặng ≠ từ chối), nên nó có test riêng chứ không nằm ké trong test trạng thái.
  B) **Huỷ KHÔNG gia hạn TTL** — `expires_at` phải y nguyên sau khi huỷ. Gia hạn ở đây là mở cửa cho
     vòng lặp đặt-huỷ-đặt không điểm dừng.
  C) **Nhắc một lần** — mốc thời gian được ghi + commit TRƯỚC khi gửi (at-most-once, như 08c).
  D) **Token cũ không lật ngược quyết định người** — huỷ khi hồ sơ đã rời `INTERVIEW_SCHEDULED` là
     no-op 200, không phải một lượt ghi đè (bài học lỗi #6 của SCH-2).
  E) **Hết khung giờ ghi cờ RIÊNG** và cờ đó **tự tắt** khi có slot trở lại.

Phần cần Postgres thật (truy vấn sweep, khung giờ nhả ra có hiện lại cho người khác không, hai lượt
huỷ đồng thời) nằm ở `test_booking_db.py` sau cờ `RUN_BOOKING_IT=1`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.application import Application, ApplicationStatus
from app.models.audit_log import AuditLog
from app.models.booking import BookingSession, BookingStatus, InterviewBooking
from app.services import booking_flow, booking_lifecycle, booking_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _EmptyResult:
    """Kết quả rỗng. `scalar()` trả None = "hồ sơ KHÔNG có lịch đã chốt" — đúng tiền đề của các test
    hết-hạn ở đây (chốt chặn "đang có BOOKED thì đừng hạ" được đo riêng trên DB thật)."""

    rowcount = 0

    def scalar(self):  # noqa: ANN201
        return None

    def scalar_one_or_none(self):  # noqa: ANN201
        return None

    def scalars(self):  # noqa: ANN201
        return self

    def first(self):  # noqa: ANN201
        return None

    def all(self) -> list:
        return []


class FakeSession:
    """AsyncSession tối thiểu + GHI LẠI THỨ TỰ thao tác.

    `trace` là thứ làm nên giá trị của file test này: phần lớn bất biến ở đây là bất biến về THỨ TỰ
    ("ghi mốc rồi mới gửi", "DB rồi mới email"), mà khẳng định trạng thái cuối cùng thì không phân
    biệt được thứ tự nào đã xảy ra.
    """

    def __init__(self, rows: dict | None = None) -> None:
        self._rows = rows or {}
        self.added: list = []
        self.commits = 0
        self.trace: list[str] = []

    async def get(self, model, pk):  # noqa: ANN001
        return self._rows.get((model, pk))

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def execute(self, *_a, **_kw):  # noqa: ANN201
        return _EmptyResult()

    async def commit(self) -> None:
        self.commits += 1
        self.trace.append("commit")

    async def rollback(self) -> None:
        self.trace.append("rollback")

    async def refresh(self, _obj) -> None:
        pass

    def audits(self) -> list[tuple[str, str]]:
        return [(a.node, a.action) for a in self.added if isinstance(a, AuditLog)]


def _app(status: str = ApplicationStatus.INTERVIEW_SCHEDULED.value) -> Application:
    row = Application(id=5, applicant_email="me@e.com", job_id=2, status=status)
    row.parsed_data = {"full_name": "Nguyễn Văn A"}
    row.uncertainty_flags = []
    return row


def _session_row(*, expires_in_hours: float = 40, booked: bool = True) -> BookingSession:
    row = BookingSession(
        id=7, application_id=5, token="tok-abc",
        expires_at=_now() + timedelta(hours=expires_in_hours),
    )
    row.booked_at = _now() if booked else None
    row.cancelled_at = None
    row.reminded_at = None
    row.no_slots_at = None
    return row


def _booking(bid: int = 11) -> InterviewBooking:
    start = _now() + timedelta(days=3)
    return InterviewBooking(
        id=bid, application_id=5, start_at=start, end_at=start + timedelta(hours=1),
        status=BookingStatus.BOOKED.value,
    )


def _capture_cancel_email(monkeypatch) -> dict:
    seen: dict = {}

    async def fake(_s, **kw):  # noqa: ANN001
        seen.update(kw)
        return {"mode": "booking_cancelled", "email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_booking_cancelled", fake)
    return seen


def _stub_cancel_booked(monkeypatch, booking: InterviewBooking | None) -> None:
    async def fake(_s, _aid, **_kw):  # noqa: ANN001
        if booking is not None:
            booking.status = BookingStatus.CANCELLED.value
        return booking

    monkeypatch.setattr(booking_service, "cancel_booked", fake)


# ── A) Hết hạn liên kết: về NGƯỜI, KHÔNG auto-reject ─────────────────────────────────────


async def test_timeout_goes_to_pending_review_never_rejected(monkeypatch) -> None:
    """Bất biến xuyên dự án: im lặng của ứng viên KHÔNG phải lời từ chối (đối xứng FR-SCR-3)."""
    app_row = _app(ApplicationStatus.AWAITING_BOOKING.value)
    sess_row = _session_row(expires_in_hours=-1, booked=False)
    session = FakeSession({(Application, 5): app_row})
    killed: list[int] = []
    monkeypatch.setattr(
        booking_service, "cancel_sessions",
        lambda _s, aid, **_kw: _async(killed.append(aid) or 1),
    )

    await booking_lifecycle.handle_booking_timeout(session, sess_row)

    assert app_row.status == ApplicationStatus.PENDING_REVIEW.value
    assert app_row.status != ApplicationStatus.REJECTED.value
    assert "booking_no_response" in app_row.uncertainty_flags
    assert app_row.escalation_reason  # HR phải đọc được VÌ SAO ca này quay lại hàng chờ
    # Huỷ MỌI liên kết còn sống, không riêng phiên đang xử: một phiên mồ côi còn sống là còn đường
    # cho token cũ lật ngược quyết định vừa ghi (lỗi #6 SCH-2, phía hết hạn).
    assert killed == [5]
    assert ("scheduler", "booking_no_response") in session.audits()


async def test_timeout_blames_the_calendar_when_there_were_no_slots(monkeypatch) -> None:
    """Ứng viên mở link mà lịch trống rỗng thì họ KHÔNG có gì để bấm.

    Dán "không phản hồi" lên họ chính là cái đổ-lỗi-nhầm-người FR-BOOK-6 sinh ra để chặn — và tệ hơn,
    nó XOÁ luôn nhãn "hết khung giờ" (vì `no_slot_application_ids` lọc `cancelled_at IS NULL`), nên
    bằng chứng duy nhất về lỗi của hệ thống biến mất đúng lúc HR cần nó."""
    app_row = _app(ApplicationStatus.AWAITING_BOOKING.value)
    sess_row = _session_row(expires_in_hours=-1, booked=False)
    sess_row.no_slots_at = _now()
    session = FakeSession({(Application, 5): app_row})
    monkeypatch.setattr(booking_service, "cancel_sessions", lambda *_a, **_kw: _async(1))

    await booking_lifecycle.handle_booking_timeout(session, sess_row)

    assert "booking_no_slots" in app_row.uncertainty_flags
    assert "booking_no_response" not in app_row.uncertainty_flags
    assert "công ty" in app_row.escalation_reason
    assert ("scheduler", "booking_no_slots") in session.audits()


async def test_timeout_sends_no_email_to_candidate(monkeypatch) -> None:
    """Hết hạn CHƯA phải một quyết định — gửi thư lúc này là thay HR công bố một kết luận chưa ai đưa."""
    sent: list = []
    for name in ("notify_decision", "notify_booking_cancelled", "notify_booking_reminder"):
        monkeypatch.setattr(
            booking_lifecycle.scheduler, name,
            lambda *_a, **_kw: sent.append(1),  # noqa: ARG005
        )
    session = FakeSession({(Application, 5): _app(ApplicationStatus.AWAITING_BOOKING.value)})

    await booking_lifecycle.handle_booking_timeout(session, _session_row(expires_in_hours=-1, booked=False))

    assert sent == []


# ── C) Nhắc MỘT lần: ghi mốc + commit TRƯỚC khi gửi ──────────────────────────────────────


async def test_interview_reminder_marks_before_sending(monkeypatch) -> None:
    """At-most-once: Resend trục trặc thì thiếu MỘT lời nhắc — chứ không dội mail mỗi vòng sweep."""
    booking = _booking()
    session = FakeSession({(Application, 5): _app()})

    async def fake_send(_s, **kw):  # noqa: ANN001
        # Lúc thư bay đi, mốc PHẢI đã nằm trong DB (đã commit) — nếu không, một lần gửi lỗi sau khi
        # email đã thực sự đi sẽ khiến vòng sau nhắc lại.
        assert booking.reminder_sent_at is not None
        session.trace.append("send")
        return {"mode": "interview_reminder", "email_sent": True}

    monkeypatch.setattr(booking_lifecycle.scheduler, "notify_interview_reminder", fake_send)
    monkeypatch.setattr(booking_service, "booked_session", lambda *_a, **_kw: _noop_session())

    await booking_lifecycle.send_interview_reminder(session, booking)

    assert session.trace.index("commit") < session.trace.index("send")


async def _noop_session():
    return _session_row()


async def test_link_reminder_marks_before_sending(monkeypatch) -> None:
    sess_row = _session_row(expires_in_hours=2, booked=False)
    session = FakeSession({(Application, 5): _app(ApplicationStatus.AWAITING_BOOKING.value)})
    seen: dict = {}

    async def fake_send(_s, **kw):  # noqa: ANN001
        assert sess_row.reminded_at is not None
        seen.update(kw)
        return {"mode": "booking_reminder", "email_sent": True}

    monkeypatch.setattr(booking_lifecycle.scheduler, "notify_booking_reminder", fake_send)

    await booking_lifecycle.send_booking_reminder(session, sess_row)

    # DÙNG LẠI đúng token cũ (§10b.3) — phát link thứ hai là ứng viên có hai thư, không biết cái nào sống.
    assert seen["booking_url"].endswith("/booking/tok-abc")


# ── B) Ứng viên huỷ: nhả slot, KHÔNG gia hạn TTL ─────────────────────────────────────────


async def test_candidate_cancel_reopens_without_extending_ttl(monkeypatch) -> None:
    app_row, sess_row, booking = _app(), _session_row(expires_in_hours=40), _booking()
    deadline_before = sess_row.expires_at
    session = FakeSession({(Application, 5): app_row})
    monkeypatch.setattr(booking_service, "load_valid_session", _returning(sess_row))
    _stub_cancel_booked(monkeypatch, booking)
    email = _capture_cancel_email(monkeypatch)

    out = await booking_flow.cancel_by_candidate(session, "tok-abc")

    assert out["cancelled"] is True and out["can_rebook"] is True
    assert app_row.status == ApplicationStatus.AWAITING_BOOKING.value
    # `booked_at` PHẢI về None: `load_valid_session` bỏ qua hạn khi phiên đã đặt, nên giữ nguyên nó
    # là biến liên kết thành vĩnh viễn — đúng cái "gia hạn TTL" mà PRD §10b.6 cấm.
    assert sess_row.booked_at is None
    assert sess_row.expires_at == deadline_before  # KHÔNG gia hạn
    assert email["rebook_url"].endswith("/booking/tok-abc")


async def test_candidate_cancel_after_link_expired_goes_to_hr(monkeypatch) -> None:
    """Hết hạn thì không hứa một đường chọn lại không tồn tại — về HR, và thư KHÔNG kèm link."""
    app_row, sess_row = _app(), _session_row(expires_in_hours=-1)
    session = FakeSession({(Application, 5): app_row})
    monkeypatch.setattr(booking_service, "load_valid_session", _returning(sess_row))
    _stub_cancel_booked(monkeypatch, _booking())
    email = _capture_cancel_email(monkeypatch)

    out = await booking_flow.cancel_by_candidate(session, "tok-abc")

    assert out["can_rebook"] is False
    assert app_row.status == ApplicationStatus.PENDING_REVIEW.value
    assert app_row.status != ApplicationStatus.REJECTED.value  # huỷ ≠ từ chối
    assert email["rebook_url"] is None


# ── D) Token cũ KHÔNG lật ngược quyết định người ─────────────────────────────────────────


async def test_candidate_cancel_is_noop_when_not_scheduled(monkeypatch) -> None:
    """HR vừa từ chối/huỷ xong, ứng viên mới bấm link huỷ: KHÔNG đụng gì, và KHÔNG phải lỗi."""
    app_row = _app(ApplicationStatus.PENDING_REVIEW.value)
    session = FakeSession({(Application, 5): app_row})
    monkeypatch.setattr(booking_service, "load_valid_session", _returning(_session_row()))

    async def explode(*_a, **_kw):  # pragma: no cover — chạm vào là test đỏ
        raise AssertionError("KHÔNG được huỷ booking khi hồ sơ đã rời INTERVIEW_SCHEDULED")

    monkeypatch.setattr(booking_service, "cancel_booked", explode)
    email = _capture_cancel_email(monkeypatch)

    out = await booking_flow.cancel_by_candidate(session, "tok-abc")

    assert out == {"cancelled": False, "job_title": "vị trí ứng tuyển",
                   "can_rebook": False, "email_sent": False}
    assert app_row.status == ApplicationStatus.PENDING_REVIEW.value
    assert email == {}


# ── HR: huỷ lịch / gửi lại link (ghép lại = "đổi lịch") ──────────────────────────────────


async def test_hr_cancel_releases_and_returns_to_queue(monkeypatch) -> None:
    app_row, booking = _app(), _booking()
    session = FakeSession({(Application, 5): app_row})
    _stub_cancel_booked(monkeypatch, booking)
    email = _capture_cancel_email(monkeypatch)

    out = await booking_flow.cancel_by_hr(session, 5)

    assert out.status == ApplicationStatus.PENDING_REVIEW.value
    assert booking.status == BookingStatus.CANCELLED.value
    assert email["by_hr"] is True and email.get("rebook_url") is None  # HR cầm ca, không mời tự đặt lại
    assert ("human_review", "booking_cancelled") in session.audits()


async def test_hr_cancel_rejects_when_no_interview(monkeypatch) -> None:
    session = FakeSession({(Application, 5): _app(ApplicationStatus.AWAITING_BOOKING.value)})
    with pytest.raises(booking_flow.BookingActionError) as exc:
        await booking_flow.cancel_by_hr(session, 5)
    assert exc.value.status_code == 409


async def test_hr_resend_refuses_while_scheduled() -> None:
    """Lịch đã chốt mà phát thêm đường chọn giờ = một ứng viên chiếm hai khung giờ."""
    session = FakeSession({(Application, 5): _app(ApplicationStatus.INTERVIEW_SCHEDULED.value)})
    with pytest.raises(booking_flow.BookingActionError) as exc:
        await booking_flow.resend_booking_link(session, 5)
    assert exc.value.status_code == 409
    assert "Huỷ lịch trước" in exc.value.message


async def test_hr_resend_kills_old_link_before_issuing_new(monkeypatch) -> None:
    """Không dọn phiên cũ thì `dispatch_booking_invite` DÙNG LẠI nó — "gửi lại" chỉ gửi lại đúng
    liên kết sắp hết hạn mà HR đang muốn thay."""
    order: list[str] = []
    app_row = _app(ApplicationStatus.PENDING_REVIEW.value)
    session = FakeSession({(Application, 5): app_row})

    async def fake_cancel_sessions(*_a, **_kw):  # noqa: ANN001
        order.append("cancel_sessions")
        return 1

    async def fake_dispatch(*_a, **_kw):  # noqa: ANN001
        order.append("dispatch")
        return True

    monkeypatch.setattr(booking_service, "cancel_sessions", fake_cancel_sessions)
    monkeypatch.setattr(booking_flow, "dispatch_booking_invite", fake_dispatch)
    monkeypatch.setattr(booking_service, "has_any_session", _returning(True))

    await booking_flow.resend_booking_link(session, 5)

    assert order == ["cancel_sessions", "dispatch"]


async def test_hr_resend_refuses_application_never_invited(monkeypatch) -> None:
    """"Gửi LẠI" chỉ có nghĩa với hồ sơ ĐÃ từng được mời.

    Không có chốt này, nút gửi-lại trở thành một đường mời TẮT: một ca PENDING_REVIEW chưa ai duyệt
    vẫn nhận thư mời phỏng vấn THẬT, bỏ qua /review, và audit không có dòng `approve` nào — trong khi
    PRD §11 bắt buộc ghi lại quyết định của HR."""
    session = FakeSession({(Application, 5): _app(ApplicationStatus.PENDING_REVIEW.value)})
    monkeypatch.setattr(booking_service, "has_any_session", _returning(False))

    async def explode(*_a, **_kw):  # pragma: no cover — chạm vào là test đỏ
        raise AssertionError("KHÔNG được gửi thư mời cho hồ sơ chưa từng được duyệt")

    monkeypatch.setattr(booking_flow, "dispatch_booking_invite", explode)

    with pytest.raises(booking_flow.BookingActionError) as exc:
        await booking_flow.resend_booking_link(session, 5)
    assert exc.value.status_code == 409
    assert "chưa từng được mời" in exc.value.message


# ── E) Hết khung giờ: cờ RIÊNG, và cờ tự tắt ─────────────────────────────────────────────


async def test_no_slots_sets_flag_once_and_audits() -> None:
    app_row, sess_row = _app(ApplicationStatus.AWAITING_BOOKING.value), _session_row(booked=False)
    session = FakeSession()

    await booking_flow._record_slot_availability(
        session, sess_row, app_row, had_no_slots=False, has_slots=False
    )
    assert sess_row.no_slots_at is not None
    assert ("scheduler", "booking_no_slots") in session.audits()

    # Vẫn hết slot ở lượt sau → KHÔNG ghi thêm gì (idempotent bằng mốc, không đếm).
    before = session.commits
    await booking_flow._record_slot_availability(
        session, sess_row, app_row, had_no_slots=True, has_slots=False
    )
    assert session.commits == before


async def test_no_slots_flag_clears_when_slots_return() -> None:
    """Cảnh báo không tự tắt là cảnh báo sẽ bị phớt lờ — kể cả khi HR đã mở thêm lịch từ lâu."""
    app_row, sess_row = _app(ApplicationStatus.AWAITING_BOOKING.value), _session_row(booked=False)
    sess_row.no_slots_at = _now()
    session = FakeSession()

    await booking_flow._record_slot_availability(
        session, sess_row, app_row, had_no_slots=True, has_slots=True
    )

    assert sess_row.no_slots_at is None


def _async(value):  # noqa: ANN001, ANN202
    """Bọc một giá trị thành coroutine — để `lambda` thay được hàm async trong monkeypatch."""

    async def run():  # noqa: ANN202
        return value

    return run()


def _returning(value):  # noqa: ANN001, ANN202
    async def fake(*_a, **_kw):  # noqa: ANN202
        return value

    return fake
