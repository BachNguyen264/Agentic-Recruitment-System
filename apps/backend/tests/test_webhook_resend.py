"""Test EMAIL-1 — webhook Resend: chữ ký, miễn trừ middleware, idempotent, bảng xử lý bounce.

Webhook là endpoint CÔNG KHAI CÓ MUTATION: không verify chữ ký thì bất kỳ ai cũng giả được sự kiện
bounce và phá hồ sơ của ứng viên thật. Đây là phần được test kỹ nhất của lát này.
"""

from __future__ import annotations

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
