"""cv_reader — trích văn bản thô từ CV (PDF/DOCX). PRD §7.1 (tool đọc theo định dạng).

Làm việc trên **BYTES** (slice 06): file CV có thể nằm trên đĩa (dev) hoặc Cloudflare R2 (prod) —
nguồn bytes do seam `services/storage` cung cấp, cv_reader KHÔNG mở path. Chọn bộ đọc theo ĐUÔI của
tên/key (key luôn giữ đuôi — xem `storage.build_cv_key`): PDF -> PyMuPDF (fitz), DOCX -> python-docx.
Text quá ngắn (CV ảnh scan / rỗng) -> EmptyCVTextError để node set `parse_failed` (OCR ngoài phạm vi).
"""

from __future__ import annotations

import io
import multiprocessing
import sys
import zipfile
from pathlib import PurePosixPath

from app.core.config import settings
from app.core.logging import get_logger

# Dưới ngưỡng này coi như không trích được văn bản (CV ảnh scan / file rỗng).
MIN_TEXT_CHARS = 50

logger = get_logger("app.tools.cv_reader")


class CVReadError(Exception):
    """Không đọc được CV: định dạng không hỗ trợ hoặc file lỗi/hỏng."""


class EmptyCVTextError(CVReadError):
    """Trích được quá ít text — CV có thể là ảnh scan (OCR ngoài phạm vi slice này)."""


def _joined_len(parts: list[str]) -> int:
    """Độ dài chuỗi SAU khi `"\\n".join(parts)` — `n-1` dấu xuống dòng, không phải `n`.

    Cộng `+1` cho MỌI phần (bản trước) làm `taken` lớn hơn độ dài thật đúng 1, nên `break` ở
    `taken >= budget` trả về `budget - 1` ký tự. `[:budget]` không cắt gì, và `parser.parse_cv` suy
    ra `truncated = len(text) >= budget` → **False** ⇒ CV BỊ CẮT mà KHÔNG có cờ `cv_truncated`, tức
    vô hiệu hoá đúng cái chốt "CV mất phần cuối không được lọt gate auto".
    """
    return sum(len(p) for p in parts) + max(0, len(parts) - 1)


def _extract_pdf(data: bytes, budget: int) -> str:
    import fitz  # PyMuPDF

    parts: list[str] = []
    # stream= đọc thẳng từ bytes (không cần file tạm) — bắt buộc khi CV nằm trên object storage.
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            parts.append(page.get_text())
            if _joined_len(parts) >= budget:
                # DỪNG ĐỌC hẳn, không chỉ cắt kết quả cuối: mỗi `get_text()` tiếp theo vừa tốn CPU
                # vừa cấp phát thêm RAM cho phần chắc chắn bị vứt.
                #
                # ⚠ Chốt này chỉ bảo vệ ca NHIỀU TRANG. Nó KHÔNG bảo vệ được ca một trang: `break`
                # chỉ chạy SAU khi `get_text()` của trang hiện tại xong, mà chi phí của một trang là
                # BẬC HAI theo số glyph (đo: 6.6 KB → 90 s). Hạn giờ cứng ở `extract_text_bounded`
                # mới là thứ chặn ca đó.
                break
    return "\n".join(parts)[:budget]


def _extract_docx(data: bytes, budget: int) -> str:
    from docx import Document

    # TIỀN KIỂM trước khi python-docx đụng vào file: `Document()` dựng lxml cho TOÀN BỘ
    # `word/document.xml` rồi mới tới lượt vòng `break` bên dưới, nên không có phép kiểm này thì
    # trần ký tự không cản được gì (đo: .docx 442 KB chứa XML 116.5 MB → RSS +639 MB). ZIP khai sẵn
    # kích thước sau giải nén nên đọc central directory gần như miễn phí.
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            uncompressed = sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile as exc:
        raise CVReadError(f"File DOCX hỏng hoặc không phải ZIP hợp lệ: {exc}") from exc
    if uncompressed > settings.parser_max_cv_uncompressed_bytes:
        raise CVReadError(
            f"DOCX giải nén quá lớn ({uncompressed:,} byte, trần "
            f"{settings.parser_max_cv_uncompressed_bytes:,}) — file có thể được dựng để phá."
        )

    doc = Document(io.BytesIO(data))
    parts: list[str] = []
    for para in doc.paragraphs:
        parts.append(para.text)
        if _joined_len(parts) >= budget:
            break
    return "\n".join(parts)[:budget]


