"""Lớp phủ cấu hình DB → `Settings` (PRD §NFR-8).

CƠ CHẾ, và vì sao nó rẻ đến mức này: `settings` là một object pydantic MUTABLE (`model_config` không
đặt `frozen=True`), nên `settings.score_pass_threshold = 70` có hiệu lực NGAY cho mọi chỗ đọc
`settings.score_pass_threshold` về sau. Nhờ vậy KHÔNG phải sửa hơn 100 điểm đọc rải khắp backend —
chỉ cần nạp DB rồi gán đè, một lần lúc khởi động và một lần sau mỗi lần HR bấm Lưu.

Cái giá của sự rẻ đó là hai cái bẫy, và cả hai đều được xử ở file này:

  BẪY 1 — `validate_assignment` KHÔNG bật, nên gán giá trị sai kiểu sẽ KHÔNG bị pydantic chặn.
  Một chuỗi "abc" gán vào `score_pass_threshold` sẽ nằm im cho tới khi có CV thật chạy qua rồi nổ
  giữa pipeline nền. Vì vậy MỌI giá trị phải đi qua `config_registry.coerce()` TRƯỚC khi gán.

  BẪY 2 — bốn `@lru_cache` đóng băng 24 field. Nặng nhất là `load_booking_config()`: nó cache CẢ 14
  biến BOOKING_*, và trong toàn bộ mã sản phẩm KHÔNG có một lời gọi `cache_clear()` nào (chỉ test
  gọi). Không xoá cache thì HR đổi giờ làm việc xong, lưới khung giờ vẫn sinh theo cấu hình cũ cho
  tới lần khởi động lại — mà giao diện thì đã báo "đã lưu". Xem `invalidate_caches()`.

  Kèm một lệch NGẦM mà bẫy 2 che mất: `booking_timezone` được đọc ở HAI đường — qua
  `load_booking_config()` (có cache) và THẲNG từ `settings` ở `email_templates`. Nếu chỉ gán mà
  không xoá cache, email sẽ hiện múi giờ MỚI trong khi khung giờ vẫn sinh theo múi giờ CŨ. Xoá cache
  làm hai đường khớp lại.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.config_registry import (
    CONFIG_FIELDS,
    FIELDS_BY_NAME,
    ConfigField,
    ConfigValueError,
    coerce,
)
from app.core.logging import get_logger
from app.models.app_config import AppConfig

logger = get_logger("app.config")


def invalidate_caches() -> None:
    """Xoá mọi `@lru_cache` đang giữ ảnh chụp của `settings`. Xem BẪY 2 ở docstring đầu file.

    Import TRONG hàm, không phải ở đầu file: `booking_config` và `calendar` import ngược lại
    `settings`, còn service này được `main.py` gọi lúc lifespan — import vòng ở cấp module sẽ làm
    thứ tự nạp phụ thuộc vào việc ai import ai trước.
    """
    from app.services.booking_config import load_booking_config
    from app.services.calendar import get_calendar_provider

    load_booking_config.cache_clear()
    get_calendar_provider.cache_clear()


def current_value(field: ConfigField) -> Any:
    return getattr(settings, field.name)


def _assign(field: ConfigField, value: Any) -> None:
    setattr(settings, field.name, value)


def _validate_cross_field() -> None:
    """Ràng buộc LIÊN Ô — thứ `coerce()` không thể biết vì nó chỉ nhìn một ô.

    Phần đặt lịch KHÔNG kiểm lại bằng tay: gọi thẳng `load_booking_config()` (sau khi đã xoá cache)
    để dùng LẠI đúng bộ kiểm mà lưới khung giờ dùng thật — giờ nghỉ trưa nằm trong giờ làm, giờ bắt
    đầu trước giờ kết thúc, buổi phỏng vấn không dài hơn cả ngày làm việc. Viết lại bộ kiểm đó ở đây
    là tạo ra cơ hội cho hai bộ luật lệch nhau.
    """
    from app.services.booking_config import BookingConfigError, load_booking_config

    try:
        load_booking_config()
    except BookingConfigError as exc:
        raise ConfigValueError(f"Cấu hình đặt lịch không hợp lệ: {exc}") from exc

    if settings.screener_reminder_hours >= settings.screener_deadline_hours:
        raise ConfigValueError(
            f"'Nhắc trả lời sau' ({settings.screener_reminder_hours} giờ) phải NHỎ HƠN 'Hạn trả lời "
            f"câu hỏi sàng lọc' ({settings.screener_deadline_hours} giờ) — đặt bằng hoặc lớn hơn thì "
            "thư nhắc không bao giờ kịp gửi."
        )


def apply_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """Kiểm + gán một tập cấu hình lên `settings`. Trả về map {key: giá trị đã ép kiểu}.

    NGUYÊN TỬ: nếu bất kỳ ô nào sai, hoặc ràng buộc liên ô vỡ, TOÀN BỘ được hoàn về giá trị trước đó
    rồi mới ném lỗi. Không có chuyện gán được nửa chừng — nửa chừng ở đây nghĩa là lưới khung giờ
    chạy với giờ bắt đầu mới nhưng giờ kết thúc cũ.

    Khoá lạ (không có trong bảng đăng ký) bị BỎ QUA kèm cảnh báo, không ném lỗi: đó là dòng cấu hình
    còn sót trong DB sau khi ai đó xoá một field khỏi code, và nó không được phép chặn khởi động.
    """
    snapshot = {f.name: current_value(f) for f in CONFIG_FIELDS}
    applied: dict[str, Any] = {}
    try:
        for key, value in raw.items():
            field = FIELDS_BY_NAME.get(key)
            if field is None:
                logger.warning("Bỏ qua cấu hình lạ trong DB: %s (không có trong bảng đăng ký)", key)
                continue
            applied[key] = coerce(field, value)
            _assign(field, applied[key])
        invalidate_caches()
        _validate_cross_field()
    except Exception:
        for name, old in snapshot.items():
            setattr(settings, name, old)
        invalidate_caches()
        raise
    return applied


async def load_overrides(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.execute(select(AppConfig))).scalars().all()
    return {row.key: row.value for row in rows}


async def apply_from_db(session: AsyncSession) -> int:
    """Nạp DB → gán lên `settings`. Gọi lúc lifespan và sau mỗi lần lưu. Trả số cấu hình đã áp.

    KHÔNG BAO GIỜ ném: cấu hình hỏng trong DB không được phép làm backend không khởi động nổi. Hỏng
    thì chạy tiếp bằng mặc định của code và hét vào log — mặc định luôn là một cấu hình chạy được.
    """
    try:
        overrides = await load_overrides(session)
        if not overrides:
            return 0
        applied = apply_overrides(overrides)
        logger.info("Đã áp %d cấu hình từ DB: %s", len(applied), ", ".join(sorted(applied)))
        return len(applied)
    except Exception as exc:  # noqa: BLE001 — chạy bằng mặc định còn hơn không khởi động được
        logger.error(
            "KHÔNG áp được cấu hình từ DB (%s: %s) — chạy bằng mặc định trong code. "
            "Vào Cấu hình hệ thống sửa lại giá trị sai hoặc bấm Khôi phục mặc định.",
            type(exc).__name__,
            exc,
        )
        return 0


async def save_overrides(
    session: AsyncSession, updates: dict[str, Any], *, hr_user_id: int | None
) -> dict[str, Any]:
    """Kiểm → áp vào tiến trình → ghi DB. Trả về map {key: giá trị đã ép kiểu} đã lưu.

    THỨ TỰ CÓ CHỦ Ý: áp vào `settings` TRƯỚC, ghi DB SAU. Nếu giá trị mới làm vỡ ràng buộc thì
    `apply_overrides` đã tự hoàn tác và ném ra — DB chưa hề bị đụng tới. Ngược lại (ghi DB trước)
    sẽ để lại một hàng độc trong bảng, và lần khởi động sau nó lại được nạp lên.

    Giá trị TRÙNG mặc định thì XOÁ hàng thay vì lưu — xem docstring của model `AppConfig`.
    Caller ghi `audit_log`; service này không ghi để không phải kéo theo `application_id`.
    """
    applied = apply_overrides(updates)
    for key, value in applied.items():
        if value == FIELDS_BY_NAME[key].default:
            await session.execute(delete(AppConfig).where(AppConfig.key == key))
            continue
        row = await session.get(AppConfig, key)
        if row is None:
            session.add(AppConfig(key=key, value=value, updated_by=hr_user_id))
        else:
            row.value = value
            row.updated_by = hr_user_id
    await session.flush()
    return applied


async def reset_override(session: AsyncSession, key: str) -> Any:
    """Trả MỘT cấu hình về mặc định: xoá hàng DB + gán lại giá trị mặc định vào `settings`."""
    field = FIELDS_BY_NAME.get(key)
    if field is None:
        raise ConfigValueError(f"Không có cấu hình tên {key!r}.")
    await session.execute(delete(AppConfig).where(AppConfig.key == key))
    apply_overrides({key: field.default})
    await session.flush()
    return field.default
