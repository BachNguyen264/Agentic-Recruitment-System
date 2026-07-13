"""Test slice 03c — Gate rank (auto-từ-chối sau ranker, cấu hình theo JD). PRD §9, §8.3.

Phủ ba tầng (mock scheduler/email — KHÔNG gửi thật, KHÔNG chạm DB thật):
  1) route_after_ranker: 3 nhánh đúng THỨ TỰ ƯU TIÊN (uncertain → human_review LUÔN; confident+đạt
     → screener; confident+điểm thấp SẠCH → gate ON auto_reject / OFF human_review).
  2) gate node đặt REJECTED (không gửi email — node không có session).
  3) background: nhánh auto_reject → delegate scheduler.notify_decision("reject") + status REJECTED
     + audit gate/auto_reject (điểm phát email DUY NHẤT; lỗi gửi nuốt có kiểm soát).
  4) job_service.set_gate_config: bật/tắt gate theo JD (không đụng field còn lại).

BẤT BIẾN (PRD §9): ranker đặt require_human_review cho MỌI điểm thấp → đó là TRIGGER của gate,
KHÔNG phải tín hiệu bất định. Ca có cờ/low-confidence LUÔN về human_review dù gate bật (an toàn).
"""

from __future__ import annotations

import pytest

from app.agents.policy import route_after_ranker
from app.core.config import settings

_LOW = settings.score_pass_threshold - 20   # điểm thấp rõ ràng
_PASS = settings.score_pass_threshold + 20   # điểm đạt rõ ràng


def _state(
    *,
    confidence: float = 1.0,
    flags: list[str] | None = None,
    require_review: bool = False,
    score: float | None = None,
    auto_reject: bool = False,
    error: str | None = None,
) -> dict:
    return {
        "error": error,
        "confidence": confidence,
        "uncertainty_flags": flags or [],
        "require_human_review": require_review,
        "score": score,
        "input": {"jd": {"gate_config": {"auto_reject": auto_reject, "auto_invite": False}}},
    }


# ── route_after_ranker: 3 nhánh theo thứ tự ưu tiên ──────────────────────────


def test_route_confident_clean_low_score_gate_on_auto_rejects() -> None:
    # Tự tin, KHÔNG cờ, điểm thấp (ranker đặt require_review) + gate BẬT → auto_reject.
    st = _state(require_review=True, score=_LOW, auto_reject=True)
    assert route_after_ranker(st) == "auto_reject"


def test_route_confident_clean_low_score_gate_off_human_review() -> None:
    # Cùng ca nhưng gate TẮT → human_review (hành vi mặc định, không đổi).
    st = _state(require_review=True, score=_LOW, auto_reject=False)
    assert route_after_ranker(st) == "human_review"


def test_route_flagged_low_score_gate_on_still_human_review() -> None:
    # Điểm thấp NHƯNG có cờ bất định → uncertain → human_review dù gate BẬT (an toàn — gate no-op).
    st = _state(flags=["score_signal_mismatch"], require_review=True, score=_LOW, auto_reject=True)
    assert route_after_ranker(st) == "human_review"


def test_route_low_confidence_gate_on_still_human_review() -> None:
    # confidence dưới ngưỡng → uncertain → human_review dù gate BẬT.
    st = _state(confidence=0.3, require_review=True, score=_LOW, auto_reject=True)
    assert route_after_ranker(st) == "human_review"


def test_route_error_gate_on_still_human_review() -> None:
    # Lỗi kỹ thuật → uncertain → human_review dù gate BẬT.
    st = _state(error="boom", require_review=True, score=_LOW, auto_reject=True)
    assert route_after_ranker(st) == "human_review"


def test_route_confident_pass_goes_to_human_review() -> None:
    # BUG A fix: đạt ngưỡng + tự tin → human_review (HR duyệt → scheduler gửi thư MỜI thật, đường
    # 03b+04). Auto-mời chưa xây (mặc định TẮT) nên KHÔNG auto-schedule câm; gate auto_reject KHÔNG
    # áp cho ca ĐẠT (dù bật) — chỉ áp ca điểm thấp.
    st = _state(require_review=False, score=_PASS, auto_reject=True)
    assert route_after_ranker(st) == "human_review"


# ── gate node: đặt REJECTED, KHÔNG gửi email ─────────────────────────────────


def test_gate_node_sets_rejected() -> None:
    from app.agents.nodes.gate import gate_auto_reject_node

    out = gate_auto_reject_node(_state(require_review=True, score=_LOW, auto_reject=True))
    from app.models.application import ApplicationStatus

    assert out["status"] == ApplicationStatus.REJECTED.value
    assert out["result"]["action"] == "auto_reject"


# ── background: nhánh auto_reject → delegate scheduler (thư từ chối THẬT) ─────