def extract_text(data: bytes, name: str, *, max_chars: int | None = None) -> str:
    """Trích text thô từ BYTES CV; `name` (tên file/key) chỉ dùng để chọn bộ đọc theo đuôi.

    Raise ``CVReadError``/``EmptyCVTextError`` cho ca không đọc được. KHÔNG bắt lỗi tại đây —
    node parser quyết định set `parse_failed`.

    `max_chars` = TRẦN ký tự, áp BÊN TRONG bộ đọc (mặc định `settings.parser_max_cv_chars`). Chạm
    trần thì chuỗi trả về dài ĐÚNG BẰNG trần; người gọi nhận ra bằng `len(text) >= max_chars` rồi tự
    quyết gắn cờ (xem `parser.parse_cv` → `cv_truncated`). Ở đây KHÔNG raise: CV dài bất thường vẫn
    là hồ sơ ĐỌC ĐƯỢC — nó phải vào human_review, không phải bị vứt như file hỏng.
    """
    suffix = PurePosixPath(name or "").suffix.lower()

    if suffix == ".pdf":
        reader = _extract_pdf
    elif suffix == ".docx":
        reader = _extract_docx
    else:
        raise CVReadError(f"Định dạng không hỗ trợ: {suffix or '(không có đuôi)'} — chỉ nhận .pdf/.docx.")

    if not data:
        raise EmptyCVTextError("File CV rỗng — không trích được văn bản.")

    budget = settings.parser_max_cv_chars if max_chars is None else max_chars
    try:
        text = reader(data, budget)
    except CVReadError:
        raise
    except Exception as exc:  # noqa: BLE001 — gói lỗi đọc file thành tín hiệu parse_failed
        raise CVReadError(f"Lỗi khi đọc {name}: {exc}") from exc

    if len(text.strip()) < MIN_TEXT_CHARS:
        raise EmptyCVTextError(
            "CV có thể là ảnh scan hoặc rỗng — không trích được văn bản (OCR ngoài phạm vi)."
        )
    return text


# ── Trích văn bản CÓ HẠN GIỜ CỨNG ───────────────────────────────────────────────────────────────


def _mp_context() -> multiprocessing.context.BaseContext:
    """Context tạo tiến trình con. `forkserver` trên Unix (prod), `spawn` trên Windows (dev).

    KHÔNG dùng `fork` thẳng: fork từ một tiến trình async đang chạy kế thừa cả khoá malloc/import mà
    luồng khác đang giữ ⇒ con có thể treo ngay lúc import `fitz`.

    `forkserver` fork từ một tiến trình phụ SẠCH (không thread), nên vừa an toàn vừa **không phải
    import lại `__main__`** — điều `spawn` bắt buộc phải làm. Lần import lại đó là một nguồn lỗi
    thật: nó phụ thuộc việc `__main__` có đường dẫn import lại được, và sẽ nổ `OSError` ở bất kỳ môi
    trường nào chạy code qua stdin/REPL. Prod (`python -m app` trong Docker Linux) do đó không bao
    giờ trả giá re-import, còn dev Windows thì chấp nhận `spawn` (~0.3s/CV, chỉ ở máy lập trình).
    """
    if sys.platform == "win32":
        return multiprocessing.get_context("spawn")
    ctx = multiprocessing.get_context("forkserver")
    # Nạp sẵn module này trong forkserver ⇒ mỗi lần fork con đã có `fitz`/`docx` sẵn sàng.
    ctx.set_forkserver_preload(["app.tools.cv_reader"])
    return ctx


