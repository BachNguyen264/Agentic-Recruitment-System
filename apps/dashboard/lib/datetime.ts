// Hiển thị mốc thời gian phỏng vấn — MỘT hàm cho cả hai phía (SCH-2/SCH-3 · PRD §10b).
//
// LUÔN quy về giờ Việt Nam và LUÔN kèm THỨ. Hai lý do, cả hai đều đã suýt cắn:
//   1. Để trình duyệt tự dùng múi giờ của máy thì một ứng viên đang ở nước ngoài đọc ra giờ khác
//      với giờ hẹn thật — và không có gì báo lỗi.
//   2. Có thứ trong chuỗi thì "06/08" hết cửa bị đọc nhầm thành ngày 8 tháng 6.
//
// Trang HR và trang ứng viên phải đọc ra CÙNG một chuỗi, nên hàm này nằm ở lib chứ không chép hai
// bản: hai bản lệch nhau nghĩa là hai người nói về hai giờ khác nhau trong cùng một buổi phỏng vấn.
// Khớp `email_templates.format_vn_datetime` phía backend (cùng múi giờ, cùng có thứ).

const VN_TZ = "Asia/Ho_Chi_Minh";

export function formatVnDateTime(iso: string): string {
  const at = new Date(iso);
  const time = new Intl.DateTimeFormat("vi-VN", {
    timeZone: VN_TZ, hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(at);
  const date = new Intl.DateTimeFormat("vi-VN", {
    timeZone: VN_TZ, weekday: "long", day: "2-digit", month: "2-digit", year: "numeric",
  }).format(at);
  return `${time} · ${date}`;
}
