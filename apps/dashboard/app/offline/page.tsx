import type { Metadata } from "next";

export const metadata: Metadata = { title: "Mất kết nối — HireFlow" };

// TUYỆT ĐỐI KHÔNG thêm "use client" vào file này.
// Service worker chỉ `cache.add("/offline")` — tức chỉ lưu HTML. Các chunk JS của route này thì
// CHƯA AI từng tải (không ai chủ động vào /offline lúc đang online), mà nhánh `/_next/static/` của
// sw.js là cache-khi-fetch-lần-đầu chứ không phải precache. Nên trang sẽ VẼ được nhưng KHÔNG
// hydrate: mọi nút React ở đây là nút chết. Thẻ <a> thường là một lượt điều hướng thật, đi qua
// nhánh network-first và chạy ngay khi có mạng trở lại.
//
// Chữ phải TRUNG TÍNH, không mang giọng HR: PWARegister đăng ký SW ở scope "/" (app/layout.tsx),
// nên trang này cũng phục vụ ứng viên mất sóng giữa chừng ở /apply, /screening, /booking.
export default function OfflinePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-[520px] flex-col justify-center px-6 py-12 text-center">
      <p className="font-heading text-[13px] font-bold uppercase tracking-[0.08em] text-ink/65">
        HireFlow
      </p>
      <h1 className="mt-3 text-[28px] sm:text-[32px]">Mất kết nối máy chủ</h1>
      <p className="mx-auto mt-3 max-w-[42ch] text-[14px] leading-relaxed text-ink/70">
        Thiết bị của bạn hiện không liên lạc được với máy chủ HireFlow. Dữ liệu không được lưu trên
        máy nên trang này chưa hiển thị được nội dung nào — hãy kiểm tra kết nối rồi thử lại.
      </p>
      <p className="mt-6">
        {/* href="" trỏ về CHÍNH URL hiện tại: service worker trả trang này TẠI địa chỉ người dùng
            vừa yêu cầu, nên "Thử lại" = gọi lại đúng trang đó. Cố định "/review" thì HR thì đúng
            nhưng ứng viên mất sóng ở /apply hay /booking/{token} sẽ bị ném vào khu vực HR rồi đá ra
            /login — mà trang này phục vụ CẢ HAI (PWARegister đăng ký SW ở scope "/"). */}
        <a
          href=""
          className="inline-flex min-h-11 items-center justify-center rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-white hover:bg-accent-600"
        >
          Thử lại
        </a>
      </p>
    </main>
  );
}
