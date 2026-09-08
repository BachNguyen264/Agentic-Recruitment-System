"""Cấu hình hệ thống sửa được lúc chạy (PRD §NFR-8).

Mỗi test ở đây bảo vệ một cái bẫy CỤ THỂ mà kiểm kê cấu hình đã tìm ra, không phải kiểm "hàm chạy
không lỗi". Xem docstring của `app_config_service` để biết bối cảnh từng bẫy.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings, settings
from app.core.config_registry import (
    CACHED_FIELDS,
    CONFIG_FIELDS,
    FIELDS_BY_NAME,
    GROUP_ORDER,
    ConfigValueError,
    coerce,
)
from app.services import app_config_service as svc
from app.services.booking_config import load_booking_config


@pytest.fixture(autouse=True)
def _restore_settings():
    """Trả `settings` về nguyên trạng sau mỗi test — nó là singleton TOÀN CỤC của tiến trình.

    Không có fixture này thì một test đổi ngưỡng điểm sẽ làm hỏng mọi test chạy sau nó, và hỏng theo
    kiểu phụ thuộc thứ tự chạy — loại lỗi tốn nhiều giờ nhất để tìm.
    """
    before = {f.name: getattr(settings, f.name) for f in CONFIG_FIELDS}
    yield
    for name, value in before.items():
        setattr(settings, name, value)
    svc.invalidate_caches()


# ── Bảng đăng ký ──────────────────────────────────────────────────────────────────────────────────
def test_registry_never_exposes_secrets_or_bootstrap_fields() -> None:
    """Không một bí mật hay cấu hình khởi động nào được lọt lên giao diện HR.

    `_assert_registry_is_sane()` đã chặn lúc import, nhưng nó chặn theo TÊN. Test này chặn theo DANH
    SÁCH: đây là những field mà đổi lúc chạy hoặc là vô nghĩa (đã đọc xong lúc import) hoặc là lỗ
    hổng (bí mật hiện trên màn hình ai cũng xem được).
    """
    forbidden = {
        "openai_api_key", "resend_api_key", "jwt_secret", "qdrant_api_key",
        "resend_webhook_secret", "r2_access_key_id", "r2_secret_access_key",
        "hr_admin_password", "hr_admin_email",
        "database_url", "checkpointer_database_url", "host", "port", "app_env",
        "cors_origins", "cookie_secure", "cookie_samesite", "cookie_domain",
        "storage_backend", "cv_upload_dir", "enable_llm", "enable_dev_endpoints",
        "rate_limit_enabled", "max_request_bytes", "trust_proxy_headers",
    }
    assert not (forbidden & set(FIELDS_BY_NAME)), (
        "Field bí mật/bootstrap lọt vào bảng cấu hình sửa được: "
        f"{sorted(forbidden & set(FIELDS_BY_NAME))}"
    )


def test_every_registered_field_exists_in_settings_and_has_a_group() -> None:
    for f in CONFIG_FIELDS:
        assert f.name in Settings.model_fields, f"{f.name} không có trong Settings"
        assert f.group in GROUP_ORDER, f"{f.name} thuộc nhóm lạ {f.group!r}"
        assert f.label and f.tooltip, f"{f.name} thiếu nhãn hoặc giải thích"


def test_default_is_read_from_settings_not_copied() -> None:
    """Mặc định phải DẪN XUẤT từ `Settings`, không chép tay — nếu không hai file sẽ lệch nhau.

    Kiểm bằng cách sửa mặc định trong `Settings.model_fields` rồi xem bảng đăng ký có theo không.
    """
    field = FIELDS_BY_NAME["score_pass_threshold"]
    assert field.default == Settings.model_fields["score_pass_threshold"].default

    original = Settings.model_fields["score_pass_threshold"].default
    Settings.model_fields["score_pass_threshold"].default = 77.0
    try:
        assert field.default == 77.0, "bảng đăng ký đang chép tay giá trị mặc định"
    finally:
        Settings.model_fields["score_pass_threshold"].default = original


# ── BẪY 1: validate_assignment KHÔNG bật ─────────────────────────────────────────────────────────
def test_pydantic_does_not_validate_assignment_so_coerce_must() -> None:
    """Chứng minh vì sao `coerce()` là bắt buộc, không phải phòng xa.

    `Settings` không đặt `validate_assignment`, nên gán thẳng một chuỗi vào ô số KHÔNG bị pydantic
    chặn — nó nằm im tới lúc có CV thật chạy qua rồi nổ giữa pipeline nền. Nếu một ngày ai đó bật
    `validate_assignment=True` thì test này đỏ, và đó là tin TỐT: lúc đó `coerce` có thêm một lưới
    thứ hai đỡ phía sau.
    """
    settings.score_pass_threshold = "rác"  # type: ignore[assignment]
    assert settings.score_pass_threshold == "rác", (
        "pydantic nay đã chặn gán sai kiểu — cập nhật lại docstring của app_config_service"
    )


@pytest.mark.parametrize(
    "key, bad",
    [
        ("score_pass_threshold", "abc"),
        ("score_pass_threshold", 150),      # vượt trần 100
        ("score_pass_threshold", -1),       # dưới sàn 0
        ("booking_slots_offered", 99),      # vượt trần 12
        ("ranker_model", "gpt-4o-mini"),    # không có trong danh sách đóng
        ("email_min_interval_ms", 100),     # dưới 500 = tự đâm vào hạn mức Resend
        ("email_from", ""),                 # không nullable
    ],
)
def test_coerce_rejects_bad_values(key: str, bad: object) -> None:
    with pytest.raises(ConfigValueError):
        coerce(FIELDS_BY_NAME[key], bad)


def test_coerce_accepts_empty_for_nullable_fields() -> None:
    assert coerce(FIELDS_BY_NAME["email_reply_to"], "") is None
    assert coerce(FIELDS_BY_NAME["booking_lunch"], "") is None


# ── BẪY 2: @lru_cache đóng băng cấu hình đặt lịch ─────────────────────────────────────────────────
def test_changing_work_hours_actually_reaches_the_slot_grid() -> None:
    """Cái bẫy đắt nhất: `load_booking_config()` có `@lru_cache` và mã sản phẩm KHÔNG hề gọi
    `cache_clear()` ở đâu (trước slice này chỉ test gọi).

    Không có `invalidate_caches()` thì HR đổi giờ làm việc, giao diện báo "đã lưu", mà lưới khung giờ
    vẫn sinh theo giờ CŨ cho tới lần khởi động lại. Sai lặng lẽ, và chỉ lộ ra khi ứng viên phàn nàn
    không có khung giờ nào phù hợp.
    """
    assert load_booking_config().work_end.hour == 17
    svc.apply_overrides({"booking_work_end": "20:00"})
    assert load_booking_config().work_end.hour == 20, "cache chưa được xoá — giá trị mới không tới nơi dùng"


def test_booking_timezone_has_no_silent_skew_between_email_and_grid() -> None:
    """`booking_timezone` được đọc ở HAI đường: qua `load_booking_config()` (có cache) và THẲNG từ
    `settings` ở `email_templates`. Nếu chỉ gán mà không xoá cache, email hiện múi giờ MỚI còn khung
    giờ vẫn sinh theo múi giờ CŨ — lệch ngầm, rất khó phát hiện.
    """
    svc.apply_overrides({"booking_timezone": "Asia/Tokyo"})
    assert str(load_booking_config().tz) == "Asia/Tokyo"
    assert settings.booking_timezone == "Asia/Tokyo"


def test_every_cached_field_is_marked_hot_reload_false() -> None:
    """Bảng đăng ký phải biết field nào có tầng cache. Thêm field BOOKING_* mới mà quên đánh dấu thì
    test này đỏ — chứ không phải người dùng phát hiện hộ sau vài tuần."""
    booking_fields = {f.name for f in CONFIG_FIELDS if f.name.startswith("booking_")}
    assert booking_fields <= CACHED_FIELDS


# ── Ràng buộc liên ô + tính nguyên tử ────────────────────────────────────────────────────────────
def test_lunch_outside_work_hours_is_rejected_by_booking_own_validator() -> None:
    with pytest.raises(ConfigValueError, match="đặt lịch không hợp lệ"):
        svc.apply_overrides({"booking_work_start": "14:00"})


def test_reminder_must_be_earlier_than_deadline() -> None:
    with pytest.raises(ConfigValueError, match="NHỎ HƠN"):
        svc.apply_overrides({"screener_reminder_hours": 100})


def test_a_rejected_batch_leaves_nothing_applied() -> None:
    """NGUYÊN TỬ. Gán được nửa chừng ở đây nghĩa là lưới khung giờ chạy với giờ bắt đầu MỚI nhưng giờ
    kết thúc CŨ — một cấu hình chưa từng ai chọn."""
    before_start = settings.booking_work_start
    before_score = settings.score_pass_threshold
    with pytest.raises(ConfigValueError):
        svc.apply_overrides({"score_pass_threshold": 75, "booking_work_start": "14:00"})
    assert settings.booking_work_start == before_start
    assert settings.score_pass_threshold == before_score, (
        "ô hợp lệ vẫn bị gán dù cả lô bị từ chối — apply_overrides không nguyên tử"
    )
    # Và cache cũng phải được dựng lại từ giá trị ĐÃ HOÀN TÁC, không giữ ảnh chụp giữa chừng.
    assert f"{load_booking_config().work_start:%H:%M}" == before_start


def test_unknown_key_is_skipped_not_fatal() -> None:
    """Dòng cấu hình còn sót trong DB sau khi ai đó xoá field khỏi code KHÔNG được phép chặn khởi động."""
    applied = svc.apply_overrides({"field_da_bi_xoa_tu_doi_truoc": 1, "score_pass_threshold": 70})
    assert applied == {"score_pass_threshold": 70.0}
    assert settings.score_pass_threshold == 70.0
