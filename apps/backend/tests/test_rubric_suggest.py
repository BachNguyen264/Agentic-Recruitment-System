"""Test JD-3 — AI gợi ý rubric (PRD §12.1 FR-HR-RUBRIC-1, trụ cột 4). MOCK LLM, không gọi API.

Phủ:
  1) Service: mock LLM → list {criterion, weight, reasoning}; PLAIN-TEXT (bóc HTML) vào prompt +
     cấp bậc làm ngữ cảnh; lỗi LLM → RubricSuggestError; build_suggester_chat reasoning vs non-reasoning.
  2) Count/reset (FakeSession): bump +1; update_job reset về 0 khi nội dung JD đổi, GIỮ khi chỉ rubric đổi.
  3) Endpoint (ASGITransport + require_hr): tăng count + trả remaining; cap → 429 (KHÔNG gọi LLM);
     lỗi LLM → 502 (KHÔNG tiêu lượt); JD không có → 404; chưa login → 401.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.core.database import get_session
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.hr_user import HrUser
from app.models.job_posting import JobPosting
from app.schemas.job_posting import GateConfig, JobPostingCreate, RubricCriterion
from app.schemas.rubric_suggest import RubricSuggestion, SuggestedCriterion
from app.services import job_service, rubric_suggester

# ── Fakes ────────────────────────────────────────────────────────────────────


class CapturingLLM:
    """Ghi lại prompt được gửi + trả RubricSuggestion cố định (kiểm plain-text vào LLM)."""

    def __init__(self, result: RubricSuggestion) -> None:
        self._result = result
        self.prompt: str | None = None

    async def ainvoke(self, prompt: str) -> RubricSuggestion:
        self.prompt = prompt
        return self._result


def _suggestion(*pairs: tuple[str, float]) -> RubricSuggestion:
    return RubricSuggestion(
        criteria=[
            SuggestedCriterion(criterion=c, weight=w, reasoning="vì JD nhấn mạnh") for c, w in pairs
        ]
    )


# ── 1) Service (unit, mock LLM) ──────────────────────────────────────────────


async def test_suggest_rubric_returns_criteria_list() -> None:
    llm = CapturingLLM(_suggestion(("Kinh nghiệm Node.js", 0.5), ("Kỹ năng lãnh đạo", 0.3)))
    out = await rubric_suggester.suggest_rubric(
        title="Lead Backend", description="Xây hệ thống", requirements="Node.js", level="lead", llm=llm
    )
    assert [c["criterion"] for c in out] == ["Kinh nghiệm Node.js", "Kỹ năng lãnh đạo"]
    assert [c["weight"] for c in out] == [0.5, 0.3]
    assert all("reasoning" in c for c in out)


async def test_suggest_rubric_strips_html_and_includes_level() -> None:
    # Mô tả/yêu cầu là HTML định dạng → prompt PHẢI là plain-text (không tag) + có nhãn cấp bậc.
    llm = CapturingLLM(_suggestion(("A", 1.0)))
    await rubric_suggester.suggest_rubric(
        title="Senior Dev",
        description="<p>Xây <strong>REST API</strong> async</p>",
        requirements="<ul><li>5+ năm Node.js</li><li>PostgreSQL</li></ul>",
        level="senior",
        llm=llm,
    )
    p = llm.prompt or ""
    assert "<" not in p and ">" not in p  # KHÔNG còn tag HTML
    assert "strong" not in p and "<li>" not in p
    assert "REST API async" in p  # nội dung plain-text giữ nguyên
    assert "5+ năm Node.js" in p
    assert "Senior" in p  # cấp bậc làm ngữ cảnh (nhãn _LEVEL_LABELS)


async def test_suggest_rubric_llm_error_raises() -> None:
    class BoomLLM:
        async def ainvoke(self, _prompt):
            raise RuntimeError("OpenAI down")

    with pytest.raises(rubric_suggester.RubricSuggestError):
        await rubric_suggester.suggest_rubric(
            title="X", description="d", requirements="r", level=None, llm=BoomLLM()
        )


def test_build_suggester_chat_reasoning_vs_non_reasoning(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "rubric_suggest_model", "gpt-5-mini")
    monkeypatch.setattr(settings, "rubric_suggest_reasoning_effort", "low")
    chat = rubric_suggester.build_suggester_chat()
    assert chat.reasoning_effort == "low"
    assert chat.temperature != 0  # reasoning: temperature bị bỏ (None), KHÔNG phải 0

    monkeypatch.setattr(settings, "rubric_suggest_model", "gpt-4.1")
    monkeypatch.setattr(settings, "rubric_suggest_reasoning_effort", None)
    chat2 = rubric_suggester.build_suggester_chat()
    assert chat2.temperature == 0  # non-reasoning: temperature=0


# ── 2) Count + reset (FakeSession, không DB) ─────────────────────────────────


class FakeSession:
    def __init__(self, job: JobPosting | None) -> None:
        self._job = job
        self.commits = 0

    async def get(self, _model, pk):  # noqa: ANN001
        return self._job if (self._job is not None and self._job.id == pk) else None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass

    async def refresh(self, _obj) -> None:
        pass


def _job(**overrides) -> JobPosting:
    base = dict(
        id=1,
        title="Backend Intern (Node.js)",
        description="Xây REST API cho hệ thống đặt vé.",
        requirements="Node.js\nExpress\nMongoDB",
        level="junior",
        salary=None,
        benefits=None,
        employment_type=None,
        rubric=[{"criterion": "Kinh nghiệm Node.js", "weight": 0.6},
                {"criterion": "Hiểu biết DB", "weight": 0.4}],
        screener_questions=["Mức lương kỳ vọng?"],
        gate_config={"auto_reject": False, "auto_invite": False},
        status="OPEN",
        embedding_ref="point-old",
        rubric_suggestion_count=2,
    )
    base.update(overrides)
    return JobPosting(**base)


def _payload(**overrides) -> JobPostingCreate:
    base = dict(
        title="Backend Intern (Node.js)",
        description="Xây REST API cho hệ thống đặt vé.",
        requirements="Node.js\nExpress\nMongoDB",
        rubric=[RubricCriterion(criterion="Kinh nghiệm Node.js", weight=0.6),
                RubricCriterion(criterion="Hiểu biết DB", weight=0.4)],
        screener_questions=["Mức lương kỳ vọng?"],
        gate_config=GateConfig(auto_reject=False, auto_invite=False),
    )
    base.update(overrides)
    return JobPostingCreate(**base)


async def test_bump_increments_count() -> None:
    job = _job(rubric_suggestion_count=1)
    out = await job_service.bump_rubric_suggestion_count(FakeSession(job), 1)
    assert out.rubric_suggestion_count == 2


async def test_bump_missing_job_returns_none() -> None:
    assert await job_service.bump_rubric_suggestion_count(FakeSession(None), 999) is None


def _mock_embed(monkeypatch) -> None:
    async def fake_embed(_text: str) -> list[float]:
        return [0.0] * 1536

    async def fake_upsert(job_id: int, vector, *, title: str) -> str:
        return "point-new"

    monkeypatch.setattr(job_service, "embed_text", fake_embed)
    monkeypatch.setattr(job_service.qdrant_service, "upsert_jd", fake_upsert)


async def test_update_job_resets_count_when_content_changes(monkeypatch) -> None:
    _mock_embed(monkeypatch)
    job = _job(rubric_suggestion_count=3)
    await job_service.update_job(
        FakeSession(job), 1, _payload(description="Mô tả MỚI hoàn toàn khác.")
    )
    assert job.rubric_suggestion_count == 0  # nội dung đổi → reset cap gợi ý


async def test_update_job_keeps_count_when_only_rubric_changes(monkeypatch) -> None:
    _mock_embed(monkeypatch)
    job = _job(rubric_suggestion_count=3)
    await job_service.update_job(
        FakeSession(job), 1,
        _payload(rubric=[RubricCriterion(criterion="Kinh nghiệm Node.js", weight=1.0)]),
    )
    assert job.rubric_suggestion_count == 3  # chỉ rubric đổi → lưu cấu hình KHÔNG tiêu lượt


# ── 3) Endpoint (ASGITransport + require_hr) ─────────────────────────────────


class EndpointSession:
    """Phục vụ cả require_hr (get HrUser) lẫn handler (get JobPosting) + commit/refresh."""

    def __init__(self, *, job: JobPosting | None, user: HrUser | None) -> None:
        self._job = job
        self._user = user
        self.commits = 0

    async def get(self, model, pk):  # noqa: ANN001
        if model is HrUser:
            return self._user if (self._user and self._user.id == pk) else None
        if model is JobPosting:
            return self._job if (self._job and self._job.id == pk) else None
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj) -> None:
        pass

    async def rollback(self) -> None:
        pass


def _user() -> HrUser:
    u = HrUser(email="admin@ars.local", password_hash=hash_password("Correct1!"))
    u.id = 1
    return u


def _client(session: EndpointSession) -> httpx.AsyncClient:
    async def _fake_session():
        yield session

    app.dependency_overrides[get_session] = _fake_session
    transport = httpx.ASGITransport(app=app)  # KHÔNG chạy lifespan → không chạm Neon.
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _authed(c: httpx.AsyncClient) -> None:
    c.cookies.set(settings.auth_cookie_name, create_access_token("1"))


async def test_endpoint_suggests_and_increments(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rubric_suggest_max_retries", 3)

    async def fake_suggest(**_kwargs):
        return [{"criterion": "Kinh nghiệm Node.js", "weight": 0.6, "reasoning": "JD nhấn mạnh"}]

    monkeypatch.setattr(rubric_suggester, "suggest_rubric", fake_suggest)
    session = EndpointSession(job=_job(rubric_suggestion_count=0), user=_user())
    async with _client(session) as c:
        _authed(c)
        r = await c.post("/api/jobs/1/suggest-rubric")
    assert r.status_code == 200
    body = r.json()
    assert body["criteria"][0]["criterion"] == "Kinh nghiệm Node.js"
    assert body["used"] == 1
    assert body["remaining"] == 2


async def test_endpoint_cap_blocks_429_without_calling_llm(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rubric_suggest_max_retries", 3)
    called = {"llm": False}

    async def spy_suggest(**_kwargs):
        called["llm"] = True
        return []

    monkeypatch.setattr(rubric_suggester, "suggest_rubric", spy_suggest)
    session = EndpointSession(job=_job(rubric_suggestion_count=3), user=_user())
    async with _client(session) as c:
        _authed(c)
        r = await c.post("/api/jobs/1/suggest-rubric")
    assert r.status_code == 429
    assert called["llm"] is False  # cap chặn TRƯỚC khi gọi LLM
    assert "hết lượt" in r.json()["detail"].lower()


async def test_endpoint_llm_error_502_no_count_bump(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rubric_suggest_max_retries", 3)

    async def boom_suggest(**_kwargs):
        raise rubric_suggester.RubricSuggestError("OpenAI down")

    monkeypatch.setattr(rubric_suggester, "suggest_rubric", boom_suggest)
    session = EndpointSession(job=_job(rubric_suggestion_count=0), user=_user())
    async with _client(session) as c:
        _authed(c)
        r = await c.post("/api/jobs/1/suggest-rubric")
    assert r.status_code == 502
    assert session.commits == 0  # KHÔNG tiêu lượt khi LLM lỗi


async def test_endpoint_404_missing_job(monkeypatch) -> None:
    async def fake_suggest(**_kwargs):
        return []

    monkeypatch.setattr(rubric_suggester, "suggest_rubric", fake_suggest)
    session = EndpointSession(job=None, user=_user())
    async with _client(session) as c:
        _authed(c)
        r = await c.post("/api/jobs/999/suggest-rubric")
    assert r.status_code == 404


async def test_endpoint_requires_auth_401() -> None:
    session = EndpointSession(job=_job(), user=_user())
    async with _client(session) as c:  # KHÔNG set cookie
        r = await c.post("/api/jobs/1/suggest-rubric")
    assert r.status_code == 401
