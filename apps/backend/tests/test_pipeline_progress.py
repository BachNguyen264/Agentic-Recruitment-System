"""Mốc tiến độ pipeline + endpoint ảnh chụp cho bảng điều hành (PRD §12.1 FR-HR-DASH-1, §13).

Vì sao cần: trước đây `PARSING`/`RANKING` CHỈ tồn tại trong graph state (bộ nhớ). Các node có trả
`status`, nhưng `_stream_collect` gom vào `trace` và `process_application` chỉ ghi DB ở khối GHI
cuối cùng — nên hồ sơ nằm ở `SUBMITTED` suốt cả hai lượt LLM (~34s) rồi nhảy thẳng sang trạng thái
cuối. Không một nhịp hỏi lại nào, kể cả SSE, vẽ được pipeline từ dữ liệu không tồn tại.

Phủ bốn việc:
  (a) `_stream_collect` gọi `on_node` NGAY khi mỗi node xong, và KHÔNG gọi cho `__interrupt__`.
  (b) `process_application` ghi PARSING TRƯỚC khi chạy, RANKING NGAY SAU parser.
  (c) `_mark_progress` không bao giờ giết pipeline, và không kéo ngược hồ sơ đã rời vạch chưa-quyết.
  (d) `GET /api/applications/pipeline` khai TRƯỚC `/{application_id}` (không thì 422) và đếm đủ
      mọi trạng thái PRD §13.
"""

from __future__ import annotations

from app.models.application import Application, ApplicationStatus

# KHÔNG đặt `pytestmark = pytest.mark.asyncio`: pyproject bật `asyncio_mode = "auto"` nên test async
# tự chạy, còn dán mark lên các test ĐỒNG BỘ trong file này chỉ sinh cảnh báo.


class _FakeSession:
    """AsyncSession tối thiểu (mock — KHÔNG chạm DB)."""

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


class _Ctx:
    def __init__(self, session) -> None:  # noqa: ANN001
        self._s = session

    async def __aenter__(self):
        return self._s

    async def __aexit__(self, *_a) -> bool:
        return False


def _clean_out(status: str) -> dict:
    return {
        "branch": "human_review",
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
        "trace": [{"node": "parser", "status": "PARSING", "uncertainty_flags": []}],
        "suspended": False,
    }


# ── (a) runner: móc on_node ──────────────────────────────────────────────────


class _FakeGraph:
    """Graph giả phát đúng chuỗi sự kiện `astream(stream_mode="updates")` mà runner đọc."""

    def __init__(self, updates: list[dict]) -> None:
        self._updates = updates

    async def astream(self, _input, _config, stream_mode: str):  # noqa: ANN001, ARG002
        for u in self._updates:
            yield u

    async def aget_state(self, _config):  # noqa: ANN001
        class _Snap:
            next = ()
            values = {"status": "PENDING_REVIEW"}

        return _Snap()


async def test_on_node_fires_per_completed_node_in_order() -> None:
    from app.agents.runner import _stream_collect

    graph = _FakeGraph(
        [{"parser": {"status": "PARSING"}}, {"ranker": {"status": "RANKING"}}]
    )
    seen: list[str] = []

    async def _on_node(name: str) -> None:
        seen.append(name)

    _snapshot, trace = await _stream_collect(graph, {}, {}, _on_node)
    assert seen == ["parser", "ranker"]
    assert [s["node"] for s in trace] == ["parser", "ranker"]


async def test_on_node_not_fired_for_interrupt_event() -> None:
    """`__interrupt__` là điểm SUSPEND, không phải node hoàn tất — payload là tuple Interrupt.
    Gọi callback cho nó sẽ ghi một mốc tiến độ bịa ra tên node `__interrupt__`."""
    from app.agents.runner import _stream_collect

    graph = _FakeGraph([{"parser": {"status": "PARSING"}}, {"__interrupt__": ("x",)}])
    seen: list[str] = []

    async def _on_node(name: str) -> None:
        seen.append(name)

    await _stream_collect(graph, {}, {}, _on_node)
    assert seen == ["parser"]


async def test_stream_collect_without_callback_still_works() -> None:
    """`on_node` là tuỳ chọn — `resume_with_trace` và test cũ gọi không truyền gì."""
    from app.agents.runner import _stream_collect

    _snap, trace = await _stream_collect(_FakeGraph([{"parser": {}}]), {}, {})
    assert [s["node"] for s in trace] == ["parser"]


# ── (b) background: PARSING trước khi chạy, RANKING ngay sau parser ──────────


