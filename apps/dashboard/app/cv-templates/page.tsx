import type { Metadata } from "next";
import Link from "next/link";
import { btn } from "@/components/ui";
import { CV_TEMPLATES, templateFileUrl } from "@/lib/cv-templates";

export const metadata: Metadata = {
  title: "Mẫu CV miễn phí — HireFlow",
  description:
    "Chín mẫu CV theo ngành nghề, tải về dạng .docx để điền hoặc .pdf để xem trước bố cục.",
};

// Kho CV mẫu — trang CÔNG KHAI, hoàn toàn TĨNH.
//
// Cố ý KHÔNG có `"use client"`: không state, không fetch, không TanStack Query. Là Server
// Component nên Next prerender sẵn lúc build (`○ Static`) và phần JS RIÊNG của route chỉ còn
// 186 B — không phải 0, đừng viết là 0: con số đó là payload RSC tối thiểu Next luôn kèm theo,
// còn 87.3 kB nữa là chunk DÙNG CHUNG toàn app (framework + Providers ở root layout) mà mọi
// route đều gánh. Điều thật sự đạt được là trang KHÔNG kéo theo bundle HR — nhờ nằm ngoài
// nhóm route `(hr)` nên shell sidebar và guard gọi `/api/auth/me` không hề được nạp.
//
// Không gọi API nghĩa là không đụng rate-limit theo IP của `core/hardening.py` — ứng viên xem
// mẫu bao lâu tuỳ thích rồi mới sang /apply nộp mà không tiêu mất quota của lượt POST hồ sơ.
export default function CvTemplatesPage() {
  return (
    <main>
      <p className="eyebrow">Kho mẫu</p>
      <h1 className="mt-1.5 text-[30px] sm:text-[36px]">Mẫu CV theo ngành nghề</h1>
      <p className="mt-2 max-w-[62ch] text-[14px] leading-relaxed text-ink/65">
        Chọn mẫu gần với ngành của bạn, tải về, điền thông tin rồi quay lại nộp. Bản{" "}
        <strong className="font-semibold text-ink">.docx</strong> để chỉnh sửa (Word, Google Docs,
        WPS); bản <strong className="font-semibold text-ink">.pdf</strong> là bản in sẵn, mở lên
        xem bố cục thành phẩm sau khi tải. Hệ thống nhận cả hai định dạng khi nộp.
      </p>

      <ul className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {/* Thẻ KHÔNG có `hover:border-…`: ở /apply thẻ đổi viền khi rê chuột nghĩa là CẢ thẻ bấm
            được (hover đó nằm trên chính <Link>). Thẻ ở đây chỉ hai nút bấm được, phần còn lại
            (~90% diện tích) không làm gì — sáng lên khi rê là hứa hẹn sai, mà ứng viên vừa học
            nghĩa của hiệu ứng đó ở đúng màn hình ngay trước. */}
        {CV_TEMPLATES.map((tpl) => (
          <li
            key={tpl.slug}
            className="flex flex-col rounded-xl border-2 border-divider bg-canvas p-5"
          >
            <h2 className="font-heading text-[17px] font-bold">{tpl.name}</h2>
            {/* `flex-1` đẩy hàng nút xuống đáy: mô tả dài ngắn khác nhau nhưng nút của 3 thẻ
                cùng hàng vẫn thẳng nhau. */}
            <p className="mt-1.5 flex-1 text-[13px] leading-relaxed text-ink/65">{tpl.blurb}</p>

            {/* `flex-wrap` để nút thứ ba (Google Docs) xuống dòng chứ không làm vỡ thẻ.
                Chính vì XUỐNG DÒNG mà nút đó phải tự lo chiều cao (xem `!py-2 border-2
                border-transparent` bên dưới): `align-items: stretch` chỉ cân bằng chiều cao
                TRONG một dòng flex, nút đứng một mình ở dòng dưới thì không ai kéo nó lên.
                Đo thật: `secondary` có `border-2` nên cao 37.5px và kéo `primary` cùng dòng lên
                theo; `ghost` (không viền, `py-1`) chỉ 33.5px — trước khi vá còn 26px. Viền TRONG
                SUỐT bù đúng 4px của border để ba nút bằng nhau dù nằm dòng nào. */}
            <div className="mt-4 flex flex-wrap gap-2">
              {/* `download` chỉ có hiệu lực vì file cùng origin (nằm trong `public/`) — trình
                  duyệt LƯU file thay vì mở PDF ngay trong tab.

                  `aria-label` cần vì đọc màn hình gặp 9 link "Tải .docx" giống hệt nhau thì
                  không biết là mẫu ngành gì. Nhưng nó phải MỞ ĐẦU bằng ĐÚNG chữ nhìn thấy:
                  `aria-label` ĐÈ nội dung thẻ, nên nếu viết "Tải mẫu CV X định dạng DOCX" thì
                  tên khả truy cập KHÔNG còn chứa chuỗi "Tải .docx" — người dùng điều khiển bằng
                  giọng nói (Voice Control/Voice Access) đọc thấy nút gì thì nói đúng chữ đó, và
                  sẽ không khớp được link nào. Đó là WCAG 2.5.3 "Label in Name", mức A. */}
              <a
                href={templateFileUrl(tpl.slug, "docx")}
                download
                aria-label={`Tải .docx — mẫu CV ${tpl.name}`}
                className={btn("primary")}
              >
                Tải .docx
              </a>
              <a
                href={templateFileUrl(tpl.slug, "pdf")}
                download
                aria-label={`Tải .pdf — mẫu CV ${tpl.name}`}
                className={btn("secondary")}
              >
                Tải .pdf
              </a>
              {tpl.googleDocsUrl && (
                <a
                  href={tpl.googleDocsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`Sửa trên Google Docs — mẫu CV ${tpl.name} (mở tab mới)`}
                  className={btn("ghost", "!px-3 !py-2 border-2 border-transparent")}
                >
                  Sửa trên Google Docs
                </a>
              )}
            </div>
          </li>
        ))}
      </ul>

      <p className="mt-7 border-t-2 border-divider pt-5 text-[14px] text-ink/65">
        Điền xong rồi?{" "}
        <Link href="/apply" className="font-heading font-bold text-accent hover:underline">
          Xem vị trí đang tuyển và nộp hồ sơ →
        </Link>
      </p>
    </main>
  );
}
