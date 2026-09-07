"""Bảng đăng ký cấu hình chỉnh được lúc chạy (Cấu hình hệ thống — PRD §NFR-8).

VÌ SAO CÓ FILE NÀY: `Settings` (config.py) là ảnh chụp env lúc import tiến trình — muốn đổi một
ngưỡng phải sửa env rồi deploy lại. Nhưng NFR-8 nói "ngưỡng confidence, mốc nhắc/timeout, bộ câu hỏi
Screener, hai gate — đều cấu hình được". File này khai báo TẬP CON của `Settings` mà HR được phép
đổi từ giao diện, kèm nhãn/giải thích/ràng buộc.

BA QUY TẮC ĐỂ KHÔNG SINH NGUỒN CHÂN LÝ THỨ HAI:

1. **Giá trị mặc định KHÔNG viết lại ở đây** — đọc thẳng từ `Settings.model_fields[name].default`.
   Sửa mặc định thì sửa ở config.py, chỗ này tự theo. Chép tay số mặc định sang đây là cách chắc
   chắn nhất để hai file nói hai con số khác nhau sau vài tháng.
2. **Chỉ khai báo field TUNABLE.** Thứ đọc lúc import (host/port/database_url/cors) hoặc là bí mật
   (api key) KHÔNG bao giờ vào đây — xem `_assert_registry_is_sane()` ở cuối file, nó chặn ngay lúc
   import nếu ai đó lỡ thêm một secret vào.
3. **`hot_reload=False` KHÔNG có nghĩa là "phải khởi động lại"** — nghĩa là "phải xoá cache sau khi
   gán". Xem `app_config_service.invalidate_caches()`. Nhãn này tồn tại để người sửa code sau biết
   field nào có tầng cache ở giữa.

Ràng buộc ở đây là ràng buộc TỪNG Ô. Ràng buộc LIÊN Ô (giờ nghỉ trưa phải nằm trong giờ làm việc,
nhắc phải sớm hơn hạn) do `BookingConfig.validate()` và `app_config_service` lo — xem docstring của
`apply_overrides()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any

from app.core.config import Settings

# Model OpenAI được phép chọn. Cố ý là danh sách ĐÓNG: gõ nhầm tên model chỉ lộ ra lúc có CV thật
# chạy qua (một lỗi 404 từ OpenAI giữa pipeline nền), chứ không lộ lúc bấm Lưu.
_CHAT_MODELS = ("gpt-4.1-mini", "gpt-4.1", "gpt-5-mini", "gpt-5")
_EMBED_MODELS = ("text-embedding-3-small", "text-embedding-3-large")
_EFFORT = ("", "low", "medium", "high")


class ConfigValueError(ValueError):
    """Giá trị người dùng nhập không hợp lệ. Router dịch thành 422 kèm nguyên văn thông điệp."""


@dataclass(frozen=True)
class ConfigField:
    name: str
    group: str
    label: str
    tooltip: str
    kind: str  # int | float | str | bool | enum
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None
    unit: str | None = None
    hot_reload: bool = True
    nullable: bool = False
    # Cảnh báo hiện NGAY dưới ô nhập — dành cho những cấu hình mà giá trị hợp lệ vẫn có thể vô nghĩa.
    warning: str | None = None

    @property
    def default(self) -> Any:
        """Mặc định LẤY TỪ `Settings`, không chép tay. Xem quy tắc 1 ở docstring đầu file."""
        return Settings.model_fields[self.name].get_default(call_default_factory=True)


def _f(**kw: Any) -> ConfigField:
    return ConfigField(**kw)


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# Bảng đăng ký. Thứ tự trong danh sách = thứ tự hiển thị trong nhóm.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
GROUP_ORDER: tuple[str, ...] = (
    "Chấm điểm",
    "Sàng lọc",
    "Đặt lịch",
    "Email",
    "Mô hình AI",
    "Giới hạn an toàn",
    "Vận hành",
    "Xác thực HR",
)

CONFIG_FIELDS: tuple[ConfigField, ...] = (
    # ── Chấm điểm ────────────────────────────────────────────────────────────────────────────────
    _f(
        name="score_pass_threshold", group="Chấm điểm", kind="float", minimum=0, maximum=100,
        label="Điểm đạt (ngưỡng qua vòng CV)",
        tooltip="Hồ sơ từ điểm này trở lên được coi là ĐẠT và đi tiếp sang vòng sàng lọc. Dưới ngưỡng "
                "sẽ cần HR xem xét, hoặc bị từ chối tự động nếu JD đó đã bật gate auto-reject.",
    ),
    _f(
        name="score_near_band", group="Chấm điểm", kind="float", minimum=0, maximum=50, unit="điểm",
        label="Dải điểm 'sát ngưỡng'",
        tooltip="Hồ sơ có điểm cách ngưỡng đạt trong khoảng này sẽ được gắn cờ cảnh báo để HR lưu ý, "
                "vì máy không đủ tự tin để tự quyết.",
    ),
    _f(
        name="confidence_threshold", group="Chấm điểm", kind="float", minimum=0, maximum=1,
        label="Ngưỡng tự tin tối thiểu của AI",
        tooltip="Dưới mức này hệ thống tự nhận là 'không chắc' và chuyển hồ sơ cho HR quyết định, bất "
                "kể điểm cao hay thấp. Tăng số này = nhiều hồ sơ về tay HR hơn.",
    ),
    _f(
        name="ranker_model", group="Chấm điểm", kind="enum", choices=_CHAT_MODELS,
        label="Mô hình chấm điểm hồ sơ",
        tooltip="Model quyết định điểm số của ứng viên. Đây là lựa chọn ảnh hưởng lớn nhất tới chất "
                "lượng lọc CV.",
    ),
    _f(
        name="ranker_reasoning_effort", group="Chấm điểm", kind="enum", choices=_EFFORT, nullable=True,
        label="Mức độ suy luận khi chấm điểm",
        tooltip="Để trống = chấm nhanh, không suy luận. low/medium/high = chấm kỹ hơn, chính xác hơn "
                "nhưng chậm và đắt hơn.",
    ),
    # ── Sàng lọc ─────────────────────────────────────────────────────────────────────────────────
    _f(
        name="screener_deadline_hours", group="Sàng lọc", kind="float", minimum=1, maximum=720, unit="giờ",
        label="Hạn trả lời câu hỏi sàng lọc",
        tooltip="Ứng viên có bao lâu để điền biểu mẫu sàng lọc kể từ lúc nhận email. Hết hạn mà không "
                "trả lời thì hồ sơ về tay HR — KHÔNG bị từ chối tự động.",
    ),
    _f(
        name="screener_reminder_hours", group="Sàng lọc", kind="float", minimum=1, maximum=720, unit="giờ",
        label="Nhắc trả lời sau",
        tooltip="Sau ngần này giờ kể từ lúc GỬI mà ứng viên chưa trả lời, hệ thống gửi MỘT thư nhắc. "
                "Phải nhỏ hơn hạn trả lời, nếu không thư nhắc sẽ không bao giờ kịp gửi.",
    ),
    # ── Đặt lịch ─────────────────────────────────────────────────────────────────────────────────
    _f(
        name="booking_timezone", group="Đặt lịch", kind="str", hot_reload=False,
        label="Múi giờ của công ty",
        tooltip="Mọi giờ hiện cho ứng viên đều quy về múi giờ này. Máy chủ chạy giờ UTC nên đây phải "
                "là giờ làm việc THỰC TẾ của công ty. Cần tên IANA, ví dụ Asia/Ho_Chi_Minh.",
    ),
    _f(
        name="booking_work_days", group="Đặt lịch", kind="str", hot_reload=False,
        label="Ngày làm việc trong tuần",
        tooltip="1 = Thứ Hai … 7 = Chủ Nhật. Nhận dạng '1-5', '1,3,5' hoặc '1-5,7'. Hệ thống chỉ mở "
                "khung phỏng vấn vào những ngày này.",
    ),
    _f(
        name="booking_work_start", group="Đặt lịch", kind="str", hot_reload=False,
        label="Giờ bắt đầu làm việc",
        tooltip="Mốc sớm nhất có thể xếp phỏng vấn trong ngày. Dạng HH:MM.",
    ),
    _f(
        name="booking_work_end", group="Đặt lịch", kind="str", hot_reload=False,
        label="Giờ kết thúc làm việc",
        tooltip="Buổi phỏng vấn phải KẾT THÚC trước mốc này. Kéo dài giờ này là cách hiệu quả nhất để "
                "tăng số khung giờ khả dụng. Dạng HH:MM.",
    ),
    _f(
        name="booking_lunch", group="Đặt lịch", kind="str", hot_reload=False, nullable=True,
        label="Giờ nghỉ trưa",
        tooltip="Không xếp phỏng vấn đè lên khoảng này. Dạng HH:MM-HH:MM và phải nằm trong giờ làm "
                "việc. Để TRỐNG nếu công ty không nghỉ trưa cố định.",
    ),
    _f(
        name="booking_duration_minutes", group="Đặt lịch", kind="int", minimum=1, maximum=480,
        unit="phút", hot_reload=False,
        label="Độ dài một buổi phỏng vấn",
        tooltip="Giảm số này sẽ sinh ra nhiều khung giờ hơn trong cùng một ngày làm việc.",
    ),
    _f(
        name="booking_buffer_minutes", group="Đặt lịch", kind="int", minimum=0, maximum=240,
        unit="phút", hot_reload=False,
        label="Thời gian nghỉ giữa hai buổi",
        tooltip="Khoảng trống để người phỏng vấn nghỉ/ghi chú. Cộng với độ dài buổi sẽ ra bước nhảy "
                "giữa hai mốc giờ.",
    ),
    _f(
        name="booking_lead_time_hours", group="Đặt lịch", kind="float", minimum=0, maximum=720,
        unit="giờ", hot_reload=False,
        label="Báo trước tối thiểu",
        tooltip="Không mời ứng viên vào khung giờ sớm hơn ngần này kể từ lúc họ bấm vào link — họ cần "
                "thời gian thu xếp.",
    ),
    _f(
        name="booking_window_days", group="Đặt lịch", kind="int", minimum=1, maximum=180,
        unit="ngày", hot_reload=False,
        label="Mở lịch trước bao nhiêu ngày",
        tooltip="Ứng viên được chọn giờ trong phạm vi ngần này ngày kể từ hôm nay. Tăng số này là cách "
                "trực tiếp nhất để thêm khung giờ khả dụng.",
    ),
    _f(
        name="booking_slots_offered", group="Đặt lịch", kind="int", minimum=1, maximum=12,
        unit="khung", hot_reload=False,
        label="Số khung giờ đề xuất mỗi lần",
        tooltip="Mỗi lượt ứng viên mở link sẽ thấy ngần này lựa chọn và GIỮ CHỖ cả ngần này khung. Đặt "
                "cao sẽ làm hết lịch khi nhiều người cùng xem.",
    ),
    _f(
        name="booking_max_per_day", group="Đặt lịch", kind="int", minimum=1, maximum=50,
        unit="buổi", hot_reload=False,
        label="Số buổi phỏng vấn tối đa mỗi ngày",
        tooltip="Trần cứng số buổi trong một ngày, áp SAU khi đã sinh lưới giờ.",
        warning="Với giờ làm việc hiện tại, lưới chỉ sinh ra 5 mốc/ngày — nên trần lớn hơn 5 sẽ không "
                "bao giờ chạm tới. Muốn tăng sức chứa thì chỉnh giờ kết thúc làm việc, độ dài buổi "
                "hoặc thời gian nghỉ.",
    ),
    _f(
        name="booking_hold_minutes", group="Đặt lịch", kind="float", minimum=1, maximum=120,
        unit="phút", hot_reload=False,
        label="Thời gian giữ chỗ khi đang chọn",
        tooltip="Khung giờ được giữ tạm trong lúc ứng viên cân nhắc. Hết thời gian này mà chưa xác "
                "nhận thì khung giờ được nhả lại cho người khác.",
    ),
    _f(
        name="booking_link_ttl_hours", group="Đặt lịch", kind="float", minimum=1, maximum=720,
        unit="giờ", hot_reload=False,
        label="Hạn sử dụng link đặt lịch",
        tooltip="Ứng viên có bao lâu để BẮT ĐẦU đặt lịch kể từ khi nhận thư mời. Hết hạn mà chưa đặt "
                "thì hồ sơ về tay HR — KHÔNG bị từ chối tự động.",
    ),
    _f(
        name="booking_interview_reminder_hours", group="Đặt lịch", kind="float", minimum=0, maximum=720,
        unit="giờ", hot_reload=False,
        label="Nhắc trước buổi phỏng vấn",
        tooltip="Gửi MỘT thư nhắc kèm file lịch khi buổi phỏng vấn còn cách ngần này giờ.",
    ),
    _f(
        name="booking_reminder_hours", group="Đặt lịch", kind="float", minimum=0, maximum=720,
        unit="giờ", hot_reload=False,
        label="Nhắc chọn lịch khi link sắp hết hạn",
        tooltip="Đo theo thời gian CÒN LẠI của link — khác với nhắc sàng lọc (cái đó đo từ lúc gửi). "
                "Gửi MỘT lần. Nên nhỏ hơn hạn sử dụng link.",
    ),
    # ── Email ────────────────────────────────────────────────────────────────────────────────────
    _f(
        name="email_from", group="Email", kind="str",
        label="Địa chỉ gửi thư",
        tooltip="Tên người gửi hiện trên thư của ứng viên. Phải thuộc tên miền đã xác thực với Resend, "
                "nếu không thư chỉ gửi được cho chính tài khoản của bạn.",
    ),
    _f(
        name="email_reply_to", group="Email", kind="str", nullable=True,
        label="Địa chỉ nhận thư trả lời",
        tooltip="Khi ứng viên bấm Reply, thư sẽ tới hộp thư này. Để trống thì thư trả lời rơi vào địa "
                "chỉ gửi (thường không ai đọc).",
    ),
    _f(
        name="email_min_interval_ms", group="Email", kind="int", minimum=500, maximum=5000, unit="ms",
        label="Khoảng cách tối thiểu giữa hai thư",
        tooltip="Resend chỉ cho gửi 2 thư mỗi giây. Giảm số này xuống dưới 500 là tự đâm vào giới hạn "
                "của chính mình.",
    ),
    _f(
        name="email_max_retries", group="Email", kind="int", minimum=0, maximum=10, unit="lần",
        label="Số lần gửi lại khi lỗi tạm thời",
        tooltip="Chỉ áp cho lỗi mạng / quá tải. Không áp cho địa chỉ sai định dạng hay khi đã cạn hạn "
                "mức gửi trong ngày.",
    ),
    _f(
        name="resend_webhook_tolerance_seconds", group="Email", kind="float", minimum=30, maximum=3600,
        unit="giây",
        label="Cửa sổ chống phát lại webhook",
        tooltip="Sự kiện có dấu thời gian cũ hơn ngần này sẽ bị từ chối, tránh việc kẻ xấu ghi lại rồi "
                "gửi lại một sự kiện hợp lệ.",
    ),
    _f(
        name="resend_webhook_max_bytes", group="Email", kind="int", minimum=4096, maximum=1048576,
        unit="byte",
        label="Kích thước tối đa một gói webhook",
        tooltip="Gói tin thật của Resend chỉ cỡ 1-2KB. Trần này chặn việc ai đó ném gói hàng chục MB "
                "vào đường công khai không có hạn mức.",
    ),
    # ── Mô hình AI ───────────────────────────────────────────────────────────────────────────────
    _f(
        name="parser_model", group="Mô hình AI", kind="enum", choices=_CHAT_MODELS,
        label="Mô hình trích xuất CV",
        tooltip="Model OpenAI dùng để đọc CV thành dữ liệu có cấu trúc. Đổi sang model mạnh hơn thì "
                "chính xác hơn nhưng đắt và chậm hơn.",
    ),
    _f(
        name="embedding_model", group="Mô hình AI", kind="enum", choices=_EMBED_MODELS,
        label="Mô hình vector hoá JD/CV",
        tooltip="Chỉ đổi khi biết rõ mình đang làm gì.",
        warning="Đổi model này BẮT BUỘC phải đổi cả số chiều vector (EMBEDDING_DIM trong .env) và tạo "
                "collection Qdrant MỚI — kích thước vector là bất biến của collection, dữ liệu cũ "
                "không dùng lại được.",
    ),
    _f(
        name="rubric_suggest_model", group="Mô hình AI", kind="enum", choices=_CHAT_MODELS,
        label="Mô hình gợi ý tiêu chí chấm điểm",
        tooltip="Model dùng khi HR bấm 'AI gợi ý rubric' lúc tạo JD.",
    ),
    _f(
        name="rubric_suggest_reasoning_effort", group="Mô hình AI", kind="enum", choices=_EFFORT,
        nullable=True,
        label="Mức độ suy luận khi gợi ý rubric",
        tooltip="Như mức suy luận của chấm điểm, áp cho phần gợi ý tiêu chí.",
    ),
    _f(
        name="rubric_suggest_max_retries", group="Mô hình AI", kind="int", minimum=1, maximum=20,
        unit="lần",
        label="Số lần được gợi ý rubric mỗi JD",
        tooltip="Giới hạn số lần bấm nút gợi ý cho một tin tuyển dụng (đếm lại từ đầu khi nội dung JD "
                "thay đổi) để tránh tốn chi phí AI.",
    ),
    # ── Giới hạn an toàn ─────────────────────────────────────────────────────────────────────────
    _f(
        name="openai_timeout_seconds", group="Giới hạn an toàn", kind="float", minimum=30, maximum=600,
        unit="giây",
        label="Hạn giờ tối đa cho một lượt gọi AI",
        tooltip="Chặn trường hợp AI treo vô hạn, giữ chỗ trong hàng đợi. Đặt quá thấp sẽ giết cả những "
                "lượt chấm điểm vẫn đang chạy tốt (ranker thật mất khoảng 25 giây).",
    ),
    _f(
        name="parser_max_cv_chars", group="Giới hạn an toàn", kind="int", minimum=200, maximum=500_000,
        unit="ký tự",
        label="Số ký tự tối đa đọc từ một CV",
        tooltip="Chặn chi phí token khi gặp file CV bất thường — một PDF 0.9MB từng trích ra 12,46 "
                "TRIỆU ký tự qua đường công khai. 60.000 ký tự tương đương 20-30 trang A4.",
    ),
    _f(
        name="parser_extract_timeout_seconds", group="Giới hạn an toàn", kind="float", minimum=5,
        maximum=120, unit="giây",
        label="Hạn giờ trích văn bản từ file CV",
        tooltip="Giết tiến trình con khi một file PDF độc hại làm thư viện treo. File hợp lệ nặng nhất "
                "chỉ tốn dưới 1 giây.",
    ),
    _f(
        name="parser_max_cv_uncompressed_bytes", group="Giới hạn an toàn", kind="int",
        minimum=1_048_576, maximum=268_435_456, unit="byte",
        label="Dung lượng DOCX tối đa sau giải nén",
        tooltip="Chặn zip-bomb: một .docx 442KB có thể bung ra 116MB XML làm hết bộ nhớ máy chủ. 32MB "
                "rộng hơn mọi CV thật.",
    ),
    # ── Vận hành ─────────────────────────────────────────────────────────────────────────────────
    _f(
        name="stuck_application_timeout_minutes", group="Vận hành", kind="float", minimum=5,
        maximum=1440, unit="phút",
        label="Coi hồ sơ là 'kẹt' sau",
        tooltip="Hồ sơ còn đứng ở bước đọc CV / chấm điểm quá lâu sẽ được đưa về hàng chờ HR kèm cảnh "
                "báo lỗi kỹ thuật. Phải lớn hơn nhiều thời gian chạy thật (khoảng 35 giây).",
    ),
    # ── Xác thực HR ──────────────────────────────────────────────────────────────────────────────
    _f(
        name="jwt_expiry_minutes", group="Xác thực HR", kind="int", minimum=15, maximum=10_080,
        unit="phút",
        label="Thời gian giữ phiên đăng nhập",
        tooltip="Sau ngần này phút HR phải đăng nhập lại. Mặc định 480 = một ca làm việc 8 tiếng. Đổi "
                "chỉ ảnh hưởng tới phiên MỚI; phiên đang mở giữ hạn cũ.",
    ),
)

FIELDS_BY_NAME: dict[str, ConfigField] = {f.name: f for f in CONFIG_FIELDS}

# Field có tầng cache ở giữa → sau khi gán phải xoá cache, nếu không giá trị mới không tới nơi dùng.
CACHED_FIELDS: frozenset[str] = frozenset(f.name for f in CONFIG_FIELDS if not f.hot_reload)


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# Kiểm giá trị TỪNG Ô
# ──────────────────────────────────────────────────────────────────────────────────────────────────
def coerce(field: ConfigField, raw: Any) -> Any:
    """Ép kiểu + kiểm ràng buộc của MỘT ô. Ném `ConfigValueError` với thông điệp tiếng Việt.

    Nhận `raw` thô từ JSON (str/int/float/None). Chuỗi rỗng ở field `nullable` = "để trống" → None,
    TRỪ `kind="str"` không nullable (chuỗi rỗng ở đó là lỗi nhập chứ không phải ý định xoá).
    """
    label = field.label

    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        if field.nullable:
            # `ranker_reasoning_effort` mặc định "low" nhưng để trống là hợp lệ (= không suy luận).
            return None if field.kind != "enum" else ("" if "" in (field.choices or ()) else None)
        raise ConfigValueError(f"{label}: không được để trống.")

    if field.kind == "enum":
        text = str(raw)
        if text not in (field.choices or ()):
            allowed = ", ".join(repr(c) if c else "(để trống)" for c in field.choices or ())
            raise ConfigValueError(f"{label}: giá trị {text!r} không hợp lệ. Chỉ nhận: {allowed}.")
        return text

    if field.kind == "str":
        text = str(raw).strip()
        if not text:
            raise ConfigValueError(f"{label}: không được để trống.")
        return text

    if field.kind in ("int", "float"):
        try:
            number = int(raw) if field.kind == "int" else float(raw)
        except (TypeError, ValueError):
            kind_vn = "số nguyên" if field.kind == "int" else "số"
            raise ConfigValueError(f"{label}: phải là {kind_vn}, nhận được {raw!r}.") from None
        if field.minimum is not None and number < field.minimum:
            raise ConfigValueError(f"{label}: phải từ {_fmt(field.minimum)} trở lên (nhận {_fmt(number)}).")
        if field.maximum is not None and number > field.maximum:
            raise ConfigValueError(f"{label}: không được vượt {_fmt(field.maximum)} (nhận {_fmt(number)}).")
        return number

    raise ConfigValueError(f"{label}: kiểu {field.kind!r} chưa được hỗ trợ.")


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _assert_registry_is_sane() -> None:
    """Chạy lúc import. Thà nổ ngay khi khởi động còn hơn để một secret lọt lên giao diện.

    Chặn ba lỗi người-sửa-code dễ mắc: khai tên field không có thật trong `Settings` (gõ nhầm sẽ im
    lặng cho tới lúc ai đó bấm Lưu), đưa nhầm secret/bootstrap vào danh sách sửa được, và trùng key.
    """
    forbidden = ("api_key", "secret", "password", "database_url", "token")
    for f in CONFIG_FIELDS:
        if f.name not in Settings.model_fields:
            raise RuntimeError(f"config_registry: {f.name!r} không tồn tại trong Settings.")
        if any(bad in f.name for bad in forbidden):
            raise RuntimeError(f"config_registry: {f.name!r} trông như bí mật — KHÔNG được cho sửa qua giao diện.")
    if len(FIELDS_BY_NAME) != len(CONFIG_FIELDS):
        raise RuntimeError("config_registry: có key trùng nhau.")
    unknown_groups = {f.group for f in CONFIG_FIELDS} - set(GROUP_ORDER)
    if unknown_groups:
        raise RuntimeError(f"config_registry: nhóm chưa khai trong GROUP_ORDER: {sorted(unknown_groups)}")


_assert_registry_is_sane()
