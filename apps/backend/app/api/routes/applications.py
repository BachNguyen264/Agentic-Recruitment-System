"""Routes Application — POST (nộp CV) / GET (đọc). Scaffold: chưa đẩy vào pipeline (Phase 5)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DBSession
from app.schemas.application import ApplicationCreate, ApplicationRead
from app.services import application_service

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
async def create_application(payload: ApplicationCreate, session: DBSession) -> ApplicationRead:
    app_row = await application_service.create_application(session, payload)
    # TODO (Phase 5 · PRD §8.3): đẩy vào xử lý bất đồng bộ bằng BackgroundTasks.
    return ApplicationRead.model_validate(app_row)


@router.get("", response_model=list[ApplicationRead])
async def list_applications(session: DBSession) -> list[ApplicationRead]:
    rows = await application_service.list_applications(session)
    return [ApplicationRead.model_validate(r) for r in rows]


@router.get("/{application_id}", response_model=ApplicationRead)
async def get_application(application_id: int, session: DBSession) -> ApplicationRead:
    app_row = await application_service.get_application(session, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="Application không tồn tại")
    return ApplicationRead.model_validate(app_row)
