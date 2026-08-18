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
    assert svc.status_for_event("email.failed") == DeliveryStatus.FAILED.value
    assert svc.status_for_event("email.bounced") == DeliveryStatus.BOUNCED.value
    assert svc.status_for_event("email.complained") == DeliveryStatus.COMPLAINED.value


def test_handled_event_set_is_exact() -> None:
    """Khoá TẬP sự kiện được xử lý, không chỉ từng cái một.

    `test_event_type_mapping` chỉ kiểm từng khoá nên nó vẫn XANH khi ai đó thêm một loại sự kiện
    vào `_EVENT_STATUS` mà quên `_RANK`/`_STATUS_FLAG` — thứ khiến sự kiện đó rơi vào im lặng.
    Cùng nếp `test_single_channel_map_excludes_reject`.
    """
    assert set(svc._EVENT_STATUS) == {
        "email.sent", "email.delivered", "email.failed", "email.bounced", "email.complained",
    }


def test_unknown_event_type_ignored() -> None:
    """Resend còn gửi `email.opened`/`email.clicked`/`email.delivery_delayed`/`email.suppressed`
    — không phải sự kiện của ta, và cũng KHÔNG được coi là lỗi (trả 204, đừng bắt Resend thử lại).

    `email.failed` ĐÃ RỜI nhóm này (xem `test_event_type_mapping`) — nó nay được xử lý thật.
    """
    assert svc.status_for_event("email.opened") is None
    assert svc.status_for_event("email.delivery_delayed") is None
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
    — không có gì "hỏng" để cứu bằng cách hạ trạng thái, nên nó KHÔNG được hạ.

    `FAILED` thì ĐƯỢC (bổ sung khi bật `email.failed`): thư chưa hề rời hệ thống, nên ứng viên đang
    chờ một thứ sẽ không bao giờ tới. Để nguyên trạng thái thì lưới sweep sẽ hết hạn rồi dán nhãn
    "không phản hồi" lên người chưa từng nhận được gì.
    """
    assert svc._DEMOTABLE == {"BOUNCED", "FAILED"}
    assert DeliveryStatus.COMPLAINED.value not in svc._DEMOTABLE


def test_negative_set_is_derived_from_flag_map() -> None:
    """`_NEGATIVE` phải LUÔN bằng tập khoá của `_STATUS_FLAG`.

    Đây là bất biến thay cho cái ternary hai nhánh cũ: mọi sự kiện xấu đều phải có cờ RIÊNG. Viết
    tay hai danh sách song song là cách một loại mới lọt vào `_NEGATIVE` rồi mượn nhầm cờ của loại
    khác — cụ thể là `email_complained`, cờ KHÔNG BAO GIỜ được gỡ.
    """
    assert svc._NEGATIVE == frozenset(svc._STATUS_FLAG)
    assert svc._DEMOTABLE <= svc._NEGATIVE


def test_each_negative_status_has_its_own_flag() -> None:
    """Ba sự kiện xấu, BA cờ khác nhau — không cái nào dùng chung tên với cái nào."""
    flags = list(svc._STATUS_FLAG.values())
    assert len(flags) == len(set(flags))
    assert svc._STATUS_FLAG[DeliveryStatus.FAILED.value] == svc.EMAIL_SEND_FAILED_FLAG


def test_send_failed_flag_does_not_collide_with_scheduler_audit_action() -> None:
    """Cờ KHÔNG được trùng chuỗi `email_failed` — tên đó `scheduler._dispatch` đã dùng làm `action`
    trong audit_log cho lượt gọi Resend NÉM lỗi tại chỗ (chuyện khác hẳn, cùng node="scheduler").

    Và audit của webhook cũng phải mang tên KHÁC, nếu không hai sự kiện ngược nhau trở thành một
    dòng log không phân biệt nổi — đúng lớp lỗi đã vá ở commit d4fbfd5.
    """
    assert svc.EMAIL_SEND_FAILED_FLAG != "email_failed"
    assert svc._AUDIT_ACTION[DeliveryStatus.FAILED.value] != "email_failed"


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


# ── `email.failed`: nguyên nhân nằm ở `data.failed.reason`, KHÔNG phải `data.bounce.*` ───────────


def test_failure_reason_extracted_and_truncated() -> None:
    assert svc.failure_reason_of({"failed": {"reason": "reached_daily_quota"}}) == (
        "reached_daily_quota"
    )
    long_reason = svc.failure_reason_of({"failed": {"reason": "x" * 900}})
    assert long_reason is not None and len(long_reason) <= svc._MAX_REASON


def test_failure_reason_none_when_absent() -> None:
    assert svc.failure_reason_of({}) is None
    assert svc.failure_reason_of({"failed": {}}) is None
    assert svc.failure_reason_of({"failed": {"reason": ""}}) is None


def test_failure_reason_of_rejects_garbage_shapes() -> None:
    """Cùng kỷ luật C1 với `bounce_reason_of`: payload rác trả None, TUYỆT ĐỐI không ném — một
    exception ở đây từng nuốt mất cả sự kiện (route đã hứa 204 nên Resend không gửi lại)."""
    assert svc.failure_reason_of("khong-phai-dict") is None
    assert svc.failure_reason_of(None) is None
    assert svc.failure_reason_of({"failed": "boom"}) is None
    assert svc.failure_reason_of({"failed": ["reason", "x"]}) is None


def test_reason_reader_matches_event_type() -> None:
    """Bẫy hình dạng payload: hai sự kiện để nguyên nhân ở HAI CHỖ khác nhau.

    Dùng nhầm bộ đọc không ném lỗi — nó chỉ trả None, tức HR nhận cảnh báo đỏ KHÔNG kèm lý do.
    `_reason_for` là chỗ duy nhất biết sự bất đối xứng này, nên nó phải chọn đúng cả hai chiều.
    """
    failed_payload = {"failed": {"reason": "reached_daily_quota"}}
    bounce_payload = {"bounce": {"type": "Permanent", "message": "mailbox not found"}}

    # Chiều đúng
    assert svc._reason_for(DeliveryStatus.FAILED.value, failed_payload) == "reached_daily_quota"
    assert "Permanent" in (svc._reason_for(DeliveryStatus.BOUNCED.value, bounce_payload) or "")
    # Chiều chéo — chứng minh hai hàm KHÔNG thay thế được cho nhau (nếu ai đó gộp làm một,
    # hai assert này đỏ ngay thay vì để lý do biến mất trong im lặng trên bản live).
    assert svc._reason_for(DeliveryStatus.BOUNCED.value, failed_payload) is None
    assert svc._reason_for(DeliveryStatus.FAILED.value, bounce_payload) is None


# ── F2 (final review): Transient (hộp thư đầy/tạm thời) KHÔNG được xử lý y hệt Permanent ────────


def test_is_transient_bounce_recognizes_type_case_insensitive() -> None:
    assert svc._is_transient_bounce({"bounce": {"type": "Transient"}}) is True
    assert svc._is_transient_bounce({"bounce": {"type": "transient"}}) is True
    assert svc._is_transient_bounce({"bounce": {"type": " TRANSIENT "}}) is True


def test_is_transient_bounce_false_for_permanent_or_absent() -> None:
    assert svc._is_transient_bounce({"bounce": {"type": "Permanent"}}) is False
    assert svc._is_transient_bounce({"bounce": {}}) is False
    assert svc._is_transient_bounce({}) is False


def test_is_transient_bounce_rejects_non_dict_payload() -> None:
    """Cùng kỷ luật với `bounce_reason_of`/`email_id_of` (C1): hình dạng payload rác KHÔNG được ném."""
    assert svc._is_transient_bounce(None) is False
    assert svc._is_transient_bounce("khong-phai-dict") is False
    assert svc._is_transient_bounce({"bounce": "hard bounce"}) is False
    assert svc._is_transient_bounce({"bounce": ["type", "Transient"]}) is False


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


# ── Endpoint ────────────────────────────────────────────────────────────────
import httpx
import pytest

from app.core.hardening import OriginCheckMiddleware, RateLimitMiddleware


def _headers(body: bytes, *, secret: str = _SECRET, ts: str = _TS) -> dict[str, str]:
    return {
        "svix-id": _ID,
        "svix-timestamp": ts,
        "svix-signature": sign_svix_payload(secret=secret, msg_id=_ID, timestamp=ts, body=body),
        "content-type": "application/json",
    }


@pytest.fixture
def client(monkeypatch):
    """App THẬT nhưng chỉ mount router webhook — không kéo theo lifespan/DB của app đầy đủ.

    `get_session` được ghi đè bằng một object rỗng: dependency của FastAPI chạy TRƯỚC thân handler,
    nên không ghi đè thì cả test 401/503 cũng mở một connection Postgres thật (chậm + đòi DB cho
    những test vốn không cần).
    """
    from fastapi import FastAPI

    from app.api.routes import webhooks
    from app.core.database import get_session

    monkeypatch.setattr(webhooks.settings, "resend_webhook_secret", _SECRET)
    monkeypatch.setattr(webhooks.settings, "resend_webhook_tolerance_seconds", 300.0)
    monkeypatch.setattr(webhooks, "_now", lambda: _NOW)

    app = FastAPI()
    app.include_router(webhooks.router, prefix="/api")
    app.dependency_overrides[get_session] = lambda: object()
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_valid_signature_accepted(client, monkeypatch) -> None:
    seen: list[dict] = []
    from app.api.routes import webhooks

    async def fake_handle(_session, event: dict) -> None:  # noqa: ANN001
        seen.append(event)

    monkeypatch.setattr(webhooks, "_handle", fake_handle)
    async with client as c:
        r = await c.post("/api/webhooks/resend", content=_BODY, headers=_headers(_BODY))
    assert r.status_code == 204
    assert seen and seen[0]["type"] == "email.bounced"


async def test_forged_signature_rejected_401(client, monkeypatch) -> None:
    """Giả mạo → 401 và KHÔNG chạm nghiệp vụ (không có tác dụng phụ nào)."""
    from app.api.routes import webhooks

    async def boom(*_a):  # noqa: ANN002, ANN202
        raise AssertionError("nghiệp vụ KHÔNG được chạy khi chữ ký sai")

    monkeypatch.setattr(webhooks, "_handle", boom)
    bad = dict(_headers(_BODY), **{"svix-signature": "v1,YWJjZA=="})
    async with client as c:
        r = await c.post("/api/webhooks/resend", content=_BODY, headers=bad)
    assert r.status_code == 401


async def test_missing_signature_headers_rejected_401(client) -> None:
    async with client as c:
        r = await c.post("/api/webhooks/resend", content=_BODY,
                         headers={"content-type": "application/json"})
    assert r.status_code == 401


async def test_secret_not_configured_returns_503(client, monkeypatch) -> None:
    """Chưa cấu hình secret → TỪ CHỐI, không phải "cho qua vì chưa bật"."""
    from app.api.routes import webhooks

    monkeypatch.setattr(webhooks.settings, "resend_webhook_secret", None)
    async with client as c:
        r = await c.post("/api/webhooks/resend", content=_BODY, headers=_headers(_BODY))
    assert r.status_code == 503


async def test_invalid_json_with_valid_signature_returns_400(client) -> None:
    body = b"khong-phai-json"
    async with client as c:
        r = await c.post("/api/webhooks/resend", content=body, headers=_headers(body))
    assert r.status_code == 400


# ── Miễn trừ middleware: hành vi ta ĐANG DỰA VÀO mà chưa có test nào giữ ─────
async def test_webhook_is_exempt_from_rate_limit() -> None:
    """Resend gọi từ VÀI IP cố định. Siết theo IP là gom hết vào một xô → 429 → MẤT sự kiện bounce,
    và mất im lặng (Resend thử lại vài lần rồi thôi)."""
    from fastapi import FastAPI

    app = FastAPI()

    @app.post("/api/webhooks/resend")
    async def hook() -> dict:
        return {"ok": True}

    app.add_middleware(
        RateLimitMiddleware, login_max=1, login_window_seconds=60,
        public_max=1, public_window_seconds=60, trust_proxy=False, enabled=True,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        for _ in range(5):
            assert (await c.post("/api/webhooks/resend", json={})).status_code == 200


async def test_webhook_passes_origin_check_without_origin_header() -> None:
    """Request server-to-server KHÔNG có header `Origin` — phải cho qua, nếu không webhook chết hẳn."""
    from fastapi import FastAPI

    app = FastAPI()

    @app.post("/api/webhooks/resend")
    async def hook() -> dict:
        return {"ok": True}

    app.add_middleware(OriginCheckMiddleware, allowed=frozenset({"https://ars.vercel.app"}))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.post("/api/webhooks/resend", json={})).status_code == 200


# ── Important-1 (audit sau commit 1a51c27): router THẬT (`app.main.app`) phải KHÔNG bị `require_hr`
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Mọi test ở trên tự dựng `FastAPI()` rồi mount CHỈ `webhooks.router` — không test nào từng chạm
# `app.main.app` thật, nên một mutation thêm `dependencies=_HR_ONLY` vào dòng
# `app.include_router(webhooks.router, ...)` ở main.py lọt qua TOÀN BỘ 424 test cũ mà không bị bắt
# (reviewer đã chạy mutation này và xác nhận: tất cả xanh). Hậu quả prod: Resend nhận 401 cho MỌI sự
# kiện, bounce mất IM LẶNG — đúng chế độ hỏng Task 6 sinh ra để ngăn. Test dưới đây chạm app thật.
async def test_webhook_route_on_real_app_is_not_gated_by_require_hr(monkeypatch) -> None:
    """Gửi request có chữ ký HỢP LỆ, KHÔNG kèm cookie phiên nào, tới `app.main.app` THẬT (không phải
    app tự dựng của các test khác) — phải 204. Nếu router lỡ bị gắn `require_hr`, thiếu cookie sẽ bị
    chặn NGAY Ở TẦNG DEPENDENCY (trước khi vào thân handler) → 401, và test này bắt được ngay."""
    from app.api.routes import webhooks
    from app.core.database import get_session
    from app.main import app as main_app

    async def fake_handle(_session, event: dict) -> None:  # noqa: ANN001
        pass

    monkeypatch.setattr(webhooks.settings, "resend_webhook_secret", _SECRET)
    monkeypatch.setattr(webhooks.settings, "resend_webhook_tolerance_seconds", 300.0)
    monkeypatch.setattr(webhooks, "_now", lambda: _NOW)
    monkeypatch.setattr(webhooks, "_handle", fake_handle)

    main_app.dependency_overrides[get_session] = lambda: object()
    try:
        # KHÔNG chạy lifespan (ASGITransport mặc định không gọi lifespan) → không chạm
        # checkpointer/Neon thật, dù import nguyên `app.main.app`.
        transport = httpx.ASGITransport(app=main_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post("/api/webhooks/resend", content=_BODY, headers=_headers(_BODY))
        assert r.status_code == 204  # KHÔNG cookie mà vẫn qua — chốt chặn là CHỮ KÝ, không phải cookie.
    finally:
        main_app.dependency_overrides.clear()


# ── Important-2 (audit sau commit 1a51c27): trần thân RIÊNG cho webhook ─────────────────────────
# `/api/webhooks/*` là path công khai DUY NHẤT không có xô rate-limit (miễn trừ có chủ ý). Trần
# CHUNG `max_request_bytes` (12MB, cỡ CV) áp cho MỌI POST khác biến nó thành đường khuếch đại KHÔNG
# hạn mức: không cần chữ ký đúng, gửi lặp lại body cỡ chục MB vẫn ép server đệm hết + chạy trọn
# HMAC-SHA256 trước khi bị từ chối. `resend_webhook_max_bytes` (mặc định 64KB) đóng khe này.
async def test_oversized_declared_content_length_rejected_413_before_business(
    client, monkeypatch
) -> None:
    """Content-Length KHAI vượt trần riêng của webhook → 413, và KHÔNG chạm nghiệp vụ (kiểm ở Bước 0,
    trước cả kiểm secret/verify chữ ký — không cần chữ ký hợp lệ để bắt được ca này)."""
    from app.api.routes import webhooks

    async def boom(*_a):  # noqa: ANN002, ANN202
        raise AssertionError("nghiệp vụ KHÔNG được chạy khi body vượt trần khai báo")

    monkeypatch.setattr(webhooks, "_handle", boom)
    oversized = b"x" * (webhooks.settings.resend_webhook_max_bytes + 1)
    async with client as c:
        r = await c.post("/api/webhooks/resend", content=oversized)
    assert r.status_code == 413


async def test_content_length_at_exactly_the_cap_is_accepted(client, monkeypatch) -> None:
    """Biên: ĐÚNG bằng trần (không vượt) phải KHÔNG bị 413 — kiểm dùng `>`, không phải `>=`. Chữ ký
    tính trên đúng body gửi nên vẫn hợp lệ, và trần mặc định lớn hơn payload thật rất nhiều nên request
    hợp lệ bình thường (`test_valid_signature_accepted`) không bao giờ va trần này."""
    from app.api.routes import webhooks

    async def fake_handle(_session, event: dict) -> None:  # noqa: ANN001
        pass

    monkeypatch.setattr(webhooks, "_handle", fake_handle)
    # Đệm bằng khoảng trắng: `json.loads` BỎ QUA whitespace ở đuôi (xem `decode()` trong stdlib
    # `json/decoder.py`) nên body vẫn parse ra đúng dict gốc, đi tới tận `_handle` — test chạm đúng
    # nhánh "được CHẤP NHẬN", không dừng sớm ở 400.
    at_cap = _BODY + b" " * (webhooks.settings.resend_webhook_max_bytes - len(_BODY))
    assert len(at_cap) == webhooks.settings.resend_webhook_max_bytes
    async with client as c:
        r = await c.post("/api/webhooks/resend", content=at_cap, headers=_headers(at_cap))
    assert r.status_code == 204


async def test_missing_content_length_is_not_blocked_by_webhook_size_check(
    client, monkeypatch
) -> None:
    """THIẾU `Content-Length` (Transfer-Encoding: chunked — proxy CÓ QUYỀN chuyển tiếp kiểu này)
    KHÔNG bị chặn ở Bước 0: chặn cứng khi thiếu header sẽ giết mọi lượt Resend đi qua proxy chunked
    trên bản live trong khi dev vẫn chạy ngon (đúng bài học đã có ở `BodySizeLimitMiddleware`)."""
    from app.api.routes import webhooks

    seen: list[dict] = []

    async def fake_handle(_session, event: dict) -> None:  # noqa: ANN001
        seen.append(event)

    monkeypatch.setattr(webhooks, "_handle", fake_handle)

    async def _chunks():
        yield _BODY

    async with client as c:
        r = await c.post("/api/webhooks/resend", content=_chunks(), headers=_headers(_BODY))
    assert r.status_code == 204
    assert seen and seen[0]["type"] == "email.bounced"
