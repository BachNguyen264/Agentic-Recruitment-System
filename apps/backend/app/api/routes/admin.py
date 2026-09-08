"""Cấu hình hệ thống — khu quản trị nội bộ của HR (PRD §NFR-8, §16/NFR-3).

Router này đứng SAU `require_hr` ở cấp router (xem `main.py`) — giống jobs/applications/agents. Không
có endpoint nào ở đây được mở cho ứng viên: nó vừa đọc được toàn bộ nhật ký quyết định, vừa đổi được
ngưỡng chấm điểm của cả hệ thống.

BA NHÓM, cố ý gom một chỗ vì cùng một khán giả (HR ở vai quản trị) và cùng một tần suất (hiếm):
  1. `/admin/config`     — đọc/ghi cấu hình chạy được (bảng `app_config` + lớp phủ lên `settings`).
  2. `/admin/audit-log`  — ĐỌC nhật ký kiểm toán. Trước slice này bảng `audit_log` được 8 service ghi
                           rất dày nhưng KHÔNG có một đường đọc nào — dữ liệu FR-PIPE-4/NFR-3 tích
                           luỹ mà không ai xem được, muốn tra phải vào thẳng Postgres.
  3. Trạng thái hạ tầng  — KHÔNG có endpoint mới: dùng lại `/api/health` + `/api/health/metrics`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentHr, DBSession
from app.core.config_registry import CONFIG_FIELDS, GROUP_ORDER, ConfigValueError
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.schemas.admin import (
    AuditLogItem,
    AuditLogPage,
    ConfigFieldOut,
    ConfigGroupOut,
    ConfigUpdateRequest,
    ConfigUpdateResult,
)
from app.services import app_config_service, audit_service

router = APIRouter(prefix="/admin", tags=["admin"])


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# 1) Cấu hình hệ thống
# ──────────────────────────────────────────────────────────────────────────────────────────────────
@router.get("/config", response_model=list[ConfigGroupOut], summary="Đọc toàn bộ cấu hình sửa được")
async def get_config(session: DBSession) -> list[ConfigGroupOut]:
    """Trả cấu hình theo NHÓM, kèm giá trị hiện tại + mặc định + ràng buộc để giao diện tự dựng form.

    `value` đọc từ `settings` (đã có lớp phủ DB) chứ không đọc lại DB: đó mới là con số mà hệ thống
    ĐANG THỰC SỰ dùng. Nếu một dòng trong DB hỏng và bị bỏ qua lúc khởi động, màn hình phải hiện giá
    trị đang chạy thật, không phải giá trị hỏng nằm trong bảng.
    """
    overrides = await app_config_service.load_overrides(session)
    by_group: dict[str, list[ConfigFieldOut]] = {g: [] for g in GROUP_ORDER}
    for f in CONFIG_FIELDS:
        by_group[f.group].append(
            ConfigFieldOut(
                key=f.name,
                label=f.label,
                tooltip=f.tooltip,
                kind=f.kind,
                value=app_config_service.current_value(f),
                default=f.default,
                minimum=f.minimum,
                maximum=f.maximum,
                choices=list(f.choices) if f.choices else None,
                unit=f.unit,
                nullable=f.nullable,
                warning=f.warning,
                is_overridden=f.name in overrides,
            )
        )
    return [ConfigGroupOut(group=g, fields=by_group[g]) for g in GROUP_ORDER if by_group[g]]


@router.put("/config", response_model=ConfigUpdateResult, summary="Lưu cấu hình")
async def update_config(
    payload: ConfigUpdateRequest, session: DBSession, hr: CurrentHr
) -> ConfigUpdateResult:
    """Lưu một tập cấu hình. Sai một ô là KHÔNG lưu ô nào — xem `app_config_service.apply_overrides`.

    Ghi `audit_log` với `application_id=None` (đây là hành động cấp hệ thống, không thuộc hồ sơ nào)
    và ghi ĐÍCH DANH từng cặp cũ→mới, vì đổi ngưỡng chấm điểm là thứ ảnh hưởng tới MỌI hồ sơ đi qua
    sau đó — sáu tháng sau nhìn lại phải trả lời được "vì sao lô CV tháng 10 rớt nhiều thế".
    """
    if not payload.values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Không có cấu hình nào để lưu.")

    before = {
        key: app_config_service.current_value(f)
        for key in payload.values
        if (f := _field_or_404(key))
    }
    try:
        applied = await app_config_service.save_overrides(
            session, payload.values, hr_user_id=hr.id
        )
    except ConfigValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    changed = {k: v for k, v in applied.items() if v != before.get(k)}
    if changed:
        await audit_service.record(
            session,
            application_id=None,
            node="system",
            action="config_updated",
            detail={
                "by": hr.email,
                "changes": {k: {"from": before.get(k), "to": v} for k, v in changed.items()},
            },
        )
    await session.commit()
    return ConfigUpdateResult(saved=list(applied), changed=list(changed))


@router.delete("/config/{key}", response_model=ConfigUpdateResult, summary="Khôi phục mặc định")
async def reset_config(key: str, session: DBSession, hr: CurrentHr) -> ConfigUpdateResult:
    field = _field_or_404(key)
    before = app_config_service.current_value(field)
    try:
        default = await app_config_service.reset_override(session, key)
    except ConfigValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if before != default:
        await audit_service.record(
            session,
            application_id=None,
            node="system",
            action="config_reset",
            detail={"by": hr.email, "changes": {key: {"from": before, "to": default}}},
        )
    await session.commit()
    return ConfigUpdateResult(saved=[key], changed=[key] if before != default else [])


def _field_or_404(key: str):
    from app.core.config_registry import FIELDS_BY_NAME

    field = FIELDS_BY_NAME.get(key)
    if field is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Không có cấu hình tên {key!r}.")
    return field


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# 2) Nhật ký kiểm toán
# ──────────────────────────────────────────────────────────────────────────────────────────────────
@router.get("/audit-log", response_model=AuditLogPage, summary="Đọc nhật ký kiểm toán")
async def list_audit_log(
    session: DBSession,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    node: str | None = Query(None, description="Lọc theo node: parser|ranker|screener|scheduler|human_review|system"),
    application_id: int | None = Query(None, description="Chỉ lấy nhật ký của một hồ sơ"),
) -> AuditLogPage:
    """Phân trang SERVER, mới nhất trước.

    Sắp theo `(created_at DESC, id DESC)` chứ không chỉ `created_at`: nhiều bản ghi trong cùng một
    pipeline được ghi trong cùng một mili-giây, và offset trên khoá không duy nhất thì trang sau sẽ
    lặp hoặc nuốt dòng. Đây đúng là lỗi AUDIT-1 đã vấp ở danh sách hồ sơ.

    Trần `limit` là 200 vì mỗi dòng chở theo `detail` JSONB có thể khá nặng.
    """
    where = []
    if node:
        where.append(AuditLog.node == node)
    if application_id is not None:
        where.append(AuditLog.application_id == application_id)

    total = (
        await session.execute(select(func.count()).select_from(AuditLog).where(*where))
    ).scalar_one()

    rows = (
        (
            await session.execute(
                select(AuditLog, Application.applicant_email)
                .outerjoin(Application, AuditLog.application_id == Application.id)
                .where(*where)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .all()
    )
    return AuditLogPage(
        total=total,
        limit=limit,
        offset=offset,
        items=[
            AuditLogItem(
                id=log.id,
                application_id=log.application_id,
                applicant_email=email,
                node=log.node,
                action=log.action,
                confidence=log.confidence,
                uncertainty_flags=log.uncertainty_flags or [],
                escalation_reason=log.escalation_reason,
                detail=log.detail or {},
                created_at=log.created_at,
            )
            for log, email in rows
        ],
    )


@router.get("/audit-log/nodes", response_model=dict[str, int], summary="Đếm bản ghi theo node")
async def audit_log_node_counts(session: DBSession) -> dict[str, int]:
    """Nguồn cho bộ lọc: chỉ hiện node THỰC SỰ có dữ liệu, kèm số lượng.

    MỘT câu SQL GROUP BY, payload cỡ cố định — cùng lý do như `/applications/pipeline`: đừng bắt
    giao diện tải cả bảng về rồi tự đếm.
    """
    rows = (
        await session.execute(select(AuditLog.node, func.count()).group_by(AuditLog.node))
    ).all()
    return {node: count for node, count in rows}
