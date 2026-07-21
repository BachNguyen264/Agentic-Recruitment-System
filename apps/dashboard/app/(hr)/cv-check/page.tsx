"use client";

import { useState } from "react";
import type { ParseCvResponse } from "@ars/shared-types";
import { CVUpload } from "@/components/CVUpload";
import { ParsedCVResult } from "@/components/ParsedCVResult";
import { btn, PageHeader } from "@/components/ui";

// Công cụ HR: thử Parser (PRD §7.1) trên một CV bất kỳ mà KHÔNG tạo hồ sơ, KHÔNG lưu file.
// Nằm trong shell (hr)/ nên điều hướng đã có ở sidebar — không cần link "← Về dashboard".
export default function CvCheckPage() {
  const [result, setResult] = useState<ParseCvResponse | null>(null);
  // "Phân tích CV khác" phải xoá CẢ file đang chọn, không chỉ kết quả. File nằm trong state của
  // CVUpload + CVFilePicker, nên đổi key để remount cả nhánh — nếu chỉ setResult(null) thì dropzone
  // vẫn hiện tên CV cũ và nút vẫn bật, trong khi màn hình nói "chưa có kết quả": giao diện nói dối
  // và HR dễ bấm phân tích lại đúng CV vừa chạy (tốn thêm một lượt gọi LLM).
  const [runKey, setRunKey] = useState(0);

  return (
    <div className="mx-auto max-w-[820px] px-4 pb-8 pt-6 sm:px-8">
      <PageHeader
        eyebrow="Công cụ · Parser"
        title="Kiểm tra bóc tách CV"
        description="Tải lên một CV (PDF/DOCX) để xem Parser trích ra gì — họ tên, kỹ năng, kinh nghiệm, học vấn — kèm độ tin cậy. Xử lý trong bộ nhớ, KHÔNG lưu file và KHÔNG tạo hồ sơ ứng viên."
      />

      <CVUpload key={runKey} onResult={setResult} />

      {result && (
        <div className="mt-6">
          <ParsedCVResult
            parsed_data={result.parsed_data}
            confidence={result.confidence}
            uncertainty_flags={result.uncertainty_flags}
            escalation_reason={result.escalation_reason}
          />
          <button
            type="button"
            onClick={() => {
              setResult(null);
              setRunKey((k) => k + 1);
            }}
            className={btn("ghost", "mt-3 !pl-0")}
          >
            ↻ Phân tích CV khác
          </button>
        </div>
      )}
    </div>
  );
}
