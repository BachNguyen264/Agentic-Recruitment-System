// ── Kho CV mẫu (cv-templates) — NGUỒN DUY NHẤT cho trang /cv-templates ──
//
// File thật nằm ở `public/cv-templates/{slug}.docx` và `{slug}.pdf` — phục vụ TĨNH bởi Next,
// KHÔNG qua backend (khác hẳn CV ứng viên nộp: cái đó nằm trong bucket R2 PRIVATE và chỉ stream
// qua `require_hr`, xem NFR-4). Mẫu CV là tài liệu công khai, ai tải cũng được.
//
// `slug` suy ra CẢ HAI đường dẫn file nên chỉ khai báo một lần — thêm/đổi mẫu thì sửa đúng ở đây,
// không phải dò 18 chuỗi rải rác. Đổi `slug` mà quên đổi tên file trong `public/` → nút tải ra 404
// (Next trả trang 404 chứ không phải file), nên hai bên PHẢI khớp từng ký tự.

export type CvTemplate = {
  /** Trùng TÊN FILE trong `public/cv-templates/` (không kèm đuôi). */
  slug: string;
  /** Tên ngành nghề hiện trên thẻ. */
  name: string;
  /** Mô tả một dòng — mẫu này khác các mẫu khác ở chỗ nào. */
  blurb: string;
  /**
   * Link Google Docs dạng "Tạo bản sao" (`https://docs.google.com/document/d/<ID>/copy`) — ứng
   * viên bấm là có ngay bản riêng trên Drive để sửa online, tự lưu, tự xuất PDF.
   *
   * `null` = CHƯA tải mẫu đó lên Drive → thẻ chỉ hiện 2 nút tải file, KHÔNG hiện nút chết dẫn
   * tới 404. Dán URL vào là nút thứ ba tự xuất hiện, không cần sửa code trang.
   *
   * Phải là link `/copy`, KHÔNG phải `/edit`: link `/edit` cho người lạ sửa thẳng vào bản gốc,
   * ứng viên sau vào sẽ thấy thông tin của ứng viên trước.
   */
  googleDocsUrl: string | null;
};

export const CV_TEMPLATES: CvTemplate[] = [
  {
    slug: "mau-cv-tong-quat",
    name: "Tổng quát",
    blurb: "Bố cục trung tính, dùng được cho hầu hết vị trí.",
    googleDocsUrl:
      "https://docs.google.com/document/d/1agmoMo7NlMs7kqwVTWTk2GAbK2Jq5gGt/copy",
  },
  {
    slug: "mau-cv-cong-nghe-thong-tin",
    name: "Công nghệ thông tin",
    blurb: "Làm nổi bật dự án, công nghệ sử dụng và đóng góp kỹ thuật.",
    googleDocsUrl:
      "https://docs.google.com/document/d/1_9xulaZ6LfDJA-URY4MViCBWC-AIXvY8/copy",
  },
  {
    slug: "mau-cv-kinh-doanh-ban-hang",
    name: "Kinh doanh & Bán hàng",
    blurb: "Nhấn vào chỉ tiêu, doanh số và tệp khách hàng đã phụ trách.",
    googleDocsUrl:
      "https://docs.google.com/document/d/1UxXYnWtiDbQXrHxrE9X11yIPbQEcEhQg/copy",
  },
  {
    slug: "mau-cv-marketing-truyen-thong",
    name: "Marketing & Truyền thông",
    blurb: "Nhấn vào chiến dịch, kênh triển khai và số liệu hiệu quả.",
    googleDocsUrl:
      "https://docs.google.com/document/d/16xlenypz2nkZG2tOUIuDUyqWb4IjH4Qf/copy",
  },
  {
    slug: "mau-cv-ke-toan-tai-chinh",
    name: "Kế toán & Tài chính",
    blurb: "Nhấn vào nghiệp vụ, phần mềm kế toán và chứng chỉ chuyên môn.",
    googleDocsUrl:
      "https://docs.google.com/document/d/1hGcbowq3jwfrIvyoyGmhqJRrtkwRnsHh/copy",
  },
  {
    slug: "mau-cv-hanh-chinh-nhan-su",
    name: "Hành chính & Nhân sự",
    blurb: "Nhấn vào quy trình, quản lý hồ sơ và công tác nhân sự.",
    googleDocsUrl:
      "https://docs.google.com/document/d/148SNMGFWE7GwuS_wYPooKuFYYKThFL9a/copy",
  },
  {
    slug: "mau-cv-cham-soc-khach-hang",
    name: "Chăm sóc khách hàng",
    blurb: "Nhấn vào kỹ năng giao tiếp và cách xử lý tình huống khó.",
    googleDocsUrl:
      "https://docs.google.com/document/d/13fTqudJ92kSfywRl6f09YAvOWBRvGqE-/copy",
  },
  {
    slug: "mau-cv-thiet-ke-sang-tao",
    name: "Thiết kế & Sáng tạo",
    blurb: "Chừa sẵn chỗ cho link portfolio và bộ công cụ thiết kế.",
    googleDocsUrl:
      "https://docs.google.com/document/d/1c9d4Ra6tJLxxrRpfCFqIrO-7jhp-mwGC/copy",
  },
  {
    slug: "mau-cv-sinh-vien-moi-tot-nghiep",
    name: "Sinh viên mới tốt nghiệp",
    blurb: "Chưa nhiều kinh nghiệm — đề cao học vấn, dự án và hoạt động.",
    googleDocsUrl:
      "https://docs.google.com/document/d/1FdeE1rP--W41CEw_q4-wPiphZoNBeaFI/copy",
  },
];

/** Đường dẫn file tĩnh của một mẫu. Dùng chung cho cả hai nút tải để không lệch nhau. */
export function templateFileUrl(slug: string, ext: "docx" | "pdf"): string {
  return `/cv-templates/${slug}.${ext}`;
}