def _extract_worker(conn, data: bytes, name: str, budget: int) -> None:
    """Thân tiến trình con: trích rồi gửi kết quả qua pipe. Cấp module để `spawn` pickle được."""
    try:
        conn.send(("ok", extract_text(data, name, max_chars=budget)))
    except CVReadError as exc:
        # Giữ NGUYÊN phân biệt rỗng-vs-hỏng: `EmptyCVTextError` là lớp con và caller phân biệt được.
        conn.send(("empty" if isinstance(exc, EmptyCVTextError) else "cv", str(exc)))
    except BaseException as exc:  # noqa: BLE001 — mọi thứ khác cũng phải về được cha
        conn.send(("other", f"{type(exc).__name__}: {exc}"))
    finally:
        conn.close()


def extract_text_bounded(data: bytes, name: str, *, max_chars: int | None = None) -> str:
    """`extract_text` chạy trong TIẾN TRÌNH CON có hạn giờ cứng — dùng ở đường nộp CV công khai.

    Vì sao phải là tiến trình chứ không phải luồng: chi phí bố cục của PyMuPDF là **bậc hai theo số
    glyph**, và một trang duy nhất đủ để tiêu hàng phút (đo: PDF 1 trang 6.6 KB → 90 s; 37 KB →
    >600 s). Không phép kiểm KÍCH THƯỚC nào bắt được ca đó. Tệ hơn, PyMuPDF là SWIG và **không nhả
    GIL**, nên `asyncio.to_thread` KHÔNG cô lập được: event loop đứng theo, kể cả `/api/health/live`
    ⇒ Render coi service đã chết → SIGKILL → lifespan không chạy → mọi BackgroundTask đang bay bốc
    hơi. Chỉ một tiến trình GIẾT ĐƯỢC mới chặn được. Con chết vì OOM thì cha vẫn sống — đó cũng là
    nửa còn lại của lớp phòng thủ cho ca DOCX nén cao.

    ⚠ NGOẠI LỆ có chủ ý của câu "Ở đây KHÔNG raise" trong `extract_text`: quá hạn thì RAISE
    `CVReadError`. Một file vượt hạn giờ là file dựng để phá, không phải "CV dài đọc được". Cả hai
    đường đều về `parse_failed` → `policy.should_review` → **PENDING_REVIEW, KHÔNG auto-từ-chối**
    (PRD §13 giữ nguyên); cái mất chỉ là phân biệt `cv_truncated` vs `parse_failed`.

    Dùng `spawn` trên MỌI nền tảng thay vì `fork`: fork từ một tiến trình async đang chạy có thể
    kế thừa khoá malloc/import do luồng khác đang giữ và treo con. `app/__main__.py` có
    `if __name__ == "__main__"` nên lần re-import của spawn KHÔNG dựng thêm server.
    """
    budget = settings.parser_max_cv_chars if max_chars is None else max_chars
    timeout = settings.parser_extract_timeout_seconds

    ctx = _mp_context()
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_extract_worker, args=(child_conn, data, name, budget), daemon=True
    )
    proc.start()
    child_conn.close()  # cha phải nhả đầu ghi, nếu không `poll` không bao giờ thấy EOF

    try:
        if not parent_conn.poll(timeout):
            logger.warning("cv_reader: trích %s quá %.1fs — giết tiến trình con", name, timeout)
            raise CVReadError(
                f"Đọc CV quá hạn {timeout:g}s — file có thể được dựng để phá hệ thống."
            )
        try:
            kind, payload = parent_conn.recv()
        except EOFError as exc:
            # Con chết mà chưa gửi gì (thường là OOM-kill). Cha SỐNG — đó là điểm của thiết kế này.
            raise CVReadError(
                f"Tiến trình đọc CV kết thúc bất thường (exitcode={proc.exitcode})."
            ) from exc
    finally:
        parent_conn.close()
        if proc.is_alive():
            proc.terminate()
        proc.join(timeout=5)
        if proc.is_alive():  # terminate không ăn (hiếm) → SIGKILL
            proc.kill()
            proc.join(timeout=5)

    if kind == "ok":
        return payload
    if kind == "empty":
        raise EmptyCVTextError(payload)
    raise CVReadError(payload)