async def test_marks_parsing_before_run_and_ranking_after_parser(monkeypatch) -> None:
    """Đúng thứ tự HR nhìn thấy trên dashboard: ô parser sáng trong lúc parser chạy, tắt và chuyển
    sang ô ranker NGAY khi parser xong — chứ không phải cả hai cùng tối suốt 34 giây."""
    from app.tasks import background

    app_row = Application(id=41, applicant_email="a@e.com", job_id=None, status="SUBMITTED")
    session = _FakeSession({(Application, 41): app_row})
    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _Ctx(session))

    seen: list[tuple[str, str]] = []

    async def _fake_run(**kw):
        seen.append(("lúc pipeline khởi động", app_row.status))
        await kw["on_node"]("parser")
        seen.append(("ngay sau parser", app_row.status))
        await kw["on_node"]("ranker")
        seen.append(("ngay sau ranker", app_row.status))
        return _clean_out(ApplicationStatus.PENDING_REVIEW.value)

    monkeypatch.setattr(background, "run_with_trace", _fake_run)

    await background.process_application(41)

    assert seen == [
        ("lúc pipeline khởi động", ApplicationStatus.PARSING.value),
        ("ngay sau parser", ApplicationStatus.RANKING.value),
        # Sau ranker KHÔNG có mốc mới: quyết định chốt ngay ở khối GHI, thêm mốc chỉ tốn một lượt
        # mượn pool mà không cho HR biết thêm gì.
        ("ngay sau ranker", ApplicationStatus.RANKING.value),
    ]
    assert app_row.status == ApplicationStatus.PENDING_REVIEW.value  # khối GHI vẫn chốt như cũ


# ── (c) _mark_progress: không giết pipeline, không kéo ngược trạng thái ──────


async def test_mark_progress_never_raises(monkeypatch) -> None:
    """Ghi mốc là dữ liệu HIỂN THỊ. Pool cạn ở đây mà ném ra thì giết pipeline của một ứng viên
    thật vì một con số trang trí."""
    from app.tasks import background

    class _Dead(_FakeSession):
        async def get(self, model, pk):  # noqa: ANN001
            raise TimeoutError("QueuePool limit reached")

    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _Ctx(_Dead({})))
    await background._mark_progress(7, ApplicationStatus.RANKING.value)  # KHÔNG được raise


async def test_mark_progress_refuses_to_drag_back_decided_application(monkeypatch) -> None:
    """Mốc đến MUỘN không được kéo ngược hồ sơ đã rời vạch chưa-quyết. Kịch bản thật: pipeline treo
    lâu → sweep đối soát đẩy về PENDING_REVIEW → HR quyết + thư đã gửi → mốc RANKING mới tới nơi."""
    from app.tasks import background

    decided = Application(id=42, applicant_email="b@e.com", status=ApplicationStatus.REJECTED.value)
    session = _FakeSession({(Application, 42): decided})
    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _Ctx(session))

    await background._mark_progress(42, ApplicationStatus.RANKING.value)

    assert decided.status == ApplicationStatus.REJECTED.value
    assert session.commits == 0


async def test_mark_progress_ignores_deleted_application(monkeypatch) -> None:
    """Hồ sơ bị xóa giữa chừng (vd reset_demo_data) → im lặng bỏ qua, không ném."""
    from app.tasks import background

    session = _FakeSession({})
    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _Ctx(session))
    await background._mark_progress(999, ApplicationStatus.PARSING.value)
    assert session.commits == 0


# ── (d) endpoint pipeline ────────────────────────────────────────────────────


def test_pipeline_route_declared_before_application_id() -> None:
    """FastAPI khớp route theo THỨ TỰ khai báo. Đảo hai dòng này thì `/pipeline` rơi vào tay
    `get_application` và chết 422 — bảng điều hành trắng mà backend vẫn 'khoẻ'."""
    from app.main import app

    paths = [r.path for r in app.routes if getattr(r, "path", "").startswith("/api/applications")]
    assert paths.index("/api/applications/pipeline") < paths.index(
        "/api/applications/{application_id}"
    )


def test_pipeline_route_is_hr_gated() -> None:
    """Nhịp hỏi lại của dashboard KHÔNG được là lỗ hổng đếm hồ sơ cho người ngoài (PRD §4)."""
    from app.api.deps import require_hr
    from app.main import app

    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/applications/pipeline")
    assert require_hr in [d.call for d in route.dependant.dependencies]


