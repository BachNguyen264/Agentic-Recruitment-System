"""Test EMAIL-1 — webhook Resend: chữ ký, miễn trừ middleware, idempotent, bảng xử lý bounce.

Webhook là endpoint CÔNG KHAI CÓ MUTATION: không verify chữ ký thì bất kỳ ai cũng giả được sự kiện
bounce và phá hồ sơ của ứng viên thật. Đây là phần được test kỹ nhất của lát này.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

from app.core.webhook_signature import sign_svix_payload, verify_svix_signature

_SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"  # khoá mẫu của Svix docs — KHÔNG phải secret thật
_ID = "msg_2b3c"
_TS = "1786000000"
_NOW = 1786000000.0
_BODY = b'{"type":"email.bounced","data":{"email_id":"e_1"}}'


def _sig() -> str:
    return sign_svix_payload(secret=_SECRET, msg_id=_ID, timestamp=_TS, body=_BODY)


def _verify(**over) -> bool:  # noqa: ANN003
    kw = dict(
        secret=_SECRET, msg_id=_ID, timestamp=_TS, signature_header=_sig(),
        body=_BODY, now=_NOW, tolerance_seconds=300.0,
    )
    kw.update(over)
    return verify_svix_signature(**kw)


def test_valid_signature_passes() -> None:
    assert _verify() is True


def test_tampered_body_fails() -> None:
    assert _verify(body=b'{"type":"email.bounced","data":{"email_id":"e_HACKED"}}') is False


def test_wrong_secret_fails() -> None:
    assert _verify(secret="whsec_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=") is False


def test_missing_signature_fails() -> None:
    assert _verify(signature_header="") is False


def test_replay_outside_tolerance_fails() -> None:
    """Chữ ký ĐÚNG nhưng cũ: kẻ chặn được một request hợp lệ sẽ phát lại nó mãi mãi nếu không chặn."""
    assert _verify(now=_NOW + 301.0) is False
    assert _verify(now=_NOW - 301.0) is False


def test_within_tolerance_passes() -> None:
    assert _verify(now=_NOW + 299.0) is True


def test_garbage_timestamp_fails() -> None:
    assert _verify(timestamp="không-phải-số") is False


def test_accepts_any_matching_version_in_multi_signature_header() -> None:
    """Svix gửi NHIỀU chữ ký khi đang xoay khoá — khớp một cái là đủ."""
    header = f"v1,khongphaichuky {_sig()}"
    assert _verify(signature_header=header) is True


def test_ignores_unknown_signature_version() -> None:
    assert _verify(signature_header="v2,YWJj") is False


# --- Vòng sửa sau security review (opus, security-auditor, "Not approved") ---------------------
#
# Bài học của vòng review: khẳng định "mọi ca bất thường → False" trong report trước ĐƯỢC RÚT RA
# TỪ ĐỌC CODE, không phải từ chạy thử — reviewer fuzz thì 4/23 ca nổ exception thật. Các test dưới
# đây khoá lại đúng những ca đã nổ, và 3 test cuối khoá lại thuật toán (không chỉ hành vi bên ngoài)
# vì `sign_svix_payload`/`verify_svix_signature` dùng chung `_digest` — một lỗi trong cách dựng
# `signed_content` (ví dụ bỏ sót `msg_id`) sẽ khiến hai hàm tự khớp nhau và MỌI test trên vẫn xanh.


def test_empty_secret_fails() -> None:
    """CRITICAL: `base64.b64decode("", validate=True)` trả `b''` HỢP LỆ (không ném) — secret rỗng
    phải bị chặn TRƯỚC khi decode, không thì HMAC chạy bình thường với khoá RỖNG mà kẻ tấn công
    cũng biết trước (ca thật: `RESEND_WEBHOOK_SECRET` chưa set trên Render). Tự dựng chữ ký bằng
    khoá rỗng THẲNG bằng hmac/hashlib (KHÔNG qua `sign_svix_payload` — hàm đó CỐ Ý raise khi secret
    rỗng vì nó là helper dựng dữ liệu test hợp lệ, không phải đường cần test ở đây)."""
    signed = f"{_ID}.{_TS}".encode() + b"." + _BODY
    forged = "v1," + base64.b64encode(hmac.new(b"", signed, hashlib.sha256).digest()).decode()
    assert (
        verify_svix_signature(
            secret="", msg_id=_ID, timestamp=_TS, signature_header=forged,
            body=_BODY, now=_NOW, tolerance_seconds=300.0,
        )
        is False
    )


def test_secret_with_only_whsec_prefix_fails() -> None:
    """Cùng lỗ hổng CRITICAL, qua đường khác: đúng tiền tố `whsec_` nhưng KHÔNG có phần thân —
    sau khi cắt tiền tố cũng ra chuỗi rỗng, phải bị chặn giống hệt secret rỗng ở trên."""
    signed = f"{_ID}.{_TS}".encode() + b"." + _BODY
    forged = "v1," + base64.b64encode(hmac.new(b"", signed, hashlib.sha256).digest()).decode()
    assert (
        verify_svix_signature(
            secret="whsec_", msg_id=_ID, timestamp=_TS, signature_header=forged,
            body=_BODY, now=_NOW, tolerance_seconds=300.0,
        )
        is False
    )


def test_non_ascii_signature_header_fails() -> None:
    """`hmac.compare_digest` trên kiểu `str` bắt buộc ASCII-only — Starlette decode header theo
    latin-1 nên `svix-signature: v1,café` từng ném `TypeError` (⇒ 500) thay vì trả `False` (⇒ 401)."""
    assert _verify(signature_header="v1,café") is False


def test_huge_timestamp_fails() -> None:
    """`int("9"*400)` THÀNH CÔNG (dưới ngưỡng 4300 chữ số của Python 3.11+), rồi `now - sent_at`
    từng ném `OverflowError` — attacker điều khiển hoàn toàn giá trị `svix-timestamp`."""
    assert _verify(timestamp="9" * 400) is False


def test_none_msg_id_fails() -> None:
    """Task sau đọc header thiếu bằng `request.headers.get("svix-id")` → `None` — từng ném
    `AttributeError` khi gọi `.encode()` trên `None`."""
    assert _verify(msg_id=None) is False  # type: ignore[arg-type]


def test_none_body_fails() -> None:
    """Cùng lý do — body rỗng/thiếu ở tầng request từng ném `TypeError` trong `bytes.join`."""
    assert _verify(body=None) is False  # type: ignore[arg-type]


def test_known_answer_hardcoded_signature_passes() -> None:
    """Vector ĐỘC LẬP: giá trị base64 dưới đây được tính TAY bằng `hmac`/`hashlib`/`base64` trong
    một `python -c` KHÔNG import `app.core.webhook_signature` (không dùng `sign_svix_payload`) —
    khoá cứng ngay trong test để không phụ thuộc bất kỳ hàm nào của module đang kiểm tra. Nếu ai đó
    sửa `_digest` (đổi thứ tự nối chuỗi, đổi dấu phân cách, quên `msg_id`...), test này đỏ mà không
    cần tin vào chính module đang bị nghi ngờ."""
    known_header = "v1,O/OU8qv8ODjiVuyFLFr8Pf/hp7+F/54FTA1sbV0GY2k="
    assert (
        verify_svix_signature(
            secret=_SECRET, msg_id=_ID, timestamp=_TS, signature_header=known_header,
            body=_BODY, now=_NOW, tolerance_seconds=300.0,
        )
        is True
    )


def test_signature_built_for_different_msg_id_fails() -> None:
    """Bắt mutation bỏ `msg_id` khỏi `signed_content`: nếu bỏ, chữ ký ký cho `msg_id` KHÁC vẫn khớp
    khi verify với `msg_id` thật — vì `sign_*`/`verify_*` dùng chung `_digest`, test dựng-rồi-verify
    thông thường (kiểu `test_valid_signature_passes`) KHÔNG bắt được lỗi này."""
    sig_for_other_id = sign_svix_payload(secret=_SECRET, msg_id="msg_OTHER", timestamp=_TS, body=_BODY)
    assert _verify(signature_header=sig_for_other_id) is False


def test_signature_built_for_different_timestamp_fails() -> None:
    """Tương tự test trên nhưng cho `timestamp` — bắt mutation bỏ `timestamp` khỏi `signed_content`."""
    sig_for_other_ts = sign_svix_payload(secret=_SECRET, msg_id=_ID, timestamp="1786000001", body=_BODY)
    assert _verify(signature_header=sig_for_other_ts) is False


# ── Ánh xạ sự kiện → trạng thái giao hàng ───────────────────────────────────
from app.models.application import Application
from app.models.email_delivery import DeliveryStatus
from app.services import email_delivery as svc


def test_event_type_mapping() -> None:
    assert svc.status_for_event("email.sent") == DeliveryStatus.SENT.value
    assert svc.status_for_event("email.delivered") == DeliveryStatus.DELIVERED.value
    assert svc.status_for_event("email.bounced") == DeliveryStatus.BOUNCED.value
    assert svc.status_for_event("email.complained") == DeliveryStatus.COMPLAINED.value


def test_unknown_event_type_ignored() -> None:
    """Resend còn gửi `email.opened`/`email.clicked`/`email.delivery_delayed` — không phải sự kiện
    của ta, và cũng KHÔNG được coi là lỗi (trả 204, đừng bắt Resend thử lại)."""
    assert svc.status_for_event("email.opened") is None
    assert svc.status_for_event("") is None


def test_bounce_reason_extracted_and_truncated() -> None:
    reason = svc.bounce_reason_of({"bounce": {"type": "Permanent", "subType": "General",
                                              "message": "x" * 900}})
    assert reason is not None and len(reason) <= svc._MAX_REASON
    assert "Permanent" in reason


def test_bounce_reason_none_when_absent() -> None:
    assert svc.bounce_reason_of({}) is None


def test_email_id_read_from_either_field() -> None:
    """Payload Resend đã đổi hình dạng giữa các phiên bản tài liệu — đọc cả hai, đừng đoán một."""
    assert svc.email_id_of({"data": {"email_id": "e_1"}}) == "e_1"
    assert svc.email_id_of({"data": {"id": "e_2"}}) == "e_2"
    assert svc.email_id_of({"data": {}}) is None


def test_single_channel_map_excludes_reject() -> None:
    """Quyết định #4: bounce thư TỪ CHỐI chỉ gắn cờ. Hàng chờ HR chỉ có hai nút, và cả hai đều dẫn
    tới hậu quả sai (mời một người đã bị từ chối / bounce vòng hai vào đúng địa chỉ chết)."""
    assert "reject" not in svc._SINGLE_CHANNEL
    assert set(svc._SINGLE_CHANNEL) == {"invite", "screener", "screener_reminder"}


def test_demotable_excludes_complained() -> None:
    """Quyết định #I3 (adversarial review, người dùng đã chốt): complaint là bằng chứng thư ĐÃ TỚI
    — không có gì "hỏng" để cứu bằng cách hạ trạng thái. Chỉ BOUNCED mới được phép hạ."""
    assert svc._DEMOTABLE == {"BOUNCED"}


# ── C1 (adversarial review): payload rác KHÔNG được làm mất tín hiệu bounce ─────────────────
# Trước vòng sửa này, `bounce` là chuỗi thay vì object khiến `.get()` ném AttributeError NGAY GIỮA
# `_process` — bị `except Exception` trần nuốt cùng rollback, nên CẢ sự kiện bounce biến mất trong
# im lặng. Hai test dưới khoá lại: hình dạng payload rác không được ném, phải trả None êm.


def test_email_id_of_rejects_non_dict_data() -> None:
    assert svc.email_id_of({"data": "khong-phai-dict"}) is None
    assert svc.email_id_of({"data": ["a", "b"]}) is None
    assert svc.email_id_of({"data": None}) is None
    assert svc.email_id_of({}) is None


def test_bounce_reason_of_rejects_non_dict_data_or_bounce() -> None:
    assert svc.bounce_reason_of("khong-phai-dict") is None
    assert svc.bounce_reason_of(None) is None
    assert svc.bounce_reason_of({"bounce": "hard bounce"}) is None  # C1: repro CHÍNH XÁC của reviewer
    assert svc.bounce_reason_of({"bounce": ["type", "Permanent"]}) is None


async def test_handle_event_lets_infra_errors_surface(monkeypatch) -> None:  # noqa: ANN001
    """C1 phần 2: `handle_event` chỉ nuốt lỗi HÌNH DẠNG payload — lỗi HẠ TẦNG (mất kết nối DB giữa
    chừng, deadlock...) phải NỔI LÊN cho route xử lý, vì Resend thử lại LÀ đúng hướng cho loại lỗi
    này (khác payload rác, thử lại sẽ hỏng y hệt). Mô phỏng bằng cách làm `status_for_event` ném một
    lỗi KHÔNG nằm trong `_PAYLOAD_ERRORS` — nếu `handle_event` nuốt luôn cả lỗi này thì assertion
    `pytest.raises` dưới đây sẽ đỏ."""
    import pytest

    class _FakeSession:
        async def rollback(self) -> None:
            pass

    def boom(_event_type: str) -> str | None:
        raise RuntimeError("mất kết nối Neon giữa chừng (mô phỏng)")

    monkeypatch.setattr(svc, "status_for_event", boom)
    with pytest.raises(RuntimeError):
        await svc.handle_event(_FakeSession(), {"type": "email.bounced", "data": {}})


# ── I2 (adversarial review): hai guard của `_clear_bounce` từng KHÔNG có test canh riêng —
# mutation của reviewer xoá CẢ HAI guard mà 34/34 test vẫn xanh. Mỗi test dưới đây khoá MỘT guard.


def test_clear_bounce_keeps_flag_when_delivered_to_different_address() -> None:
    """Guard 1 (`recipient != app_row.applicant_email`): một địa chỉ KHÁC gửi thành công không được
    phép gỡ cờ bounce của địa chỉ đã hỏng — hai email khác nhau là hai chuyện khác nhau."""
    app_row = Application(applicant_email="that-su@e.com")
    app_row.uncertainty_flags = [svc.EMAIL_BOUNCED_FLAG]
    app_row.escalation_reason = svc._REASON_INVITE
    svc._clear_bounce(app_row, recipient="dia-chi-khac@e.com")
    assert svc.EMAIL_BOUNCED_FLAG in app_row.uncertainty_flags
    assert app_row.escalation_reason == svc._REASON_INVITE


def test_clear_bounce_keeps_unrelated_escalation_reason() -> None:
    """Guard 2 (`escalation_reason in _BOUNCE_REASONS`): lý do escalation do MỘT chuyện KHÁC đặt
    (vd HR huỷ lịch) không được xoá dù cờ bounce vẫn gỡ đúng khi cùng địa chỉ."""
    app_row = Application(applicant_email="a@e.com")
    app_row.uncertainty_flags = [svc.EMAIL_BOUNCED_FLAG]
    app_row.escalation_reason = "HR đã huỷ lịch phỏng vấn — cần sắp xếp lại với ứng viên."
    svc._clear_bounce(app_row, recipient="a@e.com")  # CÙNG địa chỉ → cờ ĐƯỢC gỡ
    assert svc.EMAIL_BOUNCED_FLAG not in app_row.uncertainty_flags
    assert app_row.escalation_reason == "HR đã huỷ lịch phỏng vấn — cần sắp xếp lại với ứng viên."


def test_clear_bounce_never_touches_complained_flag() -> None:
    """Fix vòng 3 (adversarial review — lỗi THẬT, không phải chuyện đặt tên): `_clear_bounce` CHỈ
    được phép gỡ `EMAIL_BOUNCED_FLAG`. Cờ complained là dấu vết "ứng viên đã báo chúng ta là spam" —
    một lượt giao hàng thành công về sau chứng minh địa chỉ hoạt động (nên gỡ được cờ bounce) nhưng
    KHÔNG hề phủ nhận việc họ từng bấm spam. Nếu ai đó "tổng quát hoá" hàm này để gỡ mọi cờ liên quan
    tới email, test này bắt được ngay (xem mutation trong task-7-report.md)."""
    app_row = Application(applicant_email="a@e.com")
    app_row.uncertainty_flags = [svc.EMAIL_BOUNCED_FLAG, svc.EMAIL_COMPLAINED_FLAG]
    svc._clear_bounce(app_row, recipient="a@e.com")  # CÙNG địa chỉ → chỉ BOUNCE được gỡ
    assert svc.EMAIL_BOUNCED_FLAG not in app_row.uncertainty_flags
    assert svc.EMAIL_COMPLAINED_FLAG in app_row.uncertainty_flags  # KHÔNG BAO GIỜ bị gỡ ở đây
