"""Template email CỐ ĐỊNH cho Scheduler (PRD §7.4). KHÔNG sinh bằng LLM — nhất quán + an toàn
pháp lý (cùng lý do bộ câu hỏi Screener cố định). Chỉ điền {candidate_name}, {job_title}.

An toàn: tên lấy từ CV (không tin cậy) → ESCAPE HTML trước khi nhúng vào thân email; tiêu đề
(email header) → bỏ newline chống header injection.
"""

from __future__ import annotations

import html as _html
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def _esc(value: str | None, *, fallback: str) -> str:
    text = (value or "").strip()
    return _html.escape(text) if text else fallback


def _subject_safe(value: str | None, *, fallback: str) -> str:
    text = " ".join((value or "").split()) or fallback  # gộp whitespace/newline về 1 dòng
    return text


def _wrap(body: str) -> str:
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.6;'
        f'color:#0f172a;max-width:560px">{body}'
        '<p style="margin-top:24px">Trân trọng,<br/>Bộ phận Tuyển dụng</p></div>'
    )


_WEEKDAYS_VI = {
    1: "Thứ Hai", 2: "Thứ Ba", 3: "Thứ Tư", 4: "Thứ Năm",
    5: "Thứ Sáu", 6: "Thứ Bảy", 7: "Chủ Nhật",
}


def format_vn_datetime(value: datetime) -> str:
    """Mốc thời gian → chuỗi tiếng Việt theo `Asia/Ho_Chi_Minh`: "09:15, Thứ Năm 06/08/2026".

    LUÔN quy về giờ Việt Nam và LUÔN ghi rõ thứ: DB lưu UTC, còn ứng viên đọc email trên điện thoại
    ở múi giờ bất kỳ. Bỏ thứ đi thì "06/08" dễ bị đọc nhầm ngày/tháng và người ta lỡ buổi phỏng vấn.
    """
    local = value.astimezone(ZoneInfo(settings.booking_timezone))
    return f"{local:%H:%M}, {_WEEKDAYS_VI[local.isoweekday()]} {local:%d/%m/%Y}"


def invite_email(
    candidate_name: str | None,
    job_title: str | None,
    *,
    booking_url: str,
    deadline_text: str,
) -> tuple[str, str]:
    """Thư mời phỏng vấn KÈM LINK TỰ ĐẶT LỊCH (SCH-2 · PRD §10b.1, FR-BOOK-1). Trả (subject, html).

    Hệ thống KHÔNG chốt hộ giờ — ứng viên tự chọn (§10b). Vì thế thư mời phải mang theo link; câu
    "sẽ liên hệ sắp lịch" của bản cũ nay là sai sự thật vì sẽ chẳng có ai liên hệ nữa.
    `booking_url` do hệ thống dựng (FRONTEND_BASE_URL + token) — vẫn escape quote vì nằm trong href.
    """
    name = _esc(candidate_name, fallback="Ứng viên")
    title = _esc(job_title, fallback="vị trí ứng tuyển")
    href = _html.escape(booking_url, quote=True)
    deadline = _esc(deadline_text, fallback="thời gian quy định")
    subject = _subject_safe(
        f"Thư mời phỏng vấn — vị trí {job_title}" if job_title else "Thư mời phỏng vấn",
        fallback="Thư mời phỏng vấn",
    )
    html = _wrap(
        f"<p>Kính gửi {name},</p>"
        f"<p>Chúc mừng bạn! Sau khi xem xét hồ sơ, chúng tôi trân trọng mời bạn tham gia phỏng vấn "
        f"cho vị trí <strong>{title}</strong>.</p>"
        f"<p>Bạn vui lòng <strong>tự chọn khung giờ phù hợp nhất</strong> với mình qua liên kết dưới "
        f"đây, trong vòng <strong>{deadline}</strong>:</p>"
        f'<p><a href="{href}">Chọn giờ phỏng vấn</a></p>'
        "<p>Nếu nút không bấm được, hãy sao chép liên kết này vào trình duyệt:</p>"
        f'<p style="word-break:break-all;color:#475569">{href}</p>'
        "<p>Mong sớm được trao đổi cùng bạn.</p>"
    )
    return subject, html