async def test_status_counts_returns_every_prd_status_even_at_zero() -> None:
    """Client không phải đoán khoá nào tồn tại: thiếu khoá và giá trị 0 là hai chuyện khác nhau."""
    from app.services import application_service

    class _CountSession:
        async def execute(self, _stmt):  # noqa: ANN001
            return [(ApplicationStatus.REJECTED.value, 3), (ApplicationStatus.PARSING.value, 1)]

    counts = await application_service.status_counts(_CountSession())

    assert set(counts) == {s.value for s in ApplicationStatus}
    assert counts[ApplicationStatus.REJECTED.value] == 3
    assert counts[ApplicationStatus.PARSING.value] == 1
    assert counts[ApplicationStatus.INTERVIEW_SCHEDULED.value] == 0


def test_dashboard_active_set_is_not_the_safety_set() -> None:
    """Hai tập CỐ Ý khác nhau. Gộp chúng lại thì lỗi lộ ra ở xử-lý-lỗi/đối-soát (cho phép ghi đè
    AWAITING_BOOKING = 'mời xong lại từ chối'), chứ không phải ở dashboard."""
    from app.models.application import DASHBOARD_ACTIVE_STATUSES, IN_FLIGHT_STATUSES

    assert IN_FLIGHT_STATUSES < DASHBOARD_ACTIVE_STATUSES  # con thật sự, không bằng nhau
    assert ApplicationStatus.AWAITING_BOOKING.value in DASHBOARD_ACTIVE_STATUSES
    assert ApplicationStatus.AWAITING_BOOKING.value not in IN_FLIGHT_STATUSES
    # Trạng thái KẾT THÚC không được nằm trong panel "đang chạy".
    for done in (ApplicationStatus.REJECTED, ApplicationStatus.INTERVIEW_SCHEDULED):
        assert done.value not in DASHBOARD_ACTIVE_STATUSES


async def test_parsing_mark_failure_does_not_kill_the_pipeline(monkeypatch) -> None:
    """Mốc `PARSING` hỏng thì pipeline vẫn PHẢI chạy — cùng chính sách với `_mark_progress`.

    Mốc này là dữ liệu HIỂN THỊ, y hệt mốc `RANKING`. DASH-1 ghi nó bằng một `commit()` TRẦN nằm
    trong khối `try` lớn của `process_application`; nếu KHÔNG gói `try` riêng thì một lỗi ghi thoáng
    qua (kết nối Neon đứt ngay giữa `get` và `commit`) rơi xuống `_escalate_technical_error` và biến
    hồ sơ thành `PENDING_REVIEW[error]` — parser lẫn ranker không chạy lần nào, `parsed_data` rỗng,
    `score` NULL, tất cả vì một con số trang trí. Đây là điểm hỏng DASH-1 mở ra: trước nó khối ĐỌC
    không có `commit()` nào. Test này từng ĐỎ đúng ở dòng `await session.commit()` đó.

    Khẳng định HÀNH VI (pipeline có chạy không), KHÔNG khẳng định cách vá — nên nó vẫn canh đúng
    nếu sau này mốc PARSING chuyển sang đi qua `_mark_progress`.
    """
    from app.tasks import background

    app_row = Application(id=43, applicant_email="c@e.com", job_id=None, status="SUBMITTED")

    class _FlakyFirstCommit(_FakeSession):
        """Chỉ lượt commit ĐẦU TIÊN hỏng — đúng lượt ghi mốc PARSING."""

        async def commit(self) -> None:
            self.commits += 1
            if self.commits == 1:
                # KHÔNG dùng "QueuePool timed out": lượt mượn connection xảy ra ở `session.get` ĐẦU
                # TIÊN, không phải ở `commit()` — đường đó đã escalate CÓ CHỦ Ý (xem
                # test_stuck_hardening). Ca thật ở đây là kết nối ĐỨT giữa `get` và `commit`.
                raise ConnectionResetError("Neon đóng kết nối giữa get và commit")

    session = _FlakyFirstCommit({(Application, 43): app_row})
    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _Ctx(session))

    ran: list[str] = []

    async def _fake_run(**kw):
        ran.append("pipeline")
        return _clean_out(ApplicationStatus.PENDING_REVIEW.value)

    monkeypatch.setattr(background, "run_with_trace", _fake_run)

    await background.process_application(43)

    assert ran == ["pipeline"], "mốc hiển thị hỏng đã giết pipeline của một ứng viên thật"
    # Chuỗi phải khớp NGUYÊN VĂN `_escalate_technical_error` gọi ở nhánh `except` của
    # `process_application` — lệch một chữ là assert này luôn xanh và không canh gì cả.
    assert app_row.escalation_reason != "Lỗi kỹ thuật khi xử lý pipeline (error)."
    assert app_row.status == ApplicationStatus.PENDING_REVIEW.value  # kết quả THẬT của pipeline
