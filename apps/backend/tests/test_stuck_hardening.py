"""Test hardening tải — hồ sơ KHÔNG được mất im lặng khi hạ tầng đuối (PRD §13, NFR-1).

Phủ ba việc:
  (a) `process_application`: lỗi ở thao tác DB ĐẦU TIÊN (pool cạn) → hồ sơ KHÔNG kẹt câm, có audit
      `error` + escalation. Trước fix, thao tác đầu nằm NGOÀI try → ném thẳng ra BackgroundTasks.
  (b) `stuck_applications.sweep_stuck_once`: hồ sơ kẹt quá hạn → PENDING_REVIEW[error], idempotent,
      KHÔNG auto-reject, KHÔNG đụng hồ sơ còn tươi / hồ sơ ngoài trạng thái đang-bay.
  (c) KHÔNG hồi quy: pipeline vẫn parse→rank→route như cũ, và connection ĐƯỢC NHẢ trước khi gọi LLM.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.application import Application, ApplicationStatus
from app.models.audit_log import AuditLog
from app.models.job_posting import JobPosting

pytestmark = pytest.mark.asyncio


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _FakeSession:
    """AsyncSession tối thiểu (mock — KHÔNG chạm DB). Đếm số lần được MỞ để kiểm vòng đời session."""

    def __init__(self, rows: dict) -> None:
        self._rows = rows
        self.added: list = []
        self.commits = 0

    async def get(self, model, pk):  # noqa: ANN001
        return self._rows.get((model, pk))

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj) -> None:
        pass

    async def rollback(self) -> None:
        pass

    def audits(self) -> list[tuple[str, str]]:
        return [(a.node, a.action) for a in self.added if isinstance(a, AuditLog)]


class _Ctx:
    """Bản mô phỏng `AsyncSessionLocal()` — đếm số lần mở session (mỗi lần = một lần mượn pool)."""

    opened = 0

    def __init__(self, session: _FakeSession) -> None:
        self._s = session

    async def __aenter__(self) -> _FakeSession:
        type(self).opened += 1
        return self._s

    async def __aexit__(self, *_a) -> bool:
        return False


async def _await_value(value):
    return value


def _clean_out(status: str, branch: str = "human_review") -> dict:
    return {
        "branch": branch,
        "final": {
            "status": status,
            "parsed_data": {"full_name": "Nguyễn Văn A"},
            "score": 72.0,
            "semantic_similarity": 0.7,
            "confidence": 1.0,
            "uncertainty_flags": [],
            "escalation_reason": None,
            "scratchpad": {},
        },
        "trace": [
            {"node": "parser", "status": "PARSING", "uncertainty_flags": []},
            {"node": "ranker", "status": "RANKING", "uncertainty_flags": []},
            {"node": "human_review", "status": status, "uncertainty_flags": []},
        ],
        "suspended": False,
    }


# ── (a) Lỗi ở thao tác DB ĐẦU TIÊN → KHÔNG kẹt câm ───────────────────────────


async def test_pool_timeout_on_first_db_op_escalates_not_silent(monkeypatch) -> None:
    """Pool cạn ngay ở `session.get` đầu tiên: KHÔNG raise ra ngoài BackgroundTasks, và hồ sơ được
    hạ về PENDING_REVIEW[error] kèm audit — không còn "201 nhưng mất hồ sơ"."""
    from app.tasks import background

    app_row = Application(id=30, applicant_email="me@e.com", job_id=2, status="SUBMITTED")
    rescue = _FakeSession({(Application, 30): app_row})
    calls = {"n": 0}

    class _FailFirstSession(_FakeSession):
        async def get(self, model, pk):  # noqa: ANN001
            calls["n"] += 1
            raise TimeoutError("QueuePool limit of size 5 overflow 10 reached, connection timed out")

    failing = _FailFirstSession({})

    def _factory():
        # Session ĐẦU (đọc) chết vì pool; session cứu hộ (mở MỚI trong _escalate) thì sống.
        return _Ctx(failing if calls["n"] == 0 else rescue)

    monkeypatch.setattr(background, "AsyncSessionLocal", _factory)

    await background.process_application(30)  # KHÔNG được raise ra ngoài

    assert app_row.status == ApplicationStatus.PENDING_REVIEW.value
    assert app_row.escalation_reason == "Lỗi kỹ thuật khi xử lý pipeline (error)."
    assert ("system", "error") in rescue.audits()  # có DẤU VẾT, không mất im lặng


async def test_escalate_never_raises_when_rescue_session_also_dies(monkeypatch) -> None:
    """Pool cạn SẠCH: cả session cứu hộ cũng chết → vẫn KHÔNG ném ra BackgroundTasks (chỉ log).
    Hồ sơ còn ở SUBMITTED và lưới cuối là sweep đối soát — đó là lý do lưới ấy tồn tại."""
    from app.tasks import background

    class _AlwaysDead(_FakeSession):
        async def get(self, model, pk):  # noqa: ANN001
            raise TimeoutError("QueuePool limit reached")

    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _Ctx(_AlwaysDead({})))

    await background.process_application(31)  # KHÔNG raise — đây chính là điều đang kiểm


async def test_session_teardown_error_does_not_downgrade_awaiting_screener(monkeypatch) -> None:
    """HỒI QUY (adversarial review): lỗi lúc ĐÓNG session ở giai đoạn GHI KHÔNG được hạ trạng thái.

    Vì `try` nay bao cả `async with`, phần thoát khối cũng rơi vào handler lỗi. Mà thoát khối KHÔNG
    vô hại: `audit_service.record(commit=True)` kết thúc bằng `refresh()` → mở lại transaction → lúc
    đóng còn một ROLLBACK đi qua mạng, ném được. Nếu handler cứ hạ trạng thái thì hồ sơ đã
    AWAITING_SCREENER (magic-link ĐÃ gửi) rơi về PENDING_REVIEW[error] → ứng viên nộp câu trả lời bị
    409 (`screening._load_valid`) và MẤT bài dự tuyển — họ là guest, không có gì để khiếu nại.
    """
    from app.tasks import background

    app_row = Application(id=35, applicant_email="me@e.com", job_id=None,
                          status=ApplicationStatus.AWAITING_SCREENER.value)
    session = _FakeSession({(Application, 35): app_row})

    class _ExplodingTeardownCtx:
        """Vào bình thường, nhưng THOÁT thì ném — mô phỏng ROLLBACK chết lúc đóng session."""

        first = True

        async def __aenter__(self):
            return session

        async def __aexit__(self, *_a):
            if type(self).first:
                type(self).first = False
                raise ConnectionResetError("Neon rớt kết nối giữa refresh và rollback lúc đóng")
            return False

    monkeypatch.setattr(background, "AsyncSessionLocal", _ExplodingTeardownCtx)
    monkeypatch.setattr(
        background, "run_with_trace",
        lambda **_kw: _await_value(_clean_out(ApplicationStatus.PENDING_REVIEW.value)),
    )

    await background.process_application(35)  # KHÔNG raise ra ngoài

    # Magic-link đã gửi → hồ sơ PHẢI ở nguyên AWAITING_SCREENER để ứng viên còn nộp được câu trả lời.
    assert app_row.status == ApplicationStatus.AWAITING_SCREENER.value
    assert app_row.escalation_reason != "Lỗi kỹ thuật khi xử lý pipeline (error)."


async def test_scheduling_not_downgraded_by_technical_error(monkeypatch) -> None:
    """Đối xứng: SCHEDULING = "đã quyết mời, thư mời CÓ THỂ đã gửi" → KHÔNG hạ về [error], nếu không
    HR nhận thẻ lỗi rồi từ chối đúng người vừa được mời."""
    from app.tasks import background

    app_row = Application(id=36, applicant_email="me@e.com", job_id=None,
                          status=ApplicationStatus.SCHEDULING.value)
    session = _FakeSession({(Application, 36): app_row})
    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _Ctx(session))

    await background._escalate_technical_error(36, "Lỗi kỹ thuật khi xử lý pipeline (error).")

    assert app_row.status == ApplicationStatus.SCHEDULING.value
    assert ("system", "error") not in session.audits()


async def test_in_flight_statuses_shared_by_both_nets() -> None:
    """Hai lưới (handler lỗi của background + sweep đối soát) PHẢI dùng chung một định nghĩa
    "trạng thái nào còn được ghi đè". Lệch nhau là cách sinh ra chính lớp lỗi cả hai đang chặn."""
    from app.models.application import IN_FLIGHT_STATUSES
    from app.services import stuck_applications

    assert set(stuck_applications._STUCK_STATUSES) == set(IN_FLIGHT_STATUSES)
    assert set(IN_FLIGHT_STATUSES) == {"SUBMITTED", "PARSING", "RANKING"}


async def test_terminal_status_not_overwritten_by_late_pipeline(monkeypatch) -> None:
    """Hồ sơ đã REJECTED (thư từ chối ĐÃ gửi) mà kết quả pipeline về muộn → KHÔNG ghi đè.
    Ghi đè ở đây là "từ chối xong lại mời"."""
    from app.tasks import background

    app_row = Application(id=32, applicant_email="me@e.com", job_id=None,
                          status=ApplicationStatus.REJECTED.value)
    session = _FakeSession({(Application, 32): app_row})
    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _Ctx(session))
    monkeypatch.setattr(
        background, "run_with_trace",
        lambda **_kw: _await_value(_clean_out(ApplicationStatus.PENDING_REVIEW.value)),
    )

    await background.process_application(32)

    assert app_row.status == ApplicationStatus.REJECTED.value  # quyết định đã phát ra ngoài: GIỮ
    assert ("system", "received") not in session.audits()  # dừng TRƯỚC khi ghi bất cứ thứ gì


# ── (c) KHÔNG hồi quy + connection ĐƯỢC NHẢ trước khi gọi LLM ────────────────


async def test_connection_released_before_llm_call(monkeypatch) -> None:
    """BẤT BIẾN CỐT LÕI của fix: lúc pipeline (parser+ranker LLM) chạy, KHÔNG session nào đang mở.

    Kiểm bằng cách đếm mở/đóng: `run_with_trace` chạy khi số session đang mở = 0. Trước fix, con số
    đó là 1 suốt hàng chục giây — chính là thứ làm cạn pool.
    """
    from app.tasks import background

    app_row = Application(id=33, applicant_email="me@e.com", job_id=2, status="SUBMITTED")
    job = JobPosting(id=2, title="Backend Intern", screener_questions=[])
    session = _FakeSession({(Application, 33): app_row, (JobPosting, 2): job})

    live = {"open": 0, "during_pipeline": None}

    class _CountingCtx:
        async def __aenter__(self):
            live["open"] += 1
            return session

        async def __aexit__(self, *_a):
            live["open"] -= 1
            return False

    async def fake_run(**_kw):
        live["during_pipeline"] = live["open"]  # chụp số session đang mở NGAY lúc gọi LLM
        return _clean_out(ApplicationStatus.PENDING_REVIEW.value)

    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _CountingCtx())
    monkeypatch.setattr(background, "run_with_trace", fake_run)

    await background.process_application(33)

    assert live["during_pipeline"] == 0, "pipeline vẫn đang giữ session — fix hỏng"
    assert live["open"] == 0  # đóng sạch sau khi xong
    # KHÔNG hồi quy: vẫn ghi đủ audit + persist kết quả như trước.
    assert app_row.status == ApplicationStatus.PENDING_REVIEW.value
    assert app_row.score == 72.0
    audits = session.audits()
    assert ("system", "received") in audits
    assert ("parser", "parsed") in audits
    assert ("ranker", "ranked") in audits
    assert ("system", "route:human_review") in audits


async def test_jd_snapshot_read_before_pipeline(monkeypatch) -> None:
    """JD (rubric/gate/screener_questions) vẫn được nạp ĐÚNG và truyền vào pipeline dù session đã đóng
    trước khi chạy — chống lỗi "chụp thiếu dữ liệu" khi tách vòng đời session."""
    from app.tasks import background

    app_row = Application(id=34, applicant_email="me@e.com", job_id=2, status="SUBMITTED")
    job = JobPosting(
        id=2, title="Backend Intern", description="<p>Mô tả</p>", requirements="<p>Node.js</p>",
        rubric=[{"criterion": "Node.js", "weight": 1.0}],
        screener_questions=["Mức lương kỳ vọng?"],
        gate_config={"auto_reject": True, "auto_invite": False},
    )
    session = _FakeSession({(Application, 34): app_row, (JobPosting, 2): job})
    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _Ctx(session))

    captured: dict = {}

    async def fake_run(**kw):
        captured.update(kw)
        return _clean_out(ApplicationStatus.PENDING_REVIEW.value)

    monkeypatch.setattr(background, "run_with_trace", fake_run)

    await background.process_application(34)

    jd = captured["jd"]
    assert jd["job_id"] == 2 and jd["title"] == "Backend Intern"
    assert jd["rubric"] == [{"criterion": "Node.js", "weight": 1.0}]
    assert jd["gate_config"] == {"auto_reject": True, "auto_invite": False}
    assert jd["screener_questions"] == ["Mức lương kỳ vọng?"]
    assert captured["applicant_email"] == "me@e.com"


# ── (b) Sweep đối soát hồ sơ kẹt ─────────────────────────────────────────────


class _SweepSession(_FakeSession):
    """Thêm `execute` để giả hai truy vấn của sweep: quét id + SELECT … FOR UPDATE."""

    def __init__(self, rows: dict, due_ids: list[int], locked: dict) -> None:
        super().__init__(rows)
        self._due_ids = due_ids
        self._locked = locked
        self.executed = 0

    async def execute(self, _stmt):  # noqa: ANN001
        self.executed += 1
        due_ids, locked = self._due_ids, self._locked

        class _Result:
            def __init__(self, first: bool) -> None:
                self._first = first

            def scalars(self):
                outer = self

                class _S:
                    def all(_self):  # noqa: ANN001
                        return list(due_ids) if outer._first else []

                return _S()

            def scalar_one_or_none(self):
                return locked.get("row")

        # Lần execute ĐẦU của mỗi session = quét id; các lần sau = row-lock.
        return _Result(self.executed == 1 and bool(due_ids))


def _factory_for(session):
    class _F:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_a):
            return False

    return lambda: _F()


async def test_sweep_reconciles_stuck_application(monkeypatch) -> None:
    """Hồ sơ kẹt ở SUBMITTED quá hạn → PENDING_REVIEW[error] + audit, KHÔNG auto-reject."""
    from app.services import stuck_applications

    stuck = Application(id=40, applicant_email="me@e.com", status="SUBMITTED")
    stuck.updated_at = _now() - timedelta(hours=2)

    read = _SweepSession({}, [40], {})
    work = _SweepSession({}, [], {"row": stuck})
    sessions = iter([read, work])

    class _F:
        async def __aenter__(self):
            return next(sessions)

        async def __aexit__(self, *_a):
            return False

    counts = await stuck_applications.sweep_stuck_once(lambda: _F())

    assert counts == {"reconciled": 1, "errors": 0}
    assert stuck.status == ApplicationStatus.PENDING_REVIEW.value
    assert stuck.escalation_reason == "Xử lý bị gián đoạn giữa chừng — cần HR xem lại (error)."
    assert ("system", "stuck_reconciled") in work.audits()
    # TUYỆT ĐỐI KHÔNG auto-reject: im lặng của hệ thống không phải lỗi ứng viên (PRD §9).
    assert stuck.status != ApplicationStatus.REJECTED.value
    detail = [a for a in work.added if isinstance(a, AuditLog)][0].detail
    assert detail["previous_status"] == "SUBMITTED"


async def test_sweep_idempotent_second_pass_does_nothing() -> None:
    """Chạy lại vòng quét trên hồ sơ VỪA đối soát → không đụng lần hai (status đã rời trạng thái
    đang-bay nên re-check trong lock chặn lại)."""
    from app.services import stuck_applications

    already = Application(id=41, applicant_email="me@e.com",
                          status=ApplicationStatus.PENDING_REVIEW.value)
    already.updated_at = _now() - timedelta(hours=2)

    read = _SweepSession({}, [41], {})
    work = _SweepSession({}, [], {"row": already})
    sessions = iter([read, work])

    class _F:
        async def __aenter__(self):
            return next(sessions)

        async def __aexit__(self, *_a):
            return False

    counts = await stuck_applications.sweep_stuck_once(lambda: _F())

    assert counts == {"reconciled": 0, "errors": 0}
    assert work.audits() == []  # không ghi gì thêm
    assert already.status == ApplicationStatus.PENDING_REVIEW.value


async def test_sweep_skips_application_finished_between_scan_and_lock() -> None:
    """Đua: hồ sơ được quét ra nhưng pipeline ghi xong TRƯỚC khi khóa → re-check trong lock bỏ qua,
    KHÔNG đè lên kết quả thật (vd đã INTERVIEW_SCHEDULED)."""
    from app.services import stuck_applications

    finished = Application(id=42, applicant_email="me@e.com",
                           status=ApplicationStatus.INTERVIEW_SCHEDULED.value)
    finished.updated_at = _now()

    read = _SweepSession({}, [42], {})
    work = _SweepSession({}, [], {"row": finished})
    sessions = iter([read, work])

    class _F:
        async def __aenter__(self):
            return next(sessions)

        async def __aexit__(self, *_a):
            return False

    counts = await stuck_applications.sweep_stuck_once(lambda: _F())

    assert counts == {"reconciled": 0, "errors": 0}
    assert finished.status == ApplicationStatus.INTERVIEW_SCHEDULED.value


async def test_sweep_skips_fresh_row_inside_lock() -> None:
    """Hồ sơ còn SUBMITTED nhưng `updated_at` vừa mới → re-check trong lock KHÔNG cướp hồ sơ đang chạy."""
    from app.services import stuck_applications

    fresh = Application(id=43, applicant_email="me@e.com", status="SUBMITTED")
    fresh.updated_at = _now()

    read = _SweepSession({}, [43], {})
    work = _SweepSession({}, [], {"row": fresh})
    sessions = iter([read, work])

    class _F:
        async def __aenter__(self):
            return next(sessions)

        async def __aexit__(self, *_a):
            return False

    counts = await stuck_applications.sweep_stuck_once(lambda: _F())

    assert counts == {"reconciled": 0, "errors": 0}
    assert fresh.status == "SUBMITTED"


async def test_sweep_disabled_when_threshold_not_positive(monkeypatch) -> None:
    """`STUCK_APPLICATION_TIMEOUT_MINUTES <= 0` = TẮT lưới: thoát sớm, KHÔNG truy vấn gì."""
    from app.core.config import settings
    from app.services import stuck_applications

    monkeypatch.setattr(settings, "stuck_application_timeout_minutes", 0.0)
    touched = _SweepSession({}, [99], {})

    counts = await stuck_applications.sweep_stuck_once(_factory_for(touched))

    assert counts == {"reconciled": 0, "errors": 0}
    assert touched.executed == 0  # không mở truy vấn nào


async def test_sweep_statuses_exclude_scheduling_and_awaiting() -> None:
    """Chốt bất biến: SCHEDULING (thư mời CÓ THỂ đã gửi) và AWAITING_SCREENER (có sweep riêng)
    KHÔNG nằm trong tầm quét — chống "mời xong lại từ chối" và chống hai lưới giẫm chân nhau."""
    from app.services import stuck_applications

    assert ApplicationStatus.SCHEDULING.value not in stuck_applications._STUCK_STATUSES
    assert ApplicationStatus.AWAITING_SCREENER.value not in stuck_applications._STUCK_STATUSES
    assert ApplicationStatus.REJECTED.value not in stuck_applications._STUCK_STATUSES
    assert ApplicationStatus.INTERVIEW_SCHEDULED.value not in stuck_applications._STUCK_STATUSES
    assert set(stuck_applications._STUCK_STATUSES) == {"SUBMITTED", "PARSING", "RANKING"}