def booking_confirmed_email(
    candidate_name: str | None,
    job_title: str | None,
    *,
    start_at: datetime,
    end_at: datetime,
    manage_url: str | None = None,
) -> tuple[str, str]:
    """Thư XÁC NHẬN lịch phỏng vấn sau khi ứng viên chọn giờ (PRD §10b.1, §12.4 FR-NOTI-1).

    Tệp `.ics` được đính kèm ở tầng gọi (scheduler) — thư vẫn phải ghi RÕ ngày giờ bằng chữ, vì
    không phải ứng viên nào cũng mở được tệp đính kèm trên điện thoại.

    `manage_url` (SCH-3 · FR-BOOK-4) là **chính liên kết đặt lịch cũ**, không phải token thứ hai:
    mở ra thấy lịch đã chốt kèm nút huỷ. Một liên kết cho cả vòng đời thì ứng viên không phải phân
    biệt "link nào để xem, link nào để huỷ", và ta không có thêm token phải theo dõi.
    """
    name = _esc(candidate_name, fallback="Ứng viên")
    title = _esc(job_title, fallback="vị trí ứng tuyển")
    when = _esc(format_vn_datetime(start_at), fallback="")
    minutes = max(1, round((end_at - start_at).total_seconds() / 60))
    subject = _subject_safe(
        f"Xác nhận lịch phỏng vấn — vị trí {job_title}" if job_title else "Xác nhận lịch phỏng vấn",
        fallback="Xác nhận lịch phỏng vấn",
    )
    if manage_url:
        href = _html.escape(manage_url, quote=True)
        change = (
            "<p>Nếu bạn cần <strong>huỷ hoặc chọn giờ khác</strong>, vui lòng mở liên kết dưới đây:</p>"
            f'<p><a href="{href}">Xem hoặc huỷ lịch phỏng vấn</a></p>'
            '<p style="word-break:break-all;color:#475569">' + href + "</p>"
        )
    else:
        change = "<p>Nếu bạn cần thay đổi, vui lòng phản hồi email này để chúng tôi hỗ trợ.</p>"
    html = _wrap(
        f"<p>Kính gửi {name},</p>"
        f"<p>Chúng tôi xác nhận buổi phỏng vấn cho vị trí <strong>{title}</strong> đã được đặt vào:</p>"
        f'<p style="font-size:16px;font-weight:bold;color:#0f172a">{when} (giờ Việt Nam)</p>'
        f"<p>Thời lượng dự kiến: {minutes} phút. Chúng tôi có đính kèm tệp lịch "
        "(<code>.ics</code>) để bạn thêm vào ứng dụng lịch của mình.</p>" + change
    )
    return subject, html


def interview_reminder_email(
    candidate_name: str | None,
    job_title: str | None,
    *,
    start_at: datetime,
    end_at: datetime,
    manage_url: str | None = None,
) -> tuple[str, str]:
    """Thư NHẮC trước buổi phỏng vấn (SCH-3 · PRD §10b.6, FR-BOOK-4). Gửi MỘT lần, kèm lại `.ics`.

    Đính kèm `.ics` LẦN NỮA là cố ý: ứng viên nào chưa thêm vào lịch lúc nhận thư xác nhận thì đây
    là cơ hội thứ hai, và đó chính là nhóm dễ quên buổi phỏng vấn nhất.
    """
    name = _esc(candidate_name, fallback="Ứng viên")
    title = _esc(job_title, fallback="vị trí ứng tuyển")
    when = _esc(format_vn_datetime(start_at), fallback="")
    minutes = max(1, round((end_at - start_at).total_seconds() / 60))
    subject = _subject_safe(
        f"Nhắc: buổi phỏng vấn sắp tới — vị trí {job_title}"
        if job_title
        else "Nhắc: buổi phỏng vấn sắp tới",
        fallback="Nhắc: buổi phỏng vấn sắp tới",
    )
    if manage_url:
        href = _html.escape(manage_url, quote=True)
        change = (
            "<p>Nếu có việc đột xuất, bạn có thể huỷ hoặc chọn giờ khác tại đây:</p>"
            f'<p><a href="{href}">Xem hoặc huỷ lịch phỏng vấn</a></p>'
            # URL thô: `html_to_text` (bản text của thư) chỉ giữ text-node, không giữ href — thiếu
            # dòng này là bản text mất nút huỷ đúng lúc ứng viên cần nó nhất.
            f'<p style="word-break:break-all;color:#475569">{href}</p>'
        )
    else:
        change = "<p>Nếu có việc đột xuất, vui lòng phản hồi email này sớm nhất có thể.</p>"
    html = _wrap(
        f"<p>Kính gửi {name},</p>"
        f"<p>Đây là lời nhắc về buổi phỏng vấn vị trí <strong>{title}</strong> của bạn:</p>"
        f'<p style="font-size:16px;font-weight:bold;color:#0f172a">{when} (giờ Việt Nam)</p>'
        f"<p>Thời lượng dự kiến: {minutes} phút. Tệp lịch (<code>.ics</code>) được đính kèm lần nữa "
        "để bạn tiện thêm vào ứng dụng lịch.</p>" + change +
        "<p>Chúc bạn một buổi phỏng vấn thuận lợi.</p>"
    )
    return subject, html


