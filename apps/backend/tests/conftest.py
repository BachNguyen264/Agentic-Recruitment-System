"""Cấu hình dùng chung cho toàn bộ test backend (pytest tự nạp file này, không cần import).

Hiện chỉ có MỘT fixture: chặn `email_service` ngủ THẬT (xem bên dưới). Thêm fixture dùng chung
khác vào đây khi cần — đừng lặp lại logic reset ở từng file test.
"""

from __future__ import annotations

import pytest

from app.services import email_service


@pytest.fixture(autouse=True)
def _no_real_email_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    """AUTOUSE cho MỌI test: `email_service._paced_send` (EMAIL-1) không được ngủ THẬT.

    Trước khi có fixture này, test nào chạm `send_email` mà KHÔNG tự tiêm đồng hồ giả (vd các test
    cũ trong `test_email.py`, viết trước khi EMAIL-1 thêm giữ nhịp/retry) sẽ ngủ bằng
    `asyncio.sleep` THẬT: một lượt lỗi liên tục ăn đủ backoff 3 lần (~3.9s), và hai lượt gửi liên
    tiếp trong CÙNG phiên pytest ăn đúng khoảng giữ nhịp (mặc định 550ms, hoặc bất cứ giá trị nào
    `.env` của máy dev đặt) — thời lượng suite trở nên phụ thuộc máy chạy, đúng thứ CI không được
    có. Đồng hồ giả ở đây CHẠY (không đứng yên): mỗi lần gọi `_monotonic()` tiến thêm một chút, và
    `_sleep` giả chỉ cộng dồn "thời gian đã ngủ" vào đồng hồ đó — nhờ vậy `_paced_send` vẫn tính
    được `wait`/backoff hợp lý (không phải lúc nào cũng ngủ, không phải lúc nào cũng bỏ qua) mà
    không tốn một mili-giây THẬT nào.

    Test nào cần KIỂM SỐ ĐO chính xác của giấc ngủ (khoảng nghỉ, thứ tự backoff) thì dùng fixture
    `paced` cục bộ trong `tests/test_email_delivery.py` — fixture đó nhận `monkeypatch` CÙNG một
    instance với fixture này trong một test (pytest gộp theo scope), nên nó ghi đè LÊN TRÊN các
    giá trị đặt ở đây và trở thành hiệu lực cuối cùng; không có xung đột.
    """
    clock = {"t": 0.0}

    def fake_monotonic() -> float:
        clock["t"] += 0.01
        return clock["t"]

    async def fake_sleep(seconds: float) -> None:
        clock["t"] += seconds

    monkeypatch.setattr(email_service, "_monotonic", fake_monotonic)
    monkeypatch.setattr(email_service, "_sleep", fake_sleep)
    monkeypatch.setattr(email_service, "_last_send_at", 0.0)