class _FakeSession:
    """AsyncSession tối thiểu cho process_application (mock — KHÔNG chạm DB)."""

    def __init__(self, rows: dict) -> None:
        self._rows = rows  # {(Model, pk): obj}
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


def _auto_reject_out(status: str) -> dict:
    return {
        "branch": "auto_reject",
        "final": {
            "status": status,
            "parsed_data": {"full_name": "Nguyễn Văn A"},
            "score": _LOW,
            "semantic_similarity": 0.1,
            "confidence": 1.0,
            "uncertainty_flags": [],
            "escalation_reason": None,
            "scratchpad": {},
        },
        "trace": [
            {"node": "parser", "status": "PARSED", "uncertainty_flags": []},
            {"node": "ranker", "status": "RANKING", "uncertainty_flags": []},
            {"node": "gate", "status": status, "uncertainty_flags": []},
        ],
    }


async def test_background_auto_reject_delegates_scheduler(monkeypatch) -> None:
    from app.agents.nodes import scheduler
    from app.models.application import Application, ApplicationStatus
    from app.models.audit_log import AuditLog
    from app.models.job_posting import JobPosting
    from app.tasks import background

    app_row = Application(id=1, applicant_email="me@e.com", job_id=2, status="SUBMITTED")
    job = JobPosting(id=2, title="Backend Intern")
    session = _FakeSession({(Application, 1): app_row, (JobPosting, 2): job})

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _Ctx())
    monkeypatch.setattr(
        background, "run_with_trace",
        lambda **_kw: _await_value(_auto_reject_out(ApplicationStatus.REJECTED.value)),
    )

    captured: dict = {}

    async def fake_notify(_session, mode, **kw):  # noqa: ANN001 — khớp chữ ký notify_decision
        captured.update(mode=mode, **kw)
        return {"mode": mode, "email_sent": True}

    monkeypatch.setattr(scheduler, "notify_decision", fake_notify)

    await background.process_application(1)

    # Auto-reject: status REJECTED + delegate scheduler(reject) đúng recipient/tên/vị trí.
    assert app_row.status == ApplicationStatus.REJECTED.value
    assert captured["mode"] == "reject"
    assert captured["applicant_email"] == "me@e.com"
    assert captured["candidate_name"] == "Nguyễn Văn A"
    assert captured["job_title"] == "Backend Intern"
    # Audit gate/auto_reject được ghi (điểm phát email do scheduler tự ghi).
    audits = [(a.node, a.action) for a in session.added if isinstance(a, AuditLog)]
    assert ("gate", "auto_reject") in audits


async def test_background_auto_reject_survives_notify_error(monkeypatch) -> None:
    # notify_decision raise (vd audit commit lỗi SAU khi email đã gửi) KHÔNG được reset REJECTED về
    # PENDING_REVIEW — dispatch phải cô lập khỏi handler lỗi kỹ thuật (quyết định đã commit).
    from app.agents.nodes import scheduler
    from app.models.application import Application, ApplicationStatus
    from app.models.job_posting import JobPosting
    from app.tasks import background

    app_row = Application(id=1, applicant_email="me@e.com", job_id=2, status="SUBMITTED")
    job = JobPosting(id=2, title="Backend Intern")
    session = _FakeSession({(Application, 1): app_row, (JobPosting, 2): job})

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _Ctx())
    monkeypatch.setattr(
        background, "run_with_trace",
        lambda **_kw: _await_value(_auto_reject_out(ApplicationStatus.REJECTED.value)),
    )

    async def boom(_session, mode, **kw):  # noqa: ANN001
        raise RuntimeError("audit commit failed after email sent")

    monkeypatch.setattr(scheduler, "notify_decision", boom)

    await background.process_application(1)  # KHÔNG được raise ra ngoài

    assert app_row.status == ApplicationStatus.REJECTED.value  # REJECTED giữ nguyên, KHÔNG reset


async def _await_value(value):
    return value


# ── set_gate_config: bật/tắt gate theo JD (PATCH endpoint) ───────────────────


async def test_set_gate_config_toggles_only_given_field() -> None:
    from app.models.job_posting import JobPosting
    from app.services import job_service

    job = JobPosting(id=2, title="X", gate_config={"auto_reject": False, "auto_invite": False})
    session = _FakeSession({(JobPosting, 2): job})

    out = await job_service.set_gate_config(session, 2, auto_reject=True)

    assert out is job
    assert out.gate_config["auto_reject"] is True
    assert out.gate_config["auto_invite"] is False  # KHÔNG đụng field không truyền
    assert session.commits == 1


async def test_set_gate_config_missing_job_returns_none() -> None:
    from app.services import job_service

    session = _FakeSession({})
    assert await job_service.set_gate_config(session, 999, auto_reject=True) is None