def booking_reminder_email(
    candidate_name: str | None,
    job_title: str | None,
    *,
    booking_url: str,
    deadline_text: str,
) -> tuple[str, str]:
    """Thư NHẮC ứng viên CHỌN LỊCH khi liên kết sắp hết hạn (SCH-3 · PRD §10b.6, FR-BOOK-3).

    DÙNG LẠI đúng liên kết cũ (token KHÔNG one-time — §10b.3): phát link mới là ứng viên có hai thư
    với hai liên kết và không biết cái nào còn sống. Đối xứng `screener_reminder_email` của 08c.
    """
    name = _esc(candidate_name, fallback="Ứng viên")
    title = _esc(job_title, fallback="vị trí ứng tuyển")
    href = _html.escape(booking_url, quote=True)
    deadline = _esc(deadline_text, fallback="thời gian còn lại")
    subject = _subject_safe(
        f"Nhắc: chọn giờ phỏng vấn — vị trí {job_title}" if job_title else "Nhắc: chọn giờ phỏng vấn",
        fallback="Nhắc: chọn giờ phỏng vấn",
    )
    html = _wrap(
        f"<p>Kính gửi {name},</p>"
        f"<p>Chúng tôi nhận thấy bạn chưa chọn khung giờ phỏng vấn cho vị trí <strong>{title}</strong>. "
        f"Đây là lời nhắc thân thiện — liên kết dưới đây còn hiệu lực trong <strong>{deadline}</strong>:</p>"
        f'<p><a href="{href}">Chọn giờ phỏng vấn</a></p>'
        "<p>Nếu nút không bấm được, hãy sao chép liên kết này vào trình duyệt:</p>"
        f'<p style="word-break:break-all;color:#475569">{href}</p>'
    )
    return subject, html


def booking_cancelled_email(
    candidate_name: str | None,
    job_title: str | None,
    *,
    start_at: datetime,
    rebook_url: str | None = None,
    by_hr: bool = False,
) -> tuple[str, str]:
    """Thư xác nhận buổi phỏng vấn ĐÃ HUỶ (SCH-3 · PRD §10b.6, FR-BOOK-4).

    Hai ngữ cảnh, một template — khác nhau đúng ở chỗ ứng viên phải làm gì tiếp:

    - `rebook_url` có → ứng viên tự chọn lại giờ được (liên kết CŨ vẫn còn hạn). Không nhắc tới hạn
      mới, vì không có hạn mới: TTL gốc giữ nguyên (§10b.6).
    - không có → hết hạn hoặc HR huỷ; nói rõ **Bộ phận Tuyển dụng sẽ liên hệ**, đừng để người đọc
      ngồi chờ một liên kết không tồn tại.

    `by_hr` chỉ đổi CÂU MỞ: ứng viên tự bấm huỷ mà nhận thư "chúng tôi đã huỷ lịch của bạn" thì đọc
    như bị từ chối.
    """
    name = _esc(candidate_name, fallback="Ứng viên")
    title = _esc(job_title, fallback="vị trí ứng tuyển")
    when = _esc(format_vn_datetime(start_at), fallback="")
    subject = _subject_safe(
        f"Huỷ lịch phỏng vấn — vị trí {job_title}" if job_title else "Huỷ lịch phỏng vấn",
        fallback="Huỷ lịch phỏng vấn",
    )
    opening = (
        f"<p>Buổi phỏng vấn vị trí <strong>{title}</strong> dự kiến lúc <strong>{when}</strong> "
        "(giờ Việt Nam) đã được huỷ."
        + (" Rất tiếc vì sự bất tiện này.</p>" if by_hr else " Khung giờ đó đã được nhả lại.</p>")
    )
    if rebook_url:
        href = _html.escape(rebook_url, quote=True)
        tail = (
            "<p>Bạn vẫn có thể <strong>chọn một khung giờ khác</strong> qua chính liên kết cũ:</p>"
            f'<p><a href="{href}">Chọn giờ phỏng vấn khác</a></p>'
            f'<p style="word-break:break-all;color:#475569">{href}</p>'
        )
    else:
        tail = "<p>Bộ phận Tuyển dụng sẽ liên hệ với bạn để sắp xếp lại thời gian phù hợp.</p>"
    return subject, _wrap(f"<p>Kính gửi {name},</p>{opening}{tail}")


def screener_email(
    candidate_name: str | None,
    job_title: str | None,
    *,
    form_url: str,
    deadline_text: str,
) -> tuple[str, str]:
    """Thư mời trả lời bộ câu hỏi sàng lọc qua magic-link (PRD §7.3, §10). CỐ ĐỊNH, không LLM.

    `form_url` do hệ thống dựng (FRONTEND_BASE_URL + token urlsafe) — vẫn escape quote vì nằm trong
    `href="..."`. Trả (subject, html)."""
    name = _esc(candidate_name, fallback="Ứng viên")
    title = _esc(job_title, fallback="vị trí ứng tuyển")
    href = _html.escape(form_url, quote=True)
    deadline = _esc(deadline_text, fallback="thời gian quy định")
    subject = _subject_safe(
        f"Bổ sung thông tin ứng tuyển — vị trí {job_title}" if job_title else "Bổ sung thông tin ứng tuyển",
        fallback="Bổ sung thông tin ứng tuyển",
    )
    html = _wrap(
        f"<p>Kính gửi {name},</p>"
        f"<p>Cảm ơn bạn đã ứng tuyển vị trí <strong>{title}</strong>. Để tiếp tục quy trình, vui lòng "
        f"dành ít phút trả lời một vài câu hỏi bổ sung qua liên kết dưới đây trong vòng <strong>{deadline}</strong>.</p>"
        f'<p><a href="{href}">Trả lời câu hỏi sàng lọc</a></p>'
        "<p>Nếu nút không bấm được, hãy sao chép liên kết này vào trình duyệt:</p>"
        f'<p style="word-break:break-all;color:#475569">{href}</p>'
    )
    return subject, html


def screener_reminder_email(
    candidate_name: str | None,
    job_title: str | None,
    *,
    form_url: str,
    deadline_text: str,
) -> tuple[str, str]:
    """Thư NHẮC trả lời bộ câu hỏi sàng lọc (08c · PRD §10 FR-SCR-3). Gửi MỘT LẦN khi quá mốc nhắc mà
    chưa phản hồi; DÙNG LẠI magic-link cũ (token còn hạn). Cùng cơ chế escape như screener_email
    (name/title escape HTML; form_url trong href escape quote). Trả (subject, html)."""
    name = _esc(candidate_name, fallback="Ứng viên")
    title = _esc(job_title, fallback="vị trí ứng tuyển")
    href = _html.escape(form_url, quote=True)
    deadline = _esc(deadline_text, fallback="thời gian còn lại")
    subject = _subject_safe(
        f"Nhắc: bổ sung thông tin ứng tuyển — vị trí {job_title}"
        if job_title
        else "Nhắc: bổ sung thông tin ứng tuyển",
        fallback="Nhắc: bổ sung thông tin ứng tuyển",
    )
    html = _wrap(
        f"<p>Kính gửi {name},</p>"
        f"<p>Chúng tôi nhận thấy bạn chưa hoàn tất phần câu hỏi bổ sung cho vị trí "
        f"<strong>{title}</strong>. Đây là lời nhắc thân thiện — vui lòng dành ít phút trả lời qua "
        f"liên kết dưới đây trong vòng <strong>{deadline}</strong> để chúng tôi tiếp tục xem xét hồ sơ của bạn.</p>"
        f'<p><a href="{href}">Trả lời câu hỏi sàng lọc</a></p>'
        "<p>Nếu nút không bấm được, hãy sao chép liên kết này vào trình duyệt:</p>"
        f'<p style="word-break:break-all;color:#475569">{href}</p>'
    )
    return subject, html


def rejection_email(candidate_name: str | None, job_title: str | None) -> tuple[str, str]:
    """Thư từ chối — cảm ơn, rất tiếc chưa phù hợp, chúc may mắn. Trả (subject, html)."""
    name = _esc(candidate_name, fallback="Ứng viên")
    title = _esc(job_title, fallback="vị trí ứng tuyển")
    subject = _subject_safe(
        f"Kết quả ứng tuyển — vị trí {job_title}" if job_title else "Kết quả ứng tuyển",
        fallback="Kết quả ứng tuyển",
    )
    html = _wrap(
        f"<p>Kính gửi {name},</p>"
        f"<p>Cảm ơn bạn đã quan tâm và ứng tuyển vị trí <strong>{title}</strong> tại công ty "
        "chúng tôi.</p>"
        "<p>Sau khi cân nhắc kỹ lưỡng, rất tiếc hồ sơ của bạn chưa phù hợp với yêu cầu vị trí ở "
        "thời điểm này. Chúng tôi sẽ lưu hồ sơ và liên hệ khi có cơ hội phù hợp hơn.</p>"
        "<p>Chúc bạn nhiều may mắn và thành công trên con đường sự nghiệp.</p>"
    )
    return subject, html
